"""Besprechungen: Liste, Einzelansicht, Protokoll bearbeiten, Sprecher umbenennen, Dateien, Export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from protokoll_assistent.ablauf import bibliothek
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Dienste, dienste
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
}


def _besprechung(d: Dienste, kennung: str) -> bibliothek.Besprechung:
    gefunden = bibliothek.finde(d.ausgabeordner(), kennung)
    if gefunden is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diese Besprechung gibt es nicht (mehr).")
    return gefunden


def _word_neu(besprechung: bibliothek.Besprechung) -> str | None:
    """Die automatische Word-Datei passend neu schreiben; scheitert das, bleibt der Rest gueltig."""
    neuestes = besprechung.neuestes_protokoll
    try:
        dokument_export_service.automatisches_word(besprechung.transkript, neuestes.json if neuestes else None)
    except dokument_export_service.ExportFehler as fehler:
        return str(fehler)
    return None


@router.get("/export/formate")
def formate() -> list[dict[str, Any]]:
    return [{"id": f.id, "name": f.name, "inhalte": list(f.inhalte)} for f in dokument_export_service.FORMATE]


@router.get("", response_model=list[modelle.Besprechung])
def liste(d: Dienste = Depends(dienste)) -> list[dict[str, Any]]:
    return [b.als_dict() for b in bibliothek.besprechungen(d.ausgabeordner())]


@router.get("/{kennung}", response_model=modelle.BesprechungDetails)
def details(kennung: str, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    return bibliothek.details(_besprechung(d, kennung))


@router.put("/{kennung}/protokoll")
def protokoll_speichern(kennung: str, daten: modelle.ProtokollSpeichern, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    besprechung = _besprechung(d, kennung)
    neuestes = besprechung.neuestes_protokoll
    if neuestes is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Zu dieser Besprechung gibt es noch kein Protokoll.")
    md = neuestes.md or neuestes.json.with_suffix(".md")
    try:
        export_service.update_protocol_exports(neuestes.json, md, daten.text)
    except (OSError, ValueError) as fehler:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Speichern fehlgeschlagen: {fehler}") from fehler
    return {"gespeichert": True, "word_hinweis": _word_neu(besprechung)}


@router.put("/{kennung}/sprecher")
def sprecher_umbenennen(kennung: str, daten: modelle.SprecherNamen, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    besprechung = _besprechung(d, kennung)
    namen = {k: v.strip() for k, v in daten.namen.items() if v.strip()}
    try:
        export_service.reexport_with_new_names(besprechung.transkript, namen)
    except OSError as fehler:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Neu schreiben fehlgeschlagen: {fehler}") from fehler
    return {"gespeichert": True, "word_hinweis": _word_neu(besprechung)}


@router.get("/{kennung}/dateien/{name}")
def datei(kennung: str, name: str, d: Dienste = Depends(dienste)) -> FileResponse:
    besprechung = _besprechung(d, kennung)
    # Nur Dateien, die zur Besprechung gehoeren -- nachgeschlagen, nie aus dem Namen gebaut.
    treffer = next((p for p in besprechung.dateien() if p.name == name), None)
    if treffer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diese Datei gehört nicht zur Besprechung.")
    return FileResponse(treffer, media_type=MEDIENTYPEN.get(treffer.suffix.lower(), "application/octet-stream"), filename=treffer.name)


@router.post("/{kennung}/export")
def exportieren(kennung: str, daten: modelle.ExportAnfrage, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    besprechung = _besprechung(d, kennung)
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
