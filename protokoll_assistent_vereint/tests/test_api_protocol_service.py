"""Tests fuer 'services/api_protocol_service.py'.

'urllib.request.urlopen' wird durchgehend gefaked - kein Test spricht ein
echtes Netzwerk an (siehe CLAUDE.md, Regel 4)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from protokoll_assistent_vereint.services import api_protocol_service as svc


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _chat_antwort(inhalt: str) -> dict:
    return {"choices": [{"message": {"content": inhalt}}]}


def test_generate_json_liest_json_aus_der_antwort(monkeypatch):
    protokoll = {"titel": "Testprotokoll", "themen": []}
    monkeypatch.setattr(
        svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(_chat_antwort(json.dumps(protokoll)))
    )

    ergebnis = svc.generate_json(
        "Transkripttext", "Systemprompt", "modell-x",
        endpoint_url="https://example.test/chat/completions", api_key="geheim",
    )

    assert ergebnis == protokoll


def test_generate_json_schickt_autorisierung_und_json_format(monkeypatch):
    aufgezeichnet = {}

    def fake_urlopen(request, timeout=None):
        aufgezeichnet["body"] = json.loads(request.data.decode("utf-8"))
        aufgezeichnet["headers"] = dict(request.headers)
        return _FakeResponse(_chat_antwort(json.dumps({"titel": "x"})))

    monkeypatch.setattr(svc.urllib.request, "urlopen", fake_urlopen)

    svc.generate_json(
        "Transkripttext", "Systemprompt", "modell-x",
        endpoint_url="https://example.test/chat/completions", api_key="geheim",
    )

    assert aufgezeichnet["headers"]["Authorization"] == "Bearer geheim"
    assert aufgezeichnet["body"]["response_format"] == {"type": "json_object"}
    assert aufgezeichnet["body"]["messages"] == [
        {"role": "system", "content": "Systemprompt"},
        {"role": "user", "content": "Transkripttext"},
    ]


def test_generate_json_meldet_http_fehler(monkeypatch):
    def werfen(*a, **k):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)
    monkeypatch.setattr(urllib.error.HTTPError, "read", lambda self: b"kaputt", raising=False)

    with pytest.raises(svc.ApiProtocolError, match="HTTP 500"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_meldet_nicht_erreichbaren_endpunkt(monkeypatch):
    def werfen(*a, **k):
        raise urllib.error.URLError("nicht erreichbar")

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)

    with pytest.raises(svc.ApiProtocolError, match="nicht erreichbar"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_meldet_zeitueberschreitung(monkeypatch):
    def werfen(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)

    with pytest.raises(svc.ApiProtocolError, match="Zeitlimit"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_meldet_fehlerfeld_in_der_antwort(monkeypatch):
    monkeypatch.setattr(
        svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({"error": "Modell ueberlastet"})
    )

    with pytest.raises(svc.ApiProtocolError, match="Modell ueberlastet"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_meldet_unerwartete_antwortform(monkeypatch):
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({"choices": []}))

    with pytest.raises(svc.ApiProtocolError, match="Unerwartete Antwort"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_meldet_nicht_parsbares_json(monkeypatch):
    monkeypatch.setattr(
        svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(_chat_antwort("kein json hier"))
    )

    with pytest.raises(svc.ApiProtocolError, match="nicht als JSON gelesen"):
        svc.generate_json(
            "Text", "System", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_json_findet_json_in_umgebendem_text(monkeypatch):
    protokoll = {"titel": "In Markdown verpackt"}
    text_mit_codezaun = f"```json\n{json.dumps(protokoll)}\n```"
    monkeypatch.setattr(
        svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(_chat_antwort(text_mit_codezaun))
    )

    ergebnis = svc.generate_json(
        "Text", "System", "modell-x",
        endpoint_url="https://example.test/chat/completions", api_key="geheim",
    )

    assert ergebnis == protokoll
