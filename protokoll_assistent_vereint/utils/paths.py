"""Zentrale, ausschliesslich relative Pfadermittlung fuer die vereinte Anwendung.

Bewusst nach demselben Muster wie ``lokale_windows_app/utils/paths.py``:
keine absoluten Benutzerpfade, keine fest eingetragenen Benutzernamen. Alle
Pfade werden relativ zum Speicherort dieser Anwendung ermittelt.

WICHTIG: Diese Datei deckt bewusst NUR das ab, was ausschliesslich diese
Anwendung selbst betrifft (Konfiguration, Ausgabeordner, Aufnahmen,
Systemprompt-Vorlagenbibliothek). Alles, was 'services.pipeline_service'
(aus 'lokale_windows_app', wiederverwendet statt kopiert) INTERN selbst
ueber einen bare ``from utils.paths import ...`` aufloest - der
Arbeitsordner fuer Chunks/Manifeste ("get_work_dir") und die AKTIVE
Systemprompt-Datei ("get_system_prompt_file") -, gehoert absichtlich NICHT
hierher: ein zweiter, eigener Satz dieser Funktionen wuerde von
'pipeline_service' schlicht nie gelesen und waere damit irrefuehrend totes
Wissen. Code, der diese beiden Dinge braucht (siehe 'gui/main_window.py'),
importiert sie bewusst bare aus 'utils.paths' (setzt voraus, dass
'lokale_windows_app' im Suchpfad steht - siehe 'app.py')."""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """Wurzelverzeichnis dieser Anwendung.

    Bei einer mit PyInstaller gebauten EXE ist dies der Ordner der EXE-Datei
    (One-Directory-Build). Im Quellcode-Betrieb ist es der Ordner, der
    ``app.py`` enthaelt (Elternordner von ``utils``)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_settings_dir() -> Path:
    directory = get_app_dir() / "einstellungen"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_systemprompt_vorlagen_dir() -> Path:
    """Bibliothek eigener, benannter Systemprompt-Vorlagen (siehe
    'utils/systemprompt_vorlagen.py'). Getrennt von der jeweils AKTIVEN
    Systemprompt-Datei, die 'lokale_windows_app' selbst verwaltet."""
    directory = get_settings_dir() / "systemprompt_vorlagen"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_default_output_dir() -> Path:
    directory = get_app_dir() / "ausgabe"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_recordings_dir() -> Path:
    """Ablageort fuer per Mikrofon aufgenommene WAV-Dateien (Voice Recording)."""
    directory = get_app_dir() / "aufnahmen"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_config_file() -> Path:
    """Rechnerspezifische, lokale Einstellungen. Enthaelt niemals
    Zugangsdaten (siehe 'services/secret_store.py' fuer API-Schluessel) und
    wird nicht versioniert."""
    return get_app_dir() / "konfiguration.json"
