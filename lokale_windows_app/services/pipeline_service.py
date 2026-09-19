"""Orchestrierung der vollstaendigen lokalen Verarbeitung.

Ablauf: Datei pruefen -> Audio normalisieren -> Chunks planen -> Modell laden
-> Chunks sequenziell transkribieren+ausrichten -> globale Diarisierung ->
Zusammenfuehren (globale Zeitstempel + Overlap-Dedup) -> Sprecherzuordnung ->
TXT/JSON/SRT/VTT-Export -> mehrstufige lokale Ollama-Protokollauswertung ->
Protokoll-Export -> Verarbeitungsbericht.

Die eigentlichen ML-Aufrufe (Transkription, Diarisierung, Ollama) sind ueber
Parameter austauschbar, damit die Ablaufsteuerung -- Fortsetzen nach Abbruch,
Ueberspringen fertiger Chunks, Fehlerbehandlung eines einzelnen Chunks --
unabhaengig von GPU/faster-whisper/pyannote/Ollama getestet werden kann. Ohne
Angabe werden die echten lokalen Implementierungen verwendet.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from services import (
    chunking_service,
    diarization_service,
    export_service,
    ffmpeg_service,
    manifest_service,
    merge_service,
    model_service,
    ollama_service,
    protocol_service,
    speaker_merge_service,
    transcription_service,
)
from utils.logging_setup import get_logger
from utils.timeformat import format_timestamp

logger = get_logger()

STAGE_LABELS = {
    "datei_pruefung": "Datei wird geprüft",
    "audio_normalisierung": "Audio wird vorbereitet",
    "chunk_planung": "Chunks werden geplant",
    "modell_laden": "Modell wird geladen",
    "transkription": "Transkription läuft",
    "ausrichtung": "Zeitstempel werden ausgerichtet",
    "diarisierung": "Sprecher werden getrennt",
    "zusammenfuehrung": "Chunks werden zusammengeführt",
    "export_transkript": "Ausgabedateien werden erstellt",
    "protokoll_auswertung": "Lokale Protokollauswertung läuft",
    "export_protokoll": "Protokolldateien werden erstellt",
    "abgeschlossen": "Verarbeitung abgeschlossen",
}


class PipelineCancelled(RuntimeError):
    pass


class PipelineError(RuntimeError):
    pass


@dataclass
class PipelineSettings:
    source_path: Path
    output_dir: Path
    language: str | None = "de"
    min_speakers: int | None = None
    max_speakers: int | None = None
    allow_download: bool = False
    batch_size: int = 4
    device_preference: str = "cuda"
    resume_mode: Literal["fortsetzen", "neu_beginnen"] = "fortsetzen"
    run_protocol: bool = True
    ollama_model: str = ollama_service.DEFAULT_MODEL
    whisper_model: str = model_service.WHISPER_MODEL_NAME
    protocol_group_size: int = 4
    enable_diarization: bool = True


@dataclass
class PipelineCallbacks:
    on_stage: Callable[[str, str], None] = lambda key, detail: None
    on_chunk_progress: Callable[[int, int], None] = lambda current, total: None
    on_overall_progress: Callable[[float], None] = lambda fraction: None
    on_preview: Callable[[str], None] = lambda text: None
    on_log: Callable[[str], None] = lambda message: None
    should_cancel: Callable[[], bool] = lambda: False


@dataclass
class PipelineResult:
    work_dir: Path
    export_paths: export_service.ExportPaths
    protocol_paths: tuple[Path, Path] | None
    report_paths: tuple[Path, Path]
    speaker_names: dict[str, str]
    segments: list[dict[str, Any]]
    manifest: dict[str, Any]


def _check_cancel(callbacks: PipelineCallbacks) -> None:
    if callbacks.should_cancel():
        raise PipelineCancelled("Verarbeitung durch Benutzer abgebrochen.")


def validate_source_file(source_path: Path) -> None:
    if not source_path.exists():
        raise PipelineError(f"Datei nicht gefunden: {source_path}")
    if not source_path.is_file():
        raise PipelineError(f"Kein gültiger Dateipfad: {source_path}")
    if source_path.stat().st_size == 0:
        raise PipelineError(f"Datei ist leer: {source_path.name}")


def _build_protocol_chunk_texts(
    chunk_plans: list[chunking_service.ChunkPlan],
    merged_segments: list[dict[str, Any]],
    speaker_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Baut je Chunk den zugehoerigen (bereits global datierten und
    deduplizierten) Transkriptausschnitt fuer die Ollama-Auswertung."""
    chunk_texts = []
    for plan in chunk_plans:
        lines = []
        for segment in merged_segments:
            if plan.global_start <= segment["start"] < plan.global_end:
                # 'sprecher_id' darf fehlen - dict.get(None) ist erlaubt
                # und liefert dann den Standardwert.
                sprecher_id = segment.get("sprecher_id")
                name = speaker_names.get(sprecher_id, "Sprecher unbekannt")  # type: ignore[arg-type]
                lines.append(f"[{format_timestamp(segment['start'])}] {name}: {segment['text']}")
        chunk_texts.append(
            {
                "index": plan.index,
                "start_str": format_timestamp(plan.global_start),
                "end_str": format_timestamp(plan.global_end),
                "text": "\n".join(lines),
            }
        )
    return chunk_texts


