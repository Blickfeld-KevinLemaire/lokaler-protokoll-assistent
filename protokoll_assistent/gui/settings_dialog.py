"""Einstellungen des Protokoll-Assistenten.

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

from pathlib import Path
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.gui.worker import OllamaPullWorker
from protokoll_assistent.services import ollama_service, secret_store
from protokoll_assistent.utils import app_config

# Auswahlpunkt, hinter dem ein frei eingegebener Ollama-Modellname gilt.
EIGENES_OLLAMA_MODELL = "__eigenes_modell__"

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
        from protokoll_assistent.services import model_service

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

        einrichten_button = QPushButton("Einrichtung starten (Downloads, Systemtest, Modellwahl) …", seite)
        einrichten_button.clicked.connect(self._open_lokal_einrichtung)
        layout.addRow(einrichten_button)

        diagnose_button = QPushButton("Nur Systemdiagnose …", seite)
        diagnose_button.clicked.connect(self._open_diagnostics)
        layout.addRow(diagnose_button)

        return seite

    def _open_lokal_einrichtung(self) -> None:
        from protokoll_assistent.gui.wizard import LokalEinrichtungDialog

        dialog = LokalEinrichtungDialog(self)
        dialog.exec()

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
        from protokoll_assistent.gui.dialogs import DiagnosticsDialog
        from protokoll_assistent.utils.paths import get_default_output_dir

        # Der Parameter heisst 'output_dir': Die Diagnose prueft damit
        # freien Platz und Schreibbarkeit des AUSGABEordners. Mit dem
        # Anwendungsordner beantwortet sie die Frage fuer das falsche
        # Laufwerk, sobald die Ausgabe woanders liegt.
        ausgabeordner = self._config.get("ausgabeordner")
        ziel = Path(ausgabeordner) if ausgabeordner else get_default_output_dir()
        dialog = DiagnosticsDialog(ziel, self)
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
        self._ollama_worker: OllamaPullWorker | None = None

        self.ollama_modell_combo = QComboBox(seite)
        for option in ollama_service.OLLAMA_MODELLE:
            self.ollama_modell_combo.addItem(f"{option.label} - ca. {option.groesse_gb:g} GB", option.id)
        self.ollama_modell_combo.addItem("Eigenen Modellnamen eingeben …", EIGENES_OLLAMA_MODELL)
        layout.addRow("Ollama-Modell:", self.ollama_modell_combo)

        self.ollama_modell_edit = QLineEdit(seite)
        self.ollama_modell_edit.setPlaceholderText("z. B. phi4 oder qwen3:30b (Namen siehe ollama.com/library)")
        layout.addRow("Modellname:", self.ollama_modell_edit)

        gespeichert = (self._config.get("ollama_modell") or ollama_service.DEFAULT_MODEL).strip()
        index = self.ollama_modell_combo.findData(gespeichert)
        if index >= 0:
            self.ollama_modell_combo.setCurrentIndex(index)
        else:
            self.ollama_modell_combo.setCurrentIndex(self.ollama_modell_combo.findData(EIGENES_OLLAMA_MODELL))
            self.ollama_modell_edit.setText(gespeichert)
        self.ollama_modell_combo.currentIndexChanged.connect(self._ollama_auswahl_geaendert)
        self.ollama_modell_edit.editingFinished.connect(self._ollama_status_aktualisieren)

        self.ollama_hinweis_label = QLabel("", seite)
        self.ollama_hinweis_label.setWordWrap(True)
        layout.addRow(self.ollama_hinweis_label)

        self.ollama_status_label = QLabel("", seite)
        self.ollama_status_label.setWordWrap(True)
        layout.addRow("Status:", self.ollama_status_label)

        self.ollama_fortschritt = QProgressBar(seite)
        self.ollama_fortschritt.setRange(0, 100)
        self.ollama_fortschritt.setVisible(False)
        layout.addRow(self.ollama_fortschritt)

        knopfzeile = QHBoxLayout()
        self.ollama_download_button = QPushButton("Jetzt herunterladen", seite)
        self.ollama_download_button.setObjectName("PrimaryButton")
        self.ollama_download_button.clicked.connect(self._ollama_herunterladen)
        self.ollama_pruefen_button = QPushButton("Status prüfen", seite)
        self.ollama_pruefen_button.clicked.connect(self._ollama_status_aktualisieren)
        knopfzeile.addWidget(self.ollama_download_button)
        knopfzeile.addWidget(self.ollama_pruefen_button)
        knopfzeile.addStretch(1)
        layout.addRow(knopfzeile)

        hinweis = QLabel(
            "Das gewählte Modell wird für die Nachbearbeitung benutzt. Beim ersten Start der "
            "lokalen Einrichtung wird das hier eingestellte Modell mit heruntergeladen. Ein anderes "
            "lässt sich jederzeit auswählen und hier nachladen; ein Download kann je nach Modell "
            "mehrere Gigabyte groß sein.",
            seite,
        )
        hinweis.setWordWrap(True)
        layout.addRow(hinweis)

        self._ollama_auswahl_geaendert()
        return seite

    def ollama_modell(self) -> str:
        """Der aktuell eingestellte Ollama-Modellname."""
        if self.ollama_modell_combo.currentData() == EIGENES_OLLAMA_MODELL:
            return self.ollama_modell_edit.text().strip()
        return str(self.ollama_modell_combo.currentData())

    def _ollama_auswahl_geaendert(self, _index: int = 0) -> None:
        eigenes = self.ollama_modell_combo.currentData() == EIGENES_OLLAMA_MODELL
        self.ollama_modell_edit.setVisible(eigenes)
        option = ollama_service.get_modell_option(self.ollama_modell())
        self.ollama_hinweis_label.setText(option.hinweis if option else "")
        self._ollama_status_aktualisieren()

    def _ollama_status_aktualisieren(self) -> None:
        modell = self.ollama_modell()
        if not modell:
            self.ollama_status_label.setText("Bitte einen Modellnamen eingeben.")
            self.ollama_download_button.setEnabled(False)
            return
        try:
            installiert = ollama_service.list_models(timeout=1.5)
        except ollama_service.OllamaError:
            self.ollama_status_label.setText(
                "Ollama ist nicht erreichbar. Ollama starten oder über „Einrichtung starten“ "
                "(Reiter Transkription) installieren, dann „Status prüfen“."
            )
            self.ollama_download_button.setEnabled(self._ollama_worker is None)
            return
        if ollama_service.is_model_available(modell):
            self.ollama_status_label.setText(f"✓ '{modell}' ist installiert.")
            self.ollama_download_button.setEnabled(False)
        else:
            weitere = [name for name in installiert if name]
            zusatz = f" Bereits installiert: {', '.join(weitere)}." if weitere else ""
            self.ollama_status_label.setText(f"'{modell}' ist noch nicht installiert.{zusatz}")
            self.ollama_download_button.setEnabled(self._ollama_worker is None)

    def _ollama_herunterladen(self) -> None:
        modell = self.ollama_modell()
        if not modell or self._ollama_worker is not None:
            return
        self.ollama_download_button.setEnabled(False)
        self.ollama_modell_combo.setEnabled(False)
        self.ollama_fortschritt.setValue(0)
        self.ollama_fortschritt.setVisible(True)
        self.ollama_status_label.setText(f"Lade '{modell}' herunter …")
        self._ollama_worker = OllamaPullWorker(modell, self)
        self._ollama_worker.fortschritt.connect(self._ollama_fortschritt_anzeigen)
        self._ollama_worker.fertig.connect(self._ollama_download_fertig)
        self._ollama_worker.fehlgeschlagen.connect(self._ollama_download_fehlgeschlagen)
        self._ollama_worker.start()

    def _ollama_fortschritt_anzeigen(self, status: str, fertig: int, gesamt: int) -> None:
        if gesamt > 0:
            self.ollama_fortschritt.setRange(0, 100)
            self.ollama_fortschritt.setValue(round(fertig / gesamt * 100))
            self.ollama_status_label.setText(f"{status}: {fertig / 1e9:.1f} von {gesamt / 1e9:.1f} GB")
        else:
            self.ollama_status_label.setText(status)

    def _ollama_download_beendet(self) -> None:
        self._ollama_worker = None
        self.ollama_fortschritt.setVisible(False)
        self.ollama_modell_combo.setEnabled(True)

    def _ollama_download_fertig(self, modell: str) -> None:
        self._ollama_download_beendet()
        self._ollama_status_aktualisieren()

    def _ollama_download_fehlgeschlagen(self, modell: str, meldung: str) -> None:
        self._ollama_download_beendet()
        self.ollama_status_label.setText(f"Download fehlgeschlagen: {meldung}")
        self.ollama_download_button.setEnabled(True)

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
            "ollama_modell": self.ollama_modell() or ollama_service.DEFAULT_MODEL,
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
        if merken and wert:
            try:
                secret_store.save_api_key(schluessel_name, wert)
            except secret_store.SecretStoreUnavailableError as error:
                QMessageBox.warning(self, "Schlüssel nicht gespeichert", str(error))
        elif not merken:
            # Ein zuvor gemerkter Schluessel wird entfernt. Ist der
            # Anmeldeinformationsspeicher nicht verfuegbar, gibt es auch nichts zu
            # entfernen - und der Anwender wollte ohnehin nichts merken. Eine
            # Meldung waere hier nur Laerm.
            try:
                secret_store.delete_api_key(schluessel_name)
            except secret_store.SecretStoreUnavailableError:
                return
