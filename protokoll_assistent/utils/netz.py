"""Netzzugriff, der auch hinter Firmenproxys und Zertifikatspruefungen funktioniert.

Das Problem: Pythons ``ssl`` kennt unter Windows nur den Zertifikatsspeicher des
Rechners (``ROOT``/``CA``) und prueft mit OpenSSL. Fehlt dort das
Wurzelzertifikat -- ein Rechner, der nie ueber die Windows-Aktualisierung neue
Wurzeln geholt hat, oder ein Firmennetz, dessen Zertifikatspruefung ihr eigenes
Zertifikat im Benutzer- oder Richtlinienspeicher ablegt --, endet jeder Download
mit ``CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate``,
obwohl derselbe Rechner die Seite im Browser oeffnet.

Dagegen gibt es drei Stufen, jede nur, wenn die vorige an der
**Zertifikatspruefung** scheitert (andere Fehler -- kein Netz, 404 -- bleiben, was
sie sind):

1. ``systemzertifikate_nutzen``: Beim Start prueft Python (und mit ihm ``urllib``,
   ``requests``, ``httpx``, Hugging Face) ueber Windows' eigene Zertifikatspruefung
   (Paket ``truststore``): alle Speicher, fehlende Wurzeln werden nachgeladen,
   Zertifikate des Firmennetzes gelten, wenn der Browser ihnen traut.
2. ``herunterladen_mit_windows`` mit ``curl.exe`` (Schannel, gehoert zu Windows):
   dasselbe fuer Rechner, auf denen ``truststore`` fehlt (aeltere Einrichtung).
   Der System-Proxy wird mitgegeben; meldet Schannel nur, dass es die Sperrliste
   nicht pruefen konnte (Proxy sperrt sie), folgt ein Versuch, der genau das
   hinnimmt (``--ssl-revoke-best-effort``) -- ein tatsaechlich gesperrtes Zertifikat
   und die Kette bis zur Wurzel werden weiter geprueft.
3. ``herunterladen_mit_windows`` mit Windows PowerShell (.NET): benutzt die
   Proxy-Einstellungen des Benutzers samt Anmeldung am Proxy.

Die Zeitgrenze ist in den Stufen 2 und 3 eine Grenze fuer den STILLSTAND, nicht
fuer die ganze Uebertragung: Der Ollama-Installer hat knapp 2 GB, und gerade
hinter einem pruefenden Firmenproxy ist die Leitung langsam. Beide Stufen lassen
sich abbrechen und melden, wie viel schon geladen ist.

Die Pruefung bleibt in jeder Stufe an: Es wird nie ein Zertifikat ungeprueft
akzeptiert. Nur fuer feste Herstelleradressen (FFmpeg, Ollama) gedacht.
"""

from __future__ import annotations

import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protokoll_assistent.utils.prozess import KEIN_FENSTER


# --------------------------------------------------------------------------
# Stufe 1: Windows' Zertifikatspruefung fuer den ganzen Prozess
# --------------------------------------------------------------------------
def systemzertifikate_nutzen() -> bool:
    """Laesst Python ueber die Zertifikatspruefung des Betriebssystems pruefen. ``True``, wenn aktiv.
    Ohne das Paket (aeltere Einrichtung) oder unter Python < 3.10 bleibt alles beim Alten."""
    try:
        import truststore  # type: ignore[import-not-found,unused-ignore]

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001 -- fehlt das Paket oder geht es nicht, laeuft die Anwendung wie bisher
        return False
    return True


def ist_zertifikatsfehler(fehler: BaseException) -> bool:
    """Ist das ein Fehler der Zertifikatspruefung (auch eingepackt in ``URLError``)?"""
    if isinstance(fehler, ssl.SSLCertVerificationError):
        return True
    grund = fehler.reason if isinstance(fehler, urllib.error.URLError) else None
    return isinstance(grund, ssl.SSLCertVerificationError)


