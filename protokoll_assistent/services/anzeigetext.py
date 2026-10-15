"""Text fuer das Display eines Aufnahmegeraets.

Die eingebauten Schriften der Geraete haben nur ASCII (keine Umlaute). Dieses Modul macht Text anzeigbar:
Umlaute werden umschrieben (ae, oe, ue, ss), typografische Zeichen ersetzt, Markdown entfernt."""

from __future__ import annotations

_ERSETZUNGEN = str.maketrans(
    {
        "\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue", "\u00c4": "Ae", "\u00d6": "Oe", "\u00dc": "Ue", "\u00df": "ss",
        "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201c": '"',
        "\u201d": '"', "\u201e": '"', "\u2026": "...", "\u2022": "-", "\u00a0": " ", "\u20ac": "EUR",
    }
)


def fuer_display(text: str) -> str:
    """Macht einen Text fuers Display des Geraets tauglich: Umlaute umschrieben, typografische Zeichen ersetzt,
    Markdown entfernt, alles Uebrige ausserhalb von ASCII wird ein ``?`` (sichtbar statt verschluckt).
    Zeilenumbrueche und Nummerierung bleiben."""
    zeilen = []
    for zeile in text.replace("\r", "").split("\n"):
        zeile = zeile.translate(_ERSETZUNGEN).replace("**", "").replace("__", "").replace("`", "")
        zeile = zeile.lstrip("#> ").rstrip()
        if zeile.startswith(("* ", "- ")):
            zeile = "- " + zeile[2:].lstrip()
        zeile = "".join(z if 32 <= ord(z) < 127 else "?" for z in zeile)
        zeilen.append(zeile)
    kompakt = "\n".join(zeilen)
    while "\n\n\n" in kompakt:
        kompakt = kompakt.replace("\n\n\n", "\n\n")
    return kompakt.strip()
