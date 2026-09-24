"""Zusatzdialoge: Systemdiagnose und Fehlermeldungen.

Den Systemprompt bearbeitet der Anwender inzwischen direkt im Hauptfenster
(Gruppe "Nachbearbeitung", mit Vorlagenbibliothek) -- der fruehere
'SystemPromptDialog' hatte danach keinen Aufrufer mehr und ist entfallen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class DiagnosticsRunner(QThread):
    """Fuehrt die Systemdiagnose im Hintergrund aus. Oeffentlich, damit sie
    sowohl vom Diagnose-Dialog als auch von der Systemtest-Seite des
    Einrichtungsassistenten (``gui/wizard.py``) wiederverwendet werden kann."""

    check_started = Signal(str)
    finished_with_results = Signal(list)

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self._output_dir = output_dir

    def run(self) -> None:
        from protokoll_assistent.utils import diagnostics

        results = diagnostics.run_diagnostics(self._output_dir, on_check_started=self.check_started.emit)
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
        self._thread.check_started.connect(self._on_check_started)
        self._thread.finished_with_results.connect(self._show_results)
        self._thread.start()

    def _on_check_started(self, label: str) -> None:
        self.status_label.setText(f"Diagnose läuft … ({label})")

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
