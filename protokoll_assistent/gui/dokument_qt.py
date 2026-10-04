"""PDF und OpenDocument aus dem HTML-Text des Exportdienstes, mit Qt.

Qt bringt beides mit (``QPdfWriter``, ``QTextDocumentWriter``) -- eine
zusaetzliche PDF-Bibliothek ist deshalb nicht noetig. Die Funktionen haben die
Form ``(html_text, zielpfad)``, die ``services.dokument_export_service`` als
``schreiber`` erwartet.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument, QTextDocumentWriter

from protokoll_assistent.services.dokument_export_service import Schreiber


def _dokument(html_text: str) -> QTextDocument:
    dokument = QTextDocument()
    dokument.setHtml(html_text)
    return dokument


def schreibe_pdf(html_text: str, ziel: Path) -> None:
    schreiber = QPdfWriter(str(ziel))
    schreiber.setPageSize(QPageSize(QPageSize.A4))
    schreiber.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Millimeter)
    _dokument(html_text).print_(schreiber)


def schreibe_odt(html_text: str, ziel: Path) -> None:
    # Das Format wird ausdruecklich genannt: Der Zielpfad ist ein Arbeitsname
    # mit Endung '.tmp', an der Qt es nicht erkennen koennte.
    schreiber = QTextDocumentWriter(str(ziel), QByteArray(b"ODF"))
    if not schreiber.write(_dokument(html_text)):
        raise RuntimeError("Die OpenDocument-Datei konnte nicht geschrieben werden.")


SCHREIBER: dict[str, Schreiber] = {"pdf": schreibe_pdf, "odt": schreibe_odt}
