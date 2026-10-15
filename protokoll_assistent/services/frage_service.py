"""Fragen an eine Besprechung per Sprache, gestellt am Aufnahmegeraet.

Der Ablauf einer Frage (alles lokal, ein Arbeitsfaden, nie mehrere gleichzeitig -- Prozessor und Grafikkarte
gehoeren immer nur einer Frage):

1. ``verstehen``: Die gesprochene Frage wird in Text umgewandelt (Whisper).
2. ``antworten``: Das Sprachmodell beantwortet sie anhand des Transkripts und der Zusammenfassung dieser Aufnahme.
3. ``sprechen``: Die Antwort wird gesprochen (lokale Sprachsynthese) und als WAV bereitgestellt.

Das Geraet reicht die Frage ein (``einreichen``), fragt den Stand ab (``stand``) und holt am Ende den Ton (``ton``).
Die einzelnen Schritte kommen als Funktionen von aussen; dieses Modul kennt weder Whisper noch Ollama noch eine
Sprachsynthese und laesst sich mit Attrappen testen. Ohne Sprachausgabe endet die Frage mit der Antwort als Text.

Fragen und Antworten bleiben nur kurz im Speicher (``MAX_ALTER_SEKUNDEN``); nichts wird auf die Platte geschrieben,
ausser dem Ton der Frage, den die Spracherkennung als Datei braucht.
"""

from __future__ import annotations

import logging
import queue
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

VERSTEHEN = "verstehen"
ANTWORTEN = "antworten"
SPRECHEN = "sprechen"
FERTIG = "fertig"
FEHLER = "fehler"

MAX_EINTRAEGE = 20
MAX_ALTER_SEKUNDEN = 15 * 60
# Eine Frage ist kurz: 60 s WAV (16 kHz, 16 Bit) sind 1,9 MB.
MAX_FRAGE_BYTES = 3 * 1024 * 1024
ENDUNGEN = {".wav", ".opus", ".ogg"}
# Die Firmware haelt die Anzeige in 1024 Byte (VERMERK_FRAGE_ANZEIGE_MAX, mit Nullbyte); die Anzeige ist ASCII
ANZEIGE_MAX_ZEICHEN = 1000

# Erkennt die Frage: (Ton der Frage, Endung mit Punkt) -> Text
ErkennenFn = Callable[[bytes, str], str]
# Beantwortet sie: (Frage, Geraet, Dateiname der Aufnahme, Ausgabeart) -> Antworttext
AntwortFn = Callable[[str, str, str, str], str]
# Das Display bekommt die Antwort als Text; mit Ton wird sie zusaetzlich gesprochen
AUSGABE_ANZEIGE = "anzeige"
AUSGABE_TON = "ton"
# Macht den Antworttext fuers Display tauglich (ASCII)
AnzeigeFn = Callable[[str], str]
# Spricht die Antwort: Text -> WAV
SprechenFn = Callable[[str], bytes]
# Gibt es zu dieser Aufnahme schon etwas, wozu man fragen kann (Transkript)?
BereitFn = Callable[[str, str], bool]


class Ueberlastet(RuntimeError):
    """Es warten schon ``max_eintraege`` Fragen auf ihre Bearbeitung; jede haelt ihren Ton im Speicher."""


