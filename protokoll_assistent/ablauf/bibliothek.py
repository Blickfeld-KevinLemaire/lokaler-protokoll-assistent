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

Umbenennen aendert nur den *Anzeigenamen* (Feld ``anzeigename`` im
Transkript-JSON), keine Datei: Kennung, Freigaben und Dateinamen bleiben.
Zugeordnet (aeltere Protokolle, Exporte) wird weiter ueber den Quellstamm
(``Besprechung.stamm``), nie ueber den angezeigten Titel.

Loeschen legt alle Dateien einer Besprechung in einen Papierkorb: den von
Windows (Funktion von aussen, siehe ``services/papierkorb_service``) oder --
im Servermodus und wenn das scheitert -- ``<Ausgabeordner>/.papierkorb/``.
Diesen Ordner liest die Bibliothek nie.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

TRANSKRIPT_MUSTER = re.compile(r"^(?P<stamm>.+)_lokal_transkript_(?P<zeit>\d{8}_\d{6})(?:_\d+)?$")
PROTOKOLL_MUSTER = re.compile(r"^(?P<stamm>.+)_protokoll_(?P<zeit>\d{8}_\d{6})(?:_\d+)?$")
DATEI_ARTEN = (".txt", ".srt", ".vtt", ".docx", ".md", ".json", ".pdf", ".odt", ".html")
# Ausweich-Papierkorb im Ausgabeordner (Servermodus, oder wenn der von Windows nicht geht).
PAPIERKORB_ORDNER = ".papierkorb"
NAME_HOECHSTENS = 120
_RICHTUNGSZEICHEN = frozenset("‪‫‬‭‮⁦⁧⁨⁩")


class BibliothekFehler(Exception):
    """Umbenennen oder Loeschen ging nicht; der Text ist fuer Menschen gedacht."""


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
    # Quellstamm (``quelldatei_stamm``): Danach heissen Exporte und werden aeltere Protokolle zugeordnet. Der
    # Titel kann nach einem Umbenennen anders lauten. Leer: wie der Titel.
    stamm: str = ""

    def __post_init__(self) -> None:
        if not self.stamm:
            self.stamm = self.titel

    @property
    def neuestes_protokoll(self) -> Protokoll | None:
        return max(self.protokolle, key=lambda p: p.zeit) if self.protokolle else None

    def dateien(self) -> list[Path]:
        """Alle Dateien der Besprechung: Transkript- und Protokollstaemme mit bekannten Endungen und die
        Exporte (``<quellname>_transkript|protokoll|gesamt[_n].<endung>``, siehe ``dokument_export_service``)."""
        staemme = {self.transkript.stem, *(p.json.stem for p in self.protokolle)}
        ordner = self.transkript.parent
        gefunden = [ordner / f"{stamm}{endung}" for stamm in sorted(staemme) for endung in DATEI_ARTEN]
        exporte = self._exporte()
        return [p for p in gefunden if p.is_file()] + [p for p in exporte if p not in gefunden]

    def dokument(self) -> Path | None:
        """Das Word-Dokument der Besprechung (mit Protokoll: Zusammenfassung und Transkript in einem), das nach
        jeder Verarbeitung von selbst entsteht -- siehe ``dokument_export_service.automatisches_word``."""
        neuestes = self.neuestes_protokoll
        kandidaten = ([neuestes.json.with_suffix(".docx")] if neuestes is not None else []) + [
            self.transkript.with_suffix(".docx")
        ]
        return next((p for p in kandidaten if p.is_file()), None)

    def sichtbare_dateien(self) -> list[Path]:
        """Was die Oberflaeche unter „Dateien“ zeigt: das eine Dokument und alles, was jemand exportiert hat.
        Die Daten, aus denen die Anwendung liest (JSON, Markdown), und die Begleitdateien aelterer Laeufe
        (TXT/SRT/VTT) bleiben verborgen -- herunterladen lassen sie sich ueber ``dateien()`` trotzdem."""
        dokument = self.dokument()
        return ([dokument] if dokument is not None else []) + self._exporte()

    def _exporte(self) -> list[Path]:
        ordner = self.transkript.parent
        export = re.compile(rf"^{re.escape(self.stamm)}_(transkript|protokoll|gesamt)(_\d+)?$")
        # Sprecher-Exporte ('<quellname>_<Sprechername>[_n].wav/.txt', siehe sprecher_export_service).
        sprecher = re.compile(rf"^{re.escape(self.stamm)}_(?!lokal_transkript_|protokoll_).+$")
        exporte = sorted(
            p
            for p in ordner.iterdir()
            if p.is_file()
            and (
                (p.suffix.lower() in DATEI_ARTEN and export.match(p.stem))
                or (p.suffix.lower() in (".wav", ".txt") and sprecher.match(p.stem))
            )
        ) if ordner.is_dir() else []
        return exporte

    def als_dict(self) -> dict[str, Any]:
        neuestes = self.neuestes_protokoll
        dokument = self.dokument()
        return {
            "id": self.id,
            "titel": self.titel,
            "zeit": self.zeit,
            "transkript": str(self.transkript),
            "dokument": str(dokument) if dokument is not None else None,
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


def _anzeigename(daten: dict[str, Any]) -> str:
    """Der vergebene Name (Umbenennen) -- nur, wenn er auch jetzt noch gueltig waere (die Datei kann von Hand
    bearbeitet sein)."""
    wert = daten.get("anzeigename")
    if not isinstance(wert, str):
        return ""
    try:
        return name_pruefen(wert)
    except BibliothekFehler:
        return ""


def name_pruefen(name: str) -> str:
    """Ein neuer Anzeigename: ohne Leerraum aussen, 1 bis ``NAME_HOECHSTENS`` Zeichen, keine Steuerzeichen."""
    sauber = name.strip()
    if not sauber:
        raise BibliothekFehler("Der Name darf nicht leer sein.")
    if len(sauber) > NAME_HOECHSTENS:
        raise BibliothekFehler(f"Der Name darf höchstens {NAME_HOECHSTENS} Zeichen lang sein.")
    # Steuerzeichen, Zeilentrenner und die Richtungszeichen, mit denen sich ein Name rueckwaerts darstellen liesse.
    if any(unicodedata.category(zeichen) in ("Cc", "Zl", "Zp") or zeichen in _RICHTUNGSZEICHEN for zeichen in sauber):
        raise BibliothekFehler("Der Name darf keine Steuerzeichen oder Zeilenumbrüche enthalten.")
    return sauber


def besprechungen(ordner: Path) -> list[Besprechung]:
    """Alle Besprechungen im Ordner, neueste zuerst. Ein fehlender Ordner ist leer, kein Fehler."""
    if not ordner.is_dir():
        return []
    transkripte: list[Besprechung] = []
    protokolle: list[tuple[Protokoll, str, str]] = []  # (Protokoll, Quellstamm, Transkriptdatei)
    # Flach (Windows-Anwendung) und eine Ebene tiefer (Servermodus legt je Aufnahme einen Ordner an). Der
    # Papierkorb ist kein Aufnahmeordner: Was dort liegt, ist geloescht.
    for pfad in [*ordner.glob("*.json"), *(p for p in ordner.glob("*/*.json") if p.parent.name != PAPIERKORB_ORDNER)]:
        if treffer := TRANSKRIPT_MUSTER.match(pfad.stem):
            daten = _json_lesen(pfad)
            if not daten.get("segmente"):
                continue
            stamm = str(daten.get("quelldatei_stamm") or treffer["stamm"])
            titel = _anzeigename(daten) or stamm
            transkripte.append(Besprechung(pfad.stem, titel, treffer["zeit"], pfad, _angaben(daten), stamm=stamm))
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
                if b.stamm == stamm and b.zeit <= protokoll.zeit and b.transkript.parent == ordner_des_protokolls
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
        "dateien": [{"name": p.name, "art": p.suffix.lstrip("."), "groesse": p.stat().st_size} for p in besprechung.sichtbare_dateien()],
    }


