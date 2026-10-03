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
from protokoll_assistent.services import chat_verlauf_service, ollama_service  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402
from protokoll_assistent.utils.diagnostics import DiagnosticCheck  # noqa: E402


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


@pytest.fixture(autouse=True)
def ollama_nicht_erreichbar(monkeypatch):
    """Kein Test fragt einen echten Ollama-Dienst."""

    def unerreichbar(base_url=ollama_service.OLLAMA_BASE_URL, timeout=5):
        raise ollama_service.OllamaError("kein Dienst im Test")

    monkeypatch.setattr(ollama_service, "list_models", unerreichbar)


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
    return qt_widgets(
        cp.ChatPage(lambda: ordner, lambda: tmp_path / "cache", lambda: "schluessel", lambda: tmp_path / "verlaeufe")
    )


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



# --------------------------------------------------------------------------
# Hinweisleiste: fehlendes Modell, Download erst auf Wunsch
# --------------------------------------------------------------------------
class _PullAttrappe:
    instanzen: ClassVar[list] = []

    def __init__(self, modell, parent=None):
        self.modell = modell
        self.gestartet = False
        self.fortschritt = _Signal()
        self.fertig = _Signal()
        self.fehlgeschlagen = _Signal()
        _PullAttrappe.instanzen.append(self)

    def start(self):
        self.gestartet = True


def _ollama_mit(monkeypatch, installiert):
    monkeypatch.setattr(ollama_service, "list_models", lambda base_url=None, timeout=5: list(installiert))


def test_ohne_ollama_steht_ein_hinweis_ohne_download_knopf(seite):
    seite.hinweis_pruefen()
    assert seite.hinweis_rahmen.isVisibleTo(seite)
    assert "Ollama ist nicht erreichbar" in seite.hinweis_label.text()
    assert not seite.hinweis_download_button.isVisibleTo(seite)


def test_fehlendes_einbettungsmodell_steht_als_erster_hinweis_und_wird_nicht_ungefragt_geladen(seite, monkeypatch):
    _PullAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "OllamaPullWorker", _PullAttrappe)
    _ollama_mit(monkeypatch, ["qwen3:8b"])  # Chatmodell da, Einbettungsmodell fehlt

    seite.hinweis_pruefen()

    assert seite.hinweis_rahmen.isVisibleTo(seite)
    assert "Einbettungsmodell „bge-m3“ (ca. 1.2 GB)" in seite.hinweis_label.text()
    assert "erst heruntergeladen, wenn Sie es möchten" in seite.hinweis_label.text()
    assert seite.hinweis_download_button.isVisibleTo(seite)
    assert _PullAttrappe.instanzen == []  # nichts ungefragt


def test_hinweis_verschwindet_nach_dem_download(seite, monkeypatch):
    _PullAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "OllamaPullWorker", _PullAttrappe)
    installiert = ["qwen3:8b"]
    _ollama_mit(monkeypatch, installiert)
    seite.hinweis_pruefen()

    seite.hinweis_download_button.click()
    arbeiter = _PullAttrappe.instanzen[-1]
    assert arbeiter.gestartet and arbeiter.modell == "bge-m3"
    assert not seite.hinweis_download_button.isEnabled()
    seite.hinweis_download_button.click()  # zweiter Klick: kein zweiter Download
    assert len(_PullAttrappe.instanzen) == 1

    arbeiter.fortschritt.emit("pulling abc", 600_000_000, 1_200_000_000)
    assert seite.hinweis_fortschritt.value() == 50 and "0.6 von 1.2 GB" in seite.hinweis_label.text()
    arbeiter.fortschritt.emit("verifying", 0, 0)
    assert seite.hinweis_label.text() == "verifying"

    installiert.append("bge-m3")
    arbeiter.fertig.emit("bge-m3")
    assert not seite.hinweis_rahmen.isVisibleTo(seite)  # Meldung ist weg


def test_nach_dem_ersten_modell_wird_das_naechste_fehlende_gezeigt(seite, monkeypatch):
    _PullAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "OllamaPullWorker", _PullAttrappe)
    installiert: list[str] = []
    _ollama_mit(monkeypatch, installiert)
    seite.hinweis_pruefen()
    assert "Einbettungsmodell" in seite.hinweis_label.text()
    seite.hinweis_download_button.click()
    installiert.append("bge-m3")
    _PullAttrappe.instanzen[-1].fertig.emit("bge-m3")
    assert "Chatmodell „qwen3:8b“" in seite.hinweis_label.text()


def test_download_fehler_bleibt_sichtbar_und_erneuter_versuch_ist_moeglich(seite, monkeypatch):
    _PullAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "OllamaPullWorker", _PullAttrappe)
    _ollama_mit(monkeypatch, ["qwen3:8b"])
    seite.hinweis_pruefen()
    seite.hinweis_download_button.click()
    _PullAttrappe.instanzen[-1].fehlgeschlagen.emit("bge-m3", "kein Speicherplatz")
    assert "kein Speicherplatz" in seite.hinweis_label.text()
    assert seite.hinweis_rahmen.isVisibleTo(seite) and seite.hinweis_download_button.isEnabled()


