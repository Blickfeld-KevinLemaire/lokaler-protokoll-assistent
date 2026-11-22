"""Frag mein Meeting: Fragen an Transkripte und Protokolle, Antwort Wort fuer Wort als Strom."""

from __future__ import annotations

import asyncio
import json
import logging as _logging
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste
from protokoll_assistent.api.routen_besprechungen import unterlagen_fuer
from protokoll_assistent.services import api_chat_service, chat_service, chat_verlauf_service, ollama_service
from protokoll_assistent.utils.paths import get_chatverlaeufe_dir, get_work_dir

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = _logging.getLogger(__name__)
_ENDE = object()


def chat_einstellungen(d: Dienste) -> chat_service.ChatEinstellungen:
    konfig = d.steuerung.konfiguration()
    if konfig.get("chatbot_modus") == "api":
        schluessel = d.steuerung.schluessel.hole(d.steuerung.schluessel.name_fuer_chat(konfig)) or ""
        return chat_service.ChatEinstellungen(
            "api",
            str(konfig.get("chatbot_api_modell") or ""),
            str(konfig.get("chatbot_api_embedding_modell") or ""),
            str(konfig.get("chatbot_api_endpunkt") or ""),
            str(konfig.get("chatbot_api_embedding_endpunkt") or ""),
            schluessel,
            kontext=str(konfig.get("chatbot_kontext") or chat_service.KONTEXT_AUSZUEGE),
        )
    return chat_service.ChatEinstellungen(
        "lokal",
        str(konfig.get("chatbot_ollama_modell") or ollama_service.DEFAULT_MODEL),
        str(konfig.get("chatbot_embedding_modell") or ""),
        kontext=str(konfig.get("chatbot_kontext") or chat_service.KONTEXT_AUSZUEGE),
    )


def verlaeufe_ordner(wer: Angemeldet) -> Path:
    """Chatverlaeufe: in der Windows-Anwendung wie bisher, im Servermodus je Nutzer."""
    basis = get_chatverlaeufe_dir()
    return basis / "nutzer" / wer.besitzer if wer.besitzer else basis


def _sse(art: str, daten: dict[str, Any]) -> str:
    return f"event: {art}\ndata: {json.dumps(daten, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post("")
async def fragen(
    daten: modelle.ChatAnfrage, request: Request, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> StreamingResponse:
    """Antwortet als Server-Sent Events: ``status``, ``token`` (Stueck fuer Stueck), dann ``fertig`` mit Antwort,
    Quellen und Verlaufskennung -- oder ``fehler``."""
    ordner = verlaeufe_ordner(wer)
    verlauf = chat_verlauf_service.lade(ordner, daten.verlauf_id) if daten.verlauf_id else None
    if daten.verlauf_id and verlauf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Chat gibt es nicht (mehr).")
    pfade = await asyncio.to_thread(unterlagen_fuer, d, wer, daten.besprechungen)
    einstellungen = chat_einstellungen(d)
    schlange: asyncio.Queue[Any] = asyncio.Queue()
    schleife = asyncio.get_running_loop()

    def senden(art: str, inhalt: dict[str, Any]) -> None:
        schleife.call_soon_threadsafe(schlange.put_nowait, _sse(art, inhalt))

    def arbeiten() -> None:
        nonlocal verlauf
        try:
            if not pfade:
                raise chat_service.ChatFehler("Es gibt noch keine Transkripte oder Protokolle, nach denen sich fragen ließe.")
            dokumente = [chat_service.lade_dokument(p) for p in pfade]
            embed_fn, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
            bisher = [{"role": n["role"], "content": n["content"]} for n in (verlauf.nachrichten if verlauf else [])]
            antwort, quellen = chat_service.beantworte(
                daten.frage,
                dokumente,
                bisher,
                embed_fn,
                chat_fn,
                get_work_dir() / "chat_vektoren",
                einstellungen.modell_kennung,
                einstellungen.chat_modell,
                on_status=lambda text: senden("status", {"text": text}),
                on_token=lambda stueck: senden("token", {"text": stueck}),
                kontext=einstellungen.kontext,
            )
            if verlauf is None:
                verlauf = chat_verlauf_service.neuer_verlauf(ordner, daten.frage)
            verlauf.nachrichten = [
                *verlauf.nachrichten,
                {"role": "user", "content": daten.frage, "quellen": []},
                {"role": "assistant", "content": antwort, "quellen": quellen},
            ]
            verlauf.dokumente = [str(p) for p in pfade]
            chat_verlauf_service.speichern(ordner, verlauf)
            senden("fertig", {"antwort": antwort, "quellen": quellen, "verlauf_id": verlauf.id})
        except (chat_service.ChatFehler, ollama_service.OllamaError, api_chat_service.ApiChatError) as fehler:
            senden("fehler", {"text": str(fehler)})
        except Exception as fehler:  # keine Tracebacks in die Oberflaeche, aber ins Protokoll
            logger.exception("Unerwarteter Fehler im Chat")
            senden("fehler", {"text": f"Unerwarteter Fehler: {fehler}"})
        finally:
            schleife.call_soon_threadsafe(schlange.put_nowait, _ENDE)

    threading.Thread(target=arbeiten, name="chat", daemon=True).start()

    async def strom() -> AsyncIterator[str]:
        while True:
            stueck = await schlange.get()
            if stueck is _ENDE:
                return
            yield stueck

    return StreamingResponse(strom(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/verlaeufe")
def verlaeufe(wer: Angemeldet = Depends(angemeldet)) -> list[dict[str, Any]]:
    return [
        {"id": v.id, "titel": v.titel, "erstellt": v.erstellt, "aktualisiert": v.aktualisiert, "fragen": len(v.nachrichten) // 2}
        for v in chat_verlauf_service.lade_alle(verlaeufe_ordner(wer))
    ]


@router.get("/verlaeufe/{kennung}")
def verlauf_lesen(kennung: str, wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    verlauf = chat_verlauf_service.lade(verlaeufe_ordner(wer), kennung)
    if verlauf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Chat gibt es nicht (mehr).")
    return {"id": verlauf.id, "titel": verlauf.titel, "nachrichten": verlauf.nachrichten, "dokumente": verlauf.dokumente}


@router.delete("/verlaeufe/{kennung}")
def verlauf_loeschen(kennung: str, wer: Angemeldet = Depends(angemeldet)) -> dict[str, bool]:
    return {"geloescht": chat_verlauf_service.loesche(verlaeufe_ordner(wer), kennung)}
