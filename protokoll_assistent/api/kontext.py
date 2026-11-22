"""Was alle Endpunkte einer App-Instanz gemeinsam haben."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

from protokoll_assistent.ablauf.geraete_automatik import GeraeteAutomatik
from protokoll_assistent.ablauf.steuerung import Steuerung
from protokoll_assistent.api.sicherheit import ROLLE_DESKTOP, Zugang
from protokoll_assistent.utils.paths import get_recordings_dir


@dataclass
class Dienste:
    steuerung: Steuerung
    automatik: GeraeteAutomatik | None
    zugang: Zugang
    # Ordner, in den Hochgeladenes kommt (Browser im Netz, Aufnahme im Browser).
    hochlade_ordner: Callable[[], Path] = get_recordings_dir
    # Zusaetzliche Ordner, aus denen im Servermodus Dateien per Pfad angegeben werden duerfen.
    erlaubte_ordner: Callable[[], list[Path]] = list
    # Wird nach dem Speichern der Einstellungen aufgerufen (Empfang neu anwenden usw.).
    nach_einstellungen: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    plattform_windows: bool = os.name == "nt"

    @property
    def rolle(self) -> str:
        return self.zugang.rolle

    @property
    def ist_desktop(self) -> bool:
        return self.rolle == ROLLE_DESKTOP

    def ausgabeordner(self) -> Path:
        return self.steuerung.ausgabeordner()

    def pfad_pruefen(self, text: str) -> Path:
        """Ein vom Aufrufer genannter Pfad. Auf dem eigenen Rechner (desktop) jeder vorhandene; im Netz nur
        einer in den freigegebenen Ordnern -- sonst koennte jeder Angemeldete beliebige Dateien des Servers
        verarbeiten lassen."""
        if not text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Pfad angegeben.")
        pfad = Path(text).expanduser()
        if self.ist_desktop:
            return pfad
        aufgeloest = pfad.resolve()
        ordner = [self.hochlade_ordner(), self.ausgabeordner(), *self.erlaubte_ordner()]
        eingabe = self.steuerung.konfiguration().get("eingabeordner")
        if eingabe:
            ordner.append(Path(eingabe))
        for basis in ordner:
            try:
                aufgeloest.relative_to(basis.resolve())
            except ValueError:
                continue
            return aufgeloest
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dieser Ordner ist für den Zugriff über das Netz nicht freigegeben.")


def dienste(request: Request) -> Dienste:
    return request.app.state.dienste  # type: ignore[no-any-return]


def nur_desktop(request: Request) -> Dienste:
    d = dienste(request)
    if not d.ist_desktop:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur in der Windows-Anwendung verfügbar.")
    return d


def automatik(d: Dienste) -> GeraeteAutomatik:
    if d.automatik is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Der Empfang für Aufnahmegeräte ist hier nicht eingerichtet.")
    return d.automatik
