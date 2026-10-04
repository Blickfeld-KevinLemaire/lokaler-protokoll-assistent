"""Ollama auf Wunsch des Anwenders einrichten -- ohne Rueckfragen.

Ollama wird bewusst NICHT mit der Anwendung ausgeliefert: Es bringt
Laufzeitbibliotheken von NVIDIA und AMD unter deren eigenen Bedingungen mit,
belegt installiert knapp 3 GB und waere beim Anwender schnell veraltet. Die
Ersteinrichtung laedt deshalb -- erst nach ausdruecklicher Zustimmung -- den
offiziellen Installer vom Hersteller und installiert ihn still fuer das
eigene Benutzerkonto:

1. ``ermittle_status``   -- ist Ollama schon da? Dann wird nie neu installiert.
2. ``lade_installer``    -- nur HTTPS, nur von den bekannten Adressen, mit
                            Groessen- und Formatpruefung.
3. ``pruefe_signatur``   -- die Datei muss gueltig von "Ollama Inc."
                            signiert sein, sonst wird sie nicht ausgefuehrt.
4. ``installiere_still`` -- Inno-Setup-Schalter, keine Administratorrechte
                            (``PrivilegesRequired=lowest`` im Ollama-Installer).
5. ``warte_auf_dienst``  -- bis der Dienst unter 127.0.0.1:11434 antwortet.

Alle Zugriffe auf Netz, Registry und Programme sind als Parameter
austauschbar: Die Tests brauchen weder Netz noch Ollama (CLAUDE.md, Regel 4).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.services import ollama_service

OLLAMA_LIZENZ_URL = "https://github.com/ollama/ollama/blob/main/LICENSE"
OLLAMA_BEDINGUNGEN_URL = "https://ollama.com/terms"

# ollama.com leitet ueber github.com auf den Speicher der Release-Dateien weiter
# (geprueft am 04.10.2026). Eine Weiterleitung anderswohin wird abgelehnt.
ERLAUBTE_HOSTS = frozenset(
    {"ollama.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)
# Der Installer von Ollama 0.35.1 ist 1,58 GB gross.
MIN_GROESSE_BYTES = 100 * 1024**2
MAX_GROESSE_BYTES = 5 * 1024**3
BLOCK_BYTES = 1024**2
SIGNIERER = "O=Ollama Inc."

# Eintrag des Ollama-Installers unter HKCU (AppId aus Ollamas 'app/ollama.iss').
_DEINSTALLATIONS_SCHLUESSEL = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{44E83376-CE68-45EB-8FC1-393500EB558C}_is1"
)
_KEIN_FENSTER = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOSGELOEST = getattr(subprocess, "DETACHED_PROCESS", 0)

INSTALLATION_ZEITLIMIT_SEKUNDEN = 15 * 60
DIENST_ZEITLIMIT_SEKUNDEN = 120

# Rueckgabewerte von Inno Setup (https://jrsoftware.org/ishelp/topic_setupexitcodes.htm).
_INNO_MELDUNGEN = {
    2: "Die Installation wurde abgebrochen.",
    5: "Die Installation wurde abgebrochen.",
    8: "Die Installation braucht einen Neustart des Computers. Bitte neu starten und die Einrichtung erneut öffnen.",
}

FortschrittFn = Callable[[int, int], None]  # (geladene Bytes, Gesamtbytes)
LogFn = Callable[[str], None]


class OllamaEinrichtungFehler(RuntimeError):
    """Mit einer Meldung, die der Anwender verstehen kann."""


@dataclass(frozen=True)
class OllamaStatus:
    installiert: bool
    pfad: Path | None = None
    version: str | None = None
    dienst_laeuft: bool = False


@dataclass(frozen=True)
class SignaturErgebnis:
    ok: bool
    unterzeichner: str
    meldung: str


# --------------------------------------------------------------------------
# Ist Ollama schon da?
# --------------------------------------------------------------------------
def _registry_eintrag() -> tuple[Path | None, str | None] | None:
    """(Installationsordner, Version) aus dem Deinstallationseintrag, ``None``
    ohne Eintrag oder ausserhalb von Windows."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DEINSTALLATIONS_SCHLUESSEL) as schluessel:

            def wert(name: str) -> str | None:
                try:
                    return str(winreg.QueryValueEx(schluessel, name)[0]) or None
                except OSError:
                    return None

            ordner = wert("InstallLocation")
            return (Path(ordner) if ordner else None), wert("DisplayVersion")
    except OSError:
        return None


