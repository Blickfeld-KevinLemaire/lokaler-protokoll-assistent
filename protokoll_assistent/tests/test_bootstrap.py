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


def test_frozen_ohne_mitgelieferte_laufzeit_tut_nichts(monkeypatch, tmp_path):
    # Nur die reine EXE/das ZIP weitergegeben, ohne die vom Installer
    # mitgelieferte Python-Laufzeitumgebung ('python\python.exe' NEBEN der
    # EXE) -- der lokale Modus laesst sich dann nicht automatisch
    # einrichten. Das darf nicht abstuerzen; 'main_window.py' faengt den
    # fehlenden lokalen Modus beim Start einer Transkription separat ab.
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)  # kein 'python\python.exe' darunter

    called = []
    monkeypatch.setattr(bootstrap, "_relaunch", lambda *a: called.append(a))
    bootstrap.ensure_runtime_and_relaunch()
    assert called == []


def test_frozen_mit_mitgelieferter_laufzeit_richtet_ein_und_startet_neu(monkeypatch, tmp_path):
    # Der eigentliche, vorher fehlende Fall: die gebaute EXE bringt PySide6 &
    # Co. mit, aber bewusst nicht Torch/faster-whisper/pyannote (siehe
    # 'release.yml') -- fuer den lokalen Modus muss sich das genau wie im
    # Quellcode-Betrieb selbst einrichten, nur mit der mitgelieferten
    # Python-Laufzeitumgebung als Basis statt der (nicht dafuer nutzbaren)
    # EXE selbst.
    from protokoll_assistent.utils import paths

    app_dir = tmp_path / "Protokoll-Assistent"
    bundled_python = app_dir / "python" / "python.exe"
    bundled_python.parent.mkdir(parents=True)
    bundled_python.write_text("dummy", encoding="utf-8")
    runtime_venv_dir = app_dir / "runtime" / "venv"

    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "get_app_dir", lambda: app_dir)
    monkeypatch.setattr(paths, "get_active_venv_dir", lambda: runtime_venv_dir)
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

    # Die mitgelieferte Python-Laufzeitumgebung legt die neue venv an --
    # NICHT die EXE selbst (die liesse sich gar nicht als 'python -m venv'
    # aufrufen).
    assert create_venv_calls == [(runtime_venv_dir, bundled_python)]
    assert len(install_calls) == 3
    assert relaunch_calls == [paths.venv_python_path(runtime_venv_dir)]


def _relaunch_cwd_testen(monkeypatch, tmp_path, *, app_dir: Path) -> Path:
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_app_dir", lambda: app_dir)

    calls = []

    class _FakeCompleted:
        returncode = 0

    def _fake_run(befehl, env, cwd):
        calls.append((befehl, cwd))
        return _FakeCompleted()

    monkeypatch.setattr(bootstrap.subprocess, "run", _fake_run)

    with pytest.raises(SystemExit) as exc_info:
        bootstrap._relaunch(Path("/irgendwo/python.exe"))

    assert exc_info.value.code == 0
    assert len(calls) == 1
    befehl, cwd = calls[0]
    assert befehl == [str(Path("/irgendwo/python.exe")), "-m", "protokoll_assistent.app"]
    return Path(cwd)


def test_relaunch_geht_aus_quellcode_eine_ebene_ueber_app_dir(monkeypatch, tmp_path):
    # Im Quellcode-Betrieb bedeutet 'get_app_dir()' den Paketordner selbst
    # ('protokoll_assistent/', Elternordner von 'utils') -- importierbar ist
    # das Paket erst eine Ebene darueber, der Projektwurzel. 'sys.frozen'
    # existiert ausserhalb einer gebauten EXE grundsaetzlich nicht.
    app_dir = tmp_path / "protokoll_assistent"
    cwd = _relaunch_cwd_testen(monkeypatch, tmp_path, app_dir=app_dir)
    assert cwd == tmp_path


def test_relaunch_bleibt_in_app_dir_wenn_gebaut(monkeypatch, tmp_path):
    # In der gebauten EXE ist 'get_app_dir()' bereits der Ordner der EXE
    # selbst, und der mitgelieferte Quelltext liegt dort ALS Unterordner
    # direkt drin -- 'cwd' darf also nicht eine Ebene hoeher gehen.
    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    cwd = _relaunch_cwd_testen(monkeypatch, tmp_path, app_dir=tmp_path)
    assert cwd == tmp_path


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
