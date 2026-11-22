"""Ollama: installierte und empfohlene Modelle, Modell herunterladen (als Auftrag mit Fortschritt)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from protokoll_assistent.ablauf.auftraege import Fortschritt
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, dienste, nur_admin
from protokoll_assistent.services import ollama_service

router = APIRouter(prefix="/api/ollama", tags=["ollama"])


def _option(o: ollama_service.OllamaModellOption) -> dict[str, Any]:
    return {"id": o.id, "label": o.label, "groesse_gb": o.groesse_gb, "hinweis": o.hinweis}


@router.get("/modelle")
def modelle_stand() -> dict[str, Any]:
    laeuft = ollama_service.is_service_running(timeout=2)
    try:
        installiert = ollama_service.list_models(timeout=3) if laeuft else []
    except ollama_service.OllamaError:
        installiert = []
    return {
        "laeuft": laeuft,
        "installiert": installiert,
        "empfohlen": [_option(o) for o in ollama_service.OLLAMA_MODELLE],
        "einbettung": [_option(o) for o in ollama_service.OLLAMA_EMBEDDING_MODELLE],
    }


@router.post("/laden", status_code=201)
def laden(daten: modelle.ModellLaden, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    """Laedt ein Modell herunter. Laeuft als Auftrag mit niedrigem Vorrang -- eine Verarbeitung geht vor."""
    name = daten.modell.strip()

    def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
        def melden(status_text: str, fertig: Any, gesamt: Any) -> None:
            fortschritt.stufe("laden", status_text)
            if gesamt:
                fortschritt.gesamt(float(fertig or 0) / float(gesamt))

        ollama_service.pull_model(name, progress_cb=melden)
        return {"modell": name}

    auftrag = d.steuerung.auftraege.einreihen("modell_laden", name, ausfuehren, vorrang=-5, angaben={"modell": name})
    return auftrag.als_dict()
