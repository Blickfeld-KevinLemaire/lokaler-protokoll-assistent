"""Sprechertrennung mit pyannote -- Uebergabe als In-Memory-Waveform.

Statt pyannote die Audiodatei selbst oeffnen zu lassen (was ueber
TorchCodec laeuft und bei FFmpeg-Versionen ausserhalb 4-7 eine Warnung
ausloesen kann), wird das bereits geladene numpy-Array aus
``transcription_service.load_audio_array`` in einen Torch-Tensor
umgewandelt und pyannote als Waveform-Dictionary uebergeben:
``{"waveform": tensor, "sample_rate": 16000}``.
"""

from __future__ import annotations

from typing import Any

SAMPLE_RATE = 16000


def build_waveform_dict(audio_array, sample_rate: int = SAMPLE_RATE) -> dict[str, Any]:
    import torch  # type: ignore

    tensor = torch.from_numpy(audio_array).float()
    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    return {"waveform": tensor, "sample_rate": sample_rate}


def diarize_waveform(
    pipeline,
    waveform_dict: dict[str, Any],
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[dict[str, Any]]:
    """Fuehrt die Diarisierung aus und liefert eine einfache Liste globaler
    Sprecherabschnitte ``[{"start", "end", "speaker"}]``."""
    call_kwargs: dict[str, Any] = {}
    if min_speakers is not None:
        call_kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        call_kwargs["max_speakers"] = max_speakers

    annotation = pipeline(waveform_dict, **call_kwargs)

    turns = []
    for segment, _, speaker in annotation.itertracks(yield_label=True):
        turns.append({"start": float(segment.start), "end": float(segment.end), "speaker": str(speaker)})
    turns.sort(key=lambda turn: float(turn["start"]))  # type: ignore[arg-type]
    return turns


def extract_speaker_embedding(
    embedding_model,
    waveform_dict: dict[str, Any],
    start: float,
    end: float,
):
    """Best-Effort-Extraktion eines Sprecher-Embeddings fuer ein Zeitfenster.

    Wird ausschliesslich fuer den Rueckfallpfad (Embedding-basierte
    Zuordnung ueber Chunk-Grenzen, siehe ``speaker_merge_service``)
    benoetigt, wenn KEINE globale Diarisierung auf dem Gesamtaudio moeglich
    war.
    """

    waveform = waveform_dict["waveform"]
    sample_rate = waveform_dict["sample_rate"]
    start_sample = max(0, int(start * sample_rate))
    end_sample = min(waveform.shape[-1], int(end * sample_rate))
    if end_sample <= start_sample:
        return None
    cropped = {"waveform": waveform[:, start_sample:end_sample], "sample_rate": sample_rate}
    embedding = embedding_model(cropped)
    try:
        return embedding.flatten().tolist()
    except AttributeError:
        return list(embedding)
