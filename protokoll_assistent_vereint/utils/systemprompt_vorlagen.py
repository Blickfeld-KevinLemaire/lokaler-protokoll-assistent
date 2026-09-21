"""Systemprompt-Vorlagen fuer die Nachbearbeitung.

Drei feste, eingebaute Vorlagen (wortgleich mit den bisherigen
'SYSTEMPROMPT_VORLAGEN' in 'protokoll_assistent_gui.py') plus beliebig viele
eigene, vom Anwender gespeicherte Vorlagen (je eine '.txt'-Datei unter
'get_systemprompt_vorlagen_dir()'). Wird sowohl vom Hauptfenster (Auswahl
und Bearbeitung fuer den aktuellen Lauf) als auch indirekt von den
Einstellungen benutzt."""

from __future__ import annotations

from protokoll_assistent_vereint.utils.paths import get_systemprompt_vorlagen_dir

STANDARD_SYSTEMPROMPT = (
    "Fasse das folgende Besprechungstranskript in klarer, gut strukturierter "
    "Form zusammen. Nenne die wichtigsten Themen, getroffene Entscheidungen "
    "und offene Aufgaben mit Verantwortlichen, falls erkennbar."
)

EINGEBAUTE_VORLAGEN: dict[str, str] = {
    "Zusammenfassung": STANDARD_SYSTEMPROMPT,
    "Agenda": (
        "Erstelle aus dem folgenden Besprechungstranskript eine strukturierte "
        "Agenda im Nachhinein: Liste die behandelten Themen in der besprochenen "
        "Reihenfolge auf, mit je 1-2 Saetzen Inhalt."
    ),
    "Prioritaetenliste": (
        "Erstelle aus dem folgenden Besprechungstranskript eine priorisierte "
        "Aufgabenliste. Sortiere nach Dringlichkeit, nenne wenn moeglich "
        "Verantwortliche und Termine."
    ),
}


def eigene_vorlagen() -> dict[str, str]:
    vorlagen: dict[str, str] = {}
    for pfad in sorted(get_systemprompt_vorlagen_dir().glob("*.txt")):
        vorlagen[pfad.stem] = pfad.read_text(encoding="utf-8")
    return vorlagen


def alle_vorlagen() -> dict[str, str]:
    vorlagen = dict(EINGEBAUTE_VORLAGEN)
    vorlagen.update(eigene_vorlagen())
    return vorlagen


def vorlage_speichern(name: str, text: str) -> None:
    """Speichert eine neue eigene Vorlage. Wirft 'ValueError', wenn der Name
    einer eingebauten Vorlage entspricht - die bleiben unveraenderlich."""
    if name in EINGEBAUTE_VORLAGEN:
        raise ValueError(f"'{name}' ist eine eingebaute Vorlage und kann nicht ersetzt werden.")
    ziel = get_systemprompt_vorlagen_dir() / f"{name}.txt"
    ziel.write_text(text, encoding="utf-8")
