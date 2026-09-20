"""Tests fuer die Fensterklasse ``ProtokollGUI``.

Die Tests oeffnen ein echtes (verstecktes) Tk-Fenster. Modale Dialoge werden
nicht von Hand bedient, sondern ueber ``root.after`` ferngesteuert - sonst
wuerde ``wait_window`` den Test blockieren.
"""

from __future__ import annotations

import json
import queue
import tkinter as tk
from tkinter import ttk

import pytest

import protokoll_assistent_gui as gui


# --------------------------------------------------------------------------
# Hilfsmittel
# --------------------------------------------------------------------------
@pytest.fixture
def fenster(tk_wurzel, tmp_path, monkeypatch):
    """Ein fertig aufgebautes ProtokollGUI mit temporaeren Ordnern."""
    for name in ("INPUT_DIR", "OUTPUT_DIR", "CHECKPOINT_DIR", "SETTINGS_DIR", "ERGEBNIS_DIR"):
        monkeypatch.setattr(gui, name, tmp_path / name.lower())
    monkeypatch.setattr(gui, "APP_DIR", tmp_path)
    return gui.ProtokollGUI(tk_wurzel)


def _alle_kinder(widget):
    for kind in widget.winfo_children():
        yield kind
        yield from _alle_kinder(kind)


def _dialog_fernsteuern(root, eingaben=None, knopf="Uebernehmen"):
    """Fuellt im naechsten Toplevel die Eingabefelder und drueckt einen Knopf."""

    def handler():
        oben = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not oben:
            root.after(10, handler)
            return
        dialog = oben[-1]
        felder = [w for w in _alle_kinder(dialog) if isinstance(w, ttk.Entry)]
        if eingaben is not None:
            for feld, wert in zip(felder, eingaben, strict=False):
                feld.delete(0, "end")
                feld.insert(0, wert)
        for w in _alle_kinder(dialog):
            if isinstance(w, ttk.Button) and w.cget("text") == knopf:
                w.invoke()
                return
        dialog.destroy()

    root.after(10, handler)


class _SofortigesEreignis:
    """Ersatz fuer threading.Event: 'wait' kehrt sofort zurueck.

    Damit braucht kein Test einen zweiten Faden, nur um ein Ereignis zu setzen.
    Das ist nicht nur schneller, sondern auch sicher: Wird ein Tk-Objekt im
    Muell eines Nebenfadens eingesammelt, bricht Tcl den ganzen Prozess ab.
    """

    def __init__(self):
        self._gesetzt = False

    def clear(self):
        self._gesetzt = False

    def set(self):
        self._gesetzt = True

    def is_set(self):
        return self._gesetzt

    def wait(self, timeout=None):
        return True


@pytest.fixture
def stumme_dialoge(monkeypatch):
    """Faengt alle messagebox-Aufrufe ab und protokolliert sie."""
    aufrufe: list[tuple[str, str]] = []
    for name in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(
            gui.messagebox, name, lambda titel, text, _n=name: aufrufe.append((_n, titel))
        )
    return aufrufe


# --------------------------------------------------------------------------
# Aufbau
# --------------------------------------------------------------------------
def test_fenster_baut_sich_auf(fenster):
    assert fenster.root.title() == "Protokoll-Assistent"
    assert fenster.transkript_pfad is None
    assert fenster.audio_files == []
    assert fenster.systemprompt_text.get("1.0", "end").strip() == gui.DEFAULT_SYSTEMPROMPT


def test_fenster_legt_ordner_an(fenster):
    assert gui.OUTPUT_DIR.is_dir()
    assert gui.ERGEBNIS_DIR.is_dir()


# --------------------------------------------------------------------------
# Kleine Bedienelemente
# --------------------------------------------------------------------------
def test_theme_umschalten(fenster):
    fenster.dunkel_var.set(True)
    fenster._theme_umschalten()
    assert fenster.aktuelles_theme == "dark"

    fenster.dunkel_var.set(False)
    fenster._theme_umschalten()
    assert fenster.aktuelles_theme == "light"


def test_schluessel_sichtbarkeit_umschalten(fenster):
    fenster.show_key_var.set(True)
    fenster._toggle_key_visibility()
    assert fenster.api_key_entry.cget("show") == ""

    fenster.show_key_var.set(False)
    fenster._toggle_key_visibility()
    assert fenster.api_key_entry.cget("show") == "*"


