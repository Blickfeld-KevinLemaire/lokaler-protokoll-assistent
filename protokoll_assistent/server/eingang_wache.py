"""Der Eingangsordner des Servermodus als Lieferant der gemeinsamen Auftragswarteschlange.

Frueher arbeitete ``server/dienst.py`` den Eingang in einer eigenen Schleife ab
-- neben dem Empfang der Aufnahmegeraete, ohne von ihm zu wissen. Jetzt reiht
diese Wache jede fertige Datei als Auftrag ein (Herkunft ``ordner``); die
Verarbeitung selbst ist unveraendert ``verarbeitung.verarbeite`` (Transkript,
Protokoll, weitere Formate, ``ergebnis.json``, Webhook). Danach wandert die
Datei nach ``verarbeitet/`` bzw. ``fehler/`` wie bisher.

Mit mehreren Nutzern gehoeren die Ergebnisse dem in ``PROTOKOLL_EINGANG_NUTZER``
genannten Nutzer (sonst niemandem -- dann sehen sie nur Admins).
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.auftraege import Auftrag, Fortschritt, Status
from protokoll_assistent.ablauf.steuerung import Steuerung
from protokoll_assistent.server import verarbeitung, warteschlange
from protokoll_assistent.server.einstellungen import ServerEinstellungen

logger = logging.getLogger("protokoll_assistent.server")
ART = "verarbeitung"


class EingangsWache:
    def __init__(
        self,
        steuerung: Steuerung,
        einstellungen: ServerEinstellungen,
        zustand_datei: Path,
        *,
        besitzer: str | None = None,
        verarbeiten: Any = verarbeitung.verarbeite,
        webhook: Any = verarbeitung.melde_webhook,
    ):
        self.steuerung = steuerung
        self.einstellungen = einstellungen
        self.besitzer = besitzer
        self._verarbeiten = verarbeiten
        self._webhook = webhook
        self._zustand = warteschlange.Zustand(zustand_datei)
        self._beobachter = warteschlange.Beobachter(einstellungen.eingang, einstellungen.stabil_sekunden, self._zustand)
        self._eingereiht: set[Path] = set()
        self._sperre = threading.Lock()
        self._stopp = threading.Event()
        self._faden: threading.Thread | None = None

    def einmal(self) -> list[Auftrag]:
        """Eine Abfrage: alle jetzt fertigen, noch nicht eingereihten Dateien einreihen."""
        neu = []
        for datei in self._beobachter.bereite_dateien():
            with self._sperre:
                if datei in self._eingereiht:
                    continue
                self._eingereiht.add(datei)
            neu.append(self._einreihen(datei))
        return neu

    def _einreihen(self, datei: Path) -> Auftrag:
        schluessel = self._beobachter.schluessel(datei)
        einstellungen = dataclasses.replace(self.einstellungen, ausgang=self.steuerung.ausgabeordner(self.besitzer))

        def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
            ergebnis = self._verarbeiten(
                datei, einstellungen, abbrechen=fortschritt.abbruch_gewuenscht, protokollieren=fortschritt.meldung
            )
            daten: dict[str, Any] = ergebnis.als_dict()
            if ergebnis.status == verarbeitung.STATUS_FEHLER:
                raise RuntimeError(ergebnis.fehler or "Die Verarbeitung ist fehlgeschlagen.")
            return daten

        def danach(auftrag: Auftrag) -> None:
            with self._sperre:
                self._eingereiht.discard(datei)
            if auftrag.status is Status.ABGEBROCHEN:
                logger.info("Abgebrochen: %s bleibt im Eingang.", datei.name)
                return
            ok = auftrag.status is Status.FERTIG
            ziel = warteschlange.ORDNER_VERARBEITET if ok else warteschlange.ORDNER_FEHLER
            if schluessel is not None:
                self._zustand.merke(schluessel, verarbeitung.STATUS_FERTIG if ok else verarbeitung.STATUS_FEHLER)
            if warteschlange.verschiebe_nach(datei, self.einstellungen.eingang, ziel) is None:
                logger.warning("%s konnte nicht verschoben werden; sie wird nicht noch einmal verarbeitet.", datei.name)
            self.steuerung.bus.senden("dateien", {"grund": "eingang_verarbeitet", "datei": datei.name})
            if self.einstellungen.webhook_url:
                nutzlast = auftrag.ergebnis or {"status": verarbeitung.STATUS_FEHLER, "datei": datei.name, "fehler": auftrag.fehler}
                problem = self._webhook(self.einstellungen.webhook_url, nutzlast, self.einstellungen.webhook_token)
                if problem:
                    logger.warning("Webhook nicht zugestellt: %s", problem)

        return self.steuerung.auftraege.einreihen(
            ART, datei.name, ausfuehren, herkunft="ordner", angaben={"quelle": str(datei)}, nach_ende=danach, besitzer=self.besitzer
        )

    # ------------------------------------------------------------------
    def starten(self) -> None:
        if self._faden is not None:
            return
        self.einstellungen.eingang.mkdir(parents=True, exist_ok=True)
        self._stopp.clear()
        self._faden = threading.Thread(target=self._schleife, name="eingang", daemon=True)
        self._faden.start()
        logger.info("Beobachte %s", self.einstellungen.eingang)

    def _schleife(self) -> None:
        while not self._stopp.wait(self.einstellungen.abfrage_sekunden):
            try:
                self.einmal()
            except Exception:  # die Wache darf nie sterben
                logger.exception("Eingang konnte nicht gelesen werden")

    def stoppen(self) -> None:
        self._stopp.set()
