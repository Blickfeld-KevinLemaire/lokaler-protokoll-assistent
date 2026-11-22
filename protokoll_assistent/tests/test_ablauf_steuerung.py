"""Steuerung: Transkription und Auswertung als Auftraege, Auswertung im Anschluss."""

from __future__ import annotations

from pathlib import Path

import pytest

from protokoll_assistent.ablauf.auftraege import Status
from protokoll_assistent.ablauf.steuerung import ART_AUSWERTUNG, ART_TRANSKRIPTION, Steuerung
from protokoll_assistent.ablauf.verarbeitungswege import Ablauffehler, AuswertungsWunsch, TranskriptionsWunsch
from protokoll_assistent.tests.ablauf_hilfen import alle_auftraege_ausfuehren, steuerung_fuer_test


def _audio(tmp_path: Path) -> Path:
    datei = tmp_path / "besprechung.wav"
    datei.write_bytes(b"RIFF")
    return datei


def test_transkription_mit_anschliessender_auswertung(tmp_path: Path) -> None:
    steuerung, pipeline = steuerung_fuer_test({})
    gespiegelt: list[tuple[str, float | None, str]] = []
    nachher: list[Status] = []
    auftrag = steuerung.transkription_starten(
        TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus", mit_auswertung=True),
        systemprompt="Kurz bitte",
        nach_ende=lambda a: nachher.append(a.status),
        fortschritt_spiegeln=lambda *werte: gespiegelt.append(werte),
    )
    assert auftrag.art == ART_TRANSKRIPTION and auftrag.angaben["modus"] == "lokal"
    alle_auftraege_ausfuehren(steuerung)
    assert auftrag.status is Status.FERTIG
    assert auftrag.ergebnis is not None and auftrag.ergebnis["sprecher"] == {"SPEAKER_00": "Sprecher 1"}
    assert nachher == [Status.FERTIG]
    assert ("transkription", None, "Transkription") in gespiegelt
    assert ("transkription", 0.5, "Transkription") in gespiegelt
    auswertung = [a for a in steuerung.auftraege.liste() if a.art == ART_AUSWERTUNG]
    assert len(auswertung) == 1 and auswertung[0].status is Status.FERTIG
    assert pipeline.auswertungen[0].system_prompt == "Kurz bitte"
    assert auswertung[0].ergebnis is not None and auswertung[0].ergebnis["protokoll_md"].endswith(".md")


def test_anschliessende_auswertung_scheitert_mit_hinweis(tmp_path: Path) -> None:
    steuerung, _pipeline = steuerung_fuer_test({})
    hinweise: list[str] = []
    steuerung.bus.abonnieren(lambda e: hinweise.append(e.daten.get("text", "")) if e.art == "hinweis" else None)
    steuerung.abh.modell_fehlt = lambda modell: True
    steuerung.transkription_starten(TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus", mit_auswertung=True))
    alle_auftraege_ausfuehren(steuerung)
    assert any("Sprachmodell fehlt" in text for text in hinweise)
    assert [a.art for a in steuerung.auftraege.liste()] == [ART_TRANSKRIPTION]


def test_fehlgeschlagene_transkription_ohne_auswertung(tmp_path: Path) -> None:
    steuerung, pipeline = steuerung_fuer_test({})
    pipeline.transkription_fehler = RuntimeError("GPU weg")
    auftrag = steuerung.transkription_starten(TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus", mit_auswertung=True))
    alle_auftraege_ausfuehren(steuerung)
    assert (auftrag.status, auftrag.fehler) == (Status.FEHLER, "GPU weg")
    assert pipeline.auswertungen == []


def test_pruefung_vor_dem_einreihen(tmp_path: Path) -> None:
    steuerung, _pipeline = steuerung_fuer_test({})
    with pytest.raises(Ablauffehler):
        steuerung.transkription_starten(TranskriptionsWunsch(tmp_path / "fehlt.wav", tmp_path))
    with pytest.raises(Ablauffehler):
        steuerung.auswertung_starten(AuswertungsWunsch(tmp_path / "fehlt.json", tmp_path))
    assert steuerung.auftraege.liste() == []


def test_abbrechen_und_ausgabeordner(tmp_path: Path) -> None:
    steuerung, _pipeline = steuerung_fuer_test({"ausgabeordner": str(tmp_path / "ziel")})
    assert steuerung.ausgabeordner() == tmp_path / "ziel"
    auftrag = steuerung.transkription_starten(TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus"))
    assert steuerung.abbrechen(auftrag.id)
    assert auftrag.status is Status.ABGEBROCHEN


def test_starten_und_beenden() -> None:
    steuerung = Steuerung()
    steuerung.starten()
    steuerung.beenden()
    assert steuerung.ausgabeordner().name
