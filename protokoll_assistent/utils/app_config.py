"""Rechnerspezifische, lokale Konfiguration.

Eine einfache JSON-Datei neben der Anwendung, nicht versioniert, mit
sinnvollen Standardwerten falls sie fehlt. Hier steht auch, ob
Transkription und Nachbearbeitung lokal oder ueber eine API laufen -
diese Wahl ist eine Einstellung und kein eigenes Programm.

Es wird hier NIEMALS ein API-Schluessel gespeichert - nur ob der Anwender
das Merken auf diesem Geraet ueberhaupt aktiviert hat (siehe
'services/secret_store.py', das die eigentlichen Schluessel getrennt und
verschluesselt in der Windows-Anmeldeinformationsverwaltung ablegt)."""

from __future__ import annotations

import json
from typing import Any

from protokoll_assistent.utils.paths import get_config_file

# Fuer die API-Wege gibt es bewusst KEINE Voreinstellung: Endpunkte und Modelle
# bleiben leer, bis der Anwender einen Anbieter gewaehlt hat (siehe
# 'services/api_anbieter.py'). Frueher stand hier OpenRouter -- und Aufnahmen
# bzw. Texte gingen ohne bewusste Entscheidung an diesen Vermittler.
_STANDARD_OLLAMA_MODELL = "qwen3.5:4b-q4_K_M"
_STANDARD_CHATBOT_EMBEDDING = "bge-m3"

DEFAULTS: dict[str, Any] = {
    "eingabeordner": None,
    "ausgabeordner": None,
    "aufnahmegeraet": None,
    "einrichtung_abgeschlossen": False,
    # "" | "transkription": Die Ersteinrichtung hat die Anwendung fuer die
    # Rechenumgebung neu gestartet und setzt danach an dieser Stelle fort.
    "einrichtung_fortsetzen": "",
    # Ersteinrichtung mit "Nicht mehr fragen" geschlossen, ohne zuzustimmen:
    # Die schwere Rechenumgebung wird nicht ungefragt geladen, bis der Anwender
    # die lokale Einrichtung selbst startet (siehe app.py).
    "lokale_einrichtung_zurueckgestellt": False,
    # "lokal" | "api"
    "transkription_modus": "lokal",
    "whisper_modell": None,
    "geraetepraeferenz": "auto",
    # Gewaehlter API-Anbieter je Bereich: "" (keiner gewaehlt) | "eigener" | Kennung aus api_anbieter.ANBIETER
    "api_transkription_voreinstellung": "",
    "api_transkription_endpunkt": "",
    "api_transkription_modell": "",
    "api_transkription_anbieter": "",
    "api_transkription_schluessel_merken": False,
    # "lokal" | "api"
    "nachbearbeitung_modus": "lokal",
    "ollama_modell": _STANDARD_OLLAMA_MODELL,
    "api_nachbearbeitung_voreinstellung": "",
    "api_nachbearbeitung_endpunkt": "",
    "api_nachbearbeitung_modell": "",
    "api_nachbearbeitung_eigener_schluessel": False,
    "api_nachbearbeitung_schluessel_merken": False,
    "aktive_systemprompt_vorlage": None,
    # Letzte Wahl im Exportdialog
    "export_zielordner": None,
    "export_formate": ["docx", "pdf"],
    # Chatbot "Frag mein Meeting": "lokal" (Ollama) | "api"
    "chatbot_modus": "lokal",
    "chatbot_ollama_modell": _STANDARD_OLLAMA_MODELL,
    "chatbot_embedding_modell": _STANDARD_CHATBOT_EMBEDDING,
    "chatbot_api_voreinstellung": "",
    "chatbot_api_endpunkt": "",
    "chatbot_api_modell": "",
    "chatbot_api_embedding_endpunkt": "",
    "chatbot_api_embedding_modell": "",
    "chatbot_api_eigener_schluessel": False,
    "chatbot_api_schluessel_merken": False,
}


def load_config() -> dict[str, Any]:
    path = get_config_file()
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        # Gueltiges JSON, aber kein Objekt (z. B. eine Liste nach einem
        # misslungenen Eingriff von Hand). Ohne diese Pruefung scheitert
        # '.items()' unten mit einem 'AttributeError' -- und zwar in 'app.py'
        # noch VOR dem ersten Fenster, also ohne jede sichtbare Meldung.
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
