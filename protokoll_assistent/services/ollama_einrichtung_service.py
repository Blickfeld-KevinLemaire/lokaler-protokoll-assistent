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
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.services import ollama_service
from protokoll_assistent.utils import netz

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
_NEUE_GRUPPE = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

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
    # Diese Form versteht mypy: Auf Linux (CI-Pruefung) gilt der Rest als
    # unerreichbar, statt die Windows-Funktionen von 'winreg' zu vermissen.
    if sys.platform != "win32":
        return None
    import winreg

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
    """Ist Ollama wirklich da? Nur, wenn es ``ollama.exe`` gibt oder ein Dienst antwortet. Ein Deinstallationseintrag
    allein genuegt nicht: Wurde Ollama von Hand geloescht oder nur halb installiert, bleibt er stehen -- die
    Einrichtung hielt Ollama dann fuer installiert, und die Nachbearbeitung scheiterte spaeter mit "nicht gefunden"."""
    pfad = finde_fn()
    if pfad is not None and not pfad.is_file():
        pfad = None
    eintrag = registry_fn()
    ordner, version = eintrag if eintrag is not None else (None, None)
    if pfad is None and ordner is not None and (ordner / "ollama.exe").is_file():
        pfad = ordner / "ollama.exe"
    dienst = dienst_fn()
    return OllamaStatus(installiert=pfad is not None or dienst, pfad=pfad, version=version, dienst_laeuft=dienst)


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


def _lade_mit_windows(
    url: str,
    teil: Path,
    urspruenglich: OSError,
    windows_fn: Callable[..., Any],
    pruefsumme: Any,
    abbrechen_fn: Callable[[], bool],
    melde: FortschrittFn,
) -> int:
    """Zweiter Versuch nach einem Zertifikatsfehler von Python: Windows' eigener TLS-Stack laedt die Datei, danach
    dieselben Pruefungen wie beim ersten Weg. Liefert die Groesse; bei jedem Mangel ``OllamaEinrichtungFehler``.
    Abbruch und Fortschritt gelten auch hier -- die Gesamtgroesse ist auf diesem Weg vorab nicht bekannt (0)."""
    try:
        try:
            endgueltig = windows_fn(
                url, teil, abbrechen_fn=abbrechen_fn, fortschritt_fn=lambda geladen: melde(geladen, 0)
            )
            _pruefe_adresse(endgueltig)  # nach allen Weiterleitungen
            groesse = teil.stat().st_size
            if not MIN_GROESSE_BYTES <= groesse <= MAX_GROESSE_BYTES:
                raise OllamaEinrichtungFehler(
                    f"Der Ollama-Installer hat eine unerwartete Größe ({groesse / 1024**2:.0f} MB). "
                    "Aus Sicherheitsgründen wurde er nicht verwendet."
                )
            with teil.open("rb") as datei:
                if datei.read(2) != b"MZ":
                    raise OllamaEinrichtungFehler("Die geladene Datei ist kein Windows-Programm.")
                datei.seek(0)
                while block := datei.read(BLOCK_BYTES):
                    pruefsumme.update(block)
            return groesse
        except netz.Abgebrochen as fehler:
            raise OllamaEinrichtungFehler("Der Download wurde abgebrochen.") from fehler
        except OSError as fehler:
            raise OllamaEinrichtungFehler(
                f"Der Ollama-Installer konnte nicht geladen werden ({urspruenglich}). Das Zertifikat des Servers "
                f"wird auf diesem Rechner nicht anerkannt (Firmennetz oder fehlende Windows-Updates?). {fehler}"
            ) from urspruenglich
    except OllamaEinrichtungFehler:
        teil.unlink(missing_ok=True)
        raise


def lade_installer(
    ziel_ordner: Path,
    fortschritt: FortschrittFn | None = None,
    *,
    url: str = ollama_service.OLLAMA_INSTALLER_URL,
    oeffnen_fn: Callable[..., Any] = urllib.request.urlopen,
    abbrechen_fn: Callable[[], bool] = lambda: False,
    log: LogFn | None = None,
    windows_fn: Callable[..., Any] = netz.herunterladen_mit_windows,
) -> Path:
    """Laedt ``OllamaSetup.exe`` nach ``ziel_ordner`` und liefert den Pfad. Scheitert nur Pythons Zertifikatspruefung
    (``utils/netz.py``), laedt Windows' eigene Pruefung die Datei; Groesse, Adresse und Signatur gelten dann genauso."""
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
        if not netz.ist_zertifikatsfehler(fehler):
            raise OllamaEinrichtungFehler(
                f"Der Ollama-Installer konnte nicht geladen werden ({fehler}). Bitte die Internetverbindung prüfen."
            ) from fehler
        gesamt = _lade_mit_windows(url, teil, fehler, windows_fn, pruefsumme, abbrechen_fn, melde)
    _umbenennen_mit_wiederholung(teil, ziel)
    if log is not None:
        log(f"Ollama-Installer geladen ({gesamt / 1024**2:.0f} MB, SHA-256 {pruefsumme.hexdigest()}).")
    return ziel


