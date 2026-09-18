"""WhisperX-Transkription ueber die Python-API (kein Kommandozeilen-Aufruf).

Audio wird bewusst vorab per ``whisperx.load_audio`` in den Speicher
geladen (numpy-Array, 16kHz mono). Dieses Array wird sowohl fuer die
Transkription als auch -- als Torch-Tensor verpackt -- fuer die
Sprechertrennung (``diarization_service``) verwendet. Dadurch muss
pyannote die Datei nicht selbst ueber TorchCodec oeffnen, was die im
Auftrag beschriebene FFmpeg-9/TorchCodec-Inkompatibilitaet umgeht.

Alle schweren Importe (torch, whisperx) erfolgen lazy innerhalb der
Funktionen, damit dieses Modul auf einem Rechner ohne diese
Abhaengigkeiten wenigstens importiert werden kann.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_audio_array(path: Path):
    """Laedt eine (bereits normalisierte oder chunk-geschnittene) WAV-Datei
    als 16kHz-Mono-numpy-Array -- identisch zu WhisperX' eigenem Loader."""
    import whisperx  # type: ignore

    return whisperx.load_audio(str(path))


def load_whisper_model(
    model_name: str,
    device: str,
    compute_type: str,
    language: str | None,
):
    import whisperx  # type: ignore

    return whisperx.load_model(
        model_name,
        device=device,
        compute_type=compute_type,
        language=language,
    )


def transcribe_audio_array(
    model,
    audio_array,
    batch_size: int = 4,
    language: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"batch_size": batch_size}
    if language:
        kwargs["language"] = language
    return model.transcribe(audio_array, **kwargs)


def load_align_model(language_code: str, device: str):
    import whisperx  # type: ignore

    align_model, metadata = whisperx.load_align_model(language_code=language_code, device=device)
    return align_model, metadata


def align_segments(
    segments: list[dict[str, Any]],
    align_model,
    metadata,
    audio_array,
    device: str,
) -> dict[str, Any]:
    import whisperx  # type: ignore

    return whisperx.align(
        segments,
        align_model,
        metadata,
        audio_array,
        device,
        return_char_alignments=False,
    )


def segments_to_plain(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Wandelt das WhisperX-Ergebnis in die interne, einfache Segmentform
    ``{"start", "end", "text", "speaker"}`` um (lokale Chunk-Zeitstempel)."""
    plain = []
    for segment in result.get("segments", []):
        plain.append(
            {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
                "text": str(segment.get("text", "")).strip(),
                "speaker": segment.get("speaker"),
                "words": segment.get("words", []),
            }
        )
    return plain
