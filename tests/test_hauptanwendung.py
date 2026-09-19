"""Tests fuer das Startfenster (``hauptanwendung.py``)."""

from __future__ import annotations

import sys
import tkinter as tk

import pytest

import hauptanwendung as ha


@pytest.fixture
def fenster(tk_wurzel):
    return ha.HauptanwendungFenster(tk_wurzel)


def test_fenster_baut_sich_auf(fenster):
    assert "Protokoll-Assistent" in fenster.root.title()
    assert fenster.log_text is not None


def test_theme_umschalten(fenster):
    fenster.dunkel_var.set(True)
    fenster._theme_umschalten()
    assert fenster.aktuelles_theme == "dark"

    fenster.dunkel_var.set(False)
    fenster._theme_umschalten()
    assert fenster.aktuelles_theme == "light"


def test_theme_umschalten_ohne_sv_ttk(fenster, monkeypatch):
    monkeypatch.setattr(ha.theme, "HAT_SV_TTK", False)
    fenster.dunkel_var.set(True)
    fenster._theme_umschalten()
    assert fenster.aktuelles_theme == "dark"


def test_log_schreibt_und_sperrt_wieder(fenster):
    fenster._log("eine Meldung")
    assert "eine Meldung" in fenster.log_text.get("1.0", "end")
    assert str(fenster.log_text.cget("state")) == "disabled"


def test_karte_ohne_sv_ttk(fenster, monkeypatch):
    monkeypatch.setattr(ha.theme, "HAT_SV_TTK", False)
    fenster._build_karte("Titel", "Beschreibung", "Los", lambda: None)  # darf nicht werfen


# --------------------------------------------------------------------------
# starte_lokal / starte_api
# --------------------------------------------------------------------------
def test_starte_lokal_ohne_datei(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(ha, "LOKAL_ENTRY", tmp_path / "gibtesnicht.py")
    fehler = []
    monkeypatch.setattr(ha.messagebox, "showerror", lambda t, _n: fehler.append(t))

    fenster.starte_lokal()

    assert fehler == ["Nicht gefunden"]


def test_starte_lokal(fenster, monkeypatch, tmp_path):
    eintrag = tmp_path / "app.py"
    eintrag.write_text("", encoding="utf-8")
    monkeypatch.setattr(ha, "LOKAL_ENTRY", eintrag)

    aufrufe = []
    monkeypatch.setattr(ha.subprocess, "Popen", lambda cmd, cwd: aufrufe.append((cmd, cwd)))

    fenster.starte_lokal()

    assert aufrufe[0][0] == [sys.executable, str(eintrag)]
    assert "Lokale Anwendung" in fenster.log_text.get("1.0", "end")


def test_starte_api_ohne_datei(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(ha, "API_ENTRY", tmp_path / "gibtesnicht.py")
    fehler = []
    monkeypatch.setattr(ha.messagebox, "showerror", lambda t, _n: fehler.append(t))

    fenster.starte_api()

    assert fehler == ["Nicht gefunden"]


def test_starte_api(fenster, monkeypatch, tmp_path):
    eintrag = tmp_path / "gui.py"
    eintrag.write_text("", encoding="utf-8")
    monkeypatch.setattr(ha, "API_ENTRY", eintrag)

    aufrufe = []
    monkeypatch.setattr(ha.subprocess, "Popen", lambda cmd, cwd: aufrufe.append((cmd, cwd)))

    fenster.starte_api()

    assert aufrufe[0][0] == [sys.executable, str(eintrag)]
    assert "Schnittstellen-Anwendung" in fenster.log_text.get("1.0", "end")


def test_starte_prozess_meldet_fehler(fenster, monkeypatch, tmp_path):
    def werfen(*_a, **_k):
        raise OSError("kein Python")

    monkeypatch.setattr(ha.subprocess, "Popen", werfen)
    fehler = []
    monkeypatch.setattr(ha.messagebox, "showerror", lambda _t, text: fehler.append(text))

    fenster._starte_prozess(["python"], cwd=tmp_path, beschreibung="Testlauf")

    assert "kein Python" in fehler[0]
    # Nach einem Fehler darf keine Erfolgsmeldung im Protokoll stehen.
    assert "wird gestartet" not in fenster.log_text.get("1.0", "end")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_startet_und_beendet(monkeypatch):
    erzeugt: dict[str, tk.Tk] = {}

    class _FensterAttrappe:
        def __init__(self, root):
            root.withdraw()
            erzeugt["root"] = root

    monkeypatch.setattr(ha, "HauptanwendungFenster", _FensterAttrappe)
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self: None)

    try:
        assert ha.main() == 0
    finally:
        if "root" in erzeugt:
            erzeugt["root"].destroy()
