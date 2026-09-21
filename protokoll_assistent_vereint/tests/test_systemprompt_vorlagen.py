"""Tests fuer 'utils/systemprompt_vorlagen.py'."""

from __future__ import annotations

import pytest

from protokoll_assistent_vereint.utils import systemprompt_vorlagen as sv


@pytest.fixture
def isolierter_vorlagenordner(tmp_path, monkeypatch):
    ordner = tmp_path / "vorlagen"
    ordner.mkdir()
    monkeypatch.setattr(sv, "get_systemprompt_vorlagen_dir", lambda: ordner)
    return ordner


def test_eingebaute_vorlagen_enthalten_die_drei_bekannten():
    assert set(sv.EINGEBAUTE_VORLAGEN) == {"Zusammenfassung", "Agenda", "Prioritaetenliste"}


def test_eigene_vorlagen_ohne_dateien_ist_leer(isolierter_vorlagenordner):
    assert sv.eigene_vorlagen() == {}


def test_eigene_vorlagen_liest_txt_dateien(isolierter_vorlagenordner):
    (isolierter_vorlagenordner / "Team-Standup.txt").write_text("Text A", encoding="utf-8")
    (isolierter_vorlagenordner / "Retro.txt").write_text("Text B", encoding="utf-8")

    vorlagen = sv.eigene_vorlagen()

    assert vorlagen == {"Retro": "Text B", "Team-Standup": "Text A"}


def test_alle_vorlagen_kombiniert_eingebaut_und_eigene(isolierter_vorlagenordner):
    (isolierter_vorlagenordner / "Eigene.txt").write_text("Mein Text", encoding="utf-8")

    vorlagen = sv.alle_vorlagen()

    assert vorlagen["Zusammenfassung"] == sv.STANDARD_SYSTEMPROMPT
    assert vorlagen["Eigene"] == "Mein Text"


def test_vorlage_speichern_schreibt_datei(isolierter_vorlagenordner):
    sv.vorlage_speichern("Neue Vorlage", "Inhalt")
    datei = isolierter_vorlagenordner / "Neue Vorlage.txt"
    assert datei.read_text(encoding="utf-8") == "Inhalt"


def test_vorlage_speichern_kann_eingebaute_nicht_ueberschreiben(isolierter_vorlagenordner):
    with pytest.raises(ValueError, match="Agenda"):
        sv.vorlage_speichern("Agenda", "Anderer Text")
    assert not (isolierter_vorlagenordner / "Agenda.txt").exists()
