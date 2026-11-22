"""Datenformen der Programmschnittstelle (daraus entsteht ``openapi.json`` und der TypeScript-Client)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Fehler(BaseModel):
    titel: str
    text: str
    code: str


class Anmeldung(BaseModel):
    schluessel: str = Field(min_length=1, max_length=256)


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


class ChatAnfrage(BaseModel):
    frage: str = Field(min_length=1, max_length=20_000)
    besprechungen: list[str] = Field(default_factory=list, description="Kennungen der Besprechungen")
    verlauf_id: str | None = None


class OrdnerOeffnen(BaseModel):
    pfad: str


class ModellLaden(BaseModel):
    modell: str = Field(min_length=1, max_length=200)
