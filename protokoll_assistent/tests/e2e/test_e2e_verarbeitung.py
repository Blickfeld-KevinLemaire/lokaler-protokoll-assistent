"""Ende-zu-Ende: Aufnahme -> Transkript -> Protokoll -> Word, ohne Oberflaeche.

Benutzt wird der Servermodus (``python -m protokoll_assistent.server --einmal``)
im Python der ML-Laufzeitumgebung -- dieselbe Verarbeitungskette wie in der
Anwendung, aber ohne Fenster. Die Sprechertrennung laeuft nur, wenn
``HF_TOKEN`` gesetzt ist (das pyannote-Modell ist zugangsbeschraenkt).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from protokoll_assistent.tests.e2e import besprechung
from protokoll_assistent.utils import paths

pytestmark = pytest.mark.timeout(3600)


def _verarbeite(aufnahme: Path, laufzeit_python: Path, sprachmodell: str, tmp_path: Path) -> tuple[dict, Path]:
    eingang, ausgang, daten = tmp_path / "eingang", tmp_path / "ausgang", tmp_path / "daten"
    eingang.mkdir()
    shutil.copy2(aufnahme, eingang / aufnahme.name)
    umgebung = {
        **os.environ,
        "PROTOKOLL_EINGANG": str(eingang),
        "PROTOKOLL_AUSGANG": str(ausgang),
        "PROTOKOLL_DATEN_DIR": str(daten),
        "PROTOKOLL_STABIL_SEKUNDEN": "0",
        "PROTOKOLL_OLLAMA_MODELL": sprachmodell,
        "PROTOKOLL_SPRECHERTRENNUNG": "1" if os.environ.get("HF_TOKEN") else "0",
        "PROTOKOLL_EXPORT_FORMATE": "docx",
        "PYTHONUTF8": "1",
    }
    lauf = subprocess.run(
        [str(laufzeit_python), "-m", "protokoll_assistent.server", "--einmal"],
        cwd=paths.get_project_root(),
        env=umgebung,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3500,
        check=False,
    )
    assert lauf.returncode == 0, lauf.stdout[-3000:] + lauf.stderr[-3000:]
    ergebnisse = list(ausgang.glob("*/ergebnis.json"))
    assert len(ergebnisse) == 1, f"Kein Ergebnis im Ausgang.\n{lauf.stdout[-3000:]}"
    ergebnis = json.loads(ergebnisse[0].read_text(encoding="utf-8"))
    assert ergebnis["status"] == "fertig", ergebnis
    assert ergebnis["protokoll_fehler"] is None, ergebnis
    return ergebnis, ergebnisse[0].parent


def _transkript(ordner: Path) -> dict:
    kandidaten = list(ordner.glob("*_lokal_transkript_*.json"))
    assert kandidaten, sorted(p.name for p in ordner.iterdir())
    return json.loads(kandidaten[0].read_text(encoding="utf-8"))


def _protokoll(ordner: Path) -> dict:
    kandidaten = list(ordner.glob("*_protokoll_*.json"))
    assert kandidaten, sorted(p.name for p in ordner.iterdir())
    return json.loads(kandidaten[0].read_text(encoding="utf-8"))


def test_gespielte_besprechung_wird_transkribiert_und_ausgewertet(besprechung_wav, laufzeit_python, sprachmodell, tmp_path):
    _ergebnis, ordner = _verarbeite(besprechung_wav, laufzeit_python, sprachmodell, tmp_path)

    assert list(ordner.glob("*.docx")), sorted(p.name for p in ordner.iterdir())
    text = " ".join(s["text"] for s in _transkript(ordner)["segmente"])
    # Die Spracherkennung muss die Namen und Fakten aus dem Drehbuch hoeren.
    for wort in ("Becker", "Wagner", "Schulz", "Testplan", "Betriebsrat"):
        assert besprechung.enthaelt_eines(text, wort), f"'{wort}' fehlt im Transkript: {text}"
    assert besprechung.enthaelt_eines(text, *besprechung.UMZUGSTERMIN), text

    protokoll = json.dumps(_protokoll(ordner), ensure_ascii=False)
    assert besprechung.enthaelt_eines(protokoll, *besprechung.UMZUGSTERMIN), protokoll
    assert besprechung.enthaelt_eines(protokoll, *besprechung.BUDGET), protokoll
    assert besprechung.enthaelt_eines(protokoll, "testplan"), protokoll


def test_echte_aufnahme_laeuft_durch(laufzeit_python, sprachmodell, tmp_path):
    """Echtes Material (z. B. eine Podiumsdiskussion). Es gibt keine
    Musterloesung, geprueft wird nur, dass jede Stufe etwas Plausibles liefert."""
    roh = os.environ.get("PROTOKOLL_E2E_AUFNAHME", "").strip()
    if not roh:
        pytest.skip("PROTOKOLL_E2E_AUFNAHME ist nicht gesetzt.")
    aufnahme = Path(roh)
    assert aufnahme.is_file(), f"{aufnahme} gibt es nicht."

    _ergebnis, ordner = _verarbeite(aufnahme, laufzeit_python, sprachmodell, tmp_path)

    segmente = _transkript(ordner)["segmente"]
    woerter = sum(len(s["text"].split()) for s in segmente)
    assert woerter > 100, f"Nur {woerter} Woerter erkannt."
    protokoll = _protokoll(ordner)
    assert (protokoll.get("kurzzusammenfassung") or "").strip(), protokoll
    assert protokoll.get("themen"), protokoll
