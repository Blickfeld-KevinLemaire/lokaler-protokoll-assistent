"""Zentrale, ausschliesslich relative Pfadermittlung.

Es werden bewusst keine absoluten Benutzerpfade und keine fest eingetragenen
Benutzernamen verwendet. Alle Pfade werden relativ zum Speicherort der
Anwendung (bzw. der gebauten EXE) ermittelt.
"""

from __future__ import annotations

import hashlib
import os
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


def _daten_ordner(name: str) -> Path:
    """Ordner fuer veraenderliche Daten. Ist ``PROTOKOLL_DATEN_DIR`` gesetzt (im
    Container: ein eingebundenes Volume), liegen sie dort, sonst neben der
    Anwendung. Die mitgelieferten Dateien (Vorlagen, Systemprompt) bleiben
    immer im Anwendungsordner."""
    basis = os.environ.get("PROTOKOLL_DATEN_DIR", "").strip()
    return (Path(basis) if basis else get_app_dir()) / name


def get_logs_dir() -> Path:
    directory = _daten_ordner("logs")
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


# SHA-256 des normalisierten Textes (siehe '_prompt_normalisieren') der frueher
# mitgelieferten Standard-Systemprompts mit fester JSON-Struktur: Fassung aus
# 62736dd (wortgleich zuvor in 'lokale_windows_app/einstellungen/') und aus
# 96674cf. Seit die Nachbearbeitung nur noch dem Systemprompt folgt, liesse ein
# solcher Prompt das Modell JSON ins Protokoll schreiben. Die Texte selbst
# stehen in 'tests/test_systemprompt_datei.py'.
_FRUEHERE_STANDARD_SYSTEMPROMPTS_SHA256 = frozenset(
    {
        "02c4aa7fd8f01e22f5bb0877d1136fbb9b4808c091be5dabd204907bd6fedba3",
        "6e3885a13ae1658828da4834d7dd0d9a144813ea81681adb1e630eb947051ca4",
    }
)


def _prompt_normalisieren(text: str) -> str:
    """Gleicht ab, was Editoren unter Windows nebenbei aendern: BOM,
    Zeilenenden, Leerraum am Zeilenende und am Anfang/Ende."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(zeile.rstrip() for zeile in text.split("\n")).strip()


def ist_frueherer_standard_systemprompt(text: str) -> bool:
    """True, wenn ``text`` unveraendert einer der frueher mitgelieferten
    Standard-Prompts ist (also nie vom Anwender bearbeitet wurde)."""
    pruefsumme = hashlib.sha256(_prompt_normalisieren(text).encode("utf-8")).hexdigest()
    return pruefsumme in _FRUEHERE_STANDARD_SYSTEMPROMPTS_SHA256


def ensure_system_prompt_file_exists() -> None:
    """Legt die Prompt-Datei aus der Referenzkopie an, wenn sie fehlt.

    Steht darin noch unveraendert ein frueher mitgelieferter Standard (feste
    JSON-Struktur), wird er durch den aktuellen Standard ersetzt -- sonst
    behielten Anwender nach einem Update den alten Prompt. Ein vom Anwender
    bearbeiteter Prompt bleibt immer, wie er ist."""
    settings_file = get_system_prompt_file()
    default_file = get_default_system_prompt_file()
    standard = default_file.read_text(encoding="utf-8") if default_file.is_file() else None
    if standard is not None and ist_frueherer_standard_systemprompt(standard):
        # Auch die Referenzkopie kann noch die alte Fassung sein; der neue
        # Standard ist leer.
        standard = ""
    if not settings_file.is_file():
        if standard is not None:
            settings_file.write_text(standard, encoding="utf-8")
        return
    try:
        inhalt = settings_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if ist_frueherer_standard_systemprompt(inhalt):
        try:
            settings_file.write_text(standard or "", encoding="utf-8")
        except OSError:
            # Gesperrt (z. B. Virenscanner): beim naechsten Start erneut.
            pass

def get_work_dir() -> Path:
    """Wurzelordner fuer Arbeitsdaten (Chunks, Zwischenstaende, Manifeste)."""
    directory = _daten_ordner("arbeitsdaten")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_sprecherprofile_dir() -> Path:
    """Ablage der gespeicherten Sprecherprofile (Stimmabdruecke).

    Stimmabdruecke sind biometrische Daten: Der Ordner wird nicht versioniert,
    nicht in den Installer aufgenommen und bei der Deinstallation absichtlich
    nicht angefasst. Er wird nur beim ersten Speichern eines Profils angelegt."""
    return get_app_dir() / "sprecherprofile"


def get_chatverlaeufe_dir() -> Path:
    """Ablage der gespeicherten Chatverlaeufe ("Frag mein Meeting").

    Enthaelt Inhalte aus Besprechungen: nicht versioniert, nicht im Installer,
    bei der Deinstallation absichtlich nicht angefasst. Wird erst beim ersten
    Speichern angelegt."""
    return get_app_dir() / "chatverlaeufe"


def get_default_output_dir() -> Path:
    directory = get_app_dir() / "ausgabe"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_recordings_dir() -> Path:
    """Ablageort fuer per Mikrofon aufgenommene WAV-Dateien (Voice Recording).

    Existiert unabhaengig davon, ob der Anwender bereits einen Eingabeordner
    gewaehlt hat - eine Aufnahme muss immer irgendwo landen koennen."""
    directory = get_app_dir() / "aufnahmen"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_systemprompt_vorlagen_dir() -> Path:
    """Bibliothek eigener, benannter Systemprompt-Vorlagen (siehe
    'utils/systemprompt_vorlagen.py'). Getrennt von der jeweils AKTIVEN
    Systemprompt-Datei ('get_system_prompt_file'): Eine Vorlage ist ein
    Vorrat, aus dem der Anwender fuer einen Lauf auswaehlt."""
    directory = get_settings_dir() / "systemprompt_vorlagen"
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
