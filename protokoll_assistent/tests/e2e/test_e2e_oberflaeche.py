"""Ende-zu-Ende durch die Oberflaeche: echte Knoepfe, echte Arbeiter, echte Modelle.

Das Hauptfenster wird wie von einem Menschen bedient -- Datei waehlen,
Knopf druecken, auf das Ergebnis warten. Ersetzt werden nur die Dateidialoge
(sie wuerden auf eine Eingabe warten) und die Meldungsfenster (sie werden
mitgeschrieben statt angezeigt). Die Arbeiter (QThread), Ollama und Whisper
laufen echt.

* Protokoll aus einem Transkript: laeuft in der Entwicklungsumgebung.
* Transkription bis zum Protokoll: Das Fenster startet die Verarbeitung im
  eigenen Prozess, braucht also faster-whisper und PyTorch. Der Test laeuft
  deshalb nur im Python der ML-Laufzeitumgebung und wird sonst uebersprungen::

      runtime\\venv\\Scripts\\python -m pip install pytest pytest-qt pytest-timeout
      $env:PROTOKOLL_E2E = "1"
      runtime\\venv\\Scripts\\python -m pytest protokoll_assistent/tests/e2e/test_e2e_oberflaeche.py -m e2e
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton  # noqa: E402

from protokoll_assistent.tests.e2e import besprechung  # noqa: E402

pytestmark = pytest.mark.timeout(3600)

MIT_LAUFZEIT = importlib.util.find_spec("faster_whisper") is not None


@pytest.fixture
def fenster(qt_widgets, tmp_path, monkeypatch, daten_ordner, sprachmodell):
    """Hauptfenster mit eigener Konfiguration, Ausgabe im Temp-Ordner und
    mitgeschriebenen Meldungen statt modaler Fenster."""
    from protokoll_assistent.gui import main_window as mw
    from protokoll_assistent.services import secret_store
    from protokoll_assistent.utils import app_config

    konfig = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: konfig)
    ausgabe = tmp_path / "ausgabe"
    ausgabe.mkdir()
    app_config.save_config(
        {
            **app_config.DEFAULTS,
            "ausgabeordner": str(ausgabe),
            "ollama_modell": sprachmodell,
            "nachbearbeitung_modus": "lokal",
            "transkription_modus": "lokal",
            "einrichtung_abgeschlossen": True,
        }
    )
    # Nie die echte Windows-Anmeldeinformationsverwaltung anfassen.
    monkeypatch.setattr(secret_store, "load_api_key", lambda name: None)
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: None)
    monkeypatch.setattr(secret_store, "delete_api_key", lambda name: None)

    meldungen: list[tuple[str, str, str]] = []
    for art in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox, art, staticmethod(lambda parent, titel, text, *a, _art=art, **k: meldungen.append((_art, titel, text)))
        )
    window = qt_widgets(mw.MainWindow())
    window.show()
    return window, ausgabe, meldungen


def _knopf(window, text: str) -> QPushButton:
    treffer = [k for k in window.findChildren(QPushButton) if k.text() == text]
    assert len(treffer) == 1, f"Knopf '{text}' {len(treffer)}-mal gefunden"
    return treffer[0]


def _datei_waehlen(monkeypatch, pfad: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(pfad), "")))


def _warte_auf_meldung(qtbot, meldungen, titel: str, timeout_s: int) -> tuple[str, str, str]:
    """Wartet, bis eine Meldung mit diesem Titel kommt; scheitert sofort bei einem Fehler."""

    def da() -> bool:
        fehler = [m for m in meldungen if m[0] == "critical" or "fehlgeschlagen" in m[1].lower()]
        assert not fehler, fehler
        return any(m[1] == titel for m in meldungen)

    qtbot.waitUntil(da, timeout=timeout_s * 1000)
    return next(m for m in meldungen if m[1] == titel)


def _protokoll(ausgabe: Path) -> dict:
    dateien = sorted(ausgabe.rglob("*_protokoll_*.json"))
    assert dateien, sorted(p.name for p in ausgabe.rglob("*"))
    return json.loads(dateien[-1].read_text(encoding="utf-8"))


def test_hauptfenster_erstellt_protokoll_aus_transkript(fenster, qtbot, transkript, monkeypatch):
    window, ausgabe, meldungen = fenster

    _datei_waehlen(monkeypatch, transkript)
    qtbot.mouseClick(_knopf(window, "Transkript auswählen …"), Qt.LeftButton)
    assert transkript.name in window.transcript_label.text()

    qtbot.mouseClick(window.protocol_start_button, Qt.LeftButton)
    _art, _titel, text = _warte_auf_meldung(qtbot, meldungen, "Nachbearbeitung abgeschlossen", timeout_s=900)

    assert str(ausgabe) in text
    assert window.status_label.text() == "Nachbearbeitung abgeschlossen."
    protokoll = json.dumps(_protokoll(ausgabe), ensure_ascii=False)
    assert besprechung.enthaelt_eines(protokoll, *besprechung.UMZUGSTERMIN), protokoll
    assert besprechung.enthaelt_eines(protokoll, *besprechung.BUDGET), protokoll
    assert besprechung.enthaelt_eines(protokoll, "testplan"), protokoll


@pytest.mark.skipif(not MIT_LAUFZEIT, reason="Nur im Python der ML-Laufzeitumgebung (faster-whisper fehlt hier)")
def test_hauptfenster_transkribiert_und_erstellt_das_protokoll(fenster, qtbot, besprechung_wav, monkeypatch):
    from protokoll_assistent.utils import hf_env, paths

    # Die Verarbeitung laeuft hier im Testprozess: Die Fixture '_keine_echten_tokens'
    # blendet die .env aus -- fuer die Sprechertrennung wird der echte Token gebraucht.
    monkeypatch.setattr(hf_env, "_env_datei", lambda: paths.get_project_root() / hf_env.ENV_DATEI)
    window, ausgabe, meldungen = fenster

    _datei_waehlen(monkeypatch, besprechung_wav)
    qtbot.mouseClick(_knopf(window, "Andere Datei wählen …"), Qt.LeftButton)
    assert besprechung_wav.name in window.file_label.text()

    def rueckfrage_bestaetigen() -> None:
        # Der echte Dialog "Wie soll verarbeitet werden?": Protokoll gleich mit erstellen.
        dialog = QApplication.activeModalWidget()
        if dialog is None or not hasattr(dialog, "protokoll_checkbox"):
            QTimer.singleShot(50, rueckfrage_bestaetigen)
            return
        dialog.protokoll_checkbox.setChecked(True)
        dialog.accept()

    QTimer.singleShot(0, rueckfrage_bestaetigen)
    qtbot.mouseClick(window.start_button, Qt.LeftButton)

    _warte_auf_meldung(qtbot, meldungen, "Nachbearbeitung abgeschlossen", timeout_s=1800)
    transkripte = sorted(ausgabe.rglob("*_lokal_transkript_*.json"))
    assert transkripte, sorted(p.name for p in ausgabe.rglob("*"))
    text = " ".join(s["text"] for s in json.loads(transkripte[-1].read_text(encoding="utf-8"))["segmente"])
    for wort in ("Becker", "Wagner", "Testplan"):
        assert besprechung.enthaelt_eines(text, wort), text
    if window.diarization_checkbox.isChecked():
        assert window.speaker_table.rowCount() >= 2, "Die Sprechertabelle zeigt weniger als zwei Sprecher."
    protokoll = json.dumps(_protokoll(ausgabe), ensure_ascii=False)
    assert besprechung.enthaelt_eines(protokoll, *besprechung.UMZUGSTERMIN), protokoll
