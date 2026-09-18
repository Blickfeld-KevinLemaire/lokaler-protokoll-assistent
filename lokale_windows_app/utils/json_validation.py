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

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return None
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