# --------------------------------------------------------------------------
# Stufen 2 und 3: Windows' eigene Programme
# --------------------------------------------------------------------------
def _system32(*teile: str) -> Path | None:
    wurzel = os.environ.get("SystemRoot")
    if not wurzel:
        return None
    pfad = Path(wurzel, "System32", *teile)
    return pfad if pfad.is_file() else None


def _curl() -> str | None:
    pfad = _system32("curl.exe")
    return str(pfad) if pfad else shutil.which("curl.exe")


def _powershell() -> str | None:
    pfad = _system32("WindowsPowerShell", "v1.0", "powershell.exe")
    return str(pfad) if pfad else shutil.which("powershell.exe")


def _proxy_fuer(url: str) -> str | None:
    """Der in Windows (Internetoptionen) oder per Umgebungsvariable eingestellte Proxy fuer ``url`` --
    ``curl.exe`` liest die Windows-Einstellung selbst nicht."""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
        if urllib.request.proxy_bypass(host):
            return None
        return urllib.request.getproxies().get("https")
    except Exception:  # noqa: BLE001 -- ein unlesbarer Proxy darf den Download nicht verhindern
        return None


_SPERRLISTE = ("CRYPT_E_NO_REVOCATION_CHECK", "CRYPT_E_REVOCATION_OFFLINE", "revocation")

# Obergrenze fuer einen einzelnen Hilfsprozess. Die eigentliche Zeitgrenze ist der
# Stillstand (siehe Modul-Docstring); das hier faengt nur einen haengenden Prozess ab.
HOECHSTDAUER_SEKUNDEN = 6 * 3600
_TAKT_SEKUNDEN = 0.5


class Abgebrochen(OSError):
    """Der Anwender hat den Download abgebrochen."""


def _ohne_zugangsdaten(text: str) -> str:
    """Name und Kennwort eines Proxys ('http://name:kennwort@proxy') gehoeren in keine Meldung und kein Protokoll."""
    return re.sub(r"(?<=://)[^/@\s]+@", "***@", text)


def _ausfuehren(
    befehl: list[str],
    *,
    encoding: str | None = None,
    env: dict[str, str] | None = None,
    abbrechen_fn: Callable[[], bool] | None = None,
    takt_fn: Callable[[], None] | None = None,
    hoechstdauer: float = HOECHSTDAUER_SEKUNDEN,
) -> subprocess.CompletedProcess[str]:
    """Wie ``subprocess.run(capture_output=True, text=True)``, aber abbrechbar: Alle halbe Sekunde wird
    ``abbrechen_fn`` gefragt und ``takt_fn`` aufgerufen (Fortschritt). ``errors="replace"``, weil die
    Hilfsprogramme Fehlertexte in der Sprache und Codepage des Rechners schreiben -- ein nicht lesbares
    Zeichen darf die Meldung nicht kosten (ein 'ue' aus Codepage 850 gibt es in cp1252 nicht)."""
    with subprocess.Popen(
        befehl,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding=encoding,
        errors="replace",
        env=env,
        creationflags=KEIN_FENSTER,
    ) as prozess:
        ende = time.monotonic() + hoechstdauer
        while True:
            try:
                ausgabe, fehlertext = prozess.communicate(timeout=_TAKT_SEKUNDEN)
                break
            except subprocess.TimeoutExpired:
                abbruch = abbrechen_fn is not None and abbrechen_fn()
                if abbruch or time.monotonic() > ende:
                    prozess.kill()
                    prozess.communicate()
                    if abbruch:
                        raise Abgebrochen("Der Download wurde abgebrochen.") from None
                    # Ohne die Befehlszeile: Darin kann der Proxy samt Kennwort stehen.
                    raise OSError("Zeitüberschreitung") from None
                if takt_fn is not None:
                    takt_fn()
    return subprocess.CompletedProcess(befehl, prozess.returncode, ausgabe, fehlertext)


