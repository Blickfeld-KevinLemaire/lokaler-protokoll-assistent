"""Testet die Entscheidungslogik von bootstrap.py OHNE echte
Netzwerk-/pip-/venv-Operationen: alle side-effect-behafteten Aufrufe
(venv.EnvBuilder, pip-Installation, Prozess-Neustart) werden ersetzt."""

from __future__ import annotations

from pathlib import Path

import pytest

from protokoll_assistent import bootstrap
from protokoll_assistent.services import environment_service


class _FakeSplash:
    def __init__(self):
        self.messages: list[str] = []

    def log(self, message):
        self.messages.append(message)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_real_splash(monkeypatch):
    monkeypatch.setattr(bootstrap, "_try_create_splash", lambda: _FakeSplash())
    monkeypatch.setattr(bootstrap, "_wait_for_acknowledgement", lambda splash: None)
    monkeypatch.delenv(bootstrap.MARKER_ENV_VAR, raising=False)


def test_returns_immediately_when_already_in_managed_venv(monkeypatch):
    monkeypatch.setenv(bootstrap.MARKER_ENV_VAR, "1")
    called = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda *a: called.append(a))
    bootstrap.ensure_runtime_and_relaunch()
    assert called == []  # kehrt zurueck, ohne irgendetwas zu tun


def test_returns_immediately_when_frozen_pyinstaller_build(monkeypatch):
    # In einer gebauten EXE ist bereits alles gebuendelt -- kein erneutes
    # Einrichten oder Neustarten noetig oder gewollt.
    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    called = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda *a: called.append(a))
    bootstrap.ensure_runtime_and_relaunch()
    assert called == []


def test_uses_existing_legacy_venv_without_installing(monkeypatch, tmp_path):
    legacy_dir = tmp_path / "legacy" / ".venv-whisperx"
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: legacy_dir)

    relaunch_calls = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe: relaunch_calls.append(python_exe))

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    bootstrap.ensure_runtime_and_relaunch()

    assert len(relaunch_calls) == 1
    assert install_calls == []  # keine Installation auf dem bereits fertigen Referenz-PC


def test_fresh_pc_creates_venv_and_installs_then_relaunches(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)

    monkeypatch.setattr(environment_service, "is_supported_python_version", lambda: True)
    monkeypatch.setattr(environment_service, "detect_nvidia_gpu", lambda: False)

    created_dirs = []

    class _FakeEnvBuilder:
        def __init__(self, with_pip=True):
            pass

        def create(self, path):
            created_dirs.append(path)
            python_path = paths.venv_python_path(runtime_venv_dir)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", _FakeEnvBuilder)

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    relaunch_calls = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe: relaunch_calls.append(python_exe))

    bootstrap.ensure_runtime_and_relaunch()

    assert created_dirs == [str(runtime_venv_dir)]
    assert len(install_calls) == 3  # pip upgrade, torch, restliche Pakete
    assert len(relaunch_calls) == 1
    assert relaunch_calls[0] == paths.venv_python_path(runtime_venv_dir)


def test_unsupported_python_version_without_alternate_reports_diagnosis_and_exits(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)
    monkeypatch.setattr(environment_service, "is_supported_python_version", lambda: False)
    # Determinismus unabhaengig davon, was auf dem Testrechner tatsaechlich
    # installiert ist: es soll hier bewusst keine Alternative gefunden werden.
    monkeypatch.setattr(environment_service, "find_alternate_supported_python", lambda: None)

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.ensure_runtime_and_relaunch()

    assert exc_info.value.code == 1
    assert install_calls == []


def test_unsupported_python_version_uses_alternate_when_found(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)
    monkeypatch.setattr(environment_service, "is_supported_python_version", lambda: False)
    alternate = Path("/irgendwo/python3.11")
    monkeypatch.setattr(environment_service, "find_alternate_supported_python", lambda: alternate)
    monkeypatch.setattr(environment_service, "detect_nvidia_gpu", lambda: False)

    create_venv_calls = []

    def _fake_create_venv(venv_dir, base_python=None):
        create_venv_calls.append((venv_dir, base_python))
        python_path = paths.venv_python_path(runtime_venv_dir)
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_create_venv", _fake_create_venv)

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    relaunch_calls = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe: relaunch_calls.append(python_exe))

    bootstrap.ensure_runtime_and_relaunch()

    assert create_venv_calls == [(runtime_venv_dir, alternate)]
    assert len(install_calls) == 3
    assert len(relaunch_calls) == 1
    # Das ALTERNATIVE Python wird nur zum Anlegen der Umgebung verwendet;
    # gestartet wird danach ganz normal ueber die neue venv.
    assert relaunch_calls[0] == paths.venv_python_path(runtime_venv_dir)


def test_installation_failure_exits_nonzero_and_does_not_relaunch(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)
    monkeypatch.setattr(environment_service, "is_supported_python_version", lambda: True)
    monkeypatch.setattr(environment_service, "detect_nvidia_gpu", lambda: False)

    class _FakeEnvBuilder:
        def __init__(self, with_pip=True):
            pass

        def create(self, path):
            python_path = paths.venv_python_path(runtime_venv_dir)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", _FakeEnvBuilder)

    def _failing_run_logged(cmd, splash):
        raise RuntimeError("Simulierter Netzwerkfehler")

    monkeypatch.setattr(bootstrap, "_run_logged", _failing_run_logged)

    relaunch_calls = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe: relaunch_calls.append(python_exe))

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.ensure_runtime_and_relaunch()

    assert exc_info.value.code == 1
    assert relaunch_calls == []


def test_create_venv_without_base_python_uses_env_builder(monkeypatch, tmp_path):
    calls = []

    class _FakeEnvBuilder:
        def __init__(self, with_pip=True):
            calls.append(("init", with_pip))

        def create(self, path):
            calls.append(("create", path))

    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", _FakeEnvBuilder)
    bootstrap._create_venv(tmp_path / "venv", base_python=None)
    assert calls == [("init", True), ("create", str(tmp_path / "venv"))]


def test_create_venv_with_base_python_calls_subprocess(monkeypatch, tmp_path):
    calls = []

    class _FakeResult:
        returncode = 0
        stderr = ""

    def fake_run(command, capture_output, text):
        calls.append(command)
        return _FakeResult()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    venv_dir = tmp_path / "venv"
    bootstrap._create_venv(venv_dir, base_python=Path("/anderswo/python3.11"))
    # str(Path(...)) statt eines festen POSIX-Strings, damit der Test
    # auch unter Windows gilt.
    assert calls == [[str(Path("/anderswo/python3.11")), "-m", "venv", str(venv_dir)]]


def test_create_venv_with_base_python_raises_on_failure(monkeypatch, tmp_path):
    class _FakeResult:
        returncode = 1
        stderr = "irgendein Fehler"

    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: _FakeResult())

    with pytest.raises(RuntimeError, match="irgendein Fehler"):
        bootstrap._create_venv(tmp_path / "venv", base_python=Path("/anderswo/python3.11"))
