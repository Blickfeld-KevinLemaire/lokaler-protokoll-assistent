"""Sprechertrennung (pyannote) in einem eigenen Prozess.

Warum ein eigener Prozess: Im selben Prozess wie Whisper -- also neben der
CUDA-Umgebung von CTranslate2 -- loeste pyannote auf der GPU dreimal einen
Bluescreen HYPERVISOR_ERROR aus (Laptop mit RTX PRO 500, Speicherintegritaet
an; 19.09. und 04.10.2026), jedes Mal direkt beim Start der Sprechertrennung.
In einem frischen Prozess, in dem nur PyTorch die Karte benutzt, lief dieselbe
Sprechertrennung auf derselben Karte problemlos (89 s Audio in 7 s). Der
Prozess endet nach getaner Arbeit; sein Grafikspeicher ist dann sicher frei.

Aufruf (macht die Pipeline selbst, mit der Projektwurzel als Arbeitsordner):

    python -m protokoll_assistent.services.diarisierung_prozess AUDIO AUSGABE.json
        [--min N] [--max N] [--geraet cuda|cpu]

AUSGABE.json enthaelt ``{"turns": [...], "embeddings": {...}}``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# Eine Stunde Material braucht auf der GPU ein bis zwei Minuten, auf der CPU
# rund 25. Die Grenze faengt nur einen haengenden Prozess ab.
ZEITLIMIT_SEKUNDEN = 3 * 60 * 60

LaufFn = Callable[..., Any]


class DiarisierungsprozessFehler(RuntimeError):
    """Der eigene Prozess hat kein Ergebnis geliefert."""


def diarisiere_in_eigenem_prozess(
    audio: Path,
    min_sprecher: int | None,
    max_sprecher: int | None,
    geraet: str = "cuda",
    python: str | None = None,
    lauf_fn: LaufFn | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Startet die Sprechertrennung als eigenen Prozess und liefert
    ``(turns, embeddings)``. ``lauf_fn`` ersetzt ``subprocess.run`` im Test."""
    from protokoll_assistent.utils.paths import get_project_root

    with tempfile.TemporaryDirectory(prefix="diarisierung_") as ordner:
        ausgabe = Path(ordner) / "ergebnis.json"
        befehl = [python or sys.executable, "-m", __name__, str(audio), str(ausgabe), "--geraet", geraet]
        if min_sprecher is not None:
            befehl += ["--min", str(min_sprecher)]
        if max_sprecher is not None:
            befehl += ["--max", str(max_sprecher)]
        try:
            lauf = (lauf_fn or subprocess.run)(
                befehl,
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=ZEITLIMIT_SEKUNDEN,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as fehler:
            raise DiarisierungsprozessFehler(f"Der Prozess fuer die Sprechertrennung lief nicht: {fehler}") from fehler
        if lauf.returncode != 0 or not ausgabe.is_file():
            letzte = (lauf.stderr or lauf.stdout or "").strip().splitlines()[-3:]
            raise DiarisierungsprozessFehler(
                f"Die Sprechertrennung im eigenen Prozess ist gescheitert (Code {lauf.returncode}): " + " | ".join(letzte)
            )
        try:
            daten = json.loads(ausgabe.read_text(encoding="utf-8"))
            return list(daten["turns"]), dict(daten["embeddings"])
        except (OSError, ValueError, KeyError, TypeError) as fehler:
            raise DiarisierungsprozessFehler(f"Das Ergebnis der Sprechertrennung ist unlesbar: {fehler}") from fehler


def main(argv: Sequence[str] | None = None) -> int:
    """Einstieg im eigenen Prozess: pyannote laden, trennen, Ergebnis schreiben."""
    parser = argparse.ArgumentParser(prog="protokoll_assistent.services.diarisierung_prozess")
    parser.add_argument("audio")
    parser.add_argument("ausgabe")
    parser.add_argument("--min", type=int, default=None)
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--geraet", default="cuda", choices=("cuda", "cpu"))
    argumente = parser.parse_args(argv)

    from protokoll_assistent.services import diarization_service, model_service, transcription_service

    pipeline = model_service.load_pyannote_pipeline(argumente.geraet)
    wellenform = diarization_service.build_waveform_dict(transcription_service.load_audio_array(argumente.audio))
    embeddings: dict[str, list[float]] = {}
    turns = diarization_service.diarize_waveform(
        pipeline, wellenform, argumente.min, argumente.max, embeddings_out=embeddings
    )
    Path(argumente.ausgabe).write_text(json.dumps({"turns": turns, "embeddings": embeddings}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
