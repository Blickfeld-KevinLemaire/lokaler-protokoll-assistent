"""Zusatzdialoge: Systemdiagnose und Fehlermeldungen.

Den Systemprompt bearbeitet der Anwender inzwischen direkt im Hauptfenster
(Gruppe "Nachbearbeitung", mit Vorlagenbibliothek) -- der fruehere
'SystemPromptDialog' hatte danach keinen Aufrufer mehr und ist entfallen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QRadioButton,
    QSpinBox,
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


class AudioquelleDialog(QDialog):
    """'Audioquelle waehlen': Mikrofon oder Mediendatei als grosse Karten,
    darunter bei Mikrofon die verfuegbaren Eingaenge. Die Auswahl fuehrt das
    Hauptfenster aus (``quelle`` und ``geraet_index``)."""

    def __init__(self, geraete: list[str], aktuelles_geraet: int = 0, mikrofon_verfuegbar: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neue Transkription")
        self.resize(560, 460)
        self.quelle = "mikrofon" if mikrofon_verfuegbar else "datei"
        self.geraet_index = max(aktuelles_geraet, 0)

        layout = QVBoxLayout(self)
        ueber = QLabel("NEUE TRANSKRIPTION", self)
        ueber.setObjectName("StepIndicator")
        layout.addWidget(ueber)
        titel = QLabel("Audioquelle wählen", self)
        titel.setObjectName("PageTitle")
        layout.addWidget(titel)
        untertitel = QLabel("Alles bleibt auf diesem Computer, sofern der lokale Modus gewählt ist.", self)
        untertitel.setObjectName("PageSubtitle")
        layout.addWidget(untertitel)

        karten = QHBoxLayout()
        self.mikrofon_karte = QPushButton("🎙  Mikrofon\nIntegriert, USB oder Audio-Interface", self)
        self.datei_karte = QPushButton("📄  Mediendatei\nMP3, WAV, M4A, MP4 und mehr", self)
        self._karten = QButtonGroup(self)
        for karte in (self.mikrofon_karte, self.datei_karte):
            karte.setObjectName("SourceCard")
            karte.setCheckable(True)
            karte.setMinimumHeight(72)
            self._karten.addButton(karte)
            karten.addWidget(karte)
        self._karten.setExclusive(True)
        self.mikrofon_karte.setEnabled(mikrofon_verfuegbar)
        (self.mikrofon_karte if mikrofon_verfuegbar else self.datei_karte).setChecked(True)
        self.mikrofon_karte.clicked.connect(lambda: self._waehle("mikrofon"))
        self.datei_karte.clicked.connect(lambda: self._waehle("datei"))
        layout.addLayout(karten)

        self.geraete_liste = QListWidget(self)
        self.geraete_liste.addItems(geraete)
        if geraete:
            self.geraete_liste.setCurrentRow(min(self.geraet_index, len(geraete) - 1))
        self.geraete_liste.currentRowChanged.connect(self._geraet_gewaehlt)
        layout.addWidget(self.geraete_liste, stretch=1)

        self.hinweis = QLabel("", self)
        self.hinweis.setObjectName("PageSubtitle")
        self.hinweis.setWordWrap(True)
        layout.addWidget(self.hinweis)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        abbrechen = QPushButton("Abbrechen", self)
        abbrechen.clicked.connect(self.reject)
        self.weiter_button = QPushButton("", self)
        self.weiter_button.setObjectName("PrimaryButton")
        self.weiter_button.clicked.connect(self.accept)
        knoepfe.addWidget(abbrechen)
        knoepfe.addWidget(self.weiter_button)
        layout.addLayout(knoepfe)
        self._aktualisieren()

    def _waehle(self, quelle: str) -> None:
        self.quelle = quelle
        self._aktualisieren()

    def _geraet_gewaehlt(self, zeile: int) -> None:
        if zeile >= 0:
            self.geraet_index = zeile

    def _aktualisieren(self) -> None:
        mikrofon = self.quelle == "mikrofon"
        self.geraete_liste.setVisible(mikrofon)
        self.hinweis.setText(
            "" if mikrofon else "Im nächsten Schritt wählst du die Datei aus. Es startet keine Aufnahme."
        )
        self.weiter_button.setText("Aufnahme starten" if mikrofon else "Datei wählen …")


class EndverarbeitungDialog(QDialog):
    """'Verarbeitung waehlen' vor dem Start: Sprecher erkennen (mit oder ohne
    bekannte Anzahl) und ob danach direkt das Protokoll erstellt wird."""

    def __init__(
        self,
        sprecher_erkennen: bool,
        sprecherzahl: int | None,
        vorlagen: list[str],
        aktuelle_vorlage: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Verarbeitung wählen")
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        ueber = QLabel("VERARBEITUNG", self)
        ueber.setObjectName("StepIndicator")
        layout.addWidget(ueber)
        titel = QLabel("Verarbeitung wählen", self)
        titel.setObjectName("PageTitle")
        layout.addWidget(titel)
        untertitel = QLabel("Diese Auswahl gilt nur für diese Besprechung.", self)
        untertitel.setObjectName("PageSubtitle")
        layout.addWidget(untertitel)

        self.sprecher_checkbox = QCheckBox("Sprecher erkennen", self)
        self.sprecher_checkbox.setChecked(sprecher_erkennen)
        layout.addWidget(self.sprecher_checkbox)
        zeile = QHBoxLayout()
        zeile.addWidget(QLabel("Anzahl der Sprecher:", self))
        self.automatisch_radio = QRadioButton("Automatisch", self)
        self.bekannt_radio = QRadioButton("Ich kenne sie:", self)
        self.anzahl_spin = QSpinBox(self)
        self.anzahl_spin.setRange(1, 30)
        self.anzahl_spin.setValue(sprecherzahl or 2)
        (self.bekannt_radio if sprecherzahl else self.automatisch_radio).setChecked(True)
        for widget in (self.automatisch_radio, self.bekannt_radio, self.anzahl_spin):
            zeile.addWidget(widget)
        zeile.addStretch(1)
        layout.addLayout(zeile)
        self.sprecher_checkbox.toggled.connect(self._sprecher_umgeschaltet)
        self.bekannt_radio.toggled.connect(self._sprecher_umgeschaltet)

        self.protokoll_checkbox = QCheckBox("Danach direkt das Protokoll erstellen", self)
        layout.addWidget(self.protokoll_checkbox)
        vorlage_zeile = QHBoxLayout()
        vorlage_zeile.addWidget(QLabel("Vorlage:", self))
        self.vorlage_combo = QComboBox(self)
        self.vorlage_combo.addItems(vorlagen)
        if aktuelle_vorlage in vorlagen:
            self.vorlage_combo.setCurrentIndex(vorlagen.index(aktuelle_vorlage))
        vorlage_zeile.addWidget(self.vorlage_combo, stretch=1)
        layout.addLayout(vorlage_zeile)
        self.protokoll_checkbox.toggled.connect(self.vorlage_combo.setEnabled)
        self.vorlage_combo.setEnabled(False)
        layout.addStretch(1)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        abbrechen = QPushButton("Abbrechen", self)
        abbrechen.clicked.connect(self.reject)
        start = QPushButton("Verarbeitung starten", self)
        start.setObjectName("PrimaryButton")
        start.clicked.connect(self.accept)
        knoepfe.addWidget(abbrechen)
        knoepfe.addWidget(start)
        layout.addLayout(knoepfe)
        self._sprecher_umgeschaltet()

    def _sprecher_umgeschaltet(self) -> None:
        aktiv = self.sprecher_checkbox.isChecked()
        self.automatisch_radio.setEnabled(aktiv)
        self.bekannt_radio.setEnabled(aktiv)
        self.anzahl_spin.setEnabled(aktiv and self.bekannt_radio.isChecked())

    @property
    def sprecher_erkennen(self) -> bool:
        return self.sprecher_checkbox.isChecked()

    @property
    def sprecherzahl(self) -> int | None:
        if self.sprecher_erkennen and self.bekannt_radio.isChecked():
            return self.anzahl_spin.value()
        return None

    @property
    def protokoll_erstellen(self) -> bool:
        return self.protokoll_checkbox.isChecked()

    @property
    def vorlage(self) -> str | None:
        return self.vorlage_combo.currentText() if self.protokoll_erstellen else None


class ChatSystemcheckDialog(QDialog):
    """Ergebnis des Systemchecks fuer den Chatbot: eine Zeile je Pruefung."""

    def __init__(self, pruefungen: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Systemcheck Chatbot")
        self.resize(720, 360)
        layout = QVBoxLayout(self)

        alles_ok = all(p.ok or not p.critical for p in pruefungen)
        self.zusammenfassung = QLabel(
            "✓ Der Chatbot ist einsatzbereit." if alles_ok else "✗ Der Chatbot ist noch nicht einsatzbereit - siehe unten.",
            self,
        )
        self.zusammenfassung.setObjectName("PageTitle")
        layout.addWidget(self.zusammenfassung)

        self.tabelle = QTableWidget(len(pruefungen), 2, self)
        self.tabelle.setHorizontalHeaderLabels(["Prüfung", "Ergebnis"])
        self.tabelle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabelle.verticalHeader().setVisible(False)
        for zeile, pruefung in enumerate(pruefungen):
            self.tabelle.setItem(zeile, 0, QTableWidgetItem(pruefung.label))
            self.tabelle.setItem(zeile, 1, render_check_item(pruefung))
        layout.addWidget(self.tabelle)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Close, self)
        knoepfe.rejected.connect(self.reject)
        knoepfe.accepted.connect(self.accept)
        layout.addWidget(knoepfe)


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
