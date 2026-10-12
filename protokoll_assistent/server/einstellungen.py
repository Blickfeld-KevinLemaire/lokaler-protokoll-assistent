"""Einstellungen des Servermodus -- ausschliesslich aus Umgebungsvariablen.

Im Container gibt es keinen Einstellungsdialog; alles steht in der
``docker-compose.yml``. Geheimnisse (``HF_TOKEN``, ``PROTOKOLL_WEBHOOK_TOKEN``)
kommen ebenfalls aus der Umgebung und werden nie geloggt. Fuer die
Aufnahmegeraete stehen dort nur die SHA-256-Hashes ihrer Token
(``PROTOKOLL_EMPFANG_GERAETE``), nie die Token selbst.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from protokoll_assistent.services import dokument_export_service, geraete_empfang_service, model_service, ollama_service

# Formate, die ohne Oberflaeche geschrieben werden koennen (PDF und OpenDocument
# braucht Qt und gibt es im Container deshalb nicht).
SERVER_FORMATE = ("docx", "md", "txt", "html", "srt", "vtt", "json")


class EinstellungsFehler(ValueError):
    """Ungueltige Einstellung, mit lesbarer Meldung."""


def _wahrheitswert(roh: str | None, standard: bool, name: str) -> bool:
    if roh is None or not roh.strip():
        return standard
    wert = roh.strip().lower()
    if wert in ("1", "true", "ja", "an", "yes", "on"):
        return True
    if wert in ("0", "false", "nein", "aus", "no", "off"):
        return False
    raise EinstellungsFehler(f"{name}: '{roh}' ist weder an noch aus (erlaubt: 1/0, ja/nein, an/aus).")


def _zahl(roh: str | None, standard: float, name: str, minimum: float = 0.0) -> float:
    if roh is None or not roh.strip():
        return standard
    try:
        wert = float(roh.replace(",", "."))
    except ValueError as fehler:
        raise EinstellungsFehler(f"{name}: '{roh}' ist keine Zahl.") from fehler
    if wert < minimum:
        raise EinstellungsFehler(f"{name}: muss mindestens {minimum:g} sein.")
    return wert


def _ganzzahl_oder_none(roh: str | None, name: str) -> int | None:
    if roh is None or not roh.strip():
        return None
    return int(_zahl(roh, 0, name, minimum=1))


@dataclass(frozen=True)
class ServerEinstellungen:
    eingang: Path
    ausgang: Path
    abfrage_sekunden: float = 10.0
    # So lange muss eine Datei unveraendert sein, bevor sie angefasst wird: Ein
    # Geraet, das noch schreibt, darf nicht halb gelesen werden.
    stabil_sekunden: float = 30.0
    sprache: str | None = "de"
    whisper_modell: str = model_service.WHISPER_MODEL_NAME
    ollama_modell: str = ollama_service.DEFAULT_MODEL
    sprechertrennung: bool = True
    protokoll: bool = True
    modelle_laden: bool = True
    geraet: str = "cuda"
    min_sprecher: int | None = None
    max_sprecher: int | None = None
    export_formate: tuple[str, ...] = ()
    webhook_url: str = ""
    webhook_token: str = ""
    # Empfang fuer die WLAN-Aufnahmegeraete (GERAETE-SCHNITTSTELLE.md). Aus,
    # bis er ausdruecklich eingeschaltet wird -- erst dann oeffnet der Dienst
    # einen Port.
    empfang: bool = False
    empfang_port: int = geraete_empfang_service.STANDARD_PORT
    empfang_geraete: tuple[geraete_empfang_service.Geraet, ...] = ()

    @classmethod
    def aus_umgebung(cls, umgebung: Mapping[str, str]) -> ServerEinstellungen:
        def lies(name: str) -> str | None:
            return umgebung.get(f"PROTOKOLL_{name}")

        sprache = (lies("SPRACHE") or "de").strip().lower()
        geraet = (lies("GERAET") or "cuda").strip().lower()
        if geraet not in ("cuda", "cpu"):
            raise EinstellungsFehler(f"PROTOKOLL_GERAET: '{geraet}' ist nicht erlaubt (cuda oder cpu).")
        formate = tuple(f.strip().lower() for f in (lies("EXPORT_FORMATE") or "").split(",") if f.strip())
        for format_id in formate:
            if format_id not in SERVER_FORMATE or dokument_export_service.finde_format(format_id) is None:
                raise EinstellungsFehler(
                    f"PROTOKOLL_EXPORT_FORMATE: '{format_id}' gibt es im Server nicht "
                    f"(erlaubt: {', '.join(SERVER_FORMATE)})."
                )
        webhook = (lies("WEBHOOK_URL") or "").strip()
        empfang = _wahrheitswert(lies("EMPFANG"), False, "PROTOKOLL_EMPFANG")
        try:
            empfang_geraete = geraete_empfang_service.geraete_aus_text(lies("EMPFANG_GERAETE") or "")
        except ValueError as fehler:
            raise EinstellungsFehler(f"PROTOKOLL_EMPFANG_GERAETE: {fehler}") from fehler
        if empfang and not empfang_geraete:
            raise EinstellungsFehler(
                "PROTOKOLL_EMPFANG ist an, aber PROTOKOLL_EMPFANG_GERAETE ist leer. Ein Token pro Geraet "
                "erzeugt 'python -m protokoll_assistent.server --token-erzeugen <Name>'."
            )
        empfang_port = int(_zahl(lies("EMPFANG_PORT"), geraete_empfang_service.STANDARD_PORT, "PROTOKOLL_EMPFANG_PORT", 1))
        if empfang_port > 65535:
            raise EinstellungsFehler("PROTOKOLL_EMPFANG_PORT: hoechstens 65535.")
        if webhook and not webhook.lower().startswith(("http://", "https://")):
            raise EinstellungsFehler("PROTOKOLL_WEBHOOK_URL muss mit http:// oder https:// beginnen.")
        return cls(
            eingang=Path((lies("EINGANG") or "/daten/eingang").strip()),
            ausgang=Path((lies("AUSGANG") or "/daten/ausgang").strip()),
            abfrage_sekunden=_zahl(lies("ABFRAGE_SEKUNDEN"), 10.0, "PROTOKOLL_ABFRAGE_SEKUNDEN", 1.0),
            stabil_sekunden=_zahl(lies("STABIL_SEKUNDEN"), 30.0, "PROTOKOLL_STABIL_SEKUNDEN", 0.0),
            sprache=None if sprache in ("auto", "automatisch") else sprache,
            whisper_modell=(lies("WHISPER_MODELL") or model_service.WHISPER_MODEL_NAME).strip(),
            ollama_modell=(lies("OLLAMA_MODELL") or ollama_service.DEFAULT_MODEL).strip(),
            sprechertrennung=_wahrheitswert(lies("SPRECHERTRENNUNG"), True, "PROTOKOLL_SPRECHERTRENNUNG"),
            protokoll=_wahrheitswert(lies("PROTOKOLL_ERSTELLEN"), True, "PROTOKOLL_PROTOKOLL_ERSTELLEN"),
            modelle_laden=_wahrheitswert(lies("MODELLE_LADEN"), True, "PROTOKOLL_MODELLE_LADEN"),
            geraet=geraet,
            min_sprecher=_ganzzahl_oder_none(lies("MIN_SPRECHER"), "PROTOKOLL_MIN_SPRECHER"),
            max_sprecher=_ganzzahl_oder_none(lies("MAX_SPRECHER"), "PROTOKOLL_MAX_SPRECHER"),
            export_formate=formate,
            webhook_url=webhook,
            webhook_token=(lies("WEBHOOK_TOKEN") or "").strip(),
            empfang=empfang,
            empfang_port=empfang_port,
            empfang_geraete=empfang_geraete,
        )
