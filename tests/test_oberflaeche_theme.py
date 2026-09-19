"""Tests fuer das gemeinsame Erscheinungsbild (``oberflaeche_theme.py``)."""

from __future__ import annotations

import sys
import tkinter as tk

import pytest

import oberflaeche_theme as theme


def test_bevorzugtes_farbschema_ausserhalb_von_windows(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "linux")
    assert theme.bevorzugtes_farbschema() == "light"


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="winreg gibt es nur unter Windows.")
@pytest.mark.parametrize(("registry_wert", "erwartet"), [(1, "light"), (0, "dark")])
def test_bevorzugtes_farbschema_liest_registry(monkeypatch, registry_wert, erwartet):
    import winreg

    monkeypatch.setattr(theme.sys, "platform", "win32")
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: object())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *a: (registry_wert, 0))
    assert theme.bevorzugtes_farbschema() == erwartet


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="winreg gibt es nur unter Windows.")
def test_bevorzugtes_farbschema_faellt_bei_registry_fehler_zurueck(monkeypatch):
    import winreg

    def werfen(*_a, **_k):
        raise OSError("kein Zugriff")

    monkeypatch.setattr(theme.sys, "platform", "win32")
    monkeypatch.setattr(winreg, "OpenKey", werfen)
    assert theme.bevorzugtes_farbschema() == "light"


def test_schriftart_einrichten(tk_wurzel):
    theme.schriftart_einrichten(tk_wurzel)  # darf nicht werfen
    import tkinter.font as tkfont

    assert tkfont.nametofont("TkDefaultFont").cget("family") == "Segoe UI"


def test_schriftart_einrichten_uebersteht_tcl_fehler(tk_wurzel, monkeypatch):
    import tkinter.font as tkfont

    def werfen(_name):
        raise tk.TclError("kein solcher Font")

    monkeypatch.setattr(tkfont, "nametofont", werfen)
    theme.schriftart_einrichten(tk_wurzel)  # darf nicht werfen


def test_anwenden_liefert_gewaehltes_farbschema(tk_wurzel):
    assert theme.anwenden(tk_wurzel, "dark") == "dark"


def test_anwenden_ohne_sv_ttk_nutzt_clam(tk_wurzel, monkeypatch):
    monkeypatch.setattr(theme, "HAT_SV_TTK", False)
    assert theme.anwenden(tk_wurzel, "light") == "light"


def test_anwenden_uebersteht_fehlendes_clam_theme(tk_wurzel, monkeypatch):
    from tkinter import ttk

    monkeypatch.setattr(theme, "HAT_SV_TTK", False)

    class _Style:
        def __init__(self, _root):
            pass

        def theme_use(self, _name):
            raise tk.TclError("kein clam")

    monkeypatch.setattr(ttk, "Style", _Style)
    assert theme.anwenden(tk_wurzel, "light") == "light"


def test_anwenden_ohne_farbschema_fragt_system(tk_wurzel, monkeypatch):
    monkeypatch.setattr(theme, "bevorzugtes_farbschema", lambda: "dark")
    assert theme.anwenden(tk_wurzel) == "dark"


@pytest.mark.parametrize("farbschema", ["light", "dark", "unbekannt"])
def test_text_widget_faerben(tk_wurzel, farbschema):
    widget = tk.Text(tk_wurzel)
    theme.text_widget_faerben(widget, farbschema)
    erwartet = theme.TEXT_FARBEN.get(farbschema, theme.TEXT_FARBEN["light"])
    assert widget.cget("background") == erwartet["bg"]
    assert widget.cget("foreground") == erwartet["fg"]
    assert str(widget.cget("relief")) == "flat"
