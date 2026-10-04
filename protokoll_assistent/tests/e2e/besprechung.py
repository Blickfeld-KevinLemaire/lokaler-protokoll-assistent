"""Die gespielte Besprechung fuer die Ende-zu-Ende-Tests.

Drei Personen, eine Entscheidung mit Datum und Betrag, zwei Aufgaben mit
Verantwortlichen und Fristen, eine offene Frage und ein Folgetermin. Weil der
Inhalt feststeht, koennen die Tests pruefen, ob genau diese Fakten im
Transkript, im Protokoll und in den Antworten des Chatbots ankommen.

Die Stimmen sind die deutschen Windows-Stimmen (Hedda, Stefan, Katja); die Texte
stehen deshalb mit Umlauten, sonst spraeche die Stimme 'laeuft'. Daraus
entsteht bei Bedarf eine WAV-Datei (siehe ``conftest.besprechung_wav``).
"""

from __future__ import annotations

import json
from pathlib import Path

# (Sprecher-ID, Anzeigename, Windows-Stimme, Text)
BEITRAEGE: list[tuple[str, str, str, str]] = [
    (
        "SPEAKER_00",
        "Anna Becker",
        "Microsoft Hedda",
        "Guten Morgen zusammen. Ich bin Anna Becker und leite das Projekt. Heute geht es um den Umzug "
        "der Kundendatenbank auf den neuen Server. Thomas, wie ist der technische Stand?",
    ),
    (
        "SPEAKER_01",
        "Thomas Wagner",
        "Microsoft Stefan",
        "Hier ist Thomas Wagner. Die neue Hardware ist eingerichtet, die Datensicherung läuft. "
        "Aus technischer Sicht koennen wir am vierzehnten November umziehen.",
    ),
    (
        "SPEAKER_02",
        "Katrin Schulz",
        "Microsoft Katja",
        "Katrin Schulz aus der Finanzabteilung. Für den Umzug haben wir achtundvierzigtausend Euro "
        "eingeplant. Das reicht, wenn die Schulung der Mitarbeiter nicht teurer wird als gedacht.",
    ),
    (
        "SPEAKER_00",
        "Anna Becker",
        "Microsoft Hedda",
        "Dann halten wir fest: Der Umzug findet am vierzehnten November statt, und das Budget von "
        "achtundvierzigtausend Euro ist freigegeben. Thomas, du schreibst bitte den Testplan.",
    ),
    (
        "SPEAKER_01",
        "Thomas Wagner",
        "Microsoft Stefan",
        "Mache ich. Der Testplan ist bis Freitag, den vierundzwanzigsten Oktober, fertig.",
    ),
    (
        "SPEAKER_02",
        "Katrin Schulz",
        "Microsoft Katja",
        "Ich hole bis Ende Oktober drei Angebote für die Schulung ein. Offen ist noch, ob wir am "
        "Wochenende arbeiten müssen. Das sollten wir mit dem Betriebsrat klären.",
    ),
    (
        "SPEAKER_00",
        "Anna Becker",
        "Microsoft Hedda",
        "Gut. Die Frage zur Wochenendarbeit bleibt offen. Wir treffen uns wieder am "
        "achtundzwanzigsten Oktober. Danke euch.",
    ),
]

# Pausen zwischen den Beitraegen in Sekunden; die Zeitstempel im Transkript
# werden aus einer festen Sprechgeschwindigkeit geschaetzt.
_SEKUNDEN_PRO_ZEICHEN = 0.065
_PAUSE = 1.0


def transkript_daten() -> dict:
    """Ein Transkript im Exportformat der Anwendung (wie
    ``export_service.build_json_result``), aus dem Drehbuch statt aus einer
    Aufnahme. So laesst sich die Nachbearbeitung pruefen, ohne Spracherkennung."""
    segmente = []
    zeit = 0.0
    for nummer, (sprecher_id, name, _stimme, text) in enumerate(BEITRAEGE, start=1):
        dauer = len(text) * _SEKUNDEN_PRO_ZEICHEN
        segmente.append(
            {
                "nummer": nummer,
                "start_sekunden": round(zeit, 3),
                "ende_sekunden": round(zeit + dauer, 3),
                "sprecher_id": sprecher_id,
                "sprecher": name,
                "text": text,
            }
        )
        zeit += dauer + _PAUSE
    namen = {sprecher_id: name for sprecher_id, name, _stimme, _text in BEITRAEGE}
    return {
        "quelldatei_stamm": "besprechung_datenbankumzug",
        "sprechertrennung_aktiv": True,
        "sprecher_zuordnung": [{"sprecher_id": k, "anzeigename": v} for k, v in namen.items()],
        "segmente": segmente,
    }


def schreibe_transkript(ordner: Path) -> Path:
    pfad = ordner / "besprechung_datenbankumzug_transkript.json"
    pfad.write_text(json.dumps(transkript_daten(), ensure_ascii=False, indent=2), encoding="utf-8")
    return pfad


def normalisiert(text: str) -> str:
    """Kleinbuchstaben, Umlaute ausgeschrieben, Tausenderpunkte und Leerraum in
    Zahlen entfernt -- damit '48.000 €', '48000 Euro' und 'achtundvierzigtausend'
    sich mit wenigen Mustern pruefen lassen."""
    text = text.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    ergebnis = []
    for i, zeichen in enumerate(text):
        zwischen_ziffern = 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()
        if zeichen in ".   " and zwischen_ziffern:
            continue
        ergebnis.append(zeichen)
    return "".join(ergebnis)


def enthaelt_eines(text: str, *muster: str) -> bool:
    norm = normalisiert(text)
    return any(normalisiert(m) in norm for m in muster)


# Die Fakten in den Formen, in denen ein Modell sie wiedergeben darf.
UMZUGSTERMIN = ("14. november", "14.11", "14 november", "vierzehnten november")
BUDGET = ("48000", "48 000", "48k", "48 tsd", "achtundvierzigtausend")
FRIST_TESTPLAN = ("24. oktober", "24.10", "24 oktober", "vierundzwanzigsten oktober")
FOLGETERMIN = ("28. oktober", "28.10", "28 oktober", "achtundzwanzigsten oktober")
