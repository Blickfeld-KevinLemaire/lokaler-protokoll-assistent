"""Tests fuer das Hauptfenster ('gui/main_window.py').

Es wird nie eine echte Verarbeitung gestartet: 'TranscriptionWorker' und
'ProtocolWorker' werden durch eine Attrappe ersetzt. 'secret_store' wird
durch einen In-Memory-Speicher ersetzt - kein Test spricht die echte
Windows-Anmeldeinformationsverwaltung oder ein echtes Netzwerk an."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar
from unittest import mock

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from protokoll_assistent.gui import main_window as mw  # noqa: E402
from protokoll_assistent.services import (  # noqa: E402
    api_protocol_service,
    api_transcription_service,
    export_service,
    manifest_service,
    model_service,
    ollama_service,
    recording_service,
    secret_store,
)
from protokoll_assistent.utils import app_config  # noqa: E402


class _WorkerAttrappe:
    """Sieht aus wie ein TranscriptionWorker/ProtocolWorker, startet aber nichts."""

    instanzen: ClassVar[list] = []

    def __init__(self, settings, parent=None, **kwargs):
        self.settings = settings
        self.kwargs = kwargs
        self.gestartet = False
        _WorkerAttrappe.instanzen.append(self)
        for name in (
            "stage_changed", "chunk_progress", "overall_progress", "preview_updated",
            "log_message", "finished_ok", "failed", "cancelled_signal", "finished",
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
def schluessel_speicher(monkeypatch):
    gespeichert: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: gespeichert.__setitem__(name, wert))
    monkeypatch.setattr(secret_store, "load_api_key", lambda name: gespeichert.get(name))
    monkeypatch.setattr(secret_store, "delete_api_key", lambda name: gespeichert.pop(name, None))
    return gespeichert


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

    monkeypatch.setattr(mw, "get_default_output_dir", lambda: ausgabe, raising=False)
    monkeypatch.setattr(mw, "get_recordings_dir", lambda: aufnahmen, raising=False)
    monkeypatch.setattr(mw, "get_work_dir", lambda: arbeit, raising=False)
    monkeypatch.setattr(mw, "get_system_prompt_file", lambda: prompt, raising=False)

    monkeypatch.setattr(model_service, "get_gpu_description", lambda: "Testhardware")
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: [])
    return {"ausgabe": ausgabe, "arbeit": arbeit, "aufnahmen": aufnahmen, "prompt": prompt, "konfig": konfig_datei}


@pytest.fixture
def fenster(qt_widgets, isolierte_konfiguration, schluessel_speicher, monkeypatch):
    _WorkerAttrappe.instanzen.clear()
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "ProtocolWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    # Die meisten Tests hier pruefen die Ablaufsteuerung, nicht ob auf DIESEM
    # Testrechner tatsaechlich 'faster_whisper' installiert ist (siehe
    # 'test_start_lokal_ohne_laufzeitumgebung_meldet_fehler' fuer den
    # Gegenfall) - deshalb hier standardmaessig "vorhanden" simulieren.
    monkeypatch.setattr(mw.MainWindow, "_lokale_laufzeitumgebung_verfuegbar", staticmethod(lambda: True))
    return qt_widgets(mw.MainWindow())


@pytest.fixture
def audio_datei(tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    datei = ordner / "sitzung.mp3"
    datei.write_bytes(b"\x00" * 64)
    return datei


@pytest.fixture
def gemeldete_fehler(monkeypatch):
    fehler: list[str] = []
    monkeypatch.setattr(mw, "show_error", lambda p, titel, text: fehler.append(titel))
    return fehler


# --------------------------------------------------------------------------
# Aufbau
# --------------------------------------------------------------------------
def test_fenster_baut_sich_auf(fenster):
    assert fenster.windowTitle() == "Protokoll-Assistent"
    assert fenster.hardware_label.text() == "Testhardware"
    assert fenster.start_button.isEnabled()
    assert fenster.protocol_start_button.isEnabled()


def test_datenschutzhinweis_ist_sichtbar(fenster):
    from protokoll_assistent.gui.strings import PRIVACY_NOTICE

    treffer = [k for k in fenster.findChildren(mw.QLabel) if k.text() == PRIVACY_NOTICE]
    assert treffer


def test_modus_lokal_ist_standard(fenster):
    assert fenster.transkription_lokal_radio.isChecked()
    assert fenster.nachbearbeitung_lokal_radio.isChecked()
    assert not fenster.transkription_datenschutz_hinweis.isVisible() or fenster.isHidden()


def test_datenschutzhinweis_erscheint_bei_api_modus(fenster):
    fenster.transkription_api_radio.setChecked(True)
    assert not fenster.transkription_datenschutz_hinweis.isHidden()
    fenster.transkription_lokal_radio.setChecked(True)
    assert fenster.transkription_datenschutz_hinweis.isHidden()


def test_modus_wechsel_wird_gespeichert(fenster):
    fenster.transkription_api_radio.setChecked(True)
    assert app_config.load_config()["transkription_modus"] == "api"

    fenster.nachbearbeitung_api_radio.setChecked(True)
    assert app_config.load_config()["nachbearbeitung_modus"] == "api"


# --------------------------------------------------------------------------
# Ordner- und Dateiauswahl (unveraendert gegenueber der lokalen Variante)
# --------------------------------------------------------------------------
def test_eingabeordner_waehlen(fenster, audio_datei, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(audio_datei.parent))
    )
    fenster._choose_input_folder()
    assert fenster._input_folder == audio_datei.parent
    assert fenster.file_list.count() == 1


def test_dateiauswahl_ohne_datei_loest_nichts_aus(fenster):
    assert fenster._source_path is None


def test_datei_ueber_dialog_waehlen(fenster, audio_datei, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(audio_datei), ""))
    )
    fenster._choose_file()
    assert fenster._source_path == audio_datei


class _FakeDropEvent:
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


def test_drop_datei_setzt_quelle_ohne_automatische_transkription(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei))
    fenster.dropEvent(event)
    assert fenster._source_path == audio_datei
    assert event.accepted
    assert _WorkerAttrappe.instanzen == []  # keine automatische Transkription


# --------------------------------------------------------------------------
# Mikrofonaufnahme
# --------------------------------------------------------------------------
def _geraet(name, hostapi_name="WASAPI"):
    return recording_service.Aufnahmegeraet(index=0, name=name, hostapi_name=hostapi_name, default_samplerate=16000.0)


class _FakeMikrofonAufnahme:
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


def test_aufnahme_start_beenden_uebergibt_datei_wie_dateiauswahl(fenster, monkeypatch):
    monkeypatch.setattr(recording_service, "MikrofonAufnahme", _FakeMikrofonAufnahme)
    geraet = _geraet("Headset-Mikrofon")
    fenster._recording_devices = [geraet]
    fenster.recording_device_combo.clear()
    fenster.recording_device_combo.addItem(geraet.anzeigename)

    fenster._start_recording()
    assert fenster._recording is not None
    assert fenster._recording.gestartet

    aufgenommene_datei = fenster._recording.zielpfad
    fenster._stop_recording()

    assert fenster._recording is None
    assert fenster._source_path == aufgenommene_datei


# --------------------------------------------------------------------------
# Transkript auswaehlen
# --------------------------------------------------------------------------
def test_transkript_ueber_dialog_waehlen(fenster, tmp_path, monkeypatch):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(transkript), "")))
    fenster._choose_transcript()
    assert fenster._selected_transcript_path == transkript


# --------------------------------------------------------------------------
# Systemprompt-Vorlagen (inline im Hauptfenster)
# --------------------------------------------------------------------------
def test_eingebaute_vorlagen_stehen_zur_auswahl(fenster):
    eintraege = [fenster.vorlage_combo.itemText(i) for i in range(fenster.vorlage_combo.count())]
    assert "Zusammenfassung" in eintraege
    assert "Agenda" in eintraege


def test_vorlage_anwenden_fuellt_editor(fenster):
    from protokoll_assistent.utils.systemprompt_vorlagen import EINGEBAUTE_VORLAGEN

    index = fenster.vorlage_combo.findData("Agenda")
    fenster.vorlage_combo.setCurrentIndex(index)
    assert fenster.systemprompt_editor.toPlainText() == EINGEBAUTE_VORLAGEN["Agenda"]


def test_neue_vorlage_speichern(fenster, monkeypatch, isolierte_konfiguration, tmp_path):
    vorlagen_ordner = tmp_path / "vorlagen"
    vorlagen_ordner.mkdir()
    from protokoll_assistent.utils import systemprompt_vorlagen as sv

    monkeypatch.setattr(sv, "get_systemprompt_vorlagen_dir", lambda: vorlagen_ordner)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Team-Standup", True)))

    fenster.systemprompt_editor.setPlainText("Eigener Text")
    fenster._neue_vorlage_speichern()

    assert (vorlagen_ordner / "Team-Standup.txt").read_text(encoding="utf-8") == "Eigener Text"
    assert fenster.vorlage_combo.currentData() == "Team-Standup"


def test_neue_vorlage_kann_eingebaute_nicht_ueberschreiben(fenster, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Agenda", True)))
    gewarnt = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: gewarnt.append(a)))
    fenster._neue_vorlage_speichern()
    assert gewarnt


# --------------------------------------------------------------------------
# Start der Transkription: Eingabepruefungen
# --------------------------------------------------------------------------
def test_start_ohne_datei(fenster, gemeldete_fehler):
    fenster._start_transcription()
    assert gemeldete_fehler == ["Keine Datei ausgewählt"]


def test_start_mit_verschwundener_datei(fenster, gemeldete_fehler, tmp_path):
    fenster._source_path = tmp_path / "weg.mp3"
    fenster._start_transcription()
    assert gemeldete_fehler == ["Datei nicht gefunden"]


def test_start_lokal_erzeugt_arbeiter_ohne_api_funktionen(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    assert arbeiter.settings.source_path == audio_datei
    assert arbeiter.kwargs["transcribe_chunk_fn"] is None
    assert arbeiter.kwargs["diarize_fn"] is None


def test_start_lokal_ohne_laufzeitumgebung_meldet_fehler(fenster, gemeldete_fehler, audio_datei, monkeypatch):
    # Wurde die Anwendung mit gespeichertem Modus "api" gestartet (oder mitten
    # in der Sitzung auf "Lokal" umgeschaltet), ohne dass 'bootstrap' die
    # schweren ML-Pakete eingerichtet hat, darf "Transkription starten" nicht
    # tief in der Pipeline mit einem kryptischen Fehler scheitern.
    monkeypatch.setattr(mw.MainWindow, "_lokale_laufzeitumgebung_verfuegbar", staticmethod(lambda: False))
    fenster._source_path = audio_datei

    fenster._start_transcription()

    assert gemeldete_fehler == ["Lokale Laufzeitumgebung noch nicht eingerichtet"]
    assert _WorkerAttrappe.instanzen == []


def test_start_api_ohne_schluessel_meldet_fehler(fenster, gemeldete_fehler, audio_datei):
    fenster._source_path = audio_datei
    fenster.transkription_api_radio.setChecked(True)

    fenster._start_transcription()

    assert gemeldete_fehler == ["Kein API-Schlüssel"]
    assert _WorkerAttrappe.instanzen == []


def test_start_api_mit_gemerktem_schluessel_erzeugt_arbeiter_mit_api_funktion(
    fenster, audio_datei, schluessel_speicher
):
    schluessel_speicher["transkription"] = "geheim-123"
    fenster._source_path = audio_datei
    fenster.transkription_api_radio.setChecked(True)

    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    transcribe_fn = arbeiter.kwargs["transcribe_chunk_fn"]
    assert transcribe_fn.func is api_transcription_service.transcribe_chunk_via_api
    assert transcribe_fn.keywords["api_key"] == "geheim-123"
    assert arbeiter.kwargs["diarize_fn"] is api_transcription_service.diarize_via_api_speakers


def test_start_api_mit_sitzungsschluessel_erzeugt_arbeiter(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster.transkription_api_radio.setChecked(True)
    fenster._session_api_keys["transkription"] = "nur-diese-sitzung"

    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.kwargs["transcribe_chunk_fn"].keywords["api_key"] == "nur-diese-sitzung"


def test_abbruch_transkription(fenster, audio_datei):
    fenster._source_path = audio_datei
    fenster._start_transcription()
    fenster._cancel_transcription()
    assert _WorkerAttrappe.instanzen[-1].abbruch_angefordert is True
    assert not fenster.cancel_button.isEnabled()


# --------------------------------------------------------------------------
# Start der Nachbearbeitung: Eingabepruefungen
# --------------------------------------------------------------------------
def test_nachbearbeitung_ohne_transkript(fenster, gemeldete_fehler):
    fenster._start_protocol()
    assert gemeldete_fehler == ["Kein Transkript ausgewählt"]


def test_nachbearbeitung_ohne_systemprompt_meldet_fehler(fenster, gemeldete_fehler, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("   ")

    fenster._start_protocol()

    assert gemeldete_fehler == ["Kein Systemprompt"]


def test_nachbearbeitung_lokal_erzeugt_arbeiter_ohne_generate_fn(fenster, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")

    fenster._start_protocol()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    assert arbeiter.kwargs["protocol_generate_fn"] is None
    assert arbeiter.settings.transcript_json_path == transkript


def test_nachbearbeitung_gibt_systemprompt_direkt_mit(fenster, tmp_path, isolierte_konfiguration):
    """Der Prompt reist ueber die Einstellungen, nicht ueber eine Datei."""
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Mein Prompt fuer diesen Lauf.")

    fenster._start_protocol()

    assert _WorkerAttrappe.instanzen[-1].settings.system_prompt == "Mein Prompt fuer diesen Lauf."


def test_nachbearbeitung_laesst_systemprompt_der_lokalen_anwendung_unberuehrt(
    fenster, tmp_path, isolierte_konfiguration
):
    """'get_system_prompt_file()' haelt den GESPEICHERTEN Systemprompt.
    Ein Text, der nur fuer diesen einen Lauf gilt, darf ihn nicht
    ueberschreiben - gelesen werden darf die Datei (Vorbelegung des
    Editors), geschrieben nicht."""
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Nur fuer diesen einen Lauf.")

    fenster._start_protocol()

    assert isolierte_konfiguration["prompt"].read_text(encoding="utf-8") == "Ein Prompt."


def test_nachbearbeitung_api_ohne_schluessel_meldet_fehler(fenster, gemeldete_fehler, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")
    fenster.nachbearbeitung_api_radio.setChecked(True)

    fenster._start_protocol()

    assert gemeldete_fehler == ["Kein API-Schlüssel"]


def _benutzter_api_schluessel(generate_fn, monkeypatch) -> str:
    """Welchen Schluessel reicht die uebergebene Funktion tatsaechlich an
    'api_protocol_service.generate_json' weiter?

    Bewusst ueber einen echten Aufruf geprueft und nicht ueber
    'functools.partial.keywords': Die Funktion ist eine Closure, weil sie
    zusaetzlich 'ApiProtocolError' in 'OllamaError' uebersetzen muss (siehe
    '_start_protocol'). Ein Test, der an der Verpackung haengt, geht bei
    jeder solchen Aenderung kaputt, obwohl das Verhalten stimmt."""
    notiert: dict[str, str] = {}

    def _aufzeichnen(prompt, system, *, model, endpoint_url, api_key):
        notiert["api_key"] = api_key
        return {}

    monkeypatch.setattr(api_protocol_service, "generate_json", _aufzeichnen)
    generate_fn("Prompt", "System")
    return notiert["api_key"]


def test_nachbearbeitung_api_faellt_ohne_eigenen_schluessel_auf_transkriptionsschluessel_zurueck(
    fenster, tmp_path, schluessel_speicher, monkeypatch
):
    schluessel_speicher["transkription"] = "gemeinsamer-schluessel"
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")
    fenster.nachbearbeitung_api_radio.setChecked(True)

    fenster._start_protocol()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    generate_fn = arbeiter.kwargs["protocol_generate_fn"]
    assert _benutzter_api_schluessel(generate_fn, monkeypatch) == "gemeinsamer-schluessel"


def test_nachbearbeitung_api_mit_eigenem_schluessel(fenster, tmp_path, schluessel_speicher, monkeypatch):
    schluessel_speicher["transkription"] = "transkriptions-schluessel"
    schluessel_speicher["nachbearbeitung"] = "eigener-schluessel"
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")
    fenster.nachbearbeitung_api_radio.setChecked(True)
    app_config.update_config(api_nachbearbeitung_eigener_schluessel=True)

    fenster._start_protocol()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    generate_fn = arbeiter.kwargs["protocol_generate_fn"]
    assert _benutzter_api_schluessel(generate_fn, monkeypatch) == "eigener-schluessel"


def test_abbruch_nachbearbeitung(fenster, tmp_path):
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")

    fenster._start_protocol()
    fenster._cancel_protocol()

    assert _WorkerAttrappe.instanzen[-1].abbruch_angefordert is True


# --------------------------------------------------------------------------
# Einstellungen oeffnen
# --------------------------------------------------------------------------
def test_einstellungen_oeffnen_und_akzeptieren_uebernimmt_modus(fenster, monkeypatch):
    class _FakeSettingsDialog:
        def __init__(self, parent=None):
            self.eingegebene_schluessel = {"transkription": "aus-dialog"}

        def exec(self):
            app_config.update_config(transkription_modus="api")
            return True

    monkeypatch.setattr(mw, "SettingsDialog", _FakeSettingsDialog)

    fenster._open_settings()

    assert fenster.transkription_api_radio.isChecked()
    assert fenster._session_api_keys["transkription"] == "aus-dialog"


def test_einstellungen_oeffnen_und_abbrechen_aendert_nichts(fenster, monkeypatch):
    class _FakeSettingsDialog:
        def __init__(self, parent=None):
            self.eingegebene_schluessel = {}

        def exec(self):
            return False

    monkeypatch.setattr(mw, "SettingsDialog", _FakeSettingsDialog)

    fenster._open_settings()

    assert fenster.transkription_lokal_radio.isChecked()


# --------------------------------------------------------------------------
# Fortschritt / Ergebnisbehandlung
# --------------------------------------------------------------------------
def test_stufe_transkription(fenster):
    fenster._on_transcription_stage_changed("transkription", "Chunk 1 wird transkribiert")
    assert fenster.status_label.text() == "Chunk 1 wird transkribiert"
    assert fenster.transcription_status_label.text() == "Chunk 1 wird transkribiert"


def test_chunk_fortschritt(fenster):
    fenster._on_chunk_progress(3, 7)
    assert fenster.chunk_progress_bar.value() == 3


def test_gesamtfortschritt(fenster):
    fenster._on_overall_progress(0.5)
    assert fenster.overall_progress_bar.value() == 50


def _transkript_ergebnis_bauen(tmp_path, eintraege):
    json_datei = tmp_path / "ergebnis.json"
    json_datei.write_text(json.dumps({"sprecher_zuordnung": eintraege}, ensure_ascii=False), encoding="utf-8")
    txt_datei = tmp_path / "ergebnis.txt"
    txt_datei.write_text("Transkripttext", encoding="utf-8")
    pfade = export_service.ExportPaths(txt=txt_datei, json=json_datei, srt=tmp_path / "a.srt", vtt=tmp_path / "a.vtt")

    class _Ergebnis:
        export_paths = pfade

    return _Ergebnis()


def test_transkription_erfolgreich_waehlt_transkript_automatisch(fenster, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    ergebnis = _transkript_ergebnis_bauen(tmp_path, [])

    fenster._on_transcription_finished_ok(ergebnis)

    assert fenster._selected_transcript_path == ergebnis.export_paths.json
    assert fenster.status_label.text() == "Transkription abgeschlossen."


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
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    ergebnis = _protokoll_ergebnis_bauen(tmp_path)
    fenster._on_protocol_finished_ok(ergebnis)
    assert fenster.status_label.text() == "Nachbearbeitung abgeschlossen."


def test_nachbearbeitung_fehlschlag(fenster, tmp_path, monkeypatch):
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warnungen.append(a)))
    ergebnis = _protokoll_ergebnis_bauen(tmp_path, protokoll_fehler="Ollama nicht erreichbar")
    fenster._on_protocol_finished_ok(ergebnis)
    assert warnungen
    assert "fehlgeschlagen" in fenster.status_label.text()


def test_transkription_fehlgeschlagen(fenster, gemeldete_fehler):
    fenster._on_transcription_failed("Modell nicht gefunden")
    assert fenster.status_label.text() == "Fehler bei der Transkription."
    assert gemeldete_fehler == ["Transkription fehlgeschlagen"]


def test_transkription_abgebrochen(fenster):
    fenster._on_transcription_cancelled()
    assert fenster.status_label.text() == "Transkription abgebrochen."


def test_nachbearbeitung_fehlgeschlagen(fenster, gemeldete_fehler):
    fenster._on_protocol_failed("Modell nicht gefunden")
    assert fenster.status_label.text() == "Fehler bei der Nachbearbeitung."
    assert gemeldete_fehler == ["Nachbearbeitung fehlgeschlagen"]


def test_nachbearbeitung_abgebrochen_meldung(fenster):
    fenster._on_protocol_cancelled()
    assert fenster.status_label.text() == "Nachbearbeitung abgebrochen."


def test_stufe_protokoll_fehlgeschlagen_setzt_tooltip(fenster):
    fenster._on_protocol_stage_changed("protokoll_fehlgeschlagen", "kaputt")
    assert fenster.protocol_status_label.toolTip() == "kaputt"


def test_protokollmeldung_landet_im_tooltip(fenster):
    fenster._on_log_message("Eine Meldung")
    assert fenster.status_label.toolTip() == "Eine Meldung"


# --------------------------------------------------------------------------
# Sprechertabelle
# --------------------------------------------------------------------------
def test_sprechertabelle_wird_gefuellt(fenster, tmp_path):
    ergebnis = _transkript_ergebnis_bauen(
        tmp_path,
        [{"sprecher_id": "SPEAKER_00", "anzahl_segmente": 12, "sprechdauer_sekunden": 90, "anzeigename": "Sprecher 1"}],
    )
    fenster._populate_speaker_table(ergebnis)
    assert fenster.speaker_table.rowCount() == 1
    assert fenster.speaker_table.item(0, 0).text() == "SPEAKER_00"
    assert fenster.apply_names_button.isEnabled()


def test_sprechertabelle_ohne_eintraege(fenster, tmp_path):
    fenster._populate_speaker_table(_transkript_ergebnis_bauen(tmp_path, []))
    assert fenster.speaker_table.rowCount() == 0
    assert not fenster.apply_names_button.isEnabled()


def test_namen_uebernehmen_ohne_ergebnis(fenster):
    fenster._last_transcription_result = None
    fenster._apply_speaker_names()  # darf nicht werfen


def test_namen_uebernehmen(fenster, tmp_path, monkeypatch):
    ergebnis = _transkript_ergebnis_bauen(
        tmp_path,
        [{"sprecher_id": "SPEAKER_00", "anzahl_segmente": 3, "sprechdauer_sekunden": 10, "anzeigename": "Sprecher 1"}],
    )
    fenster._last_transcription_result = ergebnis
    fenster._populate_speaker_table(ergebnis)
    fenster.speaker_table.item(0, 3).setText("  Mueller  ")

    uebergeben = {}
    neue_txt = tmp_path / "neu.txt"
    neue_txt.write_text("Neuer Text", encoding="utf-8")
    neue_pfade = export_service.ExportPaths(txt=neue_txt, json=tmp_path / "neu.json", srt=tmp_path / "n.srt", vtt=tmp_path / "n.vtt")

    def fake_reexport(json_pfad, overrides):
        uebergeben["overrides"] = overrides
        return neue_pfade

    monkeypatch.setattr(export_service, "reexport_with_new_names", fake_reexport)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))

    fenster._apply_speaker_names()

    assert uebergeben["overrides"] == {"SPEAKER_00": "Mueller"}
    assert fenster.preview_edit.toPlainText() == "Neuer Text"


def test_namen_uebernehmen_meldet_exportfehler(fenster, tmp_path, monkeypatch, gemeldete_fehler):
    ergebnis = _transkript_ergebnis_bauen(tmp_path, [])
    fenster._last_transcription_result = ergebnis

    def werfen(_j, _o):
        raise OSError("Platte voll")

    monkeypatch.setattr(export_service, "reexport_with_new_names", werfen)
    fenster._apply_speaker_names()
    assert gemeldete_fehler == ["Export fehlgeschlagen"]


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
    monkeypatch.setattr(manifest_service, "load_manifest", lambda work_dir: {"anzahl_chunks": 4})
    monkeypatch.setattr(
        manifest_service,
        "find_resumable_state",
        lambda manifest: {"vollstaendig": False, "fertige_chunks": [0, 1], "naechster_chunk": 2},
    )
    fenster._refresh_resume_status()
    assert "2 von 4 Chunks" in fenster.resume_status_label.text()


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


def test_spaetes_hash_ergebnis_ueberschreibt_die_anzeige_nicht(fenster, audio_datei):
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
    fenster._refresh_resume_status()

    def darf_nicht_aufgerufen_werden(_pfad, *args, **kwargs):
        raise AssertionError("Der Hash war bereits bekannt.")

    monkeypatch.setattr(manifest_service, "compute_file_hash", darf_nicht_aufgerufen_werden)
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(lambda url: None))
    fenster._open_intermediate_folder()  # darf nicht werfen


# --------------------------------------------------------------------------
# Ausgabeordner, Fenster schliessen, Zeitanzeigen
# --------------------------------------------------------------------------
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


def test_fenster_schliessen_beendet_laufende_aufnahme(fenster, monkeypatch):
    beendet = []

    class _Aufnahme:
        def stop(self):
            beendet.append(True)

    fenster._recording = _Aufnahme()
    from PySide6.QtGui import QCloseEvent

    fenster.closeEvent(QCloseEvent())
    assert beendet == [True]


def test_restzeit_ohne_chunks(fenster):
    fenster._chunk_progress = (0, 0)
    fenster._update_remaining_estimate(10.0)
    assert fenster.remaining_label.text() == "--"


def test_restzeit_wird_geschaetzt(fenster):
    fenster._chunk_progress = (2, 6)
    fenster._update_remaining_estimate(60.0)
    assert fenster.remaining_label.text() == "2:00"


def test_verstrichene_zeit_ohne_start(fenster):
    fenster._start_time = None
    fenster._update_elapsed_label()  # darf nicht werfen


def test_verstrichene_zeit(fenster):
    import time

    fenster._start_time = time.monotonic() - 65
    fenster._chunk_progress = (0, 0)
    fenster._update_elapsed_label()
    assert fenster.elapsed_label.text().startswith("1:0")


# --------------------------------------------------------------------------
# Aufnahmegeraete: weitere Faelle
# --------------------------------------------------------------------------
def test_aufnahme_ohne_geraete_deaktiviert_start_button(fenster):
    assert fenster._recording_devices == []
    assert "Keine Audioeingabegeräte" in fenster.recording_hint_label.text()
    assert not fenster.recording_start_button.isEnabled()


def test_aufnahmegeraete_werden_geladen_und_vorausgewaehlt(fenster, monkeypatch):
    geraete = [_geraet("ReSpeaker USB Mic Array"), _geraet("Headset-Mikrofon")]
    monkeypatch.setattr(recording_service, "liste_aufnahmegeraete", lambda: geraete)
    monkeypatch.setattr(recording_service, "standard_eingabe_index", lambda: None)

    fenster._populate_recording_devices()

    werte = [fenster.recording_device_combo.itemText(i) for i in range(fenster.recording_device_combo.count())]
    assert werte == ["ReSpeaker USB Mic Array (WASAPI)", "Headset-Mikrofon (WASAPI)"]
    assert fenster.recording_start_button.isEnabled()


def test_aufnahmegeraet_wechsel_wird_gespeichert(fenster, monkeypatch):
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


def test_aufnahme_pause_umschalten(fenster, monkeypatch):
    monkeypatch.setattr(recording_service, "MikrofonAufnahme", _FakeMikrofonAufnahme)
    geraet = _geraet("Headset-Mikrofon")
    fenster._recording_devices = [geraet]
    fenster.recording_device_combo.clear()
    fenster.recording_device_combo.addItem(geraet.anzeigename)
    fenster._start_recording()

    fenster._toggle_recording_pause()
    assert fenster._recording.ist_pausiert
    assert fenster.recording_pause_button.text() == "Fortsetzen"

    fenster._toggle_recording_pause()
    assert not fenster._recording.ist_pausiert
    assert fenster.recording_pause_button.text() == "Pause"

    fenster._update_recording_display()


def test_aufnahme_beenden_ohne_laufende_aufnahme_tut_nichts(fenster):
    fenster._stop_recording()
    assert fenster._recording is None


def test_aufnahme_pause_ohne_laufende_aufnahme_tut_nichts(fenster):
    fenster._toggle_recording_pause()
    assert fenster._recording is None


# --------------------------------------------------------------------------
# Datei-/Ordnerauswahl: weitere Faelle
# --------------------------------------------------------------------------
def test_eingabeordner_waehlen_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    vorher = fenster._input_folder
    fenster._choose_input_folder()
    assert fenster._input_folder == vorher


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
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(audio_datei.parent)))
    fenster._choose_input_folder()
    fenster._select_file_in_list("sitzung.mp3")
    fenster._on_file_list_selection_changed()
    assert fenster._source_path == audio_datei


def test_dateiauswahl_ohne_treffer_aendert_nichts(fenster):
    fenster._select_file_in_list("gibtesnicht.mp3")
    fenster._on_file_list_selection_changed()
    assert fenster._source_path is None


def test_datei_ueber_dialog_abgebrochen(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    fenster._choose_file()
    assert fenster._source_path is None


def test_drag_enter_akzeptiert_urls(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei))
    fenster.dragEnterEvent(event)
    assert event.accepted


def test_drag_enter_ohne_urls_wird_nicht_akzeptiert(fenster):
    event = _FakeDropEvent(QMimeData())
    fenster.dragEnterEvent(event)
    assert not event.accepted


def test_drop_ordner_setzt_eingabeordner(fenster, audio_datei):
    event = _FakeDropEvent(_mime_data_fuer(audio_datei.parent))
    fenster.dropEvent(event)
    assert fenster._input_folder == audio_datei.parent
    assert event.accepted


def test_fenster_uebernimmt_startordner(qt_widgets, isolierte_konfiguration, schluessel_speicher, audio_datei, monkeypatch):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    fenster = qt_widgets(mw.MainWindow(initial_folder=audio_datei.parent, initial_file="sitzung.mp3"))
    assert fenster._source_path == audio_datei
    assert "sitzung.mp3" in fenster.file_label.text()


def test_fenster_ignoriert_unbekannte_startdatei(qt_widgets, isolierte_konfiguration, schluessel_speicher, audio_datei, monkeypatch):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    monkeypatch.setattr(mw, "DateiHashWorker", _HashWorkerAttrappe)
    fenster = qt_widgets(mw.MainWindow(initial_folder=audio_datei.parent, initial_file="fehlt.mp3"))
    assert fenster._source_path is None


def test_fenster_liest_ordner_aus_konfiguration(qt_widgets, isolierte_konfiguration, schluessel_speicher, audio_datei, monkeypatch):
    monkeypatch.setattr(mw, "TranscriptionWorker", _WorkerAttrappe)
    app_config.save_config({**app_config.DEFAULTS, "eingabeordner": str(audio_datei.parent), "ausgabeordner": str(isolierte_konfiguration["ausgabe"])})
    fenster = qt_widgets(mw.MainWindow())
    assert fenster._input_folder == audio_datei.parent


# --------------------------------------------------------------------------
# Start der Anwendung: immer als Modul
# --------------------------------------------------------------------------
def test_neustart_startet_die_anwendung_als_modul():
    """'bootstrap._relaunch' darf die Anwendung nicht ueber einen Dateipfad
    starten.

    Ein Pfadstart ("python .../app.py") legt nur den Ordner der Datei in den
    Suchpfad -- kein einziger Paketimport waere dann aufloesbar, und der
    Start endete sofort mit 'ModuleNotFoundError'. Genau das ist frueher
    passiert, als Einstiegspunkt und Verarbeitungskette noch in getrennten
    Ordnern lagen."""
    from protokoll_assistent import bootstrap

    aufrufe = []
    with mock.patch.object(bootstrap.subprocess, "run") as lauf:
        lauf.return_value = mock.Mock(returncode=0)
        with pytest.raises(SystemExit):
            bootstrap._relaunch(Path("C:/irgendwo/python.exe"))
        aufrufe = lauf.call_args

    befehl = aufrufe.args[0]
    assert befehl[1:] == ["-m", "protokoll_assistent.app"]
    # Aus der Projektwurzel heraus, sonst ist das Paket nicht importierbar
    # (im Quellcode-Betrieb: eine Ebene ueber dem Paketordner selbst -- siehe
    # 'test_bootstrap.py' fuer die gebaute EXE, wo das anders ist).
    assert Path(aufrufe.kwargs["cwd"]) == Path(bootstrap.__file__).resolve().parent.parent


def test_anwendungsmodul_ist_aus_neutralem_verzeichnis_aufloesbar(tmp_path):
    """Gegenprobe in einem eigenen Prozess: Das Paket muss sich finden
    lassen, ohne dass das Arbeitsverzeichnis zufaellig die Projektwurzel
    ist."""
    wurzel = Path(mw.__file__).resolve().parent.parent.parent
    programm = (
        "import importlib.util, sys; "
        f"sys.path.insert(0, {str(wurzel)!r}); "
        "print(importlib.util.find_spec('protokoll_assistent.app') is not None)"
    )
    ergebnis = subprocess.run(
        [sys.executable, "-c", programm], cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False
    )

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip() == "True"


# --------------------------------------------------------------------------
# API-Schluessel: der Anmeldeinformationsspeicher darf fehlen
# --------------------------------------------------------------------------
def _keyring_fehlt(monkeypatch):
    def _nicht_verfuegbar(name):
        raise secret_store.SecretStoreUnavailableError("'keyring' ist nicht installiert.")

    monkeypatch.setattr(secret_store, "load_api_key", _nicht_verfuegbar)


def test_api_schluessel_faellt_ohne_keyring_auf_sitzungsschluessel_zurueck(fenster, monkeypatch):
    """Im lokalen Modus laeuft die Anwendung in der von 'bootstrap.py'
    verwalteten Umgebung, und die enthaelt 'keyring' nicht. Ein
    ungeschuetztes 'load_api_key' bricht dort ab - noch VOR dem Rueckgriff
    auf den eben eingetippten Sitzungsschluessel."""
    _keyring_fehlt(monkeypatch)
    fenster._session_api_keys["transkription"] = "nur-fuer-diese-sitzung"

    assert fenster._verwendbarer_api_schluessel("transkription") == "nur-fuer-diese-sitzung"


def test_api_schluessel_ohne_keyring_und_ohne_sitzungsschluessel_ist_none(fenster, monkeypatch):
    _keyring_fehlt(monkeypatch)

    assert fenster._verwendbarer_api_schluessel("transkription") is None


def test_transkription_startet_ohne_keyring_mit_sitzungsschluessel(fenster, audio_datei, monkeypatch):
    """Der ganze Weg: kein Anmeldeinformationsspeicher, Schluessel nur aus
    dem Einstellungsdialog - die Transkription muss trotzdem starten."""
    _keyring_fehlt(monkeypatch)
    fenster._source_path = audio_datei
    fenster.transkription_api_radio.setChecked(True)
    fenster._session_api_keys["transkription"] = "sitzungsschluessel"

    fenster._start_transcription()

    arbeiter = _WorkerAttrappe.instanzen[-1]
    assert arbeiter.gestartet is True
    assert arbeiter.kwargs["transcribe_chunk_fn"].keywords["api_key"] == "sitzungsschluessel"


# --------------------------------------------------------------------------
# Fehler des API-Modells muessen im gnaedigen Pfad landen
# --------------------------------------------------------------------------
def test_api_nachbearbeitungsfehler_wird_zu_ollama_error(fenster, tmp_path, schluessel_speicher, monkeypatch):
    """'pipeline_service.run_protocol' behandelt nur
    '(ProtocolValidationError, OllamaError)' gnaedig: Bericht schreiben,
    Transkript behalten, Fehler als 'protokoll_fehler' melden. Ein
    durchgereichter 'ApiProtocolError' (HTTP 401, Endpunkt nicht
    erreichbar, Zeitlimit) landet stattdessen als nichtssagender
    "Unerwarteter Fehler" im Worker."""
    schluessel_speicher["transkription"] = "schluessel"
    transkript = tmp_path / "ergebnis.json"
    transkript.write_text("{}", encoding="utf-8")
    fenster._set_transcript_path(transkript)
    fenster.systemprompt_editor.setPlainText("Fasse zusammen.")
    fenster.nachbearbeitung_api_radio.setChecked(True)

    fenster._start_protocol()
    generate_fn = _WorkerAttrappe.instanzen[-1].kwargs["protocol_generate_fn"]

    def _scheitert(prompt, system, *, model, endpoint_url, api_key):
        raise api_protocol_service.ApiProtocolError("HTTP 401: ungueltiger Schluessel")

    monkeypatch.setattr(api_protocol_service, "generate_json", _scheitert)

    with pytest.raises(ollama_service.OllamaError, match="401"):
        generate_fn("Prompt", "System")


# --------------------------------------------------------------------------
# Whisper-Modell und Offline-Modus
# --------------------------------------------------------------------------
def test_whisper_modell_nimmt_eigene_einstellung():
    assert mw.ermittle_whisper_modell({"whisper_modell": "small"}) == "small"


def test_whisper_modell_nimmt_ohne_einstellung_den_standard():
    """Es gibt nur noch EINE Konfiguration - der frueher noetige Rueckfall
    auf die Konfiguration einer zweiten Anwendung ist entfallen."""
    assert mw.ermittle_whisper_modell({"whisper_modell": None}) == model_service.WHISPER_MODEL_NAME
    assert mw.ermittle_whisper_modell({}) == model_service.WHISPER_MODEL_NAME


def test_offline_modus_ist_vorbelegt_und_verbietet_das_herunterladen(fenster, audio_datei):
    assert fenster.offline_checkbox.isChecked() is True

    fenster._source_path = audio_datei
    fenster._start_transcription()

    assert _WorkerAttrappe.instanzen[-1].settings.allow_download is False


def test_offline_modus_abgewaehlt_erlaubt_das_herunterladen(fenster, audio_datei):
    """Ohne diesen Schalter stand 'allow_download=False' fest im Code - ein
    noch nicht eingerichtetes Whisper-Modell konnte damit nie geladen
    werden, obwohl der Einstellungsdialog genau das zusagt."""
    fenster.offline_checkbox.setChecked(False)
    fenster._source_path = audio_datei

    fenster._start_transcription()

    assert _WorkerAttrappe.instanzen[-1].settings.allow_download is True


# --------------------------------------------------------------------------
# Mikrofonaufnahme darf fehlen
# --------------------------------------------------------------------------
def test_fehlendes_sounddevice_schaltet_nur_die_aufnahme_ab(fenster, monkeypatch):
    """'services.recording_service' importiert 'sounddevice' auf
    Modulebene; die von 'bootstrap.py' verwaltete Laufzeitumgebung enthaelt
    es nicht. Ein Import auf Modulebene haette dort das Oeffnen des
    Hauptfensters verhindert - wegen einer Zusatzfunktion, ohne die der
    Rest der Anwendung vollstaendig arbeitet."""

    def _fehlt():
        raise ImportError("No module named 'sounddevice'")

    monkeypatch.setattr(mw, "lade_recording_service", _fehlt)

    fenster._populate_recording_devices()

    assert fenster._recording_devices == []
    assert fenster.recording_start_button.isEnabled() is False
    assert "sounddevice" in fenster.recording_hint_label.text()