def ermittle_status(
    *,
    finde_fn: Callable[[], Path | None] = ollama_service.find_ollama_executable,
    registry_fn: Callable[[], tuple[Path | None, str | None] | None] = _registry_eintrag,
    dienst_fn: Callable[[], bool] = ollama_service.is_service_running,
) -> OllamaStatus:
    pfad = finde_fn()
    eintrag = registry_fn()
    ordner, version = eintrag if eintrag is not None else (None, None)
    if pfad is None and ordner is not None and (ordner / "ollama.exe").is_file():
        pfad = ordner / "ollama.exe"
    dienst = dienst_fn()
    return OllamaStatus(installiert=pfad is not None or eintrag is not None or dienst, pfad=pfad, version=version, dienst_laeuft=dienst)


# --------------------------------------------------------------------------
# Installer laden
# --------------------------------------------------------------------------
def _pruefe_adresse(url: str) -> None:
    teile = urllib.parse.urlsplit(url)
    if teile.scheme != "https" or (teile.hostname or "") not in ERLAUBTE_HOSTS:
        raise OllamaEinrichtungFehler(
            f"Der Ollama-Installer sollte von einer unerwarteten Adresse kommen ({teile.scheme}://{teile.hostname}). "
            "Aus Sicherheitsgründen wurde nichts geladen."
        )


def _umbenennen_mit_wiederholung(quelle: Path, ziel: Path, versuche: int = 5, warten: float = 0.5) -> None:
    """Wie 'manifest_service._ersetzen_mit_wiederholung': Ein Virenscanner haelt
    eine eben geschriebene Datei unter Windows kurz offen (CLAUDE.md, Regel 1)
    -- gerade eine frisch geladene .exe pruefen sie gruendlich."""
    for versuch in range(versuche):
        try:
            quelle.replace(ziel)
            return
        except PermissionError:
            if versuch == versuche - 1:
                raise
            time.sleep(warten)


def lade_installer(
    ziel_ordner: Path,
    fortschritt: FortschrittFn | None = None,
    *,
    url: str = ollama_service.OLLAMA_INSTALLER_URL,
    oeffnen_fn: Callable[..., Any] = urllib.request.urlopen,
    abbrechen_fn: Callable[[], bool] = lambda: False,
    log: LogFn | None = None,
) -> Path:
    """Laedt ``OllamaSetup.exe`` nach ``ziel_ordner`` und liefert den Pfad."""
    melde = fortschritt or (lambda geladen, gesamt: None)
    _pruefe_adresse(url)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    ziel = ziel_ordner / "OllamaSetup.exe"
    teil = ziel_ordner / "OllamaSetup.exe.part"
    pruefsumme = hashlib.sha256()
    try:
        with oeffnen_fn(url, timeout=60) as antwort:
            _pruefe_adresse(antwort.geturl())  # nach allen Weiterleitungen
            try:
                gesamt = int(antwort.headers.get("Content-Length") or 0)
            except ValueError:
                gesamt = 0
            if not MIN_GROESSE_BYTES <= gesamt <= MAX_GROESSE_BYTES:
                raise OllamaEinrichtungFehler(
                    f"Der Ollama-Installer hat eine unerwartete Größe ({gesamt / 1024**2:.0f} MB). "
                    "Aus Sicherheitsgründen wurde er nicht verwendet."
                )
            geladen = 0
            with teil.open("wb") as datei:
                while block := antwort.read(BLOCK_BYTES):
                    if abbrechen_fn():
                        raise OllamaEinrichtungFehler("Der Download wurde abgebrochen.")
                    if geladen == 0 and block[:2] != b"MZ":
                        raise OllamaEinrichtungFehler("Die geladene Datei ist kein Windows-Programm.")
                    datei.write(block)
                    pruefsumme.update(block)
                    geladen += len(block)
                    melde(geladen, gesamt)
            if geladen != gesamt:
                raise OllamaEinrichtungFehler(
                    "Der Download des Ollama-Installers ist unvollständig. Bitte die Internetverbindung prüfen "
                    "und erneut versuchen."
                )
    except OllamaEinrichtungFehler:
        teil.unlink(missing_ok=True)
        raise
    except OSError as fehler:  # URLError ist ein OSError
        teil.unlink(missing_ok=True)
        raise OllamaEinrichtungFehler(
            f"Der Ollama-Installer konnte nicht geladen werden ({fehler}). Bitte die Internetverbindung prüfen."
        ) from fehler
    _umbenennen_mit_wiederholung(teil, ziel)
    if log is not None:
        log(f"Ollama-Installer geladen ({gesamt / 1024**2:.0f} MB, SHA-256 {pruefsumme.hexdigest()}).")
    return ziel