def test_vorlage_uebernehmen(fenster):
    fenster.template_var.set("Agenda")
    fenster._apply_template()
    assert "Agenda" in fenster.systemprompt_text.get("1.0", "end")


def test_vorlage_unbekannt_aendert_nichts(fenster):
    vorher = fenster.systemprompt_text.get("1.0", "end")
    fenster.template_var.set("gibt es nicht")
    fenster._apply_template()
    assert fenster.systemprompt_text.get("1.0", "end") == vorher


def test_engine_wechsel_auf_api(fenster):
    fenster.engine_var.set("api")
    fenster.model_var.set(gui.DEFAULT_LOCAL_MODEL)
    fenster._engine_geaendert()

    assert fenster.model_var.get() == gui.DEFAULT_API_MODEL
    assert str(fenster.endpoint_entry.cget("state")) == "normal"
    assert "API-Endpunkt" in fenster.model_hinweis_var.get()


def test_engine_wechsel_auf_lokal(fenster):
    fenster.engine_var.set("lokal")
    fenster.model_var.set(gui.DEFAULT_API_MODEL)
    fenster._engine_geaendert()

    assert fenster.model_var.get() == gui.DEFAULT_LOCAL_MODEL
    assert str(fenster.endpoint_entry.cget("state")) == "disabled"
    assert "lokal" in fenster.model_hinweis_var.get()


def test_engine_wechsel_behaelt_eigenes_modell(fenster):
    fenster.engine_var.set("api")
    fenster.model_var.set("mein/eigenes-modell")
    fenster._engine_geaendert()
    assert fenster.model_var.get() == "mein/eigenes-modell"


# --------------------------------------------------------------------------
# Ordner- und Transkriptauswahl
# --------------------------------------------------------------------------
def test_ordner_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_k: "")
    fenster.choose_folder()
    assert fenster.selected_folder is None


def test_ordner_waehlen_mit_dateien(fenster, monkeypatch, tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    (ordner / "b.mp3").write_bytes(b"\x00")
    (ordner / "a.wav").write_bytes(b"\x00")
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_k: str(ordner))

    fenster.choose_folder()

    assert [p.name for p in fenster.audio_files] == ["a.wav", "b.mp3"]
    assert fenster.file_var.get() == "a.wav"
    assert fenster.folder_label_var.get() == str(ordner)


def test_ordner_waehlen_ohne_passende_dateien(fenster, monkeypatch, tmp_path):
    ordner = tmp_path / "leer"
    ordner.mkdir()
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_k: str(ordner))

    fenster.choose_folder()

    assert fenster.audio_files == []
    assert "keine unterstuetzte Datei" in fenster.folder_label_var.get()


def test_datei_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_k: "")
    fenster.choose_file()
    assert fenster.selected_folder is None


def test_datei_waehlen_setzt_ordner_und_datei(fenster, monkeypatch, tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    (ordner / "a.wav").write_bytes(b"\x00")
    gewaehlte_datei = ordner / "b.mp3"
    gewaehlte_datei.write_bytes(b"\x00")
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_k: str(gewaehlte_datei))

    fenster.choose_file()

    assert fenster.selected_folder == ordner
    assert [p.name for p in fenster.audio_files] == ["a.wav", "b.mp3"]
    assert fenster.file_var.get() == "b.mp3"
    assert fenster.folder_label_var.get() == str(ordner)


def test_datei_waehlen_datei_ausserhalb_der_ordner_erkennung(fenster, monkeypatch, tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    gewaehlte_datei = ordner / "unbekannt.xyz"
    gewaehlte_datei.write_bytes(b"\x00")
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_k: str(gewaehlte_datei))

    fenster.choose_file()

    assert fenster.file_var.get() == "unbekannt.xyz"
    assert gewaehlte_datei in fenster.audio_files


class _FakeDnDEvent:
    """Bildet ein echtes tkdnd-Drop-Event nach: tkdnd umschliesst jeden
    abgelegten Pfad in geschweifte Klammern, damit Tcl beim Zerlegen ueber
    'splitlist' Backslashes (Windows-Pfade!) nicht als Escape-Zeichen
    interpretiert. Ohne diese Klammern wuerde z. B. aus 'C:\\Temp' ein
    zerstoertes 'C:Temp'."""

    def __init__(self, data: str) -> None:
        self.data = "{" + data + "}" if data else data


