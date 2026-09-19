"""Hauptfenster von Protokoll-Assistent Lokal (PySide6).

Die Verarbeitung laeuft immer in einem Hintergrund-Thread
(``gui.worker.PipelineWorker``), damit die Oberflaeche waehrend
Transkription, Diarisierung und lokaler Protokollauswertung nicht
einfriert.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs import DiagnosticsDialog, SystemPromptDialog, show_error
from gui.strings import PRIVACY_NOTICE
from gui.worker import PipelineWorker
from services import export_service, manifest_service, model_service, pipeline_service
from utils.app_config import load_config, update_config
from utils.paths import get_default_output_dir, get_system_prompt_file, get_work_dir
from utils.timeformat import format_duration_human

SUPPORTED_EXTENSION_NAMES = [
    "mp3", "mp4", "m4a", "wav", "aac", "flac", "ogg", "opus", "mov", "mkv", "webm",
]
SUPPORTED_EXTENSIONS = " ".join(f"*.{name}" for name in SUPPORTED_EXTENSION_NAMES)
SUPPORTED_SUFFIXES = {f".{name}" for name in SUPPORTED_EXTENSION_NAMES}

TRANSCRIPT_STAGES = {
    "datei_pruefung",
    "audio_normalisierung",
    "chunk_planung",
    "modell_laden",
    "transkription",
    "ausrichtung",
    "diarisierung",
    "zusammenfuehrung",
    "export_transkript",
}
PROTOCOL_STAGES = {"protokoll_auswertung", "export_protokoll"}


class MainWindow(QMainWindow):
    def __init__(self, initial_folder: Path | None = None, initial_file: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Protokoll-Assistent Lokal")
        self.resize(1100, 850)
        self.setAcceptDrops(True)

        config = load_config()
        self._configured_whisper_model: str | None = config.get("whisper_modell")
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

        self._worker: PipelineWorker | None = None
        self._start_time: float | None = None
        self._chunk_progress = (0, 0)
        self._last_result: pipeline_service.PipelineResult | None = None

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)

        self._build_ui()
        self._refresh_hardware_label()
        self._init_whisper_model_selection()

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

        privacy_label = QLabel(PRIVACY_NOTICE, self)
        privacy_label.setObjectName("PrivacyBanner")
        privacy_label.setWordWrap(True)
        root_layout.addWidget(privacy_label)

        splitter = QSplitter(self)
        root_layout.addWidget(splitter, stretch=1)

        left_panel = QWidget(self)
        splitter.addWidget(left_panel)
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(self._build_file_group())
        left_layout.addWidget(self._build_settings_group())
        left_layout.addWidget(self._build_resume_group())
        left_layout.addWidget(self._build_control_group())
        left_layout.addWidget(self._build_progress_group())
        left_layout.addStretch(1)

        right_panel = QWidget(self)
        splitter.addWidget(right_panel)
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(self._build_preview_group(), stretch=1)
        right_layout.addWidget(self._build_speaker_group(), stretch=1)

        splitter.setSizes([420, 680])

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("1. Eingabeordner und Datei", self)
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

    def _build_settings_group(self) -> QGroupBox:
        group = QGroupBox("2. Einstellungen", self)
        layout = QFormLayout(group)

        self.language_combo = QComboBox(self)
        self.language_combo.addItem("Deutsch (de)", "de")
        self.language_combo.addItem("Automatisch erkennen", None)
        layout.addRow("Sprache:", self.language_combo)

        self.whisper_model_combo = QComboBox(self)
        for option in model_service.WHISPER_MODELLE:
            self.whisper_model_combo.addItem(option.label, option.id)
        self.whisper_model_combo.currentIndexChanged.connect(self._update_whisper_model_hint)
        layout.addRow("Whisper-Modell:", self.whisper_model_combo)

        self.whisper_model_hint_label = QLabel("", self)
        self.whisper_model_hint_label.setWordWrap(True)
        layout.addRow(self.whisper_model_hint_label)

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

        self.offline_checkbox = QCheckBox("Offline-Modus (empfohlen)", self)
        self.offline_checkbox.setChecked(True)
        layout.addRow(self.offline_checkbox)

        self.protocol_checkbox = QCheckBox("Lokales Protokoll erstellen (Ollama)", self)
        self.protocol_checkbox.setChecked(True)
        layout.addRow(self.protocol_checkbox)

        prompt_button = QPushButton("Systemprompt bearbeiten …", self)
        prompt_button.clicked.connect(self._edit_system_prompt)
        layout.addRow(prompt_button)

        diagnostics_button = QPushButton("Systemdiagnose …", self)
        diagnostics_button.clicked.connect(self._open_diagnostics)
        layout.addRow(diagnostics_button)

        return group

    def _build_resume_group(self) -> QGroupBox:
        group = QGroupBox("3. Fortsetzen bei Langzeitaufnahmen", self)
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

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("4. Verarbeitung", self)
        layout = QHBoxLayout(group)

        self.start_button = QPushButton("Start", self)
        self.start_button.clicked.connect(self._start_processing)
        layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Abbrechen", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_processing)
        layout.addWidget(self.cancel_button)

        return group

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Fortschritt", self)
        layout = QFormLayout(group)

        self.status_label = QLabel("Bereit.", self)
        self.status_label.setWordWrap(True)
        layout.addRow("Status:", self.status_label)

        self.transcription_status_label = QLabel("wartet", self)
        layout.addRow("Transkriptionsstatus:", self.transcription_status_label)

        self.protocol_status_label = QLabel("wartet", self)
        layout.addRow("Status Ollama-Auswertung:", self.protocol_status_label)

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
    # Hilfsfunktionen
    # ------------------------------------------------------------------
    def _refresh_hardware_label(self) -> None:
        self.hardware_label.setText(model_service.get_gpu_description())

    def _init_whisper_model_selection(self) -> None:
        model_id = self._configured_whisper_model
        if not model_id:
            from utils import diagnostics

            vram_gb = diagnostics.check_gpu_vram().extra.get("vram_gb")
            ram_gb = diagnostics.check_ram().extra.get("ram_gb")
            model_id = model_service.empfehle_whisper_modell(vram_gb, ram_gb)

        index = self.whisper_model_combo.findData(model_id)
        if index < 0:
            index = self.whisper_model_combo.findData(model_service.WHISPER_MODEL_NAME)
        if index >= 0:
            self.whisper_model_combo.setCurrentIndex(index)
        self._update_whisper_model_hint()

    def _update_whisper_model_hint(self, *_args) -> None:
        model_id = self.whisper_model_combo.currentData()
        option = model_service.get_whisper_model_option(model_id)
        hinweis = option.hinweis if option else ""

        # Reicht der Speicher knapp nicht, wird trotzdem das gute Modell
        # empfohlen - der Nutzer kann Programme schließen und bekommt dann
        # die volle Qualität. Deshalb hier ein Hinweis statt eines stillen
        # Wechsels auf ein schwächeres Modell.
        if model_id == model_service.WHISPER_MODEL_NAME:
            from utils import diagnostics

            warnung = model_service.speicherwarnung(
                diagnostics.check_gpu_vram().extra.get("vram_gb"),
                diagnostics.check_ram().extra.get("ram_gb"),
            )
            if warnung:
                hinweis = f"{hinweis}\n\n⚠ {warnung}" if hinweis else f"⚠ {warnung}"

        self.whisper_model_hint_label.setText(hinweis)
        if model_id:
            update_config(whisper_modell=model_id)

    def _toggle_speaker_limits(self, checked: bool) -> None:
        self.min_speakers_spin.setEnabled(checked)
        self.max_speakers_spin.setEnabled(checked)

    def _toggle_diarization(self, checked: bool) -> None:
        self.limit_speakers_checkbox.setEnabled(checked)
        if not checked:
            self.limit_speakers_checkbox.setChecked(False)
        self.min_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())
        self.max_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())

    def _choose_input_folder(self) -> None:
        start_dir = str(self._input_folder) if self._input_folder else str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Eingabeordner wählen", start_dir)
        if directory:
            self._set_input_folder(Path(directory))

    def _set_input_folder(self, folder: Path) -> None:
        self._input_folder = folder
        self.folder_label.setText(str(folder))
        self._populate_file_list(folder)
        update_config(eingabeordner=str(folder))

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

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", str(self._output_dir))
        if not directory:
            return
        self._output_dir = Path(directory)
        self.output_label.setText(str(self._output_dir))
        update_config(ausgabeordner=str(self._output_dir))

    def _refresh_resume_status(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            return
        try:
            file_hash = manifest_service.compute_file_hash(self._source_path)
            work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
            manifest = manifest_service.load_manifest(work_dir)
        except OSError as error:
            self.resume_status_label.setText(f"Datei konnte nicht gelesen werden: {error}")
            return

        if manifest is None:
            self.resume_status_label.setText("Keine vorherige Verarbeitung für diese Datei gefunden.")
            self.resume_combo.setCurrentIndex(1)  # neu_beginnen, da nichts zum Fortsetzen da ist
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
        self.resume_combo.setCurrentIndex(0)  # fortsetzen als Standard

    def _open_intermediate_folder(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            show_error(self, "Keine Datei ausgewählt", "Bitte zuerst eine Datei auswählen.")
            return
        file_hash = manifest_service.compute_file_hash(self._source_path)
        work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(work_dir)))

    def _edit_system_prompt(self) -> None:
        dialog = SystemPromptDialog(self)
        dialog.exec()

    def _open_diagnostics(self) -> None:
        dialog = DiagnosticsDialog(self._output_dir, self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Start / Abbruch / Fortschritt
    # ------------------------------------------------------------------
    def _start_processing(self) -> None:
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
        if not get_system_prompt_file().is_file():
            show_error(
                self,
                "Systemprompt fehlt",
                "Die Datei 'einstellungen/systemprompt_protokoll.txt' fehlt. Bitte über "
                "'Systemprompt bearbeiten' einmal speichern.",
            )
            return

        settings = pipeline_service.PipelineSettings(
            source_path=self._source_path,
            output_dir=self._output_dir,
            language=self.language_combo.currentData(),
            min_speakers=self.min_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            max_speakers=self.max_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            allow_download=not self.offline_checkbox.isChecked(),
            resume_mode=self.resume_combo.currentData(),
            run_protocol=self.protocol_checkbox.isChecked(),
            whisper_model=self.whisper_model_combo.currentData() or model_service.WHISPER_MODEL_NAME,
            enable_diarization=self.diarization_checkbox.isChecked(),
        )

        self._set_controls_running(True)
        self.preview_edit.clear()
        self.speaker_table.setRowCount(0)
        self.apply_names_button.setEnabled(False)
        self.status_label.setText("Verarbeitung wird gestartet …")
        self.transcription_status_label.setText("läuft")
        self.protocol_status_label.setText("wartet" if settings.run_protocol else "deaktiviert")

        import time

        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self._worker = PipelineWorker(settings, self)
        self._worker.stage_changed.connect(self._on_stage_changed)
        self._worker.chunk_progress.connect(self._on_chunk_progress)
        self._worker.overall_progress.connect(self._on_overall_progress)
        self._worker.preview_updated.connect(self.preview_edit.setPlainText)
        self._worker.log_message.connect(self._on_log_message)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(lambda: self._set_controls_running(False))
        self._worker.start()

    def _cancel_processing(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self.status_label.setText("Abbruch angefordert -- wird nach dem aktuellen Chunk wirksam.")
            self.cancel_button.setEnabled(False)

    def _set_controls_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if not running:
            self._elapsed_timer.stop()

    def _update_elapsed_label(self) -> None:
        if self._start_time is None:
            return
        import time

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

    def _on_stage_changed(self, key: str, detail: str) -> None:
        self.status_label.setText(detail)
        if key in TRANSCRIPT_STAGES:
            self.transcription_status_label.setText(detail)
        if key in PROTOCOL_STAGES:
            self.protocol_status_label.setText(detail)
        if key == "abgeschlossen":
            self.transcription_status_label.setText("abgeschlossen")
            if self.protocol_checkbox.isChecked():
                self.protocol_status_label.setText("abgeschlossen")

    def _on_chunk_progress(self, current: int, total: int) -> None:
        self._chunk_progress = (current, total)
        self.chunk_progress_bar.setMaximum(max(total, 1))
        self.chunk_progress_bar.setValue(current)
        self.chunk_progress_bar.setFormat(f"Chunk {current} von {total}")

    def _on_overall_progress(self, fraction: float) -> None:
        self.overall_progress_bar.setValue(round(fraction * 100))

    def _on_log_message(self, message: str) -> None:
        self.status_label.setToolTip(message)

    def _on_finished_ok(self, result: pipeline_service.PipelineResult) -> None:
        self._last_result = result
        self.status_label.setText("Verarbeitung abgeschlossen.")
        self._populate_speaker_table(result)
        QMessageBox.information(
            self,
            "Verarbeitung abgeschlossen",
            f"Ausgabedateien wurden erstellt in:\n{result.export_paths.txt.parent}",
        )

    def _on_failed(self, message: str) -> None:
        self.status_label.setText("Fehler bei der Verarbeitung.")
        show_error(self, "Verarbeitung fehlgeschlagen", message)

    def _on_cancelled(self) -> None:
        self.status_label.setText("Verarbeitung abgebrochen.")

    # ------------------------------------------------------------------
    # Sprechertabelle
    # ------------------------------------------------------------------
    def _populate_speaker_table(self, result: pipeline_service.PipelineResult) -> None:
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
        if self._last_result is None:
            return
        overrides: dict[str, str] = {}
        for row in range(self.speaker_table.rowCount()):
            # Eine Zelle kann leer sein - dann liefert "item" None.
            id_zelle = self.speaker_table.item(row, 0)
            namens_zelle = self.speaker_table.item(row, 3)
            if id_zelle is None or namens_zelle is None:
                continue
            name = namens_zelle.text().strip()
            if name:
                overrides[id_zelle.text()] = name
        try:
            new_paths = export_service.reexport_with_new_names(self._last_result.export_paths.json, overrides)
        except OSError as error:
            show_error(self, "Export fehlgeschlagen", f"Die Ausgabedateien konnten nicht neu erzeugt werden:\n{error}")
            return
        self.preview_edit.setPlainText(new_paths.txt.read_text(encoding="utf-8")[:20000])
        QMessageBox.information(
            self, "Ausgaben aktualisiert", f"TXT/JSON/SRT/VTT wurden mit den neuen Namen neu erzeugt:\n{new_paths.txt.parent}"
        )
