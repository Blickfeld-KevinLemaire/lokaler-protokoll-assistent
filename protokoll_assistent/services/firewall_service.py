"""Windows-Firewall: den Empfang fuer die Aufnahmegeraete im Heimnetz freigeben.

Ohne Freigabe verwirft Windows die Anfragen der Geraete still (am Geraet laeuft
jede Verbindung in eine Zeitueberschreitung). Ob eine Freigabe fehlt, laesst sich
von diesem Rechner aus nicht verlaesslich abfragen -- Port-Regeln sind ohne
Administratorrechte nicht lesbar, und die alte Abfrage ``HNetCfg.FwMgr.IsPortAllowed``
meldet immer "erlaubt". Verlaesslich ist nur, ob sich das Geraet meldet; die
Oberflaeche bietet diese Freigabe deshalb an, wenn ein eingerichtetes Geraet
ausbleibt.

Die Regel gilt fuer den Port (nicht fuer ein Programm: im Quelltextbetrieb laeuft
der Dienst unter wechselnden Python-Interpretern) und nur fuer private und
Domaenen-Netze, nie fuer oeffentliche. Angelegt wird sie in einer eigenen
PowerShell mit Administratorrechten; Windows fragt dafuer nach (UAC). Der
Installer legt bewusst keine Regel an.
"""

from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable
from typing import Any

ABGEBROCHEN_EXIT_CODE = 1223  # ERROR_CANCELLED: die Rueckfrage von Windows wurde abgelehnt
WARTEN_SEKUNDEN = 180


class FirewallFehler(RuntimeError):
    pass


def regel_name(port: int) -> str:
    return f"VERMERK Empfang (Port {port})"


def _kodiert(befehl: str) -> str:
    """Fuer ``-EncodedCommand``: UTF-16LE, Base64 -- keine Anfuehrungszeichen zu verschachteln."""
    return base64.b64encode(befehl.encode("utf-16-le")).decode("ascii")


def freigabe_befehl(port: int) -> list[str]:
    """Die Befehlszeile (ohne Shell): eine normale PowerShell startet eine zweite mit Administratorrechten,
    wartet auf sie und gibt deren Exit-Code weiter (1223, wenn die Rueckfrage abgelehnt wurde)."""
    if not 1 <= int(port) <= 65535:
        raise FirewallFehler(f"Ungültiger Port: {port}")
    name = regel_name(int(port))
    innen = (
        f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName '{name}' -Direction Inbound -Protocol TCP -LocalPort {int(port)} "
        "-Action Allow -Profile Private,Domain -ErrorAction Stop | Out-Null"
    )
    aussen = (
        "try { $p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{_kodiert(innen)}'; exit $p.ExitCode }} "
        f"catch {{ exit {ABGEBROCHEN_EXIT_CODE} }}"
    )
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", _kodiert(aussen)]


def empfang_freigeben(port: int, ausfuehren: Callable[..., Any] = subprocess.run) -> None:
    """Legt die Regel an (oder ersetzt eine gleichnamige). Wirft ``FirewallFehler`` mit einer Meldung fuer den
    Anwender, wenn es nicht geklappt hat."""
    try:
        ergebnis = ausfuehren(
            freigabe_befehl(port),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=WARTEN_SEKUNDEN,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise FirewallFehler("Die Freigabe ließ sich nicht anlegen.") from fehler
    if ergebnis.returncode == ABGEBROCHEN_EXIT_CODE:
        raise FirewallFehler("Die Freigabe wurde nicht erlaubt.")
    if ergebnis.returncode != 0:
        raise FirewallFehler("Die Freigabe ließ sich nicht anlegen.")
