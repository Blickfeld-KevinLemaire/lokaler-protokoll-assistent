"""Live-Verarbeitung waehrend einer Geraeteaufnahme und Status fuers Geraet.

Ein Aufnahmegeraet (``GERAETE-SCHNITTSTELLE.md``) schickt seine Aufnahme
waehrend der Aufnahme in kleinen Stuecken; die Software haengt sie an eine
wachsende Datei an. Dieses Modul nutzt die Zeit bis zum Ende der Aufnahme:

* :class:`LiveTranskription` transkribiert die wachsende Datei **laufend** mit
  einem gleitenden Fenster. Sobald genug neues Audio da ist (ca. 20 s), wird vom
  letzten sicheren Punkt bis jetzt transkribiert. Alles, was Whisper dabei sicher
  abgeschlossen hat, gilt als *bestaetigt*; das letzte Segment am Fensterende kann
  abgeschnitten sein und wird beim naechsten Durchlauf neu mitgerechnet. So waechst
  ein Transkript mit ca. 20 bis 40 s Verzoegerung, ohne zerhackte Woerter.
  Beim Ende der Aufnahme fehlen nur die letzten Sekunden: Die Verarbeitung der
  fertigen Datei uebernimmt die bestaetigten Segmente
  (``PipelineSettings.vorab_live``) und transkribiert nur den Rest.
* :class:`StatusRegister` haelt fest, wie weit die Verarbeitung je Aufnahme ist
  (``empfang``, ``wartet``, ``transkription``, ``auswertung``, ``fertig``,
  ``fehler``). Das Geraet fragt den Stand ab
  (``GET /api/v1/aufnahmen/<Name>/status``) und zeigt am Ende
  "Transkription erfolgreich".

Ohne Qt und ohne schwere Pakete: Transkribierer und Audio-Schnitt werden
uebergeben (:func:`cpu_transkribierer_fabrik`, :func:`standard_extrahieren`
sind die echten), die Tests ersetzen sie. Das Sprachmodell laeuft bewusst auf
dem **Prozessor**: Whisper (ca. 3 GB) und das 8B-Sprachmodell (ca. 7 GB)
passen zusammen nicht in 8 GB Grafikspeicher (``firmware/docs/messung-phase0.md``).
Whisper schafft auf dem Prozessor ca. das Dreifache der Echtzeit; die Fenster
sind also schneller transkribiert, als neues Audio ankommt.
"""

from __future__ import annotations

import contextlib
import gc
import hashlib
import json
import logging
import queue
import shutil
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from protokoll_assistent.services import merge_service, ogg_opus

if TYPE_CHECKING:  # pragma: no cover - nur fuer die Typpruefung
    from protokoll_assistent.services.live_auswertung_service import LiveAuswertung

logger = logging.getLogger(__name__)

# Zustaende, die ein Geraet ueber ``/status`` zu sehen bekommt.
EMPFANG = "empfang"  # Die Aufnahme laeuft noch (oder das Ende steht aus).
WARTET = "wartet"  # Ende da, die Verarbeitung ist eingereiht.
TRANSKRIPTION = "transkription"
# Nur fuer Geraete, die eine Rueckfrage wuenschen (``X-Rueckfrage``): Das Transkript steht, die Zusammenfassung
# wartet auf die Freigabe am Geraet (``POST .../zusammenfassung``).
TRANSKRIPT = "transkript"
AUSWERTUNG = "auswertung"
FERTIG = "fertig"
FEHLER = "fehler"
ZUSTAENDE = (EMPFANG, WARTET, TRANSKRIPTION, TRANSKRIPT, AUSWERTUNG, FERTIG, FEHLER)

