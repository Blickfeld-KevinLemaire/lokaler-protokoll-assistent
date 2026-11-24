"""Was unter „Dateien“ einer Besprechung erscheint: das eine Dokument und die Exporte, nicht die Daten."""

from __future__ import annotations

import json
from pathlib import Path

from protokoll_assistent.ablauf import bibliothek
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben


def _besprechung(ordner: Path) -> bibliothek.Besprechung:
    treffer = bibliothek.besprechungen(ordner)
    assert len(treffer) == 1
    return treffer[0]


def test_daten_und_begleitdateien_bleiben_verborgen(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / "Runde_lokal_transkript_20260101_100000.json")
    for endung in (".txt", ".srt", ".vtt"):
        transkript.with_suffix(endung).write_text("alt", encoding="utf-8")
    b = _besprechung(tmp_path)
    assert b.dokument() is None and b.sichtbare_dateien() == []
    # Herunterladen bleibt moeglich (nachgeschlagen in 'dateien()').
    assert transkript.with_suffix(".txt") in b.dateien()

    word = transkript.with_suffix(".docx")
    word.write_bytes(b"PK")
    export = tmp_path / "Runde_transkript.pdf"
    export.write_bytes(b"%PDF")
    b = _besprechung(tmp_path)
    assert b.sichtbare_dateien() == [word, export]
    namen = [d["name"] for d in bibliothek.details(b)["dateien"]]
    assert namen == [word.name, export.name]


def test_mit_protokoll_zaehlt_dessen_dokument(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / "Runde_lokal_transkript_20260101_100000.json")
    transkript.with_suffix(".docx").write_bytes(b"PK")
    protokoll = tmp_path / "Runde_protokoll_20260101_100100.json"
    protokoll.write_text(json.dumps({"ergebnis": "# Protokoll", "transkript_datei": transkript.name}), encoding="utf-8")
    protokoll.with_suffix(".md").write_text("# Protokoll\n", encoding="utf-8")
    b = _besprechung(tmp_path)
    # Das Dokument mit Protokoll gibt es (noch) nicht: dann das des Transkripts.
    assert b.dokument() == transkript.with_suffix(".docx")
    protokoll.with_suffix(".docx").write_bytes(b"PK")
    b = _besprechung(tmp_path)
    assert b.sichtbare_dateien() == [protokoll.with_suffix(".docx")]