# --------------------------------------------------------------------------
# Echtheit pruefen
# --------------------------------------------------------------------------
# Rueckgabewerte von WinVerifyTrust, benannt wie 'Get-AuthenticodeSignature' sie meldet. Alles andere erscheint
# als Fehlercode -- und gilt genauso als ungueltig.
_WINTRUST_STATUS = {
    0x00000000: "Valid",
    0x800B0100: "NotSigned",  # TRUST_E_NOSIGNATURE
    0x80096010: "HashMismatch",  # TRUST_E_BAD_DIGEST: Datei nach dem Signieren veraendert
    0x800B0109: "NotTrusted",  # CERT_E_UNTRUSTEDROOT
    0x800B0111: "NotTrusted",  # TRUST_E_EXPLICIT_DISTRUST
}


def _lies_signatur(pfad: Path) -> tuple[str, str]:
    """(Status, Unterzeichner) der eingebetteten Authenticode-Signatur -- direkt ueber ``WinVerifyTrust`` aus
    ``wintrust.dll``, also dieselbe Pruefung, die ``Get-AuthenticodeSignature`` intern aufruft.

    Frueher lief das ueber Windows PowerShell 5.1 in einem eigenen Prozess mit 60 s Zeitlimit. Auf langsameren
    Laptops lief es in dieses Limit (die Pruefung liest den ganzen, ~1,7 GB grossen Installer), und wo eine
    Firmenrichtlinie PowerShell sperrt (AppLocker, WDAC), war sie gar nicht moeglich -- beides Mal wurde Ollama
    nicht installiert. ``wintrust.dll`` gehoert zu jedem Windows und laeuft hier im eigenen Prozess; gemessen
    1,3 s statt 7,7 s fuer den Installer von Ollama 0.40 (13.11.2026). Ein Zeitlimit braucht es damit nicht.

    Keine Sperrlistenabfrage (``WTD_REVOKE_NONE``, wie ``Get-AuthenticodeSignature``): Sie kann hinter einem
    Firmenproxy haengen. Wirft ``OSError``, wenn die Pruefung selbst nicht moeglich ist."""
    if sys.platform != "win32":
        raise OSError("Die Signaturprüfung gibt es nur unter Windows.")
    import ctypes
    import uuid
    from ctypes import wintypes

    class _Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class _DateiInfo(ctypes.Structure):  # WINTRUST_FILE_INFO
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE),
            ("pgKnownSubject", ctypes.c_void_p),
        ]

    class _Daten(ctypes.Structure):  # WINTRUST_DATA
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pPolicyCallbackData", ctypes.c_void_p),
            ("pSIPClientData", ctypes.c_void_p),
            ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD),
            ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(_DateiInfo)),
            ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE),
            ("pwszURLReference", wintypes.LPWSTR),
            ("dwProvFlags", wintypes.DWORD),
            ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", ctypes.c_void_p),
        ]

    class _AnbieterZertifikat(ctypes.Structure):  # Anfang von CRYPT_PROVIDER_CERT
        _fields_ = [("cbStruct", wintypes.DWORD), ("pCert", ctypes.c_void_p)]

    wintrust = ctypes.WinDLL("wintrust")
    crypt32 = ctypes.WinDLL("crypt32")
    pruefen = wintrust.WinVerifyTrust
    pruefen.argtypes = [wintypes.HWND, ctypes.POINTER(_Guid), ctypes.POINTER(_Daten)]
    pruefen.restype = wintypes.LONG
    anbieter = wintrust.WTHelperProvDataFromStateData
    anbieter.argtypes = [wintypes.HANDLE]
    anbieter.restype = ctypes.c_void_p
    unterzeichner_fn = wintrust.WTHelperGetProvSignerFromChain
    unterzeichner_fn.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    unterzeichner_fn.restype = ctypes.c_void_p
    zertifikat_fn = wintrust.WTHelperGetProvCertFromChain
    zertifikat_fn.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    zertifikat_fn.restype = ctypes.c_void_p
    name_fn = crypt32.CertGetNameStringW
    name_fn.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
    name_fn.restype = wintypes.DWORD

    # WINTRUST_ACTION_GENERIC_VERIFY_V2: die Authenticode-Pruefung
    kennung = uuid.UUID("00AAC56B-CD44-11d0-8CC2-00C04FC295EE")
    aktion = _Guid(kennung.fields[0], kennung.fields[1], kennung.fields[2])
    aktion.Data4[:] = list(kennung.bytes[8:])
    datei = _DateiInfo(ctypes.sizeof(_DateiInfo), str(pfad), None, None)
    daten = _Daten()
    daten.cbStruct = ctypes.sizeof(_Daten)
    daten.dwUIChoice = 2  # WTD_UI_NONE
    daten.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
    daten.dwUnionChoice = 1  # WTD_CHOICE_FILE
    daten.pFile = ctypes.pointer(datei)
    daten.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    code = pruefen(None, ctypes.byref(aktion), ctypes.byref(daten)) & 0xFFFFFFFF
    unterzeichner = ""
    try:
        zeiger = anbieter(daten.hWVTStateData)
        zeiger = unterzeichner_fn(zeiger, 0, False, 0) if zeiger else None
        zeiger = zertifikat_fn(zeiger, 0) if zeiger else None
        if zeiger:
            zertifikat = _AnbieterZertifikat.from_address(zeiger).pCert
            # CERT_X500_NAME_STR | CERT_NAME_STR_REVERSE_FLAG: "CN=..., O=..., C=..." wie bei PowerShell
            art = wintypes.DWORD(3 | 0x02000000)
            puffer = ctypes.create_unicode_buffer(2048)
            name_fn(zertifikat, 2, 0, ctypes.byref(art), puffer, len(puffer))  # CERT_NAME_RDN_TYPE
            unterzeichner = puffer.value
    finally:
        daten.dwStateAction = 2  # WTD_STATEACTION_CLOSE
        pruefen(None, ctypes.byref(aktion), ctypes.byref(daten))
    return _WINTRUST_STATUS.get(code, f"Fehler 0x{code:08X}"), unterzeichner


