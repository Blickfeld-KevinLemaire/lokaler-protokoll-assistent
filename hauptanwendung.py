"""Hauptanwendung -- Startpunkt zur Auswahl zwischen den beiden Wegen:

1. Lokal arbeiten: startet 'lokale_windows_app/app.py' (WhisperX + pyannote,
   vollstaendig offline). Beim allerersten Start dort laufen automatisch der
   Einrichtungsassistent (Systemtest, Modellempfehlung/-download) und die
   selbstinstallierende Laufzeitumgebung durch.
2. Eine Schnittstelle nutzen, die der Nutzer selbst einrichtet: startet
   'protokoll_assistent_gui.py' (Cloud-Transkription ueber einen vom Nutzer
   eingegebenen API-Schluessel, z. B. OpenRouter).

Diese Datei startet selbst keine schwere Verarbeitung -- sie waehlt nur aus
und startet die jeweils andere, bereits vorhandene Anwendung als eigenen
Prozess.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

# Wurde die Anwendung mit PyInstaller gebaut (Installer-Variante)? Dann liegen
# neben dieser EXE keine .py-Dateien der Cloud-Variante, sondern eine zweite
# EXE; und 'sys.executable' ist nicht mehr Python, sondern diese EXE selbst.
IST_GEBUNDEN = bool(getattr(sys, "frozen", False))


def _app_dir() -> Path:
    if IST_GEBUNDEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _app_dir()
LOKAL_ENTRY = APP_DIR / "lokale_windows_app" / "app.py"
API_ENTRY = APP_DIR / "protokoll_assistent_gui.py"
# Nur in der Installer-Variante vorhanden: die gebaute Cloud-Anwendung.
API_EXE = APP_DIR / "Protokoll-Assistent-Cloud.exe"

# Dieselbe Reihenfolge wie in 'lokale_windows_app/Start-Protokoll-Assistent.ps1'.
PYTHON_KANDIDATEN: tuple[list[str], ...] = (
    ["py", "-3.11"],
    ["py", "-3.10"],
    ["python3.11"],
    ["python3.10"],
    ["python"],
)

PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/"

sys.path.insert(0, str(APP_DIR))
import oberflaeche_theme as theme  # noqa: E402


def python_fuer_lokale_app() -> list[str] | None:
    """Sucht ein Python 3.10/3.11 fuer die lokale Anwendung.

    Nur fuer die Installer-Variante noetig: dort ist 'sys.executable' die
    gebaute EXE und kann 'app.py' nicht ausfuehren. Die lokale Anwendung
    richtet sich ihre eigene Umgebung ('runtime\\venv') selbst ein, braucht
    dafuer aber ein vorhandenes Python -- genau wie beim Start ueber
    'Start-Protokoll-Assistent.ps1'.

    Gibt den Aufruf als Liste zurueck (z. B. ``["py", "-3.11"]``) oder
    ``None``, wenn kein passendes Python gefunden wurde.
    """
    ohne_fenster = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for kandidat in PYTHON_KANDIDATEN:
        if shutil.which(kandidat[0]) is None:
            continue
        try:
            ergebnis = subprocess.run(
                [*kandidat, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=ohne_fenster,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        # 'py --version' schreibt je nach Version nach stdout oder stderr.
        ausgabe = f"{ergebnis.stdout} {ergebnis.stderr}"
        if re.search(r"Python 3\.(10|11)\b", ausgabe):
            return list(kandidat)
    return None


class HauptanwendungFenster:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Protokoll-Assistent")
        root.geometry("760x560")
        root.minsize(660, 480)

        self.aktuelles_theme = theme.anwenden(root)

        self._build_widgets()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self) -> None:
        kopfzeile = ttk.Frame(self.root)
        kopfzeile.pack(fill="x", padx=16, pady=(16, 0))
        ttk.Label(
            kopfzeile, text="Protokoll-Assistent", font=("Segoe UI", 18, "bold")
        ).pack(side="left")
        if theme.HAT_SV_TTK:
            self.dunkel_var = tk.BooleanVar(value=(self.aktuelles_theme == "dark"))
            ttk.Checkbutton(
                kopfzeile,
                text="Dunkles Design",
                style="Switch.TCheckbutton",
                variable=self.dunkel_var,
                command=self._theme_umschalten,
            ).pack(side="right")

        ttk.Label(
            self.root,
            text="Wie möchten Sie arbeiten?",
            font=("Segoe UI", 12),
        ).pack(anchor="w", padx=16, pady=(8, 4))

        self._build_karte(
            titel="Lokal (vollständig offline)",
            beschreibung=(
                "Transkription und Sprechertrennung laufen komplett auf diesem "
                "Computer (WhisperX + pyannote.audio). Es werden keine Audio- "
                "oder Videodaten übertragen.\n\n"
                "Beim allerersten Start richtet sich die Anwendung selbst ein: "
                "Systemtest, Empfehlung eines passenden Whisper-Modells anhand "
                "Ihrer Hardware (Sie entscheiden, welches Modell verwendet "
                "wird) und automatischer Modell-Download. Das kann je nach "
                "Internetverbindung einige Minuten dauern."
            ),
            knopf_text="Lokal starten",
            befehl=self.starte_lokal,
        )

        self._build_karte(
            titel="Schnittstelle nutzen (selbst eingerichtet)",
            beschreibung=(
                "Transkription über eine von Ihnen eingerichtete Schnittstelle "
                "(aktuell: OpenRouter). Sie geben dafür Ihren eigenen "
                "API-Schlüssel ein. Schneller einsatzbereit, es müssen keine "
                "lokalen KI-Modelle heruntergeladen werden -- die Aufnahme wird "
                "dafür zur Verarbeitung übertragen."
            ),
            knopf_text="Schnittstelle starten",
            befehl=self.starte_api,
        )

        log_frame = ttk.LabelFrame(self.root, text="Status")
        log_frame.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=6, state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        theme.text_widget_faerben(self.log_text, self.aktuelles_theme)

    def _build_karte(self, titel: str, beschreibung: str, knopf_text: str, befehl) -> None:
        karte = ttk.LabelFrame(self.root, text=titel)
        karte.pack(fill="x", padx=16, pady=8)
        ttk.Label(karte, text=beschreibung, wraplength=680, justify="left").pack(
            anchor="w", padx=10, pady=(8, 8)
        )
        button = ttk.Button(karte, text=knopf_text, command=befehl)
        if theme.HAT_SV_TTK:
            button.configure(style="Accent.TButton")
        button.pack(anchor="e", padx=10, pady=(0, 10))

    def _theme_umschalten(self) -> None:
        neues_theme = "dark" if self.dunkel_var.get() else "light"
        if theme.HAT_SV_TTK:
            theme.sv_ttk.set_theme(neues_theme)
        self.aktuelles_theme = neues_theme
        theme.text_widget_faerben(self.log_text, neues_theme)

    # --------------------------------------------------------------- Start

    def _log(self, nachricht: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", nachricht + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def starte_lokal(self) -> None:
        if not LOKAL_ENTRY.is_file():
            messagebox.showerror(
                "Nicht gefunden",
                f"Die lokale Anwendung wurde nicht gefunden:\n{LOKAL_ENTRY}",
            )
            return
        if IST_GEBUNDEN:
            python = python_fuer_lokale_app()
            if python is None:
                messagebox.showerror(
                    "Python fehlt",
                    "Fuer die lokale Anwendung wird Python 3.10 oder 3.11 "
                    "benoetigt; auf diesem Computer wurde keines gefunden.\n\n"
                    "Bitte von "
                    f"{PYTHON_DOWNLOAD_URL} installieren (beim Installieren "
                    '"Add python.exe to PATH" ankreuzen) und danach erneut '
                    "versuchen.\n\n"
                    "Die Schnittstellen-Variante laeuft auch ohne Python.",
                )
                return
            befehl = [*python, str(LOKAL_ENTRY)]
        else:
            befehl = [sys.executable, str(LOKAL_ENTRY)]
        self._starte_prozess(
            befehl,
            cwd=LOKAL_ENTRY.parent,
            beschreibung="Lokale Anwendung (WhisperX)",
        )

    def starte_api(self) -> None:
        if IST_GEBUNDEN:
            # In der Installer-Variante ist die Cloud-Anwendung eine eigene EXE.
            if not API_EXE.is_file():
                messagebox.showerror(
                    "Nicht gefunden",
                    f"Die Schnittstellen-Anwendung wurde nicht gefunden:\n{API_EXE}",
                )
                return
            self._starte_prozess(
                [str(API_EXE)],
                cwd=API_EXE.parent,
                beschreibung="Schnittstellen-Anwendung (API)",
            )
            return
        if not API_ENTRY.is_file():
            messagebox.showerror(
                "Nicht gefunden",
                f"Die Schnittstellen-Anwendung wurde nicht gefunden:\n{API_ENTRY}",
            )
            return
        self._starte_prozess(
            [sys.executable, str(API_ENTRY)],
            cwd=API_ENTRY.parent,
            beschreibung="Schnittstellen-Anwendung (API)",
        )

    def _starte_prozess(self, befehl: list[str], cwd: Path, beschreibung: str) -> None:
        try:
            subprocess.Popen(befehl, cwd=str(cwd))
        except OSError as error:
            messagebox.showerror("Fehler beim Starten", f"{beschreibung} konnte nicht gestartet werden:\n{error}")
            return
        self._log(f"{beschreibung} wird gestartet ...")


def main() -> int:
    root = tk.Tk()
    HauptanwendungFenster(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
