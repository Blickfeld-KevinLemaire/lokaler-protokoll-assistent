"""Tests fuer die Ablaufsteuerung von pipeline_service.run_pipeline.

Die schweren ML-Backends (faster-whisper, pyannote, Ollama) werden durch
einfache Stub-Funktionen ersetzt, damit Resume-Verhalten und
Fehlerbehandlung eines einzelnen Chunks ohne GPU/echte Modelle getestet
werden koennen. FFmpeg-Aufrufe werden ebenfalls durch Stubs ersetzt, da in
dieser Sandbox kein FFmpeg installiert ist.
"""

from __future__ import annotations

import json

import pytest

import protokoll_assistent.utils.paths as utils_paths
from protokoll_assistent.services import (
    chunking_service,
    manifest_service,
    ollama_service,
    pipeline_service,
    protocol_service,
)


# --------------------------------------------------------------------------
# Live-Vorschau waehrend der Verarbeitung
# --------------------------------------------------------------------------
def test_build_preview_text_mit_diarisierung_zeigt_zeitstempel_und_sprecher():
    segmente = [
        {"start": 0.0, "sprecher_id": "SPEAKER_00", "text": "Hallo."},
        {"start": 5.0, "sprecher_id": "SPEAKER_01", "text": "Und hallo zurueck."},
    ]
    text = pipeline_service.build_preview_text(segmente, diarization_enabled=True)
    zeilen = text.splitlines()
    assert len(zeilen) == 2
    assert zeilen[0].startswith("[")
    assert "SPEAKER_00: Hallo." in zeilen[0]


def test_build_preview_text_ohne_diarisierung_zeigt_reinen_text_ohne_zeitstempel():
    segmente = [
        {"start": 0.0, "sprecher_id": None, "text": "Hallo."},
        {"start": 5.0, "sprecher_id": None, "text": "Und hallo zurueck."},
    ]
    text = pipeline_service.build_preview_text(segmente, diarization_enabled=False)
    assert text == "Hallo. Und hallo zurueck."
    assert "None" not in text
    assert "[" not in text


def test_build_preview_text_begrenzt_auf_zwei_minuten():
    segmente = [
        {"start": 0.0, "sprecher_id": None, "text": "Frueh."},
        {"start": 119.0, "sprecher_id": None, "text": "Noch drin."},
        {"start": 121.0, "sprecher_id": None, "text": "Zu spaet."},
    ]
    text = pipeline_service.build_preview_text(segmente, diarization_enabled=False)
    assert "Frueh." in text
    assert "Noch drin." in text
    assert "Zu spaet." not in text


def test_build_preview_text_ohne_segmente():
    assert pipeline_service.build_preview_text([], diarization_enabled=True) == ""
    assert pipeline_service.build_preview_text([], diarization_enabled=False) == ""


@pytest.fixture()
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


def _fake_diarize(normalized_path, min_speakers, max_speakers):
    return [{"start": 0.0, "end": 100000.0, "speaker": "SPEAKER_00"}]


def _make_settings(source_file, tmp_path, resume_mode="fortsetzen"):
    output_dir = tmp_path / "ausgabe"
    return pipeline_service.PipelineSettings(
        source_path=source_file,
        output_dir=output_dir,
        run_protocol=False,
        resume_mode=resume_mode,
    )


def test_pipeline_completes_with_stubbed_backends(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)  # < 600s -> genau ein Chunk

    def transcribe(chunk_wav_path):
        return [{"start": 1.0, "end": 5.0, "text": "Hallo Welt", "speaker": "SPEAKER_00"}]

    result = pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=transcribe,
        diarize_fn=_fake_diarize,
    )
    assert result.export_paths.txt.is_file()
    assert manifest_service.is_fully_processed(result.manifest)


def test_pipeline_skips_diarization_when_disabled(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    def transcribe(chunk_wav_path):
        return [{"start": 1.0, "end": 5.0, "text": "Hallo Welt", "speaker": "SPEAKER_00"}]

    diarize_calls = []

    def diarize_fn_should_not_run(*args, **kwargs):
        diarize_calls.append(args)
        return [{"start": 0.0, "end": 100000.0, "speaker": "SPEAKER_00"}]

    settings = _make_settings(source_file, tmp_path)
    settings.enable_diarization = False

    result = pipeline_service.run_pipeline(
        settings,
        transcribe_chunk_fn=transcribe,
        diarize_fn=diarize_fn_should_not_run,
    )
    assert diarize_calls == []  # Diarisierung wurde nicht aufgerufen -- spart Rechenzeit.

    json_data = json.loads(result.export_paths.json.read_text(encoding="utf-8"))
    assert json_data["sprechertrennung_aktiv"] is False
    assert json_data["anzahl_sprecher"] == 0
    assert json_data["sprecher_zuordnung"] == []

    txt_content = result.export_paths.txt.read_text(encoding="utf-8")
    assert "Sprechertrennung: deaktiviert" in txt_content
    assert "Hallo Welt" in txt_content


def test_pipeline_stops_on_faulty_chunk_and_keeps_previous_progress(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    # 1300s -> 3 Chunks (0-600, 590-1190, 1180-1300).
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    call_count = {"n": 0}

    def flaky_transcribe(chunk_wav_path):
        call_count["n"] += 1
        if "chunk_0002" in chunk_wav_path.name:
            raise RuntimeError("Simulierter Absturz waehrend Chunk 2")
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            transcribe_chunk_fn=flaky_transcribe,
            diarize_fn=_fake_diarize,
        )
    assert call_count["n"] == 2  # Chunk 1 erfolgreich, Chunk 2 schlaegt fehl, Chunk 3 nie versucht

    work_dir = manifest_service.get_work_dir_for_file(
        tmp_path / "arbeitsdaten", manifest_service.compute_file_hash(source_file)
    )
    manifest = manifest_service.load_manifest(work_dir)
    state = manifest_service.find_resumable_state(manifest)
    assert state["fertige_chunks"] == [0]
    assert state["naechster_chunk"] == 1
    assert manifest_service.chunk_transcript_path(work_dir, 0).is_file()
    assert not manifest_service.chunk_transcript_path(work_dir, 1).is_file()


def test_pipeline_resume_does_not_recompute_finished_chunks(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    call_count = {"n": 0}

    def flaky_transcribe(chunk_wav_path):
        call_count["n"] += 1
        if "chunk_0002" in chunk_wav_path.name:
            raise RuntimeError("Simulierter Absturz waehrend Chunk 2")
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            transcribe_chunk_fn=flaky_transcribe,
            diarize_fn=_fake_diarize,
        )
    calls_before_resume = call_count["n"]

    def working_transcribe(chunk_wav_path):
        call_count["n"] += 1
        return [{"start": 1.0, "end": 5.0, "text": f"Text {chunk_wav_path.name}", "speaker": "SPEAKER_00"}]

    result = pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=working_transcribe,
        diarize_fn=_fake_diarize,
    )
    # Nur die beiden verbleibenden Chunks (2 und 3) wurden neu transkribiert.
    assert call_count["n"] - calls_before_resume == 2
    assert manifest_service.is_fully_processed(result.manifest)
    assert result.export_paths.txt.is_file()