# --------------------------------------------------------------------------
# Echtheit pruefen
# --------------------------------------------------------------------------
# Der Pfad kommt ueber eine Umgebungsvariable, nie in den Befehlstext: Mit
# '-Command' fuegt PowerShell alle weiteren Argumente zu EINEM Befehl zusammen --
# ein Benutzerordner mit Leerzeichen ("C:\Users\Max Mustermann") wuerde den
# Aufruf zerreissen, ein Name mit ';' sogar etwas ausfuehren.
_PFAD_VARIABLE = "PROTOKOLL_PRUEFDATEI"
_SIGNATUR_SKRIPT = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    f"$s = Get-AuthenticodeSignature -LiteralPath $env:{_PFAD_VARIABLE}; "
    "@{s = [string]$s.Status; u = [string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress"
)


def _signatur_umgebung(pfad: Path) -> dict[str, str]:
    """Die Umgebung fuer Windows PowerShell 5.1 -- OHNE 'PSModulePath': Wurde die
    Anwendung aus PowerShell 7 gestartet, zeigt die Variable auf deren Module, und
    5.1 kann 'Get-AuthenticodeSignature' dann nicht laden (am 04.10.2026 so
    aufgefallen). Ohne die Variable nimmt 5.1 seine eigenen."""
    umgebung = {name: wert for name, wert in os.environ.items() if name.upper() != "PSMODULEPATH"}
    umgebung[_PFAD_VARIABLE] = str(pfad)
    return umgebung


def pruefe_signatur(pfad: Path, *, ausfuehren_fn: Callable[..., Any] = subprocess.run) -> SignaturErgebnis:
    """Prueft die Authenticode-Signatur ueber PowerShell. Im Zweifel NICHT ok:
    Fehlt PowerShell, dauert es zu lange oder ist die Antwort unlesbar, wird der
    Installer nicht ausgefuehrt ("fail closed").

    Warum die Signatur und keine feste Pruefsumme: Der Installer aendert sich mit
    jeder Ollama-Fassung. Die Signatur bindet die Datei ueber eine
    Zertifizierungsstelle an den Hersteller -- das ist die aussagekraeftige Pruefung."""
    selbst = "Bitte Ollama selbst von ollama.com installieren."
    powershell = shutil.which("powershell") or "powershell"
    try:
        ergebnis = ausfuehren_fn(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _SIGNATUR_SKRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=_KEIN_FENSTER,
            env=_signatur_umgebung(pfad),
            stdin=subprocess.DEVNULL,
        )
        daten = json.loads(ergebnis.stdout)
        status, unterzeichner = str(daten.get("s", "")), str(daten.get("u", ""))
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as fehler:
        return SignaturErgebnis(False, "", f"Die Echtheit des Ollama-Installers ließ sich nicht prüfen ({fehler}). {selbst}")
    if status != "Valid":
        return SignaturErgebnis(
            False, unterzeichner, f"Der Ollama-Installer ist nicht gültig signiert (Status: {status or 'unbekannt'}). {selbst}"
        )
    if SIGNIERER not in unterzeichner:
        return SignaturErgebnis(
            False, unterzeichner, f"Der Ollama-Installer ist von jemand anderem signiert ({unterzeichner}). {selbst}"
        )
    return SignaturErgebnis(True, unterzeichner, "Signatur gültig: Ollama Inc.")