# So viel neues Audio (seit dem letzten sicheren Punkt und seit dem letzten Durchlauf) muss da sein, bevor
# ein Fenster transkribiert wird. Kleiner = geringere Verzoegerung, aber mehr Rechenaufwand fuer das Neu-
# Mitrechnen des unsicheren Endes.
NEU_MIN_SEKUNDEN = 20.0
# Laengstes Fenster. Findet Whisper in einem Fenster kein sicher abgeschlossenes Segment (ein langer
# Monolog), waechst das Fenster mit jedem Durchlauf bis hierhin; dann gilt alles darin als bestaetigt.
FENSTER_MAX_SEKUNDEN = 45.0
# Von der Dauer der wachsenden Datei wird so viel abgezogen: Das Ende kann noch nicht gesichert sein.
ABSTAND_SEKUNDEN = 0.5
# Endet das letzte Segment weniger als so weit vor dem Fensterende, kann es abgeschnitten sein.
ENDE_TOLERANZ_SEKUNDEN = 1.5
# Fenster ohne jede Sprache: so weit wird trotzdem vorgerueckt (eine Sekunde Reserve fuer einen Wortanfang).
STILLE_RESERVE_SEKUNDEN = 1.0
# Aufgegebene Aufnahmen (das Geraet kam nie zum Ende) raeumt der Start weg.
STAGING_MAX_ALTER_SEKUNDEN = 7 * 24 * 3600
# So lange wartet der Abschluss einer Aufnahme hoechstens auf eine noch laufende Anfrage der Teilauswertung.
AUSWERTUNG_WARTEN_SEKUNDEN = 300.0
ENDUNGEN = (".opus", ".ogg")

TranskribiererFabrik = Callable[[], Callable[[Path], list[dict[str, Any]]]]
ExtrahierFn = Callable[[Path, Path, float, float], Any]
DauerFn = Callable[[Path], float | None]
# (Geraet, Datei, bisheriger Text, bestaetigt bis [s]); laeuft im Arbeitsfaden
AenderungsFn = Callable[[str, str, str, float], None]


# --------------------------------------------------------------------------
# Status fuer das Geraet
# --------------------------------------------------------------------------
class StatusRegister:
    """Stand der Verarbeitung je Aufnahme (Geraet + Dateiname des Geraets).

    Wird aus mehreren Faeden benutzt (Oberflaeche, Live-Arbeiter, HTTP)."""

    def __init__(self, *, max_eintraege: int = 200, jetzt: Callable[[], float] = time.time):
        self._eintraege: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._sperre = threading.Lock()
        self._max = max_eintraege
        self._jetzt = jetzt

    def setze(
        self, geraet: str, datei: str, zustand: str, fortschritt: float | None = None, meldung: str = ""
    ) -> None:
        if zustand not in ZUSTAENDE:
            raise ValueError(f"Unbekannter Zustand: {zustand}")
        eintrag: dict[str, Any] = {"zustand": zustand}
        if fortschritt is not None:
            eintrag["fortschritt"] = round(min(max(fortschritt, 0.0), 1.0), 3)
        if meldung:
            eintrag["meldung"] = meldung
        eintrag["aktualisiert"] = int(self._jetzt())
        with self._sperre:
            self._eintraege[(geraet, datei)] = eintrag
            self._eintraege.move_to_end((geraet, datei))
            while len(self._eintraege) > self._max:
                self._eintraege.popitem(last=False)

    def hole(self, geraet: str, datei: str) -> dict[str, Any] | None:
        with self._sperre:
            eintrag = self._eintraege.get((geraet, datei))
            return dict(eintrag) if eintrag is not None else None


@dataclass(frozen=True)
class Wunsch:
    """Was ein Geraet fuer eine Aufnahme angegeben hat: Auftrag (Name einer Vorlage) und ob es nach dem
    Transkript fragen will, ob die Zusammenfassung erstellt werden soll."""

    auftrag: str | None = None
    rueckfrage: bool = False


