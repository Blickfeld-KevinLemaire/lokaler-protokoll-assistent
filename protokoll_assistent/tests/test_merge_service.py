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


def test_to_global_segments_verschiebt_auch_die_wortzeiten():
    from protokoll_assistent.services.merge_service import to_global_segments

    lokal = [{"start": 1.0, "end": 2.0, "text": "a", "words": [{"word": " a", "start": 1.0, "end": 2.0}]}]
    global_ = to_global_segments(lokal, 100.0)
    assert global_[0]["words"] == [{"word": " a", "start": 101.0, "end": 102.0}]
    assert lokal[0]["words"][0]["start"] == 1.0


# --------------------------------------------------------------------------
# Saetze, die an der Chunk-Grenze zerschnitten wurden
# --------------------------------------------------------------------------
def test_am_chunk_ende_abgeschnittener_satz_weicht_der_vollstaendigen_fassung():
    # Der vorige Chunk endet bei 600 s mitten im Satz; der neue hat ihn ganz. Frueher blieb (bei hoher
    # Aehnlichkeit) die abgeschnittene Fassung -- "zehn" fehlte im Transkript.
    merged = [
        {"start": 580.0, "end": 588.0, "text": "Das war der erste Punkt."},
        {"start": 594.0, "end": 600.0, "text": "Dann treffen wir uns alle wieder am Montag um"},
    ]
    new_chunk = [{"start": 594.2, "end": 601.5, "text": "Dann treffen wir uns alle wieder am Montag um zehn."}]
    result = merge_chunk_into_result(merged, new_chunk, overlap_start=590.0, overlap_end=600.0)
    texte = [segment["text"] for segment in result]
    assert texte == ["Das war der erste Punkt.", "Dann treffen wir uns alle wieder am Montag um zehn."]
    assert "moegliche_ueberschneidung" not in result[1]


def test_abgeschnittener_satz_mit_langem_rest_steht_nicht_doppelt_da():
    # Mittlere Aehnlichkeit: Frueher standen beide Fassungen im Transkript (und gingen doppelt ins Protokoll).
    merged = [{"start": 596.0, "end": 600.0, "text": "Wir sollten das Angebot"}]
    new_chunk = [
        {"start": 596.1, "end": 606.0, "text": "Wir sollten das Angebot bis Freitag noch einmal gemeinsam durchgehen und dann erst verschicken."}
    ]
    result = merge_chunk_into_result(merged, new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert [segment["text"] for segment in result] == [new_chunk[0]["text"]]


def test_am_chunk_anfang_abgeschnittener_satz_wird_nicht_wiederholt():
    merged = [{"start": 586.0, "end": 592.5, "text": "Die Zahlen fuer das dritte Quartal liegen jetzt vor."}]
    new_chunk = [
        {"start": 590.0, "end": 592.4, "text": "Quartal liegen jetzt vor."},
        {"start": 593.0, "end": 597.0, "text": "Sie sind besser als erwartet."},
    ]
    result = merge_chunk_into_result(merged, new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert [segment["text"] for segment in result] == [
        "Die Zahlen fuer das dritte Quartal liegen jetzt vor.",
        "Sie sind besser als erwartet.",
    ]


def test_kurzes_wort_am_chunk_anfang_bleibt_trotz_gleichem_ende():
    # Ein einzelnes "Ja." ist keine abgeschnittene Fassung des vorigen Satzes.
    merged = [{"start": 588.0, "end": 591.0, "text": "Dann sagen wir ja"}]
    new_chunk = [{"start": 590.2, "end": 590.9, "text": "Ja."}]
    result = merge_chunk_into_result(merged, new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert len(result) == 2


def test_aehnlicher_text_mitten_im_fenster_wird_nicht_ersetzt():
    # Kein Segment an der Chunk-Grenze: Es bleibt beim bisherigen Verhalten (das vorhandene Segment bleibt).
    merged = [{"start": 591.0, "end": 594.0, "text": "und dann haben wir das Protokoll verschickt"}]
    new_chunk = [{"start": 591.1, "end": 594.2, "text": "und dann haben wir das Protokoll verschickt."}]
    result = merge_chunk_into_result(merged, new_chunk, overlap_start=590.0, overlap_end=600.0)
    assert result == merged
