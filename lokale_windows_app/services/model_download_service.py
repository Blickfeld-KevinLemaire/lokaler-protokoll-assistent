"""Wiederverwendbare Logik zum einmaligen Herunterladen aller lokalen Modelle.

Wird sowohl vom eigenstaendigen Skript ``Modelle-herunterladen.py`` (Konsole,
``print``/``getpass``) als auch vom GUI-Einrichtungsassistenten
(``gui/wizard.py``, Qt-Signale statt Konsole) verwendet. Die eigentliche
Logik ist bewusst an dieser Stelle einmal implementiert.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from services import model_service, ollama_service
from utils.hf_env import has_hf_token

LogFn = Callable[[str], None]
TokenProviderFn = Callable[[], str | None]


def download_whisper_and_alignment(log: LogFn, model_name: str | None = None) -> bool:
    model_name = model_name or model_service.WHISPER_MODEL_NAME
    log(f"Whisper-Modell ({model_name}) ...")
    try:
        from faster_whisper import WhisperModel  # type: ignore

        device, compute_type = model_service.get_device_and_compute_type()
        log(f"Geraet: {device} ({compute_type})")
        # Das Anlegen laedt das Modell bei Bedarf herunter und legt es im
        # Zwischenspeicher ab - genau das ist hier gewollt.
        WhisperModel(model_name, device=device, compute_type=compute_type)
        log("Whisper-Modell verfuegbar.")
        # Ein eigenes Alignment-Modell wird nicht mehr gebraucht:
        # faster-whisper liefert die Wortzeitstempel selbst.
        return True
    except ImportError as error:
        log(f"FEHLER: faster-whisper ist nicht installiert ({error}).")
        return False
    except Exception as error:
        log(f"FEHLER beim Laden des Whisper-Modells: {error}")
        return False


def download_pyannote(log: LogFn, get_token: TokenProviderFn | None = None) -> bool:
    import os

    log("pyannote-Modell (speaker-diarization-community-1) ...")
    if not has_hf_token() and get_token is not None:
        token = get_token()
        if token:
            os.environ["HF_TOKEN"] = token

    try:
        model_service.load_pyannote_pipeline(device="cpu")
        log("pyannote-Modell verfuegbar.")
        return True
    except ImportError as error:
        log(f"FEHLER: pyannote.audio ist nicht installiert ({error}).")
        return False
    except Exception as error:
        message = str(error)
        if "gated" in message.lower() or "401" in message or "403" in message:
            log(
                "FEHLER: Die Nutzungsbedingungen des pyannote-Modells wurden vermutlich "
                "noch nicht akzeptiert. Bitte folgenden Link oeffnen, anmelden und die "
                f"Bedingungen akzeptieren:\n  {model_service.PYANNOTE_LICENSE_URL}"
            )
        else:
            log(f"FEHLER beim Laden des pyannote-Modells: {error}")
        return False


def download_ollama_model(log: LogFn, model: str = ollama_service.DEFAULT_MODEL) -> bool:
    log(f"Ollama-Modell ({model}) ...")
    executable = ollama_service.find_ollama_executable()
    if executable is None:
        log("FEHLER: Ollama wurde nicht gefunden.")
        return False
    if not ollama_service.is_service_running():
        log("FEHLER: Der Ollama-Dienst laeuft nicht.")
        return False
    if ollama_service.is_model_available(model):
        log(f"Modell '{model}' ist bereits vorhanden.")
        return True

    log(f"Lade Modell '{model}' herunter (kann mehrere Minuten dauern) ...")
    completed = subprocess.run([str(executable), "pull", model], check=False)
    if completed.returncode != 0:
        log(f"FEHLER: 'ollama pull {model}' ist fehlgeschlagen.")
        return False
    log(f"Modell '{model}' erfolgreich heruntergeladen.")
    return True


def download_all_models(
    log: LogFn, get_token: TokenProviderFn | None = None, whisper_model: str | None = None
) -> dict[str, bool]:
    """Fuehrt alle drei Download-Schritte nacheinander aus und gibt das
    Ergebnis je Schritt zurueck (fuer Einrichtungsstatus.json / Anzeige).

    Wird vom Konsolen-/Automatisierungsweg (``Modelle-herunterladen.py``)
    verwendet, der -- anders als der GUI-Assistent -- keine interaktive
    Hardware-basierte Modellempfehlung anzeigt. Ohne ``whisper_model`` wird
    das Standardmodell aus ``model_service.WHISPER_MODEL_NAME`` geladen."""
    return {
        "whisperx_und_alignment": download_whisper_and_alignment(log, model_name=whisper_model),
        "pyannote": download_pyannote(log, get_token=get_token),
        "ollama_modell": download_ollama_model(log),
    }
