"""Einstiegspunkt der vereinten Anwendung (Protokoll-Assistent).

Eine Oberflaeche fuer beide Wege - lokal (faster-whisper/pyannote/Ollama)
oder ueber eine API-Schnittstelle. Die komplette Verarbeitungslogik
(``services.pipeline_service`` und alles, was sie braucht) lebt
unveraendert in ``lokale_windows_app`` und wird hier wiederverwendet, nicht
kopiert - deshalb traegt dieses Modul ``lokale_windows_app`` als ERSTES in
den Suchpfad ein, noch vor jedem eigenen Import.

Die schwere lokale Laufzeitumgebung (Torch/faster-whisper/pyannote, per
``lokale_windows_app/bootstrap.py`` selbstinstallierend) wird NUR
eingerichtet, wenn der gespeicherte Modus tatsaechlich "lokal" ist. Ein
reiner API-Anwender bekommt einen schnellen, leichten Start ohne diese
Pakete - genau das Versprechen, das bisher nur die separate Cloud-Variante
gegeben hat. Schaltet der Anwender spaeter in den Einstellungen auf
"Lokal" um, greift dieselbe Einrichtung beim naechsten Start.

``bootstrap.ensure_runtime_and_relaunch`` MUSS vor jedem Import von
PySide6/Torch stehen (siehe deren Docstring) - deshalb die ungewoehnliche
Reihenfolge in dieser Datei.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJEKT_WURZEL = Path(__file__).resolve().parent.parent
_LOKALE_WINDOWS_APP = _PROJEKT_WURZEL / "lokale_windows_app"

# Zwei Eintraege, und die Reihenfolge ist wesentlich:
#
# 1. Die PROJEKTWURZEL muss im Suchpfad stehen, damit die eigenen, bewusst
#    qualifizierten Importe ('protokoll_assistent_vereint.X.Y') ueberhaupt
#    aufloesbar sind. Beim Start als Skript ("python app.py", und genau so
#    startet auch 'bootstrap._relaunch' diese Datei neu) enthaelt sys.path
#    nur den Ordner DIESER Datei - die Wurzel eben nicht. Ohne diese Zeile
#    endet der Start sofort mit "No module named 'protokoll_assistent_vereint'".
# 2. 'lokale_windows_app' muss VOR der Wurzel stehen, damit die bare
#    Importe ('services', 'utils', 'gui') dort landen - so wie
#    'pipeline_service' sie intern selbst aufloest.
sys.path.insert(0, str(_PROJEKT_WURZEL))
sys.path.insert(0, str(_LOKALE_WINDOWS_APP))

from protokoll_assistent_vereint.utils import app_config  # noqa: E402

_config = app_config.load_config()

if _config["transkription_modus"] == "lokal":
    import bootstrap  # noqa: E402

    bootstrap.ensure_runtime_and_relaunch(app_entry=Path(__file__).resolve())

# Ab hier laeuft der Prozess entweder in der vom lokalen Modus vorbereiteten
# Laufzeitumgebung, oder - im reinen API-Modus - direkt in der Umgebung, die
# 'requirements-vereint.txt' bereitstellt (PySide6, sounddevice, keyring).
from services import ffmpeg_service  # noqa: E402
from utils.logging_setup import get_logger  # noqa: E402


def main() -> int:
    logger = get_logger()
    logger.info("Protokoll-Assistent (vereint) wird gestartet.")

    # Wird in jedem Modus gebraucht: Audio-Normalisierung und Chunk-Zuschnitt
    # laufen unabhaengig davon, ob die eigentliche Transkription lokal oder
    # ueber eine API erfolgt.
    ffmpeg_service.ensure_ffmpeg_on_path()

    from PySide6.QtWidgets import QApplication

    from gui import theme
    from protokoll_assistent_vereint.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Protokoll-Assistent")
    theme.apply_theme(app)

    # Referenzen halten, sonst werden die Fenster ohne Elternobjekt vom
    # Python-Garbage-Collector verworfen, sobald keine lokale Variable mehr
    # auf sie zeigt (siehe 'lokale_windows_app/app.py' fuer dasselbe Muster).
    windows: dict[str, object] = {}

    zeige_einrichtungsassistent = (
        not _config["einrichtung_abgeschlossen"] and _config["transkription_modus"] == "lokal"
    )
    if zeige_einrichtungsassistent:
        from gui.wizard import SetupWizard

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
