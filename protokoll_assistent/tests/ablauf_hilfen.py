"""Gemeinsame Bausteine fuer die Tests der Ablaufsteuerung und der Programmschnittstelle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.steuerung import Abhaengigkeiten, Steuerung
from protokoll_assistent.ablauf.verarbeitungswege import Schluesselablage
from protokoll_assistent.services import export_service, pipeline_service


def transkript_json_schreiben(pfad: Path, text: str = "Hallo zusammen.") -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(
        json.dumps(
            {
                "segmente": [
                    {"start_sekunden": 0.0, "ende_sekunden": 2.0, "sprecher_id": "SPEAKER_00", "text": text},
                ],
                "sprecher_zuordnung": [{"sprecher_id": "SPEAKER_00", "anzeigename": "Sprecher 1"}],
                "sprechertrennung_aktiv": True,
                "quelldatei_stamm": pfad.stem.split("_lokal_transkript_")[0],
                "lauf_zeitstempel": pfad.stem.rsplit("_lokal_transkript_", 1)[-1],
                "quelldatei": "besprechung.wav",
                "erstellt": "2026-01-01T12:00:00+01:00",
                "modell": "test",
                "sprache": "de",
                "verarbeitungsdauer_sekunden": 1.0,
                "verarbeitungsgeraet": "cpu",
            }
        ),
        encoding="utf-8",
    )
    return pfad


class FalschePipeline:
    """Ersetzt 'run_transcription'/'run_protocol': schreibt kleine Dateien und merkt sich die Aufrufe."""

    def __init__(self) -> None:
        self.transkriptionen: list[pipeline_service.PipelineSettings] = []
        self.auswertungen: list[pipeline_service.ProtocolSettings] = []
        self.protokoll_fehler: str | None = None
        self.transkription_fehler: Exception | None = None

    def run_transcription(
        self,
        settings: pipeline_service.PipelineSettings,
        callbacks: pipeline_service.PipelineCallbacks | None = None,
        transcribe_chunk_fn: Any = None,
        diarize_fn: Any = None,
    ) -> pipeline_service.TranscriptionResult:
        self.transkriptionen.append(settings)
        callbacks = callbacks or pipeline_service.PipelineCallbacks()
        callbacks.on_stage("transkription", "Transkription")
        callbacks.on_overall_progress(0.5)
        callbacks.on_preview("Hallo zusammen.")
        if self.transkription_fehler is not None:
            raise self.transkription_fehler
        stamm = settings.source_path.stem
        basis = settings.output_dir / f"{stamm}_lokal_transkript_20260101_120000"
        json_pfad = transkript_json_schreiben(basis.with_suffix(".json"))
        for endung in (".txt", ".srt", ".vtt"):
            basis.with_suffix(endung).write_text("Hallo zusammen.", encoding="utf-8")
        pfade = export_service.ExportPaths(
            basis.with_suffix(".txt"), json_pfad, basis.with_suffix(".srt"), basis.with_suffix(".vtt")
        )
        return pipeline_service.TranscriptionResult(
            work_dir=settings.output_dir,
            export_paths=pfade,
            speaker_names={"SPEAKER_00": "Sprecher 1"},
            segments=[],
            manifest={},
            total_duration=2.0,
            run_timestamp="20260101_120000",
            timings={},
        )

    def run_protocol(
        self,
        settings: pipeline_service.ProtocolSettings,
        callbacks: pipeline_service.PipelineCallbacks | None = None,
        protocol_generate_fn: Any = None,
    ) -> pipeline_service.ProtocolResult:
        self.auswertungen.append(settings)
        callbacks = callbacks or pipeline_service.PipelineCallbacks()
        callbacks.on_stage("protokoll", "Protokoll")
        callbacks.on_overall_progress(1.0)
        if self.protokoll_fehler:
            return pipeline_service.ProtocolResult(settings.output_dir, None, (Path(), Path()), self.protokoll_fehler)
        stamm = settings.transcript_json_path.stem.replace("_lokal_transkript_", "_protokoll_")
        json_pfad = settings.output_dir / f"{stamm}.json"
        md_pfad = settings.output_dir / f"{stamm}.md"
        json_pfad.write_text(json.dumps({"protokoll": "# Protokoll"}), encoding="utf-8")
        md_pfad.write_text("# Protokoll\n", encoding="utf-8")
        return pipeline_service.ProtocolResult(settings.output_dir, (json_pfad, md_pfad), (Path(), Path()))


def steuerung_fuer_test(
    konfiguration: dict[str, Any], pipeline: FalschePipeline | None = None, *, umgebung: dict[str, str] | None = None
) -> tuple[Steuerung, FalschePipeline]:
    pipeline = pipeline or FalschePipeline()
    steuerung = Steuerung(
        schluessel=Schluesselablage(umgebung=umgebung or {}),
        abhaengigkeiten=Abhaengigkeiten(
            konfiguration_laden=lambda: konfiguration,
            run_transcription=pipeline.run_transcription,
            run_protocol=pipeline.run_protocol,
            laufzeit_verfuegbar=lambda: True,
            modell_fehlt=lambda modell: False,
        ),
    )
    return steuerung, pipeline


def alle_auftraege_ausfuehren(steuerung: Steuerung) -> None:
    while steuerung.auftraege.ausfuehren_im_aufrufer():
        pass
