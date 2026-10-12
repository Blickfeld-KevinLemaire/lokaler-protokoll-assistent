"""Lesen von JSON-Objekten aus Modellantworten.

Reine, ohne Zusatzabhaengigkeiten testbare Logik. Die Nachbearbeitung
(``services.protocol_service``) arbeitet mit Freitext und braucht das nicht
mehr; es dient noch ``generate_json`` in ``ollama_service`` und
``api_protocol_service``.
"""

from __future__ import annotations

import json
import re
from typing import Any


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
        # Kein reines JSON -- weiter mit dem naechsten Versuch.
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Der Codeblock enthaelt kein gueltiges JSON -- weiter mit der Klammersuche.
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
                # Ungueltig -- die Schleife sucht hinter dieser Klammer weiter.
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
