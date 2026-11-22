"""Transkriptionen und Auswertungen starten, ansehen, abbrechen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from protokoll_assistent.ablauf.verarbeitungswege import Ablauffehler, AuswertungsWunsch, TranskriptionsWunsch
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Dienste, dienste

router = APIRouter(prefix="/api/auftraege", tags=["auftraege"])

FEHLER_ANTWORT: dict[int | str, dict[str, Any]] = {422: {"model": modelle.Fehler, "description": "Prüfung vor dem Start gescheitert"}}


def ablauffehler_antwort(fehler: Ablauffehler) -> JSONResponse:
    """Ein Ablauffehler ist kein Programmfehler: 422 mit Titel, Text und Code fuer die Oberflaeche."""
    return JSONResponse(status_code=422, content=fehler.als_dict())


@router.get("", response_model=list[modelle.Auftrag])
def liste(d: Dienste = Depends(dienste)) -> list[dict[str, Any]]:
    return [a.als_dict() for a in d.steuerung.auftraege.liste()]


@router.get("/{auftrag_id}", response_model=modelle.Auftrag)
def einer(auftrag_id: str, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    auftrag = d.steuerung.auftraege.hole(auftrag_id)
    if auftrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Auftrag gibt es nicht (mehr).")
    return auftrag.als_dict()


@router.post("/transkription", response_model=modelle.Auftrag, status_code=201, responses=FEHLER_ANTWORT)
def transkription(daten: modelle.TranskriptionAnfrage, d: Dienste = Depends(dienste)) -> Any:
    quelle = d.pfad_pruefen(daten.quelle)
    if daten.min_sprecher and daten.max_sprecher and daten.min_sprecher > daten.max_sprecher:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Die Mindestzahl der Sprecher ist größer als die Höchstzahl.")
    wunsch = TranskriptionsWunsch(
        quelle=quelle,
        ausgabe=d.ausgabeordner(),
        sprache=daten.sprache or None,
        min_sprecher=daten.min_sprecher,
        max_sprecher=daten.max_sprecher,
        sprechertrennung=daten.sprechertrennung,
        offline=daten.offline,
        fortsetzen=daten.fortsetzen,
        mit_auswertung=daten.mit_auswertung,
    )
    try:
        auftrag = d.steuerung.transkription_starten(wunsch, systemprompt=daten.systemprompt)
    except Ablauffehler as fehler:
        return ablauffehler_antwort(fehler)
    return JSONResponse(status_code=201, content=auftrag.als_dict())


@router.post("/auswertung", response_model=modelle.Auftrag, status_code=201, responses=FEHLER_ANTWORT)
def auswertung(daten: modelle.AuswertungAnfrage, d: Dienste = Depends(dienste)) -> Any:
    transkript = d.pfad_pruefen(daten.transkript)
    try:
        auftrag = d.steuerung.auswertung_starten(
            AuswertungsWunsch(transkript=Path(transkript), ausgabe=d.ausgabeordner(), systemprompt=daten.systemprompt)
        )
    except Ablauffehler as fehler:
        return ablauffehler_antwort(fehler)
    return JSONResponse(status_code=201, content=auftrag.als_dict())


@router.delete("/{auftrag_id}")
def abbrechen(auftrag_id: str, d: Dienste = Depends(dienste)) -> dict[str, bool]:
    if d.steuerung.auftraege.hole(auftrag_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Auftrag gibt es nicht (mehr).")
    return {"abgebrochen": d.steuerung.abbrechen(auftrag_id)}
