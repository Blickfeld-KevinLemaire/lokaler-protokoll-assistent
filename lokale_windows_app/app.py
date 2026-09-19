"""Einstiegspunkt von Protokoll-Assistent Lokal.

Macht die Anwendung auf JEDEM PC lauffaehig, nicht nur auf einem einzelnen,
manuell vorbereiteten Rechner:

1. ``bootstrap.ensure_runtime_and_relaunch`` sorgt zuerst dafuer, dass eine
   lauffaehige Python-Umgebung existiert (vorhandene '.venv-whisperx' ODER
   automatisch angelegte 'runtime\\venv') und startet die Anwendung darin
   neu. Diese Zeile MUSS vor jedem Import von PySide6/Torch/faster-whisper stehen,
   da diese Pakete zum allerersten Start noch gar nicht installiert sein
   koennen.
2. Danach zeigt die Anwendung einen Einrichtungsassistenten
   (``gui.wizard.SetupWizard``): fehlende Programme/Modelle werden
   heruntergeladen, ein Systemtest prueft die Einsatzbereitschaft, und der
   Nutzer waehlt seinen Eingabeordner.
3. Anschliessend oeffnet sich das eigentliche Hauptfenster
   (``gui.main_window.MainWindow``).

Es findet zu keinem Zeitpunkt eine Netzwerkuebertragung von Audio- oder
Videoinhalten statt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bootstrap

bootstrap.ensure_runtime_and_relaunch(app_entry=Path(__file__).resolve())

# Ab hier laeuft der Prozess garantiert in der vorbereiteten Umgebung --
# PySide6 & Co. sind installiert.
from services import ffmpeg_service  # noqa: E402
from utils.logging_setup import get_logger  # noqa: E402
from utils.paths import ensure_system_prompt_file_exists  # noqa: E402


def main() -> int:
    logger = get_logger()
    logger.info("Protokoll-Assistent Lokal wird gestartet.")

    ensure_system_prompt_file_exists()
    ffmpeg_service.ensure_ffmpeg_on_path()

    from PySide6.QtWidgets import QApplication

    from gui import theme
    from gui.main_window import MainWindow
    from gui.wizard import SetupWizard

    app = QApplication(sys.argv)
    app.setApplicationName("Protokoll-Assistent Lokal")
    theme.apply_theme(app)

    windows: dict[str, object] = {}

    def _on_setup_finished(folder: str, filename: str) -> None:
        window = MainWindow(
            initial_folder=Path(folder) if folder else None,
            initial_file=filename or None,
        )
        windows["main"] = window  # Referenz halten, sonst wird das Fenster verworfen
        window.show()
        wizard.close()

    wizard = SetupWizard()
    wizard.setup_finished.connect(_on_setup_finished)
    wizard.show()

    exit_code = app.exec()
    logger.info("Protokoll-Assistent Lokal wurde beendet (Code %s).", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
