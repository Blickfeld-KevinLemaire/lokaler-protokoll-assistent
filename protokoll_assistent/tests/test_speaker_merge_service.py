import pytest

from protokoll_assistent.services.speaker_merge_service import (
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


# --- wortgenaue Zuordnung ---------------------------------------------------


def _wort(text, start, ende):
    return {"word": text, "start": start, "end": ende}


def test_wortgenau_teilt_segment_bei_sprecherwechsel():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segment = {
        "start": 0.0,
        "end": 4.0,
        "text": "Guten Tag zusammen danke Anna",
        "nummer": 1,
        "words": [
            _wort(" Guten", 0.0, 0.5),
            _wort(" Tag", 0.5, 1.0),
            _wort(" zusammen", 1.0, 2.0),
            _wort(" danke", 2.5, 3.0),
            _wort(" Anna", 3.0, 4.0),
        ],
    }
    turns = [
        {"start": 0.0, "end": 2.2, "speaker": "SPEAKER_00"},
        {"start": 2.2, "end": 4.0, "speaker": "SPEAKER_01"},
    ]
    ergebnis = assign_speakers_by_words([segment], turns)
    assert [(s["sprecher_id"], s["text"]) for s in ergebnis] == [
        ("SPEAKER_00", "Guten Tag zusammen"),
        ("SPEAKER_01", "danke Anna"),
    ]
    assert ergebnis[0]["end"] == 2.0
    assert ergebnis[1]["start"] == 2.5
    assert [s["nummer"] for s in ergebnis] == [1, 2]


def test_wortgenau_ein_sprecher_laesst_segment_unveraendert():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segment = {
        "start": 0.0,
        "end": 2.0,
        "text": "Ein  Satz.",
        "words": [_wort(" Ein", 0.0, 1.0), _wort(" Satz.", 1.0, 2.0)],
    }
    ergebnis = assign_speakers_by_words([segment], [{"start": 0.0, "end": 5.0, "speaker": "S0"}])
    assert len(ergebnis) == 1
    assert ergebnis[0]["text"] == "Ein  Satz."
    assert ergebnis[0]["sprecher_id"] == "S0"
    assert "sprecher_id" not in segment


def test_wortgenau_ohne_wortzeiten_faellt_auf_ueberlappung_zurueck():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segmente = [
        {"start": 0.0, "end": 5.0, "text": "a", "words": []},
        {"start": 0.0, "end": 5.0, "text": "b"},
        {"start": 0.0, "end": 5.0, "text": "c", "words": [{"word": "c"}]},
    ]
    turns = [
        {"start": 0.0, "end": 1.0, "speaker": "S0"},
        {"start": 1.0, "end": 5.0, "speaker": "S1"},
    ]
    ergebnis = assign_speakers_by_words(segmente, turns)
    assert [s["sprecher_id"] for s in ergebnis] == ["S1", "S1", "S1"]
    assert all("nummer" not in s for s in ergebnis)


def test_wortgenau_einzelwort_an_der_grenze_wird_geglaettet():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segment = {
        "start": 0.0,
        "end": 3.0,
        "text": "eins zwei drei",
        "words": [_wort(" eins", 0.0, 1.0), _wort(" zwei", 1.0, 2.0), _wort(" drei", 2.0, 3.0)],
    }
    turns = [
        {"start": 0.0, "end": 1.0, "speaker": "S0"},
        {"start": 1.0, "end": 2.0, "speaker": "S1"},
        {"start": 2.0, "end": 3.0, "speaker": "S0"},
    ]
    ergebnis = assign_speakers_by_words([segment], turns)
    assert len(ergebnis) == 1
    assert ergebnis[0]["sprecher_id"] == "S0"


def test_wortgenau_luecke_nimmt_naechsten_sprecher_zu_weit_entfernt_bleibt_leer():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segment = {
        "start": 10.0,
        "end": 12.0,
        "text": "x y",
        "words": [_wort(" x", 10.0, 11.0), _wort(" y", 11.0, 12.0)],
    }
    nah = assign_speakers_by_words([segment], [{"start": 0.0, "end": 9.5, "speaker": "S0"}])
    assert nah[0]["sprecher_id"] == "S0"
    weit = assign_speakers_by_words([segment], [{"start": 0.0, "end": 5.0, "speaker": "S0"}])
    assert weit[0]["sprecher_id"] is None
    ohne = assign_speakers_by_words([segment], [])
    assert ohne[0]["sprecher_id"] is None


def test_wortgenau_woerter_ohne_leerzeichen_werden_mit_leerzeichen_verbunden():
    from protokoll_assistent.services.speaker_merge_service import assign_speakers_by_words

    segment = {
        "start": 0.0,
        "end": 2.0,
        "text": "Hallo Welt",
        "words": [_wort("Hallo", 0.0, 1.0), _wort("Welt", 1.0, 2.0)],
    }
    turns = [{"start": 0.0, "end": 1.0, "speaker": "S0"}, {"start": 1.0, "end": 2.0, "speaker": "S1"}]
    ergebnis = assign_speakers_by_words([segment], turns)
    assert [s["text"] for s in ergebnis] == ["Hallo", "Welt"]
