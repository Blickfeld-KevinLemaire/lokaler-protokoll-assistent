"""Gemeinsame Vorbereitungen fuer die Tests der lokalen Windows-Anwendung.

Die Qt-Tests laufen unsichtbar ("offscreen"), damit sie auch auf einem
Build-Server ohne Bildschirm funktionieren.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Muss gesetzt sein, BEVOR die erste QApplication entsteht.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """Genau eine QApplication fuer die ganze Testsitzung.

    Qt erlaubt nur eine Instanz pro Prozess; sie wird am Ende bewusst nicht
    zerstoert, weil Qt das beim Prozessende selbst erledigt.
    """
    pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def qt_widgets(qt_app):
    """Sammelt erzeugte Fenster ein und raeumt sie nach dem Test sicher weg."""
    erzeugte = []

    def merken(widget):
        erzeugte.append(widget)
        return widget

    yield merken

    for widget in reversed(erzeugte):
        try:
            widget.close()
            widget.deleteLater()
        except Exception:  # noqa: S110 - beim Aufraeumen ist ein Fehler egal
            pass
    qt_app.processEvents()


@pytest.fixture(autouse=True)
def _keine_echten_tokens(monkeypatch):
    """Kein Test darf versehentlich einen echten Hugging-Face-Token benutzen --
    weder aus der Umgebung noch aus der .env im Projektordner noch aus der
    Windows-Anmeldeinformationsverwaltung."""
    from protokoll_assistent.utils import hf_env

    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hf_env, "_env_datei", lambda: Path(__file__).parent / "gibt-es-nicht.env")
    monkeypatch.setattr(hf_env, "_token_aus_anmeldeinfos", lambda: "")
