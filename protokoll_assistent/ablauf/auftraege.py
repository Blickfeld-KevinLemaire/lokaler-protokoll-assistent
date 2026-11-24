"""Eine Warteschlange fuer alle Verarbeitungen -- egal, wer sie anstoesst.

Transkriptionen und Auswertungen belegen die Grafikkarte bzw. das
Sprachmodell. Frueher konnten Oberflaeche, Aufnahmegeraete und (im
Servermodus) der Eingangsordner je eigene Laeufe starten und mussten sich
gegenseitig abfragen ("laeuft gerade etwas?"). Jetzt gibt es genau einen
Arbeitsfaden: Er nimmt den Auftrag mit dem hoechsten Vorrang, bei gleichem
Vorrang den aeltesten.

Ein Auftrag ist eine Funktion, die einen :class:`Fortschritt` bekommt und ein
JSON-faehiges Ergebnis liefert. Was sie meldet, geht als Ereignis an die
Oberflaeche (siehe ``ereignisse``).
"""

from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from protokoll_assistent.ablauf.ereignisse import Ereignisbus
from protokoll_assistent.services import pipeline_service

# So oft gehen Fortschritt und Vorschau hoechstens an die Oberflaeche. Die Pipeline meldet teils
# mehrmals pro Sekunde; jede Meldung als Ereignis waere nur Last fuer Netz und Browser.
MELDE_ABSTAND_SEKUNDEN = 0.5
MAX_MELDUNGEN = 300
# Erledigte Auftraege bleiben so lange in der Liste, damit die Oberflaeche sie noch zeigen kann.
MAX_ERLEDIGTE = 100

# Vorrang: hoeher kommt frueher dran.
VORRANG_NORMAL = 0
VORRANG_NACHHOLEN = -10  # Zusammenfassungen, auf die niemand mehr wartet
VORRANG_GERAET = 10  # fertige Geraeteaufnahme
VORRANG_FREIGABE = 20  # am Geraet freigegeben: dort wartet jemand


class Status(str, Enum):
    WARTET = "wartet"
    LAEUFT = "laeuft"
    FERTIG = "fertig"
    FEHLER = "fehler"
    ABGEBROCHEN = "abgebrochen"


ERLEDIGT = frozenset({Status.FERTIG, Status.FEHLER, Status.ABGEBROCHEN})


class AuftragAbgebrochen(RuntimeError):
    """Kann eine Auftragsfunktion werfen, wenn sie den Abbruch selbst bemerkt."""


@dataclass
class Auftrag:
    id: str
    art: str
    titel: str
    herkunft: str = "oberflaeche"
    vorrang: int = VORRANG_NORMAL
    status: Status = Status.WARTET
    erstellt: float = 0.0
    gestartet: float | None = None
    beendet: float | None = None
    stufe: str = ""
    stufe_text: str = ""
    fortschritt: float | None = None
    abschnitt: tuple[int, int] | None = None
    vorschau: str = ""
    meldungen: list[str] = field(default_factory=list)
    ergebnis: dict[str, Any] | None = None
    fehler: str | None = None
    # Frei verwendbare Angaben fuer die Oberflaeche (Quelldatei, Geraet ...), JSON-faehig.
    angaben: dict[str, Any] = field(default_factory=dict)
    # Servermodus: wem der Auftrag gehoert (Anmeldename). In der Windows-Anwendung immer None.
    besitzer: str | None = None

    def als_dict(self, *, mit_vorschau: bool = True) -> dict[str, Any]:
        return {
            "id": self.id,
            "art": self.art,
            "titel": self.titel,
            "herkunft": self.herkunft,
            "besitzer": self.besitzer,
            "vorrang": self.vorrang,
            "status": self.status.value,
            "erstellt": self.erstellt,
            "gestartet": self.gestartet,
            "beendet": self.beendet,
            "stufe": self.stufe,
            "stufe_text": self.stufe_text,
            "fortschritt": self.fortschritt,
            "abschnitt": list(self.abschnitt) if self.abschnitt else None,
            "vorschau": self.vorschau if mit_vorschau else "",
            "meldungen": list(self.meldungen[-50:]),
            "ergebnis": self.ergebnis,
            "fehler": self.fehler,
            "angaben": dict(self.angaben),
        }


