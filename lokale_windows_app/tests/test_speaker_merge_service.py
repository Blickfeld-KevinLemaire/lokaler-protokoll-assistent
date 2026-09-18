import pytest

from services.speaker_merge_service import (
    assign_speakers_by_overlap,
    cosine_similarity,
    match_speakers_across_chunks,
)


def test_cosine_similarity_identical_vectors_is_one():
    vector = [1.0, 2.0, 3.0]
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_assign_speakers_by_overlap_picks_largest_overlap():
    segments = [{"start": 0.0, "end": 5.0, "text": "hallo"}]
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 5.0, "speaker": "SPEAKER_01"},
    ]
    result = assign_speakers_by_overlap(segments, turns)
    assert result[0]["sprecher_id"] == "SPEAKER_01"


def test_assign_speakers_by_overlap_no_matching_turn_leaves_none():
    segments = [{"start": 100.0, "end": 105.0, "text": "text"}]
    turns = [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]
    result = assign_speakers_by_overlap(segments, turns)
    assert result[0]["sprecher_id"] is None


def _embedding(base, noise=0.0):
    return [base + noise, base * 0.5 - noise, base * 0.2]


def test_similar_embeddings_across_chunks_are_merged():
    embeddings = {
        0: {"SPEAKER_00": _embedding(1.0), "SPEAKER_01": _embedding(5.0)},
        1: {"SPEAKER_00": _embedding(5.0, noise=0.01), "SPEAKER_01": _embedding(1.0, noise=0.01)},
    }
    mapping = match_speakers_across_chunks(embeddings, threshold=0.9)
    # Chunk 1's SPEAKER_00 (aehnlich zu Chunk 0's SPEAKER_01) muss demselben globalen Sprecher zugeordnet werden.
    assert mapping[(0, "SPEAKER_01")]["global_id"] == mapping[(1, "SPEAKER_00")]["global_id"]
    assert mapping[(0, "SPEAKER_00")]["global_id"] == mapping[(1, "SPEAKER_01")]["global_id"]


def test_dissimilar_embeddings_never_merged_below_threshold():
    embeddings = {
        0: {"SPEAKER_00": [1.0, 0.0, 0.0]},
        1: {"SPEAKER_00": [0.0, 1.0, 0.0]},  # orthogonal -> Aehnlichkeit 0
    }
    mapping = match_speakers_across_chunks(embeddings, threshold=0.75)
    assert mapping[(0, "SPEAKER_00")]["global_id"] != mapping[(1, "SPEAKER_00")]["global_id"]
    assert mapping[(1, "SPEAKER_00")]["neu_da_unter_schwelle"] is True


def test_very_first_speaker_overall_gets_full_confidence():
    embeddings = {0: {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.0, 1.0]}}
    mapping = match_speakers_across_chunks(embeddings)
    # Der allererste Sprecher eroeffnet den ersten globalen Sprecher ohne Vergleich.
    assert mapping[(0, "SPEAKER_00")]["confidence"] == 1.0
    # Der zweite (dissimilare) Sprecher wird gegen den ersten verglichen,
    # liegt unter dem Schwellwert und wird deshalb korrekt NICHT
    # zusammengefuehrt, sondern als neuer, eigener globaler Sprecher angelegt.
    assert mapping[(0, "SPEAKER_01")]["global_id"] != mapping[(0, "SPEAKER_00")]["global_id"]
    assert mapping[(0, "SPEAKER_01")]["neu_da_unter_schwelle"] is True
