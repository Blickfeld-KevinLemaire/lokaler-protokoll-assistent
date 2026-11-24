"""Prueft das Inno-Setup-Skript gegen die anderen Teile des Builds (es selbst laeuft nur im Release-Build)."""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJEKT = Path(__file__).resolve().parents[2]
SKRIPT = PROJEKT / "installer" / "protokoll-assistent.iss"
TAURI_KONFIGURATION = PROJEKT / "oberflaeche" / "src-tauri" / "tauri.conf.json"


def _abschnitt(text: str, name: str) -> list[str]:
    """Die Zeilen eines Abschnitts (``[UninstallDelete]`` ...), ohne Kommentare."""
    zeilen: list[str] = []
    drin = False
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile.startswith("["):
            drin = zeile == f"[{name}]"
            continue
        if drin and zeile and not zeile.startswith(";"):
            zeilen.append(zeile)
    return zeilen


def test_deinstallation_entfernt_die_protokolle_des_fensters():
    # Die Hinweise nach der Installation sagen, die Protokolldateien wuerden mit entfernt. Die des Fensters (Tauri)
    # liegen aber unter %LOCALAPPDATA%\<identifier> und blieben bisher liegen.
    identifier = json.loads(TAURI_KONFIGURATION.read_text(encoding="utf-8"))["identifier"]
    eintraege = _abschnitt(SKRIPT.read_text(encoding="utf-8"), "UninstallDelete")
    namen = [m.group(1) for e in eintraege if (m := re.search(r'Name:\s*"([^"]+)"', e))]
    assert f"{{localappdata}}\\{identifier}" in namen
