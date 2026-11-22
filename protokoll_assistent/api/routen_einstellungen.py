"""Einstellungen, API-Schluessel und Systemprompt-Vorlagen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, dienste, nur_admin
from protokoll_assistent.services import api_anbieter, secret_store
from protokoll_assistent.utils import app_config
from protokoll_assistent.utils.paths import get_system_prompt_file
from protokoll_assistent.utils.systemprompt_vorlagen import (
    alle_vorlagen,
    eigene_vorlagen,
    name_pruefen,
    vorlage_speichern,
)

router = APIRouter(prefix="/api/einstellungen", tags=["einstellungen"])

SCHLUESSEL_NAMEN = ("transkription", "nachbearbeitung", "chatbot")
# Nicht ueber diesen Weg aenderbar: eigene Endpunkte (Geraete, Zugaenge) oder nur intern.
GESCHUETZTE_FELDER = frozenset({"geraete_empfang_geraete", "server_zugaenge"})


def _oeffentliche_konfiguration(konfig: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in konfig.items() if k not in GESCHUETZTE_FELDER}


@router.get("")
def lesen(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    return _oeffentliche_konfiguration(d.steuerung.konfiguration())


@router.patch("")
def aendern(
    aenderungen: dict[str, Any] = Body(...), d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)
) -> dict[str, Any]:
    """Nur bekannte Felder; alles andere ist ein Fehler (statt still verworfen zu werden)."""
    unbekannt = sorted(set(aenderungen) - set(app_config.DEFAULTS))
    geschuetzt = sorted(set(aenderungen) & GESCHUETZTE_FELDER)
    if unbekannt or geschuetzt:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Nicht änderbare Einstellungen: {', '.join(unbekannt + geschuetzt)}"
        )
    if not d.ist_desktop and {"ausgabeordner", "eingabeordner", "export_zielordner"} & set(aenderungen):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ordner lassen sich nur am Rechner selbst ändern.")
    neu = app_config.update_config(**aenderungen)
    for aufruf in d.nach_einstellungen:
        aufruf(neu)
    d.steuerung.bus.senden("einstellungen", {"geaendert": sorted(aenderungen)})
    return _oeffentliche_konfiguration(neu)


@router.get("/anbieter")
def anbieter() -> list[dict[str, Any]]:
    """Bekannte API-Anbieter mit fertigen Adressen fuer Transkription, Nachbearbeitung und Chat."""
    return [
        {
            "id": a.id,
            "name": a.name,
            "standort": a.standort,
            "hinweis": a.hinweis,
            "schluessel_link": a.schluessel_link,
            "doku_link": a.doku_link,
            "hat_platzhalter": a.hat_platzhalter,
            "chat": {"url": a.chat_url(), "modell": a.chat_modell} if a.kann_chat else None,
            "embedding": {"url": a.embedding_url(), "modell": a.embedding_modell} if a.kann_embeddings else None,
            "transkription": {"url": a.transkription_url(), "modell": a.transkription_modell}
            if a.kann_transkription
            else None,
        }
        for a in api_anbieter.ANBIETER
    ]


@router.get("/schluessel")
def schluessel_stand(d: Dienste = Depends(dienste)) -> dict[str, bool]:
    """Nur ob ein Schluessel vorliegt -- der Wert verlaesst den Dienst nie."""
    return {name: d.steuerung.schluessel.vorhanden(name) for name in SCHLUESSEL_NAMEN}


@router.put("/schluessel/{name}")
def schluessel_setzen(
    name: str, daten: modelle.Schluesselsatz, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)
) -> dict[str, bool]:
    if name not in SCHLUESSEL_NAMEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekannter Schlüssel.")
    gemerkt = False
    if daten.merken and daten.wert:
        try:
            secret_store.save_api_key(name, daten.wert)
            gemerkt = True
        except secret_store.SecretStoreUnavailableError:
            gemerkt = False
    if not gemerkt:
        d.steuerung.schluessel.fuer_sitzung(name, daten.wert)
    return {"vorhanden": d.steuerung.schluessel.vorhanden(name), "gemerkt": gemerkt}


@router.delete("/schluessel/{name}")
def schluessel_loeschen(name: str, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    if name not in SCHLUESSEL_NAMEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekannter Schlüssel.")
    d.steuerung.schluessel.fuer_sitzung(name, "")
    try:
        secret_store.delete_api_key(name)
    except secret_store.SecretStoreUnavailableError:
        pass
    return {"vorhanden": d.steuerung.schluessel.vorhanden(name)}


@router.get("/vorlagen", response_model=list[modelle.Vorlage])
def vorlagen() -> list[dict[str, Any]]:
    eigene = eigene_vorlagen()
    return [{"name": name, "text": text, "eigene": name in eigene} for name, text in alle_vorlagen().items()]


@router.put("/vorlagen/{name}")
def vorlage_ablegen(name: str, daten: modelle.VorlageSpeichern, _a: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    try:
        name_pruefen(name)
        vorlage_speichern(name, daten.text)
    except ValueError as fehler:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(fehler)) from fehler
    return {"gespeichert": True}


@router.get("/systemprompt")
def systemprompt() -> dict[str, str]:
    try:
        return {"text": get_system_prompt_file().read_text(encoding="utf-8")}
    except OSError:
        return {"text": ""}


@router.put("/systemprompt")
def systemprompt_speichern(daten: modelle.VorlageSpeichern, _a: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    datei = get_system_prompt_file()
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(daten.text, encoding="utf-8")
    return {"gespeichert": True}
