"""Aus Einstellungen und Wunsch wird ein startbereiter Pipeline-Lauf.

Welcher Weg gilt (lokal oder API), welche Funktionen die Pipeline bekommt,
welcher Schluessel gebraucht wird und was vorher geprueft werden muss -- das
stand bisher in ``MainWindow._start_transcription``/``_start_protocol`` und
las Knoepfe aus. Hier bekommt es einen :class:`TranskriptionsWunsch` bzw.
:class:`AuswertungsWunsch` und die gespeicherte Konfiguration.

Scheitert eine Pruefung, gibt es einen :class:`Ablauffehler` mit Titel und
Text fuer den Anwender und einem ``code``, an dem die Oberflaeche erkennt,
wohin sie den Anwender schicken kann (Einstellungen, lokale Einrichtung).
"""

from __future__ import annotations

import functools
import importlib.util
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from protokoll_assistent.services import (
    api_anbieter,
    api_protocol_service,
    api_transcription_service,
    model_service,
    ollama_service,
    pipeline_service,
    secret_store,
)

TranscribeFn = Callable[[Path], list[dict[str, Any]]]
DiarizeFn = Callable[[Path, int | None, int | None], list[dict[str, Any]]]
GenerateFn = Callable[[str, str], str]

# Codes fuer die Oberflaeche: Sie kann daraufhin z. B. die passende Einstellungsseite oeffnen.
CODE_EINGABE = "eingabe"
CODE_EINSTELLUNGEN = "einstellungen"
CODE_SCHLUESSEL = "schluessel"
CODE_LOKALE_EINRICHTUNG = "lokale_einrichtung"
CODE_MODELL_FEHLT = "modell_fehlt"
CODE_BELEGT = "belegt"

# Schluessel aus Umgebungsvariablen (Servermodus/Container): VERMERK_API_SCHLUESSEL_TRANSKRIPTION usw.
UMGEBUNG_PRAEFIX = "VERMERK_API_SCHLUESSEL_"


BEREICH_TRANSKRIPTION = "transkription"
BEREICH_ZUSAMMENFASSUNG = "zusammenfassung"


class Ablauffehler(Exception):
    """Texte fuer Menschen, nicht fuer Techniker: kein "API", kein "Ollama", kein "Endpunkt"."""

    def __init__(self, titel: str, text: str, code: str = CODE_EINGABE, bereich: str = ""):
        super().__init__(text)
        self.titel = titel
        self.text = text
        self.code = code
        self.bereich = bereich

    def als_dict(self) -> dict[str, str]:
        return {"titel": self.titel, "text": self.text, "code": self.code, "bereich": self.bereich}


class Schluesselablage:
    """API-Schluessel: gemerkt (Anmeldeinformationsverwaltung), aus der Umgebung oder nur fuer diese Sitzung.

    Die Abfrage des Anmeldeinformationsspeichers ist abgesichert: Im lokalen Modus laeuft das Programm in der
    von 'bootstrap.py' verwalteten Laufzeitumgebung, und dort fehlt 'keyring' unter Umstaenden. Dann gilt eben
    nur der Sitzungsschluessel oder die Umgebungsvariable."""

    def __init__(self, umgebung: dict[str, str] | None = None):
        self._sitzung: dict[str, str] = {}
        self._umgebung = umgebung if umgebung is not None else os.environ

    def fuer_sitzung(self, name: str, wert: str) -> None:
        if wert:
            self._sitzung[name] = wert
        else:
            self._sitzung.pop(name, None)

    def hole(self, name: str) -> str | None:
        try:
            gemerkt = secret_store.load_api_key(name)
        except secret_store.SecretStoreUnavailableError:
            gemerkt = None
        return gemerkt or self._sitzung.get(name) or self._umgebung.get(UMGEBUNG_PRAEFIX + name.upper()) or None

    def vorhanden(self, name: str) -> bool:
        return bool(self.hole(name))

    def name_fuer_nachbearbeitung(self, konfiguration: dict[str, Any]) -> str:
        return "nachbearbeitung" if konfiguration.get("api_nachbearbeitung_eigener_schluessel") else "transkription"

    def name_fuer_chat(self, konfiguration: dict[str, Any]) -> str:
        """Der eigene Chat-Schluessel, sonst derselbe wie bei der Nachbearbeitung (dort eigener oder der der
        Transkription)."""
        if konfiguration.get("chatbot_api_eigener_schluessel"):
            return "chatbot"
        return self.name_fuer_nachbearbeitung(konfiguration)


def ermittle_whisper_modell(konfiguration: dict[str, Any]) -> str:
    """Das Whisper-Modell fuer den lokalen Modus: das eingestellte, sonst der eingebaute Standard."""
    gewaehlt = konfiguration.get("whisper_modell")
    return str(gewaehlt) if gewaehlt else model_service.WHISPER_MODEL_NAME


