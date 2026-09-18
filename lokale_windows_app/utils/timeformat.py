"""Zeitformatierung fuer Anzeige, TXT-, SRT- und VTT-Export."""

from __future__ import annotations


def _split(seconds: float) -> tuple[int, int, int, int]:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return hours, minutes, secs, millis


def format_timestamp(seconds: float) -> str:
    """``HH:MM:SS.mmm`` -- fuer TXT und JSON-Anzeige."""
    hours, minutes, secs, millis = _split(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_srt_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm`` -- SRT verlangt ein Komma vor den Millisekunden."""
    hours, minutes, secs, millis = _split(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """``HH:MM:SS.mmm`` -- WebVTT verlangt einen Punkt."""
    return format_timestamp(seconds)


def format_duration_human(seconds: float) -> str:
    """Kurze, fuer Menschen lesbare Dauer, z.B. ``1:04:12``."""
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
