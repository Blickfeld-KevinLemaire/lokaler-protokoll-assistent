"""Transkriptionen und Auswertungen starten, ansehen, abbrechen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from protokoll_assistent.ablauf.auftraege import Auftrag
from protokoll_assistent.ablauf.verarbeitungswege import Ablauffehler, AuswertungsWunsch, TranskriptionsWunsch
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste
from protokoll_assistent.api.sichtbarkeit import auftrag_fuer

router = APIRouter(prefix="/api/auftraege", tags=["auftraege"])

FEHLER_ANTWORT: dict[int | str, dict[str, Any]] = {422: {"model": modelle.Fehler, "description": "Prüfung vor dem Start gescheitert"}}


def ablauffehler_antwort(fehler: Ablauffehler) -> JSONResponse:
    """Ein Ablauffehler ist kein Programmfehler: 422 mit Titel, Text und Code fuer die Oberflaeche."""
    return JSONResponse(status_code=422, content=fehler.als_dict())


def _darf_aendern(d: Dienste, wer: Angemeldet, auftrag: Auftrag) -> bool:
    if not d.mehrbenutzer or wer.admin:
        return True
    return auftrag.besitzer is not None and wer.besitzer is not None and auftrag.besitzer.lower() == wer.besitzer.lower()


def _gestartet(d: Dienste, wer: Angemeldet, auftrag: Auftrag) -> JSONResponse:
    """201 mit dem Auftrag und seinem Platz in der Warteschlange (0 = laeuft sofort bzw. als Naechstes)."""
    daten = auftrag_fuer(d, wer, auftrag.als_dict())
    daten["platz"] = d.steuerung.auftraege.platz(auftrag.id)
    return JSONResponse(status_code=201, content=daten)


@router.get("", response_model=list[modelle.Auftrag])
def liste(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> list[dict[str, Any]]:
    return [auftrag_fuer(d, wer, a.als_dict()) for a in d.steuerung.auftraege.liste()]


@router.get("/{auftrag_id}", response_model=modelle.Auftrag)
def einer(auftrag_id: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    auftrag = d.steuerung.auftraege.hole(auftrag_id)
    if auftrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Auftrag gibt es nicht (mehr).")
    return auftrag_fuer(d, wer, auftrag.als_dict())


@router.post("/transkription", response_model=modelle.Auftrag, status_code=201, responses=FEHLER_ANTWORT)
def transkription(daten: modelle.TranskriptionAnfrage, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> Any:
    quelle = d.pfad_pruefen(daten.quelle, wer)
    if daten.min_sprecher and daten.max_sprecher and daten.min_sprecher > daten.max_sprecher:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Die Mindestzahl der Sprecher ist größer als die Höchstzahl.")
    wunsch = TranskriptionsWunsch(
        quelle=quelle,
        ausgabe=d.ausgabeordner(wer),
        sprache=daten.sprache or None,
        min_sprecher=daten.min_sprecher,
        max_sprecher=daten.max_sprecher,
        sprechertrennung=daten.sprechertrennung,
        offline=daten.offline,
        fortsetzen=daten.fortsetzen,
        mit_auswertung=daten.mit_auswertung,
    )
    try:
        auftrag = d.steuerung.transkription_starten(wunsch, systemprompt=daten.systemprompt, besitzer=wer.besitzer)
    except Ablauffehler as fehler:
        return ablauffehler_antwort(fehler)
    return _gestartet(d, wer, auftrag)


@router.post("/auswertung", response_model=modelle.Auftrag, status_code=201, responses=FEHLER_ANTWORT)
def auswertung(daten: modelle.AuswertungAnfrage, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> Any:
    transkript = d.pfad_pruefen(daten.transkript, wer)
    try:
        # Das Protokoll gehoert neben sein Transkript: Nur dort ordnet die Bibliothek es zu. Ergebnisse aus dem
        # Eingangsordner liegen je Aufnahme in einem Unterordner -- im Ausgabeordner selbst bliebe ein neues
        # Protokoll unsichtbar.
        auftrag = d.steuerung.auswertung_starten(
            AuswertungsWunsch(transkript=Path(transkript), ausgabe=Path(transkript).parent, systemprompt=daten.systemprompt),
            besitzer=wer.besitzer,
        )
    except Ablauffehler as fehler:
        return ablauffehler_antwort(fehler)
    return _gestartet(d, wer, auftrag)


@router.delete("/{auftrag_id}")
def abbrechen(auftrag_id: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, bool]:
    auftrag = d.steuerung.auftraege.hole(auftrag_id)
    if auftrag is None or not _darf_aendern(d, wer, auftrag):
        # Fremde Auftraege gibt es fuer andere Nutzer zum Abbrechen schlicht nicht.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Auftrag gibt es nicht (mehr).")
    return {"abgebrochen": d.steuerung.abbrechen(auftrag_id)}