def test_senden_wird_bei_fehlendem_modell_nicht_gestartet(seite, ordner, monkeypatch):
    _transkript(ordner, "a")
    seite.aktualisieren()
    _ollama_mit(monkeypatch, ["qwen3:8b"])
    seite.hinweis_pruefen()
    seite.eingabe.setText("Frage")
    seite.senden()
    assert "fehlende Modell herunterladen" in seite.status_label.text()
    assert _ArbeiterAttrappe.instanzen == []


def test_hinweis_im_api_modus_ohne_schluessel(qt_widgets, ordner, tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "ChatWorker", _ArbeiterAttrappe)
    app_config.update_config(
        chatbot_modus="api",
        chatbot_api_endpunkt="https://api.test/chat",
        chatbot_api_embedding_endpunkt="https://api.test/emb",
    )
    ohne = qt_widgets(cp.ChatPage(lambda: ordner, lambda: tmp_path / "c", lambda: "", lambda: tmp_path / "v"))
    assert "kein API-Schlüssel" in ohne.hinweis_label.text() and not ohne.hinweis_download_button.isVisibleTo(ohne)
    mit = qt_widgets(cp.ChatPage(lambda: ordner, lambda: tmp_path / "c", lambda: "k", lambda: tmp_path / "v"))
    assert not mit.hinweis_rahmen.isVisibleTo(mit)


def test_hinweis_im_api_modus_ohne_anbieter(qt_widgets, ordner, tmp_path, monkeypatch):
    """Ab Werk ist kein Anbieter gewaehlt -- das steht als Erstes oben, auch wenn
    schon ein Schluessel da ist."""
    monkeypatch.setattr(cp, "ChatWorker", _ArbeiterAttrappe)
    app_config.update_config(chatbot_modus="api")
    seite = qt_widgets(cp.ChatPage(lambda: ordner, lambda: tmp_path / "c", lambda: "k", lambda: tmp_path / "v"))
    assert "noch kein Anbieter gewählt" in seite.hinweis_label.text()
    assert seite.hinweis_rahmen.isVisibleTo(seite) and not seite.hinweis_download_button.isVisibleTo(seite)


# --------------------------------------------------------------------------
# Systemcheck
# --------------------------------------------------------------------------
class _CheckAttrappe:
    instanzen: ClassVar[list] = []

    def __init__(self, einstellungen, parent=None):
        self.einstellungen = einstellungen
        self.gestartet = False
        self.fertig = _Signal()
        _CheckAttrappe.instanzen.append(self)

    def start(self):
        self.gestartet = True


def test_systemcheck_zeigt_das_ergebnis_in_einem_dialog(seite, monkeypatch):
    _CheckAttrappe.instanzen.clear()
    monkeypatch.setattr(cp, "ChatCheckWorker", _CheckAttrappe)
    gezeigt = []
    monkeypatch.setattr(
        cp,
        "ChatSystemcheckDialog",
        lambda ergebnisse, parent=None: type("D", (), {"exec": lambda self: gezeigt.append(ergebnisse)})(),
    )

    seite.systemcheck_starten()
    arbeiter = _CheckAttrappe.instanzen[-1]
    assert arbeiter.gestartet and not seite.systemcheck_button.isEnabled()
    assert arbeiter.einstellungen.modus == "lokal"
    seite.systemcheck_starten()  # laeuft schon
    assert len(_CheckAttrappe.instanzen) == 1

    ergebnisse = [DiagnosticCheck("a", "Ollama", True, "ok", True)]
    arbeiter.fertig.emit(ergebnisse)
    assert gezeigt == [ergebnisse]
    assert seite.systemcheck_button.isEnabled() and seite.status_label.text() == ""


# --------------------------------------------------------------------------
# Gespeicherte Chats
# --------------------------------------------------------------------------
def _frage_stellen(seite, frage, antwort, quellen=()):
    seite.eingabe.setText(frage)
    seite.senden()
    _ArbeiterAttrappe.instanzen[-1].fertig.emit(antwort, list(quellen))


def test_beantwortete_frage_wird_als_chat_gespeichert_und_in_der_liste_gezeigt(seite, ordner, tmp_path):
    t = _transkript(ordner, "a")
    seite.aktualisieren()
    _frage_stellen(seite, "Wie hoch ist das Budget?", "5000 Euro.", ["a ab 00:00:05"])

    gespeichert = chat_verlauf_service.lade_alle(tmp_path / "verlaeufe")
    assert len(gespeichert) == 1
    assert gespeichert[0].titel == "Wie hoch ist das Budget?"
    assert gespeichert[0].dokumente == [str(t)]
    assert [n["role"] for n in gespeichert[0].nachrichten] == ["user", "assistant"]
    assert gespeichert[0].nachrichten[1]["quellen"] == ["a ab 00:00:05"]
    assert seite.verlaeufe_liste.count() == 1
    assert "Wie hoch ist das Budget?" in seite.verlaeufe_liste.item(0).text()

    _frage_stellen(seite, "Und der Termin?", "Freitag.")
    assert len(chat_verlauf_service.lade_alle(tmp_path / "verlaeufe")) == 1  # derselbe Chat
    assert len(chat_verlauf_service.lade_alle(tmp_path / "verlaeufe")[0].nachrichten) == 4


