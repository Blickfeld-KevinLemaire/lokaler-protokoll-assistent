from protokoll_assistent.utils.timeformat import (
    format_duration_human,
    format_srt_timestamp,
    format_timestamp,
    format_vtt_timestamp,
)


def test_format_timestamp_basic():
    assert format_timestamp(2.78) == "00:00:02.780"
    assert format_timestamp(17.18) == "00:00:17.180"


def test_format_timestamp_hours():
    assert format_timestamp(3661.5) == "01:01:01.500"


def test_format_timestamp_negative_clamped_to_zero():
    assert format_timestamp(-5) == "00:00:00.000"


def test_srt_uses_comma():
    assert format_srt_timestamp(2.78) == "00:00:02,780"


def test_vtt_uses_dot():
    assert format_vtt_timestamp(2.78) == "00:00:02.780"


def test_duration_human_minutes_and_hours():
    assert format_duration_human(65) == "1:05"
    assert format_duration_human(3725) == "1:02:05"
