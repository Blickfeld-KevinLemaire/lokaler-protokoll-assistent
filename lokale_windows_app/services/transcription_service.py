"""Transkription ueber faster-whisper (Python-API, kein Kommandozeilenaufruf).

Audio wird bewusst vorab in den Speicher geladen (numpy-Array, 16kHz mono).
Dieses Array wird sowohl fuer die Transkription als auch -- als Torch-Tensor
verpackt -- fuer die Sprechertrennung (``diarization_service``) verwendet.
Dadurch muss pyannote die Datei nicht selbst ueber TorchCodec oeffnen, was
die im Auftrag beschriebene FFmpeg-9/TorchCodec-Inkompatibilitaet umgeht.

Frueher lief das ueber WhisperX. WhisperX ist aber nur eine Huelle um
faster-whisper und hat den ganzen Abhaengigkeitsbaum festgenagelt
('torch~=2.8.0', 'huggingface-hub<1.0.0'); dadurch waren 17 bekannte
Sicherheitsluecken unvermeidbar. Seit dem direkten Aufruf von
faster-whisper meldet pip-audit keine Luecken mehr. Die Feinausrichtung
der Wortzeitstempel ('whisperx.align') faellt damit weg -- die dabei
erzeugten Wortdaten wurden im Projekt nirgends gelesen, und die
Wortzeitstempel liefert faster-whisper mit 'word_timestamps=True' selbst.

Alle schweren Importe erfolgen lazy innerhalb der Funktionen, damit dieses
Modul auf einem Rechner ohne diese Abhaengigkeiten wenigstens importiert
werden kann.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any


def load_audio_array(path: Path):
    """Laedt eine (bereits normalisierte oder chunk-geschnittene) WAV-Datei
    als 16kHz-Mono-numpy-Array.

    ``decode_audio`` gehoert zu faster-whisper und benutzt PyAV, also die
    mitgelieferten Bibliotheken -- es wird KEIN ffmpeg-Programm auf dem
    Rechner gebraucht. Das Ergebnis entspricht dem frueheren
    ``whisperx.load_audio``.
    """
    from faster_whisper.audio import decode_audio  # type: ignore

    return decode_audio(str(path), sampling_rate=16000)


def load_whisper_model(
    model_name: str,
    device: str,
    compute_type: str,
    language: str | None,
):
    """Laedt das Whisper-Modell.

    ``language`` gehoert bei faster-whisper nicht zum Modell, sondern zum
    einzelnen Transkriptionsaufruf. Der Parameter bleibt erhalten, damit
    die Aufrufer unveraendert bleiben; ausgewertet wird er in
    ``transcribe_audio_array``.
    """
    # torch MUSS vor faster_whisper importiert werden. Erst der Import legt
    # die CUDA-Bibliotheken von PyTorch in den Suchpfad; ohne ihn findet
    # CTranslate2 'cublas64_12.dll' nicht und die Transkription bricht auf
    # der GPU ab. Bisher ging das nur gut, weil 'pipeline_service' vorher
    # zufaellig 'get_device_and_compute_type' aufruft, das torch importiert -
    # eine unsichtbare Abhaengigkeit von der Aufrufreihenfolge.
    # Am 19.09.2026 gemessen: ohne diesen Import scheitert die GPU, mit ihm
    # laeuft sie.
    import torch  # type: ignore  # noqa: F401
    from faster_whisper import WhisperModel  # type: ignore

    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _unterstuetzt_stapelverarbeitung(model) -> bool:
    """Nimmt ``model.transcribe`` ueberhaupt ein ``batch_size`` entgegen?

    ``faster_whisper.WhisperModel`` tut das nicht,
    ``faster_whisper.BatchedInferencePipeline`` schon. Blind uebergeben
    wuerde die Transkription beim ersten Chunk mit einem TypeError
    abbrechen, deshalb wird die Signatur gefragt statt geraten.
    """
    try:
        parameter = inspect.signature(model.transcribe).parameters
    except (TypeError, ValueError):
        return False
    if "batch_size" in parameter:
        return True
    return any(eintrag.kind is inspect.Parameter.VAR_KEYWORD for eintrag in parameter.values())


def transcribe_audio_array(
    model,
    audio_array,
    batch_size: int = 4,
    language: str | None = None,
) -> dict[str, Any]:
    """Transkribiert ein Audio-Array und liefert die frueher von WhisperX
    bekannte Ergebnisform ``{"segments": [...], "language": "de"}``.

    faster-whisper gibt die Segmente als Generator zurueck; er wird hier
    vollstaendig ausgewertet, damit die Aufrufer wie bisher eine Liste
    bekommen.

    ``batch_size`` wird nur uebergeben, wenn das Modell den Parameter
    kennt. Das ist beim hier benutzten ``WhisperModel`` NICHT der Fall --
    nur eine ``BatchedInferencePipeline`` wertet ihn aus. Bisher wurde der
    Wert gar nicht verwendet, obwohl er von der Oberflaeche ueber
    ``PipelineSettings`` bis hierher gereicht wird und die Beschreibung
    etwas anderes behauptete.
    """
    kwargs: dict[str, Any] = {
        "word_timestamps": True,
        "vad_filter": True,
    }
    if language:
        kwargs["language"] = language
    if batch_size and _unterstuetzt_stapelverarbeitung(model):
        kwargs["batch_size"] = batch_size

    segments, info = model.transcribe(audio_array, **kwargs)

    gesammelt: list[dict[str, Any]] = []
    for segment in segments:
        gesammelt.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": str(segment.text),
                "words": [
                    {
                        "word": wort.word,
                        "start": float(wort.start),
                        "end": float(wort.end),
                    }
                    for wort in (segment.words or [])
                ],
            }
        )

    return {
        "segments": gesammelt,
        "language": getattr(info, "language", language or "de"),
    }


def segments_to_plain(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Wandelt das Transkriptionsergebnis in die interne, einfache
    Segmentform ``{"start", "end", "text", "speaker"}`` um (lokale
    Chunk-Zeitstempel)."""
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
