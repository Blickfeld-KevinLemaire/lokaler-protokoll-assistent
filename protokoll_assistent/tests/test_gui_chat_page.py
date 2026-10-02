"""Tests fuer die Seite "Frag mein Meeting" ('gui/chat_page.py').

Der Hintergrundarbeiter wird durch eine Attrappe ersetzt: kein Test fragt ein
Modell, einen Ollama-Dienst oder das Netz an."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import ClassVar

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtCore import Qt  # noqa: E402

from protokoll_assistent.gui import chat_page as cp  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402


class _Signal:
    def __init__(self):
        self.empfaenger = []

    def connect(self, funktion):
        self.empfaenger.append(funktion)

    def emit(self, *args):
        for funktion in self.empfaenger:
            funktion(*args)


class _ArbeiterAttrappe:
    instanzen: ClassVar[list] = []

    def __init__(self, frage, dokumente, verlauf, einstellungen, cache_dir, parent=None):
        self.frage, self.dokumente, self.verlauf = frage, dokumente, verlauf
        self.einstellungen, self.cache_dir = einstellungen, cache_dir
        self.gestartet = False
        self.status = _Signal()
        self.token = _Signal()
        self.fertig = _Signal()
        self.fehlgeschlagen = _Signal()
        _ArbeiterAttrappe.instanzen.append(self)

    def start(self):
        self.gestartet = True


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    konfig = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: konfig)
    ausgabe = tmp_path / "ausgabe"
    ausgabe.mkdir()
    return ausgabe


def _transkript(ordner: Path, name: str, alter: float = 0) -> Path:
    pfad = ordner / f"{name}_lokal_transkript_20260101_100000.json"
    pfad.write_text(json.dumps({"segmente": [{"start_sekunden": 1.0, "text": "Hallo"}]}), encoding="utf-8")
    zeit = time.time() - alter
    os.utime(pfad, (zeit, zeit))
    return pfad


def _protokoll(ordner: Path, name: str, alter: float = 0) -> Path:
    pfad = ordner / f"{name}_protokoll_20260101_110000.md"
    pfad.write_text("# P", encoding="utf-8")
    zeit = time.time() - alter
    os.utime(pfad, (zeit, zeit))
    return pfad


@pytest.fixture
def seite(qt_widgets, ordner, tmp_path, monkeypatch):
    _ArbeiterAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "ChatWorker", _ArbeiterAttrappe)
    return qt_widgets(cp.ChatPage(lambda: ordner, lambda: tmp_path / "cache", lambda: "schluessel"))


def _eintraege(seite):
    return [
        (seite.unterlagen_liste.item(i).text(), seite.unterlagen_liste.item(i).checkState() == Qt.Checked)
        for i in range(seite.unterlagen_liste.count())
    ]


def test_leere_seite_zeigt_hilfetext_und_hinweis(seite):
    assert seite.unterlagen_liste.count() == 0
    seite.aktualisieren()
    assert "Noch keine Unterlagen" in seite.unterlagen_hinweis.text()
    assert "Welche Beschlüsse" in seite.verlauf_anzeige.toPlainText()


def test_unterlagen_werden_gelistet_und_die_neueste_ist_vorausgewaehlt(seite, ordner):
    _transkript(ordner, "alt", alter=500)
    _protokoll(ordner, "neu", alter=10)
    seite.aktualisieren()
    assert _eintraege(seite) == [
        ("Zusammenfassung - neu (01.01.2026 11:00)", True),
        ("Transkript - alt (01.01.2026 10:00)", False),
    ]
    assert [p.name for p in seite.ausgewaehlte_pfade()] == ["neu_protokoll_20260101_110000.md"]


def test_haken_bleiben_beim_neu_laden_erhalten_neue_unterlagen_sind_ungesetzt(seite, ordner):
    _transkript(ordner, "a", alter=100)
    seite.aktualisieren()
    seite.alle_button.click()
    _protokoll(ordner, "b", alter=1)
    seite.aktualisieren()
    zustand = dict(_eintraege(seite))
    assert zustand["Transkript - a (01.01.2026 10:00)"] is True
    assert zustand["Zusammenfassung - b (01.01.2026 11:00)"] is False
    seite.keine_button.click()
    assert seite.ausgewaehlte_pfade() == []


def test_senden_ohne_frage_oder_ohne_unterlagen_startet_nichts(seite, ordner):
    seite.eingabe.setText("   ")
    seite.senden()
    seite.eingabe.setText("Was?")
    seite.senden()  # keine Unterlagen
    assert "mindestens eine Unterlage" in seite.status_label.text()
    assert _ArbeiterAttrappe.instanzen == []
    assert seite.eingabe.text() == "Was?"  # die Frage bleibt stehen


def test_frage_antwort_ablauf_mit_verlauf_und_quellen(seite, ordner):
    _transkript(ordner, "a")
    seite.aktualisieren()
    seite.eingabe.setText("Wie hoch ist das <Budget>?")
    seite.senden()

    arbeiter = _ArbeiterAttrappe.instanzen[-1]
    assert arbeiter.gestartet and arbeiter.frage == "Wie hoch ist das <Budget>?"
    assert arbeiter.verlauf == []
    assert arbeiter.einstellungen.modus == "lokal" and arbeiter.cache_dir.name == "cache"
    assert not seite.senden_button.isEnabled() and not seite.eingabe.isEnabled()
    assert seite.eingabe.text() == ""
    seite.senden()  # waehrend einer Antwort: kein zweiter Arbeiter
    assert len(_ArbeiterAttrappe.instanzen) == 1

    arbeiter.status.emit("Antwort wird erzeugt …")
    assert seite.status_label.text() == "Antwort wird erzeugt …"
    arbeiter.token.emit("Es sind ")
    arbeiter.token.emit("5000 <Euro>.")
    assert "Es sind 5000 <Euro>." in seite.verlauf_anzeige.toPlainText()

    arbeiter.fertig.emit("Es sind 5000 Euro.", ["Transkript a ab 00:00:05"])
    text = seite.verlauf_anzeige.toPlainText()
    assert "Wie hoch ist das <Budget>?" in text and "Es sind 5000 Euro." in text
    assert "Quellen: Transkript a ab 00:00:05" in text
    assert seite.senden_button.isEnabled() and seite.eingabe.isEnabled()

    seite.eingabe.setText("Und der Termin?")
    seite.senden()
    zweiter = _ArbeiterAttrappe.instanzen[-1]
    assert zweiter.verlauf == [
        {"role": "user", "content": "Wie hoch ist das <Budget>?"},
        {"role": "assistant", "content": "Es sind 5000 Euro."},
    ]


def test_fehler_wird_angezeigt_und_die_seite_bleibt_bedienbar(seite, ordner):
    _transkript(ordner, "a")
    seite.aktualisieren()
    seite.eingabe.setText("Frage")
    seite.senden()
    _ArbeiterAttrappe.instanzen[-1].fehlgeschlagen.emit("Ollama ist nicht erreichbar")
    assert "Fehler: Ollama ist nicht erreichbar" in seite.verlauf_anzeige.toPlainText()
    assert seite.senden_button.isEnabled()
    # Fehler und unbeantwortete Frage gehoeren nicht in den Verlauf, der ans Modell geht.
    seite.eingabe.setText("noch mal")
    seite.senden()
    assert _ArbeiterAttrappe.instanzen[-1].verlauf == []


def test_neuer_chat_leert_den_verlauf_nicht_waehrend_einer_antwort(seite, ordner):
    _transkript(ordner, "a")
    seite.aktualisieren()
    seite.eingabe.setText("Frage")
    seite.senden()
    seite.neuer_chat()  # laeuft noch: ignoriert
    assert "Frage" in seite.verlauf_anzeige.toPlainText()
    _ArbeiterAttrappe.instanzen[-1].fertig.emit("Antwort", [])
    seite.neuer_chat()
    assert "Welche Beschlüsse" in seite.verlauf_anzeige.toPlainText()


def test_einstellungen_lokal_und_api_mit_datenschutzhinweis(seite):
    seite.einstellungen_aktualisiert()
    assert "Lokal: qwen3:8b · Einbettung: bge-m3" in seite.modell_label.text()
    assert not seite.datenschutz_label.isVisibleTo(seite)
    e = seite.einstellungen()
    assert (e.modus, e.chat_modell, e.embedding_modell, e.api_schluessel) == ("lokal", "qwen3:8b", "bge-m3", "")

    app_config.update_config(chatbot_modus="api", chatbot_api_modell="gpt-x", chatbot_api_embedding_modell="emb-x")
    seite.einstellungen_aktualisiert()
    assert "API: gpt-x · Einbettung: emb-x" in seite.modell_label.text()
    assert seite.datenschutz_label.isVisibleTo(seite)
    e = seite.einstellungen()
    assert (e.modus, e.chat_modell, e.api_schluessel) == ("api", "gpt-x", "schluessel")
    assert e.modell_kennung == "api:emb-x"
