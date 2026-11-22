"""Startet die Programmschnittstelle.

    python -m protokoll_assistent.api --rolle desktop --port 0 --port-datei <pfad>
    python -m protokoll_assistent.api --rolle server --host 0.0.0.0 --port 8780
    python -m protokoll_assistent.api zugang-anlegen <Name>      (Zugangsschluessel fuer den Servermodus)
    python -m protokoll_assistent.api openapi                    (Schnittstellenbeschreibung ausgeben)

Rolle ``desktop``: Den Schluessel uebergibt das Desktop-Fenster in der Umgebung
(``VERMERK_API_SCHLUESSEL``). Fehlt er, startet der Dienst nur mit
``--entwicklung`` -- dann erzeugt er einen und legt ihn (mit Port) in
``api_zugang.json`` im Einstellungsordner ab, wo der Entwicklungsserver der
Oberflaeche ihn findet. Ohne Schluessel gibt es keinen Betrieb.

Port: Mit ``--port 0`` (Vorgabe der Rolle desktop) vergibt Windows einen freien Port. Der Dienst bindet ihn
selbst und schreibt danach ``{"port", "pid", "netz_port", "version"}`` atomar in die ``--port-datei`` --
erst daraus erfaehrt das Fenster den Port. Ob dort wirklich *sein* Dienst antwortet, prueft das Fenster
mit ``/api/info`` und seinem Schluessel (ein fremder Prozess antwortet mit 401 oder gar nicht).

``VERMERK_ELTERN_PID``: Prozess des Desktop-Fensters (bzw. durch Komma getrennt
mehrere, wenn sich der Dienst fuer den lokalen Modus selbst neu gestartet hat).
Endet einer davon, beendet sich auch dieser Dienst -- sonst blieben nach einem Absturz des Fensters verwaiste
Dienste zurueck, die den Port und die Grafikkarte belegen.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.aufnahme import Aufnahmesteuerung
from protokoll_assistent.ablauf.geraete_automatik import GeraeteAutomatik
from protokoll_assistent.ablauf.nutzer import NutzerFehler, Nutzerverwaltung
from protokoll_assistent.ablauf.steuerung import Steuerung
from protokoll_assistent.api.app import TAURI_URSPRUENGE, app_erstellen
from protokoll_assistent.api.kontext import Dienste
from protokoll_assistent.api.sicherheit import (
    ROLLE_DESKTOP,
    ROLLE_SERVER,
    UMGEBUNG_SCHLUESSEL,
    Zugang,
    schluessel_erzeugen,
    schluessel_hash,
    zugaenge_aus_konfiguration,
)
from protokoll_assistent.services import geraete_empfang_service
from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung
from protokoll_assistent.utils import app_config, paths
from protokoll_assistent.utils.paths import ensure_system_prompt_file_exists, get_paket_dir
from protokoll_assistent.version import VERSION

STANDARD_SERVER_PORT = 8780
# Exit-Code fuer "bitte neu starten" -- das Fenster startet den Dienst dann sofort wieder
# (oberflaeche/src-tauri/src/ueberwachung.rs, NEUSTART_EXIT_CODE).
NEUSTART_EXIT_CODE = 75
ENTWICKLUNG_URSPRUENGE = ("http://localhost:5173", "http://127.0.0.1:5173")


def oberflaeche_ordner() -> Path | None:
    """Die gebaute Oberflaeche: neben der EXE (``oberflaeche``) oder im Projekt (``oberflaeche/build``)."""
    kandidaten = [
        Path(os.environ["VERMERK_OBERFLAECHE"]) if os.environ.get("VERMERK_OBERFLAECHE") else None,
        get_paket_dir().parent / "oberflaeche" / "build",
        Path(getattr(sys, "_MEIPASS", "")) / "oberflaeche" if getattr(sys, "frozen", False) else None,
    ]
    return next((k for k in kandidaten if k is not None and (k / "index.html").is_file()), None)


def zugang_datei() -> Path:
    return paths.get_settings_dir() / "api_zugang.json"


def desktop_schluessel(entwicklung: bool, port: int, umgebung: dict[str, str] | None = None) -> str:
    umgebung = umgebung if umgebung is not None else dict(os.environ)
    schluessel = umgebung.get(UMGEBUNG_SCHLUESSEL, "").strip()
    if schluessel:
        return schluessel
    if not entwicklung:
        raise SystemExit(
            f"{UMGEBUNG_SCHLUESSEL} fehlt. Die Rolle 'desktop' startet nur mit Schlüssel "
            "(oder zum Entwickeln mit --entwicklung)."
        )
    schluessel = schluessel_erzeugen()
    datei = zugang_datei()
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps({"port": port, "schluessel": schluessel}), encoding="utf-8")
    with contextlib.suppress(OSError):
        datei.chmod(0o600)
    return schluessel


def nutzer_datei() -> Path:
    return paths.get_settings_dir() / "nutzer.json"


def dienste_erstellen(
    rolle: str, schluessel: str | None, steuerung: Steuerung | None = None, *, mehrbenutzer: bool = False
) -> Dienste:
    """``mehrbenutzer``: der Servermodus mit Nutzerverwaltung. Die Netzfreigabe der Windows-Anwendung ist
    Rolle server, aber ein Mensch -- dort bleibt es bei den festen Zugangsschluesseln."""
    steuerung = steuerung or Steuerung()
    if mehrbenutzer:
        steuerung.mehrbenutzer = True
    automatik = GeraeteAutomatik(steuerung)

    def zugaenge() -> dict[str, str]:
        return zugaenge_aus_konfiguration(
            steuerung.konfiguration().get("server_zugaenge") or [], os.environ.get("VERMERK_ZUGANG") or None
        )

    zugang = Zugang(
        rolle,
        start_schluessel=schluessel if rolle == ROLLE_DESKTOP else None,
        zugaenge=zugaenge,
        nutzer=Nutzerverwaltung(nutzer_datei()) if mehrbenutzer else None,
    )
    dienste = Dienste(steuerung=steuerung, automatik=automatik, zugang=zugang)
    dienste.nach_einstellungen.append(automatik.anwenden)
    if rolle == ROLLE_DESKTOP:
        dienste.aufnahme = Aufnahmesteuerung(
            steuerung.bus,
            steuerung.aufnahmeordner,
            konfiguration=steuerung.konfiguration,
            merken=lambda name: app_config.update_config(aufnahmegeraet=name),
        )
    return dienste


def eltern_wache(pid: int, beenden: Callable[[], None]) -> threading.Thread:
    """Wartet im Hintergrund auf das Ende des Elternprozesses und ruft dann ``beenden`` auf."""

    def warten() -> None:
        if os.name == "nt":  # pragma: no cover - nur Windows
            import ctypes

            synchronize = 0x00100000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            griff = kernel32.OpenProcess(synchronize, False, pid)
            if griff:
                kernel32.WaitForSingleObject(griff, 0xFFFFFFFF)
                kernel32.CloseHandle(griff)
        else:
            # Nie 'os.kill(pid, 0)' verwenden: Unter Windows beendet das den Prozess.
            while os.getppid() == pid:
                threading.Event().wait(1.0)
        beenden()

    faden = threading.Thread(target=warten, name="eltern-wache", daemon=True)
    faden.start()
    return faden


def socket_binden(host: str, port: int) -> socket.socket:
    """Bindet den Port **selbst**, bevor der Server startet.

    Port 0: Windows vergibt einen freien -- es gibt kein "erst pruefen, dann binden", zwischen dem ein anderes
    Programm den Port wegschnappen koennte. Ist ein fester Port belegt, kommt hier ein ``OSError`` (und nicht
    erst in uvicorn, das in dem Fall den ganzen Prozess beendet)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        # Kein zweiter Prozess darf denselben Port zusaetzlich binden (unter Windows sonst moeglich).
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(False)
    return sock


