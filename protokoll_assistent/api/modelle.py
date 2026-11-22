"""Datenformen der Programmschnittstelle (daraus entsteht ``openapi.json`` und der TypeScript-Client)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Fehler(BaseModel):
    titel: str
    text: str
    code: str


class Anmeldung(BaseModel):
    """Entweder ``schluessel`` (Zugangsschluessel) oder ``name`` + ``passwort``."""

    schluessel: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=64)
    passwort: str | None = Field(default=None, max_length=512)


class Faehigkeiten(BaseModel):
    lokale_transkription: bool
    mikrofon: bool
    dateipfade: bool
    ordner_oeffnen: bool
    geraete_empfang: bool


class Info(BaseModel):
    version: str
    rolle: str
    angemeldet_als: str
    anzeigename: str
    admin: bool
    mehrbenutzer: bool
    faehigkeiten: Faehigkeiten
    einrichtung_abgeschlossen: bool
    ausgabeordner: str


class Auftrag(BaseModel):
    id: str
    art: str
    titel: str
    herkunft: str
    vorrang: int
    status: str
    erstellt: float
    besitzer: str | None = None
    # Auftrag eines anderen Nutzers (Servermodus): nur Stand und Platz, ohne Inhalt.
    fremd: bool = False
    # Nur in der Antwort auf einen Start: wie viele Auftraege vorher drankommen (0 = sofort).
    platz: int | None = None
    gestartet: float | None = None
    beendet: float | None = None
    stufe: str = ""
    stufe_text: str = ""
    fortschritt: float | None = None
    abschnitt: list[int] | None = None
    vorschau: str = ""
    meldungen: list[str] = []
    ergebnis: dict[str, Any] | None = None
    fehler: str | None = None
    angaben: dict[str, Any] = {}


class Zustand(BaseModel):
    letzte_nummer: int
    auftraege: list[Auftrag]
    empfang: dict[str, Any] | None
    freigaben: list[dict[str, str]]


class TranskriptionAnfrage(BaseModel):
    quelle: str = Field(min_length=1, description="Pfad der Audio-/Videodatei (auf dem Rechner des Dienstes)")
    sprache: str | None = "de"
    min_sprecher: int | None = Field(default=None, ge=1, le=30)
    max_sprecher: int | None = Field(default=None, ge=1, le=30)
    sprechertrennung: bool = True
    offline: bool = False
    fortsetzen: bool = True
    mit_auswertung: bool = False
    systemprompt: str | None = None


class AuswertungAnfrage(BaseModel):
    transkript: str = Field(min_length=1, description="Pfad der Transkript-JSON")
    systemprompt: str | None = None


class Besprechung(BaseModel):
    besitzer: str | None = None
    eigen: bool = True
    geteilt_mit: list[str] = []
    id: str
    titel: str
    zeit: str
    transkript: str
    dauer_sekunden: float | None = None
    anzahl_sprecher: int | None = None
    sprache: str | None = None
    hat_protokoll: bool
    protokolle: list[dict[str, str]]


class Sprecher(BaseModel):
    id: str | None
    name: str | None
    segmente: int | None = None
    sekunden: float | None = None


class Segment(BaseModel):
    start: float | None
    ende: float | None
    sprecher_id: str | None = None
    sprecher: str | None = None
    text: str | None = None


class Datei(BaseModel):
    name: str
    art: str
    groesse: int


class ProtokollText(BaseModel):
    id: str
    text: str


class BesprechungDetails(Besprechung):
    sprecher: list[Sprecher]
    segmente: list[Segment]
    protokoll: ProtokollText | None
    dateien: list[Datei]


class ProtokollSpeichern(BaseModel):
    text: str = Field(max_length=2_000_000)


class SprecherNamen(BaseModel):
    namen: dict[str, str]


class ExportAnfrage(BaseModel):
    inhalt: str = Field(pattern="^(transkript|protokoll|beides)$")
    formate: list[str] = Field(min_length=1)


class EingangsDatei(BaseModel):
    name: str
    pfad: str
    groesse: int
    geaendert: float


class Schluesselsatz(BaseModel):
    wert: str = Field(max_length=4096)
    merken: bool = False


class Vorlage(BaseModel):
    name: str
    text: str
    eigene: bool


class VorlageSpeichern(BaseModel):
    text: str = Field(max_length=200_000)


class GeraetAnlegen(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    # Servermodus: wem das Geraet gehoert (Anmeldename). Ohne: allgemeiner Ordner, nur fuer Admins sichtbar.
    besitzer: str | None = Field(default=None, max_length=32)


class ChatAnfrage(BaseModel):
    frage: str = Field(min_length=1, max_length=20_000)
    besprechungen: list[str] = Field(default_factory=list, description="Kennungen der Besprechungen")
    verlauf_id: str | None = None


class OrdnerOeffnen(BaseModel):
    pfad: str


class ModellLaden(BaseModel):
    modell: str = Field(min_length=1, max_length=200)


class Freigabe(BaseModel):
    mit: list[str] = Field(default_factory=list, max_length=200, description='"alle" oder Anmeldenamen; leer = nicht geteilt')


class NutzerAnlegen(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    anzeigename: str = Field(default="", max_length=80)
    admin: bool = False
    passwort: str | None = Field(default=None, max_length=512)


class NutzerAendern(BaseModel):
    anzeigename: str | None = Field(default=None, max_length=80)
    admin: bool | None = None
    aktiv: bool | None = None
    passwort: str | None = Field(default=None, max_length=512, description='Neues Passwort; "" entfernt es')


class PasswortAendern(BaseModel):
    bisher: str = Field(default="", max_length=512)
    neu: str = Field(min_length=1, max_length=512)


class ZugangAnlegen(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=60)


# ---------------------------------------------------------------- Ersteinrichtung
Modus = Literal["lokal", "api"]


class EinrichtungVorhanden(BaseModel):
    """Was schon auf diesem Rechner ist (gefragt werden nur Platte, Registry und der lokale Ollama-Dienst)."""

    ffmpeg: bool
    ollama: bool
    ollama_laeuft: bool
    ollama_version: str | None = None
    ollama_modelle: list[str] = []
    laufzeit: bool = Field(description="Rechenumgebung (PyTorch & Co.) liegt auf der Platte")
    laufzeit_aktiv: bool = Field(description="Dieser Dienst laeuft schon in der Rechenumgebung")
    sprachmodell: bool
    einbettung: bool
    whisper: bool
    pyannote: bool
    hf_token: bool


class EinrichtungStand(BaseModel):
    einrichtung_abgeschlossen: bool
    naechster_schritt: str = Field(description='"willkommen" | "neustart" | "mitschrift" | "fertig"')
    einrichtung_fortsetzen: str
    lokale_einrichtung_zurueckgestellt: bool
    arbeitsweise: dict[str, str] = Field(description='{"transkription", "nachbearbeitung", "chatbot"} -> "lokal" | "api"')
    modelle: dict[str, str]
    vorhanden: EinrichtungVorhanden
    offen: list[str] = Field(description="Kennungen der Bausteine (wie in /kosten), die fuer die Arbeitsweise noch fehlen")
    rechenumgebung_fehlt: bool
    neustart_noetig: bool = Field(description='Der Dienst muss einmal neu starten ("Die App startet kurz neu")')
    online_ohne_anbieter: list[str]
    geraete: int
    geraete_empfang_aktiv: bool
    auftraege: list[Auftrag]


class EinrichtungSchritt(BaseModel):
    kennung: str = Field(description='"mitschrift" | "sprecher" | "protokoll" | "chat"')
    name: str
    stufe: str = Field(description='"gut" | "maessig" | "nicht"')
    text: str
    dauer_von: float | None = None
    dauer_bis: float | None = None
    einheit: str = Field(default="", description='"minuten_je_stunde_aufnahme" | "sekunden_je_frage" | ""')
    ort: str = Field(default="", description='"Grafikkarte" | "Prozessor" | ""')


class EinrichtungModell(BaseModel):
    id: str
    name: str
    groesse_gb: float | None = None
    stufe: str
    text: str
    auf_grafikkarte: bool
    empfohlen: bool


class EinrichtungRechner(BaseModel):
    profil: dict[str, Any]
    schritte: list[EinrichtungSchritt]
    empfehlung: str | None = Field(description='"lokal" | "gemischt" | "api" | null (Anwender entscheidet)')
    begruendung: str
    hinweise: list[str]
    empfohlene_modelle: dict[str, str | None]
    whisper_modelle: list[EinrichtungModell]
    sprachmodelle: list[EinrichtungModell]
    einbettungsmodelle: list[EinrichtungModell]


class EinrichtungBaustein(BaseModel):
    kennung: str = Field(description='"ffmpeg" | "ollama" | "sprachmodell" | "einbettung" | "laufzeit" | "whisper" | "pyannote"')
    name: str
    download_gb: float
    platz_gb: float
    hinweis: str
    vorhanden: bool


class EinrichtungKosten(BaseModel):
    arbeitsweise: dict[str, str]
    bausteine: list[EinrichtungBaustein]
    download_gb: float
    platz_gb: float
    download_minuten_von: float
    download_minuten_bis: float
    annahme_mbit: int
    freier_platz_gb: float | None
    platz_knapp: bool
    zustimmung_noetig: bool
    neustart_noetig: bool
    ollama_lizenz: dict[str, str] | None


class EinrichtungEntscheidung(BaseModel):
    transkription: Modus
    nachbearbeitung: Modus
    chatbot: Modus
    sprachmodell: str | None = Field(default=None, max_length=200, description="Ollama-Modell fuer das Protokoll (aus /rechner)")
    whisper_modell: str | None = Field(default=None, max_length=100)
    zustimmung_rechenumgebung: bool = Field(
        default=False, description="Zustimmung, die Rechenumgebung fuer die lokale Mitschrift beim naechsten Start zu laden"
    )


class EinrichtungZustimmung(BaseModel):
    zustimmung: bool = Field(description="Ausdrueckliche Zustimmung zum Herunterladen; ohne sie wird nichts geladen")


class EinrichtungModelle(BaseModel):
    zustimmung: bool = Field(description="Ausdrueckliche Zustimmung zum Herunterladen; ohne sie wird nichts geladen")
    sprachmodelle: list[str] | None = Field(
        default=None, max_length=10, description="Ollama-Modelle; ohne Angabe: was die Arbeitsweise braucht und fehlt"
    )
    whisper: bool = False
    whisper_modell: str | None = Field(default=None, max_length=100, description="ohne Angabe: das eingestellte")
    sprechertrennung: bool = False
    hf_token: str | None = Field(default=None, max_length=512, description="Zugang zu Hugging Face (wird nie zurueckgegeben)")
    hf_token_merken: bool = True


class EinrichtungAnbieter(BaseModel):
    bereich: Literal["transkription", "nachbearbeitung", "chatbot"]
    anbieter: str = Field(min_length=1, max_length=40, description='Kennung aus /api/einstellungen/anbieter oder "eigener"')
    endpunkt: str | None = Field(default=None, max_length=500)
    modell: str | None = Field(default=None, max_length=200)
    einbettung_endpunkt: str | None = Field(default=None, max_length=500)
    einbettung_modell: str | None = Field(default=None, max_length=200)
    schluessel: str | None = Field(default=None, max_length=4096)
    merken: bool = False


class EinrichtungAnbieterErgebnis(BaseModel):
    bereich: str
    anbieter: str
    endpunkt: str
    modell: str
    adresse_vollstaendig: bool
    schluessel_vorhanden: bool
    gemerkt: bool


class EinrichtungSpaeter(BaseModel):
    nicht_mehr_fragen: bool = False
