"""Tests fuer die Konsolen-Einstiegspunkte der lokalen Einrichtung.

Diese Skripte sind duenne Huellen um bereits getestete Dienste. Sie werden
hier trotzdem geprueft, weil genau sie beim Anwender als Erstes laufen - und
weil ein Tippfehler darin die gesamte Einrichtung unbenutzbar macht.

``systempruefung.py`` und ``modelle_herunterladen.py`` (aufgerufen von
``Einrichtung-Lokal.ps1``) sind eigenstaendige Skripte und werden ueber ihren
Dateipfad geladen. Der Dienst (``python -m protokoll_assistent.api``) hat
eigene Tests (``test_api_*.py``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent


def _lade_nach_pfad(dateiname: str, modulname: str):
    """Laedt ein Skript, dessen Dateiname kein gueltiger Modulname ist."""
    pfad = APP_DIR / dateiname
    spec = importlib.util.spec_from_file_location(modulname, pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[modulname] = modul
    spec.loader.exec_module(modul)
    return modul


class _Pruefung:
    def __init__(self, key="k", ok=True, critical=False, label="Bezeichnung", detail="Detail"):
        self.key = key
        self.ok = ok
        self.critical = critical
        self.label = label
        self.detail = detail


@pytest.fixture
def status_abgefangen(monkeypatch):
    """Faengt das Schreiben der Einrichtungsstatus-Datei ab."""
    from protokoll_assistent.utils import setup_status

    geschrieben: list[tuple] = []
    monkeypatch.setattr(setup_status, "load_status", lambda: {})
    monkeypatch.setattr(setup_status, "save_status", lambda status: None)
    monkeypatch.setattr(
        setup_status,
        "mark_phase",
        lambda status, phase, ok, details: geschrieben.append((phase, ok, details)),
    )
    return geschrieben


# --------------------------------------------------------------------------
# systempruefung.py
# --------------------------------------------------------------------------
@pytest.fixture
def systempruefung():
    return _lade_nach_pfad("systempruefung.py", "systempruefung_test_modul")


def test_phase1_alles_erfuellt(systempruefung, monkeypatch, status_abgefangen, capsys):
    from protokoll_assistent.utils import diagnostics

    for name in (
        "check_python_version", "check_windows", "check_cuda", "check_gpu_vram",
        "check_ram", "check_ffmpeg", "check_ffprobe", "check_ollama_installed",
    ):
        monkeypatch.setattr(diagnostics, name, lambda _n=name: _Pruefung(key=_n, ok=True))
    monkeypatch.setattr(diagnostics, "check_disk_space", lambda pfad: _Pruefung(ok=True))
    monkeypatch.setattr(diagnostics, "format_report", lambda checks: "BERICHT")

    assert systempruefung.run_phase1() is True
    assert status_abgefangen[0][0] == "systempruefung"
    assert status_abgefangen[0][1] is True
    assert "Alle kritischen Systemvoraussetzungen sind erfuellt." in capsys.readouterr().out


def test_phase1_meldet_fehlende_voraussetzungen(
    systempruefung, monkeypatch, status_abgefangen, capsys
):
    from protokoll_assistent.utils import diagnostics

    for name in (
        "check_python_version", "check_windows", "check_cuda", "check_gpu_vram",
        "check_ram", "check_ffprobe", "check_ollama_installed",
    ):
        monkeypatch.setattr(diagnostics, name, lambda _n=name: _Pruefung(key=_n, ok=True))
    monkeypatch.setattr(diagnostics, "check_disk_space", lambda pfad: _Pruefung(ok=True))
    monkeypatch.setattr(
        diagnostics,
        "check_ffmpeg",
        lambda: _Pruefung(key="ffmpeg", ok=False, critical=True, label="FFmpeg", detail="fehlt"),
    )
    monkeypatch.setattr(diagnostics, "format_report", lambda checks: "BERICHT")

    assert systempruefung.run_phase1() is False

    ausgabe = capsys.readouterr().out
    assert "FEHLENDE VORAUSSETZUNGEN" in ausgabe
    assert "FFmpeg" in ausgabe
    assert status_abgefangen[0][1] is False


def _alle_offline_pruefungen(monkeypatch, ok=True):
    from protokoll_assistent.utils import diagnostics

    for name in (
        "check_ffmpeg", "check_ffprobe", "check_whisperx_import", "check_pyannote_import",
        "check_model_cache", "check_ollama_running", "check_ollama_model",
    ):
        monkeypatch.setattr(diagnostics, name, lambda _n=name, _ok=ok: _Pruefung(key=_n, ok=_ok))
    monkeypatch.setattr(diagnostics, "check_output_dir_writable", lambda pfad: _Pruefung(ok=ok))


def test_phase4_offline_erfolgreich(systempruefung, monkeypatch, status_abgefangen, capsys):
    _alle_offline_pruefungen(monkeypatch, ok=True)
    gesetzt = []
    monkeypatch.setattr(systempruefung, "enable_offline_mode", lambda: gesetzt.append(True))

    assert systempruefung.run_phase4_offline_check() is True

    assert gesetzt == [True]
    assert status_abgefangen[0][0] == "offline_pruefung"
    assert "erfolgreich" in capsys.readouterr().out


def test_phase4_offline_unvollstaendig(systempruefung, monkeypatch, status_abgefangen, capsys):
    _alle_offline_pruefungen(monkeypatch, ok=False)
    monkeypatch.setattr(systempruefung, "enable_offline_mode", lambda: None)

    assert systempruefung.run_phase4_offline_check() is False
    assert "UNVOLLSTAENDIG" in capsys.readouterr().out


def test_systempruefung_main_phase1(systempruefung, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["systempruefung"])
    monkeypatch.setattr(systempruefung, "run_phase1", lambda: True)
    monkeypatch.setattr(
        systempruefung, "run_phase4_offline_check", lambda: pytest.fail("falsche Phase")
    )
    assert systempruefung.main() == 0


def test_systempruefung_main_offline_check(systempruefung, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["systempruefung", "--offline-check"])
    monkeypatch.setattr(systempruefung, "run_phase1", lambda: pytest.fail("falsche Phase"))
    monkeypatch.setattr(systempruefung, "run_phase4_offline_check", lambda: False)
    assert systempruefung.main() == 1


# --------------------------------------------------------------------------
# modelle_herunterladen.py
# --------------------------------------------------------------------------
@pytest.fixture
def modelle_skript(monkeypatch):
    # 'main()' haengt sonst das echte 'truststore' ein und tauscht 'ssl.SSLContext' fuer den ganzen
    # Testprozess aus -- alle Tests danach liefen mit veraendertem ssl (wie in der Fixture 'app_modul').
    from protokoll_assistent.utils import netz

    monkeypatch.setattr(netz, "systemzertifikate_nutzen", lambda: True)
    return _lade_nach_pfad("modelle_herunterladen.py", "modelle_herunterladen_test_modul")


def test_argumente_ohne_modell(modelle_skript):
    args = modelle_skript._parse_args([])
    assert args.modell is None


def test_argumente_mit_modell(modelle_skript):
    assert modelle_skript._parse_args(["--modell", "large-v2"]).modell == "large-v2"


def test_token_abfrage_verdeckt(modelle_skript, monkeypatch, capsys):
    monkeypatch.setattr(modelle_skript.getpass, "getpass", lambda prompt: "  geheim  ")
    assert modelle_skript._prompt_for_token() == "geheim"
    # Der Token darf nicht auf dem Bildschirm landen.
    assert "geheim" not in capsys.readouterr().out


def test_token_abfrage_leer_ergibt_none(modelle_skript, monkeypatch):
    monkeypatch.setattr(modelle_skript.getpass, "getpass", lambda prompt: "   ")
    assert modelle_skript._prompt_for_token() is None


def test_modelle_main_erfolg(modelle_skript, monkeypatch, status_abgefangen, capsys):
    from protokoll_assistent.services import model_download_service

    monkeypatch.setattr(sys, "argv", ["modelle_herunterladen"])
    monkeypatch.setattr(modelle_skript, "disable_offline_mode", lambda: None)
    monkeypatch.setattr(
        model_download_service,
        "download_all_models",
        lambda log, get_token, whisper_model: {"pyannote": True, "whisper": True},
    )

    assert modelle_skript.main() == 0
    assert status_abgefangen[0][0] == "modelle"
    assert "vollstaendig heruntergeladen" in capsys.readouterr().out


def test_modelle_main_teilweise_fehlgeschlagen(
    modelle_skript, monkeypatch, status_abgefangen, capsys
):
    from protokoll_assistent.services import model_download_service

    monkeypatch.setattr(sys, "argv", ["modelle_herunterladen", "--modell", "large-v3"])
    monkeypatch.setattr(modelle_skript, "disable_offline_mode", lambda: None)
    monkeypatch.setattr(
        model_download_service,
        "download_all_models",
        lambda log, get_token, whisper_model: {"pyannote": False, "whisper": True},
    )

    assert modelle_skript.main() == 1

    ausgabe = capsys.readouterr().out
    assert "Gewaehltes Whisper-Modell: large-v3" in ausgabe
    assert "Nicht alle Modelle" in ausgabe
    assert status_abgefangen[0][1] is False
