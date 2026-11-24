"""Aufnahmegeraete (VERMERK Raum): Empfang, Live-Transkription, automatische Verarbeitung, Fragen.

Frueher verteilt auf ``gui/geraete_empfang.py`` (``EmpfangsSteuerung``) und
das Hauptfenster (drei Warteschlangen, ``_automatik``, Ollama-Wache). Hier
ohne Qt, fuer Windows-Anwendung und Servermodus gleichermassen.

Ablauf einer Geraeteaufnahme:

1. Der Empfangsdienst (``services/geraete_empfang_service``) nimmt die Teile
   an; die Live-Transkription rechnet waehrenddessen auf dem Prozessor mit.
2. Ist die Datei vollstaendig und die Live-Transkription durch, reiht
   :meth:`GeraeteAutomatik.aufnahme_bereit` eine Transkription ein (Vorrang
   vor Auftraegen aus der Oberflaeche).
3. Danach entweder sofort die Auswertung -- oder, wenn das Geraet fragen
   will, warten auf "Ja"/"Nein" am Geraet. Ein "Ja" kommt vor allen anderen
   Auftraegen dran (dort wartet jemand). Zieht das Geraet zu einer neuen
   Aufnahme weiter, wird die Zusammenfassung nachgeholt, wenn die
   Grafikkarte beides verkraftet -- sonst bleibt es beim Transkript.

Alle Methoden sind aus beliebigen Faeden aufrufbar (HTTP-Faeden des
Empfangs, Arbeitsfaden der Auftraege).
"""

from __future__ import annotations

import glob
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf import auftraege, bibliothek
from protokoll_assistent.ablauf.auftraege import Auftrag, Status
from protokoll_assistent.ablauf.steuerung import KEINE_SPRACHE, Steuerung
from protokoll_assistent.ablauf.verarbeitungswege import (
    Ablauffehler,
    AuswertungsWunsch,
    TranskriptionsWunsch,
    api_auswertung_funktion,
    ermittle_whisper_modell,
)
from protokoll_assistent.services import (
    api_anbieter,
    chat_service,
    chunking_service,
    frage_service,
    geraete_empfang_service,
    geraete_fragen,
    live_auswertung_service,
    live_service,
    model_service,
    ollama_service,
)
from protokoll_assistent.utils.paths import get_recordings_dir, get_work_dir
from protokoll_assistent.utils.systemprompt_vorlagen import alle_vorlagen

# So lange wartet die automatische Auswertung hoechstens auf eine noch laufende Teilauswertung der Aufnahme.
VORAB_AUSWERTUNG_WARTEN = 300.0
OLLAMA_WACHE_SEKUNDEN = 30.0
MAX_ERGEBNISSE = 50

Schluessel = tuple[str, str]  # (Geraet, Dateiname des Geraets)

logger = logging.getLogger(__name__)


class MeldendesStatusRegister(live_service.StatusRegister):
    """Wie das Statusregister fuer die Geraete -- jede Aenderung geht zusaetzlich an die Oberflaeche."""

    def __init__(self, melden: Callable[[dict[str, Any]], object]):
        super().__init__()
        self._melden = melden

    def setze(self, geraet: str, datei: str, zustand: str, fortschritt: float | None = None, meldung: str = "") -> None:
        super().setze(geraet, datei, zustand, fortschritt, meldung)
        eintrag = self.hole(geraet, datei) or {}
        self._melden({"geraet": geraet, "datei": datei, **eintrag})


@dataclass
class _Freigabe:
    pfad: Path
    transkript: Path
    auftrag: str  # Systemprompt-Text


@dataclass
class Abhaengigkeiten:
    """Ersetzbar in Tests."""

    dienst_fabrik: Callable[..., geraete_empfang_service.GeraeteEmpfang] = geraete_empfang_service.GeraeteEmpfang
    nebenher_moeglich: Callable[[dict[str, Any]], bool] | None = None
    transkribierer_fabrik: Callable[[str, str | None, bool], Callable[[], Any]] = live_service.cpu_transkribierer_fabrik
    ollama_laeuft: Callable[[], bool] = lambda: ollama_service.is_service_running(timeout=2)
    ollama_starten: Callable[[], bool] = lambda: bool(ollama_service.dienst_starten())
    modell_fehlt: Callable[[str], bool] = ollama_service.modell_fehlt
    arbeitsordner: Callable[[], Path] = get_work_dir
    standard_ziel: Callable[[], Path] = get_recordings_dir