def _ist_von_ollama(unterzeichner: str) -> bool:
    """Steht im Namen des Zertifikats genau die Organisation ``O=Ollama Inc.``? Ein blosser Textvergleich
    liesse auch ``O=Ollama Inc.x`` oder ein ``CN="..., O=Ollama Inc."`` gelten. Angaben in Anfuehrungszeichen
    (koennen Kommas enthalten) zaehlen deshalb nicht als eigenes Feld."""
    ohne_zitate = re.sub(r'"[^"]*"', '""', unterzeichner)
    return any(feld.strip() == SIGNIERER for feld in ohne_zitate.split(","))


def pruefe_signatur(
    pfad: Path, *, lies_fn: Callable[[Path], tuple[str, str]] = _lies_signatur
) -> SignaturErgebnis:
    """Prueft die Authenticode-Signatur (``_lies_signatur``). Im Zweifel NICHT ok:
    Laesst sich die Signatur nicht lesen, wird der Installer nicht ausgefuehrt
    ("fail closed").

    Warum die Signatur und keine feste Pruefsumme: Der Installer aendert sich mit
    jeder Ollama-Fassung. Die Signatur bindet die Datei ueber eine
    Zertifizierungsstelle an den Hersteller -- das ist die aussagekraeftige Pruefung."""
    selbst = "Bitte Ollama selbst von ollama.com installieren."
    try:
        status, unterzeichner = lies_fn(pfad)
    except (OSError, AttributeError, ValueError) as fehler:  # AttributeError: Funktion fehlt in wintrust.dll
        return SignaturErgebnis(False, "", f"Die Echtheit des Ollama-Installers ließ sich nicht prüfen ({fehler}). {selbst}")
    if status != "Valid":
        return SignaturErgebnis(
            False, unterzeichner, f"Der Ollama-Installer ist nicht gültig signiert (Status: {status or 'unbekannt'}). {selbst}"
        )
    if not _ist_von_ollama(unterzeichner):
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
    """Startet den Ollama-Dienst (``ollama serve``), losgeloest von uns. Nur wenn es ``ollama.exe`` nicht gibt, die
    Ollama-Anwendung: Sie beendete sich bei Tests mitten in einem Modell-Download selbst (Ollama 0.40.4), der reine
    Dienst nicht -- und fuer das Aufnahmegeraet muss der Dienst laufen, ohne dass jemand ein Fenster bedient."""
    if ordner is None:
        return
    dienst = ordner / "ollama.exe"
    if dienst.is_file():
        subprocess.Popen(
            [str(dienst), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_LOSGELOEST | _KEIN_FENSTER | _NEUE_GRUPPE,
            close_fds=True,
        )
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