def test_bei_datei_abgelegt_ordner(fenster, tmp_path):
    ordner = tmp_path / "abgelegt"
    ordner.mkdir()
    (ordner / "a.wav").write_bytes(b"\x00")

    fenster._bei_datei_abgelegt(_FakeDnDEvent(str(ordner)))

    assert fenster.selected_folder == ordner
    assert fenster.file_var.get() == "a.wav"


def test_bei_datei_abgelegt_datei(fenster, tmp_path):
    ordner = tmp_path / "abgelegt"
    ordner.mkdir()
    datei = ordner / "b.mp3"
    datei.write_bytes(b"\x00")

    fenster._bei_datei_abgelegt(_FakeDnDEvent(str(datei)))

    assert fenster.selected_folder == ordner
    assert fenster.file_var.get() == "b.mp3"


def test_bei_datei_abgelegt_ohne_pfad(fenster):
    fenster._bei_datei_abgelegt(_FakeDnDEvent(""))
    assert fenster.selected_folder is None


def test_transkript_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_k: "")
    fenster.waehle_transkript()
    assert fenster.transkript_pfad is None


def test_transkript_waehlen(fenster, monkeypatch, tmp_path):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_k: str(datei))

    fenster.waehle_transkript()

    assert fenster.transkript_pfad == datei
    assert fenster.transkript_label_var.get() == str(datei)


# --------------------------------------------------------------------------
# Sprecherdialog
# --------------------------------------------------------------------------
def test_sprecher_dialog_uebernehmen(fenster):
    _dialog_fernsteuern(fenster.root, eingaben=["Mueller", "Schmidt"])
    ergebnis = fenster._zeige_sprecher_dialog(
        {
            "Sprecher 1": {"beispiel": "Ich bin Mueller.", "vorschlag": "Mueller"},
            "Sprecher 2": {"beispiel": "Guten Tag.", "vorschlag": None},
        }
    )
    assert ergebnis == {"Sprecher 1": "Mueller", "Sprecher 2": "Schmidt"}


def test_sprecher_dialog_leere_felder_werden_verworfen(fenster):
    _dialog_fernsteuern(fenster.root, eingaben=["", "  "])
    ergebnis = fenster._zeige_sprecher_dialog(
        {
            "Sprecher 1": {"beispiel": "a", "vorschlag": None},
            "Sprecher 2": {"beispiel": "b", "vorschlag": None},
        }
    )
    assert ergebnis == {}


def test_sprecher_dialog_ueberspringen(fenster):
    _dialog_fernsteuern(fenster.root, eingaben=["Mueller"], knopf="Ueberspringen")
    ergebnis = fenster._zeige_sprecher_dialog(
        {"Sprecher 1": {"beispiel": "a", "vorschlag": "Mueller"}}
    )
    assert ergebnis == {}


def test_frage_sprecher_namen_geht_ueber_die_queue(fenster):
    # Die Methode ruft zuerst 'clear()' und wartet dann auf die Antwort aus dem
    # Tk-Hauptfaden. Statt einen echten Faden zu starten, wird hier nur das
    # Warten selbst ersetzt: Ein Timer-Faden koennte beim Aufraeumen ein
    # Tk-Objekt einsammeln, und Tcl stuerzt ab, wenn das nicht im Hauptfaden
    # passiert ("Tcl_AsyncDelete: async handler deleted by the wrong thread").
    fenster.sprecher_namen_ergebnis = {"Sprecher 1": "Mueller"}
    fenster.sprecher_dialog_event = _SofortigesEreignis()

    assert fenster._frage_sprecher_namen({}) == {"Sprecher 1": "Mueller"}
    assert fenster.message_queue.get_nowait()[0] == "sprecher_dialog"


# --------------------------------------------------------------------------
# sprecher_umbenennen
# --------------------------------------------------------------------------
def test_sprecher_umbenennen_ohne_transkript(fenster, stumme_dialoge):
    fenster.sprecher_umbenennen()
    assert ("showwarning", "Kein Transkript ausgewaehlt") in stumme_dialoge


def test_sprecher_umbenennen_ohne_json(fenster, stumme_dialoge, tmp_path):
    txt = tmp_path / "t.txt"
    txt.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = txt
    fenster.sprecher_umbenennen()
    assert ("showwarning", "Keine JSON-Datei gefunden") in stumme_dialoge


