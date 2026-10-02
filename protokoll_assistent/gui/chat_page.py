"""Seite "Frag mein Meeting": Chat mit den eigenen Transkripten und Zusammenfassungen.

Links die Unterlagen zum Anhaken (Transkripte und Zusammenfassungen aus dem
Ausgabeordner), rechts der Chat. Die Antworten kommen aus ``services.chat_service``
(Suche in den Unterlagen, dann Antwort des Chatmodells); welches Modell dahinter
steht - lokal ueber Ollama oder per API - bestimmt der Reiter "Chatbot" in den
Einstellungen.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.gui.worker import ChatWorker
from protokoll_assistent.services import chat_service
from protokoll_assistent.utils import app_config

HILFETEXT = (
    "Wählen Sie links Unterlagen aus und stellen Sie eine Frage, zum Beispiel: "
    "„Welche Beschlüsse wurden gefasst?“, „Wer macht bis wann was?“ oder "
    "„Was wurde zum Budget gesagt?“. Die Antwort stützt sich nur auf die ausgewählten Unterlagen."
)
DATENSCHUTZ_API = (
    "API-Modus: Ihre Fragen, passende Textstellen und die Texte der ausgewählten Unterlagen werden an den "
    "eingetragenen, externen Anbieter übertragen."
)


class ChatPage(QWidget):
    def __init__(
        self,
        ausgabe_ordner_fn: Callable[[], Path],
        cache_ordner_fn: Callable[[], Path],
        schluessel_fn: Callable[[], str],
        parent=None,
    ):
        super().__init__(parent)
        self._ausgabe_ordner_fn = ausgabe_ordner_fn
        self._cache_ordner_fn = cache_ordner_fn
        self._schluessel_fn = schluessel_fn
        self._worker: ChatWorker | None = None
        # [{"role": "user"|"assistant", "content": ..., "quellen": [...]}]
        self._nachrichten: list[dict[str, Any]] = []
        self._laufende_antwort = ""
        self._geladen = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._baue_unterlagen(), stretch=1)
        layout.addWidget(self._baue_chat(), stretch=3)
        self.einstellungen_aktualisiert()
        self._darstellen()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def _baue_unterlagen(self) -> QWidget:
        spalte = QWidget(self)
        layout = QVBoxLayout(spalte)
        layout.setContentsMargins(0, 0, 0, 0)
        titel = QLabel("Unterlagen", self)
        titel.setObjectName("FieldCaption")
        layout.addWidget(titel)

        self.unterlagen_liste = QListWidget(self)
        self.unterlagen_liste.setToolTip("Haken setzen, welche Transkripte und Zusammenfassungen der Chat nutzen soll.")
        layout.addWidget(self.unterlagen_liste, stretch=1)

        zeile = QHBoxLayout()
        self.alle_button = QPushButton("Alle", self)
        self.alle_button.clicked.connect(lambda: self._alle_setzen(True))
        self.keine_button = QPushButton("Keine", self)
        self.keine_button.clicked.connect(lambda: self._alle_setzen(False))
        self.neu_laden_button = QPushButton("Neu laden", self)
        self.neu_laden_button.clicked.connect(self.aktualisieren)
        for knopf in (self.alle_button, self.keine_button, self.neu_laden_button):
            zeile.addWidget(knopf)
        layout.addLayout(zeile)

        self.unterlagen_hinweis = QLabel("", self)
        self.unterlagen_hinweis.setObjectName("PageSubtitle")
        self.unterlagen_hinweis.setWordWrap(True)
        layout.addWidget(self.unterlagen_hinweis)
        return spalte

    def _baue_chat(self) -> QWidget:
        spalte = QWidget(self)
        layout = QVBoxLayout(spalte)
        layout.setContentsMargins(0, 0, 0, 0)

        kopf = QHBoxLayout()
        self.modell_label = QLabel("", self)
        self.modell_label.setObjectName("PageSubtitle")
        kopf.addWidget(self.modell_label, stretch=1)
        self.neuer_chat_button = QPushButton("Neuer Chat", self)
        self.neuer_chat_button.clicked.connect(self.neuer_chat)
        kopf.addWidget(self.neuer_chat_button)
        layout.addLayout(kopf)

        self.datenschutz_label = QLabel(DATENSCHUTZ_API, self)
        self.datenschutz_label.setObjectName("DatenschutzHinweis")
        self.datenschutz_label.setWordWrap(True)
        layout.addWidget(self.datenschutz_label)

        self.verlauf_anzeige = QTextBrowser(self)
        self.verlauf_anzeige.setOpenLinks(False)
        layout.addWidget(self.verlauf_anzeige, stretch=1)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("PageSubtitle")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.fortschritt = QProgressBar(self)
        self.fortschritt.setRange(0, 0)  # laufende Anzeige ohne Prozentwert
        self.fortschritt.setTextVisible(False)
        self.fortschritt.setFixedHeight(8)
        self.fortschritt.setVisible(False)
        layout.addWidget(self.fortschritt)

        eingabe_zeile = QHBoxLayout()
        self.eingabe = QLineEdit(self)
        self.eingabe.setPlaceholderText("Frag mein Meeting …")
        self.eingabe.returnPressed.connect(self.senden)
        eingabe_zeile.addWidget(self.eingabe, stretch=1)
        self.senden_button = QPushButton("Senden", self)
        self.senden_button.setObjectName("PrimaryButton")
        self.senden_button.clicked.connect(self.senden)
        eingabe_zeile.addWidget(self.senden_button)
        layout.addLayout(eingabe_zeile)
        return spalte

    # ------------------------------------------------------------------
    # Unterlagen
    # ------------------------------------------------------------------
    def aktualisieren(self) -> None:
        """Liest den Ausgabeordner neu ein. Haken bleiben erhalten; beim ersten
        Mal ist die neueste Unterlage vorausgewaehlt, spaeter neue ungesetzt."""
        gesetzt = set(self.ausgewaehlte_pfade())
        erstes_mal = not self._geladen
        pfade = chat_service.finde_dokumente(self._ausgabe_ordner_fn())
        self.unterlagen_liste.clear()
        for nummer, pfad in enumerate(pfade):
            eintrag = QListWidgetItem(chat_service.anzeigename(pfad))
            eintrag.setData(Qt.UserRole, str(pfad))
            eintrag.setToolTip(str(pfad))
            eintrag.setFlags(eintrag.flags() | Qt.ItemIsUserCheckable)
            vorgewaehlt = pfad in gesetzt or (erstes_mal and nummer == 0)
            eintrag.setCheckState(Qt.Checked if vorgewaehlt else Qt.Unchecked)
            self.unterlagen_liste.addItem(eintrag)
        self._geladen = True
        self.unterlagen_hinweis.setText(
            "" if pfade else "Noch keine Unterlagen im Ausgabeordner. Erst eine Transkription (und ggf. Nachbearbeitung) erstellen."
        )

    def ausgewaehlte_pfade(self) -> list[Path]:
        pfade = []
        for zeile in range(self.unterlagen_liste.count()):
            eintrag = self.unterlagen_liste.item(zeile)
            if eintrag.checkState() == Qt.Checked:
                pfade.append(Path(str(eintrag.data(Qt.UserRole))))
        return pfade

    def _alle_setzen(self, an: bool) -> None:
        for zeile in range(self.unterlagen_liste.count()):
            self.unterlagen_liste.item(zeile).setCheckState(Qt.Checked if an else Qt.Unchecked)

    # ------------------------------------------------------------------
    # Einstellungen
    # ------------------------------------------------------------------
    def einstellungen(self) -> chat_service.ChatEinstellungen:
        konfig = app_config.load_config()
        if konfig["chatbot_modus"] == "api":
            return chat_service.ChatEinstellungen(
                "api",
                konfig["chatbot_api_modell"],
                konfig["chatbot_api_embedding_modell"],
                konfig["chatbot_api_endpunkt"],
                konfig["chatbot_api_embedding_endpunkt"],
                self._schluessel_fn() or "",
            )
        return chat_service.ChatEinstellungen("lokal", konfig["chatbot_ollama_modell"], konfig["chatbot_embedding_modell"])

    def einstellungen_aktualisiert(self) -> None:
        """Zeigt an, welches Modell gilt, und blendet im API-Modus den Datenschutzhinweis ein."""
        konfig = app_config.load_config()
        api = konfig["chatbot_modus"] == "api"
        if api:
            text = f"API: {konfig['chatbot_api_modell']} · Einbettung: {konfig['chatbot_api_embedding_modell']}"
        else:
            text = f"Lokal: {konfig['chatbot_ollama_modell']} · Einbettung: {konfig['chatbot_embedding_modell']}"
        self.modell_label.setText(text + "  (änderbar unter Einstellungen → Chatbot)")
        self.datenschutz_label.setVisible(api)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def neuer_chat(self) -> None:
        if self._worker is not None:
            return
        self._nachrichten.clear()
        self.status_label.setText("")
        self._darstellen()

    def senden(self) -> None:
        if self._worker is not None:
            return
        frage = self.eingabe.text().strip()
        if not frage:
            return
        pfade = self.ausgewaehlte_pfade()
        if not pfade:
            self.status_label.setText("Bitte links mindestens eine Unterlage anhaken.")
            return
        verlauf = self._verlauf_fuer_das_modell()
        self._nachrichten.append({"role": "user", "content": frage, "quellen": []})
        self.eingabe.clear()
        self._laufende_antwort = ""
        self._beschaeftigt(True)
        self._darstellen()

        self._worker = ChatWorker(frage, pfade, verlauf, self.einstellungen(), self._cache_ordner_fn(), self)
        self._worker.status.connect(self.status_label.setText)
        self._worker.token.connect(self._token_erhalten)
        self._worker.fertig.connect(self._antwort_fertig)
        self._worker.fehlgeschlagen.connect(self._fehlgeschlagen)
        self._worker.start()

    def _verlauf_fuer_das_modell(self) -> list[dict[str, str]]:
        """Nur Fragen mit Antwort: Fehlermeldungen und unbeantwortete Fragen
        gehoeren nicht in das Gespraech, das ans Modell geht."""
        verlauf: list[dict[str, str]] = []
        for aktuell, folgend in zip(self._nachrichten, self._nachrichten[1:], strict=False):
            if aktuell["role"] == "user" and folgend["role"] == "assistant":
                verlauf.append({"role": "user", "content": aktuell["content"]})
                verlauf.append({"role": "assistant", "content": folgend["content"]})
        return verlauf

    def _beschaeftigt(self, an: bool) -> None:
        self.senden_button.setEnabled(not an)
        self.eingabe.setEnabled(not an)
        self.neuer_chat_button.setEnabled(not an)
        self.fortschritt.setVisible(an)

    def _token_erhalten(self, stueck: str) -> None:
        self._laufende_antwort += stueck
        self._darstellen()

    def _antwort_fertig(self, antwort: str, quellen: list) -> None:
        self._worker = None
        self._laufende_antwort = ""
        self._nachrichten.append({"role": "assistant", "content": antwort, "quellen": list(quellen)})
        self.status_label.setText("")
        self._beschaeftigt(False)
        self._darstellen()
        self.eingabe.setFocus()

    def _fehlgeschlagen(self, meldung: str) -> None:
        self._worker = None
        self._laufende_antwort = ""
        # Die unbeantwortete Frage bleibt stehen, damit man sie erneut stellen kann.
        self._nachrichten.append({"role": "fehler", "content": meldung, "quellen": []})
        self.status_label.setText("")
        self._beschaeftigt(False)
        self._darstellen()

    # ------------------------------------------------------------------
    # Darstellung
    # ------------------------------------------------------------------
    @staticmethod
    def _html(text: str) -> str:
        return html.escape(text).replace("\n", "<br>")

    def _darstellen(self) -> None:
        if not self._nachrichten and not self._laufende_antwort:
            self.verlauf_anzeige.setHtml(f"<p style='color:#5b6270'>{self._html(HILFETEXT)}</p>")
            return
        teile = []
        for nachricht in self._nachrichten:
            rolle = nachricht["role"]
            if rolle == "user":
                teile.append(
                    "<p style='background:#e8f0fe;padding:8px'><b>Sie</b><br>" + self._html(nachricht["content"]) + "</p>"
                )
            elif rolle == "assistant":
                quellen = ""
                if nachricht["quellen"]:
                    quellen = (
                        "<br><span style='color:#5b6270;font-size:small'>Quellen: "
                        + self._html("; ".join(nachricht["quellen"]))
                        + "</span>"
                    )
                teile.append(
                    "<p style='background:#f3f4f6;padding:8px'><b>Frag mein Meeting</b><br>"
                    + self._html(nachricht["content"])
                    + quellen
                    + "</p>"
                )
            else:
                teile.append("<p style='color:#c0392b'><b>Fehler:</b> " + self._html(nachricht["content"]) + "</p>")
        if self._laufende_antwort:
            teile.append(
                "<p style='background:#f3f4f6;padding:8px'><b>Frag mein Meeting</b><br>"
                + self._html(self._laufende_antwort)
                + "</p>"
            )
        self.verlauf_anzeige.setHtml("".join(teile))
        leiste = self.verlauf_anzeige.verticalScrollBar()
        leiste.setValue(leiste.maximum())