def test_pipeline_restart_mode_recomputes_everything(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    call_count = {"n": 0}

    def transcribe(chunk_wav_path):
        call_count["n"] += 1
        return [{"start": 1.0, "end": 5.0, "text": "Text", "speaker": "SPEAKER_00"}]

    settings = _make_settings(source_file, tmp_path)
    pipeline_service.run_pipeline(settings, transcribe_chunk_fn=transcribe, diarize_fn=_fake_diarize)
    assert call_count["n"] == 1

    restart_settings = _make_settings(source_file, tmp_path, resume_mode="neu_beginnen")
    pipeline_service.run_pipeline(restart_settings, transcribe_chunk_fn=transcribe, diarize_fn=_fake_diarize)
    assert call_count["n"] == 2  # wurde bewusst erneut komplett berechnet


def test_pipeline_raises_clear_error_for_missing_file(tmp_path):
    settings = _make_settings(tmp_path / "existiert_nicht.wav", tmp_path)
    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.run_pipeline(settings)


def test_pipeline_can_be_cancelled_between_chunks(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=1300.0)

    def transcribe(chunk_wav_path):
        return [{"start": 1.0, "end": 5.0, "text": "Text", "speaker": "SPEAKER_00"}]

    cancel_after = {"count": 0}

    def should_cancel():
        cancel_after["count"] += 1
        return cancel_after["count"] > 3

    callbacks = pipeline_service.PipelineCallbacks(should_cancel=should_cancel)
    with pytest.raises(pipeline_service.PipelineCancelled):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            callbacks=callbacks,
            transcribe_chunk_fn=transcribe,
            diarize_fn=_fake_diarize,
        )


# ---------------------------------------------------------------------------
# Protokollauswertung: Ueberlappung, Neubeginn und Fehlerbehandlung
# ---------------------------------------------------------------------------

def _vollstaendiges_protokoll(titel: str = "Protokoll") -> str:
    """Antwort des Modells: reiner Text, ohne vorgegebene Struktur."""
    return titel


def _systemprompt_bereitstellen(monkeypatch, tmp_path):
    prompt = tmp_path / "systemprompt.txt"
    prompt.write_text("Du bist ein Protokollassistent.", encoding="utf-8")
    monkeypatch.setattr(utils_paths, "get_system_prompt_file", lambda: prompt)


def _einfaches_segment(_pfad):
    return [{"start": 1.0, "end": 5.0, "text": "Hallo", "speaker": "SPEAKER_00"}]


def test_ueberlappung_landet_nur_in_einem_protokoll_abschnitt():
    # Die Chunks ueberlappen sich um 10 Sekunden. Wird ein Segment aus
    # diesem Bereich beiden Abschnitten mitgegeben, zaehlt das Modell
    # dieselbe Aussage zweimal - genau das hat merge_service vorher
    # muehsam bereinigt.
    plaene = chunking_service.plan_chunks(1200.0)
    segmente = [
        {"start": 100.0, "end": 105.0, "text": "frueh", "sprecher_id": "S0"},
        {"start": 595.0, "end": 598.0, "text": "in der Ueberlappung", "sprecher_id": "S0"},
        {"start": 700.0, "end": 705.0, "text": "spaet", "sprecher_id": "S0"},
    ]

    texte = pipeline_service._build_protocol_chunk_texts(plaene, segmente, {"S0": "Anna"})

    gesamt = "\n".join(eintrag["text"] for eintrag in texte)
    assert gesamt.count("in der Ueberlappung") == 1
    assert gesamt.count("frueh") == 1
    assert gesamt.count("spaet") == 1


def test_protokoll_abschnitte_verlieren_kein_segment():
    # Das verschobene Fenster darf nichts auslassen: Die Abschnitte muessen
    # luecken- UND ueberschneidungsfrei aneinander anschliessen.
    plaene = chunking_service.plan_chunks(1800.0)
    segmente = [
        {"start": float(s), "end": float(s) + 1.0, "text": f"segment{s}", "sprecher_id": "S0"}
        for s in range(0, 1800, 20)
    ]

    texte = pipeline_service._build_protocol_chunk_texts(plaene, segmente, {"S0": "Anna"})

    zeilen = [zeile for eintrag in texte for zeile in eintrag["text"].splitlines()]
    assert len(zeilen) == len(segmente)