def test_sprecher_umbenennen_ohne_sprecher(fenster, stumme_dialoge, tmp_path):
    txt = tmp_path / "t.txt"
    txt.write_text("x", encoding="utf-8")
    (tmp_path / "t.json").write_text(
        json.dumps({"segmente": [{"sprecher": "Sprecher unbekannt", "inhalt": "Hi"}]}),
        encoding="utf-8",
    )
    fenster.transkript_pfad = txt
    fenster.sprecher_umbenennen()
    assert ("showinfo", "Keine Sprecher gefunden") in stumme_dialoge


def test_sprecher_umbenennen_schreibt_namen(fenster, stumme_dialoge, tmp_path):
    txt = tmp_path / "t.txt"
    js = tmp_path / "t.json"
    txt.write_text("Kopf\n\n[00:00:00.000 --> 00:00:01.000] Sprecher 1: Hallo\n", encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "segmente": [
                    {
                        "sprecher": "Sprecher 1",
                        "inhalt": "Hallo",
                        "start": "00:00:00.000",
                        "ende": "00:00:01.000",
                        "start_sekunden": 0,
                    }
                ],
                "woerter": [],
                "sprecher": [{"sprecher_id": "A", "bezeichnung": "Sprecher 1"}],
            }
        ),
        encoding="utf-8",
    )
    fenster.transkript_pfad = txt
    _dialog_fernsteuern(fenster.root, eingaben=["Mueller"])

    fenster.sprecher_umbenennen()

    assert "Mueller: Hallo" in txt.read_text(encoding="utf-8")
    assert ("showinfo", "Fertig") in stumme_dialoge


def test_sprecher_umbenennen_abgebrochen_aendert_nichts(fenster, stumme_dialoge, tmp_path):
    txt = tmp_path / "t.txt"
    js = tmp_path / "t.json"
    original = "Kopf\n\n[00:00:00.000 --> 00:00:01.000] Sprecher 1: Hallo\n"
    txt.write_text(original, encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "segmente": [{"sprecher": "Sprecher 1", "inhalt": "Hallo", "start_sekunden": 0}],
                "woerter": [],
                "sprecher": [],
            }
        ),
        encoding="utf-8",
    )
    fenster.transkript_pfad = txt
    _dialog_fernsteuern(fenster.root, knopf="Ueberspringen")

    fenster.sprecher_umbenennen()

    assert txt.read_text(encoding="utf-8") == original


# --------------------------------------------------------------------------
# start_transkription: Eingabepruefungen
# --------------------------------------------------------------------------
def test_start_transkription_ohne_datei(fenster, stumme_dialoge):
    fenster.start_transkription()
    assert ("showwarning", "Keine Datei ausgewaehlt") in stumme_dialoge


def test_start_transkription_ohne_schluessel(fenster, stumme_dialoge, tmp_path):
    fenster.audio_files = [tmp_path / "a.mp3"]
    fenster.file_var.set("a.mp3")
    fenster.api_key_var.set("")
    fenster.start_transkription()
    assert ("showwarning", "API-Schluessel fehlt") in stumme_dialoge


def test_start_transkription_ohne_endpunkt(fenster, stumme_dialoge, tmp_path):
    fenster.audio_files = [tmp_path / "a.mp3"]
    fenster.file_var.set("a.mp3")
    fenster.api_key_var.set("k")
    fenster.transkription_endpoint_var.set("")
    fenster.start_transkription()
    assert ("showwarning", "Angaben fehlen") in stumme_dialoge


def test_start_transkription_startet_arbeitsfaden(fenster, tmp_path, monkeypatch):
    fenster.audio_files = [tmp_path / "a.mp3"]
    fenster.selected_folder = tmp_path
    fenster.file_var.set("a.mp3")
    fenster.api_key_var.set("k")

    gestartet = {}
    monkeypatch.setattr(fenster, "_run_transkription", lambda *a: gestartet.setdefault("args", a))

    fenster.start_transkription()
    fenster.worker_thread.join(timeout=5)

    assert gestartet["args"][0] == tmp_path / "a.mp3"
    assert gestartet["args"][1] == "k"


def test_start_transkription_blockt_bei_laufendem_job(fenster, stumme_dialoge, monkeypatch):
    class _LebenderFaden:
        def is_alive(self):
            return True

    fenster.worker_thread = _LebenderFaden()
    fenster.start_transkription()
    assert stumme_dialoge == []


# --------------------------------------------------------------------------
# start_nachbearbeitung: Eingabepruefungen
# --------------------------------------------------------------------------
def test_start_nachbearbeitung_ohne_transkript(fenster, stumme_dialoge):
    fenster.start_nachbearbeitung()
    assert ("showwarning", "Kein Transkript ausgewaehlt") in stumme_dialoge


