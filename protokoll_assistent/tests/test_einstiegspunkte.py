"""Tests fuer die drei Einstiegspunkte der lokalen Anwendung.

Diese Skripte sind duenne Huellen um bereits getestete Dienste. Sie werden
hier trotzdem geprueft, weil genau sie beim Anwender als Erstes laufen - und
weil ein Tippfehler darin die gesamte Anwendung unbenutzbar macht.

Besonderheit: ``app.py`` ruft ``bootstrap.ensure_runtime_and_relaunch``
bereits beim Import auf (das muss so sein, bevor PySide6/Torch importiert
werden). Die Tests ersetzen den Aufruf deshalb, bevor das Modul geladen wird.
``systempruefung.py`` und ``modelle_herunterladen.py`` sind eigenstaendige
bzw. Grossbuchstaben im Namen und werden ueber ihren Dateipfad geladen.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest import mock

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
# app.py
# --------------------------------------------------------------------------
@pytest.fixture
def app_modul(monkeypatch, tmp_path):
    from protokoll_assistent import bootstrap
    from protokoll_assistent.utils import app_config

    # Ohne das wuerde der Import den Prozess neu starten wollen.
    monkeypatch.setattr(bootstrap, "ensure_runtime_and_relaunch", lambda: None)
    # Eigene Konfigurationsdatei je Test. 'app.py' liest sie beim IMPORT, und
    # 'main()' schreibt sie ueber 'einrichtung_abgeschlossen' auch zurueck -
    # ohne diese Trennung veraendert ein Test die echte Datei im Arbeitsbaum
    # und bestimmt damit das Ergebnis des naechsten.
    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    sys.modules.pop("protokoll_assistent.app", None)
    modul = importlib.import_module("protokoll_assistent.app")
    yield modul
    sys.modules.pop("protokoll_assistent.app", None)


def test_app_import_startet_keinen_neustart(app_modul):
    assert callable(app_modul.main)


def test_app_main_zeigt_direkt_das_hauptfenster(app_modul, monkeypatch, tmp_path):
    # Kein Einrichtungsassistent mehr VOR dem Hauptfenster (siehe
    # 'gui.wizard.LokalEinrichtungDialog' -- die Ersteinrichtung ist jetzt
    # ein gezielter Schritt aus den Einstellungen heraus, kein Startzwang
    # davor). Eine bereits abgeschlossene Einrichtung simuliert eine
    # wiederkehrende Installation, bei der auch der automatische Dialog
    # (siehe die beiden Tests weiter unten) nicht mehr erscheint.
    pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")
    from protokoll_assistent.services import ffmpeg_service
    from protokoll_assistent.utils import app_config, paths

    app_config.update_config(einrichtung_abgeschlossen=True)
    monkeypatch.setattr(paths, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(app_modul, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)

    from protokoll_assistent.gui import main_window as mw
    from protokoll_assistent.gui import theme

    erzeugt: dict[str, object] = {}

    class _HauptfensterAttrappe:
        def __init__(self, initial_folder=None, initial_file=None):
            erzeugt["hauptfenster"] = (initial_folder, initial_file)

        def show(self):
            erzeugt["hauptfenster_gezeigt"] = True

    class _QAppAttrappe:
        def __init__(self, argv):
            erzeugt["argv"] = argv

        def setApplicationName(self, name):
            erzeugt["name"] = name

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "MainWindow", _HauptfensterAttrappe)
    monkeypatch.setattr(theme, "apply_theme", lambda app: erzeugt.setdefault("theme", True))
    with mock.patch("PySide6.QtWidgets.QApplication", _QAppAttrappe):
        assert app_modul.main() == 0

    assert erzeugt["theme"] is True
    assert erzeugt["hauptfenster"] == (None, None)
    assert erzeugt["hauptfenster_gezeigt"] is True


def test_app_main_gibt_exitcode_durch(app_modul, monkeypatch):
    pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")
    from protokoll_assistent.services import ffmpeg_service
    from protokoll_assistent.utils import app_config

    app_config.update_config(einrichtung_abgeschlossen=True)
    monkeypatch.setattr(app_modul, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)

    from protokoll_assistent.gui import main_window as mw
    from protokoll_assistent.gui import theme

    class _HauptfensterAttrappe:
        def __init__(self, initial_folder=None, initial_file=None):
            pass

        def show(self):
            pass

    class _QAppAttrappe:
        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def exec(self):
            return 3

    monkeypatch.setattr(mw, "MainWindow", _HauptfensterAttrappe)
    monkeypatch.setattr(theme, "apply_theme", lambda app: None)
    # Der Rueckgabewert von app.exec() wird durchgereicht.
    with mock.patch("PySide6.QtWidgets.QApplication", _QAppAttrappe):
        assert app_modul.main() == 3


def test_app_main_bietet_lokale_einrichtung_bei_frischer_installation(app_modul, monkeypatch):
    # Lokale Verarbeitung ist der bevorzugte, datenschutzfreundliche Weg und
    # bekommt deshalb bei einer frischen Installation (Einrichtung noch
    # nicht abgeschlossen) einmalig automatisch Vorrang -- als Dialog UEBER
    # dem schon sichtbaren Hauptfenster, nicht als Bildschirm davor.
    pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")
    from protokoll_assistent.services import ffmpeg_service
    from protokoll_assistent.utils import app_config

    monkeypatch.setattr(app_modul, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)

    from protokoll_assistent.gui import main_window as mw
    from protokoll_assistent.gui import theme, wizard

    erzeugt: dict[str, object] = {}

    class _HauptfensterAttrappe:
        def __init__(self, initial_folder=None, initial_file=None):
            pass

        def show(self):
            pass

    class _EinrichtungsDialogAttrappe:
        def __init__(self, parent):
            erzeugt["dialog_eltern"] = parent

        def exec(self):
            erzeugt["dialog_ausgefuehrt"] = True

    class _QAppAttrappe:
        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def exec(self):
            return 0

    from PySide6.QtCore import QTimer

    monkeypatch.setattr(mw, "MainWindow", _HauptfensterAttrappe)
    monkeypatch.setattr(wizard, "LokalEinrichtungDialog", _EinrichtungsDialogAttrappe)
    monkeypatch.setattr(theme, "apply_theme", lambda app: None)
    # Nicht auf einen echten Timer-Tick warten -- direkt ausfuehren.
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, fn: fn()))

    with mock.patch("PySide6.QtWidgets.QApplication", _QAppAttrappe):
        assert app_modul.main() == 0

    assert erzeugt["dialog_ausgefuehrt"] is True
    assert isinstance(erzeugt["dialog_eltern"], _HauptfensterAttrappe)
    assert app_config.load_config()["einrichtung_abgeschlossen"] is True


def test_app_main_fragt_bei_abgeschlossener_einrichtung_nicht_erneut(app_modul, monkeypatch):
    pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")
    from protokoll_assistent.services import ffmpeg_service
    from protokoll_assistent.utils import app_config

    app_config.update_config(einrichtung_abgeschlossen=True)
    monkeypatch.setattr(app_modul, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)

    from protokoll_assistent.gui import main_window as mw
    from protokoll_assistent.gui import theme

    aufgerufen = []

    class _HauptfensterAttrappe:
        def __init__(self, initial_folder=None, initial_file=None):
            pass

        def show(self):
            pass

    class _QAppAttrappe:
        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def exec(self):
            return 0

    from PySide6.QtCore import QTimer

    monkeypatch.setattr(mw, "MainWindow", _HauptfensterAttrappe)
    monkeypatch.setattr(theme, "apply_theme", lambda app: None)
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, fn: aufgerufen.append(fn)))

    with mock.patch("PySide6.QtWidgets.QApplication", _QAppAttrappe):
        assert app_modul.main() == 0

    assert aufgerufen == []


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
def modelle_skript():
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
