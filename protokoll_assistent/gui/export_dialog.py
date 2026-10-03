"""Dialog "Exportieren": Transkript und/oder Protokoll in gaengige Formate
(Word, PDF, Markdown, Text, HTML, OpenDocument, Untertitel, JSON) in einen
frei gewaehlten Ordner.

Die eigentliche Arbeit macht ``services.dokument_export_service``; der Dialog
sammelt nur Inhalt, Formate und Ziel. Unabhaengig davon legt die Verarbeitung
von selbst immer eine zusammengefasste Word-Datei neben die Ausgaben.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from protokoll_assistent.services import dokument_export_service as export
from protokoll_assistent.utils import app_config

STANDARD_FORMATE = ["docx", "pdf"]


class ExportDialog(QDialog):
    def __init__(
        self,
        transkript_json: Path | None,
        protokoll_json: Path | None,
        start_ordner: Path,
        schreiber: dict[str, export.Schreiber] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.resize(560, 520)
        self._transkript_json = transkript_json
        self._protokoll_json = protokoll_json
        self._schreiber = schreiber or {}
        self.geschrieben: list[Path] = []

        konfig = app_config.load_config()
        layout = QVBoxLayout(self)
        titel = QLabel("Exportieren", self)
        titel.setObjectName("PageTitle")
        layout.addWidget(titel)
        untertitel = QLabel(
            "Transkript und Protokoll in das gewünschte Format bringen und in einen Ordner Ihrer Wahl "
            "legen. Eine zusammengefasste Word-Datei entsteht außerdem bei jeder Verarbeitung von selbst.",
            self,
        )
        untertitel.setObjectName("PageSubtitle")
        untertitel.setWordWrap(True)
        layout.addWidget(untertitel)

        # Inhalt
        layout.addWidget(QLabel("Was soll exportiert werden?", self))
        self.transkript_radio = QRadioButton("Transkript", self)
        self.protokoll_radio = QRadioButton("Protokoll / Zusammenfassung", self)
        self.beides_radio = QRadioButton("Beides in einem Dokument (Protokoll, danach das Transkript)", self)
        self._inhalt_gruppe = QButtonGroup(self)
        for radio in (self.transkript_radio, self.protokoll_radio, self.beides_radio):
            self._inhalt_gruppe.addButton(radio)
            layout.addWidget(radio)
            radio.toggled.connect(self._formate_aktualisieren)

        protokoll_zeile = QHBoxLayout()
        self.protokoll_label = QLabel("", self)
        self.protokoll_label.setWordWrap(True)
        protokoll_zeile.addWidget(self.protokoll_label, stretch=1)
        self.protokoll_waehlen_button = QPushButton("Protokoll wählen …", self)
        self.protokoll_waehlen_button.clicked.connect(self._protokoll_waehlen)
        protokoll_zeile.addWidget(self.protokoll_waehlen_button)
        layout.addLayout(protokoll_zeile)

        # Formate
        layout.addWidget(QLabel("Formate:", self))
        raster = QGridLayout()
        self.format_checkboxen: dict[str, QCheckBox] = {}
        gemerkt = konfig.get("export_formate") or STANDARD_FORMATE
        for index, format_ in enumerate(export.FORMATE):
            box = QCheckBox(format_.name, self)
            box.setChecked(format_.id in gemerkt)
            self.format_checkboxen[format_.id] = box
            raster.addWidget(box, index // 2, index % 2)
        layout.addLayout(raster)

        # Ziel
        layout.addWidget(QLabel("Zielordner:", self))
        ziel_zeile = QHBoxLayout()
        self.ziel_edit = QLineEdit(str(konfig.get("export_zielordner") or start_ordner), self)
        ziel_zeile.addWidget(self.ziel_edit, stretch=1)
        self.ziel_waehlen_button = QPushButton("Wählen …", self)
        self.ziel_waehlen_button.clicked.connect(self._ziel_waehlen)
        ziel_zeile.addWidget(self.ziel_waehlen_button)
        layout.addLayout(ziel_zeile)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        knoepfe = QHBoxLayout()
        self.ordner_oeffnen_button = QPushButton("Ordner öffnen", self)
        self.ordner_oeffnen_button.setEnabled(False)
        self.ordner_oeffnen_button.clicked.connect(self._ordner_oeffnen)
        knoepfe.addWidget(self.ordner_oeffnen_button)
        knoepfe.addStretch(1)
        self.schliessen_button = QPushButton("Schließen", self)
        self.schliessen_button.clicked.connect(self.reject)
        knoepfe.addWidget(self.schliessen_button)
        self.exportieren_button = QPushButton("Exportieren", self)
        self.exportieren_button.setObjectName("PrimaryButton")
        self.exportieren_button.clicked.connect(self.exportieren)
        knoepfe.addWidget(self.exportieren_button)
        layout.addLayout(knoepfe)

        self._verfuegbarkeit_aktualisieren()
        # Vorauswahl: am meisten, was vorliegt
        if transkript_json is not None and self._protokoll_json is not None:
            self.beides_radio.setChecked(True)
        elif transkript_json is not None:
            self.transkript_radio.setChecked(True)
        elif self._protokoll_json is not None:
            self.protokoll_radio.setChecked(True)
        self._formate_aktualisieren()

    # ------------------------------------------------------------------
    def inhalt(self) -> str:
        if self.beides_radio.isChecked():
            return export.INHALT_BEIDES
        if self.protokoll_radio.isChecked():
            return export.INHALT_PROTOKOLL
        return export.INHALT_TRANSKRIPT

    def gewaehlte_formate(self) -> list[str]:
        return [f.id for f in export.FORMATE if self.format_checkboxen[f.id].isChecked() and self.format_checkboxen[f.id].isEnabled()]

    def _verfuegbarkeit_aktualisieren(self) -> None:
        hat_transkript = self._transkript_json is not None
        protokoll = self._protokoll_json
        self.transkript_radio.setEnabled(hat_transkript)
        self.protokoll_radio.setEnabled(protokoll is not None)
        self.beides_radio.setEnabled(hat_transkript and protokoll is not None)
        self.protokoll_label.setText(
            f"Protokoll: {protokoll.name}" if protokoll is not None else "Es liegt noch kein Protokoll vor."
        )

    def _formate_aktualisieren(self, *_args) -> None:
        """Untertitel und JSON gibt es nicht fuer jeden Inhalt."""
        inhalt = self.inhalt()
        for format_ in export.FORMATE:
            box = self.format_checkboxen[format_.id]
            moeglich = inhalt in format_.inhalte
            box.setEnabled(moeglich)
            box.setToolTip("" if moeglich else "Für diesen Inhalt nicht verfügbar.")

    def _protokoll_waehlen(self) -> None:
        start = str(self._protokoll_json.parent) if self._protokoll_json else self.ziel_edit.text()
        datei, _ = QFileDialog.getOpenFileName(self, "Protokoll wählen", start, "Protokoll (*.json)")
        if not datei:
            return
        self._protokoll_json = Path(datei)
        self._verfuegbarkeit_aktualisieren()
        if self._transkript_json is not None:
            self.beides_radio.setChecked(True)
        else:
            self.protokoll_radio.setChecked(True)

    def _ziel_waehlen(self) -> None:
        ordner = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.ziel_edit.text())
        if ordner:
            self.ziel_edit.setText(ordner)

    def _ordner_oeffnen(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.ziel_edit.text().strip()))

    # ------------------------------------------------------------------
    def exportieren(self) -> None:
        formate = self.gewaehlte_formate()
        ziel_text = self.ziel_edit.text().strip()
        if not ziel_text:
            self._melden("Bitte einen Zielordner wählen.", fehler=True)
            return
        if not formate:
            self._melden("Bitte mindestens ein Format ankreuzen.", fehler=True)
            return
        ziel = Path(ziel_text)
        try:
            self.geschrieben = export.exportiere(
                self.inhalt(),
                formate,
                ziel,
                transkript_json=self._transkript_json,
                protokoll_json=self._protokoll_json,
                schreiber=self._schreiber,
            )
            fehlermeldung = ""
        except export.ExportTeilweise as teilweise:
            self.geschrieben = teilweise.geschrieben
            fehlermeldung = "\n".join(teilweise.fehler)
        except (export.ExportFehler, OSError) as fehler:
            self._melden(str(fehler), fehler=True)
            return

        # Auswahl merken (nur, was wirklich gelaufen ist)
        app_config.update_config(export_zielordner=str(ziel), export_formate=formate)
        text = "Gespeichert in " + str(ziel) + ":\n" + "\n".join(f"• {p.name}" for p in self.geschrieben)
        if fehlermeldung:
            text += "\n\nNicht geschrieben:\n" + fehlermeldung
        self._melden(text, fehler=bool(fehlermeldung))
        self.ordner_oeffnen_button.setEnabled(True)

    def _melden(self, text: str, fehler: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet("color: #b00020;" if fehler else "")
