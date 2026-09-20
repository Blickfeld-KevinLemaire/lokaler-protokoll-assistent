"""Tests fuer das Hauptfenster der lokalen Anwendung (``gui/main_window.py``).

Es wird nie eine echte Verarbeitung gestartet: ``TranscriptionWorker`` und
``ProtocolWorker`` werden durch eine Attrappe ersetzt, die nichts tut.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from gui import main_window as mw  # noqa: E402
from services import export_service, manifest_service, model_service, recording_service  # noqa: E402
from utils import app_config, paths  # noqa: E402


class _WorkerAttrappe:
    """Sieht aus wie ein TranscriptionWorker/ProtocolWorker, startet aber nichts.

    Beide echten Klassen senden nur eine Teilmenge dieser Signale (ein
    ProtocolWorker kennt z. B. kein 'chunk_progress') - die Attrappe bietet
    einfach alle an, das schadet nicht.
    """

    instanzen: ClassVar[list] = []

    def __init__(self, settings, parent=None):
        self.settings = settings
        self.cancelled = False
        self.gestartet = False
        _WorkerAttrappe.instanzen.append(self)
        for name in (
            "stage_changed",
            "chunk_progress",
            "overall_progress",
            "preview_updated",
            "log_message",
            "finished_ok",
            "failed",
            "cancelled_signal",
            "finished",
        ):
            setattr(self, name, _Signal())
        self.cancelled = _Signal()

    def start(self):
        self.gestartet = True

    def request_cancel(self):
        self.abbruch_angefordert = True


class _Signal:
    def __init__(self):
        self.empfaenger = []

    def connect(self, funktion):
        self.empfaenger.append(funktion)

    def emit(self, *args):
        for funktion in self.empfaenger:
            funktion(*args)


class _HashWorkerAttrappe:
    """Wie DateiHashWorker, aber ohne Nebenfaden.

    Die Fenstertests kommen bewusst ohne echte Threads aus (siehe
    CLAUDE.md). Der Hash wird deshalb sofort in 'start()' berechnet und
    das Ergebnis direkt gemeldet.
    """

    def __init__(self, pfad, parent=None):
        self._pfad = pfad
        self.fertig = _Signal()
        self.fehlgeschlagen = _Signal()

    def start(self):
        try:
            hashwert = manifest_service.compute_file_hash(self._pfad)
        except OSError as fehler:
            self.fehlgeschlagen.emit(str(self._pfad), str(fehler))
            return
        self.fertig.emit(str(self._pfad), hashwert)


@pytest.fixture
def isolierte_konfiguration(tmp_path, monkeypatch):
    """Konfiguration, Arbeits- und Ausgabeordner liegen im Temp-Verzeichnis."""
    konfig_datei = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: konfig_datei)

    ausgabe = tmp_path / "ausgabe"
    arbeit = tmp_path / "arbeitsdaten"
    aufnahmen = tmp_path / "mikrofon_aufnahmen"
    prompt = tmp_path / "systemprompt_protokoll.txt"
    prompt.write_text("Ein Prompt.", encoding="utf-8")
    for ordner in (ausgabe, arbeit, aufnahmen):
        ordner.mkdir()

    for modul in (mw, paths):
        monkeypatch.setattr(modul, "get_default_output_dir", lambda: ausgabe, raising=False)
        monkeypatch.setattr(modul, "get_work_dir", lambda: arbeit, raising=False)
        monkeypatch.setattr(modul, "get_system_prompt_file", lambda: prompt, raising=False)
        monkeypatch.setattr(modul, "get_recordings_dir", lambda: aufnahmen, raising=False)

    # Keine echte Hardware-Abfrage.
    monkeypatch.setattr(model_service, "get_gpu_description", lambda: "Testhardware")
    # Keine echte Audiogeraete-Abfrage - Tests, die konkrete Geraete brauchen,
    # patchen 'recording_service.liste_aufnahmegeraete' selbst um und rufen
    # 'fenster._populate_recording_devices()' danach erneut auf.
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: [])
    return {
        "ausgabe": ausgabe,
        "arbeit": arbeit,
        "aufnahmen": aufnahmen,
        "prompt": prompt,
        "konfig": konfig_datei,
    }


@pytest.fixture
def fenster(qt_widgets, isolierte_konfiguration, monkeypatch):
    _WorkerAttrappe.instanzen.clear()
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "ProtocolWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    return qt_widgets(mw.MainWindow())


@pytest.fixture
def audio_datei(tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    datei = ordner / "sitzung.mp3"
    datei.write_bytes(b"\x00" * 64)
    return datei


# --------------------------------------------------------------------------
# Aufbau
# --------------------------------------------------------------------------
def test_fenster_baut_sich_auf(fenster):
    assert fenster.windowTitle() == "Protokoll-Assistent Lokal"
    assert fenster.hardware_label.text() == "Testhardware"
    assert fenster.start_button.isEnabled()
    assert fenster.protocol_start_button.isEnabled()


def test_datenschutzhinweis_ist_sichtbar(fenster):
    from gui.strings import PRIVACY_NOTICE

    treffer = [
        kind
        for kind in fenster.findChildren(mw.QLabel)
        if kind.text() == PRIVACY_NOTICE
    ]
    assert treffer, "Der Datenschutzhinweis muss im Fenster stehen."


def test_fenster_uebernimmt_startordner(qt_widgets, isolierte_konfiguration, audio_datei, monkeypatch):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "ProtocolWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    fenster = qt_widgets(mw.MainWindow(initial_folder=audio_datei.parent, initial_file="sitzung.mp3"))

    assert fenster._source_path == audio_datei
    assert "sitzung.mp3" in fenster.file_label.text()


def test_fenster_ignoriert_unbekannte_startdatei(
    qt_widgets, isolierte_konfiguration, audio_datei, monkeypatch
):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    fenster = qt_widgets(mw.MainWindow(initial_folder=audio_datei.parent, initial_file="fehlt.mp3"))
    assert fenster._source_path is None


def test_fenster_liest_ordner_aus_konfiguration(
    qt_widgets, isolierte_konfiguration, audio_datei, monkeypatch
):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    app_config.save_config(
        {
            "eingabeordner": str(audio_datei.parent),
            "ausgabeordner": str(isolierte_konfiguration["ausgabe"]),
        }
    )
    fenster = qt_widgets(mw.MainWindow())
    assert fenster._input_folder == audio_datei.parent


def test_fenster_ignoriert_ungueltigen_ordner_aus_konfiguration(
    qt_widgets, isolierte_konfiguration, tmp_path, monkeypatch
):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    app_config.save_config({"eingabeordner": str(tmp_path / "gibtesnicht")})
    fenster = qt_widgets(mw.MainWindow())
    assert fenster._input_folder is None


# --------------------------------------------------------------------------
# Modellwahl und Bedienelemente
# --------------------------------------------------------------------------
def test_whisper_modell_hinweis_wird_gesetzt(fenster):
    fenster._update_whisper_model_hint()
    assert isinstance(fenster.whisper_model_hint_label.text(), str)


def test_whisper_modell_empfehlung_ohne_konfiguration(
    qt_widgets, isolierte_konfiguration, monkeypatch
):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    from utils import diagnostics

    class _Ergebnis:
        def __init__(self, extra):
            self.extra = extra

    monkeypatch.setattr(diagnostics, "check_gpu_vram", lambda: _Ergebnis({"vram_gb": 8}))
    monkeypatch.setattr(diagnostics, "check_ram", lambda: _Ergebnis({"ram_gb": 32}))

    fenster = qt_widgets(mw.MainWindow())
    assert fenster.whisper_model_combo.currentData()


def test_sprecheranzahl_umschalten(fenster):
    fenster._toggle_speaker_limits(True)
    assert fenster.min_speakers_spin.isEnabled()
    fenster._toggle_speaker_limits(False)
    assert not fenster.min_speakers_spin.isEnabled()


# --------------------------------------------------------------------------
# Ordner- und Dateiauswahl
# --------------------------------------------------------------------------
def test_eingabeordner_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    vorher = fenster._input_folder
    fenster._choose_input_folder()
    assert fenster._input_folder == vorher


def test_eingabeordner_waehlen(fenster, audio_datei, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(audio_datei.parent))
    )
    fenster._choose_input_folder()

    assert fenster._input_folder == audio_datei.parent
    assert fenster.file_list.count() == 1
    assert fenster.file_list.item(0).text() == "sitzung.mp3"


def test_dateiliste_ignoriert_fremde_endungen(fenster, tmp_path):
    ordner = tmp_path / "gemischt"
    ordner.mkdir()
    (ordner / "a.mp3").write_bytes(b"\x00")
    (ordner / "notiz.txt").write_text("x", encoding="utf-8")

    fenster._populate_file_list(ordner)

    assert [fenster.file_list.item(i).text() for i in range(fenster.file_list.count())] == ["a.mp3"]


def test_dateiliste_bei_unlesbarem_ordner(fenster, tmp_path):
    fenster._populate_file_list(tmp_path / "gibtesnicht")
    assert fenster.file_list.count() == 0


def test_dateiauswahl_in_der_liste(fenster, audio_datei, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(audio_datei.parent))
    )
    fenster._choose_input_folder()
    fenster._select_file_in_list("sitzung.mp3")
    fenster._on_file_list_selection_changed()

    assert fenster._source_path == audio_datei


def test_dateiauswahl_ohne_treffer_aendert_nichts(fenster):
    fenster._select_file_in_list("gibtesnicht.mp3")
    fenster._on_file_list_selection_changed()
    assert fenster._source_path is None


def test_datei_ueber_dialog_waehlen(fenster, audio_datei, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(audio_datei), ""))
    )
    fenster._choose_file()
    assert fenster._source_path == audio_datei


def test_datei_ueber_dialog_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    fenster._choose_file()
    assert fenster._source_path is None


class _FakeDropEvent:
    """Sieht wie ein ``QDropEvent``/``QDragEnterEvent`` aus, ohne echte Drag-Session."""

    def __init__(self, mime_data):
        self._mime_data = mime_data
        self.accepted = False

    def mimeData(self):
        return self._mime_data

    def acceptProposedAction(self):
        self.accepted = True


def _mime_data_fuer(pfad):
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(pfad))])
    return mime_data


def test_drag_enter_akzeptiert_urls(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei))
    fenster.dragEnterEvent(event)
    assert event.accepted


def test_drag_enter_ohne_urls_wird_nicht_akzeptiert(fenster):
    event = _FakeDropEvent(QMimeData())
    fenster.dragEnterEvent(event)
    assert not event.accepted


def test_drop_datei_setzt_quelle(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei))
    fenster.dropEvent(event)
    assert fenster._source_path == audio_datei
    assert event.accepted


def test_drop_ordner_setzt_eingabeordner(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei.parent))
    fenster.dropEvent(event)
    assert fenster._input_folder == audio_datei.parent
    assert fenster.file_list.count() == 1
    assert event.accepted


# --------------------------------------------------------------------------
# Mikrofonaufnahme (Voice Recording)
# --------------------------------------------------------------------------
def _geraet(name, hostapi_name="WASAPI"):
    return recording_service.Aufnahmegeraet(
        index=0, name=name, hostapi_name=hostapi_name, default_samplerate=16000.0
    )


class _FakeMikrofonAufnahme:
    """Ersetzt die echte Aufnahme - kein Geraet, kein Thread, keine Queue."""

    def __init__(self, geraet, zielpfad, stream_klasse=None):
        self.geraet = geraet
        self.zielpfad = zielpfad
        self.gestartet = False
        self._pausiert = False
        self._dauer = 0.0
        self._pegel = 0.0

    def start(self):
        self.gestartet = True
        self.zielpfad.write_bytes(b"RIFF....WAVEfmt ")

    def pause(self):
        self._pausiert = True

    def fortsetzen(self):
        self._pausiert = False

    @property
    def ist_pausiert(self):
        return self._pausiert

    @property
    def dauer_sekunden(self):
        return self._dauer

    @property
    def pegel(self):
        return self._pegel

    def stop(self):
        return self.zielpfad


def test_aufnahmegeraete_werden_geladen_und_vorausgewaehlt(fenster, monkeypatch):
    geraete = [_geraet("ReSpeaker USB Mic Array"), _geraet("Headset-Mikrofon")]
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: geraete)
    monkeypatch.setattr(recording_service, "standard_eingabe_index", lambda: None)

    fenster._populate_recording_devices()

    werte = [fenster.recording_device_combo.itemText(i) for i in range(fenster.recording_device_combo.count())]
    assert werte == ["ReSpeaker USB Mic Array (WASAPI)", "Headset-Mikrofon (WASAPI)"]
    assert fenster.recording_device_combo.currentText() == "ReSpeaker USB Mic Array (WASAPI)"
    assert fenster.recording_hint_label.text() == ""
    assert fenster.recording_start_button.isEnabled()


def test_aufnahme_ohne_geraete_deaktiviert_start_button(fenster):
    assert fenster._recording_devices == []
    assert "Keine Audioeingabegeräte" in fenster.recording_hint_label.text()
    assert not fenster.recording_start_button.isEnabled()


def test_aufnahmegeraet_faellt_auf_gespeichertes_zurueck_wenn_verfuegbar(fenster, monkeypatch):
    monkeypatch.setattr(mw, "load_config", lambda: {"aufnahmegeraet": "Headset-Mikrofon (WASAPI)"})
    geraete = [_geraet("ReSpeaker USB Mic Array"), _geraet("Headset-Mikrofon")]
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: geraete)
    monkeypatch.setattr(recording_service, "standard_eingabe_index", lambda: None)

    fenster._populate_recording_devices()

    assert fenster.recording_device_combo.currentText() == "Headset-Mikrofon (WASAPI)"
    assert fenster.recording_hint_label.text() == ""


def test_aufnahmegeraet_wechsel_wird_gespeichert(fenster, monkeypatch, isolierte_konfiguration):
    geraete = [_geraet("ReSpeaker USB Mic Array"), _geraet("Headset-Mikrofon")]
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: geraete)
    monkeypatch.setattr(recording_service, "standard_eingabe_index", lambda: None)
    fenster._populate_recording_devices()

    fenster.recording_device_combo.setCurrentIndex(1)

    assert app_config.load_config()["aufnahmegeraet"] == "Headset-Mikrofon (WASAPI)"


def test_aufnahme_starten_ohne_geraet_zeigt_fehler(fenster, monkeypatch):
    fehler = []
    monkeypatch.setattr(mw, "show_error", lambda *a: fehler.append(a))
    fenster._recording_devices = []

    fenster._start_recording()

    assert fehler
    assert fenster._recording is None


def test_aufnahme_start_pause_beenden_uebergibt_datei_wie_dateiauswahl(fenster, monkeypatch):
    monkeypatch.setattr(recording_service, "MikrofonAufnahme", _FakeMikrofonAufnahme)
    geraet = _geraet("Headset-Mikrofon")
    fenster._recording_devices = [geraet]
    fenster.recording_device_combo.clear()
    fenster.recording_device_combo.addItem(geraet.anzeigename)

    fenster._start_recording()

    assert fenster._recording is not None
    assert fenster._recording.gestartet
    # Das Fenster wird im Test nie tatsaechlich angezeigt - 'isVisible()'
    # waere deshalb immer False. 'isHidden()' spiegelt dagegen den
    # ausdruecklich per hide()/show() gesetzten Zustand des Widgets selbst.
    assert fenster.recording_start_button.isHidden()
    assert not fenster.recording_pause_button.isHidden()
    assert not fenster.recording_stop_button.isHidden()
    assert fenster.recording_status_label.text() == "🔴 Aufnahme läuft"
    assert not fenster.recording_device_combo.isEnabled()

    fenster._toggle_recording_pause()
    assert fenster._recording.ist_pausiert
    assert fenster.recording_pause_button.text() == "Fortsetzen"
    assert fenster.recording_status_label.text() == "⏸ Aufnahme pausiert"

    fenster._toggle_recording_pause()
    assert not fenster._recording.ist_pausiert
    assert fenster.recording_pause_button.text() == "Pause"

    aufgenommene_datei = fenster._recording.zielpfad
    fenster._stop_recording()

    assert fenster._recording is None
    assert fenster.recording_device_combo.isEnabled()
    assert not fenster.recording_start_button.isHidden()
    assert fenster.recording_pause_button.isHidden()
    assert fenster.recording_stop_button.isHidden()
    # Genau der Mechanismus, der auch beim direkten Dateidialog greift:
    assert fenster._source_path == aufgenommene_datei
    assert fenster.file_label.text() == f"Ausgewählt: {aufgenommene_datei.name}"


def test_aufnahme_beenden_ohne_laufende_aufnahme_tut_nichts(fenster):
    fenster._stop_recording()
    assert fenster._recording is None


def test_aufnahme_pause_ohne_laufende_aufnahme_tut_nichts(fenster):
    fenster._toggle_recording_pause()
    assert fenster._recording is None


def test_ausgabeordner_waehlen(fenster, tmp_path, monkeypatch):
    ziel = tmp_path / "neue_ausgabe"
    ziel.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(ziel)))

    fenster._choose_output_dir()

    assert fenster._output_dir == ziel
    assert fenster.output_label.text() == str(ziel)


def test_ausgabeordner_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    vorher = fenster._output_dir
    fenster._choose_output_dir()
    assert fenster._output_dir == vorher


# --------------------------------------------------------------------------
# Fortsetzen-Status
# --------------------------------------------------------------------------
def test_fortsetzen_ohne_datei(fenster):
    fenster._refresh_resume_status()  # darf nicht werfen


def test_fortsetzen_ohne_manifest(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster._refresh_resume_status()
    assert "Keine vorherige Verarbeitung" in fenster.resume_status_label.text()


def test_fortsetzen_mit_unvollstaendigem_manifest(fenster, audio_datei, monkeypatch):
    fenster._source_path = audio_datei
    monkeypatch.setattr(
        manifest_service, "load_manifest", lambda work_dir: {"anzahl_chunks": 4}
    )
    monkeypatch.setattr(
        manifest_service,
        "find_resumable_state",
        lambda manifest: {"vollstaendig": False, "fertige_chunks": [0, 1], "naechster_chunk": 2},
    )

    fenster._refresh_resume_status()

    assert "2 von 4 Chunks" in fenster.resume_status_label.text()
    assert "Nächster Chunk: 3" in fenster.resume_status_label.text()


def test_fortsetzen_mit_vollstaendigem_manifest(fenster, audio_datei, monkeypatch):
    fenster._source_path = audio_datei
    monkeypatch.setattr(manifest_service, "load_manifest", lambda work_dir: {"anzahl_chunks": 2})
    monkeypatch.setattr(
        manifest_service,
        "find_resumable_state",
        lambda manifest: {"vollstaendig": True, "fertige_chunks": [0, 1], "naechster_chunk": None},
    )

    fenster._refresh_resume_status()

    assert "bereits vollständig verarbeitet" in fenster.resume_status_label.text()


def test_fortsetzen_meldet_lesefehler(fenster, audio_datei, monkeypatch):
    fenster._source_path = audio_datei

    def werfen(_pfad):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(manifest_service, "compute_file_hash", werfen)
    fenster._refresh_resume_status()

    assert "nicht gelesen werden" in fenster.resume_status_label.text()


def test_zwischenordner_ohne_datei_meldet_fehler(fenster, monkeypatch):
    fehler = []
    monkeypatch.setattr(mw, "show_error", lambda p, t, m: fehler.append(t))
    fenster._open_intermediate_folder()
    assert fehler == ["Keine Datei ausgewählt"]


def test_zwischenordner_oeffnen(fenster, audio_datei, monkeypatch):
    fenster._source_path = audio_datei
    geoeffnet = []
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(geoeffnet.append))

    fenster._open_intermediate_folder()

    assert len(geoeffnet) == 1


# --------------------------------------------------------------------------
# Dialoge
# --------------------------------------------------------------------------
def test_systemprompt_dialog_wird_geoeffnet(fenster, monkeypatch):
    geoeffnet = []
    monkeypatch.setattr(mw.SystemPromptDialog, "exec", lambda self: geoeffnet.append(True))
    fenster._edit_system_prompt()
    assert geoeffnet == [True]


def test_diagnose_dialog_wird_geoeffnet(fenster, monkeypatch):
    monkeypatch.setattr(mw.DiagnosticsDialog, "exec", lambda self: None)
    monkeypatch.setattr(
        "gui.dialogs.DiagnosticsRunner.start", lambda self: None
    )
    fenster._open_diagnostics()  # darf nicht werfen


# --------------------------------------------------------------------------
# Transkript auswaehlen (Eingang der Nachbearbeitung)
# --------------------------------------------------------------------------
def test_transkript_ueber_dialog_waehlen(fenster, tmp_path, monkeypatch):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(transkript), ""))
    )
    fenster._choose_transcript()
    assert fenster._selected_transcript_path == transkript
    assert "ergebnis.json" in fenster.transcript_label.text()


def test_transkript_ueber_dialog_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    fenster._choose_transcript()
    assert fenster._selected_transcript_path is None


# --------------------------------------------------------------------------
# Start der Transkription: Eingabepruefungen
# --------------------------------------------------------------------------
@pytest.fixture
def gemeldete_fehler(monkeypatch):
    fehler: list[str] = []
    monkeypatch.setattr(mw, "show_error", lambda p, titel, text: fehler.append(titel))
    return fehler


def test_start_ohne_datei(fenster, gemeldete_fehler):
    fenster._start_transcription()
    assert gemeldete_fehler == ["Keine Datei ausgewählt"]


def test_start_mit_verschwundener_datei(fenster, gemeldete_fehler, tmp_path):
    fenster._source_path = tmp_path / "weg.mp3"
    fenster._start_transcription()
    assert gemeldete_fehler == ["Datei nicht gefunden"]


def test_start_mit_leerer_datei(fenster, gemeldete_fehler, tmp_path):
    leer = tmp_path / "leer.mp3"
    leer.write_bytes(b"")
    fenster._source_path = leer
    fenster._start_transcription()
    assert gemeldete_fehler == ["Datei ist leer"]


def test_start_mit_unbeschreibbarem_ausgabeordner(
    fenster, gemeldete_fehler, audio_datei, tmp_path
):
    # Eine Datei dort, wo ein Ordner sein muesste -> mkdir scheitert.
    blockade = tmp_path / "blockiert"
    blockade.write_text("belegt", encoding="utf-8")
    fenster._source_path = audio_datei
    fenster._output_dir = blockade / "unterordner"

    fenster._start_transcription()

    assert gemeldete_fehler == ["Ausgabeordner ungültig"]


def test_start_transkription_braucht_keinen_systemprompt(
    fenster, gemeldete_fehler, audio_datei, isolierte_konfiguration
):
    # Der Systemprompt wird erst fuer die Nachbearbeitung gebraucht - die
    # Transkription laeuft auch ohne ihn.
    isolierte_konfiguration["prompt"].unlink()
    fenster._source_path = audio_datei

    fenster._start_transcription()

    assert gemeldete_fehler == []
    assert _WorkerAttrappe.instanzen[-1].gestartet is True


def test_start_erzeugt_arbeiter_mit_einstellungen(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster.limit_speakers_checkbox.setChecked(True)
    fenster.min_speakers_spin.setValue(2)
    fenster.max_speakers_spin.setValue(5)
    fenster.offline_checkbox.setChecked(True)

    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    assert arbeiter.settings.source_path == audio_datei
    assert arbeiter.settings.min_speakers == 2
    assert arbeiter.settings.max_speakers == 5
    assert arbeiter.settings.allow_download is False
    assert not fenster.start_button.isEnabled()
    assert fenster.cancel_button.isEnabled()


def test_start_ohne_sprecherbegrenzung(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster.limit_speakers_checkbox.setChecked(False)

    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.settings.min_speakers is None
    assert arbeiter.settings.max_speakers is None


def test_abbruch(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster._start_transcription()

    fenster._cancel_transcription()

    assert _WorkerAttrappe.instanzen[-1].abbruch_angefordert is True
    assert "Abbruch angefordert" in fenster.status_label.text()
    assert not fenster.cancel_button.isEnabled()


def test_abbruch_ohne_laufenden_arbeiter(fenster):
    fenster._cancel_transcription()  # darf nicht werfen


# --------------------------------------------------------------------------
# Start der Nachbearbeitung: Eingabepruefungen
# --------------------------------------------------------------------------
def test_nachbearbeitung_ohne_transkript(fenster, gemeldete_fehler):
    fenster._start_protocol()
    assert gemeldete_fehler == ["Kein Transkript ausgewählt"]


def test_nachbearbeitung_mit_verschwundenem_transkript(fenster, gemeldete_fehler, tmp_path):
    fenster._selected_transcript_path = tmp_path / "weg.json"
    fenster._start_protocol()
    assert gemeldete_fehler == ["Transkript nicht gefunden"]


def test_nachbearbeitung_ohne_systemprompt(
    fenster, gemeldete_fehler, tmp_path, isolierte_konfiguration
):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    isolierte_konfiguration["prompt"].unlink()

    fenster._start_protocol()

    assert gemeldete_fehler == ["Systemprompt fehlt"]


def test_nachbearbeitung_erzeugt_arbeiter_mit_einstellungen(fenster, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)

    fenster._start_protocol()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    assert arbeiter.settings.transcript_json_path == transkript
    assert not fenster.protocol_start_button.isEnabled()
    assert not fenster.start_button.isEnabled()  # geteilte Anzeige -- kein Parallellauf
    assert fenster.protocol_cancel_button.isEnabled()


def test_nachbearbeitung_abbruch(fenster, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster._start_protocol()

    fenster._cancel_protocol()

    assert _WorkerAttrappe.instanzen[-1].abbruch_angefordert is True
    assert not fenster.protocol_cancel_button.isEnabled()


def test_nachbearbeitung_abbruch_ohne_laufenden_arbeiter(fenster):
    fenster._cancel_protocol()  # darf nicht werfen


# --------------------------------------------------------------------------
# Fortschrittsanzeigen
# --------------------------------------------------------------------------
def test_stufe_transkription(fenster):
    fenster._on_transcription_stage_changed("transkription", "Chunk 1 wird transkribiert")
    assert fenster.status_label.text() == "Chunk 1 wird transkribiert"
    assert fenster.transcription_status_label.text() == "Chunk 1 wird transkribiert"


def test_stufe_transkription_abgeschlossen(fenster):
    fenster._on_transcription_stage_changed("abgeschlossen", "fertig")
    assert fenster.transcription_status_label.text() == "fertig"


def test_stufe_protokoll(fenster):
    fenster._on_protocol_stage_changed("protokoll_auswertung", "Protokoll wird erstellt")
    assert fenster.protocol_status_label.text() == "Protokoll wird erstellt"


def test_stufe_protokoll_fehlgeschlagen_setzt_tooltip(fenster):
    fenster._on_protocol_stage_changed("protokoll_fehlgeschlagen", "kaputt")
    assert fenster.protocol_status_label.text() == "kaputt"
    assert fenster.protocol_status_label.toolTip() == "kaputt"


def test_chunk_fortschritt(fenster):
    fenster._on_chunk_progress(3, 7)
    assert fenster.chunk_progress_bar.value() == 3
    assert fenster.chunk_progress_bar.maximum() == 7
    assert "Chunk 3 von 7" in fenster.chunk_progress_bar.format()


def test_gesamtfortschritt(fenster):
    fenster._on_overall_progress(0.42)
    assert fenster.overall_progress_bar.value() == 42


def test_protokollmeldung_landet_im_tooltip(fenster):
    fenster._on_log_message("Eine Meldung")
    assert fenster.status_label.toolTip() == "Eine Meldung"


def test_restzeit_ohne_chunks(fenster):
    fenster._chunk_progress = (0, 0)
    fenster._update_remaining_estimate(10.0)
    assert fenster.remaining_label.text() == "--"


def test_restzeit_wird_geschaetzt(fenster):
    fenster._chunk_progress = (2, 6)
    fenster._update_remaining_estimate(60.0)
    # 30 s pro Chunk, 4 Chunks offen -> 2 Minuten
    assert fenster.remaining_label.text() == "2:00"


def test_verstrichene_zeit_ohne_start(fenster):
    fenster._start_time = None
    fenster._update_elapsed_label()  # darf nicht werfen


def test_verstrichene_zeit(fenster, monkeypatch):
    import time

    fenster._start_time = time.monotonic() - 65
    fenster._chunk_progress = (0, 0)
    fenster._update_elapsed_label()
    assert fenster.elapsed_label.text().startswith("1:0")


# --------------------------------------------------------------------------
# Ergebnisbehandlung: Transkription
# --------------------------------------------------------------------------
def _transkript_ergebnis_bauen(tmp_path, eintraege):
    json_datei = tmp_path / "ergebnis.json"
    json_datei.write_text(
        json.dumps({"sprecher_zuordnung": eintraege}, ensure_ascii=False), encoding="utf-8"
    )
    txt_datei = tmp_path / "ergebnis.txt"
    txt_datei.write_text("Transkripttext", encoding="utf-8")

    pfade = export_service.ExportPaths(
        txt=txt_datei, json=json_datei, srt=tmp_path / "a.srt", vtt=tmp_path / "a.vtt"
    )

    class _Ergebnis:
        export_paths = pfade

    return _Ergebnis()


def test_sprechertabelle_wird_gefuellt(fenster, tmp_path):
    ergebnis = _transkript_ergebnis_bauen(
        tmp_path,
        [
            {
                "sprecher_id": "SPEAKER_00",
                "anzahl_segmente": 12,
                "sprechdauer_sekunden": 90,
                "anzeigename": "Sprecher 1",
            }
        ],
    )

    fenster._populate_speaker_table(ergebnis)

    assert fenster.speaker_table.rowCount() == 1
    assert fenster.speaker_table.item(0, 0).text() == "SPEAKER_00"
    assert fenster.speaker_table.item(0, 1).text() == "12"
    assert fenster.speaker_table.item(0, 2).text() == "1:30"
    assert fenster.apply_names_button.isEnabled()


def test_sprechertabelle_ohne_eintraege(fenster, tmp_path):
    fenster._populate_speaker_table(_transkript_ergebnis_bauen(tmp_path, []))
    assert fenster.speaker_table.rowCount() == 0
    assert not fenster.apply_names_button.isEnabled()


def test_transkription_erfolgreich(fenster, tmp_path, monkeypatch):
    infos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: infos.append(a)))
    ergebnis = _transkript_ergebnis_bauen(tmp_path, [])

    fenster._on_transcription_finished_ok(ergebnis)

    assert fenster.status_label.text() == "Transkription abgeschlossen."
    assert fenster._last_transcription_result is ergebnis
    # Das Transkript wird automatisch als Eingang der Nachbearbeitung
    # vorausgewaehlt - genau der Punkt der ganzen Umstellung.
    assert fenster._selected_transcript_path == ergebnis.export_paths.json
    assert "ergebnis.json" in fenster.transcript_label.text()
    assert infos


def test_transkription_fehlgeschlagen(fenster, gemeldete_fehler):
    fenster._on_transcription_failed("Modell nicht gefunden")
    assert fenster.status_label.text() == "Fehler bei der Transkription."
    assert gemeldete_fehler == ["Transkription fehlgeschlagen"]


def test_transkription_abgebrochen(fenster):
    fenster._on_transcription_cancelled()
    assert fenster.status_label.text() == "Transkription abgebrochen."


# --------------------------------------------------------------------------
# Sprechernamen uebernehmen
# --------------------------------------------------------------------------
def test_namen_uebernehmen_ohne_ergebnis(fenster):
    fenster._last_transcription_result = None
    fenster._apply_speaker_names()  # darf nicht werfen


def test_namen_uebernehmen(fenster, tmp_path, monkeypatch):
    ergebnis = _transkript_ergebnis_bauen(
        tmp_path,
        [
            {
                "sprecher_id": "SPEAKER_00",
                "anzahl_segmente": 3,
                "sprechdauer_sekunden": 10,
                "anzeigename": "Sprecher 1",
            }
        ],
    )
    fenster._last_transcription_result = ergebnis
    fenster._populate_speaker_table(ergebnis)
    fenster.speaker_table.item(0, 3).setText("  Mueller  ")

    uebergeben = {}
    neue_txt = tmp_path / "neu.txt"
    neue_txt.write_text("Neuer Text", encoding="utf-8")
    neue_pfade = export_service.ExportPaths(
        txt=neue_txt, json=tmp_path / "neu.json", srt=tmp_path / "n.srt", vtt=tmp_path / "n.vtt"
    )

    def fake_reexport(json_pfad, overrides):
        uebergeben["overrides"] = overrides
        return neue_pfade

    monkeypatch.setattr(export_service, "reexport_with_new_names", fake_reexport)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))

    fenster._apply_speaker_names()

    assert uebergeben["overrides"] == {"SPEAKER_00": "Mueller"}
    assert fenster.preview_edit.toPlainText() == "Neuer Text"


def test_namen_uebernehmen_ueberspringt_leere_namen(fenster, tmp_path, monkeypatch):
    ergebnis = _transkript_ergebnis_bauen(
        tmp_path,
        [
            {
                "sprecher_id": "SPEAKER_00",
                "anzahl_segmente": 1,
                "sprechdauer_sekunden": 1,
                "anzeigename": "",
            }
        ],
    )
    fenster._last_transcription_result = ergebnis
    fenster._populate_speaker_table(ergebnis)

    uebergeben = {}
    neue_txt = tmp_path / "neu.txt"
    neue_txt.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        export_service,
        "reexport_with_new_names",
        lambda j, o: uebergeben.setdefault("overrides", o)
        or export_service.ExportPaths(
            txt=neue_txt, json=j, srt=neue_txt, vtt=neue_txt
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))

    fenster._apply_speaker_names()

    assert uebergeben["overrides"] == {}


def test_namen_uebernehmen_meldet_exportfehler(fenster, tmp_path, monkeypatch, gemeldete_fehler):
    ergebnis = _transkript_ergebnis_bauen(tmp_path, [])
    fenster._last_transcription_result = ergebnis

    def werfen(_j, _o):
        raise OSError("Platte voll")

    monkeypatch.setattr(export_service, "reexport_with_new_names", werfen)

    fenster._apply_speaker_names()

    assert gemeldete_fehler == ["Export fehlgeschlagen"]


# --------------------------------------------------------------------------
# Ergebnisbehandlung: Nachbearbeitung
# --------------------------------------------------------------------------
def _protokoll_ergebnis_bauen(tmp_path, protokoll_fehler=None):
    protokoll_pfade = None
    if protokoll_fehler is None:
        protokoll_txt = tmp_path / "protokoll.txt"
        protokoll_txt.write_text("Protokolltext", encoding="utf-8")
        protokoll_pfade = (protokoll_txt, tmp_path / "protokoll.json")

    class _Ergebnis:
        work_dir = tmp_path
        protocol_paths = protokoll_pfade
        report_paths = (tmp_path / "bericht.txt", tmp_path / "bericht.json")

    _Ergebnis.protokoll_fehler = protokoll_fehler
    return _Ergebnis()


def test_nachbearbeitung_erfolgreich(fenster, tmp_path, monkeypatch):
    infos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: infos.append(a)))
    ergebnis = _protokoll_ergebnis_bauen(tmp_path)

    fenster._on_protocol_finished_ok(ergebnis)

    assert fenster.status_label.text() == "Nachbearbeitung abgeschlossen."
    assert fenster._last_protocol_result is ergebnis
    assert infos


def test_nachbearbeitung_meldet_fehlschlag(fenster, tmp_path, monkeypatch):
    warnungen = []
    infos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warnungen.append(a)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: infos.append(a)))
    ergebnis = _protokoll_ergebnis_bauen(tmp_path, protokoll_fehler="Ollama ist nicht erreichbar")

    fenster._on_protocol_finished_ok(ergebnis)

    assert warnungen, "Es haette gewarnt werden muessen."
    assert not infos, "Ein Erfolgsfenster waere hier irrefuehrend."
    assert "Ollama ist nicht erreichbar" in warnungen[0][2]
    assert "fehlgeschlagen" in fenster.status_label.text()
    assert fenster._last_protocol_result is ergebnis


def test_nachbearbeitung_fehlgeschlagen(fenster, gemeldete_fehler):
    fenster._on_protocol_failed("Modell nicht gefunden")
    assert fenster.status_label.text() == "Fehler bei der Nachbearbeitung."
    assert gemeldete_fehler == ["Nachbearbeitung fehlgeschlagen"]


def test_nachbearbeitung_abgebrochen_meldung(fenster):
    fenster._on_protocol_cancelled()
    assert fenster.status_label.text() == "Nachbearbeitung abgebrochen."


# --------------------------------------------------------------------------
# Dateihash laeuft im Hintergrund
# --------------------------------------------------------------------------
def test_hash_wird_je_datei_nur_einmal_berechnet(fenster, audio_datei, monkeypatch):
    # Bei mehrstuendigen Aufnahmen kostet SHA-256 Sekunden. Wer in der
    # Liste hin- und herklickt, darf das nicht jedes Mal bezahlen.
    aufrufe = []
    echte_funktion = manifest_service.compute_file_hash

    def zaehlend(pfad, *args, **kwargs):
        aufrufe.append(pfad)
        return echte_funktion(pfad, *args, **kwargs)

    monkeypatch.setattr(manifest_service, "compute_file_hash", zaehlend)
    fenster._source_path = audio_datei

    fenster._refresh_resume_status()
    fenster._refresh_resume_status()
    fenster._refresh_resume_status()

    assert len(aufrufe) == 1


def test_geaenderte_datei_wird_neu_gehasht(fenster, audio_datei, monkeypatch):
    aufrufe = []
    echte_funktion = manifest_service.compute_file_hash

    def zaehlend(pfad, *args, **kwargs):
        aufrufe.append(pfad)
        return echte_funktion(pfad, *args, **kwargs)

    monkeypatch.setattr(manifest_service, "compute_file_hash", zaehlend)
    fenster._source_path = audio_datei
    fenster._refresh_resume_status()

    # Andere Groesse -> der gemerkte Wert gilt nicht mehr.
    audio_datei.write_bytes(b"\x01" * 128)
    fenster._refresh_resume_status()

    assert len(aufrufe) == 2


def test_spaetes_hash_ergebnis_ueberschreibt_die_anzeige_nicht(fenster, audio_datei):
    # Waehrend der Berechnung kann laengst eine andere Datei gewaehlt sein.
    fenster._source_path = audio_datei
    fenster.resume_status_label.setText("Anzeige der neuen Datei")

    fenster._zeige_fortsetzbarkeit(str(audio_datei.parent / "andere.mp3"), "egal")

    assert fenster.resume_status_label.text() == "Anzeige der neuen Datei"


def test_spaeter_hash_fehler_ueberschreibt_die_anzeige_nicht(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster.resume_status_label.setText("Anzeige der neuen Datei")

    fenster._hash_fehlgeschlagen(str(audio_datei.parent / "andere.mp3"), "Zugriff verweigert")

    assert fenster.resume_status_label.text() == "Anzeige der neuen Datei"


def test_zwischenordner_nutzt_den_gemerkten_hash(fenster, audio_datei, monkeypatch):
    fenster._source_path = audio_datei
    fenster._refresh_resume_status()  # fuellt den Zwischenspeicher

    def darf_nicht_aufgerufen_werden(_pfad, *args, **kwargs):
        raise AssertionError("Der Hash war bereits bekannt.")

    monkeypatch.setattr(manifest_service, "compute_file_hash", darf_nicht_aufgerufen_werden)
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(lambda url: None))

    fenster._open_intermediate_folder()  # darf nicht werfen


def test_hash_arbeiter_meldet_ergebnis(qt_app, audio_datei):
    # Die echte Klasse -- 'run()' wird direkt aufgerufen, damit in einem
    # Fenstertest kein zusaetzlicher Faden laeuft (siehe CLAUDE.md).
    from gui.worker import DateiHashWorker

    ergebnisse = []
    arbeiter = DateiHashWorker(audio_datei)
    arbeiter.fertig.connect(lambda pfad, wert: ergebnisse.append((pfad, wert)))

    arbeiter.run()

    assert ergebnisse == [(str(audio_datei), manifest_service.compute_file_hash(audio_datei))]


def test_hash_arbeiter_meldet_lesefehler(qt_app, tmp_path):
    from gui.worker import DateiHashWorker

    fehler = []
    arbeiter = DateiHashWorker(tmp_path / "gibtesnicht.mp3")
    arbeiter.fehlgeschlagen.connect(lambda pfad, text: fehler.append(text))

    arbeiter.run()

    assert len(fehler) == 1
