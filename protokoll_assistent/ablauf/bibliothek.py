"""Die Besprechungen im Ausgabeordner: Transkript, zugehoerige Protokolle und Dateien.

Die Verarbeitung legt alles flach in den Ausgabeordner:

* ``<stamm>_lokal_transkript_<zeit>.json`` (+ ``.txt``, ``.srt``, ``.vtt``, ``.docx``)
* ``<stamm>_protokoll_<zeit>.json`` (+ ``.md``, ``.docx``)

Eine *Besprechung* ist hier ein Transkript samt den Protokollen, die daraus
entstanden sind. Neuere Protokolle tragen den Namen ihres Transkripts
(``transkript_datei``); aeltere werden ueber den Quellnamen und die Zeit
zugeordnet (das juengste Transkript desselben Namens, das vor dem Protokoll
entstand).

Die Kennung einer Besprechung ist der Dateistamm ihres Transkripts. Pfade
werden nie aus einer Kennung *gebaut*, sondern nur in der Liste
nachgeschlagen -- so kann eine Anfrage nicht aus dem Ordner herausfuehren.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRANSKRIPT_MUSTER = re.compile(r"^(?P<stamm>.+)_lokal_transkript_(?P<zeit>\d{8}_\d{6})(?:_\d+)?$")
PROTOKOLL_MUSTER = re.compile(r"^(?P<stamm>.+)_protokoll_(?P<zeit>\d{8}_\d{6})(?:_\d+)?$")
DATEI_ARTEN = (".txt", ".srt", ".vtt", ".docx", ".md", ".json", ".pdf", ".odt", ".html")


@dataclass
class Protokoll:
    json: Path
    md: Path | None
    zeit: str

    @property
    def id(self) -> str:
        return self.json.stem


@dataclass
class Besprechung:
    id: str
    titel: str
    zeit: str
    transkript: Path
    angaben: dict[str, Any] = field(default_factory=dict)
    protokolle: list[Protokoll] = field(default_factory=list)

    @property
    def neuestes_protokoll(self) -> Protokoll | None:
        return max(self.protokolle, key=lambda p: p.zeit) if self.protokolle else None

    def dateien(self) -> list[Path]:
        """Alle Dateien der Besprechung (Transkript- und Protokollstaemme, bekannte Endungen)."""
        staemme = {self.transkript.stem, *(p.json.stem for p in self.protokolle)}
        ordner = self.transkript.parent
        gefunden = [ordner / f"{stamm}{endung}" for stamm in sorted(staemme) for endung in DATEI_ARTEN]
        return [p for p in gefunden if p.is_file()]

    def als_dict(self) -> dict[str, Any]:
        neuestes = self.neuestes_protokoll
        return {
            "id": self.id,
            "titel": self.titel,
            "zeit": self.zeit,
            "transkript": str(self.transkript),
            "dauer_sekunden": self.angaben.get("dauer_sekunden"),
            "anzahl_sprecher": self.angaben.get("anzahl_sprecher"),
            "sprache": self.angaben.get("sprache"),
            "hat_protokoll": neuestes is not None,
            "protokolle": [{"id": p.id, "zeit": p.zeit} for p in sorted(self.protokolle, key=lambda p: p.zeit)],
        }


def _json_lesen(pfad: Path) -> dict[str, Any]:
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def _angaben(daten: dict[str, Any]) -> dict[str, Any]:
    segmente = daten.get("segmente") or []
    dauer = max((float(s.get("ende_sekunden") or 0) for s in segmente if isinstance(s, dict)), default=0.0)
    return {
        "dauer_sekunden": round(dauer, 1),
        "anzahl_sprecher": daten.get("anzahl_sprecher"),
        "sprache": daten.get("sprache"),
        "quelldatei": daten.get("quelldatei"),
    }


def besprechungen(ordner: Path) -> list[Besprechung]:
    """Alle Besprechungen im Ordner, neueste zuerst. Ein fehlender Ordner ist leer, kein Fehler."""
    if not ordner.is_dir():
        return []
    transkripte: list[Besprechung] = []
    protokolle: list[tuple[Protokoll, str, str]] = []  # (Protokoll, Quellstamm, Transkriptdatei)
    # Flach (Windows-Anwendung) und eine Ebene tiefer (Servermodus legt je Aufnahme einen Ordner an).
    for pfad in [*ordner.glob("*.json"), *ordner.glob("*/*.json")]:
        if treffer := TRANSKRIPT_MUSTER.match(pfad.stem):
            daten = _json_lesen(pfad)
            if not daten.get("segmente"):
                continue
            titel = str(daten.get("quelldatei_stamm") or treffer["stamm"])
            transkripte.append(Besprechung(pfad.stem, titel, treffer["zeit"], pfad, _angaben(daten)))
        elif treffer := PROTOKOLL_MUSTER.match(pfad.stem):
            daten = _json_lesen(pfad)
            md = pfad.with_suffix(".md")
            protokolle.append(
                (
                    Protokoll(pfad, md if md.is_file() else None, treffer["zeit"]),
                    str(daten.get("quelldatei_stamm") or treffer["stamm"]),
                    str(daten.get("transkript_datei") or ""),
                )
            )
    nach_datei = {(b.transkript.parent, b.transkript.name): b for b in transkripte}
    for protokoll, stamm, transkript_datei in protokolle:
        ordner_des_protokolls = protokoll.json.parent
        ziel = nach_datei.get((ordner_des_protokolls, transkript_datei)) if transkript_datei else None
        if ziel is None:
            kandidaten = [
                b
                for b in transkripte
                if b.titel == stamm and b.zeit <= protokoll.zeit and b.transkript.parent == ordner_des_protokolls
            ]
            ziel = max(kandidaten, key=lambda b: b.zeit) if kandidaten else None
        if ziel is not None:
            ziel.protokolle.append(protokoll)
    return sorted(transkripte, key=lambda b: (b.zeit, b.id), reverse=True)


def finde(ordner: Path, kennung: str) -> Besprechung | None:
    return next((b for b in besprechungen(ordner) if b.id == kennung), None)


def details(besprechung: Besprechung) -> dict[str, Any]:
    """Alles, was die Oberflaeche zum Anzeigen und Bearbeiten braucht."""
    daten = _json_lesen(besprechung.transkript)
    neuestes = besprechung.neuestes_protokoll
    protokoll_text = ""
    if neuestes is not None:
        if neuestes.md is not None:
            try:
                protokoll_text = neuestes.md.read_text(encoding="utf-8")
            except OSError:
                protokoll_text = ""
        if not protokoll_text:
            protokoll_text = str(_json_lesen(neuestes.json).get("ergebnis") or "")
    return {
        **besprechung.als_dict(),
        "sprecher": [
            {
                "id": s.get("sprecher_id"),
                "name": s.get("anzeigename"),
                "segmente": s.get("anzahl_segmente"),
                "sekunden": s.get("sprechdauer_sekunden"),
            }
            for s in daten.get("sprecher_zuordnung") or []
            if isinstance(s, dict)
        ],
        "segmente": [
            {
                "start": s.get("start_sekunden"),
                "ende": s.get("ende_sekunden"),
                "sprecher_id": s.get("sprecher_id"),
                "sprecher": s.get("sprecher"),
                "text": s.get("text"),
            }
            for s in daten.get("segmente") or []
            if isinstance(s, dict)
        ],
        "protokoll": {"id": neuestes.id, "text": protokoll_text} if neuestes is not None else None,
        "dateien": [{"name": p.name, "art": p.suffix.lstrip("."), "groesse": p.stat().st_size} for p in besprechung.dateien()],
    }
