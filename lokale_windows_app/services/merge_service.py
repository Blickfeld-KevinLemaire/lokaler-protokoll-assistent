"""Zusammenfuehrung der Chunk-Transkripte zu globalen Zeitstempeln.

Aufgaben:
* Addition des globalen Chunk-Startzeitpunkts auf alle lokalen Zeitstempel,
* Bereinigung von Dubletten im 10-Sekunden-Ueberlappungsbereich anhand von
  zeitlicher Ueberschneidung und Textaehnlichkeit,
* Erhalt unsicherer/mehrdeutiger Passagen (werden markiert, nicht geloescht).

Nur eindeutig erkannte Dubletten (hohe Textaehnlichkeit UND zeitliche
Ueberschneidung im Overlap-Fenster) werden entfernt. Alles andere bleibt
erhalten -- im Zweifel wird lieber zu wenig als zu viel geloescht.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

HIGH_SIMILARITY_THRESHOLD = 0.85
LOW_SIMILARITY_THRESHOLD = 0.40


def normalize_text_for_compare(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text


def text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(
        None, normalize_text_for_compare(a), normalize_text_for_compare(b)
    ).ratio()


def to_global_segments(local_segments: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    global_segments = []
    for segment in local_segments:
        converted = dict(segment)
        converted["start"] = segment["start"] + offset
        converted["end"] = segment["end"] + offset
        global_segments.append(converted)
    return global_segments


def merge_chunk_into_result(
    merged_segments: list[dict[str, Any]],
    new_chunk_segments: list[dict[str, Any]],
    overlap_start: float,
    overlap_end: float,
    high_threshold: float = HIGH_SIMILARITY_THRESHOLD,
    low_threshold: float = LOW_SIMILARITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Fuegt die (bereits global datierten) Segmente eines Chunks an.

    Segmente des neuen Chunks, die im Ueberlappungsfenster liegen und einem
    bereits vorhandenen Segment textlich eindeutig entsprechen, werden
    verworfen. Mehrdeutige Faelle werden als ``moegliche_ueberschneidung``
    markiert, aber nicht geloescht.
    """
    if overlap_end <= overlap_start:
        merged_segments.extend(new_chunk_segments)
        return merged_segments

    previous_candidates = [
        segment
        for segment in merged_segments
        if segment["end"] > overlap_start and segment["start"] < overlap_end
    ]

    for segment in new_chunk_segments:
        in_overlap_window = segment["start"] < overlap_end and segment["end"] > overlap_start
        if not in_overlap_window:
            merged_segments.append(segment)
            continue

        # Beide Segmente liegen im gemeinsamen Ueberlappungsfenster -- das
        # allein macht sie zu Duplikat-Kandidaten. Eine zusaetzliche exakte
        # Zeitueberschneidung wird nicht verlangt, da WhisperX denselben
        # gesprochenen Inhalt in den beiden ueberlappenden Chunks nicht
        # zwingend auf identische Sekundenbruchteile schneidet.
        best_similarity = 0.0
        for previous in previous_candidates:
            best_similarity = max(best_similarity, text_similarity(segment["text"], previous["text"]))

        if best_similarity >= high_threshold:
            continue  # eindeutiges Duplikat -- verwerfen

        segment_copy = dict(segment)
        if best_similarity >= low_threshold:
            segment_copy["moegliche_ueberschneidung"] = True
        merged_segments.append(segment_copy)

    return merged_segments


def merge_chunk_transcripts(
    chunk_plans: list[Any],
    chunk_local_segments: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Fuehrt alle Chunk-Transkripte zu einer global datierten Segmentliste
    zusammen. ``chunk_plans`` sind ``services.chunking_service.ChunkPlan``-
    Objekte (oder aequivalente Objekte mit ``global_start`` und
    ``overlap_with_previous``/``is_first``).
    """
    merged: list[dict[str, Any]] = []
    for plan, local_segments in zip(chunk_plans, chunk_local_segments):
        global_segments = to_global_segments(local_segments, plan.global_start)
        if plan.is_first:
            merged.extend(global_segments)
            continue
        overlap_start = plan.global_start
        overlap_end = plan.global_start + plan.overlap_with_previous
        merge_chunk_into_result(merged, global_segments, overlap_start, overlap_end)

    merged.sort(key=lambda segment: (segment["start"], segment["end"]))
    for index, segment in enumerate(merged, start=1):
        segment["nummer"] = index
    return merged
