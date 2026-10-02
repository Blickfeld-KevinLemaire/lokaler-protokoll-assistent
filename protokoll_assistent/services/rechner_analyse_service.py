"""Analyse des Rechners, bevor irgendetwas heruntergeladen wird.

Die Einrichtung soll dem Anwender zuerst sagen, **welche Modelle auf diesem
Computer gut laufen und welche eher nicht** -- und erst danach laden. Dazu
werden Arbeitsspeicher, Prozessorkerne, Grafikkarte und freier Platz
ermittelt und jedes Modell der Auswahllisten bewertet:

* ``GUT``      -- laeuft flott.
* ``MAESSIG``  -- laeuft, aber merklich langsam oder knapp.
* ``NICHT``    -- auf diesem Rechner nicht sinnvoll.

Die Ermittlung braucht weder PyTorch noch ein Modell (sie laeuft auch im
reinen API-Betrieb): Die Grafikkarte wird ueber ``nvidia-smi`` gefragt, der
Arbeitsspeicher ueber ``psutil`` oder die Windows-Schnittstelle. Alle
Zugriffe auf den Rechner sind als Parameter austauschbar, damit die Tests
weder Hardware noch Programme brauchen (CLAUDE.md, Regel 4).

Die Bewertungen sind **Schaetzungen**. Fest steht nur, was am 19.09.2026
gemessen wurde (siehe ``model_service``: Turbo braucht 2,26 GB
Grafikspeicher bzw. 2,04 GB Arbeitsspeicher und laeuft auf der CPU in
3,8-facher Echtzeit). Der Rest folgt daraus bzw. aus den Groessenangaben der
Modelle und ist bewusst vorsichtig gewaehlt.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from protokoll_assistent.services import model_service, ollama_service

GUT = "gut"
MAESSIG = "maessig"
NICHT = "nicht"

BEREICH_TRANSKRIPTION = "Transkription"
BEREICH_NACHBEARBEITUNG = "Nachbearbeitung (Protokoll)"
BEREICH_SUCHE = "Frag mein Meeting (Suche)"

# Reserve fuer Betriebssystem, Sprechertrennung und andere Programme.
SPEICHER_RESERVE_GB = 3.0
# Arbeitsspeicher fuer den Kontext eines Sprachmodells (Ollama, 8192 Token).
KONTEXT_ZUSCHLAG_GB = 1.5

# Vielfaches der Echtzeit, in dem ein Whisper-Modell auf einem durchschnittlichen
# Rechner (>= 8 Kerne) ohne Grafikkarte transkribiert. 'large-v3-turbo' ist
# gemessen (3,8); 'large-v3' ist laut model_service etwa siebenmal langsamer,
# die kleineren Modelle entsprechend schneller. Alles andere ist geschaetzt.
CPU_ECHTZEIT_FAKTOR: dict[str, float] = {
    "large-v3": 0.5,
    "large-v3-turbo": 3.8,
    "distil-large-v3": 3.8,
    "medium": 1.2,
    "small": 6.0,
    "base": 14.0,
    "tiny": 25.0,
}
# Gut ab dieser Echtzeit-Vielfachen; darunter dauert die Transkription
# ungefaehr so lange wie die Aufnahme oder laenger.
ECHTZEIT_GUT = 2.0
ECHTZEIT_MAESSIG = 0.7

# Downloadgroessen der Bausteine, die immer gebraucht werden (gerundet).
GROESSE_WHISPER_TURBO_GB = 1.6
GROESSE_PYANNOTE_GB = 0.5
GROESSE_WERKZEUGE_GB = 1.9  # FFmpeg ca. 0,2 + Ollama ca. 1,7


@dataclass(frozen=True)
class RechnerProfil:
    ram_gb: float | None = None
    cpu_kerne: int | None = None
    gpu_name: str | None = None
    vram_gb: float | None = None
    freier_platz_gb: float | None = None

    @property
    def hat_gpu(self) -> bool:
        return self.vram_gb is not None and self.vram_gb > 0


@dataclass(frozen=True)
class Bewertung:
    bereich: str
    modell_id: str
    name: str
    stufe: str
    text: str


@dataclass
class Analyse:
    profil: RechnerProfil
    bewertungen: list[Bewertung] = field(default_factory=list)
    # Bereich -> empfohlene Modell-ID (None, wenn nichts davon sinnvoll laeuft).
    empfehlung: dict[str, str | None] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Hardware ermitteln
# --------------------------------------------------------------------------
class _SpeicherStatus(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 -- ctypes verlangt eine veraenderbare Liste
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _ram_gb() -> float | None:
    """Gesamter Arbeitsspeicher in GB oder ``None``, wenn nicht ermittelbar."""
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().total) / (1024**3)
    except ImportError:
        pass
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    try:
        status = _SpeicherStatus()
        status.dwLength = ctypes.sizeof(_SpeicherStatus)
        if not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return float(status.ullTotalPhys) / (1024**3)
    except (OSError, AttributeError):  # pragma: no cover - nur unter Windows erreichbar
        return None


def _gpu() -> tuple[str | None, float | None]:
    """Name und Grafikspeicher (GB) der ersten NVIDIA-Karte, sonst ``(None, None)``.

    Gefragt wird ``nvidia-smi``, das der NVIDIA-Treiber mitbringt -- so geht
    es ohne PyTorch. Nur NVIDIA zaehlt: CTranslate2 (faster-whisper) und
    PyTorch beschleunigen unter Windows ausschliesslich ueber CUDA; eine AMD-
    oder Intel-Grafik hilft hier nicht.
    """
    programm = shutil.which("nvidia-smi")
    if programm is None:
        return None, None
    try:
        ergebnis = subprocess.run(
            [programm, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if ergebnis.returncode != 0:
        return None, None
    return _gpu_aus_ausgabe(ergebnis.stdout)


def _gpu_aus_ausgabe(ausgabe: str) -> tuple[str | None, float | None]:
    """Liest die erste Zeile von ``nvidia-smi`` ("Name, MiB")."""
    zeilen = [z.strip() for z in ausgabe.splitlines() if z.strip()]
    if not zeilen:
        return None, None
    name, _, speicher = zeilen[0].rpartition(",")
    try:
        return name.strip() or None, float(speicher.strip()) / 1024
    except ValueError:
        return None, None


def _freier_platz_gb(ordner: Path) -> float | None:
    try:
        return shutil.disk_usage(str(ordner)).free / (1024**3)
    except OSError:
        return None


def ermittle_profil(
    ordner: Path,
    *,
    ram_fn: Callable[[], float | None] = _ram_gb,
    gpu_fn: Callable[[], tuple[str | None, float | None]] = _gpu,
    kerne_fn: Callable[[], int | None] = os.cpu_count,
    platz_fn: Callable[[Path], float | None] = _freier_platz_gb,
) -> RechnerProfil:
    gpu_name, vram_gb = gpu_fn()
    return RechnerProfil(
        ram_gb=ram_fn(),
        cpu_kerne=kerne_fn(),
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        freier_platz_gb=platz_fn(ordner),
    )


def beschreibe_profil(profil: RechnerProfil) -> str:
    teile = []
    teile.append(f"Arbeitsspeicher: {profil.ram_gb:.1f} GB" if profil.ram_gb else "Arbeitsspeicher: unbekannt")
    teile.append(f"Prozessorkerne: {profil.cpu_kerne}" if profil.cpu_kerne else "Prozessorkerne: unbekannt")
    if profil.hat_gpu:
        teile.append(f"Grafikkarte: {profil.gpu_name or 'NVIDIA'} mit {profil.vram_gb:.1f} GB")
    else:
        teile.append("Grafikkarte: keine NVIDIA-Karte erkannt (die CPU rechnet)")
    if profil.freier_platz_gb is not None:
        teile.append(f"Freier Platz: {profil.freier_platz_gb:.0f} GB")
    return "\n".join(teile)


# --------------------------------------------------------------------------
# Bewerten
# --------------------------------------------------------------------------
def _cpu_faktor(profil: RechnerProfil) -> float:
    """Wie viel langsamer als ein 8-Kern-Rechner der Prozessor rechnet."""
    kerne = profil.cpu_kerne or 4
    if kerne >= 8:
        return 1.0
    if kerne >= 4:
        return 0.6
    return 0.3


def _bewerte_whisper(profil: RechnerProfil, option: model_service.WhisperModelOption) -> Bewertung:
    name = option.label.split(" (")[0]

    def ergebnis(stufe: str, text: str) -> Bewertung:
        return Bewertung(BEREICH_TRANSKRIPTION, option.id, name, stufe, text)

    if profil.hat_gpu and profil.vram_gb is not None:
        if profil.vram_gb >= option.min_vram_gb + model_service.SPEICHER_ZUSCHLAG_GB:
            return ergebnis(GUT, "Läuft schnell auf der Grafikkarte.")
        if profil.vram_gb >= option.min_vram_gb:
            return ergebnis(MAESSIG, "Passt knapp in den Grafikspeicher; andere Programme schließen.")

    bedarf = max(option.min_vram_gb, 0.5)
    if profil.ram_gb is not None and profil.ram_gb < bedarf + SPEICHER_RESERVE_GB:
        return ergebnis(NICHT, f"Der Arbeitsspeicher ({profil.ram_gb:.1f} GB) reicht dafür nicht.")

    echtzeit = CPU_ECHTZEIT_FAKTOR.get(option.id, 1.0) * _cpu_faktor(profil)
    if echtzeit >= ECHTZEIT_GUT:
        return ergebnis(GUT, f"Läuft auf dem Prozessor etwa {echtzeit:.1f}-fach schneller als die Aufnahme (Schätzung).")
    if echtzeit >= ECHTZEIT_MAESSIG:
        return ergebnis(
            MAESSIG,
            "Läuft auf dem Prozessor, dauert aber etwa so lange wie die Aufnahme (Schätzung).",
        )
    return ergebnis(NICHT, "Auf dem Prozessor deutlich länger als die Aufnahme – ohne Grafikkarte nicht sinnvoll.")


def _bewerte_sprachmodell(profil: RechnerProfil, option: ollama_service.OllamaModellOption) -> Bewertung:
    name = option.label.split(" (")[0]

    def ergebnis(stufe: str, text: str) -> Bewertung:
        return Bewertung(BEREICH_NACHBEARBEITUNG, option.id, name, stufe, text)

    bedarf = option.groesse_gb + KONTEXT_ZUSCHLAG_GB
    if profil.hat_gpu and profil.vram_gb is not None and profil.vram_gb >= bedarf:
        return ergebnis(GUT, "Läuft flüssig auf der Grafikkarte.")

    if profil.ram_gb is not None and profil.ram_gb < bedarf + SPEICHER_RESERVE_GB:
        return ergebnis(NICHT, f"Zu groß für den Arbeitsspeicher ({profil.ram_gb:.1f} GB).")

    kerne = profil.cpu_kerne or 4
    if option.groesse_gb <= 3.5:
        if kerne >= 6:
            return ergebnis(GUT, "Klein genug, um auch auf dem Prozessor zügig zu laufen.")
        return ergebnis(MAESSIG, "Läuft auf dem Prozessor, bei wenigen Kernen aber spürbar langsam.")
    if option.groesse_gb <= 6.0:
        return ergebnis(MAESSIG, "Läuft auf dem Prozessor, die Auswertung dauert aber einige Minuten.")
    return ergebnis(NICHT, "Ohne passende Grafikkarte zu langsam.")


def _bewerte_einbettung(profil: RechnerProfil, option: ollama_service.OllamaModellOption) -> Bewertung:
    name = option.label.split(" (")[0]
    bedarf = option.groesse_gb + 1.0
    if profil.ram_gb is not None and profil.ram_gb < bedarf + SPEICHER_RESERVE_GB:
        return Bewertung(BEREICH_SUCHE, option.id, name, NICHT, f"Zu groß für den Arbeitsspeicher ({profil.ram_gb:.1f} GB).")
    return Bewertung(BEREICH_SUCHE, option.id, name, GUT, "Klein genug für jeden üblichen Rechner.")


def _waehle(bewertungen: list[Bewertung], bevorzugt: list[str]) -> str | None:
    """Erste bevorzugte ID mit Stufe GUT, sonst erste mit MAESSIG, sonst None."""
    stufen = {b.modell_id: b.stufe for b in bewertungen}
    for gewuenscht in (GUT, MAESSIG):
        for modell_id in bevorzugt:
            if stufen.get(modell_id) == gewuenscht:
                return modell_id
    return None


def analysiere(profil: RechnerProfil) -> Analyse:
    """Bewertet alle Modelle der Auswahllisten fuer dieses Profil."""
    whisper = [_bewerte_whisper(profil, o) for o in model_service.WHISPER_MODELLE]
    sprache = [_bewerte_sprachmodell(profil, o) for o in ollama_service.OLLAMA_MODELLE]
    suche = [_bewerte_einbettung(profil, o) for o in ollama_service.OLLAMA_EMBEDDING_MODELLE]

    empfehlung: dict[str, str | None] = {
        # Qualitaet vor Tempo: Turbo, solange es nicht ausfaellt, sonst das genuegsame 'small'.
        BEREICH_TRANSKRIPTION: _waehle(whisper, [model_service.WHISPER_MODEL_NAME, "small"]),
        BEREICH_NACHBEARBEITUNG: _waehle(sprache, [ollama_service.DEFAULT_MODEL, "qwen3:4b"]),
        BEREICH_SUCHE: _waehle(suche, ["bge-m3", "nomic-embed-text"]),
    }
    # 'GUT' vor 'MAESSIG' gilt je ID; fuer Transkription soll Turbo (auch maessig)
    # vor einem guten 'small' stehen, weil die Genauigkeit den Unterschied macht.
    turbo = next((b for b in whisper if b.modell_id == model_service.WHISPER_MODEL_NAME), None)
    if turbo is not None and turbo.stufe != NICHT:
        empfehlung[BEREICH_TRANSKRIPTION] = turbo.modell_id

    return Analyse(
        profil=profil,
        bewertungen=[*whisper, *sprache, *suche],
        empfehlung=empfehlung,
        hinweise=_hinweise(profil, empfehlung, whisper, sprache),
    )


def _hinweise(
    profil: RechnerProfil,
    empfehlung: dict[str, str | None],
    whisper: list[Bewertung],
    sprache: list[Bewertung],
) -> list[str]:
    hinweise: list[str] = []
    if not profil.hat_gpu:
        hinweise.append(
            "Keine NVIDIA-Grafikkarte erkannt: Alles läuft auf dem Prozessor. Das funktioniert, "
            "ist aber langsamer – besonders bei der Nachbearbeitung."
        )
    if profil.ram_gb is not None and profil.ram_gb < 8:
        hinweise.append(
            f"Mit {profil.ram_gb:.1f} GB Arbeitsspeicher ist der Rechner knapp ausgestattet. "
            "Andere Programme bitte schließen."
        )
    if empfehlung[BEREICH_NACHBEARBEITUNG] is None or all(b.stufe == NICHT for b in sprache):
        hinweise.append(
            "Für die Nachbearbeitung ist hier kein lokales Sprachmodell sinnvoll. "
            "Das Protokoll lässt sich stattdessen über eine API erstellen (Einstellungen)."
        )
    if empfehlung[BEREICH_TRANSKRIPTION] is None or all(b.stufe == NICHT for b in whisper):
        hinweise.append(
            "Für die Transkription ist hier kein lokales Modell sinnvoll. "
            "Sie lässt sich stattdessen über eine API ausführen (Einstellungen)."
        )
    if profil.freier_platz_gb is not None:
        benoetigt = GROESSE_WHISPER_TURBO_GB + GROESSE_PYANNOTE_GB + GROESSE_WERKZEUGE_GB
        modell = ollama_service.get_modell_option(empfehlung[BEREICH_NACHBEARBEITUNG] or "")
        if modell is not None:
            benoetigt += modell.groesse_gb
        if profil.freier_platz_gb < benoetigt + 2:
            hinweise.append(
                f"Freier Platz: {profil.freier_platz_gb:.0f} GB. Die Einrichtung lädt etwa "
                f"{benoetigt:.0f} GB herunter – bitte vorher Platz schaffen."
            )
    return hinweise
