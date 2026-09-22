"""Prueft, ob die Laufzeit-Pakete der lokalen Anwendung zusammenpassen.

Warum es dieses Skript gibt
---------------------------
Die lokale Anwendung installiert sich beim ersten Start selbst -- mit ZWEI
getrennten pip-Aufrufen aus ZWEI verschiedenen Quellen:

1. PyTorch von einem eigenen Index von pytorch.org (je nach GPU cu... oder
   cpu), siehe 'requirements-torch.txt'.
2. Alles Weitere von PyPI, siehe 'requirements-laufzeit.txt'.

Genau dazwischen liegt die Falle: Der zweite Aufruf kann PyTorch wieder
ueberschreiben. Verlangt z. B. WhisperX 'torch~=2.8.0', der eingestellte
CUDA-Index kennt aber nur 2.5.1, dann installiert pip beim zweiten Aufruf
kommentarlos ein PyTorch von PyPI -- und der sorgfaeltig gewaehlte
CUDA-Build ist weg. Auf dem Rechner des Anwenders faellt das erst auf,
wenn die GPU unerwartet nicht benutzt wird.

Ein einzelner Aufloesungslauf findet das nicht, weil das Problem ZWISCHEN
den beiden Aufrufen liegt. Deshalb prueft dieses Skript beides:

* Laesst sich 'requirements-laufzeit.txt' ueberhaupt aufloesen? (Passen die
  Pakete also untereinander?)
* Gibt es die dabei geforderte PyTorch-Fassung in JEDEM eingestellten
  pytorch.org-Index? (Passt also der zweite Aufruf zum ersten - und zwar
  fuer alte wie neue Karten?)

Aufgeloest wird fuer Windows und Python 3.11 -- unabhaengig davon, auf
welchem System das Skript laeuft. Es wird nichts installiert, nur
Metadaten werden gelesen; der Lauf dauert wenige Sekunden.

Aufruf (im Projektstamm):
    uv run python -m protokoll_assistent.tools.laufzeit_pakete_pruefen

Rueckgabewert 0 = alles passt, 1 = passt nicht (mit Begruendung).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from packaging.requirements import Requirement

from protokoll_assistent.services import environment_service as env

# Fuer diese Fassung wird aufgeloest: die Fassung, die der Installer
# mitliefert. 3.10 wird ebenfalls unterstuetzt, loest aber nicht
# grundsaetzlich anders auf.
PYTHON_VERSION = "3.11"
PYTHON_PLATFORM = "x86_64-pc-windows-msvc"


def loese_laufzeitpakete_auf(ziel: Path) -> str:
    """Loest 'requirements-laufzeit.txt' gegen PyPI auf.

    Schlaegt fehl, wenn die Pakete untereinander nicht zusammenpassen.
    Gibt die aufgeloeste, vollstaendig festgelegte Liste zurueck.
    """
    befehl = [
        "uv",
        "pip",
        "compile",
        str(env.RUNTIME_REQUIREMENTS_FILE),
        "--python-version",
        PYTHON_VERSION,
        "--python-platform",
        PYTHON_PLATFORM,
        "--quiet",
        "--output-file",
        str(ziel),
    ]
    ergebnis = subprocess.run(befehl, capture_output=True, text=True, check=False)
    if ergebnis.returncode != 0:
        raise RuntimeError(
            "Die Laufzeit-Pakete passen nicht zusammen - 'uv pip compile' "
            f"ist fehlgeschlagen:\n\n{ergebnis.stderr.strip()}"
        )
    return ziel.read_text(encoding="utf-8")


def gefragte_version(aufgeloest: str, paket: str) -> str | None:
    """Liest die aufgeloeste Fassung eines Pakets aus der erzeugten Liste."""
    treffer = re.search(rf"^{re.escape(paket)}==([^\s;]+)", aufgeloest, re.MULTILINE)
    return treffer.group(1) if treffer else None


def index_kennt_version(index_url: str, paket: str, version: str) -> bool:
    """Prueft, ob ein pytorch.org-Index diese Fassung fuer Windows/3.11 hat.

    Die Indexseiten sind einfache HTML-Listen mit Dateinamen wie
    'torch-2.8.0+cu126-cp311-cp311-win_amd64.whl'.
    """
    url = f"{index_url.rstrip('/')}/{paket}/"
    try:
        with urllib.request.urlopen(url, timeout=60) as antwort:
            seite = antwort.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as fehler:
        raise RuntimeError(f"Index nicht erreichbar: {url} ({fehler})") from fehler

    # '+cu126' o. ae. darf hinter der Fassung stehen, muss aber nicht.
    muster = re.compile(
        rf"{re.escape(paket)}-{re.escape(version)}(%2B|\+)?[^-]*-cp311-cp311-win_amd64\.whl",
        re.IGNORECASE,
    )
    return bool(muster.search(seite))


def passt_torch_angabe(aufgeloest: str) -> bool:
    """Prueft, ob 'requirements-torch.txt' die geforderte Fassung zulaesst.

    Der erste pip-Aufruf installiert PyTorch nach dieser Datei, der zweite
    installiert WhisperX & Co. Erlaubt die Angabe hier eine ANDERE Fassung
    als die, die der zweite Aufruf verlangt, dann ersetzt pip den
    CUDA-Build kommentarlos durch einen CPU-Build von PyPI.
    """
    passt = True
    for anforderung_text in env.read_requirements(env.TORCH_REQUIREMENTS_FILE):
        anforderung = Requirement(anforderung_text)
        version = gefragte_version(aufgeloest, anforderung.name)
        if version is None:
            print(f"   {anforderung.name}: wird von den uebrigen Paketen nicht verlangt.")
            continue
        if not anforderung.specifier:
            passt = False
            print(
                f"   OHNE VERSION: '{anforderung_text}' laesst jede Fassung zu.\n"
                f"          Der erste pip-Aufruf nimmt dann die neueste aus dem\n"
                f"          CUDA-Index, der zweite ersetzt sie durch {version} von\n"
                f"          PyPI - ohne CUDA. Bitte '{anforderung.name}~={version}'\n"
                f"          eintragen."
            )
        elif version not in anforderung.specifier:
            passt = False
            print(
                f"   PASST NICHT: '{anforderung_text}' laesst {version} nicht zu,\n"
                f"          genau das verlangen aber die Pakete aus\n"
                f"          'requirements-laufzeit.txt'. Der zweite pip-Aufruf\n"
                f"          wuerde den CUDA-Build ersetzen.\n"
                f"          Bitte auf '{anforderung.name}~={version}' aendern."
            )
        else:
            print(f"   {anforderung_text} laesst die geforderte {version} zu.")
    return passt


def sind_cuda12_indizes() -> bool:
    """Prueft, dass die CUDA-Indizes CUDA 12 sind.

    CTranslate2 -- ueber faster-whisper der Kern der Transkription -- ist
    gegen CUDA 12 gebaut und laedt 'cublas64_12.dll'. Ein PyTorch mit
    CUDA 13 (Index 'cu130') bringt stattdessen 'cublas64_13.dll' mit; die
    Transkription bricht dann auf der GPU ab mit "Library cublas64_12.dll
    is not found or cannot be loaded". Am 19.09.2026 genau so gemessen --
    die Installation lief sauber durch, erst die erste Transkription
    scheiterte.
    """
    passt = True
    for name, index_url in (
        ("bis Ada/Hopper", env.TORCH_CUDA_INDEX_URL),
        ("Blackwell", env.TORCH_CUDA_BLACKWELL_INDEX_URL),
    ):
        treffer = re.search(r"/cu(\d)(\d+)/?$", index_url)
        if treffer is None:
            passt = False
            print(f"   UNKLAR: Aus '{index_url}' laesst sich die CUDA-Fassung nicht lesen.")
        elif treffer.group(1) != "1" or not index_url.rstrip("/").endswith(
            tuple(f"cu12{ziffer}" for ziffer in "0123456789")
        ):
            passt = False
            print(
                f"   FALSCH: Index {name} ist kein CUDA-12-Build ({index_url}).\n"
                f"          CTranslate2 laedt 'cublas64_12.dll'; mit CUDA 13\n"
                f"          bricht die Transkription auf der GPU ab."
            )
        else:
            print(f"   {name}: {index_url} ist CUDA 12.")
    return passt


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument(
        "--ausgabe",
        type=Path,
        default=Path("laufzeit-aufgeloest.txt"),
        help="Wohin die aufgeloeste Paketliste geschrieben wird (fuer pip-audit).",
    )
    argumente = zerleger.parse_args()

    print("1) Passen die Laufzeit-Pakete untereinander?")
    try:
        aufgeloest = loese_laufzeitpakete_auf(argumente.ausgabe)
    except RuntimeError as fehler:
        print(f"   FEHLER: {fehler}")
        return 1
    anzahl = len(re.findall(r"^\S+==", aufgeloest, re.MULTILINE))
    print(f"   In Ordnung - {anzahl} Pakete aufgeloest nach {argumente.ausgabe}.")

    print("\n2) Gibt es das geforderte PyTorch auch in den pytorch.org-Indizes?")
    # ALLE Indizes pruefen, die die Anwendung benutzen kann - sonst faellt
    # erst beim Anwender auf, dass ausgerechnet seine Kartengeneration die
    # geforderte Fassung nicht bekommt.
    indizes = {
        "GPU bis Ada/Hopper": env.TORCH_CUDA_INDEX_URL,
        "GPU Blackwell": env.TORCH_CUDA_BLACKWELL_INDEX_URL,
        "CPU": env.TORCH_CPU_INDEX_URL,
    }
    fehlt = False
    for paket in ("torch", "torchaudio"):
        version = gefragte_version(aufgeloest, paket)
        if version is None:
            print(f"   {paket}: kommt in der aufgeloesten Liste nicht vor - nichts zu pruefen.")
            continue
        for name, index_url in indizes.items():
            try:
                vorhanden = index_kennt_version(index_url, paket, version)
            except RuntimeError as fehler:
                print(f"   FEHLER: {fehler}")
                return 1
            if vorhanden:
                print(f"   {paket}=={version} im Index {name} vorhanden.")
            else:
                fehlt = True
                print(
                    f"   FEHLT: {paket}=={version} gibt es im Index {name} nicht\n"
                    f"          ({index_url}).\n"
                    f"          Folge: Der erste pip-Aufruf installiert {paket} von dort,\n"
                    f"          der zweite ueberschreibt es kommentarlos mit der Fassung\n"
                    f"          von PyPI - bei CUDA ist damit die GPU-Unterstuetzung weg.\n"
                    f"          Abhilfe: einen Index waehlen, der {version} kennt, oder\n"
                    f"          die Anforderung in 'requirements-laufzeit.txt' begrenzen."
                )

    print("\n3) Passt die Angabe in 'requirements-torch.txt' dazu?")
    if not passt_torch_angabe(aufgeloest):
        fehlt = True

    print("\n4) Sind die CUDA-Indizes CUDA 12?")
    if not sind_cuda12_indizes():
        fehlt = True

    if fehlt:
        print("\nErgebnis: Die Pakete passen NICHT zusammen.")
        return 1
    print("\nErgebnis: Alles passt zusammen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
