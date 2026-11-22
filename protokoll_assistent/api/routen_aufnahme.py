"""Mikrofonaufnahme der Windows-Anwendung: Geraete, Start, Pause, Fortsetzen, Stopp. Pegel als Ereignis ``aufnahme``.

Im Browser (Servermodus) nimmt die Oberflaeche selbst auf und laedt hoch -- dort
gibt es diese Endpunkte nicht.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from protokoll_assistent.ablauf.aufnahme import AufnahmeFehler, Aufnahmesteuerung
from protokoll_assistent.api.kontext import Dienste, nur_desktop

router = APIRouter(prefix="/api/aufnahme", tags=["aufnahme"])


class AufnahmeStart(BaseModel):
    geraet: str | None = Field(default=None, max_length=300)


def _steuerung(d: Dienste) -> Aufnahmesteuerung:
    if d.aufnahme is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufnehmen gibt es hier nicht.")
    return d.aufnahme


def _fehler(fehler: AufnahmeFehler) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(fehler))


@router.get("")
def stand(d: Dienste = Depends(nur_desktop)) -> dict[str, Any]:
    return _steuerung(d).stand()


@router.get("/geraete")
def geraete(d: Dienste = Depends(nur_desktop)) -> list[dict[str, Any]]:
    try:
        return _steuerung(d).geraete()
    except AufnahmeFehler as fehler:
        raise _fehler(fehler) from fehler


@router.post("/start")
def starten(daten: AufnahmeStart, d: Dienste = Depends(nur_desktop)) -> dict[str, Any]:
    try:
        return _steuerung(d).starten(daten.geraet)
    except AufnahmeFehler as fehler:
        raise _fehler(fehler) from fehler


@router.post("/pause")
def pausieren(d: Dienste = Depends(nur_desktop)) -> dict[str, Any]:
    try:
        return _steuerung(d).pausieren()
    except AufnahmeFehler as fehler:
        raise _fehler(fehler) from fehler


@router.post("/fortsetzen")
def fortsetzen(d: Dienste = Depends(nur_desktop)) -> dict[str, Any]:
    try:
        return _steuerung(d).fortsetzen()
    except AufnahmeFehler as fehler:
        raise _fehler(fehler) from fehler


@router.post("/stopp")
def stoppen(d: Dienste = Depends(nur_desktop)) -> dict[str, Any]:
    """Beendet die Aufnahme; die WAV-Datei liegt danach im Aufnahmeordner (Antwort: Pfad, Name, Dauer)."""
    try:
        return _steuerung(d).stoppen()
    except AufnahmeFehler as fehler:
        raise _fehler(fehler) from fehler
