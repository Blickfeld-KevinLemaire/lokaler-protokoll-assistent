"""Logo und Programmsymbol (Erscheinungsbild).

Die Dateien liegen in ``resources/`` und werden mit
``tools/logo_erzeugen.py`` aus der EPS-Vorlage erzeugt. Fehlt eine Datei, bleibt
die Anwendung benutzbar: Es gibt dann kein Symbol bzw. nur den Namen als Text.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

ICON_DATEI = "vermerk_icon.ico"
LOGO_DATEI = "vermerk_logo.png"
LOGO_HELL_DATEI = "vermerk_logo_hell.png"


def ressourcen_ordner() -> Path:
    """In der gebauten Anwendung liegt 'resources' im Datenordner von
    PyInstaller, im Quellcode neben diesem Paket."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def app_icon() -> QIcon:
    """Bildmarke als Fenster- und Programmsymbol (leer, wenn die Datei fehlt)."""
    pfad = ressourcen_ordner() / ICON_DATEI
    return QIcon(str(pfad)) if pfad.is_file() else QIcon()


def logo_pixmap(breite: int, hell: bool = False, geraetepixelverhaeltnis: float = 2.0) -> QPixmap | None:
    """Das grosse Logo mit der gewuenschten Breite in logischen Pixeln.

    ``hell=True`` liefert die Fassung fuer dunkle Hintergruende. Es wird mit dem
    Geraetepixelverhaeltnis hochaufgeloest skaliert, damit es auf Bildschirmen
    mit Skalierung scharf bleibt. ``None``, wenn die Datei fehlt."""
    pfad = ressourcen_ordner() / (LOGO_HELL_DATEI if hell else LOGO_DATEI)
    if not pfad.is_file():
        return None
    original = QPixmap(str(pfad))
    if original.isNull():
        return None
    pixmap = original.scaledToWidth(round(breite * geraetepixelverhaeltnis), Qt.SmoothTransformation)
    pixmap.setDevicePixelRatio(geraetepixelverhaeltnis)
    return pixmap
