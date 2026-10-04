"""Umgang mit Hugging-Face-Token und Offline-Modus.

Regeln (verbindlich):
* Der Token kommt aus der Umgebungsvariable ``HF_TOKEN`` oder, wenn sie fehlt,
  aus der Datei ``.env`` im Projektordner (Zeile ``HF_TOKEN=...``). Die
  ``.env`` ist von Git ignoriert und darf nie committet werden; aus ihr wird
  nur ``HF_TOKEN`` gelesen, nichts anderes.
* Der Token wird niemals angezeigt, geloggt oder in einer Konfigurationsdatei
  gespeichert.
* Es wird jeweils nur geprueft, OB ein Token vorhanden ist (Ja/Nein).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATEI = ".env"


def _env_datei() -> Path:
    from protokoll_assistent.utils.paths import get_project_root

    return get_project_root() / ENV_DATEI


def _token_aus_env_datei(datei: Path | None = None) -> str:
    """``HF_TOKEN`` aus einer .env-Datei (``KEY=WERT``, ``#`` = Kommentar,
    optional ``export`` davor und Anfuehrungszeichen um den Wert)."""
    try:
        zeilen = (datei or _env_datei()).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for zeile in zeilen:
        zeile = zeile.strip()
        if zeile.startswith("export "):
            zeile = zeile[len("export ") :].lstrip()
        name, gleich, wert = zeile.partition("=")
        if gleich and name.strip() == "HF_TOKEN":
            return wert.strip().strip('"').strip("'").strip()
    return ""


def _token() -> str:
    return os.environ.get("HF_TOKEN", "").strip() or _token_aus_env_datei()


def has_hf_token() -> bool:
    return bool(_token())


def get_hf_token_for_download() -> str | None:
    """Liefert den Token nur zur direkten Weitergabe an huggingface_hub/pyannote.

    Der Rueckgabewert darf nicht geloggt oder gespeichert werden.
    """
    return _token() or None


def enable_offline_mode() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def disable_offline_mode() -> None:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)


def is_offline_mode() -> bool:
    return os.environ.get("HF_HUB_OFFLINE") == "1"
