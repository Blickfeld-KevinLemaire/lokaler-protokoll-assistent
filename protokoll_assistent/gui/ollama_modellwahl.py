"""Auswahl eines Ollama-Modells mit Status und "Jetzt herunterladen".

Wird in den Einstellungen fuer die Nachbearbeitung und doppelt fuer den
Chatbot (Chatmodell und Einbettungsmodell) benutzt: eine Auswahl aus einer
kuratierten Liste mit Groessenangabe, ein eigener Modellname, der Status
(installiert oder nicht) und der Download mit Fortschritt.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QWidget,
)

from protokoll_assistent.gui.worker import OllamaPullWorker
from protokoll_assistent.services import ollama_service

# Auswahlpunkt, hinter dem ein frei eingegebener Modellname gilt.
EIGENES_MODELL = "__eigenes_modell__"


class OllamaModellWahl(QWidget):
    modell_geaendert = Signal(str)

    def __init__(
        self,
        optionen: list[ollama_service.OllamaModellOption],
        standard: str,
        gespeichert: str | None,
        beschriftung: str = "Ollama-Modell:",
        parent=None,
    ):
        super().__init__(parent)
        self._standard = standard
        self._worker: OllamaPullWorker | None = None
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox(self)
        for option in optionen:
            self.combo.addItem(f"{option.label} - ca. {option.groesse_gb:g} GB", option.id)
        self.combo.addItem("Eigenen Modellnamen eingeben …", EIGENES_MODELL)
        layout.addRow(beschriftung, self.combo)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Name aus der Ollama-Bibliothek, z. B. phi4 (ollama.com/library)")
        layout.addRow("Modellname:", self.edit)

        name = (gespeichert or standard).strip()
        index = self.combo.findData(name)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        else:
            self.combo.setCurrentIndex(self.combo.findData(EIGENES_MODELL))
            self.edit.setText(name)
        self.combo.currentIndexChanged.connect(self._auswahl_geaendert)
        self.edit.editingFinished.connect(self.aktualisieren)

        self.hinweis_label = QLabel("", self)
        self.hinweis_label.setWordWrap(True)
        layout.addRow(self.hinweis_label)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        layout.addRow("Status:", self.status_label)

        self.fortschritt = QProgressBar(self)
        self.fortschritt.setRange(0, 100)
        self.fortschritt.setVisible(False)
        layout.addRow(self.fortschritt)

        knopfzeile = QHBoxLayout()
        self.download_button = QPushButton("Jetzt herunterladen", self)
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self.herunterladen)
        self.pruefen_button = QPushButton("Status prüfen", self)
        self.pruefen_button.clicked.connect(self.aktualisieren)
        knopfzeile.addWidget(self.download_button)
        knopfzeile.addWidget(self.pruefen_button)
        knopfzeile.addStretch(1)
        layout.addRow(knopfzeile)

        self._optionen = optionen
        self._auswahl_geaendert()

    def modell(self) -> str:
        """Der aktuell eingestellte Modellname (leer, wenn ein eigener Name fehlt)."""
        if self.combo.currentData() == EIGENES_MODELL:
            return self.edit.text().strip()
        return str(self.combo.currentData())

    def modell_oder_standard(self) -> str:
        return self.modell() or self._standard

    def _auswahl_geaendert(self, _index: int = 0) -> None:
        self.edit.setVisible(self.combo.currentData() == EIGENES_MODELL)
        option = ollama_service.get_modell_option(self.modell())
        self.hinweis_label.setText(option.hinweis if option else "")
        self.aktualisieren()
        self.modell_geaendert.emit(self.modell())

    def aktualisieren(self) -> None:
        modell = self.modell()
        if not modell:
            self.status_label.setText("Bitte einen Modellnamen eingeben.")
            self.download_button.setEnabled(False)
            return
        try:
            installiert = ollama_service.list_models(timeout=1.5)
        except ollama_service.OllamaError:
            self.status_label.setText(
                "Ollama ist nicht erreichbar. Ollama starten oder über „Einrichtung starten“ "
                "(Reiter Transkription) installieren, dann „Status prüfen“."
            )
            self.download_button.setEnabled(self._worker is None)
            return
        if ollama_service.is_model_available(modell):
            self.status_label.setText(f"✓ '{modell}' ist installiert.")
            self.download_button.setEnabled(False)
        else:
            weitere = [name for name in installiert if name]
            zusatz = f" Bereits installiert: {', '.join(weitere)}." if weitere else ""
            self.status_label.setText(f"'{modell}' ist noch nicht installiert.{zusatz}")
            self.download_button.setEnabled(self._worker is None)

    def herunterladen(self) -> None:
        modell = self.modell()
        if not modell or self._worker is not None:
            return
        self.download_button.setEnabled(False)
        self.combo.setEnabled(False)
        self.fortschritt.setValue(0)
        self.fortschritt.setVisible(True)
        self.status_label.setText(f"Lade '{modell}' herunter …")
        self._worker = OllamaPullWorker(modell, self)
        self._worker.fortschritt.connect(self._fortschritt_anzeigen)
        self._worker.fertig.connect(self._fertig)
        self._worker.fehlgeschlagen.connect(self._fehlgeschlagen)
        self._worker.start()

    def _fortschritt_anzeigen(self, status: str, fertig: int, gesamt: int) -> None:
        if gesamt > 0:
            self.fortschritt.setRange(0, 100)
            self.fortschritt.setValue(round(fertig / gesamt * 100))
            self.status_label.setText(f"{status}: {fertig / 1e9:.1f} von {gesamt / 1e9:.1f} GB")
        else:
            self.status_label.setText(status)

    def _beendet(self) -> None:
        self._worker = None
        self.fortschritt.setVisible(False)
        self.combo.setEnabled(True)

    def _fertig(self, modell: str) -> None:
        self._beendet()
        self.aktualisieren()

    def _fehlgeschlagen(self, modell: str, meldung: str) -> None:
        self._beendet()
        self.status_label.setText(f"Download fehlgeschlagen: {meldung}")
        self.download_button.setEnabled(True)