def test_neu_beginnen_erzeugt_das_protokoll_wirklich_neu(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    def einstellungen(modus):
        return pipeline_service.PipelineSettings(
            source_path=source_file,
            output_dir=tmp_path / "ausgabe",
            run_protocol=True,
            resume_mode=modus,
        )

    erster = pipeline_service.run_pipeline(
        einstellungen("fortsetzen"),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
        protocol_generate_fn=lambda prompt, system: _vollstaendiges_protokoll("ALT"),
    )
    assert json.loads(erster.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"] == "ALT"

    aufrufe = []

    def neues_modell(prompt, system):
        aufrufe.append(prompt)
        return _vollstaendiges_protokoll("NEU")

    zweiter = pipeline_service.run_pipeline(
        einstellungen("neu_beginnen"),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
        protocol_generate_fn=neues_modell,
    )

    assert aufrufe, "Bei 'neu beginnen' wurde das Modell gar nicht gefragt."
    assert json.loads(zweiter.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"] == "NEU"


def test_neu_beginnen_transkribiert_alle_chunks_erneut(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)
    durchlaeufe = []

    def transkribiere(pfad):
        durchlaeufe.append(pfad)
        return _einfaches_segment(pfad)

    pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=transkribiere,
        diarize_fn=_fake_diarize,
    )
    assert len(durchlaeufe) == 1

    pipeline_service.run_pipeline(
        _make_settings(source_file, tmp_path, resume_mode="neu_beginnen"),
        transcribe_chunk_fn=transkribiere,
        diarize_fn=_fake_diarize,
    )
    assert len(durchlaeufe) == 2


def test_fortsetzen_verwendet_fertige_chunks_weiterhin(monkeypatch, tmp_path, source_file):
    # Gegenprobe zum Neubeginn: Fortsetzen darf gerade NICHT neu rechnen.
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)
    durchlaeufe = []

    def transkribiere(pfad):
        durchlaeufe.append(pfad)
        return _einfaches_segment(pfad)

    for _ in range(2):
        pipeline_service.run_pipeline(
            _make_settings(source_file, tmp_path),
            transcribe_chunk_fn=transkribiere,
            diarize_fn=_fake_diarize,
        )

    assert len(durchlaeufe) == 1


def test_gescheiterte_protokollauswertung_wird_gemeldet(monkeypatch, tmp_path, source_file):
    # Das Transkript ist fertig, nur die Auswertung nicht. Frueher meldete
    # die Ablaufsteuerung trotzdem nur "abgeschlossen", und die Oberflaeche
    # zeigte einen Erfolg an, obwohl keine Protokolldatei entstanden war.
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    stufen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_stage=lambda key, detail: stufen.append(key))

    ergebnis = pipeline_service.run_pipeline(
        pipeline_service.PipelineSettings(
            source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=True
        ),
        callbacks,
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
        # Eine leere Antwort, auch beim zweiten Versuch - so antwortet ein
        # Modell, das die Anfrage nicht beantworten konnte.
        protocol_generate_fn=lambda prompt, system: "",
    )

    assert "protokoll_fehlgeschlagen" in stufen
    assert ergebnis.protocol_paths is None
    assert ergebnis.protokoll_fehler
    assert ergebnis.manifest["protokoll_status"] == manifest_service.STATUS_FEHLGESCHLAGEN
    # Das Transkript bleibt nutzbar.
    assert ergebnis.export_paths.txt.is_file()


def test_nicht_erreichbares_ollama_bricht_die_verarbeitung_nicht_ab(
    monkeypatch, tmp_path, source_file
):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    def ollama_ist_aus(prompt, system):
        raise ollama_service.OllamaError("Ollama ist nicht erreichbar")

    ergebnis = pipeline_service.run_pipeline(
        pipeline_service.PipelineSettings(
            source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=True
        ),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
        protocol_generate_fn=ollama_ist_aus,
    )

    assert ergebnis.export_paths.txt.is_file()
    assert ergebnis.protocol_paths is None
    assert "nicht erreichbar" in (ergebnis.protokoll_fehler or "")


