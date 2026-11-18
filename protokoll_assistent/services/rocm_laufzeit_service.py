"""Rechenumgebung fuer AMD-Grafikkarten: Transkription ueber ROCm.

faster-whisper rechnet mit CTranslate2. Dessen Pakete auf PyPI koennen nur CPU
und NVIDIA (CUDA); fuer AMD gibt es eigene Windows-Raeder, die gegen ROCm 7.2
gebaut sind. Sie brauchen zur Laufzeit AMDs ROCm-Bibliotheken (hipBLAS,
rocBLAS), die AMD fuer Windows als pip-Pakete anbietet. Beides kommt also
zusaetzlich in die Umgebung, NACH den normalen Paketen:

1. AMDs ROCm-Pakete (``ROCM_PAKETE``) -- direkt von repo.radeon.com, je mit
   festem SHA-256, den pip prueft.
2. CTranslate2 mit ROCm. Das gibt es nur als Archiv auf der Release-Seite von
   CTranslate2 (``rocm-python-wheels-Windows.zip``, alle Python-Fassungen).
   ``raeder_bereitstellen`` laedt es, prueft den SHA-256 und legt die Raeder
   fuer die unterstuetzten Python-Fassungen in einen Ordner; pip waehlt daraus
   das passende und ersetzt damit das CTranslate2 von PyPI.

CTranslate2 findet die ROCm-Bibliotheken selbst (``_rocm_sdk_core/bin`` und
``_rocm_sdk_libraries*/bin`` neben sich). PyTorch bleibt der CPU-Build: Die
Sprechertrennung (pyannote) rechnet auf AMD-Karten auf dem Prozessor.

Gemessen am 18.11.2026 auf einer RX 9070 XT (Treiber mit ``amdhip64_7.dll``):
large-v3-turbo in 18-facher Echtzeit, Wort fuer Wort derselbe Text wie auf der
CPU (dort 3,4-fach). AMD verlangt fuer ROCm 7.2.1 mindestens den
Grafiktreiber 26.2.2; mit einem aelteren findet CTranslate2 keine Karte, und
die Transkription laeuft wie bisher auf dem Prozessor.

**Pflege:** Neue Fassungen von ROCm oder CTranslate2 hier eintragen (URL,
SHA-256, Version) und ``amd_grafikkarten.WHISPER_ROCM_ZIELE`` gegen die neuen
Bibliotheken pruefen. Eine geaenderte Angabe aendert die Einrichtungskennung --
bestehende AMD-Installationen richten sich beim naechsten Start neu ein.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from pathlib import Path

from protokoll_assistent.services import rechner_analyse_service
from protokoll_assistent.services.rechner_analyse_service import Grafikkarte

ROCM_VERSION = "7.2.1"
_ROCM_BASIS = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1"
# 'name @ url#sha256=...': pip prueft den Hash und bricht bei einer Abweichung ab.
ROCM_PAKETE = [
    f"rocm-sdk-core @ {_ROCM_BASIS}/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl"
    "#sha256=f68989d48df71cbfc3cb68bf705dc37c0f56e9666feddb59a1a0f5ff7539fe1c",
    f"rocm-sdk-libraries-custom @ {_ROCM_BASIS}/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl"
    "#sha256=c7fe0b0731af8896093ff69e11496830d3cb6a4aed73e895c60b7cbdc200be92",
    f"rocm @ {_ROCM_BASIS}/rocm-7.2.1.tar.gz#sha256=9084902eaa69213a00a90784ad89e6e5fe73c702df0cc6cc3a70d777c7a6142b",
]

CTRANSLATE2_VERSION = "4.9.0"
CTRANSLATE2_ARCHIV_URL = (
    "https://github.com/OpenNMT/CTranslate2/releases/download/v4.9.0/rocm-python-wheels-Windows.zip"
)
CTRANSLATE2_ARCHIV_SHA256 = "99cbc7210f035d04ed2f38aa653e79b2b1dcc90cb7503af72d880785b66b7f84"
_ARCHIV_NAME = "ctranslate2-rocm-windows.zip"


class RocmEinrichtungsFehler(RuntimeError):
    pass


def amd_karte_erkannt(
    karten_fn: Callable[[], list[Grafikkarte]] = rechner_analyse_service.grafikkarten_aus_registry,
) -> bool:
    """Steckt eine AMD-Karte im Rechner, auf der die Transkription ueber ROCm rechnen kann (Liste in
    ``amd_grafikkarten``, genug eigener Grafikspeicher)? Schnell genug fuer jeden Programmstart."""
    for name, vram in karten_fn():
        profil = rechner_analyse_service.RechnerProfil(gpu_name=name, vram_gb=vram)
        if profil.amd_rocm:
            return True
    return False


def kennungsbestandteile() -> list[str]:
    """Was in die Einrichtungskennung eingeht: aendert sich eine Angabe, richtet sich die Umgebung neu ein."""
    return [*ROCM_PAKETE, CTRANSLATE2_ARCHIV_URL, CTRANSLATE2_ARCHIV_SHA256]


def _sha256(datei: Path) -> str:
    pruefsumme = hashlib.sha256()
    with datei.open("rb") as quelle:
        for block in iter(lambda: quelle.read(1024 * 1024), b""):
            pruefsumme.update(block)
    return pruefsumme.hexdigest()


def _rad_namen(python_fassungen: tuple[tuple[int, int], ...]) -> list[str]:
    return [
        f"ctranslate2-{CTRANSLATE2_VERSION}-cp{haupt}{neben}-cp{haupt}{neben}-win_amd64.whl"
        for haupt, neben in python_fassungen
    ]


def raeder_bereitstellen(
    ordner: Path,
    python_fassungen: tuple[tuple[int, int], ...],
    *,
    lade_fn: Callable[[str, Path], None] | None = None,
) -> Path:
    """Laedt das CTranslate2-Archiv (falls noch nicht gueltig vorhanden), prueft es und legt die Raeder fuer
    ``python_fassungen`` in ``ordner``. Liefert den Ordner fuer ``pip --find-links``."""
    if lade_fn is None:
        from protokoll_assistent.utils import netz

        def lade_fn(url: str, ziel: Path) -> None:
            netz.lade_datei(url, ziel, timeout=900)

    ordner.mkdir(parents=True, exist_ok=True)
    archiv = ordner / _ARCHIV_NAME
    if not archiv.is_file() or _sha256(archiv) != CTRANSLATE2_ARCHIV_SHA256:
        teil = archiv.with_suffix(".part")
        teil.unlink(missing_ok=True)
        lade_fn(CTRANSLATE2_ARCHIV_URL, teil)
        if _sha256(teil) != CTRANSLATE2_ARCHIV_SHA256:
            teil.unlink(missing_ok=True)
            raise RocmEinrichtungsFehler(
                "Das Archiv mit CTranslate2 für AMD-Grafikkarten hat nicht die erwartete Prüfsumme und wurde verworfen."
            )
        teil.replace(archiv)

    gesucht = set(_rad_namen(python_fassungen))
    with zipfile.ZipFile(archiv) as zip_datei:
        for eintrag in zip_datei.infolist():
            name = Path(eintrag.filename).name  # Pfade im Archiv ('temp-windows/...') bewusst verwerfen
            if name in gesucht:
                (ordner / name).write_bytes(zip_datei.read(eintrag))
                gesucht.discard(name)
    if gesucht:
        raise RocmEinrichtungsFehler(f"Im CTranslate2-Archiv fehlen: {', '.join(sorted(gesucht))}")
    return ordner


def pip_befehle(python_exe: Path, raeder_ordner: Path) -> list[list[str]]:
    """Die beiden zusaetzlichen pip-Aufrufe -- nach den normalen Paketen, damit das CTranslate2 von PyPI
    ersetzt wird und nicht umgekehrt."""
    python_str = str(python_exe)
    return [
        [python_str, "-m", "pip", "install", *ROCM_PAKETE],
        [
            python_str,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(raeder_ordner),
            "--force-reinstall",
            "--no-deps",
            f"ctranslate2=={CTRANSLATE2_VERSION}",
        ],
    ]


def laufzeit_aktiv() -> bool:
    """Laeuft diese Umgebung mit AMDs ROCm-Paketen? Nur dann kann CTranslate2 eine AMD-Karte ansprechen."""
    import importlib.util

    return importlib.util.find_spec("rocm_sdk") is not None