def run_pipeline(
    settings: PipelineSettings,
    callbacks: PipelineCallbacks | None = None,
    transcribe_chunk_fn: Callable[[Path], list[dict[str, Any]]] | None = None,
    diarize_fn: Callable[[Path, int | None, int | None], list[dict[str, Any]]] | None = None,
    protocol_generate_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> PipelineResult:
    callbacks = callbacks or PipelineCallbacks()
    started_at = time.monotonic()
    timings: dict[str, float] = {}

    callbacks.on_stage("datei_pruefung", STAGE_LABELS["datei_pruefung"])
    validate_source_file(settings.source_path)
    _check_cancel(callbacks)

    from utils.paths import get_work_dir

    base_work_dir = get_work_dir()
    file_hash = manifest_service.compute_file_hash(settings.source_path)
    work_dir = manifest_service.get_work_dir_for_file(base_work_dir, file_hash)

    existing_manifest = manifest_service.load_manifest(work_dir)
    if existing_manifest is not None and settings.resume_mode == "neu_beginnen":
        existing_manifest = None

    callbacks.on_stage("audio_normalisierung", STAGE_LABELS["audio_normalisierung"])
    ffmpeg_service.ensure_ffmpeg_on_path()
    normalized_path = work_dir / "audio_normalisiert.wav"
    stage_start = time.monotonic()
    if not normalized_path.exists():
        ffmpeg_service.normalize_audio(settings.source_path, normalized_path)
    total_duration = ffmpeg_service.probe_duration_seconds(normalized_path)
    timings["audio_normalisierung"] = time.monotonic() - stage_start
    _check_cancel(callbacks)

    callbacks.on_stage("chunk_planung", STAGE_LABELS["chunk_planung"])
    chunk_plans = chunking_service.plan_chunks(total_duration)

    if existing_manifest is None:
        manifest = manifest_service.create_manifest(
            settings.source_path,
            file_hash,
            total_duration,
            chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS,
            chunking_service.DEFAULT_OVERLAP_SECONDS,
            len(chunk_plans),
            [
                {"index": plan.index, "global_start": plan.global_start, "global_end": plan.global_end}
                for plan in chunk_plans
            ],
            {
                "sprache": settings.language,
                "min_sprecher": settings.min_speakers,
                "max_sprecher": settings.max_speakers,
                "modell": settings.whisper_model,
                "sprechertrennung_aktiv": settings.enable_diarization,
            },
        )
        manifest_service.save_manifest(work_dir, manifest)
    else:
        manifest = existing_manifest

    resume_state = manifest_service.find_resumable_state(manifest)
    callbacks.on_log(
        f"{len(resume_state['fertige_chunks'])} von {len(chunk_plans)} Chunks bereits abgeschlossen."
    )

    callbacks.on_stage("modell_laden", STAGE_LABELS["modell_laden"])
    device, compute_type = model_service.get_device_and_compute_type(settings.device_preference)
    model_service.prepare_offline_mode(settings.allow_download)

    whisper_model = None
    if transcribe_chunk_fn is None:
        whisper_model = transcription_service.load_whisper_model(
            settings.whisper_model, device, compute_type, settings.language
        )

        def transcribe_chunk_fn(chunk_wav_path: Path) -> list[dict[str, Any]]:  # noqa: F811
            audio_array = transcription_service.load_audio_array(chunk_wav_path)
            result = transcription_service.transcribe_audio_array(
                whisper_model, audio_array, settings.batch_size, settings.language
            )
            # Frueher lief hier zusaetzlich 'whisperx.align'. Der Schritt ist
            # mit dem Wegfall von WhisperX entfallen: faster-whisper liefert
            # die Wortzeitstempel selbst, und die dabei erzeugten Wortdaten
            # wurden im Projekt ohnehin nirgends gelesen.
            return transcription_service.segments_to_plain(result)

    callbacks.on_stage("transkription", STAGE_LABELS["transkription"])
    chunk_segment_lists: list[list[dict[str, Any]]] = []
    for plan in chunk_plans:
        _check_cancel(callbacks)
        callbacks.on_chunk_progress(plan.index + 1, len(chunk_plans))
        transcript_path = manifest_service.chunk_transcript_path(work_dir, plan.index)
        chunk_status = next(c for c in manifest["chunks"] if c["index"] == plan.index)

        if chunk_status["status"] == manifest_service.STATUS_ABGESCHLOSSEN and transcript_path.exists():
            chunk_segment_lists.append(json.loads(transcript_path.read_text(encoding="utf-8")))
            callbacks.on_overall_progress((plan.index + 1) / len(chunk_plans) * 0.5)
            continue

        manifest_service.update_chunk_status(manifest, plan.index, manifest_service.STATUS_IN_BEARBEITUNG)
        manifest_service.save_manifest(work_dir, manifest)
        try:
            chunk_wav = manifest_service.chunk_audio_path(work_dir, plan.index)
            if not chunk_wav.exists():
                ffmpeg_service.extract_chunk_wav(
                    normalized_path, chunk_wav, plan.global_start, plan.global_end
                )
            local_segments = transcribe_chunk_fn(chunk_wav)
            transcript_path.write_text(
                json.dumps(local_segments, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            manifest_service.update_chunk_status(manifest, plan.index, manifest_service.STATUS_ABGESCHLOSSEN)
            manifest_service.save_manifest(work_dir, manifest)
            chunk_segment_lists.append(local_segments)
        except PipelineCancelled:
            raise
        except Exception as error:
            manifest_service.update_chunk_status(
                manifest, plan.index, manifest_service.STATUS_FEHLGESCHLAGEN, str(error)
            )
            manifest_service.save_manifest(work_dir, manifest)
            raise PipelineError(
                f"Chunk {plan.index + 1} von {len(chunk_plans)} ist fehlgeschlagen: {error}"
            ) from error

        callbacks.on_overall_progress((plan.index + 1) / len(chunk_plans) * 0.5)

    callbacks.on_stage("diarisierung", STAGE_LABELS["diarisierung"])
    if not settings.enable_diarization:
        callbacks.on_log(
            "Sprechertrennung deaktiviert -- Transkript wird ohne Sprecherzuordnung erstellt."
        )
        diarization_turns: list[dict[str, Any]] = []
    elif diarize_fn is None:
        pipeline = model_service.load_pyannote_pipeline(device)
        full_audio_array = transcription_service.load_audio_array(normalized_path)
        waveform_dict = diarization_service.build_waveform_dict(full_audio_array)
        diarization_turns = diarization_service.diarize_waveform(
            pipeline, waveform_dict, settings.min_speakers, settings.max_speakers
        )
    else:
        diarization_turns = diarize_fn(normalized_path, settings.min_speakers, settings.max_speakers)
    manifest["diarisierung_status"] = manifest_service.STATUS_ABGESCHLOSSEN
    manifest_service.save_manifest(work_dir, manifest)
    _check_cancel(callbacks)

    callbacks.on_stage("zusammenfuehrung", STAGE_LABELS["zusammenfuehrung"])
    merged_segments = merge_service.merge_chunk_transcripts(chunk_plans, chunk_segment_lists)
    merged_segments = speaker_merge_service.assign_speakers_by_overlap(merged_segments, diarization_turns)
    callbacks.on_preview(
        "\n".join(
            f"[{format_timestamp(s['start'])}] {s.get('sprecher_id')}: {s['text']}"
            for s in merged_segments[:50]
        )
    )

    callbacks.on_stage("export_transkript", STAGE_LABELS["export_transkript"])
    speaker_order = export_service.speaker_ids_in_order_of_appearance(merged_segments)
    speaker_names = export_service.build_speaker_names(speaker_order)
    run_timestamp = export_service.make_run_timestamp()
    created_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    device_desc = model_service.get_gpu_description()
    processing_duration = time.monotonic() - started_at
    export_paths = export_service.write_transcript_exports(
        settings.output_dir,
        settings.source_path.name,
        settings.source_path.stem,
        run_timestamp,
        created_iso,
        f"faster-whisper {settings.whisper_model}",
        settings.language or "automatisch erkannt",
        device_desc,
        processing_duration,
        merged_segments,
        speaker_names,
        settings.enable_diarization,
    )

    protocol_paths = None
    manifest["protokoll_status"] = manifest_service.STATUS_AUSSTEHEND
    if settings.run_protocol:
        callbacks.on_stage("protokoll_auswertung", STAGE_LABELS["protokoll_auswertung"])
        _check_cancel(callbacks)
        from utils.paths import get_system_prompt_file

        system_prompt = get_system_prompt_file().read_text(encoding="utf-8")
        chunk_texts = _build_protocol_chunk_texts(chunk_plans, merged_segments, speaker_names)

        def default_ollama_generate(prompt: str, system: str) -> dict[str, Any]:
            return ollama_service.generate_json(prompt, system, model=settings.ollama_model)

        generate_fn = protocol_generate_fn or default_ollama_generate
        try:
            protocol = protocol_service.run_full_protocol_pipeline(
                chunk_texts,
                work_dir,
                system_prompt,
                generate_fn,
                settings.protocol_group_size,
                progress_cb=lambda stage, current, total: callbacks.on_stage(
                    "protokoll_auswertung",
                    f"{STAGE_LABELS['protokoll_auswertung']} ({stage}: {current + 1}/{max(total, 1)})",
                ),
            )
            manifest["protokoll_status"] = manifest_service.STATUS_ABGESCHLOSSEN
            callbacks.on_stage("export_protokoll", STAGE_LABELS["export_protokoll"])
            protocol_paths = export_service.write_protocol_exports(
                settings.output_dir, protocol, settings.source_path.stem, run_timestamp
            )
        except protocol_service.ProtocolValidationError as error:
            manifest["protokoll_status"] = manifest_service.STATUS_FEHLGESCHLAGEN
            manifest_service.save_manifest(work_dir, manifest)
            callbacks.on_log(f"Protokollauswertung fehlgeschlagen: {error}")

    manifest_service.save_manifest(work_dir, manifest)

    timings["gesamt"] = time.monotonic() - started_at
    report = export_service.build_processing_report(
        manifest,
        {
            "whisperx": settings.whisper_model,
            "ollama": settings.ollama_model if settings.run_protocol else None,
        },
        timings,
    )
    report_paths = export_service.write_processing_report(work_dir, report)

    callbacks.on_stage("abgeschlossen", STAGE_LABELS["abgeschlossen"])
    callbacks.on_overall_progress(1.0)

    return PipelineResult(
        work_dir=work_dir,
        export_paths=export_paths,
        protocol_paths=protocol_paths,
        report_paths=report_paths,
        speaker_names=speaker_names,
        segments=merged_segments,
        manifest=manifest,
    )
