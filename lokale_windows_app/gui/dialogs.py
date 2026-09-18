"""Zusatzdialoge: Systemprompt-Editor und Systemdiagnose."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from utils.paths import get_default_system_prompt_file, get_system_prompt_file


class SystemPromptDialog(QDialog):
    """Erlaubt das Anzeigen, Bearbeiten und Zuruecksetzen des Systemprompts
    vor jeder Auswertung (Datei ``einstellungen/systemprompt_protokoll.txt``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Systemprompt für die Protokollauswertung")
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Dieser Text steuert, wie das lokale Ollama-Modell das Protokoll erstellt. "
                "Änderungen werden in 'einstellungen/systemprompt_protokoll.txt' gespeichert."
            )
        )

        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(self._load_current_prompt())
        layout.addWidget(self.editor)

        button_row = QHBoxLayout()
        reset_button = QPushButton("Auf Standard zurücksetzen", self)
        reset_button.clicked.connect(self._reset_to_default)
        button_row.addWidget(reset_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_current_prompt(self) -> str:
        prompt_file = get_system_prompt_file()
        if prompt_file.is_file():
            return prompt_file.read_text(encoding="utf-8")
        default_file = get_default_system_prompt_file()
        return default_file.read_text(encoding="utf-8") if default_file.is_file() else ""

    def _reset_to_default(self) -> None:
        default_file = get_default_system_prompt_file()
        if default_file.is_file():
            self.editor.setPlainText(default_file.read_text(encoding="utf-8"))

    def _save_and_close(self) -> None:
        get_system_prompt_file().write_text(self.editor.toPlainText(), encoding="utf-8")
        self.accept()


class DiagnosticsRunner(QThread):
    """Fuehrt die Systemdiagnose im Hintergrund aus. Oeffentlich, damit sie
    sowohl vom Diagnose-Dialog als auch von der Systemtest-Seite des
    Einrichtungsassistenten (``gui/wizard.py``) wiederverwendet werden kann."""

    finished_with_results = Signal(list)

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self._output_dir = output_dir

    def run(self) -> None:
        from utils import diagnostics

        results = diagnostics.run_diagnostics(self._output_dir)
        self.finished_with_results.emit(results)


def render_check_item(check) -> QTableWidgetItem:
    """Baut die farblich markierte Ergebniszelle fuer eine einzelne
    Diagnosepruefung -- gemeinsam genutzt von Dialog und Assistent."""
    symbol = "OK" if check.ok else ("FEHLT" if check.critical else "HINWEIS")
    item = QTableWidgetItem(f"[{symbol}] {check.detail}")
    if not check.ok and check.critical:
        item.setForeground(Qt.red)
    elif not check.ok:
        item.setForeground(Qt.darkYellow)
    else:
        item.setForeground(Qt.darkGreen)
    return item


class DiagnosticsDialog(QDialog):
    """Fuehrt die Systemdiagnose aus und zeigt die Ergebnisse tabellarisch an."""

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Systemdiagnose")
        self.resize(760, 480)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Diagnose läuft …", self)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Prüfung", "Ergebnis"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._thread = DiagnosticsRunner(output_dir, self)
        self._thread.finished_with_results.connect(self._show_results)
        self._thread.start()

    def _show_results(self, results) -> None:
        self.status_label.setText("Diagnose abgeschlossen.")
        self.table.setRowCount(len(results))
        for row, check in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(check.label))
            self.table.setItem(row, 1, render_check_item(check))


def show_error(parent, title: str, message: str) -> None:
    """Zeigt eine kurze, verstaendliche Fehlermeldung -- niemals einen
    vollstaendigen Python-Traceback."""
    QMessageBox.critical(parent, title, message)
