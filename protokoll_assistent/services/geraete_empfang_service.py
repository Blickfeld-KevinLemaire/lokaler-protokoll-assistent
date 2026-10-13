"""Empfang fuer die WLAN-Aufnahmegeraete.

Die Geraete (Firmware unter ``firmware/``) laden ihre Aufnahmen in Stuecken
hoch; dieser Dienst nimmt sie entgegen, prueft sie und legt fertige Dateien im
Eingangsordner ab. Die Schnittstelle steht in ``GERAETE-SCHNITTSTELLE.md`` --
dieses Modul setzt sie um, fuer die Windows-Anwendung und den Servermodus
gleichermassen (deshalb ohne Qt).

Aufbau:

* :class:`Ablage` -- Teilstaende, Abschluss, Pruefsumme, Ablage. Kennt kein
  HTTP und ist dadurch ohne Netz testbar.
* :class:`GeraeteEmpfang` -- der HTTP-Dienst (Standardbibliothek) davor:
  Anmeldung per Token, Kopfzeilen lesen, Antworten schreiben.

Sicherheit: Der Dienst ist aus, bis er eingeschaltet wird. Jedes Geraet hat ein
eigenes Token; gespeichert wird nur dessen SHA-256. Ein Token wird nie
protokolliert.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

logger = logging.getLogger(__name__)

SCHNITTSTELLE = 1
DIENST_KENNUNG = "protokoll-assistent"
STANDARD_PORT = 8765
# Bindet an alle Netzwerkschnittstellen: Die Geraete kommen aus dem WLAN, nicht
# vom eigenen Rechner. Der Dienst laeuft nur, wenn er eingeschaltet ist, und
# jede Anfrage braucht ein Token.
STANDARD_ADRESSE = "0.0.0.0"  # noqa: S104
TEIL_MAX_BYTES = 4 * 1024 * 1024
# Opus mit 24 kbit/s sind ca. 11 MB pro Stunde; WAV vom S3 ca. 115 MB pro
# Stunde. 2 GB reichen fuer jede realistische Aufnahme und begrenzen trotzdem,
# was ein fehlerhaftes Geraet auf die Platte schreiben kann.
STANDARD_MAX_DATEI_BYTES = 2 * 1024**3
# So viel muss nach dem Schreiben noch frei bleiben -- die Verarbeitung
# braucht selbst Platz (WAV-Zwischenstaende, Transkripte).
PLATZ_RESERVE_BYTES = 200 * 1024**2
MAX_VERBINDUNGEN = 8
ZEITLIMIT_SEKUNDEN = 30.0
TEILSTAND_MAX_ALTER_SEKUNDEN = 7 * 24 * 3600
# Hoechstens so viele abgeschlossene Aufnahmen merkt sich der Dienst, um
# Wiederholungen zu erkennen. Ein Geraet wiederholt nur kurz nach dem Abschluss.
MAX_FERTIG_EINTRAEGE = 2000

EMPFANGSORDNER = ".empfang"
ERLAUBTE_ENDUNGEN = (".opus", ".ogg", ".wav", ".mp3")

_DATEINAME = re.compile(r"^[A-Za-z0-9_-]{1,64}\.(?:opus|ogg|wav|mp3)$", re.IGNORECASE)
_GERAETENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GERAETE_ID = re.compile(r"^[0-9a-f]{12}$")
_FIRMWARE = re.compile(r"^[A-Za-z0-9._/+-]{1,64}$")
_LESEBLOCK = 64 * 1024
# Sanftes Schliessen: So lange und so viel liest der Dienst nach seiner Antwort
# noch weg, bevor er die Verbindung schliesst (siehe _Anfrage.finish).
NACHLAUF_SEKUNDEN = 2.0
NACHLAUF_MAX_BYTES = TEIL_MAX_BYTES + 1024 * 1024


# --------------------------------------------------------------------------
# Geraete und Token
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Geraet:
    name: str
    token_sha256: str


def token_erzeugen() -> str:
    """Neues Token fuer ein Geraet (256 Bit, URL-sicher, 43 Zeichen)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def geraetename_gueltig(name: str) -> bool:
    """Buchstaben, Ziffern, ``_`` und ``-``, hoechstens 32 Zeichen. Der Name
    steht spaeter vorn im Dateinamen jeder Aufnahme dieses Geraets."""
    return bool(_GERAETENAME.match(name))


