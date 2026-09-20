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

import utils.paths as utils_paths
from services import chunking_service, manifest_service, ollama_service, pipeline_service


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

def _vollstaendiges_protokoll(titel: str = "Protokoll") -> dict:
    return {
        "titel": titel,
        "kurzzusammenfassung": "",
        "teilnehmende_oder_sprecher": [],
        "themen": [],
        "entscheidungen": [],
        "aufgaben": [],
        "termine": [],
        "offene_fragen": [],
        "wichtige_fakten": [],
        "unsichere_transkriptstellen": [],
        "quellenhinweise": [],
        "kernaussagen": [],
    }


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
    assert json.loads(erster.protocol_paths[0].read_text(encoding="utf-8"))["titel"] == "ALT"

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
    assert json.loads(zweiter.protocol_paths[0].read_text(encoding="utf-8"))["titel"] == "NEU"


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
        # Ein Fehlerobjekt statt der geforderten Struktur - so antwortet ein
        # Modell, das die Anfrage nicht beantworten konnte.
        protocol_generate_fn=lambda prompt, system: {"error": "Modell nicht geladen"},
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
