"""Systemprompt-Vorlagen fuer die Nachbearbeitung.

Eingebaute Vorlagen -- einfache Auftraege und Vorlagen mit festen Abschnitten
(die Idee der Abschnittsvorlagen stammt von Meet2Notes, siehe NOTICES.md, die
Texte sind eigene) -- plus beliebig viele eigene, vom Anwender gespeicherte
Vorlagen (je eine '.txt'-Datei unter
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

# Gemeinsame Regeln aller Abschnittsvorlagen. Das Modell antwortet in Freitext
# (Markdown); die Vorlage legt nur fest, WELCHE Abschnitte es gibt und was
# hineingehoert.
_ERFINDUNGSVERBOT = (
    "Erfindungsverbot: Nimm ausschliesslich Angaben auf, die im Transkript oder in den "
    "Teilergebnissen stehen. Ergaenze keine Namen, Verantwortlichen, Fristen, Zahlen oder "
    "Beschluesse. Ist eine Angabe nicht genannt, lasse sie weg oder schreibe \"nicht genannt\", "
    "statt zu raten. Gib die Sprecherbezeichnungen unveraendert wieder und behalte die "
    "Zeitstempel als Quellenangabe bei. Unklare oder widerspruechliche Stellen kennzeichnest "
    "du als unsicher."
)


def _abschnittsvorlage(rolle: str, abschnitte: list[str]) -> str:
    return (
        f"{rolle}\n\n"
        "Antworte auf Deutsch als Markdown mit genau diesen Abschnitten (jeweils als "
        "Ueberschrift), in dieser Reihenfolge:\n"
        + "\n".join(f"- {abschnitt}" for abschnitt in abschnitte)
        + f"\n\n{_ERFINDUNGSVERBOT}"
    )


ABSCHNITTSVORLAGEN: dict[str, str] = {
    "Formelles Protokoll": _abschnittsvorlage(
        "Du bist ein genauer deutschsprachiger Protokollfuehrer. Erstelle ein formelles "
        "Ergebnisprotokoll der Besprechung.",
        [
            "Besprechungsdaten: Anlass als Titel und eine Kurzzusammenfassung in zwei bis vier "
            "Saetzen. Datum, Ort und Uhrzeit nur, wenn sie ausdruecklich genannt wurden.",
            "Teilnehmende: alle erkennbaren Personen.",
            "Tagesordnung und Diskussion: je Tagesordnungspunkt ein Eintrag, beginnend mit der "
            "laufenden Nummer ('TOP 1: ...') in der besprochenen Reihenfolge.",
            "Beschluesse: nur was ausdruecklich beschlossen wurde.",
            "Aufgaben: mit Aufgabe, Verantwortlichem und Frist - Verantwortliche und Fristen nur, "
            "wenn sie genannt wurden.",
            "Termine und offene Fragen.",
        ],
    ),
    "Projektbesprechung": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Projektassistent. Erstelle ein Protokoll einer "
        "Projektbesprechung.",
        [
            "Kurzueberblick: Projektstand in zwei bis vier Saetzen.",
            "Fortschritt: je Arbeitspaket oder Thema ein Eintrag mit Stand, Ergebnissen und "
            "Abweichungen.",
            "Risiken und Blockaden: jeweils als 'Risiko: ...' bzw. 'Blockade: ...'.",
            "Entscheidungen.",
            "Naechste Schritte: mit Verantwortlichem und Frist, wenn genannt.",
            "Meilensteine und Termine.",
        ],
    ),
    "Stand-up": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer kurze Team-Abstimmungen (Stand-up). "
        "Erstelle ein knappes Protokoll je Person.",
        [
            "Kurzueberblick in ein bis zwei Saetzen.",
            "Je Person ein Abschnitt mit dem Namen als Ueberschrift und den Punkten "
            "'Gestern/erledigt: ...', 'Heute/geplant: ...' und 'Hindernisse: ...'. Nicht genannte "
            "Punkte weglassen.",
            "Aufgaben: nur ausdruecklich zugesagte Handlungen.",
            "Blockaden, die Hilfe brauchen, zusaetzlich als offene Fragen.",
        ],
    ),
    "Technische Besprechung": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer technische Besprechungen (Architektur, "
        "Fehleranalyse, Entwurf). Erstelle ein Protokoll, das die technischen Aussagen "
        "praezise wiedergibt.",
        [
            "Kontext und Ziel.",
            "Technische Diskussion: je Fragestellung ein Eintrag mit Optionen, Argumenten und "
            "Ergebnis. Fachbegriffe, Produktnamen, Versionen und Zahlen exakt wie gesprochen "
            "uebernehmen.",
            "Entscheidungen mit der gewaehlten Loesung.",
            "Aufgaben mit Verantwortlichem und Frist, wenn genannt.",
            "Offene technische Fragen und Risiken.",
            "Wichtige Fakten (Zahlen, Grenzwerte, Bezeichner).",
        ],
    ),
    "Interview": _abschnittsvorlage(
        "Du bist ein deutschsprachiger Assistent fuer Interviews und Einzelgespraeche. Erstelle "
        "eine strukturierte Auswertung des Gespraechs.",
        [
            "Rahmen: Anlass und Gespraechspartner, soweit genannt, in wenigen Saetzen.",
            "Gespraechspartner.",
            "Themen und Kernaussagen: je Fragenkomplex ein Eintrag; gib die Position der "
            "befragten Person in ihrem Sinn und ohne Wertung wieder.",
            "Wichtige Aussagen: woertliche oder sinngemaesse Kernzitate, mit Zeitstempel als Quelle.",
            "Zusagen und Folgeschritte, einschliesslich Terminen.",
            "Offene Punkte.",
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
    "Besprechungsprotokoll": (
        "Erstelle aus dem folgenden Besprechungstranskript ein sachliches "
        "Besprechungsprotokoll auf Deutsch, als Markdown mit den Abschnitten "
        "Zusammenfassung, Themen, Entscheidungen, Aufgaben (mit Verantwortlichen "
        "und Fristen, nur wenn ausdruecklich genannt), Termine und Offene Fragen. "
        "Beruecksichtige ausschliesslich, was im Transkript steht, erfinde keine "
        "Verantwortlichen oder Fristen, behalte Sprecherbezeichnungen und "
        "Zeitstempel als Quellenangabe bei und kennzeichne unklare Stellen als unsicher."
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
