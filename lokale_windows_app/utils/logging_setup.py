"""Zentrales Logging.

Wichtig: Es duerfen niemals Zugangsdaten (HF_TOKEN) oder Audio-/Transkript-
inhalte in die Logdatei geschrieben werden. Es werden ausschliesslich
technische Ablaufinformationen protokolliert.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils.paths import get_logs_dir

_LOGGER_NAME = "protokoll_assistent_lokal"
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    log_file = get_logs_dir() / "protokoll_assistent_lokal.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    return setup_logging()
