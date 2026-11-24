"""Gesundheit, Anmeldung, Info, Zustand und der Ereignisstrom (Server-Sent Events)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from protokoll_assistent.ablauf.auftraege import ERLEDIGT
from protokoll_assistent.ablauf.ereignisse import Ereignis
from protokoll_assistent.ablauf.verarbeitungswege import lokale_laufzeit_verfuegbar
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste, nur_admin, nur_desktop
from protokoll_assistent.api.sicherheit import COOKIE_NAME, SITZUNG_SEKUNDEN
from protokoll_assistent.api.sichtbarkeit import auftrag_fuer, ereignis_fuer
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


@oeffentlich.get("/anmeldung")
def anmeldung(request: Request) -> dict[str, bool]:
    """Ohne Anmeldung: Welche Arten der Anmeldung gibt es hier? (Name + Passwort nur mit mehreren Nutzern.)"""
    return {"mehrbenutzer": dienste(request).mehrbenutzer}


@oeffentlich.post("/anmelden")
def anmelden(daten: modelle.Anmeldung, request: Request, response: Response) -> dict[str, str]:
    d = dienste(request)
    adresse = request.client.host if request.client else "?"
    if d.zugang.zu_viele_fehlversuche(adresse):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Zu viele Fehlversuche. Bitte eine Minute warten.")
    if daten.name:
        ergebnis = d.zugang.anmelden_mit_passwort(daten.name, daten.passwort or "", adresse)
        fehltext = "Name oder Passwort stimmen nicht."
    else:
        ergebnis = d.zugang.anmelden(daten.schluessel or "", adresse)
        fehltext = "Der Zugangsschlüssel stimmt nicht."
    if ergebnis is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, fehltext)
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
def info(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    konfig = d.steuerung.konfiguration()
    eintrag = d.nutzer.hole(wer.name) if d.nutzer is not None else None
    return {
        "version": VERSION,
        "rolle": d.rolle,
        "angemeldet_als": wer.name,
        "anzeigename": eintrag.anzeigename if eintrag is not None else wer.name,
        "admin": wer.admin,
        "mehrbenutzer": d.mehrbenutzer,
        "faehigkeiten": {
            "lokale_transkription": d.steuerung.abh.laufzeit_verfuegbar(),
            "mikrofon": d.ist_desktop and d.aufnahme is not None and _mikrofon_moeglich(),
            "dateipfade": d.ist_desktop,
            "ordner_oeffnen": d.ist_desktop and d.plattform_windows,
            "geraete_empfang": d.automatik is not None,
            "firewall_freigabe": d.ist_desktop and d.plattform_windows and d.automatik is not None,
        },
        "einrichtung_abgeschlossen": bool(konfig.get("einrichtung_abgeschlossen")),
        "ausgabeordner": str(d.ausgabeordner(wer)),
    }


@geschuetzt.get("/zustand", response_model=modelle.Zustand)
def zustand(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    """Vollstaendiger Stand mit der Nummer des letzten Ereignisses. Danach ``/ereignisse?seit=<nummer>``
    abonnieren: So geht zwischen Laden und Abo nichts verloren."""
    letzte = d.steuerung.bus.letzte_nummer
    return {
        "letzte_nummer": letzte,
        # Uhrzeit des Dienstes: Die Oberflaeche rechnet Restzeiten damit, nicht mit ihrer eigenen Uhr.
        "jetzt": time.time(),
        "auftraege": [auftrag_fuer(d, wer, a.als_dict()) for a in d.steuerung.auftraege.liste()],
        "empfang": d.automatik.beschreibung() if d.automatik is not None and (wer.admin or not d.mehrbenutzer) else None,
        "aufnahme": d.aufnahme.stand() if d.aufnahme is not None else None,
        "freigaben": [
            f
            for f in (d.automatik.wartende_freigaben() if d.automatik is not None else [])
            if not d.mehrbenutzer or wer.admin or d.automatik.besitzer_von(f["geraet"]) == wer.besitzer  # type: ignore[union-attr]
        ],
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
    wer: Angemeldet = Depends(angemeldet),
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
                sichtbar = ereignis_fuer(d, wer, ereignis.art, ereignis.daten)
                if sichtbar is not None:
                    yield sse_zeile(ereignis if sichtbar is ereignis.daten else Ereignis(ereignis.nummer, ereignis.art, sichtbar, ereignis.zeit))
        finally:
            abo.beenden()

    return StreamingResponse(
        strom(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@geschuetzt.get("/system/diagnose")
def diagnose(d: Dienste = Depends(dienste), _admin: Angemeldet = Depends(nur_admin)) -> list[dict[str, Any]]:
    pruefungen = diagnostics.run_diagnostics(output_dir=d.ausgabe_basis())
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


@geschuetzt.post("/system/neustart")
def neustart(d: Dienste = Depends(nur_desktop), _a: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    """Den Dienst neu starten (z. B. nach der Ersteinrichtung, damit die Rechenumgebung geladen wird). Der Dienst
    beendet sich mit einem eigenen Exit-Code, und das Fenster startet ihn sofort wieder -- die Prozesse steuert
    allein das Fenster.

    Solange etwas laeuft oder wartet (Verarbeitung, auch von einem Aufnahmegeraet, oder eine Aufnahme), lehnt der
    Dienst mit 409 ab: Der Neustart braeche es ab, wartende Auftraege gingen verloren."""
    if d.neustart_anfordern is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Neu starten ist hier nicht möglich.")
    offen = [a for a in d.steuerung.auftraege.liste() if a.status not in ERLEDIGT]
    if offen:
        anzahl = "Ein Auftrag läuft" if len(offen) == 1 else f"{len(offen)} Aufträge laufen"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{anzahl} noch oder warten. Neu starten geht, sobald alles fertig ist – sonst würde es abgebrochen.",
        )
    if d.aufnahme is not None and d.aufnahme.stand().get("laeuft"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Gerade läuft eine Aufnahme. Bitte erst die Aufnahme beenden, dann neu starten."
        )
    d.neustart_anfordern()
    return {"neustart": True}


def _python_ist_eingefroren() -> bool:
    return bool(getattr(sys, "frozen", False))


@geschuetzt.get("/system/laufzeit")
def laufzeit(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    return {
        "lokale_transkription": lokale_laufzeit_verfuegbar(),
        "eingefroren": _python_ist_eingefroren(),
        "python": sys.version.split()[0],
    }
