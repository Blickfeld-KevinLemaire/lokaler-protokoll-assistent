"""Dauer einer Ogg-Opus-Datei, auch einer, die gerade noch waechst.

Die Aufnahmegeraete schicken ihre Aufnahme waehrend der Aufnahme Stueck fuer
Stueck an die Software (``GERAETE-SCHNITTSTELLE.md``); die Datei am PC ist bis
zum Abschluss unfertig und am Ende womoeglich mitten in einer Ogg-Seite
abgeschnitten. ``ffprobe`` schaetzt die Dauer so nur aus der Dateigroesse. Hier
wird sie genau gelesen: aus der Granulposition der letzten **vollstaendigen**
Seite (bei Opus zaehlt sie Abtastwerte bei 48 kHz, abzueglich der Vorlaufzeit
aus dem ``OpusHead``).

Nur Standardbibliothek, keine Abhaengigkeit von ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

_MUSTER = b"OggS"
_KOPF_MIN = 27  # feste Laenge des Seitenkopfes vor der Segmenttabelle
_OPUS_RATE = 48000
_STANDARD_VORLAUF = 312  # Abtastwerte; der Wert der libopus-Voreinstellung bei 16 kHz
_UNBEKANNT = 0xFFFFFFFFFFFFFFFF  # Granulposition -1: auf dieser Seite endet kein Paket
# So weit hinten im Dateiende wird nach vollstaendigen Seiten gesucht. Eine Seite
# der Geraete (ca. 1 s bei 24 kbit/s) hat gut 3 KB; mehrere Sekunden Luft genuegen.
_SUCHFENSTER = 256 * 1024


def _seite_lesen(daten: bytes, ab: int) -> tuple[int, int] | None:
    """``(Granulposition, Ende der Seite)`` fuer eine vollstaendige Seite ab ``ab``,
    sonst ``None`` (kein gueltiger Kopf oder Seite abgeschnitten)."""
    if daten[ab : ab + 4] != _MUSTER or len(daten) < ab + _KOPF_MIN:
        return None
    if daten[ab + 4] != 0:  # Version des Ogg-Formats
        return None
    segmente = daten[ab + 26]
    kopf_ende = ab + _KOPF_MIN + segmente
    if len(daten) < kopf_ende:
        return None
    nutzlast = sum(daten[ab + _KOPF_MIN : kopf_ende])
    ende = kopf_ende + nutzlast
    if len(daten) < ende:
        return None
    return int.from_bytes(daten[ab + 6 : ab + 14], "little"), ende


def _letzte_granulposition(daten: bytes) -> int | None:
    """Granulposition der letzten vollstaendigen Seite mit einem abgeschlossenen Paket."""
    ab = daten.find(_MUSTER)
    while ab != -1:
        # Von diesem Kandidaten aus alle Seiten der Reihe nach lesen. Ein
        # zufaelliges "OggS" in der Nutzlast scheitert daran, dass danach keine
        # gueltige Seite folgt.
        letzte: int | None = None
        stelle = ab
        gueltig = True
        while stelle < len(daten):
            seite = _seite_lesen(daten, stelle)
            if seite is None:
                # Abgeschnitten (normal am Ende) oder kein Kopf (falscher Kandidat).
                gueltig = daten[stelle : stelle + 4] == _MUSTER or stelle + 4 > len(daten)
                break
            granul, stelle = seite
            if granul != _UNBEKANNT:
                letzte = granul
        if gueltig and letzte is not None:
            return letzte
        ab = daten.find(_MUSTER, ab + 1)
    return None


def _vorlauf(kopf: bytes) -> int:
    stelle = kopf.find(b"OpusHead")
    if stelle == -1 or len(kopf) < stelle + 12:
        return _STANDARD_VORLAUF
    return int.from_bytes(kopf[stelle + 10 : stelle + 12], "little")


def opus_dauer_sekunden(pfad: Path) -> float | None:
    """Dauer der bisher vollstaendig vorliegenden Aufnahme in Sekunden.

    ``None``, wenn die Datei fehlt, kein Ogg-Opus ist oder noch keine Seite mit
    abgeschlossenem Paket enthalten kann (ganz am Anfang)."""
    try:
        with pfad.open("rb") as datei:
            kopf = datei.read(512)
            if not kopf.startswith(_MUSTER) or b"OpusHead" not in kopf:
                return None
            datei.seek(0, 2)
            groesse = datei.tell()
            datei.seek(max(0, groesse - _SUCHFENSTER))
            ende = datei.read()
    except OSError:
        return None
    granul = _letzte_granulposition(ende)
    if granul is None:
        return None
    return max(0.0, (granul - _vorlauf(kopf)) / _OPUS_RATE)
