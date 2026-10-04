"""Start: ``python -m protokoll_assistent.server`` (im Container der Standardbefehl)."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import sys
from collections.abc import Mapping, Sequence

from protokoll_assistent.server.dienst import Dienst
from protokoll_assistent.server.einstellungen import EinstellungsFehler, ServerEinstellungen
from protokoll_assistent.utils.hf_env import has_hf_token
from protokoll_assistent.utils.paths import _daten_ordner, ensure_system_prompt_file_exists, get_work_dir


def pruefe_umgebung(einstellungen: ServerEinstellungen) -> list[tuple[bool, str]]:
    """Selbsttest fuer ``--pruefen``: Was fehlt, bevor die erste Aufnahme kommt?"""
    from protokoll_assistent.services import ollama_service

    ergebnisse: list[tuple[bool, str]] = []
    ergebnisse.append((shutil.which("ffmpeg") is not None, "FFmpeg im Suchpfad"))
    ergebnisse.append((shutil.which("ffprobe") is not None, "ffprobe im Suchpfad"))
    for modul, bezeichnung in (("faster_whisper", "faster-whisper"), ("pyannote.audio", "pyannote.audio"), ("docx", "python-docx")):
        try:
            __import__(modul)
            vorhanden = True
        except ImportError:
            vorhanden = False
        ergebnisse.append((vorhanden, f"Paket {bezeichnung}"))
    ergebnisse.append((has_hf_token(), "HF_TOKEN gesetzt (fuer die Sprechertrennung)"))
    for ordner, name in ((einstellungen.eingang, "Eingang"), (einstellungen.ausgang, "Ausgang")):
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            probe = ordner / ".schreibtest"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            ergebnisse.append((True, f"{name}ordner beschreibbar: {ordner}"))
        except OSError as fehler:
            ergebnisse.append((False, f"{name}ordner nicht beschreibbar ({ordner}): {fehler}"))
    if einstellungen.protokoll:
        laeuft = ollama_service.is_service_running()
        ergebnisse.append((laeuft, f"Ollama erreichbar unter {ollama_service.OLLAMA_BASE_URL}"))
    return ergebnisse


def main(argv: Sequence[str] | None = None, umgebung: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protokoll_assistent.server", description="Automatische Verarbeitung ohne Oberflaeche.")
    parser.add_argument("--einmal", action="store_true", help="Den Eingang einmal abarbeiten und beenden.")
    parser.add_argument("--pruefen", action="store_true", help="Umgebung pruefen und beenden.")
    argumente = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stdout)
    try:
        einstellungen = ServerEinstellungen.aus_umgebung(os.environ if umgebung is None else umgebung)
    except EinstellungsFehler as fehler:
        print(f"Einstellungsfehler: {fehler}", file=sys.stderr)
        return 2

    if argumente.pruefen:
        ergebnisse = pruefe_umgebung(einstellungen)
        for ok, text in ergebnisse:
            print(f"[{'OK' if ok else 'FEHLT'}] {text}")
        # Ollama und HF_TOKEN fehlen im Bau-Test des Images legitim: nur das, ohne das nichts laeuft, ist kritisch.
        kritisch = ("FFmpeg", "ffprobe", "Paket", "ordner")
        return 0 if all(ok for ok, text in ergebnisse if any(k in text for k in kritisch)) else 1

    ensure_system_prompt_file_exists()
    dienst = Dienst(einstellungen, _daten_ordner("server_zustand") / "zustand.json")
    for signal_name in ("SIGTERM", "SIGINT"):
        nummer = getattr(signal, signal_name, None)
        if nummer is not None:
            signal.signal(nummer, lambda *_: dienst.stoppen())
    get_work_dir()  # legt den Arbeitsordner an
    if argumente.einmal:
        einstellungen.eingang.mkdir(parents=True, exist_ok=True)
        # 'einmal' wartet nicht auf die Stabilitaetspruefung zwischen zwei Abfragen: zweimal abfragen.
        dienst.einmal()
        dienst.einmal()
        return 0
    dienst.lauf()
    return 0


if __name__ == "__main__":
    sys.exit(main())
