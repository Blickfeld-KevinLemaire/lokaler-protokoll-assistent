"""Seite "Frag mein Meeting": Chat mit den eigenen Transkripten und Zusammenfassungen.

Links oben die Unterlagen zum Anhaken, darunter die gespeicherten Verlaeufe;
rechts der Chat. Ganz oben steht - nur wenn noetig - ein Hinweis, was fuer den
Chat noch fehlt (z. B. das Einbettungsmodell) mit einer Schaltflaeche zum
Herunterladen. Nichts wird ungefragt heruntergeladen. Der Hinweis verschwindet,
sobald alles da ist. Der Systemcheck zeigt, ob der Chat mit den aktuellen
Einstellungen funktioniert.

Die Antworten kommen aus ``services.chat_service``; welches Modell dahinter
steht - lokal ueber Ollama oder per API - bestimmt der Reiter "Chatbot" in den
Einstellungen. Jede beantwortete Frage speichert den Verlauf
(``services.chat_verlauf_service``).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent.gui.dialogs import ChatSystemcheckDialog
from protokoll_assistent.gui.worker import ChatCheckWorker, ChatWorker, OllamaPullWorker
from protokoll_assistent.services import chat_service, chat_verlauf_service, ollama_service
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


def _groesse_text(modell: str) -> str:
    option = ollama_service.get_modell_option(modell)
    return f" (ca. {option.groesse_gb:g} GB)" if option else ""


class ChatPage(QWidget):
    def __init__(
        self,
        ausgabe_ordner_fn: Callable[[], Path],
        cache_ordner_fn: Callable[[], Path],
        schluessel_fn: Callable[[], str],
        verlaeufe_ordner_fn: Callable[[], Path],
        parent=None,
    ):
        super().__init__(parent)
        self._ausgabe_ordner_fn = ausgabe_ordner_fn
        self._cache_ordner_fn = cache_ordner_fn
        self._schluessel_fn = schluessel_fn
        self._verlaeufe_ordner_fn = verlaeufe_ordner_fn
        self._worker: ChatWorker | None = None
        self._pull_worker: OllamaPullWorker | None = None
        self._check_worker: ChatCheckWorker | None = None
        self._fehlendes_modell: str | None = None
        # [{"role": "user"|"assistant"|"fehler", "content": ..., "quellen": [...]}]
        self._nachrichten: list[dict[str, Any]] = []
        self._verlauf: chat_verlauf_service.Verlauf | None = None
        self._laufende_antwort = ""
        self._geladen = False

        haupt = QVBoxLayout(self)
        haupt.setContentsMargins(0, 0, 0, 0)
        haupt.setSpacing(10)
        haupt.addWidget(self._baue_hinweis())
        inhalt = QHBoxLayout()
        inhalt.setSpacing(16)
        inhalt.addWidget(self._baue_linke_spalte(), stretch=1)
        inhalt.addWidget(self._baue_chat(), stretch=3)
        haupt.addLayout(inhalt, stretch=1)

        self.einstellungen_aktualisiert()
        self._darstellen()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def _baue_hinweis(self) -> QWidget:
        """Hinweisleiste ganz oben: was fuer den Chat noch fehlt."""
        self.hinweis_rahmen = QFrame(self)
        self.hinweis_rahmen.setObjectName("SetupBanner")
        layout = QVBoxLayout(self.hinweis_rahmen)
        zeile = QHBoxLayout()
        self.hinweis_label = QLabel("", self.hinweis_rahmen)
        self.hinweis_label.setWordWrap(True)
        zeile.addWidget(self.hinweis_label, stretch=1)
        self.hinweis_download_button = QPushButton("Jetzt herunterladen", self.hinweis_rahmen)
        self.hinweis_download_button.setObjectName("PrimaryButton")
        self.hinweis_download_button.clicked.connect(self._modell_herunterladen)
        zeile.addWidget(self.hinweis_download_button)
        layout.addLayout(zeile)
        self.hinweis_fortschritt = QProgressBar(self.hinweis_rahmen)
        self.hinweis_fortschritt.setRange(0, 100)
        self.hinweis_fortschritt.setVisible(False)
        layout.addWidget(self.hinweis_fortschritt)
        self.hinweis_rahmen.setVisible(False)
        return self.hinweis_rahmen

    def _baue_linke_spalte(self) -> QWidget:
        spalte = QWidget(self)
        layout = QVBoxLayout(spalte)
        layout.setContentsMargins(0, 0, 0, 0)

        titel = QLabel("Unterlagen", self)
        titel.setObjectName("FieldCaption")
        layout.addWidget(titel)
        self.unterlagen_liste = QListWidget(self)
        self.unterlagen_liste.setToolTip("Haken setzen, welche Transkripte und Zusammenfassungen der Chat nutzen soll.")
        layout.addWidget(self.unterlagen_liste, stretch=3)
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

        verlauf_titel = QLabel("Gespeicherte Chats", self)
        verlauf_titel.setObjectName("FieldCaption")
        layout.addWidget(verlauf_titel)
        self.verlaeufe_liste = QListWidget(self)
        self.verlaeufe_liste.setToolTip("Anklicken, um einen früheren Chat zu öffnen und fortzusetzen.")
        self.verlaeufe_liste.itemClicked.connect(self._verlauf_angeklickt)
        layout.addWidget(self.verlaeufe_liste, stretch=2)
        verlauf_zeile = QHBoxLayout()
        self.verlauf_umbenennen_button = QPushButton("Umbenennen …", self)
        self.verlauf_umbenennen_button.clicked.connect(self._verlauf_umbenennen)
        self.verlauf_loeschen_button = QPushButton("Löschen …", self)
        self.verlauf_loeschen_button.clicked.connect(self._verlauf_loeschen)
        verlauf_zeile.addWidget(self.verlauf_umbenennen_button)
        verlauf_zeile.addWidget(self.verlauf_loeschen_button)
        layout.addLayout(verlauf_zeile)
        return spalte

    def _baue_chat(self) -> QWidget:
        spalte = QWidget(self)
        layout = QVBoxLayout(spalte)
        layout.setContentsMargins(0, 0, 0, 0)

        kopf = QHBoxLayout()
        self.modell_label = QLabel("", self)
        self.modell_label.setObjectName("PageSubtitle")
        kopf.addWidget(self.modell_label, stretch=1)
        self.systemcheck_button = QPushButton("Systemcheck", self)
        self.systemcheck_button.setToolTip("Prüft, ob der Chatbot mit den aktuellen Einstellungen funktioniert.")
        self.systemcheck_button.clicked.connect(self.systemcheck_starten)
        kopf.addWidget(self.systemcheck_button)
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
    # Seite oeffnen / Unterlagen
    # ------------------------------------------------------------------
    def aktualisieren(self) -> None:
        """Liest Unterlagen und gespeicherte Chats neu ein und prueft, ob fuer
        den Chat noch etwas fehlt. Haken bleiben erhalten; beim ersten Mal ist
        die neueste Unterlage vorausgewaehlt, spaeter neue ungesetzt."""
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
            ""
            if pfade
            else "Noch keine Unterlagen im Ausgabeordner. Erst eine Transkription (und ggf. Nachbearbeitung) erstellen."
        )
        self._verlaeufe_laden()
        self.hinweis_pruefen()

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
    # Einstellungen und Hinweisleiste
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
        """Zeigt an, welches Modell gilt, und prueft den Hinweis neu."""
        konfig = app_config.load_config()
        api = konfig["chatbot_modus"] == "api"
        if api:
            text = f"API: {konfig['chatbot_api_modell']} · Einbettung: {konfig['chatbot_api_embedding_modell']}"
        else:
            text = f"Lokal: {konfig['chatbot_ollama_modell']} · Einbettung: {konfig['chatbot_embedding_modell']}"
        self.modell_label.setText(text + "  (änderbar unter Einstellungen → Chatbot)")
        self.datenschutz_label.setVisible(api)
        self.hinweis_pruefen()

    def hinweis_pruefen(self) -> None:
        """Hinweisleiste: fehlt etwas, steht das als Erstes ganz oben. Ein fehlendes
        Ollama-Modell laesst sich dort herunterladen - aber erst auf Wunsch."""
        if self._pull_worker is not None:
            return
        einstellungen = self.einstellungen()
        self._fehlendes_modell = None
        text = ""
        if einstellungen.modus == "api":
            if not einstellungen.api_schluessel:
                text = "Für den Chat im API-Modus ist noch kein API-Schlüssel hinterlegt (Einstellungen → Chatbot)."
        else:
            try:
                ollama_service.list_models(timeout=1.5)
            except ollama_service.OllamaError:
                text = "Ollama ist nicht erreichbar. Bitte Ollama starten oder installieren; der Systemcheck zeigt Details."
            else:
                self._fehlendes_modell = chat_service.fehlendes_modell(einstellungen)
                if self._fehlendes_modell:
                    art = "Einbettungsmodell" if self._fehlendes_modell == einstellungen.embedding_modell else "Chatmodell"
                    text = (
                        f"Für den Chat fehlt noch das {art} „{self._fehlendes_modell}“"
                        f"{_groesse_text(self._fehlendes_modell)}. Es wird erst heruntergeladen, wenn Sie es möchten."
                    )
        self.hinweis_label.setText(text)
        self.hinweis_download_button.setVisible(self._fehlendes_modell is not None)
        self.hinweis_download_button.setEnabled(True)
        self.hinweis_fortschritt.setVisible(False)
        self.hinweis_rahmen.setVisible(bool(text))

    def _modell_herunterladen(self) -> None:
        modell = self._fehlendes_modell
        if not modell or self._pull_worker is not None:
            return
        self.hinweis_download_button.setEnabled(False)
        self.hinweis_fortschritt.setValue(0)
        self.hinweis_fortschritt.setVisible(True)
        self.hinweis_label.setText(f"Lade „{modell}“ herunter …")
        self._pull_worker = OllamaPullWorker(modell, self)
        self._pull_worker.fortschritt.connect(self._pull_fortschritt)
        self._pull_worker.fertig.connect(self._pull_fertig)
        self._pull_worker.fehlgeschlagen.connect(self._pull_fehlgeschlagen)
        self._pull_worker.start()

    def _pull_fortschritt(self, status: str, fertig: int, gesamt: int) -> None:
        if gesamt > 0:
            self.hinweis_fortschritt.setValue(round(fertig / gesamt * 100))
            self.hinweis_label.setText(f"{status}: {fertig / 1e9:.1f} von {gesamt / 1e9:.1f} GB")
        else:
            self.hinweis_label.setText(status)

    def _pull_fertig(self, modell: str) -> None:
        self._pull_worker = None
        self.hinweis_pruefen()  # verschwindet, sobald alles da ist; zeigt sonst das naechste fehlende Modell

    def _pull_fehlgeschlagen(self, modell: str, meldung: str) -> None:
        self._pull_worker = None
        self.hinweis_pruefen()
        self.hinweis_label.setText(f"Download fehlgeschlagen: {meldung}")
        self.hinweis_rahmen.setVisible(True)

    # ------------------------------------------------------------------
    # Systemcheck
    # ------------------------------------------------------------------
    def systemcheck_starten(self) -> None:
        if self._check_worker is not None:
            return
        self.systemcheck_button.setEnabled(False)
        self.status_label.setText("Systemcheck läuft …")
        self._check_worker = ChatCheckWorker(self.einstellungen(), self)
        self._check_worker.fertig.connect(self._systemcheck_fertig)
        self._check_worker.start()

    def _systemcheck_fertig(self, ergebnisse: list) -> None:
        self._check_worker = None
        self.systemcheck_button.setEnabled(True)
        self.status_label.setText("")
        self.hinweis_pruefen()
        ChatSystemcheckDialog(ergebnisse, self).exec()

    # ------------------------------------------------------------------
    # Gespeicherte Chats
    # ------------------------------------------------------------------
    def _verlaeufe_laden(self) -> None:
        aktuelle_id = self._verlauf.id if self._verlauf else None
        self.verlaeufe_liste.clear()
        for verlauf in chat_verlauf_service.lade_alle(self._verlaeufe_ordner_fn()):
            try:
                zeit = datetime.fromisoformat(verlauf.aktualisiert).strftime("%d.%m.%Y %H:%M")
            except ValueError:
                zeit = ""
            eintrag = QListWidgetItem(f"{verlauf.titel}\n{zeit}" if zeit else verlauf.titel)
            eintrag.setData(Qt.UserRole, verlauf.id)
            eintrag.setToolTip(f"{len(verlauf.nachrichten) // 2} Fragen")
            self.verlaeufe_liste.addItem(eintrag)
            if verlauf.id == aktuelle_id:
                self.verlaeufe_liste.setCurrentItem(eintrag)

    def _gewaehlte_verlauf_id(self) -> str | None:
        eintrag = self.verlaeufe_liste.currentItem()
        return None if eintrag is None else str(eintrag.data(Qt.UserRole))

    def _verlauf_angeklickt(self, eintrag: QListWidgetItem) -> None:
        if self._worker is not None:
            return
        verlauf = chat_verlauf_service.lade(self._verlaeufe_ordner_fn(), str(eintrag.data(Qt.UserRole)))
        if verlauf is None:
            self.status_label.setText("Dieser Chat konnte nicht gelesen werden.")
            self._verlaeufe_laden()
            return
        self._verlauf = verlauf
        self._nachrichten = [
            {"role": n["role"], "content": str(n.get("content", "")), "quellen": list(n.get("quellen", []))}
            for n in verlauf.nachrichten
        ]
        vorhandene = {pfad for pfad in verlauf.dokumente if Path(pfad).is_file()}
        for zeile in range(self.unterlagen_liste.count()):
            punkt = self.unterlagen_liste.item(zeile)
            punkt.setCheckState(Qt.Checked if str(punkt.data(Qt.UserRole)) in vorhandene else Qt.Unchecked)
        fehlend = len(verlauf.dokumente) - len(vorhandene)
        self.status_label.setText(
            f"{fehlend} der damals benutzten Unterlagen gibt es nicht mehr." if fehlend > 0 else ""
        )
        self._darstellen()

    def _verlauf_umbenennen(self) -> None:
        kennung = self._gewaehlte_verlauf_id()
        if kennung is None:
            return
        verlauf = chat_verlauf_service.lade(self._verlaeufe_ordner_fn(), kennung)
        if verlauf is None:
            return
        from PySide6.QtWidgets import QInputDialog

        titel, ok = QInputDialog.getText(self, "Chat umbenennen", "Neuer Titel:", text=verlauf.titel)
        if ok and chat_verlauf_service.umbenennen(self._verlaeufe_ordner_fn(), kennung, titel):
            if self._verlauf is not None and self._verlauf.id == kennung:
                self._verlauf.titel = " ".join(titel.split())
            self._verlaeufe_laden()

    def _verlauf_loeschen(self) -> None:
        kennung = self._gewaehlte_verlauf_id()
        if kennung is None or self._worker is not None:
            return
        antwort = QMessageBox.question(self, "Chat löschen", "Diesen gespeicherten Chat endgültig löschen?")
        if antwort != QMessageBox.Yes:
            return
        chat_verlauf_service.loesche(self._verlaeufe_ordner_fn(), kennung)
        if self._verlauf is not None and self._verlauf.id == kennung:
            self.neuer_chat()
        self._verlaeufe_laden()

    def _verlauf_speichern(self, pfade: list[Path]) -> None:
        gespeichert = self._beantwortete_nachrichten()
        if not gespeichert:
            return
        ordner = self._verlaeufe_ordner_fn()
        if self._verlauf is None:
            self._verlauf = chat_verlauf_service.neuer_verlauf(ordner, gespeichert[0]["content"])
        self._verlauf.nachrichten = gespeichert
        self._verlauf.dokumente = [str(pfad) for pfad in pfade]
        try:
            chat_verlauf_service.speichern(ordner, self._verlauf)
        except OSError as fehler:
            self.status_label.setText(f"Der Chat konnte nicht gespeichert werden: {fehler}")
            return
        self._verlaeufe_laden()

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def neuer_chat(self) -> None:
        if self._worker is not None:
            return
        self._nachrichten.clear()
        self._verlauf = None
        self.verlaeufe_liste.clearSelection()
        self.verlaeufe_liste.setCurrentRow(-1)
        self.status_label.setText("")
        self._darstellen()

    def senden(self) -> None:
        if self._worker is not None:
            return
        frage = self.eingabe.text().strip()
        if not frage:
            return
        if self._fehlendes_modell:
            self.status_label.setText("Bitte oben zuerst das fehlende Modell herunterladen.")
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
        self._worker.fertig.connect(lambda antwort, quellen, p=pfade: self._antwort_fertig(antwort, quellen, p))
        self._worker.fehlgeschlagen.connect(self._fehlgeschlagen)
        self._worker.start()

    def _beantwortete_nachrichten(self) -> list[dict[str, Any]]:
        """Nur Fragen mit Antwort (samt Quellen): Fehlermeldungen und unbeantwortete
        Fragen gehoeren weder ins Gespraech ans Modell noch in den gespeicherten Chat."""
        paare: list[dict[str, Any]] = []
        for aktuell, folgend in zip(self._nachrichten, self._nachrichten[1:], strict=False):
            if aktuell["role"] == "user" and folgend["role"] == "assistant":
                paare.append({"role": "user", "content": aktuell["content"], "quellen": []})
                paare.append({"role": "assistant", "content": folgend["content"], "quellen": list(folgend["quellen"])})
        return paare

    def _verlauf_fuer_das_modell(self) -> list[dict[str, str]]:
        return [{"role": n["role"], "content": n["content"]} for n in self._beantwortete_nachrichten()]

    def _beschaeftigt(self, an: bool) -> None:
        self.senden_button.setEnabled(not an)
        self.eingabe.setEnabled(not an)
        self.neuer_chat_button.setEnabled(not an)
        self.fortschritt.setVisible(an)

    def _token_erhalten(self, stueck: str) -> None:
        self._laufende_antwort += stueck
        self._darstellen()

    def _antwort_fertig(self, antwort: str, quellen: list, pfade: list[Path] | None = None) -> None:
        self._worker = None
        self._laufende_antwort = ""
        self._nachrichten.append({"role": "assistant", "content": antwort, "quellen": list(quellen)})
        self.status_label.setText("")
        self._beschaeftigt(False)
        self._darstellen()
        self._verlauf_speichern(pfade if pfade is not None else self.ausgewaehlte_pfade())
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
