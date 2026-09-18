"""Einrichtungsfenster fuer den Protokoll-Assistenten (Windows).

Prueft/erledigt die Schritte 2-4 aus der Installationsanleitung (Python,
FFmpeg, lokales KI-Modell) und legt am Ende eine Desktop-Verknuepfung mit
Icon fuer den Start der eigentlichen Anwendung an (Schritt 5). Schritt 1
(Projekt herunterladen) erledigt Protokoll-Assistent-Einrichten.bat, bevor
dieses Fenster ueberhaupt startet.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protokoll_assistent_gui as gui  # find_ffmpeg(), FFMPEG_SUCHPFADE, DEFAULT_LOCAL_MODEL
import oberflaeche_theme as theme

APP_DIR = Path(__file__).resolve().parent
IST_WINDOWS = sys.platform.startswith("win")

FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html"
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/"


def check_python() -> tuple[bool, str]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return True, f"Python {version} gefunden."
    return False, f"Python {version} gefunden - bitte auf 3.10 oder neuer aktualisieren."


def find_ollama() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidate = Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def create_desktop_shortcut(app_dir: Path, log: Callable[[str], None]) -> Path:
    if not IST_WINDOWS:
        raise RuntimeError("Die Desktop-Verknuepfung kann nur unter Windows erstellt werden.")

    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    shortcut_path = desktop / "Protokoll-Assistent.lnk"
    target = app_dir / "Protokoll-Assistent-Starten.bat"
    icon_source = shutil.which("pythonw") or shutil.which("python") or sys.executable

    powershell_befehl = (
        "$WshShell = New-Object -ComObject WScript.Shell; "
        f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); '
        f'$Shortcut.TargetPath = "{target}"; '
        f'$Shortcut.WorkingDirectory = "{app_dir}"; '
        f'$Shortcut.IconLocation = "{icon_source},0"; '
        '$Shortcut.Description = "Lokalen Protokoll-Assistenten starten"; '
        "$Shortcut.Save()"
    )
    log("Erstelle Desktop-Verknuepfung ueber PowerShell ...")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", powershell_befehl],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell konnte die Verknuepfung nicht erstellen.")
    return shortcut_path


class EinrichtungsFenster:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Protokoll-Assistent - Einrichtung")
        root.geometry("760x640")
        root.minsize(640, 520)

        self.aktuelles_theme = theme.anwenden(root)

        self.message_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.status_vars: dict[str, tk.StringVar] = {}

        self._build_widgets()
        self._poll_queue()
        self.root.after(200, self._pruefe_alles)

    # ------------------------------------------------------------------ UI

    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}

        ttk.Label(
            self.root,
            text=(
                "Dieses Fenster prueft die Voraussetzungen fuer den "
                "Protokoll-Assistenten und richtet sie bei Bedarf ein."
            ),
            wraplength=720,
            justify="left",
        ).pack(fill="x", **pad)

        # Erscheinungsbild (optional)
        design_frame = ttk.LabelFrame(self.root, text="Erscheinungsbild (optional)")
        design_frame.pack(fill="x", **pad)
        self.status_vars["design"] = tk.StringVar(value="wird geprueft ...")
        ttk.Label(design_frame, textvariable=self.status_vars["design"], wraplength=700).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        row_design = ttk.Frame(design_frame)
        row_design.pack(fill="x", padx=8, pady=6)
        ttk.Button(row_design, text="Erneut pruefen", command=self._pruefe_design).pack(
            side="left"
        )
        self.design_button = ttk.Button(
            row_design, text="Modernes Design installieren", command=self._design_installieren
        )
        self.design_button.pack(side="left", padx=8)

        # Schritt 1 - Projekt
        step1 = ttk.LabelFrame(self.root, text="Schritt 1: Projekt")
        step1.pack(fill="x", **pad)
        self.status_vars["projekt"] = tk.StringVar(value=f"Projektordner: {APP_DIR}")
        ttk.Label(step1, textvariable=self.status_vars["projekt"], wraplength=700).pack(
            anchor="w", padx=8, pady=6
        )

        # Schritt 2 - Python
        step2 = ttk.LabelFrame(self.root, text="Schritt 2: Python")
        step2.pack(fill="x", **pad)
        self.status_vars["python"] = tk.StringVar(value="wird geprueft ...")
        ttk.Label(step2, textvariable=self.status_vars["python"]).pack(anchor="w", padx=8, pady=6)

        # Schritt 3 - FFmpeg
        step3 = ttk.LabelFrame(self.root, text="Schritt 3: FFmpeg (fuer Video/grosse Audiodateien)")
        step3.pack(fill="x", **pad)
        self.status_vars["ffmpeg"] = tk.StringVar(value="wird geprueft ...")
        ttk.Label(step3, textvariable=self.status_vars["ffmpeg"], wraplength=700).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        row3 = ttk.Frame(step3)
        row3.pack(fill="x", padx=8, pady=6)
        ttk.Button(row3, text="Erneut pruefen", command=self._pruefe_ffmpeg).pack(side="left")
        ttk.Button(
            row3, text="Download-Seite oeffnen", command=lambda: webbrowser.open(FFMPEG_DOWNLOAD_URL)
        ).pack(side="left", padx=8)
        ttk.Label(
            step3,
            text="Nach dem Herunterladen bitte so entpacken, dass ffmpeg.exe unter C:\\ffmpeg\\bin\\ffmpeg.exe liegt.",
            foreground="#555555",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        # Schritt 4 - Ollama
        step4 = ttk.LabelFrame(self.root, text="Schritt 4: Lokales KI-Modell (Ollama)")
        step4.pack(fill="x", **pad)
        self.status_vars["ollama"] = tk.StringVar(value="wird geprueft ...")
        ttk.Label(step4, textvariable=self.status_vars["ollama"], wraplength=700).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        row4 = ttk.Frame(step4)
        row4.pack(fill="x", padx=8, pady=6)
        ttk.Button(row4, text="Erneut pruefen", command=self._pruefe_ollama).pack(side="left")
        ttk.Button(
            row4, text="Download-Seite oeffnen", command=lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL)
        ).pack(side="left", padx=8)
        self.pull_button = ttk.Button(
            row4,
            text=f"Modell laden ({gui.DEFAULT_LOCAL_MODEL})",
            command=self._modell_laden,
        )
        self.pull_button.pack(side="left", padx=8)

        # Schritt 5 - Verknuepfung
        step5 = ttk.LabelFrame(self.root, text="Schritt 5: Start-Icon")
        step5.pack(fill="x", **pad)
        ttk.Button(
            step5, text="Desktop-Verknuepfung erstellen", command=self._verknuepfung_erstellen
        ).pack(side="left", padx=8, pady=6)
        ttk.Button(
            step5, text="Anwendung jetzt starten", command=self._anwendung_starten
        ).pack(side="left", padx=8, pady=6)

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Ablauf")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)
        theme.text_widget_faerben(self.log_text, self.aktuelles_theme)

    # --------------------------------------------------------------- Logik

    def _log(self, message: str) -> None:
        self.message_queue.put(("log", message))

    def _append_log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _pruefe_alles(self) -> None:
        ok, text = check_python()
        self.status_vars["python"].set(("OK: " if ok else "Problem: ") + text)
        if not ok:
            webbrowser.open(PYTHON_DOWNLOAD_URL)
        self._pruefe_design()
        self._pruefe_ffmpeg()
        self._pruefe_ollama()

    def _pruefe_design(self) -> None:
        if theme.HAT_SV_TTK:
            self.status_vars["design"].set(
                "OK: Modernes Design (sv-ttk) ist installiert."
            )
            self.design_button.config(state="disabled")
        else:
            self.status_vars["design"].set(
                "Nicht installiert. Die Anwendung laeuft auch so, dann mit dem "
                "einfachen Standard-Design."
            )
            self.design_button.config(state="normal")

    def _design_installieren(self) -> None:
        self.design_button.config(state="disabled")
        threading.Thread(target=self._design_installieren_hintergrund, daemon=True).start()

    def _design_installieren_hintergrund(self) -> None:
        self._log("Installiere modernes Design (sv-ttk) ...")
        try:
            prozess = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--quiet", "sv-ttk"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert prozess.stdout is not None
            for zeile in prozess.stdout:
                self._log(zeile.rstrip())
            prozess.wait()
            if prozess.returncode == 0:
                self._log("Modernes Design installiert. Bitte Fenster neu starten.")
            else:
                self._log(f"FEHLER: pip endete mit Code {prozess.returncode}.")
        except OSError as error:
            self._log(f"FEHLER bei der Installation: {error}")
        finally:
            self.message_queue.put(("enable_design_button", None))

    def _pruefe_ffmpeg(self) -> None:
        pfad = gui.find_ffmpeg()
        if pfad:
            self.status_vars["ffmpeg"].set(f"OK: FFmpeg gefunden unter {pfad}")
        else:
            self.status_vars["ffmpeg"].set(
                "Nicht gefunden. Fuer reine, kleine MP3-Aufnahmen nicht zwingend noetig."
            )

    def _pruefe_ollama(self) -> None:
        pfad = find_ollama()
        if pfad:
            self.status_vars["ollama"].set(f"OK: Ollama gefunden unter {pfad}")
            self.pull_button.config(state="normal")
        else:
            self.status_vars["ollama"].set(
                "Nicht gefunden. Ohne Ollama kann das Transkript nicht lokal weiterverarbeitet werden."
            )
            self.pull_button.config(state="disabled")

    def _modell_laden(self) -> None:
        ollama_pfad = find_ollama()
        if not ollama_pfad:
            messagebox.showwarning("Ollama fehlt", "Bitte zuerst Ollama installieren.")
            return
        self.pull_button.config(state="disabled")
        threading.Thread(
            target=self._modell_laden_hintergrund, args=(ollama_pfad,), daemon=True
        ).start()

    def _modell_laden_hintergrund(self, ollama_pfad: str) -> None:
        modell = gui.DEFAULT_LOCAL_MODEL
        self._log(f"Lade Modell '{modell}' herunter ('ollama pull {modell}') ...")
        try:
            prozess = subprocess.Popen(
                [ollama_pfad, "pull", modell],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert prozess.stdout is not None
            for zeile in prozess.stdout:
                self._log(zeile.rstrip())
            prozess.wait()
            if prozess.returncode == 0:
                self._log(f"Modell '{modell}' ist bereit.")
            else:
                self._log(f"FEHLER: 'ollama pull {modell}' endete mit Code {prozess.returncode}.")
        except OSError as error:
            self._log(f"FEHLER beim Ausfuehren von Ollama: {error}")
        finally:
            self.message_queue.put(("enable_pull", None))

    def _verknuepfung_erstellen(self) -> None:
        try:
            pfad = create_desktop_shortcut(APP_DIR, self._log)
            self._log(f"Verknuepfung erstellt: {pfad}")
            messagebox.showinfo(
                "Fertig", f"Verknuepfung wurde auf dem Desktop angelegt:\n{pfad}"
            )
        except Exception as error:  # noqa: BLE001 - Fehler soll dem Nutzer angezeigt werden
            self._log(f"FEHLER: {error}")
            messagebox.showerror("Fehler", str(error))

    def _anwendung_starten(self) -> None:
        skript = APP_DIR / "hauptanwendung.py"
        try:
            subprocess.Popen([sys.executable, str(skript)], cwd=str(APP_DIR))
        except OSError as error:
            messagebox.showerror("Fehler", f"Anwendung konnte nicht gestartet werden: {error}")

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "enable_pull":
                    self.pull_button.config(state="normal")
                elif kind == "enable_design_button":
                    self._pruefe_design()
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def main() -> int:
    root = tk.Tk()
    EinrichtungsFenster(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