def dateiname_gueltig(name: str) -> bool:
    return bool(_DATEINAME.match(name))


def geraete_aus_text(text: str) -> tuple[Geraet, ...]:
    """Liest ``Name:SHA256, Name2:SHA256`` (Servermodus, ``PROTOKOLL_EMPFANG_GERAETE``).

    Wirft ``ValueError`` mit lesbarer Meldung -- ein Tippfehler soll beim
    Start auffallen, nicht erst, wenn das Geraet abgewiesen wird."""
    geraete: list[Geraet] = []
    for eintrag in (teil.strip() for teil in text.split(",")):
        if not eintrag:
            continue
        name, trenner, hashwert = eintrag.partition(":")
        name, hashwert = name.strip(), hashwert.strip().lower()
        if not trenner or not geraetename_gueltig(name):
            raise ValueError(f"'{eintrag[:40]}' ist kein Eintrag der Form Name:SHA256 mit gueltigem Geraetenamen.")
        if not _SHA256.match(hashwert):
            raise ValueError(f"Zu '{name}' fehlt ein gueltiger SHA-256-Hash (64 Hex-Zeichen).")
        geraete.append(Geraet(name, hashwert))
    _doppelte_pruefen(geraete)
    return tuple(geraete)


def geraete_aus_konfiguration(eintraege: Iterable[Any]) -> tuple[Geraet, ...]:
    """Geraete aus ``konfiguration.json`` (Liste von ``{"name", "token_sha256"}``).
    Unbrauchbare Eintraege (von Hand verbogen) werden uebergangen."""
    geraete: list[Geraet] = []
    namen: set[str] = set()
    for eintrag in eintraege:
        if not isinstance(eintrag, Mapping):
            continue
        name = str(eintrag.get("name", ""))
        hashwert = str(eintrag.get("token_sha256", "")).lower()
        if geraetename_gueltig(name) and _SHA256.match(hashwert) and name.lower() not in namen:
            namen.add(name.lower())
            geraete.append(Geraet(name, hashwert))
    return tuple(geraete)


def _doppelte_pruefen(geraete: list[Geraet]) -> None:
    namen = [g.name.lower() for g in geraete]
    doppelt = sorted({n for n in namen if namen.count(n) > 1})
    if doppelt:
        raise ValueError(f"Geraetename mehrfach vergeben: {', '.join(doppelt)}")


def geraet_zum_token(token: str, geraete: Iterable[Geraet]) -> Geraet | None:
    if not token:
        return None
    gesucht = token_hash(token)
    treffer = None
    for geraet in geraete:
        # Alle vergleichen, nicht beim ersten Treffer aufhoeren: gleiche Laufzeit.
        if hmac.compare_digest(gesucht, geraet.token_sha256):
            treffer = geraet
    return treffer


@dataclass(frozen=True)
class Kontakt:
    """Was ein Geraet bei seiner letzten Anfrage ueber sich mitgeteilt hat --
    fuer Zuordnung und Fehlersuche, nie fuer die Anmeldung."""

    geraete_id: str | None
    firmware: str | None
    adresse: str
    zeit: float


def geraete_id_lesen(wert: str | None) -> str | None:
    """``X-Geraete-Id``: Werks-MAC, 12 Hex-Zeichen. Anderes wird ignoriert."""
    text = (wert or "").strip().lower().replace(":", "").replace("-", "")
    return text if _GERAETE_ID.match(text) else None


def firmware_lesen(wert: str | None) -> str | None:
    text = (wert or "").strip()
    return text if _FIRMWARE.match(text) else None