# --------------------------------------------------------------------------
# Umbenennen
# --------------------------------------------------------------------------
def umbenennen(besprechung: Besprechung, name: str) -> str:
    """Setzt den Anzeigenamen. Nur das Feld ``anzeigename`` im Transkript-JSON aendert sich -- keine Datei wird
    umbenannt, Kennung und Freigaben bleiben. Lautet der Name wieder wie der Quellstamm, entfaellt das Feld."""
    neu = name_pruefen(name)
    pfad = besprechung.transkript
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        raise BibliothekFehler(f"Das Transkript ließ sich nicht lesen: {fehler}") from fehler
    if not isinstance(daten, dict):
        raise BibliothekFehler("Das Transkript ist beschädigt.")
    if neu == besprechung.stamm:
        daten.pop("anzeigename", None)
    else:
        daten["anzeigename"] = neu
    _json_ersetzen(pfad, daten)
    besprechung.titel = neu
    return neu


def _json_ersetzen(pfad: Path, daten: dict[str, Any]) -> None:
    """Atomar: erst unter eindeutigem Arbeitsnamen schreiben, dann ersetzen (mit Wiederholung bei WinError 5)."""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=pfad.parent, prefix=pfad.name + ".", suffix=".tmp", delete=False
    ) as handle:
        json.dump(daten, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    try:
        _ersetzen_mit_wiederholung(temp, pfad)
    except OSError as fehler:
        temp.unlink(missing_ok=True)
        raise BibliothekFehler(f"Speichern ging nicht: {fehler}") from fehler


# --------------------------------------------------------------------------
# Loeschen
# --------------------------------------------------------------------------
Papierkorb = Callable[[list[Path]], None]


def zu_loeschen(besprechung: Besprechung, alle: list[Besprechung]) -> list[Path]:
    """Was beim Loeschen mitgeht: Transkript und Protokolle mit ihren Begleitdateien, dazu die Exporte -- aber keine
    Datei, die eine andere Besprechung im selben Ordner ebenso fuer sich beansprucht (dieselbe Aufnahme noch einmal
    transkribiert, oder ein laengerer Name wie 'sitzung_2' neben 'sitzung'), und keine Datei eines anderen Laufs."""
    eigene = {besprechung.transkript.stem, *(p.json.stem for p in besprechung.protokolle)}
    andere = [b for b in alle if b.id != besprechung.id and b.transkript.parent == besprechung.transkript.parent]
    fremd = {p for b in andere for p in b.dateien()}
    return [
        p
        for p in besprechung.dateien()
        if p.stem in eigene
        or not (p in fremd or TRANSKRIPT_MUSTER.match(p.stem) or PROTOKOLL_MUSTER.match(p.stem))
    ]


def loeschen(
    besprechung: Besprechung, ordner: Path, *, papierkorb: Papierkorb | None = None, jetzt: datetime | None = None
) -> Path | None:
    """Legt alle Dateien der Besprechung in einen Papierkorb. ``ordner`` ist der Ausgabeordner, in dem sie gefunden
    wurde; die Aufnahme selbst (im Aufnahmeordner) bleibt unberuehrt.

    Mit ``papierkorb`` (Windows) dorthin; scheitert das, und ohne ``papierkorb`` (Servermodus) nach
    ``<ordner>/.papierkorb/<zeit>_<kennung>/``. Liegt die Besprechung in einem eigenen Unterordner (Servermodus: einer
    je Aufnahme) und bleibt dort kein anderes Transkript, geht dessen Rest mit, und der leere Ordner verschwindet.

    Gibt den Ordner im Ausweich-Papierkorb zurueck, oder ``None``, wenn alles im Papierkorb von Windows liegt."""
    dateien = zu_loeschen(besprechung, besprechungen(ordner))
    unterordner = besprechung.transkript.parent
    eigener_ordner = unterordner != ordner and not any(
        TRANSKRIPT_MUSTER.match(p.stem) for p in unterordner.glob("*.json") if p not in dateien
    )
    if eigener_ordner:
        dateien += sorted(p for p in unterordner.iterdir() if p.is_file() and p not in dateien)
    # Das Transkript zuletzt: Scheitert vorher etwas, steht die Besprechung noch in der Liste.
    dateien.sort(key=lambda p: p == besprechung.transkript)
    ziel: Path | None = None
    if papierkorb is not None:
        try:
            papierkorb(dateien)
        except OSError:
            ziel = _in_ordner_verschieben([p for p in dateien if p.exists()], ordner, besprechung.id, jetzt)
    else:
        ziel = _in_ordner_verschieben(dateien, ordner, besprechung.id, jetzt)
    if eigener_ordner:
        try:
            unterordner.rmdir()
        except OSError:
            pass  # nicht leer (z. B. ein Unterordner, den jemand von Hand angelegt hat): dann bleibt er
    return ziel


def _in_ordner_verschieben(dateien: list[Path], ordner: Path, kennung: str, jetzt: datetime | None) -> Path:
    basis = ordner / PAPIERKORB_ORDNER / f"{(jetzt or datetime.now()).strftime('%Y%m%d_%H%M%S')}_{kennung}"
    ziel, zaehler = basis, 1
    while ziel.exists():
        zaehler += 1
        ziel = basis.with_name(f"{basis.name}_{zaehler}")
    ziel.mkdir(parents=True)
    verschoben: list[tuple[Path, Path]] = []
    for quelle in dateien:
        try:
            _verschieben(quelle, ziel / quelle.name)
        except OSError as fehler:
            # Zurueck, was schon verschoben ist: lieber ganz als halb geloescht.
            for alt, neu in reversed(verschoben):
                try:
                    _verschieben(neu, alt)
                except OSError:
                    continue
            # Nur, wenn leer: Was nicht zurueck ging, bleibt im Papierkorb erhalten.
            with contextlib.suppress(OSError):
                ziel.rmdir()
            raise BibliothekFehler(
                f"„{quelle.name}“ ließ sich nicht löschen. Ist die Datei noch in einem anderen Programm geöffnet?"
            ) from fehler
        verschoben.append((quelle, ziel / quelle.name))
    return ziel


def _verschieben(quelle: Path, ziel: Path) -> None:
    """Innerhalb desselben Laufwerks (der Papierkorb liegt im Ausgabeordner) ist das ein Umbenennen -- mit derselben
    Wiederholung wie beim Ersetzen, falls ein Virenscanner die Datei kurz offen haelt (CLAUDE.md, Regel 1)."""
    if os.path.lexists(ziel):
        raise FileExistsError(ziel)
    _ersetzen_mit_wiederholung(quelle, ziel)