def _mit_curl(url: str, ziel: Path, timeout: int, ausfuehren_fn: Callable[..., Any], **lauf: Any) -> str:
    curl = _curl()
    if curl is None:
        raise OSError("curl.exe fehlt")
    proxy = _proxy_fuer(url)
    letzter = ""
    for sperrliste_nachsichtig in (False, True):
        # Kein '--max-time': Das begrenzte die GANZE Uebertragung (1,9 GB in 300 s verlangen 50 Mbit/s).
        # Abgebrochen wird, wenn 'timeout' Sekunden lang praktisch nichts mehr kommt.
        befehl = [
            curl, "--location", "--fail", "--silent", "--show-error",
            "--proto", "=https", "--proto-redir", "=https",
            "--connect-timeout", "60", "--speed-limit", "1", "--speed-time", str(timeout),
            "--output", str(ziel), "--write-out", "%{url_effective}",
        ]  # fmt: skip
        if proxy:
            befehl += ["--proxy", proxy]
        if sperrliste_nachsichtig:
            # Nimmt nur hin, dass die Sperrliste nicht erreichbar ist. Ein gesperrtes Zertifikat
            # bleibt ein Fehler ('--ssl-no-revoke' schaltete die Pruefung dagegen ganz ab).
            befehl.append("--ssl-revoke-best-effort")
        befehl.append(url)
        # Ohne 'encoding': curl schreibt Windows-Meldungen in der ANSI-Codepage, die Python hier auch annimmt.
        ergebnis = ausfuehren_fn(befehl, **lauf)
        if ergebnis.returncode == 0:
            return str(ergebnis.stdout or "").strip() or url
        ziel.unlink(missing_ok=True)
        letzter = (ergebnis.stderr or "").strip() or f"Exit-Code {ergebnis.returncode}"
        if not any(wort in letzter for wort in _SPERRLISTE):
            break  # nur diese eine Pruefung lohnt einen zweiten Versuch
    raise OSError(letzter)


# Adresse und Ziel kommen ueber Umgebungsvariablen, nie in den Befehlstext (siehe
# 'ollama_einrichtung_service._PFAD_VARIABLE': Leerzeichen und ';' im Benutzerordner).
#
# Kein 'Invoke-WebRequest -PassThru': Windows PowerShell 5.1 haelt dabei die ganze Antwort im
# Arbeitsspeicher -- bei knapp 2 GB zu viel. Der Datenstrom wird direkt in die Datei kopiert.
# Die Ausgabe ist UTF-8 (wie in 'ollama_einrichtung_service._SIGNATUR_SKRIPT'): Ohne das schreibt
# 5.1 in der OEM-Codepage (850), und die deutschen Fehlertexte kamen in Python nicht an.
_POWERSHELL_SKRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
    "[Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials; "
    "$anfrage = [Net.WebRequest]::Create($env:VERMERK_URL); "
    "$anfrage.Timeout = [int]$env:VERMERK_STILLSTAND_MS; "
    "$anfrage.ReadWriteTimeout = [int]$env:VERMERK_STILLSTAND_MS; "
    "$antwort = $anfrage.GetResponse(); "
    "try { "
    "$quelle = $antwort.GetResponseStream(); "
    "$datei = [IO.File]::Create($env:VERMERK_ZIEL); "
    "try { $quelle.CopyTo($datei) } finally { $datei.Dispose() }; "
    "[Console]::Out.Write($antwort.ResponseUri.AbsoluteUri) "
    "} finally { $antwort.Dispose() }"
)


def _mit_powershell(url: str, ziel: Path, timeout: int, ausfuehren_fn: Callable[..., Any], **lauf: Any) -> str:
    powershell = _powershell()
    if powershell is None:
        raise OSError("PowerShell fehlt")
    # Ohne 'PSModulePath': aus PowerShell 7 gestartet, zeigt die Variable auf dessen Module, die 5.1 nicht laedt.
    umgebung = {name: wert for name, wert in os.environ.items() if name.upper() != "PSMODULEPATH"}
    umgebung["VERMERK_URL"], umgebung["VERMERK_ZIEL"] = url, str(ziel)
    umgebung["VERMERK_STILLSTAND_MS"] = str(timeout * 1000)
    ergebnis = ausfuehren_fn(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_SKRIPT],
        encoding="utf-8",
        env=umgebung,
        **lauf,
    )
    if ergebnis.returncode != 0:
        ziel.unlink(missing_ok=True)
        # Nur die Meldung selbst, ohne die Angabe der Skriptstelle ("In Zeile:1 Zeichen:432 ...").
        meldung = re.split(r"\n\s*(?:In Zeile|At line)\b", (ergebnis.stderr or "").strip())[0]
        raise OSError(" ".join(meldung.split()) or f"Exit-Code {ergebnis.returncode}")
    return str(ergebnis.stdout or "").strip() or url


