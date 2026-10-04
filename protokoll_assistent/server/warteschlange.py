"""Erkennt neue, fertig geschriebene Aufnahmen im Eingangsordner.

Ein Aufnahmegeraet (oder ein Kopiervorgang) schreibt eine Datei ueber Sekunden
bis Minuten. Angefasst wird sie erst, wenn sie bei zwei Abfragen hintereinander
gleich gross ist **und** seit ``stabil_sekunden`` nicht mehr veraendert wurde.
Fertig verarbeitete Dateien wandern in den Unterordner ``verarbeitet``,
fehlgeschlagene in ``fehler``; zusaetzlich merkt sich ein kleiner Zustand,
welche Dateien schon erledigt sind -- fuer den Fall, dass das Verschieben nicht
geht (schreibgeschuetzte Freigabe).
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung

AUDIO_ENDUNGEN = frozenset(
    {".mp3", ".mp4", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".mov", ".mkv", ".webm", ".wma", ".amr"}
)
ORDNER_VERARBEITET = "verarbeitet"
ORDNER_FEHLER = "fehler"
# Dateien, die Programme waehrend des Schreibens/Kopierens anlegen.
UNFERTIG_MARKEN = (".part", ".partial", ".tmp", ".temp", ".crdownload", ".filepart", ".lock")


def _schluessel(pfad: Path, groesse: int, mtime_ns: int, eingang: Path) -> str:
    try:
        relativ = pfad.relative_to(eingang).as_posix()
    except ValueError:
        relativ = pfad.name
    return f"{relativ}|{groesse}|{mtime_ns}"


class Zustand:
    """Merkt sich erledigte Dateien (Name + Groesse + Aenderungszeit)."""

    def __init__(self, datei: Path):
        self._datei = datei
        self._eintraege: dict[str, dict[str, Any]] = {}
        try:
            daten = json.loads(datei.read_text(encoding="utf-8"))
            if isinstance(daten, dict) and isinstance(daten.get("dateien"), dict):
                self._eintraege = daten["dateien"]
        except (OSError, ValueError):
            # Fehlt die Datei oder ist sie unlesbar, beginnt der Zustand leer.
            # Folge: Aufnahmen, die nicht verschoben werden konnten, werden
            # ein zweites Mal verarbeitet -- verloren geht nichts.
            pass

    def bekannt(self, schluessel: str) -> bool:
        return schluessel in self._eintraege

    def merke(self, schluessel: str, status: str, ausgabe: str | None = None) -> None:
        self._eintraege[schluessel] = {"status": status, "ausgabe": ausgabe, "zeit": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._speichern()

    def _speichern(self) -> None:
        self._datei.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._datei.parent, suffix=".tmp", delete=False
        ) as handle:
            json.dump({"version": 1, "dateien": self._eintraege}, handle, ensure_ascii=False, indent=2)
            temp = Path(handle.name)
        _ersetzen_mit_wiederholung(temp, self._datei)


class Beobachter:
    def __init__(
        self,
        eingang: Path,
        stabil_sekunden: float,
        zustand: Zustand,
        *,
        jetzt: Callable[[], float] = time.time,
    ):
        self._eingang = eingang
        self._stabil = stabil_sekunden
        self._zustand = zustand
        self._jetzt = jetzt
        # Pfad -> (Groesse, mtime_ns) bei der letzten Abfrage
        self._gesehen: dict[Path, tuple[int, int]] = {}

    def schluessel(self, pfad: Path) -> str | None:
        try:
            st = pfad.stat()
        except OSError:
            return None
        return _schluessel(pfad, st.st_size, st.st_mtime_ns, self._eingang)

    def _kandidaten(self) -> list[Path]:
        gefunden: list[Path] = []
        try:
            eintraege = sorted(self._eingang.rglob("*"))
        except OSError:
            return []
        for pfad in eintraege:
            teile = pfad.relative_to(self._eingang).parts
            if teile[0] in (ORDNER_VERARBEITET, ORDNER_FEHLER) or any(t.startswith(".") for t in teile):
                continue
            name = pfad.name.lower()
            if pfad.suffix.lower() not in AUDIO_ENDUNGEN or name.endswith(UNFERTIG_MARKEN) or name.startswith("~"):
                continue
            try:
                if pfad.is_file():
                    gefunden.append(pfad)
            except OSError:
                continue
        return gefunden

    def bereite_dateien(self) -> list[Path]:
        """Fertig geschriebene, noch nicht erledigte Dateien, aelteste zuerst."""
        bereit: list[tuple[int, Path]] = []
        vorhanden: set[Path] = set()
        for pfad in self._kandidaten():
            try:
                st = pfad.stat()
            except OSError:
                continue
            vorhanden.add(pfad)
            marke = (st.st_size, st.st_mtime_ns)
            vorher = self._gesehen.get(pfad)
            self._gesehen[pfad] = marke
            if st.st_size == 0 or vorher != marke:
                continue  # leer oder gerade noch veraendert
            if self._jetzt() - st.st_mtime_ns / 1e9 < self._stabil:
                continue  # zu frisch
            if self._zustand.bekannt(_schluessel(pfad, st.st_size, st.st_mtime_ns, self._eingang)):
                continue  # schon erledigt (Verschieben war nicht moeglich)
            bereit.append((st.st_mtime_ns, pfad))
        for weg in set(self._gesehen) - vorhanden:
            del self._gesehen[weg]
        return [pfad for _, pfad in sorted(bereit)]


def verschiebe_nach(pfad: Path, eingang: Path, unterordner: str) -> Path | None:
    """Raeumt die Datei in ``eingang/<unterordner>/`` (Struktur bleibt erhalten).

    Gibt den neuen Pfad zurueck oder ``None``, wenn das nicht geht (z. B.
    schreibgeschuetzte Freigabe) -- dann sorgt der ``Zustand`` dafuer, dass die
    Datei nicht noch einmal verarbeitet wird."""
    try:
        relativ = pfad.relative_to(eingang)
    except ValueError:
        relativ = Path(pfad.name)
    ziel = eingang / unterordner / relativ
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        zaehler = 2
        endgueltig = ziel
        while endgueltig.exists():
            endgueltig = ziel.with_name(f"{ziel.stem}_{zaehler}{ziel.suffix}")
            zaehler += 1
        pfad.replace(endgueltig)
    except OSError:
        return None
    return endgueltig