class GeraeteAutomatik:
    def __init__(self, steuerung: Steuerung, abhaengigkeiten: Abhaengigkeiten | None = None):
        self.steuerung = steuerung
        self.abh = abhaengigkeiten or Abhaengigkeiten()
        self._sperre = threading.RLock()
        self.status = MeldendesStatusRegister(lambda daten: steuerung.bus.senden("geraet_status", daten))
        self.wuensche = live_service.WunschRegister()
        self._freigaben: dict[Schluessel, _Freigabe] = {}
        self._freigegeben: set[Schluessel] = set()  # "Ja" am Geraet, Auswertung eingereiht
        self._nachholen: set[Schluessel] = set()
        self._ergebnisse: dict[Schluessel, dict[str, Path]] = {}
        self._live_einstellungen: tuple[str, str | None, bool] = ("", "de", True)
        self._live_auswertung: live_auswertung_service.AuswertungsEinstellungen | None = None
        self._frage_transkribierer: Callable[[Path], list[dict[str, Any]]] | None = None
        self.live = live_service.LiveTranskription(
            self.abh.arbeitsordner(),
            self._live_transkribierer,
            status=self.status,
            bei_aenderung=self._live_geaendert,
            auswertung=live_auswertung_service.LiveAuswertung(lambda: self._live_auswertung),
            auftrag_fn=self._auftrag_des_geraets,
        )
        self.fragen = frage_service.FragenDienst(
            erkennen=self._frage_erkennen,
            antworten=self._frage_beantworten,
            anzeige=geraete_fragen.fuer_display,
            sprechen=None,
            bereit=self._frage_bereit,
        )
        self._dienst: geraete_empfang_service.GeraeteEmpfang | None = None
        # Liegengebliebene Aufnahmen (siehe ``_liegengebliebene_einreihen``) nur beim ersten Start des Empfangs
        # suchen: Bei einem spaeteren Neustart (Einstellungen geaendert) laufen sie womoeglich gerade.
        self._liegengebliebene_gesucht = False
        self._stand: tuple[Any, ...] | None = None
        self.fehler: str | None = None
        self.fehler_code: str | None = None
        self.zuletzt = ""
        # Ollama-Wache
        self._wache_stopp = threading.Event()
        self._wache_faden: threading.Thread | None = None
        self._ollama_modell_gemeldet: str | None = None
        self._ollama_problem_aktiv = False

    # ------------------------------------------------------------------
    # Empfang
    # ------------------------------------------------------------------
    @property
    def laeuft(self) -> bool:
        return self._dienst is not None

    def anwenden(self, konfiguration: dict[str, Any] | None = None) -> None:
        """Empfang passend zu den Einstellungen starten, stoppen oder neu starten -- nur bei Aenderungen."""
        config = konfiguration if konfiguration is not None else self.steuerung.konfiguration()
        self._live_einstellungen = (
            ermittle_whisper_modell(config),
            config.get("sprache") or "de",
            not config.get("offline", False),
        )
        self._live_auswertung = self._live_auswertung_lesen(config)
        geraete = geraete_empfang_service.geraete_aus_konfiguration(config.get("geraete_empfang_geraete") or [])
        aktiv = bool(config.get("geraete_empfang_aktiv")) and bool(geraete)
        port = _port(config.get("geraete_empfang_port"))
        ziel_text = config.get("eingabeordner")
        ziel = Path(ziel_text) if ziel_text else self.abh.standard_ziel()
        live_aktiv = bool(config.get("geraete_live_aktiv", True))
        stand = (aktiv, port, geraete, ziel, live_aktiv)
        nachholen: geraete_empfang_service.GeraeteEmpfang | None = None
        with self._sperre:
            if stand == self._stand and (self._dienst is not None or not aktiv):
                return
            self._empfang_stoppen()
            self._stand = stand
            self.fehler = None
            self.fehler_code = None
            if not aktiv:
                self._empfang_melden()
                return
            zusaetze: dict[str, Any] = {
                "status_fn": self.status.hole,
                "auftraege_fn": lambda: list(alle_vorlagen()),
                "bei_zusammenfassung": self._zusammenfassung_freigegeben_rueckruf,
                "bei_keine_zusammenfassung": self._zusammenfassung_abgelehnt_rueckruf,
                "bei_wunsch": self._wunsch,
                "fragen": self.fragen,
                # Neuer Kontakt (auch nach jedem Neustart des Empfangs): Die Oberflaeche laedt die Geraeteliste
                # beim Ereignis "empfang" neu -- sonst stuende ein verbundenes Geraet dort als "Noch nicht verbunden".
                "bei_kontakt": lambda _geraet: self._empfang_melden(),
            }
            if self.steuerung.mehrbenutzer:
                zusaetze["ziel_fuer_geraet"] = lambda geraet: self.steuerung.aufnahmeordner(self.besitzer_von(geraet))
            if live_aktiv:
                zusaetze["bei_teil"] = self.live.teil_gewachsen
                zusaetze["bei_abschluss"] = self._abschluss
                zusaetze["bei_verworfen"] = self.live.verwerfen
            dienst = self.abh.dienst_fabrik(ziel, geraete, port=port, bei_neuer_aufnahme=self._neue_aufnahme, **zusaetze)
            try:
                # Vorab, getrennt vom Port: Ein nicht erreichbarer Eingangsordner (Netzlaufwerk aus, USB-Stick
                # abgezogen) meldete sich sonst als "Anschluss belegt" -- und man suchte den Fehler am Port.
                ziel.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.fehler = f"Der Ordner für eingehende Aufnahmen ist nicht erreichbar: {ziel}"
                self.fehler_code = "ordner"
                self._empfang_melden()
                return
            try:
                dienst.starten()
            except OSError:
                self.fehler = "Der Empfang ist gerade nicht möglich – ein anderes Programm benutzt denselben Anschluss."
                self.fehler_code = "port_belegt"
                self._empfang_melden()
                return
            self._dienst = dienst
            if live_aktiv and not self._liegengebliebene_gesucht:
                self._liegengebliebene_gesucht = True
                nachholen = dienst
        self._empfang_melden()
        if nachholen is not None:
            self._liegengebliebene_einreihen(nachholen)

    def _empfang_stoppen(self) -> None:
        dienst, self._dienst = self._dienst, None
        self._stand = None
        if dienst is not None:
            dienst.stoppen()

    def stoppen(self) -> None:
        self._wache_stopp.set()
        with self._sperre:
            self._empfang_stoppen()
        self.live.stoppen()
        self.fragen.stoppen()

    def besitzer_von(self, geraet: str) -> str | None:
        """Wem das Geraet gehoert (Servermodus). In der Windows-Anwendung immer None: ein Rechner, ein Mensch."""
        if not self.steuerung.mehrbenutzer:
            return None
        for eintrag in self.steuerung.konfiguration().get("geraete_empfang_geraete") or []:
            if isinstance(eintrag, dict) and str(eintrag.get("name", "")).lower() == geraet.lower():
                besitzer = str(eintrag.get("besitzer") or "").strip()
                return besitzer or None
        return None

    def kontakte(self) -> dict[str, geraete_empfang_service.Kontakt]:
        dienst = self._dienst
        return dienst.kontakte() if dienst is not None else {}

    def beschreibung(self) -> dict[str, Any]:
        with self._sperre:
            if self._stand is None or self._dienst is None:
                return {"aktiv": False, "fehler": self.fehler, "fehler_code": self.fehler_code, "zuletzt": self.zuletzt}
            _aktiv, port, geraete, ziel, live = self._stand
            return {
                "aktiv": True,
                "port": port,
                "geraete": len(geraete),
                "ziel": str(ziel),
                "live": live,
                "fehler": self.fehler,
                "fehler_code": self.fehler_code,
                "zuletzt": self.zuletzt,
            }

    def _empfang_melden(self) -> None:
        self.steuerung.bus.senden("empfang", self.beschreibung())

    def _zuletzt(self, text: str) -> None:
        self.zuletzt = f"{text} ({time.strftime('%H:%M')})"
        self._empfang_melden()

    def _neue_aufnahme(self, pfad: Path, geraet: str) -> None:
        self._zuletzt(f"Angekommen: {pfad.name} von {geraet}")
        self.steuerung.bus.senden("dateien", {"grund": "neue_aufnahme", "pfad": str(pfad), "geraet": geraet})

    def _abschluss(self, geraet: str, datei: str, ziel: Path) -> None:
        self.status.setze(geraet, datei, live_service.WARTET, meldung="Aufnahme angekommen")
        self.live.abgeschlossen(geraet, datei, ziel, lambda: self._aufnahme_bereit_rueckruf(ziel, geraet, datei))

    def _aufnahme_bereit_rueckruf(self, ziel: Path, geraet: str, datei: str) -> None:
        self.aufnahme_bereit(ziel, geraet, datei)

    def _wunsch(self, geraet: str, datei: str, auftrag: str | None, rueckfrage: bool) -> None:
        if self.wuensche.merke(geraet, datei, auftrag, rueckfrage):
            self.geraet_weitergezogen(geraet, datei)

    def _zusammenfassung_freigegeben_rueckruf(self, geraet: str, datei: str) -> bool:
        self.zusammenfassung_gewuenscht(geraet, datei)
        return True

    def _zusammenfassung_abgelehnt_rueckruf(self, geraet: str, datei: str) -> bool:
        self.zusammenfassung_abgelehnt(geraet, datei)
        return True

    # ------------------------------------------------------------------
    # Live-Transkription
    # ------------------------------------------------------------------
    def _live_transkribierer(self) -> Any:
        modell, sprache, download = self._live_einstellungen
        return self.abh.transkribierer_fabrik(modell, sprache, download)()

    def _live_geaendert(self, geraet: str, datei: str, text: str, bis: float) -> None:
        self.steuerung.bus.senden("live", {"geraet": geraet, "datei": datei, "text": text, "bis": bis})

    def _auftrag_des_geraets(self, geraet: str, datei: str) -> str | None:
        """Text des Auftrags, den das Geraet gewaehlt hat; ``None``: der aus den Einstellungen."""
        wunsch = self.wuensche.hole(geraet, datei)
        if wunsch is None or wunsch.auftrag is None:
            return None
        return alle_vorlagen().get(wunsch.auftrag)

    def _live_auswertung_lesen(self, config: dict[str, Any]) -> live_auswertung_service.AuswertungsEinstellungen | None:
        """Womit die Teilauswertung waehrend der Aufnahme rechnet: derselbe Auftrag und dasselbe Modell wie die
        automatische Auswertung nach dem Ende. ``None``: aus oder nicht moeglich."""
        if not (config.get("geraete_live_aktiv", True) and config.get("geraete_live_auswertung_vorab", True)):
            return None
        auftrag = alle_vorlagen().get(str(config.get("geraete_live_auftrag") or ""), "")
        abschnitt = chunking_service.auswertungs_abschnitt(config.get("geraete_live_abschnitt_sekunden"))
        if config.get("nachbearbeitung_modus") == "api":
            endpunkt = str(config.get("api_nachbearbeitung_endpunkt") or "")
            modell = str(config.get("api_nachbearbeitung_modell") or "")
            if not (api_anbieter.adresse_vollstaendig(endpunkt) and modell):
                return None
            schluessel = self.steuerung.schluessel.hole(self.steuerung.schluessel.name_fuer_nachbearbeitung(config))
            if not schluessel:
                return None
            return live_auswertung_service.AuswertungsEinstellungen(
                auftrag, f"api:{endpunkt}|{modell}", api_auswertung_funktion(endpunkt, modell, schluessel), abschnitt_sekunden=abschnitt
            )
        lokal = str(config.get("ollama_modell") or ollama_service.DEFAULT_MODEL)
        return live_auswertung_service.AuswertungsEinstellungen(
            auftrag,
            lokal,
            lambda prompt, system: ollama_service.generate_text(prompt, system, model=lokal),
            abschnitt_sekunden=abschnitt,
        )

    # ------------------------------------------------------------------
    # Automatische Verarbeitung
    # ------------------------------------------------------------------
    def aufnahme_bereit(self, pfad: Path, geraet: str, datei: str) -> Auftrag | None:
        """Eine Aufnahme ist vollstaendig angekommen: Transkription einreihen."""
        config = self.steuerung.konfiguration()
        gewaehlt = self._auftrag_des_geraets(geraet, datei)
        auftrag_text = gewaehlt if gewaehlt is not None else alle_vorlagen().get(str(config.get("geraete_live_auftrag") or ""), "")
        wunsch = self.wuensche.hole(geraet, datei)
        rueckfrage = wunsch is not None and wunsch.rueckfrage
        besitzer = self.besitzer_von(geraet)
        self.status.setze(geraet, datei, live_service.TRANSKRIPTION, 0.0, "Transkription beginnt")
        self._zuletzt(f"Automatische Verarbeitung: {pfad.name} von {geraet}")

        def danach(auftrag: Auftrag) -> None:
            self._transkription_beendet(auftrag, pfad, geraet, datei, auftrag_text, rueckfrage)

        try:
            return self.steuerung.transkription_starten(
                TranskriptionsWunsch(
                    quelle=pfad,
                    ausgabe=self.steuerung.ausgabeordner(besitzer),
                    sprache=config.get("sprache") or "de",
                    offline=bool(config.get("offline", False)),
                    vorab_live=self.live.vorab_fuer(pfad),
                ),
                herkunft=f"geraet:{geraet}",
                vorrang=auftraege.VORRANG_GERAET,
                nach_ende=danach,
                fortschritt_spiegeln=self._spiegel(geraet, datei, live_service.TRANSKRIPTION),
                besitzer=besitzer,
            )
        except Ablauffehler as fehler:
            self.status.setze(geraet, datei, live_service.FEHLER, None, f"Verarbeitung nicht möglich: {fehler.titel}")
            self.steuerung.hinweis(f"{fehler.titel}: {fehler.text}", stufe="fehler", quelle=geraet, code=fehler.code, bereich=fehler.bereich)
            return None

    def _liegengebliebene_einreihen(self, dienst: geraete_empfang_service.GeraeteEmpfang) -> None:
        """Beim Start: Aufnahmen, die vollstaendig ankamen, deren Verarbeitung aber nie zu Ende kam (Software oder
        Rechner wurden dazwischen beendet), wieder einreihen. Die Warteschlange ueberlebt keinen Neustart, und das
        Geraet hoert nach dreimal "unbekannt" auf zu fragen -- die Aufnahme bliebe sonst unbearbeitet liegen.

        Eine Rueckfrage am Geraet gilt danach nicht mehr (der Wunsch lag nur im Speicher): Es geht ohne Rueckfrage
        mit dem eingestellten Auftrag weiter. Das Geraet sieht den Stand wieder ueber ``…/status``."""
        try:
            offen = dienst.ablage.offene_aufnahmen()
        except Exception:  # der Empfang laeuft trotzdem
            logger.exception("Liegengebliebene Aufnahmen nicht gefunden")
            return
        for geraet, datei, pfad in offen:
            try:
                self._liegengebliebene_aufnahme(dienst, geraet, datei, pfad)
            except Exception:  # eine Aufnahme darf die anderen nicht aufhalten
                logger.exception("Aufnahme %s konnte nicht wieder eingereiht werden", pfad.name)

    def _liegengebliebene_aufnahme(
        self, dienst: geraete_empfang_service.GeraeteEmpfang, geraet: str, datei: str, pfad: Path
    ) -> None:
        if not pfad.is_file():  # verschoben oder geloescht: nichts mehr zu tun
            dienst.ablage.verarbeitung_erledigt(pfad)
            return
        ausgabe = self.steuerung.ausgabeordner(self.besitzer_von(geraet))
        transkripte = sorted(ausgabe.glob(f"{glob.escape(pfad.stem)}_lokal_transkript_*.json"))
        if not transkripte:
            logger.info("Nach dem Neustart wieder eingereiht: %s von %s", pfad.name, geraet)
            self.aufnahme_bereit(pfad, geraet, datei)
            return
        # Das Transkript steht schon: nicht noch einmal transkribieren.
        transkript = transkripte[-1]
        besprechung = next((b for b in bibliothek.besprechungen(ausgabe) if b.transkript == transkript), None)
        if besprechung is None:  # leeres Transkript
            self._abschliessen(geraet, datei, pfad, live_service.FEHLER, f"{KEINE_SPRACHE}.")
            return
        self._ergebnis_merken(geraet, datei, transkript=transkript)
        if besprechung.protokolle:
            self._abschliessen(geraet, datei, pfad, live_service.FERTIG, "Transkription erfolgreich")
            return
        config = self.steuerung.konfiguration()
        auftrag_text = alle_vorlagen().get(str(config.get("geraete_live_auftrag") or ""), "")
        logger.info("Nach dem Neustart: Zusammenfassung fuer %s von %s eingereiht", pfad.name, geraet)
        self._auswertung_einreihen(
            geraet, datei, pfad, transkript, auftrag_text, rueckfrage=False, vorrang=auftraege.VORRANG_GERAET
        )

    def _verarbeitung_erledigt(self, pfad: Path) -> None:
        """Im Empfang vermerken, dass die Verarbeitung zu Ende ist -- nach einem Neustart nicht wieder einreihen."""
        dienst = self._dienst
        if dienst is None:
            return
        try:
            dienst.ablage.verarbeitung_erledigt(pfad)
        except Exception:  # nur Buchfuehrung: schlimmstenfalls prueft der naechste Start die Aufnahme noch einmal
            logger.exception("Ende der Verarbeitung von %s nicht vermerkt", pfad.name)

    def _spiegel(self, geraet: str, datei: str, zustand: str) -> Callable[[str, float | None, str], None]:
        def spiegeln(_stufe: str, anteil: float | None, text: str) -> None:
            if anteil is None:
                aktuell = self.status.hole(geraet, datei) or {}
                anteil = aktuell.get("fortschritt")
            self.status.setze(geraet, datei, zustand, anteil, text)

        return spiegeln

    def _transkription_beendet(
        self, auftrag: Auftrag, pfad: Path, geraet: str, datei: str, auftrag_text: str, rueckfrage: bool
    ) -> None:
        if auftrag.status is not Status.FERTIG or not auftrag.ergebnis:
            if auftrag.status is Status.ABGEBROCHEN:
                text = "Die Transkription wurde abgebrochen."
            elif (auftrag.fehler or "").startswith(KEINE_SPRACHE):
                text = f"{KEINE_SPRACHE}."
            else:
                text = "Die Transkription ist fehlgeschlagen."
            self.status.setze(geraet, datei, live_service.FEHLER, None, text)
            self._verarbeitung_erledigt(pfad)
            self._zuletzt(f"{text} {pfad.name} von {geraet}")
            return
        transkript = Path(auftrag.ergebnis["transkript_json"])
        self._ergebnis_merken(geraet, datei, transkript=transkript)
        if rueckfrage:
            with self._sperre:
                self._freigaben[(geraet, datei)] = _Freigabe(pfad, transkript, auftrag_text)
            self.status.setze(geraet, datei, live_service.TRANSKRIPT, 1.0, "Transkription erfolgreich")
            self._zuletzt(f"Transkript steht, wartet auf Freigabe am Gerät: {pfad.name} von {geraet}")
            if self.wuensche.neueste(geraet) not in (None, datei):
                self.ohne_antwort_weiter(geraet, datei)
            return
        self._auswertung_einreihen(geraet, datei, pfad, transkript, auftrag_text, rueckfrage=False, vorrang=auftraege.VORRANG_GERAET)

    def _auswertung_einreihen(
        self, geraet: str, datei: str, pfad: Path, transkript: Path, auftrag_text: str, *, rueckfrage: bool, vorrang: int
    ) -> Auftrag | None:
        config = self.steuerung.konfiguration()
        besitzer = self.besitzer_von(geraet)
        wunsch = AuswertungsWunsch(
            transkript=transkript,
            ausgabe=self.steuerung.ausgabeordner(besitzer),
            systemprompt=auftrag_text,
            abschnitt_sekunden=chunking_service.auswertungs_abschnitt(config.get("geraete_live_abschnitt_sekunden")),
        )
        if config.get("geraete_live_auswertung_vorab", True):
            # Schon waehrend der Aufnahme berechnete Teilergebnisse uebernehmen. Dafuer bekommt das Modell hier wie
            # dort den Text ohne Sprecherangaben -- sonst passten die Eingaben nicht zusammen.
            wunsch.ohne_sprecher = True
            wunsch.vorab_auswertung = lambda: self.live.auswertung_fuer(pfad, warten=VORAB_AUSWERTUNG_WARTEN)
        self.status.setze(geraet, datei, live_service.AUSWERTUNG, 0.5, "Zusammenfassung wird erstellt")

        def danach(auftrag: Auftrag) -> None:
            self._auswertung_beendet(auftrag, pfad, geraet, datei, rueckfrage)

        try:
            return self.steuerung.auswertung_starten(
                wunsch,
                herkunft=f"geraet:{geraet}",
                vorrang=vorrang,
                nach_ende=danach,
                fortschritt_spiegeln=self._spiegel(geraet, datei, live_service.AUSWERTUNG),
                besitzer=besitzer,
            )
        except Ablauffehler as fehler:
            self._abschliessen(geraet, datei, pfad, live_service.FEHLER, f"Auswertung nicht möglich: {fehler.titel}")
            self.steuerung.hinweis(f"{fehler.titel}: {fehler.text}", stufe="fehler", quelle=geraet, code=fehler.code, bereich=fehler.bereich)
            return None

    def _auswertung_beendet(self, auftrag: Auftrag, pfad: Path, geraet: str, datei: str, rueckfrage: bool) -> None:
        with self._sperre:
            self._freigegeben.discard((geraet, datei))
        ergebnis = auftrag.ergebnis or {}
        if auftrag.status is Status.ABGEBROCHEN:
            self._abschliessen(geraet, datei, pfad, live_service.FEHLER, "Die Auswertung wurde abgebrochen.")
        elif auftrag.status is not Status.FERTIG or ergebnis.get("protokoll_fehler"):
            self._abschliessen(geraet, datei, pfad, live_service.FEHLER, "Die Auswertung ist fehlgeschlagen.")
        else:
            if ergebnis.get("protokoll_md"):
                self._ergebnis_merken(geraet, datei, zusammenfassung=Path(ergebnis["protokoll_md"]))
            meldung = "Zusammenfassung fertig" if rueckfrage else "Transkription erfolgreich"
            self._abschliessen(geraet, datei, pfad, live_service.FERTIG, meldung)

    def _abschliessen(self, geraet: str, datei: str, pfad: Path, zustand: str, meldung: str) -> None:
        self.status.setze(geraet, datei, zustand, 1.0 if zustand == live_service.FERTIG else None, meldung)
        if zustand == live_service.FERTIG:
            self.live.freigeben(pfad)
        self._verarbeitung_erledigt(pfad)
        self._zuletzt(f"{meldung}: {pfad.name} von {geraet}")

    # ------------------------------------------------------------------
    # Rueckfrage am Geraet
    # ------------------------------------------------------------------
    def zusammenfassung_gewuenscht(self, geraet: str, datei: str) -> None:
        """Das Geraet hat die Zusammenfassung freigegeben: vor allen anderen Auftraegen."""
        with self._sperre:
            freigabe = self._freigaben.get((geraet, datei))
            if freigabe is None or (geraet, datei) in self._freigegeben:
                return
            self._freigegeben.add((geraet, datei))
        self._zusammenfassung_erstellen(geraet, datei, vorrang=auftraege.VORRANG_FREIGABE)

    def _zusammenfassung_erstellen(self, geraet: str, datei: str, *, vorrang: int) -> None:
        with self._sperre:
            freigabe = self._freigaben.pop((geraet, datei), None)
            self._nachholen.discard((geraet, datei))
        if freigabe is None:
            return  # schon erledigt
        self._zuletzt(f"Zusammenfassung wird erstellt: {freigabe.pfad.name} von {geraet}")
        self._auswertung_einreihen(
            geraet, datei, freigabe.pfad, freigabe.transkript, freigabe.auftrag, rueckfrage=True, vorrang=vorrang
        )

    def zusammenfassung_abgelehnt(self, geraet: str, datei: str) -> None:
        """Am Geraet "Nein": Das Transkript bleibt, eine Zusammenfassung gibt es nicht."""
        with self._sperre:
            if (geraet, datei) in self._freigegeben:
                return  # "Ja" kam zuerst und gilt
            self._nachholen.discard((geraet, datei))
        self._ohne_zusammenfassung_abschliessen(geraet, datei, "ohne Zusammenfassung (am Gerät abgelehnt)")

    def geraet_weitergezogen(self, geraet: str, neue_datei: str) -> None:
        """Das Geraet hat eine neue Aufnahme begonnen: Nach frueheren fragt es nicht mehr."""
        with self._sperre:
            offen = [s for s in self._freigaben if s[0] == geraet and s[1] != neue_datei and s not in self._freigegeben]
        for schluessel in offen:
            self.ohne_antwort_weiter(*schluessel)

    def ohne_antwort_weiter(self, geraet: str, datei: str) -> None:
        """Niemand beantwortet die Rueckfrage mehr. Reicht die Grafikkarte fuer die Zusammenfassung neben der
        neuen Aufnahme, wird sie nachgeholt (nach allem anderen); sonst bleibt es beim Transkript."""
        with self._sperre:
            if (geraet, datei) not in self._freigaben or (geraet, datei) in self._nachholen:
                return
        if self._nebenher_moeglich():
            with self._sperre:
                self._nachholen.add((geraet, datei))
            self._zuletzt(f"Zusammenfassung ohne Rückfrage folgt: {datei} von {geraet}")
            self._zusammenfassung_erstellen(geraet, datei, vorrang=auftraege.VORRANG_NACHHOLEN)
        else:
            self._ohne_zusammenfassung_abschliessen(
                geraet, datei, "ohne Zusammenfassung (Grafikspeicher reicht nicht neben der neuen Aufnahme)"
            )

    def _ohne_zusammenfassung_abschliessen(self, geraet: str, datei: str, grund: str) -> None:
        with self._sperre:
            freigabe = self._freigaben.pop((geraet, datei), None)
        if freigabe is None:
            return
        self.status.setze(geraet, datei, live_service.FERTIG, 1.0, "Transkription erfolgreich")
        self.live.freigeben(freigabe.pfad)
        self._verarbeitung_erledigt(freigabe.pfad)
        self._zuletzt(f"Transkript fertig, {grund}: {freigabe.pfad.name} von {geraet}")

    def _nebenher_moeglich(self) -> bool:
        config = self.steuerung.konfiguration()
        if self.abh.nebenher_moeglich is not None:
            return self.abh.nebenher_moeglich(config)
        if config.get("nachbearbeitung_modus") == "api":
            return True
        modell = str(config.get("ollama_modell") or ollama_service.DEFAULT_MODEL)
        bedarf = max(ollama_service.belegter_grafikspeicher(timeout=2), ollama_service.geschaetzter_grafikspeicher(modell) or 0)
        return model_service.sprachmodell_passt_neben_whisper(model_service.gesamter_grafikspeicher(), bedarf or None)

    def wartende_freigaben(self) -> list[dict[str, str]]:
        with self._sperre:
            return [{"geraet": g, "datei": d, "pfad": str(f.pfad)} for (g, d), f in self._freigaben.items()]

    # ------------------------------------------------------------------
    # Fragen per Sprache
    # ------------------------------------------------------------------
    def _ergebnis_merken(self, geraet: str, datei: str, **pfade: Path) -> None:
        with self._sperre:
            eintrag = self._ergebnisse.setdefault((geraet, datei), {})
            eintrag.update(pfade)
            while len(self._ergebnisse) > MAX_ERGEBNISSE:
                del self._ergebnisse[next(iter(self._ergebnisse))]

    def _frage_bereit(self, geraet: str, datei: str) -> bool:
        with self._sperre:
            return "transkript" in self._ergebnisse.get((geraet, datei), {})

    def _frage_erkennen(self, ton: bytes, endung: str) -> str:
        with self._sperre:
            if self._frage_transkribierer is None:
                self._frage_transkribierer = self._live_transkribierer()
            transkribieren = self._frage_transkribierer
        return geraete_fragen.frage_verstehen(ton, endung, transkribieren=transkribieren, extrahieren=live_service.standard_extrahieren)

    def _frage_beantworten(self, frage: str, geraet: str, datei: str, ausgabe: str) -> str:
        with self._sperre:
            eintrag = dict(self._ergebnisse.get((geraet, datei), {}))
        unterlagen = [p for p in (eintrag.get("zusammenfassung"), eintrag.get("transkript")) if p is not None]
        konfig = self.steuerung.konfiguration()
        modell = konfig.get("chatbot_ollama_modell") or konfig.get("ollama_modell") or ollama_service.DEFAULT_MODEL
        # Immer lokal und mit dem ganzen Text: Das Geraet fragt im eigenen Netz, ohne Einbettungsmodell.
        einstellungen = chat_service.ChatEinstellungen("lokal", modell, "", kontext=chat_service.KONTEXT_VOLLTEXT)
        _embed, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
        return geraete_fragen.antwort_aus_unterlagen(frage, unterlagen, chat_fn, ausgabe)

    # ------------------------------------------------------------------
    # Ollama-Wache
    # ------------------------------------------------------------------
    def ollama_wird_gebraucht(self, config: dict[str, Any]) -> bool:
        """Liefert ein Geraet an und wird lokal ausgewertet? Dann braucht es Ollama, auch ohne jemanden davor.
        Nicht waehrend der Ersteinrichtung: Sie installiert Ollama erst."""
        return (
            bool(config.get("einrichtung_abgeschlossen"))
            and bool(config.get("geraete_empfang_aktiv"))
            and config.get("nachbearbeitung_modus") != "api"
        )

    def wache_starten(self) -> None:
        if self._wache_faden is not None:
            return
        self._wache_stopp.clear()
        self._wache_faden = threading.Thread(target=self._wache_schleife, name="ollama-wache", daemon=True)
        self._wache_faden.start()

    def _wache_schleife(self) -> None:
        while not self._wache_stopp.wait(OLLAMA_WACHE_SEKUNDEN):
            try:
                self.ollama_pruefen()
            except Exception as fehler:  # die Wache darf nie sterben
                self.steuerung.hinweis(f"Ollama-Prüfung gescheitert: {fehler}", stufe="warnung", quelle="ollama")

    def ollama_pruefen(self) -> None:
        """Laeuft der Dienst noch? Sonst neu starten; fehlt das Modell, einmal melden."""
        config = self.steuerung.konfiguration()
        if not self.ollama_wird_gebraucht(config):
            return
        modell = str(config.get("ollama_modell") or ollama_service.DEFAULT_MODEL)
        if not self.abh.ollama_laeuft():
            self._ollama_modell_gemeldet = None
            if not self.abh.ollama_starten():
                self._ollama_problem_aktiv = True
                self.steuerung.hinweis(
                    "Die KI für Zusammenfassungen läuft nicht und ließ sich nicht starten.",
                    stufe="fehler",
                    quelle="ollama",
                    code="ki_nicht_erreichbar",
                )
                return
            self._ollama_problem_aktiv = False
            self.steuerung.hinweis("Die KI für Zusammenfassungen wurde neu gestartet.", quelle="ollama", code="ki_neu_gestartet")
        if self.abh.modell_fehlt(modell):
            if self._ollama_modell_gemeldet != modell:
                self._ollama_modell_gemeldet = modell
                self._ollama_problem_aktiv = True
                self.steuerung.hinweis(
                    "Das Sprachmodell für Zusammenfassungen fehlt noch.",
                    stufe="fehler",
                    quelle="ollama",
                    code="modell_fehlt",
                )
            return
        self._ollama_modell_gemeldet = None
        if self._ollama_problem_aktiv:
            self._ollama_problem_aktiv = False
            self.steuerung.hinweis("", stufe="erledigt", quelle="ollama")


def _port(wert: Any) -> int:
    try:
        port = int(wert)
    except (TypeError, ValueError):
        return geraete_empfang_service.STANDARD_PORT
    return port if 1 <= port <= 65535 else geraete_empfang_service.STANDARD_PORT
