"""Analyse des Rechners, bevor irgendetwas heruntergeladen wird.

Die Einrichtung soll dem Anwender zuerst sagen, **welche Modelle auf diesem
Computer gut laufen und welche eher nicht** -- und erst danach laden. Dazu
werden Arbeitsspeicher, Prozessorkerne, Grafikkarte und freier Platz
ermittelt und jedes Modell der Auswahllisten bewertet:

* ``GUT``      -- laeuft flott.
* ``MAESSIG``  -- laeuft, aber merklich langsam oder knapp.
* ``NICHT``    -- auf diesem Rechner nicht sinnvoll.

Die Ermittlung braucht weder PyTorch noch ein Modell (sie laeuft auch im
reinen API-Betrieb): Die Grafikkarte(n) werden ueber Windows (PowerShell/WMI)
und bei NVIDIA zusaetzlich ueber ``nvidia-smi`` ermittelt -- gleich, von
welchem Hersteller sie ist --, der Arbeitsspeicher ueber ``psutil`` oder die
Windows-Schnittstelle. Alle
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
import json
import os
import re
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


HERSTELLER_NVIDIA = "nvidia"
HERSTELLER_AMD = "amd"
HERSTELLER_INTEL = "intel"
HERSTELLER_SONSTIGE = "sonstige"

# Adapter, die keine echte Grafikkarte sind (Fernwartung, virtuelle Maschinen ...).
_KEINE_GRAFIKKARTE = ("basic display", "basic render", "remote", "virtual", "parsec", "citrix", "displaylink")
_AMD_EINZELKARTE = re.compile(r"\brx\b|radeon pro|radeon vii|instinct|firepro", re.IGNORECASE)


def gpu_hersteller(name: str | None) -> str | None:
    """Hersteller nach dem Namen der Grafikkarte, ``None`` ohne Namen."""
    if not name:
        return None
    klein = name.lower()
    if any(wort in klein for wort in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla")):
        return HERSTELLER_NVIDIA
    if "amd" in klein or "radeon" in klein or "ati " in klein:
        return HERSTELLER_AMD
    if "intel" in klein:
        return HERSTELLER_INTEL
    return HERSTELLER_SONSTIGE


def gpu_ist_integriert(name: str | None) -> bool:
    """Teilt sich die Grafik den Arbeitsspeicher mit dem Prozessor? Das ist bei
    allen Intel-Karten ausser 'Arc' und bei AMD-Prozessorgrafik (Vega, 'Radeon
    Graphics', 780M ...) der Fall. Bei einem unbekannten Hersteller geht die
    Analyse vorsichtig davon aus, dass die Karte nichts beschleunigt."""
    hersteller = gpu_hersteller(name)
    if hersteller == HERSTELLER_NVIDIA:
        return False
    if hersteller == HERSTELLER_INTEL:
        return "arc" not in (name or "").lower()
    if hersteller == HERSTELLER_AMD:
        return _AMD_EINZELKARTE.search(name or "") is None
    return True


@dataclass(frozen=True)
class RechnerProfil:
    ram_gb: float | None = None
    cpu_kerne: int | None = None
    gpu_name: str | None = None
    vram_gb: float | None = None
    freier_platz_gb: float | None = None

    @property
    def hat_grafikkarte(self) -> bool:
        return self.gpu_name is not None

    @property
    def gpu_hersteller(self) -> str | None:
        return gpu_hersteller(self.gpu_name)

    @property
    def gpu_integriert(self) -> bool:
        return self.hat_grafikkarte and gpu_ist_integriert(self.gpu_name)

    @property
    def cuda_gpu(self) -> bool:
        """NVIDIA-Karte mit bekanntem Speicher: die einzige, auf der faster-whisper
        und PyTorch beschleunigen (beide rechnen ueber CUDA)."""
        return self.gpu_hersteller == HERSTELLER_NVIDIA and self.vram_gb is not None and self.vram_gb > 0

    @property
    def radeon_moeglich(self) -> bool:
        """Radeon-Einzelkarte: Ollama kann sie nutzen, aber nur bestimmte Modelle
        (ROCm). Ob genau diese dazugehoert, laesst sich hier nicht vorab sagen."""
        return (
            self.gpu_hersteller == HERSTELLER_AMD
            and not self.gpu_integriert
            and self.vram_gb is not None
            and self.vram_gb > 0
        )


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


Grafikkarte = tuple[str, float | None]  # (Name, Grafikspeicher in GB, falls bekannt)

_KEIN_FENSTER = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Fragt Windows nach allen Grafikadaptern. 'AdapterRAM' ist nur 32 Bit breit und
# meldet bei Karten ab 4 GB nichts Brauchbares; der echte Wert steht in der
# Registry ('HardwareInformation.qwMemorySize').
_POWERSHELL_SKRIPT = (
    "$cim = Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM;"
    "$reg = Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
    "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue | "
    "Select-Object DriverDesc,@{n='Mem';e={$_.'HardwareInformation.qwMemorySize'}};"
    "@{cim=@($cim);reg=@($reg)} | ConvertTo-Json -Depth 3 -Compress"
)


def _grafikkarten() -> list[Grafikkarte]:
    """Alle Grafikkarten dieses Rechners -- gleich von welchem Hersteller.

    NVIDIA-Karten werden bevorzugt ueber ``nvidia-smi`` gelesen (genauer
    Speicher), alle anderen und der Rest ueber Windows."""
    karten = _grafikkarten_nvidia_smi()
    for name, vram in _grafikkarten_windows():
        if karten and gpu_hersteller(name) == HERSTELLER_NVIDIA:
            continue  # schon genau ueber nvidia-smi erfasst
        karten.append((name, vram))
    return karten


def _grafikkarten_nvidia_smi() -> list[Grafikkarte]:
    programm = shutil.which("nvidia-smi")
    if programm is None:
        return []
    try:
        ergebnis = subprocess.run(
            [programm, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=_KEIN_FENSTER,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if ergebnis.returncode != 0:
        return []
    return _karten_aus_smi_ausgabe(ergebnis.stdout)


def _karten_aus_smi_ausgabe(ausgabe: str) -> list[Grafikkarte]:
    """Liest die Zeilen von ``nvidia-smi`` ("Name, MiB")."""
    karten: list[Grafikkarte] = []
    for zeile in ausgabe.splitlines():
        name, _, speicher = zeile.strip().rpartition(",")
        try:
            karten.append((name.strip() or "NVIDIA", float(speicher.strip()) / 1024))
        except ValueError:
            continue
    return karten


def _grafikkarten_windows() -> list[Grafikkarte]:
    powershell = shutil.which("powershell")
    if powershell is None:
        return []
    try:
        ergebnis = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_SKRIPT],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=_KEIN_FENSTER,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if ergebnis.returncode != 0:
        return []
    return _karten_aus_powershell_ausgabe(ergebnis.stdout)


def _als_liste(wert) -> list:
    """PowerShell macht aus einem einzelnen Element ein Objekt statt einer Liste."""
    if wert is None:
        return []
    return wert if isinstance(wert, list) else [wert]


def _speicher_gb(roh) -> float | None:
    """Speichergroesse aus einem Registrywert: Zahl oder (je nach Treiber) Bytefolge."""
    if isinstance(roh, list) and roh and all(isinstance(b, int) for b in roh):
        roh = int.from_bytes(bytes(b & 0xFF for b in roh), "little")
    if isinstance(roh, (int, float)) and roh > 0:
        return float(roh) / (1024**3)
    return None


def _karten_aus_powershell_ausgabe(text: str) -> list[Grafikkarte]:
    try:
        daten = json.loads(text)
    except ValueError:
        return []
    if not isinstance(daten, dict):
        return []
    registry = {
        str(e.get("DriverDesc")): _speicher_gb(e.get("Mem"))
        for e in _als_liste(daten.get("reg"))
        if isinstance(e, dict)
    }
    karten: list[Grafikkarte] = []
    for adapter in _als_liste(daten.get("cim")):
        if not isinstance(adapter, dict) or not adapter.get("Name"):
            continue
        name = str(adapter["Name"]).strip()
        if any(wort in name.lower() for wort in _KEINE_GRAFIKKARTE):
            continue
        vram = registry.get(name)
        if vram is None:
            vram = _speicher_gb(adapter.get("AdapterRAM"))
        karten.append((name, vram))
    return karten


def waehle_grafikkarte(karten: list[Grafikkarte]) -> Grafikkarte | None:
    """Die Karte, die am meisten bringt: NVIDIA vor anderen Einzelkarten vor
    integrierter Grafik, innerhalb davon die mit dem meisten Speicher."""

    def rang(karte: Grafikkarte) -> tuple[int, float]:
        name, vram = karte
        if gpu_hersteller(name) == HERSTELLER_NVIDIA:
            stufe = 2
        elif not gpu_ist_integriert(name):
            stufe = 1
        else:
            stufe = 0
        return stufe, vram or 0.0

    return max(karten, key=rang) if karten else None


def _freier_platz_gb(ordner: Path) -> float | None:
    try:
        return shutil.disk_usage(str(ordner)).free / (1024**3)
    except OSError:
        return None


def ermittle_profil(
    ordner: Path,
    *,
    ram_fn: Callable[[], float | None] = _ram_gb,
    gpu_fn: Callable[[], list[Grafikkarte]] = _grafikkarten,
    kerne_fn: Callable[[], int | None] = os.cpu_count,
    platz_fn: Callable[[Path], float | None] = _freier_platz_gb,
) -> RechnerProfil:
    beste = waehle_grafikkarte(gpu_fn())
    gpu_name, vram_gb = beste if beste is not None else (None, None)
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
    if profil.hat_grafikkarte:
        speicher = f" mit {profil.vram_gb:.1f} GB" if profil.vram_gb else ""
        if profil.cuda_gpu:
            zusatz = "beschleunigt Transkription und Nachbearbeitung"
        elif profil.gpu_integriert:
            zusatz = "in den Prozessor integriert, teilt sich den Arbeitsspeicher und beschleunigt hier nichts"
        elif profil.radeon_moeglich:
            zusatz = "für die Transkription nicht nutzbar (nur NVIDIA), für die Nachbearbeitung je nach Kartenmodell möglich"
        else:
            zusatz = "wird nicht genutzt (beschleunigt wird nur mit NVIDIA)"
        teile.append(f"Grafikkarte: {profil.gpu_name}{speicher} – {zusatz}")
    else:
        teile.append("Grafikkarte: keine erkannt (der Prozessor rechnet)")
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

    if profil.cuda_gpu and profil.vram_gb is not None:
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
    passt_in_den_grafikspeicher = profil.vram_gb is not None and profil.vram_gb >= bedarf
    if profil.cuda_gpu and passt_in_den_grafikspeicher:
        return ergebnis(GUT, "Läuft flüssig auf der Grafikkarte.")

    auf_dem_prozessor = _sprachmodell_auf_dem_prozessor(profil, option, ergebnis)
    if profil.radeon_moeglich and passt_in_den_grafikspeicher and auf_dem_prozessor.stufe != GUT:
        # Ollama nutzt Radeon-Karten nur, wenn das Kartenmodell unterstuetzt wird
        # (ROCm) -- das laesst sich vorab nicht sagen, deshalb hoechstens "maessig".
        return ergebnis(
            MAESSIG,
            "Die Radeon-Karte kann Ollama beschleunigen, sofern sie unterstützt wird – "
            "sonst läuft es auf dem Prozessor.",
        )
    return auf_dem_prozessor


def _sprachmodell_auf_dem_prozessor(
    profil: RechnerProfil,
    option: ollama_service.OllamaModellOption,
    ergebnis: Callable[[str, str], Bewertung],
) -> Bewertung:
    bedarf = option.groesse_gb + KONTEXT_ZUSCHLAG_GB
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
        BEREICH_NACHBEARBEITUNG: _waehle(sprache, [ollama_service.DEFAULT_MODEL]),
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
    if not profil.cuda_gpu:
        hinweise.append(_grafikhinweis(profil))
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


def _grafikhinweis(profil: RechnerProfil) -> str:
    langsamer = "Das funktioniert, ist aber langsamer – besonders bei der Nachbearbeitung."
    if not profil.hat_grafikkarte:
        return f"Keine Grafikkarte erkannt: Alles läuft auf dem Prozessor. {langsamer}"
    if profil.gpu_integriert:
        return (
            f"Die Grafik ({profil.gpu_name}) ist in den Prozessor integriert und teilt sich den "
            f"Arbeitsspeicher. Sie beschleunigt hier nichts: Alles läuft auf dem Prozessor. {langsamer}"
        )
    if profil.radeon_moeglich:
        return (
            f"Erkannt: {profil.gpu_name}. Die Transkription nutzt nur NVIDIA-Karten (CUDA) und läuft "
            "deshalb auf dem Prozessor. Ollama kann viele Radeon-Karten für die Nachbearbeitung nutzen – "
            "ob genau diese unterstützt wird, zeigt sich erst beim Ausprobieren."
        )
    return (
        f"Erkannt: {profil.gpu_name}. Beschleunigt wird nur mit NVIDIA-Karten (CUDA); "
        f"hier läuft alles auf dem Prozessor. {langsamer}"
    )
