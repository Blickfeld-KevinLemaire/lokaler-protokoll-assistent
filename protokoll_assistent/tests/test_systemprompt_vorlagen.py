"""Tests fuer 'utils/systemprompt_vorlagen.py'."""

from __future__ import annotations

import pytest

from protokoll_assistent.utils import systemprompt_vorlagen as sv


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


def test_vorlage_speichern_lehnt_unzulaessige_dateinamen_ab(isolierter_vorlagenordner):
    """Der Vorlagenname IST der Dateiname. Naheliegende Namen fuer
    Besprechungsvorlagen enthalten aber Zeichen, die Windows in Dateinamen
    verbietet - ohne Pruefung scheitert erst das Schreiben, mit einem
    'OSError' aus pathlib."""
    with pytest.raises(ValueError, match="Dateinamen"):
        sv.vorlage_speichern("Wer macht was?", "Inhalt")
    assert list(isolierter_vorlagenordner.glob("*.txt")) == []


@pytest.mark.parametrize("name", ["Kundengespraech A/B", 'Thema "Budget"', "Team: Vertrieb", "A*B", "C|D", "E<F>G"])
def test_vorlage_speichern_lehnt_jedes_verbotene_zeichen_ab(isolierter_vorlagenordner, name):
    with pytest.raises(ValueError):
        sv.vorlage_speichern(name, "Inhalt")


def test_vorlage_speichern_lehnt_leeren_namen_ab(isolierter_vorlagenordner):
    with pytest.raises(ValueError, match="Namen"):
        sv.vorlage_speichern("   ", "Inhalt")


def test_name_pruefen_nennt_die_gefundenen_zeichen(isolierter_vorlagenordner):
    with pytest.raises(ValueError) as fehler:
        sv.name_pruefen("Wer? Was: Wo/")
    meldung = str(fehler.value)
    assert "?" in meldung
    assert ":" in meldung
    assert "/" in meldung


def test_vorlage_speichern_akzeptiert_umlaute_und_leerzeichen(isolierter_vorlagenordner):
    """Umlaute sind in Dateinamen zulaessig und sollen nicht abgelehnt werden."""
    sv.vorlage_speichern("Große Besprechung", "Inhalt")
    assert (isolierter_vorlagenordner / "Große Besprechung.txt").read_text(encoding="utf-8") == "Inhalt"
