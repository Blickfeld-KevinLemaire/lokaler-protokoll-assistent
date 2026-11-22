"""Besprechungen: Liste, Einzelansicht, Protokoll bearbeiten, Sprecher umbenennen, Dateien, Export, Teilen.

Windows-Anwendung: Kennung = Dateistamm des Transkripts. Servermodus mit
mehreren Nutzern: Kennung = ``<besitzer>~<stamm>``; jeder sieht seine eigenen
und die mit ihm geteilten Besprechungen. Aendern darf nur der Besitzer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from protokoll_assistent.ablauf import bibliothek, freigaben
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste
from protokoll_assistent.services import dokument_export_service, export_service

router = APIRouter(prefix="/api/besprechungen", tags=["besprechungen"])

MEDIENTYPEN = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".srt": "application/x-subrip",
    ".vtt": "text/vtt; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".wav": "audio/wav",
}


@dataclass
class Gefunden:
    besprechung: bibliothek.Besprechung
    besitzer: str | None
    eigen: bool


def _kennung(d: Dienste, besitzer: str | None, stamm: str) -> str:
    return freigaben.kennung(besitzer, stamm) if d.mehrbenutzer and besitzer else stamm


def _als_dict(d: Dienste, g: Gefunden) -> dict[str, Any]:
    daten = g.besprechung.als_dict()
    daten["id"] = _kennung(d, g.besitzer, g.besprechung.id)
    daten["besitzer"] = g.besitzer
    daten["eigen"] = g.eigen
    daten["geteilt_mit"] = d.freigaben().mit_wem(g.besitzer, g.besprechung.id) if d.mehrbenutzer and g.besitzer else []
    return daten


def _alle(d: Dienste, wer: Angemeldet) -> list[Gefunden]:
    eigene = [Gefunden(b, wer.besitzer, True) for b in bibliothek.besprechungen(d.ausgabeordner(wer))]
    if not d.mehrbenutzer or wer.besitzer is None:
        return eigene
    geteilte = []
    for besitzer, stamm in d.freigaben().sichtbar_fuer(wer.besitzer):
        gefunden = bibliothek.finde(d.ausgabeordner_von(besitzer), stamm)
        if gefunden is not None:
            geteilte.append(Gefunden(gefunden, besitzer, False))
    return sorted(eigene + geteilte, key=lambda g: (g.besprechung.zeit, g.besprechung.id), reverse=True)


def besprechung_finden(d: Dienste, wer: Angemeldet, kennung: str, *, aendern: bool = False) -> Gefunden:
    if d.mehrbenutzer and wer.besitzer is not None:
        teile = freigaben.zerlegen(kennung)
        besitzer, stamm = teile if teile is not None else (wer.besitzer, kennung)
        eigen = besitzer.lower() == wer.besitzer.lower()
        if not eigen and not d.freigaben().darf_lesen(wer.besitzer, besitzer, stamm):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Dieses Transkript gibt es nicht (mehr).")
        gefunden = bibliothek.finde(d.ausgabeordner_von(besitzer), stamm)
        ergebnis = Gefunden(gefunden, besitzer, eigen) if gefunden is not None else None
    else:
        gefunden = bibliothek.finde(d.ausgabeordner(wer), kennung)
        ergebnis = Gefunden(gefunden, None, True) if gefunden is not None else None
    if ergebnis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dieses Transkript gibt es nicht (mehr).")
    if aendern and not ergebnis.eigen:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Geteilte Transkripte kann nur der Besitzer ändern.")
    return ergebnis


def unterlagen_fuer(d: Dienste, wer: Angemeldet, kennungen: list[str]) -> list[Path]:
    """Transkript und neuestes Protokoll je gewaehlter Besprechung (ohne Auswahl: alle sichtbaren) -- fuer den Chat."""
    alle = _alle(d, wer)
    gewaehlt = [g for g in alle if _kennung(d, g.besitzer, g.besprechung.id) in set(kennungen)] if kennungen else alle
    pfade: list[Path] = []
    for g in gewaehlt:
        pfade.append(g.besprechung.transkript)
        neuestes = g.besprechung.neuestes_protokoll
        if neuestes is not None and neuestes.md is not None:
            pfade.append(neuestes.md)
    return pfade


def _word_neu(besprechung: bibliothek.Besprechung) -> str | None:
    """Die automatische Word-Datei passend neu schreiben; scheitert das, bleibt der Rest gueltig."""
    neuestes = besprechung.neuestes_protokoll
    try:
        dokument_export_service.automatisches_word(besprechung.transkript, neuestes.json if neuestes else None)
    except dokument_export_service.ExportFehler as fehler:
        return str(fehler)
    return None


# Literale Pfade VOR denen mit Platzhalter (ein Platzhalter verschluckt sonst das Literal).
@router.get("/export/formate")
def formate() -> list[dict[str, Any]]:
    return [{"id": f.id, "name": f.name, "inhalte": list(f.inhalte)} for f in dokument_export_service.FORMATE]


@router.get("", response_model=list[modelle.Besprechung])
def liste(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> list[dict[str, Any]]:
    return [_als_dict(d, g) for g in _alle(d, wer)]


@router.get("/{kennung}", response_model=modelle.BesprechungDetails)
def details(kennung: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    g = besprechung_finden(d, wer, kennung)
    return {**bibliothek.details(g.besprechung), **_als_dict(d, g)}


@router.put("/{kennung}/protokoll")
def protokoll_speichern(
    kennung: str, daten: modelle.ProtokollSpeichern, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    besprechung = besprechung_finden(d, wer, kennung, aendern=True).besprechung
    neuestes = besprechung.neuestes_protokoll
    if neuestes is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Zu diesem Transkript gibt es noch keine Zusammenfassung.")
    md = neuestes.md or neuestes.json.with_suffix(".md")
    try:
        export_service.update_protocol_exports(neuestes.json, md, daten.text)
    except (OSError, ValueError) as fehler:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Speichern fehlgeschlagen: {fehler}") from fehler
    return {"gespeichert": True, "word_hinweis": _word_neu(besprechung)}


@router.put("/{kennung}/sprecher")
def sprecher_umbenennen(
    kennung: str, daten: modelle.SprecherNamen, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    besprechung = besprechung_finden(d, wer, kennung, aendern=True).besprechung
    namen = {k: v.strip() for k, v in daten.namen.items() if v.strip()}
    try:
        export_service.reexport_with_new_names(besprechung.transkript, namen)
    except OSError as fehler:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Neu schreiben fehlgeschlagen: {fehler}") from fehler
    return {"gespeichert": True, "word_hinweis": _word_neu(besprechung)}


@router.put("/{kennung}/freigabe")
def teilen(
    kennung: str, daten: modelle.Freigabe, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    """Mit wem die Besprechung geteilt ist (``["alle"]``, einzelne Anmeldenamen oder leer)."""
    if not d.mehrbenutzer or wer.besitzer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teilen gibt es nur auf dem Server mit mehreren Nutzern.")
    g = besprechung_finden(d, wer, kennung, aendern=True)
    bekannt = {n.name.lower() for n in d.nutzer.liste()} if d.nutzer is not None else set()
    unbekannt = [m for m in daten.mit if m != freigaben.ALLE and m.lower() not in bekannt]
    if unbekannt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unbekannte Nutzer: {', '.join(unbekannt)}")
    mit = d.freigaben().setzen(wer.besitzer, g.besprechung.id, daten.mit)
    return {"geteilt_mit": mit}


@router.get("/{kennung}/dateien/{name}")
def datei(kennung: str, name: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> FileResponse:
    besprechung = besprechung_finden(d, wer, kennung).besprechung
    # Nur Dateien, die zur Besprechung gehoeren -- nachgeschlagen, nie aus dem Namen gebaut.
    treffer = next((p for p in besprechung.dateien() if p.name == name), None)
    if treffer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diese Datei gehört nicht zu diesem Transkript.")
    return FileResponse(treffer, media_type=MEDIENTYPEN.get(treffer.suffix.lower(), "application/octet-stream"), filename=treffer.name)


@router.post("/{kennung}/export")
def exportieren(
    kennung: str, daten: modelle.ExportAnfrage, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    besprechung = besprechung_finden(d, wer, kennung, aendern=True).besprechung
    neuestes = besprechung.neuestes_protokoll
    if daten.inhalt != dokument_export_service.INHALT_TRANSKRIPT and neuestes is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Für diesen Inhalt fehlt das Protokoll.")
    zielordner = Path(str(d.steuerung.konfiguration().get("export_zielordner") or "")) if d.ist_desktop else None
    if zielordner is None or not str(zielordner) or str(zielordner) == ".":
        zielordner = besprechung.transkript.parent
    try:
        pfade = dokument_export_service.exportiere(
            daten.inhalt,
            daten.formate,
            zielordner,
            transkript_json=besprechung.transkript,
            protokoll_json=neuestes.json if neuestes else None,
        )
        fehler: list[str] = []
    except dokument_export_service.ExportTeilweise as teilweise:
        pfade, fehler = teilweise.geschrieben, teilweise.fehler
    except dokument_export_service.ExportFehler as problem:
        raise HTTPException(422, str(problem)) from problem
    return {"dateien": [{"name": p.name, "pfad": str(p)} for p in pfade], "fehler": fehler}
