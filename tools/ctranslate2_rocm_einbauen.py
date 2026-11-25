"""Baut CTranslate2 mit ROCm in das AMD-Image ein (nur ``Dockerfile`` mit ``GRAFIKKARTE=amd``).

    python3 ctranslate2_rocm_einbauen.py URL SHA256

Die CTranslate2-Pakete auf PyPI koennen nur CPU und NVIDIA. Fuer AMD gibt es eigene Raeder als Archiv auf der
Release-Seite von CTranslate2 (``rocm-python-wheels-Linux.zip``). Dieses Skript

1. laedt das Archiv und prueft seinen SHA-256 (bei einer Abweichung bricht der Bau ab),
2. ersetzt das CTranslate2 von PyPI durch das Rad fuer die laufende Python-Fassung,
3. traegt den Bibliotheksordner von PyTorch als Suchpfad NUR in die Bibliothek von CTranslate2 ein
   (``patchelf --add-rpath``).

Zu 3.: CTranslate2 braucht zur Laufzeit ``libamdhip64.so.7``, ``libhipblas.so.3`` und ``libhiprand.so.1``.
PyTorch aus dem ROCm-Index bringt genau diese Bibliotheken (samt rocBLAS und seinen Rechenkernen) in
``torch/lib`` mit -- eine zweite ROCm-Installation von mehreren GB im Image ist dafuer nicht noetig. Wer die
ROCm-Fassung von PyTorch aendert, prueft, dass sie zur Hauptversion passt, gegen die CTranslate2 gebaut ist
(``readelf -d`` auf ``libctranslate2*.so``).

Bewusst NICHT ueber ``ldconfig`` fuer den ganzen Ordner: ``torch/lib`` bringt auch allgemeine Bibliotheken mit
(``libtinfo.so.6`` u. a.). Systemweit eingetragen verdraengten sie die des Systems, und ``ffmpeg`` brach mit
"undefined symbol: _nc_tiparm" ab -- jede Verarbeitung scheiterte schon beim Vorbereiten der Aufnahme
(gemessen am 25.11.2026).

Laeuft im Bau des Images als root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def sha256(datei: Path) -> str:
    pruefsumme = hashlib.sha256()
    with datei.open("rb") as quelle:
        for block in iter(lambda: quelle.read(1024 * 1024), b""):
            pruefsumme.update(block)
    return pruefsumme.hexdigest()


def rad_auswaehlen(namen: list[str], fassung: tuple[int, int]) -> str:
    """Das Rad fuer diese Python-Fassung (ohne die Fassungen ohne GIL, ``cp314t``)."""
    kennung = f"cp{fassung[0]}{fassung[1]}"
    passend = [n for n in namen if Path(n).name.endswith(".whl") and f"-{kennung}-{kennung}-" in Path(n).name]
    if len(passend) != 1:
        raise SystemExit(f"Im Archiv gibt es kein eindeutiges Rad fuer {kennung}: {passend or 'keines'}")
    return passend[0]


def main(argumente: list[str]) -> int:
    if len(argumente) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    url, erwartet = argumente[0], argumente[1].strip().lower()
    with tempfile.TemporaryDirectory() as ordner_text:
        ordner = Path(ordner_text)
        archiv = ordner / "ctranslate2-rocm.zip"
        print(f"Lade {url}", flush=True)
        urllib.request.urlretrieve(url, archiv)  # noqa: S310 -- feste Adresse aus dem Dockerfile, Hash folgt
        tatsaechlich = sha256(archiv)
        if tatsaechlich != erwartet:
            raise SystemExit(f"Pruefsumme falsch: erwartet {erwartet}, erhalten {tatsaechlich}")
        with zipfile.ZipFile(archiv) as zip_datei:
            eintrag = rad_auswaehlen(zip_datei.namelist(), sys.version_info[:2])
            rad = ordner / Path(eintrag).name
            rad.write_bytes(zip_datei.read(eintrag))
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(rad)], check=True
        )

    import torch  # noqa: PLC0415 -- erst hier: Nur im AMD-Image steht der ROCm-Bau von PyTorch bereit

    if not getattr(torch.version, "hip", None):
        raise SystemExit("PyTorch ist nicht der ROCm-Bau (TORCH_INDEX_URL pruefen).")
    bibliotheken = Path(torch.__file__).parent / "lib"
    # Nur finden, nicht importieren: Ohne den Suchpfad laedt die Bibliothek ja gerade noch nicht.
    fundort = importlib.util.find_spec("ctranslate2")
    if fundort is None or fundort.origin is None:
        raise SystemExit("ctranslate2 ist nicht installiert.")
    paketordner = Path(fundort.origin).parent.parent
    ct2_bibliotheken = sorted((paketordner / "ctranslate2.libs").glob("libctranslate2*.so*"))
    if len(ct2_bibliotheken) != 1:
        raise SystemExit(f"Keine eindeutige libctranslate2 gefunden: {ct2_bibliotheken}")
    # PyTorch legt die Bibliotheken ohne Versionsendung ab ('libhiprand.so'); CTranslate2 verlangt sie unter ihrem
    # SONAME ('libhiprand.so.1'). 'ldconfig -n' legt nur diese Verweise in genau diesem Ordner an und laesst den
    # Zwischenspeicher des Linkers (und damit das uebrige System) in Ruhe.
    subprocess.run(["ldconfig", "-n", str(bibliotheken)], check=True)
    pip = [sys.executable, "-m", "pip"]
    subprocess.run([*pip, "install", "--no-cache-dir", "patchelf"], check=True)
    subprocess.run(["patchelf", "--add-rpath", str(bibliotheken), str(ct2_bibliotheken[0])], check=True)
    subprocess.run([*pip, "uninstall", "-y", "patchelf"], check=True)
    # Laedt die Bibliothek jetzt (ohne Karte; die gibt es beim Bau nicht).
    subprocess.run([sys.executable, "-c", "import ctranslate2"], check=True)
    print(f"CTranslate2 mit ROCm eingebaut; Bibliotheken aus {bibliotheken} (ROCm {torch.version.hip}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
