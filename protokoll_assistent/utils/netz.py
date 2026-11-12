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
   nicht pruefen konnte (Proxy sperrt sie), folgt ein Versuch ohne diese eine Pruefung --
   die Kette bis zur Wurzel wird weiter geprueft.
3. ``herunterladen_mit_windows`` mit Windows PowerShell (.NET): benutzt die
   Proxy-Einstellungen des Benutzers samt Anmeldung am Proxy.

Die Pruefung bleibt in jeder Stufe an: Es wird nie ein Zertifikat ungeprueft
akzeptiert. Nur fuer feste Herstelleradressen (FFmpeg, Ollama) gedacht.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import sys
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


def _mit_curl(url: str, ziel: Path, timeout: int, ausfuehren_fn: Callable[..., Any]) -> str:
    curl = _curl()
    if curl is None:
        raise OSError("curl.exe fehlt")
    proxy = _proxy_fuer(url)
    letzter = ""
    for ohne_sperrliste in (False, True):
        befehl = [
            curl, "--location", "--fail", "--silent", "--show-error",
            "--proto", "=https", "--proto-redir", "=https",
            "--max-time", str(timeout), "--output", str(ziel),
            "--write-out", "%{url_effective}",
        ]  # fmt: skip
        if proxy:
            befehl += ["--proxy", proxy]
        if ohne_sperrliste:
            befehl.append("--ssl-no-revoke")
        befehl.append(url)
        ergebnis = ausfuehren_fn(
            befehl, capture_output=True, text=True, timeout=timeout + 30, check=False, creationflags=KEIN_FENSTER
        )
        if ergebnis.returncode == 0:
            return str(ergebnis.stdout or "").strip() or url
        ziel.unlink(missing_ok=True)
        letzter = (ergebnis.stderr or "").strip() or f"Exit-Code {ergebnis.returncode}"
        if not any(wort in letzter for wort in _SPERRLISTE):
            break  # nur diese eine Pruefung lohnt einen zweiten Versuch
    raise OSError(letzter)


# Adresse und Ziel kommen ueber Umgebungsvariablen, nie in den Befehlstext (siehe
# 'ollama_einrichtung_service._PFAD_VARIABLE': Leerzeichen und ';' im Benutzerordner).
_POWERSHELL_SKRIPT = (
    "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; "
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
    "[Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials; "
    "$r = Invoke-WebRequest -UseBasicParsing -Uri $env:VERMERK_URL -OutFile $env:VERMERK_ZIEL -PassThru; "
    "[Console]::Out.Write($r.BaseResponse.ResponseUri.AbsoluteUri)"
)


def _mit_powershell(url: str, ziel: Path, timeout: int, ausfuehren_fn: Callable[..., Any]) -> str:
    powershell = _powershell()
    if powershell is None:
        raise OSError("PowerShell fehlt")
    # Ohne 'PSModulePath': aus PowerShell 7 gestartet, zeigt die Variable auf dessen Module, die 5.1 nicht laedt.
    umgebung = {name: wert for name, wert in os.environ.items() if name.upper() != "PSMODULEPATH"}
    umgebung["VERMERK_URL"], umgebung["VERMERK_ZIEL"] = url, str(ziel)
    ergebnis = ausfuehren_fn(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_SKRIPT],
        capture_output=True,
        text=True,
        timeout=timeout + 30,
        check=False,
        env=umgebung,
        creationflags=KEIN_FENSTER,
    )
    if ergebnis.returncode != 0:
        ziel.unlink(missing_ok=True)
        raise OSError((ergebnis.stderr or "").strip() or f"Exit-Code {ergebnis.returncode}")
    return str(ergebnis.stdout or "").strip() or url


def herunterladen_mit_windows(
    url: str,
    ziel: Path,
    timeout: int = 300,
    *,
    ausfuehren_fn: Callable[..., Any] = subprocess.run,
) -> str:
    """Laedt ``url`` mit Windows' eigenen Programmen nach ``ziel`` (erst ``curl.exe``, dann PowerShell) und
    liefert die Adresse nach allen Weiterleitungen, damit der Aufrufer sie pruefen kann. Das Ergebnis ist
    immer HTTPS. ``OSError`` bei jedem Misserfolg, mit den Meldungen beider Wege."""
    if sys.platform != "win32":
        raise OSError("Windows-eigener Download nicht verfuegbar (kein Windows).")
    if urllib.parse.urlsplit(url).scheme != "https":
        raise OSError("Nur HTTPS-Adressen werden geladen.")
    fehler: list[str] = []
    for name, weg in (("curl", _mit_curl), ("PowerShell", _mit_powershell)):
        try:
            endgueltig = weg(url, ziel, timeout, ausfuehren_fn)
        except (OSError, subprocess.SubprocessError) as grund:
            ziel.unlink(missing_ok=True)
            fehler.append(f"{name}: {grund}")
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
