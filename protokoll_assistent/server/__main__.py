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
from protokoll_assistent.services import geraete_empfang_service
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
    if einstellungen.empfang:
        namen = ", ".join(g.name for g in einstellungen.empfang_geraete)
        ergebnisse.append((True, f"Empfang fuer Aufnahmegeraete auf Port {einstellungen.empfang_port}: {namen}"))
    return ergebnisse


def token_ausgeben(name: str) -> int:
    """``--token-erzeugen``: neues Token fuer ein Aufnahmegeraet. Das Token wird
    nur hier einmal angezeigt; in die Einstellungen gehoert nur sein Hash."""
    if not geraete_empfang_service.geraetename_gueltig(name):
        print(
            f"'{name}' ist kein gueltiger Geraetename (Buchstaben, Ziffern, _ und -, hoechstens 32 Zeichen).",
            file=sys.stderr,
        )
        return 2
    token = geraete_empfang_service.token_erzeugen()
    print(f"Token fuer '{name}' -- in die server_config.h des Geraets eintragen, es wird nur jetzt angezeigt:")
    print(f"  {token}")
    print("Eintrag fuer PROTOKOLL_EMPFANG_GERAETE (mehrere Geraete mit Komma trennen):")
    print(f"  {name}:{geraete_empfang_service.token_hash(token)}")
    return 0


def main(argv: Sequence[str] | None = None, umgebung: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protokoll_assistent.server", description="Automatische Verarbeitung ohne Oberflaeche.")
    parser.add_argument("--einmal", action="store_true", help="Den Eingang einmal abarbeiten und beenden.")
    parser.add_argument("--pruefen", action="store_true", help="Umgebung pruefen und beenden.")
    parser.add_argument(
        "--token-erzeugen", metavar="NAME", help="Token fuer ein Aufnahmegeraet erzeugen, anzeigen und beenden."
    )
    argumente = parser.parse_args(argv)
    if argumente.token_erzeugen is not None:
        return token_ausgeben(argumente.token_erzeugen)

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
    empfang = None
    if einstellungen.empfang:
        empfang = geraete_empfang_service.GeraeteEmpfang(
            einstellungen.eingang, einstellungen.empfang_geraete, port=einstellungen.empfang_port
        )
        try:
            empfang.starten()
        except OSError as fehler:
            print(f"Empfang fuer Aufnahmegeraete: Port {einstellungen.empfang_port} nicht nutzbar ({fehler}).", file=sys.stderr)
            return 2
    try:
        dienst.lauf()
    finally:
        if empfang is not None:
            empfang.stoppen()
    return 0


if __name__ == "__main__":
    sys.exit(main())
