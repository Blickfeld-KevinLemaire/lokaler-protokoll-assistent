"""Sprachausgabe: aus dem Text einer Antwort wird Ton fuer das Aufnahmegeraet.

Dieses Modul kennt keine Sprachsynthese selbst. Eine **Engine** wird von aussen hereingereicht: eine Funktion, die
einen Satz entgegennimmt und ``(PCM16-Mono-Bytes, Abtastrate)`` liefert. Welche Engine das ist (und dass sie
lokal rechnet), entscheidet die Oberflaeche; hier steht nur, was jede Engine braucht:

* den Text sprechbar machen (kein Markdown, keine Aufzaehlungszeichen, keine Quellenangaben),
* ihn in Saetze teilen (Engines klingen auf kurzen Stuecken besser und bleiben im Speicher klein),
* den Ton auf die Abtastrate des Geraets bringen und als WAV verpacken.

Ohne Qt und ohne numpy, damit es sich ohne weitere Pakete testen laesst.
"""

from __future__ import annotations

import array
import io
import re
import sys
import wave
from collections.abc import Callable

# (Satz) -> (PCM16 Mono, little endian; Abtastrate in Hz)
Engine = Callable[[str], tuple[bytes, int]]

# Das Geraet spielt 16 kHz, 16 Bit, mono: das spart Speicher und Funkzeit; fuer Sprache genuegt es.
GERAET_ABTASTRATE = 16000
# Laengere Saetze zerlegt die Engine ohnehin schlecht; hoechstens so viele Zeichen am Stueck.
SATZ_MAX_ZEICHEN = 240
# Pause zwischen zwei Saetzen
SATZ_PAUSE_SEKUNDEN = 0.25
# Obergrenze fuer eine Antwort: Zu langes Vorlesen taugt nicht, und das Geraet haelt den Ton im Speicher.
ANTWORT_MAX_SEKUNDEN = 90

_SATZENDE = re.compile(r"(?<=[.!?])\s+|\n+")
_QUELLE = re.compile(r"\s*\(\s*[^()]*?(?:\d{1,2}:\d{2})[^()]*\)")  # "(Protokoll, 10:32)"
_MARKDOWN = re.compile(r"[*`#>|~]+")
_LISTENPUNKT = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


class SprachausgabeFehler(RuntimeError):
    """Der Text konnte nicht gesprochen werden."""


def sprechtext(text: str) -> str:
    """Macht eine Modellantwort vorlesbar: Markdown, Listenpunkte, Quellenangaben und Links weg, ein Gedankenstrich
    zwischen Satzteilen bleibt als Komma."""
    ergebnis = _LINK.sub(r"\1", text)
    ergebnis = _QUELLE.sub("", ergebnis)
    ergebnis = _LISTENPUNKT.sub("", ergebnis)
    ergebnis = _MARKDOWN.sub("", ergebnis)
    ergebnis = ergebnis.replace(" - ", ", ").replace("–", ",").replace("—", ",")
    ergebnis = re.sub(r"[ \t]+", " ", ergebnis)
    ergebnis = re.sub(r"\n{2,}", "\n", ergebnis)
    return ergebnis.strip()


def saetze(text: str, max_zeichen: int = SATZ_MAX_ZEICHEN) -> list[str]:
    """Teilt in Saetze; ein zu langer Satz wird an Kommas (sonst an Leerzeichen) geteilt."""
    ergebnis: list[str] = []
    for roh in _SATZENDE.split(text):
        satz = roh.strip()
        while len(satz) > max_zeichen:
            schnitt = max(satz.rfind(", ", 0, max_zeichen), satz.rfind("; ", 0, max_zeichen))
            if schnitt < max_zeichen // 3:
                schnitt = satz.rfind(" ", 0, max_zeichen)
            if schnitt <= 0:
                schnitt = max_zeichen
            ergebnis.append(satz[: schnitt + 1].strip())
            satz = satz[schnitt + 1 :].strip()
        if satz:
            ergebnis.append(satz)
    return [s for s in ergebnis if any(zeichen.isalnum() for zeichen in s)]


def umrechnen(pcm: bytes, von: int, nach: int) -> bytes:
    """PCM16 Mono von einer Abtastrate auf eine andere (lineare Interpolation; fuer Sprache ausreichend)."""
    if von <= 0 or nach <= 0:
        raise SprachausgabeFehler("Ungueltige Abtastrate.")
    werte = array.array("h")
    werte.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder == "big":  # pragma: no cover - Windows/ARM laufen little endian
        werte.byteswap()
    if von != nach and len(werte) > 1:
        anzahl = max(1, round(len(werte) * nach / von))
        schritt = (len(werte) - 1) / max(anzahl - 1, 1)
        neu = array.array("h", bytes(2 * anzahl))
        for i in range(anzahl):
            position = i * schritt
            links = int(position)
            rechts = min(links + 1, len(werte) - 1)
            anteil = position - links
            neu[i] = int(werte[links] * (1.0 - anteil) + werte[rechts] * anteil)
        werte = neu
    if sys.byteorder == "big":  # pragma: no cover
        werte.byteswap()
    return werte.tobytes()


def stille(sekunden: float, abtastrate: int) -> bytes:
    return bytes(2 * round(sekunden * abtastrate))


def wav(pcm: bytes, abtastrate: int) -> bytes:
    """PCM16 Mono als WAV-Datei im Speicher."""
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(abtastrate)
        datei.writeframes(pcm)
    return puffer.getvalue()


def sprechen(
    text: str,
    engine: Engine,
    *,
    abtastrate: int = GERAET_ABTASTRATE,
    max_sekunden: float = ANTWORT_MAX_SEKUNDEN,
) -> bytes:
    """Der Text als WAV (16-Bit-Mono, ``abtastrate``) -- Satz fuer Satz durch die Engine, mit kurzen Pausen.

    Wird die Antwort laenger als ``max_sekunden``, bricht sie an einer Satzgrenze ab. ``SprachausgabeFehler``,
    wenn nichts Sprechbares im Text steht oder die Engine scheitert."""
    teile = saetze(sprechtext(text))
    if not teile:
        raise SprachausgabeFehler("Es gibt nichts zu sprechen.")
    pause = stille(SATZ_PAUSE_SEKUNDEN, abtastrate)
    ton = bytearray()
    for satz in teile:
        try:
            pcm, rate = engine(satz)
        except SprachausgabeFehler:
            raise
        except Exception as fehler:
            raise SprachausgabeFehler(f"Die Sprachausgabe ist fehlgeschlagen: {fehler}") from fehler
        ton += umrechnen(pcm, rate, abtastrate)
        if len(ton) // 2 >= max_sekunden * abtastrate:
            break
        ton += pause
    return wav(bytes(ton), abtastrate)
