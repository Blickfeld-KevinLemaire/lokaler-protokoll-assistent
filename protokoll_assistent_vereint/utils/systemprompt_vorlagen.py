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


# Unter Windows in Dateinamen verboten. Der Vorlagenname IST der Dateiname
# (ohne '.txt'), weil 'eigene_vorlagen()' ihn aus dem Dateinamen zurueckliest
# - deshalb wird ein unzulaessiger Name abgelehnt und nicht stillschweigend
# umgeschrieben: sonst hiesse die gespeicherte Vorlage plaetzlich anders als
# eingegeben.
_VERBOTENE_ZEICHEN = '<>:"/\\|?*'


def name_pruefen(name: str) -> None:
    """Wirft 'ValueError', wenn aus dem Namen kein Dateiname werden kann.

    Ohne diese Pruefung schlaegt erst das Schreiben fehl - und zwar mit
    einem 'OSError' aus den Tiefen von pathlib. Gerade naheliegende Namen
    fuer Besprechungsvorlagen sind betroffen ("Wer macht was?",
    "Kundengespraech A/B")."""
    if not name.strip():
        raise ValueError("Bitte einen Namen für die Vorlage eingeben.")
    gefunden = sorted({zeichen for zeichen in name if zeichen in _VERBOTENE_ZEICHEN})
    if gefunden:
        raise ValueError(
            f"Der Name enthält Zeichen, die in einem Dateinamen nicht erlaubt sind: "
            f"{' '.join(gefunden)}\n\nBitte einen Namen ohne {_VERBOTENE_ZEICHEN} wählen."
        )


def vorlage_speichern(name: str, text: str) -> None:
    """Speichert eine neue eigene Vorlage. Wirft 'ValueError', wenn der Name
    einer eingebauten Vorlage entspricht (die bleiben unveraenderlich) oder
    als Dateiname nicht zulaessig ist."""
    if name in EINGEBAUTE_VORLAGEN:
        raise ValueError(f"'{name}' ist eine eingebaute Vorlage und kann nicht ersetzt werden.")
    name_pruefen(name)
    ziel = get_systemprompt_vorlagen_dir() / f"{name}.txt"
    ziel.write_text(text, encoding="utf-8")
