"""Wer sieht welche Ereignisse? (Servermodus mit mehreren Nutzern)

Grundsatz: Inhalte (Dateinamen, Vorschau, Live-Transkript, Ergebnisse) sieht
nur, wem sie gehoeren. Damit die gemeinsame Warteschlange verstaendlich bleibt,
sehen alle, *dass* vor ihnen etwas laeuft und wie weit es ist -- ohne Inhalt.
Admins sehen zusaetzlich den Zustand des Servers (Empfang, Ollama, Geraete-
status), aber auch sie keine fremden Inhalte ausser den Auftragstiteln.

In der Windows-Anwendung (ein Mensch) geht alles unveraendert durch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.auftraege import fuer_betrachter
from protokoll_assistent.api.kontext import Angemeldet, Dienste

NUR_ADMIN_QUELLEN = frozenset({"ollama", "netz"})


def auftrag_fuer(d: Dienste, wer: Angemeldet, daten: dict[str, Any]) -> dict[str, Any]:
    return fuer_betrachter(daten, wer.besitzer, alles_sehen=not d.mehrbenutzer or wer.admin)


def _eigenes_geraet(d: Dienste, wer: Angemeldet, geraet: str) -> bool:
    if d.automatik is None:
        return False
    besitzer = d.automatik.besitzer_von(geraet)
    return besitzer is not None and wer.besitzer is not None and besitzer.lower() == wer.besitzer.lower()


def _in_eigenen_ordnern(d: Dienste, wer: Angemeldet, pfad: str) -> bool:
    ziel = Path(pfad).resolve()
    for basis in (d.aufnahmeordner(wer), d.ausgabeordner(wer)):
        try:
            ziel.relative_to(basis.resolve())
        except ValueError:
            continue
        return True
    return False


def ereignis_fuer(d: Dienste, wer: Angemeldet, art: str, daten: dict[str, Any]) -> dict[str, Any] | None:
    """Die Fassung des Ereignisses fuer diesen Nutzer -- oder ``None``, wenn er es nicht bekommt."""
    if not d.mehrbenutzer:
        return daten
    if art == "auftrag":
        return auftrag_fuer(d, wer, daten)
    if art == "auftrag_meldung":
        auftrag = d.steuerung.auftraege.hole(str(daten.get("id", "")))
        if auftrag is None:
            return None
        eigen = auftrag.besitzer is not None and wer.besitzer is not None and auftrag.besitzer.lower() == wer.besitzer.lower()
        return daten if eigen else None
    if art == "live":
        return daten if _eigenes_geraet(d, wer, str(daten.get("geraet", ""))) else None
    if art == "geraet_status":
        return daten if wer.admin or _eigenes_geraet(d, wer, str(daten.get("geraet", ""))) else None
    if art == "empfang":
        return daten if wer.admin else None
    if art == "dateien":
        pfad = daten.get("pfad")
        return daten if not pfad or _in_eigenen_ordnern(d, wer, str(pfad)) else None
    if art == "hinweis":
        quelle = str(daten.get("quelle") or "")
        if quelle in NUR_ADMIN_QUELLEN:
            return daten if wer.admin else None
        if quelle and d.automatik is not None and d.automatik.besitzer_von(quelle) is not None:
            return daten if _eigenes_geraet(d, wer, quelle) or wer.admin else None
        return daten
    return daten
