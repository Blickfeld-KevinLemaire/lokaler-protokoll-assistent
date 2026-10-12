"""Aufnahmegeraete im WLAN: Einstellungsseite und Steuerung des Empfangs.

Der Empfang selbst (HTTP, Pruefsumme, Ablage) steckt ohne Qt in
``services/geraete_empfang_service.py`` und wird vom Servermodus genauso
benutzt. Hier liegt nur, was die Windows-Anwendung zusaetzlich braucht:

* :class:`EmpfangsSteuerung` startet und stoppt den Dienst nach den
  Einstellungen und meldet neue Aufnahmen als Qt-Signal an das Hauptfenster.
* :class:`GeraeteSeite` ist der Reiter "Aufnahmegeräte" im Einstellungsdialog:
  Empfang an/aus, Port, Geraete anlegen und entfernen.

Ein Token wird beim Anlegen genau einmal angezeigt; gespeichert wird nur sein
SHA-256 in ``konfiguration.json``.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.utils import app_config

SICHERHEITS_HINWEIS = (
    "Ist der Empfang eingeschaltet, nimmt die Anwendung im lokalen Netz Aufnahmen von den "
    "eingetragenen Geräten an. Jedes Gerät meldet sich mit seinem eigenen Token an. Die Übertragung "
    "ist nicht verschlüsselt: Nur im eigenen, vertrauenswürdigen WLAN einschalten. Beim ersten Start "
    "fragt die Windows-Firewall, ob die Anwendung Verbindungen annehmen darf – für private Netzwerke zulassen."
)


# --------------------------------------------------------------------------
# Steuerung
# --------------------------------------------------------------------------
class EmpfangsSteuerung(QObject):
    """Haelt den Empfangsdienst passend zu Einstellungen und Zielordner.

    ``neue_aufnahme`` wird aus dem Faden des Dienstes ausgeloest; Qt stellt es
    dem Hauptfenster ueber dessen Ereignisschleife zu."""

    neue_aufnahme = Signal(str, str)  # Pfad der Datei, Geraetename

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        dienst_fabrik: Callable[..., geraete_empfang_service.GeraeteEmpfang] | None = None,
    ):
        super().__init__(parent)
        # Erst beim Start aufgeloest, nicht hier: So laesst sich der Dienst in
        # Tests auch nach dem Bau des Fensters noch ersetzen.
        self._fabrik = dienst_fabrik
        self._dienst: geraete_empfang_service.GeraeteEmpfang | None = None
        self._stand: tuple[Any, ...] | None = None
        self.fehler: str | None = None

    @property
    def laeuft(self) -> bool:
        return self._dienst is not None

    def anwenden(self, ziel: Path, konfiguration: dict[str, Any] | None = None) -> None:
        """Startet, stoppt oder startet neu -- nur wenn sich etwas geaendert hat."""
        config = konfiguration if konfiguration is not None else app_config.load_config()
        geraete = geraete_empfang_service.geraete_aus_konfiguration(config.get("geraete_empfang_geraete") or [])
        aktiv = bool(config.get("geraete_empfang_aktiv")) and bool(geraete)
        port = _port(config.get("geraete_empfang_port"))
        stand = (aktiv, port, geraete, ziel)
        if stand == self._stand and (self._dienst is not None or not aktiv):
            return
        self.stoppen()
        self._stand = stand
        self.fehler = None
        if not aktiv:
            return
        fabrik = self._fabrik or geraete_empfang_service.GeraeteEmpfang
        dienst = fabrik(ziel, geraete, port=port, bei_neuer_aufnahme=self._melden)
        try:
            dienst.starten()
        except OSError as fehler:
            self.fehler = f"Port {port} ist nicht nutzbar ({fehler.strerror or fehler}). Anderen Port in den Einstellungen wählen."
            return
        self._dienst = dienst

    def kontakte(self) -> dict[str, geraete_empfang_service.Kontakt]:
        """Letzter Kontakt je Geraet, solange der Empfang laeuft."""
        return self._dienst.kontakte() if self._dienst is not None else {}

    def stoppen(self) -> None:
        dienst, self._dienst = self._dienst, None
        self._stand = None
        if dienst is not None:
            dienst.stoppen()

    def beschreibung(self) -> str:
        """Kurzer Zustand fuer das Hauptfenster; leer, wenn der Empfang aus ist."""
        if self.fehler:
            return f"Aufnahmegeräte: {self.fehler}"
        if self._dienst is None or self._stand is None:
            return ""
        _aktiv, port, geraete, ziel = self._stand
        anzahl = len(geraete)
        return f"Aufnahmegeräte: Empfang an (Port {port}, {anzahl} {'Gerät' if anzahl == 1 else 'Geräte'}) → {ziel}"

    def _melden(self, pfad: Path, geraet: str) -> None:
        self.neue_aufnahme.emit(str(pfad), geraet)


def _port(wert: Any) -> int:
    try:
        port = int(wert)
    except (TypeError, ValueError):
        return geraete_empfang_service.STANDARD_PORT
    return port if 1 <= port <= 65535 else geraete_empfang_service.STANDARD_PORT


# --------------------------------------------------------------------------
# Einstellungsseite
# --------------------------------------------------------------------------
def kontakt_text(kontakt: geraete_empfang_service.Kontakt | None) -> str:
    """Spalte "Zuletzt gesehen": wann, von wo, welche Hardware und Firmware."""
    if kontakt is None:
        return "–"
    teile = [time.strftime("%d.%m. %H:%M", time.localtime(kontakt.zeit)), kontakt.adresse]
    if kontakt.geraete_id:
        teile.append(f"Id {kontakt.geraete_id}")
    if kontakt.firmware:
        teile.append(kontakt.firmware)
    return ", ".join(teile)


def konfigurationszeilen(basis_url: str, token: str) -> str:
    """Was in die ``server_config.h`` des Geraets gehoert (siehe ``firmware/``)."""
    return f'#define VERMERK_PC_BASE_URL  "{basis_url}"\n#define VERMERK_PC_TOKEN     "{token}"\n'


class TokenDialog(QDialog):
    """Zeigt das Token eines neuen Geraets genau einmal an."""

    def __init__(self, name: str, token: str, basis_url: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Token für „{name}“")
        layout = QVBoxLayout(self)
        hinweis = QLabel(
            "Dieses Token wird nur jetzt angezeigt. Tragen Sie es zusammen mit der Adresse in die "
            "Konfiguration des Geräts ein (server_config.h). Geht es verloren, das Gerät entfernen "
            "und neu anlegen. Gültig wird es mit „Speichern“ im Einstellungsdialog.",
            self,
        )
        hinweis.setWordWrap(True)
        layout.addWidget(hinweis)
        self.token_feld = QLineEdit(token, self)
        self.token_feld.setReadOnly(True)
        layout.addWidget(self.token_feld)
        self.konfiguration_feld = QPlainTextEdit(konfigurationszeilen(basis_url, token), self)
        self.konfiguration_feld.setReadOnly(True)
        layout.addWidget(self.konfiguration_feld)
        kopieren = QPushButton("Zeilen kopieren", self)
        kopieren.clicked.connect(self._kopieren)
        layout.addWidget(kopieren)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok, self)
        knoepfe.accepted.connect(self.accept)
        layout.addWidget(knoepfe)

    def _kopieren(self) -> None:
        QApplication.clipboard().setText(self.konfiguration_feld.toPlainText())


class GeraeteSeite(QWidget):
    """Reiter "Aufnahmegeräte" im Einstellungsdialog."""

    def __init__(
        self,
        config: dict[str, Any],
        parent: QWidget | None = None,
        kontakte: dict[str, geraete_empfang_service.Kontakt] | None = None,
    ):
        super().__init__(parent)
        self._kontakte = dict(kontakte or {})
        self._geraete: list[dict[str, Any]] = [
            dict(eintrag)
            for eintrag in (config.get("geraete_empfang_geraete") or [])
            if isinstance(eintrag, dict)
        ]
        layout = QVBoxLayout(self)

        erklaerung = QLabel(
            "Die WLAN-Aufnahmegeräte laden ihre Aufnahmen selbst in den Eingabeordner dieser Anwendung "
            "hoch (ohne Eingabeordner: in den Ordner „aufnahmen“). Jedes Gerät braucht ein eigenes Token.",
            self,
        )
        erklaerung.setWordWrap(True)
        layout.addWidget(erklaerung)

        self.aktiv_checkbox = QCheckBox("Empfang für Aufnahmegeräte einschalten", self)
        self.aktiv_checkbox.setChecked(bool(config.get("geraete_empfang_aktiv")))
        layout.addWidget(self.aktiv_checkbox)

        port_zeile = QHBoxLayout()
        port_zeile.addWidget(QLabel("Port:", self))
        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(_port(config.get("geraete_empfang_port")))
        self.port_spin.valueChanged.connect(self._adressen_anzeigen)
        port_zeile.addWidget(self.port_spin)
        port_zeile.addStretch(1)
        layout.addLayout(port_zeile)

        self.adressen_label = QLabel(self)
        self.adressen_label.setWordWrap(True)
        self.adressen_label.setTextInteractionFlags(self.adressen_label.textInteractionFlags() | Qt.TextSelectableByMouse)
        layout.addWidget(self.adressen_label)

        self.tabelle = QTableWidget(0, 3, self)
        self.tabelle.setHorizontalHeaderLabels(["Gerät", "Angelegt", "Zuletzt gesehen"])
        self.tabelle.horizontalHeader().setStretchLastSection(True)
        self.tabelle.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.tabelle, stretch=1)

        knoepfe = QHBoxLayout()
        self.hinzufuegen_button = QPushButton("Gerät hinzufügen …", self)
        self.hinzufuegen_button.clicked.connect(self._hinzufuegen)
        self.entfernen_button = QPushButton("Entfernen", self)
        self.entfernen_button.clicked.connect(self._entfernen)
        knoepfe.addWidget(self.hinzufuegen_button)
        knoepfe.addWidget(self.entfernen_button)
        knoepfe.addStretch(1)
        layout.addLayout(knoepfe)

        hinweis = QLabel(SICHERHEITS_HINWEIS, self)
        hinweis.setWordWrap(True)
        layout.addWidget(hinweis)

        self._tabelle_fuellen()
        self._adressen_anzeigen()

    # ------------------------------------------------------------------
    def aenderungen(self) -> dict[str, Any]:
        """Die Werte fuer ``app_config.update_config``."""
        return {
            "geraete_empfang_aktiv": self.aktiv_checkbox.isChecked(),
            "geraete_empfang_port": self.port_spin.value(),
            "geraete_empfang_geraete": [dict(eintrag) for eintrag in self._geraete],
        }

    def basis_url(self) -> str:
        adressen = geraete_empfang_service.lokale_adressen()
        rechner = adressen[0] if adressen else "<Adresse dieses PCs>"
        return f"http://{rechner}:{self.port_spin.value()}"

    # ------------------------------------------------------------------
    def _adressen_anzeigen(self) -> None:
        adressen = geraete_empfang_service.lokale_adressen()
        port = self.port_spin.value()
        if adressen:
            text = "Adresse für die Geräte: " + ", ".join(f"http://{a}:{port}" for a in adressen)
        else:
            text = "Die Adresse dieses PCs im lokalen Netz ließ sich nicht ermitteln (ipconfig zeigt sie an)."
        self.adressen_label.setText(text)

    def _tabelle_fuellen(self) -> None:
        self.tabelle.setRowCount(0)
        for eintrag in self._geraete:
            zeile = self.tabelle.rowCount()
            self.tabelle.insertRow(zeile)
            self.tabelle.setItem(zeile, 0, QTableWidgetItem(str(eintrag.get("name", ""))))
            self.tabelle.setItem(zeile, 1, QTableWidgetItem(str(eintrag.get("angelegt", ""))))
            self.tabelle.setItem(zeile, 2, QTableWidgetItem(kontakt_text(self._kontakte.get(str(eintrag.get("name", ""))))))

    def _name_erfragen(self) -> str | None:
        name, ok = QInputDialog.getText(self, "Gerät hinzufügen", "Name des Geräts (z. B. S3-Audio):")
        return name.strip() if ok else None

    def _token_zeigen(self, name: str, token: str) -> None:
        TokenDialog(name, token, self.basis_url(), self).exec()

    def _hinzufuegen(self) -> None:
        name = self._name_erfragen()
        if not name:
            return
        if not geraete_empfang_service.geraetename_gueltig(name):
            QMessageBox.warning(
                self,
                "Gerät hinzufügen",
                "Erlaubt sind Buchstaben, Ziffern, „_“ und „-“, höchstens 32 Zeichen, ohne Leerzeichen.",
            )
            return
        if any(str(e.get("name", "")).lower() == name.lower() for e in self._geraete):
            QMessageBox.warning(self, "Gerät hinzufügen", f"Ein Gerät „{name}“ gibt es schon.")
            return
        token = geraete_empfang_service.token_erzeugen()
        self._geraete.append(
            {
                "name": name,
                "token_sha256": geraete_empfang_service.token_hash(token),
                "angelegt": dt.date.today().isoformat(),
            }
        )
        self._tabelle_fuellen()
        self._token_zeigen(name, token)

    def _entfernen(self) -> None:
        zeilen = sorted({index.row() for index in self.tabelle.selectedIndexes()}, reverse=True)
        for zeile in zeilen:
            if 0 <= zeile < len(self._geraete):
                del self._geraete[zeile]
        self._tabelle_fuellen()
