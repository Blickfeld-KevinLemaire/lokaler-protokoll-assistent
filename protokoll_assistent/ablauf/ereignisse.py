"""Ereignisse fuer die Oberflaeche: fortlaufend nummeriert, kurz gepuffert.

Die Oberflaeche holt sich zuerst einen vollstaendigen Zustand (mit der Nummer
des letzten Ereignisses) und abonniert danach alle Ereignisse *ab dieser
Nummer*. So geht zwischen "Zustand laden" und "Abo steht" nichts verloren, und
eine abgerissene Verbindung setzt mit ``Last-Event-ID`` genau dort wieder an.

Ist die gewuenschte Nummer schon aus dem Puffer gefallen (Rechner lag im
Ruhezustand, Verbindung war lange weg), bekommt das Abo als Erstes ein
Ereignis ``neu_laden``: Dann laedt die Oberflaeche den Zustand neu, statt mit
Luecken weiterzuarbeiten.

Zugestellt wird ueber eine Funktion je Abonnent. Die Programmschnittstelle
reicht dort ``loop.call_soon_threadsafe`` herein -- der Bus selbst kennt
weder asyncio noch Faeden ausser seiner eigenen Sperre.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PUFFER_GROESSE = 2000
NEU_LADEN = "neu_laden"


@dataclass(frozen=True)
class Ereignis:
    nummer: int
    art: str
    daten: dict[str, Any] = field(default_factory=dict)
    zeit: float = 0.0

    def als_dict(self) -> dict[str, Any]:
        return {"nummer": self.nummer, "art": self.art, "daten": self.daten, "zeit": self.zeit}


Zustellung = Callable[[Ereignis], object]


class Abo:
    """Ein angemeldeter Empfaenger. ``beenden`` meldet ihn ab (mehrfach harmlos)."""

    def __init__(self, bus: Ereignisbus, schluessel: int):
        self._bus = bus
        self._schluessel = schluessel

    def beenden(self) -> None:
        self._bus._abmelden(self._schluessel)


class Ereignisbus:
    def __init__(self, puffer_groesse: int = PUFFER_GROESSE, *, jetzt: Callable[[], float] = time.time):
        self._sperre = threading.Lock()
        self._puffer: deque[Ereignis] = deque(maxlen=puffer_groesse)
        self._nummer = 0
        self._empfaenger: dict[int, Zustellung] = {}
        self._schluessel = itertools.count(1)
        self._jetzt = jetzt

    @property
    def letzte_nummer(self) -> int:
        with self._sperre:
            return self._nummer

    def senden(self, art: str, daten: dict[str, Any] | None = None) -> Ereignis:
        # Zugestellt wird unter der Sperre: Nur so kommen die Ereignisse bei jedem Abonnenten in der
        # Reihenfolge ihrer Nummern an (ein Fortschritt 0,4 nach 0,5 liesse den Balken springen). Deshalb
        # duerfen Zustellfunktionen nicht blockieren -- sie reihen nur ein.
        with self._sperre:
            self._nummer += 1
            ereignis = Ereignis(self._nummer, art, dict(daten or {}), self._jetzt())
            self._puffer.append(ereignis)
            for zustellen in list(self._empfaenger.values()):
                try:
                    zustellen(ereignis)
                except Exception:  # noqa: S112 -- ein kaputtes Abo darf die anderen nicht treffen
                    continue
        return ereignis

    def abonnieren(self, zustellen: Zustellung, seit: int | None = None) -> Abo:
        """Meldet ``zustellen`` an. Mit ``seit`` kommen zuerst alle gepufferten
        Ereignisse mit groesserer Nummer -- oder ``neu_laden``, wenn welche fehlen.

        Nachholen und Anmelden geschehen unter derselben Sperre wie das Senden: Ein gleichzeitig
        gesendetes Ereignis kommt so genau einmal und an der richtigen Stelle an."""
        with self._sperre:
            schluessel = next(self._schluessel)
            if seit is not None and seit < self._nummer:
                aeltestes = self._puffer[0].nummer if self._puffer else self._nummer + 1
                if seit + 1 < aeltestes:
                    zustellen(Ereignis(self._nummer, NEU_LADEN, {"grund": "luecke"}, self._jetzt()))
                else:
                    for ereignis in self._puffer:
                        if ereignis.nummer > seit:
                            zustellen(ereignis)
            self._empfaenger[schluessel] = zustellen
        return Abo(self, schluessel)

    def _abmelden(self, schluessel: int) -> None:
        with self._sperre:
            self._empfaenger.pop(schluessel, None)

    @property
    def anzahl_abos(self) -> int:
        with self._sperre:
            return len(self._empfaenger)
