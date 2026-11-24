"""Tests fuer 'utils/prozess.py' und die Logging-Einrichtung ohne Konsole."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from protokoll_assistent.utils import logging_setup, paths, prozess


def test_kein_fenster_ist_das_windows_flag():
    assert prozess.KEIN_FENSTER == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert prozess.NEUE_PROZESSGRUPPE == getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def test_aus_dem_job_ist_das_windows_flag():
    assert prozess.AUS_DEM_JOB == getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def test_ausserhalb_des_jobs_starten(monkeypatch):
    monkeypatch.setattr(prozess, "AUS_DEM_JOB", 0x01000000)
    aufrufe = []

    def starte(befehl, **kwargs):
        aufrufe.append((befehl, kwargs))
        return "kind"

    assert prozess.ausserhalb_des_jobs_starten(starte, ("a", "b"), creationflags=8, close_fds=True) == "kind"
    assert aufrufe == [(["a", "b"], {"creationflags": 8 | 0x01000000, "close_fds": True})]


def test_ausserhalb_des_jobs_starten_ohne_erlaubnis_des_umgebenden_jobs(monkeypatch):
    """Ein fremder Job ohne JOB_OBJECT_LIMIT_BREAKAWAY_OK laesst CreateProcess mit ERROR_ACCESS_DENIED scheitern --
    dann startet der Prozess eben im Job, statt gar nicht."""
    monkeypatch.setattr(prozess, "AUS_DEM_JOB", 0x01000000)
    flags = []

    def starte(befehl, **kwargs):
        flags.append(kwargs["creationflags"])
        if kwargs["creationflags"] & 0x01000000:
            raise PermissionError(13, "Zugriff verweigert")
        return "kind"

    assert prozess.ausserhalb_des_jobs_starten(starte, ["a"], creationflags=8) == "kind"
    assert flags == [8 | 0x01000000, 8]


def test_ausserhalb_des_jobs_starten_andere_fehler_und_ohne_windows(monkeypatch):
    monkeypatch.setattr(prozess, "AUS_DEM_JOB", 0x01000000)
    aufrufe = []

    def fehlt(befehl, **kwargs):
        aufrufe.append(kwargs)
        raise FileNotFoundError("weg")

    with pytest.raises(FileNotFoundError):
        prozess.ausserhalb_des_jobs_starten(fehlt, ["a"])
    assert len(aufrufe) == 1  # kein zweiter Versuch: Am Job lag es nicht
    monkeypatch.setattr(prozess, "AUS_DEM_JOB", 0)
    gesehen = []
    prozess.ausserhalb_des_jobs_starten(lambda befehl, **k: gesehen.append(k), ["a"], creationflags=4)
    assert gesehen == [{"creationflags": 4}]


def _logger_frisch_einrichten(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(logging_setup, "_configured", False)
    logger = logging.getLogger(logging_setup._LOGGER_NAME)
    alte = list(logger.handlers)
    logger.handlers.clear()
    try:
        return logging_setup.setup_logging(), alte
    except BaseException:
        logger.handlers[:] = alte
        raise


def _handler_zuruecksetzen(logger, alte):
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers[:] = alte


def test_logging_schreibt_ohne_konsole_nur_in_die_datei(monkeypatch, tmp_path):
    # Gebaute EXE und 'pythonw' haben keine Konsole: 'sys.stderr' ist dort None.
    monkeypatch.setattr(sys, "stderr", None)
    logger, alte = _logger_frisch_einrichten(monkeypatch, tmp_path)
    try:
        arten = {type(h) for h in logger.handlers}
        assert logging.StreamHandler not in arten and len(logger.handlers) == 1
        logger.info("ohne konsole")  # darf nicht scheitern
    finally:
        _handler_zuruecksetzen(logger, alte)
    assert "ohne konsole" in (tmp_path / "protokoll_assistent.log").read_text(encoding="utf-8")


def test_logging_zeigt_mit_konsole_auch_dort(monkeypatch, tmp_path):
    logger, alte = _logger_frisch_einrichten(monkeypatch, tmp_path)
    try:
        assert any(type(h) is logging.StreamHandler for h in logger.handlers)
    finally:
        _handler_zuruecksetzen(logger, alte)
