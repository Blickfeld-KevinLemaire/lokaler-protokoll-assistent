"""Zusatzdialoge: Systemdiagnose und Fehlermeldungen.

Den Systemprompt bearbeitet der Anwender inzwischen direkt im Hauptfenster
(Gruppe "Nachbearbeitung", mit Vorlagenbibliothek) -- der fruehere
'SystemPromptDialog' hatte danach keinen Aufrufer mehr und ist entfallen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from protokoll_assistent.services import sprecherprofil_service


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


class SprecherprofileDialog(QDialog):
    """Verwaltung der gespeicherten Sprecherprofile: ansehen, umbenennen,
    loeschen. Neue Profile entstehen in der Sprechertabelle des Hauptfensters."""

    def __init__(self, parent=None, ordner: Path | None = None):
        super().__init__(parent)
        self._ordner = ordner
        self.setWindowTitle("Sprecherprofile verwalten")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        hinweis = QLabel(
            "Gespeicherte Stimmen werden zur Wiedererkennung in neuen Aufnahmen benutzt. "
            "Ein Stimmabdruck ist ein biometrisches Datum: Er bleibt ausschließlich auf diesem "
            "Rechner und wird nie übertragen. Jedes Profil lässt sich hier löschen.",
            self,
        )
        hinweis.setWordWrap(True)
        layout.addWidget(hinweis)

        self.liste = QListWidget(self)
        layout.addWidget(self.liste)

        zeile = QHBoxLayout()
        self.umbenennen_button = QPushButton("Umbenennen …", self)
        self.umbenennen_button.clicked.connect(self._umbenennen)
        self.loeschen_button = QPushButton("Löschen …", self)
        self.loeschen_button.clicked.connect(self._loeschen)
        zeile.addWidget(self.umbenennen_button)
        zeile.addWidget(self.loeschen_button)
        zeile.addStretch(1)
        layout.addLayout(zeile)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Close, self)
        knoepfe.rejected.connect(self.reject)
        knoepfe.accepted.connect(self.accept)
        layout.addWidget(knoepfe)

        self._laden()

    def _laden(self) -> None:
        self.liste.clear()
        for profil in sprecherprofil_service.lade_profile(self._ordner):
            proben = int(profil.get("anzahl_proben", 1))
            eintrag = QListWidgetItem(f"{profil['name']}  ({proben} {'Probe' if proben == 1 else 'Proben'})")
            eintrag.setData(Qt.UserRole, profil["id"])
            self.liste.addItem(eintrag)
        leer = self.liste.count() == 0
        self.umbenennen_button.setEnabled(not leer)
        self.loeschen_button.setEnabled(not leer)
        if not leer:
            self.liste.setCurrentRow(0)

    def _gewaehlte_id(self) -> str | None:
        eintrag = self.liste.currentItem()
        return None if eintrag is None else str(eintrag.data(Qt.UserRole))

    def _umbenennen(self) -> None:
        profil_id = self._gewaehlte_id()
        if profil_id is None:
            return
        aktuell = self.liste.currentItem().text().rsplit("  (", 1)[0]
        name, ok = QInputDialog.getText(self, "Profil umbenennen", "Neuer Name:", text=aktuell)
        if not ok:
            return
        try:
            sprecherprofil_service.profil_umbenennen(profil_id, name, self._ordner)
        except sprecherprofil_service.ProfilFehler as error:
            show_error(self, "Umbenennen nicht möglich", str(error))
            return
        self._laden()

    def _loeschen(self) -> None:
        profil_id = self._gewaehlte_id()
        if profil_id is None:
            return
        name = self.liste.currentItem().text().rsplit("  (", 1)[0]
        antwort = QMessageBox.question(
            self, "Profil löschen", f"Das Profil „{name}“ und der gespeicherte Stimmabdruck werden gelöscht."
        )
        if antwort != QMessageBox.Yes:
            return
        sprecherprofil_service.profil_loeschen(profil_id, self._ordner)
        self._laden()


def show_error(parent, title: str, message: str) -> None:
    """Zeigt eine kurze, verstaendliche Fehlermeldung -- niemals einen
    vollstaendigen Python-Traceback."""
    QMessageBox.critical(parent, title, message)
