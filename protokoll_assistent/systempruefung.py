"""Phase 1 (Systempruefung) und Phase 4 (Offline-Pruefung) der Einrichtung.

Wird von ``Einrichtung-Lokal.ps1`` in der benachbarten virtuellen Umgebung
``.venv-whisperx`` ausgefuehrt. Kann auch direkt aufgerufen werden, um den
Systemstatus jederzeit erneut zu pruefen, ohne die gesamte Einrichtung neu
zu starten.

Aufruf:
    python Systempruefung.py                 -> Phase 1: Systemvoraussetzungen
    python Systempruefung.py --offline-check  -> Phase 4: Offline-Funktionspruefung
"""

from __future__ import annotations

import argparse
import sys

from protokoll_assistent.utils import diagnostics, setup_status
from protokoll_assistent.utils.hf_env import enable_offline_mode
from protokoll_assistent.utils.paths import get_default_output_dir


def run_phase1() -> bool:
    print("=" * 72)
    print("PHASE 1: SYSTEMPRUEFUNG")
    print("=" * 72)

    checks = [
        diagnostics.check_python_version(),
        diagnostics.check_windows(),
        diagnostics.check_cuda(),
        diagnostics.check_gpu_vram(),
        diagnostics.check_ram(),
        diagnostics.check_disk_space(get_default_output_dir()),
        diagnostics.check_ffmpeg(),
        diagnostics.check_ffprobe(),
        diagnostics.check_ollama_installed(),
    ]
    print(diagnostics.format_report(checks))

    critical_failed = [c for c in checks if c.critical and not c.ok]
    ok = not critical_failed

    status = setup_status.load_status()
    setup_status.mark_phase(
        status,
        "systempruefung",
        ok,
        {check.key: check.ok for check in checks},
    )
    setup_status.save_status(status)

    if critical_failed:
        print("\nFEHLENDE VORAUSSETZUNGEN:")
        for check in critical_failed:
            print(f"  - {check.label}: {check.detail}")
        print(
            "\nBitte die fehlenden Voraussetzungen beheben und 'Systempruefung.py' erneut ausfuehren."
        )
    else:
        print("\nAlle kritischen Systemvoraussetzungen sind erfuellt.")
    return ok


def run_phase4_offline_check() -> bool:
    print("=" * 72)
    print("PHASE 4: OFFLINE-FUNKTIONSPRUEFUNG")
    print("=" * 72)

    enable_offline_mode()
    print("HF_HUB_OFFLINE=1 und TRANSFORMERS_OFFLINE=1 wurden fuer diese Pruefung gesetzt.")

    results: dict[str, bool] = {}

    ffmpeg_check = diagnostics.check_ffmpeg()
    ffprobe_check = diagnostics.check_ffprobe()
    results["ffmpeg"] = ffmpeg_check.ok
    results["ffprobe"] = ffprobe_check.ok
    print(f"FFmpeg: {'OK' if ffmpeg_check.ok else 'FEHLT'} -- {ffmpeg_check.detail}")
    print(f"ffprobe: {'OK' if ffprobe_check.ok else 'FEHLT'} -- {ffprobe_check.detail}")

    whisperx_check = diagnostics.check_whisperx_import()
    results["whisperx_import"] = whisperx_check.ok
    print(f"faster-whisper-Import: {'OK' if whisperx_check.ok else 'FEHLT'} -- {whisperx_check.detail}")

    pyannote_check = diagnostics.check_pyannote_import()
    results["pyannote_import"] = pyannote_check.ok
    print(f"pyannote-Import: {'OK' if pyannote_check.ok else 'FEHLT'} -- {pyannote_check.detail}")

    model_cache_check = diagnostics.check_model_cache()
    results["modell_cache"] = model_cache_check.ok
    print(f"Modell-Cache: {'OK' if model_cache_check.ok else 'FEHLT'} -- {model_cache_check.detail}")

    output_check = diagnostics.check_output_dir_writable(get_default_output_dir())
    results["schreibzugriff"] = output_check.ok
    print(f"Schreibzugriff: {'OK' if output_check.ok else 'FEHLT'} -- {output_check.detail}")

    ollama_running_check = diagnostics.check_ollama_running()
    results["ollama_erreichbar"] = ollama_running_check.ok
    print(f"Ollama erreichbar: {'OK' if ollama_running_check.ok else 'FEHLT'} -- {ollama_running_check.detail}")

    ollama_model_check = diagnostics.check_ollama_model()
    results["ollama_modell"] = ollama_model_check.ok
    print(f"Ollama-Modell: {'OK' if ollama_model_check.ok else 'FEHLT'} -- {ollama_model_check.detail}")

    ok = all(results.values())

    status = setup_status.load_status()
    setup_status.mark_phase(status, "offline_pruefung", ok, results)
    setup_status.save_status(status)

    if ok:
        print("\nOffline-Funktionspruefung erfolgreich: alle Komponenten funktionieren ohne Internetzugriff.")
    else:
        fehlend = [key for key, value in results.items() if not value]
        print(f"\nOffline-Funktionspruefung UNVOLLSTAENDIG. Fehlend/fehlerhaft: {', '.join(fehlend)}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Systempruefung fuer Protokoll-Assistent Lokal.")
    parser.add_argument(
        "--offline-check",
        action="store_true",
        help="Fuehrt stattdessen die Phase-4-Offline-Funktionspruefung aus.",
    )
    args = parser.parse_args()

    ok = run_phase4_offline_check() if args.offline_check else run_phase1()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
