"""Tests fuer die Schritte einer Sprachfrage (services/geraete_fragen.py): Frage verstehen, aus Unterlagen beantworten."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import chat_service, geraete_fragen


def test_frage_verstehen_schneidet_und_transkribiert_den_ton(tmp_path):
    gesehen = {}

    def extrahieren(quelle: Path, ziel: Path, start: float, ende: float):
        gesehen["quelle"] = (quelle.name, quelle.read_bytes())
        gesehen["bereich"] = (start, ende)
        ziel.write_bytes(b"wav")

    def transkribieren(wav: Path):
        gesehen["wav"] = wav.read_bytes()
        return [{"text": " Was macht"}, {"text": "Fritz? "}, {"text": ""}]

    text = geraete_fragen.frage_verstehen(
        b"OggS-ton", ".opus", transkribieren=transkribieren, extrahieren=extrahieren, arbeitsordner=tmp_path
    )
    assert text == "Was macht Fritz?"
    assert gesehen["quelle"] == ("frage.opus", b"OggS-ton") and gesehen["wav"] == b"wav"
    assert gesehen["bereich"] == (0.0, geraete_fragen.FRAGE_MAX_SEKUNDEN)
    assert list(tmp_path.iterdir()) == []  # der Ton der Frage bleibt nicht liegen


def _transkript(pfad: Path) -> Path:
    pfad.write_text(
        json.dumps({"segmente": [{"start": 5.0, "end": 9.0, "text": "Fritz schreibt das Angebot.", "sprecher": "Anna"}]}),
        encoding="utf-8",
    )
    return pfad


def test_antwort_aus_unterlagen_nimmt_zusammenfassung_und_transkript(tmp_path):
    transkript = _transkript(tmp_path / "t.json")
    zusammenfassung = tmp_path / "z.txt"
    zusammenfassung.write_text("Aufgabe: Fritz, Angebot.", encoding="utf-8")
    angefragt = []

    def chat(nachrichten, _on_token):
        angefragt.append(nachrichten)
        return "Fritz schreibt das Angebot."

    antwort = geraete_fragen.antwort_aus_unterlagen(
        "Was macht Fritz?", [zusammenfassung, transkript, tmp_path / "fehlt.txt"], chat
    )
    assert antwort == "Fritz schreibt das Angebot."
    inhalt = angefragt[0][-1]["content"]
    assert "Aufgabe: Fritz, Angebot." in inhalt and "Fritz schreibt das Angebot." in inhalt
    assert "Was macht Fritz?" in inhalt and "nummerierte Liste" in inhalt  # Standard: fuers Display
    angefragt.clear()
    geraete_fragen.antwort_aus_unterlagen("Was macht Fritz?", [transkript], chat, geraete_fragen.AUSGABE_TON)
    assert "hoechstens vier kurze Saetze" in angefragt[0][-1]["content"]


def test_ohne_unterlagen_gibt_es_keine_antwort(tmp_path):
    with pytest.raises(chat_service.ChatFehler, match="keine Unterlagen"):
        geraete_fragen.antwort_aus_unterlagen("Frage?", [tmp_path / "fehlt.json"], lambda n, t: "x")


def test_fuer_display_schreibt_umlaute_um_und_entfernt_markdown():
    text = "**Ergebnis:**\n1. Fritz schreibt das Angebot \u2013 bis Freitag.\n2. \u201eBudget\u201c pr\u00fcfen\n\n\n\n* Gr\u00f6\u00dfe \u20ac 5\n### \u00dcberblick"
    assert geraete_fragen.fuer_display(text) == (
        "Ergebnis:\n1. Fritz schreibt das Angebot - bis Freitag.\n2. \"Budget\" pruefen\n\n- Groesse EUR 5\nUeberblick"
    )
    assert geraete_fragen.fuer_display("Caf\u00e9 \u4e2d") == "Caf? ?"  # Unbekanntes wird sichtbar, nicht verschluckt