def test_erfolgreiche_auswertung_setzt_keinen_fehler(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    ergebnis = pipeline_service.run_pipeline(
        pipeline_service.PipelineSettings(
            source_path=source_file, output_dir=tmp_path / "ausgabe", run_protocol=True
        ),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
        protocol_generate_fn=lambda prompt, system: _vollstaendiges_protokoll("Fertig"),
    )

    assert ergebnis.protokoll_fehler is None
    assert ergebnis.protocol_paths is not None


# ---------------------------------------------------------------------------
# Zweistufiger Ablauf: eigenstaendige Transkription und eigenstaendige
# Protokollauswertung eines bereits vorliegenden Transkripts.
# ---------------------------------------------------------------------------


def test_run_transcription_completes_without_protocol(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    stufen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_stage=lambda key, detail: stufen.append(key))

    ergebnis = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        callbacks,
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    assert ergebnis.export_paths.txt.is_file()
    assert ergebnis.export_paths.json.is_file()
    assert ergebnis.report_paths is not None
    assert ergebnis.report_paths[0].is_file()
    assert manifest_service.is_fully_processed(ergebnis.manifest)
    assert "protokoll_auswertung" not in stufen  # bewusst kein Protokollschritt
    assert "abgeschlossen" in stufen


def test_run_protocol_liest_export_und_erzeugt_protokoll(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=lambda prompt, system: _vollstaendiges_protokoll("NEU"),
    )

    assert ergebnis.protokoll_fehler is None
    assert ergebnis.protocol_paths is not None
    assert json.loads(ergebnis.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"] == "NEU"
    assert ergebnis.report_paths[0].is_file()


def test_run_protocol_funktioniert_ohne_diarisierung(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    settings = _make_settings(source_file, tmp_path)
    settings.enable_diarization = False
    transkript = pipeline_service.run_transcription(
        settings, transcribe_chunk_fn=_einfaches_segment, diarize_fn=_fake_diarize
    )

    aufgezeichnete_prompts = []

    def protokoll_generieren(prompt, system):
        aufgezeichnete_prompts.append(prompt)
        return _vollstaendiges_protokoll("Ohne Sprecher")

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=protokoll_generieren,
    )

    assert ergebnis.protokoll_fehler is None
    gesamt_prompt = "\n".join(aufgezeichnete_prompts)
    assert "Sprecher unbekannt" not in gesamt_prompt
    assert "SPEAKER_00" not in gesamt_prompt


def test_load_transcript_for_protocol_liest_export_korrekt(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    segments, speaker_names, diarization_enabled, source_stem = pipeline_service.load_transcript_for_protocol(
        transkript.export_paths.json
    )

    assert diarization_enabled is True
    assert source_stem == source_file.stem
    assert len(segments) == 1
    assert segments[0]["text"] == "Hallo"
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 5.0
    assert speaker_names == transkript.speaker_names


def test_load_transcript_for_protocol_wirft_bei_leeren_segmenten(tmp_path):
    datei = tmp_path / "leer.json"
    datei.write_text(json.dumps({"segmente": []}), encoding="utf-8")
    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.load_transcript_for_protocol(datei)


def test_load_transcript_for_protocol_wirft_bei_kaputter_datei(tmp_path):
    datei = tmp_path / "kaputt.json"
    datei.write_text("das ist kein JSON", encoding="utf-8")
    with pytest.raises(pipeline_service.PipelineError):
        pipeline_service.load_transcript_for_protocol(datei)


def test_run_protocol_ist_unabhaengig_von_der_audioquelle(monkeypatch, tmp_path, source_file):
    # Die Nachbearbeitung wird ueber den Hash der TRANSKRIPT-Datei
    # fortsetzbar gemacht, nicht ueber den Hash der Audiodatei - sie muss
    # also auch dann funktionieren, wenn die Audioquelle laengst nicht mehr
    # vorliegt.
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )
    source_file.unlink()

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=lambda prompt, system: _vollstaendiges_protokoll("Ohne Audio"),
    )

    assert ergebnis.protokoll_fehler is None
    erwarteter_work_dir = manifest_service.get_work_dir_for_file(
        tmp_path / "arbeitsdaten", manifest_service.compute_file_hash(transkript.export_paths.json)
    )
    assert ergebnis.work_dir == erwarteter_work_dir
    assert ergebnis.work_dir != transkript.work_dir


def test_run_protocol_meldet_ollama_fehler(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    def ollama_ist_aus(prompt, system):
        raise ollama_service.OllamaError("Ollama ist nicht erreichbar")

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=ollama_ist_aus,
    )

    assert ergebnis.protocol_paths is None
    assert "nicht erreichbar" in (ergebnis.protokoll_fehler or "")
    assert ergebnis.report_paths[0].is_file()


def test_run_protocol_nimmt_den_mitgegebenen_systemprompt(monkeypatch, tmp_path, source_file):
    """'ProtocolSettings.system_prompt' hat Vorrang vor der
    Einstellungsdatei.

    Ohne diesen Weg muesste ein Aufrufer, der den Prompt fuer EINEN Lauf
    vorgibt (das Hauptfenster laesst ihn bearbeiten), ihn
    erst nach 'get_system_prompt_file()' schreiben - und damit den
    gespeicherten Systemprompt dieser Anwendung hier ueberschreiben."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    benutzte_systemprompts = []

    def protokoll_generieren(prompt, system):
        benutzte_systemprompts.append(system)
        return _vollstaendiges_protokoll("NEU")

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt="Nur fuer diesen einen Lauf.",
        ),
        protocol_generate_fn=protokoll_generieren,
    )

    assert ergebnis.protokoll_fehler is None
    assert benutzte_systemprompts
    assert set(benutzte_systemprompts) == {"Nur fuer diesen einen Lauf."}
    # Die Einstellungsdatei bleibt unberuehrt.
    assert (tmp_path / "systemprompt.txt").read_text(encoding="utf-8") == "Du bist ein Protokollassistent."


def test_run_protocol_liest_ohne_mitgegebenen_systemprompt_weiter_die_datei(monkeypatch, tmp_path, source_file):
    """Gegenprobe: Fuer die lokale Anwendung aendert das neue Feld nichts."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    benutzte_systemprompts = []

    def protokoll_generieren(prompt, system):
        benutzte_systemprompts.append(system)
        return _vollstaendiges_protokoll("NEU")

    pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json, output_dir=tmp_path / "ausgabe"
        ),
        protocol_generate_fn=protokoll_generieren,
    )

    assert set(benutzte_systemprompts) == {"Du bist ein Protokollassistent."}


def test_run_protocol_ohne_systemprompt_laesst_das_modell_frei_zusammenfassen(monkeypatch, tmp_path, source_file):
    """Leerer Systemprompt: Das Modell bekommt die neutrale Vorgabe -- und
    keinerlei feste Besprechungsstruktur."""
    from protokoll_assistent.services import protocol_service

    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    benutzte_systemprompts = []

    def protokoll_generieren(prompt, system):
        benutzte_systemprompts.append(system)
        return "Frei zusammengefasst."

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt="",
        ),
        protocol_generate_fn=protokoll_generieren,
    )

    assert ergebnis.protokoll_fehler is None
    assert set(benutzte_systemprompts) == {protocol_service.OHNE_VORGABE_SYSTEMPROMPT}
    daten = json.loads(ergebnis.protocol_paths[0].read_text(encoding="utf-8"))
    assert daten["ohne_systemprompt"] is True


