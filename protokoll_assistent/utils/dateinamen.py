"""Dateinamen aus Angaben, die aus einer Datei stammen (z. B. ``quelldatei_stamm`` im Transkript).

Ein Transkript ist eine JSON-Datei; im Servermodus kann ein Nutzer sie selbst hochladen. Was darin als
Namensanfang steht, darf deshalb nie einen Ordner bestimmen: kein Trenner, kein Laufwerk, kein ``..``.
"""

from __future__ import annotations

import re

_UNZULAESSIG = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
STAMM_MAX = 120


def sicherer_stamm(text: object, ersatz: str = "aufnahme") -> str:
    """Nur ein Stueck Dateiname. Gewoehnliche Namen ("Besprechung 2026-11-24") bleiben unveraendert, damit
    vorhandene Dateien weiter gefunden und ueberschrieben werden."""
    stamm = _UNZULAESSIG.sub("_", str(text or "")).strip(" .")
    return stamm[:STAMM_MAX] or ersatz
