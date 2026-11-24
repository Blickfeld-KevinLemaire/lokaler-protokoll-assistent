"""Was alle Endpunkte einer App-Instanz gemeinsam haben: Dienste, wer angemeldet ist, wessen Ordner gilt."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

from protokoll_assistent.ablauf.aufnahme import Aufnahmesteuerung
from protokoll_assistent.ablauf.freigaben import Freigaben
from protokoll_assistent.ablauf.geraete_automatik import GeraeteAutomatik
from protokoll_assistent.ablauf.nutzer import Nutzerverwaltung
from protokoll_assistent.ablauf.steuerung import NUTZER_ORDNER, Steuerung
from protokoll_assistent.api.sicherheit import ROLLE_DESKTOP, Zugang


@dataclass(frozen=True)
class Angemeldet:
    name: str
    admin: bool
    # Mehrere Nutzer: Anmeldename des Besitzers eigener Daten; sonst None (alles gehoert dem einen Menschen).
    besitzer: str | None


@dataclass
class Dienste:
    steuerung: Steuerung
    automatik: GeraeteAutomatik | None
    zugang: Zugang
    # Ordner, in den Hochgeladenes kommt. Ohne Angabe: der Aufnahmeordner der Steuerung (je Nutzer).
    hochlade_ordner: Callable[[], Path] | None = None
    # Zusaetzliche Ordner, aus denen im Netz Dateien per Pfad angegeben werden duerfen.
    erlaubte_ordner: Callable[[], list[Path]] = list
    # Wird nach dem Speichern der Einstellungen aufgerufen (Empfang neu anwenden usw.).
    nach_einstellungen: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    plattform_windows: bool = os.name == "nt"
    # Beendet den Dienst fuer einen Neustart durch das Fenster (siehe ``api/__main__``); None: geht hier nicht.
    neustart_anfordern: Callable[[], None] | None = None
    # Mikrofonaufnahme (nur Windows-Anwendung); None: gibt es hier nicht.
    aufnahme: Aufnahmesteuerung | None = None

    @property
    def rolle(self) -> str:
        return self.zugang.rolle

    @property
    def ist_desktop(self) -> bool:
        return self.rolle == ROLLE_DESKTOP

    @property
    def nutzer(self) -> Nutzerverwaltung | None:
        return self.zugang.nutzer

    @property
    def mehrbenutzer(self) -> bool:
        return self.zugang.nutzer is not None

    def freigaben(self) -> Freigaben:
        return Freigaben(self.steuerung.ausgabe_basis() / "freigaben.json")

    # ------------------------------------------------------------------
    # Ordner je Angemeldetem
    # ------------------------------------------------------------------
    def ausgabeordner(self, wer: Angemeldet | None = None) -> Path:
        return self.steuerung.ausgabeordner(wer.besitzer if wer is not None else None)

    def ausgabe_basis(self) -> Path:
        return self.steuerung.ausgabe_basis()

    def ausgabeordner_von(self, besitzer: str | None) -> Path:
        return self.steuerung.ausgabeordner(besitzer)

    def aufnahmeordner(self, wer: Angemeldet | None = None) -> Path:
        if self.hochlade_ordner is not None and (wer is None or wer.besitzer is None):
            return self.hochlade_ordner()
        return self.steuerung.aufnahmeordner(wer.besitzer if wer is not None else None)

    def pfad_pruefen(self, text: str, wer: Angemeldet | None = None) -> Path:
        """Ein vom Aufrufer genannter Pfad. Auf dem eigenen Rechner (desktop) jeder vorhandene; im Netz nur
        einer in den eigenen bzw. freigegebenen Ordnern -- sonst koennte jeder Angemeldete beliebige Dateien
        des Servers verarbeiten lassen."""
        if not text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Pfad angegeben.")
        pfad = Path(text).expanduser()
        if self.ist_desktop:
            return pfad
        aufgeloest = pfad.resolve()
        ordner = [self.aufnahmeordner(wer), self.ausgabeordner(wer)]
        if not self.mehrbenutzer:
            ordner += self.erlaubte_ordner()
            eingabe = self.steuerung.konfiguration().get("eingabeordner")
            if eingabe:
                ordner.append(Path(eingabe))
        for basis in ordner:
            if _liegt_in(aufgeloest, basis):
                return aufgeloest
        if (
            self.mehrbenutzer
            and wer is not None
            and wer.admin
            and _liegt_in(aufgeloest, self.ausgabe_basis())
            and not _liegt_in(aufgeloest, self.ausgabe_basis() / NUTZER_ORDNER)
        ):
            # Ergebnisse ohne Besitzer (allgemeiner Ordner) verwalten die Admins -- die Ordner der Nutzer nicht.
            return aufgeloest
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Auf diesen Ordner gibt es hier keinen Zugriff.")


def _liegt_in(pfad: Path, basis: Path) -> bool:
    try:
        pfad.relative_to(basis.resolve())
    except ValueError:
        return False
    return True


def dienste(request: Request) -> Dienste:
    return request.app.state.dienste  # type: ignore[no-any-return]


def angemeldet(request: Request) -> Angemeldet:
    d = dienste(request)
    name = d.zugang.wer(request)
    if name is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet.")
    besitzer = name if d.mehrbenutzer and name != "umgebung" else None
    return Angemeldet(name=name, admin=d.zugang.ist_admin(name), besitzer=besitzer)


def nur_admin(request: Request) -> Angemeldet:
    wer = angemeldet(request)
    if not wer.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Das darf nur ein Admin.")
    return wer


def nur_desktop(request: Request) -> Dienste:
    d = dienste(request)
    if not d.ist_desktop:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur in der Windows-Anwendung verfügbar.")
    return d


def automatik(d: Dienste) -> GeraeteAutomatik:
    if d.automatik is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Der Empfang für Aufnahmegeräte ist hier nicht eingerichtet.")
    return d.automatik
