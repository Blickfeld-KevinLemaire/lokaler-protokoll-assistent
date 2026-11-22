"""Gesundheit, Anmeldung, Info, Zustand und der Ereignisstrom (Server-Sent Events)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from protokoll_assistent.ablauf.ereignisse import Ereignis
from protokoll_assistent.ablauf.verarbeitungswege import lokale_laufzeit_verfuegbar
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Dienste, dienste, nur_desktop
from protokoll_assistent.api.sicherheit import COOKIE_NAME, SITZUNG_SEKUNDEN
from protokoll_assistent.utils import diagnostics
from protokoll_assistent.version import VERSION

# Ohne Ereignis so oft ein Kommentar in den Strom: Proxys und der Browser halten die Verbindung sonst nicht offen.
HERZSCHLAG_SEKUNDEN = 15.0

oeffentlich = APIRouter(prefix="/api", tags=["system"])
geschuetzt = APIRouter(prefix="/api", tags=["system"])


@oeffentlich.get("/gesundheit")
def gesundheit() -> dict[str, str]:
    """Ohne Anmeldung: Laeuft der Dienst? Verraet nichts ausser der Version."""
    return {"status": "ok", "version": VERSION}


@oeffentlich.post("/anmelden")
def anmelden(daten: modelle.Anmeldung, request: Request, response: Response) -> dict[str, str]:
    d = dienste(request)
    adresse = request.client.host if request.client else "?"
    if d.zugang.zu_viele_fehlversuche(adresse):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Zu viele Fehlversuche. Bitte eine Minute warten.")
    ergebnis = d.zugang.anmelden(daten.schluessel, adresse)
    if ergebnis is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Der Zugangsschlüssel stimmt nicht.")
    token, name = ergebnis
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SITZUNG_SEKUNDEN,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"angemeldet_als": name}


@oeffentlich.post("/abmelden")
def abmelden(request: Request, response: Response) -> dict[str, bool]:
    dienste(request).zugang.abmelden(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"abgemeldet": True}


def _mikrofon_moeglich() -> bool:
    return importlib.util.find_spec("sounddevice") is not None


@geschuetzt.get("/info", response_model=modelle.Info)
def info(request: Request, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    konfig = d.steuerung.konfiguration()
    return {
        "version": VERSION,
        "rolle": d.rolle,
        "angemeldet_als": d.zugang.wer(request) or "",
        "faehigkeiten": {
            "lokale_transkription": d.steuerung.abh.laufzeit_verfuegbar(),
            "mikrofon": d.ist_desktop and _mikrofon_moeglich(),
            "dateipfade": d.ist_desktop,
            "ordner_oeffnen": d.ist_desktop and d.plattform_windows,
            "geraete_empfang": d.automatik is not None,
        },
        "einrichtung_abgeschlossen": bool(konfig.get("einrichtung_abgeschlossen")),
        "ausgabeordner": str(d.ausgabeordner()),
    }


@geschuetzt.get("/zustand", response_model=modelle.Zustand)
def zustand(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    """Vollstaendiger Stand mit der Nummer des letzten Ereignisses. Danach ``/ereignisse?seit=<nummer>``
    abonnieren: So geht zwischen Laden und Abo nichts verloren."""
    letzte = d.steuerung.bus.letzte_nummer
    return {
        "letzte_nummer": letzte,
        "auftraege": [a.als_dict() for a in d.steuerung.auftraege.liste()],
        "empfang": d.automatik.beschreibung() if d.automatik is not None else None,
        "freigaben": d.automatik.wartende_freigaben() if d.automatik is not None else [],
    }


def sse_zeile(ereignis: Ereignis) -> str:
    """Ein Ereignis im Format von Server-Sent Events -- immer ``str`` (ein ``dict`` im Strom fiele erst beim
    Senden auf, ausserhalb jeder Fehlerbehandlung, und der Client bekaeme eine leere Antwort)."""
    daten = json.dumps(ereignis.als_dict(), ensure_ascii=False, separators=(",", ":"))
    return f"id: {ereignis.nummer}\nevent: {ereignis.art}\ndata: {daten}\n\n"


@geschuetzt.get("/ereignisse")
async def ereignisse(
    request: Request,
    seit: int | None = None,
    last_event_id: str | None = Header(default=None),
    d: Dienste = Depends(dienste),
) -> StreamingResponse:
    """Strom aller Ereignisse ab ``seit`` (oder ``Last-Event-ID``). Der Client liest ihn mit ``fetch`` (die
    Kopfzeile ``Authorization`` laesst sich mit ``EventSource`` nicht setzen)."""
    if seit is None and last_event_id and last_event_id.isdigit():
        seit = int(last_event_id)
    schlange: asyncio.Queue[Ereignis] = asyncio.Queue()
    schleife = asyncio.get_running_loop()
    abo = d.steuerung.bus.abonnieren(lambda e: schleife.call_soon_threadsafe(schlange.put_nowait, e), seit=seit)

    async def strom() -> AsyncIterator[str]:
        try:
            yield ": verbunden\n\n"
            while not await request.is_disconnected():
                try:
                    ereignis = await asyncio.wait_for(schlange.get(), HERZSCHLAG_SEKUNDEN)
                except asyncio.TimeoutError:
                    yield ": herzschlag\n\n"
                    continue
                yield sse_zeile(ereignis)
        finally:
            abo.beenden()

    return StreamingResponse(
        strom(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@geschuetzt.get("/system/diagnose")
def diagnose(d: Dienste = Depends(dienste)) -> list[dict[str, Any]]:
    pruefungen = diagnostics.run_diagnostics(output_dir=d.ausgabeordner())
    return [
        {"id": p.key, "name": p.label, "ok": p.ok, "text": p.detail, "kritisch": p.critical} for p in pruefungen
    ]


@geschuetzt.post("/system/ordner-oeffnen")
def ordner_oeffnen(daten: modelle.OrdnerOeffnen, d: Dienste = Depends(nur_desktop)) -> dict[str, bool]:
    """Ordner oder Datei im Explorer zeigen -- nur in der Windows-Anwendung (nie fuer Zugriffe aus dem Netz)."""
    pfad = Path(daten.pfad)
    if not pfad.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Den Ordner gibt es nicht.")
    if not d.plattform_windows:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Nur unter Windows.")
    if pfad.is_file():  # pragma: no cover - nur Windows
        subprocess.Popen(["explorer", "/select,", str(pfad)])
    else:  # pragma: no cover - nur Windows
        os.startfile(str(pfad))  # type: ignore[attr-defined]  # noqa: S606
    return {"geoeffnet": True}


def _python_ist_eingefroren() -> bool:
    return bool(getattr(sys, "frozen", False))


@geschuetzt.get("/system/laufzeit")
def laufzeit(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    return {
        "lokale_transkription": lokale_laufzeit_verfuegbar(),
        "eingefroren": _python_ist_eingefroren(),
        "python": sys.version.split()[0],
    }
