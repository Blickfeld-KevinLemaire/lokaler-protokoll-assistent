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
        # Die Wortzeiten sind ebenfalls chunk-lokal; die wortgenaue
        # Sprecherzuordnung vergleicht sie mit der globalen Diarisierung.
        if segment.get("words"):
            converted["words"] = [
                {**wort, "start": wort["start"] + offset, "end": wort["end"] + offset}
                for wort in segment["words"]
            ]
        global_segments.append(converted)
    return global_segments


# So nah an der Chunk-Grenze gilt ein Segment als dort abgeschnitten (Sekunden).
_GRENZNAEHE_SEKUNDEN = 1.0


def _ueberlappen_zeitlich(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["start"] < b["end"] + 0.5 and b["start"] < a["end"] + 0.5


def _ist_am_chunk_ende_abgeschnitten(vorher: dict[str, Any], neu: dict[str, Any], chunk_ende: float) -> bool:
    """Endet ``vorher`` am Ende seines Chunks, waehrend ``neu`` dasselbe Stueck weiterfuehrt?"""
    return (
        vorher["end"] >= chunk_ende - _GRENZNAEHE_SEKUNDEN
        and neu["end"] > vorher["end"]
        and _ueberlappen_zeitlich(vorher, neu)
    )


def _ist_anfang_von(vorher: dict[str, Any], neu: dict[str, Any]) -> bool:
    kurz, lang = normalize_text_for_compare(vorher["text"]), normalize_text_for_compare(neu["text"])
    return bool(kurz) and len(lang) > len(kurz) and lang.startswith(kurz)


def _ist_am_chunk_anfang_abgeschnitten(vorher: dict[str, Any], neu: dict[str, Any], chunk_anfang: float) -> bool:
    """Beginnt ``neu`` am Anfang seines Chunks mitten in dem Satz, den ``vorher`` ganz enthaelt?"""
    kurz, lang = normalize_text_for_compare(neu["text"]), normalize_text_for_compare(vorher["text"])
    return (
        neu["start"] <= chunk_anfang + _GRENZNAEHE_SEKUNDEN
        and neu["end"] <= vorher["end"] + 0.5
        and _ueberlappen_zeitlich(vorher, neu)
        and len(kurz.split()) >= 2
        and len(lang) > len(kurz)
        and lang.endswith(kurz)
    )


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
        # Zeitueberschneidung wird nicht verlangt, da das Transkriptionsmodell denselben
        # gesprochenen Inhalt in den beiden ueberlappenden Chunks nicht
        # zwingend auf identische Sekundenbruchteile schneidet.
        best_similarity = 0.0
        aehnlichstes: dict[str, Any] | None = None
        for previous in previous_candidates:
            aehnlichkeit = text_similarity(segment["text"], previous["text"])
            if aehnlichkeit > best_similarity:
                best_similarity, aehnlichstes = aehnlichkeit, previous

        # Derselbe Satz, an der Chunk-Grenze zerschnitten: Der vorige Chunk hoert mitten im Satz auf
        # ("... treffen uns am Montag um"), der neue hat ihn ganz ("... am Montag um zehn."). Dann gilt die
        # VOLLSTAENDIGE Fassung. Frueher blieb die abgeschnittene (bei hoher Aehnlichkeit fiel "zehn" weg),
        # oder der Satz stand zweimal im Transkript (bei mittlerer).
        abgeschnitten = next(
            (
                previous
                for previous in previous_candidates
                if _ist_am_chunk_ende_abgeschnitten(previous, segment, overlap_end)
                and ((previous is aehnlichstes and best_similarity >= high_threshold) or _ist_anfang_von(previous, segment))
            ),
            None,
        )
        if abgeschnitten is not None:
            stelle = next(i for i, vorhanden in enumerate(merged_segments) if vorhanden is abgeschnitten)
            merged_segments[stelle] = segment
            previous_candidates[previous_candidates.index(abgeschnitten)] = segment
            continue

        # Umgekehrt: Der neue Chunk beginnt mitten in einem Satz, den der vorige ganz hat.
        if any(_ist_am_chunk_anfang_abgeschnitten(previous, segment, overlap_start) for previous in previous_candidates):
            continue

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
    for plan, local_segments in zip(chunk_plans, chunk_local_segments, strict=False):
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
