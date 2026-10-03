"""Tests fuer 'services/api_transcription_service.py'.

'urllib.request.urlopen' wird durchgehend gefaked - kein Test spricht ein
echtes Netzwerk an (siehe CLAUDE.md, Regel 4)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from protokoll_assistent.services import api_transcription_service as svc


# --------------------------------------------------------------------------
# Groessenbegrenzung
# --------------------------------------------------------------------------
def test_pruefe_uebertragungsgroesse_erlaubt_kleine_datei(tmp_path):
    datei = tmp_path / "chunk.wav"
    datei.write_bytes(b"x" * 1024)
    svc.pruefe_uebertragungsgroesse(datei)  # darf nicht werfen


def test_pruefe_uebertragungsgroesse_wirft_bei_zu_grosser_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "MAX_DIRECT_AUDIO_SIZE", 100)
    datei = tmp_path / "chunk.wav"
    datei.write_bytes(b"x" * 200)
    with pytest.raises(svc.ApiTranscriptionError, match="zu gross"):
        svc.pruefe_uebertragungsgroesse(datei)


# --------------------------------------------------------------------------
# Anfrage-Form
# --------------------------------------------------------------------------
def test_build_request_ohne_diarisierung_hat_kein_provider_feld():
    request = svc.build_request(
        b"audiodaten", "wav", "modell-x", "azure", diarization_enabled=False
    )
    assert "provider" not in request
    assert request["model"] == "modell-x"
    assert request["input_audio"]["format"] == "wav"
    assert request["response_format"] == "verbose_json"


def test_build_request_mit_diarisierung_setzt_provider_feld():
    request = svc.build_request(
        b"audiodaten", "wav", "modell-x", "azure", diarization_enabled=True
    )
    assert request["provider"] == {"options": {"azure": {"diarization": {"enabled": True}}}}


def test_build_request_ohne_anbieter_laesst_provider_feld_weg():
    request = svc.build_request(b"audiodaten", "wav", "modell-x", "  ", diarization_enabled=True)
    assert "provider" not in request


# --------------------------------------------------------------------------
# call_endpoint: Fehlerbehandlung
# --------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_call_endpoint_erfolgreich(monkeypatch):
    monkeypatch.setattr(
        svc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({"segments": []})
    )
    result = svc.call_endpoint({"model": "x"}, "https://example.test", "schluessel")
    assert result == {"segments": []}


def test_call_endpoint_meldet_http_fehler(monkeypatch):
    def werfen(*a, **k):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)
    monkeypatch.setattr(
        urllib.error.HTTPError, "read", lambda self: b"Ungueltiger Schluessel", raising=False
    )
    with pytest.raises(svc.ApiTranscriptionError, match="HTTP 401"):
        svc.call_endpoint({"model": "x"}, "https://example.test", "falsch")


def test_call_endpoint_meldet_nicht_erreichbaren_endpunkt(monkeypatch):
    def werfen(*a, **k):
        raise urllib.error.URLError("nicht erreichbar")

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)
    with pytest.raises(svc.ApiTranscriptionError, match="nicht erreichbar"):
        svc.call_endpoint({"model": "x"}, "https://example.test", "schluessel")


def test_call_endpoint_meldet_zeitueberschreitung(monkeypatch):
    def werfen(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(svc.urllib.request, "urlopen", werfen)
    with pytest.raises(svc.ApiTranscriptionError, match="Zeitlimit"):
        svc.call_endpoint({"model": "x"}, "https://example.test", "schluessel")


def test_call_endpoint_meldet_fehlerfeld_in_der_antwort(monkeypatch):
    monkeypatch.setattr(
        svc.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"error": "Modell nicht gefunden"}),
    )
    with pytest.raises(svc.ApiTranscriptionError, match="Modell nicht gefunden"):
        svc.call_endpoint({"model": "x"}, "https://example.test", "schluessel")


# --------------------------------------------------------------------------
# Antwort-Normalisierung
# --------------------------------------------------------------------------
def test_normalize_segments_liest_segments_feld():
    response = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hallo", "speaker": "spk_0"},
            {"start": 2.0, "end": 4.0, "text": "Welt", "speaker": "spk_1"},
        ]
    }
    segments = svc.normalize_segments(response)
    assert len(segments) == 2
    assert segments[0] == {"start": 0.0, "end": 2.0, "text": "Hallo", "speaker": "spk_0", "words": []}


def test_normalize_segments_faellt_auf_words_zurueck():
    response = {
        "words": [
            {"word": "Hallo", "start": 0.0, "end": 0.5, "speaker": "spk_0"},
            {"word": "Welt.", "start": 0.5, "end": 1.0, "speaker": "spk_0"},
        ]
    }
    segments = svc.normalize_segments(response)
    assert len(segments) == 1
    assert segments[0]["text"] == "Hallo Welt."
    assert segments[0]["speaker"] == "spk_0"


def test_normalize_segments_ohne_sprecher_liefert_none():
    response = {"segments": [{"start": 0.0, "end": 1.0, "text": "Text"}]}
    segments = svc.normalize_segments(response)
    assert segments[0]["speaker"] is None


def test_normalize_segments_ohne_inhalt_ist_leer():
    assert svc.normalize_segments({}) == []
    assert svc.normalize_segments({"segments": []}) == []


def test_group_words_to_segments_teilt_bei_sprecherwechsel():
    words = [
        {"word": "Hallo", "start": 0.0, "end": 0.5, "speaker": "spk_0"},
        {"word": "Welt", "start": 0.5, "end": 1.0, "speaker": "spk_1"},
    ]
    segments = svc.group_words_to_segments(words)
    assert len(segments) == 2
    assert segments[0]["speaker"] == "spk_0"
    assert segments[1]["speaker"] == "spk_1"


def test_group_words_to_segments_teilt_bei_langer_pause():
    words = [
        {"word": "Hallo.", "start": 0.0, "end": 0.5, "speaker": "spk_0"},
        {"word": "Spaeter", "start": 5.0, "end": 5.5, "speaker": "spk_0"},
    ]
    segments = svc.group_words_to_segments(words)
    assert len(segments) == 2


# --------------------------------------------------------------------------
# transcribe_chunk_via_api: End-zu-End innerhalb des Moduls
# --------------------------------------------------------------------------
def test_transcribe_chunk_via_api_end_zu_ende(tmp_path, monkeypatch):
    chunk = tmp_path / "chunk_0001.wav"
    chunk.write_bytes(b"RIFF....WAVEfmt ")

    aufgezeichnete_anfrage = {}

    def fake_urlopen(request, timeout=None):
        aufgezeichnete_anfrage["body"] = json.loads(request.data.decode("utf-8"))
        aufgezeichnete_anfrage["headers"] = dict(request.headers)
        return _FakeResponse(
            {"segments": [{"start": 0.0, "end": 1.0, "text": "Hallo", "speaker": "spk_0"}]}
        )

    monkeypatch.setattr(svc.urllib.request, "urlopen", fake_urlopen)

    segments = svc.transcribe_chunk_via_api(
        chunk,
        endpoint_url="https://example.test/transkription",
        api_key="geheim",
        model_name="modell-x",
        provider_name="azure",
        diarization_enabled=True,
    )

    assert segments == [{"start": 0.0, "end": 1.0, "text": "Hallo", "speaker": "spk_0", "words": []}]
    assert aufgezeichnete_anfrage["body"]["model"] == "modell-x"
    # urllib normalisiert Headernamen auf 'Titel-Fall'.
    assert aufgezeichnete_anfrage["headers"]["Authorization"] == "Bearer geheim"


# --------------------------------------------------------------------------
# diarize_via_api_speakers
# --------------------------------------------------------------------------
def _manifest_service():
    from protokoll_assistent.services import manifest_service

    return manifest_service


def test_diarize_via_api_speakers_baut_turns_aus_chunk_transkripten(tmp_path):
    manifest_service = _manifest_service()
    work_dir = tmp_path / "arbeitsdaten" / "hash123"
    work_dir.mkdir(parents=True)
    (work_dir / "transkripte").mkdir()

    manifest = {
        "chunks": [
            {"index": 0, "global_start": 0.0, "global_end": 600.0},
            {"index": 1, "global_start": 590.0, "global_end": 700.0},
        ]
    }
    manifest_service.save_manifest(work_dir, manifest)

    manifest_service.chunk_transcript_path(work_dir, 0).write_text(
        json.dumps([{"start": 1.0, "end": 2.0, "text": "Hallo", "speaker": "spk_0"}]),
        encoding="utf-8",
    )
    manifest_service.chunk_transcript_path(work_dir, 1).write_text(
        json.dumps([{"start": 3.0, "end": 4.0, "text": "Welt", "speaker": "spk_1"}]),
        encoding="utf-8",
    )

    normalized_path = work_dir / "audio_normalisiert.wav"
    turns = svc.diarize_via_api_speakers(normalized_path, None, None)

    assert turns == [
        {"start": 1.0, "end": 2.0, "speaker": "spk_0"},
        {"start": 593.0, "end": 594.0, "speaker": "spk_1"},
    ]


def test_diarize_via_api_speakers_ohne_manifest_liefert_leere_liste(tmp_path):
    normalized_path = tmp_path / "irgendwo" / "audio_normalisiert.wav"
    normalized_path.parent.mkdir(parents=True)
    assert svc.diarize_via_api_speakers(normalized_path, None, None) == []


def test_diarize_via_api_speakers_ueberspringt_segmente_ohne_sprecher(tmp_path):
    manifest_service = _manifest_service()
    work_dir = tmp_path / "arbeitsdaten" / "hash456"
    work_dir.mkdir(parents=True)
    (work_dir / "transkripte").mkdir()

    manifest = {"chunks": [{"index": 0, "global_start": 0.0, "global_end": 600.0}]}
    manifest_service.save_manifest(work_dir, manifest)
    manifest_service.chunk_transcript_path(work_dir, 0).write_text(
        json.dumps([{"start": 1.0, "end": 2.0, "text": "Hallo", "speaker": None}]),
        encoding="utf-8",
    )

    normalized_path = work_dir / "audio_normalisiert.wav"
    assert svc.diarize_via_api_speakers(normalized_path, None, None) == []
