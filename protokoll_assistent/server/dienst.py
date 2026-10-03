"""Die Schleife des Servermodus: Eingang beobachten, verarbeiten, ablegen, melden."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protokoll_assistent.server import verarbeitung, warteschlange
from protokoll_assistent.server.einstellungen import ServerEinstellungen
from protokoll_assistent.server.verarbeitung import Ergebnis

logger = logging.getLogger("protokoll_assistent.server")


class Dienst:
    def __init__(
        self,
        einstellungen: ServerEinstellungen,
        zustand_datei: Path,
        *,
        verarbeiten: Callable[..., Ergebnis] = verarbeitung.verarbeite,
        webhook: Callable[..., str | None] = verarbeitung.melde_webhook,
        jetzt: Callable[[], float] = time.time,
        schlafen: Callable[[float], None] | None = None,
    ):
        self.einstellungen = einstellungen
        self._verarbeiten = verarbeiten
        self._webhook = webhook
        self._stopp = threading.Event()
        self._schlafen = schlafen or (lambda sekunden: self._stopp.wait(sekunden) and None)
        self._zustand = warteschlange.Zustand(zustand_datei)
        self._beobachter = warteschlange.Beobachter(
            einstellungen.eingang, einstellungen.stabil_sekunden, self._zustand, jetzt=jetzt
        )

    def stoppen(self) -> None:
        """Beendet nach der laufenden Datei -- oder bricht sie ab (sie wird beim
        naechsten Start fortgesetzt, weil die Chunk-Zwischenstaende erhalten bleiben)."""
        self._stopp.set()

    @property
    def gestoppt(self) -> bool:
        return self._stopp.is_set()

    # ------------------------------------------------------------------
    def einmal(self) -> int:
        """Eine Abfrage: alle jetzt fertigen Dateien der Reihe nach verarbeiten."""
        verarbeitet = 0
        for datei in self._beobachter.bereite_dateien():
            if self._stopp.is_set():
                break
            self._eine_datei(datei)
            verarbeitet += 1
        return verarbeitet

    def lauf(self) -> None:
        self.einstellungen.eingang.mkdir(parents=True, exist_ok=True)
        self.einstellungen.ausgang.mkdir(parents=True, exist_ok=True)
        logger.info("Beobachte %s -> Ergebnisse in %s", self.einstellungen.eingang, self.einstellungen.ausgang)
        while not self._stopp.is_set():
            self.einmal()
            self._schlafen(self.einstellungen.abfrage_sekunden)
        logger.info("Dienst beendet.")

    # ------------------------------------------------------------------
    def _eine_datei(self, datei: Path) -> None:
        schluessel = self._beobachter.schluessel(datei)
        logger.info("Verarbeite %s", datei.name)
        ergebnis = self._verarbeiten(
            datei,
            self.einstellungen,
            abbrechen=self._stopp.is_set,
            protokollieren=lambda text: logger.info("  %s", text),
        )
        if ergebnis.status == verarbeitung.STATUS_ABGEBROCHEN:
            logger.info("Abgebrochen: %s bleibt im Eingang und wird beim naechsten Start fortgesetzt.", datei.name)
            return

        ziel = warteschlange.ORDNER_VERARBEITET if ergebnis.status == verarbeitung.STATUS_FERTIG else warteschlange.ORDNER_FEHLER
        if ergebnis.status == verarbeitung.STATUS_FEHLER:
            logger.error("Fehler bei %s: %s", datei.name, ergebnis.fehler)
        else:
            logger.info("Fertig: %s -> %s", datei.name, ergebnis.ausgabe)
            if ergebnis.protokoll_fehler:
                logger.warning("Das Protokoll fehlt (%s); das Transkript liegt vor.", ergebnis.protokoll_fehler)
        if schluessel is not None:
            self._zustand.merke(schluessel, ergebnis.status, str(ergebnis.ausgabe) if ergebnis.ausgabe else None)
        verschoben = warteschlange.verschiebe_nach(datei, self.einstellungen.eingang, ziel)
        if verschoben is None:
            logger.warning("%s konnte nicht verschoben werden; sie wird nicht noch einmal verarbeitet.", datei.name)
        self._melden(ergebnis)

    def _melden(self, ergebnis: Ergebnis) -> None:
        if not self.einstellungen.webhook_url:
            return
        nutzlast: dict[str, Any] = ergebnis.als_dict()
        problem = self._webhook(self.einstellungen.webhook_url, nutzlast, self.einstellungen.webhook_token)
        if problem:
            logger.warning("Webhook nicht zugestellt: %s", problem)