def test_run_protocol_schreibt_genau_den_text_des_modells(monkeypatch, tmp_path, source_file):
    """Die Ausgabedatei enthaelt nur, was das Modell nach dem Systemprompt
    geliefert hat -- keine zusaetzlich eingefuegte Gliederung."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt="Nenne nur die Termine.",
        ),
        protocol_generate_fn=lambda prompt, system: "- 12.10. Abgabe",
    )

    json_pfad, md_pfad = ergebnis.protocol_paths
    assert md_pfad.read_text(encoding="utf-8") == "- 12.10. Abgabe\n"
    daten = json.loads(json_pfad.read_text(encoding="utf-8"))
    assert daten["systemprompt"] == "Nenne nur die Termine."
    assert daten["ohne_systemprompt"] is False
    assert daten["ergebnis"] == "- 12.10. Abgabe"


def test_run_protocol_mit_anderem_systemprompt_liefert_neues_ergebnis(monkeypatch, tmp_path, source_file):
    """Gleiches Transkript, anderer Auftrag: kein Ergebnis zum alten Auftrag."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    def lauf(prompt_text, antwort):
        return pipeline_service.run_protocol(
            pipeline_service.ProtocolSettings(
                transcript_json_path=transkript.export_paths.json,
                output_dir=tmp_path / "ausgabe",
                system_prompt=prompt_text,
            ),
            protocol_generate_fn=lambda prompt, system: antwort,
        )

    # Direkt nach jedem Lauf lesen: Die Ausgabedatei traegt einen Zeitstempel
    # auf die Sekunde genau, zwei Laeufe in einer Sekunde teilen sich den Namen.
    erster = lauf("Erstelle eine Agenda.", "AGENDA")
    assert json.loads(erster.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"] == "AGENDA"
    zweiter = lauf("Erstelle eine Prioritaetenliste.", "PRIORITAETEN")
    assert json.loads(zweiter.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"] == "PRIORITAETEN"


# --------------------------------------------------------------------------
# Automatische Word-Datei
# --------------------------------------------------------------------------
def test_automatische_word_datei_wird_protokolliert(tmp_path, monkeypatch):
    meldungen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_log=meldungen.append)
    dienst = pipeline_service.dokument_export_service
    aufrufe = []

    def erzeugen(transkript, protokoll=None):
        aufrufe.append((transkript, protokoll))
        return tmp_path / "x.docx"

    monkeypatch.setattr(dienst, "automatisches_word", erzeugen)
    pipeline_service._automatisches_word(callbacks, tmp_path / "t.json", tmp_path / "p.json")
    assert aufrufe == [(tmp_path / "t.json", tmp_path / "p.json")]
    assert meldungen == ["Word-Datei erstellt: x.docx"]


def test_automatische_word_datei_ohne_python_docx_bleibt_still(tmp_path, monkeypatch):
    meldungen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_log=meldungen.append)
    monkeypatch.setattr(pipeline_service.dokument_export_service, "automatisches_word", lambda t, p=None: None)
    pipeline_service._automatisches_word(callbacks, tmp_path / "t.json")
    assert meldungen == []


def test_fehler_bei_der_word_datei_bricht_die_verarbeitung_nicht_ab(tmp_path, monkeypatch):
    meldungen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_log=meldungen.append)
    dienst = pipeline_service.dokument_export_service

    def werfen(t, p=None):
        raise dienst.ExportFehler("Zugriff verweigert")

    monkeypatch.setattr(dienst, "automatisches_word", werfen)
    pipeline_service._automatisches_word(callbacks, tmp_path / "t.json")
    assert meldungen == ["Die Word-Datei wurde nicht erstellt: Zugriff verweigert"]


