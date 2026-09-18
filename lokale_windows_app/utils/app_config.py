"""Rechnerspezifische, lokale Konfiguration.

Damit dieselbe Anwendung unveraendert auf jedem PC funktioniert, werden
Dinge wie der zuletzt genutzte Eingabe-/Ausgabeordner oder die
Geraetepraeferenz (GPU/CPU) NICHT im Code, sondern in einer lokalen
JSON-Datei neben der Anwendung gespeichert. Diese Datei ist rein
informativ/komfortabel -- fehlt sie, verwendet die Anwendung sinnvolle
Standardwerte.

Es werden niemals Zugangsdaten (z.B. HF_TOKEN) hier gespeichert.
"""

from __future__ import annotations

import json
from typing import Any

from utils.paths import get_config_file

DEFAULTS: dict[str, Any] = {
    "eingabeordner": None,
    "ausgabeordner": None,
    "geraetepraeferenz": "auto",  # "auto" | "cuda" | "cpu"
    "einrichtung_abgeschlossen": False,
    "whisper_modell": None,  # None = noch keine bewusste Wahl getroffen
}


def load_config() -> dict[str, Any]:
    path = get_config_file()
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: value for key, value in data.items() if key in DEFAULTS})
    return merged


def save_config(config: dict[str, Any]) -> None:
    path = get_config_file()
    to_save = {key: config.get(key, DEFAULTS[key]) for key in DEFAULTS}
    path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")


def update_config(**changes: Any) -> dict[str, Any]:
    config = load_config()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unbekannter Konfigurationsschluessel: {key}")
        config[key] = value
    save_config(config)
    return config
