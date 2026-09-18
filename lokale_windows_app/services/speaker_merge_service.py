"""Sprecherzuordnung -- innerhalb einer Aufnahme und ueber Chunk-Grenzen.

Bevorzugte Architektur (siehe Auftrag): Die Diarisierung laeuft nach
Moeglichkeit EINMAL global auf dem normalisierten Gesamtaudio. Die global
erkannten Sprecherabschnitte werden dann anhand der globalen Zeitstempel den
transkribierten Segmenten zugeordnet (``assign_speakers_by_overlap``).
Dadurch bleiben Sprecher-IDs automatisch ueber Chunk-Grenzen und Pausen
hinweg stabil, ohne dass Sprecher aus verschiedenen Chunks anhand ihrer
(nur lokal gueltigen) Bezeichnung zusammengefuehrt werden muessten.

Nur wenn eine globale Diarisierung nicht moeglich ist (z.B. wegen der
Aufnahmelaenge oder begrenzter Ressourcen), kommt die Embedding-basierte
Zuordnung ueber Chunk-Grenzen (``match_speakers_across_chunks``) zum
Einsatz. Sie fuehrt Sprecher NIEMALS willkuerlich zusammen: Unterhalb des
Schwellwerts wird immer ein neuer globaler Sprecher angelegt, nie eine
Vermutungszusammenfuehrung.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_MATCH_THRESHOLD = 0.75
UNCERTAIN_MARGIN = 0.15


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Embeddings muessen die gleiche Laenge haben.")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def assign_speakers_by_overlap(
    segments: list[dict[str, Any]],
    diarization_turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ordnet jedem Segment den Sprecher mit der groessten zeitlichen
    Ueberschneidung aus der globalen Diarisierung zu."""
    result = []
    for segment in segments:
        best_speaker = None
        best_overlap = 0.0
        for turn in diarization_turns:
            overlap = min(segment["end"], turn["end"]) - max(segment["start"], turn["start"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]
        segment_copy = dict(segment)
        segment_copy["sprecher_id"] = best_speaker
        result.append(segment_copy)
    return result


def match_speakers_across_chunks(
    chunk_speaker_embeddings: dict[int, dict[str, list[float]]],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Ordnet lokale (Chunk-gebundene) Sprecherembeddings globalen
    Sprecher-IDs zu. Wird nur als Rueckfalloption verwendet, wenn keine
    globale Diarisierung moeglich war.

    Rueckgabe: ``{(chunk_index, lokales_label): {"global_id", "confidence",
    "unsicher", ...}}``. Es wird niemals unterhalb des Schwellwerts
    zusammengefuehrt -- in diesem Fall entsteht immer ein neuer globaler
    Sprecher.
    """
    mapping: dict[tuple[int, str], dict[str, Any]] = {}
    centroids: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    next_id = 0

    def new_global_id() -> str:
        nonlocal next_id
        generated = f"GLOBAL_SPEAKER_{next_id:02d}"
        next_id += 1
        return generated

    for chunk_index in sorted(chunk_speaker_embeddings):
        for local_label, embedding in chunk_speaker_embeddings[chunk_index].items():
            if not centroids:
                global_id = new_global_id()
                centroids[global_id] = list(embedding)
                counts[global_id] = 1
                mapping[(chunk_index, local_label)] = {
                    "global_id": global_id,
                    "confidence": 1.0,
                    "unsicher": False,
                }
                continue

            best_id = None
            best_similarity = -1.0
            for global_id, centroid in centroids.items():
                similarity = cosine_similarity(embedding, centroid)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_id = global_id

            if best_similarity >= threshold:
                count = counts[best_id]
                centroid = centroids[best_id]
                centroids[best_id] = [
                    (c * count + e) / (count + 1) for c, e in zip(centroid, embedding)
                ]
                counts[best_id] = count + 1
                mapping[(chunk_index, local_label)] = {
                    "global_id": best_id,
                    "confidence": best_similarity,
                    "unsicher": best_similarity < threshold + UNCERTAIN_MARGIN,
                }
            else:
                global_id = new_global_id()
                centroids[global_id] = list(embedding)
                counts[global_id] = 1
                mapping[(chunk_index, local_label)] = {
                    "global_id": global_id,
                    "confidence": best_similarity,
                    "unsicher": best_similarity >= threshold - UNCERTAIN_MARGIN,
                    "neu_da_unter_schwelle": True,
                }

    return mapping
