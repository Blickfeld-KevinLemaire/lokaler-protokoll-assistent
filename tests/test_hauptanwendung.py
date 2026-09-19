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


# --------------------------------------------------------------------------
# Installer-Variante (mit PyInstaller gebaut, 'sys.frozen' gesetzt)
# --------------------------------------------------------------------------
class _LaufErgebnis:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr


def test_app_dir_gebunden_nutzt_ordner_der_exe(monkeypatch, tmp_path):
    exe = tmp_path / "Protokoll-Assistent.exe"
    monkeypatch.setattr(ha, "IST_GEBUNDEN", True)
    monkeypatch.setattr(ha.sys, "executable", str(exe))

    assert ha._app_dir() == tmp_path


def test_python_suche_findet_passende_version(monkeypatch):
    monkeypatch.setattr(ha.shutil, "which", lambda _name: "C:/Windows/py.exe")
    monkeypatch.setattr(
        ha.subprocess, "run", lambda *_a, **_k: _LaufErgebnis(stdout="Python 3.11.9\n")
    )

    assert ha.python_fuer_lokale_app() == ["py", "-3.11"]


def test_python_suche_akzeptiert_ausgabe_auf_stderr(monkeypatch):
    # 'py --version' schreibt je nach Version nach stderr statt stdout.
    monkeypatch.setattr(ha.shutil, "which", lambda _name: "C:/Windows/py.exe")
    monkeypatch.setattr(
        ha.subprocess, "run", lambda *_a, **_k: _LaufErgebnis(stderr="Python 3.10.11\n")
    )

    assert ha.python_fuer_lokale_app() == ["py", "-3.11"]


def test_python_suche_ueberspringt_falsche_version(monkeypatch):
    monkeypatch.setattr(ha.shutil, "which", lambda _name: "C:/Windows/py.exe")
    monkeypatch.setattr(
        ha.subprocess, "run", lambda *_a, **_k: _LaufErgebnis(stdout="Python 3.13.0\n")
    )

    assert ha.python_fuer_lokale_app() is None


def test_python_suche_ohne_python_im_pfad(monkeypatch):
    monkeypatch.setattr(ha.shutil, "which", lambda _name: None)

    assert ha.python_fuer_lokale_app() is None


def test_python_suche_ueberspringt_kaputten_aufruf(monkeypatch):
    def werfen(*_a, **_k):
        raise OSError("Aufruf fehlgeschlagen")

    monkeypatch.setattr(ha.shutil, "which", lambda _name: "C:/Windows/py.exe")
    monkeypatch.setattr(ha.subprocess, "run", werfen)

    assert ha.python_fuer_lokale_app() is None


def test_starte_lokal_gebunden_nutzt_gefundenes_python(fenster, monkeypatch, tmp_path):
    eintrag = tmp_path / "app.py"
    eintrag.write_text("", encoding="utf-8")
    monkeypatch.setattr(ha, "IST_GEBUNDEN", True)
    monkeypatch.setattr(ha, "LOKAL_ENTRY", eintrag)
    monkeypatch.setattr(ha, "python_fuer_lokale_app", lambda: ["py", "-3.11"])

    aufrufe = []
    monkeypatch.setattr(ha.subprocess, "Popen", lambda cmd, cwd: aufrufe.append((cmd, cwd)))

    fenster.starte_lokal()

    assert aufrufe[0][0] == ["py", "-3.11", str(eintrag)]


def test_starte_lokal_gebunden_ohne_python_meldet_sich(fenster, monkeypatch, tmp_path):
    eintrag = tmp_path / "app.py"
    eintrag.write_text("", encoding="utf-8")
    monkeypatch.setattr(ha, "IST_GEBUNDEN", True)
    monkeypatch.setattr(ha, "LOKAL_ENTRY", eintrag)
    monkeypatch.setattr(ha, "python_fuer_lokale_app", lambda: None)

    fehler = []
    monkeypatch.setattr(ha.messagebox, "showerror", lambda titel, text: fehler.append((titel, text)))
    monkeypatch.setattr(
        ha.subprocess, "Popen", lambda *_a, **_k: pytest.fail("darf nicht starten")
    )

    fenster.starte_lokal()

    assert fehler[0][0] == "Python fehlt"
    assert ha.PYTHON_DOWNLOAD_URL in fehler[0][1]


def test_starte_api_gebunden_startet_zweite_exe(fenster, monkeypatch, tmp_path):
    exe = tmp_path / "Protokoll-Assistent-Cloud.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(ha, "IST_GEBUNDEN", True)
    monkeypatch.setattr(ha, "API_EXE", exe)

    aufrufe = []
    monkeypatch.setattr(ha.subprocess, "Popen", lambda cmd, cwd: aufrufe.append((cmd, cwd)))

    fenster.starte_api()

    assert aufrufe[0][0] == [str(exe)]
    assert "Schnittstellen-Anwendung" in fenster.log_text.get("1.0", "end")


def test_starte_api_gebunden_ohne_exe(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(ha, "IST_GEBUNDEN", True)
    monkeypatch.setattr(ha, "API_EXE", tmp_path / "gibtesnicht.exe")

    fehler = []
    monkeypatch.setattr(ha.messagebox, "showerror", lambda titel, _text: fehler.append(titel))

    fenster.starte_api()

    assert fehler == ["Nicht gefunden"]
