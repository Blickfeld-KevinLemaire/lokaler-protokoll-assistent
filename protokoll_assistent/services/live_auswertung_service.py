"""Teilauswertung waehrend der Aufnahme: Stufe 1 und 2 der Auswertung schon rechnen, solange das Meeting laeuft.

Nach dem Ende einer Aufnahme ist die Auswertung durch das Sprachmodell der groesste Posten der Wartezeit
(gemessen ca. 84 % der Verarbeitungszeit, ``firmware/docs/messung-phase0.md``). Sie arbeitet in Stufen
(``protocol_service``): Stufe 1 wendet den Auftrag auf jeden 600-s-Abschnitt an, Stufe 2 fuehrt benachbarte
Teilergebnisse gruppenweise zusammen, Stufe 3 erstellt das Endergebnis. Dieses Modul rechnet Stufe 1 fuer jeden
Abschnitt, sobald dessen Text komplett vorliegt (die Live-Transkription ``live_service`` hat ihn bestaetigt), und
Stufe 2 fuer jede Gruppe, die feststeht. Am Ende fehlen nur noch die letzten Abschnitte und die Stufe 3.

Das Sprachmodell laeuft dabei auf der Grafikkarte, Whisper auf dem Prozessor -- beide gleichzeitig (deshalb
rechnet die Live-Transkription nicht auf der Grafikkarte; sie teilen sich den Speicher nicht).

**Wiederverwendung nur bei gleicher Eingabe.** Jedes Ergebnis wird unter der Kennung seiner kompletten Eingabe
(Modell, Auftrag, Prompt mit Text) gemerkt (``protocol_service.eingabe_kennung``). Die fertige Auswertung
uebernimmt es nur, wenn ihre Anfrage dieselbe Kennung hat (``protocol_service.vorab_ergebnisse_ablegen``);
sonst fragt sie neu. Damit die Texte uebereinstimmen, bekommt das Modell hier wie in der fertigen Auswertung den
reinen Fliesstext ohne Sprecherangaben (``PipelineSettings``/``ProtocolSettings.ohne_sprecher``): Die
Sprechertrennung entsteht erst am Ende der Aufnahme.

Ohne Qt: Die Verbindung zum Sprachmodell (Ollama oder API) kommt als Funktion von aussen.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from protokoll_assistent.services import chunking_service, pipeline_service, protocol_service

logger = logging.getLogger(__name__)

# Nach einem Fehler (Ollama nicht erreichbar ...) so lange nicht erneut versuchen.
FEHLER_PAUSE_SEKUNDEN = 60.0


@dataclass(frozen=True)
class AuswertungsEinstellungen:
    """Womit ausgewertet wird. Muss zu dem passen, womit die fertige Auswertung spaeter laeuft."""

    auftrag: str  # Systemprompt (leer erlaubt: das Modell fasst frei zusammen)
    modell: str | None  # wie ``ProtocolSettings.protokoll_modell_kennung or ollama_model``
    generate_fn: Callable[[str, str], str]
    gruppengroesse: int = 4
    # Laenge der Abschnitte (Sekunden); muss zu ``ProtocolSettings.abschnitt_sekunden`` der fertigen Auswertung passen.
    abschnitt_sekunden: float = chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS


EinstellungenFn = Callable[[], AuswertungsEinstellungen | None]


@dataclass
class _Stand:
    segmente: list[dict[str, Any]] = field(default_factory=list)
    bestaetigt_bis: float = 0.0
    ende: bool = False
    naechster: int = 0  # Index des naechsten Abschnitts, der noch nicht ausgewertet wurde
    analysen: dict[int, str] = field(default_factory=dict)  # Abschnitt -> Teilergebnis (Stufe 1)
    stufe1: dict[str, str] = field(default_factory=dict)  # Eingabekennung -> Ergebnis
    stufe2: dict[str, str] = field(default_factory=dict)
    naechster_versuch: float = 0.0
    in_arbeit: bool = False


class LiveAuswertung:
    """Rechnet Stufe 1 und 2 der Auswertung fuer wachsende Aufnahmen vorab (ein Arbeitsfaden, nie parallel:
    Das Sprachmodell bekommt immer nur eine Anfrage)."""

    def __init__(self, einstellungen_fn: EinstellungenFn, *, jetzt: Callable[[], float] = time.monotonic):
        self._einstellungen_fn = einstellungen_fn
        self._jetzt = jetzt
        self._staende: dict[str, _Stand] = {}
        self._vorgemerkt: set[str] = set()
        self._bedingung = threading.Condition()
        self._warte: queue.Queue[str | None] = queue.Queue()
        self._faden: threading.Thread | None = None
        self._stopp = False

    # ------------------------------------------------------------------
    # Von aussen
    # ------------------------------------------------------------------
    def fortschritt(self, schluessel: str, segmente: list[dict[str, Any]], bestaetigt_bis: float) -> None:
        """Die Live-Transkription hat Segmente bestaetigt: alles bis ``bestaetigt_bis`` steht fest."""
        with self._bedingung:
            stand = self._staende.setdefault(schluessel, _Stand())
            if stand.ende:
                return
            stand.segmente = segmente
            stand.bestaetigt_bis = bestaetigt_bis
        self._anstossen(schluessel)

    def beenden(self, schluessel: str) -> None:
        """Die Aufnahme ist zu Ende: Es kommen keine neuen Segmente und keine neuen Anfragen mehr dazu. Eine
        gerade laufende Anfrage rechnet noch fertig; alle uebrigen Abschnitte uebernimmt die fertige Auswertung.

        Nicht parallel weiterrechnen: Die Verarbeitung der fertigen Datei laedt jetzt Whisper auf die
        Grafikkarte. Eine weitere Anfrage holte das Sprachmodell daneben zurueck -- genau die Lage, die auf
        6-GB-Karten "CUDA out of memory" ausloeste (``pipeline_service._grafikspeicher_fuer_whisper_freimachen``)."""
        with self._bedingung:
            stand = self._staende.get(schluessel)
            if stand is None:
                return
            stand.ende = True

    def warte_auf_leerlauf(self, schluessel: str, zeitlimit: float) -> None:
        """Wartet hoechstens ``zeitlimit`` Sekunden, bis keine Anfrage dieser Aufnahme mehr laeuft oder ansteht."""
        ende = self._jetzt() + zeitlimit
        with self._bedingung:
            self._warten_solange_beschaeftigt(schluessel, ende)

    def _warten_solange_beschaeftigt(self, schluessel: str, ende: float) -> None:
        """Erwartet die gehaltene ``_bedingung``."""
        stand = self._staende.get(schluessel)
        while (
            stand is not None and (stand.in_arbeit or schluessel in self._vorgemerkt) and self._jetzt() < ende
        ):
            self._bedingung.wait(timeout=max(0.01, min(0.5, ende - self._jetzt())))

    def vorab_fuer(self, schluessel: str, warten: float = 0.0) -> dict[str, dict[str, str]] | None:
        """Die fertigen Teilergebnisse ``{"stufe1": {Kennung: Text}, "stufe2": {...}}``; ``None``, wenn es keine gibt.

        Mit ``warten`` (Sekunden) wird gewartet, bis eine gerade laufende Anfrage ans Sprachmodell fertig ist --
        sonst rechnete die fertige Auswertung dasselbe noch einmal."""
        ende = self._jetzt() + warten
        with self._bedingung:
            stand = self._staende.get(schluessel)
            if stand is None:
                return None
            self._warten_solange_beschaeftigt(schluessel, ende)
            if not stand.stufe1 and not stand.stufe2:
                return None
            return {"stufe1": dict(stand.stufe1), "stufe2": dict(stand.stufe2)}

    def anzahl(self, schluessel: str) -> int:
        """Wie viele Abschnitte sind schon ausgewertet (fuer eine Anzeige)."""
        with self._bedingung:
            stand = self._staende.get(schluessel)
            return stand.naechster if stand is not None else 0

    def freigeben(self, schluessel: str) -> None:
        with self._bedingung:
            self._staende.pop(schluessel, None)

    def stoppen(self) -> None:
        self._stopp = True
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

    # ------------------------------------------------------------------
    # Arbeiter
    # ------------------------------------------------------------------
    def _anstossen(self, schluessel: str) -> None:
        with self._bedingung:
            if self._faden is None and not self._stopp:
                self._faden = threading.Thread(target=self._lauf, name="live-auswertung", daemon=True)
                self._faden.start()
            if schluessel in self._vorgemerkt:
                return
            self._vorgemerkt.add(schluessel)
        self._warte.put(schluessel)

    def _lauf(self) -> None:
        while True:
            schluessel = self._warte.get()
            try:
                if schluessel is None:
                    return
                with self._bedingung:
                    self._vorgemerkt.discard(schluessel)
                    stand = self._staende.get(schluessel)
                    if stand is not None:
                        stand.in_arbeit = True
                try:
                    if stand is not None:
                        self._bearbeite(stand)
                except Exception:
                    logger.exception("Live-Auswertung von %s fehlgeschlagen", schluessel)
                finally:
                    with self._bedingung:
                        if stand is not None:
                            stand.in_arbeit = False
                        self._bedingung.notify_all()
            finally:
                self._warte.task_done()

    def _bearbeite(self, stand: _Stand) -> None:
        if stand.ende or self._jetzt() < stand.naechster_versuch:
            return
        einstellungen = self._einstellungen_fn()
        if einstellungen is None:
            return
        try:
            while not self._stopp:
                if not self._naechster_abschnitt(stand, einstellungen):
                    break
        except Exception as fehler:
            # Sprachmodell nicht erreichbar, leere Antwort ... Die fertige Auswertung rechnet dann selbst.
            logger.warning("Teilauswertung waehrend der Aufnahme nicht moeglich: %s", fehler)
            stand.naechster_versuch = self._jetzt() + FEHLER_PAUSE_SEKUNDEN

    def _naechster_abschnitt(self, stand: _Stand, einstellungen: AuswertungsEinstellungen) -> bool:
        """Wertet den naechsten Abschnitt aus (Stufe 1), wenn sein Text komplett vorliegt, und danach alle
        Gruppen, die dadurch feststehen (Stufe 2). ``False``, wenn nichts zu tun war."""
        index = stand.naechster
        laenge = chunking_service.auswertungs_abschnitt(einstellungen.abschnitt_sekunden)
        schritt = laenge - chunking_service.DEFAULT_OVERLAP_SECONDS
        anfang = index * schritt
        ende = anfang + laenge
        with self._bedingung:
            if stand.ende or ende > stand.bestaetigt_bis:
                return False
            segmente = list(stand.segmente)
        plan = chunking_service.ChunkPlan(
            index=index,
            global_start=anfang,
            global_end=ende,
            overlap_with_previous=0.0 if index == 0 else chunking_service.DEFAULT_OVERLAP_SECONDS,
            is_first=index == 0,
            is_last=False,
        )
        auftrag = protocol_service.effektiver_systemprompt(einstellungen.auftrag)
        texte = pipeline_service.baue_protokoll_chunk_texte([plan], segmente, {}, False, fliesstext=True)
        if texte:  # ein Abschnitt ohne Text wird (wie in der fertigen Auswertung) nicht angefragt
            chunk = texte[0]
            prompt = protocol_service.build_stage1_prompt(
                index, str(chunk["start_str"]), str(chunk["end_str"]), str(chunk["text"])
            )
            ergebnis = protocol_service.generate_checked(
                prompt, auftrag, einstellungen.generate_fn, leer_erlaubt=True
            )
            kennung = protocol_service.eingabe_kennung(prompt, auftrag, einstellungen.modell)
            with self._bedingung:
                stand.stufe1[kennung] = ergebnis
                stand.analysen[index] = ergebnis
        with self._bedingung:
            stand.naechster = index + 1
        self._gruppen_zusammenfuehren(stand, einstellungen, auftrag)
        return True

    def _gruppen_zusammenfuehren(
        self, stand: _Stand, einstellungen: AuswertungsEinstellungen, auftrag: str
    ) -> None:
        with self._bedingung:
            ergebnisse = [
                stand.analysen[i] for i in range(stand.naechster) if i in stand.analysen and stand.analysen[i].strip()
            ]
        gruppen = protocol_service.gruppen_bilden(ergebnisse, einstellungen.gruppengroesse)
        for index, gruppe in enumerate(gruppen):
            if stand.ende or self._stopp:
                return  # siehe 'beenden'
            if len(gruppe) < 2 or not protocol_service.abschluss_der_gruppe_steht_fest(
                gruppen, index, einstellungen.gruppengroesse
            ):
                continue
            prompt = protocol_service.build_stage2_prompt(gruppe)
            kennung = protocol_service.eingabe_kennung(prompt, auftrag, einstellungen.modell)
            if kennung in stand.stufe2:
                continue
            ergebnis = protocol_service.generate_checked(prompt, auftrag, einstellungen.generate_fn)
            with self._bedingung:
                stand.stufe2[kennung] = ergebnis
