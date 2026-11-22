"""Aufnahmegeraete (VERMERK Raum): anlegen, entfernen, Stand. Das Token wird genau einmal gezeigt."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Dienste, automatik, dienste
from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.utils import app_config

router = APIRouter(prefix="/api/geraete", tags=["geraete"])


def konfigurationszeilen(basis_url: str, token: str) -> str:
    """Was in die ``server_config.h`` des Geraets gehoert (siehe ``firmware/``)."""
    return f'#define VERMERK_PC_BASE_URL  "{basis_url}"\n#define VERMERK_PC_TOKEN     "{token}"\n'


def basis_urls(port: int) -> list[str]:
    return [f"http://{adresse}:{port}" for adresse in geraete_empfang_service.lokale_adressen()]


@router.get("")
def stand(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    a = automatik(d)
    konfig = d.steuerung.konfiguration()
    kontakte = a.kontakte()
    port = int(konfig.get("geraete_empfang_port") or geraete_empfang_service.STANDARD_PORT)
    geraete = []
    for eintrag in konfig.get("geraete_empfang_geraete") or []:
        if not isinstance(eintrag, dict):
            continue
        name = str(eintrag.get("name", ""))
        kontakt = kontakte.get(name)
        erwartet = str(eintrag.get("geraete_id") or "")
        geraete.append(
            {
                "name": name,
                "angelegt": eintrag.get("angelegt", ""),
                "geraete_id": erwartet or None,
                "kontakt": None
                if kontakt is None
                else {
                    "zeit": kontakt.zeit,
                    "adresse": kontakt.adresse,
                    "geraete_id": kontakt.geraete_id,
                    "firmware": kontakt.firmware,
                    "andere_id": bool(kontakt.geraete_id and erwartet and kontakt.geraete_id != erwartet),
                },
            }
        )
    return {"empfang": a.beschreibung(), "geraete": geraete, "adressen": basis_urls(port), "freigaben": a.wartende_freigaben()}


@router.post("", status_code=201)
def anlegen(daten: modelle.GeraetAnlegen, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    a = automatik(d)
    name = daten.name.strip()
    if not geraete_empfang_service.geraetename_gueltig(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Erlaubt sind Buchstaben, Ziffern, „_“ und „-“, höchstens 32 Zeichen, ohne Leerzeichen.",
        )
    konfig = d.steuerung.konfiguration()
    geraete = [dict(e) for e in konfig.get("geraete_empfang_geraete") or [] if isinstance(e, dict)]
    if any(str(e.get("name", "")).lower() == name.lower() for e in geraete):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ein Gerät „{name}“ gibt es schon.")
    token = geraete_empfang_service.token_erzeugen()
    geraete.append({"name": name, "token_sha256": geraete_empfang_service.token_hash(token), "angelegt": dt.date.today().isoformat()})
    neu = app_config.update_config(geraete_empfang_geraete=geraete)
    a.anwenden(neu)
    port = int(neu.get("geraete_empfang_port") or geraete_empfang_service.STANDARD_PORT)
    urls = basis_urls(port)
    basis = urls[0] if urls else f"http://<Adresse dieses Rechners>:{port}"
    # Nur in dieser Antwort: gespeichert wird allein der Hash.
    return {"name": name, "token": token, "basis_url": basis, "konfiguration": konfigurationszeilen(basis, token)}


@router.delete("/{name}")
def entfernen(name: str, d: Dienste = Depends(dienste)) -> dict[str, bool]:
    a = automatik(d)
    konfig = d.steuerung.konfiguration()
    vorher = [dict(e) for e in konfig.get("geraete_empfang_geraete") or [] if isinstance(e, dict)]
    nachher = [e for e in vorher if str(e.get("name", "")).lower() != name.lower()]
    if len(nachher) == len(vorher):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dieses Gerät gibt es nicht.")
    a.anwenden(app_config.update_config(geraete_empfang_geraete=nachher))
    return {"entfernt": True}