class Fortschritt:
    """Was eine Auftragsfunktion meldet. ``callbacks()`` passt direkt in die Pipeline."""

    def __init__(self, verwaltung: Auftragsverwaltung, auftrag: Auftrag, abbruch: threading.Event):
        self._verwaltung = verwaltung
        self._auftrag = auftrag
        self._abbruch = abbruch
        self._zuletzt_gemeldet = 0.0

    @property
    def auftrag_id(self) -> str:
        return self._auftrag.id

    def abbruch_gewuenscht(self) -> bool:
        return self._abbruch.is_set()

    def stufe(self, schluessel: str, text: str) -> None:
        with self._verwaltung._sperre:
            self._auftrag.stufe = schluessel
            self._auftrag.stufe_text = text
        self._melden(sofort=True)

    def abschnitt(self, aktuell: int, gesamt: int) -> None:
        with self._verwaltung._sperre:
            self._auftrag.abschnitt = (aktuell, gesamt)
        self._melden()

    def gesamt(self, anteil: float) -> None:
        with self._verwaltung._sperre:
            self._auftrag.fortschritt = max(0.0, min(1.0, float(anteil)))
        self._melden(sofort=anteil >= 1.0)

    def vorschau(self, text: str) -> None:
        with self._verwaltung._sperre:
            self._auftrag.vorschau = text
        self._melden(vorschau=True)

    def meldung(self, text: str) -> None:
        with self._verwaltung._sperre:
            self._auftrag.meldungen.append(text)
            del self._auftrag.meldungen[:-MAX_MELDUNGEN]
        self._verwaltung._bus.senden("auftrag_meldung", {"id": self._auftrag.id, "text": text})

    def angaben(self, **werte: Any) -> None:
        with self._verwaltung._sperre:
            self._auftrag.angaben.update(werte)
        self._melden(sofort=True)

    def callbacks(self) -> pipeline_service.PipelineCallbacks:
        return pipeline_service.PipelineCallbacks(
            on_stage=self.stufe,
            on_chunk_progress=self.abschnitt,
            on_overall_progress=self.gesamt,
            on_preview=self.vorschau,
            on_log=self.meldung,
            should_cancel=self.abbruch_gewuenscht,
        )

    def _melden(self, *, sofort: bool = False, vorschau: bool = False) -> None:
        jetzt = self._verwaltung._jetzt()
        if not sofort and jetzt - self._zuletzt_gemeldet < MELDE_ABSTAND_SEKUNDEN:
            self._verwaltung._nachmelden_vormerken(self._auftrag.id)
            return
        self._zuletzt_gemeldet = jetzt
        self._verwaltung._auftrag_melden(self._auftrag, mit_vorschau=vorschau or sofort)


AuftragsFunktion = Callable[[Fortschritt], dict[str, Any] | None]
Nachfolger = Callable[[Auftrag], None]


@dataclass
class _Eintrag:
    auftrag: Auftrag
    funktion: AuftragsFunktion
    nach_ende: Nachfolger | None
    abbruch: threading.Event


