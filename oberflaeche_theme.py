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
    """Wendet Schriftart und Theme auf das Fenster an, liefert das aktive Farbschema."""
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