@dataclass
class _Frage:
    id: str
    geraet: str
    datei: str
    frage_ton: bytes
    endung: str
    zustand: str = VERSTEHEN
    frage: str = ""
    antwort: str = ""
    meldung: str = ""
    wav: bytes | None = None
    erstellt: float = 0.0
    fehler: str = ""
    ausgabe: str = AUSGABE_ANZEIGE
    anzeige: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class FragenDienst:
    def __init__(
        self,
        *,
        erkennen: ErkennenFn,
        antworten: AntwortFn,
        sprechen: SprechenFn | None = None,
        bereit: BereitFn | None = None,
        anzeige: AnzeigeFn | None = None,
        jetzt: Callable[[], float] = time.time,
        max_eintraege: int = MAX_EINTRAEGE,
        max_alter: float = MAX_ALTER_SEKUNDEN,
    ):
        self._erkennen = erkennen
        self._antworten = antworten
        self._sprechen = sprechen
        self._bereit = bereit
        self._anzeige = anzeige
        self._jetzt = jetzt
        self._max_eintraege = max_eintraege
        self._max_alter = max_alter
        self._fragen: dict[str, _Frage] = {}
        self._sperre = threading.Lock()
        self._warte: queue.Queue[str | None] = queue.Queue()
        self._faden: threading.Thread | None = None
        self._stopp = False

    # ------------------------------------------------------------------
    # Fuer das Geraet (HTTP-Faeden)
    # ------------------------------------------------------------------
    @property
    def spricht(self) -> bool:
        """Mit Sprachausgabe? Sonst endet eine Frage mit dem Text der Antwort."""
        return self._sprechen is not None

    def bereit_fuer(self, geraet: str, datei: str) -> bool:
        return True if self._bereit is None else bool(self._bereit(geraet, datei))

    def einreichen(self, geraet: str, datei: str, ton: bytes, endung: str, ausgabe: str = AUSGABE_ANZEIGE) -> str:
        """Nimmt eine Frage an und gibt ihre Kennung zurueck; die Bearbeitung laeuft im Hintergrund.

        ``ausgabe``: ``anzeige`` (Text fuers Display, Standard) oder ``ton`` (zusaetzlich gesprochen,
        wenn eine Sprachausgabe da ist). ``Ueberlastet``, wenn der Speicher schon voller unbearbeiteter Fragen ist."""
        if endung not in ENDUNGEN:
            raise ValueError(f"Unbekannte Endung: {endung}")
        if ausgabe not in (AUSGABE_ANZEIGE, AUSGABE_TON):
            raise ValueError(f"Unbekannte Ausgabe: {ausgabe}")
        frage = _Frage(
            id=secrets.token_hex(8), geraet=geraet, datei=datei, frage_ton=ton, endung=endung, ausgabe=ausgabe, erstellt=self._jetzt()
        )
        with self._sperre:
            self._aufraeumen()
            # Nur Fragen in Arbeit sind uebrig: nicht noch eine (mit bis zu 3 MB Ton) dazulegen.
            if len(self._fragen) >= self._max_eintraege:
                raise Ueberlastet("Es warten schon zu viele Fragen.")
            self._fragen[frage.id] = frage
        self._anstossen(frage.id)
        return frage.id

    def stand(self, geraet: str, frage_id: str) -> dict[str, Any] | None:
        """Der Stand fuer das Geraet; ``None``, wenn es die Frage nicht gibt (oder sie einem anderen Geraet gehoert)."""
        with self._sperre:
            frage = self._fragen.get(frage_id)
            if frage is None or frage.geraet != geraet:
                return None
            # Reihenfolge mit Absicht: Das Geraet liest in einen festen Puffer (6 KB). Was es braucht, steht vorn;
            # ``antwort`` (ungekuerzt) zuletzt -- wird sie abgeschnitten, fehlt dem Display nichts.
            daten: dict[str, Any] = {"zustand": frage.zustand}
            if frage.frage:
                # Die Schriften der Geraete haben keine Umlaute: die Frage wie die Anzeige als ASCII
                daten["frage"] = self._anzeige(frage.frage) if self._anzeige is not None else frage.frage
            if frage.anzeige:
                daten["anzeige"] = frage.anzeige
            if frage.meldung:
                daten["meldung"] = frage.meldung
            if frage.zustand == FERTIG:
                daten["ton_bytes"] = len(frage.wav) if frage.wav else 0
            if frage.antwort:
                daten["antwort"] = frage.antwort
            return daten

    def ton(self, geraet: str, frage_id: str) -> bytes | None:
        with self._sperre:
            frage = self._fragen.get(frage_id)
            if frage is None or frage.geraet != geraet or frage.zustand != FERTIG:
                return None
            return frage.wav

    def stoppen(self) -> None:
        self._stopp = True
        faden = self._faden
        if faden is not None:
            self._warte.put(None)
            faden.join(timeout=10)
            self._faden = None

    def warte_bis_fertig(self, zeitlimit: float = 10.0) -> bool:
        """Fuer Tests: wartet, bis alle eingereichten Fragen bearbeitet sind."""
        ende = time.monotonic() + zeitlimit
        while time.monotonic() < ende:
            if self._warte.unfinished_tasks == 0:
                return True
            time.sleep(0.005)
        return False

    # ------------------------------------------------------------------
    # Arbeiter
    # ------------------------------------------------------------------
    def _aufraeumen(self) -> None:
        """Alte und ueberzaehlige Fragen verwerfen (unter der Sperre aufrufen). Eine Frage in Arbeit bleibt."""
        jetzt = self._jetzt()
        for kennung in [k for k, f in self._fragen.items() if f.zustand in (FERTIG, FEHLER) and jetzt - f.erstellt > self._max_alter]:
            del self._fragen[kennung]
        while len(self._fragen) >= self._max_eintraege:
            erledigt = [k for k, f in self._fragen.items() if f.zustand in (FERTIG, FEHLER)]
            if not erledigt:
                break
            del self._fragen[erledigt[0]]

    def _anstossen(self, kennung: str) -> None:
        with self._sperre:
            if self._faden is None and not self._stopp:
                self._faden = threading.Thread(target=self._lauf, name="fragen", daemon=True)
                self._faden.start()
        self._warte.put(kennung)

    def _lauf(self) -> None:
        while True:
            kennung = self._warte.get()
            try:
                if kennung is None or self._stopp:
                    return
                with self._sperre:
                    frage = self._fragen.get(kennung)
                if frage is not None:
                    self._bearbeite(frage)
            finally:
                self._warte.task_done()

    def _setze(self, eintrag: _Frage, **felder: Any) -> None:
        with self._sperre:
            for name, wert in felder.items():
                setattr(eintrag, name, wert)

    def _bearbeite(self, frage: _Frage) -> None:
        try:
            self._setze(frage, zustand=VERSTEHEN, meldung="Frage wird verstanden")
            text = self._erkennen(frage.frage_ton, frage.endung).strip()
            if not text:
                self._setze(frage, zustand=FEHLER, meldung="Die Frage war nicht zu verstehen.", frage_ton=b"")
                return
            self._setze(frage, frage=text, frage_ton=b"", zustand=ANTWORTEN, meldung="Antwort wird gesucht")
            antwort = self._antworten(text, frage.geraet, frage.datei, frage.ausgabe).strip()
            if not antwort:
                self._setze(frage, zustand=FEHLER, meldung="Es gibt keine Antwort.")
                return
            anzeige = _anzeige_kuerzen(self._anzeige(antwort)) if self._anzeige is not None else ""
            if self._sprechen is None or frage.ausgabe != AUSGABE_TON:
                self._setze(
                    frage, antwort=antwort, anzeige=anzeige, zustand=FERTIG, meldung="Antwort (ohne Sprachausgabe)"
                )
                return
            self._setze(
                frage, antwort=antwort, anzeige=anzeige, zustand=SPRECHEN, meldung="Antwort wird gesprochen"
            )
            wav = self._sprechen(antwort)
            self._setze(frage, wav=wav, zustand=FERTIG, meldung="")
        except Exception as fehler:
            logger.warning("Frage von %s zu %s fehlgeschlagen: %s", frage.geraet, frage.datei, fehler)
            self._setze(frage, zustand=FEHLER, meldung=_kurz(str(fehler)), frage_ton=b"")


def _anzeige_kuerzen(text: str, laenge: int = ANZEIGE_MAX_ZEICHEN) -> str:
    """Die Laenge steht nur im Prompt; haelt sich das Modell nicht daran, an einer Zeilengrenze kuerzen."""
    if len(text) <= laenge:
        return text
    schnitt = text.rfind("\n", 0, laenge - 3)
    return text[: schnitt if schnitt > 0 else laenge - 3].rstrip() + "..."


def _kurz(text: str, laenge: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= laenge else text[: laenge - 1] + "…"
