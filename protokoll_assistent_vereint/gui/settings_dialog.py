"""Einstellungen der vereinten Anwendung.

Zwei Reiter, wie vom Auftrag verlangt: "Transkription" entscheidet lokal
(installiertes Whisper-Modell) vs. API-Schnittstelle; "Nachbearbeitung"
entscheidet lokal (Ollama) vs. API-Modell.

Die Auswahl und Bearbeitung des Systemprompts fuer den jeweils aktuellen
Lauf (Vorlage per Dropdown oder freier Text) gehoert bewusst NICHT hierher,
sondern liegt inline in der Nachbearbeitungs-Gruppe des Hauptfensters
('gui/main_window.py') - genau dort, wo der Nutzer sie beim Start der
Nachbearbeitung braucht. Neue Vorlagen anlegen ('utils/systemprompt_vorlagen.py')
ist ebenfalls dort moeglich.

API-Schluessel werden NIE in diese Einstellungsdatei geschrieben (siehe
'utils/app_config.py') - nur ob der Anwender das Merken ueberhaupt
aktiviert hat. Der eigentliche Schluessel geht ausschliesslich ueber
'services/secret_store.py' in die Windows-Anmeldeinformationsverwaltung.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent_vereint.services import secret_store
from protokoll_assistent_vereint.utils import app_config

DATENSCHUTZ_HINWEIS_API = (
    "Bei aktiver API-Schnittstelle wird die Aufnahme an den oben eingetragenen, "
    "externen Anbieter übertragen. Für diese Übertragung kann in diesem Moment "
    "kein Datenschutz gewährleistet werden – der Anwender ist für die von ihm "
    "gewählte Schnittstelle selbst verantwortlich."
)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(680, 520)

        self._config = app_config.load_config()
        # Vom Aufrufer (MainWindow) ausgewertet, um die eingegebenen
        # Schluessel fuer den Rest der Sitzung im Speicher zu behalten -
        # unabhaengig davon, ob "auf diesem Geraet merken" angehakt war.
        # Ohne das waere ein nicht dauerhaft gespeicherter Schluessel sofort
        # nach dem Schliessen dieses Dialogs wieder weg (siehe
        # '_schluessel_anwenden': ohne Haken wird ein zuvor gespeicherter
        # Schluessel sogar geloescht).
        self.eingegebene_schluessel: dict[str, str] = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        layout.addWidget(tabs, stretch=1)
        tabs.addTab(self._build_transkription_tab(), "Transkription")
        tabs.addTab(self._build_nachbearbeitung_tab(), "Nachbearbeitung")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._speichern_und_schliessen)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Reiter "Transkription"
    # ------------------------------------------------------------------
    def _build_transkription_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        modus_zeile = QHBoxLayout()
        self.transkription_lokal_radio = QRadioButton("Lokal", tab)
        self.transkription_api_radio = QRadioButton("API-Schnittstelle", tab)
        self._transkription_modus_gruppe = QButtonGroup(tab)
        self._transkription_modus_gruppe.addButton(self.transkription_lokal_radio)
        self._transkription_modus_gruppe.addButton(self.transkription_api_radio)
        modus_zeile.addWidget(self.transkription_lokal_radio)
        modus_zeile.addWidget(self.transkription_api_radio)
        modus_zeile.addStretch(1)
        layout.addLayout(modus_zeile)

        self.transkription_seiten = QStackedWidget(tab)
        self.transkription_seiten.addWidget(self._build_transkription_lokal_seite())
        self.transkription_seiten.addWidget(self._build_transkription_api_seite())
        layout.addWidget(self.transkription_seiten, stretch=1)

        self.transkription_lokal_radio.toggled.connect(self._transkription_seite_umschalten)
        self.transkription_api_radio.toggled.connect(self._transkription_seite_umschalten)

        if self._config["transkription_modus"] == "api":
            self.transkription_api_radio.setChecked(True)
        else:
            self.transkription_lokal_radio.setChecked(True)

        return tab

    def _transkription_seite_umschalten(self) -> None:
        self.transkription_seiten.setCurrentIndex(1 if self.transkription_api_radio.isChecked() else 0)

    def _build_transkription_lokal_seite(self) -> QWidget:
        from services import model_service

        seite = QWidget(self)
        layout = QFormLayout(seite)

        self.whisper_modell_combo = QComboBox(seite)
        for option in model_service.WHISPER_MODELLE:
            self.whisper_modell_combo.addItem(option.label, option.id)
        gespeichertes_modell = self._config.get("whisper_modell") or model_service.WHISPER_MODEL_NAME
        index = self.whisper_modell_combo.findData(gespeichertes_modell)
        if index >= 0:
            self.whisper_modell_combo.setCurrentIndex(index)
        layout.addRow("Whisper-Modell:", self.whisper_modell_combo)

        hinweis = QLabel(
            "Wird beim ersten Einsatz im lokalen Modus automatisch heruntergeladen und "
            "eingerichtet (kann je nach Internetverbindung einige Minuten dauern).",
            seite,
        )
        hinweis.setWordWrap(True)
        layout.addRow(hinweis)

        diagnose_button = QPushButton("Systemdiagnose …", seite)
        diagnose_button.clicked.connect(self._open_diagnostics)
        layout.addRow(diagnose_button)

        return seite

    def _build_transkription_api_seite(self) -> QWidget:
        seite = QWidget(self)
        layout = QFormLayout(seite)

        self.api_transkription_endpunkt_edit = QLineEdit(
            self._config["api_transkription_endpunkt"], seite
        )
        layout.addRow("Endpunkt (Basis-URL):", self.api_transkription_endpunkt_edit)

        self.api_transkription_modell_edit = QLineEdit(self._config["api_transkription_modell"], seite)
        layout.addRow("Modellname:", self.api_transkription_modell_edit)

        self.api_transkription_anbieter_edit = QLineEdit(
            self._config["api_transkription_anbieter"], seite
        )
        layout.addRow("Anbieter (Sprechertrennung):", self.api_transkription_anbieter_edit)

        schluessel_zeile = QHBoxLayout()
        self.api_transkription_schluessel_edit = QLineEdit(seite)
        self.api_transkription_schluessel_edit.setEchoMode(QLineEdit.Password)
        vorhandener_schluessel = self._gespeicherten_schluessel_laden("transkription")
        if vorhandener_schluessel:
            self.api_transkription_schluessel_edit.setText(vorhandener_schluessel)
        schluessel_zeile.addWidget(self.api_transkription_schluessel_edit)
        anzeigen_checkbox = QCheckBox("anzeigen", seite)
        anzeigen_checkbox.toggled.connect(
            lambda checked: self.api_transkription_schluessel_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        schluessel_zeile.addWidget(anzeigen_checkbox)
        layout.addRow("API-Schlüssel:", schluessel_zeile)

        self.api_transkription_merken_checkbox = QCheckBox(
            "Auf diesem Gerät merken (Windows-Anmeldeinformationsverwaltung)", seite
        )
        self.api_transkription_merken_checkbox.setChecked(
            bool(self._config["api_transkription_schluessel_merken"])
        )
        layout.addRow(self.api_transkription_merken_checkbox)

        hinweis = QLabel(DATENSCHUTZ_HINWEIS_API, seite)
        hinweis.setObjectName("DatenschutzHinweis")
        hinweis.setWordWrap(True)
        layout.addRow(hinweis)

        return seite

    def _open_diagnostics(self) -> None:
        from gui.dialogs import DiagnosticsDialog
        from protokoll_assistent_vereint.utils.paths import get_app_dir

        dialog = DiagnosticsDialog(get_app_dir(), self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Reiter "Nachbearbeitung"
    # ------------------------------------------------------------------
    def _build_nachbearbeitung_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        modus_zeile = QHBoxLayout()
        self.nachbearbeitung_lokal_radio = QRadioButton("Lokal (Ollama)", tab)
        self.nachbearbeitung_api_radio = QRadioButton("API-Modell", tab)
        self._nachbearbeitung_modus_gruppe = QButtonGroup(tab)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_lokal_radio)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_api_radio)
        modus_zeile.addWidget(self.nachbearbeitung_lokal_radio)
        modus_zeile.addWidget(self.nachbearbeitung_api_radio)
        modus_zeile.addStretch(1)
        layout.addLayout(modus_zeile)

        self.nachbearbeitung_seiten = QStackedWidget(tab)
        self.nachbearbeitung_seiten.addWidget(self._build_nachbearbeitung_lokal_seite())
        self.nachbearbeitung_seiten.addWidget(self._build_nachbearbeitung_api_seite())
        layout.addWidget(self.nachbearbeitung_seiten, stretch=1)

        self.nachbearbeitung_lokal_radio.toggled.connect(self._nachbearbeitung_seite_umschalten)
        self.nachbearbeitung_api_radio.toggled.connect(self._nachbearbeitung_seite_umschalten)

        if self._config["nachbearbeitung_modus"] == "api":
            self.nachbearbeitung_api_radio.setChecked(True)
        else:
            self.nachbearbeitung_lokal_radio.setChecked(True)

        return tab

    def _nachbearbeitung_seite_umschalten(self) -> None:
        self.nachbearbeitung_seiten.setCurrentIndex(1 if self.nachbearbeitung_api_radio.isChecked() else 0)

    def _build_nachbearbeitung_lokal_seite(self) -> QWidget:
        seite = QWidget(self)
        layout = QFormLayout(seite)
        self.ollama_modell_edit = QLineEdit(self._config["ollama_modell"], seite)
        layout.addRow("Ollama-Modellname:", self.ollama_modell_edit)
        return seite

    def _build_nachbearbeitung_api_seite(self) -> QWidget:
        seite = QWidget(self)
        layout = QFormLayout(seite)

        self.api_nachbearbeitung_endpunkt_edit = QLineEdit(
            self._config["api_nachbearbeitung_endpunkt"], seite
        )
        layout.addRow("Endpunkt (Basis-URL):", self.api_nachbearbeitung_endpunkt_edit)

        self.api_nachbearbeitung_modell_edit = QLineEdit(
            self._config["api_nachbearbeitung_modell"], seite
        )
        layout.addRow("Modellname:", self.api_nachbearbeitung_modell_edit)

        self.api_nachbearbeitung_eigener_schluessel_checkbox = QCheckBox(
            "Eigenen Schlüssel verwenden (sonst: derselbe wie bei der Transkription)", seite
        )
        self.api_nachbearbeitung_eigener_schluessel_checkbox.setChecked(
            bool(self._config["api_nachbearbeitung_eigener_schluessel"])
        )
        layout.addRow(self.api_nachbearbeitung_eigener_schluessel_checkbox)

        schluessel_zeile = QHBoxLayout()
        self.api_nachbearbeitung_schluessel_edit = QLineEdit(seite)
        self.api_nachbearbeitung_schluessel_edit.setEchoMode(QLineEdit.Password)
        vorhandener_schluessel = self._gespeicherten_schluessel_laden("nachbearbeitung")
        if vorhandener_schluessel:
            self.api_nachbearbeitung_schluessel_edit.setText(vorhandener_schluessel)
        schluessel_zeile.addWidget(self.api_nachbearbeitung_schluessel_edit)
        anzeigen_checkbox = QCheckBox("anzeigen", seite)
        anzeigen_checkbox.toggled.connect(
            lambda checked: self.api_nachbearbeitung_schluessel_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        schluessel_zeile.addWidget(anzeigen_checkbox)
        layout.addRow("Eigener API-Schlüssel:", schluessel_zeile)

        self.api_nachbearbeitung_eigener_schluessel_checkbox.toggled.connect(
            self.api_nachbearbeitung_schluessel_edit.setEnabled
        )
        self.api_nachbearbeitung_schluessel_edit.setEnabled(
            self.api_nachbearbeitung_eigener_schluessel_checkbox.isChecked()
        )

        self.api_nachbearbeitung_merken_checkbox = QCheckBox(
            "Auf diesem Gerät merken (Windows-Anmeldeinformationsverwaltung)", seite
        )
        self.api_nachbearbeitung_merken_checkbox.setChecked(
            bool(self._config["api_nachbearbeitung_schluessel_merken"])
        )
        layout.addRow(self.api_nachbearbeitung_merken_checkbox)

        return seite

    # ------------------------------------------------------------------
    # Speichern
    # ------------------------------------------------------------------
    def _speichern_und_schliessen(self) -> None:
        aenderungen: dict[str, Any] = {
            "transkription_modus": "api" if self.transkription_api_radio.isChecked() else "lokal",
            "whisper_modell": self.whisper_modell_combo.currentData(),
            "api_transkription_endpunkt": self.api_transkription_endpunkt_edit.text().strip(),
            "api_transkription_modell": self.api_transkription_modell_edit.text().strip(),
            "api_transkription_anbieter": self.api_transkription_anbieter_edit.text().strip(),
            "api_transkription_schluessel_merken": self.api_transkription_merken_checkbox.isChecked(),
            "nachbearbeitung_modus": "api" if self.nachbearbeitung_api_radio.isChecked() else "lokal",
            "ollama_modell": self.ollama_modell_edit.text().strip(),
            "api_nachbearbeitung_endpunkt": self.api_nachbearbeitung_endpunkt_edit.text().strip(),
            "api_nachbearbeitung_modell": self.api_nachbearbeitung_modell_edit.text().strip(),
            "api_nachbearbeitung_eigener_schluessel": (
                self.api_nachbearbeitung_eigener_schluessel_checkbox.isChecked()
            ),
            "api_nachbearbeitung_schluessel_merken": self.api_nachbearbeitung_merken_checkbox.isChecked(),
        }
        app_config.update_config(**aenderungen)

        transkription_schluessel = self.api_transkription_schluessel_edit.text().strip()
        if transkription_schluessel:
            self.eingegebene_schluessel["transkription"] = transkription_schluessel
        nachbearbeitung_schluessel = self.api_nachbearbeitung_schluessel_edit.text().strip()
        if nachbearbeitung_schluessel:
            self.eingegebene_schluessel["nachbearbeitung"] = nachbearbeitung_schluessel

        self._schluessel_anwenden(
            merken=self.api_transkription_merken_checkbox.isChecked(),
            schluessel_name="transkription",
            eingabefeld=self.api_transkription_schluessel_edit,
        )
        self._schluessel_anwenden(
            merken=self.api_nachbearbeitung_merken_checkbox.isChecked(),
            schluessel_name="nachbearbeitung",
            eingabefeld=self.api_nachbearbeitung_schluessel_edit,
        )

        self.accept()

    def _gespeicherten_schluessel_laden(self, schluessel_name: str) -> str | None:
        """Ist die Windows-Anmeldeinformationsverwaltung nicht verfuegbar
        (kein Backend, Dienst deaktiviert o.ae.), darf das Oeffnen der
        Einstellungen nicht abstuerzen - der Anwender kann den Schluessel
        dann weiterhin von Hand eintragen, nur eben ohne die zuvor
        gespeicherte Vorbelegung."""
        try:
            return secret_store.load_api_key(schluessel_name)
        except secret_store.SecretStoreUnavailableError:
            return None

    def _schluessel_anwenden(self, *, merken: bool, schluessel_name: str, eingabefeld: QLineEdit) -> None:
        wert = eingabefeld.text().strip()
        try:
            if merken and wert:
                secret_store.save_api_key(schluessel_name, wert)
            elif not merken:
                secret_store.delete_api_key(schluessel_name)
        except secret_store.SecretStoreUnavailableError as error:
            QMessageBox.warning(self, "Schlüssel nicht gespeichert", str(error))
