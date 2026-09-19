"""Gemeinsame Vorbereitungen fuer die Tests der Cloud-Variante.

Die Module im Projektstamm (``protokoll_assistent_v2.py`` und Co.) legen ihre
Ordnerpfade beim Import als Modulkonstanten fest. Damit Tests niemals in die
echten Ordner ``eingabe``/``ausgabe``/``zwischenstaende`` schreiben, biegt die
Fixture ``isolierte_app_ordner`` diese Konstanten auf ein temporaeres
Verzeichnis um.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJEKT_WURZEL = Path(__file__).resolve().parent.parent
if str(PROJEKT_WURZEL) not in sys.path:
    sys.path.insert(0, str(PROJEKT_WURZEL))


@pytest.fixture
def isolierte_app_ordner(tmp_path, monkeypatch):
    """Biegt die Ordnerkonstanten der Cloud-Variante auf ``tmp_path`` um.

    Gibt ein Dict mit den angelegten Ordnern zurueck.
    """
    import protokoll_assistent_v2 as kern

    ordner = {
        "INPUT_DIR": tmp_path / "eingabe",
        "OUTPUT_DIR": tmp_path / "ausgabe",
        "CHECKPOINT_DIR": tmp_path / "zwischenstaende",
        "SETTINGS_DIR": tmp_path / "einstellungen",
    }
    for pfad in ordner.values():
        pfad.mkdir(parents=True, exist_ok=True)

    for name, pfad in ordner.items():
        monkeypatch.setattr(kern, name, pfad)
    monkeypatch.setattr(kern, "TERMS_FILE", ordner["SETTINGS_DIR"] / "fachbegriffe.txt")

    return ordner


@pytest.fixture(scope="session")
def tk_verfuegbar() -> bool:
    """Prueft einmalig, ob sich ueberhaupt ein Tk-Fenster oeffnen laesst."""
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        wurzel = tk.Tk()
    except Exception:
        return False
    wurzel.destroy()
    return True


@pytest.fixture
def tk_wurzel(tk_verfuegbar):
    """Ein verstecktes Tk-Hauptfenster, das nach dem Test sicher zugeht."""
    if not tk_verfuegbar:
        pytest.skip("Keine Fensterumgebung fuer tkinter verfuegbar.")
    import tkinter as tk

    wurzel = tk.Tk()
    wurzel.withdraw()
    try:
        yield wurzel
    finally:
        # Noch geplante 'after'-Rueckrufe (z. B. die Queue-Abfrage der GUI)
        # wuerden sonst nach dem Schliessen feuern und Tcl-Warnungen ausgeben.
        try:
            for auftrag_id in wurzel.tk.call("after", "info"):
                wurzel.after_cancel(str(auftrag_id))
        except Exception:  # noqa: S110 - beim Aufraeumen ist ein Fehler egal
            pass
        try:
            wurzel.destroy()
        except Exception:  # noqa: S110 - beim Aufraeumen ist ein Fehler egal
            pass


@pytest.fixture(autouse=True)
def _keine_echten_api_schluessel(monkeypatch):
    """Kein Test darf versehentlich einen echten Schluessel aus der Umgebung ziehen."""
    for name in ("OPENROUTER_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    os.environ.pop("PROTOKOLL_UPLOAD_BESTAETIGT", None)
