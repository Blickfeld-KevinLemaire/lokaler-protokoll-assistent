"""Gespeicherte Chatverlaeufe des Chatbots "Frag mein Meeting".

Jeder Verlauf ist eine JSON-Datei im Ordner ``chatverlaeufe/`` (siehe
``utils.paths.get_chatverlaeufe_dir``): Titel, Zeiten, die dabei benutzten
Unterlagen und die Nachrichten mit Quellen. Die Dateien enthalten Inhalte aus
Besprechungen und werden deshalb weder versioniert noch in den Installer
aufgenommen (siehe ``SECURITY.md``).
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

FORMAT_VERSION = 1
MAX_TITEL = 60
_ID = re.compile(r"^[0-9]{8}_[0-9]{6}(_[0-9]+)?$")


@dataclass
class Verlauf:
    id: str
    titel: str
    erstellt: str
    aktualisiert: str
    dokumente: list[str] = field(default_factory=list)
    nachrichten: list[dict[str, Any]] = field(default_factory=list)


def _jetzt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def titel_aus_frage(frage: str) -> str:
    einzeilig = " ".join(frage.split())
    return einzeilig if len(einzeilig) <= MAX_TITEL else einzeilig[: MAX_TITEL - 1].rstrip() + "…"


def neuer_verlauf(ordner: Path, erste_frage: str) -> Verlauf:
    """Legt einen Verlauf mit eindeutiger Kennung an (noch nicht gespeichert)."""
    basis = datetime.now().strftime("%Y%m%d_%H%M%S")
    kennung, zaehler = basis, 1
    while (ordner / f"{kennung}.json").exists():
        zaehler += 1
        kennung = f"{basis}_{zaehler}"
    jetzt = _jetzt()
    return Verlauf(kennung, titel_aus_frage(erste_frage) or "Neuer Chat", jetzt, jetzt)


def speichern(ordner: Path, verlauf: Verlauf) -> None:
    if not _ID.match(verlauf.id):
        raise ValueError(f"Ungueltige Verlaufskennung: {verlauf.id!r}")
    verlauf.aktualisiert = _jetzt()
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / f"{verlauf.id}.json"
    # Atomar schreiben (Projektregel 1): erst unter Arbeitsnamen, dann ersetzen.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ordner, suffix=".tmp", delete=False) as handle:
        json.dump({"version": FORMAT_VERSION, **asdict(verlauf)}, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    _ersetzen_mit_wiederholung(temp, ziel)


def _lesen(pfad: Path) -> Verlauf | None:
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict) or not _ID.match(str(daten.get("id", ""))):
        return None
    nachrichten = [
        n for n in daten.get("nachrichten", []) if isinstance(n, dict) and n.get("role") in {"user", "assistant"}
    ]
    return Verlauf(
        id=str(daten["id"]),
        titel=str(daten.get("titel") or "Chat"),
        erstellt=str(daten.get("erstellt", "")),
        aktualisiert=str(daten.get("aktualisiert", "")),
        dokumente=[str(d) for d in daten.get("dokumente", []) if isinstance(d, str)],
        nachrichten=nachrichten,
    )


def lade(ordner: Path, kennung: str) -> Verlauf | None:
    if not _ID.match(kennung):
        return None
    return _lesen(ordner / f"{kennung}.json")


def lade_alle(ordner: Path) -> list[Verlauf]:
    """Alle lesbaren Verlaeufe, zuletzt benutzte zuerst. Beschaedigte Dateien
    werden uebersprungen, damit sie die Liste nicht blockieren."""
    if not ordner.is_dir():
        return []
    verlaeufe = [v for pfad in ordner.glob("*.json") if (v := _lesen(pfad)) is not None]
    return sorted(verlaeufe, key=lambda v: (v.aktualisiert, v.id), reverse=True)


def loesche(ordner: Path, kennung: str) -> bool:
    if not _ID.match(kennung):
        return False
    pfad = ordner / f"{kennung}.json"
    if not pfad.is_file():
        return False
    pfad.unlink()
    return True


def umbenennen(ordner: Path, kennung: str, neuer_titel: str) -> bool:
    verlauf = lade(ordner, kennung)
    titel = " ".join(neuer_titel.split())
    if verlauf is None or not titel:
        return False
    verlauf.titel = titel
    speichern(ordner, verlauf)
    return True
