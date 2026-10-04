"""Ersteinrichtung: erklaert das Programm, zeigt, was auf DIESEM Computer
moeglich ist und was es kostet -- und laedt erst nach Zustimmung.

Sieben Schritte, alle in einem Dialog ueber dem Hauptfenster:

1. Willkommen        -- was das Programm macht.
2. Ihr Computer      -- Hardware, je Arbeitsschritt "geht gut / langsam /
                        nicht" mit ungefaehrer Dauer, dazu eine Empfehlung.
3. Arbeitsweise      -- alles hier, alles online oder gemischt.
4. Was noetig ist    -- Downloads und Platz, Lizenzhinweise, Zustimmung.
5. Einrichtung       -- FFmpeg, Ollama (still, nur fuers eigene Konto),
                        Sprachmodelle. Fehlt fuer die lokale Mitschrift die
                        Rechenumgebung, startet die Anwendung dafuer neu
                        (``bootstrap`` richtet sie ein) und setzt bei 6 fort.
6. Mitschrift        -- Whisper-Modell und Sprechererkennung (HF-Zugang).
7. Fertig.

Geschlossen werden kann jederzeit ("Spaeter einrichten"): Dann erscheint der
Dialog beim naechsten Start wieder -- ausser mit "Nicht mehr fragen". Ohne
Zustimmung wird in keinem Fall etwas geladen (siehe
``bootstrap.laufzeit_beim_start_einrichten``).

Nur fuer die Windows-Anwendung; der Servermodus kennt keine Oberflaeche.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from protokoll_assistent import bootstrap
from protokoll_assistent.gui.settings_dialog import DATENSCHUTZ_HINWEIS_API
from protokoll_assistent.services import (
    einrichtungsplan_service,
    model_service,
    ollama_einrichtung_service,
    ollama_service,
    rechner_analyse_service,
    secret_store,
)
from protokoll_assistent.services.einrichtungsplan_service import Baustein, Moeglichkeiten
from protokoll_assistent.services.rechner_analyse_service import GUT, MAESSIG, NICHT, Analyse
from protokoll_assistent.utils import app_config, hf_env
from protokoll_assistent.utils.logging_setup import get_logger

logger = get_logger()

FORTSETZEN_TRANSKRIPTION = "transkription"

HF_KONTO_URL = "https://huggingface.co/join"
HF_TOKEN_URL = "https://huggingface.co/settings/tokens"  # noqa: S105 -- eine Adresse, kein Schluessel

_ZEICHEN = {GUT: "✓", MAESSIG: "~", NICHT: "✗"}
_STUFEN_TEXT = {GUT: "geht gut", MAESSIG: "geht, aber langsam", NICHT: "nicht sinnvoll"}

_LOSGELOEST = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _starte_prozess(befehl: list[str], ordner: Path, umgebung: dict[str, str]) -> None:
    """Startet die Anwendung als eigenstaendigen Prozess (fuer den Neustart)."""
    subprocess.Popen(befehl, cwd=str(ordner), env=umgebung, creationflags=_LOSGELOEST, close_fds=True)


def laufzeit_vorhanden() -> bool:
    """Ist die Rechenumgebung fuer die lokale Mitschrift schon da?"""
    if importlib.util.find_spec("faster_whisper") is not None:
        return True
    from protokoll_assistent.utils.paths import get_active_venv_python

    return get_active_venv_python().is_file()


def _ollama_modelle() -> set[str]:
    try:
        return set(ollama_service.list_models(timeout=3))
    except ollama_service.OllamaError:
        return set()


def _modell_da(name: str, vorhanden: set[str]) -> bool:
    return name in vorhanden or (":" not in name and f"{name}:latest" in vorhanden)


# --------------------------------------------------------------------------
# Hintergrundarbeiter
# --------------------------------------------------------------------------
class ErmittlungsWorker(QThread):
    """Rechner analysieren und nachsehen, was schon da ist. Laedt nichts."""

    fertig = Signal(object, object)  # Analyse, dict mit "ffmpeg"/"ollama"/"laufzeit"/"modelle"

    def __init__(
        self,
        ordner: Path,
        parent=None,
        *,
        analyse_fn: Callable[[Path], Analyse] | None = None,
        vorhanden_fn: Callable[[], dict[str, Any]] | None = None,
    ):
        super().__init__(parent)
        self._ordner = ordner
        self._analyse_fn = analyse_fn or (
            lambda ordner: rechner_analyse_service.analysiere(rechner_analyse_service.ermittle_profil(ordner))
        )
        self._vorhanden_fn = vorhanden_fn or self._vorhanden

    @staticmethod
    def _vorhanden() -> dict[str, Any]:
        from protokoll_assistent.services import ffmpeg_service

        status = ollama_einrichtung_service.ermittle_status()
        return {
            "ffmpeg": ffmpeg_service.find_ffmpeg() is not None,
            "ollama": status.installiert,
            "laufzeit": laufzeit_vorhanden(),
            "modelle": _ollama_modelle() if status.dienst_laeuft else set(),
        }

    def run(self) -> None:
        try:
            analyse = self._analyse_fn(self._ordner)
        except Exception:  # Die Einrichtung darf daran nicht scheitern
            logger.exception("Rechner-Analyse fehlgeschlagen")
            analyse = rechner_analyse_service.analysiere(rechner_analyse_service.RechnerProfil())
        try:
            vorhanden = self._vorhanden_fn()
        except Exception:
            logger.exception("Pruefung vorhandener Bausteine fehlgeschlagen")
            vorhanden = {}
        self.fertig.emit(analyse, vorhanden)


class EinrichtungsWorker(QThread):
    """Laedt FFmpeg, installiert Ollama und holt die Sprachmodelle -- der Reihe nach."""

    schritt = Signal(str, str)  # Kennung, "laeuft" | "ok" | "fehler"
    fortschritt = Signal(int, int)  # fertig, gesamt (Bytes; 0, 0 = unbestimmt)
    log_line = Signal(str)
    fertig = Signal(dict)  # Kennung -> gelungen

    def __init__(
        self,
        aufgaben: list[str],
        modelle: list[str],
        parent=None,
        *,
        ffmpeg_fn: Callable[[Callable[[str], None]], bool] | None = None,
        ollama_fn: Callable[..., bool] | None = None,
        pull_fn: Callable[..., None] | None = None,
    ):
        super().__init__(parent)
        self._aufgaben = aufgaben
        self._modelle = modelle
        self._ffmpeg_fn = ffmpeg_fn or self._ffmpeg
        self._ollama_fn = ollama_fn or self._ollama
        self._pull_fn = pull_fn or ollama_service.pull_model
        self._abbrechen = False

    def abbrechen(self) -> None:
        self._abbrechen = True

    @staticmethod
    def _ffmpeg(log: Callable[[str], None]) -> bool:
        from protokoll_assistent.services import ffmpeg_service

        ffmpeg_service.ensure_ffmpeg_available(progress_cb=log)
        return ffmpeg_service.find_ffmpeg() is not None and ffmpeg_service.find_ffprobe() is not None

    def _ollama(self, log: Callable[[str], None]) -> bool:
        from protokoll_assistent.utils.paths import get_app_dir

        return ollama_einrichtung_service.installiere_ollama(
            get_app_dir() / "runtime" / "installer",
            log,
            lambda fertig, gesamt: self.fortschritt.emit(fertig, gesamt),
            abbrechen_fn=lambda: self._abbrechen,
        )

    def _ausfuehren(self, kennung: str, aufgabe: Callable[[], bool]) -> bool:
        self.schritt.emit(kennung, "laeuft")
        self.fortschritt.emit(0, 0)
        try:
            ok = bool(aufgabe())
        except (ollama_einrichtung_service.OllamaEinrichtungFehler, ollama_service.OllamaError) as fehler:
            self.log_line.emit(str(fehler))
            ok = False
        except Exception as fehler:  # keine Tracebacks in der Oberflaeche
            logger.exception("Einrichtungsschritt %s fehlgeschlagen", kennung)
            self.log_line.emit(f"Unerwarteter Fehler: {fehler}")
            ok = False
        self.schritt.emit(kennung, "ok" if ok else "fehler")
        return ok

    def run(self) -> None:
        ergebnis: dict[str, bool] = {}
        if "ffmpeg" in self._aufgaben:
            ergebnis["ffmpeg"] = self._ausfuehren("ffmpeg", lambda: self._ffmpeg_fn(self.log_line.emit))
        ollama_bereit = True
        if "ollama" in self._aufgaben:
            ollama_bereit = ergebnis["ollama"] = self._ausfuehren("ollama", lambda: self._ollama_fn(self.log_line.emit))
        for modell in self._modelle:
            kennung = f"modell:{modell}"
            if not ollama_bereit or self._abbrechen:
                self.schritt.emit(kennung, "fehler")
                ergebnis[kennung] = False
                continue

            def ziehen(modell: str = modell) -> bool:
                self.log_line.emit(f"Lade {modell} ...")
                self._pull_fn(
                    modell, progress_cb=lambda status, fertig, gesamt: self.fortschritt.emit(fertig, gesamt)
                )
                return True

            ergebnis[kennung] = self._ausfuehren(kennung, ziehen)
        self.fertig.emit(ergebnis)


class MitschriftWorker(QThread):
    """Whisper-Modell und Sprechererkennung laden (in der Rechenumgebung)."""

    log_line = Signal(str)
    fertig = Signal(dict)

    def __init__(
        self,
        whisper_modell: str,
        token: str | None,
        sprechertrennung: bool,
        parent=None,
        *,
        whisper_fn: Callable[..., bool] | None = None,
        pyannote_fn: Callable[..., bool] | None = None,
    ):
        super().__init__(parent)
        self._whisper_modell = whisper_modell
        self._token = token  # nur zur Weitergabe, nie ins Log
        self._sprechertrennung = sprechertrennung
        self._whisper_fn = whisper_fn
        self._pyannote_fn = pyannote_fn

    def run(self) -> None:
        from protokoll_assistent.services import model_download_service

        whisper_fn = self._whisper_fn or model_download_service.download_whisper_and_alignment
        pyannote_fn = self._pyannote_fn or model_download_service.download_pyannote
        ergebnis: dict[str, bool] = {}
        try:
            ergebnis["whisper"] = bool(whisper_fn(self.log_line.emit, model_name=self._whisper_modell))
            if self._sprechertrennung:
                token = self._token
                ergebnis["pyannote"] = bool(pyannote_fn(self.log_line.emit, get_token=lambda: token))
        except Exception as fehler:  # keine Tracebacks in der Oberflaeche
            logger.exception("Download fuer die Mitschrift fehlgeschlagen")
            self.log_line.emit(f"Unerwarteter Fehler: {fehler}")
        self.fertig.emit(ergebnis)


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------
def _ueberschrift(text: str, eltern: QWidget) -> QLabel:
    label = QLabel(text, eltern)
    label.setObjectName("PageTitle")
    return label


def _text(text: str, eltern: QWidget, *, untertitel: bool = False) -> QLabel:
    label = QLabel(text, eltern)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    if untertitel:
        label.setObjectName("PageSubtitle")
    return label


class ErsteinrichtungDialog(QDialog):
    NEUSTART = 2
    SCHRITTE = ("Willkommen", "Ihr Computer", "Arbeitsweise", "Was nötig ist", "Einrichtung", "Mitschrift", "Fertig")
    (S_WILLKOMMEN, S_RECHNER, S_ARBEITSWEISE, S_KOSTEN, S_EINRICHTUNG, S_MITSCHRIFT, S_FERTIG) = range(7)

    def __init__(self, parent=None, start_bei: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Protokoll-Assistent einrichten")
        self.setObjectName("WizardRoot")
        self.resize(860, 680)

        self.analyse: Analyse | None = None
        self.moeglichkeiten: Moeglichkeiten | None = None
        self.vorhanden: dict[str, Any] = {}
        self.bausteine: list[Baustein] = []
        self.ergebnisse: dict[str, bool] = {}
        self._zugestimmt = False
        self._fortsetzung = start_bei == FORTSETZEN_TRANSKRIPTION
        self._ermittlung: ErmittlungsWorker | None = None
        self._einrichtung: EinrichtungsWorker | None = None
        self._mitschrift: MitschriftWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        schritte = QHBoxLayout()
        self._schritt_labels: list[QLabel] = []
        for nummer, name in enumerate(self.SCHRITTE, start=1):
            label = QLabel(f"{nummer}. {name}", self)
            label.setObjectName("StepIndicator")
            schritte.addWidget(label)
            self._schritt_labels.append(label)
        schritte.addStretch(1)
        layout.addLayout(schritte)

        self.stack = QStackedWidget(self)
        for bauen in (
            self._baue_willkommen,
            self._baue_rechner,
            self._baue_arbeitsweise,
            self._baue_kosten,
            self._baue_einrichtung,
            self._baue_mitschrift,
            self._baue_fertig,
        ):
            self.stack.addWidget(bauen())
        layout.addWidget(self.stack, stretch=1)

        unten = QHBoxLayout()
        self.spaeter_button = QPushButton("Später einrichten", self)
        self.spaeter_button.clicked.connect(self.reject)
        unten.addWidget(self.spaeter_button)
        self.nicht_mehr_fragen = QCheckBox("Nicht mehr fragen", self)
        self.nicht_mehr_fragen.setToolTip(
            "Die Einrichtung erscheint dann nicht mehr von selbst. Sie bleibt über "
            "Einstellungen → Transkription → Lokal → „Einrichtung starten“ erreichbar."
        )
        unten.addWidget(self.nicht_mehr_fragen)
        unten.addStretch(1)
        layout.addLayout(unten)

        self._gehe_zu(self.S_MITSCHRIFT if self._fortsetzung else self.S_WILLKOMMEN)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _gehe_zu(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for nummer, label in enumerate(self._schritt_labels):
            label.setObjectName("StepIndicatorActive" if nummer == index else "StepIndicator")
            label.style().unpolish(label)
            label.style().polish(label)
        if index == self.S_RECHNER and self.analyse is None:
            self._ermitteln()
        elif index == self.S_KOSTEN:
            self._zeige_kosten()
        elif index == self.S_EINRICHTUNG:
            self._einrichtung_starten()
        elif index == self.S_MITSCHRIFT:
            self._mitschrift_vorbereiten()
        elif index == self.S_FERTIG:
            self._zeige_fertig()

    def reject(self) -> None:
        """Schliessen ohne Abschluss: Der Dialog kommt beim naechsten Start
        wieder -- ausser mit "Nicht mehr fragen"."""
        if self._einrichtung is not None and self._einrichtung.isRunning():
            self._einrichtung.abbrechen()
        if self.nicht_mehr_fragen.isChecked():
            aenderungen: dict[str, Any] = {
                "einrichtung_abgeschlossen": True,
                "einrichtung_version": app_config.EINRICHTUNG_VERSION,
                "einrichtung_fortsetzen": "",
            }
            if not self._zugestimmt and not self._fortsetzung and not laufzeit_vorhanden():
                # Ohne Zustimmung nie ungefragt die Rechenumgebung laden.
                aenderungen["lokale_einrichtung_zurueckgestellt"] = True
            app_config.update_config(**aenderungen)
        super().reject()

    # ------------------------------------------------------------------
    # 1. Willkommen
    # ------------------------------------------------------------------
    def _baue_willkommen(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Willkommen beim Protokoll-Assistenten", seite))
        layout.addWidget(_text("Der Protokoll-Assistent macht aus einer Besprechung ein fertiges Protokoll.", seite, untertitel=True))
        layout.addWidget(
            _text(
                "<ol>"
                "<li><b>Aufnehmen oder Datei wählen</b> – direkt im Programm aufnehmen oder eine vorhandene "
                "Audio- oder Videodatei öffnen.</li>"
                "<li><b>Mitschrift</b> – das Programm schreibt mit, wer was gesagt hat.</li>"
                "<li><b>Protokoll</b> – daraus entsteht eine Zusammenfassung mit Beschlüssen, Aufgaben und "
                "offenen Fragen, als Word-Datei oder PDF.</li>"
                "<li><b>Frag mein Meeting</b> – Fragen stellen wie „Was haben wir zum Budget beschlossen?“</li>"
                "</ol>"
                "<p>Das kann ganz auf diesem Computer laufen – dann verlässt nichts den Rechner – oder über "
                "einen Online-Dienst. Auf den nächsten Seiten sehen Sie, was auf Ihrem Computer gut geht und "
                "was es kostet.</p>"
                "<p><b>Es wird nichts heruntergeladen, bevor Sie zustimmen.</b></p>"
                "<p>Wer ohnehin nur einen Online-Dienst nutzen möchte, überspringt die Einrichtung und "
                "trägt gleich danach in den Einstellungen seinen API-Schlüssel ein.</p>",
                seite,
            )
        )
        layout.addStretch(1)
        knoepfe = QHBoxLayout()
        self.ueberspringen_button = QPushButton("Überspringen – ich nutze einen API-Schlüssel", seite)
        self.ueberspringen_button.setToolTip(
            "Nichts wird geladen. Mitschrift, Protokoll und Frag mein Meeting laufen dann über einen "
            "Online-Dienst: Aufnahme bzw. Text gehen an den Anbieter, den Sie in den Einstellungen wählen."
        )
        self.ueberspringen_button.clicked.connect(self._ueberspringen)
        knoepfe.addWidget(self.ueberspringen_button)
        knoepfe.addStretch(1)
        self.los_button = QPushButton("Los geht's", seite)
        self.los_button.setObjectName("PrimaryButton")
        self.los_button.clicked.connect(lambda: self._gehe_zu(self.S_RECHNER))
        knoepfe.addWidget(self.los_button)
        layout.addLayout(knoepfe)
        return seite

    # ------------------------------------------------------------------
    # 2. Ihr Computer
    # ------------------------------------------------------------------
    def _baue_rechner(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Ihr Computer", seite))
        self.profil_label = _text("Ihr Computer wird angesehen …", seite, untertitel=True)
        layout.addWidget(self.profil_label)

        self.schritte_raster = QGridLayout()
        self.schritt_zeilen: dict[str, tuple[QLabel, QLabel]] = {}
        for zeile, schritt in enumerate(
            (
                einrichtungsplan_service.SCHRITT_MITSCHRIFT,
                einrichtungsplan_service.SCHRITT_SPRECHER,
                einrichtungsplan_service.SCHRITT_PROTOKOLL,
                einrichtungsplan_service.SCHRITT_CHAT,
            )
        ):
            name = QLabel(f"<b>{schritt}</b>", seite)
            bewertung = QLabel("…", seite)
            bewertung.setWordWrap(True)
            self.schritte_raster.addWidget(name, zeile, 0)
            self.schritte_raster.addWidget(bewertung, zeile, 1)
            self.schritt_zeilen[schritt] = (name, bewertung)
        self.schritte_raster.setColumnStretch(1, 1)
        layout.addLayout(self.schritte_raster)

        self.empfehlung_label = _text("", seite)
        self.empfehlung_label.setObjectName("SetupBanner")
        layout.addWidget(self.empfehlung_label)

        self.details_tabelle = QTableWidget(0, 3, seite)
        self.details_button = QPushButton("Details zu den Modellen zeigen", seite)
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.details_tabelle.setVisible)
        layout.addWidget(self.details_button, alignment=Qt.AlignLeft)
        self.details_tabelle.setHorizontalHeaderLabels(["Modell", "Einschätzung", "Hinweis"])
        self.details_tabelle.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.details_tabelle.verticalHeader().setVisible(False)
        self.details_tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self.details_tabelle.setVisible(False)
        layout.addWidget(self.details_tabelle, stretch=1)
        layout.addStretch(1)

        knoepfe = QHBoxLayout()
        zurueck = QPushButton("Zurück", seite)
        zurueck.clicked.connect(lambda: self._gehe_zu(self.S_WILLKOMMEN))
        knoepfe.addWidget(zurueck)
        knoepfe.addStretch(1)
        self.rechner_weiter_button = QPushButton("Weiter", seite)
        self.rechner_weiter_button.setObjectName("PrimaryButton")
        self.rechner_weiter_button.setEnabled(False)
        self.rechner_weiter_button.clicked.connect(lambda: self._gehe_zu(self.S_ARBEITSWEISE))
        knoepfe.addWidget(self.rechner_weiter_button)
        layout.addLayout(knoepfe)
        return seite

    def _ermitteln(self) -> None:
        from protokoll_assistent.utils.paths import get_default_output_dir

        if self._ermittlung is not None and self._ermittlung.isRunning():
            return
        self._ermittlung = ErmittlungsWorker(get_default_output_dir(), self)
        self._ermittlung.fertig.connect(self.zeige_ermittlung)
        self._ermittlung.start()

    def zeige_ermittlung(self, analyse: Analyse, vorhanden: dict[str, Any]) -> None:
        self.analyse = analyse
        self.vorhanden = vorhanden
        self.moeglichkeiten = einrichtungsplan_service.schaetze(analyse)
        self.profil_label.setText(rechner_analyse_service.beschreibe_profil(analyse.profil).replace("\n", "<br>"))
        for schaetzung in self.moeglichkeiten.schritte:
            _name, bewertung = self.schritt_zeilen[schaetzung.schritt]
            bewertung.setText(
                f"{_ZEICHEN[schaetzung.stufe]} {_STUFEN_TEXT[schaetzung.stufe]} – {schaetzung.text}"
            )
        hinweise = "".join(f"<li>{h}</li>" for h in analyse.hinweise)
        self.empfehlung_label.setText(
            f"<b>{self.moeglichkeiten.begruendung}</b>"
            + (f"<ul>{hinweise}</ul>" if hinweise else "")
            + "<p>Alle Zeiten sind ungefähre Werte.</p>"
        )
        self.details_tabelle.setRowCount(len(analyse.bewertungen))
        for zeile, b in enumerate(analyse.bewertungen):
            empfohlen = analyse.empfehlung.get(b.bereich) == b.modell_id
            self.details_tabelle.setItem(zeile, 0, QTableWidgetItem(f"{b.bereich}: {b.name}" + ("  ★" if empfohlen else "")))
            self.details_tabelle.setItem(zeile, 1, QTableWidgetItem(_STUFEN_TEXT[b.stufe]))
            self.details_tabelle.setItem(zeile, 2, QTableWidgetItem(b.text))
        self.details_tabelle.resizeColumnToContents(0)
        self._arbeitsweise_vorauswaehlen()
        self.rechner_weiter_button.setEnabled(True)

    # ------------------------------------------------------------------
    # 3. Arbeitsweise
    # ------------------------------------------------------------------
    def _baue_arbeitsweise(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Wie möchten Sie arbeiten?", seite))

        self.weg_gruppe = QButtonGroup(seite)
        self.weg_lokal = QRadioButton("Alles auf diesem Computer", seite)
        self.weg_online = QRadioButton("Über einen Online-Dienst", seite)
        self.weg_gemischt = QRadioButton("Selbst festlegen, was wo läuft", seite)
        # Die Erklaerung steht als eigenes, umbrechendes Label darunter: Der Text
        # eines Optionsfelds bricht in Qt nicht um und zoege das Fenster in die Breite.
        for knopf, erklaerung in (
            (self.weg_lokal, "Nichts verlässt den Rechner. Einmalig einige Gigabyte Download (siehe nächste Seite)."),
            (
                self.weg_online,
                "Keine großen Downloads, sofort startklar. Ihre Aufnahme bzw. der Text geht dafür an den Anbieter, "
                "den Sie wählen; je nach Anbieter kostet das pro Nutzung Geld.",
            ),
            (self.weg_gemischt, "Zum Beispiel die Mitschrift hier und das Protokoll online."),
        ):
            self.weg_gruppe.addButton(knopf)
            layout.addWidget(knopf)
            hinweis = _text(erklaerung, seite, untertitel=True)
            hinweis.setContentsMargins(24, 0, 0, 8)
            layout.addWidget(hinweis)

        self.einzeln = QWidget(seite)
        raster = QGridLayout(self.einzeln)
        raster.setContentsMargins(24, 0, 0, 0)
        self.wahl: dict[str, QComboBox] = {}
        for zeile, (schluessel, name) in enumerate(
            (("transkription", "Mitschrift"), ("nachbearbeitung", "Protokoll"), ("chatbot", "Frag mein Meeting"))
        ):
            raster.addWidget(QLabel(name, self.einzeln), zeile, 0)
            combo = QComboBox(self.einzeln)
            combo.addItem("auf diesem Computer", "lokal")
            combo.addItem("online", "api")
            combo.currentIndexChanged.connect(self._arbeitsweise_geaendert)
            raster.addWidget(combo, zeile, 1)
            self.wahl[schluessel] = combo
        raster.setColumnStretch(2, 1)
        layout.addWidget(self.einzeln)

        self.datenschutz_label = _text(DATENSCHUTZ_HINWEIS_API, seite)
        self.datenschutz_label.setObjectName("DatenschutzHinweis")
        layout.addWidget(self.datenschutz_label)
        self.anbieter_hinweis = _text(
            "Den Anbieter und Ihren Zugangsschlüssel tragen Sie am Ende in den Einstellungen ein.", seite
        )
        layout.addWidget(self.anbieter_hinweis)
        layout.addStretch(1)
        self.weg_gruppe.buttonToggled.connect(lambda *_: self._arbeitsweise_geaendert())

        knoepfe = QHBoxLayout()
        zurueck = QPushButton("Zurück", seite)
        zurueck.clicked.connect(lambda: self._gehe_zu(self.S_RECHNER))
        knoepfe.addWidget(zurueck)
        knoepfe.addStretch(1)
        self.arbeitsweise_weiter_button = QPushButton("Weiter", seite)
        self.arbeitsweise_weiter_button.setObjectName("PrimaryButton")
        self.arbeitsweise_weiter_button.clicked.connect(self._arbeitsweise_uebernehmen)
        knoepfe.addWidget(self.arbeitsweise_weiter_button)
        layout.addLayout(knoepfe)
        self._arbeitsweise_geaendert()
        return seite

    def _arbeitsweise_vorauswaehlen(self) -> None:
        """Die Empfehlung als Vorauswahl -- ein Online-Dienst aber nie von
        selbst: Wohin die Daten gehen, entscheidet der Anwender."""
        empfehlung = self.moeglichkeiten.empfehlung if self.moeglichkeiten else None
        self.weg_gruppe.setExclusive(False)
        for knopf in (self.weg_lokal, self.weg_online, self.weg_gemischt):
            knopf.setChecked(False)
        self.weg_gruppe.setExclusive(True)
        if empfehlung == einrichtungsplan_service.EMPFEHLUNG_LOKAL:
            self.weg_lokal.setChecked(True)
        elif empfehlung == einrichtungsplan_service.EMPFEHLUNG_GEMISCHT:
            # Nur die Einzelwahl aufklappen; "online" fuer das Protokoll waehlt der Anwender selbst.
            self.weg_gemischt.setChecked(True)
        self._arbeitsweise_geaendert()

    def arbeitsweise(self) -> dict[str, str]:
        """Bereich -> "lokal" | "api" nach der aktuellen Wahl ({} ohne Wahl)."""
        if self.weg_lokal.isChecked():
            return {schluessel: "lokal" for schluessel in self.wahl}
        if self.weg_online.isChecked():
            return {schluessel: "api" for schluessel in self.wahl}
        if self.weg_gemischt.isChecked():
            return {schluessel: combo.currentData() for schluessel, combo in self.wahl.items()}
        return {}

    def _arbeitsweise_geaendert(self, *_args) -> None:
        self.einzeln.setVisible(self.weg_gemischt.isChecked())
        wahl = self.arbeitsweise()
        online = "api" in wahl.values()
        self.datenschutz_label.setVisible(online)
        self.anbieter_hinweis.setVisible(online)
        self.arbeitsweise_weiter_button.setEnabled(bool(wahl))

    def _arbeitsweise_uebernehmen(self) -> None:
        wahl = self.arbeitsweise()
        if not wahl:
            return
        aenderungen: dict[str, Any] = {
            "transkription_modus": wahl["transkription"],
            "nachbearbeitung_modus": wahl["nachbearbeitung"],
            "chatbot_modus": wahl["chatbot"],
        }
        konfig = app_config.load_config()
        if self.analyse is not None:
            whisper = self.analyse.empfehlung.get(rechner_analyse_service.BEREICH_TRANSKRIPTION)
            if wahl["transkription"] == "lokal" and whisper and not konfig["whisper_modell"]:
                aenderungen["whisper_modell"] = whisper
            # Empfohlenes Sprachmodell nur, wo noch der Standard steht (wie 'RechnerAnalysePage').
            sprache = self.analyse.empfehlung.get(rechner_analyse_service.BEREICH_NACHBEARBEITUNG)
            if sprache and sprache != ollama_service.DEFAULT_MODEL:
                for schluessel in ("ollama_modell", "chatbot_ollama_modell"):
                    if konfig[schluessel] == ollama_service.DEFAULT_MODEL:
                        aenderungen[schluessel] = sprache
        app_config.update_config(**aenderungen)
        self._gehe_zu(self.S_KOSTEN)

    # ------------------------------------------------------------------
    # 4. Was noetig ist
    # ------------------------------------------------------------------
    def _baue_kosten(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Was dafür nötig ist", seite))
        layout.addWidget(
            _text("Das wird einmalig aus dem Internet geladen. Ihre Aufnahmen werden dabei nicht übertragen.", seite, untertitel=True)
        )
        self.kosten_tabelle = QTableWidget(0, 4, seite)
        self.kosten_tabelle.setHorizontalHeaderLabels(["Baustein", "Download", "Platz", "Hinweis"])
        kopf = self.kosten_tabelle.horizontalHeader()
        for spalte, modus in ((0, QHeaderView.Stretch), (1, QHeaderView.ResizeToContents),
                              (2, QHeaderView.ResizeToContents), (3, QHeaderView.Stretch)):
            kopf.setSectionResizeMode(spalte, modus)
        self.kosten_tabelle.setWordWrap(True)
        self.kosten_tabelle.verticalHeader().setVisible(False)
        self.kosten_tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.kosten_tabelle, stretch=1)
        self.summe_label = _text("", seite)
        layout.addWidget(self.summe_label)
        self.lizenz_label = _text(
            f"Ollama ist ein eigenständiges Programm der Ollama Inc. (Lizenz: "
            f"<a href='{ollama_einrichtung_service.OLLAMA_LIZENZ_URL}'>MIT</a>, "
            f"<a href='{ollama_einrichtung_service.OLLAMA_BEDINGUNGEN_URL}'>Nutzungsbedingungen</a>). "
            "Es wird direkt vom Hersteller geladen, auf Echtheit geprüft und nur für Ihr Benutzerkonto "
            "installiert – ohne Administratorrechte.",
            seite,
        )
        layout.addWidget(self.lizenz_label)
        self.zustimmung = QCheckBox("Ich bin einverstanden, dass das Genannte geladen und eingerichtet wird.", seite)
        self.zustimmung.toggled.connect(self._zustimmung_geaendert)
        layout.addWidget(self.zustimmung)

        knoepfe = QHBoxLayout()
        zurueck = QPushButton("Zurück", seite)
        zurueck.clicked.connect(lambda: self._gehe_zu(self.S_ARBEITSWEISE))
        knoepfe.addWidget(zurueck)
        knoepfe.addStretch(1)
        self.einrichten_button = QPushButton("Herunterladen und einrichten", seite)
        self.einrichten_button.setObjectName("PrimaryButton")
        self.einrichten_button.setEnabled(False)
        self.einrichten_button.clicked.connect(self._zustimmen)
        knoepfe.addWidget(self.einrichten_button)
        layout.addLayout(knoepfe)
        return seite

    def _modellnamen(self) -> tuple[str, str]:
        konfig = app_config.load_config()
        sprache = konfig["ollama_modell"] if konfig["nachbearbeitung_modus"] == "lokal" else konfig["chatbot_ollama_modell"]
        return sprache or ollama_service.DEFAULT_MODEL, konfig["chatbot_embedding_modell"]

    def _zeige_kosten(self) -> None:
        konfig = app_config.load_config()
        sprache, einbettung = self._modellnamen()
        modelle = self.vorhanden.get("modelle") or set()
        vorhanden = {
            "ffmpeg": bool(self.vorhanden.get("ffmpeg")),
            "ollama": bool(self.vorhanden.get("ollama")),
            "laufzeit": bool(self.vorhanden.get("laufzeit")),
            "sprachmodell": _modell_da(sprache, modelle),
            "einbettung": _modell_da(einbettung, modelle),
        }
        profil = self.analyse.profil if self.analyse else rechner_analyse_service.RechnerProfil()
        self.bausteine = einrichtungsplan_service.bausteine_fuer(
            transkription_lokal=konfig["transkription_modus"] == "lokal",
            nachbearbeitung_lokal=konfig["nachbearbeitung_modus"] == "lokal",
            chat_lokal=konfig["chatbot_modus"] == "lokal",
            cuda_gpu=profil.cuda_gpu,
            whisper_modell=konfig["whisper_modell"] or model_service.WHISPER_MODEL_NAME,
            sprachmodell=sprache,
            einbettungsmodell=einbettung,
            vorhanden=vorhanden,
        )
        self.kosten_tabelle.setRowCount(len(self.bausteine))
        for zeile, baustein in enumerate(self.bausteine):
            self.kosten_tabelle.setItem(zeile, 0, QTableWidgetItem(baustein.name))
            if baustein.vorhanden:
                self.kosten_tabelle.setItem(zeile, 1, QTableWidgetItem("bereits vorhanden ✓"))
                self.kosten_tabelle.setItem(zeile, 2, QTableWidgetItem(""))
            else:
                self.kosten_tabelle.setItem(zeile, 1, QTableWidgetItem(f"{baustein.download_gb:.1f} GB"))
                self.kosten_tabelle.setItem(zeile, 2, QTableWidgetItem(f"{baustein.platz_gb:.1f} GB"))
            self.kosten_tabelle.setItem(zeile, 3, QTableWidgetItem(baustein.hinweis))
        self.kosten_tabelle.resizeRowsToContents()

        download, platz = einrichtungsplan_service.summe(self.bausteine)
        if download <= 0:
            self.summe_label.setText("<b>Alles Nötige ist schon vorhanden.</b>")
        else:
            minuten = einrichtungsplan_service.download_minuten(download)
            text = (
                f"<b>Zusammen etwa {download:.1f} GB Download und {platz:.1f} GB Platz auf der Festplatte.</b> "
                f"Bei einer üblichen Internetverbindung (50 Mbit/s) dauert der Download "
                f"{einrichtungsplan_service.formatiere_dauer(minuten, minuten * 1.3)}."
            )
            if profil.freier_platz_gb is not None and profil.freier_platz_gb < platz + 2:
                text += f"<br><b>Achtung:</b> Frei sind nur {profil.freier_platz_gb:.0f} GB – bitte vorher Platz schaffen."
            self.summe_label.setText(text)
        self.lizenz_label.setVisible(any(b.kennung == "ollama" and not b.vorhanden for b in self.bausteine))
        self._zustimmung_geaendert()

    def _zustimmung_geaendert(self, *_args) -> None:
        download, _platz = einrichtungsplan_service.summe(self.bausteine)
        noetig = download > 0
        self.zustimmung.setVisible(noetig)
        self.einrichten_button.setText("Herunterladen und einrichten" if noetig else "Weiter")
        self.einrichten_button.setEnabled(self.zustimmung.isChecked() or not noetig)

    def _zustimmen(self) -> None:
        self._zugestimmt = True
        self.nicht_mehr_fragen.setChecked(False)
        app_config.update_config(lokale_einrichtung_zurueckgestellt=False)
        self._gehe_zu(self.S_EINRICHTUNG)

    # ------------------------------------------------------------------
    # 5. Einrichtung
    # ------------------------------------------------------------------
    def _baue_einrichtung(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Einrichtung läuft", seite))
        self.einrichtung_status = _text("", seite, untertitel=True)
        layout.addWidget(self.einrichtung_status)
        self.aufgaben_raster = QGridLayout()
        layout.addLayout(self.aufgaben_raster)
        self.aufgaben_labels: dict[str, QLabel] = {}
        self.einrichtung_fortschritt = QProgressBar(seite)
        layout.addWidget(self.einrichtung_fortschritt)
        self.einrichtung_log = QPlainTextEdit(seite)
        self.einrichtung_log.setReadOnly(True)
        layout.addWidget(self.einrichtung_log, stretch=1)

        knoepfe = QHBoxLayout()
        self.erneut_button = QPushButton("Erneut versuchen", seite)
        self.erneut_button.setVisible(False)
        self.erneut_button.clicked.connect(self._einrichtung_starten)
        knoepfe.addWidget(self.erneut_button)
        knoepfe.addStretch(1)
        self.neustart_button = QPushButton("Jetzt neu starten", seite)
        self.neustart_button.setObjectName("PrimaryButton")
        self.neustart_button.setVisible(False)
        self.neustart_button.clicked.connect(self._neu_starten)
        knoepfe.addWidget(self.neustart_button)
        self.einrichtung_weiter_button = QPushButton("Weiter", seite)
        self.einrichtung_weiter_button.setObjectName("PrimaryButton")
        self.einrichtung_weiter_button.setEnabled(False)
        self.einrichtung_weiter_button.clicked.connect(self._nach_der_einrichtung)
        knoepfe.addWidget(self.einrichtung_weiter_button)
        layout.addLayout(knoepfe)
        return seite

    def _aufgaben(self) -> tuple[list[str], list[str]]:
        """(Werkzeuge, Ollama-Modelle), die noch fehlen."""
        fehlend = {b.kennung for b in self.bausteine if not b.vorhanden}
        werkzeuge: list[str] = [k for k in ("ffmpeg", "ollama") if k in fehlend]
        sprache, einbettung = self._modellnamen()
        konfig = app_config.load_config()
        modelle = []
        if "sprachmodell" in fehlend:
            modelle.append(sprache)
            if konfig["chatbot_modus"] == "lokal" and konfig["chatbot_ollama_modell"] not in (sprache, ""):
                modelle.append(konfig["chatbot_ollama_modell"])
        if "einbettung" in fehlend:
            modelle.append(einbettung)
        return werkzeuge, modelle

    def _einrichtung_starten(self) -> None:
        if self._einrichtung is not None and self._einrichtung.isRunning():
            return
        werkzeuge, modelle = self._aufgaben()
        namen = {"ffmpeg": "FFmpeg", "ollama": "Ollama"}
        while self.aufgaben_raster.count():
            element = self.aufgaben_raster.takeAt(0)
            widget = element.widget() if element is not None else None
            if widget is not None:
                widget.deleteLater()
        self.aufgaben_labels.clear()
        for zeile, kennung in enumerate([*werkzeuge, *(f"modell:{m}" for m in modelle)]):
            name = namen.get(kennung, kennung.removeprefix("modell:"))
            self.aufgaben_raster.addWidget(QLabel(name, self), zeile, 0)
            zustand = QLabel("wartet", self)
            self.aufgaben_raster.addWidget(zustand, zeile, 1)
            self.aufgaben_labels[kennung] = zustand
        self.erneut_button.setVisible(False)
        self.neustart_button.setVisible(False)
        self.einrichtung_weiter_button.setEnabled(False)
        self.einrichtung_log.clear()
        if not werkzeuge and not modelle:
            self.einrichtung_fertig({})
            return
        self.einrichtung_status.setText("Bitte warten – je nach Internetverbindung dauert das einige Minuten.")
        self._einrichtung = EinrichtungsWorker(werkzeuge, modelle, self)
        self._einrichtung.schritt.connect(self._aufgabe_zustand)
        self._einrichtung.fortschritt.connect(self._einrichtung_fortschritt)
        self._einrichtung.log_line.connect(self.einrichtung_log.appendPlainText)
        self._einrichtung.fertig.connect(self.einrichtung_fertig)
        self._einrichtung.start()

    def _aufgabe_zustand(self, kennung: str, zustand: str) -> None:
        label = self.aufgaben_labels.get(kennung)
        if label is not None:
            label.setText({"laeuft": "läuft …", "ok": "✓ fertig", "fehler": "✗ nicht gelungen"}.get(zustand, zustand))

    def _einrichtung_fortschritt(self, fertig: int, gesamt: int) -> None:
        if gesamt > 0:
            self.einrichtung_fortschritt.setRange(0, 1000)
            self.einrichtung_fortschritt.setValue(round(fertig / gesamt * 1000))
            self.einrichtung_fortschritt.setFormat(f"{fertig / 1024**2:.0f} von {gesamt / 1024**2:.0f} MB")
        else:
            self.einrichtung_fortschritt.setRange(0, 0)

    def _braucht_neustart(self) -> bool:
        return app_config.load_config()["transkription_modus"] == "lokal" and not laufzeit_vorhanden()

    def einrichtung_fertig(self, ergebnis: dict) -> None:
        self.ergebnisse.update(ergebnis)
        self.einrichtung_fortschritt.setRange(0, 1)
        self.einrichtung_fortschritt.setValue(1)
        self.einrichtung_fortschritt.setFormat("fertig")
        fehlgeschlagen = [kennung for kennung, ok in ergebnis.items() if not ok]
        self.erneut_button.setVisible(bool(fehlgeschlagen))
        if fehlgeschlagen:
            text = (
                "Nicht alles hat geklappt (die Gründe stehen unten). Sie können es erneut versuchen oder "
                "trotzdem weitermachen – Fehlendes lässt sich später über Einstellungen → Systemdiagnose nachladen."
            )
        else:
            text = "Alles Nötige ist geladen und eingerichtet."
        if self._braucht_neustart():
            text += (
                "<br><br><b>Für die Mitschrift auf diesem Computer fehlt noch die Rechenumgebung.</b> "
                "Dafür startet das Programm einmal neu: Ein kleines Fenster zeigt den Fortschritt "
                "(einige Minuten), danach geht die Einrichtung hier weiter."
            )
            self.neustart_button.setVisible(True)
            self.einrichtung_weiter_button.setVisible(False)
        else:
            self.einrichtung_weiter_button.setVisible(True)
            self.einrichtung_weiter_button.setEnabled(True)
        self.einrichtung_status.setText(text)

    def _nach_der_einrichtung(self) -> None:
        lokal = app_config.load_config()["transkription_modus"] == "lokal"
        self._gehe_zu(self.S_MITSCHRIFT if lokal else self.S_FERTIG)

    def _neu_starten(self) -> None:
        app_config.update_config(
            einrichtung_fortsetzen=FORTSETZEN_TRANSKRIPTION,
            transkription_modus="lokal",
            lokale_einrichtung_zurueckgestellt=False,
        )
        befehl, ordner, umgebung = bootstrap.neustart_kommando()
        try:
            _starte_prozess(befehl, ordner, umgebung)
        except OSError as fehler:
            app_config.update_config(einrichtung_fortsetzen="")
            QMessageBox.warning(
                self,
                "Neustart nicht möglich",
                f"Das Programm konnte sich nicht neu starten ({fehler}). Bitte schließen und von Hand neu öffnen.",
            )
            return
        self.done(self.NEUSTART)

    # ------------------------------------------------------------------
    # 6. Mitschrift
    # ------------------------------------------------------------------
    def _baue_mitschrift(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Mitschrift vorbereiten", seite))
        layout.addWidget(
            _text("Zum Schluss werden die Modelle für die Mitschrift geladen.", seite, untertitel=True)
        )
        zeile_modell = QHBoxLayout()
        zeile_modell.addWidget(QLabel("Spracherkennung:", seite))
        self.whisper_wahl = QComboBox(seite)
        for option in model_service.WHISPER_MODELLE:
            self.whisper_wahl.addItem(option.label, option.id)
        zeile_modell.addWidget(self.whisper_wahl, stretch=1)
        layout.addLayout(zeile_modell)

        self.sprecher_checkbox = QCheckBox("Sprechererkennung einrichten (wer hat was gesagt)", seite)
        self.sprecher_checkbox.setChecked(True)
        self.sprecher_checkbox.toggled.connect(self._sprecher_geaendert)
        layout.addWidget(self.sprecher_checkbox)
        self.token_bereich = QWidget(seite)
        token_layout = QVBoxLayout(self.token_bereich)
        token_layout.setContentsMargins(24, 0, 0, 0)
        self.token_anleitung = _text(
            "Die Sprechererkennung braucht einen kostenlosen Zugang bei Hugging Face:"
            f"<ol><li><a href='{HF_KONTO_URL}'>Konto anlegen</a> (falls noch keins da ist)</li>"
            f"<li>auf der <a href='{model_service.PYANNOTE_LICENSE_URL}'>Seite des Modells</a> die "
            "Bedingungen annehmen</li>"
            f"<li>einen <a href='{HF_TOKEN_URL}'>Zugangsschlüssel</a> („Token“, Leserecht genügt) erzeugen "
            "und hier einfügen</li></ol>"
            "Ohne Schlüssel funktioniert die Mitschrift trotzdem – nur ohne Sprecher.",
            self.token_bereich,
        )
        token_layout.addWidget(self.token_anleitung)
        self.token_edit = QLineEdit(self.token_bereich)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("hf_…")
        token_layout.addWidget(self.token_edit)
        self.token_merken = QCheckBox("Auf diesem Gerät merken", self.token_bereich)
        self.token_merken.setChecked(True)
        token_layout.addWidget(self.token_merken)
        merken_hinweis = _text(
            "Verschlüsselt in der Windows-Anmeldeinformationsverwaltung, nie in einer Datei. Ohne Merken fehlt "
            "der Schlüssel der Sprechererkennung nach dem nächsten Start.",
            self.token_bereich,
            untertitel=True,
        )
        merken_hinweis.setContentsMargins(24, 0, 0, 0)
        token_layout.addWidget(merken_hinweis)
        layout.addWidget(self.token_bereich)
        self.token_vorhanden_label = _text("✓ Ein Zugang zu Hugging Face ist bereits hinterlegt.", seite)
        layout.addWidget(self.token_vorhanden_label)

        self.mitschrift_fortschritt = QProgressBar(seite)
        self.mitschrift_fortschritt.setRange(0, 1)
        self.mitschrift_fortschritt.setVisible(False)
        layout.addWidget(self.mitschrift_fortschritt)
        self.mitschrift_log = QPlainTextEdit(seite)
        self.mitschrift_log.setReadOnly(True)
        layout.addWidget(self.mitschrift_log, stretch=1)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        self.mitschrift_laden_button = QPushButton("Herunterladen", seite)
        self.mitschrift_laden_button.setObjectName("PrimaryButton")
        self.mitschrift_laden_button.clicked.connect(self._mitschrift_laden)
        knoepfe.addWidget(self.mitschrift_laden_button)
        self.mitschrift_weiter_button = QPushButton("Weiter", seite)
        self.mitschrift_weiter_button.setVisible(False)
        self.mitschrift_weiter_button.clicked.connect(lambda: self._gehe_zu(self.S_FERTIG))
        knoepfe.addWidget(self.mitschrift_weiter_button)
        layout.addLayout(knoepfe)
        return seite

    def _mitschrift_vorbereiten(self) -> None:
        gespeichert = app_config.load_config()["whisper_modell"] or model_service.WHISPER_MODEL_NAME
        index = self.whisper_wahl.findData(gespeichert)
        self.whisper_wahl.setCurrentIndex(max(index, 0))
        self._sprecher_geaendert()

    def _sprecher_geaendert(self, *_args) -> None:
        vorhanden = hf_env.has_hf_token()
        self.token_vorhanden_label.setVisible(self.sprecher_checkbox.isChecked() and vorhanden)
        self.token_bereich.setVisible(self.sprecher_checkbox.isChecked() and not vorhanden)

    def _mitschrift_laden(self) -> None:
        if self._mitschrift is not None and self._mitschrift.isRunning():
            return
        modell = self.whisper_wahl.currentData()
        app_config.update_config(whisper_modell=modell)
        sprecher = self.sprecher_checkbox.isChecked()
        token = self.token_edit.text().strip() or None
        self.mitschrift_log.clear()
        if sprecher and token and self.token_merken.isChecked():
            try:
                secret_store.save_api_key(hf_env.SCHLUESSEL_NAME, token)
                self.mitschrift_log.appendPlainText("Zugang zu Hugging Face gemerkt.")
            except secret_store.SecretStoreUnavailableError as fehler:
                self.mitschrift_log.appendPlainText(f"{fehler} Er gilt deshalb nur für diese Sitzung.")
        self.mitschrift_laden_button.setEnabled(False)
        self.mitschrift_fortschritt.setVisible(True)
        self.mitschrift_fortschritt.setRange(0, 0)
        self._mitschrift = MitschriftWorker(modell, token, sprecher and (token is not None or hf_env.has_hf_token()), self)
        self._mitschrift.log_line.connect(self.mitschrift_log.appendPlainText)
        self._mitschrift.fertig.connect(self.mitschrift_fertig)
        self._mitschrift.start()

    def mitschrift_fertig(self, ergebnis: dict) -> None:
        self.ergebnisse.update(ergebnis)
        self.mitschrift_fortschritt.setRange(0, 1)
        self.mitschrift_fortschritt.setValue(1)
        self.mitschrift_laden_button.setEnabled(True)
        self.mitschrift_laden_button.setText("Erneut versuchen" if not all(ergebnis.values()) else "Herunterladen")
        self.mitschrift_weiter_button.setVisible(True)
        self.mitschrift_weiter_button.setObjectName("PrimaryButton")
        # Die Rechenumgebung steht jetzt -- ein weiterer Neustart ist nicht noetig.
        app_config.update_config(einrichtung_fortsetzen="")

    # ------------------------------------------------------------------
    # 7. Fertig
    # ------------------------------------------------------------------
    def _baue_fertig(self) -> QWidget:
        seite = QWidget(self)
        seite.setObjectName("WizardPage")
        layout = QVBoxLayout(seite)
        layout.addWidget(_ueberschrift("Fertig", seite))
        self.fertig_label = _text("", seite)
        layout.addWidget(self.fertig_label)
        layout.addStretch(1)
        knoepfe = QHBoxLayout()
        self.anbieter_button = QPushButton("Anbieter und Schlüssel jetzt eintragen …", seite)
        self.anbieter_button.clicked.connect(self._anbieter_eintragen)
        knoepfe.addWidget(self.anbieter_button)
        knoepfe.addStretch(1)
        self.loslegen_button = QPushButton("Loslegen", seite)
        self.loslegen_button.setObjectName("PrimaryButton")
        self.loslegen_button.clicked.connect(self._abschliessen)
        knoepfe.addWidget(self.loslegen_button)
        layout.addLayout(knoepfe)
        return seite

    def _zeige_fertig(self) -> None:
        konfig = app_config.load_config()
        online = [
            name
            for schluessel, name in (
                ("transkription_modus", "Mitschrift"),
                ("nachbearbeitung_modus", "Protokoll"),
                ("chatbot_modus", "Frag mein Meeting"),
            )
            if konfig[schluessel] == "api"
        ]
        fehlt = sorted(k.removeprefix("modell:") for k, ok in self.ergebnisse.items() if not ok)
        teile = ["<p>Der Protokoll-Assistent ist eingerichtet.</p>"]
        if fehlt:
            teile.append(
                "<p>Noch nicht geklappt hat: " + ", ".join(fehlt) + ". Das lässt sich jederzeit über "
                "Einstellungen → Systemdiagnose nachholen.</p>"
            )
        if online:
            teile.append(
                "<p>Online laufen soll: " + ", ".join(online) + ". Dafür fehlen noch Anbieter und "
                "Zugangsschlüssel – am besten gleich eintragen.</p>"
            )
        teile.append("<p>Zum Start: oben eine Aufnahme wählen oder direkt aufnehmen.</p>")
        self.fertig_label.setText("".join(teile))
        self.anbieter_button.setVisible(bool(online))

    def _abschliessen(self) -> None:
        app_config.update_config(
            einrichtung_abgeschlossen=True,
            einrichtung_version=app_config.EINRICHTUNG_VERSION,
            einrichtung_fortsetzen="",
            lokale_einrichtung_zurueckgestellt=False,
        )
        self.accept()

    def _ueberspringen(self) -> None:
        """Keine lokale Einrichtung: Es wird nichts geladen, alle drei Arbeitsschritte
        laufen ueber einen Online-Dienst. Anbieter und Schluessel traegt der
        Anwender gleich danach in den Einstellungen ein; bis dahin weist das
        Hauptfenster bei jedem Start eines Schritts darauf hin, was fehlt."""
        app_config.update_config(
            transkription_modus="api",
            nachbearbeitung_modus="api",
            chatbot_modus="api",
            einrichtung_abgeschlossen=True,
            einrichtung_version=app_config.EINRICHTUNG_VERSION,
            einrichtung_fortsetzen="",
            # Ohne Zustimmung nie ungefragt die Rechenumgebung laden -- auch dann nicht,
            # wenn jemand spaeter wieder auf "Lokal" stellt: dann greift die Einrichtung
            # ueber Einstellungen -> Transkription -> Lokal -> "Einrichtung starten".
            lokale_einrichtung_zurueckgestellt=not laufzeit_vorhanden(),
        )
        self.accept()
        oeffnen = getattr(self.parent(), "_open_settings", None)
        if callable(oeffnen):
            oeffnen()

    def _anbieter_eintragen(self) -> None:
        """Die Einstellungen des Hauptfensters oeffnen (dort werden die
        Schluessel fuer die Sitzung uebernommen)."""
        self._abschliessen()
        oeffnen = getattr(self.parent(), "_open_settings", None)
        if callable(oeffnen):
            oeffnen()
