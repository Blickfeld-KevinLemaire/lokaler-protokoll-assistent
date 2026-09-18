"""Testet die Entscheidungslogik von bootstrap.py OHNE echte
Netzwerk-/pip-/venv-Operationen: alle side-effect-behafteten Aufrufe
(venv.EnvBuilder, pip-Installation, Prozess-Neustart) werden ersetzt."""

from __future__ import annotations

import pytest

import bootstrap
from services import environment_service


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
    bootstrap.ensure_runtime_and_relaunch(app_entry=__file__)
    assert called == []  # kehrt zurueck, ohne irgendetwas zu tun


def test_returns_immediately_when_frozen_pyinstaller_build(monkeypatch):
    # In einer gebauten EXE ist bereits alles gebuendelt -- kein erneutes
    # Einrichten oder Neustarten noetig oder gewollt.
    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    called = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda *a: called.append(a))
    bootstrap.ensure_runtime_and_relaunch(app_entry=__file__)
    assert called == []


def test_uses_existing_legacy_venv_without_installing(monkeypatch, tmp_path):
    legacy_dir = tmp_path / "legacy" / ".venv-whisperx"
    from utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: legacy_dir)

    relaunch_calls = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe, entry: relaunch_calls.append(python_exe))

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    bootstrap.ensure_runtime_and_relaunch(app_entry="app.py")

    assert len(relaunch_calls) == 1
    assert install_calls == []  # keine Installation auf dem bereits fertigen Referenz-PC


def test_fresh_pc_creates_venv_and_installs_then_relaunches(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from utils import paths

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
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe, entry: relaunch_calls.append(python_exe))

    bootstrap.ensure_runtime_and_relaunch(app_entry="app.py")

    assert created_dirs == [str(runtime_venv_dir)]
    assert len(install_calls) == 3  # pip upgrade, torch, restliche Pakete
    assert len(relaunch_calls) == 1
    assert relaunch_calls[0] == paths.venv_python_path(runtime_venv_dir)


def test_unsupported_python_version_aborts_without_installing(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from utils import paths

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)
    monkeypatch.setattr(environment_service, "is_supported_python_version", lambda: False)

    install_calls = []
    monkeypatch.setattr(bootstrap, "_run_logged", lambda cmd, splash: install_calls.append(cmd))

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.ensure_runtime_and_relaunch(app_entry="app.py")

    assert exc_info.value.code == 1
    assert install_calls == []


def test_installation_failure_exits_nonzero_and_does_not_relaunch(monkeypatch, tmp_path):
    runtime_venv_dir = tmp_path / "runtime" / "venv"
    legacy_dir = tmp_path / "nicht_vorhanden" / ".venv-whisperx"
    from utils import paths

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
    monkeypatch.setattr(bootstrap, "_relaunch", lambda python_exe, entry: relaunch_calls.append(python_exe))

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.ensure_runtime_and_relaunch(app_entry="app.py")

    assert exc_info.value.code == 1
    assert relaunch_calls == []