def test_start_nachbearbeitung_ohne_modell(fenster, stumme_dialoge, tmp_path):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = datei
    fenster.model_var.set("")
    fenster.start_nachbearbeitung()
    assert ("showwarning", "Modell fehlt") in stumme_dialoge


def test_start_nachbearbeitung_api_ohne_schluessel(fenster, stumme_dialoge, tmp_path):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = datei
    fenster.model_var.set("gpt")
    fenster.engine_var.set("api")
    fenster.api_key_var.set("")
    fenster.api_key_nachbearbeitung_var.set("")
    fenster.start_nachbearbeitung()
    assert ("showwarning", "API-Schluessel fehlt") in stumme_dialoge


def test_start_nachbearbeitung_api_ohne_endpunkt(fenster, stumme_dialoge, tmp_path):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = datei
    fenster.model_var.set("gpt")
    fenster.engine_var.set("api")
    fenster.api_key_nachbearbeitung_var.set("k")
    fenster.endpoint_var.set("")
    fenster.start_nachbearbeitung()
    assert ("showwarning", "API-Endpunkt fehlt") in stumme_dialoge


def test_start_nachbearbeitung_ohne_systemprompt(fenster, stumme_dialoge, tmp_path):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = datei
    fenster.model_var.set("llama3.1")
    fenster.engine_var.set("lokal")
    fenster.systemprompt_text.delete("1.0", "end")
    fenster.start_nachbearbeitung()
    assert ("showwarning", "Systemprompt fehlt") in stumme_dialoge


def test_start_nachbearbeitung_startet_arbeitsfaden(fenster, tmp_path, monkeypatch):
    datei = tmp_path / "t.txt"
    datei.write_text("x", encoding="utf-8")
    fenster.transkript_pfad = datei
    fenster.model_var.set("llama3.1")
    fenster.engine_var.set("lokal")

    gestartet = {}
    monkeypatch.setattr(
        fenster, "_run_nachbearbeitung", lambda *a: gestartet.setdefault("args", a)
    )

    fenster.start_nachbearbeitung()
    fenster.worker_thread.join(timeout=5)

    assert gestartet["args"][0] == datei
    assert gestartet["args"][1] == "lokal"


def test_start_nachbearbeitung_blockt_bei_laufendem_job(fenster, stumme_dialoge):
    class _LebenderFaden:
        def is_alive(self):
            return True

    fenster.worker_thread = _LebenderFaden()
    fenster.start_nachbearbeitung()
    assert stumme_dialoge == []


# --------------------------------------------------------------------------
# Queue-Hilfsmittel
# --------------------------------------------------------------------------
def test_log_und_progress_landen_in_der_queue(fenster):
    fenster._log("hallo")
    fenster._progress(0.5, "halb")
    assert fenster.message_queue.get_nowait() == ("log", "hallo")
    assert fenster.message_queue.get_nowait() == ("progress", (0.5, "halb"))


@pytest.mark.parametrize("antwort", [True, False])
def test_ask_confirmation(fenster, antwort):
    fenster.confirm_result = antwort
    fenster.confirm_event = _SofortigesEreignis()

    assert fenster._ask_confirmation("wirklich?") is antwort
    assert fenster.message_queue.get_nowait() == ("confirm", "wirklich?")


def test_set_text_widget_sperrt_wieder(fenster):
    fenster._set_text_widget(fenster.result_text, "Inhalt")
    assert fenster.result_text.get("1.0", "end").strip() == "Inhalt"
    assert str(fenster.result_text.cget("state")) == "disabled"


def test_append_log(fenster):
    fenster._append_log("zeile eins")
    fenster._append_log("zeile zwei")
    inhalt = fenster.log_text.get("1.0", "end")
    assert "zeile eins" in inhalt
    assert "zeile zwei" in inhalt


@pytest.mark.parametrize(("antwort", "erwartet"), [(True, True), (False, False)])
def test_show_confirm_dialog(fenster, monkeypatch, antwort, erwartet):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda _t, _n: antwort)
    fenster._show_confirm_dialog("wirklich?")
    assert fenster.confirm_result is erwartet
    assert fenster.confirm_event.is_set()


