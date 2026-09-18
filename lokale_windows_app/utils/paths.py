"""Zentrale, ausschliesslich relative Pfadermittlung.

Es werden bewusst keine absoluten Benutzerpfade und keine fest eingetragenen
Benutzernamen verwendet. Alle Pfade werden relativ zum Speicherort der
Anwendung (bzw. der gebauten EXE) ermittelt.
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """Wurzelverzeichnis der Anwendung.

    Bei einer mit PyInstaller gebauten EXE ist dies der Ordner der EXE-Datei
    (One-Directory-Build). Im Quellcode-Betrieb ist es der Ordner, der
    ``app.py`` enthaelt (Elternordner von ``utils``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_project_root() -> Path:
    """Elternverzeichnis der Anwendung (kann, muss aber nicht ``.venv-whisperx``
    enthalten -- siehe ``get_legacy_venv_dir``)."""
    return get_app_dir().parent


def venv_python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def get_legacy_venv_dir() -> Path:
    """Optionale, bereits vorhandene virtuelle Umgebung ``.venv-whisperx``
    NEBEN dem Anwendungsordner. Dies war die urspruengliche Annahme fuer
    einen einzelnen, bereits manuell eingerichteten Rechner. Die Anwendung
    ist davon NICHT mehr abhaengig (siehe ``get_runtime_venv_dir``), nutzt
    eine vorhandene, funktionierende Umgebung aber automatisch weiter, um
    unnoetige Doppel-Downloads zu vermeiden."""
    return get_project_root() / ".venv-whisperx"


def get_runtime_dir() -> Path:
    """Ordner fuer die von der Anwendung selbst verwaltete Laufzeitumgebung.
    Macht die Anwendung von einem manuell vorbereiteten Rechner unabhaengig:
    auf einem neuen PC wird hier automatisch alles Benoetigte installiert."""
    directory = get_app_dir() / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_runtime_venv_dir() -> Path:
    return get_runtime_dir() / "venv"


def get_active_venv_dir() -> Path:
    """Waehlt die zu verwendende virtuelle Umgebung: eine bereits
    vorhandene, funktionsfaehige ``.venv-whisperx`` hat Vorrang (spart Zeit
    und Speicherplatz auf einem bereits eingerichteten Rechner);
    andernfalls die selbst verwaltete Laufzeitumgebung unter ``runtime\\venv``,
    die auf jedem PC automatisch neu angelegt werden kann."""
    legacy_python = venv_python_path(get_legacy_venv_dir())
    if legacy_python.is_file():
        return get_legacy_venv_dir()
    return get_runtime_venv_dir()


def get_active_venv_python() -> Path:
    return venv_python_path(get_active_venv_dir())


# Rueckwaertskompatible Aliase (aeltere Aufrufer/Skripte).
def get_venv_dir() -> Path:
    return get_active_venv_dir()


def get_venv_python(venv_dir: Path | None = None) -> Path:
    return venv_python_path(venv_dir or get_active_venv_dir())


def get_logs_dir() -> Path:
    directory = get_app_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_settings_dir() -> Path:
    directory = get_app_dir() / "einstellungen"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

def get_system_prompt_file() -> Path:
    return get_settings_dir() / "systemprompt_protokoll.txt"


def get_default_system_prompt_file() -> Path:
    """Unveraenderliche mitgelieferte Referenzkopie fuer 'Auf Standard
    zuruecksetzen'. Wird von der Anwendung selbst niemals beschrieben."""
    return get_settings_dir() / "systemprompt_protokoll.default.txt"


def ensure_system_prompt_file_exists() -> None:
    settings_file = get_system_prompt_file()
    if not settings_file.is_file():
        default_file = get_default_system_prompt_file()
        if default_file.is_file():
            settings_file.write_text(default_file.read_text(encoding="utf-8"), encoding="utf-8")

def get_terms_file() -> Path:
    return get_settings_dir() / "fachbegriffe.txt"


def get_work_dir() -> Path:
    """Wurzelordner fuer Arbeitsdaten (Chunks, Zwischenstaende, Manifeste)."""
    directory = get_app_dir() / "arbeitsdaten"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_default_output_dir() -> Path:
    directory = get_app_dir() / "ausgabe"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_tools_ffmpeg_dir() -> Path:
    return get_app_dir() / "tools" / "ffmpeg"


def get_setup_status_file() -> Path:
    return get_app_dir() / "Einrichtungsstatus.json"


def get_config_file() -> Path:
    """Rechnerspezifische, lokale Einstellungen (zuletzt genutzter Eingabe-/
    Ausgabeordner, Geraetepraeferenz). Enthaelt niemals Zugangsdaten und wird
    nicht versioniert -- macht dieselbe Anwendung auf jedem PC individuell
    konfigurierbar, ohne Code oder feste Pfade anzupassen."""
    return get_app_dir() / "konfiguration.json"
