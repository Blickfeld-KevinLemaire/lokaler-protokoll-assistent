"""Tests fuer 'services/api_protocol_service.py'.

'urllib.request.urlopen' wird durchgehend gefaked - kein Test spricht ein
echtes Netzwerk an (siehe CLAUDE.md, Regel 4)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from protokoll_assistent.services import api_protocol_service as svc


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


def test_generate_text_liefert_freitext_ohne_json_vorgabe(monkeypatch):
    aufgezeichnet = {}

    def fake_urlopen(request, timeout=None):
        aufgezeichnet["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(_chat_antwort("- 12.10. Abgabe"))

    monkeypatch.setattr(svc.urllib.request, "urlopen", fake_urlopen)

    ergebnis = svc.generate_text(
        "Transkripttext", "Systemprompt", "modell-x",
        endpoint_url="https://example.test/chat/completions", api_key="geheim",
    )

    assert ergebnis == "- 12.10. Abgabe"
    assert "response_format" not in aufgezeichnet["body"]
    assert aufgezeichnet["body"]["messages"] == [
        {"role": "system", "content": "Systemprompt"},
        {"role": "user", "content": "Transkripttext"},
    ]


def test_generate_text_meldet_abgeschnittene_antwort(monkeypatch):
    """'finish_reason: length' heisst: Das Modell hat die Laengengrenze erreicht
    und mitten im Text aufgehoert. So ein Ergebnis darf nicht durchgehen."""
    antwort = {"choices": [{"message": {"content": "- 12.10. Abg"}, "finish_reason": "length"}]}
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(antwort))

    with pytest.raises(svc.ApiProtocolError, match="abgeschnitten"):
        svc.generate_text(
            "Transkripttext", "Systemprompt", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


def test_generate_text_nimmt_vollstaendige_antwort_an(monkeypatch):
    antwort = {"choices": [{"message": {"content": "Fertig."}, "finish_reason": "stop"}]}
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(antwort))

    assert svc.generate_text(
        "Transkripttext", "Systemprompt", "modell-x",
        endpoint_url="https://example.test/chat/completions", api_key="geheim",
    ) == "Fertig."


def test_generate_text_meldet_http_fehler(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(svc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(svc.ApiProtocolError, match="401"):
        svc.generate_text(
            "T", "S", "modell-x",
            endpoint_url="https://example.test/chat/completions", api_key="geheim",
        )


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


# --------------------------------------------------------------------------
# Antworten ohne Text und abgebrochene Verbindungen
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("wahl", "grund"),
    [
        ({"message": {"content": None, "refusal": "Das kann ich nicht."}, "finish_reason": "stop"}, "Das kann ich nicht"),
        ({"message": {"content": None}, "finish_reason": "content_filter"}, "content_filter"),
        ({"message": {"content": "halber Text"}, "finish_reason": "content_filter"}, "content_filter"),
        ({"message": {"content": None}}, "ohne Angabe"),
    ],
)
def test_generate_text_ohne_inhalt_ist_ein_fehler_und_nie_der_text_none(monkeypatch, wahl, grund):
    # 'str(None)' ergab "None": Das galt als Antwort, wurde als Zwischenstand gespeichert und stand im Protokoll.
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({"choices": [wahl]}))
    with pytest.raises(svc.ApiProtocolError, match=grund):
        svc.generate_text("p", "s", "m", endpoint_url="https://example.test", api_key="k")


@pytest.mark.parametrize("fehler", ["getrennt", "unvollstaendig", "zurueckgesetzt"])
def test_generate_text_abgebrochene_verbindung_wird_ein_api_fehler(monkeypatch, fehler):
    import http.client

    ausnahmen = {
        "getrennt": http.client.RemoteDisconnected("Remote end closed connection without response"),
        "unvollstaendig": http.client.IncompleteRead(b"{"),
        "zurueckgesetzt": ConnectionResetError(10054, "Verbindung zurueckgesetzt"),
    }

    def oeffnen(*a, **k):
        raise ausnahmen[fehler]

    monkeypatch.setattr(svc.urllib.request, "urlopen", oeffnen)
    with pytest.raises(svc.ApiProtocolError, match="abgebrochen"):
        svc.generate_text("p", "s", "m", endpoint_url="https://example.test", api_key="k")


def test_generate_text_fehlerseite_statt_json(monkeypatch):
    seite = _FakeResponse({})
    seite._body = b"<html>Anmeldung</html>"
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *a, **k: seite)
    with pytest.raises(svc.ApiProtocolError, match="kein JSON"):
        svc.generate_text("p", "s", "m", endpoint_url="https://example.test", api_key="k")