def test_run_protocol_mit_anderem_modell_liefert_neues_ergebnis(monkeypatch, tmp_path, source_file):
    """Gleiches Transkript, gleicher Auftrag, anderes Modell: Die gespeicherten
    Zwischenstaende des alten Modells duerfen nicht wiederverwendet werden."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=300.0)

    transkript = pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path),
        transcribe_chunk_fn=_einfaches_segment,
        diarize_fn=_fake_diarize,
    )

    def lauf(antwort, **modell):
        ergebnis = pipeline_service.run_protocol(
            pipeline_service.ProtocolSettings(
                transcript_json_path=transkript.export_paths.json,
                output_dir=tmp_path / "ausgabe",
                system_prompt="Fasse zusammen.",
                **modell,
            ),
            protocol_generate_fn=lambda prompt, system: antwort,
        )
        return json.loads(ergebnis.protocol_paths[0].read_text(encoding="utf-8"))["ergebnis"]

    assert lauf("VON QWEN", ollama_model="qwen3.5:4b-q4_K_M") == "VON QWEN"
    assert lauf("VON GEMMA", ollama_model="gemma4:12b-it-q4_K_M") == "VON GEMMA"
    # Ueber eine API: die Kennung des API-Modells zaehlt, nicht das lokale Modell.
    assert lauf("VON DER API", ollama_model="gemma4:12b-it-q4_K_M", protokoll_modell_kennung="api:x") == "VON DER API"
    # Dasselbe Modell wie zuvor: Zwischenstand wird wiederverwendet.
    assert lauf("NICHT GEFRAGT", ollama_model="qwen3.5:4b-q4_K_M") == "VON QWEN"


# --------------------------------------------------------------------------
# Live (waehrend der Aufnahme) transkribierte Segmente
# --------------------------------------------------------------------------
def _live_segment(start: float, ende: float, text: str) -> dict:
    return {"start": start, "end": ende, "text": text, "speaker": None, "words": []}


def _live(bis: float, *segmente: dict) -> dict:
    return {"bestaetigt_bis": bis, "segmente": list(segmente)}


def _zaehlende_transkription(gerechnet: list):
    """Attrappe fuer Whisper: merkt sich jedes Mal, welcher Audio-Bereich verlangt wurde (Dateiname des Chunks)."""

    def transcribe(chunk_wav_path):
        gerechnet.append(chunk_wav_path.name)
        return [{"start": 1.0, "end": 4.0, "text": "neu gerechnet", "speaker": None, "words": []}]

    return transcribe


def _ffmpeg_mit_aufzeichnung(monkeypatch, total_duration: float, geschnitten: list):
    _patch_ffmpeg(monkeypatch, total_duration=total_duration)

    def fake_extract(normalized, destination, start, end, ffmpeg_path=None, sample_rate=16000):
        geschnitten.append((destination.name, round(start, 3), round(end, 3)))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dummy-chunk")
        return destination

    monkeypatch.setattr(pipeline_service.ffmpeg_service, "extract_chunk_wav", fake_extract)


def test_voll_live_transkribierte_chunks_werden_nicht_noch_einmal_transkribiert(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    geschnitten: list = []
    _ffmpeg_mit_aufzeichnung(monkeypatch, 1300.0, geschnitten)  # 3 Chunks: 0-600, 590-1190, 1180-1300
    gerechnet: list = []

    settings = _make_settings(source_file, tmp_path)
    settings.vorab_live = _live(
        1220.0,
        _live_segment(10.0, 14.0, "eins"),
        _live_segment(595.0, 599.0, "zwei"),  # in der Ueberlappung von Chunk 0 und 1: steht in beiden
        _live_segment(700.0, 705.0, "drei"),
        _live_segment(1185.0, 1189.0, "vier"),  # Ueberlappung von Chunk 1 und 2
        _live_segment(1210.0, 1215.0, "fuenf"),
    )
    ergebnis = pipeline_service.run_transcription(
        settings, transcribe_chunk_fn=_zaehlende_transkription(gerechnet), diarize_fn=_fake_diarize
    )

    # Chunk 0 und 1 sind ganz abgedeckt; vom letzten (1180-1300) bleibt der Rest ab 1220
    assert gerechnet == ["chunk_0003_rest.wav"]
    assert geschnitten == [("chunk_0003_rest.wav", 1220.0, 1300.0)]  # nur 80 s statt aller 1300
    texte = [segment["text"] for segment in ergebnis.segments]
    assert texte == ["eins", "zwei", "drei", "vier", "fuenf", "neu gerechnet"]  # keine Dubletten aus den Ueberlappungen
    assert manifest_service.is_fully_processed(ergebnis.manifest)
    # Der Rest steht auf der globalen Zeitachse an der richtigen Stelle (Rest ab 1220, im Rest bei 1,0 s)
    assert ergebnis.segments[-1]["start"] == 1221.0
    # Auch im Arbeitsordner abgelegt: Eine Wiederaufnahme findet die Chunks dort.
    assert manifest_service.chunk_transcript_path(ergebnis.work_dir, 0).is_file()


def test_teilweise_abgedeckter_chunk_bekommt_nur_den_rest(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    geschnitten: list = []
    _ffmpeg_mit_aufzeichnung(monkeypatch, 300.0, geschnitten)  # ein Chunk 0-300
    gerechnet: list = []

    settings = _make_settings(source_file, tmp_path)
    settings.vorab_live = _live(250.0, _live_segment(5.0, 9.0, "anfang"), _live_segment(240.0, 249.0, "fast hinten"))
    ergebnis = pipeline_service.run_transcription(
        settings, transcribe_chunk_fn=_zaehlende_transkription(gerechnet), diarize_fn=_fake_diarize
    )

    assert gerechnet == ["chunk_0001_rest.wav"]
    assert geschnitten == [("chunk_0001_rest.wav", 250.0, 300.0)]  # nur 50 s statt 300 s
    assert [s["text"] for s in ergebnis.segments] == ["anfang", "fast hinten", "neu gerechnet"]
    assert ergebnis.segments[2]["start"] == 251.0  # 250 + 1 s im Rest


def test_zu_wenig_live_abdeckung_lohnt_nicht_der_chunk_wird_ganz_transkribiert(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    geschnitten: list = []
    _ffmpeg_mit_aufzeichnung(monkeypatch, 300.0, geschnitten)
    gerechnet: list = []

    settings = _make_settings(source_file, tmp_path)
    settings.vorab_live = _live(20.0, _live_segment(5.0, 9.0, "zu wenig"))  # nur 20 s von 300
    ergebnis = pipeline_service.run_transcription(
        settings, transcribe_chunk_fn=_zaehlende_transkription(gerechnet), diarize_fn=_fake_diarize
    )

    assert gerechnet == ["chunk_0001.wav"] and geschnitten == [("chunk_0001.wav", 0.0, 300.0)]
    assert [s["text"] for s in ergebnis.segments] == ["neu gerechnet"]  # die Live-Segmente werden nicht gemischt


@pytest.mark.parametrize(
    "vorab",
    [
        None,
        {},
        {"bestaetigt_bis": 100.0},
        {"bestaetigt_bis": 100.0, "segmente": []},
        {"bestaetigt_bis": "x", "segmente": [{"start": 1.0, "end": 2.0}]},
        {"bestaetigt_bis": 0.0, "segmente": [{"start": 1.0, "end": 2.0}]},
        {"bestaetigt_bis": 100.0, "segmente": ["kaputt", {"start": "a", "end": 2.0}]},
    ],
)
def test_live_lesen_lehnt_unbrauchbares_ab(vorab):
    assert pipeline_service._live_lesen(vorab) == (0.0, [])


def test_live_lesen_und_abdeckung():
    bis, segmente = pipeline_service._live_lesen(_live(500.0, _live_segment(1.0, 2.0, "a"), "kaputt"))
    assert bis == 500.0 and len(segmente) == 1
    plaene = chunking_service.plan_chunks(1300.0)  # 0-600, 590-1190, 1180-1300

    def abdeckung(bis_):
        return [pipeline_service._live_abdeckung(p, bis_) for p in plaene]

    assert abdeckung(0.0) == ["keine", "keine", "keine"]
    assert abdeckung(500.0) == ["teil", "keine", "keine"]   # 500 s von Chunk 0, aber nichts von Chunk 1
    assert abdeckung(600.0) == ["voll", "keine", "keine"]
    assert abdeckung(1190.0) == ["voll", "voll", "keine"]   # von Chunk 2 erst 10 s: lohnt nicht
    assert abdeckung(1220.0) == ["voll", "voll", "teil"]    # 40 s von Chunk 2
    assert abdeckung(1300.0) == ["voll", "voll", "voll"]


def test_ist_alles_live_fertig_wird_whisper_nicht_geladen(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=300.0)  # ein Chunk
    geladen = []
    monkeypatch.setattr(
        pipeline_service.transcription_service, "load_whisper_model", lambda *a, **k: geladen.append(a)
    )
    monkeypatch.setattr(pipeline_service.model_service, "get_device_and_compute_type", lambda *_a: ("cpu", "int8"))
    monkeypatch.setattr(pipeline_service.model_service, "prepare_offline_mode", lambda *_a: None)
    monkeypatch.setattr(pipeline_service.model_service, "get_gpu_description", lambda: "CPU")
    settings = _make_settings(source_file, tmp_path)
    settings.enable_diarization = False
    settings.vorab_live = _live(300.0, _live_segment(1.0, 4.0, "alles live"))
    ergebnis = pipeline_service.run_transcription(settings)  # ohne Attrappe: wuerde sonst Whisper laden
    assert geladen == []
    assert [segment["text"] for segment in ergebnis.segments] == ["alles live"]


def test_live_segmente_mit_woertern_behalten_ihre_wortzeiten_im_chunk(monkeypatch, tmp_path, source_file):
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _patch_ffmpeg(monkeypatch, total_duration=700.0)  # 0-600, 590-700
    settings = _make_settings(source_file, tmp_path)
    mit_woertern = {
        "start": 600.0,
        "end": 604.0,
        "text": "zweiter Chunk",
        "speaker": None,
        "words": [{"word": "zweiter", "start": 600.0, "end": 602.0}, {"word": "Chunk", "start": 602.0, "end": 604.0}],
    }
    settings.vorab_live = _live(700.0, _live_segment(5.0, 9.0, "erster"), mit_woertern)
    ergebnis = pipeline_service.run_transcription(settings, transcribe_chunk_fn=lambda _w: [], diarize_fn=_fake_diarize)
    segment = next(s for s in ergebnis.segments if s["text"] == "zweiter Chunk")
    assert segment["start"] == 600.0 and segment["words"][0]["start"] == 600.0  # global wie zuvor
    lokal = json.loads(manifest_service.chunk_transcript_path(ergebnis.work_dir, 1).read_text(encoding="utf-8"))
    assert lokal[0]["start"] == 10.0 and lokal[0]["words"][1]["end"] == 14.0  # im Chunk (Start 590) relativ


# --------------------------------------------------------------------------
# Auswertung: schon waehrend der Aufnahme berechnete Teilergebnisse
# --------------------------------------------------------------------------
def _langes_transkript(monkeypatch, tmp_path, source_file, dauer: float = 1300.0):
    """Ein fertiges Transkript (3 Chunks bei 1300 s) mit Sprechertrennung."""
    monkeypatch.setattr(utils_paths, "get_work_dir", lambda: tmp_path / "arbeitsdaten")
    _systemprompt_bereitstellen(monkeypatch, tmp_path)
    _patch_ffmpeg(monkeypatch, total_duration=dauer)

    def chunk_segmente(chunk_wav):
        return [{"start": float(k * 10), "end": float(k * 10 + 4), "text": f"Satz {k}", "speaker": None} for k in range(5)]

    return pipeline_service.run_transcription(
        _make_settings(source_file, tmp_path), transcribe_chunk_fn=chunk_segmente, diarize_fn=_fake_diarize
    )


def test_ohne_sprecher_bekommt_das_modell_nur_den_fliesstext(monkeypatch, tmp_path, source_file):
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file, dauer=300.0)
    prompts: list[str] = []

    def lauf(ohne_sprecher: bool) -> str:
        prompts.clear()
        pipeline_service.run_protocol(
            pipeline_service.ProtocolSettings(
                transcript_json_path=transkript.export_paths.json,
                output_dir=tmp_path / "ausgabe",
                system_prompt=f"Auftrag {ohne_sprecher}",  # eigener Auftrag: keine alten Zwischenstaende
                ohne_sprecher=ohne_sprecher,
            ),
            protocol_generate_fn=lambda prompt, system: prompts.append(prompt) or "Ergebnis",
        )
        return "\n".join(prompts)

    mit = lauf(False)
    ohne = lauf(True)
    assert "Sprecher" in mit and "[00:00" in mit
    assert "Sprecher" not in ohne and "[00:00" not in ohne and "Satz 0" in ohne


def test_vorab_ausgewertete_abschnitte_werden_uebernommen(monkeypatch, tmp_path, source_file):
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file)
    segmente, namen, _diarisierung, _stamm = pipeline_service.load_transcript_for_protocol(transkript.export_paths.json)
    plaene = chunking_service.plan_chunks(max(s["end"] for s in segmente))
    chunk_texte = pipeline_service.baue_protokoll_chunk_texte(plaene, segmente, namen, False, fliesstext=True)
    assert len(chunk_texte) == 3
    auftrag = "Liste die ToDos auf."
    modell = "qwen-test"
    stufe1 = {}
    for chunk in chunk_texte[:2]:  # die ersten beiden Abschnitte waren schon waehrend der Aufnahme fertig
        prompt = protocol_service.build_stage1_prompt(
            chunk["index"], chunk["start_str"], chunk["end_str"], chunk["text"]
        )
        stufe1[protocol_service.eingabe_kennung(prompt, auftrag, modell)] = f"VORAB {chunk['index']}"

    anfragen: list[str] = []
    protokoll: list[str] = []
    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt=auftrag,
            protokoll_modell_kennung=modell,
            ohne_sprecher=True,
            vorab_auswertung=lambda: {"stufe1": stufe1, "stufe2": {}},
        ),
        pipeline_service.PipelineCallbacks(on_log=protokoll.append),
        protocol_generate_fn=lambda prompt, system: anfragen.append(prompt) or "ERGEBNIS",
    )

    assert ergebnis.protokoll_fehler is None
    # Ohne Vorab: 3 Abschnitte + 1 Gruppe. Jetzt: nur Abschnitt 3 und die Gruppe
    assert len(anfragen) == 2 and "Abschnitt 3 " in anfragen[0]
    assert "VORAB 0" in anfragen[1] and "VORAB 1" in anfragen[1]
    assert any("Schon waehrend der Aufnahme ausgewertet: 2 Abschnitte" in zeile for zeile in protokoll)


def test_vorab_auswertung_fuer_ein_anderes_modell_wird_nicht_benutzt(monkeypatch, tmp_path, source_file):
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file)
    segmente, namen, _d, _s = pipeline_service.load_transcript_for_protocol(transkript.export_paths.json)
    plaene = chunking_service.plan_chunks(max(s["end"] for s in segmente))
    chunk_texte = pipeline_service.baue_protokoll_chunk_texte(plaene, segmente, namen, False, fliesstext=True)
    prompt = protocol_service.build_stage1_prompt(
        0, chunk_texte[0]["start_str"], chunk_texte[0]["end_str"], chunk_texte[0]["text"]
    )
    stufe1 = {protocol_service.eingabe_kennung(prompt, "Auftrag", "modell-live"): "VORAB 0"}
    anfragen: list[str] = []
    pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt="Auftrag",
            protokoll_modell_kennung="modell-final",  # die fertige Auswertung rechnet mit einem anderen Modell
            ohne_sprecher=True,
            vorab_auswertung=lambda: {"stufe1": stufe1, "stufe2": {}},
        ),
        protocol_generate_fn=lambda p, s: anfragen.append(p) or "E",
    )
    assert len(anfragen) == 4 and all("VORAB" not in a for a in anfragen)  # alles neu gefragt


def test_fehler_in_der_vorab_auswertung_stoert_die_auswertung_nicht(monkeypatch, tmp_path, source_file):
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file, dauer=300.0)

    def kaputt():
        raise RuntimeError("Teilauswertung weg")

    protokoll: list[str] = []
    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript.export_paths.json,
            output_dir=tmp_path / "ausgabe",
            system_prompt="Auftrag",
            vorab_auswertung=kaputt,
        ),
        pipeline_service.PipelineCallbacks(on_log=protokoll.append),
        protocol_generate_fn=lambda p, s: "ERGEBNIS",
    )
    assert ergebnis.protokoll_fehler is None and ergebnis.protocol_paths is not None
    assert any("Vorab-Auswertung nicht verwendet" in zeile for zeile in protokoll)


def test_kuerzere_auswertungsabschnitte_teilen_das_transkript_feiner(monkeypatch, tmp_path, source_file):
    # Text liegt bei 0-44 s und 590-634 s: mit 600-s-Abschnitten sind es 2 Abschnitte, mit 180-s-Abschnitten
    # (ab 0, 170, 340, 510 s) hat der vierte den Text ab 590 s.
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file, dauer=700.0)
    anfragen: list[str] = []

    def lauf(abschnitt: float | None) -> list[str]:
        anfragen.clear()
        pipeline_service.run_protocol(
            pipeline_service.ProtocolSettings(
                transcript_json_path=transkript.export_paths.json,
                output_dir=tmp_path / "ausgabe",
                system_prompt="Auftrag",
                abschnitt_sekunden=abschnitt,
            ),
            protocol_generate_fn=lambda prompt, system: anfragen.append(prompt) or "E",
        )
        return [a for a in anfragen if a.startswith("Das ist Abschnitt")]

    standard = lauf(None)
    kurz = lauf(180.0)  # eigene Zwischenstaende: die des 600-s-Laufs werden nicht wiederverwendet
    assert len(standard) == 2 and not any("Abschnitt 4 " in a for a in standard)
    assert any("Abschnitt 4 " in a for a in kurz)


def test_vorab_ausgewertete_abschnitte_gelten_nur_fuer_dieselbe_abschnittslaenge(monkeypatch, tmp_path, source_file):
    transkript = _langes_transkript(monkeypatch, tmp_path, source_file, dauer=700.0)
    segmente, namen, _d, _s = pipeline_service.load_transcript_for_protocol(transkript.export_paths.json)
    plaene = chunking_service.plan_chunks(max(s["end"] for s in segmente), chunk_length=180.0)
    texte = pipeline_service.baue_protokoll_chunk_texte(plaene, segmente, namen, False, fliesstext=True)
    assert len(texte) == 2  # Text nur bei 0-44 s und 590-634 s: Abschnitt 1 und 4
    stufe1 = {}
    for chunk in texte:
        prompt = protocol_service.build_stage1_prompt(
            int(chunk["index"]), chunk["start_str"], chunk["end_str"], chunk["text"]
        )
        stufe1[protocol_service.eingabe_kennung(prompt, "Auftrag", "m")] = f"VORAB {chunk['index']}"

    def lauf(abschnitt: float | None, ordner: str) -> list[str]:
        anfragen: list[str] = []
        pipeline_service.run_protocol(
            pipeline_service.ProtocolSettings(
                transcript_json_path=transkript.export_paths.json,
                output_dir=tmp_path / ordner,
                system_prompt="Auftrag",
                protokoll_modell_kennung="m",
                ohne_sprecher=True,
                abschnitt_sekunden=abschnitt,
                vorab_auswertung=lambda: {"stufe1": stufe1, "stufe2": {}},
            ),
            protocol_generate_fn=lambda p, s: anfragen.append(p) or "E",
        )
        return [a for a in anfragen if a.startswith("Das ist Abschnitt")]

    assert lauf(180.0, "kurz") == []  # beide Abschnitte kamen aus der Vorab-Auswertung
    assert len(lauf(None, "standard")) == 2  # bei 600-s-Abschnitten passt davon nichts


def test_ohne_sprecher_haengt_der_text_nicht_von_der_teilung_nach_sprechern_ab():
    """Die wortgenaue Sprecherzuordnung teilt ein Segment beim Sprecherwechsel. Waehrend der Aufnahme gibt es diese
    Teilung noch nicht -- der Auswertungstext ohne Sprecher muss trotzdem derselbe sein, sonst passt keine
    Vorab-Auswertung (die Eingabekennung waere eine andere)."""
    from protokoll_assistent.services import speaker_merge_service

    woerter = [
        {"start": 0.0, "end": 0.4, "word": " Hallo"},
        {"start": 0.4, "end": 0.9, "word": " zusammen,"},
        {"start": 1.2, "end": 1.5, "word": " ja"},
        {"start": 1.5, "end": 2.0, "word": " genau."},
    ]
    live = [{"start": 0.0, "end": 2.0, "text": "Hallo zusammen, ja genau.", "words": woerter}]
    turns = [{"start": 0.0, "end": 1.0, "speaker": "A"}, {"start": 1.1, "end": 2.0, "speaker": "B"}]
    fertig = speaker_merge_service.assign_speakers_by_words(live, turns)
    assert len(fertig) == 2  # geteilt

    plaene = chunking_service.plan_chunks(2.0)
    assert pipeline_service.baue_protokoll_chunk_texte(
        plaene, live, {}, False, fliesstext=True
    ) == pipeline_service.baue_protokoll_chunk_texte(plaene, fertig, {}, False, fliesstext=True)
    # Zeilenweise (die Form ohne 'fliesstext') unterschieden sie sich
    assert pipeline_service.baue_protokoll_chunk_texte(plaene, live, {}, False) != (
        pipeline_service.baue_protokoll_chunk_texte(plaene, fertig, {}, False)
    )
