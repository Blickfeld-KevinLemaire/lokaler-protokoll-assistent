"""Modell-/Cache-Verwaltung fuer WhisperX und pyannote.

Alle schweren Importe (torch, whisperx, huggingface_hub, pyannote) erfolgen
bewusst erst innerhalb der Funktionen ("lazy import"), damit dieses Modul
auch ohne installierte GPU-Abhaengigkeiten importiert und dessen reine
Hilfsfunktionen getestet werden koennen.

Offline-Verhalten: Wenn die benoetigten Modelle im lokalen Cache gefunden
werden, aktiviert ``prepare_offline_mode`` ``HF_HUB_OFFLINE=1`` und
``TRANSFORMERS_OFFLINE=1`` fuer die aktuelle Verarbeitung. Fehlt ein
Modell, wird das dem Aufrufer klar mitgeteilt, damit die Oberflaeche einen
bewussten, einmaligen Download anbieten kann -- es wird niemals
automatisch und unbemerkt online gegangen.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.hf_env import disable_offline_mode, enable_offline_mode, get_hf_token_for_download

WHISPER_MODEL_NAME = "large-v3-turbo"
PYANNOTE_MODEL_NAME = "pyannote/speaker-diarization-community-1"
PYANNOTE_LICENSE_URL = "https://huggingface.co/pyannote/speaker-diarization-community-1"


@dataclass
class ModelAvailability:
    whisper_ok: bool
    pyannote_ok: bool
    missing: list[str]


def check_model_cache() -> ModelAvailability:
    missing: list[str] = []
    pyannote_ok = True
    try:
        from huggingface_hub import scan_cache_dir  # type: ignore

        cache_info = scan_cache_dir()
        repo_ids = {repo.repo_id for repo in cache_info.repos}
        if PYANNOTE_MODEL_NAME not in repo_ids:
            pyannote_ok = False
            missing.append(PYANNOTE_MODEL_NAME)
    except Exception:
        pyannote_ok = False
        missing.append(PYANNOTE_MODEL_NAME)

    # WhisperX/faster-whisper verwaltet seinen eigenen Modell-Cache
    # (typischerweise ueber ctranslate2); ein direkter Cache-Scan ist dort
    # nicht über huggingface_hub moeglich. Der tatsaechliche Ladeversuch in
    # transcription_service liefert im Fehlerfall eine verstaendliche
    # Meldung, falls das Modell fehlt.
    whisper_ok = True

    return ModelAvailability(whisper_ok=whisper_ok, pyannote_ok=pyannote_ok, missing=missing)


def prepare_offline_mode(allow_download: bool) -> None:
    if allow_download:
        disable_offline_mode()
    else:
        enable_offline_mode()


def get_device_and_compute_type(requested_device: str = "cuda") -> tuple[str, str]:
    """Liefert (device, compute_type). Faellt kontrolliert auf CPU zurueck,
    wenn CUDA angefordert, aber nicht verfuegbar ist."""
    try:
        import torch  # type: ignore

        if requested_device == "cuda" and torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def get_gpu_description() -> str:
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
        return "keine CUDA-GPU erkannt (CPU-Verarbeitung)"
    except ImportError:
        return "PyTorch nicht installiert"


def load_pyannote_pipeline(device: str = "cuda"):
    """Laedt die pyannote-Diarisierungspipeline. Der HF_TOKEN wird nur zur
    direkten Weitergabe verwendet und niemals geloggt."""
    from pyannote.audio import Pipeline  # type: ignore
    import torch  # type: ignore

    token = get_hf_token_for_download()
    pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL_NAME, use_auth_token=token)
    pipeline.to(torch.device(device))
    return pipeline