class Auftragsverwaltung:
    def __init__(self, bus: Ereignisbus, *, jetzt: Callable[[], float] = time.time):
        self._bus = bus
        self._jetzt = jetzt
        self._sperre = threading.RLock()
        self._bedingung = threading.Condition(self._sperre)
        self._eintraege: dict[str, _Eintrag] = {}
        self._reihenfolge = itertools.count()
        self._position: dict[str, int] = {}
        self._laufend: str | None = None
        self._nachmelden: set[str] = set()
        self._faden: threading.Thread | None = None
        self._nachmelder: threading.Thread | None = None
        self._nachmelder_stopp = threading.Event()
        self._stopp = False

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def starten(self) -> None:
        with self._sperre:
            if self._faden is not None:
                return
            self._stopp = False
            self._faden = threading.Thread(target=self._schleife, name="auftraege", daemon=True)
            self._faden.start()
            self._nachmelder_stopp = threading.Event()
            self._nachmelder = threading.Thread(
                target=self._nachmelde_schleife, args=(self._nachmelder_stopp.wait,), name="auftraege-nachmelden", daemon=True
            )
            self._nachmelder.start()

    def beenden(self, warten: float | None = 5.0) -> None:
        """Bricht den laufenden Auftrag ab und beendet den Arbeitsfaden."""
        with self._sperre:
            self._stopp = True
            if self._laufend is not None:
                self._eintraege[self._laufend].abbruch.set()
            self._bedingung.notify_all()
            faden, self._faden = self._faden, None
            nachmelder, self._nachmelder = self._nachmelder, None
            self._nachmelder_stopp.set()
        for f in (faden, nachmelder):
            if f is not None and warten is not None:
                f.join(warten)

    # ------------------------------------------------------------------
    # Auftraege
    # ------------------------------------------------------------------
    def einreihen(
        self,
        art: str,
        titel: str,
        funktion: AuftragsFunktion,
        *,
        herkunft: str = "oberflaeche",
        vorrang: int = VORRANG_NORMAL,
        angaben: dict[str, Any] | None = None,
        nach_ende: Nachfolger | None = None,
        besitzer: str | None = None,
    ) -> Auftrag:
        """``nach_ende`` laeuft im Arbeitsfaden, sobald der Auftrag erledigt ist (gleich wie) --
        dort darf er Folgeauftraege einreihen."""
        auftrag = Auftrag(
            id=uuid.uuid4().hex[:12],
            art=art,
            titel=titel,
            herkunft=herkunft,
            vorrang=vorrang,
            erstellt=self._jetzt(),
            angaben=dict(angaben or {}),
            besitzer=besitzer,
        )
        with self._sperre:
            self._eintraege[auftrag.id] = _Eintrag(auftrag, funktion, nach_ende, threading.Event())
            self._position[auftrag.id] = next(self._reihenfolge)
            self._bedingung.notify_all()
        self._bus.senden("auftrag", auftrag.als_dict())
        return auftrag

    def abbrechen(self, auftrag_id: str) -> bool:
        """Wartende fallen sofort heraus; ein laufender bricht an der naechsten Pruefstelle ab."""
        with self._sperre:
            eintrag = self._eintraege.get(auftrag_id)
            if eintrag is None or eintrag.auftrag.status in ERLEDIGT:
                return False
            eintrag.abbruch.set()
            if eintrag.auftrag.status is Status.WARTET:
                self._abschliessen(eintrag, Status.ABGEBROCHEN)
                nach_ende = eintrag.nach_ende
            else:
                return True
        self._bus.senden("auftrag", eintrag.auftrag.als_dict())
        if nach_ende is not None:
            self._nachfolger_aufrufen(nach_ende, eintrag.auftrag)
        return True

    def hole(self, auftrag_id: str) -> Auftrag | None:
        with self._sperre:
            eintrag = self._eintraege.get(auftrag_id)
            return eintrag.auftrag if eintrag else None

    def liste(self) -> list[Auftrag]:
        with self._sperre:
            return sorted((e.auftrag for e in self._eintraege.values()), key=lambda a: self._position[a.id])

    def laeuft_etwas(self) -> bool:
        with self._sperre:
            return self._laufend is not None or any(
                e.auftrag.status is Status.WARTET for e in self._eintraege.values()
            )

    def platz(self, auftrag_id: str) -> int | None:
        """Wie viele Auftraege vor diesem drankommen (der laufende zaehlt mit). 0: laeuft gerade oder ist als
        Naechster dran, ohne dass etwas laeuft. ``None``: erledigt oder unbekannt."""
        with self._sperre:
            eintrag = self._eintraege.get(auftrag_id)
            if eintrag is None or eintrag.auftrag.status in ERLEDIGT:
                return None
            if eintrag.auftrag.status is Status.LAEUFT:
                return 0
            wartend = sorted(
                (e for e in self._eintraege.values() if e.auftrag.status is Status.WARTET),
                key=lambda e: (-e.auftrag.vorrang, self._position[e.auftrag.id]),
            )
            vorher = next(i for i, e in enumerate(wartend) if e.auftrag.id == auftrag_id)
            return vorher + (1 if self._laufend is not None else 0)

    def laufender(self) -> Auftrag | None:
        with self._sperre:
            return self._eintraege[self._laufend].auftrag if self._laufend else None

    def warten_bis_leer(self, zeitlimit: float = 10.0) -> bool:
        """Fuer Tests und das Herunterfahren: wartet, bis nichts mehr ansteht."""
        ende = time.monotonic() + zeitlimit
        with self._bedingung:
            while self.laeuft_etwas():
                rest = ende - time.monotonic()
                if rest <= 0:
                    return False
                self._bedingung.wait(min(rest, 0.1))
        return True

    # ------------------------------------------------------------------
    # Arbeitsfaden
    # ------------------------------------------------------------------
    def _naechster(self) -> _Eintrag | None:
        wartend = [e for e in self._eintraege.values() if e.auftrag.status is Status.WARTET]
        if not wartend:
            return None
        return min(wartend, key=lambda e: (-e.auftrag.vorrang, self._position[e.auftrag.id]))

    def _schleife(self) -> None:
        while True:
            with self._bedingung:
                eintrag = self._naechster()
                while eintrag is None and not self._stopp:
                    self._bedingung.wait(1.0)
                    self._nachmelden_ausfuehren()
                    eintrag = self._naechster()
                if self._stopp:
                    return
                assert eintrag is not None  # noqa: S101 -- Schleife oben endet nur mit Eintrag oder Stopp
                eintrag.auftrag.status = Status.LAEUFT
                eintrag.auftrag.gestartet = self._jetzt()
                self._laufend = eintrag.auftrag.id
            self._bus.senden("auftrag", eintrag.auftrag.als_dict())
            self._ausfuehren(eintrag)

    def ausfuehren_im_aufrufer(self) -> bool:
        """Fuehrt den naechsten wartenden Auftrag im aufrufenden Faden aus (Tests, ``--einmal``).
        Gibt zurueck, ob es einen gab."""
        with self._sperre:
            eintrag = self._naechster()
            if eintrag is None:
                return False
            eintrag.auftrag.status = Status.LAEUFT
            eintrag.auftrag.gestartet = self._jetzt()
            self._laufend = eintrag.auftrag.id
        self._bus.senden("auftrag", eintrag.auftrag.als_dict())
        self._ausfuehren(eintrag)
        return True

    def _ausfuehren(self, eintrag: _Eintrag) -> None:
        fortschritt = Fortschritt(self, eintrag.auftrag, eintrag.abbruch)
        status = Status.FERTIG
        ergebnis: dict[str, Any] | None = None
        fehler: str | None = None
        try:
            ergebnis = eintrag.funktion(fortschritt)
            if eintrag.abbruch.is_set() and ergebnis is None:
                status = Status.ABGEBROCHEN
        except (pipeline_service.PipelineCancelled, AuftragAbgebrochen):
            status = Status.ABGEBROCHEN
        except Exception as ausnahme:  # jeder Auftrag einzeln: ein Fehler stoppt nie die Warteschlange
            status = Status.FEHLER
            fehler = str(ausnahme) or type(ausnahme).__name__
        with self._sperre:
            eintrag.auftrag.ergebnis = ergebnis
            eintrag.auftrag.fehler = fehler
            self._abschliessen(eintrag, status)
            self._laufend = None
            self._nachmelden.discard(eintrag.auftrag.id)
        self._bus.senden("auftrag", eintrag.auftrag.als_dict())
        if eintrag.nach_ende is not None:
            self._nachfolger_aufrufen(eintrag.nach_ende, eintrag.auftrag)
        with self._bedingung:
            self._bedingung.notify_all()

    def _nachfolger_aufrufen(self, nach_ende: Nachfolger, auftrag: Auftrag) -> None:
        try:
            nach_ende(auftrag)
        except Exception as ausnahme:  # ein Fehler im Folgeschritt darf die Warteschlange nicht anhalten
            self._bus.senden("fehler", {"text": f"Folgeschritt nach '{auftrag.titel}' gescheitert: {ausnahme}"})

    def _abschliessen(self, eintrag: _Eintrag, status: Status) -> None:
        eintrag.auftrag.status = status
        eintrag.auftrag.beendet = self._jetzt()
        if status is Status.FERTIG:
            eintrag.auftrag.fortschritt = 1.0
        self._aufraeumen()

    def _aufraeumen(self) -> None:
        erledigt = sorted(
            (e.auftrag for e in self._eintraege.values() if e.auftrag.status in ERLEDIGT),
            key=lambda a: a.beendet or 0.0,
        )
        for auftrag in erledigt[:-MAX_ERLEDIGTE]:
            self._eintraege.pop(auftrag.id, None)
            self._position.pop(auftrag.id, None)

    # ------------------------------------------------------------------
    # Gedrosselte Meldungen
    # ------------------------------------------------------------------
    def _auftrag_melden(self, auftrag: Auftrag, *, mit_vorschau: bool) -> None:
        with self._sperre:
            daten = auftrag.als_dict(mit_vorschau=mit_vorschau)
            self._nachmelden.discard(auftrag.id)
        if not mit_vorschau:
            daten.pop("vorschau", None)
        self._bus.senden("auftrag", daten)

    def _nachmelden_vormerken(self, auftrag_id: str) -> None:
        with self._sperre:
            self._nachmelden.add(auftrag_id)

    def _nachmelden_ausfuehren(self) -> None:
        """Eine gedrosselte Meldung geht spaetestens mit der naechsten Runde des Zeitgebers (``_nachmelde_schleife``)
        bzw. des Arbeitsfadens raus."""
        with self._sperre:
            offen = [self._eintraege[i].auftrag for i in self._nachmelden if i in self._eintraege]
            self._nachmelden.clear()
        for auftrag in offen:
            self._bus.senden("auftrag", auftrag.als_dict())

    def nachmelden(self) -> None:
        """Von aussen (z. B. einem Zeitgeber der Programmschnittstelle) aufrufbar."""
        self._nachmelden_ausfuehren()

    def _nachmelde_schleife(self, warten: Callable[[float], bool]) -> None:
        """Der Zeitgeber (eigener Faden, laeuft mit ``starten``): Gedrosselte Meldungen eines *laufenden* Auftrags
        gehen spaetestens nach ``MELDE_ABSTAND_SEKUNDEN`` hinaus. Der Arbeitsfaden rechnet in dieser Zeit und kommt
        nicht dazu -- ohne Zeitgeber hinge die Anzeige auf dem Stand vor der letzten gedrosselten Meldung, bis der
        Auftrag wieder etwas meldet (bei langen Schritten minutenlang). ``warten`` liefert True zum Beenden."""
        while not warten(MELDE_ABSTAND_SEKUNDEN):
            self._nachmelden_ausfuehren()


