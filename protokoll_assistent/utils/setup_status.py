"""Verwaltung von ``Einrichtungsstatus.json``.

Die Datei haelt fest, welche Einrichtungsphasen bereits erfolgreich
abgeschlossen wurden, damit ``Einrichtung-Lokal.ps1`` nach einem Fehler an
der richtigen Stelle fortgesetzt werden kann und ``Anwendung-starten.ps1``
den regulaeren Programmstart verweigern kann, solange die Einrichtung
unvollstaendig ist.

Es werden ausschliesslich Versionsnummern, Pruefergebnisse und Zeitstempel
gespeichert -- niemals der HF_TOKEN oder andere Zugangsdaten.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from protokoll_assistent.utils.paths import get_setup_status_file

PHASES = [
    "systempruefung",
    "python_umgebung",
    "modelle",
    "offline_pruefung",
    "abschluss",
]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_status() -> dict[str, Any]:
    path = get_setup_status_file()
    if not path.is_file():
        return {"phasen": {}, "abgeschlossen": False}
    return json.loads(path.read_text(encoding="utf-8"))


def save_status(status: dict[str, Any]) -> None:
    status["aktualisiert"] = _now_iso()
    get_setup_status_file().write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mark_phase(
    status: dict[str, Any], phase: str, ok: bool, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"Unbekannte Einrichtungsphase: {phase}")
    status.setdefault("phasen", {})[phase] = {
        "erfolgreich": ok,
        "details": details or {},
        "zeitpunkt": _now_iso(),
    }
    status["abgeschlossen"] = all(
        status["phasen"].get(p, {}).get("erfolgreich", False) for p in PHASES
    )
    return status


def missing_phases(status: dict[str, Any]) -> list[str]:
    return [p for p in PHASES if not status.get("phasen", {}).get(p, {}).get("erfolgreich", False)]


def is_fully_set_up(status: dict[str, Any]) -> bool:
    return bool(status.get("abgeschlossen")) and not missing_phases(status)
