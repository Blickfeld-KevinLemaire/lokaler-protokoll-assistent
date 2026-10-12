"""Nachbearbeitung (Protokollauswertung) ueber ein OpenAI-kompatibles
Chat-Completions-Modell, als Ersatz fuer ein lokales Ollama-Modell.

'generate_text' hat bewusst dieselbe Signaturform wie
'services.ollama_service.generate_text' -
'(prompt, system, model=...) -> str' - und liefert wie dieses die Antwort
des Modells als Freitext. Dadurch passt sie unveraendert als
'protocol_generate_fn' in 'services.pipeline_service.run_protocol'
(ueber ein kleines Closure fuer Endpunkt/Schluessel, genau wie
'default_ollama_generate' es dort heute fuer 'model' tut) - die komplette
mehrstufige Protokollauswertung ('services.protocol_service') bleibt
unveraendert dieselbe, unabhaengig davon, ob ein lokales oder ein
API-Modell antwortet.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 600.0


class ApiProtocolError(RuntimeError):
    pass


def _chat_completion(
    prompt: str,
    system: str,
    model: str,
    *,
    endpoint_url: str,
    api_key: str,
    timeout: float,
    json_modus: bool,
) -> str:
    """Ruft '/chat/completions' auf und liefert den Text der Modellantwort.
    Mit 'json_modus' wird das Modell zusaetzlich auf ein JSON-Objekt
    festgelegt."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if json_modus:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        raise ApiProtocolError(f"API-Fehler HTTP {error.code} von {endpoint_url}: {details}") from error
    except urllib.error.URLError as error:
        raise ApiProtocolError(f"Der Endpunkt ist nicht erreichbar ({endpoint_url}): {error}") from error
    except TimeoutError as error:
        raise ApiProtocolError("Die Anfrage an das API-Modell hat das Zeitlimit ueberschritten.") from error

    if not isinstance(result, dict):
        raise ApiProtocolError(f"{endpoint_url} hat kein JSON-Objekt geliefert.")
    if result.get("error"):
        raise ApiProtocolError(f"Der Endpunkt meldet einen Fehler: {result['error']}")
    try:
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise ApiProtocolError(f"Unerwartete Antwort von {endpoint_url}: {result}") from error


def generate_text(
    prompt: str,
    system: str,
    model: str,
    *,
    endpoint_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Ruft '/chat/completions' auf und liefert die Antwort als Freitext --
    ohne JSON-Vorgabe. Aufbau und Form der Antwort bestimmt allein der
    Systemprompt. Funktioniert mit jedem Anbieter, der die verbreitete
    OpenAI-kompatible Schnittstelle anbietet (OpenRouter, OpenAI, IONOS AI
    Model Hub, u. v. a.)."""
    return _chat_completion(
        prompt,
        system,
        model,
        endpoint_url=endpoint_url,
        api_key=api_key,
        timeout=timeout,
        json_modus=False,
    )


def generate_json(
    prompt: str,
    system: str,
    model: str,
    *,
    endpoint_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wie 'generate_text', verlangt aber ein JSON-Objekt und liefert das
    aus der Antwort geparste Objekt."""
    # Spaeter Import, um Zirkelbezuege beim Modulladen zu vermeiden
    # (siehe 'api_transcription_service' fuer dasselbe Muster).
    from protokoll_assistent.utils.json_validation import extract_json_object

    raw_text = _chat_completion(
        prompt,
        system,
        model,
        endpoint_url=endpoint_url,
        api_key=api_key,
        timeout=timeout,
        json_modus=True,
    )
    parsed = extract_json_object(raw_text)
    if parsed is None:
        raise ApiProtocolError("Die Antwort des API-Modells konnte nicht als JSON gelesen werden.")
    return parsed
