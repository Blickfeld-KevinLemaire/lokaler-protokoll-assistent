"""Aufnahmegeraete ueber USB einrichten (``GERAETE-SCHNITTSTELLE.md``, Abschnitt
"Einrichtung über USB").

Die Software schreibt WLAN, Adresse und Token ueber die serielle
USB-Schnittstelle ins Geraet; der Kunde muss nichts kompilieren. Ohne Qt, damit
die Ablaufsteuerung ohne Fenster und ohne Geraet testbar ist: Die serielle
Verbindung wird als Objekt mit ``write``/``readline``/``close`` uebergeben.

Passwort und Token werden nie protokolliert und vom Geraet nie zurueckgegeben.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

PRAEFIX = "#VERMERK "
ESPRESSIF_VID = 0x303A
BAUDRATE = 115200
MAX_ZEILE = 512
# Antworten des Geraets duerfen laenger sein (INFO mit langem WLAN-Namen).
MAX_ANTWORT = 1024
# Ein Geraet, das gerade startet, antwortet erst nach ein, zwei Sekunden.
INFO_VERSUCHE = 3
ANTWORT_SEKUNDEN = 3.0
NEUSTART_SEKUNDEN = 20.0

_TOKEN = re.compile(r"^[\x21-\x7e]{1,128}$")
_PASSWORT = re.compile(r"^[\x20-\x7e]*$")
# http://<Rechner>[:Port] -- wie im Geraet: kein https (kein TLS), kein "/" am Ende.
_URL = re.compile(r"^http://[A-Za-z0-9._-]+(:[0-9]{1,5})?$")


class UsbFehler(Exception):
    """Lesbare Meldung fuer die Oberflaeche."""


class SerielleVerbindung(Protocol):
    def write(self, daten: bytes) -> Any: ...

    def readline(self) -> bytes: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------
# Anschluesse
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Anschluss:
    port: str
    beschreibung: str
    espressif: bool


def anschluesse_finden() -> list[Anschluss]:
    """Serielle Anschluesse, Espressif-Geraete (USB-Hersteller 0x303A) zuerst."""
    try:
        from serial.tools import list_ports  # type: ignore[import-untyped]
    except ImportError as fehler:
        raise UsbFehler("Das Paket 'pyserial' fehlt; bitte die Anwendung neu einrichten.") from fehler
    gefunden = [
        Anschluss(str(p.device), str(p.description or p.device), getattr(p, "vid", None) == ESPRESSIF_VID)
        for p in list_ports.comports()
    ]
    return sorted(gefunden, key=lambda a: (not a.espressif, a.port))


def verbindung_oeffnen(port: str) -> SerielleVerbindung:
    """Oeffnet den Anschluss mit DTR und RTS **aus**: Beim eingebauten
    USB-Serial-JTAG der ESP32 loesen diese Leitungen sonst einen Neustart oder
    den Bootloader aus."""
    try:
        import serial  # type: ignore[import-untyped]
    except ImportError as fehler:
        raise UsbFehler("Das Paket 'pyserial' fehlt; bitte die Anwendung neu einrichten.") from fehler
    verbindung = serial.Serial()
    verbindung.port = port
    verbindung.baudrate = BAUDRATE
    verbindung.timeout = 0.2
    verbindung.write_timeout = 2.0
    verbindung.dtr = False
    verbindung.rts = False
    try:
        verbindung.open()
    except (OSError, serial.SerialException) as fehler:
        raise UsbFehler(f"{port} laesst sich nicht oeffnen ({fehler}). Ist ein serieller Monitor noch offen?") from fehler
    return verbindung


# --------------------------------------------------------------------------
# Daten
# --------------------------------------------------------------------------
def _hex(text: str) -> str:
    return text.encode("utf-8").hex()


def _aus_hex(wert: Any) -> str:
    try:
        return bytes.fromhex(str(wert or "")).decode("utf-8", errors="replace")
    except ValueError:
        return ""


@dataclass(frozen=True)
class GeraeteInfo:
    geraete_id: str
    board: str
    firmware: str
    eingerichtet: bool
    wlan: str
    pc_url: str
    server_url: str
    token_pc: bool
    token_server: bool

    @classmethod
    def aus_json(cls, text: str) -> GeraeteInfo:
        try:
            daten = json.loads(text)
        except ValueError as fehler:
            raise UsbFehler("Das Geraet hat eine unlesbare Antwort geschickt.") from fehler
        if not isinstance(daten, dict) or not isinstance(daten.get("geraete_id"), str):
            raise UsbFehler("Das Geraet hat eine unvollstaendige Antwort geschickt.")
        return cls(
            geraete_id=str(daten.get("geraete_id", "")),
            board=str(daten.get("board", "")),
            firmware=str(daten.get("firmware", "")),
            eingerichtet=daten.get("eingerichtet") is True,
            wlan=_aus_hex(daten.get("wlan_hex")),
            pc_url=_aus_hex(daten.get("pc_url_hex")),
            server_url=_aus_hex(daten.get("server_url_hex")),
            token_pc=daten.get("token_pc") is True,
            token_server=daten.get("token_server") is True,
        )


@dataclass(frozen=True)
class Einrichtung:
    wlan_ssid: str
    wlan_passwort: str
    pc_url: str = ""
    pc_token: str = ""
    server_url: str = ""
    server_token: str = ""
    erste_nummer: int | None = None

    def fehler(self) -> list[str]:
        """Dieselben Regeln wie im Geraet -- hier geprueft, damit der Anwender
        die Meldung sofort und auf Deutsch sieht."""
        meldungen: list[str] = []
        if not 1 <= len(self.wlan_ssid.encode("utf-8")) <= 32 or "\x00" in self.wlan_ssid:
            meldungen.append("Der WLAN-Name muss 1 bis 32 Bytes lang sein.")
        passwort = len(self.wlan_passwort)
        if (passwort and not 8 <= passwort <= 63) or not _PASSWORT.match(self.wlan_passwort):
            meldungen.append(
                "Das WLAN-Passwort muss leer (offenes WLAN) oder 8 bis 63 Zeichen lang sein, "
                "ohne Umlaute und Zeichen ausserhalb von ASCII."
            )
        vollstaendig = 0
        for bezeichnung, url, token in (("PC", self.pc_url, self.pc_token), ("Server", self.server_url, self.server_token)):
            if not url and not token:
                continue
            if not _URL.match(url) or len(url) > 96:
                meldungen.append(
                    f"{bezeichnung}-Adresse: http://Rechner:Port mit hoechstens 96 Zeichen, ohne / am Ende "
                    "(https geht nicht, das Geraet kann kein TLS)."
                )
            if not _TOKEN.match(token):
                meldungen.append(f"{bezeichnung}: Zur Adresse gehoert ein Token (1 bis 128 Zeichen ohne Leerzeichen).")
            if url and token:
                vollstaendig += 1
        if not vollstaendig:
            meldungen.append("Mindestens ein Ziel (Adresse und Token) muss angegeben sein.")
        if self.erste_nummer is not None and not 1 <= self.erste_nummer <= 999999:
            meldungen.append("Die erste Aufnahmenummer muss zwischen 1 und 999999 liegen.")
        return meldungen

    def befehle(self) -> list[tuple[str, str]]:
        """``(Schluessel, Zeile)`` je ``SETZE``. Leere Werte werden mitgeschickt:
        Eine Einrichtung ersetzt immer die ganze vorherige."""
        werte = [
            ("wlan_ssid", self.wlan_ssid),
            ("wlan_passwort", self.wlan_passwort),
            ("pc_url", self.pc_url),
            ("pc_token", self.pc_token),
            ("server_url", self.server_url),
            ("server_token", self.server_token),
        ]
        if self.erste_nummer is not None:
            werte.append(("erste_nummer", str(self.erste_nummer)))
        return [(schluessel, f"{PRAEFIX}SETZE {schluessel} {_hex(wert)}") for schluessel, wert in werte]


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------
class Geraetesitzung:
    """Eine geoeffnete serielle Verbindung zu einem Geraet."""

    def __init__(self, verbindung: SerielleVerbindung, *, jetzt: Callable[[], float] = time.monotonic):
        self._verbindung = verbindung
        self._jetzt = jetzt

    def schliessen(self) -> None:
        with contextlib.suppress(Exception):
            self._verbindung.close()

    def _senden(self, zeile: str) -> None:
        try:
            self._verbindung.write((zeile + "\n").encode("ascii"))
        except Exception as fehler:  # pyserial meldet je nach Treiber verschiedene Fehler
            raise UsbFehler(f"Senden an das Geraet gescheitert ({fehler}).") from fehler

    def _antwort(self, passt: Callable[[str], bool], zeitlimit: float) -> str:
        """Liest Zeilen, bis eine Antwortzeile passt. Protokollzeilen des Geraets
        und das eigene Echo werden uebergangen."""
        ende = self._jetzt() + zeitlimit
        while self._jetzt() < ende:
            try:
                roh = self._verbindung.readline()
            except Exception as fehler:
                raise UsbFehler(f"Lesen vom Geraet gescheitert ({fehler}).") from fehler
            if not roh:
                continue
            zeile = roh[:MAX_ANTWORT].decode("utf-8", errors="replace").strip()
            if zeile.startswith(PRAEFIX) and passt(zeile[len(PRAEFIX):]):
                return zeile[len(PRAEFIX):]
        raise UsbFehler("Das Geraet antwortet nicht. Ist die richtige Firmware drauf und der richtige Anschluss gewaehlt?")

    def _anweisung(self, befehl: str, ok: str, fehler_schluessel: str) -> None:
        self._senden(f"{PRAEFIX}{befehl}")
        antwort = self._antwort(
            lambda z: z == f"OK {ok}" or z.startswith(f"FEHLER {fehler_schluessel}"), ANTWORT_SEKUNDEN
        )
        if antwort.startswith("FEHLER"):
            text = antwort[len(f"FEHLER {fehler_schluessel}"):].strip() or "ohne Begruendung"
            raise UsbFehler(f"Das Geraet lehnt '{fehler_schluessel}' ab: {text}")

    def info(self, versuche: int = INFO_VERSUCHE) -> GeraeteInfo:
        letzter: UsbFehler | None = None
        for _ in range(versuche):
            self._senden(f"{PRAEFIX}INFO")
            try:
                return GeraeteInfo.aus_json(self._antwort(lambda z: z.startswith("INFO {"), ANTWORT_SEKUNDEN)[5:])
            except UsbFehler as fehler:
                letzter = fehler
        raise letzter or UsbFehler("Das Geraet antwortet nicht.")

    def einrichten(self, einrichtung: Einrichtung) -> None:
        """Schreibt alle Werte und speichert. Danach startet das Geraet neu."""
        meldungen = einrichtung.fehler()
        if meldungen:
            raise UsbFehler(" ".join(meldungen))
        self._anweisung("VERWERFEN", "VERWERFEN", "VERWERFEN")
        for schluessel, zeile in einrichtung.befehle():
            self._anweisung(zeile[len(PRAEFIX):], f"SETZE {schluessel}", schluessel)
        self._anweisung("SPEICHERN", "SPEICHERN", "SPEICHERN")

    def loeschen(self) -> None:
        self._anweisung("LOESCHEN", "LOESCHEN", "LOESCHEN")


def nach_neustart_verbinden(
    port: str,
    oeffnen: Callable[[str], SerielleVerbindung] = verbindung_oeffnen,
    *,
    zeitlimit: float = NEUSTART_SEKUNDEN,
    jetzt: Callable[[], float] = time.monotonic,
    schlafen: Callable[[float], None] = time.sleep,
) -> Geraetesitzung:
    """Nach ``SPEICHERN`` startet das Geraet neu; der COM-Port verschwindet dabei
    kurz (USB meldet sich neu an) und kommt unter demselben Namen wieder."""
    ende = jetzt() + zeitlimit
    schlafen(1.5)
    letzter: Exception | None = None
    while jetzt() < ende:
        try:
            sitzung = Geraetesitzung(oeffnen(port), jetzt=jetzt)
        except UsbFehler as fehler:
            letzter = fehler
            schlafen(0.5)
            continue
        return sitzung
    raise UsbFehler(f"Nach dem Neustart war {port} nicht wieder erreichbar ({letzter}).")


def inventarzeile(info: GeraeteInfo, name: str, datum: str) -> str:
    """Zeile fuer ``geraete.csv`` im privaten Inventar (gleiche Spaltenfolge)."""
    firmware = info.firmware.split("/")[-1]
    return f"{info.geraete_id},{info.board},{name},{firmware},{datum},im-einsatz,,,"
