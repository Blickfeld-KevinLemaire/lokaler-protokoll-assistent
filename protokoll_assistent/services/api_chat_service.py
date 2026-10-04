"""Chat und Einbettungen ueber einen OpenAI-kompatiblen Endpunkt.

Gegenstueck zu ``ollama_service.chat_stream``/``ollama_service.embed`` fuer den
API-Weg des Chatbots "Frag mein Meeting". Funktioniert mit jedem Anbieter, der
``/chat/completions`` und ``/embeddings`` im verbreiteten OpenAI-Format
anbietet (OpenRouter, OpenAI, IONOS AI Model Hub u. a.).

Datenschutz: Hier verlassen Fragen UND Auszuege aus den Transkripten bzw. - fuer
die Einbettungen - die Transkripttexte selbst den Rechner. Die Oberflaeche
weist deshalb deutlich darauf hin.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 300.0

OeffneFn = Callable[..., Any]


class ApiChatError(RuntimeError):
    pass


def _post(url: str, payload: dict[str, Any], api_key: str, timeout: float, opener: OeffneFn | None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            ergebnis = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:500]
        raise ApiChatError(f"API-Fehler HTTP {error.code} von {url}: {details}") from error
    except urllib.error.URLError as error:
        raise ApiChatError(f"Der Endpunkt ist nicht erreichbar ({url}): {error.reason}") from error
    except TimeoutError as error:
        raise ApiChatError("Die Anfrage an die API hat das Zeitlimit ueberschritten.") from error
    except (OSError, ValueError) as error:
        raise ApiChatError(f"Unlesbare Antwort von {url}: {error}") from error
    if not isinstance(ergebnis, dict):
        raise ApiChatError(f"{url} hat kein JSON-Objekt geliefert.")
    if ergebnis.get("error"):
        raise ApiChatError(f"Der Endpunkt meldet einen Fehler: {ergebnis['error']}")
    return ergebnis


def chat(
    messages: list[dict[str, str]],
    model: str,
    *,
    endpoint_url: str,
    api_key: str,
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: OeffneFn | None = None,
) -> str:
    ergebnis = _post(
        endpoint_url,
        {"model": model, "messages": messages, "temperature": temperature},
        api_key,
        timeout,
        opener,
    )
    try:
        return str(ergebnis["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise ApiChatError(f"Unerwartete Antwort von {endpoint_url}: {str(ergebnis)[:300]}") from error


def embed(
    texts: list[str],
    model: str,
    *,
    endpoint_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: OeffneFn | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    ergebnis = _post(endpoint_url, {"model": model, "input": texts}, api_key, timeout, opener)
    try:
        eintraege = sorted(ergebnis["data"], key=lambda e: e.get("index", 0))
        vektoren = [[float(x) for x in eintrag["embedding"]] for eintrag in eintraege]
    except (KeyError, TypeError, ValueError) as error:
        raise ApiChatError(f"Unerwartete Antwort von {endpoint_url} (Einbettungen): {str(ergebnis)[:300]}") from error
    if len(vektoren) != len(texts):
        raise ApiChatError(
            f"Der Endpunkt lieferte {len(vektoren)} Einbettungen fuer {len(texts)} Texte."
        )
    return vektoren
