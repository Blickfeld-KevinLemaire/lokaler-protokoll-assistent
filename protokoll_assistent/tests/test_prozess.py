"""Tests fuer 'utils/prozess.py' und die Logging-Einrichtung ohne Konsole."""

from __future__ import annotations

import logging
import subprocess
import sys

from protokoll_assistent.utils import logging_setup, paths, prozess


def test_kein_fenster_ist_das_windows_flag():
    assert prozess.KEIN_FENSTER == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert prozess.NEUE_PROZESSGRUPPE == getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


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