def api_auswertung_funktion(endpunkt: str, modell: str, api_key: str) -> GenerateFn:
    """``(Prompt, Systemprompt) -> Antwort`` ueber ein API-Modell.

    Uebersetzt 'ApiProtocolError' in 'OllamaError': 'pipeline_service.run_protocol' behandelt nur diesen
    gnaedig (Fehler als 'protokoll_fehler', Transkript bleibt erhalten). Ein durchgereichter 'ApiProtocolError'
    (HTTP 401, Endpunkt nicht erreichbar) landete sonst als nichtssagender "Unerwarteter Fehler"."""

    def anfrage(prompt: str, system: str) -> str:
        try:
            return api_protocol_service.generate_text(prompt, system, model=modell, endpoint_url=endpunkt, api_key=api_key)
        except api_protocol_service.ApiProtocolError as fehler:
            raise ollama_service.OllamaError(str(fehler)) from fehler

    return anfrage


def lokale_laufzeit_verfuegbar() -> bool:
    """Ist die Laufzeitumgebung mit den schweren ML-Paketen aktiv? (siehe 'bootstrap.py')"""
    return importlib.util.find_spec("faster_whisper") is not None


def ausgabeordner_pruefen(ordner: Path) -> None:
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        probe = ordner / ".schreibtest.tmp"
        probe.write_text("test", encoding="utf-8")
        probe.unlink()
    except OSError as fehler:
        raise Ablauffehler("Ausgabeordner ungültig", f"In den Ausgabeordner kann nicht geschrieben werden:\n{fehler}") from fehler


# --------------------------------------------------------------------------
# Transkription
# --------------------------------------------------------------------------
@dataclass
class TranskriptionsWunsch:
    quelle: Path
    ausgabe: Path
    sprache: str | None = "de"
    min_sprecher: int | None = None
    max_sprecher: int | None = None
    sprechertrennung: bool = True
    offline: bool = False
    fortsetzen: bool = True
    # Nach der Transkription gleich die Auswertung (Protokoll) anschliessen.
    mit_auswertung: bool = False
    # Schon waehrend einer Geraeteaufnahme transkribierte Segmente (siehe 'live_service'), sonst None.
    vorab_live: dict[str, Any] | None = None


@dataclass
class TranskriptionsLauf:
    einstellungen: pipeline_service.PipelineSettings
    transcribe_fn: TranscribeFn | None
    diarize_fn: DiarizeFn | None
    modus: Literal["lokal", "api"]


def transkription_vorbereiten(
    wunsch: TranskriptionsWunsch,
    konfiguration: dict[str, Any],
    schluessel: Schluesselablage,
    *,
    laufzeit_verfuegbar: Callable[[], bool] = lokale_laufzeit_verfuegbar,
) -> TranskriptionsLauf:
    quelle = wunsch.quelle
    if not quelle.is_file():
        raise Ablauffehler("Datei nicht gefunden", f"Die Datei wurde nicht gefunden:\n{quelle}")
    if quelle.stat().st_size == 0:
        raise Ablauffehler("Datei ist leer", "Die ausgewählte Datei enthält keine Daten.")
    ausgabeordner_pruefen(wunsch.ausgabe)

    modus: Literal["lokal", "api"] = "api" if konfiguration.get("transkription_modus") == "api" else "lokal"
    transcribe_fn: TranscribeFn | None = None
    diarize_fn: DiarizeFn | None = None
    if modus == "lokal" and not laufzeit_verfuegbar():
        raise Ablauffehler(
            "Noch nicht bereit",
            "Für das Umwandeln in Text auf diesem Computer fehlt noch ein Teil. Er wird eingerichtet, wenn Sie "
            "zustimmen – oder Sie wählen in den Einstellungen einen Online-Dienst.",
            CODE_LOKALE_EINRICHTUNG,
            BEREICH_TRANSKRIPTION,
        )
    if modus == "api":
        endpunkt = str(konfiguration.get("api_transkription_endpunkt") or "")
        modell = str(konfiguration.get("api_transkription_modell") or "")
        if not (api_anbieter.adresse_vollstaendig(endpunkt) and modell):
            raise Ablauffehler(
                "Online-Dienst fehlt",
                "Für das Umwandeln in Text ist noch kein Online-Dienst eingerichtet. Bitte in den Einstellungen "
                "unter „Transkription“ einen wählen.",
                CODE_EINSTELLUNGEN,
                BEREICH_TRANSKRIPTION,
            )
        api_key = schluessel.hole("transkription")
        if not api_key:
            raise Ablauffehler(
                "Zugangsschlüssel fehlt",
                "Für den Online-Dienst fehlt noch der Zugangsschlüssel. Bitte in den Einstellungen unter "
                "„Transkription“ eintragen.",
                CODE_SCHLUESSEL,
                BEREICH_TRANSKRIPTION,
            )
        transcribe_fn = functools.partial(
            api_transcription_service.transcribe_chunk_via_api,
            endpoint_url=endpunkt,
            api_key=api_key,
            model_name=modell,
            provider_name=konfiguration.get("api_transkription_anbieter") or "",
            diarization_enabled=wunsch.sprechertrennung,
        )
        diarize_fn = api_transcription_service.diarize_via_api_speakers

    einstellungen = pipeline_service.PipelineSettings(
        source_path=quelle,
        output_dir=wunsch.ausgabe,
        language=wunsch.sprache,
        min_speakers=wunsch.min_sprecher,
        max_speakers=wunsch.max_sprecher,
        allow_download=not wunsch.offline,
        resume_mode="fortsetzen" if wunsch.fortsetzen else "neu_beginnen",
        run_protocol=False,
        whisper_model=ermittle_whisper_modell(konfiguration),
        enable_diarization=wunsch.sprechertrennung,
        # Live-Segmente nur lokal (ueber die API liefert der Endpunkt auch die Sprecher) und nicht bei "neu".
        vorab_live=wunsch.vorab_live if modus == "lokal" and wunsch.fortsetzen else None,
        # Nur die Daten und das Word-Dokument; Text, Untertitel usw. entstehen erst beim Exportieren.
        begleitdateien=False,
    )
    return TranskriptionsLauf(einstellungen, transcribe_fn, diarize_fn, modus)


