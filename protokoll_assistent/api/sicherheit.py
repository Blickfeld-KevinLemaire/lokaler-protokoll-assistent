"""Wer darf die Programmschnittstelle benutzen?

Regeln (Lehren aus einem aehnlichen Projekt, siehe ``ARCHITEKTUR.md``):

* Es gibt **keinen** Betrieb ohne Schluessel -- auch nicht "zum Entwickeln".
  Ein leerer Schluessel, der die Pruefung abschaltet, versteckt genau die
  Fehler, die erst beim Anwender auffallen.
* Geschuetzt wird ueber eine Abhaengigkeit am Router, nicht ueber eine
  Liste von Ausnahmen: Ein neuer Endpunkt ist von selbst geschuetzt.
* Schluessel werden in konstanter Zeit verglichen und nie protokolliert.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

from protokoll_assistent.ablauf.nutzer import Nutzerverwaltung

ROLLE_DESKTOP = "desktop"
ROLLE_SERVER = "server"
ROLLEN = (ROLLE_DESKTOP, ROLLE_SERVER)

UMGEBUNG_SCHLUESSEL = "VERMERK_API_SCHLUESSEL"
COOKIE_NAME = "vermerk_sitzung"
# Kopfzeile, die jede aendernde Anfrage mit Sitzungs-Cookie tragen muss: Ein fremdes Formular kann sie nicht
# setzen (Schutz gegen Cross-Site Request Forgery, zusaetzlich zu SameSite=Strict).
CSRF_KOPF = "x-vermerk-anfrage"
SITZUNG_SEKUNDEN = 12 * 3600
FEHLVERSUCHE_PRO_MINUTE = 10

SICHERE_METHODEN = frozenset({"GET", "HEAD", "OPTIONS"})


def schluessel_erzeugen() -> str:
    return secrets.token_urlsafe(32)


def schluessel_hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode("utf-8")).hexdigest()


ANMELDUNG_SCHLUESSEL = "schluessel"
ANMELDUNG_PASSWORT = "passwort"


@dataclass
class _Sitzung:
    name: str
    ablauf: float
    # Womit angemeldet wurde: mit einem Schluessel (``nachweis`` = sein SHA-256) oder mit dem Passwort (``nachweis``
    # = der damals gespeicherte Passwort-Hash; er aendert sich mit jedem neuen Passwort, auch wegen des Salzes).
    # ``wer()`` prueft bei jeder Anfrage nach, ob das noch gilt.
    art: str = ANMELDUNG_SCHLUESSEL
    nachweis: str = ""


@dataclass
class Zugang:
    """Die Zugangspruefung einer App-Instanz.

    ``start_schluessel``: der Schluessel dieses Starts (Rolle desktop).
    ``zugaenge``: Name -> SHA-256 eines Zugangsschluessels (Rolle server; liest bei jeder Anmeldung neu, damit
    neu angelegte oder entfernte Zugaenge sofort gelten).
    ``nutzer``: Nutzerverwaltung des Servermodus mit mehreren Nutzern (Passwort und persoenliche Schluessel).
    Ohne sie gibt es genau einen Menschen, und der darf alles."""

    rolle: str
    start_schluessel: str | None = None
    zugaenge: Callable[[], dict[str, str]] = dict
    nutzer: Nutzerverwaltung | None = None
    jetzt: Callable[[], float] = time.time
    _sitzungen: dict[str, _Sitzung] = field(default_factory=dict)
    _fehlversuche: dict[str, list[float]] = field(default_factory=dict)
    _sperre: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.rolle not in ROLLEN:
            raise ValueError(f"Unbekannte Rolle: {self.rolle}")
        if self.rolle == ROLLE_DESKTOP and not self.start_schluessel:
            raise ValueError("Die Rolle 'desktop' braucht einen Schluessel -- ohne geht es absichtlich nicht.")

    # ------------------------------------------------------------------
    def _bearer(self, request: Request) -> str | None:
        kopf = request.headers.get("authorization", "")
        art, _, wert = kopf.partition(" ")
        return wert.strip() if art.lower() == "bearer" and wert.strip() else None

    def _passender_zugang(self, schluessel: str) -> str | None:
        return self._zugang_zum_hash(schluessel_hash(schluessel))

    def _zugang_zum_hash(self, gesucht: str) -> str | None:
        """Name des Zugangs zum SHA-256 eines Schluessels oder ``None``."""
        if self.start_schluessel and hmac.compare_digest(gesucht, schluessel_hash(self.start_schluessel)):
            return "desktop"
        if self.nutzer is not None:
            gefunden = self.nutzer.zugang_hash_pruefen(gesucht)
            if gefunden is not None:
                return gefunden.name
        treffer = None
        for name, hashwert in self.zugaenge().items():
            # Alle vergleichen (konstante Zeit ueber die ganze Liste), nicht beim ersten Treffer aufhoeren.
            if hmac.compare_digest(gesucht, hashwert.lower()):
                treffer = name
        return treffer

    def wer(self, request: Request) -> str | None:
        """Name des Zugangs dieser Anfrage oder ``None``."""
        bearer = self._bearer(request)
        if bearer is not None:
            return self._passender_zugang(bearer)
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        with self._sperre:
            sitzung = self._sitzungen.get(token)
            if sitzung is None:
                return None
            if sitzung.ablauf < self.jetzt():
                del self._sitzungen[token]
                return None
            name = sitzung.name
        if not self._sitzung_gilt_noch(sitzung):
            self.abmelden(token)
            return None
        return name

    def _sitzung_gilt_noch(self, sitzung: _Sitzung) -> bool:
        """Gilt noch, womit die Sitzung angemeldet wurde? Ein entfernter oder gesperrter Nutzer, ein widerrufener
        Zugangsschluessel und ein neues Passwort beenden so auch die Browser-Sitzungen, die damit angelegt wurden
        (sonst liefen sie bis zu ``SITZUNG_SEKUNDEN`` weiter)."""
        if sitzung.art == ANMELDUNG_PASSWORT:
            gefunden = self.nutzer.hole(sitzung.name) if self.nutzer is not None else None
            if gefunden is None or not gefunden.aktiv or not gefunden.passwort:
                return False
            return hmac.compare_digest(gefunden.passwort.encode("utf-8"), sitzung.nachweis.encode("utf-8"))
        return self._zugang_zum_hash(sitzung.nachweis) == sitzung.name

    def sitzung_behalten(self, token: str | None, name: str) -> None:
        """Nach dem eigenen Passwortwechsel: Die Sitzung, mit der er geschah, bleibt bestehen (wer eben das bisherige
        Passwort genannt hat, ist es). Alle anderen mit dem alten Passwort angelegten enden bei ihrer naechsten
        Anfrage -- etwa die auf einem vergessenen Rechner."""
        if not token or self.nutzer is None:
            return
        gefunden = self.nutzer.hole(name)
        with self._sperre:
            sitzung = self._sitzungen.get(token)
            if (
                sitzung is not None
                and sitzung.art == ANMELDUNG_PASSWORT
                and sitzung.name.lower() == name.lower()
                and gefunden is not None
                and gefunden.passwort
            ):
                sitzung.nachweis = gefunden.passwort

    def ist_admin(self, name: str | None) -> bool:
        """Ohne Nutzerverwaltung (ein Rechner, ein Mensch) darf jeder Angemeldete alles. Mit ihr: Admins und
        der Notfallzugang aus der Umgebung (``VERMERK_ZUGANG``, fuer die Ersteinrichtung eines Containers)."""
        if name is None:
            return False
        if self.nutzer is None or name == "umgebung":
            return True
        gefunden = self.nutzer.hole(name)
        return gefunden is not None and gefunden.admin and gefunden.aktiv

    def pruefen(self, request: Request) -> str:
        name = self.wer(request)
        if name is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet.", headers={"WWW-Authenticate": "Bearer"})
        ueber_cookie = self._bearer(request) is None
        if ueber_cookie and request.method not in SICHERE_METHODEN and request.headers.get(CSRF_KOPF) != "1":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Anfrage ohne Kennzeichnung der Oberfläche abgelehnt.")
        return name

    # ------------------------------------------------------------------
    def zu_viele_fehlversuche(self, adresse: str) -> bool:
        grenze = self.jetzt() - 60
        with self._sperre:
            liste = [t for t in self._fehlversuche.get(adresse, []) if t > grenze]
            self._fehlversuche[adresse] = liste
            return len(liste) >= FEHLVERSUCHE_PRO_MINUTE

    def anmelden(self, schluessel: str, adresse: str) -> tuple[str, str] | None:
        """Gibt ``(Sitzungstoken, Name)`` zurueck oder ``None``. Merkt Fehlversuche je Adresse."""
        name = self._passender_zugang(schluessel) if schluessel else None
        if name is None:
            with self._sperre:
                self._fehlversuche.setdefault(adresse, []).append(self.jetzt())
            return None
        token = secrets.token_urlsafe(32)
        with self._sperre:
            self._sitzungen[token] = _Sitzung(
                name, self.jetzt() + SITZUNG_SEKUNDEN, ANMELDUNG_SCHLUESSEL, schluessel_hash(schluessel)
            )
        return token, name

    def anmelden_mit_passwort(self, name: str, passwort: str, adresse: str) -> tuple[str, str] | None:
        """Anmeldung mit Name und Passwort (nur mit Nutzerverwaltung). Merkt Fehlversuche je Adresse."""
        gefunden = self.nutzer.passwort_pruefen(name, passwort) if self.nutzer is not None and name else None
        if gefunden is None:
            with self._sperre:
                self._fehlversuche.setdefault(adresse, []).append(self.jetzt())
            return None
        token = secrets.token_urlsafe(32)
        with self._sperre:
            self._sitzungen[token] = _Sitzung(
                gefunden.name, self.jetzt() + SITZUNG_SEKUNDEN, ANMELDUNG_PASSWORT, gefunden.passwort or ""
            )
        return token, gefunden.name

    def abmelden(self, token: str | None) -> None:
        if token:
            with self._sperre:
                self._sitzungen.pop(token, None)


def zugaenge_aus_konfiguration(eintraege: Iterable[object], umgebung_schluessel: str | None = None) -> dict[str, str]:
    """``server_zugaenge`` aus der Konfiguration (``[{"name", "token_sha256"}]``) plus optional ein Schluessel
    aus der Umgebung (Container: ``VERMERK_ZUGANG``)."""
    zugaenge: dict[str, str] = {}
    for eintrag in eintraege:
        if isinstance(eintrag, dict):
            name = str(eintrag.get("name") or "").strip()
            hashwert = str(eintrag.get("token_sha256") or "").strip().lower()
            if name and len(hashwert) == 64:
                zugaenge[name] = hashwert
    if umgebung_schluessel:
        zugaenge.setdefault("umgebung", schluessel_hash(umgebung_schluessel))
    return zugaenge
