"""Die beiden Schritte einer Sprachfrage, die etwas rechnen: die Frage verstehen und aus den Unterlagen beantworten.

``frage_service`` verbindet sie mit dem Ablauf; hier stehen sie ohne Qt, mit hereingereichten Funktionen (Whisper,
Sprachmodell), damit sie sich mit Attrappen testen lassen.
"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protokoll_assistent.services import anzeigetext, chat_service

# Ausgabearten einer Antwort
AUSGABE_ANZEIGE = "anzeige"  # Text fuers Display des Geraets (Standard)
AUSGABE_TON = "ton"  # gesprochen
AUSGABEN = (AUSGABE_ANZEIGE, AUSGABE_TON)

# So lang darf die Frage hoechstens sein, die Whisper hoert (die Datei ist ohnehin auf wenige MB begrenzt)
FRAGE_MAX_SEKUNDEN = 90.0
# Kurz und gesprochen: Das Geraet liest die Antwort vor. Die Quellenangabe der Unterlagen-Antwort entfaellt.
SPRECH_HINWEIS = (
    "\n\n(Antworte auf Deutsch in gesprochener Sprache, hoechstens vier kurze Saetze, ohne Aufzaehlungen, "
    "ohne Markdown und ohne Quellenangaben. Steht die Antwort nicht in den Unterlagen, sage das in einem Satz.)"
)


ANZEIGE_HINWEIS = (
    "\n\n(Antworte auf Deutsch als kurze nummerierte Liste (1. 2. 3. ...), jeder Punkt hoechstens zwoelf Woerter "
    "(das Display ist klein), hoechstens sechs Punkte, ohne Markdown und ohne Quellenangaben. Wird nach einer bestimmten Anzahl von Punkten "
    "gefragt, halte genau diese Anzahl ein. Steht die Antwort nicht in den Unterlagen, sage das in einem Satz.)"
)

# Wie fuers Display aufbereitet wird, steht in anzeigetext (auch die Auftragsnamen brauchen es)
fuer_display = anzeigetext.fuer_display


def frage_verstehen(
    ton: bytes,
    endung: str,
    *,
    transkribieren: Callable[[Path], list[dict[str, Any]]],
    extrahieren: Callable[[Path, Path, float, float], Any],
    arbeitsordner: Path | None = None,
) -> str:
    """Der Ton einer Frage (WAV oder Ogg-Opus) als Text. ``extrahieren`` macht daraus ein 16-kHz-Mono-WAV (ffmpeg),
    ``transkribieren`` ist Whisper auf dem Prozessor."""
    with tempfile.TemporaryDirectory(prefix="frage-", dir=arbeitsordner) as ordner:
        quelle = Path(ordner) / f"frage{endung}"
        quelle.write_bytes(ton)
        wav = Path(ordner) / "frage-16k.wav"
        extrahieren(quelle, wav, 0.0, FRAGE_MAX_SEKUNDEN)
        segmente = transkribieren(wav)
    teile = [str(s.get("text", "")).strip() for s in segmente]
    return " ".join(t for t in teile if t)


def antwort_aus_unterlagen(
    frage: str, unterlagen: list[Path], chat_fn: chat_service.ChatFn, ausgabe: str = AUSGABE_ANZEIGE
) -> str:
    """Beantwortet die Frage anhand von Transkript und Zusammenfassung; nur Dateien, die es gibt, zaehlen.
    ``ausgabe`` bestimmt die Form: eine kurze Liste fuers Display oder gesprochene Saetze."""
    dokumente: list[chat_service.Dokument] = []
    for pfad in unterlagen:
        if not pfad.is_file():
            continue
        with contextlib.suppress(chat_service.ChatFehler):
            dokumente.append(chat_service.lade_dokument(pfad))
    if not dokumente:
        raise chat_service.ChatFehler("Zu dieser Aufnahme liegen keine Unterlagen vor.")
    antwort, _quellen = chat_service.beantworte_volltext(
        frage + (SPRECH_HINWEIS if ausgabe == AUSGABE_TON else ANZEIGE_HINWEIS), dokumente, [], chat_fn
    )
    return antwort
