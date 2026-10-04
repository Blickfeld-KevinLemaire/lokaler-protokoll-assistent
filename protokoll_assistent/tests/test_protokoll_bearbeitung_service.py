"""Tests fuer ``services/protokoll_bearbeitung_service.py`` und das Einlesen
korrigierter Protokolltexte in ``services/dokument_export_service.py`` -- ohne Qt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import dokument_export_service as de
from protokoll_assistent.services import export_service
from protokoll_assistent.services import protokoll_bearbeitung_service as pb

PROTOKOLL = {
    "titel": "Projektbesprechung",
    "kurzzusammenfassung": "Es wurde der Zeitplan besprochen.",
    "themen": [{"thema": "Zeitplan", "zeitraum": "00:00-00:05", "kernaussagen": ["Start im Mai", "Ende im Juli"]}],
    "entscheidungen": [{"entscheidung": "Start im Mai", "sprecher": "Anna", "zeitpunkt": "", "quelle": "00:00:01"}],
    "aufgaben": [{"aufgabe": "Plan versenden", "verantwortlich": "Ben", "frist": "", "quelle": "00:00:03"}],
    "termine": ["Mai: Start"],
    "offene_fragen": ["Wer bucht den Raum?"],
    "wichtige_fakten": [],
}


@pytest.fixture
def protokoll_datei(tmp_path: Path) -> Path:
    pfad = tmp_path / "besprechung_protokoll_20261003_090500.json"
    pfad.write_text(json.dumps(PROTOKOLL), encoding="utf-8")
    pfad.with_suffix(".md").write_text(export_service.render_protocol_markdown(PROTOKOLL), encoding="utf-8")
    return pfad


# --------------------------------------------------------------------------
# Text <-> Dokument
# --------------------------------------------------------------------------
def test_der_text_der_vorschau_ergibt_wieder_dasselbe_dokument():
    """Nichts geht verloren, wenn der Text der Vorschau unveraendert gespeichert wird."""
    dokument = de.protokoll_dokument(PROTOKOLL)
    wieder = de.dokument_aus_markdown(de.dokument_als_markdown(dokument))
    assert wieder == dokument


def test_vorschau_zeigt_titel_zusammenfassung_und_abschnitte():
    text = pb.originaltext(PROTOKOLL)
    assert text.startswith("# Projektbesprechung\n\nEs wurde der Zeitplan besprochen.\n")
    assert "## Entscheidungen\n\n- Start im Mai (Sprecher: Anna, Zeitpunkt: unklar, Quelle: 00:00:01)" in text
    assert "## Offene Fragen\n\n- Wer bucht den Raum?" in text
    assert "wichtige" not in text.lower()  # leere Abschnitte erscheinen nicht


def test_einlesen_titel_ueberschrift_liste_und_absaetze():
    dokument = de.dokument_aus_markdown(
        "# Neuer Titel\n\nErster Absatz.\nZweite Zeile.\n\n## Aufgaben\n- Eins\n* Zwei\n\n### Noch ein Abschnitt\nText\n"
    )
    assert dokument.titel == "Neuer Titel"
    assert [(a.art, a.text, a.punkte) for a in dokument.abschnitte] == [
        (de.ABSATZ, "Erster Absatz.", ()),
        (de.ABSATZ, "Zweite Zeile.", ()),
        (de.UEBERSCHRIFT, "Aufgaben", ()),
        (de.LISTE, "", ("Eins", "Zwei")),
        (de.UEBERSCHRIFT, "Noch ein Abschnitt", ()),
        (de.ABSATZ, "Text", ()),
    ]


def test_einlesen_entfernt_fettdruck_und_ohne_titel_heisst_es_protokoll():
    dokument = de.dokument_aus_markdown("- **Wichtig**: bitte lesen\n")
    assert dokument.titel == "Protokoll"
    assert dokument.abschnitte[0].punkte == ("Wichtig: bitte lesen",)


def test_zweite_hauptueberschrift_wird_ein_abschnitt():
    dokument = de.dokument_aus_markdown("# Titel\n# Zweite\n")
    assert dokument.titel == "Titel"
    assert dokument.abschnitte[0].art == de.UEBERSCHRIFT and dokument.abschnitte[0].text == "Zweite"


# --------------------------------------------------------------------------
# Speichern, Zuruecksetzen
# --------------------------------------------------------------------------
def test_vorschautext_ohne_korrektur_ist_das_original(protokoll_datei):
    protokoll = pb.lade(protokoll_datei)
    assert not pb.ist_korrigiert(protokoll)
    assert pb.vorschautext(protokoll) == pb.originaltext(protokoll)


def test_speichern_legt_korrektur_ab_und_aendert_das_original_nicht(protokoll_datei):
    text = pb.originaltext(PROTOKOLL).replace("Start im Mai", "Start im Juni")
    pb.speichern(protokoll_datei, text)

    gespeichert = json.loads(protokoll_datei.read_text(encoding="utf-8"))
    assert gespeichert[de.SCHLUESSEL_KORRIGIERT] == text
    # die Auswertung des Modells bleibt daneben erhalten
    assert gespeichert["entscheidungen"] == PROTOKOLL["entscheidungen"]
    assert pb.ist_korrigiert(gespeichert)
    assert pb.vorschautext(gespeichert) == text
    # die Markdown-Datei (die auch der Chat liest) zeigt dieselbe Fassung
    assert protokoll_datei.with_suffix(".md").read_text(encoding="utf-8") == text


def test_export_nutzt_den_korrigierten_text(protokoll_datei, tmp_path):
    pb.speichern(protokoll_datei, "# Anderer Titel\n\nNur noch ein Satz.\n\n## Aufgaben\n- Eine neue Aufgabe\n")
    ziel = tmp_path / "export"
    dateien = de.exportiere(de.INHALT_PROTOKOLL, ["md", "txt"], ziel, protokoll_json=protokoll_datei)
    inhalt = "\n".join(datei.read_text(encoding="utf-8") for datei in dateien)
    assert "Anderer Titel" in inhalt and "Eine neue Aufgabe" in inhalt
    assert "Plan versenden" not in inhalt and "Zeitplan" not in inhalt


def test_unveraenderter_text_gilt_nicht_als_korrektur(protokoll_datei):
    pb.speichern(protokoll_datei, pb.originaltext(PROTOKOLL))
    assert not pb.ist_korrigiert(pb.lade(protokoll_datei))


def test_zuruecksetzen_verwirft_die_korrektur(protokoll_datei):
    pb.speichern(protokoll_datei, "# Etwas ganz anderes\n")
    original = pb.zuruecksetzen(protokoll_datei)

    assert original == pb.originaltext(PROTOKOLL)
    assert not pb.ist_korrigiert(pb.lade(protokoll_datei))
    assert protokoll_datei.with_suffix(".md").read_text(encoding="utf-8") == export_service.render_protocol_markdown(PROTOKOLL)


def test_leerer_text_wird_nicht_gespeichert(protokoll_datei):
    vorher = protokoll_datei.read_text(encoding="utf-8")
    with pytest.raises(de.ExportFehler, match="leer"):
        pb.speichern(protokoll_datei, "  \n\n")
    assert protokoll_datei.read_text(encoding="utf-8") == vorher


def test_unlesbare_protokolldatei_meldet_export_fehler(tmp_path):
    kaputt = tmp_path / "x_protokoll_1.json"
    kaputt.write_text("{nicht json", encoding="utf-8")
    with pytest.raises(de.ExportFehler):
        pb.speichern(kaputt, "# Titel\n")
    with pytest.raises(de.ExportFehler):
        pb.lade(tmp_path / "gibt_es_nicht.json")


def test_korrektur_ohne_zeilenende_am_schluss_wird_ergaenzt(protokoll_datei):
    pb.speichern(protokoll_datei, "# Kurz")
    assert pb.vorschautext(pb.lade(protokoll_datei)) == "# Kurz\n"