def test_fehler_und_unbeantwortete_fragen_werden_nicht_gespeichert(seite, ordner, tmp_path):
    _transkript(ordner, "a")
    seite.aktualisieren()
    seite.eingabe.setText("Frage")
    seite.senden()
    _ArbeiterAttrappe.instanzen[-1].fehlgeschlagen.emit("kaputt")
    assert chat_verlauf_service.lade_alle(tmp_path / "verlaeufe") == []


def test_gespeicherten_chat_oeffnen_stellt_nachrichten_und_unterlagen_wieder_her(seite, ordner, tmp_path):
    a = _transkript(ordner, "a", alter=100)
    b = _protokoll(ordner, "b", alter=50)
    seite.aktualisieren()
    seite.keine_button.click()
    seite.unterlagen_liste.item(1).setCheckState(Qt.Checked)  # nur 'a'
    _frage_stellen(seite, "Frage 1", "Antwort 1", ["a ab 00:00:01"])
    seite.neuer_chat()
    assert "Welche Beschlüsse" in seite.verlauf_anzeige.toPlainText()
    seite.alle_button.click()

    seite._verlauf_angeklickt(seite.verlaeufe_liste.item(0))

    text = seite.verlauf_anzeige.toPlainText()
    assert "Frage 1" in text and "Antwort 1" in text and "Quellen: a ab 00:00:01" in text
    assert seite.ausgewaehlte_pfade() == [a]
    # ... und der Chat laesst sich fortsetzen: der Verlauf geht ans Modell
    seite.eingabe.setText("Frage 2")
    seite.senden()
    assert _ArbeiterAttrappe.instanzen[-1].verlauf[0] == {"role": "user", "content": "Frage 1"}
    assert b.exists()


def test_chat_oeffnen_meldet_fehlende_unterlagen_und_kaputte_dateien(seite, ordner, tmp_path):
    t = _transkript(ordner, "a")
    seite.aktualisieren()
    _frage_stellen(seite, "Frage", "Antwort")
    t.unlink()
    seite.aktualisieren()
    seite._verlauf_angeklickt(seite.verlaeufe_liste.item(0))
    assert "gibt es nicht mehr" in seite.status_label.text()

    kennung = seite.verlaeufe_liste.item(0).data(Qt.UserRole)
    (tmp_path / "verlaeufe" / f"{kennung}.json").write_text("{kaputt", encoding="utf-8")
    seite._verlauf_angeklickt(seite.verlaeufe_liste.item(0))
    assert "nicht gelesen" in seite.status_label.text()
    assert seite.verlaeufe_liste.count() == 0


def test_chat_umbenennen_und_loeschen(seite, ordner, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    _transkript(ordner, "a")
    seite.aktualisieren()
    _frage_stellen(seite, "Frage", "Antwort")
    seite.verlaeufe_liste.setCurrentRow(0)

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Budget-Runde", True)))
    seite._verlauf_umbenennen()
    assert "Budget-Runde" in seite.verlaeufe_liste.item(0).text()
    assert chat_verlauf_service.lade_alle(tmp_path / "verlaeufe")[0].titel == "Budget-Runde"

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    seite._verlauf_loeschen()
    assert seite.verlaeufe_liste.count() == 1
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    seite._verlauf_loeschen()
    assert seite.verlaeufe_liste.count() == 0
    assert "Welche Beschlüsse" in seite.verlauf_anzeige.toPlainText()  # der geoeffnete Chat wurde geschlossen


def test_umbenennen_und_loeschen_ohne_auswahl_tun_nichts(seite):
    seite._verlauf_umbenennen()
    seite._verlauf_loeschen()


def test_neuer_chat_beginnt_einen_neuen_gespeicherten_verlauf(seite, ordner, tmp_path):
    _transkript(ordner, "a")
    seite.aktualisieren()
    _frage_stellen(seite, "Erste Frage", "A1")
    seite.neuer_chat()
    _frage_stellen(seite, "Zweite Frage", "A2")
    titel = {v.titel for v in chat_verlauf_service.lade_alle(tmp_path / "verlaeufe")}
    assert titel == {"Erste Frage", "Zweite Frage"}


def test_speicherfehler_wird_gemeldet_ohne_abzustuerzen(seite, ordner, monkeypatch):
    _transkript(ordner, "a")
    seite.aktualisieren()

    def werfen(ordner, verlauf):
        raise OSError("Platte voll")

    monkeypatch.setattr(chat_verlauf_service, "speichern", werfen)
    _frage_stellen(seite, "Frage", "Antwort")
    assert "nicht gespeichert werden" in seite.status_label.text()
    assert "Antwort" in seite.verlauf_anzeige.toPlainText()
