"""Geteilte Besprechungen im Servermodus.

Jeder Nutzer hat seinen eigenen Ordner; eine Besprechung gehoert ihrem
Besitzer. Er kann sie mit einzelnen Kollegen oder mit allen teilen. Geteilt
heisst: lesen, herunterladen und im Chat danach fragen. Bearbeiten,
umbenennen und neu auswerten darf nur der Besitzer.

Gespeichert in ``freigaben.json`` im gemeinsamen Ausgabeordner:
``{"<besitzer>~<transkript-stamm>": ["alle"] | ["anna", "ben"]}``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

ALLE = "alle"
TRENNER = "~"


def kennung(besitzer: str, stamm: str) -> str:
    return f"{besitzer}{TRENNER}{stamm}"


def zerlegen(wert: str) -> tuple[str, str] | None:
    besitzer, trenner, stamm = wert.partition(TRENNER)
    return (besitzer, stamm) if trenner and besitzer and stamm else None


_SPERREN: dict[str, threading.Lock] = {}
_SPERREN_SPERRE = threading.Lock()


def _sperre_fuer(datei: Path) -> threading.Lock:
    """Eine Sperre je Datei, nicht je Objekt: Die Endpunkte bauen bei jeder Anfrage ein neues ``Freigaben``, und
    FastAPI fuehrt sie parallel in einem Threadpool aus. Eine Sperre im Objekt schuetzte dann nichts -- zwei
    gleichzeitige Aenderungen laesen denselben Stand, und eine Freigabe ginge verloren."""
    schluessel = os.path.normcase(str(datei.resolve()))
    with _SPERREN_SPERRE:
        return _SPERREN.setdefault(schluessel, threading.Lock())


class Freigaben:
    def __init__(self, datei: Path):
        self.datei = datei
        self._sperre = _sperre_fuer(datei)

    def _lesen(self) -> dict[str, list[str]]:
        try:
            roh = json.loads(self.datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(roh, dict):
            return {}
        return {str(k): [str(x) for x in v] for k, v in roh.items() if isinstance(v, list)}

    def _schreiben(self, daten: dict[str, list[str]]) -> None:
        self.datei.parent.mkdir(parents=True, exist_ok=True)
        # Eindeutiger Arbeitsname: Ein fester ("freigaben.json.tmp") wuerde von einem zweiten Schreiber (anderer
        # Prozess, gleicher Ordner) ueberschrieben oder ihm unter den Fuessen weggeschoben.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.datei.parent, prefix=self.datei.name + ".", suffix=".tmp", delete=False
        ) as handle:
            json.dump(daten, handle, ensure_ascii=False, indent=2)
            temp = Path(handle.name)
        try:
            _ersetzen_mit_wiederholung(temp, self.datei)
        except OSError:
            temp.unlink(missing_ok=True)
            raise

    def mit_wem(self, besitzer: str, stamm: str) -> list[str]:
        with self._sperre:
            return list(self._lesen().get(kennung(besitzer, stamm), []))

    def setzen(self, besitzer: str, stamm: str, mit: list[str]) -> list[str]:
        """Ersetzt die Freigabe. Leere Liste = nicht mehr geteilt. ``alle`` schliesst Einzelne ein."""
        sauber = sorted({m.strip() for m in mit if m.strip() and m.strip().lower() != besitzer.lower()})
        if ALLE in sauber:
            sauber = [ALLE]
        with self._sperre:
            daten = self._lesen()
            if sauber:
                daten[kennung(besitzer, stamm)] = sauber
            else:
                daten.pop(kennung(besitzer, stamm), None)
            self._schreiben(daten)
        return sauber

    def sichtbar_fuer(self, nutzer: str) -> list[tuple[str, str]]:
        """(Besitzer, Stamm) aller Besprechungen anderer, die ``nutzer`` sehen darf."""
        with self._sperre:
            daten = self._lesen()
        ergebnis = []
        for schluessel, mit in daten.items():
            teile = zerlegen(schluessel)
            if teile is None or teile[0].lower() == nutzer.lower():
                continue
            if ALLE in mit or nutzer.lower() in {m.lower() for m in mit}:
                ergebnis.append(teile)
        return ergebnis

    def darf_lesen(self, nutzer: str, besitzer: str, stamm: str) -> bool:
        if nutzer.lower() == besitzer.lower():
            return True
        mit = self.mit_wem(besitzer, stamm)
        return ALLE in mit or nutzer.lower() in {m.lower() for m in mit}
