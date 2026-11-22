"""Aufnahmegeraet per USB-Kabel einrichten (nur Windows-Anwendung): WLAN, Adresse und Token in einem Zug.

Die Firmware kennt zwei Ziele: diesen PC (``pc_url``/``pc_token``) und
optional einen Server (``server_url``/``server_token``). Ein Geraet kann so
gleichzeitig fuer die Windows-Anwendung und fuer den Servermodus eingerichtet
sein. Der Ablauf entspricht dem frueheren Dialog (``gui/geraete_usb_einrichtung.py``):
erkennen, schreiben, Neustart abwarten, Einrichtung bestaetigen, Eintrag speichern.

Die Aufrufe sprechen mit der seriellen Schnittstelle und dauern Sekunden (beim
Einrichten bis ~30 s, weil das Geraet neu startet); sie laufen als gewoehnliche
Funktionen in einem Faden des Servers, nicht in der Ereignisschleife.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from protokoll_assistent.api.kontext import Angemeldet, Dienste, automatik, nur_admin, nur_desktop
from protokoll_assistent.api.routen_geraete import basis_urls
from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.services import geraete_usb_service as usb
from protokoll_assistent.utils import app_config

router = APIRouter(prefix="/api/geraete/usb", tags=["geraete"])

# In Tests ersetzbar: oeffnet die serielle Verbindung zu einem Anschluss.
oeffnen: Callable[[str], usb.SerielleVerbindung] = usb.verbindung_oeffnen


class UsbErkennen(BaseModel):
    port: str = Field(min_length=1, max_length=64)


class UsbEinrichten(BaseModel):
    port: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=32)
    wlan_ssid: str = Field(min_length=1, max_length=64)
    wlan_passwort: str = Field(default="", max_length=64)
    # Leer: die erste Adresse dieses Rechners im lokalen Netz mit dem Port des Empfangs.
    pc_url: str = Field(default="", max_length=200)
    server_url: str = Field(default="", max_length=200)
    server_token: str = Field(default="", max_length=128)
    erste_nummer: int | None = Field(default=None, ge=2, le=99999)


def _info_dict(info: usb.GeraeteInfo) -> dict[str, Any]:
    return {
        "geraete_id": info.geraete_id,
        "board": info.board,
        "firmware": info.firmware,
        "eingerichtet": info.eingerichtet,
        "wlan": info.wlan,
        "fuer_pc": info.token_pc,
        "fuer_server": info.token_server,
    }


@router.get("/anschluesse")
def anschluesse(_d: Dienste = Depends(nur_desktop), _a: Angemeldet = Depends(nur_admin)) -> list[dict[str, Any]]:
    try:
        return [{"port": a.port, "beschreibung": a.beschreibung, "vermerk": a.espressif} for a in usb.anschluesse_finden()]
    except usb.UsbFehler as fehler:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(fehler)) from fehler


@router.post("/erkennen")
def erkennen(daten: UsbErkennen, d: Dienste = Depends(nur_desktop), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    try:
        sitzung = usb.Geraetesitzung(oeffnen(daten.port))
        try:
            info = sitzung.info()
        finally:
            sitzung.schliessen()
    except usb.UsbFehler as fehler:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(fehler)) from fehler
    vorhandene = d.steuerung.konfiguration().get("geraete_empfang_geraete") or []
    bekannt = next((e for e in vorhandene if isinstance(e, dict) and e.get("geraete_id") == info.geraete_id), None)
    return {**_info_dict(info), "bekannt_als": bekannt.get("name") if bekannt else None}


@router.post("/einrichten")
def einrichten(daten: UsbEinrichten, d: Dienste = Depends(nur_desktop), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    a = automatik(d)
    name = daten.name.strip()
    if not geraete_empfang_service.geraetename_gueltig(name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name: Buchstaben, Ziffern, „_“ und „-“, höchstens 32 Zeichen.")
    konfig = d.steuerung.konfiguration()
    port_empfang = int(konfig.get("geraete_empfang_port") or geraete_empfang_service.STANDARD_PORT)
    pc_url = daten.pc_url.strip() or next(iter(basis_urls(port_empfang)), "")
    if not pc_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Die Adresse dieses Rechners im Netz ließ sich nicht ermitteln.")
    token = geraete_empfang_service.token_erzeugen()
    einrichtung = usb.Einrichtung(
        wlan_ssid=daten.wlan_ssid,
        wlan_passwort=daten.wlan_passwort,
        pc_url=pc_url,
        pc_token=token,
        server_url=daten.server_url.strip(),
        server_token=daten.server_token.strip(),
        erste_nummer=daten.erste_nummer,
    )
    meldungen = einrichtung.fehler()
    if meldungen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, " ".join(meldungen))
    try:
        sitzung = usb.Geraetesitzung(oeffnen(daten.port))
        try:
            vorher = sitzung.info()
            sitzung.einrichten(einrichtung)
        finally:
            sitzung.schliessen()
        neu = usb.nach_neustart_verbinden(daten.port, oeffnen)
        try:
            info = neu.info()
        finally:
            neu.schliessen()
    except usb.UsbFehler as fehler:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(fehler)) from fehler
    if not (info.eingerichtet and info.token_pc):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Das Gerät meldet nach dem Neustart keine Einrichtung.")

    vorhandene = [dict(e) for e in konfig.get("geraete_empfang_geraete") or [] if isinstance(e, dict)]
    doppelt = any(
        str(e.get("name", "")).lower() == name.lower() and e.get("geraete_id") not in (None, vorher.geraete_id)
        for e in vorhandene
    )
    if doppelt:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ein anderes Gerät heißt schon „{name}“.")
    # Ein schon bekanntes Geraet (gleiche Werks-Id oder gleicher Name) bekommt den neuen Eintrag samt neuem Token.
    heute = dt.date.today().isoformat()
    vorhandene = [
        e for e in vorhandene if e.get("geraete_id") != info.geraete_id and str(e.get("name", "")).lower() != name.lower()
    ]
    vorhandene.append(
        {
            "name": name,
            "token_sha256": geraete_empfang_service.token_hash(token),
            "angelegt": heute,
            "geraete_id": info.geraete_id,
            "board": info.board,
            "firmware": info.firmware,
        }
    )
    # Sofort speichern: Das Geraet traegt das neue Token schon.
    a.anwenden(app_config.update_config(geraete_empfang_geraete=vorhandene, geraete_empfang_aktiv=True))
    return {"name": name, "info": _info_dict(info), "pc_url": pc_url, "inventar": usb.inventarzeile(info, name, heute)}
