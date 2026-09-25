"""Hauptfenster des Protokoll-Assistenten (PySide6).

Eine Oberflaeche fuer beide Wege: Datei/Aufnahme auswaehlen (Gruppe 1/2,
loest noch nichts aus), dann getrennt Transkription starten (Gruppe 5,
lokal ODER API-Schnittstelle - Umschalter direkt hier), dann getrennt
Nachbearbeitung eines - auch eines anderen, ausgewaehlten - Transkripts
(Gruppe 7, ebenfalls lokal ODER API umschaltbar, mit Systemprompt-Vorlage
oder freiem Text). Die strukturellen Entscheidungen (welcher Endpunkt,
welcher Schluessel, welches lokale Modell) werden einmalig in den
Einstellungen getroffen (``gui.settings_dialog.SettingsDialog``); der
Umschalter hier im Hauptfenster spiegelt nur, welcher der beiden Wege fuer
den naechsten Lauf gilt.

Die komplette Ablaufsteuerung (Chunk-Planung, Fortsetzbarkeit,
Zusammenfuehrung, Export, mehrstufige Protokollauswertung) ist
``services.pipeline_service``. Ob ein Chunk lokal oder ueber eine API
transkribiert wird, ist dort nur eine austauschbare Funktion
(``transcribe_chunk_fn``/``diarize_fn``/``protocol_generate_fn``) - diese
Datei waehlt lediglich, welche Funktion(en) das sind.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Verarbeitungskette und Hilfsmodule der Anwendung.
from protokoll_assistent.gui.dialogs import show_error
from protokoll_assistent.gui.settings_dialog import DATENSCHUTZ_HINWEIS_API, SettingsDialog
from protokoll_assistent.gui.strings import PRIVACY_NOTICE
from protokoll_assistent.gui.worker import (
    DateiHashWorker,
    ProtocolGenerateFn,
    ProtocolWorker,
    TranscriptionWorker,
)
from protokoll_assistent.services import (
    api_protocol_service,
    api_transcription_service,
    export_service,
    manifest_service,
    model_service,
    ollama_service,
    pipeline_service,
    secret_store,
)
from protokoll_assistent.utils import app_config
from protokoll_assistent.utils.paths import (
    get_default_output_dir,
    get_recordings_dir,
    get_system_prompt_file,
    get_work_dir,
)
from protokoll_assistent.utils.systemprompt_vorlagen import alle_vorlagen, vorlage_speichern
from protokoll_assistent.utils.timeformat import format_duration_human

if TYPE_CHECKING:  # pragma: no cover - nur fuer die Typpruefung
    from protokoll_assistent.services import recording_service


def lade_recording_service() -> ModuleType:
    """Laedt 'services.recording_service' erst bei Bedarf.

    Das Modul importiert 'sounddevice' auf Modulebene. Im lokalen Modus
    laeuft diese Anwendung aber in der von 'bootstrap.py' verwalteten
    Laufzeitumgebung, und deren 'requirements-laufzeit.txt' enthaelt
    'sounddevice' nicht. Ein Import auf Modulebene wuerde dort schon das
    Oeffnen des Hauptfensters verhindern -- wegen einer Zusatzfunktion
    (Mikrofonaufnahme), ohne die der Rest der Anwendung vollstaendig
    arbeitet. Der 'ImportError' landet stattdessen dort, wo er behandelt
    wird ('_populate_recording_devices' schaltet die Aufnahme dann ab und
    sagt, warum)."""
    from protokoll_assistent.services import recording_service as modul

    return modul


def ermittle_whisper_modell(konfiguration: dict[str, Any]) -> str:
    """Welches Whisper-Modell gilt fuer den lokalen Modus?

    Die Einstellung stammt aus **einer** Konfiguration -- gesetzt entweder im
    Einstellungsdialog oder vom Einrichtungsassistenten
    ('gui.wizard.SetupWizard'), der genau das Modell speichert, das er auch
    heruntergeladen hat. Ist nichts hinterlegt, gilt der eingebaute Standard.

    (Solange Oberflaeche und Assistent zu getrennten Anwendungen mit je
    eigener 'konfiguration.json' gehoerten, schrieb der Assistent in die eine
    und die Oberflaeche las aus der anderen -- direkt nach der
    Ersteinrichtung galt deshalb ein anderes Modell als das eingerichtete.
    Mit einer einzigen Konfiguration kann das nicht mehr passieren.)
    """
    gewaehlt = konfiguration.get("whisper_modell")
    if gewaehlt:
        return str(gewaehlt)
    return model_service.WHISPER_MODEL_NAME


SUPPORTED_EXTENSION_NAMES = [
    "mp3", "mp4", "m4a", "wav", "aac", "flac", "ogg", "opus", "mov", "mkv", "webm",
]
SUPPORTED_EXTENSIONS = " ".join(f"*.{name}" for name in SUPPORTED_EXTENSION_NAMES)
SUPPORTED_SUFFIXES = {f".{name}" for name in SUPPORTED_EXTENSION_NAMES}


class MainWindow(QMainWindow):
    def __init__(self, initial_folder: Path | None = None, initial_file: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Protokoll-Assistent")
        self.resize(1420, 900)
        self.setAcceptDrops(True)

        config = app_config.load_config()
        self._input_folder: Path | None = initial_folder
        if self._input_folder is None and config.get("eingabeordner"):
            candidate = Path(config["eingabeordner"])
            if candidate.is_dir():
                self._input_folder = candidate

        self._source_path: Path | None = None
        if self._input_folder is not None and initial_file:
            candidate_file = self._input_folder / initial_file
            if candidate_file.is_file():
                self._source_path = candidate_file

        if config.get("ausgabeordner") and Path(config["ausgabeordner"]).parent.exists():
            self._output_dir: Path = Path(config["ausgabeordner"])
        else:
            self._output_dir = get_default_output_dir()

        self._transcription_worker: TranscriptionWorker | None = None
        self._protocol_worker: ProtocolWorker | None = None
        self._start_time: float | None = None
        self._chunk_progress = (0, 0)
        self._last_transcription_result: pipeline_service.TranscriptionResult | None = None
        self._last_protocol_result: pipeline_service.ProtocolResult | None = None
        self._selected_transcript_path: Path | None = None
        self._hash_worker: DateiHashWorker | None = None
        self._hash_zwischenspeicher: dict[tuple[str, int, int], str] = {}
        # Eingegebene, aber nicht dauerhaft gemerkte API-Schluessel bleiben
        # fuer den Rest dieser Sitzung nutzbar (siehe
        # 'gui.settings_dialog.SettingsDialog.eingegebene_schluessel').
        self._session_api_keys: dict[str, str] = {}

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)

        self._recording_devices: list[recording_service.Aufnahmegeraet] = []
        self._recording: recording_service.MikrofonAufnahme | None = None
        self._recording_timer = QTimer(self)
        self._recording_timer.setInterval(100)
        self._recording_timer.timeout.connect(self._update_recording_display)

        self._build_ui()
        self._refresh_hardware_label()

        if self._source_path is not None:
            self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
            self._select_file_in_list(self._source_path.name)
            self._refresh_resume_status()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        header_row = QHBoxLayout()
        privacy_label = QLabel(PRIVACY_NOTICE, self)
        privacy_label.setObjectName("PrivacyBanner")
        privacy_label.setWordWrap(True)
        header_row.addWidget(privacy_label, stretch=1)
        settings_button = QPushButton("Einstellungen …", self)
        settings_button.clicked.connect(self._open_settings)
        header_row.addWidget(settings_button, alignment=Qt.AlignTop)
        root_layout.addLayout(header_row)

        splitter = QSplitter(self)
        root_layout.addWidget(splitter, stretch=1)

        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(self._build_recording_group())
        left_layout.addWidget(self._build_file_group())
        left_layout.addWidget(self._build_settings_group())
        left_layout.addWidget(self._build_resume_group())
        left_layout.addWidget(self._build_control_group())

        separator = QFrame(self)
        separator.setFrameShape(QFrame.HLine)
        left_layout.addWidget(separator)
        nachbearbeitung_label = QLabel(
            "Nachbearbeitung (separater Schritt - jederzeit für ein vorhandenes Transkript)", self
        )
        nachbearbeitung_label.setStyleSheet("font-weight: 700;")
        left_layout.addWidget(nachbearbeitung_label)

        left_layout.addWidget(self._build_transcript_selection_group())
        left_layout.addWidget(self._build_protocol_control_group())
        left_layout.addStretch(1)

        left_scroll = QScrollArea(self)
        left_scroll.setWidget(left_panel)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setMinimumWidth(480)
        splitter.addWidget(left_scroll)

        # 'Fortschritt' steht bewusst im rechten Bereich, nicht in der
        # scrollbaren linken Spalte: dort waere sie nach "Transkription
        # starten" erst nach mehrfachem Scrollen zu sehen - genau das hat in
        # der Praxis den Eindruck erweckt, es passiere gar nichts.
        right_panel = QWidget(self)
        splitter.addWidget(right_panel)
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(self._build_progress_group())
        right_layout.addWidget(self._build_preview_group(), stretch=1)
        right_layout.addWidget(self._build_speaker_group(), stretch=1)

        splitter.setSizes([650, 770])

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._session_api_keys.update(dialog.eingegebene_schluessel)
            self._apply_modus_from_config()

    def _apply_modus_from_config(self) -> None:
        config = app_config.load_config()
        if config["transkription_modus"] == "api":
            self.transkription_api_radio.setChecked(True)
        else:
            self.transkription_lokal_radio.setChecked(True)
        if config["nachbearbeitung_modus"] == "api":
            self.nachbearbeitung_api_radio.setChecked(True)
        else:
            self.nachbearbeitung_lokal_radio.setChecked(True)

    # ------------------------------------------------------------------
    # Gruppe 1: Aufnahmegeraet (Voice Recording) - unveraendert gegenueber
    # der lokalen Variante, das erzeugte WAV landet ueber '_set_source_file'
    # im selben Auswahlmechanismus wie eine per Hand gewaehlte Datei.
    # ------------------------------------------------------------------
    def _build_recording_group(self) -> QGroupBox:
        group = QGroupBox("1. Aufnahmegerät", self)
        layout = QVBoxLayout(group)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Aufnahmegerät:", self))
        self.recording_device_combo = QComboBox(self)
        self.recording_device_combo.currentIndexChanged.connect(self._on_recording_device_changed)
        device_row.addWidget(self.recording_device_combo, stretch=1)
        layout.addLayout(device_row)

        self.recording_hint_label = QLabel("", self)
        self.recording_hint_label.setWordWrap(True)
        self.recording_hint_label.setObjectName("RecordingHint")
        layout.addWidget(self.recording_hint_label)

        status_row = QHBoxLayout()
        self.recording_status_label = QLabel("", self)
        status_row.addWidget(self.recording_status_label)
        self.recording_duration_label = QLabel("", self)
        status_row.addWidget(self.recording_duration_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.recording_level_bar = QProgressBar(self)
        self.recording_level_bar.setRange(0, 100)
        self.recording_level_bar.setTextVisible(False)
        layout.addWidget(self.recording_level_bar)

        button_row = QHBoxLayout()
        self.recording_start_button = QPushButton("Voice Recording starten", self)
        self.recording_start_button.clicked.connect(self._start_recording)
        button_row.addWidget(self.recording_start_button)
        self.recording_pause_button = QPushButton("Pause", self)
        self.recording_pause_button.clicked.connect(self._toggle_recording_pause)
        self.recording_pause_button.hide()
        button_row.addWidget(self.recording_pause_button)
        self.recording_stop_button = QPushButton("Aufnahme beenden", self)
        self.recording_stop_button.clicked.connect(self._stop_recording)
        self.recording_stop_button.hide()
        button_row.addWidget(self.recording_stop_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._populate_recording_devices()
        return group

    def _populate_recording_devices(self) -> None:
        try:
            aufnahme_modul = lade_recording_service()
            self._recording_devices = aufnahme_modul.liste_aufnahmegeraete()
        except ImportError as error:
            self._recording_devices = []
            self.recording_hint_label.setText(
                "Die Mikrofonaufnahme steht in dieser Laufzeitumgebung nicht zur "
                f"Verfügung ({error}). Alles andere funktioniert unverändert; eine "
                "bereits vorhandene Aufnahme kann wie jede andere Datei ausgewählt werden."
            )
            self.recording_start_button.setEnabled(False)
            return
        except Exception as error:  # PortAudio-Fehler in ungewoehnlicher Umgebung
            self._recording_devices = []
            self.recording_hint_label.setText(f"Aufnahmegeräte konnten nicht ermittelt werden: {error}")
            self.recording_start_button.setEnabled(False)
            return

        if not self._recording_devices:
            self.recording_hint_label.setText("Keine Audioeingabegeräte gefunden.")
            self.recording_start_button.setEnabled(False)
            return

        config = app_config.load_config()
        saved = config.get("aufnahmegeraet")
        standard_index = aufnahme_modul.standard_eingabe_index()
        device, hint = aufnahme_modul.waehle_startgeraet(
            self._recording_devices, saved, standard_index
        )

        self.recording_device_combo.blockSignals(True)
        self.recording_device_combo.clear()
        for eintrag in self._recording_devices:
            self.recording_device_combo.addItem(eintrag.anzeigename)
        if device is not None:
            index = self.recording_device_combo.findText(device.anzeigename)
            if index >= 0:
                self.recording_device_combo.setCurrentIndex(index)
        self.recording_device_combo.blockSignals(False)

        self.recording_hint_label.setText(hint or "")
        self.recording_start_button.setEnabled(True)

    def _on_recording_device_changed(self, _index: int) -> None:
        anzeigename = self.recording_device_combo.currentText()
        if anzeigename:
            app_config.update_config(aufnahmegeraet=anzeigename)
            self.recording_hint_label.setText("")

    def _start_recording(self) -> None:
        anzeigename = self.recording_device_combo.currentText()
        geraet = next((g for g in self._recording_devices if g.anzeigename == anzeigename), None)
        if geraet is None:
            show_error(self, "Kein Gerät ausgewählt", "Bitte zuerst ein Aufnahmegerät auswählen.")
            return

        try:
            aufnahme_modul = lade_recording_service()
            zielpfad = get_recordings_dir() / aufnahme_modul.erzeuge_dateiname()
            aufnahme = aufnahme_modul.MikrofonAufnahme(geraet, zielpfad)
            aufnahme.start()
        except Exception as error:
            show_error(
                self,
                "Aufnahme konnte nicht gestartet werden",
                f"Das Gerät '{geraet.anzeigename}' konnte nicht geöffnet werden:\n{error}",
            )
            return
        self._recording = aufnahme

        self.recording_device_combo.setEnabled(False)
        self.recording_start_button.hide()
        self.recording_pause_button.setText("Pause")
        self.recording_pause_button.show()
        self.recording_stop_button.show()
        self.recording_status_label.setText("🔴 Aufnahme läuft")
        self._recording_timer.start()

    def _toggle_recording_pause(self) -> None:
        if self._recording is None:
            return
        if self._recording.ist_pausiert:
            self._recording.fortsetzen()
            self.recording_pause_button.setText("Pause")
            self.recording_status_label.setText("🔴 Aufnahme läuft")
        else:
            self._recording.pause()
            self.recording_pause_button.setText("Fortsetzen")
            self.recording_status_label.setText("⏸ Aufnahme pausiert")

    def _update_recording_display(self) -> None:
        if self._recording is None:
            self._recording_timer.stop()
            return
        duration = int(self._recording.dauer_sekunden)
        self.recording_duration_label.setText(f"{duration // 60:02d}:{duration % 60:02d}")
        self.recording_level_bar.setValue(int(self._recording.pegel * 100))

    def _stop_recording(self) -> None:
        if self._recording is None:
            return
        path = self._recording.stop()
        self._recording = None
        self._recording_timer.stop()

        self.recording_device_combo.setEnabled(True)
        self.recording_pause_button.hide()
        self.recording_stop_button.hide()
        self.recording_start_button.show()
        self.recording_status_label.setText("")
        self.recording_duration_label.setText("")
        self.recording_level_bar.setValue(0)

        self._set_source_file(path)

    # ------------------------------------------------------------------
    # Gruppe 2: Eingabeordner und Datei
    # ------------------------------------------------------------------
    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("2. Eingabeordner und Datei", self)
        layout = QVBoxLayout(group)

        folder_row = QHBoxLayout()
        folder_text = str(self._input_folder) if self._input_folder else "Kein Eingabeordner ausgewählt"
        self.folder_label = QLabel(folder_text, self)
        self.folder_label.setWordWrap(True)
        choose_folder_button = QPushButton("Ordner wechseln …", self)
        choose_folder_button.clicked.connect(self._choose_input_folder)
        folder_row.addWidget(choose_folder_button)
        folder_row.addWidget(self.folder_label, stretch=1)
        layout.addLayout(folder_row)

        self.file_list = QListWidget(self)
        self.file_list.setMaximumHeight(140)
        self.file_list.itemSelectionChanged.connect(self._on_file_list_selection_changed)
        layout.addWidget(self.file_list)
        if self._input_folder is not None:
            self._populate_file_list(self._input_folder)

        other_file_row = QHBoxLayout()
        choose_file_button = QPushButton("Andere Datei wählen …", self)
        choose_file_button.clicked.connect(self._choose_file)
        other_file_row.addWidget(choose_file_button)
        other_file_row.addStretch(1)
        layout.addLayout(other_file_row)

        self.file_label = QLabel("Keine Datei ausgewählt", self)
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        output_row = QHBoxLayout()
        self.output_label = QLabel(str(self._output_dir), self)
        self.output_label.setWordWrap(True)
        choose_output_button = QPushButton("Ausgabeordner wählen …", self)
        choose_output_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(choose_output_button)
        output_row.addWidget(self.output_label, stretch=1)
        layout.addLayout(output_row)

        return group

    # ------------------------------------------------------------------
    # Gruppe 3: Einstellungen fuer DIESEN Lauf (Sprache, Sprechertrennung).
    # Die strukturelle Wahl lokal/API sowie Modell-/Endpunktkonfiguration
    # gehoeren in 'SettingsDialog', nicht hierher.
    # ------------------------------------------------------------------
    def _build_settings_group(self) -> QGroupBox:
        group = QGroupBox("3. Einstellungen", self)
        layout = QFormLayout(group)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        self.language_combo = QComboBox(self)
        self.language_combo.addItem("Deutsch (de)", "de")
        self.language_combo.addItem("Automatisch erkennen", None)
        layout.addRow("Sprache:", self.language_combo)

        self.diarization_checkbox = QCheckBox("Sprechertrennung aktivieren (Sprecher erkennen)", self)
        self.diarization_checkbox.setChecked(True)
        self.diarization_checkbox.toggled.connect(self._toggle_diarization)
        layout.addRow(self.diarization_checkbox)

        diarization_hint = QLabel(
            "Deaktivieren, wenn nur der Inhalt zaehlt und die Aussagen anonym bleiben "
            "sollen (keine Sprecherzuordnung im Ergebnis).",
            self,
        )
        diarization_hint.setWordWrap(True)
        layout.addRow(diarization_hint)

        self.limit_speakers_checkbox = QCheckBox("Sprecherzahl manuell begrenzen", self)
        self.limit_speakers_checkbox.toggled.connect(self._toggle_speaker_limits)
        layout.addRow(self.limit_speakers_checkbox)

        speaker_row = QHBoxLayout()
        self.min_speakers_spin = QSpinBox(self)
        self.min_speakers_spin.setRange(1, 30)
        self.min_speakers_spin.setValue(2)
        self.min_speakers_spin.setEnabled(False)
        self.max_speakers_spin = QSpinBox(self)
        self.max_speakers_spin.setRange(1, 30)
        self.max_speakers_spin.setValue(6)
        self.max_speakers_spin.setEnabled(False)
        speaker_row.addWidget(QLabel("Min.:", self))
        speaker_row.addWidget(self.min_speakers_spin)
        speaker_row.addWidget(QLabel("Max.:", self))
        speaker_row.addWidget(self.max_speakers_spin)
        layout.addRow(speaker_row)

        # Vorher stand 'allow_download=False' fest im
        # Code -- damit setzt 'model_service.prepare_offline_mode'
        # ausnahmslos 'HF_HUB_OFFLINE=1', und ein Modell, das noch nicht
        # heruntergeladen ist, kann NIE geladen werden. Der
        # Einstellungsdialog verspricht aber genau das ("Wird beim ersten
        # Einsatz im lokalen Modus automatisch heruntergeladen").
        self.offline_checkbox = QCheckBox("Offline-Modus (empfohlen)", self)
        self.offline_checkbox.setChecked(True)
        layout.addRow(self.offline_checkbox)

        offline_hint = QLabel(
            "Verhindert jeden Netzwerkzugriff der Modelle. Für den ersten Lauf mit "
            "einem noch nicht eingerichteten Whisper-Modell einmal abwählen, damit es "
            "heruntergeladen werden darf.",
            self,
        )
        offline_hint.setWordWrap(True)
        layout.addRow(offline_hint)

        return group

    def _toggle_speaker_limits(self, checked: bool) -> None:
        self.min_speakers_spin.setEnabled(checked)
        self.max_speakers_spin.setEnabled(checked)

    def _toggle_diarization(self, checked: bool) -> None:
        self.limit_speakers_checkbox.setEnabled(checked)
        if not checked:
            self.limit_speakers_checkbox.setChecked(False)
        self.min_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())
        self.max_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())

    def _refresh_hardware_label(self) -> None:
        self.hardware_label.setText(model_service.get_gpu_description())

    # ------------------------------------------------------------------
    # Gruppe 4: Fortsetzen bei Langzeitaufnahmen
    # ------------------------------------------------------------------
    def _build_resume_group(self) -> QGroupBox:
        group = QGroupBox("4. Fortsetzen bei Langzeitaufnahmen", self)
        layout = QVBoxLayout(group)

        self.resume_status_label = QLabel(
            "Keine Datei ausgewählt -- es kann noch nicht geprüft werden, ob bereits "
            "ein Zwischenstand existiert.",
            self,
        )
        self.resume_status_label.setWordWrap(True)
        layout.addWidget(self.resume_status_label)

        row = QHBoxLayout()
        self.resume_combo = QComboBox(self)
        self.resume_combo.addItem("Verarbeitung fortsetzen", "fortsetzen")
        self.resume_combo.addItem("Vollständig neu beginnen", "neu_beginnen")
        row.addWidget(self.resume_combo)

        open_intermediate_button = QPushButton("Zwischenstände öffnen", self)
        open_intermediate_button.clicked.connect(self._open_intermediate_folder)
        row.addWidget(open_intermediate_button)
        layout.addLayout(row)

        return group

    # ------------------------------------------------------------------
    # Gruppe 5: Transkription - lokal/API-Umschalter direkt hier, damit
    # nicht jedes Mal die Einstellungen geoeffnet werden muessen.
    # ------------------------------------------------------------------
    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("5. Transkription", self)
        layout = QVBoxLayout(group)

        modus_row = QHBoxLayout()
        self.transkription_lokal_radio = QRadioButton("Lokal", self)
        self.transkription_api_radio = QRadioButton("API-Schnittstelle", self)
        self._transkription_modus_gruppe = QButtonGroup(self)
        self._transkription_modus_gruppe.addButton(self.transkription_lokal_radio)
        self._transkription_modus_gruppe.addButton(self.transkription_api_radio)
        modus_row.addWidget(self.transkription_lokal_radio)
        modus_row.addWidget(self.transkription_api_radio)
        modus_row.addStretch(1)
        layout.addLayout(modus_row)

        config = app_config.load_config()
        if config["transkription_modus"] == "api":
            self.transkription_api_radio.setChecked(True)
        else:
            self.transkription_lokal_radio.setChecked(True)
        self.transkription_lokal_radio.toggled.connect(self._transkription_modus_geaendert)
        self.transkription_api_radio.toggled.connect(self._transkription_modus_geaendert)

        self.transkription_datenschutz_hinweis = QLabel(DATENSCHUTZ_HINWEIS_API, self)
        self.transkription_datenschutz_hinweis.setObjectName("DatenschutzHinweis")
        self.transkription_datenschutz_hinweis.setWordWrap(True)
        layout.addWidget(self.transkription_datenschutz_hinweis)
        self._transkription_datenschutz_hinweis_aktualisieren()

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Transkription starten", self)
        self.start_button.clicked.connect(self._start_transcription)
        button_row.addWidget(self.start_button)
        self.cancel_button = QPushButton("Abbrechen", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_transcription)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        return group

    def _transkription_modus_geaendert(self) -> None:
        modus = "api" if self.transkription_api_radio.isChecked() else "lokal"
        app_config.update_config(transkription_modus=modus)
        self._transkription_datenschutz_hinweis_aktualisieren()

    def _transkription_datenschutz_hinweis_aktualisieren(self) -> None:
        self.transkription_datenschutz_hinweis.setVisible(self.transkription_api_radio.isChecked())

    # ------------------------------------------------------------------
    # Gemeinsame Fortschrittsgruppe
    # ------------------------------------------------------------------
    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Fortschritt", self)
        layout = QFormLayout(group)

        self.status_label = QLabel("Bereit.", self)
        self.status_label.setWordWrap(True)
        layout.addRow("Status:", self.status_label)

        self.transcription_status_label = QLabel("wartet", self)
        layout.addRow("Transkriptionsstatus:", self.transcription_status_label)

        self.protocol_status_label = QLabel("wartet", self)
        layout.addRow("Status Nachbearbeitung:", self.protocol_status_label)

        self.chunk_progress_bar = QProgressBar(self)
        layout.addRow("Aktueller Chunk:", self.chunk_progress_bar)

        self.overall_progress_bar = QProgressBar(self)
        self.overall_progress_bar.setRange(0, 100)
        layout.addRow("Gesamtfortschritt:", self.overall_progress_bar)

        self.elapsed_label = QLabel("00:00", self)
        layout.addRow("Laufzeit:", self.elapsed_label)

        self.remaining_label = QLabel("--", self)
        layout.addRow("Geschätzte Restdauer:", self.remaining_label)

        self.hardware_label = QLabel("--", self)
        layout.addRow("Hardware:", self.hardware_label)

        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("Transkriptvorschau", self)
        layout = QVBoxLayout(group)
        self.preview_edit = QPlainTextEdit(self)
        self.preview_edit.setReadOnly(True)
        layout.addWidget(self.preview_edit)
        return group

    def _build_speaker_group(self) -> QGroupBox:
        group = QGroupBox("Sprecherzuordnung", self)
        layout = QVBoxLayout(group)

        self.speaker_table = QTableWidget(0, 4, self)
        self.speaker_table.setHorizontalHeaderLabels(
            ["Technische Sprecher-ID", "Segmente", "Sprechdauer", "Name"]
        )
        self.speaker_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.speaker_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        layout.addWidget(self.speaker_table)

        self.apply_names_button = QPushButton("Namen übernehmen && Ausgaben neu erzeugen", self)
        self.apply_names_button.setEnabled(False)
        self.apply_names_button.clicked.connect(self._apply_speaker_names)
        layout.addWidget(self.apply_names_button)

        return group

    # ------------------------------------------------------------------
    # Datei-/Ordnerauswahl, Drag & Drop
    # ------------------------------------------------------------------
    def _choose_input_folder(self) -> None:
        start_dir = str(self._input_folder) if self._input_folder else str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Eingabeordner wählen", start_dir)
        if directory:
            self._set_input_folder(Path(directory))

    def _set_input_folder(self, folder: Path) -> None:
        self._input_folder = folder
        self.folder_label.setText(str(folder))
        self._populate_file_list(folder)
        app_config.update_config(eingabeordner=str(folder))

    def _populate_file_list(self, folder: Path) -> None:
        self.file_list.clear()
        try:
            files = sorted(
                path for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
            )
        except OSError:
            files = []
        for file_path in files:
            self.file_list.addItem(file_path.name)

    def _select_file_in_list(self, filename: str) -> None:
        matches = self.file_list.findItems(filename, Qt.MatchExactly)
        if matches:
            self.file_list.setCurrentItem(matches[0])

    def _on_file_list_selection_changed(self) -> None:
        items = self.file_list.selectedItems()
        if not items or self._input_folder is None:
            return
        self._source_path = self._input_folder / items[0].text()
        self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
        self._refresh_resume_status()

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Audio- oder Videodatei auswählen",
            str(self._input_folder) if self._input_folder else "",
            f"Unterstützte Dateien ({SUPPORTED_EXTENSIONS});;Alle Dateien (*)",
        )
        if not filename:
            return
        self._set_source_file(Path(filename))

    def _set_source_file(self, path: Path) -> None:
        self.file_list.clearSelection()
        self._source_path = path
        self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
        self._refresh_resume_status()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.is_dir():
            self._set_input_folder(path)
            event.acceptProposedAction()
        elif path.is_file():
            self._set_source_file(path)
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Beendet eine laufende Aufnahme sauber, statt sie beim Schliessen
        des Fensters abzuwuergen - sonst fehlt der WAV-Datei der finale
        Header und sie waere unbrauchbar."""
        if self._recording is not None:
            with contextlib.suppress(Exception):
                self._recording.stop()
        super().closeEvent(event)

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", str(self._output_dir))
        if not directory:
            return
        self._output_dir = Path(directory)
        self.output_label.setText(str(self._output_dir))
        app_config.update_config(ausgabeordner=str(self._output_dir))

    # ------------------------------------------------------------------
    # Fortsetzen-Status (Dateihash laeuft im Hintergrund)
    # ------------------------------------------------------------------
    def _dateihash(self, pfad: Path) -> str | None:
        try:
            angaben = pfad.stat()
        except OSError:
            return None
        return self._hash_zwischenspeicher.get((str(pfad), angaben.st_size, angaben.st_mtime_ns))

    def _dateihash_merken(self, pfad: Path, hashwert: str) -> None:
        try:
            angaben = pfad.stat()
        except OSError:
            return
        self._hash_zwischenspeicher[(str(pfad), angaben.st_size, angaben.st_mtime_ns)] = hashwert

    def _refresh_resume_status(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            return
        bekannt = self._dateihash(self._source_path)
        if bekannt is not None:
            self._zeige_fortsetzbarkeit(str(self._source_path), bekannt)
            return

        self.resume_status_label.setText("Datei wird geprüft …")
        self._hash_worker = DateiHashWorker(self._source_path, self)
        self._hash_worker.fertig.connect(self._zeige_fortsetzbarkeit)
        self._hash_worker.fehlgeschlagen.connect(self._hash_fehlgeschlagen)
        self._hash_worker.start()

    def _hash_fehlgeschlagen(self, pfad: str, fehler: str) -> None:
        if self._source_path is None or str(self._source_path) != pfad:
            return
        self.resume_status_label.setText(f"Datei konnte nicht gelesen werden: {fehler}")

    def _zeige_fortsetzbarkeit(self, pfad: str, file_hash: str) -> None:
        if self._source_path is None or str(self._source_path) != pfad:
            return
        self._dateihash_merken(self._source_path, file_hash)
        try:
            work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
            manifest = manifest_service.load_manifest(work_dir)
        except OSError as error:
            self.resume_status_label.setText(f"Datei konnte nicht gelesen werden: {error}")
            return

        if manifest is None:
            self.resume_status_label.setText("Keine vorherige Verarbeitung für diese Datei gefunden.")
            self.resume_combo.setCurrentIndex(1)
            return

        state = manifest_service.find_resumable_state(manifest)
        if state["vollstaendig"]:
            self.resume_status_label.setText(
                "Diese Datei wurde bereits vollständig verarbeitet. Ein Neustart berechnet alles erneut."
            )
        else:
            self.resume_status_label.setText(
                f"Unvollständige Verarbeitung gefunden: {len(state['fertige_chunks'])} von "
                f"{manifest['anzahl_chunks']} Chunks abgeschlossen. "
                f"Nächster Chunk: {state['naechster_chunk'] + 1 if state['naechster_chunk'] is not None else '-'}."
            )
        self.resume_combo.setCurrentIndex(0)

    def _open_intermediate_folder(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            show_error(self, "Keine Datei ausgewählt", "Bitte zuerst eine Datei auswählen.")
            return
        file_hash = self._dateihash(self._source_path) or manifest_service.compute_file_hash(
            self._source_path
        )
        self._dateihash_merken(self._source_path, file_hash)
        work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(work_dir)))

    # ------------------------------------------------------------------
    # Gruppe 6: Transkript auswaehlen (Eingang fuer die Nachbearbeitung)
    # ------------------------------------------------------------------
    def _build_transcript_selection_group(self) -> QGroupBox:
        group = QGroupBox("6. Transkript auswählen", self)
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        choose_transcript_button = QPushButton("Transkript auswählen …", self)
        choose_transcript_button.clicked.connect(self._choose_transcript)
        row.addWidget(choose_transcript_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.transcript_label = QLabel("Noch kein Transkript ausgewählt", self)
        self.transcript_label.setWordWrap(True)
        layout.addWidget(self.transcript_label)

        return group

    def _choose_transcript(self) -> None:
        start_dir = str(self._output_dir)
        filename, _ = QFileDialog.getOpenFileName(
            self, "Transkript auswählen", start_dir, "Transkript-JSON (*.json);;Alle Dateien (*)"
        )
        if not filename:
            return
        self._set_transcript_path(Path(filename))

    def _set_transcript_path(self, path: Path) -> None:
        self._selected_transcript_path = path
        self.transcript_label.setText(f"Ausgewählt: {path.name}")

    # ------------------------------------------------------------------
    # Gruppe 7: Nachbearbeitung - lokal/API-Umschalter, Systemprompt
    # (Vorlage per Dropdown oder freier Text, wie vom Auftrag verlangt).
    # ------------------------------------------------------------------
    def _build_protocol_control_group(self) -> QGroupBox:
        group = QGroupBox("7. Nachbearbeitung", self)
        layout = QVBoxLayout(group)

        modus_row = QHBoxLayout()
        self.nachbearbeitung_lokal_radio = QRadioButton("Lokal (Ollama)", self)
        self.nachbearbeitung_api_radio = QRadioButton("API-Modell", self)
        self._nachbearbeitung_modus_gruppe = QButtonGroup(self)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_lokal_radio)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_api_radio)
        modus_row.addWidget(self.nachbearbeitung_lokal_radio)
        modus_row.addWidget(self.nachbearbeitung_api_radio)
        modus_row.addStretch(1)
        layout.addLayout(modus_row)

        config = app_config.load_config()
        if config["nachbearbeitung_modus"] == "api":
            self.nachbearbeitung_api_radio.setChecked(True)
        else:
            self.nachbearbeitung_lokal_radio.setChecked(True)
        self.nachbearbeitung_lokal_radio.toggled.connect(self._nachbearbeitung_modus_geaendert)
        self.nachbearbeitung_api_radio.toggled.connect(self._nachbearbeitung_modus_geaendert)

        vorlagen_row = QHBoxLayout()
        vorlagen_row.addWidget(QLabel("Vorlage:", self))
        self.vorlage_combo = QComboBox(self)
        self.vorlage_combo.addItem("(freier Text)", None)
        for name in alle_vorlagen():
            self.vorlage_combo.addItem(name, name)
        self.vorlage_combo.currentIndexChanged.connect(self._vorlage_angewendet)
        vorlagen_row.addWidget(self.vorlage_combo, stretch=1)
        neue_vorlage_button = QPushButton("Als neue Vorlage speichern …", self)
        neue_vorlage_button.clicked.connect(self._neue_vorlage_speichern)
        vorlagen_row.addWidget(neue_vorlage_button)
        layout.addLayout(vorlagen_row)

        self.systemprompt_editor = QPlainTextEdit(self)
        self.systemprompt_editor.setPlaceholderText(
            "Was soll mit dem Transkript geschehen? Eigenen Text eingeben oder oben "
            "eine Vorlage auswählen."
        )
        prompt_datei = get_system_prompt_file()
        if prompt_datei.is_file():
            self.systemprompt_editor.setPlainText(prompt_datei.read_text(encoding="utf-8"))
        layout.addWidget(self.systemprompt_editor)

        button_row = QHBoxLayout()
        self.protocol_start_button = QPushButton("Nachbearbeitung starten", self)
        self.protocol_start_button.clicked.connect(self._start_protocol)
        button_row.addWidget(self.protocol_start_button)
        self.protocol_cancel_button = QPushButton("Abbrechen", self)
        self.protocol_cancel_button.setEnabled(False)
        self.protocol_cancel_button.clicked.connect(self._cancel_protocol)
        button_row.addWidget(self.protocol_cancel_button)
        layout.addLayout(button_row)

        return group

    def _nachbearbeitung_modus_geaendert(self) -> None:
        modus = "api" if self.nachbearbeitung_api_radio.isChecked() else "lokal"
        app_config.update_config(nachbearbeitung_modus=modus)

    def _vorlage_angewendet(self, _index: int) -> None:
        name = self.vorlage_combo.currentData()
        if name is None:
            return
        text = alle_vorlagen().get(name)
        if text is not None:
            self.systemprompt_editor.setPlainText(text)

    def _neue_vorlage_speichern(self) -> None:
        name, ok = QInputDialog.getText(self, "Neue Vorlage", "Name der Vorlage:")
        name = name.strip()
        if not ok or not name:
            return
        try:
            vorlage_speichern(name, self.systemprompt_editor.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Name nicht verwendbar", str(error))
            return
        except OSError as error:
            # Der Name IST der Dateiname. 'name_pruefen' faengt die verbotenen
            # Zeichen ab, es bleiben aber Faelle, die erst das Dateisystem
            # kennt: unter Windows reservierte Namen ("CON", "PRN", "LPT1"),
            # ein zu langer Pfad, ein schreibgeschuetzter Ordner.
            QMessageBox.warning(
                self,
                "Vorlage konnte nicht gespeichert werden",
                f"Die Vorlage '{name}' konnte nicht gespeichert werden:\n{error}",
            )
            return
        if self.vorlage_combo.findData(name) < 0:
            self.vorlage_combo.addItem(name, name)
        self.vorlage_combo.setCurrentIndex(self.vorlage_combo.findData(name))

    # ------------------------------------------------------------------
    # Start / Abbruch / Fortschritt: Transkription
    # ------------------------------------------------------------------
    def _start_transcription(self) -> None:
        if self._source_path is None:
            show_error(self, "Keine Datei ausgewählt", "Bitte zuerst eine Audio- oder Videodatei auswählen.")
            return
        if not self._source_path.is_file():
            show_error(self, "Datei nicht gefunden", f"Die Datei wurde nicht gefunden:\n{self._source_path}")
            return
        if self._source_path.stat().st_size == 0:
            show_error(self, "Datei ist leer", "Die ausgewählte Datei enthält keine Daten.")
            return
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            probe_file = self._output_dir / ".schreibtest.tmp"
            probe_file.write_text("test", encoding="utf-8")
            probe_file.unlink()
        except OSError as error:
            show_error(self, "Ausgabeordner ungültig", f"In den Ausgabeordner kann nicht geschrieben werden:\n{error}")
            return

        if self.transkription_lokal_radio.isChecked() and not self._lokale_laufzeitumgebung_verfuegbar():
            show_error(
                self,
                "Lokale Laufzeitumgebung noch nicht eingerichtet",
                "Für die lokale Transkription richtet diese Anwendung sich beim Start "
                "automatisch eine eigene Laufzeitumgebung ein (Whisper-Modell u. a.) -- "
                "das geschieht aber nur, wenn 'Lokal' schon beim Programmstart als "
                "Transkriptionsmodus aktiv war.\n\n"
                "Bitte die Anwendung einmal vollständig beenden und neu starten, während "
                "'Lokal' ausgewählt ist: Die Einrichtung läuft dann automatisch (kann "
                "beim ersten Mal, je nach Internetverbindung, einige Minuten dauern).",
            )
            return

        config = app_config.load_config()
        transcribe_chunk_fn = None
        diarize_fn = None
        if self.transkription_api_radio.isChecked():
            api_key = self._verwendbarer_api_schluessel("transkription")
            if not api_key:
                show_error(
                    self,
                    "Kein API-Schlüssel",
                    "Bitte zuerst in den Einstellungen einen API-Schlüssel für die Transkription hinterlegen.",
                )
                return
            transcribe_chunk_fn = functools.partial(
                api_transcription_service.transcribe_chunk_via_api,
                endpoint_url=config["api_transkription_endpunkt"],
                api_key=api_key,
                model_name=config["api_transkription_modell"],
                provider_name=config["api_transkription_anbieter"],
                diarization_enabled=self.diarization_checkbox.isChecked(),
            )
            diarize_fn = api_transcription_service.diarize_via_api_speakers

        settings = pipeline_service.PipelineSettings(
            source_path=self._source_path,
            output_dir=self._output_dir,
            language=self.language_combo.currentData(),
            min_speakers=self.min_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            max_speakers=self.max_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            allow_download=not self.offline_checkbox.isChecked(),
            resume_mode=self.resume_combo.currentData(),
            whisper_model=ermittle_whisper_modell(config),
            enable_diarization=self.diarization_checkbox.isChecked(),
        )

        self._set_controls_running(True)
        self.cancel_button.setEnabled(True)
        self.preview_edit.clear()
        self.speaker_table.setRowCount(0)
        self.apply_names_button.setEnabled(False)
        self.status_label.setText("Transkription wird gestartet …")
        self.transcription_status_label.setText("läuft")

        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self._transcription_worker = TranscriptionWorker(
            settings, self, transcribe_chunk_fn=transcribe_chunk_fn, diarize_fn=diarize_fn
        )
        self._transcription_worker.stage_changed.connect(self._on_transcription_stage_changed)
        self._transcription_worker.chunk_progress.connect(self._on_chunk_progress)
        self._transcription_worker.overall_progress.connect(self._on_overall_progress)
        self._transcription_worker.preview_updated.connect(self.preview_edit.setPlainText)
        self._transcription_worker.log_message.connect(self._on_log_message)
        self._transcription_worker.finished_ok.connect(self._on_transcription_finished_ok)
        self._transcription_worker.failed.connect(self._on_transcription_failed)
        self._transcription_worker.cancelled.connect(self._on_transcription_cancelled)
        self._transcription_worker.finished.connect(lambda: self._set_controls_running(False))
        self._transcription_worker.start()

    @staticmethod
    def _lokale_laufzeitumgebung_verfuegbar() -> bool:
        """Ist bereits eine Laufzeitumgebung mit den schweren ML-Paketen
        vorhanden? Weder in der gebauten EXE noch im Quellcode-Betrieb sind
        Torch/faster-whisper/pyannote von vornherein dabei -- 'bootstrap.py'
        richtet sie nur ein, wenn der gespeicherte Modus beim Programmstart
        bereits "lokal" war (siehe dort). Da dieser Code hier erst NACH
        'bootstrap.ensure_runtime_and_relaunch()' laeuft, ist zu diesem
        Zeitpunkt entweder die vorbereitete Umgebung bereits aktiv (dann ist
        'faster_whisper' tatsaechlich importierbar), oder die Einrichtung
        wurde uebersprungen (dann eben nicht) -- eine einfache
        Import-Pruefung deckt beide Faelle korrekt ab, ganz ohne
        Sonderbehandlung fuer 'sys.frozen'. Ohne diese Pruefung wuerde ein
        Wechsel auf "Lokal" mitten in der Sitzung erst tief in der Pipeline
        mit einem kryptischen Fehler scheitern."""
        return importlib.util.find_spec("faster_whisper") is not None

    def _verwendbarer_api_schluessel(self, schluessel_name: str) -> str | None:
        """Gemerkter Schluessel, sonst der nur fuer diese Sitzung eingegebene.

        Die Abfrage des Anmeldeinformationsspeichers MUSS abgesichert sein:
        Im lokalen Modus laeuft die Anwendung in der von 'bootstrap.py'
        verwalteten Laufzeitumgebung, und die enthaelt 'keyring' nicht
        (siehe 'requirements-laufzeit.txt'). Ungeschuetzt wuerde
        'load_api_key' dort mit 'SecretStoreUnavailableError' abbrechen --
        und zwar noch VOR dem Rueckgriff auf den Sitzungsschluessel, den der
        Anwender eben in den Einstellungen eingetippt hat. Genau derselbe
        Schutz steckt im Einstellungsdialog
        ('_gespeicherten_schluessel_laden')."""
        try:
            gemerkt = secret_store.load_api_key(schluessel_name)
        except secret_store.SecretStoreUnavailableError:
            gemerkt = None
        return gemerkt or self._session_api_keys.get(schluessel_name)

    def _cancel_transcription(self) -> None:
        if self._transcription_worker is not None:
            self._transcription_worker.request_cancel()
            self.status_label.setText("Abbruch angefordert -- wird nach dem aktuellen Chunk wirksam.")
            self.cancel_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Start / Abbruch / Fortschritt: Nachbearbeitung
    # ------------------------------------------------------------------
    def _start_protocol(self) -> None:
        if self._selected_transcript_path is None:
            show_error(
                self,
                "Kein Transkript ausgewählt",
                "Bitte zuerst eine Transkription durchführen oder ein vorhandenes Transkript auswählen.",
            )
            return
        if not self._selected_transcript_path.is_file():
            show_error(
                self, "Transkript nicht gefunden", f"Die Datei wurde nicht gefunden:\n{self._selected_transcript_path}"
            )
            return
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            probe_file = self._output_dir / ".schreibtest.tmp"
            probe_file.write_text("test", encoding="utf-8")
            probe_file.unlink()
        except OSError as error:
            show_error(self, "Ausgabeordner ungültig", f"In den Ausgabeordner kann nicht geschrieben werden:\n{error}")
            return

        systemprompt_text = self.systemprompt_editor.toPlainText().strip()
        if not systemprompt_text:
            show_error(
                self,
                "Kein Systemprompt",
                "Bitte einen Systemprompt eingeben oder oben eine Vorlage auswählen.",
            )
            return

        config = app_config.load_config()
        protocol_generate_fn: ProtocolGenerateFn | None = None
        if self.nachbearbeitung_api_radio.isChecked():
            eigener_schluessel = config["api_nachbearbeitung_eigener_schluessel"]
            schluessel_name = "nachbearbeitung" if eigener_schluessel else "transkription"
            api_key = self._verwendbarer_api_schluessel(schluessel_name)
            if not api_key:
                show_error(
                    self,
                    "Kein API-Schlüssel",
                    "Bitte zuerst in den Einstellungen einen API-Schlüssel für die Nachbearbeitung hinterlegen.",
                )
                return
            api_modell = config["api_nachbearbeitung_modell"]
            api_endpunkt = config["api_nachbearbeitung_endpunkt"]

            def _api_nachbearbeitung(prompt: str, system: str) -> dict[str, Any]:
                """Uebersetzt 'ApiProtocolError' in 'OllamaError'.

                'pipeline_service.run_protocol' behandelt einen
                fehlgeschlagenen Protokolllauf gnaedig -- aber nur fuer
                '(ProtocolValidationError, ollama_service.OllamaError)':
                dann wird der Fehler als 'protokoll_fehler' gemeldet, der
                Bericht trotzdem geschrieben und das fertige Transkript
                bleibt erhalten. Ein durchgereichter 'ApiProtocolError'
                (HTTP 401, Endpunkt nicht erreichbar, Zeitlimit) faellt
                stattdessen bis in den Worker und landet dort als
                nichtssagender "Unerwarteter Fehler"."""
                try:
                    return api_protocol_service.generate_json(
                        prompt,
                        system,
                        model=api_modell,
                        endpoint_url=api_endpunkt,
                        api_key=api_key,
                    )
                except api_protocol_service.ApiProtocolError as fehler:
                    raise ollama_service.OllamaError(str(fehler)) from fehler

            protocol_generate_fn = _api_nachbearbeitung

        settings = pipeline_service.ProtocolSettings(
            transcript_json_path=self._selected_transcript_path,
            output_dir=self._output_dir,
            ollama_model=config["ollama_modell"] or ollama_service.DEFAULT_MODEL,
            # Der im Fenster gewaehlte/bearbeitete Text wird direkt
            # mitgegeben und NICHT nach 'get_system_prompt_file()'
            # geschrieben: Was nur fuer einen Lauf gilt, gehoert nicht in
            # die gespeicherte Einstellung.
            system_prompt=systemprompt_text,
        )

        self._set_controls_running(True)
        self.protocol_cancel_button.setEnabled(True)
        self.status_label.setText("Nachbearbeitung wird gestartet …")
        self.protocol_status_label.setText("läuft")

        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self._protocol_worker = ProtocolWorker(settings, self, protocol_generate_fn=protocol_generate_fn)
        self._protocol_worker.stage_changed.connect(self._on_protocol_stage_changed)
        self._protocol_worker.overall_progress.connect(self._on_overall_progress)
        self._protocol_worker.log_message.connect(self._on_log_message)
        self._protocol_worker.finished_ok.connect(self._on_protocol_finished_ok)
        self._protocol_worker.failed.connect(self._on_protocol_failed)
        self._protocol_worker.cancelled.connect(self._on_protocol_cancelled)
        self._protocol_worker.finished.connect(lambda: self._set_controls_running(False))
        self._protocol_worker.start()

    def _cancel_protocol(self) -> None:
        if self._protocol_worker is not None:
            self._protocol_worker.request_cancel()
            self.status_label.setText("Abbruch angefordert …")
            self.protocol_cancel_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Gemeinsame Fortschrittsanzeigen
    # ------------------------------------------------------------------
    def _set_controls_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.protocol_start_button.setEnabled(not running)
        if not running:
            self.cancel_button.setEnabled(False)
            self.protocol_cancel_button.setEnabled(False)
            self._elapsed_timer.stop()

    def _update_elapsed_label(self) -> None:
        if self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        self.elapsed_label.setText(format_duration_human(elapsed))
        self._update_remaining_estimate(elapsed)

    def _update_remaining_estimate(self, elapsed: float) -> None:
        current, total = self._chunk_progress
        if current <= 0 or total <= 0:
            self.remaining_label.setText("--")
            return
        per_chunk = elapsed / current
        remaining_chunks = max(0, total - current)
        self.remaining_label.setText(format_duration_human(per_chunk * remaining_chunks))

    def _on_transcription_stage_changed(self, key: str, detail: str) -> None:
        self.status_label.setText(detail)
        self.transcription_status_label.setText(detail)

    def _on_protocol_stage_changed(self, key: str, detail: str) -> None:
        self.status_label.setText(detail)
        self.protocol_status_label.setText(detail)
        if key == "protokoll_fehlgeschlagen":
            self.protocol_status_label.setToolTip(detail)

    def _on_chunk_progress(self, current: int, total: int) -> None:
        self._chunk_progress = (current, total)
        self.chunk_progress_bar.setMaximum(max(total, 1))
        self.chunk_progress_bar.setValue(current)
        self.chunk_progress_bar.setFormat(f"Chunk {current} von {total}")

    def _on_overall_progress(self, fraction: float) -> None:
        self.overall_progress_bar.setValue(round(fraction * 100))

    def _on_log_message(self, message: str) -> None:
        self.status_label.setToolTip(message)

    def _on_transcription_finished_ok(self, result: pipeline_service.TranscriptionResult) -> None:
        self._last_transcription_result = result
        self._populate_speaker_table(result)
        self._set_transcript_path(result.export_paths.json)
        self.status_label.setText("Transkription abgeschlossen.")
        QMessageBox.information(
            self,
            "Transkription abgeschlossen",
            f"Ausgabedateien wurden erstellt in:\n{result.export_paths.txt.parent}\n\n"
            "Die Nachbearbeitung ist ein separater Schritt -- sie kann jetzt fuer dieses "
            "oder jederzeit fuer ein anderes Transkript gestartet werden.",
        )

    def _on_transcription_failed(self, message: str) -> None:
        self.status_label.setText("Fehler bei der Transkription.")
        show_error(self, "Transkription fehlgeschlagen", message)

    def _on_transcription_cancelled(self) -> None:
        self.status_label.setText("Transkription abgebrochen.")

    def _on_protocol_finished_ok(self, result: pipeline_service.ProtocolResult) -> None:
        self._last_protocol_result = result
        if result.protokoll_fehler:
            self.status_label.setText("Nachbearbeitung fehlgeschlagen.")
            QMessageBox.warning(
                self,
                "Nachbearbeitung fehlgeschlagen",
                "Die Protokollauswertung ist fehlgeschlagen, es wurde keine "
                "Protokolldatei geschrieben:\n"
                f"{result.protokoll_fehler}\n\n"
                "Das Transkript bleibt erhalten. Die Nachbearbeitung lässt sich erneut starten.",
            )
            return
        self.status_label.setText("Nachbearbeitung abgeschlossen.")
        protocol_paths = result.protocol_paths
        if protocol_paths is None:
            return
        QMessageBox.information(
            self,
            "Nachbearbeitung abgeschlossen",
            f"Protokolldateien wurden erstellt in:\n{protocol_paths[0].parent}",
        )

    def _on_protocol_failed(self, message: str) -> None:
        self.status_label.setText("Fehler bei der Nachbearbeitung.")
        show_error(self, "Nachbearbeitung fehlgeschlagen", message)

    def _on_protocol_cancelled(self) -> None:
        self.status_label.setText("Nachbearbeitung abgebrochen.")

    # ------------------------------------------------------------------
    # Sprechertabelle
    # ------------------------------------------------------------------
    def _populate_speaker_table(self, result: pipeline_service.TranscriptionResult) -> None:
        data = json.loads(result.export_paths.json.read_text(encoding="utf-8"))
        entries = data.get("sprecher_zuordnung", [])
        self.speaker_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            id_item = QTableWidgetItem(entry["sprecher_id"])
            id_item.setFlags(id_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 0, id_item)

            segments_item = QTableWidgetItem(str(entry["anzahl_segmente"]))
            segments_item.setFlags(segments_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 1, segments_item)

            duration_item = QTableWidgetItem(format_duration_human(entry["sprechdauer_sekunden"]))
            duration_item.setFlags(duration_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 2, duration_item)

            self.speaker_table.setItem(row, 3, QTableWidgetItem(entry["anzeigename"]))

        self.apply_names_button.setEnabled(len(entries) > 0)

    @staticmethod
    def _editable_flag():
        return Qt.ItemIsEditable

    def _apply_speaker_names(self) -> None:
        if self._last_transcription_result is None:
            return
        overrides: dict[str, str] = {}
        for row in range(self.speaker_table.rowCount()):
            id_zelle = self.speaker_table.item(row, 0)
            namens_zelle = self.speaker_table.item(row, 3)
            if id_zelle is None or namens_zelle is None:
                continue
            name = namens_zelle.text().strip()
            if name:
                overrides[id_zelle.text()] = name
        try:
            new_paths = export_service.reexport_with_new_names(
                self._last_transcription_result.export_paths.json, overrides
            )
        except OSError as error:
            show_error(self, "Export fehlgeschlagen", f"Die Ausgabedateien konnten nicht neu erzeugt werden:\n{error}")
            return
        self.preview_edit.setPlainText(new_paths.txt.read_text(encoding="utf-8")[:20000])
        QMessageBox.information(
            self, "Ausgaben aktualisiert", f"TXT/JSON/SRT/VTT wurden mit den neuen Namen neu erzeugt:\n{new_paths.txt.parent}"
        )
