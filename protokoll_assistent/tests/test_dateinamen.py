"""Namensstuecke aus Dateiinhalten bestimmen nie den Ordner (utils/dateinamen.py und seine Verwender)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import dokument_export_service, export_service, pipeline_service
from protokoll_assistent.utils.dateinamen import sicherer_stamm


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("Besprechung 2026-11-24", "Besprechung 2026-11-24"),
        ("Küche_Raum 3", "Küche_Raum 3"),
        ("../ben/x", "_ben_x"),
        ("..\\..\\x", "_.._x"),
        ("/daten/ausgabe/nutzer/ben/x", "_daten_ausgabe_nutzer_ben_x"),
        ("C:\\Windows\\x", "C__Windows_x"),
        ("\\\\angreifer\\freigabe\\x", "__angreifer_freigabe_x"),
        ("..", "aufnahme"),
        ("", "aufnahme"),
        (None, "aufnahme"),
    ],
)
def test_sicherer_stamm(text: object, erwartet: str) -> None:
    assert sicherer_stamm(text) == erwartet


def test_sicherer_stamm_ist_begrenzt() -> None:
    assert len(sicherer_stamm("a" * 500)) == 120


def _transkript(ordner: Path, stamm: str) -> Path:
    datei = ordner / "hochgeladen.mp3"  # im Servermodus prueft der Upload nur die Endung
    datei.write_text(
        json.dumps(
            {"segmente": [{"start_sekunden": 0, "ende_sekunden": 1, "text": "x"}], "quelldatei_stamm": stamm}
        ),
        encoding="utf-8",
    )
    return datei


@pytest.mark.parametrize("stamm", ["../fremd/x", "/tmp/fremd/x", "C:\\fremd\\x", "\\\\angreifer\\freigabe\\x"])
def test_protokoll_landet_immer_im_ausgabeordner(tmp_path: Path, stamm: str) -> None:
    eigen = tmp_path / "nutzer" / "anna"
    eigen.mkdir(parents=True)
    *_, gelesen = pipeline_service.load_transcript_for_protocol(_transkript(eigen, stamm))
    json_pfad, md_pfad = export_service.write_protocol_exports(eigen, "Ergebnis", gelesen, "20261124_120000")
    for pfad in (json_pfad, md_pfad):
        assert pfad.parent == eigen and pfad.is_file()
    assert sorted(p.name for p in tmp_path.rglob("*_protokoll_*")) == sorted([json_pfad.name, md_pfad.name])
    # Auch wer write_protocol_exports direkt mit einem fremden Stamm ruft, bleibt im Ordner.
    json2, _ = export_service.write_protocol_exports(eigen, "Ergebnis", stamm, "../20261124")
    assert json2.parent == eigen


def test_neu_schreiben_mit_fremdem_stamm_bleibt_im_ordner(tmp_path: Path) -> None:
    ordner = tmp_path / "anna"
    segmente = [{"start": 0.0, "end": 1.0, "text": "Hallo", "sprecher_id": "SPEAKER_00"}]
    pfade = export_service.write_transcript_exports(
        ordner, "x.wav", "x", "20261124_120000", "2026-11-24T12:00:00", "small", "de", "cpu", 1.0,
        segmente, export_service.build_speaker_names(["SPEAKER_00"]),
    )
    daten = json.loads(pfade.json.read_text(encoding="utf-8"))
    daten["quelldatei_stamm"] = "../fremd/x"
    daten["lauf_zeitstempel"] = "../../y"
    pfade.json.write_text(json.dumps(daten), encoding="utf-8")
    export_service.reexport_with_new_names(pfade.json, {"SPEAKER_00": "Anna"})
    assert not (tmp_path / "fremd").exists()
    assert all(p.parent == ordner for p in tmp_path.rglob("*") if p.is_file())


def test_dokumentname_aus_dem_stamm_ohne_ordner() -> None:
    assert dokument_export_service._basisname({"quelldatei_stamm": "../../x"}, None, None) == "_.._x"