# --------------------------------------------------------------------------
# Installieren und starten
# --------------------------------------------------------------------------
def installiere_still(
    pfad: Path, *, starte_fn: Callable[..., Any] = subprocess.run, zeitlimit: float = INSTALLATION_ZEITLIMIT_SEKUNDEN
) -> None:
    """Installiert ohne Fenster und Rueckfragen fuer das eigene Benutzerkonto.
    Der Ollama-Installer startet Ollama danach selbst (Eintrag unter [Run])."""
    try:
        ergebnis = starte_fn(
            [str(pfad), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
            timeout=zeitlimit,
            check=False,
            creationflags=_KEIN_FENSTER,
        )
    except subprocess.TimeoutExpired as fehler:
        raise OllamaEinrichtungFehler("Die Installation von Ollama hat zu lange gedauert.") from fehler
    except OSError as fehler:
        # z. B. wenn eine Richtlinie Programme im Benutzerordner sperrt (AppLocker)
        raise OllamaEinrichtungFehler(
            f"Der Ollama-Installer ließ sich nicht starten ({fehler}). Bitte Ollama über Ihre IT oder "
            "von ollama.com installieren."
        ) from fehler
    code = ergebnis.returncode
    if code != 0:
        raise OllamaEinrichtungFehler(
            _INNO_MELDUNGEN.get(code, f"Die Installation von Ollama ist fehlgeschlagen (Code {code}).")
        )


def _starte_app(ordner: Path | None) -> None:
    """Startet die Ollama-Anwendung (sie startet den Dienst), losgeloest von uns."""
    if ordner is None:
        return
    programm = ordner / "ollama app.exe"
    if programm.is_file():
        subprocess.Popen([str(programm)], creationflags=_LOSGELOEST | _KEIN_FENSTER, close_fds=True)


def warte_auf_dienst(
    *,
    dienst_fn: Callable[[], bool] = ollama_service.is_service_running,
    ordner_fn: Callable[[], Path | None] = lambda: (_registry_eintrag() or (None, None))[0],
    starte_app_fn: Callable[[Path | None], None] = _starte_app,
    schlafen_fn: Callable[[float], None] = time.sleep,
    uhr_fn: Callable[[], float] = time.monotonic,
    zeitlimit: float = DIENST_ZEITLIMIT_SEKUNDEN,
    nachstart_nach: float = 20,
) -> bool:
    """Wartet, bis der Dienst antwortet. Kommt er nicht von selbst, wird die
    Ollama-Anwendung einmal gestartet."""
    beginn = uhr_fn()
    nachgestartet = False
    while True:
        if dienst_fn():
            return True
        vergangen = uhr_fn() - beginn
        if vergangen >= zeitlimit:
            return False
        if not nachgestartet and vergangen >= nachstart_nach:
            starte_app_fn(ordner_fn())
            nachgestartet = True
        schlafen_fn(1.0)


def installiere_ollama(
    ziel_ordner: Path,
    log: LogFn,
    fortschritt: FortschrittFn | None = None,
    *,
    status_fn: Callable[[], OllamaStatus] = ermittle_status,
    lade_fn: Callable[..., Path] = lade_installer,
    pruef_fn: Callable[[Path], SignaturErgebnis] = pruefe_signatur,
    install_fn: Callable[[Path], None] = installiere_still,
    warte_fn: Callable[[], bool] = warte_auf_dienst,
    abbrechen_fn: Callable[[], bool] = lambda: False,
) -> bool:
    """Der ganze Ablauf. ``True``: Ollama laeuft danach. ``False``: installiert,
    aber der Dienst antwortet nicht. Fehler kommen als ``OllamaEinrichtungFehler``.
    Ist Ollama schon installiert, wird nur gestartet -- nie neu installiert."""
    status = status_fn()
    if status.installiert:
        log("Ollama ist bereits installiert" + (f" (Version {status.version})." if status.version else "."))
        if status.dienst_laeuft:
            return True
        log("Ollama wird gestartet ...")
        return warte_fn()

    log("Ollama wird vom Hersteller geladen ...")
    installer = lade_fn(ziel_ordner, fortschritt, abbrechen_fn=abbrechen_fn, log=log)
    try:
        log("Echtheit wird geprüft ...")
        signatur = pruef_fn(installer)
        if not signatur.ok:
            raise OllamaEinrichtungFehler(signatur.meldung)
        log(signatur.meldung)
        log("Ollama wird installiert (ohne Administratorrechte, nur für Ihr Benutzerkonto) ...")
        install_fn(installer)
    finally:
        installer.unlink(missing_ok=True)
    log("Ollama wird gestartet ...")
    return warte_fn()
