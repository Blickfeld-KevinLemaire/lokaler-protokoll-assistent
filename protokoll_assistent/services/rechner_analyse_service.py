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

from protokoll_assistent.services import grafikkarten_liste, model_service, ollama_service

GUT = "gut"
MAESSIG = "maessig"
NICHT = "nicht"

BEREICH_TRANSKRIPTION = "Transkription"
BEREICH_NACHBEARBEITUNG = "Nachbearbeitung (Protokoll)"
BEREICH_SUCHE = "Frag mein Meeting (Suche)"

# Reserve fuer Betriebssystem, Sprechertrennung und andere Programme.
SPEICHER_RESERVE_GB = 3.0
# Eine AMD-Karte aus der Liste zaehlt erst ab so viel Grafikspeicher als Beschleuniger: Darunter passt weder
# Whisper (gemessen 2,3 GB) noch das kleinste Sprachmodell. Betrifft vor allem Ryzen-AI-Prozessorgrafik, der im
# BIOS/UEFI oft nur 0,5-2 GB fest zugewiesen sind.
MIN_GRAFIKSPEICHER_GB = 3.0
# Ab hier empfiehlt die Einrichtung das groessere Sprachmodell (Qwen 9B statt 4B): Modell samt 32K-Kontext UND
# Whisper (falls es auf derselben Karte rechnet) passen gleichzeitig hinein -- auf 16 GB bequem, auf 12 GB nicht.
GROSSES_SPRACHMODELL = "qwen3.5:9b-q4_K_M"
# Arbeitsspeicher fuer den Kontext eines Sprachmodells (Ollama, 8192 Token).
KONTEXT_ZUSCHLAG_GB = 1.5
# Ein kleines Sprachmodell laeuft auf dem Prozessor nur dann flott ("gut"), wenn
# genug Arbeitsspeicher frei bleibt. Auf einem 8-GB-Rechner belegen Windows und
# die ueblichen Programme schon 5-6 GB; ein 4B-Modell (gemessen ~5 GB) wird dort
# eng und langsam. Erst ab diesem Wert ist bequem Platz -- darunter nur "maessig".
NACHBEARBEITUNG_GUT_RAM_GB = 16.0

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
GROESSE_WERKZEUGE_GB = 3.1  # FFmpeg ca. 0,2 + Ollama installiert 2,9 (gemessen 04.10.2026: 2,8)


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
    allen Intel-Karten ausser den Arc-Einzelkarten (A580, B580 ...; "Arc
    Graphics" und "Arc 140V" sind Prozessorgrafik) und bei AMD-Prozessorgrafik
    (Vega, 'Radeon Graphics', 780M ...) der Fall. Bei einem unbekannten
    Hersteller geht die Analyse vorsichtig davon aus, dass die Karte nichts
    beschleunigt."""
    hersteller = gpu_hersteller(name)
    if hersteller == HERSTELLER_NVIDIA:
        return False
    if hersteller == HERSTELLER_INTEL:
        return not grafikkarten_liste.ist_intel_arc_einzelkarte(name)
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
    def intel_arc_prozessorgrafik(self) -> bool:
        """Intel-Arc-Prozessorgrafik: Windows meldet dafuer nur ~128 MB eigenen Speicher, sie rechnet aber im
        geteilten Arbeitsspeicher (bis zur Haelfte davon)."""
        return (
            self.gpu_hersteller == HERSTELLER_INTEL
            and self.gpu_integriert
            and grafikkarten_liste.ist_nutzbare_prozessorgrafik(self.gpu_name)
        )

    @property
    def grafikspeicher_gb(self) -> float | None:
        """Speicher, mit dem die Karte rechnen kann: der eigene -- bei AMD-Prozessorgrafik der im BIOS fest
        zugewiesene --, bei Intel-Arc-Prozessorgrafik die Haelfte des Arbeitsspeichers (so viel teilt Windows zu)."""
        if self.intel_arc_prozessorgrafik:
            return self.ram_gb / 2 if self.ram_gb else None
        return self.vram_gb

    @property
    def _speicher_reicht(self) -> bool:
        return self.grafikspeicher_gb is not None and self.grafikspeicher_gb >= MIN_GRAFIKSPEICHER_GB

    @property
    def amd_gfx(self) -> str | None:
        """LLVM-Ziel der AMD-Karte, sofern sie in ``grafikkarten_liste`` (ROCm) steht."""
        return grafikkarten_liste.gfx_ziel(self.gpu_name) if self.gpu_hersteller == HERSTELLER_AMD else None

    @property
    def _ollama_rocm(self) -> bool:
        return self.amd_gfx in grafikkarten_liste.OLLAMA_ROCM_ZIELE

    @property
    def prozessorgrafik_nutzbar(self) -> bool:
        """Moderne Prozessorgrafik, die Ollama beschleunigt -- unabhaengig davon, ob ihr Speicher schon reicht."""
        return self.gpu_integriert and (self._ollama_rocm or grafikkarten_liste.ist_nutzbare_prozessorgrafik(self.gpu_name))

    @property
    def _vulkan_karte(self) -> bool:
        """Karte, die Ollama ueber sein Vulkan-Backend nutzt: jede AMD-Einzelkarte ausserhalb der ROCm-Liste, Intel
        Arc und moderne Prozessorgrafik (gemessen nur auf AMD, siehe ``grafikkarten_liste``)."""
        if self.cuda_gpu or self._ollama_rocm or not self.hat_grafikkarte:
            return False
        if self.gpu_integriert:
            return self.prozessorgrafik_nutzbar
        return self.gpu_hersteller in (HERSTELLER_AMD, HERSTELLER_INTEL)

    @property
    def ollama_gpu(self) -> bool:
        """Rechnet Ollama (Protokoll, "Frag mein Meeting") auf dieser Karte? NVIDIA ueber CUDA, AMD ueber ROCm oder
        Vulkan, Intel Arc ueber Vulkan -- jeweils mit genug Speicher."""
        return self.cuda_gpu or ((self._ollama_rocm or self._vulkan_karte) and self._speicher_reicht)

    @property
    def ollama_ueber_vulkan(self) -> bool:
        return self.ollama_gpu and self._vulkan_karte

    @property
    def whisper_gpu(self) -> bool:
        """Rechnet die Transkription auf dieser Karte? NVIDIA ueber CUDA, AMD laut Liste ueber ROCm. (CTranslate2
        hat kein Vulkan- und kein Intel-Backend.)"""
        return self.cuda_gpu or (self.amd_gfx in grafikkarten_liste.WHISPER_ROCM_ZIELE and self._speicher_reicht)

    @property
    def amd_rocm(self) -> bool:
        """AMD-Karte, fuer die die Rechenumgebung CTranslate2 mit ROCm bekommt (Transkription auf der Karte)."""
        return not self.cuda_gpu and self.whisper_gpu

    @property
    def braucht_igpu_freigabe(self) -> bool:
        """Ollama verwirft Prozessorgrafik, solange OLLAMA_IGPU_ENABLE nicht gesetzt ist."""
        return self.gpu_integriert and self.ollama_gpu


@dataclass(frozen=True)
class Bewertung:
    bereich: str
    modell_id: str
    name: str
    stufe: str
    text: str
    # Rechnet das Modell bei dieser Einschaetzung auf der Grafikkarte (sonst: Prozessor)?
    auf_grafikkarte: bool = False


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
    elif isinstance(roh, (bytes, bytearray)) and roh:  # REG_BINARY direkt aus 'winreg'
        roh = int.from_bytes(roh, "little")
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


_ANZEIGEADAPTER_SCHLUESSEL = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def grafikkarten_aus_registry(winreg_modul=None) -> list[Grafikkarte]:
    """Wie ``_grafikkarten_windows``, aber direkt aus der Registry: ohne PowerShell und damit schnell genug fuer
    jeden Programmstart (``bootstrap`` entscheidet damit, ob die Rechenumgebung ROCm bekommt)."""
    if winreg_modul is None:
        try:
            import winreg as winreg_modul  # type: ignore[no-redef]
        except ImportError:
            return []
    karten: list[Grafikkarte] = []
    try:
        klasse = winreg_modul.OpenKey(winreg_modul.HKEY_LOCAL_MACHINE, _ANZEIGEADAPTER_SCHLUESSEL)
    except OSError:
        return karten
    with klasse:
        for nummer in range(64):
            try:
                unterschluessel = winreg_modul.EnumKey(klasse, nummer)
            except OSError:
                break
            if not unterschluessel.isdigit():
                continue  # 'Properties' und Aehnliches
            try:
                with winreg_modul.OpenKey(klasse, unterschluessel) as adapter:
                    name = str(winreg_modul.QueryValueEx(adapter, "DriverDesc")[0]).strip()
                    try:
                        speicher = _speicher_gb(winreg_modul.QueryValueEx(adapter, "HardwareInformation.qwMemorySize")[0])
                    except OSError:
                        speicher = None
            except OSError:
                continue
            if name and not any(wort in name.lower() for wort in _KEINE_GRAFIKKARTE):
                karten.append((name, speicher))
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
        if profil.intel_arc_prozessorgrafik and profil.grafikspeicher_gb:
            speicher = f" mit bis zu {profil.grafikspeicher_gb:.1f} GB geteiltem Speicher"
        else:
            speicher = f" mit {profil.vram_gb:.1f} GB" if profil.vram_gb else ""
        teile.append(f"Grafikkarte: {profil.gpu_name}{speicher} – {_grafikkarte_zusatz(profil)}")
    else:
        teile.append("Grafikkarte: keine erkannt (der Prozessor rechnet)")
    if profil.freier_platz_gb is not None:
        teile.append(f"Freier Platz: {profil.freier_platz_gb:.0f} GB")
    return "\n".join(teile)


def _grafikkarte_zusatz(profil: RechnerProfil) -> str:
    """Was die Karte beschleunigt -- je Arbeitsschritt, damit niemand raten muss, was wo laeuft."""
    if profil.cuda_gpu:
        return "beschleunigt Transkription, Sprechererkennung, Protokoll und „Frag mein Meeting“"
    if profil.whisper_gpu and profil.ollama_gpu:
        return (
            "beschleunigt Transkription, Protokoll und „Frag mein Meeting“; "
            "die Sprechererkennung läuft auf dem Prozessor"
        )
    if profil.ollama_gpu:
        weg = " (Ollama über Vulkan)" if profil.ollama_ueber_vulkan else " (Ollama)"
        integriert = "in den Prozessor integriert, " if profil.gpu_integriert else ""
        return (
            f"{integriert}beschleunigt Protokoll und „Frag mein Meeting“{weg}; "
            "Transkription und Sprechererkennung laufen auf dem Prozessor"
        )
    if profil.prozessorgrafik_nutzbar:
        return "in den Prozessor integriert – zu wenig fest zugewiesener Grafikspeicher, alles läuft auf dem Prozessor"
    if profil.gpu_integriert:
        return "in den Prozessor integriert, teilt sich den Arbeitsspeicher und beschleunigt hier nichts"
    return "wird nicht genutzt (beschleunigt werden NVIDIA-, AMD- und Intel-Arc-Karten mit mindestens 3 GB)"


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

    def ergebnis(stufe: str, text: str, auf_grafikkarte: bool = False) -> Bewertung:
        return Bewertung(BEREICH_TRANSKRIPTION, option.id, name, stufe, text, auf_grafikkarte)

    speicher = profil.grafikspeicher_gb
    if profil.whisper_gpu and speicher is not None:
        if speicher >= option.min_vram_gb + model_service.SPEICHER_ZUSCHLAG_GB:
            return ergebnis(GUT, "Läuft schnell auf der Grafikkarte.", True)
        if speicher >= option.min_vram_gb:
            return ergebnis(MAESSIG, "Passt knapp in den Grafikspeicher; andere Programme schließen.", True)

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
    passt_in_den_grafikspeicher = profil.grafikspeicher_gb is not None and profil.grafikspeicher_gb >= bedarf
    if profil.ollama_gpu and passt_in_den_grafikspeicher:
        text = "Läuft flüssig auf der Grafikkarte" + (" (über Vulkan)." if profil.ollama_ueber_vulkan else ".")
        return Bewertung(BEREICH_NACHBEARBEITUNG, option.id, name, GUT, text, True)
    return _sprachmodell_auf_dem_prozessor(profil, option, ergebnis)


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
        genug_ram = profil.ram_gb is None or profil.ram_gb >= NACHBEARBEITUNG_GUT_RAM_GB
        if kerne >= 6 and genug_ram:
            return ergebnis(GUT, "Klein genug, um auch auf dem Prozessor zügig zu laufen.")
        if kerne < 6:
            return ergebnis(MAESSIG, "Läuft auf dem Prozessor, bei wenigen Kernen aber spürbar langsam.")
        return ergebnis(
            MAESSIG,
            "Läuft auf dem Prozessor, aber der Arbeitsspeicher ist knapp – am besten andere "
            "Programme schließen; ein Online-Dienst ist hier meist die bessere Wahl.",
        )
    if option.groesse_gb <= 6.0:
        return ergebnis(MAESSIG, "Läuft auf dem Prozessor, die Auswertung dauert aber einige Minuten.")
    return ergebnis(NICHT, "Ohne passende Grafikkarte zu langsam.")


def _bewerte_einbettung(profil: RechnerProfil, option: ollama_service.OllamaModellOption) -> Bewertung:
    name = option.label.split(" (")[0]
    bedarf = option.groesse_gb + 1.0
    if profil.ram_gb is not None and profil.ram_gb < bedarf + SPEICHER_RESERVE_GB:
        return Bewertung(BEREICH_SUCHE, option.id, name, NICHT, f"Zu groß für den Arbeitsspeicher ({profil.ram_gb:.1f} GB).")
    return Bewertung(
        BEREICH_SUCHE, option.id, name, GUT, "Klein genug für jeden üblichen Rechner.", profil.ollama_gpu
    )


def grafikspeicher_fuer_grosses_modell(profil: RechnerProfil) -> float:
    """So viel Grafikspeicher (GB) braucht es, damit das grosse Sprachmodell samt 32K-Kontext neben Whisper
    passt -- dann muss Ollama fuer eine Transkription nichts entladen."""
    option = ollama_service.get_modell_option(GROSSES_SPRACHMODELL)
    bedarf = (option.groesse_gb if option else 6.6) + ollama_service.PROTOKOLL_KONTEXT_ZUSCHLAG_BYTES / 1024**3
    if profil.whisper_gpu:
        bedarf += model_service.WHISPER_GRAFIKSPEICHER_BYTES / 1024**3
    return bedarf


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

    # Qwen 4B ist die beste Wahl, LFM2.5 der leichtere Ersatz. Auf einem knappen
    # Rechner (wenig Arbeitsspeicher, keine Grafikkarte -- beide laufen dort nur
    # "maessig") ist das kleinere LFM2.5 die realistische lokale Wahl und steht
    # deshalb vorn; '_waehle' entscheidet bei gleicher Stufe nach dieser Reihenfolge.
    lfm = "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"
    knapper_ram = profil.ram_gb is not None and profil.ram_gb < NACHBEARBEITUNG_GUT_RAM_GB
    nachbearbeitung_bevorzugt = (
        [lfm, ollama_service.DEFAULT_MODEL] if knapper_ram else [ollama_service.DEFAULT_MODEL, lfm]
    )
    # Qwen 4B ist Standard, weil es auf 6-GB-Karten passt (dort gemessen). Auf einer Karte, die das 9B-Modell
    # samt Kontext UND Whisper gleichzeitig fasst (ab ~12 GB, z. B. 16 GB), gibt es keinen Grund, darauf zu
    # verzichten: genauer bei langen Besprechungen, und auf der Grafikkarte trotzdem schnell.
    speicher = profil.grafikspeicher_gb
    if profil.ollama_gpu and speicher is not None and speicher >= grafikspeicher_fuer_grosses_modell(profil):
        nachbearbeitung_bevorzugt = [GROSSES_SPRACHMODELL, *nachbearbeitung_bevorzugt]
    empfehlung: dict[str, str | None] = {
        # Qualitaet vor Tempo: Turbo, solange es nicht ausfaellt, sonst das genuegsame 'small'.
        BEREICH_TRANSKRIPTION: _waehle(whisper, [model_service.WHISPER_MODEL_NAME, "small"]),
        BEREICH_NACHBEARBEITUNG: _waehle(sprache, nachbearbeitung_bevorzugt),
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
    grafik = _grafikhinweis(profil)
    if grafik is not None:
        hinweise.append(grafik)
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


def _grafikhinweis(profil: RechnerProfil) -> str | None:
    """Was auf diesem Rechner NICHT auf der Grafikkarte laeuft und warum -- ``None``, wenn es nichts zu sagen gibt
    (alles, was sich beschleunigen laesst, wird beschleunigt; die Schritte zeigen ohnehin, was wo laeuft)."""
    langsamer = "Das funktioniert, ist aber langsamer – besonders bei der Nachbearbeitung."
    if profil.whisper_gpu and profil.ollama_gpu:
        return None
    if not profil.hat_grafikkarte:
        return f"Keine Grafikkarte erkannt: Alles läuft auf dem Prozessor. {langsamer}"
    if profil.ollama_gpu:
        weg = "Ollama über Vulkan" if profil.ollama_ueber_vulkan else "Ollama"
        return (
            f"Erkannt: {profil.gpu_name}. Protokoll und „Frag mein Meeting“ laufen auf der Grafikkarte ({weg}). "
            "Die Transkription läuft auf dem Prozessor: Für diese Karte gibt es unter Windows keine "
            "Beschleunigung dafür."
        )
    if profil.prozessorgrafik_nutzbar and profil.gpu_hersteller == HERSTELLER_AMD:
        speicher = f"{profil.vram_gb:.1f} GB" if profil.vram_gb else "kaum"
        return (
            f"Die Prozessorgrafik ({profil.gpu_name}) kann das Protokoll beschleunigen, hat aber nur "
            f"{speicher} fest zugewiesenen Grafikspeicher. Wer im BIOS/UEFI mehr zuweist (mindestens "
            f"{MIN_GRAFIKSPEICHER_GB + 3:.0f} GB, oft „UMA Frame Buffer Size“ oder „iGPU Memory“), kann sie "
            f"nutzen – die Einrichtung danach erneut starten. Bis dahin läuft alles auf dem Prozessor. {langsamer}"
        )
    if profil.gpu_integriert:
        return (
            f"Die Grafik ({profil.gpu_name}) ist in den Prozessor integriert und teilt sich den "
            f"Arbeitsspeicher. Sie beschleunigt hier nichts: Alles läuft auf dem Prozessor. {langsamer}"
        )
    return (
        f"Erkannt: {profil.gpu_name}. Beschleunigt werden NVIDIA-, AMD- und Intel-Arc-Karten mit mindestens "
        f"{MIN_GRAFIKSPEICHER_GB:.0f} GB Grafikspeicher; hier läuft alles auf dem Prozessor. {langsamer}"
    )
