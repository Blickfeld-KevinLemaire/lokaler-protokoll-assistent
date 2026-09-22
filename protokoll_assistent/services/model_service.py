"""Modell-/Cache-Verwaltung fuer faster-whisper und pyannote.

Alle schweren Importe (torch, faster_whisper, huggingface_hub, pyannote) erfolgen
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

from protokoll_assistent.utils.hf_env import disable_offline_mode, enable_offline_mode, get_hf_token_for_download

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
# Reihenfolge. Alle Eintraege sind Standard-Modellnamen, die
# faster-whisper (ueber CTranslate2) direkt entgegennimmt; ein eigenes
# Herunterladen/Konvertieren ist nicht noetig. Zusaetzlich zu dieser Liste
# kann der Nutzer in der Oberflaeche auch eine beliebige andere gueltige
# faster-whisper-/CTranslate2-Modell-ID frei eingeben (z.B. eine eigene
# Hugging-Face-Repo-ID) -- die Liste ist also eine kuratierte Auswahl
# bewaehrter Modelle, keine abschliessende Einschraenkung.
WHISPER_MODELLE: list[WhisperModelOption] = [
    WhisperModelOption(
        id="large-v3",
        label="Large v3 (beste Qualitaet, am langsamsten)",
        min_vram_gb=6.0,
        hinweis=(
            "Hoechste Genauigkeit, auch bei Akzenten, Dialekten und Fachbegriffen. "
            "Benoetigt die meiste GPU-Leistung/-Speicher."
        ),
    ),
    WhisperModelOption(
        id="large-v3-turbo",
        label="Large v3 Turbo (empfohlener Standard: sehr gut & deutlich schneller)",
        min_vram_gb=3.0,
        hinweis=(
            "Fast so genau wie Large v3, aber deutlich schneller und genuegsamer. "
            "Guter Standard fuer die meisten PCs mit einer aktuellen Mittelklasse-GPU."
        ),
    ),
    WhisperModelOption(
        id="distil-large-v3",
        label="Distil-Large v3 (sehr schnell, primaer fuer Englisch optimiert)",
        min_vram_gb=3.0,
        hinweis=(
            "Sehr schnell und genuegsam. Fuer deutsche Aufnahmen kann die Genauigkeit "
            "spuerbar niedriger sein als bei Large v3(-Turbo), da das Modell primaer "
            "fuer Englisch destilliert wurde."
        ),
    ),
    WhisperModelOption(
        id="medium",
        label="Medium (nicht mehr empfohlen)",
        min_vram_gb=3.0,
        hinweis=(
            "Wird von Large v3 Turbo in jeder Hinsicht uebertroffen: gemessen "
            "schlechter (11,2 % statt 5,2 % Abweichung), langsamer und mit mehr "
            "Speicherbedarf. Nur noch der Vollstaendigkeit halber aufgefuehrt."
        ),
    ),
    WhisperModelOption(
        id="small",
        label="Small (schnell, genuegsam)",
        min_vram_gb=1.5,
        hinweis=(
            "Deutlich schneller, aber spuerbar weniger genau. Gut geeignet fuer "
            "schwaechere GPUs oder reinen CPU-Betrieb."
        ),
    ),
    WhisperModelOption(
        id="base",
        label="Base (sehr genuegsam)",
        min_vram_gb=0.8,
        hinweis="Nur fuer einfache Aufnahmen oder sehr schwache Hardware; fehleranfaelliger.",
    ),
    WhisperModelOption(
        id="tiny",
        label="Tiny (minimal, nur zum Ausprobieren)",
        min_vram_gb=0.5,
        hinweis="Nur zum schnellen Ausprobieren geeignet, nicht fuer echte Protokolle empfohlen.",
    ),
]

# Gemessener Bedarf von 'large-v3-turbo' (19.09.2026, NVIDIA RTX PRO 500,
# Abschnitt von 10 Minuten -- also der laengste, der am Stueck verarbeitet
# wird, siehe chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS):
#
#   auf der GPU (float16):  2,26 GB Grafikspeicher
#   auf der CPU  (int8)  :  2,04 GB Arbeitsspeicher
#
# Der Zuschlag deckt ab, was daneben noch Speicher braucht: die
# Sprechertrennung (pyannote), der Desktop und andere Programme.
TURBO_VRAM_BEDARF_GB = 2.26
TURBO_RAM_BEDARF_GB = 2.04
SPEICHER_ZUSCHLAG_GB = 1.5


def empfehle_whisper_modell(vram_gb: float | None, ram_gb: float | None) -> str:
    """Liefert die ID des empfohlenen Whisper-Modells.

    Empfohlen wird IMMER ``large-v3-turbo`` -- unabhaengig von der Hardware.
    Das ist keine Bequemlichkeit, sondern das Ergebnis von Messungen am
    19.09.2026 auf einer echten deutschen Aufnahme:

    * Turbo weicht nur **5,2 %** von ``large-v3`` ab, braucht aber statt
      5,29 GB nur 2,26 GB und ist siebenmal schneller.
    * ``medium`` ist durchgehend schlechter als ``small`` (11,2 % statt
      10,0 % Abweichung), langsamer UND speicherhungriger -- es gibt keine
      Hardware, auf der es die richtige Wahl waere.
    * ``base`` (20,9 %) und ``tiny`` (30,9 %) sind fuer echte Protokolle
      unbrauchbar: jedes fuenfte bzw. fast jedes dritte Wort weicht ab.
    * Turbo laeuft auch ohne Grafikkarte schnell genug (3,8-fache
      Echtzeit, 2,04 GB Arbeitsspeicher) -- der frueher uebliche Rueckgriff
      auf kleinere Modelle im CPU-Betrieb ist damit hinfaellig.

    Reicht der Speicher nicht, wird trotzdem Turbo empfohlen und der Nutzer
    ueber ``speicherwarnung`` darauf hingewiesen, dass er Programme
    schliessen sollte. Er kann in der Oberflaeche jederzeit ein anderes
    Modell aus ``WHISPER_MODELLE`` waehlen (``small`` ist der genuegsame
    Rueckfall, ``large-v3`` die Wahl fuer besonders schwieriges Material).

    Die Parameter bleiben erhalten, damit die Aufrufer unveraendert
    funktionieren; ausgewertet werden sie nur noch von
    ``speicherwarnung``.
    """
    return WHISPER_MODEL_NAME


def speicherwarnung(vram_gb: float | None, ram_gb: float | None) -> str | None:
    """Warnt, wenn der Speicher fuer das empfohlene Modell knapp wird.

    Gibt einen fertigen Hinweistext zurueck oder ``None``, wenn genug
    Speicher da ist. Bewusst nur ein Hinweis und kein stiller Wechsel auf
    ein schwaecheres Modell: Wer Programme schliesst, bekommt die volle
    Qualitaet -- und wer das nicht will, waehlt selbst ein kleineres
    Modell.
    """
    if vram_gb is not None and vram_gb > 0:
        noetig = TURBO_VRAM_BEDARF_GB + SPEICHER_ZUSCHLAG_GB
        if vram_gb < noetig:
            return (
                f"Die Grafikkarte hat {vram_gb:.1f} GB Speicher. Fuer das "
                f"empfohlene Modell '{WHISPER_MODEL_NAME}' werden rund "
                f"{TURBO_VRAM_BEDARF_GB:.1f} GB gebraucht, dazu etwas Reserve "
                "fuer die Sprechertrennung. Bitte andere Programme schliessen, "
                "die die Grafikkarte belegen (Spiele, Videobearbeitung, "
                "Browser mit vielen Registerkarten). Alternativ in der "
                "Modellauswahl 'small' waehlen - das braucht deutlich weniger "
                "Speicher, erkennt aber merklich ungenauer."
            )
        return None

    if ram_gb is not None and ram_gb > 0:
        noetig = TURBO_RAM_BEDARF_GB + SPEICHER_ZUSCHLAG_GB
        if ram_gb < noetig:
            return (
                f"Der Rechner hat {ram_gb:.1f} GB Arbeitsspeicher. Fuer das "
                f"empfohlene Modell '{WHISPER_MODEL_NAME}' werden rund "
                f"{TURBO_RAM_BEDARF_GB:.1f} GB gebraucht. Bitte andere "
                "Programme schliessen. Alternativ in der Modellauswahl "
                "'small' waehlen - das braucht weniger Speicher, erkennt "
                "aber merklich ungenauer."
            )
    return None


def _speicher_aus_diagnose(checks: list) -> tuple[float | None, float | None]:
    """Liest Grafik- und Arbeitsspeicher aus den Ergebnissen von
    ``utils.diagnostics.run_diagnostics`` (Checks mit den Schluesseln
    ``vram``/``ram`` und den Zahlenwerten in ``.extra``)."""
    vram_gb = None
    ram_gb = None
    for check in checks:
        extra = getattr(check, "extra", None) or {}
        if getattr(check, "key", None) == "vram":
            vram_gb = extra.get("vram_gb")
        elif getattr(check, "key", None) == "ram":
            ram_gb = extra.get("ram_gb")
    return vram_gb, ram_gb


def whisper_empfehlung_aus_diagnose(checks: list) -> str:
    """Wie ``empfehle_whisper_modell``, aber mit den Werten aus der
    Systemdiagnose."""
    vram_gb, ram_gb = _speicher_aus_diagnose(checks)
    return empfehle_whisper_modell(vram_gb, ram_gb)


def speicherwarnung_aus_diagnose(checks: list) -> str | None:
    """Wie ``speicherwarnung``, aber mit den Werten aus der Systemdiagnose."""
    vram_gb, ram_gb = _speicher_aus_diagnose(checks)
    return speicherwarnung(vram_gb, ram_gb)


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

    # faster-whisper verwaltet seinen eigenen Modell-Cache
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


def cuda_kann_wirklich_rechnen() -> bool:
    """Prueft, ob auf der GPU tatsaechlich gerechnet werden kann.

    ``torch.cuda.is_available()`` allein genuegt dafuer NICHT: Passt der
    CUDA-Build nicht zur Kartengeneration -- etwa ein cu126-Build auf einer
    Blackwell-Karte --, meldet es trotzdem ``True``. Erst die erste echte
    Rechnung scheitert dann mit "no kernel image is available for execution
    on the device", und zwar mitten in der Transkription.

    Deshalb wird hier einmal wirklich gerechnet. Das kostet Millisekunden
    und erspart einen Abbruch nach langer Laufzeit.
    """
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            return False
        probe = torch.zeros(8, 8, device="cuda")
        (probe + 1).sum().item()
        return True
    except Exception:
        # Jede Art von Fehler bedeutet hier dasselbe: die GPU ist nicht
        # benutzbar, also wird auf der CPU weitergearbeitet.
        return False


def get_device_and_compute_type(requested_device: str = "cuda") -> tuple[str, str]:
    """Liefert (device, compute_type). Faellt kontrolliert auf CPU zurueck,
    wenn CUDA angefordert, aber nicht benutzbar ist."""
    if requested_device == "cuda" and cuda_kann_wirklich_rechnen():
        return "cuda", "float16"
    return "cpu", "int8"


def get_gpu_description() -> str:
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            # Auch der Fall "AMD- oder Intel-Grafikkarte vorhanden": Die
            # Beschleunigung laeuft ueber CUDA, und CTranslate2 (ueber
            # faster-whisper der Kern der Transkription) kann ausschliesslich
            # CPU und CUDA. Fuer AMD gibt es unter Windows ausserdem gar
            # keine PyTorch-Pakete. Deshalb rechnet hier die CPU - das
            # funktioniert vollstaendig, nur langsamer.
            return (
                "keine nutzbare NVIDIA-GPU erkannt (CPU-Verarbeitung; "
                "GPU-Beschleunigung ist nur mit NVIDIA/CUDA moeglich)"
            )
        name = torch.cuda.get_device_name(0)
        if cuda_kann_wirklich_rechnen():
            return name
        # Karte da, aber der installierte PyTorch-Build passt nicht dazu.
        return (
            f"{name} - nicht benutzbar, der installierte PyTorch-Build passt "
            "nicht zu dieser Kartengeneration (CPU-Verarbeitung)"
        )
    except ImportError:
        return "PyTorch nicht installiert"


def load_pyannote_pipeline(device: str = "cuda"):
    """Laedt die pyannote-Diarisierungspipeline. Der HF_TOKEN wird nur zur
    direkten Weitergabe verwendet und niemals geloggt."""
    import torch  # type: ignore
    from pyannote.audio import Pipeline  # type: ignore

    token = get_hf_token_for_download()
    # pyannote.audio 4.x hat den Parameter von 'use_auth_token' in 'token'
    # umbenannt. Mit dem alten Namen bricht das Laden ab:
    # "Pipeline.from_pretrained() got an unexpected keyword argument
    # 'use_auth_token'". Am 19.09.2026 auf echter Hardware aufgefallen.
    pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL_NAME, token=token)
    pipeline.to(torch.device(device))
    return pipeline
