"""Rechnerspezifische, lokale Konfiguration der vereinten Anwendung.

Nach demselben Muster wie ``lokale_windows_app/utils/app_config.py``: eine
einfache JSON-Datei neben der Anwendung, nicht versioniert, mit sinnvollen
Standardwerten falls sie fehlt.

Es wird hier NIEMALS ein API-Schluessel gespeichert - nur ob der Anwender
das Merken auf diesem Geraet ueberhaupt aktiviert hat (siehe
'services/secret_store.py', das die eigentlichen Schluessel getrennt und
verschluesselt in der Windows-Anmeldeinformationsverwaltung ablegt)."""

from __future__ import annotations

import json
from typing import Any

from protokoll_assistent_vereint.utils.paths import get_config_file

# Dieselben Standardwerte wie in der bisherigen Schnittstellen-Anwendung
# (protokoll_assistent_gui.py) - siehe DEFAULT_TRANSKRIPTION_*/OPENROUTER_*
# dort. Hier als reine Vorbelegung der Einstellungen, keine Geheimnisse.
_STANDARD_TRANSKRIPTION_ENDPUNKT = "https://openrouter.ai/api/v1/audio/transcriptions"
_STANDARD_TRANSKRIPTION_MODELL = "microsoft/mai-transcribe-2"
_STANDARD_TRANSKRIPTION_ANBIETER = "azure"
_STANDARD_NACHBEARBEITUNG_ENDPUNKT = "https://openrouter.ai/api/v1/chat/completions"
_STANDARD_NACHBEARBEITUNG_MODELL = "openai/gpt-4o-mini"
_STANDARD_OLLAMA_MODELL = "qwen3:8b"

DEFAULTS: dict[str, Any] = {
    "eingabeordner": None,
    "ausgabeordner": None,
    "aufnahmegeraet": None,
    "einrichtung_abgeschlossen": False,
    # "lokal" | "api"
    "transkription_modus": "lokal",
    "whisper_modell": None,
    "geraetepraeferenz": "auto",
    "api_transkription_endpunkt": _STANDARD_TRANSKRIPTION_ENDPUNKT,
    "api_transkription_modell": _STANDARD_TRANSKRIPTION_MODELL,
    "api_transkription_anbieter": _STANDARD_TRANSKRIPTION_ANBIETER,
    "api_transkription_schluessel_merken": False,
    # "lokal" | "api"
    "nachbearbeitung_modus": "lokal",
    "ollama_modell": _STANDARD_OLLAMA_MODELL,
    "api_nachbearbeitung_endpunkt": _STANDARD_NACHBEARBEITUNG_ENDPUNKT,
    "api_nachbearbeitung_modell": _STANDARD_NACHBEARBEITUNG_MODELL,
    "api_nachbearbeitung_eigener_schluessel": False,
    "api_nachbearbeitung_schluessel_merken": False,
    "aktive_systemprompt_vorlage": None,
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
