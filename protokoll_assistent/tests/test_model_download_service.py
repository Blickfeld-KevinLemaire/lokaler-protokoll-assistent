from protokoll_assistent.services import model_download_service, ollama_service


def test_download_whisper_and_alignment_reports_missing_import_cleanly():
    # In dieser Testumgebung ist faster-whisper nicht installiert -- die Funktion
    # darf trotzdem nicht mit einem Traceback abstuerzen.
    messages = []
    result = model_download_service.download_whisper_and_alignment(messages.append)
    assert result is False
    assert any("FEHLER" in message for message in messages)


def test_download_pyannote_reports_missing_import_cleanly():
    messages = []
    result = model_download_service.download_pyannote(messages.append, get_token=lambda: None)
    assert result is False
    assert any("FEHLER" in message for message in messages)


def test_download_pyannote_uses_token_provider_when_hf_token_missing(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    provider_calls = []

    def fake_provider():
        provider_calls.append(True)
        return "geheimes-token"

    model_download_service.download_pyannote(lambda message: None, get_token=fake_provider)
    assert provider_calls == [True]
    import os

    assert os.environ.get("HF_TOKEN") == "geheimes-token"
    del os.environ["HF_TOKEN"]


def test_download_pyannote_skips_token_provider_when_already_set(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "vorhanden")
    provider_calls = []
    model_download_service.download_pyannote(lambda message: None, get_token=lambda: provider_calls.append(True))
    assert provider_calls == []


def test_download_ollama_model_fails_cleanly_when_not_found(monkeypatch):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    messages = []
    result = model_download_service.download_ollama_model(messages.append)
    assert result is False
    assert any("nicht gefunden" in message for message in messages)


def test_download_ollama_model_skips_pull_when_already_available(monkeypatch):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_service, "is_service_running", lambda: True)
    monkeypatch.setattr(ollama_service, "is_model_available", lambda model: True)
    messages = []
    result = model_download_service.download_ollama_model(messages.append)
    assert result is True
    assert any("bereits vorhanden" in message for message in messages)


def test_download_all_models_returns_dict_with_all_three_keys(monkeypatch):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    result = model_download_service.download_all_models(lambda message: None, get_token=lambda: None)
    assert set(result.keys()) == {"whisperx_und_alignment", "pyannote", "ollama_modell"}
    assert all(isinstance(value, bool) for value in result.values())
