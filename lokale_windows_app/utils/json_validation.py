"""Validierung von JSON-Antworten des lokalen Ollama-Modells.

Reine, ohne Zusatzabhaengigkeiten testbare Logik. Wird sowohl von
``services.protocol_service`` als auch von den Tests verwendet.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Erwartete Hauptfelder des finalen Protokolls (siehe Systemprompt).
PROTOCOL_REQUIRED_FIELDS: dict[str, type] = {
    "titel": str,
    "kurzzusammenfassung": str,
    "teilnehmende_oder_sprecher": list,
    "themen": list,
    "entscheidungen": list,
    "aufgaben": list,
    "termine": list,
    "offene_fragen": list,
    "wichtige_fakten": list,
    "unsichere_transkriptstellen": list,
    "quellenhinweise": list,
}

# Verbotene Felder, die auf eine Fehler-/Statusantwort statt eines Protokolls
# hindeuten (z.B. wenn das Modell ein Fehlerobjekt statt der Struktur liefert).
DISALLOWED_TOP_LEVEL_FIELDS = {"error", "fehler", "status_code"}


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extrahiert ein JSON-Objekt aus einer Modellantwort.

    LLMs liefern gelegentlich zusaetzlichen Text oder Markdown-Codezaeune um
    das eigentliche JSON. Es wird zunaechst ein direkter Parse versucht,
    andernfalls wird die erste vollstaendige ``{...}``-Klammerung gesucht.
    """
    if not isinstance(text, str):
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    suchstart = 0
    while True:
        start = text.find("{", suchstart)
        if start == -1:
            return None
        ende = _ende_der_klammerung(text, start)
        if ende is not None:
            try:
                parsed = json.loads(text[start : ende + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        # Diese Klammerung war es nicht -- hinter der oeffnenden Klammer
        # weitersuchen, statt aufzugeben. Modelle stellen ihrer Antwort
        # gern noch einen erklaerenden Satz mit Klammern voran.
        suchstart = start + 1


def _ende_der_klammerung(text: str, start: int) -> int | None:
    """Sucht zu der Klammer an ``start`` die passende schliessende Klammer.

    Zeichenketten werden dabei uebersprungen. Ohne das zaehlte eine
    geschweifte Klammer INNERHALB eines Wertes mit -- eine Modellantwort
    wie ``{"hinweis": "schliess die } Klammer"}`` galt dann als zu Ende,
    der Ausschnitt liess sich nicht lesen, und die ganze Auswertung
    scheiterte samt Reparaturversuch.
    """
    depth = 0
    in_zeichenkette = False
    maskiert = False
    for index in range(start, len(text)):
        zeichen = text[index]
        if in_zeichenkette:
            if maskiert:
                maskiert = False
            elif zeichen == "\\":
                maskiert = True
            elif zeichen == '"':
                in_zeichenkette = False
            continue
        if zeichen == '"':
            in_zeichenkette = True
        elif zeichen == "{":
            depth += 1
        elif zeichen == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def validate_protocol_json(data: Any) -> tuple[bool, list[str]]:
    """Prueft Syntax (bereits vorausgesetzt), Hauptfelder und Datentypen."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["Antwort ist kein JSON-Objekt."]

    for forbidden in DISALLOWED_TOP_LEVEL_FIELDS:
        if forbidden in data:
            errors.append(f"Unzulaessiges Statusfeld in Antwort enthalten: {forbidden}")

    for field, expected_type in PROTOCOL_REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"Pflichtfeld fehlt: {field}")
        elif not isinstance(data[field], expected_type):
            errors.append(
                f"Feld '{field}' hat falschen Typ "
                f"({type(data[field]).__name__} statt {expected_type.__name__})."
            )

    return (len(errors) == 0, errors)


def validate_chunk_analysis_json(data: Any) -> tuple[bool, list[str]]:
    """Lockerere Pruefung fuer Stufe-1-Chunk-Analysen (kein volles Protokoll)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, ["Antwort ist kein JSON-Objekt."]
    for forbidden in DISALLOWED_TOP_LEVEL_FIELDS:
        if forbidden in data:
            errors.append(f"Unzulaessiges Statusfeld in Antwort enthalten: {forbidden}")
    required_any_of = ("kernaussagen", "entscheidungen", "aufgaben", "themen")
    if not any(field in data for field in required_any_of):
        errors.append(
            "Es fehlt jedes inhaltliche Feld (mindestens eines von: "
            + ", ".join(required_any_of)
            + ")."
        )
    return (len(errors) == 0, errors)
