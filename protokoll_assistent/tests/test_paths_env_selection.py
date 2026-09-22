"""Testet die Auswahl zwischen einer bereits vorhandenen '.venv-whisperx'
und der selbst verwalteten 'runtime\\venv' -- das ist der Kern der
Portabilitaet auf einen beliebigen anderen PC."""

from protokoll_assistent.utils import paths


def test_prefers_existing_legacy_venv_when_present(monkeypatch, tmp_path):
    legacy_dir = tmp_path / "legacy" / ".venv-whisperx"
    runtime_dir = tmp_path / "app" / "runtime" / "venv"
    (legacy_dir / ("Scripts" if paths.sys.platform == "win32" else "bin")).mkdir(parents=True)
    legacy_python = paths.venv_python_path(legacy_dir)
    legacy_python.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_runtime_venv_dir", lambda: runtime_dir)

    assert paths.get_active_venv_dir() == legacy_dir


def test_falls_back_to_runtime_venv_on_fresh_pc(monkeypatch, tmp_path):
    legacy_dir = tmp_path / "legacy" / ".venv-whisperx"  # existiert nicht
    runtime_dir = tmp_path / "app" / "runtime" / "venv"

    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: legacy_dir)
    monkeypatch.setattr(paths, "get_runtime_venv_dir", lambda: runtime_dir)

    assert paths.get_active_venv_dir() == runtime_dir


def test_get_active_venv_python_uses_platform_specific_layout(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime" / "venv"
    monkeypatch.setattr(paths, "get_legacy_venv_dir", lambda: tmp_path / "fehlt" / ".venv-whisperx")
    monkeypatch.setattr(paths, "get_runtime_venv_dir", lambda: runtime_dir)
    python_path = paths.get_active_venv_python()
    assert python_path.parent.parent == runtime_dir
