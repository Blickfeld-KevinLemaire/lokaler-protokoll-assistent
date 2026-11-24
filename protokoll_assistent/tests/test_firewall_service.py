"""Freigabe in der Windows-Firewall -- nur die Befehlszeile und die Exit-Codes, nichts wird ausgefuehrt."""

from __future__ import annotations

import base64
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from protokoll_assistent.services import firewall_service as fw


def _entschluesselt(teil: str) -> str:
    return base64.b64decode(teil).decode("utf-16-le")


def test_befehl_ohne_shell_mit_rueckfrage_und_nur_privaten_netzen() -> None:
    befehl = fw.freigabe_befehl(8765)
    assert befehl[0] == "powershell.exe" and befehl[-2] == "-EncodedCommand"
    aussen = _entschluesselt(befehl[-1])
    assert "-Verb RunAs" in aussen and "-Wait" in aussen and f"exit {fw.ABGEBROCHEN_EXIT_CODE}" in aussen
    innen = _entschluesselt(aussen.split("'-EncodedCommand','")[1].split("'")[0])
    assert "-LocalPort 8765" in innen and "-Profile Private,Domain" in innen and "Public" not in innen
    assert "Remove-NetFirewallRule -DisplayName 'VERMERK Empfang (Port 8765)'" in innen


@pytest.mark.parametrize("port", [0, 70000])
def test_ungueltiger_port(port: int) -> None:
    with pytest.raises(fw.FirewallFehler):
        fw.freigabe_befehl(port)


@pytest.mark.parametrize(
    ("ergebnis", "meldung"),
    [
        (0, None),
        (fw.ABGEBROCHEN_EXIT_CODE, "nicht erlaubt"),
        (1, "nicht anlegen"),
        (OSError("fehlt"), "nicht anlegen"),
        (subprocess.TimeoutExpired("powershell", 1), "nicht anlegen"),
    ],
)
def test_exit_codes(ergebnis: Any, meldung: str | None) -> None:
    aufrufe: list[dict[str, Any]] = []

    def ausfuehren(befehl: list[str], **kw: Any) -> SimpleNamespace:
        aufrufe.append(kw)
        if isinstance(ergebnis, BaseException):
            raise ergebnis
        return SimpleNamespace(returncode=ergebnis, stdout="", stderr="")

    if meldung is None:
        fw.empfang_freigeben(8765, ausfuehren)
    else:
        with pytest.raises(fw.FirewallFehler, match=meldung):
            fw.empfang_freigeben(8765, ausfuehren)
    assert aufrufe[0]["encoding"] == "utf-8" and aufrufe[0]["errors"] == "replace" and "shell" not in aufrufe[0]
