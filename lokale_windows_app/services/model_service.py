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


@dataclass(frozen=True)
class WhisperModelOption:
    id: str
    label: str
    min_vram_gb: float
    hinweis: str


# Absteigend sortiert nach Anspruch (staerkstes zuerst) -- die
# Empfehlungslogik in ``empfehle_whisper_modell`` nutzt genau diese
# Reihenfolge. Alle Eintraege sind Standard-Modellnamen, die WhisperX
# (ueber faster-whisper/CTranslate2) direkt entgegennimmt; ein eigenes
# Herunterladen/Konvertieren ist nicht noetig. Zusaetzlich zu dieser Liste
# kann der Nutzer in der Oberflaeche auch eine beliebige andere gueltige
# WhisperX-/CTranslate2-Modell-ID frei eingeben (z.B. eine eigene
# Hugging-Face-Repo-ID) -- die Liste ist also eine kuratierte Auswahl
# bewaehrter Modelle, keine abschliessende Einschraenkung.
WHISPER_MODELLE: list[WhisperModelOption] = [
    WhisperModelOption(
        id="large-v3",
        label="Large v3 (beste Qualitaet, am langsamsten)",
        min_vram_gb=10.0,
        hinweis=(
            "Hoechste Genauigkeit, auch bei Akzenten, Dialekten und Fachbegriffen. "
            "Benoetigt die meiste GPU-Leistung/-Speicher."
        ),
    ),
    WhisperModelOption(
        id="large-v3-turbo",
        label="Large v3 Turbo (empfohlener Standard: sehr gut & deutlich schneller)",
        min_vram_gb=6.0,
        hinweis=(
            "Fast so genau wie Large v3, aber deutlich schneller und genuegsamer. "
            "Guter Standard fuer die meisten PCs mit einer aktuellen Mittelklasse-GPU."
        ),
    ),
    WhisperModelOption(
        id="distil-large-v3",
        label="Distil-Large v3 (sehr schnell, primaer fuer Englisch optimiert)",
        min_vram_gb=6.0,
        hinweis=(
            "Sehr schnell und genuegsam. Fuer deutsche Aufnahmen kann die Genauigkeit "
            "spuerbar niedriger sein als bei Large v3(-Turbo), da das Modell primaer "
            "fuer Englisch destilliert wurde."
        ),
    ),
    WhisperModelOption(
        id="medium",
        label="Medium (guter Kompromiss)",
        min_vram_gb=5.0,
        hinweis="Solide, mehrsprachige Qualitaet; laeuft auch auf kleineren GPUs.",
    ),
    WhisperModelOption(
        id="small",
        label="Small (schnell, genuegsam)",
        min_vram_gb=2.0,
        hinweis=(
            "Deutlich schneller, aber spuerbar weniger genau. Gut geeignet fuer "
            "schwaechere GPUs oder reinen CPU-Betrieb."
        ),
    ),
    WhisperModelOption(
        id="base",
        label="Base (sehr genuegsam)",
        min_vram_gb=1.0,
        hinweis="Nur fuer einfache Aufnahmen oder sehr schwache Hardware; fehleranfaelliger.",
    ),
    WhisperModelOption(
        id="tiny",
        label="Tiny (minimal, nur zum Ausprobieren)",
        min_vram_gb=0.0,
        hinweis="Nur zum schnellen Ausprobieren geeignet, nicht fuer echte Protokolle empfohlen.",
    ),
]

# CPU-Empfehlungen (kein GPU-Speicher erkannt), gestaffelt nach Arbeitsspeicher.
_CPU_EMPFEHLUNG_MIT_VIEL_RAM = "small"
_CPU_EMPFEHLUNG_STANDARD = "base"
_CPU_RAM_SCHWELLE_GB = 16.0


def empfehle_whisper_modell(vram_gb: float | None, ram_gb: float | None) -> str:
    """Liefert die ID des empfohlenen Whisper-Modells anhand der erkannten
    Hardware. Reine Heuristik, transparent nachvollziehbar -- der Nutzer
    sieht diese Empfehlung in der Oberflaeche und kann sie jederzeit durch
    ein anderes Modell aus ``WHISPER_MODELLE`` (oder eine freie Eingabe)
    ersetzen."""
    if vram_gb is not None and vram_gb > 0:
        for option in WHISPER_MODELLE:
            if vram_gb >= option.min_vram_gb:
                return option.id
        return WHISPER_MODELLE[-1].id

    # Keine GPU/kein VRAM erkannt -> CPU-Betrieb. Auf der CPU sind auch
    # kleinere Modelle bereits deutlich langsamer als auf einer GPU; groessere
    # Modelle werden hier bewusst nicht empfohlen (waeren zwar moeglich, aber
    # in der Praxis zu langsam fuer eine ganze Aufnahme).
    if ram_gb is not None and ram_gb >= _CPU_RAM_SCHWELLE_GB:
        return _CPU_EMPFEHLUNG_MIT_VIEL_RAM
    return _CPU_EMPFEHLUNG_STANDARD


def whisper_empfehlung_aus_diagnose(checks: list) -> str:
    """Wie ``empfehle_whisper_modell``, liest die Werte aber direkt aus den
    Ergebnissen von ``utils.diagnostics.run_diagnostics`` (Checks mit den
    Schluesseln ``vram``/``ram`` und den Zahlenwerten in ``.extra``)."""
    vram_gb = None
    ram_gb = None
    for check in checks:
        extra = getattr(check, "extra", None) or {}
        if getattr(check, "key", None) == "vram":
            vram_gb = extra.get("vram_gb")
        elif getattr(check, "key", None) == "ram":
            ram_gb = extra.get("ram_gb")
    return empfehle_whisper_modell(vram_gb, ram_gb)


def get_whisper_model_option(model_id: str) -> WhisperModelOption | None:
    for option in WHISPER_MODELLE:
        if option.id == model_id:
            return option
    return None


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
