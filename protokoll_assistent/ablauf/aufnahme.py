"""Mikrofonaufnahme in der Windows-Anwendung (ohne Qt).

Frueher steuerte das Hauptfenster ``services/recording_service.MikrofonAufnahme``
direkt und las den Pegel im Takt seiner Anzeige. Hier steuert die
Programmschnittstelle; Pegel, Dauer und Zustand gehen fuenfmal je Sekunde als
Ereignis ``aufnahme`` an die Oberflaeche.

``recording_service`` importiert ``sounddevice`` beim Laden. In der
Rechenumgebung des lokalen Modus fehlt das Paket unter Umstaenden -- deshalb
wird das Modul erst bei Bedarf geladen; fehlt es, gibt es eben keine Aufnahme
(``verfuegbar`` ist dann falsch), der Rest laeuft weiter.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from protokoll_assistent.ablauf.ereignisse import Ereignisbus

MELDE_ABSTAND_SEKUNDEN = 0.2


class AufnahmeFehler(RuntimeError):
    pass


def _modul_laden() -> ModuleType:
    return importlib.import_module("protokoll_assistent.services.recording_service")


class Aufnahmesteuerung:
    def __init__(
        self,
        bus: Ereignisbus,
        ziel_ordner: Callable[[], Path],
        *,
        modul_laden: Callable[[], ModuleType] = _modul_laden,
        konfiguration: Callable[[], dict[str, Any]] = dict,
        merken: Callable[[str], object] = lambda name: None,
    ):
        self._bus = bus
        self._ziel_ordner = ziel_ordner
        self._modul_laden = modul_laden
        self._konfiguration = konfiguration
        self._merken = merken
        self._sperre = threading.Lock()
        self._aufnahme: Any = None
        self._stopp = threading.Event()
        self._melder: threading.Thread | None = None

    def _modul(self) -> ModuleType:
        try:
            return self._modul_laden()
        except (ImportError, OSError) as fehler:
            raise AufnahmeFehler("Aufnehmen ist auf diesem Computer gerade nicht möglich.") from fehler

    @property
    def verfuegbar(self) -> bool:
        try:
            self._modul()
        except AufnahmeFehler:
            return False
        return True

    def geraete(self) -> list[dict[str, Any]]:
        modul = self._modul()
        try:
            liste = modul.liste_aufnahmegeraete()
            standard = modul.standard_eingabe_index()
        except Exception as fehler:
            raise AufnahmeFehler("Die Mikrofone ließen sich nicht abfragen.") from fehler
        gespeichert = self._konfiguration().get("aufnahmegeraet")
        return [
            {"name": g.anzeigename, "standard": g.index == standard, "gewaehlt": g.anzeigename == gespeichert}
            for g in liste
        ]

    def stand(self) -> dict[str, Any]:
        with self._sperre:
            a = self._aufnahme
            if a is None:
                return {"laeuft": False, "pausiert": False, "dauer": 0.0, "pegel": 0.0, "geraet": None}
            return {
                "laeuft": True,
                "pausiert": bool(a.ist_pausiert),
                "dauer": round(float(a.dauer_sekunden), 1),
                "pegel": round(float(a.pegel), 3),
                "geraet": a.geraet.anzeigename,
            }

    def starten(self, geraet_name: str | None = None) -> dict[str, Any]:
        modul = self._modul()
        with self._sperre:
            if self._aufnahme is not None:
                raise AufnahmeFehler("Es läuft schon eine Aufnahme.")
            try:
                liste = modul.liste_aufnahmegeraete()
            except Exception as fehler:
                raise AufnahmeFehler("Die Mikrofone ließen sich nicht abfragen.") from fehler
            gewuenscht = geraet_name or self._konfiguration().get("aufnahmegeraet")
            geraet, _hinweis = modul.waehle_startgeraet(liste, gewuenscht, modul.standard_eingabe_index())
            if geraet is None:
                raise AufnahmeFehler("Es ist kein Mikrofon angeschlossen.")
            ordner = self._ziel_ordner()
            ordner.mkdir(parents=True, exist_ok=True)
            aufnahme = modul.MikrofonAufnahme(geraet, ordner / modul.erzeuge_dateiname())
            try:
                aufnahme.start()
            except Exception as fehler:
                raise AufnahmeFehler(f"Das Mikrofon ließ sich nicht öffnen ({fehler}).") from fehler
            self._aufnahme = aufnahme
            self._stopp.clear()
            self._melder = threading.Thread(target=self._melden, name="aufnahme", daemon=True)
            self._melder.start()
        self._merken(geraet.anzeigename)
        return self.stand()

    def pausieren(self) -> dict[str, Any]:
        with self._sperre:
            self._laufende().pause()
        return self.stand()

    def fortsetzen(self) -> dict[str, Any]:
        with self._sperre:
            self._laufende().fortsetzen()
        return self.stand()

    def stoppen(self) -> dict[str, Any]:
        with self._sperre:
            aufnahme = self._laufende()
            dauer = float(aufnahme.dauer_sekunden)
            self._aufnahme = None
            self._stopp.set()
        pfad: Path = aufnahme.stop()
        self._bus.senden("aufnahme", {"laeuft": False, "pausiert": False, "dauer": 0.0, "pegel": 0.0, "geraet": None})
        self._bus.senden("dateien", {"grund": "aufnahme", "pfad": str(pfad)})
        return {"pfad": str(pfad), "name": pfad.name, "dauer": round(dauer, 1)}

    def _laufende(self) -> Any:
        if self._aufnahme is None:
            raise AufnahmeFehler("Es läuft keine Aufnahme.")
        return self._aufnahme

    def _melden(self) -> None:
        while not self._stopp.wait(MELDE_ABSTAND_SEKUNDEN):
            with self._sperre:
                aufnahme = self._aufnahme
                fehler = aufnahme.fehler if aufnahme is not None else None
            if aufnahme is None:
                return
            if fehler:
                # Schreiben gescheitert (Platte voll ...): beenden, was bisher aufgenommen ist, bleibt erhalten.
                try:
                    self.stoppen()
                except AufnahmeFehler:
                    return
                self._bus.senden("hinweis", {"text": "Die Aufnahme wurde beendet: " + str(fehler), "stufe": "fehler", "quelle": "aufnahme", "code": "aufnahme_fehler"})
                return
            self._bus.senden("aufnahme", self.stand())
