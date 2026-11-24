"""Selbstinstallierende Laufzeitumgebung -- macht den lokalen Modus auf jedem
PC lauffaehig, ohne dass vorher manuell eine virtuelle Umgebung eingerichtet
werden muss.

Aufgerufen wird das Modul vom Dienst der Oberflaeche (``python -m
protokoll_assistent.api`` bzw. ``vermerk-dienst.exe``, siehe
``api.__main__.rechenumgebung_vorbereiten``), bevor er startet. Ablauf beim
allerersten Start im lokalen Modus, im Quellcode-Betrieb:
1. Ist bereits eine funktionierende '.venv-whisperx' NEBEN der Anwendung
   vorhanden (der urspruengliche Referenz-Rechner), wird diese direkt
   weiterverwendet -- kein erneuter Download.
2. Andernfalls wird unter 'runtime\\venv' eine eigene, private Python-
   Umgebung angelegt und dort automatisch alles Benoetigte installiert
   (PyTorch passend zu erkannter GPU/CPU, faster-whisper, pyannote.audio,
   FastAPI, ...).
3. Der Dienst startet sich anschliessend in dieser Umgebung neu -- mit
   derselben Befehlszeile (``als_dienst``).

Im gebauten Dienst (PyInstaller) laeuft derselbe Ablauf, nur mit der vom
Installer mitgelieferten Python-Laufzeitumgebung ('python\\python.exe') als
Basis statt des aufgerufenen Interpreters -- der Dienst selbst bringt FastAPI &
Co. bereits mit, aber bewusst nicht Torch/faster-whisper/pyannote (siehe
'_ensure_runtime_and_relaunch_frozen').

Dieses Modul verwendet bewusst NUR die Python-Standardbibliothek sowie die
ebenfalls abhaengigkeitsfreien Module ``services.environment_service`` und
``utils.paths`` -- zum Zeitpunkt des Aufrufs ist ja noch nichts Zusaetzliches
installiert.

Grenzen der Automatisierung (bewusst nicht versprochen): Im Quellcode-Betrieb
muss Python selbst (3.10 oder 3.11) auf dem Zielrechner bereits vorhanden
sein (die gebaute EXE bringt dafuer ihre eigene Laufzeitumgebung mit).
NVIDIA-Treiber/CUDA muessen in jedem Fall bereits installiert sein, damit die
GPU tatsaechlich genutzt werden kann -- ohne GPU laeuft die Anwendung auf der
CPU weiter (deutlich langsamer), aber lauffaehig.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Any

from protokoll_assistent.utils.prozess import KEIN_FENSTER

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


# Die Oberflaeche nennt diesen Titel, solange sie auf die Einrichtung wartet ("Den Fortschritt zeigt das Fenster
# ...", oberflaeche/src/lib/komponenten/einrichtung/Einrichtung.svelte).
SPLASH_TITEL = "VERMERK Desktop – Einrichtung"


def _try_create_splash():
    try:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
    except Exception:
        return _ConsoleSplash()

    try:
        root = tk.Tk()
        root.title(SPLASH_TITEL)
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
        _nach_vorn_holen(root)
        return _TkSplash(root, text_widget, tk)
    except Exception:
        return _ConsoleSplash()


def _nach_vorn_holen(root: Any) -> None:
    """Das Fortschrittsfenster vor das Fenster der Anwendung holen: Es oeffnet sich aus dem Dienst heraus und lag
    sonst oft dahinter -- dort stand waehrenddessen nur "Die App startet kurz neu", minutenlang ohne Fortschritt.
    Nur kurz "immer oben", damit es danach nicht ueber allen anderen Fenstern klebt."""
    try:
        root.lift()
        root.attributes("-topmost", True)
        root.update()
        root.attributes("-topmost", False)
        root.focus_force()
        root.update()
    except Exception:  # noqa: S110 - ein kaputtes Splash-Fenster darf
        pass          # die Einrichtung nicht abbrechen.


def _run_logged(command: list[str], splash) -> None:
    splash.log("> " + " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=KEIN_FENSTER,
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
        creationflags=KEIN_FENSTER,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Anlegen der Umgebung mit {base_python} fehlgeschlagen: {completed.stderr.strip()}")


def _report_python_diagnosis_and_exit() -> None:
    """Wird aufgerufen, wenn weder das aufgerufene Python noch eine andere
    bereits vorhandene Installation unterstuetzt wird. Zeigt eine klare
    Diagnose (statt kommentarlos abzubrechen) und wartet, bis der Nutzer sie
    bestaetigt hat -- es wird dabei nichts an diesem Computer veraendert."""
    from protokoll_assistent.services import environment_service

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


# Der Dienst wird als MODUL neu gestartet, nicht ueber einen Dateipfad.
# Ein Pfadstart ("python .../api/__main__.py") legt nur den Ordner der Datei in den
# Suchpfad, kein einziger Paketimport waere dann aufloesbar.
DIENSTMODUL = "protokoll_assistent.api"
ANWENDUNGSMODUL = DIENSTMODUL
# Was der Neustart in der Rechenumgebung zusaetzlich bekommt: die Befehlszeile des Dienstes ('als_dienst').
NEUSTART_ARGUMENTE: list[str] = []
ELTERN_VARIABLE = "VERMERK_ELTERN_PID"


def _hat_konsole() -> bool:
    """Haengt dieser Prozess an einer Konsole (Entwickler-Terminal)? Der vom
    Fenster gestartete Dienst hat keine. Ohne Windows gibt es die Frage nicht."""
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return True
    return bool(windll.kernel32.GetConsoleWindow())


ALTE_GETRENNTE_ABLAGE_HINWEIS = (
    "Hinweis: Diese Installation fuehrt die Einstellungen des lokalen Modus noch getrennt im Unterordner "
    "'protokoll_assistent' (Stand vor 0.5.0-rc1). Sie laeuft so weiter. Neue Installationen benutzen einen "
    "gemeinsamen Ordner."
)


def _relaunch(python_exe: Path) -> None:
    from protokoll_assistent.utils.paths import ANWENDUNGSORDNER_VARIABLE, get_app_dir, get_paket_dir

    child_env = dict(os.environ)
    child_env[MARKER_ENV_VAR] = "1"
    # 'get_app_dir()' bedeutet im Quellcode-Betrieb den Paketordner selbst
    # ('protokoll_assistent/', Elternordner von 'utils') -- das Paket ist von
    # EINE Ebene darueber importierbar, also der Projektwurzel. In einer
    # gebauten EXE ist 'get_app_dir()' dagegen der Ordner der EXE selbst, und
    # der mitgelieferte Quelltext liegt dort ALS Unterordner direkt drin
    # (siehe '_ensure_runtime_and_relaunch_frozen') -- dort muss 'cwd' also
    # bleiben, nicht eine Ebene hoeher gehen.
    app_dir = get_app_dir()
    if getattr(sys, "frozen", False):
        cwd = app_dir
        # Der neue Prozess laeuft aus dem Quelltext und hielte dessen Ordner fuer den Anwendungsordner: Er
        # fuehrte dort eine zweite 'konfiguration.json' -- die Ersteinrichtung begann nach dem Neustart
        # von vorn, angemeldete Aufnahmegeraete und API-Einstellungen waren "weg", Ergebnisse lagen in
        # einem zweiten Ausgabeordner. Er bekommt deshalb den Ordner der EXE mit ('paths.get_app_dir').
        # Ausnahme: Installationen, die schon so getrennt arbeiten -- dort liegen die benutzten
        # Einstellungen und Daten im Unterordner; sie bleiben, wo sie sind. Die Vorgabe des Fensters
        # (VERMERK_ANWENDUNGSORDNER in der geerbten Umgebung) wird dafuer entfernt: Geerbt fuehrte der
        # neue Prozess nach dem Update auf 0.6 den Ordner der EXE -- Einrichtung, Aufnahmegeraete,
        # Einstellungen und die bisherigen Ergebnisse waren dann "weg".
        if (app_dir / "protokoll_assistent" / "konfiguration.json").is_file():
            child_env.pop(ANWENDUNGSORDNER_VARIABLE, None)
        else:
            child_env[ANWENDUNGSORDNER_VARIABLE] = str(app_dir)
    else:
        cwd = get_paket_dir().parent
    # Ohne Konsolenfenster: Dieses 'python.exe' ist der Dienst hinter dem Fenster. Ein
    # sichtbares Konsolenfenster bliebe so lange offen, wie das Programm
    # laeuft, und schloesse der Anwender es, endete auch das Programm.
    # Das Fenster bleibt trotzdem als (unsichtbare) Konsole des Prozesses
    # bestehen, so oeffnen dessen Hilfsprozesse (ffmpeg, ...) auch keine eigenen.
    # Hat dieser Prozess selbst schon eine Konsole (Start aus dem Terminal),
    # erbt das Kind sie ohne neues Fenster -- dort bleibt die Ausgabe sichtbar.
    #
    # Der neu gestartete Dienst beendet sich auch, wenn DIESER Prozess endet (das Fenster startet ihn neu
    # oder beendet ihn) -- nicht nur, wenn das Fenster endet. Sonst bliebe er als Waise zurueck und
    # hielte Port und Grafikkarte.
    bisher = child_env.get(ELTERN_VARIABLE, "").strip()
    child_env[ELTERN_VARIABLE] = ",".join(p for p in (bisher, str(os.getpid())) if p)
    # Gebaute Fassung: '-B' schreibt kein '__pycache__' in den Programmordner (sonst blieben nach der
    # Deinstallation hunderte Dateien liegen), '-s' laesst Pakete aus dem Nutzerprofil aussen vor.
    schalter = ["-B", "-s"] if getattr(sys, "frozen", False) else []
    completed = subprocess.run(
        [str(python_exe), *schalter, "-m", ANWENDUNGSMODUL, *NEUSTART_ARGUMENTE],
        env=child_env,
        cwd=str(cwd),
        creationflags=0 if _hat_konsole() else KEIN_FENSTER,
    )
    sys.exit(completed.returncode)


def als_dienst(argumente: list[str]) -> None:
    """Der Neustart in der Rechenumgebung bekommt dieselbe Befehlszeile wie der laufende Dienst (Rolle,
    Port, Port-Datei ...)."""
    global ANWENDUNGSMODUL, NEUSTART_ARGUMENTE
    ANWENDUNGSMODUL = DIENSTMODUL
    NEUSTART_ARGUMENTE = list(argumente)


def laufzeit_beim_start_einrichten(konfig: dict[str, Any], fenster_moeglich: bool, laufzeit_vorhanden: bool) -> bool:
    """Soll der Dienst vor seinem Start die Rechenumgebung einrichten
    (bzw. in die vorhandene wechseln)?

    Nur im lokalen Transkriptionsmodus -- und nie ohne Zustimmung: Bei einer
    frischen Installation (und nach "Nicht mehr fragen") erscheint zuerst die
    Ersteinrichtung der Oberflaeche in der leichten Umgebung. Sie sagt, was die
    gut 5 GB kosten, und laesst den Dienst erst nach der Zustimmung neu starten.
    Ist die Umgebung schon da, wird nichts geladen -- dann wird wie immer in sie
    gewechselt. ``fenster_moeglich``: Gibt es eine Oberflaeche, die vorher um
    Zustimmung fragen kann (der Dienst hinter dem Fenster: ja)? Ohne sie bleibt
    es beim direkten Weg."""
    if konfig.get("transkription_modus") != "lokal":
        return False
    if laufzeit_vorhanden or not fenster_moeglich:
        return True
    # Zustimmung heisst: in der Einrichtung auf der Seite "Was noetig ist" zugestimmt ('einrichtung_fortsetzen').
    # Das Umschalten auf "Auf diesem Computer" in den Einstellungen ist KEINE Zustimmung (anders als frueher
    # in der Qt-Oberflaeche): Wer anfangs online gewaehlt hatte und spaeter umschaltete, bekam beim naechsten
    # Start gut 5 GB geladen, ohne die Seite gesehen zu haben, die sagt, was das kostet -- waehrend die
    # Einstellungen "noch nicht eingerichtet [Einrichten]" zeigten. Wer schon zugestimmt hat, hat entweder die
    # Umgebung (oben) oder 'einrichtung_fortsetzen' gesetzt und wird nicht erneut gefragt.
    return bool(konfig.get("einrichtung_fortsetzen")) and not konfig.get("lokale_einrichtung_zurueckgestellt")


def laufzeit_eingerichtet() -> bool:
    """Ist die Rechenumgebung fuer den lokalen Modus VOLLSTAENDIG eingerichtet? Dass ``python.exe`` schon
    da ist, genuegt nicht: Die Datei entsteht ganz am Anfang -- bricht die Einrichtung danach ab (kein Netz,
    Platte voll), ist die Umgebung unbrauchbar. Vollstaendig ist sie, wenn die Kennung des letzten
    erfolgreichen Laufs darin liegt (oder es die von Hand eingerichtete ``.venv-whisperx`` ist)."""
    from protokoll_assistent.services import environment_service
    from protokoll_assistent.utils.paths import get_active_venv_dir, get_legacy_venv_dir, venv_python_path

    venv_dir = get_active_venv_dir()
    if not venv_python_path(venv_dir).is_file():
        return False
    return venv_dir == get_legacy_venv_dir() or environment_service.kennungsdatei(venv_dir).is_file()


def ensure_runtime_and_relaunch() -> None:
    """Sorgt fuer eine lauffaehige Umgebung und startet den Dienst darin
    neu. Kehrt zurueck, wenn bereits in der verwalteten Umgebung ausgefuehrt
    wird (dann ist nichts weiter zu tun) -- oder wenn die Einrichtung
    gescheitert ist und der Dienst ohne Rechenumgebung starten kann
    (siehe ``_ohne_rechenumgebung_weiter``)."""
    if is_running_in_managed_venv():
        return

    if getattr(sys, "frozen", False):
        _ensure_runtime_and_relaunch_frozen()
    else:
        _ensure_runtime_and_relaunch_aus_quellcode()


def _ensure_runtime_and_relaunch_frozen() -> None:
    """Der gebaute Dienst bringt FastAPI & Co. bereits mit -- aber bewusst
    NICHT Torch/faster-whisper/pyannote (siehe 'vermerk_dienst.spec': der Dienst
    bleibt dadurch klein, und ein reiner API-Anwender braucht sie nie). Waehlt der
    Anwender trotzdem den lokalen Modus, muss sich diese schwere Laufzeit
    also genauso selbst einrichten wie im Quellcode-Betrieb.

    Die gebaute EXE selbst laesst sich dafuer nicht als "python -m ..."
    aufrufen. Der Installer liefert deshalb zusaetzlich den Quelltext (Ordner
    'protokoll_assistent' im Programmordner) und eine eigenstaendige
    Python-Laufzeitumgebung ('python\\python.exe') mit -- genau damit wird hier
    die 'runtime\\venv'-Umgebung angelegt und anschliessend der Dienst (aus dem
    mitgelieferten Quelltext) neu gestartet."""
    from protokoll_assistent.utils.paths import get_active_venv_dir, get_app_dir, venv_python_path

    bundled_python = get_app_dir() / "python" / "python.exe"
    if not bundled_python.is_file():
        # Nur Fenster und Dienst weitergegeben (ZIP), ohne die mitgelieferte
        # Python-Laufzeitumgebung (kein Installer-Build) -- der lokale Modus
        # ist dann nicht automatisch einrichtbar. Das darf den Dienst
        # nicht abstuerzen lassen: Er prueft vor einer lokalen Verarbeitung
        # ohnehin, ob die Laufzeitumgebung erreichbar ist, und meldet dann
        # verstaendlich, was fehlt.
        return

    venv_dir = get_active_venv_dir()
    python_exe = venv_python_path(venv_dir)
    _richte_ml_umgebung_ein_und_starte_neu(
        venv_dir=venv_dir, python_exe=python_exe, base_python=bundled_python, hinweis_basis_python=None
    )


def _ensure_runtime_and_relaunch_aus_quellcode() -> None:
    from protokoll_assistent.services import environment_service
    from protokoll_assistent.utils.paths import get_active_venv_dir, get_legacy_venv_dir, venv_python_path

    venv_dir = get_active_venv_dir()
    python_exe = venv_python_path(venv_dir)

    if venv_dir == get_legacy_venv_dir():
        # Bereits vollstaendig vorbereiteter Rechner: nichts zu installieren.
        _relaunch(python_exe)
        return

    # Wird nur gesetzt, wenn das AUFGERUFENE Python selbst nicht unterstuetzt
    # wird, aber eine andere, bereits auf diesem Computer installierte
    # passende Version gefunden wurde. Diese wird dann NUR zum Anlegen der
    # neuen 'runtime\venv'-Umgebung verwendet -- am System aendert sich
    # dadurch nichts.
    alternate_python: Path | None = None
    hinweis_basis_python: str | None = None
    if not environment_service.is_supported_python_version():
        alternate_python = environment_service.find_alternate_supported_python()
        if alternate_python is None:
            _report_python_diagnosis_and_exit()
            return
        hinweis_basis_python = (
            f"Diagnose: Das aufgerufene Python ({sys.version_info.major}."
            f"{sys.version_info.minor}) wird nicht unterstuetzt.\n"
            f"Eine passende, bereits auf diesem Computer installierte Version "
            f"wurde gefunden und wird stattdessen verwendet:\n  {alternate_python}\n"
            "An der aufgerufenen Python-Installation wird nichts veraendert.\n"
        )

    _richte_ml_umgebung_ein_und_starte_neu(
        venv_dir=venv_dir,
        python_exe=python_exe,
        base_python=alternate_python,
        hinweis_basis_python=hinweis_basis_python,
    )


def _richte_ml_umgebung_ein_und_starte_neu(
    *, venv_dir: Path, python_exe: Path, base_python: Path | None, hinweis_basis_python: str | None
) -> None:
    """Legt bei Bedarf 'runtime\\venv' an, installiert dort Torch & Co. und
    startet die Anwendung darin neu. ``base_python`` ist der Interpreter, mit
    dem die neue Umgebung angelegt wird, falls das aufgerufene Python selbst
    dafuer nicht taugt (Quellcode-Betrieb: eine andere unterstuetzte, bereits
    installierte Version; gebaute EXE: immer die mitgelieferte
    Python-Laufzeitumgebung, da die EXE selbst keine ist) -- ``None``
    bedeutet: das aufgerufene Python selbst passt bereits."""
    from protokoll_assistent.services import environment_service, rocm_laufzeit_service

    gpu_available = environment_service.detect_nvidia_gpu()
    index_url = environment_service.select_torch_index_url(gpu_available)
    # AMD-Karte aus der Liste: Die Transkription bekommt CTranslate2 mit ROCm (siehe rocm_laufzeit_service).
    amd_rocm = not gpu_available and rocm_laufzeit_service.amd_karte_erkannt()

    # Nur die Umgebung ANZULEGEN wurde bisher uebersprungen, die
    # pip-Aufrufe liefen bei JEDEM Start erneut. Weil die Anforderungen
    # Spannen sind ('torch~=2.11.0', 'pyannote.audio>=4.0'), muss pip dafuer
    # jedes Mal den Index befragen: Eine Anwendung, die ausdruecklich
    # offline arbeiten soll, brauchte also bei jedem Start Internet -- und
    # konnte sich nebenbei ungefragt neue Paketfassungen einziehen.
    if python_exe.is_file() and environment_service.einrichtung_ist_aktuell(venv_dir, index_url, amd_rocm):
        _relaunch(python_exe)
        return

    # Gab es schon einen vollstaendigen Lauf? Dann ist das hier eine AKTUALISIERUNG (geaenderte Paketliste
    # nach einem Update, andere Grafikkarte) -- scheitert sie, laeuft die vorhandene Umgebung weiter.
    schon_eingerichtet = python_exe.is_file() and environment_service.kennungsdatei(venv_dir).is_file()

    sperre = _einrichtung_sperren(venv_dir.parent)
    if sperre is None:
        # Ein zweiter Start waehrend der Einrichtung: Zwei pip-Laeufe in derselben Umgebung zerstoeren sie.
        splash = _try_create_splash()
        splash.log(
            "Die Einrichtung laeuft bereits in einem anderen Fenster (ggf. in der Taskleiste).\n"
            "Bitte dort abwarten -- die Anwendung startet danach von selbst."
        )
        _wait_for_acknowledgement(splash)
        splash.close()
        sys.exit(0)

    splash = _try_create_splash()
    if hinweis_basis_python is not None:
        splash.log(hinweis_basis_python)
    try:
        if not environment_service.TORCH_PACKAGES or not environment_service.RUNTIME_PACKAGES:
            raise RuntimeError(
                "Die Paketlisten (requirements-*.txt) fehlen im Programmordner. Bitte die Anwendung "
                "mit dem Installer neu installieren."
            )
        if python_exe.is_file() and not schon_eingerichtet and not _pip_vorhanden(venv_dir):
            # 'python.exe' entsteht vor pip. Wurde das Anlegen unterbrochen (Absturz, Virenscanner, Platte
            # voll), scheiterte danach jeder Start an "No module named pip" -- fuer immer.
            splash.log("Eine unvollstaendig angelegte Umgebung wird entfernt und neu angelegt.")
            shutil.rmtree(venv_dir, ignore_errors=True)
        if not python_exe.is_file():
            splash.log(f"Lege private Python-Umgebung an unter:\n  {venv_dir}\n")
            try:
                _create_venv(venv_dir, base_python=base_python)
            except Exception:
                shutil.rmtree(venv_dir, ignore_errors=True)
                raise
            splash.log("Umgebung angelegt.\n")

        splash.log(environment_service.describe_plan(gpu_available, amd_rocm) + "\n")
        rocm_raeder = None
        if amd_rocm:
            splash.log("Lade CTranslate2 fuer AMD-Grafikkarten (ca. 190 MB) ...")
            rocm_raeder = rocm_laufzeit_service.raeder_bereitstellen(
                venv_dir.parent / "rocm-raeder", environment_service.SUPPORTED_PYTHON_VERSIONS
            )
        for command in environment_service.build_pip_install_commands(
            python_exe, gpu_available, index_url, rocm_raeder
        ):
            _run_logged(command, splash)

        # Erst NACH dem letzten erfolgreichen pip-Aufruf festhalten: Ein
        # abgebrochener Lauf soll beim naechsten Start wieder aufgenommen
        # werden.
        environment_service.kennung_festhalten(venv_dir, index_url, amd_rocm)
        splash.log("\nEinrichtung der Python-Pakete abgeschlossen.")
    except Exception as error:
        _sperre_freigeben(sperre)
        if schon_eingerichtet and not _dienst_pakete_vorhanden(venv_dir) and _dienst_laeuft_ohne_rechenumgebung():
            # Die vorhandene Umgebung stammt aus einer Fassung vor 0.6 und kann den Dienst nicht starten (FastAPI
            # & Co. fehlen darin). Der Neustart dort endete sofort -- das Fenster versuchte es dreimal und gab
            # auf, die Anwendung liess sich ohne Internet gar nicht mehr oeffnen. Dann lieber ohne
            # Rechenumgebung starten; die Einstellungen bleiben, beim naechsten Start wird erneut aktualisiert.
            splash.log(f"\nDie Aktualisierung der Rechenumgebung ist fehlgeschlagen: {error}")
            splash.log(
                "Das Programm startet jetzt ohne die Rechenumgebung (Transkription auf diesem Computer ist so "
                "lange nicht moeglich). Beim naechsten Start mit Internetverbindung wird die Aktualisierung "
                "nachgeholt."
            )
            time.sleep(AKTUALISIERUNG_HINWEIS_SEKUNDEN)
            splash.close()
            return
        if schon_eingerichtet:
            # Die bisherige Umgebung funktioniert. Frueher endete hier JEDER Start mit einem Fehler, sobald
            # ein Update die Paketliste geaendert hatte und der Rechner gerade kein Netz hatte -- eine
            # Anwendung, die ausdruecklich offline arbeiten soll, liess sich dann nicht mehr oeffnen.
            splash.log(f"\nDie Aktualisierung der Rechenumgebung ist fehlgeschlagen: {error}")
            splash.log(
                "Die Anwendung startet mit der vorhandenen Umgebung. Beim naechsten Start mit "
                "Internetverbindung wird die Aktualisierung nachgeholt."
            )
            time.sleep(AKTUALISIERUNG_HINWEIS_SEKUNDEN)
            splash.close()
            _relaunch(python_exe)
            return
        splash.log(f"\nFEHLER waehrend der Einrichtung: {error}")
        weiter = _ohne_rechenumgebung_weiter()
        if weiter:
            splash.log(
                "Bitte die Internetverbindung pruefen. Das Programm startet jetzt ohne die Rechenumgebung: "
                "Die Einrichtung laesst sich dort erneut starten, oder Sie arbeiten online."
            )
        else:
            splash.log("Bitte Internetverbindung pruefen und die Anwendung erneut starten.")
        _wait_for_acknowledgement(splash)
        splash.close()
        if weiter:
            return
        sys.exit(1)

    _sperre_freigeben(sperre)
    splash.log("\nStarte Anwendung in der vorbereiteten Umgebung ...")
    splash.close()
    _relaunch(python_exe)


# So lange bleibt der Hinweis auf eine gescheiterte Aktualisierung stehen, bevor die Anwendung startet.
AKTUALISIERUNG_HINWEIS_SEKUNDEN = 4.0
_OHNE_SPERRE = object()


def _pip_vorhanden(venv_dir: Path) -> bool:
    return _paket_vorhanden(venv_dir, "pip")


def _paket_vorhanden(venv_dir: Path, paket: str) -> bool:
    return (venv_dir / "Lib" / "site-packages" / paket).is_dir() or any(venv_dir.glob(f"lib/python*/site-packages/{paket}"))


def _dienst_pakete_vorhanden(venv_dir: Path) -> bool:
    """Kann der Dienst in dieser Umgebung starten? Umgebungen aus Fassungen vor 0.6 haben FastAPI und uvicorn
    nicht (damals lief dort die Qt-Oberflaeche)."""
    return _paket_vorhanden(venv_dir, "fastapi") and _paket_vorhanden(venv_dir, "uvicorn")


def _dienst_laeuft_ohne_rechenumgebung() -> bool:
    """Kann dieser Prozess den Dienst selbst starten (gebaut, oder FastAPI ist da)?"""
    return bool(getattr(sys, "frozen", False)) or importlib.util.find_spec("fastapi") is not None


def _einrichtung_sperren(ordner: Path) -> Any:
    """Sperrt die Einrichtung fuer andere Prozesse. ``None``: Ein anderer Prozess richtet gerade ein. Die
    Sperre haengt an der offenen Datei und verschwindet mit dem Prozess -- auch nach einem Absturz."""
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        datei = (ordner / "einrichtung.sperre").open("a+b")  # noqa: SIM115 -- bleibt bis zur Freigabe offen
    except OSError:
        return _OHNE_SPERRE  # Ordner nicht beschreibbar: Dann scheitert die Einrichtung selbst und meldet es.
    try:
        if sys.platform == "win32":
            import msvcrt

            datei.seek(0)
            msvcrt.locking(datei.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        datei.close()
        return None
    return datei


def _sperre_freigeben(sperre: Any) -> None:
    if sperre is not None and sperre is not _OHNE_SPERRE:
        # Laesst sich die Datei nicht schliessen, gibt Windows die Sperre spaetestens mit dem Prozessende frei.
        with contextlib.suppress(OSError):
            sperre.close()


def _ohne_rechenumgebung_weiter() -> bool:
    """Nach einer gescheiterten ERSTEN Einrichtung: Kann der Dienst ohne Rechenumgebung starten? Dann
    wird die Fortsetzung zurueckgenommen, damit nicht jeder weitere Start wieder hier landet -- frueher gab
    es von dort keinen Weg zurueck ins Programm, ausser die Einstellungsdatei von Hand zu aendern. Die
    Ersteinrichtung erscheint beim naechsten Start erneut und bietet beides an: noch einmal versuchen oder
    online arbeiten. Ohne FastAPI (Quelltext-Start mit einem nackten Python) startete der Dienst gar nicht --
    dann bleibt es beim Abbruch."""
    if not _dienst_laeuft_ohne_rechenumgebung():
        return False
    from protokoll_assistent.utils import app_config

    try:
        app_config.update_config(einrichtung_fortsetzen="", lokale_einrichtung_zurueckgestellt=True)
    except OSError:
        return False
    return True


def _wait_for_acknowledgement(splash) -> None:
    if isinstance(splash, _ConsoleSplash):
        try:
            input("\nEnter druecken, um zu beenden ...")
        except (EOFError, OSError):
            # Keine Konsole zum Lesen (z. B. ohne Fenster gestartet): dann
            # gibt es niemanden, auf den gewartet werden koennte.
            pass
    else:
        # Statt einer festen Wartezeit bekommt der Nutzer einen echten
        # Schliessen-Knopf, damit die Meldung nicht einfach unbeachtet
        # verschwindet, bevor sie gelesen werden konnte.
        splash.show_close_button()
        splash.wait_for_close()
