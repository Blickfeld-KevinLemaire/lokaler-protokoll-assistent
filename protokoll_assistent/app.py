"""Einstiegspunkt von VERMERK Desktop.

EINE Oberflaeche fuer beide Wege: Transkription und Nachbearbeitung laufen
wahlweise lokal (faster-whisper/pyannote/Ollama) oder ueber eine
API-Schnittstelle. Welcher Weg gilt, ist eine **Einstellung**
(``konfiguration.json``, bearbeitet ueber ``gui.settings_dialog``) und kein
eigenes Programm -- es gibt genau diese eine Anwendung.

Die Anwendung zeigt beim Start immer sofort das Hauptfenster -- nie einen
Einrichtungsassistenten DAVOR (kein separater "Willkommensbildschirm", der
das Hauptfenster verdeckt). Solange die Einrichtung nicht abgeschlossen ist,
oeffnet sich die Ersteinrichtung (``gui.ersteinrichtung``) als Dialog UEBER dem
bereits sichtbaren Hauptfenster: Sie erklaert das Programm, zeigt, was auf
diesem Computer moeglich ist und was es kostet, und laedt erst nach
Zustimmung. Wer sie vorher schliesst, sieht sie beim naechsten Start wieder --
ausser mit "Nicht mehr fragen". Ueber "Einstellungen -> Transkription -> Lokal
-> Einrichtung starten" bleibt der Weg jederzeit erreichbar.

Die schwere lokale Laufzeitumgebung (Torch/faster-whisper/pyannote, per
``bootstrap.py`` selbstinstallierend) wird NUR eingerichtet, wenn der
gespeicherte Transkriptionsmodus "lokal" ist UND der Anwender zugestimmt hat
(``bootstrap.laufzeit_beim_start_einrichten``). Die Ersteinrichtung laeuft
deshalb in der leichten Umgebung aus ``requirements-anwendung.txt`` und startet
die Anwendung nach der Zustimmung neu; erst dann richtet ``bootstrap`` die
Rechenumgebung ein, und die Ersteinrichtung setzt dort fort. Schaltet der
Anwender spaeter in den Einstellungen auf "Lokal" um, greift dieselbe
Einrichtung beim naechsten Start.

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

import importlib.util
import sys

from protokoll_assistent import bootstrap
from protokoll_assistent.utils import app_config, paths

_config = app_config.load_config()
_fenster_moeglich = getattr(sys, "frozen", False) or importlib.util.find_spec("PySide6") is not None

if bootstrap.laufzeit_beim_start_einrichten(
    _config, _fenster_moeglich, laufzeit_vorhanden=paths.get_active_venv_python().is_file()
):
    bootstrap.ensure_runtime_and_relaunch()

# Ab hier laeuft der Prozess entweder in der vom lokalen Modus vorbereiteten
# Laufzeitumgebung, oder - im reinen API-Modus - direkt in der Umgebung, die
# 'requirements-anwendung.txt' bereitstellt (PySide6, sounddevice, keyring).
from protokoll_assistent.services import ffmpeg_service  # noqa: E402
from protokoll_assistent.utils import netz  # noqa: E402
from protokoll_assistent.utils.logging_setup import get_logger  # noqa: E402
from protokoll_assistent.utils.paths import ensure_system_prompt_file_exists  # noqa: E402


def main() -> int:
    logger = get_logger()
    logger.info("VERMERK Desktop wird gestartet.")

    # Zertifikatspruefung ueber Windows (Firmennetze, fehlende Wurzelzertifikate): vor dem ersten Netzzugriff,
    # fuer urllib, requests, httpx und Hugging Face zugleich. Siehe 'utils/netz.py'.
    if not netz.systemzertifikate_nutzen():
        logger.info("Windows-Zertifikatspruefung nicht aktiv (Paket 'truststore' fehlt) -- Rueckfall ueber curl/PowerShell.")

    # Legt 'einstellungen/systemprompt_protokoll.txt' aus der mitgelieferten
    # Vorlage an, falls sie fehlt. Ohne das startet der Systemprompt-Editor im
    # Hauptfenster bei einer frischen Installation leer.
    ensure_system_prompt_file_exists()

    # Wird in jedem Modus gebraucht: Audio-Normalisierung und Chunk-Zuschnitt
    # laufen unabhaengig davon, ob die eigentliche Transkription lokal oder
    # ueber eine API erfolgt.
    ffmpeg_service.ensure_ffmpeg_on_path()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from protokoll_assistent.gui import theme
    from protokoll_assistent.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("VERMERK Desktop")
    theme.apply_theme(app)

    sperre = _instanz_sperren()
    if sperre is None:
        # Eine zweite Instanz koennte den Port fuer die Aufnahmegeraete nicht
        # belegen und zeigte nur einen irrefuehrenden "Port nicht nutzbar"-Fehler.
        logger.warning("VERMERK Desktop läuft bereits – zweite Instanz beendet sich.")
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            None,
            "VERMERK Desktop",
            "VERMERK Desktop läuft bereits. Bitte das vorhandene Fenster benutzen "
            "(ggf. in der Taskleiste oder im Task-Manager suchen).",
        )
        return 0

    try:
        window = MainWindow()
        window.show()

        konfig = app_config.load_config()
        if konfig["einrichtung_fortsetzen"] or not konfig["einrichtung_abgeschlossen"]:
            # Verzoegert (statt direkt vor 'app.exec()'), damit das Hauptfenster
            # tatsaechlich zuerst sichtbar gezeichnet wird, bevor der Dialog
            # darueber erscheint.
            QTimer.singleShot(0, lambda: _erstmalige_lokale_einrichtung_anbieten(window))

        exit_code = app.exec()
    finally:
        sperre.unlock()
    logger.info("VERMERK Desktop wurde beendet (Code %s).", exit_code)
    return exit_code


def _instanz_sperren():
    """Sperrdatei im Temp-Ordner des Benutzers; ``None``, wenn schon eine Instanz läuft.
    ``QLockFile`` erkennt verwaiste Sperren (Absturz, Neustart) selbst und räumt sie weg."""
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QLockFile

    sperre = QLockFile(str(Path(tempfile.gettempdir()) / "vermerk-desktop.lock"))
    sperre.setStaleLockTime(0)  # nur ein toter Prozess macht die Sperre verwaist, nie das Alter
    return sperre if sperre.tryLock(0) else None


def _erstmalige_lokale_einrichtung_anbieten(parent) -> None:
    """Die Ersteinrichtung anbieten -- oder nach dem Neustart fuer die
    Rechenumgebung an derselben Stelle fortsetzen (siehe Modul-Docstring).
    Ob sie als abgeschlossen gilt, entscheidet der Dialog selbst."""
    from PySide6.QtWidgets import QApplication

    from protokoll_assistent.gui.ersteinrichtung import ErsteinrichtungDialog

    dialog = ErsteinrichtungDialog(parent, start_bei=app_config.load_config()["einrichtung_fortsetzen"])
    if dialog.exec() == ErsteinrichtungDialog.NEUSTART:
        # Die neue Instanz ist schon gestartet; diese beendet sich.
        anwendung = QApplication.instance()
        if anwendung is not None:
            anwendung.quit()


if __name__ == "__main__":
    sys.exit(main())
