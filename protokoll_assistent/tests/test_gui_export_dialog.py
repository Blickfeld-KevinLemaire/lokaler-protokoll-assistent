"""Tests fuer 'gui/export_dialog.py' und 'gui/dokument_qt.py'."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtWidgets import QFileDialog  # noqa: E402

from protokoll_assistent.gui import dokument_qt  # noqa: E402
from protokoll_assistent.gui import export_dialog as ed  # noqa: E402
from protokoll_assistent.services import dokument_export_service as export  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402


@pytest.fixture(autouse=True)
def isolierte_konfiguration(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")


def _transkript(ordner: Path) -> Path:
    daten = {
        "quelldatei": "sitzung.mp3",
        "quelldatei_stamm": "sitzung",
        "sprechertrennung_aktiv": True,
        "anzahl_sprecher": 1,
        "segmente": [
            {"start": "00:00:01.000", "start_sekunden": 1.0, "ende_sekunden": 2.0, "sprecher": "Anna", "text": "Hallo zusammen."}
        ],
    }
    pfad = ordner / "sitzung_lokal_transkript_1.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


def _protokoll(ordner: Path) -> Path:
    pfad = ordner / "sitzung_protokoll_1.json"
    pfad.write_text(
        json.dumps({"titel": "Sitzung", "kurzzusammenfassung": "Kurz.", "aufgaben": [{"aufgabe": "Plan", "verantwortlich": "Ben"}]}),
        encoding="utf-8",
    )
    return pfad


def _dialog(qt_widgets, tmp_path, transkript=True, protokoll=True, schreiber=None):
    return qt_widgets(
        ed.ExportDialog(
            _transkript(tmp_path) if transkript else None,
            _protokoll(tmp_path) if protokoll else None,
            tmp_path / "ausgabe",
            schreiber,
        )
    )


def test_vorauswahl_je_nach_vorhandenem(qt_widgets, tmp_path):
    beides = _dialog(qt_widgets, tmp_path)
    assert beides.inhalt() == export.INHALT_BEIDES and beides.beides_radio.isChecked()
    assert beides.gewaehlte_formate() == ["docx", "pdf"]  # Standard
    assert beides.ziel_edit.text() == str(tmp_path / "ausgabe")

    nur_transkript = _dialog(qt_widgets, tmp_path, protokoll=False)
    assert nur_transkript.inhalt() == export.INHALT_TRANSKRIPT
    assert not nur_transkript.protokoll_radio.isEnabled() and not nur_transkript.beides_radio.isEnabled()
    assert "noch kein Protokoll" in nur_transkript.protokoll_label.text()

    nur_protokoll = _dialog(qt_widgets, tmp_path, transkript=False)
    assert nur_protokoll.inhalt() == export.INHALT_PROTOKOLL and not nur_protokoll.transkript_radio.isEnabled()


def test_formate_je_inhalt_freigeschaltet(qt_widgets, tmp_path):
    dialog = _dialog(qt_widgets, tmp_path)
    for kennung in ("srt", "vtt", "json"):
        assert not dialog.format_checkboxen[kennung].isEnabled()  # 'Beides': keine Untertitel/JSON
    dialog.transkript_radio.setChecked(True)
    assert all(dialog.format_checkboxen[k].isEnabled() for k in ("srt", "vtt", "json", "docx"))
    dialog.protokoll_radio.setChecked(True)
    assert dialog.format_checkboxen["json"].isEnabled() and not dialog.format_checkboxen["srt"].isEnabled()
    # Ein gesperrtes, aber angekreuztes Format wird nicht mit exportiert.
    dialog.format_checkboxen["srt"].setChecked(True)
    assert "srt" not in dialog.gewaehlte_formate()


def test_export_schreibt_dateien_und_merkt_sich_die_wahl(qt_widgets, tmp_path):
    dialog = _dialog(qt_widgets, tmp_path)
    ziel = tmp_path / "kunde"
    dialog.ziel_edit.setText(str(ziel))
    for kennung, box in dialog.format_checkboxen.items():
        box.setChecked(kennung in ("md", "txt"))

    dialog.exportieren()

    assert sorted(p.name for p in dialog.geschrieben) == ["sitzung_gesamt.md", "sitzung_gesamt.txt"]
    assert all(p.is_file() for p in dialog.geschrieben)
    assert "Gespeichert in" in dialog.status_label.text() and "sitzung_gesamt.md" in dialog.status_label.text()
    assert dialog.ordner_oeffnen_button.isEnabled()
    konfig = app_config.load_config()
    assert konfig["export_zielordner"] == str(ziel) and konfig["export_formate"] == ["md", "txt"]

    # Beim naechsten Oeffnen sind Ziel und Formate wieder da.
    neu = _dialog(qt_widgets, tmp_path)
    assert neu.ziel_edit.text() == str(ziel) and neu.gewaehlte_formate() == ["md", "txt"]


def test_export_ohne_ziel_oder_format_meldet_das(qt_widgets, tmp_path):
    dialog = _dialog(qt_widgets, tmp_path)
    dialog.ziel_edit.setText("  ")
    dialog.exportieren()
    assert "Zielordner" in dialog.status_label.text() and dialog.geschrieben == []
    dialog.ziel_edit.setText(str(tmp_path / "z"))
    for box in dialog.format_checkboxen.values():
        box.setChecked(False)
    dialog.exportieren()
    assert "mindestens ein Format" in dialog.status_label.text() and not dialog.ordner_oeffnen_button.isEnabled()


def test_export_teilweise_und_fehler(qt_widgets, tmp_path):
    dialog = _dialog(qt_widgets, tmp_path)  # kein Qt-Schreiber uebergeben -> PDF/ODT scheitern
    dialog.ziel_edit.setText(str(tmp_path / "z"))
    for kennung, box in dialog.format_checkboxen.items():
        box.setChecked(kennung in ("md", "pdf"))
    dialog.exportieren()
    assert [p.suffix for p in dialog.geschrieben] == [".md"]
    text = dialog.status_label.text()
    assert "Nicht geschrieben" in text and "PDF" in text and dialog.ordner_oeffnen_button.isEnabled()

    nur_pdf = _dialog(qt_widgets, tmp_path)
    nur_pdf.ziel_edit.setText(str(tmp_path / "z2"))
    for kennung, box in nur_pdf.format_checkboxen.items():
        box.setChecked(kennung == "pdf")
    nur_pdf.exportieren()
    assert nur_pdf.geschrieben == [] and "fehlgeschlagen" in nur_pdf.status_label.text()
    assert not nur_pdf.ordner_oeffnen_button.isEnabled()


def test_protokoll_nachtraeglich_waehlen(qt_widgets, tmp_path, monkeypatch):
    dialog = _dialog(qt_widgets, tmp_path, protokoll=False)
    protokoll = _protokoll(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(protokoll), "")))
    dialog._protokoll_waehlen()
    assert dialog.beides_radio.isEnabled() and dialog.beides_radio.isChecked()
    assert protokoll.name in dialog.protokoll_label.text()

    # Ohne Transkript wird daraus "nur Protokoll"; Abbruch aendert nichts.
    nur_protokoll = _dialog(qt_widgets, tmp_path, transkript=False, protokoll=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(protokoll), "")))
    nur_protokoll._protokoll_waehlen()
    assert nur_protokoll.protokoll_radio.isChecked()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    nur_protokoll._protokoll_waehlen()
    assert protokoll.name in nur_protokoll.protokoll_label.text()


def test_zielordner_waehlen_und_oeffnen(qt_widgets, tmp_path, monkeypatch):
    dialog = _dialog(qt_widgets, tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "gewaehlt")))
    dialog._ziel_waehlen()
    assert dialog.ziel_edit.text() == str(tmp_path / "gewaehlt")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    dialog._ziel_waehlen()
    assert dialog.ziel_edit.text() == str(tmp_path / "gewaehlt")

    geoeffnet = []
    monkeypatch.setattr(ed.QDesktopServices, "openUrl", staticmethod(lambda url: geoeffnet.append(url.toLocalFile()) or True))
    dialog._ordner_oeffnen()
    assert [Path(p) for p in geoeffnet] == [tmp_path / "gewaehlt"]


# --------------------------------------------------------------------------
# PDF und OpenDocument mit Qt
# --------------------------------------------------------------------------
def test_pdf_und_odt_werden_mit_qt_geschrieben(qt_app, tmp_path):
    transkript = _transkript(tmp_path)
    geschrieben = export.exportiere(
        export.INHALT_TRANSKRIPT,
        ["pdf", "odt"],
        tmp_path / "z",
        transkript_json=transkript,
        schreiber=dokument_qt.SCHREIBER,
    )
    pdf, odt = geschrieben
    assert pdf.suffix == ".pdf" and pdf.read_bytes().startswith(b"%PDF")
    assert odt.suffix == ".odt" and odt.read_bytes()[:2] == b"PK"
    assert not list((tmp_path / "z").glob("*.tmp"))


def test_odt_fehler_wird_gemeldet(qt_app, tmp_path):
    with pytest.raises(RuntimeError, match="OpenDocument"):
        dokument_qt.schreibe_odt("<p>x</p>", tmp_path / "gibt-es-nicht" / "x.odt")
