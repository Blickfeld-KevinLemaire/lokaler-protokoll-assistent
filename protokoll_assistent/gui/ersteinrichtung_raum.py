"""Ersteinrichtung, Schritt "Vermerk Raum": das Aufnahmegeraet (Waveshare
ESP32-S3) gleich beim ersten Start verbinden -- oder den Schritt ueberspringen.

Gefuehrt in vier Unterseiten, das Geraet haengt dabei per USB am Rechner:

1. Frage       -- Gibt es ein Vermerk Raum? Nein: "Ueberspringen".
2. Anschliessen -- USB-Anschluss suchen, Geraet erkennen (automatisch, wenn
                  genau ein ESP32 angeschlossen ist).
3. WLAN        -- WLAN-Name und Passwort; Adresse dieses PCs und ein neues
                  Token schreibt die Anwendung selbst ins Geraet.
4. Fertig      -- Das Geraet ist in der Liste, der Empfang eingeschaltet.

Die Arbeit am Geraet ist dieselbe wie im Einstellungsdialog (Reiter
"Aufnahmegeräte", ``gui/geraete_usb_einrichtung.py``) und nutzt denselben Dienst
(``services/geraete_usb_service.py``); dort bleibt die Einrichtung auch spaeter
moeglich. Die serielle Verbindung blockiert bis zu einige Sekunden (Neustart des
Geraets) und laeuft deshalb in einem eigenen Faden; Tests ersetzen
``_im_hintergrund`` durch einen direkten Aufruf.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.gui.geraete_usb_einrichtung import _Aufgabe, namensvorschlag
from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.services import geraete_usb_service as usb
from protokoll_assistent.utils import app_config

(U_FRAGE, U_ANSCHLIESSEN, U_WLAN, U_FERTIG) = range(4)

KEIN_ANSCHLUSS = "Kein serieller Anschluss gefunden. Ist das Vermerk Raum per USB angeschlossen und eingeschaltet?"


def _text(text: str, eltern: QWidget, *, untertitel: bool = False) -> QLabel:
    label = QLabel(text, eltern)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    if untertitel:
        label.setObjectName("PageSubtitle")
    return label


class VermerkRaumSeite(QWidget):
    """Eine Seite des Einrichtungsassistenten, die intern vier Unterseiten hat.

    ``weiter`` und ``zurueck`` melden dem Assistenten, dass er zur naechsten
    beziehungsweise vorigen Seite gehen soll (auch beim Ueberspringen).
    ``eingerichtet`` wird ausgeloest, sobald ein Geraet in die Konfiguration
    geschrieben wurde -- der Assistent startet danach den Empfang."""

    weiter = Signal()
    zurueck = Signal()
    eingerichtet = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        oeffnen: Callable[[str], usb.SerielleVerbindung] | None = None,
        anschluesse: Callable[[], list[usb.Anschluss]] | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("WizardPage")
        # Erst beim Aufruf aufgeloest, damit Tests den Dienst ersetzen koennen,
        # ohne echte serielle Anschluesse anzufassen.
        self._oeffnen_fn = oeffnen
        self._anschluesse_fn = anschluesse
        self._info: usb.GeraeteInfo | None = None
        self._aufgabe: _Aufgabe | None = None
        self._adresse_bekannt = True
        self.ergebnis: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        titel = QLabel("Vermerk Raum einrichten (optional)", self)
        titel.setObjectName("PageTitle")
        layout.addWidget(titel)
        self.fortschritt_label = _text("", self, untertitel=True)
        layout.addWidget(self.fortschritt_label)

        self.unterseiten = QStackedWidget(self)
        for bauen in (self._baue_frage, self._baue_anschliessen, self._baue_wlan, self._baue_fertig):
            self.unterseiten.addWidget(bauen())
        layout.addWidget(self.unterseiten, stretch=1)

        self.status_label = _text("", self)
        layout.addWidget(self.status_label)

        unten = QHBoxLayout()
        self.zurueck_button = QPushButton("Zurück", self)
        self.zurueck_button.clicked.connect(self._zurueck)
        unten.addWidget(self.zurueck_button)
        self.ueberspringen_button = QPushButton("Überspringen", self)
        self.ueberspringen_button.setToolTip(
            "Ohne Vermerk Raum weitermachen. Später: Einstellungen → Aufnahmegeräte."
        )
        self.ueberspringen_button.clicked.connect(self.weiter.emit)
        unten.addWidget(self.ueberspringen_button)
        unten.addStretch(1)
        self.primaer_button = QPushButton("", self)
        self.primaer_button.setObjectName("PrimaryButton")
        self.primaer_button.clicked.connect(self._primaer)
        unten.addWidget(self.primaer_button)
        layout.addLayout(unten)

        self._unterseite(U_FRAGE)

    # ------------------------------------------------------------------
    # Aufbau der Unterseiten
    # ------------------------------------------------------------------
    def _baue_frage(self) -> QWidget:
        seite = QWidget(self)
        layout = QVBoxLayout(seite)
        layout.addWidget(
            _text(
                "Das <b>Vermerk Raum</b> ist das Aufnahmegerät für Besprechungsräume (Waveshare ESP32-S3). "
                "Es nimmt auf und schickt die Aufnahmen per WLAN an diesen Computer; sie erscheinen dort im "
                "Eingabeordner.",
                seite,
            )
        )
        layout.addWidget(
            _text(
                "<p><b>Haben Sie ein Vermerk Raum?</b> Dann verbinden wir es jetzt mit diesem Computer – "
                "das dauert etwa eine Minute. Sie brauchen das USB-Kabel und den Namen und das Passwort Ihres "
                "WLANs.</p>"
                "<p>Wenn nicht, wählen Sie „Überspringen“. Die Einrichtung ist jederzeit nachholbar unter "
                "<b>Einstellungen → Aufnahmegeräte</b>.</p>",
                seite,
            )
        )
        layout.addStretch(1)
        return seite

    def _baue_anschliessen(self) -> QWidget:
        seite = QWidget(self)
        layout = QVBoxLayout(seite)
        layout.addWidget(
            _text(
                "<ol><li>Schließen Sie das Vermerk Raum mit einem <b>USB-Kabel</b> an diesen Computer an.</li>"
                "<li>Schalten Sie es ein und warten Sie einen Moment, bis Windows es erkannt hat.</li>"
                "<li>Das Gerät wird dann automatisch gesucht. Es kann ein paar Sekunden dauern.</li></ol>",
                seite,
            )
        )
        zeile = QHBoxLayout()
        self.anschluss_combo = QComboBox(seite)
        zeile.addWidget(self.anschluss_combo, stretch=1)
        self.suchen_button = QPushButton("Erneut suchen", seite)
        self.suchen_button.clicked.connect(self._suchen)
        zeile.addWidget(self.suchen_button)
        self.erkennen_button = QPushButton("Gerät erkennen", seite)
        self.erkennen_button.clicked.connect(self._erkennen)
        zeile.addWidget(self.erkennen_button)
        layout.addLayout(zeile)
        self.geraet_label = _text("Noch kein Gerät erkannt.", seite)
        layout.addWidget(self.geraet_label)
        layout.addStretch(1)
        return seite

    def _baue_wlan(self) -> QWidget:
        seite = QWidget(self)
        layout = QVBoxLayout(seite)
        layout.addWidget(
            _text(
                "Das Gerät meldet sich in Ihrem WLAN an, damit es Aufnahmen an diesen Computer schicken kann. "
                "Beide müssen im <b>selben Netz</b> sein. Das Gerät kann nur WLAN mit <b>2,4 GHz</b>.",
                seite,
            )
        )
        formular = QFormLayout()
        self.wlan_edit = QLineEdit(seite)
        formular.addRow("WLAN-Name:", self.wlan_edit)
        self.passwort_edit = QLineEdit(seite)
        self.passwort_edit.setEchoMode(QLineEdit.Password)
        formular.addRow("WLAN-Passwort:", self.passwort_edit)
        self.passwort_zeigen = QCheckBox("Passwort anzeigen", seite)
        self.passwort_zeigen.toggled.connect(
            lambda an: self.passwort_edit.setEchoMode(QLineEdit.Normal if an else QLineEdit.Password)
        )
        formular.addRow("", self.passwort_zeigen)
        self.name_edit = QLineEdit(seite)
        formular.addRow("Name in der Liste:", self.name_edit)
        self.adresse_edit = QLineEdit(seite)
        self.adresse_edit.setPlaceholderText("z. B. http://192.168.0.10:8765")
        self.adresse_zeile_label = QLabel("Adresse dieses PCs:", seite)
        formular.addRow(self.adresse_zeile_label, self.adresse_edit)
        layout.addLayout(formular)
        self.adresse_hinweis = _text("", seite, untertitel=True)
        layout.addWidget(self.adresse_hinweis)
        layout.addStretch(1)
        return seite

    def _baue_fertig(self) -> QWidget:
        seite = QWidget(self)
        layout = QVBoxLayout(seite)
        self.fertig_label = _text("", seite)
        layout.addWidget(self.fertig_label)
        layout.addStretch(1)
        return seite

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def zuruecksetzen(self) -> None:
        """Beim Betreten des Schritts: wieder bei der Frage beginnen -- ausser
        ein Geraet ist schon eingerichtet worden."""
        if self.ergebnis is None and not self._laeuft():
            self._unterseite(U_FRAGE)

    def _unterseite(self, index: int) -> None:
        self.unterseiten.setCurrentIndex(index)
        self.status_label.setText("")
        schritt = {U_ANSCHLIESSEN: 1, U_WLAN: 2, U_FERTIG: 3}.get(index)
        self.fortschritt_label.setText(f"Schritt {schritt} von 3" if schritt else "Ein Aufnahmegerät für Besprechungsräume.")
        self.zurueck_button.setVisible(index != U_FERTIG)
        self.ueberspringen_button.setVisible(index != U_FERTIG)
        texte = {
            U_FRAGE: "Ja, Gerät einrichten",
            U_ANSCHLIESSEN: "Weiter",
            U_WLAN: "Einrichten",
            U_FERTIG: "Weiter",
        }
        self.primaer_button.setText(texte[index])
        self.primaer_button.setEnabled(index != U_ANSCHLIESSEN or self._info is not None)
        if index == U_ANSCHLIESSEN:
            self._suchen()
        elif index == U_WLAN:
            self._wlan_vorbereiten()

    def _aktuell(self) -> int:
        return self.unterseiten.currentIndex()

    def _zurueck(self) -> None:
        if self._laeuft():
            return
        aktuell = self._aktuell()
        if aktuell == U_FRAGE:
            self.zurueck.emit()
        else:
            self._unterseite(aktuell - 1)

    def _primaer(self) -> None:
        aktuell = self._aktuell()
        if aktuell == U_FRAGE:
            self._unterseite(U_ANSCHLIESSEN)
        elif aktuell == U_ANSCHLIESSEN:
            self._unterseite(U_WLAN)
        elif aktuell == U_WLAN:
            self._einrichten()
        else:
            self.weiter.emit()

    # ------------------------------------------------------------------
    # Hintergrundarbeit
    # ------------------------------------------------------------------
    def _oeffnen(self, port: str) -> usb.SerielleVerbindung:
        return (self._oeffnen_fn or usb.verbindung_oeffnen)(port)

    def _laeuft(self) -> bool:
        return self._aufgabe is not None and self._aufgabe.isRunning()

    def _beschaeftigt(self, an: bool, text: str | None = None) -> None:
        for knopf in (self.suchen_button, self.erkennen_button, self.zurueck_button, self.ueberspringen_button):
            knopf.setEnabled(not an)
        aktuell = self._aktuell()
        if aktuell == U_ANSCHLIESSEN:
            self.primaer_button.setEnabled(not an and self._info is not None)
        elif aktuell == U_WLAN:
            self.primaer_button.setEnabled(not an)
        if text is not None:
            self.status_label.setText(text)

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
    # 2. Anschliessen
    # ------------------------------------------------------------------
    def _suchen(self) -> None:
        self.anschluss_combo.clear()
        self._info = None
        try:
            gefunden = (self._anschluesse_fn or usb.anschluesse_finden)()
        except usb.UsbFehler as fehler:
            self.status_label.setText(f"❌ {fehler}")
            gefunden = []
        for anschluss in gefunden:
            text = f"{anschluss.port} – {anschluss.beschreibung}" + (" (ESP32)" if anschluss.espressif else "")
            self.anschluss_combo.addItem(text, anschluss.port)
        self.erkennen_button.setEnabled(bool(gefunden))
        self.primaer_button.setEnabled(False)
        if not gefunden:
            self.geraet_label.setText(KEIN_ANSCHLUSS)
            return
        espressif = [a for a in gefunden if a.espressif]
        if len(espressif) == 1:
            # Genau ein ESP32 angeschlossen: Es ist das Vermerk Raum.
            self.anschluss_combo.setCurrentIndex(self.anschluss_combo.findData(espressif[0].port))
            self._erkennen()
        else:
            self.geraet_label.setText("Bitte den Anschluss des Vermerk Raums wählen und „Gerät erkennen“ drücken.")

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

        self.geraet_label.setText(f"Frage {port} ab …")
        self._beschaeftigt(True, "")
        self._im_hintergrund(abfragen, self._erkannt)

    def _erkannt(self, info: usb.GeraeteInfo) -> None:
        self._info = info
        zustand = f"bereits für WLAN „{info.wlan}“ eingerichtet" if info.eingerichtet else "noch nicht eingerichtet"
        self.geraet_label.setText(f"✅ Erkannt: {info.board}, Id {info.geraete_id}, Firmware {info.firmware} ({zustand}).")
        self._beschaeftigt(False, "")

    # ------------------------------------------------------------------
    # 3. WLAN
    # ------------------------------------------------------------------
    def _vorhandene(self) -> list[dict[str, Any]]:
        eintraege = app_config.load_config().get("geraete_empfang_geraete") or []
        return [dict(e) for e in eintraege if isinstance(e, dict)]

    def _basis_url(self) -> str:
        adressen = geraete_empfang_service.lokale_adressen()
        port = app_config.load_config().get("geraete_empfang_port") or geraete_empfang_service.STANDARD_PORT
        return f"http://{adressen[0]}:{port}" if adressen else ""

    def _wlan_vorbereiten(self) -> None:
        info = self._info
        if info is not None:
            if not self.name_edit.text().strip():
                self.name_edit.setText(namensvorschlag(info))
            if info.wlan and not self.wlan_edit.text():
                self.wlan_edit.setText(info.wlan)
        basis = self._basis_url()
        self._adresse_bekannt = bool(basis)
        if basis and not self.adresse_edit.text():
            self.adresse_edit.setText(basis)
        # Ist die Adresse ermittelt, braucht der Anwender das Feld nicht zu sehen.
        self.adresse_edit.setVisible(not self._adresse_bekannt)
        self.adresse_zeile_label.setVisible(not self._adresse_bekannt)
        if self._adresse_bekannt:
            self.adresse_hinweis.setText(f"Das Gerät schickt seine Aufnahmen an diesen Computer ({basis}).")
        else:
            self.adresse_hinweis.setText(
                "Die Adresse dieses Computers im Netz ließ sich nicht ermitteln. Bitte eintragen "
                "(„ipconfig“ in der Eingabeaufforderung zeigt sie an)."
            )

    def _einrichten(self) -> None:
        info = self._info
        port = self.anschluss_combo.currentData()
        if info is None or not port:
            return
        name = self.name_edit.text().strip()
        if not geraete_empfang_service.geraetename_gueltig(name):
            self.status_label.setText("❌ Name: Buchstaben, Ziffern, „_“ und „-“, höchstens 32 Zeichen, ohne Leerzeichen.")
            return
        if any(
            str(e.get("name", "")).lower() == name.lower() and e.get("geraete_id") != info.geraete_id
            for e in self._vorhandene()
        ):
            self.status_label.setText(f"❌ Ein anderes Gerät heißt schon „{name}“.")
            return
        token = geraete_empfang_service.token_erzeugen()
        einrichtung = usb.Einrichtung(
            wlan_ssid=self.wlan_edit.text(),
            wlan_passwort=self.passwort_edit.text(),
            pc_url=self.adresse_edit.text().strip(),
            pc_token=token,
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

        self._beschaeftigt(True, "Schreibe ins Gerät, danach startet es neu. Das dauert einige Sekunden …")
        self._im_hintergrund(schreiben, lambda neu_info: self._eingerichtet(neu_info, name, token))

    def _eingerichtet(self, info: usb.GeraeteInfo, name: str, token: str) -> None:
        self._beschaeftigt(False)
        if not (info.eingerichtet and info.token_pc):
            self.status_label.setText("❌ Das Gerät meldet nach dem Neustart keine Einrichtung. Bitte erneut versuchen.")
            return
        eintrag = {
            "name": name,
            "token_sha256": geraete_empfang_service.token_hash(token),
            "angelegt": dt.date.today().isoformat(),
            "geraete_id": info.geraete_id,
            "board": info.board,
            "firmware": info.firmware,
        }
        # Sofort speichern: Das Geraet traegt das neue Token schon. Der Empfang
        # wird eingeschaltet, sonst nimmt niemand die Aufnahmen an.
        geraete = [
            e for e in self._vorhandene() if not info.geraete_id or e.get("geraete_id") != info.geraete_id
        ]
        geraete.append(eintrag)
        app_config.update_config(geraete_empfang_geraete=geraete, geraete_empfang_aktiv=True)
        self.ergebnis = eintrag
        self.fertig_label.setText(
            f"<p>✅ <b>„{name}“ ist eingerichtet.</b></p>"
            f"<p>Das Gerät hat sich mit dem WLAN „{info.wlan}“ verbunden und meldet sich bei diesem Computer, "
            "sobald es Aufnahmen hat. Der Empfang ist eingeschaltet.</p>"
            "<p>Sie können das USB-Kabel abziehen und das Gerät im Raum aufstellen.</p>"
            "<p>Beim ersten Start fragt die Windows-Firewall, ob die Anwendung Verbindungen annehmen darf – "
            "bitte für <b>private Netzwerke</b> zulassen.</p>"
            "<p>Weitere Geräte lassen sich unter <b>Einstellungen → Aufnahmegeräte</b> hinzufügen.</p>"
        )
        self._unterseite(U_FERTIG)
        self.eingerichtet.emit()
