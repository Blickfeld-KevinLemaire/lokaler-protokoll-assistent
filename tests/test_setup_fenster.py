"""Tests fuer das Einrichtungsfenster (``setup_fenster.py``)."""

from __future__ import annotations

import queue
import sys
import tkinter as tk

import pytest

import setup_fenster as sf


class _FakeProzess:
    """Ersetzt subprocess.Popen: liefert feste Ausgabezeilen und einen Code."""

    def __init__(self, zeilen: list[str], returncode: int = 0):
        self.stdout = iter(zeilen)
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.fixture
def fenster(tk_wurzel):
    """Das Fenster plant '_pruefe_alles' per 'after(200, ...)' ein. In den Tests
    laeuft keine Tk-Ereignisschleife, der Rueckruf feuert also nie von selbst -
    die Pruefungen werden gezielt einzeln aufgerufen."""
    return sf.EinrichtungsFenster(tk_wurzel)


# --------------------------------------------------------------------------
# check_python
# --------------------------------------------------------------------------
def test_check_python_aktuelle_version():
    ok, text = sf.check_python()
    assert ok is True
    assert "gefunden" in text


def test_check_python_zu_alt(monkeypatch):
    class _Version(tuple):
        pass

    monkeypatch.setattr(sf.sys, "version_info", _Version((3, 8, 10)))
    ok, text = sf.check_python()
    assert ok is False
    assert "3.10 oder neuer" in text


# --------------------------------------------------------------------------
# find_ollama
# --------------------------------------------------------------------------
def test_find_ollama_ueber_path(monkeypatch):
    monkeypatch.setattr(sf.shutil, "which", lambda _n: "C:/bin/ollama.exe")
    assert sf.find_ollama() == "C:/bin/ollama.exe"


def test_find_ollama_im_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sf.shutil, "which", lambda _n: None)
    ziel = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    ziel.parent.mkdir(parents=True)
    ziel.write_bytes(b"\x00")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert sf.find_ollama() == str(ziel)


def test_find_ollama_nicht_vorhanden(monkeypatch, tmp_path):
    monkeypatch.setattr(sf.shutil, "which", lambda _n: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert sf.find_ollama() is None


def test_find_ollama_ohne_localappdata(monkeypatch):
    monkeypatch.setattr(sf.shutil, "which", lambda _n: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert sf.find_ollama() is None


# --------------------------------------------------------------------------
# create_desktop_shortcut
# --------------------------------------------------------------------------
def test_verknuepfung_nur_unter_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "IST_WINDOWS", False)
    with pytest.raises(RuntimeError, match="nur unter Windows"):
        sf.create_desktop_shortcut(tmp_path, lambda _m: None)


def test_verknuepfung_wird_erstellt(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "IST_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    befehle = []

    def fake_run(command, capture_output, text, timeout=None):
        befehle.append(command)
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    meldungen: list[str] = []

    pfad = sf.create_desktop_shortcut(tmp_path, meldungen.append)

    assert pfad.name == "Protokoll-Assistent.lnk"
    assert befehle[0][0] == "powershell"
    # Das Skript steht hinter "-Command"; die Pfade folgen als eigene Argumente.
    assert "CreateShortcut" in befehle[0][4]
    assert meldungen


def test_verknuepfung_meldet_powershell_fehler(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "IST_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(
        sf.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "Zugriff verweigert"})(),
    )
    with pytest.raises(RuntimeError, match="Zugriff verweigert"):
        sf.create_desktop_shortcut(tmp_path, lambda _m: None)


def test_verknuepfung_meldet_fehler_ohne_text(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "IST_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(
        sf.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "   "})(),
    )
    with pytest.raises(RuntimeError, match="PowerShell konnte"):
        sf.create_desktop_shortcut(tmp_path, lambda _m: None)


# --------------------------------------------------------------------------
# Fensteraufbau und Pruefungen
# --------------------------------------------------------------------------
def test_fenster_baut_sich_auf(fenster):
    assert fenster.root.title() == "Protokoll-Assistent - Einrichtung"
    assert set(fenster.status_vars) >= {"design", "python", "ffmpeg", "ollama"}


