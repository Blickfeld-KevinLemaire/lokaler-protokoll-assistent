import json
import urllib.error

import pytest

from protokoll_assistent.services import ollama_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_is_service_running_true_when_tags_reachable(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": []}),
    )
    assert ollama_service.is_service_running() is True


def test_is_service_running_false_on_connection_error(monkeypatch):
    def raise_error(request, timeout=None):
        raise urllib.error.URLError("Verbindung verweigert")

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_error)
    assert ollama_service.is_service_running() is False


def test_is_model_available_matches_exact_and_base_name(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": [{"name": "qwen3:8b"}]}),
    )
    assert ollama_service.is_model_available("qwen3:8b") is True
    assert ollama_service.is_model_available("qwen3") is True
    assert ollama_service.is_model_available("llama3:8b") is False


def test_is_model_available_false_when_service_down(monkeypatch):
    def raise_error(request, timeout=None):
        raise urllib.error.URLError("nicht erreichbar")

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_error)
    assert ollama_service.is_model_available() is False


def test_generate_json_parses_response_field(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": '{"titel": "Test"}'}),
    )
    result = ollama_service.generate_json("Frage", "System")
    assert result == {"titel": "Test"}


def test_generate_json_raises_on_unparsable_response(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": "das ist kein JSON"}),
    )
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_json("Frage", "System")


def test_generate_json_raises_ollama_error_on_http_error(monkeypatch):
    def raise_http_error(request, timeout=None):
        raise urllib.error.HTTPError("url", 500, "Serverfehler", {}, None)

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_json("Frage", "System")


def test_generate_json_sends_temperature_zero_and_json_format(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"response": "{}"})

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", fake_urlopen)
    ollama_service.generate_json("Frage", "System", model="qwen3:8b")
    assert captured["body"]["options"]["temperature"] == 0.0
    assert captured["body"]["format"] == "json"
    assert captured["body"]["model"] == "qwen3:8b"
    assert captured["body"]["stream"] is False


def test_ensure_ollama_or_offer_installer_returns_true_when_already_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: object())
    download_calls = []
    monkeypatch.setattr(
        ollama_service, "download_ollama_installer", lambda *a, **kw: download_calls.append((a, kw))
    )
    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path)
    assert result is True
    assert download_calls == []


def test_ensure_ollama_or_offer_installer_downloads_and_launches_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    installer_path = tmp_path / "OllamaSetup.exe"
    monkeypatch.setattr(
        ollama_service, "download_ollama_installer", lambda destination_dir, download_fn=None: installer_path
    )
    launch_calls = []
    monkeypatch.setattr(ollama_service, "launch_installer", lambda path: launch_calls.append(path))

    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, auto_launch=True)

    assert result is False
    assert launch_calls == [installer_path]


def test_ensure_ollama_or_offer_installer_skips_launch_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    monkeypatch.setattr(
        ollama_service,
        "download_ollama_installer",
        lambda destination_dir, download_fn=None: tmp_path / "OllamaSetup.exe",
    )
    launch_calls = []
    monkeypatch.setattr(ollama_service, "launch_installer", lambda path: launch_calls.append(path))

    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, auto_launch=False)

    assert result is False
    assert launch_calls == []


def test_ensure_ollama_or_offer_installer_handles_download_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)

    def failing_download(destination_dir, download_fn=None):
        raise OSError("Netzwerkfehler")

    monkeypatch.setattr(ollama_service, "download_ollama_installer", failing_download)
    messages = []
    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, progress_cb=messages.append)
    assert result is False
    assert any("nicht heruntergeladen" in message for message in messages)


def test_download_ollama_installer_uses_injected_download_fn(tmp_path):
    def fake_download(url, destination):
        destination.write_bytes(b"fake-installer-bytes")

    result = ollama_service.download_ollama_installer(tmp_path, download_fn=fake_download)
    assert result == tmp_path / "OllamaSetup.exe"
    assert result.read_bytes() == b"fake-installer-bytes"


def test_is_model_available_verlangt_die_angegebene_fassung(monkeypatch):
    # Frueher genuegte der Name vor dem Doppelpunkt. Mit einem
    # installierten 'qwen3:0.6b' galt auch 'qwen3:8b' als vorhanden -- der
    # Einrichtungsassistent liess den Download aus, die Systemdiagnose
    # meldete Erfolg, und erst nach der fertigen Transkription scheiterte
    # die Protokollauswertung am ersten Modellaufruf.
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": [{"name": "qwen3:0.6b"}]}),
    )
    assert ollama_service.is_model_available("qwen3:8b") is False
    assert ollama_service.is_model_available("qwen3:0.6b") is True
    # Ohne Fassungsangabe legt sich der Aufrufer bewusst nicht fest.
    assert ollama_service.is_model_available("qwen3") is True


def test_generate_json_liest_antwort_mit_klammer_in_zeichenkette(monkeypatch):
    # Durchgehender Weg: So kommt die Antwort wirklich bei
    # protocol_service an -- als Fliesstext um das JSON herum.
    rohantwort = 'Gerne:\n{"kernaussagen": ["Platzhalter } im Text"], "aufgaben": []}'
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": rohantwort}),
    )

    ergebnis = ollama_service.generate_json("Frage", "System")

    assert ergebnis["kernaussagen"] == ["Platzhalter } im Text"]