def herunterladen_mit_windows(
    url: str,
    ziel: Path,
    timeout: int = 300,
    *,
    ausfuehren_fn: Callable[..., Any] = _ausfuehren,
    abbrechen_fn: Callable[[], bool] | None = None,
    fortschritt_fn: Callable[[int], None] | None = None,
) -> str:
    """Laedt ``url`` mit Windows' eigenen Programmen nach ``ziel`` (erst ``curl.exe``, dann PowerShell) und
    liefert die Adresse nach allen Weiterleitungen, damit der Aufrufer sie pruefen kann. Das Ergebnis ist
    immer HTTPS. ``OSError`` bei jedem Misserfolg, mit den Meldungen beider Wege; ``Abgebrochen`` (auch ein
    ``OSError``), wenn ``abbrechen_fn`` waehrenddessen wahr wird.

    ``timeout`` ist die Grenze fuer den Stillstand in Sekunden, nicht fuer die ganze Uebertragung.
    ``fortschritt_fn`` bekommt alle halbe Sekunde die bisher geladenen Bytes."""
    if sys.platform != "win32":
        raise OSError("Windows-eigener Download nicht verfuegbar (kein Windows).")
    if urllib.parse.urlsplit(url).scheme != "https":
        raise OSError("Nur HTTPS-Adressen werden geladen.")

    def takt() -> None:
        if fortschritt_fn is None:
            return
        try:
            fortschritt_fn(ziel.stat().st_size)
        except OSError:
            pass  # noch nicht angelegt

    fehler: list[str] = []
    for name, weg in (("curl", _mit_curl), ("PowerShell", _mit_powershell)):
        try:
            endgueltig = weg(url, ziel, timeout, ausfuehren_fn, abbrechen_fn=abbrechen_fn, takt_fn=takt)
        except Abgebrochen:
            ziel.unlink(missing_ok=True)
            raise
        except subprocess.TimeoutExpired:
            # Nicht 'str(grund)': Die Meldung enthielte die ganze Befehlszeile samt Proxy-Kennwort.
            ziel.unlink(missing_ok=True)
            fehler.append(f"{name}: Zeitüberschreitung")
            continue
        except (OSError, subprocess.SubprocessError) as grund:
            ziel.unlink(missing_ok=True)
            fehler.append(f"{name}: {_ohne_zugangsdaten(str(grund))}")
            continue
        if urllib.parse.urlsplit(endgueltig).scheme != "https":
            ziel.unlink(missing_ok=True)
            raise OSError("Der Download wurde auf eine Adresse ohne HTTPS weitergeleitet.")
        return endgueltig
    raise OSError("Download ueber Windows fehlgeschlagen (" + "; ".join(fehler) + ").")


def lade_datei(
    url: str,
    ziel: Path,
    timeout: int = 300,
    *,
    oeffnen_fn: Callable[..., Any] = urllib.request.urlopen,
    windows_fn: Callable[..., Any] = herunterladen_mit_windows,
) -> None:
    """Laedt ``url`` nach ``ziel``. Scheitert nur die Zertifikatspruefung von Python, versucht es Windows' eigene."""
    try:
        with oeffnen_fn(url, timeout=timeout) as antwort, ziel.open("wb") as datei:
            shutil.copyfileobj(antwort, datei)
    except OSError as fehler:
        if not ist_zertifikatsfehler(fehler):
            raise
        ziel.unlink(missing_ok=True)
        try:
            windows_fn(url, ziel, timeout)
        except OSError as zweiter:
            raise OSError(f"{fehler} -- {zweiter}") from fehler
