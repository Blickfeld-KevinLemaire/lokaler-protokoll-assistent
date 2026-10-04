"""Ende-zu-Ende-Tests mit echten Modellen.

Diese Tests sind die bewusste Ausnahme von Regel 4 in ``CLAUDE.md``: Sie
brauchen ein laufendes Ollama, laden fehlende Modelle herunter und rechnen auf
der Grafikkarte. Deshalb laufen sie **nur auf Wunsch**:

    $env:PROTOKOLL_E2E = "1"; uv run pytest protokoll_assistent/tests/e2e -m e2e

Ohne ``PROTOKOLL_E2E=1`` werden sie uebersprungen -- in der CI und bei jedem
normalen ``uv run pytest``. Weitere Schalter:

* ``PROTOKOLL_E2E_AUFNAHME``: eine echte Aufnahme (z. B. eine
  Podiumsdiskussion). Verarbeitet wird standardmaessig nur ein Ausschnitt von
  drei Minuten, damit ein Lauf wenige Minuten dauert. Die Datei wird nur
  gelesen, nie ins Repository kopiert.
* ``PROTOKOLL_E2E_LANG=1``: zusaetzlich die ganze Aufnahme (bei einer Stunde
  Material rund fuenf Minuten mehr). Nur noetig, wenn sich genau die
  Verarbeitung langer Aufnahmen aendert: Abschnitte (``chunking_service``),
  die mehrstufige Protokollauswertung (``protocol_service``) oder die
  Kontextgroesse fuer Ollama.
* ``PROTOKOLL_E2E_PYTHON``: das Python der ML-Laufzeitumgebung fuer die
  komplette Verarbeitung (sonst die Umgebung, die ``bootstrap`` anlegt).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from protokoll_assistent.tests.e2e import besprechung

AKTIV = os.environ.get("PROTOKOLL_E2E", "").strip() == "1"
LANG = os.environ.get("PROTOKOLL_E2E_LANG", "").strip() == "1"
EINBETTUNGSMODELL = "bge-m3"
# Ausschnitt aus der echten Aufnahme: ab Minute 10 (Begruessung und Vorspann
# sind vorbei), drei Minuten lang. Ist die Aufnahme kuerzer, ab dem Anfang.
AUSSCHNITT_START_SEKUNDEN = 600
AUSSCHNITT_SEKUNDEN = 180


def pytest_collection_modifyitems(config, items):
    ordner = Path(__file__).parent
    for item in items:
        if ordner not in Path(str(item.fspath)).parents:
            continue
        item.add_marker(pytest.mark.e2e)
        if not AKTIV:
            item.add_marker(pytest.mark.skip(reason="Ende-zu-Ende-Test: nur mit PROTOKOLL_E2E=1"))


@pytest.fixture
def daten_ordner(tmp_path, monkeypatch):
    """Arbeitsdaten, Logs und Zustand in einen Wegwerfordner statt neben die Anwendung."""
    ordner = tmp_path / "daten"
    ordner.mkdir()
    monkeypatch.setenv("PROTOKOLL_DATEN_DIR", str(ordner))
    return ordner


def _modell_bereitstellen(modell: str) -> str:
    from protokoll_assistent.services import ollama_service

    if not ollama_service.is_service_running():
        pytest.fail(f"Ollama ist unter {ollama_service.OLLAMA_BASE_URL} nicht erreichbar. Bitte Ollama starten.")
    if not ollama_service.is_model_available(modell):
        # Bewusst ueber die Funktion der Anwendung: Der Download-Weg wird so mitgeprueft.
        ollama_service.pull_model(modell)
    assert ollama_service.is_model_available(modell), f"{modell} fehlt auch nach dem Download."
    return modell


@pytest.fixture(scope="session")
def sprachmodell() -> str:
    from protokoll_assistent.services import ollama_service

    return _modell_bereitstellen(os.environ.get("PROTOKOLL_E2E_MODELL", ollama_service.DEFAULT_MODEL))


@pytest.fixture(scope="session")
def einbettungsmodell() -> str:
    return _modell_bereitstellen(EINBETTUNGSMODELL)


@pytest.fixture
def transkript(tmp_path) -> Path:
    """Das Drehbuch als Transkript im Exportformat -- ohne Spracherkennung."""
    return besprechung.schreibe_transkript(tmp_path)


_SPRACHAUSGABE = r"""
param([string]$Eingabe, [string]$Ziel)
Add-Type -AssemblyName System.Speech
$beitraege = Get-Content -Raw -Encoding UTF8 $Eingabe | ConvertFrom-Json
$stimme = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$stimme.SetOutputToWaveFile($Ziel, $format)
$text = New-Object System.Speech.Synthesis.PromptBuilder
$text.Culture = [System.Globalization.CultureInfo]::GetCultureInfo("de-DE")
foreach ($b in $beitraege) {
    $text.StartVoice($b.stimme)
    $text.AppendText($b.text)
    $text.EndVoice()
    $text.AppendBreak([TimeSpan]::FromSeconds(1))
}
$stimme.Speak($text)
$stimme.Dispose()
"""


@pytest.fixture(scope="session")
def besprechung_wav(tmp_path_factory) -> Path:
    """Die gespielte Besprechung als WAV (16 kHz mono), gesprochen von den
    deutschen Windows-Stimmen. Fehlen sie, wird der Test uebersprungen."""
    if sys.platform != "win32":
        pytest.skip("Die Sprachausgabe gibt es nur unter Windows.")
    ordner = tmp_path_factory.mktemp("aufnahme")
    eingabe = ordner / "beitraege.json"
    eingabe.write_text(
        json.dumps([{"stimme": stimme, "text": text} for _id, _name, stimme, text in besprechung.BEITRAEGE]),
        encoding="utf-8",
    )
    skript = ordner / "sprechen.ps1"
    skript.write_text(_SPRACHAUSGABE, encoding="utf-8-sig")
    ziel = ordner / "besprechung_datenbankumzug.wav"
    ergebnis = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(skript), str(eingabe), str(ziel)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if ergebnis.returncode != 0 or not ziel.is_file() or ziel.stat().st_size < 100_000:
        pytest.skip(f"Sprachausgabe nicht moeglich (fehlen die deutschen Stimmen?): {ergebnis.stderr.strip()[:300]}")
    return ziel


@pytest.fixture(scope="session")
def laufzeit_python() -> Path:
    """Das Python der ML-Laufzeitumgebung (torch, faster-whisper)."""
    from protokoll_assistent.utils import paths

    roh = os.environ.get("PROTOKOLL_E2E_PYTHON", "").strip()
    python = Path(roh) if roh else paths.get_active_venv_python()
    if not python.is_file():
        pytest.skip(
            f"Keine ML-Laufzeitumgebung unter {python}. Einmal die Anwendung im lokalen Modus starten "
            "(legt sie an) oder PROTOKOLL_E2E_PYTHON setzen."
        )
    probe = subprocess.run(
        [str(python), "-c", "import faster_whisper, torch; print(torch.cuda.is_available())"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(f"Die Laufzeitumgebung {python} ist unvollstaendig: {probe.stderr.strip()[-300:]}")
    return python


@pytest.fixture(scope="session")
def echte_aufnahme() -> Path:
    roh = os.environ.get("PROTOKOLL_E2E_AUFNAHME", "").strip()
    if not roh:
        pytest.skip("PROTOKOLL_E2E_AUFNAHME ist nicht gesetzt.")
    aufnahme = Path(roh)
    assert aufnahme.is_file(), f"{aufnahme} gibt es nicht."
    return aufnahme


@pytest.fixture(scope="session")
def aufnahme_ausschnitt(echte_aufnahme, tmp_path_factory) -> Path:
    """Drei Minuten der echten Aufnahme (16 kHz mono) -- genug Material fuer
    einen echten Durchlauf, kurz genug, dass er bei jedem E2E-Lauf mitlaufen kann."""
    from protokoll_assistent.services import ffmpeg_service

    ffmpeg = ffmpeg_service.find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("FFmpeg fehlt (die Anwendung laedt es beim ersten Start nach tools/ffmpeg).")
    ziel = tmp_path_factory.mktemp("ausschnitt") / f"{echte_aufnahme.stem}_ausschnitt.wav"
    for start in (AUSSCHNITT_START_SEKUNDEN, 0):
        subprocess.run(
            [str(ffmpeg), "-y", "-v", "error", "-ss", str(start), "-t", str(AUSSCHNITT_SEKUNDEN),
             "-i", str(echte_aufnahme), "-ac", "1", "-ar", "16000", str(ziel)],
            capture_output=True,
            timeout=300,
            check=False,
        )
        # 16 kHz * 2 Byte: unter 30 s Ton war die Aufnahme kuerzer als der Startpunkt.
        if ziel.is_file() and ziel.stat().st_size > 30 * 16000 * 2:
            return ziel
    raise AssertionError(f"Aus {echte_aufnahme} liess sich kein Ausschnitt schneiden.")
