"""Erster-Start-Einrichtungsassistent -- macht die Anwendung auf jedem PC
selbsterklaerend nutzbar, ohne manuelle Vorbereitung:

1. Willkommen -- kurze Erklaerung, Datenschutzhinweis.
2. Einrichtung -- FFmpeg/Ollama werden bei Bedarf automatisch heruntergeladen,
   danach Whisper-/pyannote-/Ollama-Modell.
3. Systemtest -- zeigt, ob alles vorhanden und einsatzbereit ist.
4. Eingabeordner -- der Nutzer waehlt den Ordner mit seinen Aufnahmen.

Nach Schritt 4 wird ``setup_finished`` mit dem gewaehlten Ordner (und
optional einer vorausgewaehlten Datei) ausgeloest; ``app.py`` oeffnet
danach das eigentliche Hauptfenster.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs import DiagnosticsRunner, render_check_item
from gui.strings import PRIVACY_NOTICE
from services import model_service

STEP_NAMES = ["Willkommen", "Einrichtung", "Systemtest", "Modell", "Eingabeordner"]

SUPPORTED_EXTENSIONS = {
    ".mp3", ".mp4", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".mov", ".mkv", ".webm",
}


class WelcomePage(QWidget):
    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Willkommen bei Protokoll-Assistent Lokal", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Diese Anwendung transkribiert Audio- und Videoaufnahmen, trennt Sprecher "
            "und erstellt ein Protokoll -- vollständig auf diesem Computer.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        steps = QLabel(
            "So funktioniert die Einrichtung:\n\n"
            "1. Benötigte Programme und Modelle werden automatisch heruntergeladen\n"
            "    (faster-whisper, pyannote, ggf. FFmpeg/Ollama) -- passend zu diesem Rechner.\n"
            "2. Ein Systemtest prüft, ob alles vorhanden und einsatzbereit ist.\n"
            "3. Sie wählen einen Ordner mit Ihren Aufnahmen aus.\n"
            "4. Danach können Sie sofort mit der Transkription beginnen.",
            self,
        )
        steps.setWordWrap(True)
        layout.addWidget(steps)
        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        start_button = QPushButton("Los geht's", self)
        start_button.setObjectName("PrimaryButton")
        start_button.clicked.connect(self.continue_requested.emit)
        button_row.addWidget(start_button)
        layout.addLayout(button_row)


class InstallWorker(QThread):
    log_line = Signal(str)
    request_token = Signal()
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token_result: str | None = None
        self._token_event = threading.Event()

    def provide_token(self, token: str | None) -> None:
        self._token_result = token
        self._token_event.set()

    def _get_token(self) -> str | None:
        self._token_event.clear()
        self.request_token.emit()
        self._token_event.wait()
        return self._token_result

    def run(self) -> None:
        try:
            from services import ffmpeg_service, model_download_service, ollama_service
            from utils.paths import get_app_dir

            self.log_line.emit("Prüfe FFmpeg ...")
            ffmpeg_service.ensure_ffmpeg_available(progress_cb=self.log_line.emit)

            self.log_line.emit("\nPrüfe Ollama ...")
            installer_dir = get_app_dir() / "runtime" / "installer"
            ollama_service.ensure_ollama_or_offer_installer(installer_dir, progress_cb=self.log_line.emit)

            self.log_line.emit(
                "\nLade Sprecher-Erkennungs- und Ollama-Modell herunter (kann einige "
                "Minuten dauern) ..."
            )
            results = {
                "pyannote": model_download_service.download_pyannote(
                    self.log_line.emit, get_token=self._get_token
                ),
                "ollama_modell": model_download_service.download_ollama_model(self.log_line.emit),
            }
            self.log_line.emit(
                "\nHinweis: Das Transkriptionsmodell wird im naechsten Schritt "
                "('Modell') anhand einer Hardware-Empfehlung ausgewaehlt und heruntergeladen."
            )

            self.finished_ok.emit(results)
        except Exception as error:  # keine Tracebacks im Log -- nur die Kurzfassung
            self.failed.emit(str(error))


class InstallPage(QWidget):
    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        self._worker: InstallWorker | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Einrichtung wird vorbereitet", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Fehlende Komponenten werden jetzt automatisch heruntergeladen. Es werden "
            "dabei ausschließlich Programme/Modelle geladen -- niemals Audio- oder "
            "Videodaten.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.log_edit = QPlainTextEdit(self)
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, stretch=1)

        button_row = QHBoxLayout()
        self.retry_button = QPushButton("Erneut versuchen", self)
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self.start)
        button_row.addWidget(self.retry_button)
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_requested.emit)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

    def start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.retry_button.setVisible(False)
        self.continue_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.log_edit.clear()

        self._worker = InstallWorker(self)
        self._worker.log_line.connect(self.log_edit.appendPlainText)
        self._worker.request_token.connect(self._ask_for_token)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _ask_for_token(self) -> None:
        token, accepted = QInputDialog.getText(
            self,
            "Hugging-Face-Token",
            "Für das pyannote-Modell wird ein Hugging-Face-Token benötigt.\n"
            "Der Token wird NICHT gespeichert oder angezeigt.\n\n"
            "HF_TOKEN (leer lassen zum Überspringen):",
            QLineEdit.Password,
        )
        if self._worker is not None:
            self._worker.provide_token(token.strip() if accepted and token else None)

    def _on_finished(self, results: dict) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.log_edit.appendPlainText("\nEinrichtung abgeschlossen.")
        missing = [key for key, ok in results.items() if not ok]
        if missing:
            self.log_edit.appendPlainText(
                "Hinweis: Einige Komponenten konnten nicht automatisch eingerichtet "
                "werden: " + ", ".join(missing) + ". Sie können trotzdem fortfahren "
                "und dies später über die Systemdiagnose prüfen."
            )
        self.continue_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 1)
        self.log_edit.appendPlainText(f"\nFEHLER: {message}")
        self.retry_button.setVisible(True)
        self.continue_button.setEnabled(True)


class DiagnosticsPage(QWidget):
    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        self.last_results: list = []
        self._thread: DiagnosticsRunner | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Systemtest", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("Es wird geprüft, ob alle benötigten Komponenten einsatzbereit sind.", self)
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Prüfung", "Ergebnis"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self.summary_label = QLabel("", self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        button_row = QHBoxLayout()
        self.retry_button = QPushButton("Erneut prüfen", self)
        self.retry_button.clicked.connect(self.start)
        button_row.addWidget(self.retry_button)
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_requested.emit)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

    def start(self) -> None:
        from utils.paths import get_default_output_dir

        self.retry_button.setEnabled(False)
        self.summary_label.setText("Prüfung läuft ...")

        self._thread = DiagnosticsRunner(get_default_output_dir(), self)
        self._thread.finished_with_results.connect(self._show_results)
        self._thread.start()

    def _show_results(self, results) -> None:
        self.retry_button.setEnabled(True)
        self.last_results = results
        self.table.setRowCount(len(results))
        for row, check in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(check.label))
            self.table.setItem(row, 1, render_check_item(check))

        critical_failed = [check for check in results if check.critical and not check.ok]
        if critical_failed:
            self.summary_label.setText(
                "Es fehlen noch wichtige Komponenten: "
                + ", ".join(check.label for check in critical_failed)
                + ". Bitte zur Einrichtung zurückgehen oder erneut prüfen."
            )
        else:
            self.summary_label.setText("Alle wichtigen Prüfungen sind erfolgreich.")
        self.continue_button.setEnabled(not critical_failed)


EIGENE_MODELL_ID = "__eigene_modell_id__"


class WhisperDownloadWorker(QThread):
    log_line = Signal(str)
    finished_ok = Signal(bool)

    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self._model_name = model_name

    def run(self) -> None:
        from services import model_download_service

        try:
            ok = model_download_service.download_whisper_and_alignment(
                self.log_line.emit, model_name=self._model_name
            )
            self.finished_ok.emit(ok)
        except Exception as error:  # keine Tracebacks im Log -- nur die Kurzfassung
            self.log_line.emit(f"FEHLER: {error}")
            self.finished_ok.emit(False)


class ModelChoicePage(QWidget):
    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        self._worker: WhisperDownloadWorker | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Whisper-Modell auswählen", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Größere Modelle transkribieren genauer, benötigen aber mehr GPU-Speicher "
            "und Zeit. Basierend auf dem Systemtest wird unten ein passendes Modell "
            "vorausgewählt -- Sie können jederzeit ein anderes wählen.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.recommendation_label = QLabel("", self)
        self.recommendation_label.setWordWrap(True)
        layout.addWidget(self.recommendation_label)

        self.model_combo = QComboBox(self)
        for option in model_service.WHISPER_MODELLE:
            self.model_combo.addItem(option.label, option.id)
        self.model_combo.addItem("Eigene Modell-ID eingeben …", EIGENE_MODELL_ID)
        self.model_combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self.model_combo)

        self.custom_model_edit = QLineEdit(self)
        self.custom_model_edit.setPlaceholderText(
            "z. B. eine eigene faster-whisper-/CTranslate2-Modell-ID oder Hugging-Face-Repo-ID"
        )
        self.custom_model_edit.setVisible(False)
        layout.addWidget(self.custom_model_edit)

        self.hinweis_label = QLabel("", self)
        self.hinweis_label.setWordWrap(True)
        self.hinweis_label.setObjectName("PageSubtitle")
        layout.addWidget(self.hinweis_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 1)
        layout.addWidget(self.progress_bar)

        self.log_edit = QPlainTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(140)
        layout.addWidget(self.log_edit)

        button_row = QHBoxLayout()
        self.download_button = QPushButton("Dieses Modell herunterladen", self)
        self.download_button.clicked.connect(self._start_download)
        button_row.addWidget(self.download_button)
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._confirm)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

        self._on_selection_changed()

    def apply_recommendation(self, diagnostics_results: list) -> None:
        empfehlung = model_service.whisper_empfehlung_aus_diagnose(diagnostics_results)
        option = model_service.get_whisper_model_option(empfehlung)
        label = option.label if option else empfehlung
        self.recommendation_label.setText(f"Empfehlung für diesen Computer: {label}")

        from utils.app_config import load_config

        gespeichert = load_config().get("whisper_modell")
        ziel_id = gespeichert or empfehlung
        index = self.model_combo.findData(ziel_id)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self._on_selection_changed()

    def _on_selection_changed(self, *_args) -> None:
        model_id = self.model_combo.currentData()
        is_custom = model_id == EIGENE_MODELL_ID
        self.custom_model_edit.setVisible(is_custom)
        if is_custom:
            self.hinweis_label.setText(
                "Freie Eingabe: Die Modell-ID muss von faster-whisper ("
                "CTranslate2) unterstützt werden."
            )
        else:
            option = model_service.get_whisper_model_option(model_id)
            self.hinweis_label.setText(option.hinweis if option else "")
        self.continue_button.setEnabled(False)

    def _selected_model_name(self) -> str | None:
        model_id = self.model_combo.currentData()
        if model_id == EIGENE_MODELL_ID:
            eigene_id = self.custom_model_edit.text().strip()
            return eigene_id or None
        return model_id

    def _start_download(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        model_name = self._selected_model_name()
        if not model_name:
            self.log_edit.appendPlainText("Bitte zuerst eine Modell-ID eingeben.")
            return

        self.download_button.setEnabled(False)
        self.continue_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.log_edit.clear()

        self._worker = WhisperDownloadWorker(model_name, self)
        self._worker.log_line.connect(self.log_edit.appendPlainText)
        self._worker.finished_ok.connect(self._on_download_finished)
        self._worker.start()

    def _on_download_finished(self, ok: bool) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.download_button.setEnabled(True)
        if ok:
            self.log_edit.appendPlainText("\nModell einsatzbereit.")
        else:
            self.log_edit.appendPlainText(
                "\nDas Modell konnte nicht geladen werden. Sie können es erneut "
                "versuchen oder trotzdem fortfahren (Prüfung später über die "
                "Systemdiagnose möglich)."
            )
        self.continue_button.setEnabled(True)

    def _confirm(self) -> None:
        from utils.app_config import update_config

        model_name = self._selected_model_name()
        if model_name:
            update_config(whisper_modell=model_name)
        self.continue_requested.emit()


class InputFolderPage(QWidget):
    folder_confirmed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        self._folder: Path | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Eingabeordner auswählen", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Wählen Sie den Ordner, in dem Ihre Audio- oder Videoaufnahmen liegen. "
            "Unterstützte Dateien in diesem Ordner werden unten aufgelistet.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel("Kein Ordner ausgewählt", self)
        self.folder_label.setWordWrap(True)
        choose_button = QPushButton("Ordner wählen …", self)
        choose_button.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose_button)
        folder_row.addWidget(self.folder_label, stretch=1)
        layout.addLayout(folder_row)

        self.file_list = QListWidget(self)
        layout.addWidget(self.file_list, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter zur Anwendung", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._confirm)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

        self._preselect_last_used_folder()

    def _preselect_last_used_folder(self) -> None:
        from utils.app_config import load_config

        config = load_config()
        candidate = config.get("eingabeordner")
        if candidate and Path(candidate).is_dir():
            self._set_folder(Path(candidate))

    def _choose_folder(self) -> None:
        start_dir = str(self._folder) if self._folder else str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Eingabeordner wählen", start_dir)
        if directory:
            self._set_folder(Path(directory))

    def _set_folder(self, folder: Path) -> None:
        from utils.app_config import update_config

        self._folder = folder
        self.folder_label.setText(str(folder))
        self.file_list.clear()
        try:
            files = sorted(
                path for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        except OSError:
            files = []
        for file_path in files:
            self.file_list.addItem(file_path.name)
        self.continue_button.setEnabled(True)
        update_config(eingabeordner=str(folder))

    def _confirm(self) -> None:
        if self._folder is None:
            return
        selected_items = self.file_list.selectedItems()
        filename = selected_items[0].text() if selected_items else ""
        self.folder_confirmed.emit(str(self._folder), filename)


class SetupWizard(QWidget):
    """Container fuer alle fuenf Einrichtungsseiten."""

    setup_finished = Signal(str, str)  # (eingabeordner, vorausgewaehlte_datei_oder_leer)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardRoot")
        self.setWindowTitle("Protokoll-Assistent Lokal -- Einrichtung")
        self.resize(860, 660)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        privacy = QLabel(PRIVACY_NOTICE, self)
        privacy.setObjectName("PrivacyBanner")
        privacy.setWordWrap(True)
        outer.addWidget(privacy)

        step_row = QHBoxLayout()
        self._step_labels: list[QLabel] = []
        for index, name in enumerate(STEP_NAMES):
            label = QLabel(f"{index + 1}. {name}", self)
            label.setObjectName("StepIndicator")
            step_row.addWidget(label)
            self._step_labels.append(label)
            if index < len(STEP_NAMES) - 1:
                arrow = QLabel("→", self)
                arrow.setObjectName("StepIndicator")
                step_row.addWidget(arrow)
        step_row.addStretch(1)
        outer.addLayout(step_row)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack, stretch=1)

        self.welcome_page = WelcomePage(self)
        self.install_page = InstallPage(self)
        self.diagnostics_page = DiagnosticsPage(self)
        self.model_page = ModelChoicePage(self)
        self.folder_page = InputFolderPage(self)
        for page in (
            self.welcome_page,
            self.install_page,
            self.diagnostics_page,
            self.model_page,
            self.folder_page,
        ):
            self.stack.addWidget(page)

        self.welcome_page.continue_requested.connect(lambda: self._go_to(1))
        self.install_page.continue_requested.connect(lambda: self._go_to(2))
        self.diagnostics_page.continue_requested.connect(lambda: self._go_to(3))
        self.model_page.continue_requested.connect(lambda: self._go_to(4))
        self.folder_page.folder_confirmed.connect(self.setup_finished.emit)

        self._go_to(0)

    def _go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for label_index, label in enumerate(self._step_labels):
            label.setObjectName("StepIndicatorActive" if label_index == index else "StepIndicator")
            label.style().unpolish(label)
            label.style().polish(label)
        if index == 1:
            self.install_page.start()
        elif index == 2:
            self.diagnostics_page.start()
        elif index == 3:
            self.model_page.apply_recommendation(self.diagnostics_page.last_results)
