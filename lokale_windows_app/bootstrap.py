"""Selbstinstallierende Laufzeitumgebung -- macht die Anwendung auf jedem
PC lauffaehig, ohne dass vorher manuell eine virtuelle Umgebung eingerichtet
werden muss.

Ablauf beim allerersten Start auf einem neuen Rechner:
1. Ist bereits eine funktionierende '.venv-whisperx' NEBEN der Anwendung
   vorhanden (der urspruengliche Referenz-Rechner), wird diese direkt
   weiterverwendet -- kein erneuter Download.
2. Andernfalls wird unter 'runtime\\venv' eine eigene, private Python-
   Umgebung angelegt und dort automatisch alles Benoetigte installiert
   (PyTorch passend zu erkannter GPU/CPU, WhisperX, pyannote.audio,
   PySide6, ...).
3. Die Anwendung startet sich anschliessend in dieser Umgebung neu.

Dieses Modul verwendet bewusst NUR die Python-Standardbibliothek sowie die
ebenfalls abhaengigkeitsfreien Module ``services.environment_service`` und
``utils.paths`` -- zum Zeitpunkt des Aufrufs ist ja noch nichts Zusaetzliches
installiert.

Grenzen der Automatisierung (bewusst nicht versprochen): Python selbst
(3.10 oder 3.11) muss auf dem Zielrechner bereits vorhanden sein. NVIDIA-
Treiber/CUDA muessen ebenfalls bereits installiert sein, damit die GPU
tatsaechlich genutzt werden kann -- ohne GPU laeuft die Anwendung auf der
CPU weiter (deutlich langsamer), aber lauffaehig.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any

MARKER_ENV_VAR = "PROTOKOLL_ASSISTENT_LOKAL_VENV"


def is_running_in_managed_venv() -> bool:
    return os.environ.get(MARKER_ENV_VAR) == "1"


class _ConsoleSplash:
    def log(self, message: str) -> None:
        print(message, flush=True)

    def close(self) -> None:
        pass


class _TkSplash:
    def __init__(self, root, text_widget, tk_module) -> None:
        self._root = root
        self._text = text_widget
        self._tk = tk_module
        self._close_button: Any = None

    def log(self, message: str) -> None:
        print(message, flush=True)
        try:
            self._text.insert(self._tk.END, message + "\n")
            self._text.see(self._tk.END)
            self._root.update()
        except Exception:  # noqa: S110 - ein kaputtes Splash-Fenster darf
            pass          # die Einrichtung nicht abbrechen.

    def show_close_button(self, text: str = "Schließen") -> None:
        try:
            self._close_button = self._tk.Button(self._root, text=text, command=self._root.quit)
            self._close_button.pack(pady=8)
            self._root.update()
        except Exception:  # noqa: S110 - ein kaputtes Splash-Fenster darf
            pass          # die Einrichtung nicht abbrechen.

    def wait_for_close(self) -> None:
        if self._close_button is None:
            return
        try:
            self._root.mainloop()
        except Exception:  # noqa: S110 - ein kaputtes Splash-Fenster darf
            pass          # die Einrichtung nicht abbrechen.

    def close(self) -> None:
        try:
            self._root.destroy()
        except Exception:  # noqa: S110 - ein kaputtes Splash-Fenster darf
            pass          # die Einrichtung nicht abbrechen.


def _try_create_splash():
    try:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
    except Exception:
        return _ConsoleSplash()

    try:
        root = tk.Tk()
        root.title("Protokoll-Assistent Lokal -- Einrichtung")
        root.geometry("700x420")
        tk.Label(
            root,
            text=(
                "Die Anwendung richtet sich beim ersten Start automatisch ein.\n"
                "Dies kann je nach Internetverbindung und Rechner einige Minuten\n"
                "dauern. Es werden dabei keine Audio- oder Videodaten verarbeitet\n"
                "oder uebertragen -- lediglich benoetigte Programme/Pakete geladen."
            ),
            justify="left",
            padx=12,
            pady=8,
        ).pack(anchor="w")
        text_widget = ScrolledText(root, height=18)
        text_widget.pack(fill="both", expand=True, padx=12, pady=8)
        root.update()
        return _TkSplash(root, text_widget, tk)
    except Exception:
        return _ConsoleSplash()


def _run_logged(command: list[str], splash) -> None:
    splash.log("> " + " ".join(command))
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert process.stdout is not None  # noqa: S101 - nur Typ-Einengung,
    # 'stdout' ist durch 'stdout=subprocess.PIPE' oben garantiert gesetzt.
    for line in process.stdout:
        splash.log(line.rstrip())
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Befehl fehlgeschlagen (Exit-Code {return_code}): {' '.join(command)}")


def _create_venv(venv_dir: Path, base_python: Path | None = None) -> None:
    """Legt die neue virtuelle Umgebung an. Ohne ``base_python`` (Normalfall:
    das aufgerufene Python ist selbst unterstuetzt) geschieht das In-Prozess
    ueber ``venv.EnvBuilder``. Mit ``base_python`` (Ausweichfall: eine andere,
    bereits vorhandene passende Python-Version wurde gefunden) wird diese
    stattdessen per Unterprozess als Basis verwendet, da ``venv.EnvBuilder``
    immer nur den gerade laufenden Interpreter als Basis nehmen kann."""
    if base_python is None:
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))
        return

    completed = subprocess.run(
        [str(base_python), "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Anlegen der Umgebung mit {base_python} fehlgeschlagen: {completed.stderr.strip()}")


def _report_python_diagnosis_and_exit() -> None:
    """Wird aufgerufen, wenn weder das aufgerufene Python noch eine andere
    bereits vorhandene Installation unterstuetzt wird. Zeigt eine klare
    Diagnose (statt kommentarlos abzubrechen) und wartet, bis der Nutzer sie
    bestaetigt hat -- es wird dabei nichts an diesem Computer veraendert."""
    from services import environment_service

    splash = _try_create_splash()
    splash.log("SYSTEMDIAGNOSE: Python-Version")
    splash.log("=" * 60)
    splash.log(environment_service.python_version_error_message())
    splash.log(
        "\nEs wurde auf diesem Computer auch sonst keine unterstuetzte "
        "Python-Version (3.10 oder 3.11) gefunden."
    )
    splash.log(
        "\nZur vollstaendig lokalen Transkription fehlt auf diesem Computer:\n"
        "  - Python 3.10 oder 3.11\n"
        "\nBitte eine dieser Versionen von https://www.python.org/downloads/ "
        "installieren (beim Installer den Haken bei 'Add python.exe to PATH' "
        "setzen) und diese Anwendung danach erneut starten."
    )
    splash.log("\nEs wurde nichts an diesem Computer veraendert.")
    _wait_for_acknowledgement(splash)
    splash.close()
    sys.exit(1)


def _relaunch(python_exe: Path, app_entry: Path) -> None:
    child_env = dict(os.environ)
    child_env[MARKER_ENV_VAR] = "1"
    completed = subprocess.run([str(python_exe), str(app_entry)], env=child_env)
    sys.exit(completed.returncode)


def ensure_runtime_and_relaunch(app_entry: Path) -> None:
    """Sorgt fuer eine lauffaehige Umgebung und startet die Anwendung darin
    neu. Kehrt NUR zurueck, wenn bereits in der verwalteten Umgebung
    ausgefuehrt wird (dann ist nichts weiter zu tun)."""
    if is_running_in_managed_venv():
        return

    if getattr(sys, "frozen", False):
        # In einer mit PyInstaller gebauten EXE sind alle Abhaengigkeiten
        # bereits gebuendelt -- es gibt nichts einzurichten oder neu zu
        # starten.
        return

    from services import environment_service
    from utils.paths import get_active_venv_dir, get_legacy_venv_dir, venv_python_path

    venv_dir = get_active_venv_dir()
    python_exe = venv_python_path(venv_dir)
    using_legacy = venv_dir == get_legacy_venv_dir()

    if using_legacy:
        # Bereits vollstaendig vorbereiteter Rechner: nichts zu installieren.
        _relaunch(python_exe, app_entry)
        return

    # Wird nur gesetzt, wenn das AUFGERUFENE Python selbst nicht unterstuetzt
    # wird, aber eine andere, bereits auf diesem Computer installierte
    # passende Version gefunden wurde. Diese wird dann NUR zum Anlegen der
    # neuen 'runtime\venv'-Umgebung verwendet -- am System aendert sich
    # dadurch nichts.
    alternate_python: Path | None = None
    if not environment_service.is_supported_python_version():
        alternate_python = environment_service.find_alternate_supported_python()
        if alternate_python is None:
            _report_python_diagnosis_and_exit()
            return

    splash = _try_create_splash()
    if alternate_python is not None:
        splash.log(
            f"Diagnose: Das aufgerufene Python ({sys.version_info.major}."
            f"{sys.version_info.minor}) wird nicht unterstuetzt.\n"
            f"Eine passende, bereits auf diesem Computer installierte Version "
            f"wurde gefunden und wird stattdessen verwendet:\n  {alternate_python}\n"
            "An der aufgerufenen Python-Installation wird nichts veraendert.\n"
        )
    try:
        if not python_exe.is_file():
            splash.log(f"Lege private Python-Umgebung an unter:\n  {venv_dir}\n")
            _create_venv(venv_dir, base_python=alternate_python)
            splash.log("Umgebung angelegt.\n")

        gpu_available = environment_service.detect_nvidia_gpu()
        splash.log(environment_service.describe_plan(gpu_available) + "\n")
        for command in environment_service.build_pip_install_commands(python_exe, gpu_available):
            _run_logged(command, splash)

        splash.log("\nEinrichtung der Python-Pakete abgeschlossen.")
    except Exception as error:
        splash.log(f"\nFEHLER waehrend der Einrichtung: {error}")
        splash.log("Bitte Internetverbindung pruefen und die Anwendung erneut starten.")
        _wait_for_acknowledgement(splash)
        splash.close()
        sys.exit(1)

    splash.log("\nStarte Anwendung in der vorbereiteten Umgebung ...")
    splash.close()
    _relaunch(python_exe, app_entry)


def _wait_for_acknowledgement(splash) -> None:
    if isinstance(splash, _ConsoleSplash):
        try:
            input("\nEnter druecken, um zu beenden ...")
        except (EOFError, OSError):
            pass
    else:
        # Statt einer festen Wartezeit bekommt der Nutzer einen echten
        # Schliessen-Knopf, damit die Meldung nicht einfach unbeachtet
        # verschwindet, bevor sie gelesen werden konnte.
        splash.show_close_button()
        splash.wait_for_close()
