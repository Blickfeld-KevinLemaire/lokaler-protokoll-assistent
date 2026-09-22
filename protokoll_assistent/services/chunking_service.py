"""Planung der Zehn-Minuten-Chunks fuer Langzeitaufnahmen.

Verbindliche Vorgaben:
* maximale Chunk-Laenge: 600 Sekunden,
* Ueberlappung benachbarter Chunks: 10 Sekunden,
* ausschliesslich sequenzielle Verarbeitung (keine Parallelitaet).

Beispiel aus der Aufgabenstellung: Chunk 3 (Index 2) beginnt bei 00:19:40
(=1180s) -- das ergibt sich aus ``index * (chunk_length - overlap)`` =
``2 * 590 = 1180``. Dieses Modul stellt ausschliesslich die reine
Zeitplanung bereit; das tatsaechliche Schneiden uebernimmt
``services.ffmpeg_service``.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CHUNK_LENGTH_SECONDS = 600.0
DEFAULT_OVERLAP_SECONDS = 10.0


@dataclass(frozen=True)
class ChunkPlan:
    index: int
    global_start: float
    global_end: float
    overlap_with_previous: float
    is_first: bool
    is_last: bool

    @property
    def duration(self) -> float:
        return self.global_end - self.global_start


def plan_chunks(
    total_duration: float,
    chunk_length: float = DEFAULT_CHUNK_LENGTH_SECONDS,
    overlap: float = DEFAULT_OVERLAP_SECONDS,
) -> list[ChunkPlan]:
    if total_duration <= 0:
        raise ValueError("total_duration muss groesser als 0 sein.")
    if overlap >= chunk_length:
        raise ValueError("overlap muss kleiner als chunk_length sein.")

    if total_duration <= chunk_length:
        return [ChunkPlan(0, 0.0, total_duration, 0.0, True, True)]

    step = chunk_length - overlap
    starts: list[float] = []
    start = 0.0
    while True:
        starts.append(start)
        if start + chunk_length >= total_duration:
            break
        start += step

    plans: list[ChunkPlan] = []
    last_index = len(starts) - 1
    for index, chunk_start in enumerate(starts):
        chunk_end = min(chunk_start + chunk_length, total_duration)
        plans.append(
            ChunkPlan(
                index=index,
                global_start=chunk_start,
                global_end=chunk_end,
                overlap_with_previous=0.0 if index == 0 else overlap,
                is_first=(index == 0),
                is_last=(index == last_index),
            )
        )
    return plans


def chunk_count_for_duration(
    total_duration: float,
    chunk_length: float = DEFAULT_CHUNK_LENGTH_SECONDS,
    overlap: float = DEFAULT_OVERLAP_SECONDS,
) -> int:
    return len(plan_chunks(total_duration, chunk_length, overlap))
