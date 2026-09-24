"""Einstiegspunkt des Protokoll-Assistenten.

EINE Oberflaeche fuer beide Wege: Transkription und Nachbearbeitung laufen
wahlweise lokal (faster-whisper/pyannote/Ollama) oder ueber eine
API-Schnittstelle. Welcher Weg gilt, ist eine **Einstellung**
(``konfiguration.json``, bearbeitet ueber ``gui.settings_dialog``) und kein
eigenes Programm -- es gibt genau diese eine Anwendung.

Die Anwendung zeigt beim Start immer sofort das Hauptfenster -- nie einen
Einrichtungsassistenten davor. Die Ersteinrichtung fuer den lokalen Modus
(Downloads, Systemtest, Modellwahl; ``gui.wizard.LokalEinrichtungDialog``)
ist ein bewusster, gezielter Schritt aus den Einstellungen heraus, kein
Startzwang -- der Anwender kann sofort mit der API-Schnittstelle arbeiten
oder sich erst in Ruhe umsehen, bevor er den lokalen Modus einrichtet.

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

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info("Protokoll-Assistent wurde beendet (Code %s).", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
