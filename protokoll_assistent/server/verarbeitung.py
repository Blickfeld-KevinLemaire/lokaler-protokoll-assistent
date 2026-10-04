"""Verarbeitet eine Aufnahme und legt die Ergebnisse im Ausgangsordner ab.

Pro Aufnahme entsteht ein eigener Unterordner ``<name>_<zeitstempel>/`` mit
Transkript (TXT, JSON, SRT, VTT), Protokoll (JSON, Markdown), der
zusammengefassten Word-Datei und -- falls eingestellt -- weiteren Formaten.
Zusaetzlich steht dort ``ergebnis.json`` mit dem Ausgang des Laufs; daran
erkennen Fremdsysteme (oder das Aufnahmegeraet), dass die Aufnahme fertig ist.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.server.einstellungen import ServerEinstellungen
from protokoll_assistent.services import dokument_export_service, pipeline_service

STATUS_FERTIG = "fertig"
STATUS_FEHLER = "fehler"
STATUS_ABGEBROCHEN = "abgebrochen"
ERGEBNIS_DATEI = "ergebnis.json"

PipelineFn = Callable[[pipeline_service.PipelineSettings, pipeline_service.PipelineCallbacks], Any]


@dataclass
class Ergebnis:
    status: str
    datei: Path
    ausgabe: Path | None = None
    dateien: list[str] = field(default_factory=list)
    fehler: str | None = None
    protokoll_fehler: str | None = None
    dauer_sekunden: float = 0.0

    def als_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "datei": self.datei.name,
            "ausgabe": str(self.ausgabe) if self.ausgabe else None,
            "dateien": self.dateien,
            "fehler": self.fehler,
            "protokoll_fehler": self.protokoll_fehler,
            "dauer_sekunden": round(self.dauer_sekunden, 1),
        }


def ausgabeordner_fuer(datei: Path, einstellungen: ServerEinstellungen, jetzt: datetime | None = None) -> Path:
    zeit = (jetzt or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return einstellungen.ausgang / f"{datei.stem}_{zeit}"


def verarbeite(
    datei: Path,
    einstellungen: ServerEinstellungen,
    *,
    pipeline_fn: PipelineFn | None = None,
    abbrechen: Callable[[], bool] = lambda: False,
    protokollieren: Callable[[str], None] = lambda text: None,
    jetzt: datetime | None = None,
) -> Ergebnis:
    """Fuehrt die komplette Verarbeitung aus; Fehler werden zu ``Ergebnis``, nie zur Ausnahme."""
    start = time.monotonic()
    ausgabe = ausgabeordner_fuer(datei, einstellungen, jetzt)
    settings = pipeline_service.PipelineSettings(
        source_path=datei,
        output_dir=ausgabe,
        language=einstellungen.sprache,
        min_speakers=einstellungen.min_sprecher,
        max_speakers=einstellungen.max_sprecher,
        allow_download=einstellungen.modelle_laden,
        device_preference=einstellungen.geraet,
        resume_mode="fortsetzen",
        run_protocol=einstellungen.protokoll,
        ollama_model=einstellungen.ollama_modell,
        whisper_model=einstellungen.whisper_modell,
        enable_diarization=einstellungen.sprechertrennung,
    )
    callbacks = pipeline_service.PipelineCallbacks(
        on_stage=lambda schluessel, detail: protokollieren(detail),
        on_log=protokollieren,
        should_cancel=abbrechen,
    )
    ablauf = pipeline_fn or pipeline_service.run_pipeline

    try:
        pipeline_ergebnis = ablauf(settings, callbacks)
    except pipeline_service.PipelineCancelled:
        return Ergebnis(STATUS_ABGEBROCHEN, datei, dauer_sekunden=time.monotonic() - start)
    except Exception as fehler:  # jede Datei einzeln: ein Fehler stoppt nie den Dienst
        ergebnis = Ergebnis(STATUS_FEHLER, datei, ausgabe, fehler=str(fehler) or type(fehler).__name__)
        ergebnis.dauer_sekunden = time.monotonic() - start
        _ergebnis_schreiben(ergebnis)
        return ergebnis

    protokoll_json = pipeline_ergebnis.protocol_paths[0] if pipeline_ergebnis.protocol_paths else None
    _weitere_formate(einstellungen, ausgabe, pipeline_ergebnis.export_paths.json, protokoll_json, protokollieren)
    ergebnis = Ergebnis(
        STATUS_FERTIG,
        datei,
        ausgabe,
        protokoll_fehler=getattr(pipeline_ergebnis, "protokoll_fehler", None),
        dauer_sekunden=time.monotonic() - start,
    )
    _ergebnis_schreiben(ergebnis)
    return ergebnis


def _weitere_formate(
    einstellungen: ServerEinstellungen,
    ausgabe: Path,
    transkript_json: Path,
    protokoll_json: Path | None,
    protokollieren: Callable[[str], None],
) -> None:
    if not einstellungen.export_formate:
        return
    inhalt = dokument_export_service.INHALT_BEIDES if protokoll_json else dokument_export_service.INHALT_TRANSKRIPT
    try:
        dokument_export_service.exportiere(
            inhalt,
            list(einstellungen.export_formate),
            ausgabe,
            transkript_json=transkript_json,
            protokoll_json=protokoll_json,
        )
    except dokument_export_service.ExportFehler as fehler:
        protokollieren(f"Nicht alle Export-Formate wurden geschrieben: {fehler}")


def _ergebnis_schreiben(ergebnis: Ergebnis) -> None:
    """``ergebnis.json`` ablegen und die Dateiliste eintragen."""
    if ergebnis.ausgabe is None:
        return
    try:
        ergebnis.ausgabe.mkdir(parents=True, exist_ok=True)
        ergebnis.dateien = sorted(p.name for p in ergebnis.ausgabe.iterdir() if p.is_file() and p.name != ERGEBNIS_DATEI)
        (ergebnis.ausgabe / ERGEBNIS_DATEI).write_text(
            json.dumps(ergebnis.als_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # der Ausgang ist trotzdem im Protokoll des Dienstes


def melde_webhook(
    url: str,
    nutzlast: dict[str, Any],
    token: str = "",
    *,
    oeffnen: Callable[..., Any] | None = None,
    timeout: float = 15.0,
) -> str | None:
    """Teilt einem Fremdsystem das Ergebnis mit (POST, JSON). Gibt eine Fehlermeldung
    zurueck oder ``None``; scheitert die Meldung, geht die Verarbeitung trotzdem weiter.

    Uebertragen werden nur Dateiname, Status und Ausgabeordner -- kein Inhalt."""
    kopf = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        kopf["Authorization"] = f"Bearer {token}"
    anfrage = urllib.request.Request(
        url, data=json.dumps(nutzlast, ensure_ascii=False).encode("utf-8"), headers=kopf, method="POST"
    )
    try:
        with (oeffnen or urllib.request.urlopen)(anfrage, timeout=timeout):
            return None
    except urllib.error.HTTPError as fehler:
        return f"HTTP {fehler.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as fehler:
        return str(fehler)
