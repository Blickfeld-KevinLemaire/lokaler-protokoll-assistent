import json

import pytest

from services import protocol_service

VALID_PROTOCOL = {
    "titel": "Test",
    "kurzzusammenfassung": "Zusammenfassung",
    "teilnehmende_oder_sprecher": [],
    "themen": [],
    "entscheidungen": [],
    "aufgaben": [],
    "termine": [],
    "offene_fragen": [],
    "wichtige_fakten": [],
    "unsichere_transkriptstellen": [],
    "quellenhinweise": [],
}


def _fake_generate_factory(responses_by_call=None, raise_on_prompt_containing=None):
    """Erstellt eine generate_fn-Stub-Funktion ohne echtes Ollama."""
    calls = {"count": 0, "prompts": []}

    def generate(prompt: str, system: str):
        calls["count"] += 1
        calls["prompts"].append(prompt)
        if raise_on_prompt_containing and raise_on_prompt_containing in prompt:
            raise RuntimeError("Simulierter Verbindungsfehler zu Ollama")
        if responses_by_call and calls["count"] in responses_by_call:
            return responses_by_call[calls["count"]]
        if "finale strukturierte Protokoll" in prompt:
            return dict(VALID_PROTOCOL)
        return {"kernaussagen": [f"Punkt aus Aufruf {calls['count']}"]}

    return generate, calls


def test_stage1_result_is_cached_and_not_recomputed(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    path = tmp_path / "chunk_0001_analyse.json"

    first = protocol_service.run_stage1_chunk_analysis(
        0, "Text", "00:00:00", "00:10:00", "System", generate_fn, path, tmp_path / "roh"
    )
    assert calls["count"] == 1
    assert path.is_file()

    second = protocol_service.run_stage1_chunk_analysis(
        0, "Text", "00:00:00", "00:10:00", "System", generate_fn, path, tmp_path / "roh"
    )
    assert calls["count"] == 1  # kein erneuter Aufruf
    assert first == second


def test_generate_validated_repairs_once_on_invalid_json(tmp_path):
    generate_fn, calls = _fake_generate_factory(
        responses_by_call={1: {"nichts_brauchbares": True}, 2: {"kernaussagen": ["repariert"]}}
    )
    result = protocol_service.generate_validated(
        "Prompt",
        "System",
        generate_fn,
        lambda data: (isinstance(data, dict) and "kernaussagen" in data, ["Feld fehlt"]),
        tmp_path / "roh",
        "test",
    )
    assert calls["count"] == 2
    assert result == {"kernaussagen": ["repariert"]}
    dumps = list((tmp_path / "roh").glob("*ungueltig*"))
    assert len(dumps) == 1


def test_generate_validated_raises_after_failed_repair(tmp_path):
    generate_fn, calls = _fake_generate_factory(
        responses_by_call={1: {"falsch": True}, 2: {"immer_noch_falsch": True}}
    )
    with pytest.raises(protocol_service.ProtocolValidationError):
        protocol_service.generate_validated(
            "Prompt",
            "System",
            generate_fn,
            lambda data: (isinstance(data, dict) and "kernaussagen" in data, ["Feld fehlt"]),
            tmp_path / "roh",
            "test",
        )
    assert calls["count"] == 2


def test_full_pipeline_hierarchical_stages_produce_valid_protocol(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    chunk_texts = [
        {"index": i, "start_str": f"00:{i*10:02d}:00", "end_str": f"00:{i*10+10:02d}:00", "text": f"Chunk {i}"}
        for i in range(4)
    ]
    stage_progress = []
    result = protocol_service.run_full_protocol_pipeline(
        chunk_texts,
        tmp_path,
        "System",
        generate_fn,
        group_size=2,
        progress_cb=lambda stage, current, total: stage_progress.append(stage),
    )
    assert result["titel"] == "Test"
    # 4 Chunk-Analysen + 2 Gruppen-Zusammenfuehrungen + 1 finales Protokoll = 7 Aufrufe.
    assert calls["count"] == 7
    assert (tmp_path / "analysen" / "chunk_0001_analyse.json").is_file()
    assert (tmp_path / "zusammengefuehrt" / "protokoll.json").is_file()
    assert "stufe1_chunk_analyse" in stage_progress
    assert "stufe3_gesamtprotokoll" in stage_progress


def test_faulty_single_chunk_does_not_lose_previous_progress(tmp_path):
    generate_fn, calls = _fake_generate_factory(raise_on_prompt_containing="Abschnitt 2,")
    chunk_texts = [
        {"index": 0, "start_str": "00:00:00", "end_str": "00:10:00", "text": "Erster Abschnitt"},
        {"index": 1, "start_str": "00:10:00", "end_str": "00:20:00", "text": "Zweiter Abschnitt (fehlerhaft)"},
    ]

    with pytest.raises(RuntimeError):
        protocol_service.run_full_protocol_pipeline(chunk_texts, tmp_path, "System", generate_fn, group_size=2)

    # Chunk 0 wurde bereits erfolgreich analysiert und gespeichert.
    chunk0_path = tmp_path / "analysen" / "chunk_0001_analyse.json"
    assert chunk0_path.is_file()
    chunk1_path = tmp_path / "analysen" / "chunk_0002_analyse.json"
    assert not chunk1_path.is_file()

    calls_before_retry = calls["count"]

    # Ein erneuter Lauf (z.B. nach Behebung des Fehlers) darf Chunk 0 NICHT
    # erneut anfragen -- nur der fehlgeschlagene Chunk 1 wird nachgeholt.
    generate_fn2, calls2 = _fake_generate_factory()
    chunk0_before = json.loads(chunk0_path.read_text(encoding="utf-8"))
    result = protocol_service.run_full_protocol_pipeline(chunk_texts, tmp_path, "System", generate_fn2, group_size=2)
    assert calls2["count"] < calls_before_retry + 3  # nur Chunk 1 + Gruppe + Protokoll, nicht Chunk 0 erneut
    assert json.loads(chunk0_path.read_text(encoding="utf-8")) == chunk0_before
    assert result["titel"] == "Test"