# --------------------------------------------------------------------------
# _poll_queue
# --------------------------------------------------------------------------
def test_poll_queue_verarbeitet_alle_nachrichtenarten(fenster, monkeypatch, tmp_path):
    fehler: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, text: fehler.append(text))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda _t, _n: True)
    monkeypatch.setattr(fenster.root, "after", lambda *_a, **_k: None)  # kein Nachplanen

    transkript = tmp_path / "fertig.txt"
    fenster.message_queue.put(("log", "eine Zeile"))
    fenster.message_queue.put(("progress", (0.4, "laeuft")))
    fenster.message_queue.put(("confirm", "ok?"))
    fenster.message_queue.put(("transkript_fertig", transkript))
    fenster.message_queue.put(("nachbearbeitung_ergebnis", ("Das Ergebnis", [transkript])))
    fenster.message_queue.put(("error", "kaputt"))
    fenster.message_queue.put(("job_fertig", None))

    fenster._poll_queue()

    assert "eine Zeile" in fenster.log_text.get("1.0", "end")
    assert fenster.progress_var.get() == pytest.approx(0.4)
    assert fenster.progress_label_var.get() == "laeuft"
    assert fenster.confirm_result is True
    assert fenster.transkript_pfad == transkript
    assert fenster.result_text.get("1.0", "end").strip() == "Das Ergebnis"
    assert fenster.last_output_paths == [transkript]
    assert fehler == ["kaputt"]
    assert str(fenster.start_button.cget("state")) == "normal"


def test_poll_queue_sprecherdialog(fenster, monkeypatch):
    monkeypatch.setattr(fenster.root, "after", lambda *_a, **_k: None)
    monkeypatch.setattr(fenster, "_zeige_sprecher_dialog", lambda e: {"Sprecher 1": "Mueller"})

    fenster.message_queue.put(("sprecher_dialog", {"Sprecher 1": {}}))
    fenster._poll_queue()

    assert fenster.sprecher_namen_ergebnis == {"Sprecher 1": "Mueller"}
    assert fenster.sprecher_dialog_event.is_set()


def test_poll_queue_plant_sich_neu(fenster, monkeypatch):
    geplant: list[int] = []
    monkeypatch.setattr(fenster.root, "after", lambda ms, _cb: geplant.append(ms))
    fenster._poll_queue()
    assert geplant == [100]


# --------------------------------------------------------------------------
# _run_transkription
# --------------------------------------------------------------------------
@pytest.fixture
def transkription_vorbereitet(fenster, monkeypatch, tmp_path):
    """Setzt Bestaetigung auf 'ja' und vermeidet echte FFmpeg-/Netzaufrufe."""
    monkeypatch.setattr(fenster, "_ask_confirmation", lambda _n: True)
    monkeypatch.setattr(gui, "ensure_ffmpeg_on_path", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(gui, "get_audio_duration_seconds", lambda _p: 60.0)
    monkeypatch.setattr(gui.kern, "prepare_audio", lambda q, d: (q, "mp3"))
    quelle = tmp_path / "sitzung.mp3"
    quelle.write_bytes(b"\x00")
    return quelle


def _queue_arten(q: queue.Queue) -> list[str]:
    arten = []
    while True:
        try:
            arten.append(q.get_nowait()[0])
        except queue.Empty:
            return arten


def test_run_transkription_abgelehnt_sendet_nichts(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(fenster, "_ask_confirmation", lambda _n: False)

    def darf_nicht(*_a, **_k):
        raise AssertionError("Es haette nichts gesendet werden duerfen.")

    monkeypatch.setattr(gui, "call_transcription_endpoint", darf_nicht)

    fenster._run_transkription(tmp_path / "a.mp3", "k", "https://e", "m", "azure", False)

    assert "job_fertig" in _queue_arten(fenster.message_queue)


def test_run_transkription_kurze_datei(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {
            "segments": [{"start": 0, "end": 5, "text": "Hallo", "speaker": "A"}]
        },
    )
    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    arten = _queue_arten(fenster.message_queue)
    assert "transkript_fertig" in arten
    assert "error" not in arten
    assert (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").exists()


def test_run_transkription_ohne_ffmpeg_meldet_hinweis(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(gui, "ensure_ffmpeg_on_path", lambda: None)
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}]},
    )
    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)
    assert "transkript_fertig" in _queue_arten(fenster.message_queue)


