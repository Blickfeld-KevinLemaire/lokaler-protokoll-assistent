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
import tempfile
import time
from pathlib import Path
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
    # Grundlage der Antworten: "auszuege" (passende Ausschnitte) | "volltext" (ganzer Text)
    "chatbot_kontext": "auszuege",
    "chatbot_api_voreinstellung": "",
    "chatbot_api_endpunkt": "",
    "chatbot_api_modell": "",
    "chatbot_api_embedding_endpunkt": "",
    "chatbot_api_embedding_modell": "",
    "chatbot_api_eigener_schluessel": False,
    "chatbot_api_schluessel_merken": False,
    # Empfang fuer die WLAN-Aufnahmegeraete (GERAETE-SCHNITTSTELLE.md). Aus,
    # bis der Anwender ihn einschaltet. Je Geraet steht hier nur der
    # SHA-256 seines Tokens (Liste von {"name", "token_sha256", "angelegt"}) --
    # das Token selbst wird nur beim Anlegen einmal angezeigt.
    "geraete_empfang_aktiv": False,
    "geraete_empfang_port": 8765,
    "geraete_empfang_geraete": [],
    # Aufnahmegeraete: waehrend der Aufnahme schon transkribieren und nach dem Ende
    # automatisch auswerten. 'geraete_live_auftrag' ist der Name einer
    # Systemprompt-Vorlage (leer: das Modell fasst so zusammen, wie es sinnvoll ist).
    "geraete_live_aktiv": True,
    "geraete_live_auftrag": "",
    # Die Auswertung (Stufe 1 und 2) schon waehrend der Aufnahme vorberechnen; der Auswertungstext enthaelt
    # dann keine Sprecherangaben (die Sprechertrennung entsteht erst am Ende).
    "geraete_live_auswertung_vorab": True,
    # Laenge der Abschnitte (Sekunden), die das Sprachmodell einzeln auswertet. Kuerzere Abschnitte
    # verkuerzen die Wartezeit nach dem Ende: Es bleibt hoechstens der letzte offen.
    "geraete_live_abschnitt_sekunden": 180,
}


def load_config() -> dict[str, Any]:
    path = get_config_file()
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        # 'utf-8-sig': Der Windows-Editor speichert von Hand bearbeitete Dateien gern mit BOM.
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return dict(DEFAULTS)  # gerade gesperrt: nichts anfassen
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        # Kein JSON (halb geschrieben, von Hand beschaedigt) oder gueltiges JSON, aber kein Objekt (z. B.
        # eine Liste). Ohne diese Pruefung scheitert '.items()' unten -- in 'app.py' noch VOR dem ersten
        # Fenster, also ohne jede sichtbare Meldung.
        _defekte_datei_sichern(path)
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: value for key, value in data.items() if key in DEFAULTS})
    return merged


def save_config(config: dict[str, Any]) -> None:
    path = get_config_file()
    to_save = {key: config.get(key, DEFAULTS[key]) for key in DEFAULTS}
    # Atomar: erst unter Arbeitsnamen, dann ersetzen. Ein Absturz oder Stromausfall mitten im Schreiben
    # hinterliesse sonst eine halbe Datei -- und mit ihr waeren die Einrichtung, die angemeldeten
    # Aufnahmegeraete und alle API-Einstellungen weg.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
        json.dump(to_save, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    _ersetzen_mit_wiederholung(temp, path)


def _ersetzen_mit_wiederholung(temp: Path, ziel: Path, versuche: int = 6, warten: float = 0.1) -> None:
    """``os.replace`` mit Wiederholung: Unter Windows haelt ein Virenscanner oder der Suchindex die eben
    geschriebene Datei manchmal noch kurz offen ("Zugriff verweigert", siehe CLAUDE.md, Regel 1)."""
    for versuch in range(versuche):
        try:
            temp.replace(ziel)
            return
        except PermissionError:
            if versuch == versuche - 1:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(warten)
        except OSError:
            temp.unlink(missing_ok=True)
            raise


def _defekte_datei_sichern(path: Path) -> None:
    """Eine unlesbare Einstellungsdatei wird beiseitegelegt statt beim naechsten Speichern stillschweigend
    mit den Standardwerten ueberschrieben -- so laesst sich von Hand retten, was darin stand."""
    try:
        path.replace(path.with_name(path.stem + ".defekt.json"))
    except OSError:
        pass


def update_config(**changes: Any) -> dict[str, Any]:
    config = load_config()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unbekannter Konfigurationsschluessel: {key}")
        config[key] = value
    save_config(config)
    return config
