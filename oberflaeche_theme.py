"""Gemeinsames modernes Erscheinungsbild fuer alle Fenster.

Nutzt das Theme-Paket "sv-ttk" (Windows-11-artiger Fluent-Stil, Light/Dark),
faellt aber sauber auf ein aufgeraeumtes Standard-ttk-Theme zurueck, falls
das Paket (noch) nicht installiert ist - die Anwendung bleibt so immer
lauffaehig, auch ohne dieses Zusatzpaket.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

try:
    import sv_ttk

    HAT_SV_TTK = True
except ImportError:
    sv_ttk = None  # type: ignore[assignment]
    HAT_SV_TTK = False

TEXT_FARBEN = {
    "light": {"bg": "#fafafa", "fg": "#1a1a1a", "insertbackground": "#1a1a1a"},
    "dark": {"bg": "#1c1c1c", "fg": "#f0f0f0", "insertbackground": "#f0f0f0"},
}

# Dieselbe Akzentfarbe wie in 'lokale_windows_app/gui/theme.py' (ACCENT).
# Bewusst hier noch einmal eingetragen statt importiert: die beiden
# Anwendungen teilen sich nichts ausser der Sprache (siehe CLAUDE.md) - nur
# der Farbwert soll gleich aussehen, nicht der Code gekoppelt sein.
AKZENTFARBE = "#2f6fed"


def _falls_ohne_sv_ttk_einrichten(style: ttk.Style) -> None:
    """Faerbt das 'clam'-Fallback-Theme in derselben Akzentfarbe wie die
    lokale Variante ein.

    Ist sv-ttk installiert (der Normalfall - es steht in requirements.txt),
    greift diese Funktion nie: sv-ttk zeichnet seine Elemente ueber fest
    eingefaerbte Bilddateien, deren Farbe sich nicht per 'ttk.Style'
    ueberschreiben laesst. Ohne sv-ttk ist 'clam' dagegen ein reines
    Farb-Theme - hier lässt sich dieselbe Akzentfarbe wie im lokalen
    Hauptfenster tatsaechlich anwenden.
    """
    style.configure(
        "Accent.TButton",
        background=AKZENTFARBE,
        foreground="#ffffff",
        padding=(8, 4),
    )
    style.map("Accent.TButton", background=[("active", "#255bc4"), ("disabled", "#a9c1f2")])


def bevorzugtes_farbschema() -> str:
    """Liest unter Windows das aktuell eingestellte App-Farbschema aus."""
    if sys.platform.startswith("win"):
        try:
            import winreg

            schluessel = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            wert, _ = winreg.QueryValueEx(schluessel, "AppsUseLightTheme")
            return "light" if wert else "dark"
        except OSError:
            pass
    return "light"


def schriftart_einrichten(root: tk.Tk) -> None:
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
        try:
            schrift = tkfont.nametofont(name)
            schrift.configure(family="Segoe UI", size=10)
        except tk.TclError:
            pass


def anwenden(root: tk.Tk, farbschema: str | None = None) -> str:
    """Wendet Schriftart und Theme auf das Fenster an, liefert das aktive Farbschema.

    Der Stil 'Accent.TButton' steht danach in jedem Fall zur Verfuegung -
    mit sv-ttk ist es dessen eigener, fest eingefaerbter Stil (siehe
    '_falls_ohne_sv_ttk_einrichten'), ohne sv-ttk wird er hier passend zur
    lokalen Variante eingerichtet. Aufrufer koennen ihn also unabhaengig
    davon setzen, ob sv-ttk installiert ist.
    """
    schriftart_einrichten(root)
    gewaehlt = farbschema or bevorzugtes_farbschema()
    if HAT_SV_TTK:
        sv_ttk.set_theme(gewaehlt)
    else:
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        _falls_ohne_sv_ttk_einrichten(style)
    return gewaehlt


def text_widget_faerben(widget: tk.Text, farbschema: str) -> None:
    """Faerbt ein einfaches tk.Text-Widget passend zum ttk-Theme ein.

    ttk-Themes wie sv-ttk wirken nur auf ttk-Widgets; Text-Widgets (auch in
    ScrolledText) sind klassische tk-Widgets und muessen manuell nachgezogen
    werden, damit z. B. im Dunkelmodus kein weisses Feld stehen bleibt.
    """
    farben = TEXT_FARBEN.get(farbschema, TEXT_FARBEN["light"])
    widget.configure(
        background=farben["bg"],
        foreground=farben["fg"],
        insertbackground=farben["insertbackground"],
        relief="flat",
        borderwidth=1,
        highlightthickness=0,
    )
