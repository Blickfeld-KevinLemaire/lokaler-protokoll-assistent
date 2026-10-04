"""Protokoll in der Vorschau ansehen und korrigieren.

Die Auswertung des Modells steht in der Protokoll-JSON
(``<name>_protokoll_<zeit>.json``) und daneben als Markdown
(``....md``, das auch "Frag mein Meeting" liest). Korrigiert der Anwender den
Text in der Vorschau, wird sein Text **zusaetzlich** in der JSON abgelegt
(``dokument_export_service.SCHLUESSEL_KORRIGIERT``); die urspruengliche
Auswertung bleibt unveraendert, damit sich die Korrektur zuruecknehmen laesst.

Alle Exporte (Word, PDF, ...) gehen von dem Text aus, der in der Vorschau
steht -- siehe ``dokument_export_service.protokoll_dokument``. Die Markdown-
Datei wird mitgefuehrt, damit sie nie vom Stand der Vorschau abweicht.

Der Dienst kennt kein Qt (CLAUDE.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from protokoll_assistent.services import dokument_export_service as export
from protokoll_assistent.services import export_service

# Wenigstens einer dieser Schluessel steht in jeder Protokoll-JSON; ein Transkript
# oder eine fremde JSON-Datei hat keinen davon.
_PROTOKOLL_SCHLUESSEL = ("kurzzusammenfassung", "themen", "entscheidungen", "aufgaben", export.SCHLUESSEL_KORRIGIERT)


def lade(protokoll_json: Path) -> dict[str, Any]:
    """Die Protokoll-JSON lesen; ``ExportFehler`` mit lesbarer Meldung, wenn das nicht geht
    oder die Datei kein Protokoll ist."""
    protokoll = export.lade_protokoll(protokoll_json)
    if not any(schluessel in protokoll for schluessel in _PROTOKOLL_SCHLUESSEL):
        raise export.ExportFehler(f"{protokoll_json.name} ist kein Protokoll.")
    return protokoll


def originaltext(protokoll: dict[str, Any]) -> str:
    """Das Protokoll so, wie das Modell es ausgewertet hat -- ohne Korrektur."""
    return export.dokument_als_markdown(export.protokoll_dokument(protokoll, mit_korrektur=False))


def vorschautext(protokoll: dict[str, Any]) -> str:
    """Der Text fuer die Vorschau: die Korrektur des Anwenders, sonst das Original."""
    korrigiert = protokoll.get(export.SCHLUESSEL_KORRIGIERT)
    if isinstance(korrigiert, str) and korrigiert.strip():
        return korrigiert if korrigiert.endswith("\n") else korrigiert + "\n"
    return originaltext(protokoll)


def ist_korrigiert(protokoll: dict[str, Any]) -> bool:
    return export.SCHLUESSEL_KORRIGIERT in protokoll


def _markdown_pfad(protokoll_json: Path) -> Path:
    return protokoll_json.with_suffix(".md")


def _schreibe_text(ziel: Path, text: str) -> None:
    """Atomar ersetzen, mit Wiederholung unter Windows (siehe ``_atomar_schreiben``)."""

    def schreiben(temp: Path) -> None:
        temp.write_text(text, encoding="utf-8")

    export._atomar_schreiben(ziel, schreiben)


def _schreibe(protokoll_json: Path, protokoll: dict[str, Any], markdown: str) -> None:
    """JSON und Markdown ersetzen."""
    _schreibe_text(protokoll_json, json.dumps(protokoll, ensure_ascii=False, indent=2))
    _schreibe_text(_markdown_pfad(protokoll_json), markdown)


def speichern(protokoll_json: Path, text: str) -> None:
    """Den korrigierten Text speichern. Entspricht er dem Original, gilt das
    Protokoll als unkorrigiert (die Markierung wird entfernt). Ein leerer Text
    wird nicht gespeichert -- ein leeres Protokoll waere nie gewollt.

    ``ExportFehler`` bei unlesbarer JSON, ``OSError`` wenn das Schreiben scheitert."""
    if not text.strip():
        raise export.ExportFehler("Das Protokoll ist leer und wurde deshalb nicht gespeichert.")
    protokoll = lade(protokoll_json)
    text = text if text.endswith("\n") else text + "\n"
    if text == originaltext(protokoll):
        zuruecksetzen(protokoll_json)
        return
    protokoll[export.SCHLUESSEL_KORRIGIERT] = text
    _schreibe(protokoll_json, protokoll, text)


def zuruecksetzen(protokoll_json: Path) -> str:
    """Die Korrektur verwerfen; Rueckgabe ist der Originaltext. Die Markdown-Datei
    wird wieder so geschrieben, wie die Auswertung sie ursprunglich erzeugt hat."""
    protokoll = lade(protokoll_json)
    protokoll.pop(export.SCHLUESSEL_KORRIGIERT, None)
    _schreibe(protokoll_json, protokoll, export_service.render_protocol_markdown(protokoll))
    return originaltext(protokoll)