class WunschRegister:
    """Wuensche je Aufnahme (Geraet + Dateiname des Geraets); aus mehreren Faeden benutzt."""

    def __init__(self, *, max_eintraege: int = 200):
        self._eintraege: OrderedDict[tuple[str, str], Wunsch] = OrderedDict()
        self._sperre = threading.Lock()
        self._max = max_eintraege

    def merke(self, geraet: str, datei: str, auftrag: str | None, rueckfrage: bool) -> None:
        """Ein spaeter fehlender Auftrag loescht den frueheren nicht (nicht jede Anfrage traegt die Kopfzeile)."""
        with self._sperre:
            alt = self._eintraege.get((geraet, datei), Wunsch())
            self._eintraege[(geraet, datei)] = Wunsch(auftrag or alt.auftrag, rueckfrage or alt.rueckfrage)
            self._eintraege.move_to_end((geraet, datei))
            while len(self._eintraege) > self._max:
                self._eintraege.popitem(last=False)

    def hole(self, geraet: str, datei: str) -> Wunsch | None:
        with self._sperre:
            return self._eintraege.get((geraet, datei))


# --------------------------------------------------------------------------
# Hilfen fuer Segmente
# --------------------------------------------------------------------------
def minuten_sekunden(sekunden: float) -> str:
    gesamt = max(0, int(sekunden))
    return f"{gesamt // 60:02d}:{gesamt % 60:02d}"


def vorschau_text(segmente: list[dict[str, Any]]) -> str:
    """Das bisherige Transkript als Text mit Zeitmarke je Segment (fuer die Anzeige waehrend der Aufnahme)."""
    zeilen = []
    for segment in segmente:
        text = str(segment.get("text", "")).strip()
        if text:
            zeilen.append(f"[{minuten_sekunden(float(segment.get('start', 0.0)))}] {text}")
    return "\n".join(zeilen)


def bestaetigen(
    segmente: list[dict[str, Any]], fenster_start: float, fenster_ende: float, *, erzwingen: bool
) -> tuple[list[dict[str, Any]], float]:
    """Welche Segmente eines Fensters sind sicher, und bis wohin ist die Aufnahme damit abgedeckt?

    ``segmente`` haben globale Zeitstempel und liegen im Fenster ``[fenster_start, fenster_ende]``.
    Liefert ``(bestaetigte Segmente, neuer sicherer Punkt)``; der Punkt ist nie kleiner als
    ``fenster_start``. Kein Fortschritt ist ``([], fenster_start)``.

    * Keine Sprache im Fenster: Der Punkt rueckt bis kurz vor das Fensterende vor.
    * Das letzte Segment endet knapp vor dem Fensterende: Es kann abgeschnitten sein und
      bleibt unbestaetigt (``erzwingen`` bestaetigt es trotzdem: das Fenster ist schon so
      lang wie erlaubt, sonst kaeme ein langer Monolog nie voran)."""
    if not segmente:
        return [], max(fenster_start, fenster_ende - STILLE_RESERVE_SEKUNDEN)
    letztes = segmente[-1]
    unvollstaendig = (fenster_ende - float(letztes["end"])) < ENDE_TOLERANZ_SEKUNDEN
    fest = segmente[:-1] if (unvollstaendig and not erzwingen) else segmente
    if not fest:
        return [], fenster_start
    return fest, max(fenster_start, float(fest[-1]["end"]))


# --------------------------------------------------------------------------
# Live-Transkription
# --------------------------------------------------------------------------
@dataclass
class _Sitzung:
    geraet: str
    datei: str
    teil: Path
    ordner: Path
    bestaetigt_bis: float = 0.0
    letzte_dauer: float = 0.0  # Dauer der Datei beim letzten Durchlauf: ohne neues Audio kein neuer Versuch
    segmente: list[dict[str, Any]] = field(default_factory=list)
    ende: bool = False
    ziel: Path | None = None
    bereit: Callable[[], None] | None = None
    # Eindeutig je Upload (nicht je Dateiname): Ein Geraet kann denselben Namen ein zweites Mal hochladen --
    # nach einem verworfenen Teilstand (422), nach einer verlorenen Bestaetigung oder mit neu begonnener Zaehlung.
    kennung: str = ""