def test_pruefe_alles_mit_passender_python_version(fenster, monkeypatch):
    monkeypatch.setattr(sf, "check_python", lambda: (True, "Python 3.11.0 gefunden."))
    monkeypatch.setattr(sf, "find_ollama", lambda: None)
    monkeypatch.setattr(sf.gui, "find_ffmpeg", lambda: None)

    geoeffnet = []
    monkeypatch.setattr(sf.webbrowser, "open", geoeffnet.append)

    fenster._pruefe_alles()

    assert fenster.status_vars["python"].get().startswith("OK: ")
    assert geoeffnet == []  # kein Browser bei passender Version


def test_pruefe_alles_oeffnet_download_bei_alter_python_version(fenster, monkeypatch):
    monkeypatch.setattr(sf, "check_python", lambda: (False, "Python 3.8.0 gefunden."))
    monkeypatch.setattr(sf, "find_ollama", lambda: None)
    monkeypatch.setattr(sf.gui, "find_ffmpeg", lambda: None)

    geoeffnet = []
    monkeypatch.setattr(sf.webbrowser, "open", geoeffnet.append)

    fenster._pruefe_alles()

    assert fenster.status_vars["python"].get().startswith("Problem: ")
    assert geoeffnet == [sf.PYTHON_DOWNLOAD_URL]


def test_pruefe_design_installiert(fenster, monkeypatch):
    monkeypatch.setattr(sf.theme, "HAT_SV_TTK", True)
    fenster._pruefe_design()
    assert "OK:" in fenster.status_vars["design"].get()
    assert str(fenster.design_button.cget("state")) == "disabled"


def test_pruefe_design_fehlt(fenster, monkeypatch):
    monkeypatch.setattr(sf.theme, "HAT_SV_TTK", False)
    fenster._pruefe_design()
    assert "Nicht installiert" in fenster.status_vars["design"].get()
    assert str(fenster.design_button.cget("state")) == "normal"


def test_pruefe_ffmpeg_gefunden(fenster, monkeypatch):
    monkeypatch.setattr(sf.gui, "find_ffmpeg", lambda: "C:/bin/ffmpeg.exe")
    fenster._pruefe_ffmpeg()
    assert "C:/bin/ffmpeg.exe" in fenster.status_vars["ffmpeg"].get()


def test_pruefe_ffmpeg_fehlt(fenster, monkeypatch):
    monkeypatch.setattr(sf.gui, "find_ffmpeg", lambda: None)
    fenster._pruefe_ffmpeg()
    assert "Nicht gefunden" in fenster.status_vars["ffmpeg"].get()


def test_pruefe_ollama_gefunden(fenster, monkeypatch):
    monkeypatch.setattr(sf, "find_ollama", lambda: "C:/bin/ollama.exe")
    fenster._pruefe_ollama()
    assert "C:/bin/ollama.exe" in fenster.status_vars["ollama"].get()
    assert str(fenster.pull_button.cget("state")) == "normal"


def test_pruefe_ollama_fehlt(fenster, monkeypatch):
    monkeypatch.setattr(sf, "find_ollama", lambda: None)
    fenster._pruefe_ollama()
    assert "Nicht gefunden" in fenster.status_vars["ollama"].get()
    assert str(fenster.pull_button.cget("state")) == "disabled"


# --------------------------------------------------------------------------
# Design nachinstallieren
# --------------------------------------------------------------------------
def test_design_installieren_startet_faden(fenster, monkeypatch):
    gestartet = []

    class _Faden:
        def __init__(self, target, daemon):
            gestartet.append(target)

        def start(self):
            pass

    monkeypatch.setattr(sf.threading, "Thread", _Faden)
    fenster._design_installieren()

    assert str(fenster.design_button.cget("state")) == "disabled"
    assert gestartet


