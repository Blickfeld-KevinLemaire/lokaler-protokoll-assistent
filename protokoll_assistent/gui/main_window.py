"""Hauptfenster des Protokoll-Assistenten (PySide6).

Eine Oberflaeche fuer beide Wege: Datei/Aufnahme auswaehlen (Gruppe 1/2,
loest noch nichts aus), dann getrennt Transkription starten (Gruppe 5,
lokal ODER API-Schnittstelle - Umschalter direkt hier), dann getrennt
Nachbearbeitung eines - auch eines anderen, ausgewaehlten - Transkripts
(Gruppe 7, ebenfalls lokal ODER API umschaltbar, mit Systemprompt-Vorlage
oder freiem Text). Die strukturellen Entscheidungen (welcher Endpunkt,
welcher Schluessel, welches lokale Modell) werden einmalig in den
Einstellungen getroffen (``gui.settings_dialog.SettingsDialog``); der
Umschalter hier im Hauptfenster spiegelt nur, welcher der beiden Wege fuer
den naechsten Lauf gilt.

Die komplette Ablaufsteuerung (Chunk-Planung, Fortsetzbarkeit,
Zusammenfuehrung, Export, mehrstufige Protokollauswertung) ist
``services.pipeline_service``. Ob ein Chunk lokal oder ueber eine API
transkribiert wird, ist dort nur eine austauschbare Funktion
(``transcribe_chunk_fn``/``diarize_fn``/``protocol_generate_fn``) - diese
Datei waehlt lediglich, welche Funktion(en) das sind.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, ClassVar

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Verarbeitungskette und Hilfsmodule der Anwendung.
from protokoll_assistent.gui import branding
from protokoll_assistent.gui.chat_page import ChatPage
from protokoll_assistent.gui.dialogs import (
    AudioquelleDialog,
    EndverarbeitungDialog,
    SprecherprofileDialog,
    show_error,
)
from protokoll_assistent.gui.dokument_qt import SCHREIBER as QT_SCHREIBER
from protokoll_assistent.gui.export_dialog import ExportDialog
from protokoll_assistent.gui.geraete_empfang import EmpfangsSteuerung
from protokoll_assistent.gui.settings_dialog import DATENSCHUTZ_HINWEIS_API, SettingsDialog
from protokoll_assistent.gui.strings import PRIVACY_NOTICE
from protokoll_assistent.gui.worker import (
    DateiHashWorker,
    ProtocolGenerateFn,
    ProtocolWorker,
    TranscriptionWorker,
)
from protokoll_assistent.services import (
    api_anbieter,
    api_protocol_service,
    api_transcription_service,
    chat_service,
    chunking_service,
    dokument_export_service,
    export_service,
    frage_service,
    geraete_fragen,
    live_auswertung_service,
    live_service,
    manifest_service,
    model_service,
    ollama_service,
    pipeline_service,
    secret_store,
    sprecher_export_service,
    sprecherprofil_service,
)
from protokoll_assistent.utils import app_config
from protokoll_assistent.utils.paths import (
    get_chatverlaeufe_dir,
    get_default_output_dir,
    get_recordings_dir,
    get_system_prompt_file,
    get_work_dir,
)
from protokoll_assistent.utils.systemprompt_vorlagen import alle_vorlagen, vorlage_speichern
from protokoll_assistent.utils.timeformat import format_duration_human

if TYPE_CHECKING:  # pragma: no cover - nur fuer die Typpruefung
    from protokoll_assistent.services import recording_service


def lade_recording_service() -> ModuleType:
    """Laedt 'services.recording_service' erst bei Bedarf.

    Das Modul importiert 'sounddevice' auf Modulebene. Im lokalen Modus
    laeuft diese Anwendung aber in der von 'bootstrap.py' verwalteten
    Laufzeitumgebung, und deren 'requirements-laufzeit.txt' enthaelt
    'sounddevice' nicht. Ein Import auf Modulebene wuerde dort schon das
    Oeffnen des Hauptfensters verhindern -- wegen einer Zusatzfunktion
    (Mikrofonaufnahme), ohne die der Rest der Anwendung vollstaendig
    arbeitet. Der 'ImportError' landet stattdessen dort, wo er behandelt
    wird ('_populate_recording_devices' schaltet die Aufnahme dann ab und
    sagt, warum)."""
    from protokoll_assistent.services import recording_service as modul

    return modul


def api_auswertung_funktion(endpunkt: str, modell: str, api_key: str) -> Callable[[str, str], str]:
    """Die Anfrage an ein API-Modell fuer die Auswertung -- ``(Prompt, Systemprompt) -> Antwort``.

    Uebersetzt 'ApiProtocolError' in 'OllamaError': 'pipeline_service.run_protocol' behandelt einen
    fehlgeschlagenen Protokolllauf gnaedig -- aber nur fuer '(ProtocolValidationError,
    ollama_service.OllamaError)': dann wird der Fehler als 'protokoll_fehler' gemeldet, der Bericht trotzdem
    geschrieben und das fertige Transkript bleibt erhalten. Ein durchgereichter 'ApiProtocolError' (HTTP 401,
    Endpunkt nicht erreichbar, Zeitlimit) faellt stattdessen bis in den Worker und landet dort als
    nichtssagender "Unerwarteter Fehler"."""

    def anfrage(prompt: str, system: str) -> str:
        try:
            return api_protocol_service.generate_text(
                prompt, system, model=modell, endpoint_url=endpunkt, api_key=api_key
            )
        except api_protocol_service.ApiProtocolError as fehler:
            raise ollama_service.OllamaError(str(fehler)) from fehler

    return anfrage


def ermittle_whisper_modell(konfiguration: dict[str, Any]) -> str:
    """Welches Whisper-Modell gilt fuer den lokalen Modus?

    Die Einstellung stammt aus **einer** Konfiguration -- gesetzt entweder im
    Einstellungsdialog oder vom Einrichtungsassistenten
    ('gui.wizard.SetupWizard'), der genau das Modell speichert, das er auch
    heruntergeladen hat. Ist nichts hinterlegt, gilt der eingebaute Standard.

    (Solange Oberflaeche und Assistent zu getrennten Anwendungen mit je
    eigener 'konfiguration.json' gehoerten, schrieb der Assistent in die eine
    und die Oberflaeche las aus der anderen -- direkt nach der
    Ersteinrichtung galt deshalb ein anderes Modell als das eingerichtete.
    Mit einer einzigen Konfiguration kann das nicht mehr passieren.)
    """
    gewaehlt = konfiguration.get("whisper_modell")
    if gewaehlt:
        return str(gewaehlt)
    return model_service.WHISPER_MODEL_NAME


# So lange wartet die automatische Auswertung hoechstens auf eine noch laufende Teilauswertung der Aufnahme
# (eine Anfrage ans Sprachmodell dauert Sekunden bis wenige Minuten).
VORAB_AUSWERTUNG_WARTEN = 300.0

SUPPORTED_EXTENSION_NAMES = [
    "mp3", "mp4", "m4a", "wav", "aac", "flac", "ogg", "opus", "mov", "mkv", "webm",
]
SUPPORTED_EXTENSIONS = " ".join(f"*.{name}" for name in SUPPORTED_EXTENSION_NAMES)
SUPPORTED_SUFFIXES = {f".{name}" for name in SUPPORTED_EXTENSION_NAMES}


class MainWindow(QMainWindow):
    # Neues Live-Transkript einer Geraeteaufnahme (aus dem Arbeitsfaden der Live-Transkription, von Qt in den
    # Oberflaechenfaden gestellt): Geraet, Datei des Geraets, Text bisher, sicher transkribiert bis (Sekunden)
    live_transkript_geaendert = Signal(str, str, str, float)

    def __init__(self, initial_folder: Path | None = None, initial_file: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Protokoll-Assistent")
        # Programmsymbol fuer dieses Fenster und alle Dialoge der Anwendung.
        symbol = branding.app_icon()
        self.setWindowIcon(symbol)
        QApplication.setWindowIcon(symbol)
        self.resize(1420, 900)
        self.setAcceptDrops(True)

        config = app_config.load_config()
        self._input_folder: Path | None = initial_folder
        if self._input_folder is None and config.get("eingabeordner"):
            candidate = Path(config["eingabeordner"])
            if candidate.is_dir():
                self._input_folder = candidate

        self._source_path: Path | None = None
        if self._input_folder is not None and initial_file:
            candidate_file = self._input_folder / initial_file
            if candidate_file.is_file():
                self._source_path = candidate_file

        if config.get("ausgabeordner") and Path(config["ausgabeordner"]).parent.exists():
            self._output_dir: Path = Path(config["ausgabeordner"])
        else:
            self._output_dir = get_default_output_dir()

        self._transcription_worker: TranscriptionWorker | None = None
        self._protocol_worker: ProtocolWorker | None = None
        self._start_time: float | None = None
        self._chunk_progress = (0, 0)
        self._last_transcription_result: pipeline_service.TranscriptionResult | None = None
        self._speaker_embeddings: dict[str, list[float]] = {}
        # Gesetzt, wenn im Dialog 'Verarbeitung waehlen' das Protokoll direkt im
        # Anschluss verlangt wurde.
        self._protokoll_nach_transkription = False
        # Automatische Verarbeitung einer Geraeteaufnahme: (Geraet, Dateiname des Geraets, Datei).
        # Dazu der Auftrag fuer diesen Lauf (statt des Textes im Editor) und die Warteschlange.
        self._automatik: tuple[str, str, Path] | None = None
        self._automatik_phase = ""
        self._systemprompt_automatik: str | None = None
        self._geraete_warteschlange: list[tuple[Path, str, str]] = []
        # Aufnahmen mit fertigem Transkript, deren Zusammenfassung das Geraet noch freigeben muss:
        # (Geraet, Datei) -> (Aufnahme, Transkript-JSON, Text des Auftrags)
        self._freigaben: dict[tuple[str, str], tuple[Path, Path, str]] = {}
        self._freigabe_warteschlange: list[tuple[str, str]] = []
        # Aufnahmen, nach denen das Geraet nicht mehr fragt (es ist weitergezogen): Ihre Zusammenfassung kommt nach
        # den neuen Aufnahmen dran, wenn die Grafikkarte sie neben der naechsten Aufnahme verkraftet.
        self._nachhol_warteschlange: list[tuple[str, str]] = []
        # Unterlagen zu Geraeteaufnahmen, nach denen per Sprache gefragt werden kann:
        # (Geraet, Datei) -> {"transkript": JSON, "zusammenfassung": Text}
        self._ergebnisse: dict[tuple[str, str], dict[str, Path]] = {}
        self._frage_transkribierer: Any = None
        self._frage_sperre = threading.Lock()
        self._automatik_rueckfrage = False
        self._last_protocol_result: pipeline_service.ProtocolResult | None = None
        self._selected_transcript_path: Path | None = None
        # Das Transkript, aus dem die laufende bzw. letzte Nachbearbeitung
        # entsteht. 'ProtocolResult' traegt es nicht, und die Auswahl unter
        # "Transkript auswählen" kann sich inzwischen geaendert haben.
        self._nachbearbeitung_transkript: Path | None = None
        self._nachbearbeitung_laeuft = False
        self._hash_worker: DateiHashWorker | None = None
        self._hash_zwischenspeicher: dict[tuple[str, int, int], str] = {}
        # Eingegebene, aber nicht dauerhaft gemerkte API-Schluessel bleiben
        # fuer den Rest dieser Sitzung nutzbar (siehe
        # 'gui.settings_dialog.SettingsDialog.eingegebene_schluessel').
        self._session_api_keys: dict[str, str] = {}

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)

        self._recording_devices: list[recording_service.Aufnahmegeraet] = []
        self._recording: recording_service.MikrofonAufnahme | None = None
        self._recording_timer = QTimer(self)
        self._recording_timer.setInterval(100)
        self._recording_timer.timeout.connect(self._update_recording_display)

        self._build_ui()
        self._refresh_hardware_label()

        # Empfang fuer die WLAN-Aufnahmegeraete -- aus, bis er in den
        # Einstellungen eingeschaltet wird (siehe 'gui/geraete_empfang.py').
        self._empfang_zuletzt = ""
        self._geraete_status = live_service.StatusRegister()
        self._wuensche = live_service.WunschRegister()
        # Die Live-Transkription rechnet auf dem Prozessor und liest ihre Einstellungen aus
        # dem Arbeitsfaden heraus -- deshalb kein Zugriff auf Widgets, sondern dieser Merker.
        self._live_einstellungen: tuple[str, str | None, bool] = self._live_einstellungen_lesen()
        # Teilauswertung waehrend der Aufnahme (Sprachmodell auf der Grafikkarte, neben Whisper auf dem Prozessor);
        # sie liest ihre Einstellungen ebenfalls aus einem Merker, den die Oberflaeche pflegt.
        self._live_auswertung_stand: live_auswertung_service.AuswertungsEinstellungen | None = (
            self._live_auswertung_lesen()
        )
        self._live = live_service.LiveTranskription(
            get_work_dir(),
            self._live_transkribierer,
            status=self._geraete_status,
            bei_aenderung=self.live_transkript_geaendert.emit,
            auswertung=live_auswertung_service.LiveAuswertung(lambda: self._live_auswertung_stand),
            auftrag_fn=self._auftrag_des_geraets,
        )
        self.live_transkript_geaendert.connect(self._live_transkript_anzeigen)
        self._fragen = frage_service.FragenDienst(
            erkennen=self._frage_erkennen,
            antworten=self._frage_beantworten,
            anzeige=geraete_fragen.fuer_display,
            # Die Sprachausgabe (lokale Sprachsynthese) folgt, sobald die Engine feststeht; bis dahin
            # endet eine Frage mit der Antwort als Text.
            sprechen=None,
            bereit=self._frage_bereit,
        )
        self._geraete_empfang = EmpfangsSteuerung(
            self, live=self._live, status=self._geraete_status, wuensche=self._wuensche, fragen=self._fragen
        )
        self._geraete_empfang.zusammenfassung_gewuenscht.connect(self._zusammenfassung_gewuenscht)
        self._geraete_empfang.zusammenfassung_abgelehnt.connect(self._zusammenfassung_abgelehnt)
        self._geraete_empfang.geraet_weitergezogen.connect(self._geraet_weitergezogen)
        self._geraete_empfang.neue_aufnahme.connect(self._neue_geraete_aufnahme)
        self._geraete_empfang.aufnahme_bereit.connect(self._geraete_aufnahme_bereit)
        self._geraete_empfang_anwenden()

        if self._source_path is not None:
            self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
            self._select_file_in_list(self._source_path.name)
            self._refresh_resume_status()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    # Seiten der Navigation: (Titel, Untertitel). Die Reihenfolge entspricht den
    # Seiten im 'QStackedWidget' aus '_build_ui'.
    SEITEN: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Transkription", "Aufnahme oder Datei auswählen und in Text umwandeln."),
        ("Ergebnis und Sprecher", "Vorschau ansehen, Sprecher benennen, Stimmen anhören."),
        (
            "Nachbearbeitung",
            "Aus einem vorhandenen Transkript ein Protokoll erstellen, ansehen und bei Bedarf überarbeiten.",
        ),
        ("Frag mein Meeting", "Fragen an die ausgewählten Transkripte und Zusammenfassungen stellen."),
    )
    (SEITE_TRANSKRIPTION, SEITE_ERGEBNIS, SEITE_NACHBEARBEITUNG, SEITE_CHAT) = range(4)

    def _build_ui(self) -> None:
        """Seitenleiste mit Navigation links, rechts die gewaehlte Seite und
        darunter immer sichtbar der Fortschritt. Die Gruppen selbst
        ('_build_*_group') sind unveraendert; sie werden hier nur auf Seiten
        verteilt."""
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        content = QWidget(self)
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 22, 28, 18)
        content_layout.setSpacing(12)
        root_layout.addWidget(content, stretch=1)

        self.page_title_label = QLabel("", self)
        self.page_title_label.setObjectName("PageTitle")
        self.page_subtitle_label = QLabel("", self)
        self.page_subtitle_label.setObjectName("PageSubtitle")
        content_layout.addWidget(self.page_title_label)
        content_layout.addWidget(self.page_subtitle_label)

        privacy_label = QLabel(PRIVACY_NOTICE, self)
        privacy_label.setObjectName("PrivacyBanner")
        privacy_label.setWordWrap(True)
        content_layout.addWidget(privacy_label)

        self.page_stack = QStackedWidget(self)
        content_layout.addWidget(self.page_stack, stretch=1)

        # Zwei Spalten, damit nichts gescrollt werden muss: links die Quelle
        # (Aufnahme oder Datei), rechts die Einstellungen und der Start.
        self.page_stack.addWidget(
            self._two_column_page(
                [self._build_recording_group(), self._build_file_group()],
                [self._build_settings_group(), self._build_resume_group(), self._build_control_group()],
            )
        )
        ergebnis_seite = QSplitter(Qt.Vertical, self)
        ergebnis_seite.addWidget(self._build_preview_group())
        ergebnis_seite.addWidget(self._build_speaker_group())
        ergebnis_seite.setSizes([300, 300])
        self.page_stack.addWidget(ergebnis_seite)
        self.page_stack.addWidget(
            self._scroll_page(
                [
                    self._build_transcript_selection_group(),
                    self._build_protocol_control_group(),
                    self._build_protocol_result_group(),
                ]
            )
        )

        # Chatbot "Frag mein Meeting": Fragen an Transkripte und Zusammenfassungen.
        self.chat_page = ChatPage(
            lambda: self._output_dir,
            lambda: get_work_dir() / "chat_index",
            self._chat_api_schluessel,
            get_chatverlaeufe_dir,
        )
        self.page_stack.addWidget(self.chat_page)

        # Der Fortschritt steht unter jeder Seite, damit nach "Starten" sofort
        # zu sehen ist, dass etwas passiert - egal, welche Seite offen ist.
        content_layout.addWidget(self._build_progress_group())

        self._show_page(0)

    def _build_sidebar(self) -> QFrame:
        leiste = QFrame(self)
        leiste.setObjectName("Sidebar")
        leiste.setFixedWidth(250)
        layout = QVBoxLayout(leiste)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(6)

        # Das grosse Logo (Fassung fuer dunklen Grund) oben in der Seitenleiste;
        # fehlt die Datei, steht der Name als Text da.
        self.brand_label = QLabel(self)
        logo = branding.logo_pixmap(210, hell=True, geraetepixelverhaeltnis=self.devicePixelRatioF())
        if logo is not None:
            self.brand_label.setPixmap(logo)
            self.brand_label.setAccessibleName("VERMERK")
        else:
            self.brand_label.setText("Protokoll-Assistent")
            self.brand_label.setObjectName("BrandTitle")
        layout.addWidget(self.brand_label)
        untermarke = QLabel("Protokoll-Assistent", self)
        untermarke.setObjectName("BrandSubtitle")
        layout.addWidget(untermarke)
        layout.addSpacing(14)

        self.new_transcription_button = QPushButton("+  Neue Transkription", self)
        self.new_transcription_button.setObjectName("PrimaryButton")
        self.new_transcription_button.setToolTip("Audioquelle wählen: Mikrofon oder Mediendatei.")
        self.new_transcription_button.clicked.connect(self._new_transcription)
        layout.addWidget(self.new_transcription_button)
        layout.addSpacing(10)

        self._nav_gruppe = QButtonGroup(self)
        self._nav_gruppe.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        symbole = ("🎙", "👥", "📝", "💬")
        for index, ((titel, _), symbol) in enumerate(zip(self.SEITEN, symbole, strict=True)):
            knopf = QPushButton(f"{symbol}   {titel}", self)
            knopf.setObjectName("NavButton")
            knopf.setCheckable(True)
            knopf.clicked.connect(functools.partial(self._show_page, index))
            self._nav_gruppe.addButton(knopf, index)
            self.nav_buttons.append(knopf)
            layout.addWidget(knopf)

        layout.addStretch(1)

        self.open_output_button = QPushButton("📂   Ausgabeordner öffnen", self)
        self.open_output_button.setObjectName("NavButton")
        self.open_output_button.clicked.connect(self._open_output_folder)
        layout.addWidget(self.open_output_button)

        self.settings_button = QPushButton("⚙   Einstellungen", self)
        self.settings_button.setObjectName("NavButton")
        self.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(self.settings_button)
        return leiste

    @staticmethod
    def _two_column_page(links: list[QGroupBox], rechts: list[QGroupBox]) -> QScrollArea:
        """Seite mit zwei gleich breiten Spalten. Die Bildlaufleiste erscheint nur,
        wenn das Fenster dafuer zu klein ist."""
        inhalt = QWidget()
        inhalt.setObjectName("PageContent")
        zeile = QHBoxLayout(inhalt)
        zeile.setContentsMargins(0, 0, 8, 0)
        zeile.setSpacing(16)
        for gruppen, dehnen in ((links, links[-1]), (rechts, None)):
            spalte = QVBoxLayout()
            spalte.setSpacing(12)
            for gruppe in gruppen:
                spalte.addWidget(gruppe, stretch=1 if gruppe is dehnen else 0)
            if dehnen is None:
                spalte.addStretch(1)
            zeile.addLayout(spalte, stretch=1)
        scroll = QScrollArea()
        scroll.setWidget(inhalt)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

    @staticmethod
    def _scroll_page(gruppen: list[QGroupBox]) -> QScrollArea:
        inhalt = QWidget()
        inhalt.setObjectName("PageContent")
        layout = QVBoxLayout(inhalt)
        layout.setContentsMargins(0, 0, 8, 0)
        for gruppe in gruppen:
            layout.addWidget(gruppe)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inhalt)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

    def _show_page(self, index: int, _checked: bool = False) -> None:
        self.page_stack.setCurrentIndex(index)
        titel, untertitel = self.SEITEN[index]
        self.page_title_label.setText(titel)
        self.page_subtitle_label.setText(untertitel)
        self.nav_buttons[index].setChecked(True)
        if self.SEITEN[index][0] == "Frag mein Meeting":
            self.chat_page.aktualisieren()

    def _open_output_folder(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._session_api_keys.update(dialog.eingegebene_schluessel)
            self._apply_modus_from_config()
            self.chat_page.einstellungen_aktualisiert()
            self._geraete_empfang_anwenden()

    def _apply_modus_from_config(self) -> None:
        config = app_config.load_config()
        if config["transkription_modus"] == "api":
            self.transkription_api_radio.setChecked(True)
        else:
            self.transkription_lokal_radio.setChecked(True)
        if config["nachbearbeitung_modus"] == "api":
            self.nachbearbeitung_api_radio.setChecked(True)
        else:
            self.nachbearbeitung_lokal_radio.setChecked(True)

    # ------------------------------------------------------------------
    # Gruppe 1: Aufnahmegeraet (Voice Recording) - unveraendert gegenueber
    # der lokalen Variante, das erzeugte WAV landet ueber '_set_source_file'
    # im selben Auswahlmechanismus wie eine per Hand gewaehlte Datei.
    # ------------------------------------------------------------------
    def _build_recording_group(self) -> QGroupBox:
        group = QGroupBox("Aufnahme", self)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        device_row = QHBoxLayout()
        self.recording_device_combo = QComboBox(self)
        self.recording_device_combo.currentIndexChanged.connect(self._on_recording_device_changed)
        device_row.addWidget(self.recording_device_combo, stretch=1)
        # Beschriftet statt nur mit einem Symbol: Ein Zeichen in einem
        # schmalen Knopf wurde mit dem Innenabstand des Themes zu einem Punkt
        # abgeschnitten.
        self.recording_refresh_button = QPushButton("Neu einlesen", self)
        self.recording_refresh_button.setToolTip("Aufnahmegeräte neu einlesen (z. B. nach dem Anstecken eines Headsets).")
        self.recording_refresh_button.clicked.connect(self._refresh_recording_devices)
        device_row.addWidget(self.recording_refresh_button)
        layout.addLayout(device_row)

        # Der Hinweis (warum kein Geraet gefunden wurde o. ae.) ist meist leer und
        # nimmt dann keinen Platz ein.
        self.recording_hint_label = QLabel("", self)
        self.recording_hint_label.setWordWrap(True)
        self.recording_hint_label.setObjectName("RecordingHint")
        self.recording_hint_label.setVisible(False)
        layout.addWidget(self.recording_hint_label)

        # Knoepfe, Status und Dauer in einer Zeile, darunter der schmale Pegel.
        button_row = QHBoxLayout()
        self.recording_start_button = QPushButton("Aufnahme starten", self)
        self.recording_start_button.clicked.connect(self._start_recording)
        button_row.addWidget(self.recording_start_button)
        self.recording_pause_button = QPushButton("Pause", self)
        self.recording_pause_button.clicked.connect(self._toggle_recording_pause)
        self.recording_pause_button.hide()
        button_row.addWidget(self.recording_pause_button)
        self.recording_stop_button = QPushButton("Aufnahme beenden", self)
        self.recording_stop_button.setObjectName("DangerButton")
        self.recording_stop_button.clicked.connect(self._stop_recording)
        self.recording_stop_button.hide()
        button_row.addWidget(self.recording_stop_button)
        self.recording_status_label = QLabel("", self)
        button_row.addWidget(self.recording_status_label)
        self.recording_duration_label = QLabel("", self)
        button_row.addWidget(self.recording_duration_label)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.recording_level_bar = QProgressBar(self)
        self.recording_level_bar.setRange(0, 100)
        self.recording_level_bar.setTextVisible(False)
        self.recording_level_bar.setFixedHeight(10)
        layout.addWidget(self.recording_level_bar)

        self._populate_recording_devices()
        return group

    def _set_recording_hint(self, text: str) -> None:
        self.recording_hint_label.setText(text)
        self.recording_hint_label.setVisible(bool(text))

    def _show_no_recording_device(self) -> None:
        """Statt eines leeren Auswahlfelds (dessen Pfeil nichts oeffnet und
        keine Erklaerung bietet) steht ein deaktivierter Platzhalter in der
        Liste; der Grund steht darunter im Hinweis."""
        combo = self.recording_device_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Kein Aufnahmegerät verfügbar")
        eintrag = combo.model().item(0)
        if eintrag is not None:
            eintrag.setEnabled(False)
        combo.blockSignals(False)

    def _refresh_recording_devices(self) -> None:
        if self._recording is not None:
            return
        self._populate_recording_devices()

    def _populate_recording_devices(self) -> None:
        try:
            aufnahme_modul = lade_recording_service()
            self._recording_devices = aufnahme_modul.liste_aufnahmegeraete()
        except ImportError as error:
            self._recording_devices = []
            self._show_no_recording_device()
            self._set_recording_hint(
                "Die Mikrofonaufnahme steht in dieser Laufzeitumgebung nicht zur "
                f"Verfügung ({error}). Alles andere funktioniert unverändert; eine "
                "bereits vorhandene Aufnahme kann wie jede andere Datei ausgewählt werden."
            )
            self.recording_start_button.setEnabled(False)
            return
        except Exception as error:  # PortAudio-Fehler in ungewoehnlicher Umgebung
            self._recording_devices = []
            self._show_no_recording_device()
            self._set_recording_hint(f"Aufnahmegeräte konnten nicht ermittelt werden: {error}")
            self.recording_start_button.setEnabled(False)
            return

        if not self._recording_devices:
            self._show_no_recording_device()
            self._set_recording_hint(
                "Keine Audioeingabegeräte gefunden. Gerät anstecken und auf „Neu einlesen“ klicken; "
                "in den Windows-Datenschutzeinstellungen muss der Mikrofonzugriff für "
                "Desktop-Apps erlaubt sein."
            )
            self.recording_start_button.setEnabled(False)
            return

        config = app_config.load_config()
        saved = config.get("aufnahmegeraet")
        standard_index = aufnahme_modul.standard_eingabe_index()
        device, hint = aufnahme_modul.waehle_startgeraet(
            self._recording_devices, saved, standard_index
        )

        self.recording_device_combo.blockSignals(True)
        self.recording_device_combo.clear()
        for eintrag in self._recording_devices:
            self.recording_device_combo.addItem(eintrag.anzeigename)
        if device is not None:
            index = self.recording_device_combo.findText(device.anzeigename)
            if index >= 0:
                self.recording_device_combo.setCurrentIndex(index)
        self.recording_device_combo.blockSignals(False)

        self._set_recording_hint(hint or "")
        self.recording_start_button.setEnabled(True)

    def _on_recording_device_changed(self, _index: int) -> None:
        anzeigename = self.recording_device_combo.currentText()
        if anzeigename:
            app_config.update_config(aufnahmegeraet=anzeigename)
            self._set_recording_hint("")

    def _start_recording(self) -> None:
        anzeigename = self.recording_device_combo.currentText()
        geraet = next((g for g in self._recording_devices if g.anzeigename == anzeigename), None)
        if geraet is None:
            show_error(self, "Kein Gerät ausgewählt", "Bitte zuerst ein Aufnahmegerät auswählen.")
            return

        try:
            aufnahme_modul = lade_recording_service()
            zielpfad = get_recordings_dir() / aufnahme_modul.erzeuge_dateiname()
            aufnahme = aufnahme_modul.MikrofonAufnahme(geraet, zielpfad)
            aufnahme.start()
        except Exception as error:
            show_error(
                self,
                "Aufnahme konnte nicht gestartet werden",
                f"Das Gerät '{geraet.anzeigename}' konnte nicht geöffnet werden:\n{error}",
            )
            return
        self._recording = aufnahme

        self.recording_device_combo.setEnabled(False)
        self.recording_start_button.hide()
        self.recording_pause_button.setText("Pause")
        self.recording_pause_button.show()
        self.recording_stop_button.show()
        self.recording_status_label.setText("🔴 Aufnahme läuft")
        self._recording_timer.start()

    def _toggle_recording_pause(self) -> None:
        if self._recording is None:
            return
        if self._recording.ist_pausiert:
            self._recording.fortsetzen()
            self.recording_pause_button.setText("Pause")
            self.recording_status_label.setText("🔴 Aufnahme läuft")
        else:
            self._recording.pause()
            self.recording_pause_button.setText("Fortsetzen")
            self.recording_status_label.setText("⏸ Aufnahme pausiert")

    def _update_recording_display(self) -> None:
        if self._recording is None:
            self._recording_timer.stop()
            return
        duration = int(self._recording.dauer_sekunden)
        self.recording_duration_label.setText(f"{duration // 60:02d}:{duration % 60:02d}")
        self.recording_level_bar.setValue(int(self._recording.pegel * 100))

    def _stop_recording(self) -> None:
        if self._recording is None:
            return
        path = self._recording.stop()
        self._recording = None
        self._recording_timer.stop()

        self.recording_device_combo.setEnabled(True)
        self.recording_pause_button.hide()
        self.recording_stop_button.hide()
        self.recording_start_button.show()
        self.recording_status_label.setText("")
        self.recording_duration_label.setText("")
        self.recording_level_bar.setValue(0)

        self._set_source_file(path)

    # ------------------------------------------------------------------
    # Gruppe 2: Eingabeordner und Datei
    # ------------------------------------------------------------------
    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("Datei", self)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        folder_row = QHBoxLayout()
        folder_text = str(self._input_folder) if self._input_folder else "Kein Eingabeordner ausgewählt"
        self.folder_label = QLabel(folder_text, self)
        self.folder_label.setWordWrap(True)
        choose_folder_button = QPushButton("Ordner wechseln …", self)
        choose_folder_button.clicked.connect(self._choose_input_folder)
        folder_row.addWidget(choose_folder_button)
        folder_row.addWidget(self.folder_label, stretch=1)
        layout.addLayout(folder_row)

        # Zustand des Empfangs fuer die Aufnahmegeraete; unsichtbar, solange er aus ist.
        self.empfang_label = QLabel("", self)
        self.empfang_label.setWordWrap(True)
        self.empfang_label.setVisible(False)
        layout.addWidget(self.empfang_label)

        # Die Liste nimmt den uebrigen Platz der Spalte ein, statt eine feste
        # Hoehe zu haben.
        self.file_list = QListWidget(self)
        self.file_list.setMinimumHeight(90)
        self.file_list.itemSelectionChanged.connect(self._on_file_list_selection_changed)
        layout.addWidget(self.file_list, stretch=1)
        if self._input_folder is not None:
            self._populate_file_list(self._input_folder)

        other_file_row = QHBoxLayout()
        choose_file_button = QPushButton("Andere Datei wählen …", self)
        choose_file_button.clicked.connect(self._choose_file)
        other_file_row.addWidget(choose_file_button)
        self.file_label = QLabel("Keine Datei ausgewählt", self)
        self.file_label.setWordWrap(True)
        other_file_row.addWidget(self.file_label, stretch=1)
        layout.addLayout(other_file_row)

        output_row = QHBoxLayout()
        self.output_label = QLabel(str(self._output_dir), self)
        self.output_label.setWordWrap(True)
        choose_output_button = QPushButton("Ausgabeordner wählen …", self)
        choose_output_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(choose_output_button)
        output_row.addWidget(self.output_label, stretch=1)
        layout.addLayout(output_row)

        return group

    # ------------------------------------------------------------------
    # Gruppe 3: Einstellungen fuer DIESEN Lauf (Sprache, Sprechertrennung).
    # Die strukturelle Wahl lokal/API sowie Modell-/Endpunktkonfiguration
    # gehoeren in 'SettingsDialog', nicht hierher.
    # ------------------------------------------------------------------
    def _build_settings_group(self) -> QGroupBox:
        group = QGroupBox("Einstellungen für diesen Lauf", self)
        layout = QFormLayout(group)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        self.language_combo = QComboBox(self)
        self.language_combo.addItem("Deutsch (de)", "de")
        self.language_combo.addItem("Automatisch erkennen", None)
        layout.addRow("Sprache:", self.language_combo)

        self.diarization_checkbox = QCheckBox("Sprechertrennung (Sprecher erkennen)", self)
        self.diarization_checkbox.setChecked(True)
        self.diarization_checkbox.toggled.connect(self._toggle_diarization)
        self.diarization_checkbox.setToolTip(
            "Abwählen, wenn nur der Inhalt zählt und die Aussagen anonym bleiben sollen "
            "(keine Sprecherzuordnung im Ergebnis)."
        )
        layout.addRow(self.diarization_checkbox)

        # Begrenzung der Sprecherzahl in einer Zeile: Haken, Min., Max.
        speaker_row = QHBoxLayout()
        self.limit_speakers_checkbox = QCheckBox("Sprecherzahl begrenzen", self)
        self.limit_speakers_checkbox.toggled.connect(self._toggle_speaker_limits)
        speaker_row.addWidget(self.limit_speakers_checkbox)
        self.min_speakers_spin = QSpinBox(self)
        self.min_speakers_spin.setRange(1, 30)
        self.min_speakers_spin.setValue(2)
        self.min_speakers_spin.setEnabled(False)
        self.max_speakers_spin = QSpinBox(self)
        self.max_speakers_spin.setRange(1, 30)
        self.max_speakers_spin.setValue(6)
        self.max_speakers_spin.setEnabled(False)
        speaker_row.addWidget(QLabel("Min.:", self))
        speaker_row.addWidget(self.min_speakers_spin)
        speaker_row.addWidget(QLabel("Max.:", self))
        speaker_row.addWidget(self.max_speakers_spin)
        speaker_row.addStretch(1)
        layout.addRow(speaker_row)

        # Vorher stand 'allow_download=False' fest im
        # Code -- damit setzt 'model_service.prepare_offline_mode'
        # ausnahmslos 'HF_HUB_OFFLINE=1', und ein Modell, das noch nicht
        # heruntergeladen ist, kann NIE geladen werden. Der
        # Einstellungsdialog verspricht aber genau das ("Wird beim ersten
        # Einsatz im lokalen Modus automatisch heruntergeladen").
        self.offline_checkbox = QCheckBox("Offline-Modus (empfohlen)", self)
        self.offline_checkbox.setChecked(True)
        self.offline_checkbox.setToolTip(
            "Verhindert jeden Netzwerkzugriff der Modelle. Für den ersten Lauf mit einem noch nicht "
            "eingerichteten Whisper-Modell einmal abwählen, damit es heruntergeladen werden darf."
        )
        layout.addRow(self.offline_checkbox)

        return group

    def _toggle_speaker_limits(self, checked: bool) -> None:
        self.min_speakers_spin.setEnabled(checked)
        self.max_speakers_spin.setEnabled(checked)

    def _toggle_diarization(self, checked: bool) -> None:
        self.limit_speakers_checkbox.setEnabled(checked)
        if not checked:
            self.limit_speakers_checkbox.setChecked(False)
        self.min_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())
        self.max_speakers_spin.setEnabled(checked and self.limit_speakers_checkbox.isChecked())

    def _refresh_hardware_label(self) -> None:
        self.hardware_label.setText(model_service.get_gpu_description())

    # ------------------------------------------------------------------
    # Gruppe 4: Fortsetzen bei Langzeitaufnahmen
    # ------------------------------------------------------------------
    def _build_resume_group(self) -> QGroupBox:
        group = QGroupBox("Fortsetzen bei Langzeitaufnahmen", self)
        layout = QVBoxLayout(group)

        self.resume_status_label = QLabel(
            "Keine Datei ausgewählt -- es kann noch nicht geprüft werden, ob bereits "
            "ein Zwischenstand existiert.",
            self,
        )
        self.resume_status_label.setWordWrap(True)
        layout.addWidget(self.resume_status_label)

        row = QHBoxLayout()
        self.resume_combo = QComboBox(self)
        self.resume_combo.addItem("Verarbeitung fortsetzen", "fortsetzen")
        self.resume_combo.addItem("Vollständig neu beginnen", "neu_beginnen")
        row.addWidget(self.resume_combo)

        open_intermediate_button = QPushButton("Zwischenstände öffnen", self)
        open_intermediate_button.clicked.connect(self._open_intermediate_folder)
        row.addWidget(open_intermediate_button)
        layout.addLayout(row)

        return group

    # ------------------------------------------------------------------
    # Gruppe 5: Transkription - lokal/API-Umschalter direkt hier, damit
    # nicht jedes Mal die Einstellungen geoeffnet werden muessen.
    # ------------------------------------------------------------------
    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("Transkription starten", self)
        layout = QVBoxLayout(group)

        modus_row = QHBoxLayout()
        self.transkription_lokal_radio = QRadioButton("Lokal", self)
        self.transkription_api_radio = QRadioButton("API-Schnittstelle", self)
        self._transkription_modus_gruppe = QButtonGroup(self)
        self._transkription_modus_gruppe.addButton(self.transkription_lokal_radio)
        self._transkription_modus_gruppe.addButton(self.transkription_api_radio)
        modus_row.addWidget(self.transkription_lokal_radio)
        modus_row.addWidget(self.transkription_api_radio)
        modus_row.addStretch(1)
        layout.addLayout(modus_row)

        config = app_config.load_config()
        if config["transkription_modus"] == "api":
            self.transkription_api_radio.setChecked(True)
        else:
            self.transkription_lokal_radio.setChecked(True)
        self.transkription_lokal_radio.toggled.connect(self._transkription_modus_geaendert)
        self.transkription_api_radio.toggled.connect(self._transkription_modus_geaendert)

        self.transkription_datenschutz_hinweis = QLabel(DATENSCHUTZ_HINWEIS_API, self)
        self.transkription_datenschutz_hinweis.setObjectName("DatenschutzHinweis")
        self.transkription_datenschutz_hinweis.setWordWrap(True)
        layout.addWidget(self.transkription_datenschutz_hinweis)
        self._transkription_datenschutz_hinweis_aktualisieren()

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Transkription starten", self)
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_transcription_with_dialog)
        button_row.addWidget(self.start_button)
        self.cancel_button = QPushButton("Abbrechen", self)
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_transcription)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        return group

    def _new_transcription(self) -> None:
        """Dialog 'Audioquelle waehlen'; fuehrt danach die vorhandene
        Aufnahme- bzw. Dateiauswahl aus."""
        if self._recording is not None:
            return
        self._show_page(self.SEITE_TRANSKRIPTION)
        geraete = [geraet.anzeigename for geraet in self._recording_devices]
        dialog = AudioquelleDialog(
            geraete,
            self.recording_device_combo.currentIndex(),
            self.recording_start_button.isEnabled(),
            self,
        )
        if not dialog.exec():
            return
        if dialog.quelle == "mikrofon":
            self.recording_device_combo.setCurrentIndex(dialog.geraet_index)
            self._start_recording()
        else:
            self._choose_file()

    def _start_transcription_with_dialog(self) -> None:
        """Fragt vor dem Start die Verarbeitung ab (Sprecher, Protokoll) und
        startet dann wie bisher. Ohne Quelldatei geht es direkt an
        ``_start_transcription``, das den Fehler meldet."""
        if self._source_path is None:
            self._start_transcription()
            return
        sprecherzahl = (
            self.min_speakers_spin.value()
            if self.limit_speakers_checkbox.isChecked()
            and self.min_speakers_spin.value() == self.max_speakers_spin.value()
            else None
        )
        vorlagen = list(alle_vorlagen())
        dialog = EndverarbeitungDialog(
            self.diarization_checkbox.isChecked(),
            sprecherzahl,
            vorlagen,
            self.vorlage_combo.currentData(),
            self,
        )
        if not dialog.exec():
            return
        self.diarization_checkbox.setChecked(dialog.sprecher_erkennen)
        if dialog.sprecherzahl is not None:
            self.limit_speakers_checkbox.setChecked(True)
            self.min_speakers_spin.setValue(dialog.sprecherzahl)
            self.max_speakers_spin.setValue(dialog.sprecherzahl)
        else:
            self.limit_speakers_checkbox.setChecked(False)
        self._protokoll_nach_transkription = dialog.protokoll_erstellen
        if dialog.vorlage is not None:
            self.vorlage_combo.setCurrentIndex(self.vorlage_combo.findData(dialog.vorlage))
        vorher = self._transcription_worker
        self._start_transcription()
        if self._transcription_worker is vorher:
            # Kein neuer Arbeiter: Der Start ist gescheitert, die Fehlermeldung
            # wurde schon gezeigt.
            self._protokoll_nach_transkription = False

    def _transkription_modus_geaendert(self) -> None:
        modus = "api" if self.transkription_api_radio.isChecked() else "lokal"
        app_config.update_config(transkription_modus=modus)
        self._transkription_datenschutz_hinweis_aktualisieren()

    def _transkription_datenschutz_hinweis_aktualisieren(self) -> None:
        self.transkription_datenschutz_hinweis.setVisible(self.transkription_api_radio.isChecked())

    # ------------------------------------------------------------------
    # Gemeinsame Fortschrittsgruppe
    # ------------------------------------------------------------------
    def _build_progress_group(self) -> QGroupBox:
        """Kompakter Fortschritt, dauerhaft unter der aktuellen Seite."""
        group = QGroupBox("Fortschritt", self)
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(6)

        self.status_label = QLabel("Bereit.", self)
        self.status_label.setWordWrap(True)
        self.transcription_status_label = QLabel("wartet", self)
        self.protocol_status_label = QLabel("wartet", self)
        self.chunk_progress_bar = QProgressBar(self)
        self.overall_progress_bar = QProgressBar(self)
        self.overall_progress_bar.setRange(0, 100)
        self.elapsed_label = QLabel("00:00", self)
        self.remaining_label = QLabel("--", self)
        self.hardware_label = QLabel("--", self)

        def beschriftet(text: str, widget: QWidget) -> QWidget:
            zelle = QWidget(self)
            zeile = QVBoxLayout(zelle)
            zeile.setContentsMargins(0, 0, 0, 0)
            zeile.setSpacing(2)
            ueberschrift = QLabel(text, self)
            ueberschrift.setObjectName("FieldCaption")
            zeile.addWidget(ueberschrift)
            zeile.addWidget(widget)
            return zelle

        layout.addWidget(beschriftet("Status", self.status_label), 0, 0, 1, 4)
        layout.addWidget(beschriftet("Transkription", self.transcription_status_label), 1, 0)
        layout.addWidget(beschriftet("Nachbearbeitung", self.protocol_status_label), 1, 1)
        layout.addWidget(beschriftet("Aktueller Chunk", self.chunk_progress_bar), 1, 2)
        layout.addWidget(beschriftet("Gesamtfortschritt", self.overall_progress_bar), 1, 3)
        layout.addWidget(beschriftet("Laufzeit", self.elapsed_label), 2, 0)
        layout.addWidget(beschriftet("Geschätzte Restdauer", self.remaining_label), 2, 1)
        layout.addWidget(beschriftet("Hardware", self.hardware_label), 2, 2, 1, 2)
        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("Transkriptvorschau", self)
        layout = QVBoxLayout(group)
        self.preview_edit = QPlainTextEdit(self)
        self.preview_edit.setReadOnly(True)
        layout.addWidget(self.preview_edit)

        self.export_button = QPushButton("Exportieren …", self)
        self.export_button.setToolTip(
            "Transkript (und Protokoll) als Word, PDF, Markdown, Text, HTML, OpenDocument, Untertitel "
            "oder JSON in einen Ordner Ihrer Wahl speichern."
        )
        self.export_button.clicked.connect(self._export_oeffnen)
        layout.addWidget(self.export_button)
        return group

    def _build_speaker_group(self) -> QGroupBox:
        group = QGroupBox("Sprecherzuordnung", self)
        layout = QVBoxLayout(group)

        self.speaker_table = QTableWidget(0, 6, self)
        self.speaker_table.setHorizontalHeaderLabels(
            ["Technische Sprecher-ID", "Segmente", "Sprechdauer", "Name", "Stimme", "Profil"]
        )
        self.speaker_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.speaker_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        layout.addWidget(self.speaker_table)

        self.apply_names_button = QPushButton("Namen übernehmen && Ausgaben neu erzeugen", self)
        self.apply_names_button.setEnabled(False)
        self.apply_names_button.clicked.connect(self._apply_speaker_names)
        layout.addWidget(self.apply_names_button)

        self.profiles_button = QPushButton("Sprecherprofile verwalten …", self)
        self.profiles_button.setToolTip("Gespeicherte Stimmen ansehen, umbenennen oder löschen.")
        self.profiles_button.clicked.connect(self._manage_speaker_profiles)
        layout.addWidget(self.profiles_button)

        return group

    # ------------------------------------------------------------------
    # Datei-/Ordnerauswahl, Drag & Drop
    # ------------------------------------------------------------------
    def _choose_input_folder(self) -> None:
        start_dir = str(self._input_folder) if self._input_folder else str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Eingabeordner wählen", start_dir)
        if directory:
            self._set_input_folder(Path(directory))

    def _set_input_folder(self, folder: Path) -> None:
        self._input_folder = folder
        self.folder_label.setText(str(folder))
        self._populate_file_list(folder)
        app_config.update_config(eingabeordner=str(folder))
        self._geraete_empfang_anwenden()

    def _populate_file_list(self, folder: Path) -> None:
        self.file_list.clear()
        try:
            files = sorted(
                path for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
            )
        except OSError:
            files = []
        for file_path in files:
            self.file_list.addItem(file_path.name)

    def _select_file_in_list(self, filename: str) -> None:
        matches = self.file_list.findItems(filename, Qt.MatchExactly)
        if matches:
            self.file_list.setCurrentItem(matches[0])

    def _on_file_list_selection_changed(self) -> None:
        items = self.file_list.selectedItems()
        if not items or self._input_folder is None:
            return
        self._source_path = self._input_folder / items[0].text()
        self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
        self._refresh_resume_status()

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Audio- oder Videodatei auswählen",
            str(self._input_folder) if self._input_folder else "",
            f"Unterstützte Dateien ({SUPPORTED_EXTENSIONS});;Alle Dateien (*)",
        )
        if not filename:
            return
        self._set_source_file(Path(filename))

    def _set_source_file(self, path: Path) -> None:
        self.file_list.clearSelection()
        self._source_path = path
        self.file_label.setText(f"Ausgewählt: {self._source_path.name}")
        self._refresh_resume_status()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.is_dir():
            self._set_input_folder(path)
            event.acceptProposedAction()
        elif path.is_file():
            self._set_source_file(path)
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Beendet eine laufende Aufnahme sauber, statt sie beim Schliessen
        des Fensters abzuwuergen - sonst fehlt der WAV-Datei der finale
        Header und sie waere unbrauchbar. Ein bearbeitetes, noch nicht
        gespeichertes Ergebnis der Nachbearbeitung wird vorher angesprochen;
        bricht der Benutzer ab, bleibt das Fenster offen und alles laeuft weiter."""
        if not self._ungespeicherte_aenderungen_geklaert("das Fenster geschlossen wird"):
            event.ignore()
            return
        if self._recording is not None:
            with contextlib.suppress(Exception):
                self._recording.stop()
        self._geraete_empfang.stoppen()
        self._fragen.stoppen()
        self._live.stoppen()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Aufnahmegeraete im WLAN
    # ------------------------------------------------------------------
    def _live_auswertung_lesen(self) -> live_auswertung_service.AuswertungsEinstellungen | None:
        """Womit die Teilauswertung waehrend der Aufnahme rechnet: derselbe Auftrag und dasselbe Modell wie die
        automatische Auswertung nach dem Ende (nur dann passen ihre Ergebnisse dazu). ``None``: aus oder nicht
        moeglich (kein Anbieter, kein Schluessel) -- dann rechnet erst die Auswertung nach dem Ende."""
        config = app_config.load_config()
        if not (config.get("geraete_live_aktiv", True) and config.get("geraete_live_auswertung_vorab", True)):
            return None
        auftrag = alle_vorlagen().get(str(config.get("geraete_live_auftrag") or ""), "")
        abschnitt = chunking_service.auswertungs_abschnitt(config.get("geraete_live_abschnitt_sekunden"))
        if self.nachbearbeitung_api_radio.isChecked():
            endpunkt, modell = config["api_nachbearbeitung_endpunkt"], config["api_nachbearbeitung_modell"]
            if not (api_anbieter.adresse_vollstaendig(endpunkt) and modell):
                return None
            eigener = config["api_nachbearbeitung_eigener_schluessel"]
            schluessel = self._verwendbarer_api_schluessel("nachbearbeitung" if eigener else "transkription")
            if not schluessel:
                return None
            return live_auswertung_service.AuswertungsEinstellungen(
                auftrag,
                f"api:{endpunkt}|{modell}",
                api_auswertung_funktion(endpunkt, modell, schluessel),
                abschnitt_sekunden=abschnitt,
            )
        lokal = config["ollama_modell"] or ollama_service.DEFAULT_MODEL
        return live_auswertung_service.AuswertungsEinstellungen(
            auftrag,
            lokal,
            lambda prompt, system: ollama_service.generate_text(prompt, system, model=lokal),
            abschnitt_sekunden=abschnitt,
        )

    def _geraete_empfang_anwenden(self) -> None:
        """Empfang passend zu den Einstellungen starten oder stoppen. Die Geraete
        liefern in den Eingabeordner -- ohne einen in den Aufnahmeordner, damit
        eine Aufnahme immer irgendwo landen kann."""
        self._live_einstellungen = self._live_einstellungen_lesen()
        self._live_auswertung_stand = self._live_auswertung_lesen()
        ziel = self._input_folder if self._input_folder is not None else get_recordings_dir()
        self._geraete_empfang.anwenden(ziel)
        self._empfang_anzeigen()

    def geraete_kontakte(self) -> dict[str, Any]:
        """Fuer den Einstellungsdialog: letzter Kontakt je Aufnahmegeraet."""
        return dict(self._geraete_empfang.kontakte())

    def _empfang_anzeigen(self) -> None:
        text = self._geraete_empfang.beschreibung()
        if text and self._empfang_zuletzt:
            text = f"{text}\n{self._empfang_zuletzt}"
        self.empfang_label.setText(text)
        self.empfang_label.setVisible(bool(text))

    def _neue_geraete_aufnahme(self, pfad: str, geraet: str) -> None:
        datei = Path(pfad)
        if self._input_folder is not None and datei.parent == self._input_folder:
            ausgewaehlt = self._source_path
            self._populate_file_list(self._input_folder)
            if ausgewaehlt is not None and ausgewaehlt.parent == self._input_folder:
                self._select_file_in_list(ausgewaehlt.name)
        self._empfang_zuletzt = f"Zuletzt angekommen: {datei.name} von {geraet} ({time.strftime('%H:%M')})"
        self._empfang_anzeigen()

    # ------------------------------------------------------------------
    # Live-Transkription und automatische Auswertung von Geraeteaufnahmen
    # ------------------------------------------------------------------
    def _live_einstellungen_lesen(self) -> tuple[str, str | None, bool]:
        """(Whisper-Modell, Sprache, Download erlaubt) fuer die Live-Transkription."""
        return (
            ermittle_whisper_modell(app_config.load_config()),
            self.language_combo.currentData(),
            not self.offline_checkbox.isChecked(),
        )

    def _live_transkribierer(self) -> Any:
        """Fabrik fuer den Live-Arbeiter (laeuft in dessen Faden)."""
        modell, sprache, download = self._live_einstellungen
        return live_service.cpu_transkribierer_fabrik(modell, sprache, download)()

    def _live_transkript_anzeigen(self, geraet: str, datei: str, text: str, bis: float) -> None:
        """Waehrend eine Geraeteaufnahme laeuft, waechst ihr Transkript: in der Vorschau zeigen (solange keine eigene
        Verarbeitung dort etwas anderes anzeigt) und im Empfangshinweis nennen, wie weit es ist."""
        self._empfang_zuletzt = f"Live: {datei} von {geraet} – bis {live_service.minuten_sekunden(bis)} transkribiert"
        self._empfang_anzeigen()
        if not self._arbeit_laeuft() and self._automatik is None:
            self.preview_edit.setPlainText(text)

    def _ergebnisse_merken(self, **pfade: Path | None) -> None:
        """Die Unterlagen der Aufnahme, die gerade automatisch verarbeitet wird, fuer Fragen per Sprache merken."""
        if self._automatik is None:
            return
        geraet, datei, _pfad = self._automatik
        eintrag = self._ergebnisse.setdefault((geraet, datei), {})
        for name, pfad in pfade.items():
            if pfad is not None:
                eintrag[name] = pfad
        while len(self._ergebnisse) > 50:
            del self._ergebnisse[next(iter(self._ergebnisse))]

    def _frage_bereit(self, geraet: str, datei: str) -> bool:
        return "transkript" in self._ergebnisse.get((geraet, datei), {})

    def _frage_erkennen(self, ton: bytes, endung: str) -> str:
        """Die gesprochene Frage als Text (Whisper auf dem Prozessor; laeuft im Faden der Fragen)."""
        with self._frage_sperre:
            if self._frage_transkribierer is None:
                self._frage_transkribierer = self._live_transkribierer()
            transkribieren = self._frage_transkribierer
        return geraete_fragen.frage_verstehen(
            ton, endung, transkribieren=transkribieren, extrahieren=live_service.standard_extrahieren
        )

    def _frage_beantworten(self, frage: str, geraet: str, datei: str, ausgabe: str) -> str:
        """Antwort aus Zusammenfassung und Transkript der Aufnahme (lokales Sprachmodell, laeuft im Faden der Fragen)."""
        eintrag = self._ergebnisse.get((geraet, datei), {})
        unterlagen = [p for p in (eintrag.get("zusammenfassung"), eintrag.get("transkript")) if p is not None]
        konfig = app_config.load_config()
        modell = konfig.get("chatbot_ollama_modell") or konfig.get("ollama_modell") or ollama_service.DEFAULT_MODEL
        # Immer lokal und mit dem ganzen Text: Das Geraet fragt im eigenen Netz, ohne Einbettungsmodell.
        einstellungen = chat_service.ChatEinstellungen("lokal", modell, "", kontext=chat_service.KONTEXT_VOLLTEXT)
        _embed, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
        return geraete_fragen.antwort_aus_unterlagen(frage, unterlagen, chat_fn, ausgabe)

    def _auftrag_des_geraets(self, geraet: str, datei: str) -> str | None:
        """Text des Auftrags, den das Geraet fuer diese Aufnahme gewaehlt hat; ``None``: der aus den Einstellungen
        (kein Wunsch, oder die Vorlage gibt es nicht mehr)."""
        wunsch = self._wuensche.hole(geraet, datei)
        if wunsch is None or wunsch.auftrag is None:
            return None
        return alle_vorlagen().get(wunsch.auftrag)

    def _geraete_aufnahme_bereit(self, pfad: str, geraet: str, datei: str) -> None:
        """Eine Aufnahme ist vollstaendig angekommen: automatisch verarbeiten."""
        self._geraete_warteschlange.append((Path(pfad), geraet, datei))
        self._naechste_geraete_aufnahme()

    def _arbeit_laeuft(self) -> bool:
        return any(
            worker is not None and worker.isRunning() for worker in (self._transcription_worker, self._protocol_worker)
        )

    def _naechste_geraete_aufnahme(self) -> None:
        if self._automatik is not None or self._arbeit_laeuft():
            return
        # Wer am Geraet die Zusammenfassung freigegeben hat, wartet darauf: Das geht vor neuen Aufnahmen.
        if self._freigabe_warteschlange:
            geraet, datei = self._freigabe_warteschlange.pop(0)
            self._zusammenfassung_erstellen(geraet, datei)
            return
        if self._geraete_warteschlange:
            pfad, geraet, datei = self._geraete_warteschlange.pop(0)
            self._geraete_aufnahme_verarbeiten(pfad, geraet, datei)
            return
        # Zuletzt, was niemand mehr am Geraet erwartet: Zusammenfassungen, nach denen das Geraet nicht mehr fragt.
        if self._nachhol_warteschlange:
            geraet, datei = self._nachhol_warteschlange.pop(0)
            self._zusammenfassung_erstellen(geraet, datei)

    def _geraete_arbeit_wartet(self) -> bool:
        return bool(self._freigabe_warteschlange or self._geraete_warteschlange or self._nachhol_warteschlange)

    def _geraete_aufnahme_verarbeiten(self, pfad: Path, geraet: str, datei: str) -> None:
        """Transkription der fertigen Datei (nur der Rest nach der Live-Transkription), danach
        die Auswertung nach dem Auftrag aus den Einstellungen."""
        config = app_config.load_config()
        auftrag = str(config.get("geraete_live_auftrag") or "")
        self._automatik = (geraet, datei, pfad)
        self._automatik_phase = live_service.TRANSKRIPTION
        # Der Auftrag, den das Geraet vor der Aufnahme gewaehlt hat, geht vor dem aus den Einstellungen.
        gewaehlt = self._auftrag_des_geraets(geraet, datei)
        self._systemprompt_automatik = gewaehlt if gewaehlt is not None else alle_vorlagen().get(auftrag, "")
        wunsch = self._wuensche.hole(geraet, datei)
        self._automatik_rueckfrage = wunsch is not None and wunsch.rueckfrage
        self._set_source_file(pfad)
        self._select_file_in_list(pfad.name)
        self.resume_combo.setCurrentIndex(max(self.resume_combo.findData("fortsetzen"), 0))
        self._geraete_status.setze(geraet, datei, live_service.TRANSKRIPTION, 0.0, "Transkription beginnt")
        self._empfang_zuletzt = f"Automatische Verarbeitung: {pfad.name} von {geraet}"
        self._empfang_anzeigen()
        # Mit Rueckfrage am Geraet wartet die Zusammenfassung, bis das Geraet sie freigibt.
        self._protokoll_nach_transkription = not self._automatik_rueckfrage
        vorher = self._transcription_worker
        self._start_transcription()
        if self._transcription_worker is vorher:
            # Der Start ist gescheitert (Fehlermeldung wurde schon gezeigt).
            self._protokoll_nach_transkription = False
            self._automatik_beenden(live_service.FEHLER, "Die Verarbeitung konnte nicht gestartet werden.")

    def _automatik_wartet_auf_freigabe(self, transkript: Path) -> None:
        """Das Transkript steht. Das Geraet fragt seinen Nutzer, ob die Zusammenfassung erstellt werden soll;
        bis es sie freigibt, bleibt die Verarbeitung stehen und die Software frei fuer andere Aufnahmen."""
        if self._automatik is None:
            return
        geraet, datei, pfad = self._automatik
        self._freigaben[(geraet, datei)] = (pfad, transkript, self._systemprompt_automatik or "")
        self._automatik = None
        self._automatik_phase = ""
        self._systemprompt_automatik = None
        self._automatik_rueckfrage = False
        self._geraete_status.setze(geraet, datei, live_service.TRANSKRIPT, 1.0, "Transkription erfolgreich")
        self._empfang_zuletzt = f"Transkript steht, wartet auf Freigabe am Gerät: {pfad.name} von {geraet}"
        self._empfang_anzeigen()
        if self._wuensche.neueste(geraet) not in (None, datei):
            # Das Geraet hat schon eine neue Aufnahme begonnen: Nach dieser fragt es nicht mehr.
            self._ohne_antwort_weiter(geraet, datei)
        if self._geraete_arbeit_wartet():
            QTimer.singleShot(0, self._naechste_geraete_aufnahme)

    def _geraet_weitergezogen(self, geraet: str, neue_datei: str) -> None:
        """Das Geraet hat eine neue Aufnahme begonnen (oder ist neu gestartet und nimmt wieder auf): Nach seinen
        frueheren Aufnahmen fragt es nicht mehr. Was noch auf "Ja/Nein" wartet, geht ohne Antwort weiter."""
        for schluessel in list(self._freigaben):
            if schluessel[0] == geraet and schluessel[1] != neue_datei and schluessel not in self._freigabe_warteschlange:
                self._ohne_antwort_weiter(*schluessel)

    def _ohne_antwort_weiter(self, geraet: str, datei: str) -> None:
        """Niemand beantwortet die Rueckfrage mehr. Reicht die Grafikkarte, um die Zusammenfassung neben der
        neuen Aufnahme zu rechnen, kommt sie nach den neuen Aufnahmen dran; sonst bleibt es beim Transkript --
        die neue Aufnahme darf nicht warten, weil das Sprachmodell den Grafikspeicher haelt."""
        if (geraet, datei) not in self._freigaben or (geraet, datei) in self._nachhol_warteschlange:
            return
        if self._zusammenfassung_nebenher_moeglich():
            self._nachhol_warteschlange.append((geraet, datei))
            self._empfang_zuletzt = f"Zusammenfassung ohne Rückfrage folgt: {datei} von {geraet}"
            self._empfang_anzeigen()
            QTimer.singleShot(0, self._naechste_geraete_aufnahme)
        else:
            self._ohne_zusammenfassung_abschliessen(
                geraet, datei, "ohne Zusammenfassung (Grafikspeicher reicht nicht neben der neuen Aufnahme)"
            )

    def _zusammenfassung_abgelehnt(self, geraet: str, datei: str) -> None:
        """Am Geraet "Nein" gewaehlt: Das Transkript bleibt, eine Zusammenfassung gibt es nicht."""
        if (geraet, datei) in self._freigabe_warteschlange:
            return  # "Ja" kam zuerst und gilt
        with contextlib.suppress(ValueError):
            self._nachhol_warteschlange.remove((geraet, datei))
        self._ohne_zusammenfassung_abschliessen(geraet, datei, "ohne Zusammenfassung (am Gerät abgelehnt)")

    def _ohne_zusammenfassung_abschliessen(self, geraet: str, datei: str, grund: str) -> None:
        eintrag = self._freigaben.pop((geraet, datei), None)
        if eintrag is None:
            return
        pfad = eintrag[0]
        self._geraete_status.setze(geraet, datei, live_service.FERTIG, 1.0, "Transkription erfolgreich")
        self._live.freigeben(pfad)  # die Vorab-Teilergebnisse braucht niemand mehr
        self._empfang_zuletzt = f"Transkript fertig, {grund}: {pfad.name} von {geraet}"
        self._empfang_anzeigen()

    def _zusammenfassung_nebenher_moeglich(self) -> bool:
        """Verkraftet der Rechner eine Zusammenfassung neben der naechsten Aufnahme? Ueber eine API immer (sie
        rechnet nicht hier); lokal nur, wenn Sprachmodell und Whisper zugleich in den Grafikspeicher passen --
        sonst muesste die neue Aufnahme warten, bis das Sprachmodell entladen ist."""
        if self.nachbearbeitung_api_radio.isChecked():
            return True
        modell = app_config.load_config().get("ollama_modell") or ollama_service.DEFAULT_MODEL
        # Geladen misst Ollama selbst (mit Kontext); sonst die Schaetzung aus der Modellauswahl
        bedarf = max(ollama_service.belegter_grafikspeicher(timeout=2), ollama_service.geschaetzter_grafikspeicher(modell) or 0)
        return model_service.sprachmodell_passt_neben_whisper(model_service.gesamter_grafikspeicher(), bedarf or None)

    def _zusammenfassung_gewuenscht(self, geraet: str, datei: str) -> None:
        """Das Geraet hat die Zusammenfassung freigegeben."""
        if (geraet, datei) not in self._freigaben or (geraet, datei) in self._freigabe_warteschlange:
            return
        self._freigabe_warteschlange.append((geraet, datei))
        # Sofort Rueckmeldung ans Geraet, auch wenn noch eine andere Aufnahme verarbeitet wird.
        self._geraete_status.setze(geraet, datei, live_service.AUSWERTUNG, 0.5, "Zusammenfassung wird erstellt")
        self._naechste_geraete_aufnahme()

    def _zusammenfassung_erstellen(self, geraet: str, datei: str) -> None:
        eintrag = self._freigaben.pop((geraet, datei), None)
        if eintrag is None:
            # Schon erledigt (etwa freigegeben, waehrend sie zum Nachholen anstand): mit dem Naechsten weiter.
            if self._geraete_arbeit_wartet():
                QTimer.singleShot(0, self._naechste_geraete_aufnahme)
            return
        pfad, transkript, auftrag = eintrag
        self._automatik = (geraet, datei, pfad)
        self._automatik_phase = live_service.AUSWERTUNG
        self._automatik_rueckfrage = True
        self._systemprompt_automatik = auftrag
        self._set_transcript_path(transkript)
        self._geraete_status.setze(geraet, datei, live_service.AUSWERTUNG, 0.5, "Zusammenfassung wird erstellt")
        self._empfang_zuletzt = f"Zusammenfassung wird erstellt: {pfad.name} von {geraet}"
        self._empfang_anzeigen()
        vorher = self._protocol_worker
        self._start_protocol()
        if self._automatik is not None and self._protocol_worker is vorher:
            self._automatik_beenden(live_service.FEHLER, "Die Zusammenfassung konnte nicht gestartet werden.")

    def _automatik_status(self, zustand: str, *, fortschritt: float | None = None, detail: str = "") -> None:
        if self._automatik is None:
            return
        if zustand == live_service.AUSWERTUNG:
            self._automatik_phase = live_service.AUSWERTUNG
        geraet, datei, _pfad = self._automatik
        self._geraete_status.setze(geraet, datei, zustand, fortschritt, detail)

    def _protokoll_start_scheitert(self, titel: str, text: str) -> None:
        """Die Auswertung kann nicht beginnen. Von Hand gestartet: Fehlerfenster. In der automatischen Verarbeitung
        einer Geraeteaufnahme sitzt niemand davor -- dort kein Fenster, sondern Abschluss mit 'fehler' fuers Geraet.
        Sonst bliebe die Automatik fuer immer belegt: kein Status mehr, und keine weitere Aufnahme kaeme dran."""
        if self._automatik is None:
            show_error(self, titel, text)
            return
        self._on_log_message(text)
        self.status_label.setText(f"Automatische Auswertung nicht möglich: {titel}")
        self._automatik_beenden(live_service.FEHLER, f"Auswertung nicht möglich: {titel}")

    def _automatik_beenden(self, zustand: str, meldung: str) -> None:
        """Schliesst die automatische Verarbeitung ab und meldet das Ergebnis dem Geraet."""
        if self._automatik is None:
            return
        geraet, datei, pfad = self._automatik
        self._automatik = None
        self._automatik_phase = ""
        self._systemprompt_automatik = None
        self._automatik_rueckfrage = False
        self._geraete_status.setze(geraet, datei, zustand, 1.0 if zustand == live_service.FERTIG else None, meldung)
        if zustand == live_service.FERTIG:
            self._live.freigeben(pfad)
        self._empfang_zuletzt = f"{meldung}: {pfad.name} von {geraet} ({time.strftime('%H:%M')})"
        self._empfang_anzeigen()
        if self._geraete_arbeit_wartet():
            QTimer.singleShot(0, self._naechste_geraete_aufnahme)

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", str(self._output_dir))
        if not directory:
            return
        self._output_dir = Path(directory)
        self.output_label.setText(str(self._output_dir))
        app_config.update_config(ausgabeordner=str(self._output_dir))

    # ------------------------------------------------------------------
    # Fortsetzen-Status (Dateihash laeuft im Hintergrund)
    # ------------------------------------------------------------------
    def _dateihash(self, pfad: Path) -> str | None:
        try:
            angaben = pfad.stat()
        except OSError:
            return None
        return self._hash_zwischenspeicher.get((str(pfad), angaben.st_size, angaben.st_mtime_ns))

    def _dateihash_merken(self, pfad: Path, hashwert: str) -> None:
        try:
            angaben = pfad.stat()
        except OSError:
            return
        self._hash_zwischenspeicher[(str(pfad), angaben.st_size, angaben.st_mtime_ns)] = hashwert

    def _refresh_resume_status(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            return
        bekannt = self._dateihash(self._source_path)
        if bekannt is not None:
            self._zeige_fortsetzbarkeit(str(self._source_path), bekannt)
            return

        self.resume_status_label.setText("Datei wird geprüft …")
        self._hash_worker = DateiHashWorker(self._source_path, self)
        self._hash_worker.fertig.connect(self._zeige_fortsetzbarkeit)
        self._hash_worker.fehlgeschlagen.connect(self._hash_fehlgeschlagen)
        self._hash_worker.start()

    def _hash_fehlgeschlagen(self, pfad: str, fehler: str) -> None:
        if self._source_path is None or str(self._source_path) != pfad:
            return
        self.resume_status_label.setText(f"Datei konnte nicht gelesen werden: {fehler}")

    def _zeige_fortsetzbarkeit(self, pfad: str, file_hash: str) -> None:
        if self._source_path is None or str(self._source_path) != pfad:
            return
        self._dateihash_merken(self._source_path, file_hash)
        try:
            work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
            manifest = manifest_service.load_manifest(work_dir)
        except OSError as error:
            self.resume_status_label.setText(f"Datei konnte nicht gelesen werden: {error}")
            return

        if manifest is None:
            self.resume_status_label.setText("Keine vorherige Verarbeitung für diese Datei gefunden.")
            self.resume_combo.setCurrentIndex(1)
            return

        state = manifest_service.find_resumable_state(manifest)
        if state["vollstaendig"]:
            self.resume_status_label.setText(
                "Diese Datei wurde bereits vollständig verarbeitet. Ein Neustart berechnet alles erneut."
            )
        else:
            self.resume_status_label.setText(
                f"Unvollständige Verarbeitung gefunden: {len(state['fertige_chunks'])} von "
                f"{manifest['anzahl_chunks']} Chunks abgeschlossen. "
                f"Nächster Chunk: {state['naechster_chunk'] + 1 if state['naechster_chunk'] is not None else '-'}."
            )
        self.resume_combo.setCurrentIndex(0)

    def _open_intermediate_folder(self) -> None:
        if self._source_path is None or not self._source_path.is_file():
            show_error(self, "Keine Datei ausgewählt", "Bitte zuerst eine Datei auswählen.")
            return
        file_hash = self._dateihash(self._source_path) or manifest_service.compute_file_hash(
            self._source_path
        )
        self._dateihash_merken(self._source_path, file_hash)
        work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(work_dir)))

    # ------------------------------------------------------------------
    # Gruppe 6: Transkript auswaehlen (Eingang fuer die Nachbearbeitung)
    # ------------------------------------------------------------------
    def _build_transcript_selection_group(self) -> QGroupBox:
        group = QGroupBox("Transkript auswählen", self)
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        choose_transcript_button = QPushButton("Transkript auswählen …", self)
        choose_transcript_button.clicked.connect(self._choose_transcript)
        row.addWidget(choose_transcript_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.transcript_label = QLabel("Noch kein Transkript ausgewählt", self)
        self.transcript_label.setWordWrap(True)
        layout.addWidget(self.transcript_label)

        return group

    def _choose_transcript(self) -> None:
        start_dir = str(self._output_dir)
        filename, _ = QFileDialog.getOpenFileName(
            self, "Transkript auswählen", start_dir, "Transkript-JSON (*.json);;Alle Dateien (*)"
        )
        if not filename:
            return
        self._set_transcript_path(Path(filename))

    def _set_transcript_path(self, path: Path) -> None:
        self._selected_transcript_path = path
        self.transcript_label.setText(f"Ausgewählt: {path.name}")

    # ------------------------------------------------------------------
    # Gruppe 7: Nachbearbeitung - lokal/API-Umschalter, Systemprompt
    # (Vorlage per Dropdown oder freier Text, wie vom Auftrag verlangt).
    # ------------------------------------------------------------------
    def _build_protocol_control_group(self) -> QGroupBox:
        group = QGroupBox("Protokoll erstellen", self)
        layout = QVBoxLayout(group)

        modus_row = QHBoxLayout()
        self.nachbearbeitung_lokal_radio = QRadioButton("Lokal (Ollama)", self)
        self.nachbearbeitung_api_radio = QRadioButton("API-Modell", self)
        self._nachbearbeitung_modus_gruppe = QButtonGroup(self)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_lokal_radio)
        self._nachbearbeitung_modus_gruppe.addButton(self.nachbearbeitung_api_radio)
        modus_row.addWidget(self.nachbearbeitung_lokal_radio)
        modus_row.addWidget(self.nachbearbeitung_api_radio)
        modus_row.addStretch(1)
        layout.addLayout(modus_row)

        config = app_config.load_config()
        if config["nachbearbeitung_modus"] == "api":
            self.nachbearbeitung_api_radio.setChecked(True)
        else:
            self.nachbearbeitung_lokal_radio.setChecked(True)
        self.nachbearbeitung_lokal_radio.toggled.connect(self._nachbearbeitung_modus_geaendert)
        self.nachbearbeitung_api_radio.toggled.connect(self._nachbearbeitung_modus_geaendert)

        vorlagen_row = QHBoxLayout()
        vorlagen_row.addWidget(QLabel("Vorlage:", self))
        self.vorlage_combo = QComboBox(self)
        self.vorlage_combo.addItem("(freier Text)", None)
        for name in alle_vorlagen():
            self.vorlage_combo.addItem(name, name)
        self.vorlage_combo.currentIndexChanged.connect(self._vorlage_angewendet)
        vorlagen_row.addWidget(self.vorlage_combo, stretch=1)
        neue_vorlage_button = QPushButton("Als neue Vorlage speichern …", self)
        neue_vorlage_button.clicked.connect(self._neue_vorlage_speichern)
        vorlagen_row.addWidget(neue_vorlage_button)
        layout.addLayout(vorlagen_row)

        self.systemprompt_editor = QPlainTextEdit(self)
        self.systemprompt_editor.setPlaceholderText(
            "Was soll mit dem Transkript geschehen? Eigenen Text eingeben oder oben "
            "eine Vorlage auswählen. Bleibt das Feld leer, fasst das Modell so "
            "zusammen, wie es am sinnvollsten ist."
        )
        prompt_datei = get_system_prompt_file()
        if prompt_datei.is_file():
            self.systemprompt_editor.setPlainText(prompt_datei.read_text(encoding="utf-8"))
        layout.addWidget(self.systemprompt_editor)

        button_row = QHBoxLayout()
        self.protocol_start_button = QPushButton("Nachbearbeitung starten", self)
        self.protocol_start_button.setObjectName("PrimaryButton")
        self.protocol_start_button.clicked.connect(self._start_protocol)
        button_row.addWidget(self.protocol_start_button)
        self.protocol_cancel_button = QPushButton("Abbrechen", self)
        self.protocol_cancel_button.setObjectName("DangerButton")
        self.protocol_cancel_button.setEnabled(False)
        self.protocol_cancel_button.clicked.connect(self._cancel_protocol)
        button_row.addWidget(self.protocol_cancel_button)
        self.protocol_export_button = QPushButton("Exportieren …", self)
        self.protocol_export_button.setToolTip("Protokoll und Transkript in ein gewünschtes Format exportieren.")
        self.protocol_export_button.clicked.connect(self._export_oeffnen)
        button_row.addWidget(self.protocol_export_button)
        layout.addLayout(button_row)

        return group

    def _build_protocol_result_group(self) -> QGroupBox:
        """Ansicht des Nachbearbeitungs-Ergebnisses (Protokoll, Zusammenfassung
        o. ae.) auf der Seite "Nachbearbeitung". Der Text ist bearbeitbar und
        wird erst mit "Änderungen speichern" in die Protokolldateien (und die
        automatische Word-Datei) zurueckgeschrieben -- so laesst sich das
        Ergebnis pruefen und korrigieren, bevor es exportiert wird."""
        group = QGroupBox("Ergebnis der Nachbearbeitung", self)
        layout = QVBoxLayout(group)

        self.protocol_result_edit = QPlainTextEdit(self)
        self.protocol_result_edit.setMinimumHeight(260)
        self.protocol_result_edit.setPlaceholderText(
            "Hier erscheint das Ergebnis der Nachbearbeitung. Es lässt sich anschließend "
            "direkt bearbeiten und mit „Änderungen speichern“ in die Protokolldateien übernehmen."
        )
        # Erst bearbeitbar, wenn ein Ergebnis angezeigt wird: Vorher Getipptes
        # gehoerte zu keiner Datei und wuerde vom ersten Ergebnis ueberschrieben.
        self.protocol_result_edit.setReadOnly(True)
        self.protocol_result_edit.textChanged.connect(self._protocol_result_geaendert)
        layout.addWidget(self.protocol_result_edit)

        self.protocol_result_file_label = QLabel("Noch kein Ergebnis vorhanden.", self)
        self.protocol_result_file_label.setWordWrap(True)
        layout.addWidget(self.protocol_result_file_label)

        button_row = QHBoxLayout()
        self.protocol_save_button = QPushButton("Änderungen speichern", self)
        self.protocol_save_button.setEnabled(False)
        self.protocol_save_button.clicked.connect(self._save_protocol_edits)
        button_row.addWidget(self.protocol_save_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._protocol_result_paths: tuple[Path, Path] | None = None
        # Das Transkript, zu dem das angezeigte Ergebnis gehoert -- die
        # Word-Datei wird beim Speichern genau aus diesem Paar erzeugt.
        self._protocol_result_transkript: Path | None = None
        self._protocol_result_unveraendert = ""
        self._protocol_result_wird_gesetzt = False
        return group

    def _protocol_result_ungespeichert(self) -> bool:
        return (
            self._protocol_result_paths is not None
            and self.protocol_result_edit.toPlainText() != self._protocol_result_unveraendert
        )

    def _protocol_result_geaendert(self) -> None:
        if self._protocol_result_wird_gesetzt:
            return
        self.protocol_save_button.setEnabled(
            self._protocol_result_ungespeichert() and not self._nachbearbeitung_laeuft
        )

    def _protocol_result_sperre_anwenden(self) -> None:
        """Bearbeitbar nur, solange ein Ergebnis angezeigt wird und keine
        Nachbearbeitung laeuft -- deren Ergebnis ersetzt den Text sonst samt
        der Aenderungen, die waehrenddessen gemacht wurden."""
        self.protocol_result_edit.setReadOnly(self._protocol_result_paths is None or self._nachbearbeitung_laeuft)
        self._protocol_result_geaendert()

    def _protocol_result_anzeigen(
        self, text: str, paths: tuple[Path, Path] | None, transkript: Path | None = None
    ) -> None:
        self._protocol_result_wird_gesetzt = True
        try:
            self.protocol_result_edit.setPlainText(text)
        finally:
            self._protocol_result_wird_gesetzt = False
        self._protocol_result_paths = paths
        self._protocol_result_transkript = transkript if paths is not None else None
        self._protocol_result_unveraendert = self.protocol_result_edit.toPlainText()
        self._protocol_result_sperre_anwenden()
        if paths is None:
            self.protocol_result_file_label.setText("Noch kein Ergebnis vorhanden.")
        else:
            self.protocol_result_file_label.setText(f"Datei: {paths[1].name}")

    def _protokoll_zum_transkript(self, transkript_json: Path) -> Path | None:
        """Das angezeigte Protokoll (seine ``.json``), sofern es aus genau
        diesem Transkript entstanden ist -- sonst ``None``. Ein Protokoll zu
        einem anderen Transkript gehoert nicht in dessen Word-Datei."""
        if self._protocol_result_paths is None or self._protocol_result_transkript is None:
            return None
        if self._protocol_result_transkript.resolve() != transkript_json.resolve():
            return None
        protokoll = self._protocol_result_paths[0]
        return protokoll if protokoll.is_file() else None

    def _save_protocol_edits(self, _checked: bool = False) -> bool:
        if self._protocol_result_paths is None:
            return False
        json_path, md_path = self._protocol_result_paths
        text = self.protocol_result_edit.toPlainText()
        try:
            export_service.update_protocol_exports(json_path, md_path, text)
        except (OSError, ValueError) as error:
            show_error(self, "Speichern fehlgeschlagen", f"Das Ergebnis konnte nicht gespeichert werden:\n{error}")
            return False
        self._protocol_result_unveraendert = text
        self.protocol_save_button.setEnabled(False)
        self.status_label.setText("Änderungen am Ergebnis gespeichert.")
        # Die automatische Word-Datei enthaelt das Protokoll und soll den
        # bearbeiteten Text zeigen -- zusammen mit dem Transkript, aus dem
        # DIESES Ergebnis entstand, nicht mit dem gerade ausgewaehlten.
        transkript = self._protocol_result_transkript
        if transkript is not None and transkript.is_file():
            self._word_neu_erzeugen(transkript)
        return True

    def _ungespeicherte_aenderungen_geklaert(self, anlass: str) -> bool:
        """Fragt nach, bevor ein Vorgang das bearbeitete, noch nicht gespeicherte
        Ergebnis ersetzt oder ohne die Aenderungen weiterverwendet. Liefert
        ``False``, wenn der Benutzer abbricht."""
        if not self._protocol_result_ungespeichert():
            return True
        antwort = QMessageBox.question(
            self,
            "Ungespeicherte Änderungen",
            "Das Ergebnis der Nachbearbeitung wurde bearbeitet, aber nicht gespeichert.\n"
            f"Speichern, bevor {anlass}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if antwort == QMessageBox.Cancel:
            return False
        if antwort == QMessageBox.Save:
            return self._save_protocol_edits()
        return True

    def _nachbearbeitung_modus_geaendert(self) -> None:
        modus = "api" if self.nachbearbeitung_api_radio.isChecked() else "lokal"
        app_config.update_config(nachbearbeitung_modus=modus)

    def _vorlage_angewendet(self, _index: int) -> None:
        name = self.vorlage_combo.currentData()
        if name is None:
            return
        text = alle_vorlagen().get(name)
        if text is not None:
            self.systemprompt_editor.setPlainText(text)

    def _neue_vorlage_speichern(self) -> None:
        name, ok = QInputDialog.getText(self, "Neue Vorlage", "Name der Vorlage:")
        name = name.strip()
        if not ok or not name:
            return
        try:
            vorlage_speichern(name, self.systemprompt_editor.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Name nicht verwendbar", str(error))
            return
        except OSError as error:
            # Der Name IST der Dateiname. 'name_pruefen' faengt die verbotenen
            # Zeichen ab, es bleiben aber Faelle, die erst das Dateisystem
            # kennt: unter Windows reservierte Namen ("CON", "PRN", "LPT1"),
            # ein zu langer Pfad, ein schreibgeschuetzter Ordner.
            QMessageBox.warning(
                self,
                "Vorlage konnte nicht gespeichert werden",
                f"Die Vorlage '{name}' konnte nicht gespeichert werden:\n{error}",
            )
            return
        if self.vorlage_combo.findData(name) < 0:
            self.vorlage_combo.addItem(name, name)
        self.vorlage_combo.setCurrentIndex(self.vorlage_combo.findData(name))

    # ------------------------------------------------------------------
    # Start / Abbruch / Fortschritt: Transkription
    # ------------------------------------------------------------------
    def _start_transcription(self) -> None:
        if self._source_path is None:
            show_error(self, "Keine Datei ausgewählt", "Bitte zuerst eine Audio- oder Videodatei auswählen.")
            return
        if not self._source_path.is_file():
            show_error(self, "Datei nicht gefunden", f"Die Datei wurde nicht gefunden:\n{self._source_path}")
            return
        if self._source_path.stat().st_size == 0:
            show_error(self, "Datei ist leer", "Die ausgewählte Datei enthält keine Daten.")
            return
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            probe_file = self._output_dir / ".schreibtest.tmp"
            probe_file.write_text("test", encoding="utf-8")
            probe_file.unlink()
        except OSError as error:
            show_error(self, "Ausgabeordner ungültig", f"In den Ausgabeordner kann nicht geschrieben werden:\n{error}")
            return

        if self.transkription_lokal_radio.isChecked() and not self._lokale_laufzeitumgebung_verfuegbar():
            show_error(
                self,
                "Lokale Laufzeitumgebung noch nicht eingerichtet",
                "Für die lokale Transkription richtet diese Anwendung sich beim Start "
                "automatisch eine eigene Laufzeitumgebung ein (Whisper-Modell u. a.) -- "
                "das geschieht aber nur, wenn 'Lokal' schon beim Programmstart als "
                "Transkriptionsmodus aktiv war.\n\n"
                "Bitte die Anwendung einmal vollständig beenden und neu starten, während "
                "'Lokal' ausgewählt ist: Die Einrichtung läuft dann automatisch (kann "
                "beim ersten Mal, je nach Internetverbindung, einige Minuten dauern).",
            )
            return

        config = app_config.load_config()
        transcribe_chunk_fn = None
        diarize_fn = None
        if self.transkription_api_radio.isChecked():
            if not (
                api_anbieter.adresse_vollstaendig(config["api_transkription_endpunkt"])
                and config["api_transkription_modell"]
            ):
                show_error(
                    self,
                    "Kein Anbieter gewählt",
                    "Für die Transkription über eine API ist noch kein Anbieter gewählt oder die Adresse "
                    "unvollständig.\n\nBitte in den Einstellungen im Reiter „Transkription“ einen Anbieter "
                    "wählen (bei Microsoft Azure außerdem den Namen der eigenen Ressource in der Adresse "
                    "eintragen).",
                )
                return
            api_key = self._verwendbarer_api_schluessel("transkription")
            if not api_key:
                show_error(
                    self,
                    "Kein API-Schlüssel",
                    "Bitte zuerst in den Einstellungen einen API-Schlüssel für die Transkription hinterlegen.",
                )
                return
            transcribe_chunk_fn = functools.partial(
                api_transcription_service.transcribe_chunk_via_api,
                endpoint_url=config["api_transkription_endpunkt"],
                api_key=api_key,
                model_name=config["api_transkription_modell"],
                provider_name=config["api_transkription_anbieter"],
                diarization_enabled=self.diarization_checkbox.isChecked(),
            )
            diarize_fn = api_transcription_service.diarize_via_api_speakers

        settings = pipeline_service.PipelineSettings(
            source_path=self._source_path,
            output_dir=self._output_dir,
            language=self.language_combo.currentData(),
            min_speakers=self.min_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            max_speakers=self.max_speakers_spin.value() if self.limit_speakers_checkbox.isChecked() else None,
            allow_download=not self.offline_checkbox.isChecked(),
            resume_mode=self.resume_combo.currentData(),
            whisper_model=ermittle_whisper_modell(config),
            enable_diarization=self.diarization_checkbox.isChecked(),
            # Bei einer Geraeteaufnahme sind die ersten Bloecke schon waehrend der Aufnahme
            # transkribiert worden (leer fuer jede andere Datei). Nicht ueber die API (dort liefert der
            # Endpunkt auch die Sprecher; lokale Live-Segmente haetten keine) und nicht bei "neu beginnen".
            vorab_live=(
                self._live.vorab_fuer(self._source_path)
                if self.transkription_lokal_radio.isChecked() and self.resume_combo.currentData() != "neu_beginnen"
                else None
            ),
        )

        self._set_controls_running(True)
        self.cancel_button.setEnabled(True)
        self.preview_edit.clear()
        self.speaker_table.setRowCount(0)
        self.apply_names_button.setEnabled(False)
        self.status_label.setText("Transkription wird gestartet …")
        self.transcription_status_label.setText("läuft")

        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self._transcription_worker = TranscriptionWorker(
            settings, self, transcribe_chunk_fn=transcribe_chunk_fn, diarize_fn=diarize_fn
        )
        self._transcription_worker.stage_changed.connect(self._on_transcription_stage_changed)
        self._transcription_worker.chunk_progress.connect(self._on_chunk_progress)
        self._transcription_worker.overall_progress.connect(self._on_overall_progress)
        self._transcription_worker.preview_updated.connect(self.preview_edit.setPlainText)
        self._transcription_worker.log_message.connect(self._on_log_message)
        self._transcription_worker.finished_ok.connect(self._on_transcription_finished_ok)
        self._transcription_worker.failed.connect(self._on_transcription_failed)
        self._transcription_worker.cancelled.connect(self._on_transcription_cancelled)
        self._transcription_worker.finished.connect(lambda: self._set_controls_running(False))
        self._transcription_worker.start()

    @staticmethod
    def _lokale_laufzeitumgebung_verfuegbar() -> bool:
        """Ist bereits eine Laufzeitumgebung mit den schweren ML-Paketen
        vorhanden? Weder in der gebauten EXE noch im Quellcode-Betrieb sind
        Torch/faster-whisper/pyannote von vornherein dabei -- 'bootstrap.py'
        richtet sie nur ein, wenn der gespeicherte Modus beim Programmstart
        bereits "lokal" war (siehe dort). Da dieser Code hier erst NACH
        'bootstrap.ensure_runtime_and_relaunch()' laeuft, ist zu diesem
        Zeitpunkt entweder die vorbereitete Umgebung bereits aktiv (dann ist
        'faster_whisper' tatsaechlich importierbar), oder die Einrichtung
        wurde uebersprungen (dann eben nicht) -- eine einfache
        Import-Pruefung deckt beide Faelle korrekt ab, ganz ohne
        Sonderbehandlung fuer 'sys.frozen'. Ohne diese Pruefung wuerde ein
        Wechsel auf "Lokal" mitten in der Sitzung erst tief in der Pipeline
        mit einem kryptischen Fehler scheitern."""
        return importlib.util.find_spec("faster_whisper") is not None

    def _chat_api_schluessel(self) -> str:
        """API-Schluessel des Chatbots: der eigene, sonst derselbe wie bei der
        Nachbearbeitung (dort wiederum eigener oder der der Transkription)."""
        konfig = app_config.load_config()
        if konfig["chatbot_api_eigener_schluessel"]:
            name = "chatbot"
        elif konfig["api_nachbearbeitung_eigener_schluessel"]:
            name = "nachbearbeitung"
        else:
            name = "transkription"
        return self._verwendbarer_api_schluessel(name) or ""

    def _verwendbarer_api_schluessel(self, schluessel_name: str) -> str | None:
        """Gemerkter Schluessel, sonst der nur fuer diese Sitzung eingegebene.

        Die Abfrage des Anmeldeinformationsspeichers MUSS abgesichert sein:
        Im lokalen Modus laeuft die Anwendung in der von 'bootstrap.py'
        verwalteten Laufzeitumgebung, und die enthaelt 'keyring' nicht
        (siehe 'requirements-laufzeit.txt'). Ungeschuetzt wuerde
        'load_api_key' dort mit 'SecretStoreUnavailableError' abbrechen --
        und zwar noch VOR dem Rueckgriff auf den Sitzungsschluessel, den der
        Anwender eben in den Einstellungen eingetippt hat. Genau derselbe
        Schutz steckt im Einstellungsdialog
        ('_gespeicherten_schluessel_laden')."""
        try:
            gemerkt = secret_store.load_api_key(schluessel_name)
        except secret_store.SecretStoreUnavailableError:
            gemerkt = None
        return gemerkt or self._session_api_keys.get(schluessel_name)

    def _cancel_transcription(self) -> None:
        if self._transcription_worker is not None:
            self._transcription_worker.request_cancel()
            self.status_label.setText("Abbruch angefordert -- wird nach dem aktuellen Chunk wirksam.")
            self.cancel_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Start / Abbruch / Fortschritt: Nachbearbeitung
    # ------------------------------------------------------------------
    def _start_protocol(self) -> None:
        if self._selected_transcript_path is None:
            self._protokoll_start_scheitert(
                "Kein Transkript ausgewählt",
                "Bitte zuerst eine Transkription durchführen oder ein vorhandenes Transkript auswählen.",
            )
            return
        if not self._selected_transcript_path.is_file():
            self._protokoll_start_scheitert(
                "Transkript nicht gefunden", f"Die Datei wurde nicht gefunden:\n{self._selected_transcript_path}"
            )
            return
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            probe_file = self._output_dir / ".schreibtest.tmp"
            probe_file.write_text("test", encoding="utf-8")
            probe_file.unlink()
        except OSError as error:
            self._protokoll_start_scheitert("Ausgabeordner ungültig", f"In den Ausgabeordner kann nicht geschrieben werden:\n{error}")
            return

        # Die automatische Verarbeitung einer Geraeteaufnahme fragt nicht: Niemand sitzt davor, und ihr Ergebnis
        # ersetzt die Anzeige nicht (siehe '_on_protocol_finished_ok') -- die Bearbeitung bleibt erhalten.
        if self._automatik is None and not self._ungespeicherte_aenderungen_geklaert("ein neues Ergebnis erzeugt wird"):
            return

        # Ein leerer Systemprompt ist erlaubt: Dann fasst das Modell so
        # zusammen, wie es fuer den Inhalt am sinnvollsten ist. Ist einer
        # eingetragen, bestimmt er allein, was geschieht.
        systemprompt_text = (
            self._systemprompt_automatik
            if self._systemprompt_automatik is not None
            else self.systemprompt_editor.toPlainText()
        ).strip()

        config = app_config.load_config()
        protocol_generate_fn: ProtocolGenerateFn | None = None
        # Die Zwischenstaende gelten je Modell; ueber die API zaehlen
        # Endpunkt und API-Modell, lokal das Ollama-Modell (None).
        modell_kennung: str | None = None
        if self.nachbearbeitung_api_radio.isChecked():
            if not (
                api_anbieter.adresse_vollstaendig(config["api_nachbearbeitung_endpunkt"])
                and config["api_nachbearbeitung_modell"]
            ):
                self._protokoll_start_scheitert(
                    "Kein Anbieter gewählt",
                    "Für die Nachbearbeitung über eine API ist noch kein Anbieter gewählt oder die Adresse "
                    "unvollständig.\n\nBitte in den Einstellungen im Reiter „Nachbearbeitung“ einen Anbieter "
                    "wählen (bei Microsoft Azure außerdem den Namen der eigenen Ressource in der Adresse "
                    "eintragen).",
                )
                return
            eigener_schluessel = config["api_nachbearbeitung_eigener_schluessel"]
            schluessel_name = "nachbearbeitung" if eigener_schluessel else "transkription"
            api_key = self._verwendbarer_api_schluessel(schluessel_name)
            if not api_key:
                self._protokoll_start_scheitert(
                    "Kein API-Schlüssel",
                    "Bitte zuerst in den Einstellungen einen API-Schlüssel für die Nachbearbeitung hinterlegen.",
                )
                return
            api_modell = config["api_nachbearbeitung_modell"]
            api_endpunkt = config["api_nachbearbeitung_endpunkt"]

            protocol_generate_fn = api_auswertung_funktion(api_endpunkt, api_modell, api_key)
            modell_kennung = f"api:{api_endpunkt}|{api_modell}"

        if not self.nachbearbeitung_api_radio.isChecked():
            lokales_modell = config["ollama_modell"] or ollama_service.DEFAULT_MODEL
            if ollama_service.modell_fehlt(lokales_modell):
                self._protokoll_start_scheitert(
                    "Ollama-Modell fehlt",
                    f"Das Modell '{lokales_modell}' ist bei Ollama nicht installiert.\n\n"
                    "Bitte in den Einstellungen unter „Nachbearbeitung“ auf „Jetzt herunterladen“ klicken "
                    "oder ein anderes, bereits installiertes Modell wählen.",
                )
                return

        settings = pipeline_service.ProtocolSettings(
            transcript_json_path=self._selected_transcript_path,
            output_dir=self._output_dir,
            ollama_model=config["ollama_modell"] or ollama_service.DEFAULT_MODEL,
            # Der im Fenster gewaehlte/bearbeitete Text wird direkt
            # mitgegeben und NICHT nach 'get_system_prompt_file()'
            # geschrieben: Was nur fuer einen Lauf gilt, gehoert nicht in
            # die gespeicherte Einstellung.
            system_prompt=systemprompt_text,
            protokoll_modell_kennung=modell_kennung,
        )
        if self._automatik is not None:
            # Kurze Abschnitte: nach dem Ende bleibt hoechstens der letzte offen.
            settings.abschnitt_sekunden = chunking_service.auswertungs_abschnitt(
                app_config.load_config().get("geraete_live_abschnitt_sekunden")
            )
        if self._automatik is not None and app_config.load_config().get("geraete_live_auswertung_vorab", True):
            # Automatische Auswertung einer Geraeteaufnahme: Schon waehrend der Aufnahme berechnete Teilergebnisse
            # uebernehmen. Dazu bekommt das Modell hier wie dort den Text ohne Sprecherangaben (die Sprechertrennung
            # entsteht erst am Ende); sonst passten die Eingaben nicht zusammen.
            aufnahme = self._automatik[2]
            settings.ohne_sprecher = True
            settings.vorab_auswertung = lambda: self._live.auswertung_fuer(aufnahme, warten=VORAB_AUSWERTUNG_WARTEN)

        # Das Ergebnis gehoert zu diesem Transkript, auch wenn danach ein
        # anderes ausgewaehlt wird.
        self._nachbearbeitung_transkript = self._selected_transcript_path
        self._nachbearbeitung_laeuft = True
        self._set_controls_running(True)
        self.protocol_cancel_button.setEnabled(True)
        self.status_label.setText("Nachbearbeitung wird gestartet …")
        self.protocol_status_label.setText("läuft")

        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self._protocol_worker = ProtocolWorker(settings, self, protocol_generate_fn=protocol_generate_fn)
        self._protocol_worker.stage_changed.connect(self._on_protocol_stage_changed)
        self._protocol_worker.overall_progress.connect(self._on_overall_progress)
        self._protocol_worker.log_message.connect(self._on_log_message)
        self._protocol_worker.finished_ok.connect(self._on_protocol_finished_ok)
        self._protocol_worker.failed.connect(self._on_protocol_failed)
        self._protocol_worker.cancelled.connect(self._on_protocol_cancelled)
        self._protocol_worker.finished.connect(lambda: self._set_controls_running(False))
        self._protocol_worker.start()

    def _cancel_protocol(self) -> None:
        if self._protocol_worker is not None:
            self._protocol_worker.request_cancel()
            self.status_label.setText("Abbruch angefordert …")
            self.protocol_cancel_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Gemeinsame Fortschrittsanzeigen
    # ------------------------------------------------------------------
    def _set_controls_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.protocol_start_button.setEnabled(not running)
        if not running:
            self.cancel_button.setEnabled(False)
            self.protocol_cancel_button.setEnabled(False)
            self._elapsed_timer.stop()
            # Transkription und Nachbearbeitung laufen nie gleichzeitig.
            self._nachbearbeitung_laeuft = False
            # Auch eine Freigabe vom Geraet kann warten (sie kam, waehrend etwas anderes lief).
            if self._geraete_arbeit_wartet() and self._automatik is None:
                QTimer.singleShot(0, self._naechste_geraete_aufnahme)
        self._protocol_result_sperre_anwenden()

    def _update_elapsed_label(self) -> None:
        if self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        self.elapsed_label.setText(format_duration_human(elapsed))
        self._update_remaining_estimate(elapsed)

    def _update_remaining_estimate(self, elapsed: float) -> None:
        current, total = self._chunk_progress
        if current <= 0 or total <= 0:
            self.remaining_label.setText("--")
            return
        per_chunk = elapsed / current
        remaining_chunks = max(0, total - current)
        self.remaining_label.setText(format_duration_human(per_chunk * remaining_chunks))

    def _on_transcription_stage_changed(self, key: str, detail: str) -> None:
        self.status_label.setText(detail)
        self.transcription_status_label.setText(detail)
        self._automatik_status(live_service.TRANSKRIPTION, detail=detail)

    def _on_protocol_stage_changed(self, key: str, detail: str) -> None:
        self.status_label.setText(detail)
        self.protocol_status_label.setText(detail)
        self._automatik_status(live_service.AUSWERTUNG, detail=detail)
        if key == "protokoll_fehlgeschlagen":
            self.protocol_status_label.setToolTip(detail)

    def _on_chunk_progress(self, current: int, total: int) -> None:
        self._chunk_progress = (current, total)
        self.chunk_progress_bar.setMaximum(max(total, 1))
        self.chunk_progress_bar.setValue(current)
        self.chunk_progress_bar.setFormat(f"Chunk {current} von {total}")

    def _on_overall_progress(self, fraction: float) -> None:
        self.overall_progress_bar.setValue(round(fraction * 100))
        # Das Geraet sieht einen Balken fuer beide Schritte: erst die Transkription, dann die Auswertung.
        if self._automatik_phase == live_service.AUSWERTUNG:
            self._automatik_status(live_service.AUSWERTUNG, fortschritt=0.5 + 0.5 * fraction)
        else:
            self._automatik_status(live_service.TRANSKRIPTION, fortschritt=0.5 * fraction)

    def _on_log_message(self, message: str) -> None:
        self.status_label.setToolTip(message)

    def _on_transcription_finished_ok(self, result: pipeline_service.TranscriptionResult) -> None:
        self._last_transcription_result = result
        self._populate_speaker_table(result)
        self._set_transcript_path(result.export_paths.json)
        self.status_label.setText("Transkription abgeschlossen.")
        if self._automatik is None:  # eine Geraeteaufnahme im Hintergrund holt niemanden von seiner Seite weg
            self._show_page(self.SEITE_ERGEBNIS)
        elif self._automatik_rueckfrage:
            self._ergebnisse_merken(transkript=result.export_paths.json)
            self._automatik_wartet_auf_freigabe(result.export_paths.json)
            return
        else:
            self._ergebnisse_merken(transkript=result.export_paths.json)
        if self._protokoll_nach_transkription and self._transcription_worker is not None:
            # Erst starten, wenn der Transkriptions-Thread beendet ist: Dessen
            # 'finished' schaltet die Bedienelemente wieder frei und stoppt den
            # Zeitgeber - das wuerde sonst die eben gestartete Nachbearbeitung
            # betreffen. Slots laufen in der Reihenfolge des Verbindens.
            self._transcription_worker.finished.connect(self._start_protocol_after_transcription)
            # Meist ist der Thread hier aber SCHON beendet: Beide Signale kommen
            # als eingereihte Ereignisse aus dem Arbeits-Thread, und 'finished'
            # wurde ausgeloest, bevor die Verbindung oben bestand -- sie greift
            # dann nie, und das Protokoll startete nicht (gefunden vom
            # Oberflaechentest in tests/e2e). Dann nach den bereits eingereihten
            # Slots starten; ein doppelter Aufruf ist harmlos (siehe dort).
            if self._transcription_worker.isFinished():
                QTimer.singleShot(0, self._start_protocol_after_transcription)
            return
        QMessageBox.information(
            self,
            "Transkription abgeschlossen",
            f"Ausgabedateien wurden erstellt in:\n{result.export_paths.txt.parent}\n\n"
            "Die Nachbearbeitung ist ein separater Schritt -- sie kann jetzt fuer dieses "
            "oder jederzeit fuer ein anderes Transkript gestartet werden.",
        )

    def _word_neu_erzeugen(self, transkript_json: Path) -> None:
        """Die automatische Word-Datei mit den neuen Sprechernamen neu schreiben (still: scheitert das, bleibt der Rest gueltig).

        Das Protokoll kommt nur hinein, wenn das angezeigte Ergebnis aus genau
        diesem Transkript entstand -- sonst landete ein fremdes Protokoll in
        der Word-Datei (und ueberschriebe die des anderen Transkripts)."""
        protokoll = self._protokoll_zum_transkript(transkript_json)
        try:
            dokument_export_service.automatisches_word(transkript_json, protokoll)
        except dokument_export_service.ExportFehler as fehler:
            self._on_log_message(f"Die Word-Datei wurde nicht aktualisiert: {fehler}")

    def _export_oeffnen(self, _checked: bool = False) -> None:
        """Dialog "Exportieren": gewaehltes Transkript, dazu das Protokoll, das
        unter "Nachbearbeitung" angezeigt (und ggf. bearbeitet) wird -- ohne
        angezeigtes das des letzten Laufs, falls es eines gibt (im Dialog
        austauschbar)."""
        transkript = self._selected_transcript_path
        if transkript is None or not transkript.is_file():
            show_error(
                self,
                "Kein Transkript",
                "Es ist noch kein Transkript vorhanden. Bitte zuerst eine Aufnahme transkribieren oder "
                "unter „Nachbearbeitung“ ein Transkript auswählen.",
            )
            return
        if not self._ungespeicherte_aenderungen_geklaert("exportiert wird"):
            return
        protokoll = None
        kandidat = None
        if self._protocol_result_paths is not None:
            kandidat = self._protocol_result_paths[0]
        elif self._last_protocol_result is not None and self._last_protocol_result.protocol_paths is not None:
            kandidat = self._last_protocol_result.protocol_paths[0]
        if kandidat is not None and kandidat.is_file():
            protokoll = kandidat
        ExportDialog(transkript, protokoll, self._output_dir, QT_SCHREIBER, self).exec()

    def _start_protocol_after_transcription(self) -> None:
        if self._protokoll_nach_transkription:
            self._protokoll_nach_transkription = False
            self._start_protocol()

    def _on_transcription_failed(self, message: str) -> None:
        self._protokoll_nach_transkription = False
        self._automatik_beenden(live_service.FEHLER, "Die Transkription ist fehlgeschlagen.")
        self.status_label.setText("Fehler bei der Transkription.")
        show_error(self, "Transkription fehlgeschlagen", message)

    def _on_transcription_cancelled(self) -> None:
        self._protokoll_nach_transkription = False
        self._automatik_beenden(live_service.FEHLER, "Die Transkription wurde abgebrochen.")
        self.status_label.setText("Transkription abgebrochen.")

    def _on_protocol_finished_ok(self, result: pipeline_service.ProtocolResult) -> None:
        self._last_protocol_result = result
        if result.protokoll_fehler:
            if self._automatik is not None:
                self._automatik_beenden(live_service.FEHLER, "Die Auswertung ist fehlgeschlagen.")
                self.status_label.setText(f"Automatische Auswertung fehlgeschlagen: {result.protokoll_fehler}")
                return
            self.status_label.setText("Nachbearbeitung fehlgeschlagen.")
            QMessageBox.warning(
                self,
                "Nachbearbeitung fehlgeschlagen",
                "Die Protokollauswertung ist fehlgeschlagen, es wurde keine "
                "Protokolldatei geschrieben:\n"
                f"{result.protokoll_fehler}\n\n"
                "Das Transkript bleibt erhalten. Die Nachbearbeitung lässt sich erneut starten.",
            )
            return
        self.status_label.setText("Nachbearbeitung abgeschlossen.")
        protocol_paths = result.protocol_paths
        if self._automatik is not None:
            # Ohne Rueckfrage-Fenster: Niemand sitzt davor, das Geraet bekommt die Meldung.
            if protocol_paths is not None:
                self._ergebnisse_merken(zusammenfassung=protocol_paths[1])
            self._automatik_beenden(
                live_service.FERTIG,
                "Zusammenfassung fertig" if self._automatik_rueckfrage else "Transkription erfolgreich",
            )
            return
        if protocol_paths is None:
            return
        try:
            ergebnis_text = protocol_paths[1].read_text(encoding="utf-8")
        except OSError:
            ergebnis_text = ""
        self._protocol_result_anzeigen(ergebnis_text, protocol_paths, self._nachbearbeitung_transkript)
        self._show_page(self.SEITE_NACHBEARBEITUNG)
        QMessageBox.information(
            self,
            "Nachbearbeitung abgeschlossen",
            f"Protokolldateien wurden erstellt in:\n{protocol_paths[0].parent}\n\n"
            "Das Ergebnis steht unten auf der Seite „Nachbearbeitung“ und lässt sich dort noch bearbeiten.",
        )

    def _on_protocol_failed(self, message: str) -> None:
        self._automatik_beenden(live_service.FEHLER, "Die Auswertung ist fehlgeschlagen.")
        self.status_label.setText("Fehler bei der Nachbearbeitung.")
        show_error(self, "Nachbearbeitung fehlgeschlagen", message)

    def _on_protocol_cancelled(self) -> None:
        self._automatik_beenden(live_service.FEHLER, "Die Auswertung wurde abgebrochen.")
        self.status_label.setText("Nachbearbeitung abgebrochen.")

    # ------------------------------------------------------------------
    # Sprechertabelle
    # ------------------------------------------------------------------
    def _populate_speaker_table(self, result: pipeline_service.TranscriptionResult) -> None:
        data = json.loads(result.export_paths.json.read_text(encoding="utf-8"))
        entries = data.get("sprecher_zuordnung", [])
        # Stimmabdruecke dieses Laufs gibt es nur im lokalen Modus.
        arbeitsordner = getattr(result, "work_dir", None)
        self._speaker_embeddings = (
            sprecherprofil_service.lade_lauf_embeddings(arbeitsordner) if arbeitsordner else {}
        )
        vorschlaege = sprecherprofil_service.finde_vorschlaege(
            self._speaker_embeddings, sprecherprofil_service.lade_profile()
        )
        self.speaker_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            id_item = QTableWidgetItem(entry["sprecher_id"])
            id_item.setFlags(id_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 0, id_item)

            segments_item = QTableWidgetItem(str(entry["anzahl_segmente"]))
            segments_item.setFlags(segments_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 1, segments_item)

            duration_item = QTableWidgetItem(format_duration_human(entry["sprechdauer_sekunden"]))
            duration_item.setFlags(duration_item.flags() & ~self._editable_flag())
            self.speaker_table.setItem(row, 2, duration_item)

            self.speaker_table.setItem(row, 3, QTableWidgetItem(entry["anzeigename"]))
            self.speaker_table.setCellWidget(row, 4, self._build_voice_buttons(entry["sprecher_id"]))
            self.speaker_table.setCellWidget(
                row, 5, self._build_profile_cell(entry["sprecher_id"], vorschlaege.get(entry["sprecher_id"]))
            )

        self.apply_names_button.setEnabled(len(entries) > 0)

    def _build_voice_buttons(self, sprecher_id: str) -> QWidget:
        """Schaltflaechen 'Anhoeren' und 'Exportieren' fuer eine Tabellenzeile."""
        zelle = QWidget(self.speaker_table)
        layout = QHBoxLayout(zelle)
        layout.setContentsMargins(2, 0, 2, 0)
        hoeren = QPushButton("▶ Anhören", zelle)
        hoeren.setToolTip("Spielt eine kurze Hörprobe dieses Sprechers ab.")
        hoeren.clicked.connect(functools.partial(self._listen_to_speaker, sprecher_id))
        exportieren = QPushButton("Exportieren …", zelle)
        exportieren.setToolTip("Speichert Audio und Text dieses Sprechers als Dateien.")
        exportieren.clicked.connect(functools.partial(self._export_speaker, sprecher_id))
        layout.addWidget(hoeren)
        layout.addWidget(exportieren)
        return zelle

    def _build_profile_cell(self, sprecher_id: str, vorschlag: dict[str, Any] | None) -> QWidget:
        """Zelle 'Profil': Namensvorschlag aus einem gespeicherten Profil oder
        'Als Profil speichern'. Uebernommen wird nichts ohne Klick."""
        zelle = QWidget(self.speaker_table)
        layout = QHBoxLayout(zelle)
        layout.setContentsMargins(2, 0, 2, 0)
        if vorschlag is not None:
            fragezeichen = "" if vorschlag["sicher"] else "?"
            aehnlichkeit = f"{vorschlag['aehnlichkeit']:.2f}".replace(".", ",")
            layout.addWidget(QLabel(f"{vorschlag['name']}{fragezeichen} ({aehnlichkeit})", zelle))
            uebernehmen = QPushButton("Vorschlag übernehmen", zelle)
            uebernehmen.clicked.connect(
                functools.partial(self._accept_profile_suggestion, sprecher_id, vorschlag["name"])
            )
            layout.addWidget(uebernehmen)
        if sprecher_id in self._speaker_embeddings:
            speichern = QPushButton("Als Profil speichern", zelle)
            speichern.setToolTip("Merkt sich die Stimme dieses Sprechers für spätere Aufnahmen.")
            speichern.clicked.connect(functools.partial(self._save_speaker_profile, sprecher_id))
            layout.addWidget(speichern)
        elif vorschlag is None:
            layout.addWidget(QLabel("–", zelle))
        return zelle

    def _row_of_speaker(self, sprecher_id: str) -> int | None:
        for row in range(self.speaker_table.rowCount()):
            zelle = self.speaker_table.item(row, 0)
            if zelle is not None and zelle.text() == sprecher_id:
                return row
        return None

    def _accept_profile_suggestion(self, sprecher_id: str, name: str, _checked: bool = False) -> None:
        row = self._row_of_speaker(sprecher_id)
        if row is not None:
            self.speaker_table.setItem(row, 3, QTableWidgetItem(name))

    def _save_speaker_profile(self, sprecher_id: str, _checked: bool = False) -> None:
        row = self._row_of_speaker(sprecher_id)
        embedding = self._speaker_embeddings.get(sprecher_id)
        if row is None or not embedding:
            return
        zelle = self.speaker_table.item(row, 3)
        name = zelle.text().strip() if zelle is not None else ""
        if not name or name.startswith("Sprecher "):
            name, ok = QInputDialog.getText(self, "Profil speichern", "Name der Person:")
            if not ok:
                return
        antwort = QMessageBox.question(
            self,
            "Stimmabdruck speichern?",
            f"Der Stimmabdruck von „{name.strip()}“ wird ausschließlich lokal auf diesem Rechner "
            "gespeichert und für die Wiedererkennung in späteren Aufnahmen benutzt. Ein Stimmabdruck ist "
            "ein biometrisches Datum - bitte nur mit Einverständnis der Person speichern. "
            "Unter „Sprecherprofile verwalten“ lässt er sich jederzeit löschen.\n\nSpeichern?",
        )
        if antwort != QMessageBox.Yes:
            return
        try:
            sprecherprofil_service.profil_speichern(name, embedding)
        except (sprecherprofil_service.ProfilFehler, OSError) as error:
            show_error(self, "Profil nicht gespeichert", str(error))
            return
        self.speaker_table.setItem(row, 3, QTableWidgetItem(name.strip()))
        QMessageBox.information(self, "Profil gespeichert", f"„{name.strip()}“ wird künftig wiedererkannt.")

    def _manage_speaker_profiles(self) -> None:
        SprecherprofileDialog(self).exec()

    def _listen_to_speaker(self, sprecher_id: str, _checked: bool = False) -> None:
        if self._last_transcription_result is None:
            return
        result = self._last_transcription_result
        ziel = result.work_dir / f"hoerprobe_{sprecher_id}.wav"
        try:
            sprecher_export_service.hoerprobe_erstellen(result.export_paths.json, sprecher_id, ziel)
        except (sprecher_export_service.SprecherExportFehler, RuntimeError, OSError) as error:
            show_error(self, "Hörprobe nicht möglich", str(error))
            return
        # Mit dem Standardprogramm des Systems abspielen: keine zusaetzlichen
        # Qt-Module noetig, und die Wiedergabe laeuft unabhaengig vom Fenster.
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ziel)))

    def _export_speaker(self, sprecher_id: str, _checked: bool = False) -> None:
        if self._last_transcription_result is None:
            return
        result = self._last_transcription_result
        start = str(result.export_paths.json.parent)
        ordner = QFileDialog.getExistingDirectory(self, "Zielordner für den Sprecher-Export wählen", start)
        if not ordner:
            return
        try:
            wav, txt = sprecher_export_service.sprecher_exportieren(
                result.export_paths.json, sprecher_id, Path(ordner)
            )
        except (sprecher_export_service.SprecherExportFehler, RuntimeError, OSError) as error:
            show_error(self, "Export nicht möglich", str(error))
            return
        QMessageBox.information(
            self, "Sprecher exportiert", f"Audio und Text wurden gespeichert:\n{wav}\n{txt}"
        )

    @staticmethod
    def _editable_flag():
        return Qt.ItemIsEditable

    def _apply_speaker_names(self) -> None:
        if self._last_transcription_result is None:
            return
        overrides: dict[str, str] = {}
        for row in range(self.speaker_table.rowCount()):
            id_zelle = self.speaker_table.item(row, 0)
            namens_zelle = self.speaker_table.item(row, 3)
            if id_zelle is None or namens_zelle is None:
                continue
            name = namens_zelle.text().strip()
            if name:
                overrides[id_zelle.text()] = name
        try:
            new_paths = export_service.reexport_with_new_names(
                self._last_transcription_result.export_paths.json, overrides
            )
        except OSError as error:
            show_error(self, "Export fehlgeschlagen", f"Die Ausgabedateien konnten nicht neu erzeugt werden:\n{error}")
            return
        self.preview_edit.setPlainText(new_paths.txt.read_text(encoding="utf-8")[:20000])
        self._word_neu_erzeugen(new_paths.json)
        QMessageBox.information(
            self, "Ausgaben aktualisiert", f"TXT/JSON/SRT/VTT wurden mit den neuen Namen neu erzeugt:\n{new_paths.txt.parent}"
        )
