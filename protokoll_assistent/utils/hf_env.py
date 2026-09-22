"""Umgang mit Hugging-Face-Token und Offline-Modus.

Regeln (verbindlich):
* Der Token wird ausschliesslich aus der Umgebungsvariable ``HF_TOKEN`` gelesen.
* Der Token wird niemals angezeigt, geloggt oder in einer Konfigurationsdatei
  gespeichert.
* Es wird jeweils nur geprueft, OB ein Token vorhanden ist (Ja/Nein).
"""

from __future__ import annotations

import os


def has_hf_token() -> bool:
    return bool(os.environ.get("HF_TOKEN", "").strip())


def get_hf_token_for_download() -> str | None:
    """Liefert den Token nur zur direkten Weitergabe an huggingface_hub/pyannote.

    Der Rueckgabewert darf nicht geloggt oder gespeichert werden.
    """
    token = os.environ.get("HF_TOKEN", "").strip()
    return token or None


def enable_offline_mode() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def disable_offline_mode() -> None:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)


def is_offline_mode() -> bool:
    return os.environ.get("HF_HUB_OFFLINE") == "1"