# --------------------------------------------------------------------------
# Sicht anderer Nutzer (Servermodus)
# --------------------------------------------------------------------------
FREMD_FELDER = ("id", "art", "status", "vorrang", "erstellt", "gestartet", "beendet", "fortschritt")


def fuer_betrachter(daten: dict[str, Any], betrachter: str | None, *, alles_sehen: bool) -> dict[str, Any]:
    """Was ein Nutzer von einem Auftrag sieht. Eigene (und in der Windows-Anwendung alle): vollstaendig.
    Fremde: nur so viel, dass die eigene Position in der Warteschlange und die Wartezeit verstaendlich sind --
    kein Dateiname, keine Vorschau, kein Ergebnis.

    Ein Auftrag ohne Besitzer (Eingangsordner ohne ``PROTOKOLL_EINGANG_NUTZER``, Geraet ohne Besitzer, Modell-
    Download eines Admins) gehoert im Servermodus niemandem -- fuer Nicht-Admins ist er deshalb fremd. In der
    Windows-Anwendung gilt ``alles_sehen``."""
    besitzer = daten.get("besitzer")
    if alles_sehen or (besitzer is not None and betrachter is not None and str(besitzer).lower() == betrachter.lower()):
        return daten
    fremd = {k: daten.get(k) for k in FREMD_FELDER if k in daten}
    fremd.update({"titel": "Andere Verarbeitung", "herkunft": "andere", "besitzer": None, "fremd": True})
    return fremd