def port_datei_schreiben(ziel: Path, daten: dict[str, Any]) -> None:
    """Handschlag mit dem Desktop-Fenster: atomar (erst unter Arbeitsnamen, dann ersetzen), damit das Fenster
    nie eine halb geschriebene Datei liest."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    temp = ziel.with_name(ziel.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(daten), encoding="utf-8")
    _ersetzen_mit_wiederholung(temp, ziel)


def _uvicorn_server(app: Any) -> Any:
    import uvicorn

    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off")
    return uvicorn.Server(config)


async def _laufen(server: list[tuple[Any, socket.socket]]) -> None:
    await asyncio.gather(*(s.serve(sockets=[sock]) for s, sock in server))


def rechenumgebung_vorbereiten(rolle: str, argv: Sequence[str]) -> None:
    """Wie ``app.py``: Steht die Transkription auf "lokal" und ist zugestimmt, wechselt der Dienst vor dem
    Start in die Rechenumgebung mit Torch & Co. (und richtet sie beim ersten Mal ein). Der Servermodus
    (Container) bringt seine Pakete selbst mit; dort und wenn die Pakete schon da sind, geschieht nichts."""
    from protokoll_assistent import bootstrap
    from protokoll_assistent.ablauf.verarbeitungswege import lokale_laufzeit_verfuegbar

    if rolle != ROLLE_DESKTOP or lokale_laufzeit_verfuegbar() or bootstrap.is_running_in_managed_venv():
        return
    if bootstrap.laufzeit_beim_start_einrichten(
        app_config.load_config(), fenster_moeglich=True, laufzeit_vorhanden=bootstrap.laufzeit_eingerichtet()
    ):
        bootstrap.als_dienst(list(argv))
        bootstrap.ensure_runtime_and_relaunch()


def eingang_einrichten(dienste: Dienste, umgebung: dict[str, str] | None = None) -> Any:
    """Servermodus: Ist ``PROTOKOLL_EINGANG`` gesetzt, reiht eine Wache neue Dateien dort in die gemeinsame
    Warteschlange ein (wie frueher ``python -m protokoll_assistent.server``). Gibt die Wache oder None zurueck."""
    from protokoll_assistent.server.eingang_wache import EingangsWache
    from protokoll_assistent.server.einstellungen import EinstellungsFehler, ServerEinstellungen

    umgebung = dict(os.environ) if umgebung is None else umgebung
    if not umgebung.get("PROTOKOLL_EINGANG"):
        return None
    try:
        einstellungen = ServerEinstellungen.aus_umgebung(umgebung)
    except EinstellungsFehler as fehler:
        dienste.steuerung.hinweis(f"Eingangsordner nicht eingerichtet: {fehler}", stufe="fehler", quelle="netz")
        return None
    # Ohne eigene Einstellung landen die Ergebnisse im Ausgangsordner des Containers.
    if not dienste.steuerung.konfiguration().get("ausgabeordner"):
        app_config.update_config(ausgabeordner=str(einstellungen.ausgang))
    besitzer = (umgebung.get("PROTOKOLL_EINGANG_NUTZER") or "").strip() or None
    if besitzer is not None and (dienste.nutzer is None or dienste.nutzer.hole(besitzer) is None):
        dienste.steuerung.hinweis(
            f"PROTOKOLL_EINGANG_NUTZER: Den Nutzer „{besitzer}“ gibt es nicht; Ergebnisse sehen nur Admins.",
            stufe="fehler",
            quelle="netz",
        )
        besitzer = None
    return EingangsWache(dienste.steuerung, einstellungen, paths.get_work_dir() / "eingang_zustand.json", besitzer=besitzer)


def starten(argumente: argparse.Namespace, argv: Sequence[str] = ()) -> int:
    from protokoll_assistent.utils.logging_setup import setup_logging

    rechenumgebung_vorbereiten(argumente.rolle, argv)

    setup_logging()
    ensure_system_prompt_file_exists()
    rolle = argumente.rolle
    host = argumente.host or ("127.0.0.1" if rolle == ROLLE_DESKTOP else "0.0.0.0")  # noqa: S104 -- Servermodus lauscht im Netz
    port = argumente.port if argumente.port is not None else (0 if rolle == ROLLE_DESKTOP else STANDARD_SERVER_PORT)
    try:
        haupt_socket = socket_binden(host, port)
    except OSError as fehler:
        print(f"Port {port} auf {host} ist nicht nutzbar: {fehler}", file=sys.stderr)
        return 3
    port = int(haupt_socket.getsockname()[1])
    schluessel = desktop_schluessel(argumente.entwicklung, port) if rolle == ROLLE_DESKTOP else None
    dienste = dienste_erstellen(rolle, schluessel, mehrbenutzer=rolle == ROLLE_SERVER)
    if rolle == ROLLE_SERVER and dienste.nutzer is not None and dienste.nutzer.leer() and not os.environ.get("VERMERK_ZUGANG"):
        print(
            "Hinweis: Es gibt noch keinen Nutzer. Ersten Admin anlegen mit\n"
            "  python -m protokoll_assistent.api nutzer-anlegen <Name> --admin\n"
            "oder VERMERK_ZUGANG für die Ersteinrichtung setzen.",
            file=sys.stderr,
        )
    oberflaeche = oberflaeche_ordner()
    urspruenge = [*TAURI_URSPRUENGE, *(ENTWICKLUNG_URSPRUENGE if argumente.entwicklung else ())]
    if rolle == ROLLE_DESKTOP:
        hosts = ["127.0.0.1", "localhost"]
        app = app_erstellen(dienste, erlaubte_hosts=hosts, cors_urspruenge=urspruenge, oberflaeche=oberflaeche)
    else:
        erlaubt = [h.strip() for h in os.environ.get("VERMERK_ERLAUBTE_HOSTS", "*").split(",") if h.strip()]
        app = app_erstellen(dienste, erlaubte_hosts=erlaubt, cors_urspruenge=(), oberflaeche=oberflaeche)
    server: list[tuple[Any, socket.socket]] = [(_uvicorn_server(app), haupt_socket)]

    konfig = dienste.steuerung.konfiguration()
    netz_port: int | None = None
    if rolle == ROLLE_DESKTOP and konfig.get("netz_freigabe_aktiv"):
        # Dieselbe Steuerung zusaetzlich im Netz, aber mit eigener Zugangspruefung (Zugangsschluessel). Ist der
        # Port belegt, laeuft die Anwendung trotzdem -- nur ohne Freigabe, und die Oberflaeche sagt es.
        gewuenscht = int(konfig.get("netz_freigabe_port") or STANDARD_SERVER_PORT)
        try:
            netz_socket = socket_binden("0.0.0.0", gewuenscht)  # noqa: S104 -- ausdruecklich eingeschaltet
        except OSError:
            dienste.steuerung.hinweis(
                f"Im Netz anbieten ist eingeschaltet, aber Port {gewuenscht} wird schon benutzt. "
                "Bitte in den Einstellungen einen anderen Port wählen.",
                stufe="fehler",
                quelle="netz",
                code="port_belegt",
            )
        else:
            netz = dienste_erstellen(ROLLE_SERVER, None, steuerung=dienste.steuerung)
            netz.automatik = dienste.automatik
            netz_app = app_erstellen(netz, erlaubte_hosts=["*"], cors_urspruenge=(), oberflaeche=oberflaeche)
            server.append((_uvicorn_server(netz_app), netz_socket))
            netz_port = gewuenscht

    def beenden() -> None:
        for s, _sock in server:
            s.should_exit = True

    neustart_gewuenscht = threading.Event()

    def neustart_anfordern() -> None:
        neustart_gewuenscht.set()
        # Kurz warten, damit die Antwort auf die Anfrage noch rausgeht.
        threading.Timer(0.5, beenden).start()

    if rolle == ROLLE_DESKTOP and os.environ.get("VERMERK_ELTERN_PID"):
        dienste.neustart_anfordern = neustart_anfordern

    for eltern in os.environ.get("VERMERK_ELTERN_PID", "").split(","):
        if eltern.strip().isdigit():
            eltern_wache(int(eltern), beenden)

    dienste.steuerung.starten()
    if dienste.automatik is not None:
        dienste.automatik.anwenden()
        dienste.automatik.wache_starten()
    eingang = eingang_einrichten(dienste) if rolle == ROLLE_SERVER else None
    if eingang is not None:
        eingang.starten()
    if argumente.port_datei:
        # Erst jetzt: Der Port ist gebunden, Verbindungen warten in der Warteschlange des Sockets, bis uvicorn
        # sie annimmt -- das Fenster kann sich also sofort melden.
        port_datei_schreiben(
            Path(argumente.port_datei),
            {"port": port, "pid": os.getpid(), "netz_port": netz_port, "version": VERSION},
        )
    try:
        asyncio.run(_laufen(server))
    finally:
        if eingang is not None:
            eingang.stoppen()
        if dienste.automatik is not None:
            dienste.automatik.stoppen()
        dienste.steuerung.beenden()
    return NEUSTART_EXIT_CODE if neustart_gewuenscht.is_set() else 0


def zugang_anlegen(name: str) -> int:
    """Legt einen Zugangsschluessel an. Er wird genau einmal ausgegeben; gespeichert wird nur sein Hash."""
    import datetime as dt

    name = name.strip()
    if not geraete_empfang_service.geraetename_gueltig(name):
        print("Name: Buchstaben, Ziffern, _ und -, höchstens 32 Zeichen.", file=sys.stderr)
        return 2
    konfig = app_config.load_config()
    zugaenge = [dict(z) for z in konfig.get("server_zugaenge") or [] if isinstance(z, dict) and z.get("name") != name]
    schluessel = schluessel_erzeugen()
    zugaenge.append({"name": name, "token_sha256": schluessel_hash(schluessel), "angelegt": dt.date.today().isoformat()})
    app_config.update_config(server_zugaenge=zugaenge)
    print(f"Zugangsschlüssel für {name} (wird nur jetzt angezeigt):\n{schluessel}")
    return 0


def nutzer_anlegen(argumente: Sequence[str]) -> int:
    """Legt einen Nutzer an (Servermodus) und gibt einen ersten Zugangsschluessel genau einmal aus. Ein Passwort
    kann der Nutzer danach im Browser setzen (oder ein Admin in der Nutzerverwaltung)."""
    parser = argparse.ArgumentParser(prog="python -m protokoll_assistent.api nutzer-anlegen")
    parser.add_argument("name")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--anzeigename", default="")
    werte = parser.parse_args(list(argumente))
    verwaltung = Nutzerverwaltung(nutzer_datei())
    try:
        verwaltung.anlegen(werte.name, anzeigename=werte.anzeigename, admin=werte.admin)
        schluessel = verwaltung.zugang_anlegen(werte.name, "Erster Zugang")
    except NutzerFehler as fehler:
        print(str(fehler), file=sys.stderr)
        return 2
    print(f"Nutzer {werte.name} angelegt{' (Admin)' if werte.admin else ''}. Zugangsschlüssel (wird nur jetzt angezeigt):")
    print(schluessel)
    return 0


def openapi_ausgeben() -> int:
    dienste = dienste_erstellen(ROLLE_DESKTOP, "nur-fuer-die-beschreibung")
    app = app_erstellen(dienste)
    # Immer UTF-8 (unter Windows schriebe 'print' in der Codepage der Konsole) und immer LF.
    sys.stdout.buffer.write(openapi_text(app.openapi()).encode("utf-8"))
    return 0


def openapi_text(beschreibung: dict[str, Any]) -> str:
    return json.dumps(beschreibung, ensure_ascii=False, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["zugang-anlegen"] and len(argv) == 2:
        return zugang_anlegen(argv[1])
    if argv[:1] == ["nutzer-anlegen"]:
        return nutzer_anlegen(argv[1:])
    if argv[:1] == ["openapi"]:
        return openapi_ausgeben()
    parser = argparse.ArgumentParser(prog="python -m protokoll_assistent.api")
    parser.add_argument("--rolle", choices=(ROLLE_DESKTOP, ROLLE_SERVER), default=ROLLE_DESKTOP)
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--port-datei", default="")
    parser.add_argument("--entwicklung", action="store_true")
    return starten(parser.parse_args(argv), argv)


if __name__ == "__main__":
    sys.exit(main())
