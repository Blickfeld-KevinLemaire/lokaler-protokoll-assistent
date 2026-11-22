"""Rauchtest fuer den Dienst – so, wie ihn das Desktop-Fenster startet (nur Standardbibliothek).

    python tools/dienst_rauchtest.py dist/vermerk-dienst/vermerk-dienst.exe
    python tools/dienst_rauchtest.py --python          (python -m protokoll_assistent.api aus dem Quelltext)

Ablauf: Dienst mit ``--rolle desktop --port 0 --port-datei <tmp>`` und einem Zufallsschluessel (nur in der
Umgebung) starten, auf die Portdatei warten (hoechstens 120 s), dann pruefen:

* ``/api/gesundheit`` ohne Schluessel -> 200
* ``/api/info`` ohne Schluessel -> 401, mit Schluessel -> 200
* ``Host: evil.example`` -> 400 (Schutz gegen DNS-Rebinding)

Danach eine ZWEITE Instanz genauso: anderer Port, beide antworten, der Schluessel der einen gilt bei der
anderen nicht. Beendet werden nur die selbst gestarteten Prozesse (samt ihren Kindern, ueber die PID).
Exit-Code 0 nur, wenn alles stimmt.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

WARTEZEIT_PORTDATEI = 120.0
KEIN_FENSTER = 0x08000000 if os.name == "nt" else 0


@dataclass
class Dienst:
    name: str
    prozess: subprocess.Popen[bytes]
    schluessel: str
    port_datei: Path
    protokoll: Path
    port: int = 0
    version: str = ""


class RauchtestFehler(Exception):
    pass


def starten(befehl: list[str], name: str, arbeitsordner: Path, projekt: Path) -> Dienst:
    schluessel = secrets.token_urlsafe(32)
    port_datei = arbeitsordner / f"port-{name}.json"
    port_datei.unlink(missing_ok=True)
    anwendungsordner = arbeitsordner / f"anwendung-{name}"
    anwendungsordner.mkdir(parents=True, exist_ok=True)
    umgebung = dict(os.environ)
    umgebung.update(
        {
            "VERMERK_API_SCHLUESSEL": schluessel,
            "VERMERK_ELTERN_PID": str(os.getpid()),
            # Einstellungen/Daten des Tests nicht in den Build-Ordner (der landet im Installer).
            "VERMERK_ANWENDUNGSORDNER": str(anwendungsordner),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    umgebung.pop("VERMERK_EXTERNER_DIENST", None)
    protokoll = arbeitsordner / f"dienst-{name}.log"
    with protokoll.open("wb") as ausgabe:
        prozess = subprocess.Popen(
            [*befehl, "--rolle", "desktop", "--port", "0", "--port-datei", str(port_datei)],
            env=umgebung,
            cwd=str(projekt),
            stdin=subprocess.DEVNULL,
            stdout=ausgabe,
            stderr=subprocess.STDOUT,
            creationflags=KEIN_FENSTER,
        )
    print(f"[{name}] gestartet, PID {prozess.pid}")
    return Dienst(name, prozess, schluessel, port_datei, protokoll)


def auf_portdatei_warten(dienst: Dienst) -> None:
    ende = time.monotonic() + WARTEZEIT_PORTDATEI
    while time.monotonic() < ende:
        code = dienst.prozess.poll()
        if code is not None:
            raise RauchtestFehler(f"[{dienst.name}] Dienst hat sich vor dem Handschlag beendet (Exit-Code {code})")
        try:
            daten = json.loads(dienst.port_datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        port = daten.get("port")
        if not isinstance(port, int) or not 0 < port < 65536:
            raise RauchtestFehler(f"[{dienst.name}] Portdatei ohne gueltigen Port: {daten}")
        for feld in ("pid", "netz_port", "version"):
            if feld not in daten:
                raise RauchtestFehler(f"[{dienst.name}] Portdatei ohne '{feld}': {daten}")
        dienst.port = port
        dienst.version = str(daten["version"])
        print(f"[{dienst.name}] Portdatei: Port {port}, PID {daten['pid']}, Version {dienst.version}")
        return
    raise RauchtestFehler(f"[{dienst.name}] keine Portdatei nach {WARTEZEIT_PORTDATEI:.0f} s")


def anfrage(port: int, pfad: str, schluessel: str | None = None, host: str | None = None) -> int:
    kopf = {"Host": host or f"127.0.0.1:{port}", "Accept": "application/json"}
    if schluessel:
        kopf["Authorization"] = f"Bearer {schluessel}"
    verbindung = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        verbindung.request("GET", pfad, headers=kopf)
        antwort = verbindung.getresponse()
        antwort.read()
        return antwort.status
    finally:
        verbindung.close()


def erwarten(dienst: Dienst, beschreibung: str, ist: int, soll: int) -> None:
    ok = ist == soll
    print(f"[{dienst.name}] {'OK ' if ok else 'FEHLER'} {beschreibung}: {ist} (erwartet {soll})")
    if not ok:
        raise RauchtestFehler(f"[{dienst.name}] {beschreibung}: {ist} statt {soll}")


def pruefen(dienst: Dienst) -> None:
    erwarten(dienst, "/api/gesundheit ohne Schluessel", anfrage(dienst.port, "/api/gesundheit"), 200)
    erwarten(dienst, "/api/info ohne Schluessel", anfrage(dienst.port, "/api/info"), 401)
    erwarten(dienst, "/api/info mit Schluessel", anfrage(dienst.port, "/api/info", dienst.schluessel), 200)
    erwarten(
        dienst,
        "/api/gesundheit mit Host evil.example",
        anfrage(dienst.port, "/api/gesundheit", host="evil.example"),
        400,
    )


def beenden(dienst: Dienst) -> None:
    """Beendet genau diesen Prozess samt Kindern (ueber seine PID, nie ueber den Programmnamen)."""
    if dienst.prozess.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(dienst.prozess.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=KEIN_FENSTER,
            )
        else:
            dienst.prozess.kill()
    try:
        dienst.prozess.wait(timeout=15)
    except subprocess.TimeoutExpired:
        print(f"[{dienst.name}] WARNUNG: Prozess {dienst.prozess.pid} endet nicht")


def protokoll_zeigen(dienst: Dienst) -> None:
    try:
        text = dienst.protokoll.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    print(f"----- Ausgabe von [{dienst.name}] (Ende) -----")
    print("\n".join(text.splitlines()[-40:]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("exe", nargs="?", help="gebauter Dienst (vermerk-dienst.exe)")
    parser.add_argument("--python", action="store_true", help="python -m protokoll_assistent.api starten")
    argumente = parser.parse_args(argv)
    projekt = Path(__file__).resolve().parent.parent
    if argumente.python:
        befehl = [sys.executable, "-m", "protokoll_assistent.api"]
    elif argumente.exe:
        exe = Path(argumente.exe).resolve()
        if not exe.is_file():
            print(f"FEHLER: {exe} nicht gefunden", file=sys.stderr)
            return 2
        befehl = [str(exe)]
    else:
        parser.error("Pfad zur EXE oder --python angeben")

    arbeitsordner = Path(tempfile.mkdtemp(prefix="vermerk-rauchtest-"))
    dienste: list[Dienst] = []
    erfolg = False
    try:
        erster = starten(befehl, "1", arbeitsordner, projekt)
        dienste.append(erster)
        auf_portdatei_warten(erster)
        pruefen(erster)

        zweiter = starten(befehl, "2", arbeitsordner, projekt)
        dienste.append(zweiter)
        auf_portdatei_warten(zweiter)
        if zweiter.port == erster.port:
            raise RauchtestFehler(f"Beide Instanzen melden denselben Port {erster.port}")
        print(f"OK  zwei Instanzen, zwei Ports: {erster.port} und {zweiter.port}")
        pruefen(zweiter)
        erwarten(erster, "erste Instanz antwortet weiter", anfrage(erster.port, "/api/gesundheit"), 200)
        erwarten(
            zweiter,
            "/api/info mit dem Schluessel der ersten Instanz",
            anfrage(zweiter.port, "/api/info", erster.schluessel),
            401,
        )
        erfolg = True
    except (RauchtestFehler, OSError, http.client.HTTPException) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
    finally:
        for dienst in dienste:
            beenden(dienst)
        if not erfolg:
            for dienst in dienste:
                protokoll_zeigen(dienst)
        shutil.rmtree(arbeitsordner, ignore_errors=True)
    print("Rauchtest bestanden." if erfolg else "Rauchtest FEHLGESCHLAGEN.")
    return 0 if erfolg else 1


if __name__ == "__main__":
    sys.exit(main())