def test_run_transkription_nutzt_zwischenstand(fenster, transkription_vorbereitet, monkeypatch):
    zwischenstand = gui.CHECKPOINT_DIR / "sitzung_mai_transcribe_2_rohantwort.json"
    zwischenstand.parent.mkdir(parents=True, exist_ok=True)
    zwischenstand.write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": "gespeichert", "speaker": "A"}]}),
        encoding="utf-8",
    )

    def darf_nicht(*_a, **_k):
        raise AssertionError("Es haette kein Upload passieren duerfen.")

    monkeypatch.setattr(gui, "call_transcription_endpoint", darf_nicht)

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    assert "gespeichert" in (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").read_text("utf-8")
    assert not zwischenstand.exists()


def test_run_transkription_lange_aufnahme_wird_geteilt(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(gui, "get_audio_duration_seconds", lambda _p: 99999.0)
    monkeypatch.setattr(
        gui,
        "transcribe_in_chunks",
        lambda *a, **k: {
            "segmente": [
                {"start": "00:00:00.000", "ende": "00:00:01.000", "text": "Sprecher 1 (Teil 1): Hi"}
            ],
            "woerter": [],
            "sprecher": [],
            "dauer_sekunden": 1.0,
            "sprache": "de",
            "anzahl_abschnitte": 2,
        },
    )
    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    inhalt = (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").read_text("utf-8")
    assert "Aufgeteilt in 2 Abschnitte" in inhalt


def test_run_transkription_mit_sprecherbenennung(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {
            "segments": [{"start": 0, "end": 5, "text": "Ich bin Mueller.", "speaker": "A"}]
        },
    )
    monkeypatch.setattr(fenster, "_frage_sprecher_namen", lambda e: {"Sprecher 1": "Mueller"})

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", True)

    assert "Mueller:" in (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").read_text("utf-8")


def test_run_transkription_sprecherbenennung_uebersprungen(
    fenster, transkription_vorbereitet, monkeypatch
):
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {
            "segments": [{"start": 0, "end": 5, "text": "Hallo", "speaker": "A"}]
        },
    )
    monkeypatch.setattr(fenster, "_frage_sprecher_namen", lambda e: {})

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", True)

    assert "Sprecher 1:" in (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").read_text("utf-8")


def test_run_transkription_ohne_erkannte_sprecher(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {"segments": [{"start": 0, "end": 5, "text": "Hallo"}]},
    )

    def darf_nicht(_e):
        raise AssertionError("Ohne Sprecherlabels darf kein Dialog kommen.")

    monkeypatch.setattr(fenster, "_frage_sprecher_namen", darf_nicht)

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", True)
    assert "transkript_fertig" in _queue_arten(fenster.message_queue)


def test_run_transkription_meldet_fehler(fenster, transkription_vorbereitet, monkeypatch):
    def werfen(*_a, **_k):
        raise RuntimeError("Endpunkt kaputt")

    monkeypatch.setattr(gui, "call_transcription_endpoint", werfen)

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    assert "error" in _queue_arten(fenster.message_queue)


def test_run_transkription_abbruch_durch_benutzer(fenster, transkription_vorbereitet, monkeypatch):
    def werfen(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(gui, "call_transcription_endpoint", werfen)

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    arten = _queue_arten(fenster.message_queue)
    assert "error" not in arten
    assert "job_fertig" in arten


def test_run_transkription_ohne_erkannte_dauer(fenster, transkription_vorbereitet, monkeypatch):
    monkeypatch.setattr(gui, "get_audio_duration_seconds", lambda _p: None)
    monkeypatch.setattr(
        gui,
        "call_transcription_endpoint",
        lambda url, daten, key: {"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}]},
    )
    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)
    assert "transkript_fertig" in _queue_arten(fenster.message_queue)


# --------------------------------------------------------------------------
# _run_nachbearbeitung
# --------------------------------------------------------------------------
@pytest.fixture
def transkript_datei(tmp_path):
    datei = tmp_path / "sitzung_mai2_transkript.txt"
    datei.write_text("Das ist das Transkript.", encoding="utf-8")
    return datei


def test_run_nachbearbeitung_lokal(fenster, transkript_datei, monkeypatch):
    monkeypatch.setattr(gui, "call_local_model", lambda *a: "Die Zusammenfassung")

    fenster._run_nachbearbeitung(transkript_datei, "lokal", "llama3.1", "", "", "Fasse zusammen")

    arten = _queue_arten(fenster.message_queue)
    assert "nachbearbeitung_ergebnis" in arten
    assert (gui.ERGEBNIS_DIR / "sitzung_protokoll.txt").exists()


def test_run_nachbearbeitung_api_abgelehnt(fenster, transkript_datei, monkeypatch):
    monkeypatch.setattr(fenster, "_ask_confirmation", lambda _n: False)

    def darf_nicht(*_a, **_k):
        raise AssertionError("Es haette nichts gesendet werden duerfen.")

    monkeypatch.setattr(gui, "call_api_model", darf_nicht)

    fenster._run_nachbearbeitung(transkript_datei, "api", "gpt", "k", "https://e", "prompt")

    assert "nachbearbeitung_ergebnis" not in _queue_arten(fenster.message_queue)


def test_run_nachbearbeitung_api(fenster, transkript_datei, monkeypatch):
    monkeypatch.setattr(fenster, "_ask_confirmation", lambda _n: True)
    monkeypatch.setattr(gui, "call_api_model", lambda *a: "Antwort vom Dienst")

    fenster._run_nachbearbeitung(transkript_datei, "api", "gpt", "k", "https://e", "prompt")

    ergebnis = json.loads(
        (gui.ERGEBNIS_DIR / "sitzung_protokoll.json").read_text(encoding="utf-8")
    )
    assert ergebnis["verarbeitung"] == "api"
    assert ergebnis["endpunkt"] == "https://e"


def test_run_nachbearbeitung_meldet_fehler(fenster, transkript_datei, monkeypatch):
    def werfen(*_a, **_k):
        raise RuntimeError("Modell weg")

    monkeypatch.setattr(gui, "call_local_model", werfen)

    fenster._run_nachbearbeitung(transkript_datei, "lokal", "m", "", "", "prompt")

    assert "error" in _queue_arten(fenster.message_queue)


def test_run_nachbearbeitung_basisname_ohne_suffix(fenster, tmp_path, monkeypatch):
    datei = tmp_path / "eigener_name.txt"
    datei.write_text("Text", encoding="utf-8")
    monkeypatch.setattr(gui, "call_local_model", lambda *a: "Ergebnis")

    fenster._run_nachbearbeitung(datei, "lokal", "m", "", "", "prompt")

    assert (gui.ERGEBNIS_DIR / "eigener_name_protokoll.txt").exists()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_startet_und_beendet(monkeypatch, tmp_path):
    """'main' baut ein Fenster und laeuft bis zum Schliessen.

    'tk.Tk' selbst wird nicht ersetzt - sv-ttk prueft damit per 'isinstance',
    ob das Hauptfenster echt ist. Stattdessen wird nur 'mainloop' stillgelegt.
    """
    for name in ("INPUT_DIR", "OUTPUT_DIR", "CHECKPOINT_DIR", "SETTINGS_DIR", "ERGEBNIS_DIR"):
        monkeypatch.setattr(gui, name, tmp_path / name.lower())

    erzeugt: dict[str, tk.Tk] = {}

    class _FensterAttrappe:
        def __init__(self, root):
            root.withdraw()
            erzeugt["root"] = root

    monkeypatch.setattr(gui, "ProtokollGUI", _FensterAttrappe)
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self: None)

    try:
        assert gui.main() == 0
        assert isinstance(erzeugt["root"], tk.Tk)
    finally:
        if "root" in erzeugt:
            erzeugt["root"].destroy()


def test_zwischenstaende_werden_erst_nach_dem_speichern_geloescht(
    fenster, transkription_vorbereitet, monkeypatch
):
    # Gegenstueck zum Erhalt bei einem Fehler: Liegt das Transkript
    # wirklich auf der Platte, sind die Rohantworten entbehrlich.
    erledigt = gui.CHECKPOINT_DIR / "sitzung_teil01_rohantwort.json"
    erledigt.parent.mkdir(parents=True, exist_ok=True)
    erledigt.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(gui, "get_audio_duration_seconds", lambda _p: 99999.0)
    monkeypatch.setattr(
        gui,
        "transcribe_in_chunks",
        lambda *a, **k: {
            "segmente": [
                {"start": "00:00:00.000", "ende": "00:00:01.000", "text": "Sprecher 1 (Teil 1): Hi"}
            ],
            "woerter": [],
            "sprecher": [],
            "dauer_sekunden": 1.0,
            "sprache": "de",
            "anzahl_abschnitte": 1,
            "zwischenstaende": [erledigt],
        },
    )

    fenster._run_transkription(transkription_vorbereitet, "k", "https://e", "m", "azure", False)

    assert (gui.OUTPUT_DIR / "sitzung_mai2_transkript.txt").exists()
    assert not erledigt.exists()
