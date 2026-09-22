"""Einstiegspunkt des Protokoll-Assistenten.

EINE Oberflaeche fuer beide Wege: Transkription und Nachbearbeitung laufen
wahlweise lokal (faster-whisper/pyannote/Ollama) oder ueber eine
API-Schnittstelle. Welcher Weg gilt, ist eine **Einstellung**
(``konfiguration.json``, bearbeitet ueber ``gui.settings_dialog``) und kein
eigenes Programm -- es gibt genau diese eine Anwendung.

Die schwere lokale Laufzeitumgebung (Torch/faster-whisper/pyannote, per
``bootstrap.py`` selbstinstallierend) wird NUR eingerichtet, wenn der
gespeicherte Transkriptionsmodus tatsaechlich "lokal" ist. Wer ausschliesslich
ueber eine API arbeitet, bekommt einen schnellen, leichten Start mit den
Paketen aus ``requirements-anwendung.txt``. Schaltet der Anwender spaeter in
den Einstellungen auf "Lokal" um, greift dieselbe Einrichtung beim naechsten
Start.

``bootstrap.ensure_runtime_and_relaunch`` MUSS vor jedem Import von
PySide6/Torch stehen (siehe dessen Docstring) -- daher die ungewoehnliche
Importreihenfolge in dieser Datei.

Gestartet wird die Anwendung als Modul:

    python -m protokoll_assistent.app

Ein Start ueber den reinen Dateipfad ("python protokoll_assistent/app.py")
funktioniert bewusst NICHT mehr: Dabei stuende nur der Ordner dieser Datei im
Suchpfad und kein einziger Paketimport waere aufloesbar. Fruehere Fassungen
haben das mit 'sys.path'-Eintraegen geflickt; mit einem echten Paket ist der
Fehler nicht mehr moeglich (siehe 'bootstrap._relaunch', das die Anwendung
ebenfalls als Modul neu startet).
"""

from __future__ import annotations

import sys
from pathlib import Path

from protokoll_assistent.utils import app_config

_config = app_config.load_config()

if _config["transkription_modus"] == "lokal":
    from protokoll_assistent import bootstrap

    bootstrap.ensure_runtime_and_relaunch()

# Ab hier laeuft der Prozess entweder in der vom lokalen Modus vorbereiteten
# Laufzeitumgebung, oder - im reinen API-Modus - direkt in der Umgebung, die
# 'requirements-anwendung.txt' bereitstellt (PySide6, sounddevice, keyring).
from protokoll_assistent.services import ffmpeg_service  # noqa: E402
from protokoll_assistent.utils.logging_setup import get_logger  # noqa: E402
from protokoll_assistent.utils.paths import ensure_system_prompt_file_exists  # noqa: E402


def main() -> int:
    logger = get_logger()
    logger.info("Protokoll-Assistent wird gestartet.")

    # Legt 'einstellungen/systemprompt_protokoll.txt' aus der mitgelieferten
    # Vorlage an, falls sie fehlt. Ohne das startet der Systemprompt-Editor im
    # Hauptfenster bei einer frischen Installation leer.
    ensure_system_prompt_file_exists()

    # Wird in jedem Modus gebraucht: Audio-Normalisierung und Chunk-Zuschnitt
    # laufen unabhaengig davon, ob die eigentliche Transkription lokal oder
    # ueber eine API erfolgt.
    ffmpeg_service.ensure_ffmpeg_on_path()

    from PySide6.QtWidgets import QApplication

    from protokoll_assistent.gui import theme
    from protokoll_assistent.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Protokoll-Assistent")
    theme.apply_theme(app)

    # Referenzen halten, sonst werden die Fenster ohne Elternobjekt vom
    # Python-Garbage-Collector verworfen, sobald keine lokale Variable mehr
    # auf sie zeigt.
    windows: dict[str, object] = {}

    zeige_einrichtungsassistent = (
        not _config["einrichtung_abgeschlossen"] and _config["transkription_modus"] == "lokal"
    )
    if zeige_einrichtungsassistent:
        from protokoll_assistent.gui.wizard import SetupWizard

        def _on_setup_finished(folder: str, filename: str) -> None:
            window = MainWindow(
                initial_folder=Path(folder) if folder else None, initial_file=filename or None
            )
            windows["main"] = window
            app_config.update_config(einrichtung_abgeschlossen=True)
            window.show()
            wizard.close()

        wizard = SetupWizard()
        windows["wizard"] = wizard
        wizard.setup_finished.connect(_on_setup_finished)
        wizard.show()
    else:
        window = MainWindow()
        windows["main"] = window
        window.show()

    exit_code = app.exec()
    logger.info("Protokoll-Assistent wurde beendet (Code %s).", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
