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

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

APP_DIR = Path(__file__).resolve().parent
LOKAL_ENTRY = APP_DIR / "lokale_windows_app" / "app.py"
API_ENTRY = APP_DIR / "protokoll_assistent_gui.py"

sys.path.insert(0, str(APP_DIR))
import oberflaeche_theme as theme  # noqa: E402


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
        self._starte_prozess(
            [sys.executable, str(LOKAL_ENTRY)],
            cwd=LOKAL_ENTRY.parent,
            beschreibung="Lokale Anwendung (WhisperX)",
        )

    def starte_api(self) -> None:
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
