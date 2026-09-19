"""Diagnose- und Systempruef-Funktionen.

Diese Funktionen werden sowohl von der GUI ("Systemdiagnose"-Dialog) als
auch vom eigenstaendigen Einrichtungsskript ``Systempruefung.py`` verwendet.
Jede Pruefung ist einzeln gekapselt und faengt fehlende Abhaengigkeiten
(z.B. Torch/faster-whisper/pyannote/Ollama auf einem Entwicklungsrechner ohne
GPU) ab, damit eine einzelne fehlende Komponente nie das gesamte
Diagnoseergebnis zum Absturz bringt.

Es werden ausschliesslich Ja/Nein- bzw. informative Werte zurueckgegeben.
Der HF_TOKEN wird niemals im Klartext zurueckgegeben oder protokolliert.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

from services import environment_service, ffmpeg_service
from utils.hf_env import has_hf_token

REQUIRED_FREE_DISK_GB = 5.0
RECOMMENDED_RAM_GB = 16.0


@dataclass
class DiagnosticCheck:
    key: str
    label: str
    ok: bool
    detail: str
    critical: bool = False
    extra: dict = field(default_factory=dict)


def check_python_version() -> DiagnosticCheck:
    ok = environment_service.is_supported_python_version()
    unterstuetzt = ", ".join(
        f"{maj}.{min_}" for maj, min_ in environment_service.SUPPORTED_PYTHON_VERSIONS
    )
    detail = f"{platform.python_version()} (unterstuetzt: {unterstuetzt})"
    return DiagnosticCheck("python_version", "Python-Version", ok, detail, critical=True)


def check_windows() -> DiagnosticCheck:
    is_windows = platform.system() == "Windows"
    detail = platform.platform()
    return DiagnosticCheck(
        "windows", "Windows-Betriebssystem", is_windows, detail, critical=False
    )


def check_torch_installed() -> DiagnosticCheck:
    try:
        import torch  # type: ignore  # noqa: F401

        return DiagnosticCheck("torch", "PyTorch installiert", True, "Import erfolgreich.", critical=True)
    except ImportError as error:
        return DiagnosticCheck(
            "torch", "PyTorch installiert", False, f"Import fehlgeschlagen: {error}", critical=True
        )


def check_cuda() -> DiagnosticCheck:
    """Informativ, NICHT kritisch: die Anwendung unterstuetzt bewusst auch
    reinen CPU-Betrieb (deutlich langsamer, aber lauffaehig), damit sie auch
    auf einem PC ohne NVIDIA-GPU funktioniert."""
    try:
        import torch  # type: ignore

        available = bool(torch.cuda.is_available())
        if available:
            name = torch.cuda.get_device_name(0)
            detail = f"CUDA verfuegbar: {name}"
        else:
            detail = (
                "Keine CUDA-GPU erkannt -- die Verarbeitung laeuft auf der CPU "
                "(funktioniert, ist aber deutlich langsamer)."
            )
        return DiagnosticCheck("cuda", "GPU-Beschleunigung (CUDA)", available, detail, critical=False)
    except ImportError:
        return DiagnosticCheck(
            "cuda", "GPU-Beschleunigung (CUDA)", False, "PyTorch ist nicht installiert.", critical=False
        )
    except Exception as error:  # pragma: no cover - hardwareabhaengig
        return DiagnosticCheck(
            "cuda", "GPU-Beschleunigung (CUDA)", False, f"Fehler bei Pruefung: {error}", critical=False
        )


def check_gpu_vram() -> DiagnosticCheck:
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            return DiagnosticCheck("vram", "GPU-Speicher", False, "Keine CUDA-GPU verfuegbar.")
        total_bytes = torch.cuda.get_device_properties(0).total_memory
        total_gb = total_bytes / (1024**3)
        ok = total_gb >= 4.0
        return DiagnosticCheck(
            "vram", "GPU-Speicher", ok, f"{total_gb:.1f} GB VRAM erkannt.",
            extra={"vram_gb": total_gb},
        )
    except ImportError:
        return DiagnosticCheck("vram", "GPU-Speicher", False, "PyTorch ist nicht installiert.")
    except Exception as error:  # pragma: no cover - hardwareabhaengig
        return DiagnosticCheck("vram", "GPU-Speicher", False, f"Fehler bei Pruefung: {error}")


def check_ram() -> DiagnosticCheck:
    try:
        import psutil  # type: ignore

        total_gb = psutil.virtual_memory().total / (1024**3)
        ok = total_gb >= RECOMMENDED_RAM_GB
        return DiagnosticCheck(
            "ram", "Arbeitsspeicher", ok, f"{total_gb:.1f} GB erkannt.",
            extra={"ram_gb": total_gb},
        )
    except ImportError:
        return DiagnosticCheck(
            "ram", "Arbeitsspeicher", True, "psutil nicht installiert, Pruefung uebersprungen.", critical=False
        )


def check_disk_space(path: str | os.PathLike) -> DiagnosticCheck:
    try:
        usage = shutil.disk_usage(str(path))
        free_gb = usage.free / (1024**3)
        ok = free_gb >= REQUIRED_FREE_DISK_GB
        return DiagnosticCheck(
            "disk_space", "Freier Speicherplatz", ok, f"{free_gb:.1f} GB frei unter {path}."
        )
    except OSError as error:
        return DiagnosticCheck("disk_space", "Freier Speicherplatz", False, str(error))


def check_ffmpeg() -> DiagnosticCheck:
    found = ffmpeg_service.find_ffmpeg()
    if not found:
        return DiagnosticCheck(
            "ffmpeg", "FFmpeg", False, "FFmpeg wurde nicht gefunden.", critical=True
        )
    version = ffmpeg_service.get_tool_version(found)
    return DiagnosticCheck("ffmpeg", "FFmpeg", True, f"{found} ({version})", critical=True)


def check_ffprobe() -> DiagnosticCheck:
    found = ffmpeg_service.find_ffprobe()
    if not found:
        return DiagnosticCheck(
            "ffprobe", "ffprobe", False, "ffprobe wurde nicht gefunden.", critical=True
        )
    version = ffmpeg_service.get_tool_version(found)
    return DiagnosticCheck("ffprobe", "ffprobe", True, f"{found} ({version})", critical=True)


def check_whisperx_import() -> DiagnosticCheck:
    """Prueft die Transkriptionsbibliothek.

    Der Name bleibt aus Ruecksicht auf bestehende Aufrufer und gespeicherte
    Diagnoseberichte erhalten; geprueft wird seit dem Wegfall von WhisperX
    'faster_whisper' (WhisperX war ohnehin nur eine Huelle darum).
    """
    try:
        import faster_whisper  # type: ignore  # noqa: F401

        return DiagnosticCheck(
            "whisperx", "faster-whisper", True, "Import erfolgreich.", critical=True
        )
    except ImportError as error:
        return DiagnosticCheck(
            "whisperx", "faster-whisper", False, f"Import fehlgeschlagen: {error}", critical=True
        )


def check_pyannote_import() -> DiagnosticCheck:
    try:
        import pyannote.audio  # type: ignore  # noqa: F401

        return DiagnosticCheck("pyannote", "pyannote.audio", True, "Import erfolgreich.", critical=True)
    except ImportError as error:
        return DiagnosticCheck("pyannote", "pyannote.audio", False, f"Import fehlgeschlagen: {error}", critical=True)


def check_model_cache() -> DiagnosticCheck:
    try:
        from huggingface_hub import scan_cache_dir  # type: ignore

        cache_info = scan_cache_dir()
        repo_ids = {repo.repo_id for repo in cache_info.repos}
        needed = {
            "pyannote/speaker-diarization-community-1",
        }
        missing = needed - repo_ids
        ok = not missing
        detail = "Alle benoetigten Modelle im Cache." if ok else f"Fehlend im Cache: {', '.join(sorted(missing))}"
        return DiagnosticCheck("model_cache", "Modell-Cache", ok, detail)
    except ImportError:
        return DiagnosticCheck(
            "model_cache", "Modell-Cache", False, "huggingface_hub nicht installiert."
        )
    except Exception as error:  # pragma: no cover - abhaengig vom lokalen Cache
        return DiagnosticCheck("model_cache", "Modell-Cache", False, f"Cache konnte nicht gelesen werden: {error}")


def check_hf_token() -> DiagnosticCheck:
    present = has_hf_token()
    detail = "HF_TOKEN ist gesetzt." if present else "HF_TOKEN ist nicht gesetzt."
    return DiagnosticCheck("hf_token", "HF_TOKEN vorhanden", present, detail)


def check_output_dir_writable(path: str | os.PathLike) -> DiagnosticCheck:
    from pathlib import Path

    target = Path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe_file = target / ".schreibtest.tmp"
        probe_file.write_text("test", encoding="utf-8")
        probe_file.unlink()
        return DiagnosticCheck("output_writable", "Ausgabeordner beschreibbar", True, str(target))
    except OSError as error:
        return DiagnosticCheck("output_writable", "Ausgabeordner beschreibbar", False, str(error), critical=True)


def check_ollama_installed() -> DiagnosticCheck:
    from services import ollama_service

    path = ollama_service.find_ollama_executable()
    ok = path is not None
    detail = str(path) if path else "Ollama-Programm wurde nicht gefunden."
    return DiagnosticCheck("ollama_installed", "Ollama installiert", ok, detail)


def check_ollama_running() -> DiagnosticCheck:
    from services import ollama_service

    ok = ollama_service.is_service_running()
    detail = "Ollama-Dienst antwortet." if ok else "Ollama-Dienst antwortet nicht (laeuft er?)."
    return DiagnosticCheck("ollama_running", "Ollama-Dienst erreichbar", ok, detail)


def check_ollama_model() -> DiagnosticCheck:
    from services import ollama_service

    try:
        ok = ollama_service.is_model_available(ollama_service.DEFAULT_MODEL)
        detail = (
            f"Modell '{ollama_service.DEFAULT_MODEL}' vorhanden."
            if ok
            else f"Modell '{ollama_service.DEFAULT_MODEL}' fehlt (ollama pull {ollama_service.DEFAULT_MODEL})."
        )
        return DiagnosticCheck("ollama_model", "Ollama-Modell vorhanden", ok, detail)
    except Exception as error:
        return DiagnosticCheck("ollama_model", "Ollama-Modell vorhanden", False, str(error))


def run_diagnostics(output_dir: str | os.PathLike | None = None) -> list[DiagnosticCheck]:
    from utils.paths import get_default_output_dir

    output_dir = output_dir or get_default_output_dir()
    checks = [
        check_python_version(),
        check_windows(),
        check_torch_installed(),
        check_cuda(),
        check_gpu_vram(),
        check_ram(),
        check_disk_space(output_dir),
        check_ffmpeg(),
        check_ffprobe(),
        check_whisperx_import(),
        check_pyannote_import(),
        check_model_cache(),
        check_hf_token(),
        check_output_dir_writable(output_dir),
        check_ollama_installed(),
        check_ollama_running(),
        check_ollama_model(),
    ]
    return checks


def format_report(checks: list[DiagnosticCheck]) -> str:
    lines = []
    for check in checks:
        symbol = "[OK]" if check.ok else ("[FEHLT]" if check.critical else "[HINWEIS]")
        lines.append(f"{symbol:10s} {check.label}: {check.detail}")
    return "\n".join(lines)


if __name__ == "__main__":
    results = run_diagnostics()
    print(format_report(results))
    failed_critical = [c for c in results if c.critical and not c.ok]
    sys.exit(1 if failed_critical else 0)
