"""Erster-Start-Einrichtungsassistent -- macht die Anwendung auf jedem PC
selbsterklaerend nutzbar, ohne manuelle Vorbereitung:

1. Willkommen -- kurze Erklaerung, Datenschutzhinweis.
2. Rechner-Analyse -- BEVOR etwas geladen wird: wie gut laufen welche Modelle
   auf diesem Computer? Der Anwender bekommt die Einschaetzung zu sehen.
3. Einrichtung -- FFmpeg/Ollama werden bei Bedarf automatisch heruntergeladen,
   danach Whisper-/pyannote-/Ollama-Modell (passend zur Analyse).
4. Systemtest -- zeigt, ob alles vorhanden und einsatzbereit ist; Fehlendes
   (FFmpeg, Ollama, Ollama-Modell) laesst sich dort nachladen.
5. Modell -- Whisper-Modell waehlen und laden.
6. Eingabeordner -- der Nutzer waehlt den Ordner mit seinen Aufnahmen.

Nach Schritt 6 wird ``setup_finished`` mit dem gewaehlten Ordner (und
optional einer vorausgewaehlten Datei) ausgeloest; ``app.py`` oeffnet
danach das eigentliche Hauptfenster.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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

from protokoll_assistent.gui.dialogs import DiagnosticsRunner, render_check_item
from protokoll_assistent.gui.strings import PRIVACY_NOTICE
from protokoll_assistent.services import model_service, rechner_analyse_service

STEP_NAMES = ["Willkommen", "Rechner-Analyse", "Einrichtung", "Systemtest", "Modell", "Eingabeordner"]

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
            "1. Zuerst wird dieser Rechner analysiert: Sie sehen, welche Modelle gut\n"
            "    laufen und welche eher nicht.\n"
            "2. Benötigte Programme und Modelle werden automatisch heruntergeladen\n"
            "    (faster-whisper, pyannote, ggf. FFmpeg/Ollama) -- passend zu diesem Rechner.\n"
            "3. Ein Systemtest prüft, ob alles vorhanden und einsatzbereit ist.\n"
            "4. Sie wählen einen Ordner mit Ihren Aufnahmen aus.\n"
            "5. Danach können Sie sofort mit der Transkription beginnen.",
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


class RechnerAnalyseWorker(QThread):
    """Ermittelt die Hardware und bewertet die Modelle. Laedt nichts herunter."""

    fertig = Signal(object)  # rechner_analyse_service.Analyse

    def __init__(self, ordner: Path, parent=None):
        super().__init__(parent)
        self._ordner = ordner

    def run(self) -> None:
        profil = rechner_analyse_service.ermittle_profil(self._ordner)
        self.fertig.emit(rechner_analyse_service.analysiere(profil))


_STUFEN_ANZEIGE = {
    rechner_analyse_service.GUT: ("Läuft gut", Qt.darkGreen),
    rechner_analyse_service.MAESSIG: ("Läuft langsam / knapp", Qt.darkYellow),
    rechner_analyse_service.NICHT: ("Eher nicht geeignet", Qt.red),
}


class RechnerAnalysePage(QWidget):
    """Erster inhaltlicher Schritt: Der Rechner wird analysiert, bevor
    irgendetwas heruntergeladen wird. Die Seite zeigt je Modell, wie gut es
    hier laufen wird, und merkt sich die Empfehlung (``analyse``)."""

    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        self.analyse: rechner_analyse_service.Analyse | None = None
        self._worker: RechnerAnalyseWorker | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Rechner-Analyse", self)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Bevor etwas heruntergeladen wird, wird geprüft, welche Modelle auf diesem "
            "Computer gut laufen. Die Einschätzung ist eine Schätzung – Sie können später "
            "trotzdem jedes Modell wählen.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.profil_label = QLabel("", self)
        self.profil_label.setWordWrap(True)
        layout.addWidget(self.profil_label)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Modell", "Einschätzung", "Hinweis"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        self.hinweis_label = QLabel("", self)
        self.hinweis_label.setWordWrap(True)
        layout.addWidget(self.hinweis_label)

        button_row = QHBoxLayout()
        self.retry_button = QPushButton("Erneut analysieren", self)
        self.retry_button.clicked.connect(self.start)
        button_row.addWidget(self.retry_button)
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._bestaetigen)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

    def start(self) -> None:
        from protokoll_assistent.utils.paths import get_default_output_dir

        if self._worker is not None and self._worker.isRunning():
            return
        self.retry_button.setEnabled(False)
        self.continue_button.setEnabled(False)
        self.profil_label.setText("Der Rechner wird analysiert ...")
        self._worker = RechnerAnalyseWorker(get_default_output_dir(), self)
        self._worker.fertig.connect(self._zeige_analyse)
        self._worker.start()

    def _zeige_analyse(self, analyse) -> None:
        self.analyse = analyse
        self.retry_button.setEnabled(True)
        self.continue_button.setEnabled(True)
        self.profil_label.setText("Dieser Rechner:\n" + rechner_analyse_service.beschreibe_profil(analyse.profil))

        self.table.setRowCount(len(analyse.bewertungen))
        for zeile, bewertung in enumerate(analyse.bewertungen):
            empfohlen = analyse.empfehlung.get(bewertung.bereich) == bewertung.modell_id
            name = f"{bewertung.bereich}: {bewertung.name}" + ("  ★ empfohlen" if empfohlen else "")
            self.table.setItem(zeile, 0, QTableWidgetItem(name))
            text, farbe = _STUFEN_ANZEIGE[bewertung.stufe]
            stufe_item = QTableWidgetItem(text)
            stufe_item.setForeground(farbe)
            self.table.setItem(zeile, 1, stufe_item)
            self.table.setItem(zeile, 2, QTableWidgetItem(bewertung.text))
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)

        zeilen = [f"• {hinweis}" for hinweis in analyse.hinweise]
        gewaehlt = analyse.empfehlung.get(rechner_analyse_service.BEREICH_NACHBEARBEITUNG)
        if gewaehlt:
            zeilen.append(f"Für die Nachbearbeitung wird {gewaehlt} vorbereitet.")
        self.hinweis_label.setText("\n".join(zeilen))

    def _bestaetigen(self) -> None:
        self.uebernehme_empfehlung()
        self.continue_requested.emit()

    def uebernehme_empfehlung(self) -> None:
        """Stellt das empfohlene Sprachmodell ein -- aber nur, wo der Anwender
        noch nichts Eigenes gewaehlt hat (Einstellung steht noch auf dem
        Standardwert). Eine bewusste Wahl wird nie ueberschrieben."""
        if self.analyse is None:
            return
        from protokoll_assistent.services import ollama_service
        from protokoll_assistent.utils.app_config import load_config, update_config

        empfohlen = self.analyse.empfehlung.get(rechner_analyse_service.BEREICH_NACHBEARBEITUNG)
        if not empfohlen:
            return
        konfig = load_config()
        aenderungen = {
            schluessel: empfohlen
            for schluessel in ("ollama_modell", "chatbot_ollama_modell")
            if konfig.get(schluessel) == ollama_service.DEFAULT_MODEL
        }
        if aenderungen and empfohlen != ollama_service.DEFAULT_MODEL:
            update_config(**aenderungen)


def werkzeuge_nachladen(log) -> dict[str, bool]:
    """Stellt FFmpeg und Ollama bereit (Download, falls sie fehlen).

    Gemeinsam genutzt von der Einrichtung und vom Nachladen im Systemtest.
    Das Ergebnis sagt je Werkzeug, ob es danach wirklich da ist -- frueher
    stand bei einem fehlgeschlagenen Download nur eine Zeile im Protokoll,
    und die Einrichtung meldete trotzdem "abgeschlossen"."""
    from protokoll_assistent.services import ffmpeg_service, ollama_service
    from protokoll_assistent.utils.paths import get_app_dir

    log("Prüfe FFmpeg ...")
    ffmpeg_service.ensure_ffmpeg_available(progress_cb=log)
    ffmpeg_da = ffmpeg_service.find_ffmpeg() is not None and ffmpeg_service.find_ffprobe() is not None
    if not ffmpeg_da:
        log("FFmpeg fehlt weiterhin (Grund siehe oben).")

    log("\nPrüfe Ollama ...")
    installer_dir = get_app_dir() / "runtime" / "installer"
    ollama_da = bool(ollama_service.ensure_ollama_or_offer_installer(installer_dir, progress_cb=log))
    if not ollama_da:
        log(
            "Ollama ist noch nicht einsatzbereit. Wurde der Installer gestartet, bitte die "
            "Installation abschließen und danach im Systemtest „Erneut prüfen“ wählen."
        )
    return {"ffmpeg": ffmpeg_da, "ollama": ollama_da}


_KOMPONENTEN_NAMEN = {
    "ffmpeg": "FFmpeg",
    "ollama": "Ollama",
    "pyannote": "Sprecher-Erkennung (pyannote)",
    "ollama_modell": "Ollama-Modell",
}


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
            from protokoll_assistent.services import model_download_service, ollama_service
            from protokoll_assistent.utils import app_config

            werkzeuge = werkzeuge_nachladen(self.log_line.emit)

            self.log_line.emit(
                "\nLade Sprecher-Erkennungs- und Ollama-Modell herunter (kann einige "
                "Minuten dauern) ..."
            )
            results = {
                **werkzeuge,
                "pyannote": model_download_service.download_pyannote(
                    self.log_line.emit, get_token=self._get_token
                ),
                "ollama_modell": model_download_service.download_ollama_model(
                    self.log_line.emit, app_config.load_config()["ollama_modell"] or ollama_service.DEFAULT_MODEL
                ),
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
        missing = [_KOMPONENTEN_NAMEN.get(key, key) for key, ok in results.items() if not ok]
        if missing:
            self.log_edit.appendPlainText(
                "Hinweis: Einige Komponenten konnten nicht automatisch eingerichtet "
                "werden: " + ", ".join(missing) + ". Die Gründe stehen weiter oben. "
                "Sie können trotzdem fortfahren und dies später über die Systemdiagnose "
                "prüfen – dort lassen sich FFmpeg, Ollama und das Ollama-Modell auch "
                "nachladen."
            )
        self.continue_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 1)
        self.log_edit.appendPlainText(f"\nFEHLER: {message}")
        self.retry_button.setVisible(True)
        self.continue_button.setEnabled(True)


# Pruefungen des Systemtests, die sich ueber "Fehlendes nachladen" beheben lassen.
NACHLADBARE_PRUEFUNGEN = {"ffmpeg", "ffprobe", "ollama_installed", "ollama_model"}


class NachladenWorker(QThread):
    """Laedt im Systemtest fehlende Werkzeuge nach: FFmpeg, Ollama und das
    gewaehlte Ollama-Modell. Meldet je Schritt, ob er gelungen ist -- und bei
    einem Fehlschlag den Grund."""

    log_line = Signal(str)
    finished_ok = Signal(dict)

    def run(self) -> None:
        try:
            from protokoll_assistent.services import model_download_service, ollama_service
            from protokoll_assistent.utils import app_config

            ergebnis = werkzeuge_nachladen(self.log_line.emit)
            if ergebnis["ollama"]:
                modell = app_config.load_config()["ollama_modell"] or ollama_service.DEFAULT_MODEL
                self.log_line.emit("")
                ergebnis["ollama_modell"] = model_download_service.download_ollama_model(
                    self.log_line.emit, modell
                )
            self.finished_ok.emit(ergebnis)
        except Exception as error:  # keine Tracebacks im Log -- nur die Kurzfassung
            self.log_line.emit(f"FEHLER: {error}")
            self.finished_ok.emit({})


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

        self.nachlade_log = QPlainTextEdit(self)
        self.nachlade_log.setReadOnly(True)
        self.nachlade_log.setMaximumHeight(120)
        self.nachlade_log.setVisible(False)
        layout.addWidget(self.nachlade_log)

        button_row = QHBoxLayout()
        self.retry_button = QPushButton("Erneut prüfen", self)
        self.retry_button.clicked.connect(self.start)
        button_row.addWidget(self.retry_button)
        self.nachladen_button = QPushButton("Fehlendes nachladen", self)
        self.nachladen_button.setToolTip("Lädt FFmpeg, Ollama und das Ollama-Modell herunter, soweit sie fehlen.")
        self.nachladen_button.setVisible(False)
        self.nachladen_button.clicked.connect(self._nachladen)
        button_row.addWidget(self.nachladen_button)
        button_row.addStretch(1)
        self.continue_button = QPushButton("Weiter", self)
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_requested.emit)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

        self._nachlade_worker: NachladenWorker | None = None

    def _nachladen(self) -> None:
        if self._nachlade_worker is not None and self._nachlade_worker.isRunning():
            return
        self.nachladen_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.continue_button.setEnabled(False)
        self.nachlade_log.clear()
        self.nachlade_log.setVisible(True)
        self.summary_label.setText("Fehlendes wird nachgeladen – das kann einige Minuten dauern ...")
        self._nachlade_worker = NachladenWorker(self)
        self._nachlade_worker.log_line.connect(self.nachlade_log.appendPlainText)
        self._nachlade_worker.finished_ok.connect(self._nachladen_fertig)
        self._nachlade_worker.start()

    def _nachladen_fertig(self, ergebnis: dict) -> None:
        self.nachladen_button.setEnabled(True)
        luecken = [_KOMPONENTEN_NAMEN.get(k, k) for k, ok in ergebnis.items() if not ok]
        if luecken:
            self.nachlade_log.appendPlainText(
                "\nNicht gelungen: " + ", ".join(luecken) + ". Die Gründe stehen oben."
            )
        else:
            self.nachlade_log.appendPlainText("\nFertig.")
        self.start()  # Ergebnis gleich nachpruefen

    def start(self) -> None:
        from protokoll_assistent.utils.paths import get_default_output_dir

        self.retry_button.setEnabled(False)
        self.summary_label.setText("Prüfung läuft ...")

        self._thread = DiagnosticsRunner(get_default_output_dir(), self)
        self._thread.check_started.connect(self._on_check_started)
        self._thread.finished_with_results.connect(self._show_results)
        self._thread.start()

    def _on_check_started(self, label: str) -> None:
        self.summary_label.setText(f"Prüfung läuft … ({label})")

    def _show_results(self, results) -> None:
        self.retry_button.setEnabled(True)
        self.last_results = results
        self.table.setRowCount(len(results))
        for row, check in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(check.label))
            self.table.setItem(row, 1, render_check_item(check))

        critical_failed = [check for check in results if check.critical and not check.ok]
        nachladbar = any(
            check.key in NACHLADBARE_PRUEFUNGEN and not check.ok for check in results if hasattr(check, "key")
        )
        self.nachladen_button.setVisible(nachladbar)
        if critical_failed:
            self.summary_label.setText(
                "Es fehlen noch wichtige Komponenten: "
                + ", ".join(check.label for check in critical_failed)
                + ". Bitte zur Einrichtung zurückgehen, erneut prüfen"
                + (" oder „Fehlendes nachladen“ wählen." if nachladbar else ".")
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
        from protokoll_assistent.services import model_download_service

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
        text = f"Empfehlung für diesen Computer: {label}"

        # Reicht der Speicher knapp nicht, wird trotzdem das gute Modell
        # empfohlen - der Nutzer kann Programme schließen und bekommt dann
        # die volle Qualität. Ein stiller Wechsel auf ein schwächeres
        # Modell würde ihm diese Wahl nehmen.
        warnung = model_service.speicherwarnung_aus_diagnose(diagnostics_results)
        if warnung:
            text += f"\n\n⚠ {warnung}"
        self.recommendation_label.setText(text)

        from protokoll_assistent.utils.app_config import load_config

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
        from protokoll_assistent.utils.app_config import update_config

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
        from protokoll_assistent.utils.app_config import load_config

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
        from protokoll_assistent.utils.app_config import update_config

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
    """Container fuer alle sechs Einrichtungsseiten."""

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
        self.analyse_page = RechnerAnalysePage(self)
        self.install_page = InstallPage(self)
        self.diagnostics_page = DiagnosticsPage(self)
        self.model_page = ModelChoicePage(self)
        self.folder_page = InputFolderPage(self)
        for page in (
            self.welcome_page,
            self.analyse_page,
            self.install_page,
            self.diagnostics_page,
            self.model_page,
            self.folder_page,
        ):
            self.stack.addWidget(page)

        self.welcome_page.continue_requested.connect(lambda: self._go_to(1))
        self.analyse_page.continue_requested.connect(lambda: self._go_to(2))
        self.install_page.continue_requested.connect(lambda: self._go_to(3))
        self.diagnostics_page.continue_requested.connect(lambda: self._go_to(4))
        self.model_page.continue_requested.connect(lambda: self._go_to(5))
        self.folder_page.folder_confirmed.connect(self.setup_finished.emit)

        self._go_to(0)

    def _go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for label_index, label in enumerate(self._step_labels):
            label.setObjectName("StepIndicatorActive" if label_index == index else "StepIndicator")
            label.style().unpolish(label)
            label.style().polish(label)
        if index == 1:
            self.analyse_page.start()
        elif index == 2:
            self.install_page.start()
        elif index == 3:
            self.diagnostics_page.start()
        elif index == 4:
            self.model_page.apply_recommendation(self.diagnostics_page.last_results)


class LokalEinrichtungDialog(QDialog):
    """Richtet den lokalen Modus auf Wunsch ein -- Einrichtung (Downloads),
    Systemtest, Modellwahl. Anders als 'SetupWizard' (der ehemalige,
    automatische Ersteinrichtungs-Assistent) wird dieser Dialog **nicht**
    mehr automatisch beim Programmstart gezeigt, sondern gezielt aus den
    Einstellungen heraus geoeffnet, wenn der Anwender dort auf "Lokal"
    umschaltet (siehe 'gui/settings_dialog.py'). Die Hauptanwendung steht zu
    diesem Zeitpunkt bereits -- Willkommens- und Eingabeordner-Seite (die
    Ordnerauswahl liegt bereits im Hauptfenster) werden deshalb bewusst
    ausgelassen; die vier verbleibenden Seiten (Analyse, Einrichtung,
    Systemtest, Modell) werden unveraendert von 'SetupWizard'
    wiederverwendet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lokale Verarbeitung einrichten")
        self.resize(820, 620)

        layout = QVBoxLayout(self)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, stretch=1)

        self.analyse_page = RechnerAnalysePage(self)
        self.install_page = InstallPage(self)
        self.diagnostics_page = DiagnosticsPage(self)
        self.model_page = ModelChoicePage(self)
        for page in (self.analyse_page, self.install_page, self.diagnostics_page, self.model_page):
            self.stack.addWidget(page)

        self.analyse_page.continue_requested.connect(lambda: self._go_to(1))
        self.install_page.continue_requested.connect(lambda: self._go_to(2))
        self.diagnostics_page.continue_requested.connect(lambda: self._go_to(3))
        self.model_page.continue_requested.connect(self.accept)

        self._go_to(0)

    def _go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.analyse_page.start()
        elif index == 1:
            self.install_page.start()
        elif index == 2:
            self.diagnostics_page.start()
        elif index == 3:
            self.model_page.apply_recommendation(self.diagnostics_page.last_results)