def test_design_installieren_hintergrund_erfolg(fenster, monkeypatch):
    monkeypatch.setattr(
        sf.subprocess, "Popen", lambda *a, **k: _FakeProzess(["Sammle sv-ttk"], 0)
    )
    fenster._design_installieren_hintergrund()

    meldungen = [n[1] for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("installiert" in str(m) for m in meldungen)


def test_design_installieren_hintergrund_pip_fehler(fenster, monkeypatch):
    monkeypatch.setattr(sf.subprocess, "Popen", lambda *a, **k: _FakeProzess([], 1))
    fenster._design_installieren_hintergrund()

    meldungen = [str(n[1]) for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("FEHLER" in m for m in meldungen)


def test_design_installieren_hintergrund_ohne_pip(fenster, monkeypatch):
    def werfen(*_a, **_k):
        raise OSError("pip nicht da")

    monkeypatch.setattr(sf.subprocess, "Popen", werfen)
    fenster._design_installieren_hintergrund()

    meldungen = [str(n[1]) for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("pip nicht da" in m for m in meldungen)


# --------------------------------------------------------------------------
# Modell herunterladen
# --------------------------------------------------------------------------
def test_modell_laden_ohne_ollama(fenster, monkeypatch):
    monkeypatch.setattr(sf, "find_ollama", lambda: None)
    warnungen = []
    monkeypatch.setattr(sf.messagebox, "showwarning", lambda t, _n: warnungen.append(t))

    fenster._modell_laden()

    assert warnungen == ["Ollama fehlt"]


def test_modell_laden_startet_faden(fenster, monkeypatch):
    monkeypatch.setattr(sf, "find_ollama", lambda: "C:/bin/ollama.exe")
    gestartet = []

    class _Faden:
        def __init__(self, target, args, daemon):
            gestartet.append(args)

        def start(self):
            pass

    monkeypatch.setattr(sf.threading, "Thread", _Faden)
    fenster._modell_laden()

    assert gestartet == [("C:/bin/ollama.exe",)]
    assert str(fenster.pull_button.cget("state")) == "disabled"


def test_modell_laden_hintergrund_erfolg(fenster, monkeypatch):
    monkeypatch.setattr(
        sf.subprocess, "Popen", lambda *a, **k: _FakeProzess(["pulling manifest"], 0)
    )
    fenster._modell_laden_hintergrund("ollama")

    meldungen = [str(n[1]) for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("ist bereit" in m for m in meldungen)


def test_modell_laden_hintergrund_fehlercode(fenster, monkeypatch):
    monkeypatch.setattr(sf.subprocess, "Popen", lambda *a, **k: _FakeProzess([], 2))
    fenster._modell_laden_hintergrund("ollama")

    meldungen = [str(n[1]) for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("Code 2" in m for m in meldungen)


def test_modell_laden_hintergrund_ollama_nicht_ausfuehrbar(fenster, monkeypatch):
    def werfen(*_a, **_k):
        raise OSError("nicht ausfuehrbar")

    monkeypatch.setattr(sf.subprocess, "Popen", werfen)
    fenster._modell_laden_hintergrund("ollama")

    meldungen = [str(n[1]) for n in _queue_leeren(fenster.message_queue) if n[0] == "log"]
    assert any("nicht ausfuehrbar" in m for m in meldungen)


# --------------------------------------------------------------------------
# Verknuepfung und Start
# --------------------------------------------------------------------------
def test_verknuepfung_erstellen_erfolg(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "create_desktop_shortcut", lambda d, log: tmp_path / "x.lnk")
    infos = []
    monkeypatch.setattr(sf.messagebox, "showinfo", lambda t, _n: infos.append(t))

    fenster._verknuepfung_erstellen()

    assert infos == ["Fertig"]


def test_verknuepfung_erstellen_fehler(fenster, monkeypatch):
    def werfen(_d, _log):
        raise RuntimeError("ging nicht")

    monkeypatch.setattr(sf, "create_desktop_shortcut", werfen)
    fehler = []
    monkeypatch.setattr(sf.messagebox, "showerror", lambda t, text: fehler.append(text))

    fenster._verknuepfung_erstellen()

    assert fehler == ["ging nicht"]


def test_anwendung_starten(fenster, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(sf.subprocess, "Popen", lambda cmd, cwd: aufrufe.append(cmd))
    fenster._anwendung_starten()
    assert aufrufe[0][0] == sys.executable
    assert aufrufe[0][1].endswith("hauptanwendung.py")


def test_anwendung_starten_fehler(fenster, monkeypatch):
    def werfen(*_a, **_k):
        raise OSError("kein Python")

    monkeypatch.setattr(sf.subprocess, "Popen", werfen)
    fehler = []
    monkeypatch.setattr(sf.messagebox, "showerror", lambda t, text: fehler.append(text))

    fenster._anwendung_starten()

    assert "kein Python" in fehler[0]


# --------------------------------------------------------------------------
# Queue
# --------------------------------------------------------------------------
def _queue_leeren(q: queue.Queue) -> list[tuple[str, object]]:
    eintraege = []
    while True:
        try:
            eintraege.append(q.get_nowait())
        except queue.Empty:
            return eintraege


def test_poll_queue_verarbeitet_nachrichten(fenster, monkeypatch):
    monkeypatch.setattr(fenster.root, "after", lambda *_a, **_k: None)
    monkeypatch.setattr(sf.theme, "HAT_SV_TTK", True)

    fenster.message_queue.put(("log", "eine Zeile"))
    fenster.message_queue.put(("enable_pull", None))
    fenster.message_queue.put(("enable_design_button", None))

    fenster._poll_queue()

    assert "eine Zeile" in fenster.log_text.get("1.0", "end")
    assert str(fenster.pull_button.cget("state")) == "normal"


def test_poll_queue_plant_sich_neu(fenster, monkeypatch):
    geplant = []
    monkeypatch.setattr(fenster.root, "after", lambda ms, _cb: geplant.append(ms))
    fenster._poll_queue()
    assert geplant == [150]


def test_log_geht_ueber_die_queue(fenster):
    fenster._log("Nachricht")
    assert fenster.message_queue.get_nowait() == ("log", "Nachricht")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_startet_und_beendet(monkeypatch):
    erzeugt: dict[str, tk.Tk] = {}

    class _FensterAttrappe:
        def __init__(self, root):
            root.withdraw()
            erzeugt["root"] = root

    monkeypatch.setattr(sf, "EinrichtungsFenster", _FensterAttrappe)
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self: None)

    try:
        assert sf.main() == 0
    finally:
        if "root" in erzeugt:
            erzeugt["root"].destroy()


def test_ps_zeichenkette_schuetzt_vor_variablen_auswertung():
    """Ein '$' im Pfad darf nicht als PowerShell-Variable ausgewertet werden.

    '$' ist in Windows-Dateinamen erlaubt. Stand der Pfad frueher in einer
    DOPPELT gefuehrten Zeichenkette im Skript, machte PowerShell aus
    'Ablage$2026' die leere Variable '$2026' -- die Verknuepfung zeigte
    dann auf einen Ort ohne diesen Namensteil. Einfach gefuehrte
    Zeichenketten werten nichts aus.
    """
    assert sf.ps_zeichenkette("C:/Daten/Ablage$2026") == "'C:/Daten/Ablage$2026'"


def test_ps_zeichenkette_verdoppelt_hochkommas():
    # In einer einfach gefuehrten Zeichenkette beendet ein Hochkomma sie --
    # O'Brien waere sonst ein Syntaxfehler. Verdoppelt ist es ein Zeichen.
    assert sf.ps_zeichenkette("C:/Nutzer/O'Brien") == "'C:/Nutzer/O''Brien'"


def test_verknuepfung_fuehrt_pfade_einfach_statt_doppelt(monkeypatch, tmp_path):
    befehle = []

    def fake_run(command, capture_output, text, timeout=None):
        befehle.append(command)
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    monkeypatch.setattr(sf, "IST_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    projektordner = tmp_path / "Ablage$2026"
    projektordner.mkdir()

    sf.create_desktop_shortcut(projektordner, lambda _m: None)

    # Der Befehl besteht weiterhin nur aus Schalter und Skript: Werte hinter
    # '-Command' landen NICHT in $args, sondern werden an den Befehlstext
    # angehaengt (nachgemessen: $args.Count ist dort 0).
    assert len(befehle[0]) == 5
    skript = befehle[0][4]
    assert "Ablage$2026" in skript
    assert f"'{projektordner}'" in skript
    assert f'"{projektordner}"' not in skript


def test_verknuepfung_hat_eine_zeitgrenze(monkeypatch, tmp_path):
    gesehen = {}

    def fake_run(command, capture_output, text, timeout=None):
        gesehen["timeout"] = timeout
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    monkeypatch.setattr(sf, "IST_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    sf.create_desktop_shortcut(tmp_path, lambda _m: None)

    assert gesehen["timeout"] == sf.POWERSHELL_TIMEOUT_SECONDS
