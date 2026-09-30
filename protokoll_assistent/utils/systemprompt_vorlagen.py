"""Systemprompt-Vorlagen fuer die Nachbearbeitung.

Drei einfache und fuenf ausfuehrliche, eingebaute Vorlagen mit festen
Abschnitten (die einfachen wortgleich mit den bisherigen
'SYSTEMPROMPT_VORLAGEN' in 'protokoll_assistent_gui.py'; die Idee der
Abschnittsvorlagen stammt von Meet2Notes, siehe NOTICES.md, die Texte sind
eigene) plus beliebig viele eigene, vom Anwender gespeicherte Vorlagen (je eine '.txt'-Datei unter
'get_systemprompt_vorlagen_dir()'). Wird sowohl vom Hauptfenster (Auswahl
und Bearbeitung fuer den aktuellen Lauf) als auch indirekt von den
Einstellungen benutzt."""

from __future__ import annotations

from protokoll_assistent.utils.paths import get_systemprompt_vorlagen_dir

STANDARD_SYSTEMPROMPT = (
    "Fasse das folgende Besprechungstranskript in klarer, gut strukturierter "
    "Form zusammen. Nenne die wichtigsten Themen, getroffene Entscheidungen "
    "und offene Aufgaben mit Verantwortlichen, falls erkennbar."
)

# Gemeinsame Regeln aller Abschnittsvorlagen. Die JSON-Struktur selbst haengt
# 'protocol_service.build_stage3_prompt' an; die Vorlagen sagen nur, WAS in
# welches Feld gehoert.
_ERFINDUNGSVERBOT = (
    "Erfindungsverbot: Nimm ausschliesslich Angaben auf, die im Transkript oder in den "
    "Teilanalysen stehen. Ergaenze keine Namen, Verantwortlichen, Fristen, Zahlen oder "
    "Beschluesse. Ist eine Angabe nicht genannt, lasse das Feld leer, statt zu raten. "
    "Gib die Sprecherbezeichnungen unveraendert wieder und behalte die Zeitstempel als "
    "Quellenangabe bei. Unklare oder widerspruechliche Stellen gehoeren in "
    "'unsichere_transkriptstellen'."
)


def _abschnittsvorlage(rolle: str, abschnitte: list[str]) -> str:
    return (
        f"{rolle}\n\n"
        "Das Protokoll hat feste Abschnitte. Sie entsprechen den Feldern der JSON-Struktur:\n"
        + "\n".join(f"- {abschnitt}" for abschnitt in abschnitte)
        + f"\n\n{_ERFINDUNGSVERBOT}"
    )


ABSCHNITTSVORLAGEN: dict[str, str] = {
    "Formelles Protokoll": _abschnittsvorlage(
        "Du bist ein genauer deutschsprachiger Protokollfuehrer. Erstelle ein formelles "
        "Ergebnisprotokoll der Besprechung.",
        [
            "Besprechungsdaten: 'titel' nennt den Anlass; 'kurzzusammenfassung' hat zwei bis vier "
            "Saetze. Datum, Ort und Uhrzeit nur, wenn sie ausdruecklich genannt wurden.",
            "Teilnehmende: 'teilnehmende_oder_sprecher' mit allen erkennbaren Personen.",
            "Tagesordnung und Diskussion: 'themen', je Tagesordnungspunkt ein Eintrag; 'thema' "
            "beginnt mit der laufenden Nummer ('TOP 1: ...') in der besprochenen Reihenfolge.",
            "Beschluesse: 'entscheidungen', nur was ausdruecklich beschlossen wurde.",
            "Aufgaben: 'aufgaben' mit Aufgabe, Verantwortlich und Frist - Verantwortliche und "
            "Fristen nur, wenn sie genannt wurden.",
            "Termine und offene Fragen: 'termine' und 'offene_fragen'.",
        ],
    ),
    "Projektbesprechung": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Projektassistent. Erstelle ein Protokoll einer "
        "Projektbesprechung.",
        [
            "Kurzueberblick: 'kurzzusammenfassung' nennt Projektstand in zwei bis vier Saetzen.",
            "Fortschritt: 'themen', je Arbeitspaket oder Thema ein Eintrag; 'kernaussagen' "
            "beschreiben Stand, Ergebnisse und Abweichungen.",
            "Risiken und Blockaden: als eigene Eintraege in 'themen' mit 'thema' "
            "'Risiko: ...' bzw. 'Blockade: ...'.",
            "Entscheidungen: 'entscheidungen'.",
            "Naechste Schritte: 'aufgaben' mit Verantwortlich und Frist, wenn genannt.",
            "Meilensteine und Termine: 'termine'.",
        ],
    ),
    "Stand-up": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer kurze Team-Abstimmungen (Stand-up). "
        "Erstelle ein knappes Protokoll je Person.",
        [
            "Kurzueberblick: 'kurzzusammenfassung' in ein bis zwei Saetzen.",
            "Je Person: 'themen', ein Eintrag pro Sprecher; 'thema' ist der Name, 'kernaussagen' "
            "trennen nach 'Gestern/erledigt: ...', 'Heute/geplant: ...' und 'Hindernisse: ...'. "
            "Nicht genannte Punkte weglassen.",
            "Aufgaben: 'aufgaben' nur fuer ausdruecklich zugesagte Handlungen.",
            "Blockaden, die Hilfe brauchen: zusaetzlich in 'offene_fragen'.",
        ],
    ),
    "Technische Besprechung": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer technische Besprechungen (Architektur, "
        "Fehleranalyse, Entwurf). Erstelle ein Protokoll, das die technischen Aussagen "
        "praezise wiedergibt.",
        [
            "Kontext und Ziel: 'kurzzusammenfassung'.",
            "Technische Diskussion: 'themen', je Fragestellung ein Eintrag; 'kernaussagen' nennen "
            "Optionen, Argumente und Ergebnis. Fachbegriffe, Produktnamen, Versionen und Zahlen "
            "exakt wie gesprochen uebernehmen.",
            "Entscheidungen: 'entscheidungen' mit der gewaehlten Loesung.",
            "Aufgaben: 'aufgaben' mit Verantwortlich und Frist, wenn genannt.",
            "Offene technische Fragen und Risiken: 'offene_fragen'.",
            "Wichtige Fakten (Zahlen, Grenzwerte, Bezeichner): 'wichtige_fakten'.",
        ],
    ),
    "Interview": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer Interviews und Einzelgespraeche. Erstelle "
        "eine strukturierte Auswertung des Gespraechs.",
        [
            "Rahmen: 'titel' und 'kurzzusammenfassung' nennen Anlass und Gespraechspartner, "
            "soweit genannt.",
            "Gespraechspartner: 'teilnehmende_oder_sprecher'.",
            "Themen und Kernaussagen: 'themen', je Fragenkomplex ein Eintrag; 'kernaussagen' "
            "geben die Position der befragten Person wieder, in ihrem Sinn und ohne Wertung.",
            "Wichtige Aussagen: woertliche oder sinngemaesse Kernzitate in 'wichtige_fakten', "
            "mit Zeitstempel als Quelle.",
            "Zusagen und Folgeschritte: 'aufgaben' und 'termine'.",
            "Offene Punkte: 'offene_fragen'.",
        ],
    ),
}

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
    **ABSCHNITTSVORLAGEN,
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
