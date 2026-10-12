"""Dialog "Gerät per USB einrichten" (Reiter "Aufnahmegeräte").

Der Anwender steckt das Geraet per USB an, gibt WLAN-Name und Passwort ein --
die Anwendung erzeugt das Token und schreibt WLAN, eigene Adresse und Token in
einem Zug ins Geraet (``services/geraete_usb_service.py``). Danach ist das Geraet
in der Liste, mit seiner Werks-Id, Board und Firmware.

Die serielle Verbindung blockiert bis zu einige Sekunden (Neustart des Geraets);
sie laeuft deshalb in einem eigenen Faden. Tests ersetzen ``_im_hintergrund``
durch einen direkten Aufruf.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.services import geraete_usb_service as usb

# Vorschlag fuer den Geraetenamen je Board; die letzten vier Zeichen der Id
# machen ihn eindeutig, ohne dass der Anwender nachdenken muss.
NAMEN_VORSCHLAG = {"esp32-c6": "C6", "esp32-s3-lcd": "S3-LCD", "esp32-s3-audio": "S3-Audio"}


class _Aufgabe(QThread):
    erfolg = Signal(object)
    fehler = Signal(str)

    def __init__(self, funktion: Callable[[], Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._funktion = funktion

    def run(self) -> None:
        try:
            self.erfolg.emit(self._funktion())
        except usb.UsbFehler as fehler:
            self.fehler.emit(str(fehler))
        except Exception as fehler:  # Ein unerwarteter Fehler darf den Faden nicht stumm beenden.
            self.fehler.emit(f"Unerwarteter Fehler: {fehler}")


def namensvorschlag(info: usb.GeraeteInfo) -> str:
    return f"{NAMEN_VORSCHLAG.get(info.board, 'Geraet')}-{info.geraete_id[-4:]}"


class UsbEinrichtungDialog(QDialog):
    """``ergebnis`` ist nach einer erfolgreichen Einrichtung der neue Eintrag
    fuer ``geraete_empfang_geraete`` (mit Token-Hash, Id, Board, Firmware)."""

    def __init__(
        self,
        vorhandene: list[dict[str, Any]],
        basis_url: str,
        parent: QWidget | None = None,
        *,
        oeffnen: Callable[[str], usb.SerielleVerbindung] | None = None,
        anschluesse: Callable[[], list[usb.Anschluss]] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Gerät per USB einrichten")
        self.resize(560, 480)
        self._vorhandene = vorhandene
        # Erst beim Aufruf aufgeloest, damit Tests den Dienst ersetzen koennen,
        # ohne echte serielle Anschluesse anzufassen.
        self._oeffnen_fn = oeffnen
        self._anschluesse_fn = anschluesse
        self._info: usb.GeraeteInfo | None = None
        self._aufgabe: _Aufgabe | None = None
        self.ergebnis: dict[str, Any] | None = None
        self.inventar_zeile = ""

        layout = QVBoxLayout(self)
        anleitung = QLabel(
            "1. Gerät per USB-Kabel an diesen PC anschließen.  2. Anschluss wählen und „Gerät erkennen“.  "
            "3. WLAN eingeben und „Einrichten“. Das Gerät startet danach neu und meldet sich im WLAN an.",
            self,
        )
        anleitung.setWordWrap(True)
        layout.addWidget(anleitung)

        zeile = QHBoxLayout()
        self.anschluss_combo = QComboBox(self)
        zeile.addWidget(self.anschluss_combo, stretch=1)
        self.aktualisieren_button = QPushButton("Aktualisieren", self)
        self.aktualisieren_button.clicked.connect(self.anschluesse_laden)
        zeile.addWidget(self.aktualisieren_button)
        self.erkennen_button = QPushButton("Gerät erkennen", self)
        self.erkennen_button.clicked.connect(self._erkennen)
        zeile.addWidget(self.erkennen_button)
        layout.addLayout(zeile)

        self.geraet_label = QLabel("Noch kein Gerät erkannt.", self)
        self.geraet_label.setWordWrap(True)
        layout.addWidget(self.geraet_label)

        formular = QFormLayout()
        self.name_edit = QLineEdit(self)
        formular.addRow("Name in der Liste:", self.name_edit)
        self.wlan_edit = QLineEdit(self)
        formular.addRow("WLAN-Name:", self.wlan_edit)
        self.passwort_edit = QLineEdit(self)
        self.passwort_edit.setEchoMode(QLineEdit.Password)
        formular.addRow("WLAN-Passwort:", self.passwort_edit)
        self.passwort_zeigen = QCheckBox("Passwort anzeigen", self)
        self.passwort_zeigen.toggled.connect(
            lambda an: self.passwort_edit.setEchoMode(QLineEdit.Normal if an else QLineEdit.Password)
        )
        formular.addRow("", self.passwort_zeigen)
        self.adresse_edit = QLineEdit(basis_url, self)
        formular.addRow("Adresse dieses PCs:", self.adresse_edit)
        self.server_url_edit = QLineEdit(self)
        self.server_url_edit.setPlaceholderText("optional, z. B. http://server:8765")
        formular.addRow("Server (Servermodus):", self.server_url_edit)
        self.server_token_edit = QLineEdit(self)
        self.server_token_edit.setEchoMode(QLineEdit.Password)
        self.server_token_edit.setPlaceholderText("Token aus --token-erzeugen auf dem Server")
        formular.addRow("Server-Token:", self.server_token_edit)
        self.erste_nummer_spin = QSpinBox(self)
        self.erste_nummer_spin.setRange(1, 999999)
        formular.addRow("Erste hochzuladende Aufnahme:", self.erste_nummer_spin)
        layout.addLayout(formular)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        knoepfe = QHBoxLayout()
        self.einrichten_button = QPushButton("Einrichten", self)
        self.einrichten_button.setEnabled(False)
        self.einrichten_button.clicked.connect(self._einrichten)
        knoepfe.addWidget(self.einrichten_button)
        self.inventar_button = QPushButton("Zeile fürs Inventar kopieren", self)
        self.inventar_button.setVisible(False)
        self.inventar_button.clicked.connect(lambda: QApplication.clipboard().setText(self.inventar_zeile))
        knoepfe.addWidget(self.inventar_button)
        knoepfe.addStretch(1)
        schliessen = QPushButton("Schließen", self)
        schliessen.clicked.connect(self._schliessen)
        knoepfe.addWidget(schliessen)
        layout.addLayout(knoepfe)

        self.anschluesse_laden()

    # ------------------------------------------------------------------
    def anschluesse_laden(self) -> None:
        self.anschluss_combo.clear()
        try:
            gefunden = (self._anschluesse_fn or usb.anschluesse_finden)()
        except usb.UsbFehler as fehler:
            self.status_label.setText(str(fehler))
            gefunden = []
        for anschluss in gefunden:
            text = f"{anschluss.port} – {anschluss.beschreibung}" + (" (ESP32)" if anschluss.espressif else "")
            self.anschluss_combo.addItem(text, anschluss.port)
        self.erkennen_button.setEnabled(bool(gefunden))
        if not gefunden:
            self.geraet_label.setText("Kein serieller Anschluss gefunden. Ist das Gerät per USB angeschlossen?")

    def _oeffnen(self, port: str) -> usb.SerielleVerbindung:
        return (self._oeffnen_fn or usb.verbindung_oeffnen)(port)

    def _beschaeftigt(self, an: bool, text: str | None = None) -> None:
        for knopf in (self.erkennen_button, self.aktualisieren_button):
            knopf.setEnabled(not an)
        self.einrichten_button.setEnabled(not an and self._info is not None)
        if text is not None:
            self.status_label.setText(text)

    def _laeuft(self) -> bool:
        return self._aufgabe is not None and self._aufgabe.isRunning()

    def _im_hintergrund(self, funktion: Callable[[], Any], bei_erfolg: Callable[[Any], None]) -> None:
        aufgabe = _Aufgabe(funktion, self)
        aufgabe.erfolg.connect(bei_erfolg)
        aufgabe.fehler.connect(self._fehlgeschlagen)
        self._aufgabe = aufgabe
        aufgabe.start()

    def _fehlgeschlagen(self, text: str) -> None:
        self._beschaeftigt(False)
        self.status_label.setText(f"❌ {text}")

    # ------------------------------------------------------------------
    def _erkennen(self) -> None:
        port = self.anschluss_combo.currentData()
        if not port:
            return

        def abfragen() -> usb.GeraeteInfo:
            sitzung = usb.Geraetesitzung(self._oeffnen(port))
            try:
                return sitzung.info()
            finally:
                sitzung.schliessen()

        self._beschaeftigt(True, f"Frage {port} ab …")
        self._im_hintergrund(abfragen, self._erkannt)

    def _erkannt(self, info: usb.GeraeteInfo) -> None:
        self._info = info
        bekannt = self._eintrag_zur_id(info.geraete_id)
        if bekannt is not None:
            self.name_edit.setText(str(bekannt.get("name", "")))
        elif not self.name_edit.text().strip():
            self.name_edit.setText(namensvorschlag(info))
        if info.wlan and not self.wlan_edit.text():
            self.wlan_edit.setText(info.wlan)
        zustand = f"eingerichtet für WLAN „{info.wlan}“" if info.eingerichtet else "noch nicht eingerichtet"
        hinweis = f" – schon in der Liste als „{bekannt.get('name')}“, wird neu eingerichtet" if bekannt else ""
        self.geraet_label.setText(
            f"Erkannt: {info.board}, Id {info.geraete_id}, Firmware {info.firmware} ({zustand}){hinweis}."
        )
        self._beschaeftigt(False, "")

    def _eintrag_zur_id(self, geraete_id: str) -> dict[str, Any] | None:
        return next((e for e in self._vorhandene if e.get("geraete_id") == geraete_id), None)

    def _einrichten(self) -> None:
        info = self._info
        port = self.anschluss_combo.currentData()
        if info is None or not port:
            return
        name = self.name_edit.text().strip()
        if not geraete_empfang_service.geraetename_gueltig(name):
            self.status_label.setText("❌ Name: Buchstaben, Ziffern, „_“ und „-“, höchstens 32 Zeichen, ohne Leerzeichen.")
            return
        doppelt = any(
            str(e.get("name", "")).lower() == name.lower() and e.get("geraete_id") != info.geraete_id
            for e in self._vorhandene
        )
        if doppelt:
            self.status_label.setText(f"❌ Ein anderes Gerät heißt schon „{name}“.")
            return
        token = geraete_empfang_service.token_erzeugen()
        einrichtung = usb.Einrichtung(
            wlan_ssid=self.wlan_edit.text(),
            wlan_passwort=self.passwort_edit.text(),
            pc_url=self.adresse_edit.text().strip(),
            pc_token=token,
            server_url=self.server_url_edit.text().strip(),
            server_token=self.server_token_edit.text().strip(),
            erste_nummer=self.erste_nummer_spin.value() if self.erste_nummer_spin.value() > 1 else None,
        )
        meldungen = einrichtung.fehler()
        if meldungen:
            self.status_label.setText("❌ " + " ".join(meldungen))
            return

        def schreiben() -> usb.GeraeteInfo:
            sitzung = usb.Geraetesitzung(self._oeffnen(port))
            try:
                sitzung.einrichten(einrichtung)
            finally:
                sitzung.schliessen()
            neu = usb.nach_neustart_verbinden(port, self._oeffnen)
            try:
                return neu.info()
            finally:
                neu.schliessen()

        self._beschaeftigt(True, "Schreibe ins Gerät, danach startet es neu …")
        self._im_hintergrund(schreiben, lambda neu_info: self._eingerichtet(neu_info, name, token))

    def _eingerichtet(self, info: usb.GeraeteInfo, name: str, token: str) -> None:
        self._beschaeftigt(False)
        if not (info.eingerichtet and info.token_pc):
            self.status_label.setText("❌ Das Gerät meldet nach dem Neustart keine Einrichtung. Bitte erneut versuchen.")
            return
        heute = dt.date.today().isoformat()
        self.ergebnis = {
            "name": name,
            "token_sha256": geraete_empfang_service.token_hash(token),
            "angelegt": heute,
            "geraete_id": info.geraete_id,
            "board": info.board,
            "firmware": info.firmware,
        }
        self.inventar_zeile = usb.inventarzeile(info, name, heute)
        self.inventar_button.setVisible(True)
        self.status_label.setText(
            f"✅ „{name}“ ist eingerichtet und in der Liste gespeichert. Es meldet sich, sobald der Empfang "
            "eingeschaltet ist und das Gerät im WLAN ist. Bitte im Inventar eintragen."
        )

    def _schliessen(self) -> None:
        if self.ergebnis is not None and not self._laeuft():
            self.accept()
        else:
            self.reject()

    def reject(self) -> None:
        # Laeuft die serielle Verbindung noch, darf der Dialog (und mit ihm der
        # Faden) nicht verschwinden -- das Geraet waere halb beschrieben.
        if self._laeuft():
            self.status_label.setText("Bitte warten, das Gerät wird gerade beschrieben …")
            return
        if self.ergebnis is not None:
            self.accept()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._laeuft():
            self.status_label.setText("Bitte warten, das Gerät wird gerade beschrieben …")
            event.ignore()
            return
        super().closeEvent(event)