def lokale_adressen() -> list[str]:
    """IPv4-Adressen dieses Rechners im lokalen Netz -- fuer den Hinweis, welche
    Adresse in die ``server_config.h`` des Geraets gehoert."""
    adressen: list[str] = []
    with contextlib.suppress(OSError):
        # Ein UDP-"connect" verschickt nichts; er waehlt nur die Schnittstelle,
        # ueber die der Rechner ins Netz geht.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1, wird nie erreicht
            adressen.append(probe.getsockname()[0])
    with contextlib.suppress(OSError):
        for eintrag in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            adresse = str(eintrag[4][0])
            if adresse not in adressen:
                adressen.append(adresse)
    return [a for a in adressen if not a.startswith(("127.", "0.", "169.254."))]


# --------------------------------------------------------------------------
# Ablage: Teilstaende und Abschluss (ohne HTTP)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Antwort:
    status: int
    daten: dict[str, Any]

    def als_bytes(self) -> bytes:
        # Kompakt und ohne Leerzeichen: Die Firmware liest Felder per Textsuche.
        return json.dumps(self.daten, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fehler(status: int, text: str, **weitere: Any) -> Antwort:
    return Antwort(status, {**weitere, "fehler": text})


class Ablage:
    """Nimmt die Stuecke einer Aufnahme an und legt die fertige Datei ab.

    Teilstaende liegen in ``<ziel>/.empfang/`` -- im selben Ordner wie das
    Ziel, damit der Abschluss ein Umbenennen ist und die Datei auf einen
    Schlag erscheint. Die Namen der Teilstaende sind Hashes, nicht der
    Dateiname des Geraets: Windows lehnt Namen wie ``NUL.opus.teil`` ab.
    """

    def __init__(
        self,
        ziel: Path,
        *,
        max_datei_bytes: int = STANDARD_MAX_DATEI_BYTES,
        platz_reserve_bytes: int = PLATZ_RESERVE_BYTES,
        freier_platz: Callable[[Path], int] | None = None,
        bei_neuer_aufnahme: Callable[[Path, str], None] | None = None,
        bei_teil: Callable[[str, str, Path], None] | None = None,
        bei_abschluss: Callable[[str, str, Path], None] | None = None,
        jetzt: Callable[[], float] = time.time,
    ):
        self.ziel = ziel
        self._ordner = ziel / EMPFANGSORDNER
        self._max_datei_bytes = max_datei_bytes
        self._platz_reserve = platz_reserve_bytes
        self._freier_platz = freier_platz or (lambda pfad: shutil.disk_usage(pfad).free)
        self._bei_neuer_aufnahme = bei_neuer_aufnahme
        # Waehrend der Aufnahme (Stueck angekommen) und beim Abschluss, mit dem
        # Dateinamen, den das Geraet benutzt hat -- darunter fragt es den Status ab.
        self._bei_teil = bei_teil
        self._bei_abschluss = bei_abschluss
        self._jetzt = jetzt
        self._sperre = threading.Lock()
        self._sperren: dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------
    def _schluessel(self, geraet: str, datei: str) -> str:
        return hashlib.sha256(f"{geraet}/{datei}".encode()).hexdigest()[:32]

    def _teil_pfad(self, schluessel: str) -> Path:
        return self._ordner / f"{schluessel}.teil"

    def _sperre_fuer(self, schluessel: str) -> threading.Lock:
        with self._sperre:
            return self._sperren.setdefault(schluessel, threading.Lock())

    def stand(self, geraet: str, datei: str) -> Antwort:
        """``GET /api/v1/aufnahmen/<datei>``"""
        if not dateiname_gueltig(datei):
            return _fehler(400, "Ungueltiger Dateiname.")
        return Antwort(200, {"naechstes_byte": self._groesse(self._schluessel(geraet, datei)), "fertig": False})

    def _groesse(self, schluessel: str) -> int:
        try:
            return self._teil_pfad(schluessel).stat().st_size
        except OSError:
            return 0

    # ------------------------------------------------------------------
    def anhaengen(
        self,
        geraet: str,
        datei: str,
        offset: int,
        laenge: int,
        lesen: Callable[[int], bytes],
        gesamt: int | None = None,
        sha256: str | None = None,
    ) -> Antwort:
        """``PUT /api/v1/aufnahmen/<datei>``: haengt ``laenge`` Bytes an, die
        ``lesen`` liefert, und schliesst ab, wenn ``gesamt``/``sha256`` gesetzt sind.

        ``lesen`` wird nur aufgerufen, wenn das Stueck angenommen wird -- der
        Aufrufer erkennt daran, ob der Inhalt der Anfrage noch ungelesen ist."""
        if not dateiname_gueltig(datei):
            return _fehler(400, "Ungueltiger Dateiname.")
        if offset < 0 or laenge < 0:
            return _fehler(400, "X-Offset und Content-Length duerfen nicht negativ sein.")
        if (gesamt is None) != (sha256 is None):
            return _fehler(400, "X-Gesamtgroesse und X-SHA256 gehoeren zusammen.")
        if sha256 is not None and not _SHA256.match(sha256):
            return _fehler(400, "X-SHA256 muss aus 64 kleinen Hex-Zeichen bestehen.")
        if gesamt is not None and gesamt < 0:
            return _fehler(400, "X-Gesamtgroesse darf nicht negativ sein.")
        if laenge > TEIL_MAX_BYTES:
            return _fehler(413, f"Ein Stueck darf hoechstens {TEIL_MAX_BYTES} Bytes haben.")
        if offset + laenge > self._max_datei_bytes or (gesamt is not None and gesamt > self._max_datei_bytes):
            return _fehler(413, f"Eine Aufnahme darf hoechstens {self._max_datei_bytes} Bytes haben.")

        schluessel = self._schluessel(geraet, datei)
        with self._sperre_fuer(schluessel):
            vorhanden = self._groesse(schluessel)
            if offset != vorhanden:
                return _fehler(409, "X-Offset passt nicht zum Stand.", naechstes_byte=vorhanden, fertig=False)
            if laenge:
                antwort = self._schreiben(schluessel, offset, laenge, lesen, gesamt)
                if antwort is not None:
                    return antwort
            if gesamt is None or sha256 is None:
                if laenge and self._bei_teil is not None:
                    try:
                        self._bei_teil(geraet, datei, self._teil_pfad(schluessel))
                    except Exception:  # Eine Fehlfunktion der Live-Verarbeitung darf den Empfang nicht stoeren.
                        logger.exception("Meldung ueber das neue Stueck fehlgeschlagen")
                return Antwort(200, {"naechstes_byte": offset + laenge, "fertig": False})
            return self._abschliessen(schluessel, geraet, datei, gesamt, sha256)

    def _schreiben(
        self, schluessel: str, offset: int, laenge: int, lesen: Callable[[int], bytes], gesamt: int | None
    ) -> Antwort | None:
        self._ordner.mkdir(parents=True, exist_ok=True)
        noch_zu_erwarten = max(gesamt - offset, laenge) if gesamt is not None else laenge
        try:
            frei = self._freier_platz(self._ordner)
        except OSError:
            frei = 0
        if frei < noch_zu_erwarten + self._platz_reserve:
            return _fehler(507, "Zu wenig Platz auf der Platte.")

        teil = self._teil_pfad(schluessel)
        geschrieben = 0
        try:
            with teil.open("ab") as handle:
                while geschrieben < laenge:
                    block = lesen(min(_LESEBLOCK, laenge - geschrieben))
                    if not block:
                        break
                    handle.write(block)
                    geschrieben += len(block)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as fehler:
            logger.warning("Stueck konnte nicht geschrieben werden: %s", fehler)
            geschrieben = -1
        if geschrieben != laenge:
            # Den angefangenen Rest dieses Stuecks verwerfen: 'naechstes_byte'
            # zeigt danach wieder auf den Anfang des Stuecks.
            with contextlib.suppress(OSError), teil.open("r+b") as handle:
                handle.truncate(offset)
            return _fehler(400, "Das Stueck kam nicht vollstaendig an.", naechstes_byte=offset, fertig=False)
        return None

    def _abschliessen(self, schluessel: str, geraet: str, datei: str, gesamt: int, sha256: str) -> Antwort:
        teil = self._teil_pfad(schluessel)
        groesse = self._groesse(schluessel)
        if groesse != gesamt:
            self._verwerfen(teil)
            return _fehler(
                422, f"Groesse stimmt nicht ({groesse} statt {gesamt} Bytes).", naechstes_byte=0, fertig=False
            )
        if _datei_sha256(teil) != sha256:
            self._verwerfen(teil)
            return _fehler(422, "Pruefsumme stimmt nicht.", naechstes_byte=0, fertig=False)

        with self._sperre:
            fertig = self._fertig_laden()
            kennung = f"{geraet}/{datei}/{gesamt}/{sha256}"
            if kennung in fertig:
                # Dieselbe Aufnahme noch einmal (die Bestaetigung ging verloren):
                # keine zweite Datei, aber dieselbe Antwort.
                self._verwerfen(teil)
                return Antwort(200, {"naechstes_byte": gesamt, "fertig": True, "datei": fertig[kennung]["datei"]})
            ziel = self._freier_zielname(f"{geraet}_{datei}")
            # Erst ablegen, dann merken: Faellt dazwischen der Strom aus, entsteht
            # schlimmstenfalls eine doppelte Datei -- umgekehrt ginge sie verloren.
            _ersetzen_mit_wiederholung(teil, ziel)
            _ordner_sichern(self.ziel)
            fertig[kennung] = {"datei": ziel.name, "zeit": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._fertig_speichern(fertig)

        logger.info("Aufnahme von %s angekommen: %s (%d Bytes)", geraet, ziel.name, gesamt)
        if self._bei_abschluss is not None:
            try:
                self._bei_abschluss(geraet, datei, ziel)
            except Exception:
                logger.exception("Meldung ueber den Abschluss fehlgeschlagen")
        if self._bei_neuer_aufnahme is not None:
            try:
                self._bei_neuer_aufnahme(ziel, geraet)
            except Exception:  # Ein Fehler der Anzeige darf den Empfang nicht stoeren.
                logger.exception("Meldung ueber die neue Aufnahme fehlgeschlagen")
        return Antwort(200, {"naechstes_byte": gesamt, "fertig": True, "datei": ziel.name})

    def _freier_zielname(self, name: str) -> Path:
        ziel = self.ziel / name
        stamm, endung = ziel.stem, ziel.suffix
        nummer = 2
        while ziel.exists():
            ziel = self.ziel / f"{stamm}_{nummer}{endung}"
            nummer += 1
        return ziel

    @staticmethod
    def _verwerfen(teil: Path) -> None:
        with contextlib.suppress(OSError):
            teil.unlink()

    # ------------------------------------------------------------------
    def _fertig_datei(self) -> Path:
        return self._ordner / "fertig.json"

    def _fertig_laden(self) -> dict[str, dict[str, str]]:
        try:
            daten = json.loads(self._fertig_datei().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        eintraege = daten.get("aufnahmen") if isinstance(daten, dict) else None
        return eintraege if isinstance(eintraege, dict) else {}

    def _fertig_speichern(self, fertig: dict[str, dict[str, str]]) -> None:
        # dict behaelt die Einfuegereihenfolge: die aeltesten fallen zuerst weg.
        while len(fertig) > MAX_FERTIG_EINTRAEGE:
            del fertig[next(iter(fertig))]
        self._ordner.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._ordner, suffix=".tmp", delete=False
        ) as handle:
            json.dump({"version": 1, "aufnahmen": fertig}, handle, ensure_ascii=False, indent=2)
            temp = Path(handle.name)
        _ersetzen_mit_wiederholung(temp, self._fertig_datei())

    def aufraeumen(self, max_alter_sekunden: float = TEILSTAND_MAX_ALTER_SEKUNDEN) -> int:
        """Loescht Teilstaende, die lange nicht weitergewachsen sind. Liefert die Anzahl."""
        grenze = self._jetzt() - max_alter_sekunden
        entfernt = 0
        try:
            kandidaten = list(self._ordner.glob("*.teil")) + list(self._ordner.glob("*.tmp"))
        except OSError:
            return 0
        for pfad in kandidaten:
            try:
                if pfad.stat().st_mtime < grenze:
                    pfad.unlink()
                    entfernt += 1
            except OSError:
                continue
        return entfernt


def _datei_sha256(pfad: Path) -> str:
    pruefsumme = hashlib.sha256()
    with pfad.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            pruefsumme.update(block)
    return pruefsumme.hexdigest()


def _ordner_sichern(ordner: Path) -> None:
    """Schreibt unter Linux den Ordnereintrag der eben umbenannten Datei fest.
    Windows kennt das nicht (und braucht es fuer NTFS nicht)."""
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        handle = os.open(ordner, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_PFAD_HALLO = "/api/v1/hallo"
_PFAD_AUFNAHMEN = "/api/v1/aufnahmen/"
_ENDE_STATUS = "/status"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Unter Windows erlaubt SO_REUSEADDR einem zweiten Prozess, denselben Port
    # zu belegen -- die Geraete landeten dann zufaellig bei einem der beiden.
    allow_reuse_address = os.name != "nt"

    def __init__(self, adresse: tuple[str, int], empfang: GeraeteEmpfang):
        self.empfang = empfang
        self.plaetze = threading.BoundedSemaphore(MAX_VERBINDUNGEN)
        super().__init__(adresse, _Anfrage)


class _Anfrage(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"
    server_version = "ProtokollAssistent"
    sys_version = ""
    timeout = ZEITLIMIT_SEKUNDEN

    _ueberlastet = False

    def handle(self) -> None:
        belegt = self.server.plaetze.acquire(blocking=False)
        self._ueberlastet = not belegt
        try:
            super().handle()
        finally:
            if belegt:
                self.server.plaetze.release()

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            _sanft_schliessen(self.connection)

    def log_message(self, format: str, *args: Any) -> None:
        # Nicht auf stderr: Die Anwendung hat kein Konsolenfenster, und der Pfad
        # enthaelt nichts Geheimes, das Token steht nur in einer Kopfzeile.
        logger.debug("%s %s", self.address_string(), format % args)

    # ------------------------------------------------------------------
    def _senden(self, antwort: Antwort, *, schliessen: bool = False) -> None:
        text = antwort.als_bytes()
        if schliessen:
            self.close_connection = True
        try:
            self.send_response(antwort.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(text)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(text)
        except OSError:
            self.close_connection = True

    def _vorpruefung(self) -> Geraet | None:
        """Ueberlast und Anmeldung. Liefert das Geraet oder hat schon geantwortet."""
        if self._ueberlastet:
            self._senden(_fehler(503, "Zu viele gleichzeitige Verbindungen."), schliessen=True)
            return None
        kopf = self.headers.get("Authorization", "")
        art, _, token = kopf.partition(" ")
        geraet = geraet_zum_token(token.strip(), self.server.empfang.geraete) if art.lower() == "bearer" else None
        if geraet is None:
            # Ungelesener Inhalt bleibt im Strom -- die Verbindung muss zu.
            self._senden(_fehler(401, "Token fehlt oder ist unbekannt."), schliessen=True)
            return None
        self.server.empfang.kontakt_merken(
            geraet.name,
            geraete_id_lesen(self.headers.get("X-Geraete-Id")),
            firmware_lesen(self.headers.get("X-Firmware")),
            self.client_address[0],
        )
        return geraet

    def _pfad(self) -> str:
        return self.path.split("?", 1)[0]

    def do_GET(self) -> None:
        geraet = self._vorpruefung()
        if geraet is None:
            return
        pfad = self._pfad()
        if pfad == _PFAD_HALLO:
            self._senden(
                Antwort(
                    200,
                    {
                        "dienst": DIENST_KENNUNG,
                        "schnittstelle": SCHNITTSTELLE,
                        "geraet": geraet.name,
                        "teil_max_bytes": TEIL_MAX_BYTES,
                    },
                )
            )
        elif pfad.startswith(_PFAD_AUFNAHMEN) and pfad.endswith(_ENDE_STATUS):
            name = pfad[len(_PFAD_AUFNAHMEN) : -len(_ENDE_STATUS)]
            self._senden(self.server.empfang.status(geraet.name, name))
        elif pfad.startswith(_PFAD_AUFNAHMEN):
            self._senden(self.server.empfang.ablage.stand(geraet.name, pfad[len(_PFAD_AUFNAHMEN):]))
        else:
            self._senden(_fehler(404, "Unbekannter Pfad."))

    def do_PUT(self) -> None:
        geraet = self._vorpruefung()
        if geraet is None:
            return
        pfad = self._pfad()
        if not pfad.startswith(_PFAD_AUFNAHMEN):
            self._senden(_fehler(404, "Unbekannter Pfad."), schliessen=True)
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length") is None:
            self._senden(_fehler(411, "Content-Length fehlt (Chunked Transfer wird nicht angenommen)."), schliessen=True)
            return
        try:
            laenge = int(self.headers["Content-Length"])
            offset = int(self.headers.get("X-Offset", ""))
            gesamt_text = self.headers.get("X-Gesamtgroesse")
            gesamt = int(gesamt_text) if gesamt_text is not None else None
        except ValueError:
            self._senden(_fehler(400, "Content-Length, X-Offset und X-Gesamtgroesse muessen Zahlen sein."), schliessen=True)
            return
        sha_text = self.headers.get("X-SHA256")
        sha256 = sha_text.strip().lower() if sha_text is not None else None

        gelesen = 0

        def lesen(anzahl: int) -> bytes:
            nonlocal gelesen
            try:
                block = self.rfile.read(anzahl)
            except OSError:  # Zeitlimit oder Verbindung weg
                return b""
            gelesen += len(block)
            return block

        antwort = self.server.empfang.ablage.anhaengen(
            geraet.name, pfad[len(_PFAD_AUFNAHMEN):], offset, laenge, lesen, gesamt, sha256
        )
        # Abgelehnt, ohne den Inhalt zu lesen (409, 413, 507 ...): Den Rest eines
        # angemeldeten Geraets erst abholen und verwerfen. Schloesse der Dienst
        # sofort, setzte TCP die Verbindung mit ungelesenen Daten zurueck -- das
        # Geraet saehe dann nur einen Verbindungsfehler statt der Antwort und
        # wuesste nicht, ab welchem Byte es weitergeht.
        if 0 < laenge - gelesen <= TEIL_MAX_BYTES:
            while gelesen < laenge and lesen(min(_LESEBLOCK, laenge - gelesen)):
                pass
        # Ist der Inhalt dennoch nicht ganz gelesen, steht er noch im Strom und
        # wuerde als naechste Anfrage gedeutet: Verbindung schliessen.
        self._senden(antwort, schliessen=gelesen != laenge)

    def _nicht_erlaubt(self) -> None:
        self._senden(_fehler(405, "Methode nicht erlaubt."), schliessen=True)

    do_POST = do_DELETE = do_PATCH = do_HEAD = _nicht_erlaubt


def _sanft_schliessen(verbindung: socket.socket) -> None:
    """Schliesst wie Apache ("lingering close"): erst die Senderichtung, dann
    noch Ankommendes verwerfen, bis die Gegenseite schliesst.

    Schliesst ein Server, waehrend ungelesene Daten im Puffer liegen (der
    Inhalt einer abgelehnten Anfrage: 401, 404, 405, 411 ...), setzt TCP die
    Verbindung zurueck. Kommt das RST beim Geraet an, bevor es die Antwort
    gelesen hat, sieht es nur "Verbindung zurueckgesetzt" statt des Status. So
    kommt die Antwort sicher an. Begrenzt durch NACHLAUF_SEKUNDEN und
    NACHLAUF_MAX_BYTES -- ein Fremder kann den Dienst damit nicht festhalten."""
    with contextlib.suppress(OSError):
        verbindung.shutdown(socket.SHUT_WR)
        ende = time.monotonic() + NACHLAUF_SEKUNDEN
        verworfen = 0
        while verworfen <= NACHLAUF_MAX_BYTES:
            rest = ende - time.monotonic()
            if rest <= 0:
                break
            verbindung.settimeout(rest)
            daten = verbindung.recv(_LESEBLOCK)
            if not daten:
                break
            verworfen += len(daten)


class GeraeteEmpfang:
    """Der HTTP-Dienst. ``starten`` bindet den Port (``OSError``, wenn er belegt
    ist) und laeuft dann in einem eigenen Faden bis ``stoppen``."""

    def __init__(
        self,
        ziel: Path,
        geraete: Iterable[Geraet],
        *,
        port: int = STANDARD_PORT,
        adresse: str = STANDARD_ADRESSE,
        max_datei_bytes: int = STANDARD_MAX_DATEI_BYTES,
        bei_neuer_aufnahme: Callable[[Path, str], None] | None = None,
        bei_teil: Callable[[str, str, Path], None] | None = None,
        bei_abschluss: Callable[[str, str, Path], None] | None = None,
        status_fn: Callable[[str, str], dict[str, Any] | None] | None = None,
    ):
        self.geraete: tuple[Geraet, ...] = tuple(geraete)
        self.ablage = Ablage(
            ziel,
            max_datei_bytes=max_datei_bytes,
            bei_neuer_aufnahme=bei_neuer_aufnahme,
            bei_teil=bei_teil,
            bei_abschluss=bei_abschluss,
        )
        self._status_fn = status_fn
        self._adresse = (adresse, port)
        self._server: _Server | None = None
        self._faden: threading.Thread | None = None
        self._kontakte: dict[str, Kontakt] = {}
        self._kontakte_sperre = threading.Lock()
        self._jetzt: Callable[[], float] = time.time

    def status(self, geraet: str, datei: str) -> Antwort:
        """``GET /api/v1/aufnahmen/<datei>/status``: Wie weit ist die Verarbeitung?

        ``zustand`` ist einer aus ``live_service.ZUSTAENDE`` oder ``unbekannt`` (nichts bekannt,
        etwa nach einem Neustart der Software oder ohne Live-Verarbeitung)."""
        if not dateiname_gueltig(datei):
            return _fehler(400, "Ungueltiger Dateiname.")
        eintrag = self._status_fn(geraet, datei) if self._status_fn is not None else None
        return Antwort(200, eintrag if eintrag is not None else {"zustand": "unbekannt"})

    def kontakte(self) -> dict[str, Kontakt]:
        """Letzter Kontakt je Geraetename (seit dem Start des Dienstes)."""
        with self._kontakte_sperre:
            return dict(self._kontakte)

    def kontakt_merken(self, name: str, geraete_id: str | None, firmware: str | None, adresse: str) -> None:
        neu = Kontakt(geraete_id, firmware, adresse, self._jetzt())
        with self._kontakte_sperre:
            alt = self._kontakte.get(name)
            self._kontakte[name] = neu
        # Nur Aenderungen protokollieren: Das Geraet fragt alle paar Sekunden an.
        if alt is None or (alt.geraete_id, alt.firmware, alt.adresse) != (geraete_id, firmware, adresse):
            logger.info(
                "Geraet %s: Id %s, Firmware %s, Adresse %s", name, geraete_id or "-", firmware or "-", adresse
            )
        if alt is not None and alt.geraete_id and geraete_id and alt.geraete_id != geraete_id:
            logger.warning(
                "Das Token von %s kommt jetzt von einem anderen Geraet (%s statt %s) -- kopiert oder getauscht?",
                name,
                geraete_id,
                alt.geraete_id,
            )

    @property
    def laeuft(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        """Der tatsaechlich belegte Port (bei Port 0 vom System vergeben)."""
        if self._server is None:
            return self._adresse[1]
        return int(self._server.server_address[1])

    def starten(self) -> None:
        if self._server is not None:
            return
        self.ablage.ziel.mkdir(parents=True, exist_ok=True)
        entfernt = self.ablage.aufraeumen()
        if entfernt:
            logger.info("%d alte Teilstaende im Empfang entfernt", entfernt)
        self._server = _Server(self._adresse, self)
        self._faden = threading.Thread(target=self._server.serve_forever, name="geraete-empfang", daemon=True)
        self._faden.start()
        logger.info(
            "Empfang fuer Aufnahmegeraete auf Port %d (%d Geraete) -> %s", self.port, len(self.geraete), self.ablage.ziel
        )

    def stoppen(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._faden is not None:
            self._faden.join(timeout=5)
            self._faden = None
