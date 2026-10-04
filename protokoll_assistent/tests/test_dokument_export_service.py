"""Tests fuer ``services/dokument_export_service.py`` -- ohne Qt (PDF/ODT ueber Attrappen)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import dokument_export_service as de


def _transkript(ordner: Path, mit_sprechern: bool = True) -> Path:
    daten = {
        "quelldatei": "besprechung.mp3",
        "quelldatei_stamm": "besprechung",
        "erstellt": "2026-10-03T09:00:00",
        "modell": "large-v3-turbo",
        "sprache": "de",
        "sprechertrennung_aktiv": mit_sprechern,
        "anzahl_sprecher": 2,
        "segmente": [
            {"nummer": 1, "start_sekunden": 1.0, "ende_sekunden": 3.0, "start": "00:00:01.000", "ende": "00:00:03.000",
             "sprecher_id": "SPEAKER_00", "sprecher": "Anna", "text": "Guten Morgen <alle>.", "moegliche_ueberschneidung": False},
            {"nummer": 2, "start_sekunden": 3.5, "ende_sekunden": 5.0, "start": "00:00:03.500", "ende": "00:00:05.000",
             "sprecher_id": "SPEAKER_01", "sprecher": "Ben", "text": "Hallo & willkommen.", "moegliche_ueberschneidung": False},
        ],
    }
    pfad = ordner / "besprechung_lokal_transkript_20261003_090000.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


def _protokoll(ordner: Path) -> Path:
    daten = {
        "titel": "Projektbesprechung",
        "kurzzusammenfassung": "Es wurde der Zeitplan besprochen.",
        "themen": [{"thema": "Zeitplan", "zeitraum": "00:00-00:05", "kernaussagen": ["Start im Mai", "Ende im Juli"]}],
        "entscheidungen": [{"entscheidung": "Start im Mai", "sprecher": "Anna", "zeitpunkt": "", "quelle": "00:00:01"}],
        "aufgaben": [{"aufgabe": "Plan versenden", "verantwortlich": "Ben", "frist": "", "quelle": "00:00:03"}],
        "termine": ["Mai: Start"],
        "offene_fragen": ["Wer bucht den Raum?"],
        "wichtige_fakten": [],
    }
    pfad = ordner / "besprechung_protokoll_20261003_090500.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


# --------------------------------------------------------------------------
# Dokumente und Renderer
# --------------------------------------------------------------------------
def test_formate_je_inhalt():
    transkript = {f.id for f in de.formate_fuer(de.INHALT_TRANSKRIPT)}
    protokoll = {f.id for f in de.formate_fuer(de.INHALT_PROTOKOLL)}
    beides = {f.id for f in de.formate_fuer(de.INHALT_BEIDES)}
    assert {"docx", "pdf", "md", "txt", "html", "odt", "srt", "vtt", "json"} == transkript
    assert protokoll == {"docx", "pdf", "md", "txt", "html", "odt", "json"}
    assert beides == {"docx", "pdf", "md", "txt", "html", "odt"}
    assert de.finde_format("docx").name == "Word (.docx)" and de.finde_format("x") is None  # type: ignore[union-attr]


def test_transkript_dokument_und_markdown(tmp_path):
    dokument = de.transkript_dokument(de.lade_transkript(_transkript(tmp_path)))
    assert dokument.titel == "Transkript: besprechung.mp3"
    assert "Erkannte Sprecher: 2" in dokument.kopfzeilen
    md = de.als_markdown(dokument)
    assert md.startswith("# Transkript: besprechung.mp3")
    assert "**[00:00:01.000] Anna:** Guten Morgen <alle>." in md


def test_transkript_ohne_sprechertrennung(tmp_path):
    dokument = de.transkript_dokument(de.lade_transkript(_transkript(tmp_path, mit_sprechern=False)))
    assert not any("Sprecher" in k for k in dokument.kopfzeilen)
    assert de.als_text(dokument).count("Anna") == 0 and "[00:00:01.000]" in de.als_text(dokument)


def test_protokoll_dokument_enthaelt_alle_abschnitte(tmp_path):
    md = de.als_markdown(de.protokoll_dokument(de.lade_protokoll(_protokoll(tmp_path))))
    assert md.startswith("# Projektbesprechung")
    for erwartet in (
        "Es wurde der Zeitplan besprochen.",
        "## Themen", "Zeitplan (00:00-00:05): Start im Mai; Ende im Juli",
        "## Entscheidungen", "Zeitpunkt: unklar",
        "## Aufgaben", "Verantwortlich: Ben, Frist: unklar",
        "## Termine", "## Offene Fragen", "Wer bucht den Raum?",
    ):
        assert erwartet in md
    assert "Wichtige Fakten" not in md  # leer: kein Abschnitt


def test_kombiniertes_dokument_haengt_das_transkript_an(tmp_path):
    protokoll = de.protokoll_dokument(de.lade_protokoll(_protokoll(tmp_path)))
    transkript = de.transkript_dokument(de.lade_transkript(_transkript(tmp_path)))
    gesamt = de.kombiniertes_dokument(protokoll, transkript)
    assert gesamt.titel == "Projektbesprechung"
    arten = [a.art for a in gesamt.abschnitte]
    assert de.SEITENUMBRUCH in arten
    nach = gesamt.abschnitte[arten.index(de.SEITENUMBRUCH) + 1]
    assert (nach.art, nach.text) == (de.UEBERSCHRIFT, "Transkript")
    assert "---" in de.als_markdown(gesamt)


def test_html_ist_maskiert_und_eigenstaendig(tmp_path):
    html = de.als_html(de.transkript_dokument(de.lade_transkript(_transkript(tmp_path))))
    assert html.startswith("<!DOCTYPE html>") and 'charset="utf-8"' in html
    assert "Guten Morgen &lt;alle&gt;." in html and "Hallo &amp; willkommen." in html
    assert "<strong>[00:00:01.000] Anna:</strong>" in html
    gesamt = de.als_html(
        de.kombiniertes_dokument(
            de.protokoll_dokument(de.lade_protokoll(_protokoll(tmp_path))),
            de.transkript_dokument(de.lade_transkript(_transkript(tmp_path))),
        )
    )
    assert "<ul><li>" in gesamt and "page-break-after" in gesamt and "<h2>Themen</h2>" in gesamt


def test_text_ist_lesbar(tmp_path):
    text = de.als_text(
        de.kombiniertes_dokument(
            de.protokoll_dokument(de.lade_protokoll(_protokoll(tmp_path))),
            de.transkript_dokument(de.lade_transkript(_transkript(tmp_path))),
        )
    )
    assert text.startswith("PROJEKTBESPRECHUNG\n===") and "  - Mai: Start" in text and "[00:00:03.500] Ben: Hallo" in text


# --------------------------------------------------------------------------
# Dateien lesen
# --------------------------------------------------------------------------
def test_ungueltige_dateien_werden_lesbar_gemeldet(tmp_path):
    with pytest.raises(de.ExportFehler, match="konnte nicht gelesen werden"):
        de.lade_transkript(tmp_path / "gibt-es-nicht.json")
    kaputt = tmp_path / "kaputt.json"
    kaputt.write_text("{nein", encoding="utf-8")
    with pytest.raises(de.ExportFehler, match=r"kaputt\.json"):
        de.lade_protokoll(kaputt)
    liste = tmp_path / "liste.json"
    liste.write_text("[1]", encoding="utf-8")
    with pytest.raises(de.ExportFehler, match="nicht das erwartete Format"):
        de.lade_transkript(liste)
    ohne = tmp_path / "ohne.json"
    ohne.write_text("{}", encoding="utf-8")
    with pytest.raises(de.ExportFehler, match="keine Segmente"):
        de.lade_transkript(ohne)


# --------------------------------------------------------------------------
# Exportieren
# --------------------------------------------------------------------------
def test_export_transkript_in_viele_formate(tmp_path):
    pytest.importorskip("docx", reason="python-docx ist nicht installiert.")
    transkript = _transkript(tmp_path)
    ziel = tmp_path / "ziel"
    geschrieben = de.exportiere(
        de.INHALT_TRANSKRIPT,
        ["docx", "md", "txt", "html", "srt", "vtt", "json"],
        ziel,
        transkript_json=transkript,
    )
    assert [p.name for p in geschrieben] == [
        f"besprechung_transkript{endung}" for endung in (".docx", ".md", ".txt", ".html", ".srt", ".vtt", ".json")
    ]
    assert geschrieben[0].read_bytes()[:2] == b"PK"  # Word-Datei = ZIP
    assert "Guten Morgen" in geschrieben[1].read_text(encoding="utf-8")
    assert "-->" in geschrieben[4].read_text(encoding="utf-8")  # SRT
    assert geschrieben[5].read_text(encoding="utf-8").startswith("WEBVTT")
    assert json.loads(geschrieben[6].read_text(encoding="utf-8"))["quelldatei"] == "besprechung.mp3"
    assert not list(ziel.glob("*.tmp"))  # keine Arbeitsdateien uebrig


def test_export_protokoll_und_gemeinsames_dokument(tmp_path):
    transkript, protokoll = _transkript(tmp_path), _protokoll(tmp_path)
    ziel = tmp_path / "ziel"
    nur = de.exportiere(de.INHALT_PROTOKOLL, ["md", "json"], ziel, protokoll_json=protokoll, transkript_json=transkript)
    assert nur[0].name == "besprechung_protokoll.md" and "## Aufgaben" in nur[0].read_text(encoding="utf-8")
    assert json.loads(nur[1].read_text(encoding="utf-8"))["titel"] == "Projektbesprechung"  # Protokoll-JSON, nicht Transkript

    beides = de.exportiere(de.INHALT_BEIDES, ["md"], ziel, transkript_json=transkript, protokoll_json=protokoll)
    text = beides[0].read_text(encoding="utf-8")
    assert beides[0].name == "besprechung_gesamt.md" and "## Aufgaben" in text and "Guten Morgen" in text


def test_export_ueberschreibt_nie(tmp_path):
    transkript = _transkript(tmp_path)
    ziel = tmp_path / "ziel"
    erst = de.exportiere(de.INHALT_TRANSKRIPT, ["md"], ziel, transkript_json=transkript)
    zweit = de.exportiere(de.INHALT_TRANSKRIPT, ["md"], ziel, transkript_json=transkript)
    assert (erst[0].name, zweit[0].name) == ("besprechung_transkript.md", "besprechung_transkript_2.md")


def test_pdf_und_odt_laufen_ueber_uebergebene_schreiber(tmp_path):
    transkript = _transkript(tmp_path)
    gesehen = {}

    def pdf(html: str, pfad: Path) -> None:
        gesehen["pdf"] = html
        pfad.write_bytes(b"%PDF-")

    geschrieben = de.exportiere(
        de.INHALT_TRANSKRIPT, ["pdf"], tmp_path / "z", transkript_json=transkript, schreiber={"pdf": pdf}
    )
    assert geschrieben[0].name.endswith(".pdf") and geschrieben[0].read_bytes() == b"%PDF-"
    assert "<h1>Transkript: besprechung.mp3</h1>" in gesehen["pdf"]


def test_fehlender_schreiber_wird_gemeldet(tmp_path):
    with pytest.raises(de.ExportFehler, match="nicht zur Verfuegung"):
        de.exportiere(de.INHALT_TRANSKRIPT, ["pdf"], tmp_path / "z", transkript_json=_transkript(tmp_path))


def test_teilweiser_erfolg_behaelt_das_geschriebene(tmp_path):
    transkript = _transkript(tmp_path)
    with pytest.raises(de.ExportTeilweise) as info:
        de.exportiere(de.INHALT_TRANSKRIPT, ["md", "odt"], tmp_path / "z", transkript_json=transkript)
    assert [p.suffix for p in info.value.geschrieben] == [".md"] and info.value.geschrieben[0].is_file()
    assert any("OpenDocument" in f for f in info.value.fehler)


def test_unmoegliche_eingaben(tmp_path):
    transkript, protokoll = _transkript(tmp_path), _protokoll(tmp_path)
    with pytest.raises(de.ExportFehler, match="mindestens ein Format"):
        de.exportiere(de.INHALT_TRANSKRIPT, [], tmp_path, transkript_json=transkript)
    with pytest.raises(de.ExportFehler, match="kein Transkript"):
        de.exportiere(de.INHALT_TRANSKRIPT, ["md"], tmp_path, protokoll_json=protokoll)
    with pytest.raises(de.ExportFehler, match="noch kein Protokoll"):
        de.exportiere(de.INHALT_PROTOKOLL, ["md"], tmp_path, transkript_json=transkript)
    with pytest.raises(de.ExportFehler, match="Transkript und Protokoll"):
        de.exportiere(de.INHALT_BEIDES, ["md"], tmp_path, transkript_json=transkript)
    with pytest.raises(de.ExportFehler, match="Unbekannter Inhalt"):
        de.exportiere("quatsch", ["md"], tmp_path, transkript_json=transkript)
    # Untertitel gibt es nur fuers Transkript
    with pytest.raises(de.ExportFehler, match="nicht moeglich"):
        de.exportiere(de.INHALT_PROTOKOLL, ["srt"], tmp_path / "z", transkript_json=transkript, protokoll_json=protokoll)


def test_basisname_ohne_stamm_faellt_auf_dateinamen_zurueck(tmp_path):
    daten = {"segmente": [{"start": "0", "text": "x", "sprecher": "A"}]}
    pfad = tmp_path / "eigene_datei.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    geschrieben = de.exportiere(de.INHALT_TRANSKRIPT, ["md"], tmp_path / "z", transkript_json=pfad)
    assert geschrieben[0].name == "eigene_datei_transkript.md"
    assert de._basisname(None, None, None) == "export"


# --------------------------------------------------------------------------
# Automatische Word-Datei
# --------------------------------------------------------------------------
def test_automatisches_word_nur_transkript(tmp_path):
    pytest.importorskip("docx", reason="python-docx ist nicht installiert.")
    transkript = _transkript(tmp_path)
    ziel = de.automatisches_word(transkript)
    assert ziel == transkript.with_suffix(".docx") and ziel.read_bytes()[:2] == b"PK"


def test_automatisches_word_mit_protokoll_ist_zusammengefasst(tmp_path):
    docx = pytest.importorskip("docx", reason="python-docx ist nicht installiert.")

    transkript, protokoll = _transkript(tmp_path), _protokoll(tmp_path)
    ziel = de.automatisches_word(transkript, protokoll)
    assert ziel == protokoll.with_suffix(".docx")
    text = "\n".join(p.text for p in docx.Document(str(ziel)).paragraphs)
    assert "Projektbesprechung" in text and "Plan versenden" in text and "Guten Morgen" in text


def test_automatisches_word_ersetzt_die_vorhandene_datei(tmp_path):
    pytest.importorskip("docx", reason="python-docx ist nicht installiert.")
    transkript = _transkript(tmp_path)
    erste = de.automatisches_word(transkript)
    erste.write_bytes(b"alt")
    zweite = de.automatisches_word(transkript)
    assert zweite == erste and zweite.read_bytes()[:2] == b"PK"


def test_automatisches_word_ohne_python_docx(tmp_path, monkeypatch):
    import builtins

    echt = builtins.__import__

    def sperre(name, *args, **kwargs):
        if name == "docx":
            raise ImportError(name)
        return echt(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sperre)
    assert de.automatisches_word(_transkript(tmp_path)) is None
    with pytest.raises(de.ExportFehler, match="python-docx"):
        de.schreibe_docx(de.Dokument("T"), tmp_path / "x.docx")


def test_automatisches_word_meldet_schreibfehler(tmp_path, monkeypatch):
    pytest.importorskip("docx", reason="python-docx ist nicht installiert.")
    transkript = _transkript(tmp_path)

    def verweigern(temp, ziel):
        raise PermissionError("Zugriff verweigert")

    monkeypatch.setattr(de, "_ersetzen_mit_wiederholung", verweigern)
    with pytest.raises(de.ExportFehler, match="Zugriff verweigert"):
        de.automatisches_word(transkript)
    assert not list(tmp_path.glob("*.tmp"))


def test_eindeutiger_pfad(tmp_path):
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "a_2.md").write_text("x")
    assert de.eindeutiger_pfad(tmp_path, "a", ".md").name == "a_3.md"
