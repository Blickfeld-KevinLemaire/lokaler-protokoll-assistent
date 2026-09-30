"""Sprecher anhoeren und exportieren.

Grundlage sind die Sprecherabschnitte, die beim Transkribieren im JSON
gespeichert werden (``sprecher_turns``) und die normalisierte Audiodatei, auf
die sich ihre Zeiten beziehen (``audio_pfad``).

* ``hoerprobe_erstellen`` schneidet eine kurze Hoerprobe zusammen, damit man
  die Stimme hoert, bevor man einen Namen eintraegt.
* ``sprecher_exportieren`` schreibt Audio und Text eines Sprechers.

Die Dienste kennen kein Qt; der FFmpeg-Aufruf ist austauschbar.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from protokoll_assistent.services import ffmpeg_service
from protokoll_assistent.utils.timeformat import format_timestamp

AusschneidenFn = Callable[[Path, Path, list[tuple[float, float]]], Path]

# Abschnitte unter dieser Laenge taugen kaum zum Wiedererkennen einer Stimme.
MIN_ABSCHNITT_SEKUNDEN = 1.5
STANDARD_HOERPROBE_SEKUNDEN = 20.0


class SprecherExportFehler(RuntimeError):
    """Fehler mit einer Meldung, die der Anwender lesen kann."""


def _lade(json_pfad: Path) -> dict[str, Any]:
    daten: dict[str, Any] = json.loads(json_pfad.read_text(encoding="utf-8"))
    return daten


def abschnitte_des_sprechers(daten: dict[str, Any], sprecher_id: str) -> list[tuple[float, float]]:
    return [
        (float(turn["start_sekunden"]), float(turn["ende_sekunden"]))
        for turn in daten.get("sprecher_turns") or []
        if turn.get("sprecher_id") == sprecher_id
    ]


def _audio_pfad(daten: dict[str, Any]) -> Path:
    pfad = daten.get("audio_pfad")
    if not pfad:
        raise SprecherExportFehler(
            "Dieses Transkript enthält keine Angaben zur Audiodatei. Es stammt aus einer "
            "älteren Version - bitte die Aufnahme neu transkribieren."
        )
    audio = Path(pfad)
    if not audio.is_file():
        raise SprecherExportFehler(
            f"Die aufbereitete Audiodatei wurde nicht gefunden:\n{audio}\n\n"
            "Sie wird beim Aufräumen der Arbeitsdaten gelöscht. Bitte die Aufnahme neu transkribieren."
        )
    return audio


def hoerprobe_auswaehlen(
    abschnitte: list[tuple[float, float]], max_sekunden: float = STANDARD_HOERPROBE_SEKUNDEN
) -> list[tuple[float, float]]:
    """Waehlt die laengsten zusammenhaengenden Abschnitte, bis ``max_sekunden``
    erreicht sind, und ordnet sie zeitlich. Gibt es nur kurze Abschnitte,
    werden die verwendet, die es gibt."""
    lang = [a for a in abschnitte if a[1] - a[0] >= MIN_ABSCHNITT_SEKUNDEN]
    kandidaten = lang or list(abschnitte)
    gewaehlt: list[tuple[float, float]] = []
    summe = 0.0
    for start, ende in sorted(kandidaten, key=lambda a: a[1] - a[0], reverse=True):
        if summe >= max_sekunden:
            break
        rest = max_sekunden - summe
        ende_gekuerzt = min(ende, start + rest)
        gewaehlt.append((start, ende_gekuerzt))
        summe += ende_gekuerzt - start
    return sorted(gewaehlt)


def hoerprobe_erstellen(
    json_pfad: Path,
    sprecher_id: str,
    ziel_wav: Path,
    max_sekunden: float = STANDARD_HOERPROBE_SEKUNDEN,
    ausschneiden_fn: AusschneidenFn | None = None,
) -> Path:
    daten = _lade(json_pfad)
    abschnitte = abschnitte_des_sprechers(daten, sprecher_id)
    if not abschnitte:
        raise SprecherExportFehler(
            f"Für {sprecher_id} sind keine Sprecherabschnitte gespeichert. Das Transkript "
            "stammt vermutlich aus einer älteren Version - bitte neu transkribieren."
        )
    audio = _audio_pfad(daten)
    schneiden = ausschneiden_fn or ffmpeg_service.extract_speaker_audio
    return schneiden(audio, ziel_wav, hoerprobe_auswaehlen(abschnitte, max_sekunden))


_UNZULAESSIG = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _dateiname(text: str) -> str:
    sauber = _UNZULAESSIG.sub("_", text).strip(" .")
    return sauber or "Sprecher"


def sprecher_text(daten: dict[str, Any], sprecher_id: str) -> str:
    zeilen = [
        f"[{format_timestamp(segment['start_sekunden'])}] {segment['text']}"
        for segment in daten.get("segmente", [])
        if segment.get("sprecher_id") == sprecher_id
    ]
    return "\n".join(zeilen) + ("\n" if zeilen else "")


def sprecher_exportieren(
    json_pfad: Path,
    sprecher_id: str,
    ziel_ordner: Path,
    ausschneiden_fn: AusschneidenFn | None = None,
) -> tuple[Path, Path]:
    """Schreibt Audio (WAV) und Text (TXT) eines Sprechers in ``ziel_ordner``.
    Bestehende Dateien werden nicht ueberschrieben, sondern durchnummeriert."""
    daten = _lade(json_pfad)
    abschnitte = abschnitte_des_sprechers(daten, sprecher_id)
    if not abschnitte:
        raise SprecherExportFehler(f"Für {sprecher_id} sind keine Sprecherabschnitte gespeichert.")
    audio = _audio_pfad(daten)

    name = next(
        (e["anzeigename"] for e in daten.get("sprecher_zuordnung", []) if e.get("sprecher_id") == sprecher_id),
        sprecher_id,
    )
    stamm = f"{daten.get('quelldatei_stamm', 'aufnahme')}_{_dateiname(name)}"
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    zaehler = 1
    basis = stamm
    while (ziel_ordner / f"{basis}.wav").exists() or (ziel_ordner / f"{basis}.txt").exists():
        zaehler += 1
        basis = f"{stamm}_{zaehler}"

    schneiden = ausschneiden_fn or ffmpeg_service.extract_speaker_audio
    wav = schneiden(audio, ziel_ordner / f"{basis}.wav", sorted(abschnitte))
    txt = ziel_ordner / f"{basis}.txt"
    txt.write_text(sprecher_text(daten, sprecher_id), encoding="utf-8")
    return wav, txt
