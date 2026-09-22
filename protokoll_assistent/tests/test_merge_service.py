from protokoll_assistent.services.chunking_service import plan_chunks
from protokoll_assistent.services.merge_service import (
    merge_chunk_into_result,
    merge_chunk_transcripts,
    text_similarity,
    to_global_segments,
)


def test_to_global_segments_adds_offset():
    local = [{"start": 1.0, "end": 2.0, "text": "hallo", "speaker": "SPEAKER_00"}]
    global_segments = to_global_segments(local, offset=590.0)
    assert global_segments[0]["start"] == 591.0
    assert global_segments[0]["end"] == 592.0
    # Original bleibt unveraendert.
    assert local[0]["start"] == 1.0


def test_exact_duplicate_in_overlap_is_removed():
    merged = [{"start": 595.0, "end": 599.0, "text": "und dann haben wir das Protokoll verschickt"}]
    new_chunk = [{"start": 590.0, "end": 594.0, "text": "und dann haben wir das Protokoll verschickt"}]
    result = merge_chunk_into_result(list(merged), new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert len(result) == 1  # das Duplikat wurde verworfen


def test_uncertain_overlap_text_is_kept_and_flagged():
    merged = [{"start": 595.0, "end": 599.0, "text": "und dann haben wir das Protokoll verschickt"}]
    new_chunk = [{"start": 590.0, "end": 594.0, "text": "und dann haben wir"}]
    result = merge_chunk_into_result(list(merged), new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert len(result) == 2
    assert result[1].get("moegliche_ueberschneidung") is True


def test_distinct_text_in_overlap_window_is_kept_unmarked():
    merged = [{"start": 595.0, "end": 599.0, "text": "wir sprechen ueber das Budget"}]
    new_chunk = [{"start": 590.0, "end": 594.0, "text": "ganz andere voellig verschiedene Aussage hier"}]
    result = merge_chunk_into_result(list(merged), new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert len(result) == 2
    assert "moegliche_ueberschneidung" not in result[1]


def test_segments_outside_overlap_window_always_kept():
    merged = [{"start": 100.0, "end": 105.0, "text": "frueher Text"}]
    new_chunk = [{"start": 700.0, "end": 705.0, "text": "spaeterer Text ausserhalb des Fensters"}]
    result = merge_chunk_into_result(list(merged), new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert len(result) == 2


def test_text_similarity_identical_is_one():
    assert text_similarity("Hallo Welt.", "hallo welt") == 1.0


def test_full_merge_produces_sorted_global_segments_with_numbers():
    total_duration = 20 * 60.0
    plans = plan_chunks(total_duration)
    chunk_segments = []
    for plan in plans:
        chunk_segments.append(
            [{"start": 5.0, "end": 15.0, "text": f"Inhalt von Chunk {plan.index}", "speaker": "SPEAKER_00"}]
        )
    merged = merge_chunk_transcripts(plans, chunk_segments)
    starts = [segment["start"] for segment in merged]
    assert starts == sorted(starts)
    assert [segment["nummer"] for segment in merged] == list(range(1, len(merged) + 1))
    # Globale Zeitstempel: Chunk-Index 1 beginnt bei 590s, also global 595s.
    assert any(abs(segment["start"] - 595.0) < 0.001 for segment in merged)
