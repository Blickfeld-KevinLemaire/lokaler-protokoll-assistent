"""Auswahl des API-Anbieters in den Einstellungen.

Ein Auswahlfeld mit den Anbietern aus ``services/api_anbieter.py``. Darunter
steht, wo der Anbieter sitzt, was zu beachten ist und wo man den Schluessel
erzeugt bzw. die Dokumentation findet. Wird ein Anbieter gewaehlt, meldet
das Widget ihn ueber ``anbieter_gewaehlt``; der Einstellungsdialog traegt
daraufhin Adresse und Modell in seine Felder ein. Der Anwender muss dann nur
noch den Schluessel einsetzen.

Es ist nichts vorgewaehlt ("Bitte Anbieter waehlen ..."), solange der Anwender
sich nicht entschieden hat.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

from protokoll_assistent.services import api_anbieter
from protokoll_assistent.services.api_anbieter import ApiAnbieter

FAEHIGKEIT_TRANSKRIPTION = "transkription"
FAEHIGKEIT_CHAT = "chat"
# Chatbot: Chat UND Einbettungen (die Suche braucht beides vom selben Anbieter).
FAEHIGKEIT_CHATBOT = "chatbot"

KEINER = ""


def anbieter_passt(anbieter: ApiAnbieter, faehigkeit: str) -> bool:
    if faehigkeit == FAEHIGKEIT_TRANSKRIPTION:
        return anbieter.kann_transkription
    if faehigkeit == FAEHIGKEIT_CHATBOT:
        return anbieter.kann_chat and anbieter.kann_embeddings
    return anbieter.kann_chat


def voreinstellung_ermitteln(gespeichert: str | None, endpunkt: str | None) -> str:
    """Welcher Eintrag soll beim Oeffnen gewaehlt sein?

    Zuerst die gespeicherte Wahl. Fehlt sie (Einstellung aus einer aelteren
    Version), wird der Anbieter an der gespeicherten Adresse erkannt; eine
    unbekannte Adresse zaehlt als "eigener Endpunkt", keine Adresse als
    "nichts gewaehlt"."""
    if gespeichert:
        return gespeichert
    if not endpunkt:
        return KEINER
    anbieter = api_anbieter.erkenne_anbieter(endpunkt)
    return anbieter.id if anbieter else api_anbieter.ANBIETER_EIGENER


def beschreibung_html(anbieter: ApiAnbieter) -> str:
    """Erklaertext zu einem Anbieter (Standort, Hinweis, Links)."""
    zeilen = [f"<b>{escape(anbieter.name)}</b> – {escape(anbieter.standort)}"]
    if anbieter.hinweis:
        zeilen.append(escape(anbieter.hinweis))
    faehigkeiten = [
        name
        for name, vorhanden in (
            ("Chat", anbieter.kann_chat),
            ("Einbettungen", anbieter.kann_embeddings),
            ("Transkription", anbieter.kann_transkription),
        )
        if vorhanden
    ]
    zeilen.append("Bietet: " + ", ".join(faehigkeiten))
    zeilen.append(
        f'<a href="{escape(anbieter.schluessel_link)}">API-Schlüssel anlegen</a> · '
        f'<a href="{escape(anbieter.doku_link)}">Dokumentation</a>'
    )
    zeilen.append("Die Modellnamen sind Vorschläge und ändern sich oft – bei Bedarf in den Feldern anpassen.")
    return "<br>".join(zeilen)


class ApiAnbieterWahl(QWidget):
    # ApiAnbieter fuer einen bekannten Anbieter, None fuer "Eigener Endpunkt"
    # bzw. "Bitte waehlen" (dann bleiben die Felder unveraendert).
    anbieter_gewaehlt = Signal(object)

    def __init__(self, faehigkeit: str, ausgewaehlt: str = KEINER, parent=None):
        super().__init__(parent)
        self._faehigkeit = faehigkeit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox(self)
        self.combo.addItem("Bitte Anbieter wählen …", KEINER)
        for anbieter in api_anbieter.ANBIETER:
            if anbieter_passt(anbieter, faehigkeit):
                self.combo.addItem(anbieter.name, anbieter.id)
        self.combo.addItem("Eigener Endpunkt …", api_anbieter.ANBIETER_EIGENER)
        layout.addWidget(self.combo)

        self.info_label = QLabel("", self)
        self.info_label.setWordWrap(True)
        self.info_label.setOpenExternalLinks(True)
        layout.addWidget(self.info_label)

        self.setze(ausgewaehlt)
        self.combo.currentIndexChanged.connect(self._auswahl_geaendert)

    def anbieter_id(self) -> str:
        return str(self.combo.currentData() or KEINER)

    def anbieter(self) -> ApiAnbieter | None:
        return api_anbieter.finde_anbieter(self.anbieter_id())

    def setze(self, anbieter_id: str) -> None:
        """Waehlt einen Eintrag, ohne ``anbieter_gewaehlt`` auszuloesen (so wird
        beim Oeffnen der Einstellungen nichts ueberschrieben)."""
        index = self.combo.findData(anbieter_id)
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.blockSignals(False)
        self._info_aktualisieren()

    def _auswahl_geaendert(self, *_args) -> None:
        self._info_aktualisieren()
        self.anbieter_gewaehlt.emit(self.anbieter())

    def _info_aktualisieren(self) -> None:
        anbieter = self.anbieter()
        if anbieter is not None:
            self.info_label.setText(beschreibung_html(anbieter))
        elif self.anbieter_id() == api_anbieter.ANBIETER_EIGENER:
            self.info_label.setText(
                "Eigener Endpunkt: Adresse und Modellname unten selbst eintragen. "
                "Erwartet wird eine Schnittstelle im Format der OpenAI-API."
            )
        else:
            self.info_label.setText(
                "Es ist noch kein Anbieter ausgewählt – ohne Auswahl wird nichts an eine API übertragen."
            )