class LiveTranskription:
    """Transkribiert eine wachsende Aufnahme laufend und haelt die bestaetigten Segmente.

    Alle Aufrufe von aussen kehren sofort zurueck (sie kommen aus HTTP- und
    Oberflaechenfaeden); gearbeitet wird in einem eigenen Faden, Fenster fuer Fenster,
    nie parallel -- der Prozessor gehoert dem Whisper-Modell."""

    def __init__(
        self,
        arbeitsordner: Path,
        transkribierer_fabrik: TranskribiererFabrik,
        *,
        status: StatusRegister | None = None,
        bei_aenderung: AenderungsFn | None = None,
        dauer_fn: DauerFn = ogg_opus.opus_dauer_sekunden,
        extrahieren: ExtrahierFn | None = None,
        neu_min: float = NEU_MIN_SEKUNDEN,
        fenster_max: float = FENSTER_MAX_SEKUNDEN,
        auswertung: LiveAuswertung | None = None,
        auftrag_fn: Callable[[str, str], str | None] | None = None,
    ):
        self._auswertung = auswertung
        # (Geraet, Datei) -> Text des Auftrags, den das Geraet gewaehlt hat (``None``: der aus den Einstellungen)
        self._auftrag_fn = auftrag_fn
        self._basis = arbeitsordner / "live"
        self._fabrik = transkribierer_fabrik
        self._status = status
        self._bei_aenderung = bei_aenderung
        self._dauer_fn = dauer_fn
        self._extrahieren = extrahieren or standard_extrahieren
        self._neu_min = neu_min
        self._fenster_max = fenster_max
        # Alle Sitzungen nach ihrer Kennung; dazu je "Geraet/Datei" die Sitzung des laufenden Uploads. Eine
        # abgeschlossene Sitzung verliert diese Zuordnung (sie wartet nur noch auf die Verarbeitung ihrer Datei):
        # Ein spaeterer Upload unter demselben Namen beginnt immer eine neue.
        self._sitzungen: dict[str, _Sitzung] = {}
        self._aktuell: dict[str, str] = {}
        self._zaehler = 0
        self._sperre = threading.Lock()
        self._vorgemerkt: set[str] = set()
        self._warte: queue.Queue[str | None] = queue.Queue()
        self._transkribierer: Callable[[Path], list[dict[str, Any]]] | None = None
        self._deaktiviert = False
        self._stopp = False
        self._faden: threading.Thread | None = None
        self.aufraeumen()

    # ------------------------------------------------------------------
    # Von aussen (HTTP- und Oberflaechenfaeden)
    # ------------------------------------------------------------------
    def teil_gewachsen(self, geraet: str, datei: str, pfad: Path) -> None:
        """Ein Stueck der Aufnahme ist angekommen (die Datei ist ``pfad``)."""
        if self._deaktiviert or not datei.lower().endswith(ENDUNGEN):
            return
        schluessel = self._schluessel(geraet, datei)
        with self._sperre:
            kennung = self._aktuell.get(schluessel)
            sitzung = self._sitzungen.get(kennung) if kennung is not None else None
            if sitzung is None:
                self._zaehler += 1
                kennung = f"{schluessel}#{self._zaehler}"
                ordner = self._basis / hashlib.sha256(f"{kennung}|{time.time_ns()}".encode()).hexdigest()[:16]
                sitzung = _Sitzung(geraet, datei, pfad, ordner, kennung=kennung)
                self._sitzungen[kennung] = sitzung
                self._aktuell[schluessel] = kennung
            sitzung.teil = pfad
        self._anstossen(sitzung.kennung)

    def verwerfen(self, geraet: str, datei: str) -> None:
        """Der laufende Upload unter diesem Namen gilt nicht mehr: Das Geraet beginnt ihn von vorn (Byte 0,
        etwa nach einem verworfenen Teilstand) oder er war eine Wiederholung einer schon abgelegten Aufnahme.
        Ohne das uebernaehme die naechste Aufnahme unter demselben Namen das Transkript der vorigen.

        Eine schon abgeschlossene Sitzung bleibt unberuehrt: Ihre Datei wird gerade verarbeitet."""
        schluessel = self._schluessel(geraet, datei)
        with self._sperre:
            kennung = self._aktuell.pop(schluessel, None)
            sitzung = self._sitzungen.pop(kennung, None) if kennung is not None else None
        if sitzung is None:
            return
        if self._auswertung is not None:
            self._auswertung.freigeben(sitzung.kennung)
        shutil.rmtree(sitzung.ordner, ignore_errors=True)

    def abgeschlossen(self, geraet: str, datei: str, ziel: Path, bei_bereit: Callable[[], None]) -> None:
        """Die Aufnahme ist vollstaendig und liegt als ``ziel`` vor. ``bei_bereit``
        wird aufgerufen, sobald das gerade laufende Fenster (und eine gerade laufende
        Anfrage der Teilauswertung) fertig ist -- davor darf die Verarbeitung der fertigen
        Datei nicht beginnen, sonst rechneten beide dieselben Sekunden. Es wird kein neues
        Fenster mehr angefangen."""
        schluessel = self._schluessel(geraet, datei)
        with self._sperre:
            kennung = self._aktuell.pop(schluessel, None)
            sitzung = self._sitzungen.get(kennung) if kennung is not None else None
            if sitzung is not None:
                sitzung.ende = True
                sitzung.ziel = ziel
                sitzung.bereit = bei_bereit
        if sitzung is None:
            self._aufrufen(bei_bereit)
            return
        if self._auswertung is not None:
            self._auswertung.beenden(sitzung.kennung)  # keine neue Anfrage mehr; die fertige Auswertung uebernimmt
        self._anstossen(sitzung.kennung)

    def auswertung_fuer(self, ziel: Path, warten: float = 0.0) -> dict[str, dict[str, str]] | None:
        """Die schon waehrend der Aufnahme berechneten Teilergebnisse der Auswertung (siehe
        ``live_auswertung_service``); mit ``warten`` Sekunden Geduld, falls gerade eine Anfrage laeuft."""
        if self._auswertung is None:
            return None
        with self._sperre:
            kennung = next(
                (
                    k
                    for k, sitzung in self._sitzungen.items()
                    if sitzung.ziel is not None and _gleich(sitzung.ziel, ziel)
                ),
                None,
            )
        return self._auswertung.vorab_fuer(kennung, warten) if kennung is not None else None

    def vorab_fuer(self, ziel: Path) -> dict[str, Any] | None:
        """Bestaetigte Segmente der Aufnahme ``ziel``: ``{"bestaetigt_bis": Sekunden, "segmente": [...]}``
        (globale Zeitstempel); ``None``, wenn es nichts Brauchbares gibt."""
        with self._sperre:
            for sitzung in self._sitzungen.values():
                if sitzung.ziel is not None and _gleich(sitzung.ziel, ziel):
                    if not sitzung.segmente:
                        return None
                    return {"bestaetigt_bis": sitzung.bestaetigt_bis, "segmente": [dict(s) for s in sitzung.segmente]}
        return None

    def freigeben(self, ziel: Path) -> None:
        """Die Aufnahme ist verarbeitet: Zwischenstand loeschen."""
        with self._sperre:
            gefunden = [
                schluessel
                for schluessel, sitzung in self._sitzungen.items()
                if sitzung.ziel is not None and _gleich(sitzung.ziel, ziel)
            ]
            entfernt = [self._sitzungen.pop(schluessel) for schluessel in gefunden]
        for schluessel in gefunden:
            if self._auswertung is not None:
                self._auswertung.freigeben(schluessel)
        for sitzung in entfernt:
            shutil.rmtree(sitzung.ordner, ignore_errors=True)

    def stoppen(self) -> None:
        self._stopp = True
        if self._auswertung is not None:
            self._auswertung.stoppen()
        faden = self._faden
        if faden is not None:
            self._warte.put(None)
            faden.join(timeout=10)
            self._faden = None

    def warte_bis_fertig(self, zeitlimit: float = 10.0) -> bool:
        """Fuer Tests: wartet, bis der Arbeiter alles abgearbeitet hat."""
        ende = time.monotonic() + zeitlimit
        while time.monotonic() < ende:
            if self._warte.unfinished_tasks == 0:
                return True
            time.sleep(0.005)
        return False

    @property
    def deaktiviert(self) -> bool:
        """``True``, wenn die Live-Transkription nicht moeglich war (kein Whisper)."""
        return self._deaktiviert

    def aufraeumen(self, max_alter: float = STAGING_MAX_ALTER_SEKUNDEN) -> int:
        grenze = time.time() - max_alter
        entfernt = 0
        try:
            ordner = list(self._basis.iterdir())
        except OSError:
            return 0
        for pfad in ordner:
            with contextlib.suppress(OSError):
                if pfad.is_dir() and pfad.stat().st_mtime < grenze:
                    shutil.rmtree(pfad, ignore_errors=True)
                    entfernt += 1
        return entfernt

    # ------------------------------------------------------------------
    # Arbeiter
    # ------------------------------------------------------------------
    @staticmethod
    def _schluessel(geraet: str, datei: str) -> str:
        return f"{geraet}/{datei}"

    @staticmethod
    def _aufrufen(funktion: Callable[[], None]) -> None:
        try:
            funktion()
        except Exception:  # Eine Meldung nach aussen darf den Arbeiter nicht stoppen.
            logger.exception("Rueckruf der Live-Transkription fehlgeschlagen")

    def _anstossen(self, kennung: str) -> None:
        with self._sperre:
            if self._faden is None and not self._stopp:
                self._faden = threading.Thread(target=self._lauf, name="live-transkription", daemon=True)
                self._faden.start()
            if kennung in self._vorgemerkt:
                return
            self._vorgemerkt.add(kennung)
        self._warte.put(kennung)

    def _gilt(self, sitzung: _Sitzung) -> bool:
        """Ist die Sitzung noch registriert (nicht inzwischen verworfen oder freigegeben)?"""
        with self._sperre:
            return self._sitzungen.get(sitzung.kennung) is sitzung

    def _lauf(self) -> None:
        while True:
            schluessel = self._warte.get()
            try:
                if schluessel is None:
                    return
                with self._sperre:
                    self._vorgemerkt.discard(schluessel)
                try:
                    self._bearbeite(schluessel)
                except Exception:
                    logger.exception("Live-Transkription von %s fehlgeschlagen", schluessel)
                if self._warte.qsize() == 0:
                    self._modell_freigeben()
            finally:
                self._warte.task_done()

    def _modell_freigeben(self) -> None:
        """Ist keine Aufnahme mehr offen, das Whisper-Modell aus dem Speicher nehmen."""
        with self._sperre:
            offen = any(not sitzung.ende for sitzung in self._sitzungen.values())
        if not offen and self._transkribierer is not None:
            self._transkribierer = None
            gc.collect()

    def _bearbeite(self, kennung: str) -> None:
        with self._sperre:
            sitzung = self._sitzungen.get(kennung)
        if sitzung is None:
            return
        while not self._stopp and not sitzung.ende and not self._deaktiviert and self._gilt(sitzung):
            if not self._naechstes_fenster(sitzung):
                break
        if sitzung.ende:
            with self._sperre:
                bereit, sitzung.bereit = sitzung.bereit, None
            if bereit is not None:
                if self._auswertung is not None:
                    # Eine noch laufende Anfrage ans Sprachmodell erst fertig werden lassen: Die Verarbeitung der
                    # fertigen Datei laedt gleich Whisper auf die Grafikkarte (siehe 'LiveAuswertung.beenden').
                    self._auswertung.warte_auf_leerlauf(kennung, AUSWERTUNG_WARTEN_SEKUNDEN)
                self._aufrufen(bereit)

    def _naechstes_fenster(self, sitzung: _Sitzung) -> bool:
        """Transkribiert das naechste Fenster, wenn genug neues Audio da ist.
        ``False``, wenn nichts zu tun war (oder es nicht ging)."""
        dauer = self._dauer_fn(sitzung.teil)
        if dauer is None:
            return False
        start = sitzung.bestaetigt_bis
        # Genug Audio seit dem sicheren Punkt UND seit dem letzten Durchlauf: Sonst liefe ein Fenster, in dem
        # nichts sicher war, in einer Schleife immer wieder ueber dieselben Sekunden.
        if dauer - start < self._neu_min or dauer - sitzung.letzte_dauer < self._neu_min:
            return False
        ende = min(dauer - ABSTAND_SEKUNDEN, start + self._fenster_max)
        if ende - start < 1.0:
            return False

        sitzung.ordner.mkdir(parents=True, exist_ok=True)
        momentaufnahme = sitzung.ordner / "quelle.opus"
        wav = sitzung.ordner / "fenster.wav"
        try:
            # Eine Kopie: Die Datei waechst weiter, und beim Abschluss wird sie umbenannt.
            shutil.copyfile(sitzung.teil, momentaufnahme)
            self._extrahieren(momentaufnahme, wav, start, ende)
            if self._transkribierer is None:
                try:
                    self._transkribierer = self._fabrik()
                except Exception as fehler:
                    # Ohne Whisper gibt es keine Live-Transkription -- die Verarbeitung der fertigen Datei holt
                    # alles nach.
                    logger.warning("Live-Transkription nicht moeglich (Whisper nicht ladbar): %s", fehler)
                    self._deaktiviert = True
                    return False
            lokal = self._transkribierer(wav)
        except FileNotFoundError:
            return False  # Die Aufnahme wurde eben abgeschlossen (umbenannt).
        except Exception as fehler:
            # Ein einzelnes Fenster ging schief (Schnitt, eine kurz gesperrte Datei ...): nicht fuer immer
            # aufgeben, sondern erst mit neuem Audio wieder versuchen.
            logger.warning("Live-Fenster von %s uebersprungen: %s", sitzung.datei, fehler)
            sitzung.letzte_dauer = dauer
            return False
        finally:
            for pfad in (momentaufnahme, wav):
                with contextlib.suppress(OSError):
                    pfad.unlink()

        erzwingen = (ende - start) >= self._fenster_max - 1e-6
        global_ = merge_service.to_global_segments(lokal, start)
        fest, neuer_punkt = bestaetigen(global_, start, ende, erzwingen=erzwingen)
        if neuer_punkt > start:
            with self._sperre:
                sitzung.segmente.extend(fest)
                sitzung.bestaetigt_bis = neuer_punkt
            sitzung.letzte_dauer = 0.0  # Fortschritt: auch ein Rueckstand wird gleich weiter abgearbeitet
            self._sichern(sitzung)
            self._melden(sitzung)
        else:
            # Nichts war sicher (ein langer Satz am Fensterende): erst bei neuem Audio noch einmal versuchen,
            # sonst liefe dasselbe Fenster in einer Schleife immer wieder.
            sitzung.letzte_dauer = dauer
        return True

    def _sichern(self, sitzung: _Sitzung) -> None:
        """Den Stand neben dem Zwischenspeicher ablegen (zur Fehlersuche, nicht zum Fortsetzen)."""
        with contextlib.suppress(OSError):
            (sitzung.ordner / "live.json").write_text(
                json.dumps(
                    {"bestaetigt_bis": sitzung.bestaetigt_bis, "segmente": sitzung.segmente}, ensure_ascii=False
                ),
                encoding="utf-8",
            )

    def _melden(self, sitzung: _Sitzung) -> None:
        if not self._gilt(sitzung):
            return  # inzwischen verworfen: nichts mehr melden
        if self._auswertung is not None and not sitzung.ende:
            with self._sperre:
                kopie = [dict(s) for s in sitzung.segmente]
                punkt = sitzung.bestaetigt_bis
            # Die Auswertung rechnet in ihrem eigenen Faden: Das Sprachmodell auf der Grafikkarte, Whisper auf dem Prozessor
            auftrag = self._auftrag_fn(sitzung.geraet, sitzung.datei) if self._auftrag_fn is not None else None
            self._auswertung.fortschritt(sitzung.kennung, kopie, punkt, auftrag)
        vorher = self._status.hole(sitzung.geraet, sitzung.datei) if self._status is not None else None
        # Nur "empfang" melden, solange nichts Weiteres bekannt ist: Ein wiederholter Upload einer schon
        # abgelegten Aufnahme (die Bestaetigung ging verloren) darf ein "fertig" nicht zuruecknehmen -- das Geraet
        # zeigte sonst nie "Transkription erfolgreich". Den Stand einer neuen Aufnahme setzt ihr Abschluss.
        if self._status is not None and not sitzung.ende and (vorher is None or vorher.get("zustand") == EMPFANG):
            ausgewertet = self._auswertung.anzahl(sitzung.kennung) if self._auswertung is not None else 0
            zusatz = f", {ausgewertet} {'Abschnitt' if ausgewertet == 1 else 'Abschnitte'} ausgewertet" if ausgewertet else ""
            self._status.setze(
                sitzung.geraet,
                sitzung.datei,
                EMPFANG,
                meldung=f"Live: bis {minuten_sekunden(sitzung.bestaetigt_bis)} transkribiert{zusatz}",
            )
        if self._bei_aenderung is not None:
            with self._sperre:
                text = vorschau_text(sitzung.segmente)
                punkt = sitzung.bestaetigt_bis
            try:
                self._bei_aenderung(sitzung.geraet, sitzung.datei, text, punkt)
            except Exception:  # Die Anzeige darf die Transkription nicht stoeren.
                logger.exception("Meldung der Live-Transkription fehlgeschlagen")


