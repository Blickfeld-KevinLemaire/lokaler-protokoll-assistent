"""Integrationstest: belegt, dass die Wiederverwendung von
'services.pipeline_service' (aus 'lokale_windows_app') fuer den API-Pfad
tatsaechlich funktioniert - nicht nur in der Theorie des Plans.

Anders als die Unit-Tests in 'test_api_transcription_service.py'/
'test_api_protocol_service.py' laeuft hier die ECHTE
'pipeline_service.run_transcription()'/'run_protocol()' -Ablaufsteuerung
(Chunk-Planung, Zusammenfuehrung, Sprecherzuordnung, Export,
Protokollauswertung) mit den ECHTEN 'api_transcription_service'/
'api_protocol_service'-Funktionen als 'transcribe_chunk_fn'/'diarize_fn'/
'protocol_generate_fn' - nur 'urllib.request.urlopen' ist gefaked, kein
Test spricht ein echtes Netzwerk an."""

from __future__ import annotations

import functools
import json

import pytest

from protokoll_assistent_vereint.services import api_protocol_service, api_transcription_service
from services import pipeline_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / "aufnahme.wav"
    path.write_bytes(b"RIFF" + b"0" * 1000)
    return path


def _patch_ffmpeg(monkeypatch, total_duration: float):
    def fake_normalize(source, destination, ffmpeg_path=None, sample_rate=16000):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dummy-wav")
        return destination

    def fake_probe(path, ffprobe_path=None):
        return total_duration

    def fake_extract(normalized, destination, start, end, ffmpeg_path=None, sample_rate=16000):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dummy-chunk")
        return destination

    monkeypatch.setattr(pipeline_service.ffmpeg_service, "ensure_ffmpeg_on_path", lambda: None)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "normalize_audio", fake_normalize)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "probe_duration_seconds", fake_probe)
    monkeypatch.setattr(pipeline_service.ffmpeg_service, "extract_chunk_wav", fake_extract)


def _systemprompt_bereitstellen(monkeypatch, tmp_path):
    import utils.paths as utils_paths

    prompt = tmp_path / "systemprompt.txt"
    prompt.write_text("Du bist ein Protokollassistent.", encoding="utf-8")
    monkeypatch.setattr(utils_paths, "get_system_prompt_file", lambda: prompt)


def test_api_transkription_end_zu_ende_durch_die_echte_pipeline(monkeypatch, tmp_path, source_file):
    """Zwei Chunks (1300s -> 3 Chunks), jeder API-Aufruf liefert Segmente mit
    unterschiedlichen Sprecher-Labels vom Provider. Am Ende muessen alle drei
    Sprecher in der Export-JSON korrekt (und stabil benannt) auftauchen -
    ganz ohne dass 'diarize_fn' selbst irgendeine Diarisierung durchfuehrt."""
    import utils.paths as utils_paths

    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)  # -> 3 Chunks

    anfragen = []

    def fake_urlopen(request, timeout=None):
        anfragen.append(request)
        chunk_index = len(anfragen)
        return _FakeResponse(
            {
                "segments": [
                    {
                        "start": 1.0,
                        "end": 2.0,
                        "text": f"Text von Chunk {chunk_index}",
                        "speaker": f"spk_{chunk_index}",
                    }
                ]
            }
        )

    monkeypatch.setattr(api_transcription_service.urllib.request, "urlopen", fake_urlopen)

    transcribe_chunk_fn = functools.partial(
        api_transcription_service.transcribe_chunk_via_api,
        endpoint_url="https://example.test/transkription",
        api_key="geheim",
        model_name="modell-x",
        provider_name="azure",
        diarization_enabled=True,
    )

    settings = pipeline_service.PipelineSettings(
        source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=False
    )
    result = pipeline_service.run_transcription(
        settings,
        transcribe_chunk_fn=transcribe_chunk_fn,
        diarize_fn=api_transcription_service.diarize_via_api_speakers,
    )

    assert len(anfragen) == 3  # ein Request je Chunk
    assert result.export_paths.txt.is_file()
    assert result.export_paths.json.is_file()

    daten = json.loads(result.export_paths.json.read_text(encoding="utf-8"))
    assert daten["sprechertrennung_aktiv"] is True
    sprecher_ids = {eintrag["sprecher_id"] for eintrag in daten["sprecher_zuordnung"]}
    assert sprecher_ids == {"spk_1", "spk_2", "spk_3"}
    assert daten["anzahl_sprecher"] == 3
    # Jedes Segment hat tatsaechlich einen Sprecher zugeordnet bekommen -
    # nicht 'None', wie es bei einer leeren 'diarization_turns'-Liste ueber
    # 'assign_speakers_by_overlap' der Fall waere.
    assert all(segment["sprecher_id"] is not None for segment in daten["segmente"])


