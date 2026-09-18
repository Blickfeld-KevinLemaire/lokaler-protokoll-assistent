import pytest

from services.chunking_service import plan_chunks


def test_short_recording_is_single_chunk():
    plans = plan_chunks(300.0)
    assert len(plans) == 1
    assert plans[0].is_first and plans[0].is_last
    assert plans[0].global_start == 0.0
    assert plans[0].global_end == 300.0
    assert plans[0].overlap_with_previous == 0.0


def test_chunk_boundaries_and_overlap_example_from_spec():
    # Beispiel aus dem Auftrag: Chunk 3 (Index 2) beginnt global bei 00:19:40 = 1180s.
    total_duration = 30 * 60.0  # 30 Minuten
    plans = plan_chunks(total_duration, chunk_length=600.0, overlap=10.0)

    assert plans[0].global_start == 0.0
    assert plans[0].global_end == 600.0
    assert plans[0].overlap_with_previous == 0.0

    assert plans[1].global_start == 590.0
    assert plans[2].global_start == 1180.0  # == 00:19:40

    for plan in plans[1:]:
        assert plan.overlap_with_previous == 10.0

    # Ueberlappungsfenster zwischen Chunk i und i+1 ist exakt 10 Sekunden.
    for previous, current in zip(plans, plans[1:]):
        overlap_seconds = previous.global_end - current.global_start
        assert overlap_seconds == pytest.approx(10.0)


def test_last_chunk_never_exceeds_total_duration():
    plans = plan_chunks(1234.0)
    assert plans[-1].global_end == pytest.approx(1234.0)
    assert plans[-1].is_last
    assert all(not p.is_last for p in plans[:-1])


def test_no_chunk_shorter_than_needed_and_no_gaps():
    total_duration = 2000.0
    plans = plan_chunks(total_duration)
    # Keine Luecken: jeder naechste Chunk beginnt vor oder bei Ende des vorherigen.
    for previous, current in zip(plans, plans[1:]):
        assert current.global_start <= previous.global_end
    assert plans[-1].global_end == total_duration


def test_overlap_must_be_smaller_than_chunk_length():
    with pytest.raises(ValueError):
        plan_chunks(1000.0, chunk_length=10.0, overlap=10.0)


def test_zero_duration_rejected():
    with pytest.raises(ValueError):
        plan_chunks(0.0)