# --------------------------------------------------------------------------
# Auswertung (Protokoll)
# --------------------------------------------------------------------------
@dataclass
class AuswertungsWunsch:
    transkript: Path
    ausgabe: Path
    # None: der gespeicherte Systemprompt ('get_system_prompt_file'). Leer: frei zusammenfassen.
    systemprompt: str | None = None
    abschnitt_sekunden: float | None = None
    ohne_sprecher: bool = False
    vorab_auswertung: Callable[[], dict[str, dict[str, str]] | None] | None = None


@dataclass
class AuswertungsLauf:
    einstellungen: pipeline_service.ProtocolSettings
    generate_fn: GenerateFn | None
    modus: Literal["lokal", "api"]


def auswertung_vorbereiten(
    wunsch: AuswertungsWunsch,
    konfiguration: dict[str, Any],
    schluessel: Schluesselablage,
    *,
    modell_fehlt: Callable[[str], bool] = ollama_service.modell_fehlt,
) -> AuswertungsLauf:
    if not wunsch.transkript.is_file():
        raise Ablauffehler("Transkript nicht gefunden", f"Die Datei wurde nicht gefunden:\n{wunsch.transkript}")
    ausgabeordner_pruefen(wunsch.ausgabe)

    modus: Literal["lokal", "api"] = "api" if konfiguration.get("nachbearbeitung_modus") == "api" else "lokal"
    generate_fn: GenerateFn | None = None
    # Die Zwischenstaende gelten je Modell: ueber die API zaehlen Endpunkt und Modell, lokal das Ollama-Modell.
    kennung: str | None = None
    lokales_modell = str(konfiguration.get("ollama_modell") or ollama_service.DEFAULT_MODEL)
    if modus == "api":
        endpunkt = str(konfiguration.get("api_nachbearbeitung_endpunkt") or "")
        modell = str(konfiguration.get("api_nachbearbeitung_modell") or "")
        if not (api_anbieter.adresse_vollstaendig(endpunkt) and modell):
            raise Ablauffehler(
                "Online-Dienst fehlt",
                "Für die Zusammenfassung ist noch kein Online-Dienst eingerichtet. Bitte in den Einstellungen "
                "unter „Zusammenfassung“ einen wählen.",
                CODE_EINSTELLUNGEN,
                BEREICH_ZUSAMMENFASSUNG,
            )
        api_key = schluessel.hole(schluessel.name_fuer_nachbearbeitung(konfiguration))
        if not api_key:
            raise Ablauffehler(
                "Zugangsschlüssel fehlt",
                "Für den Online-Dienst fehlt noch der Zugangsschlüssel. Bitte in den Einstellungen unter "
                "„Zusammenfassung“ eintragen.",
                CODE_SCHLUESSEL,
                BEREICH_ZUSAMMENFASSUNG,
            )
        generate_fn = api_auswertung_funktion(endpunkt, modell, api_key)
        kennung = f"api:{endpunkt}|{modell}"
    elif modell_fehlt(lokales_modell):
        raise Ablauffehler(
            "Sprachmodell fehlt",
            "Das Sprachmodell für Zusammenfassungen ist noch nicht geladen. Bitte in den Einstellungen unter "
            "„Zusammenfassung“ herunterladen.",
            CODE_MODELL_FEHLT,
            BEREICH_ZUSAMMENFASSUNG,
        )

    einstellungen = pipeline_service.ProtocolSettings(
        transcript_json_path=wunsch.transkript,
        output_dir=wunsch.ausgabe,
        ollama_model=lokales_modell,
        system_prompt=wunsch.systemprompt.strip() if wunsch.systemprompt is not None else None,
        protokoll_modell_kennung=kennung,
        vorab_auswertung=wunsch.vorab_auswertung,
        ohne_sprecher=wunsch.ohne_sprecher,
        abschnitt_sekunden=wunsch.abschnitt_sekunden,
    )
    return AuswertungsLauf(einstellungen, generate_fn, modus)
