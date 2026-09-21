"""Einheitliches, modernes Erscheinungsbild fuer die gesamte Anwendung.

Wird einmal beim Start auf die ``QApplication`` angewendet
(``apply_theme``). Verwendet den plattformunabhaengigen "Fusion"-Stil als
Grundlage und ergaenzt ein flaches, modernes Farbschema per Stylesheet
(QSS) -- angelehnt an gaengige moderne Desktop-Anwendungen (klare Karten,
runde Ecken, eine Akzentfarbe fuer primaere Aktionen).
"""

from __future__ import annotations

ACCENT = "#2f6fed"
ACCENT_HOVER = "#255bc4"
ACCENT_TEXT = "#ffffff"
BACKGROUND = "#f4f6f9"
SURFACE = "#ffffff"
BORDER = "#dde1e8"
TEXT_PRIMARY = "#1c1e21"
TEXT_SECONDARY = "#5b6270"
SUCCESS = "#1f8a4c"
SUCCESS_BG = "#eaf6ee"
SUCCESS_BORDER = "#bfe6cc"
DANGER = "#c0392b"

APP_QSS = f"""
QWidget {{
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    color: {TEXT_PRIMARY};
}}

QMainWindow, QDialog {{
    background-color: {BACKGROUND};
}}

QWidget#WizardRoot, QWidget#WizardSidebar, QWidget#WizardPage {{
    background-color: {BACKGROUND};
}}

QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {BACKGROUND};
}}
QPushButton:disabled {{
    color: #9aa0a8;
}}

QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    border: none;
    color: {ACCENT_TEXT};
    font-weight: 600;
    padding: 10px 24px;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#PrimaryButton:disabled {{
    background-color: #a9c1f2;
    color: #eef2fc;
}}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QListWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
    selection-color: white;
}}

/* Ohne Mindestbreite schrumpft ein QComboBox in einem QFormLayout auf
   seinen aktuellen Eintrag - bei langen Modellbezeichnungen war davon oft
   nur ein Bruchteil zu lesen. */
QComboBox {{
    min-width: 300px;
    min-height: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: white;
    outline: none;
}}

QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {SURFACE};
    text-align: center;
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}

QTableWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background-color: {BACKGROUND};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-weight: 600;
}}

QLabel#PrivacyBanner {{
    background-color: {SUCCESS_BG};
    color: {SUCCESS};
    border: 1px solid {SUCCESS_BORDER};
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 600;
}}

QLabel#StepIndicator {{
    color: {TEXT_SECONDARY};
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QLabel#StepIndicatorActive {{
    color: {ACCENT};
    font-weight: 700;
}}

QLabel#PageTitle {{
    font-size: 17pt;
    font-weight: 700;
}}
QLabel#PageSubtitle {{
    color: {TEXT_SECONDARY};
}}

QScrollBar:vertical {{
    width: 10px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
