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
import logging
import os
import sys

from protokoll_assistent import bootstrap
from protokoll_assistent.utils import app_config

_config = app_config.load_config()
_fenster_moeglich = getattr(sys, "frozen", False) or importlib.util.find_spec("PySide6") is not None

if bootstrap.laufzeit_beim_start_einrichten(
    _config, _fenster_moeglich, laufzeit_vorhanden=bootstrap.laufzeit_eingerichtet()
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

    from PySide6.QtWidgets import QApplication

    from protokoll_assistent.gui import theme

    app = QApplication(sys.argv)
    app.setApplicationName("VERMERK Desktop")
    theme.apply_theme(app)

    # Fehler, die niemand abfaengt (etwa in einer Schaltflaeche), verschwanden bisher spurlos: Die gebaute
    # Anwendung hat keine Konsole. Jetzt stehen sie im Protokoll, und der Anwender erfaehrt davon.
    vorheriger_haken = sys.excepthook
    sys.excepthook = _fehlerhaken(logger)
    try:
        return _ausfuehren(app, logger)
    finally:
        sys.excepthook = vorheriger_haken


def _ausfuehren(app, logger) -> int:
    from PySide6.QtCore import QTimer

    from protokoll_assistent.gui.main_window import MainWindow

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
    if _hintergrundarbeit_laeuft(window):
        # Ein Arbeitsfaden laeuft noch (eine Anfrage an das Sprachmodell oder ein Download laesst sich nicht
        # unterbrechen). Zerstoert Python jetzt das Fenster, bricht Qt den Prozess mit einer Fehlermeldung ab
        # ("QThread: Destroyed while thread is still running"). Stattdessen endet der Prozess hier sofort --
        # alles Wichtige ist geschrieben, Zwischenstaende bleiben fuer das Fortsetzen erhalten.
        logger.warning("Beim Beenden lief noch Hintergrundarbeit; der Prozess wird ohne Warten beendet.")
        logging.shutdown()
        os._exit(exit_code)
    return exit_code


def _hintergrundarbeit_laeuft(window) -> bool:
    try:
        return bool(window.hintergrundarbeit())
    except Exception:  # Fenster schon abgebaut oder (in Tests) eine Attrappe ohne diese Methode
        return False


# So viele Fehlermeldungen zeigt der Fehlerhaken je Sitzung; danach steht alles Weitere nur im Protokoll.
_HOECHSTENS_MELDUNGEN = 3


def _fehlerhaken(logger):
    """``sys.excepthook``: schreibt jeden nicht abgefangenen Fehler ins Protokoll und zeigt ihn an."""
    zustand = {"gezeigt": 0, "offen": False}

    def haken(typ, wert, spur) -> None:
        if issubclass(typ, KeyboardInterrupt):
            sys.__excepthook__(typ, wert, spur)
            return
        logger.error("Unerwarteter Fehler", exc_info=(typ, wert, spur))
        if zustand["offen"] or zustand["gezeigt"] >= _HOECHSTENS_MELDUNGEN:
            return
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is None:
                return
            zustand["offen"] = True
            zustand["gezeigt"] += 1
            QMessageBox.critical(
                None,
                "Unerwarteter Fehler",
                f"Es ist ein unerwarteter Fehler aufgetreten:\n\n{typ.__name__}: {wert}\n\n"
                "Die Einzelheiten stehen in der Protokolldatei (Ordner „logs“ im Programmordner). "
                "Das Programm läuft weiter; im Zweifel bitte neu starten.",
            )
        except Exception:  # noqa: S110 -- der Fehlerhaken selbst darf nie werfen
            pass
        finally:
            zustand["offen"] = False

    return haken


class _OhneSperre:
    """Platzhalter, wenn sich die Sperrdatei nicht anlegen laesst (siehe ``_instanz_sperren``)."""

    def unlock(self) -> None:
        pass


# So lange wartet eine von der Anwendung selbst neu gestartete Instanz auf das Ende der alten.
WARTEN_NACH_NEUSTART_MS = 15000


def _instanz_sperren():
    """Sperrdatei im Temp-Ordner des Benutzers; ``None``, wenn schon eine Instanz läuft.
    ``QLockFile`` erkennt verwaiste Sperren (Absturz, Neustart) selbst und räumt sie weg."""
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QLockFile

    sperre = QLockFile(str(Path(tempfile.gettempdir()) / "vermerk-desktop.lock"))
    sperre.setStaleLockTime(0)  # nur ein toter Prozess macht die Sperre verwaist, nie das Alter
    # Nach "Jetzt neu starten" beendet sich die alte Instanz gerade erst: Die neue wartet auf sie, statt sich
    # mit "läuft bereits" zu verabschieden. Ein gewoehnlicher zweiter Start wartet nicht.
    warten = WARTEN_NACH_NEUSTART_MS if os.environ.get(bootstrap.NEUSTART_VARIABLE) == "1" else 0
    if sperre.tryLock(warten):
        return sperre
    if sperre.error() != QLockFile.LockError.LockFailedError:
        # Nicht "gehoert schon jemandem", sondern z. B. ein nicht beschreibbarer Temp-Ordner: Das ist kein
        # Grund, den Start mit "läuft bereits" zu verweigern.
        return _OhneSperre()
    return None


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
