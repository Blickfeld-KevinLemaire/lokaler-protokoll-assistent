"""Tests fuer die Ablaufsteuerung von pipeline_service.run_pipeline.

Die schweren ML-Backends (WhisperX, pyannote, Ollama) werden durch
einfache Stub-Funktionen ersetzt, damit Resume-Verhalten und
Fehlerbehandlung eines einzelnen Chunks ohne GPU/echte Modelle getestet
werden koennen. FFmpeg-Aufrufe werden ebenfalls durch Stubs ersetzt, da in
dieser Sandbox kein FFmpeg installiert ist.
"""

from __future__ import annotations

import json

import pytest

import utils.paths as utils_paths
from services import ffmpeg_service, manifest_service, pipeline_service


@pytest.fixture()
def source_file(tmp_path):
    path = tmp_path / "aufnahme.wav"
    path.write_bytes(b"RIFF" + b"0" * 1000)
    return path


def _patch_ffmpeg(monkeypatch, total_duration: float):
    def fake_normalize(source, destination, ffmpeg_path=None, sample_rate=16000):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dummy-wav")
        return destination

    def fake_probe(path, ffprobe_path=None):
        return total_duration

    def fake_extract(normalized, destination, start, end, ffmpeg_path=None, sample_rate=16000):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dummy-chunk")
        return destination

    monkeypatch.setattr(pipeline_service.ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "normalize_audio", fake_normalize)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "probe_duration_seconds", fake_probe)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "extract_chunk_wav", fake_extract)


def _fake_diarize(normalized_path, min_speakers, max_speakers):
    return [{"start": 0.0, "end": 100000.0, "speaker": "SPEAKER_00"}]


def _make_settings(source_file, tmp_path, resume_mode="fortsetzen"):
    output_dir = tmp_path / "ausgabe"
    return pipeline_service.PipelineSettings(
        source_path=source_file,
        output_dir=output_dir,
        run_protocol=False,
        resume_mode=resume_mode,
    )


def test_pipeline_completes_with_stubbed_backends(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)  # < 600s -> genau ein Chunk

    def transcribe(chunk_wav_path):
        return [{"start": 1.0, "end": 5.0, "text": "Hallo Welt", "speaker": "SPEAKER_00"}]

    result = pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=transcribe,
        diarize_fn=_fake_diarize,
    )
    assert result.export_paths.txt.is_file()
    assert manifest_service.is_fully_processed(result.manifest)


def test_pipeline_stops_on_faulty_chunk_and_keeps_previous_progress(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    # 1300s -> 3 Chunks (0-600, 590-1190, 1180-1300).
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    call_count = {"n": 0}

    def flaky_transcribe(chunk_wav_path):
        call_count["n"] += 1
        if "chunk_0002" in chunk_wav_path.name:
            raise RuntimeError("Simulierter Absturz waehrend Chunk 2")
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            transcribe_chunk_fn=flaky_transcribe,
            diarize_fn=_fake_diarize,
        )
    assert call_count["n"] == 2  # Chunk 1 erfolgreich, Chunk 2 schlaegt fehl, Chunk 3 nie versucht

    work_dir = manifest_service.get_work_dir_for_file(
        tmp_path / "arbeitsdaten", manifest_service.compute_file_hash(source_file)
    )
    manifest = manifest_service.load_manifest(work_dir)
    state = manifest_service.find_resumable_state(manifest)
    assert state["fertige_chunks"] == [0]
    assert state["naechster_chunk"] == 1
    assert manifest_service.chunk_transcript_path(work_dir, 0).is_file()
    assert not manifest_service.chunk_transcript_path(work_dir, 1).is_file()


def test_pipeline_resume_does_not_recompute_finished_chunks(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    call_count = {"n": 0}

    def flaky_transcribe(chunk_wav_path):
        call_count["n"] += 1
        if "chunk_0002" in chunk_wav_path.name:
            raise RuntimeError("Simulierter Absturz waehrend Chunk 2")
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            transcribe_chunk_fn=flaky_transcribe,
            diarize_fn=_fake_diarize,
        )
    calls_before_resume = call_count["n"]

    def working_transcribe(chunk_wav_path):
        call_count["n"] += 1
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    result = pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=working_transcribe,
        diarize_fn=_fake_diarize,
    )
    # Nur die beiden verbleibenden Chunks (2 und 3) wurden neu transkribiert.
    assert call_count["n"] - calls_before_resume == 2
    assert manifest_service.is_fully_processed(result.manifest)
    assert result.export_paths.txt.is_file()


def test_pipeline_restart_mode_recomputes_everything(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    call_count = {"n": 0}

    def transcribe(chunk_wav_path):
        call_count["n"] += 1
        return [{"start": 1.0, "end": 5.0, "text": "Text", "speaker": "SPEAKER_00"}]

    settings = _make_settings(source_file, tmp_path)
    pipeline_service.run_pipeline(settings, transcribe_chunk_fn=transcribe, diarize_fn=_fake_diarize)
    assert call_count["n"] == 1

    restart_settings = _make_settings(source_file, tmp_path, resume_mode="neu_beginnen")
    pipeline_service.run_pipeline(restart_settings, transcribe_chunk_fn=transcribe, diarize_fn=_fake_diarize)
    assert call_count["n"] == 2  # wurde bewusst erneut komplett berechnet


def test_pipeline_raises_clear_error_for_missing_file(tmp_path):
    settings = _make_settings(tmp_path / "existiert_nicht.wav", tmp_path)
    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(settings)


def test_pipeline_can_be_cancelled_between_chunks(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    def transcribe(chunk_wav_path):
        return [{"start": 1.0, "end": 5.0, "text": "Text", "speaker": "SPEAKER_00"}]

    cancel_after = {"count": 0}

    def should_cancel():
        cancel_after["count"] += 1
        return cancel_after["count"] > 3

    callbacks = pipeline_service.PipelineCallbacks(should_cancel=should_cancel)
    with pytest.raises(pipeline_service.PipelineCancelled):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            callbacks=callbacks,
            transcribe_chunk_fn=transcribe,
            diarize_fn=_fake_diarize,
        )