def test_api_transkription_ohne_sprechertrennung(monkeypatch, tmp_path, source_file):
    import utils.paths as utils_paths

    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)  # -> 1 Chunk

    def fake_urlopen(request, timeout=None):
        return _FakeResponse({"segments": [{"start": 1.0, "end": 2.0, "text": "Hallo Welt"}]})

    monkeypatch.setattr(api_transcription_service.urllib.request, "urlopen", fake_urlopen)

    transcribe_chunk_fn = functools.partial(
        api_transcription_service.transcribe_chunk_via_api,
        endpoint_url="https://example.test/transkription",
        api_key="geheim",
        model_name="modell-x",
        provider_name="azure",
        diarization_enabled=False,
    )

    settings = pipeline_service.PipelineSettings(
        source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=False, enable_diarization=False
    )
    result = pipeline_service.run_transcription(
        settings, transcribe_chunk_fn=transcribe_chunk_fn, diarize_fn=api_transcription_service.diarize_via_api_speakers
    )

    daten = json.loads(result.export_paths.json.read_text(encoding="utf-8"))
    assert daten["sprechertrennung_aktiv"] is False
    assert daten["sprecher_zuordnung"] == []
    assert "Hallo Welt" in result.export_paths.txt.read_text(encoding="utf-8")


def test_api_nachbearbeitung_end_zu_ende_durch_die_echte_pipeline(monkeypatch, tmp_path, source_file):
    """Baut zuerst per API-Transkription ein echtes Transkript, wertet es
    dann per API-Modell aus - beide Schritte durch die echte
    Ablaufsteuerung, nur 'urlopen' gefaked."""
    import utils.paths as utils_paths

    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    def fake_transcribe_urlopen(request, timeout=None):
        return _FakeResponse({"segments": [{"start": 1.0, "end": 2.0, "text": "Wir starten das Projekt."}]})

    monkeypatch.setattr(api_transcription_service.urllib.request, "urlopen", fake_transcribe_urlopen)

    transcribe_chunk_fn = functools.partial(
        api_transcription_service.transcribe_chunk_via_api,
        endpoint_url="https://example.test/transkription",
        api_key="geheim",
        model_name="modell-x",
        provider_name="azure",
        diarization_enabled=False,
    )
    transkript = pipeline_service.run_transcription(
        pipeline_service.PipelineSettings(
            source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=False, enable_diarization=False
        ),
        transcribe_chunk_fn=transcribe_chunk_fn,
        diarize_fn=api_transcription_service.diarize_via_api_speakers,
    )

    protokoll_antwort = {
        "titel": "Projektstart",
        "kurzzusammenfassung": "Alles begonnen.",
        "teilnehmende_oder_sprecher": [],
        "themen": [],
        "entscheidungen": [],
        "aufgaben": [],
        "termine": [],
        "offene_fragen": [],
        "wichtige_fakten": [],
        "unsichere_transkriptstellen": [],
        "quellenhinweise": [],
        "kernaussagen": ["Das Projekt ist gestartet."],
    }

    def fake_protocol_urlopen(request, timeout=None):
        return _FakeResponse(
            {"choices": [{"message": {"content": json.dumps(protokoll_antwort)}}]}
        )

    monkeypatch.setattr(api_protocol_service.urllib.request, "urlopen", fake_protocol_urlopen)

    protocol_generate_fn = functools.partial(
        api_protocol_service.generate_json,
        model="modell-nachbearbeitung",
        endpoint_url="https://example.test/chat/completions",
        api_key="geheim",
    )

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=protocol_generate_fn,
    )

    assert ergebnis.protokoll_fehler is None
    assert ergebnis.protocol_paths is not None
    gespeichertes_protokoll = json.loads(ergebnis.protocol_paths[0].read_text(encoding="utf-8"))
    assert gespeichertes_protokoll["titel"] == "Projektstart"
    # Die Nachbearbeitung ist eigenstaendig fortsetzbar, unabhaengig vom
    # Arbeitsordner der Transkription (siehe 'run_protocol'-Docstring).
    assert ergebnis.work_dir != transkript.work_dir
