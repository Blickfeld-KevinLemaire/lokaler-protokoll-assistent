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
from protokoll_assistent.utils import hf_env, paths

pytestmark = pytest.mark.timeout(3600)

LANG = os.environ.get("PROTOKOLL_E2E_LANG", "").strip() == "1"

# Beim Laden des Moduls erfasst: Die Fixture '_keine_echten_tokens' (tests/conftest.py)
# entfernt HF_TOKEN fuer jeden Test und blendet die .env aus. Hier ist der echte
# Token aber gewollt -- die Sprechertrennung laeuft nur mit ihm.
_HF_TOKEN_AUS_UMGEBUNG = os.environ.get("HF_TOKEN", "").strip()
MIT_SPRECHERTRENNUNG = bool(
    _HF_TOKEN_AUS_UMGEBUNG or hf_env._token_aus_env_datei(paths.get_project_root() / hf_env.ENV_DATEI)
)


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
        "PROTOKOLL_SPRECHERTRENNUNG": "1" if MIT_SPRECHERTRENNUNG else "0",
        # Aus der Umgebung gesetzt: weiterreichen (die .env liest der Server selbst).
        **({"HF_TOKEN": _HF_TOKEN_AUS_UMGEBUNG} if _HF_TOKEN_AUS_UMGEBUNG else {}),
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
    _sprecher_getrennt(ordner, mindestens=2)  # drei Stimmen; zwei aehnliche duerfen verschmelzen

    protokoll = json.dumps(_protokoll(ordner), ensure_ascii=False)
    assert besprechung.enthaelt_eines(protokoll, *besprechung.UMZUGSTERMIN), protokoll
    assert besprechung.enthaelt_eines(protokoll, *besprechung.BUDGET), protokoll
    assert besprechung.enthaelt_eines(protokoll, "testplan"), protokoll


def _sprecher_getrennt(ordner: Path, mindestens: int) -> None:
    """Mit Token muss die Sprechertrennung mehrere Stimmen finden; ohne bleibt sie aus."""
    if not MIT_SPRECHERTRENNUNG:
        return
    sprecher = {s.get("sprecher_id") for s in _transkript(ordner)["segmente"] if s.get("sprecher_id")}
    assert len(sprecher) >= mindestens, f"Nur {len(sprecher)} Sprecher erkannt: {sprecher}"


def _plausibel(ordner: Path, mindestens_woerter: int, mindestens_sprecher: int) -> None:
    """Fuer echtes Material gibt es keine Musterloesung: Jede Stufe muss etwas
    Plausibles liefern."""
    woerter = sum(len(s["text"].split()) for s in _transkript(ordner)["segmente"])
    assert woerter >= mindestens_woerter, f"Nur {woerter} Woerter erkannt."
    _sprecher_getrennt(ordner, mindestens=mindestens_sprecher)
    protokoll = _protokoll(ordner)
    assert (protokoll.get("kurzzusammenfassung") or "").strip(), protokoll
    assert protokoll.get("themen"), protokoll


def test_ausschnitt_einer_echten_aufnahme_laeuft_durch(aufnahme_ausschnitt, laufzeit_python, sprachmodell, tmp_path):
    """Drei Minuten echtes Material (z. B. eine Podiumsdiskussion)."""
    _ergebnis, ordner = _verarbeite(aufnahme_ausschnitt, laufzeit_python, sprachmodell, tmp_path)
    _plausibel(ordner, mindestens_woerter=150, mindestens_sprecher=1)  # ab Minute 10: ein Vortrag


@pytest.mark.skipif(not LANG, reason="Ganze Aufnahme nur mit PROTOKOLL_E2E_LANG=1 (siehe conftest.py)")
def test_echte_aufnahme_in_voller_laenge(echte_aufnahme, laufzeit_python, sprachmodell, tmp_path):
    """Mehrere 10-Minuten-Abschnitte, alle drei Stufen der Protokollauswertung
    und der volle Kontext: nur bei Aenderungen genau daran noetig."""
    _ergebnis, ordner = _verarbeite(echte_aufnahme, laufzeit_python, sprachmodell, tmp_path)
    _plausibel(ordner, mindestens_woerter=1000, mindestens_sprecher=2)  # Moderation und Podium
