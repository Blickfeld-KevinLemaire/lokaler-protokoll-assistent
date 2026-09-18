"""Reine Entscheidungslogik fuer die selbstinstallierende Laufzeitumgebung.

Dieses Modul trifft nur Entscheidungen (welche Pakete, welcher Torch-Index,
welche Python-Version ist geeignet) und baut die auszufuehrenden
pip-Befehle zusammen -- es fuehrt selbst NICHTS aus. Dadurch ist es ohne
echte Installation, ohne GPU und ohne Internetzugriff vollstaendig testbar.
Die tatsaechliche Ausfuehrung uebernimmt ``bootstrap.py``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SUPPORTED_PYTHON_VERSIONS = ((3, 10), (3, 11))

# CUDA-Wheel-Index fuer PyTorch. Bewusst eine breit unterstuetzte,
# stabile Version fuer "irgendeinen anderen PC" -- nicht zwingend identisch
# mit einer bereits manuell auf einem bestimmten Rechner eingerichteten
# neueren CUDA-Version. Fortgeschrittene Nutzer mit bereits vorhandener
# '.venv-whisperx' sind von dieser Auswahl ohnehin nicht betroffen (siehe
# utils.paths.get_active_venv_dir).
TORCH_CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu121"
TORCH_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"

TORCH_PACKAGES = ["torch", "torchaudio"]

# Alles Weitere kommt regulaer von PyPI.
RUNTIME_PACKAGES = [
    "PySide6>=6.6,<7",
    "whisperx>=3.1",
    "pyannote.audio>=3.1",
    "huggingface_hub>=0.23",
    "python-docx>=1.1",
]


def is_supported_python_version(version_info: tuple[int, int] | None = None) -> bool:
    major_minor = version_info or (sys.version_info.major, sys.version_info.minor)
    return tuple(major_minor) in SUPPORTED_PYTHON_VERSIONS


def python_version_error_message(version_info: tuple[int, int] | None = None) -> str:
    major, minor = version_info or (sys.version_info.major, sys.version_info.minor)
    supported = ", ".join(f"{maj}.{min_}" for maj, min_ in SUPPORTED_PYTHON_VERSIONS)
    return (
        f"Python {major}.{minor} wird nicht unterstuetzt (benoetigt: {supported}). "
        "Bitte eine unterstuetzte Python-Version von https://www.python.org/downloads/ "
        "installieren und die Anwendung erneut starten."
    )


def detect_nvidia_gpu() -> bool:
    """Guenstige Vorab-Pruefung VOR der Torch-Installation: ist ueberhaupt
    ein NVIDIA-Treiber/-Werkzeug vorhanden? Die endgueltige Aussage, ob CUDA
    tatsaechlich nutzbar ist, liefert erst ``torch.cuda.is_available()`` nach
    der Installation (siehe ``services.model_service``)."""
    return shutil.which("nvidia-smi") is not None


def select_torch_index_url(gpu_available: bool) -> str:
    return TORCH_CUDA_INDEX_URL if gpu_available else TORCH_CPU_INDEX_URL


def build_pip_install_commands(python_exe: Path, gpu_available: bool) -> list[list[str]]:
    """Baut die auszufuehrenden pip-Befehle als Liste von Argumentlisten
    (keine Shell-Interpolation, keine ungeprueften Benutzereingaben)."""
    python_str = str(python_exe)
    index_url = select_torch_index_url(gpu_available)

    commands = [
        [python_str, "-m", "pip", "install", "--upgrade", "pip"],
        [
            python_str,
            "-m",
            "pip",
            "install",
            "--index-url",
            index_url,
            *TORCH_PACKAGES,
        ],
        [python_str, "-m", "pip", "install", *RUNTIME_PACKAGES],
    ]
    return commands


def describe_plan(gpu_available: bool) -> str:
    geraet = "GPU (CUDA)" if gpu_available else "CPU (keine NVIDIA-GPU erkannt -- deutlich langsamer)"
    return (
        f"Geplante Installation fuer: {geraet}\n"
        f"  - PyTorch/torchaudio von: {select_torch_index_url(gpu_available)}\n"
        f"  - Weitere Pakete: {', '.join(RUNTIME_PACKAGES)}"
    )
