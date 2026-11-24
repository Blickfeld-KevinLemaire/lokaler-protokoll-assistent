"""Nutzer des Servermodus: Anmeldename, Anzeigename, Admin, Passwort und persoenliche Zugangsschluessel.

Beides ist moeglich und frei kombinierbar -- je nachdem, was in der jeweiligen
Firma einfacher ist: Anmeldung mit Name und Passwort im Browser, oder ein
persoenlicher Zugangsschluessel (auch fuer Skripte). Gespeichert werden nur
Hashes: Passwoerter mit scrypt (Salz je Passwort), Zugangsschluessel als
SHA-256 (sie sind lang und zufaellig, ein langsamer Hash bringt dort nichts).

Die Windows-Anwendung kennt keine Nutzer (ein Rechner, ein Mensch); dieses
Modul wird nur im Servermodus benutzt.

Der Anmeldename ist zugleich der Name des persoenlichen Ordners und bleibt
deshalb unveraenderlich.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.freigaben import ALLE
from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

# Nur mit ``fullmatch`` pruefen: ``match`` liesse wegen "$" einen abschliessenden Zeilenumbruch durch ("anna\n").
NAME_MUSTER = re.compile(r"[A-Za-z0-9_-]{1,32}")
# Namen mit fester Bedeutung (gleich in welcher Schreibweise): "umgebung" ist der Notfallzugang aus VERMERK_ZUGANG
# (Admin, ohne eigenen Ordner), "desktop" der Schluessel des Fensters, "alle" die Freigabe fuer alle.
RESERVIERTE_NAMEN = frozenset({"umgebung", "desktop", ALLE})
MIN_PASSWORT = 10
# scrypt: ~16 MB Speicher je Pruefung -- teuer fuer Angreifer, unmerklich bei einer Anmeldung.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LAENGE = 2**14, 8, 1, 32


class NutzerFehler(ValueError):
    pass


def schluessel_hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode("utf-8")).hexdigest()


def passwort_hash(passwort: str, salz: bytes | None = None) -> str:
    salz = salz or secrets.token_bytes(16)
    wert = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LAENGE)
    b64 = base64.b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salz).decode()}${b64(wert).decode()}"


def passwort_passt(passwort: str, gespeichert: str) -> bool:
    try:
        art, n, r, p, salz_b64, wert_b64 = gespeichert.split("$")
        if art != "scrypt":
            return False
        salz, wert = base64.b64decode(salz_b64), base64.b64decode(wert_b64)
        probe = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=int(n), r=int(r), p=int(p), dklen=len(wert))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(probe, wert)


# Fuer unbekannte Namen wird trotzdem ein Hash geprueft: Sonst verriete die Antwortzeit, welche Namen es gibt.
_ATTRAPPE = passwort_hash("attrappe-ohne-bedeutung")


@dataclass
class Nutzer:
    name: str
    anzeigename: str = ""
    admin: bool = False
    aktiv: bool = True
    passwort: str | None = None
    zugaenge: list[dict[str, str]] = field(default_factory=list)
    angelegt: str = ""

    def oeffentlich(self) -> dict[str, Any]:
        """Ohne Hashes -- so geht ein Nutzer an die Oberflaeche."""
        return {
            "name": self.name,
            "anzeigename": self.anzeigename or self.name,
            "admin": self.admin,
            "aktiv": self.aktiv,
            "hat_passwort": bool(self.passwort),
            "zugaenge": [{"bezeichnung": z.get("bezeichnung", ""), "angelegt": z.get("angelegt", "")} for z in self.zugaenge],
            "angelegt": self.angelegt,
        }


class Nutzerverwaltung:
    def __init__(self, datei: Path, *, vergebene_namen: Callable[[], Iterable[str]] = tuple):
        """``vergebene_namen``: Namen, die schon anderweitig fuer eine Anmeldung stehen (``server_zugaenge``). Ein
        Nutzer gleichen Namens bekaeme sonst die Rechte und den Ordner dessen, der diesen Zugangsschluessel hat."""
        self.datei = datei
        self._vergebene_namen = vergebene_namen
        self._sperre = threading.RLock()

    # ------------------------------------------------------------------
    def _lesen(self) -> dict[str, Nutzer]:
        try:
            roh = json.loads(self.datei.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as fehler:
            raise NutzerFehler(f"Die Nutzerliste ist nicht lesbar: {fehler}") from fehler
        nutzer: dict[str, Nutzer] = {}
        for eintrag in roh.get("nutzer", []) if isinstance(roh, dict) else []:
            if isinstance(eintrag, dict) and NAME_MUSTER.fullmatch(str(eintrag.get("name", ""))):
                bekannt = {k: v for k, v in eintrag.items() if k in Nutzer.__dataclass_fields__}
                nutzer[str(eintrag["name"]).lower()] = Nutzer(**bekannt)
        return nutzer

    def _schreiben(self, nutzer: dict[str, Nutzer]) -> None:
        self.datei.parent.mkdir(parents=True, exist_ok=True)
        temp = self.datei.with_name(self.datei.name + ".tmp")
        inhalt = {"version": 1, "nutzer": [asdict(n) for n in sorted(nutzer.values(), key=lambda n: n.name.lower())]}
        temp.write_text(json.dumps(inhalt, ensure_ascii=False, indent=2), encoding="utf-8")
        _ersetzen_mit_wiederholung(temp, self.datei)

    # ------------------------------------------------------------------
    def liste(self) -> list[Nutzer]:
        with self._sperre:
            return sorted(self._lesen().values(), key=lambda n: n.name.lower())

    def hole(self, name: str) -> Nutzer | None:
        with self._sperre:
            return self._lesen().get(name.lower())

    def leer(self) -> bool:
        return not self.liste()

    def anlegen(self, name: str, *, anzeigename: str = "", admin: bool = False, passwort: str | None = None) -> Nutzer:
        if not NAME_MUSTER.fullmatch(name):
            raise NutzerFehler("Anmeldename: Buchstaben, Ziffern, _ und -, höchstens 32 Zeichen.")
        if name.lower() in RESERVIERTE_NAMEN:
            raise NutzerFehler(f"Den Namen „{name}“ verwendet das Programm selbst. Bitte einen anderen wählen.")
        if name.lower() in {str(n).lower() for n in self._vergebene_namen()}:
            raise NutzerFehler(f"„{name}“ ist schon der Name eines Zugangsschlüssels. Bitte einen anderen wählen.")
        if passwort is not None:
            _passwort_pruefen(passwort)
        with self._sperre:
            alle = self._lesen()
            if name.lower() in alle:
                raise NutzerFehler(f"Den Namen „{name}“ gibt es schon.")
            neu = Nutzer(
                name=name,
                anzeigename=anzeigename.strip() or name,
                admin=admin,
                passwort=passwort_hash(passwort) if passwort else None,
                angelegt=dt.date.today().isoformat(),
            )
            alle[name.lower()] = neu
            self._schreiben(alle)
            return neu

    def aendern(
        self, name: str, *, anzeigename: str | None = None, admin: bool | None = None, aktiv: bool | None = None
    ) -> Nutzer:
        with self._sperre:
            alle = self._lesen()
            nutzer = alle.get(name.lower())
            if nutzer is None:
                raise NutzerFehler("Diesen Nutzer gibt es nicht.")
            if anzeigename is not None:
                nutzer.anzeigename = anzeigename.strip() or nutzer.name
            if admin is not None:
                nutzer.admin = admin
            if aktiv is not None:
                nutzer.aktiv = aktiv
            if not any(n.admin and n.aktiv for n in alle.values()):
                raise NutzerFehler("Es muss mindestens einen aktiven Admin geben.")
            self._schreiben(alle)
            return nutzer

    def entfernen(self, name: str) -> None:
        with self._sperre:
            alle = self._lesen()
            if alle.pop(name.lower(), None) is None:
                raise NutzerFehler("Diesen Nutzer gibt es nicht.")
            if not any(n.admin and n.aktiv for n in alle.values()):
                raise NutzerFehler("Es muss mindestens einen aktiven Admin geben.")
            self._schreiben(alle)

    def passwort_setzen(self, name: str, passwort: str | None) -> None:
        """``None`` entfernt das Passwort (dann nur noch Anmeldung mit Zugangsschluessel)."""
        if passwort is not None:
            _passwort_pruefen(passwort)
        with self._sperre:
            alle = self._lesen()
            nutzer = alle.get(name.lower())
            if nutzer is None:
                raise NutzerFehler("Diesen Nutzer gibt es nicht.")
            nutzer.passwort = passwort_hash(passwort) if passwort else None
            self._schreiben(alle)

    def passwort_pruefen(self, name: str, passwort: str) -> Nutzer | None:
        nutzer = self.hole(name) if NAME_MUSTER.fullmatch(name) else None
        gespeichert = nutzer.passwort if nutzer is not None and nutzer.passwort else _ATTRAPPE
        passt = passwort_passt(passwort, gespeichert)
        if nutzer is None or not nutzer.aktiv or not nutzer.passwort or not passt:
            return None
        return nutzer

    def zugang_anlegen(self, name: str, bezeichnung: str) -> str:
        """Neuer persoenlicher Zugangsschluessel; der Klartext kommt genau einmal zurueck."""
        bezeichnung = bezeichnung.strip()[:60] or "Zugang"
        schluessel = secrets.token_urlsafe(32)
        with self._sperre:
            alle = self._lesen()
            nutzer = alle.get(name.lower())
            if nutzer is None:
                raise NutzerFehler("Diesen Nutzer gibt es nicht.")
            if any(z.get("bezeichnung") == bezeichnung for z in nutzer.zugaenge):
                raise NutzerFehler(f"Einen Zugang „{bezeichnung}“ gibt es schon.")
            nutzer.zugaenge.append(
                {"bezeichnung": bezeichnung, "token_sha256": schluessel_hash(schluessel), "angelegt": dt.date.today().isoformat()}
            )
            self._schreiben(alle)
        return schluessel

    def zugang_entfernen(self, name: str, bezeichnung: str) -> None:
        with self._sperre:
            alle = self._lesen()
            nutzer = alle.get(name.lower())
            if nutzer is None:
                raise NutzerFehler("Diesen Nutzer gibt es nicht.")
            vorher = len(nutzer.zugaenge)
            nutzer.zugaenge = [z for z in nutzer.zugaenge if z.get("bezeichnung") != bezeichnung]
            if len(nutzer.zugaenge) == vorher:
                raise NutzerFehler("Diesen Zugang gibt es nicht.")
            self._schreiben(alle)

    def zugang_pruefen(self, schluessel: str) -> Nutzer | None:
        """Zu welchem aktiven Nutzer gehoert dieser Schluessel? Vergleicht alle (konstante Zeit)."""
        return self.zugang_hash_pruefen(schluessel_hash(schluessel))

    def zugang_hash_pruefen(self, gesucht: str) -> Nutzer | None:
        """Wie ``zugang_pruefen``, aber mit dem SHA-256 des Schluessels -- so prueft eine Browser-Sitzung bei jeder
        Anfrage nach, ob der Schluessel, mit dem sie angelegt wurde, noch gilt (ohne den Klartext aufzuheben)."""
        treffer: Nutzer | None = None
        for nutzer in self.liste():
            for zugang in nutzer.zugaenge:
                if hmac.compare_digest(gesucht, str(zugang.get("token_sha256", "")).lower()) and nutzer.aktiv:
                    treffer = nutzer
        return treffer


def _passwort_pruefen(passwort: str) -> None:
    if len(passwort) < MIN_PASSWORT:
        raise NutzerFehler(f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen.")