def _gleich(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


# --------------------------------------------------------------------------
# Die echten Bausteine (schwere Pakete erst beim Aufruf)
# --------------------------------------------------------------------------
def standard_extrahieren(quelle: Path, ziel_wav: Path, start: float, ende: float) -> Path:
    """Schneidet ``[start, ende]`` aus der (Opus-)Datei als 16-kHz-Mono-WAV."""
    from protokoll_assistent.services import ffmpeg_service

    ffmpeg_service.ensure_ffmpeg_on_path()
    return ffmpeg_service.extract_chunk_wav(quelle, ziel_wav, start, ende)


def cpu_transkribierer_fabrik(
    whisper_modell: str, sprache: str | None, erlaube_download: bool
) -> TranskribiererFabrik:
    """Laedt Whisper auf dem **Prozessor** (``int8``) und liefert die Funktion,
    die ein Fenster-WAV in Segmente mit Fenster-Zeitstempeln umwandelt."""

    def fabrik() -> Callable[[Path], list[dict[str, Any]]]:
        from protokoll_assistent.services import model_service, transcription_service

        geraet, rechenart = model_service.get_device_and_compute_type("cpu")
        model_service.prepare_offline_mode(erlaube_download)
        modell = transcription_service.load_whisper_model(whisper_modell, geraet, rechenart, sprache)

        def transkribiere(wav: Path) -> list[dict[str, Any]]:
            audio = transcription_service.load_audio_array(wav)
            ergebnis = transcription_service.transcribe_audio_array(modell, audio, 4, sprache)
            return transcription_service.segments_to_plain(ergebnis)

        return transkribiere

    return fabrik
