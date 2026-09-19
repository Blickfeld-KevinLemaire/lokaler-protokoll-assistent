"""Reine Entscheidungslogik fuer die selbstinstallierende Laufzeitumgebung.

Dieses Modul trifft nur Entscheidungen (welche Pakete, welcher Torch-Index,
welche Python-Version ist geeignet) und baut die auszufuehrenden
pip-Befehle zusammen -- es fuehrt selbst NICHTS aus. Dadurch ist es ohne
echte Installation, ohne GPU und ohne Internetzugriff vollstaendig testbar.
Die tatsaechliche Ausfuehrung uebernimmt ``bootstrap.py``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SUPPORTED_PYTHON_VERSIONS = ((3, 10), (3, 11))

# CUDA-Wheel-Index fuer PyTorch. Bewusst eine breit unterstuetzte,
# stabile Version fuer "irgendeinen anderen PC" -- nicht zwingend identisch
# mit einer bereits manuell auf einem bestimmten Rechner eingerichteten
# neueren CUDA-Version. Fortgeschrittene Nutzer mit bereits vorhandener
# '.venv-whisperx' sind von dieser Auswahl ohnehin nicht betroffen (siehe
# utils.paths.get_active_venv_dir).
#
# Es gibt ZWEI CUDA-Indizes, weil kein einzelner alle Karten bedient:
#
#   * cu126 fuer alles bis einschliesslich Ada/Hopper. Dieser Index bringt
#     noch Kernel fuer aeltere Karten mit.
#   * cu129 fuer Blackwell (Rechenfaehigkeit 12.0 und hoeher, also RTX 50xx
#     und RTX PRO). Blackwell-Kernel (sm_120) gibt es erst ab CUDA 12.8 -
#     cu126 kennt sie nicht. Umgekehrt lassen die neuen Indizes die
#     aeltesten Karten fallen. Deshalb wird anhand der erkannten Karte
#     ausgewaehlt (siehe select_torch_index_url).
#
# Stand 19.09.2026 nicht mehr cu121: Dieser Index kannte hoechstens PyTorch
# 2.5.1, WhisperX verlangt aber inzwischen 'torch~=2.8.0'. Der zweite
# pip-Aufruf (Pakete von PyPI) hat den CUDA-Build deshalb kommentarlos
# durch einen PyPI-Build ersetzt - die GPU-Unterstuetzung war damit still
# weg, ohne jede Fehlermeldung. 'tools/laufzeit_pakete_pruefen.py' prueft
# genau das fuer beide Indizes.
TORCH_CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu126"
TORCH_CUDA_BLACKWELL_INDEX_URL = "https://download.pytorch.org/whl/cu129"

# Ab dieser Rechenfaehigkeit ist eine Karte eine Blackwell-Karte.
BLACKWELL_COMPUTE_CAPABILITY = (12, 0)
TORCH_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"

# Die Paketlisten stehen bewusst in Textdateien neben der Anwendung und nicht
# als Liste hier im Code: nur so sehen Dependabot und pip-audit sie. Als
# Python-Liste waren ausgerechnet die groessten und sicherheitsrelevantesten
# Pakete des Projekts (PyTorch, WhisperX, pyannote.audio) fuer beide
# unsichtbar - sie tauchten in keinem Manifest auf.
REQUIREMENTS_DIR = Path(__file__).resolve().parent.parent
TORCH_REQUIREMENTS_FILE = REQUIREMENTS_DIR / "requirements-torch.txt"
RUNTIME_REQUIREMENTS_FILE = REQUIREMENTS_DIR / "requirements-laufzeit.txt"


def read_requirements(path: Path) -> list[str]:
    """Liest eine requirements-Datei: eine Anforderung je Zeile.

    Kommentare ('#') und Leerzeilen werden uebersprungen. Bewusst kein
    vollstaendiger Parser -- diese Dateien werden von Hand oder von
    Dependabot gepflegt und enthalten nur einfache Anforderungen.
    """
    requirements = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            requirements.append(entry)
    return requirements


# Wird von einem eigenen Index von pytorch.org installiert (siehe oben).
TORCH_PACKAGES = read_requirements(TORCH_REQUIREMENTS_FILE)

# Alles Weitere kommt regulaer von PyPI.
RUNTIME_PACKAGES = read_requirements(RUNTIME_REQUIREMENTS_FILE)


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


def _pruefe_py_launcher_version(major: int, minor: int) -> Path | None:
    """Fragt (nur unter Windows sinnvoll) den 'py'-Launcher, ob eine
    bestimmte Python-Version bereits auf diesem Computer installiert ist,
    unabhaengig davon, mit welchem Python dieses Skript gerade laeuft.
    Installiert oder veraendert nichts -- reine Abfrage."""
    py_launcher = shutil.which("py")
    if not py_launcher:
        return None
    try:
        completed = subprocess.run(
            [py_launcher, f"-{major}.{minor}", "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    pfad_text = completed.stdout.strip()
    return Path(pfad_text) if pfad_text else None


def find_alternate_supported_python() -> Path | None:
    """Sucht nach einer bereits auf diesem Computer installierten,
    unterstuetzten Python-Version (3.10 oder 3.11) -- wird nur aufgerufen,
    wenn der aktuell aufgerufene Interpreter selbst NICHT unterstuetzt wird
    (z. B. Python 3.12/3.13). Installiert, laedt herunter oder veraendert
    bewusst nichts an diesem Computer; liefert nur einen bereits
    vorhandenen Pfad oder ``None``."""
    if sys.platform == "win32":
        for major, minor in SUPPORTED_PYTHON_VERSIONS:
            gefunden = _pruefe_py_launcher_version(major, minor)
            if gefunden is not None:
                return gefunden

    # Plattformuebergreifender Rueckfallweg ueber uebliche Befehlsnamen.
    for major, minor in SUPPORTED_PYTHON_VERSIONS:
        pfad = shutil.which(f"python{major}.{minor}")
        if pfad:
            return Path(pfad)
    return None


def detect_nvidia_gpu() -> bool:
    """Guenstige Vorab-Pruefung VOR der Torch-Installation: ist ueberhaupt
    ein NVIDIA-Treiber/-Werkzeug vorhanden? Die endgueltige Aussage, ob CUDA
    tatsaechlich nutzbar ist, liefert erst ``torch.cuda.is_available()`` nach
    der Installation (siehe ``services.model_service``)."""
    return shutil.which("nvidia-smi") is not None


def detect_compute_capability() -> tuple[int, int] | None:
    """Fragt die Rechenfaehigkeit der ersten NVIDIA-Karte beim Treiber ab.

    Geht ueber ``nvidia-smi`` und funktioniert damit schon VOR der
    Torch-Installation. Gibt z. B. ``(8, 6)`` fuer eine Ampere- oder
    ``(12, 0)`` fuer eine Blackwell-Karte zurueck, oder ``None``, wenn sich
    das nicht ermitteln laesst (kein Treiber, altes nvidia-smi, unerwartete
    Ausgabe). ``None`` ist kein Fehler -- es bedeutet nur, dass der
    Standard-Index genommen wird.
    """
    werkzeug = shutil.which("nvidia-smi")
    if werkzeug is None:
        return None
    try:
        completed = subprocess.run(
            [werkzeug, "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None

    erste_zeile = completed.stdout.strip().splitlines()
    if not erste_zeile:
        return None
    teile = erste_zeile[0].strip().split(".")
    if len(teile) != 2 or not all(teil.strip().isdigit() for teil in teile):
        return None
    return int(teile[0]), int(teile[1])


def select_torch_index_url(
    gpu_available: bool,
    compute_capability: tuple[int, int] | None = None,
) -> str:
    """Waehlt den Paket-Index fuer PyTorch passend zur gefundenen Karte.

    Ohne GPU: der CPU-Index. Mit GPU entscheidet die Rechenfaehigkeit,
    denn kein einzelner CUDA-Index bedient alle Karten (siehe oben).
    Laesst sie sich nicht ermitteln, wird der breiter unterstuetzte
    aeltere Index genommen -- er laeuft auf mehr Karten.
    """
    if not gpu_available:
        return TORCH_CPU_INDEX_URL
    if compute_capability is None:
        compute_capability = detect_compute_capability()
    if compute_capability is not None and compute_capability >= BLACKWELL_COMPUTE_CAPABILITY:
        return TORCH_CUDA_BLACKWELL_INDEX_URL
    return TORCH_CUDA_INDEX_URL


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
