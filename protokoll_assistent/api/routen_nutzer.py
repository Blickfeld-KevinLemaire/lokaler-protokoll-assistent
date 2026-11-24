"""Nutzerverwaltung (Servermodus): Admins legen Nutzer an; jeder verwaltet sein Passwort und seine Schluessel.

Ein neuer Zugangsschluessel wird genau einmal im Klartext zurueckgegeben.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from protokoll_assistent.ablauf.nutzer import NutzerFehler, Nutzerverwaltung, passwort_passt
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste, nur_admin
from protokoll_assistent.api.sicherheit import COOKIE_NAME
from protokoll_assistent.utils import app_config

router = APIRouter(prefix="/api", tags=["nutzer"])


def _verwaltung(d: Dienste) -> Nutzerverwaltung:
    if d.nutzer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nutzer gibt es nur auf dem Server mit mehreren Nutzern.")
    return d.nutzer


def _fehler(fehler: NutzerFehler) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(fehler))


# ---------------------------------------------------------------- selbst
@router.get("/ich")
def ich(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    eintrag = d.nutzer.hole(wer.name) if d.nutzer is not None else None
    if eintrag is None:
        return {"name": wer.name, "anzeigename": wer.name, "admin": wer.admin, "hat_passwort": False, "zugaenge": []}
    return eintrag.oeffentlich()


@router.put("/ich/passwort")
def eigenes_passwort(
    daten: modelle.PasswortAendern, request: Request, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, bool]:
    # Andere mit dem alten Passwort angelegte Sitzungen enden; die, mit der das Passwort geaendert wurde, bleibt.
    verwaltung = _verwaltung(d)
    eintrag = verwaltung.hole(wer.name)
    if eintrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Nutzer gibt es nicht.")
    if eintrag.passwort and not passwort_passt(daten.bisher, eintrag.passwort):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Das bisherige Passwort stimmt nicht.")
    try:
        verwaltung.passwort_setzen(wer.name, daten.neu)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    d.zugang.sitzung_behalten(request.cookies.get(COOKIE_NAME), wer.name)
    return {"gespeichert": True}


@router.post("/ich/zugaenge", status_code=201)
def eigener_zugang(daten: modelle.ZugangAnlegen, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, str]:
    try:
        schluessel = _verwaltung(d).zugang_anlegen(wer.name, daten.bezeichnung)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    return {"bezeichnung": daten.bezeichnung.strip(), "schluessel": schluessel}


@router.delete("/ich/zugaenge/{bezeichnung}")
def eigenen_zugang_entfernen(bezeichnung: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, bool]:
    verwaltung = _verwaltung(d)
    eintrag = verwaltung.hole(wer.name)
    if (
        eintrag is not None
        and not eintrag.passwort
        and [z.get("bezeichnung") for z in eintrag.zugaenge] == [bezeichnung]
    ):
        # Sonst sperrte man sich selbst aus (beim einzigen Admin bliebe nur noch der Notfallzugang).
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Das ist Ihr einziger Zugang. Bitte zuerst ein Passwort setzen oder einen weiteren Schlüssel anlegen.",
        )
    try:
        verwaltung.zugang_entfernen(wer.name, bezeichnung)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    return {"entfernt": True}


# ---------------------------------------------------------------- Admin
@router.get("/nutzer")
def liste(d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> list[dict[str, Any]]:
    return [n.oeffentlich() for n in _verwaltung(d).liste()]


@router.get("/nutzer/namen")
def namen(d: Dienste = Depends(dienste), _w: Angemeldet = Depends(angemeldet)) -> list[dict[str, str]]:
    """Fuer das Teilen: wer ist da (nur Name und Anzeigename, aktive Nutzer)."""
    return [{"name": n.name, "anzeigename": n.anzeigename or n.name} for n in _verwaltung(d).liste() if n.aktiv]


@router.post("/nutzer", status_code=201)
def anlegen(daten: modelle.NutzerAnlegen, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    try:
        neu = _verwaltung(d).anlegen(daten.name, anzeigename=daten.anzeigename, admin=daten.admin, passwort=daten.passwort or None)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    return neu.oeffentlich()


@router.patch("/nutzer/{name}")
def aendern(
    name: str, daten: modelle.NutzerAendern, request: Request, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(nur_admin)
) -> dict[str, Any]:
    verwaltung = _verwaltung(d)
    try:
        if daten.passwort is not None:
            verwaltung.passwort_setzen(name, daten.passwort or None)
        geaendert = verwaltung.aendern(name, anzeigename=daten.anzeigename, admin=daten.admin, aktiv=daten.aktiv)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    if daten.passwort and name.lower() == wer.name.lower():
        # Das eigene Passwort ueber die Nutzerliste: wie unter "Konto" bleibt diese Sitzung, andere enden.
        d.zugang.sitzung_behalten(request.cookies.get(COOKIE_NAME), wer.name)
    return geaendert.oeffentlich()


@router.delete("/nutzer/{name}")
def entfernen(name: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    if name.lower() == wer.name.lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Den eigenen Zugang kann man nicht selbst entfernen.")
    try:
        _verwaltung(d).entfernen(name)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    _geraete_freigeben(d, name)
    return {"entfernt": True}


def _geraete_freigeben(d: Dienste, name: str) -> None:
    """Geraete des entfernten Nutzers werden "Allgemein" (sichtbar fuer Admins). Sonst landeten ihre Aufnahmen
    weiter im Ordner eines Nutzers, den es nicht mehr gibt -- und niemand saehe sie."""
    eintraege = [dict(e) for e in d.steuerung.konfiguration().get("geraete_empfang_geraete") or [] if isinstance(e, dict)]
    betroffen = [e for e in eintraege if str(e.get("besitzer") or "").lower() == name.lower()]
    for eintrag in betroffen:
        eintrag.pop("besitzer", None)
    if betroffen:
        app_config.update_config(geraete_empfang_geraete=eintraege)


@router.post("/nutzer/{name}/zugaenge", status_code=201)
def zugang_fuer(name: str, daten: modelle.ZugangAnlegen, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, str]:
    try:
        schluessel = _verwaltung(d).zugang_anlegen(name, daten.bezeichnung)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    return {"bezeichnung": daten.bezeichnung.strip(), "schluessel": schluessel}


@router.delete("/nutzer/{name}/zugaenge/{bezeichnung}")
def zugang_entfernen(name: str, bezeichnung: str, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, bool]:
    try:
        _verwaltung(d).zugang_entfernen(name, bezeichnung)
    except NutzerFehler as fehler:
        raise _fehler(fehler) from fehler
    return {"entfernt": True}
