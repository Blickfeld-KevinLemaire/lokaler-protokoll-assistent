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
# Wort ausserhalb jeder Sprecherstrecke: hoechstens so weit darf die naechste
# Strecke entfernt sein, damit das Wort ihr noch zugeschlagen wird.
_MAX_LUECKE_SEKUNDEN = 1.0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Embeddings muessen die gleiche Laenge haben.")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
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


def _sprecher_fuer_wort(wort: dict[str, Any], diarization_turns: list[dict[str, Any]]) -> str | None:
    """Sprecher mit der groessten Ueberschneidung mit dem Wort; liegt das
    Wort in keiner Sprecherstrecke, entscheidet die zeitlich naechste, sofern
    sie nicht weiter als ``_MAX_LUECKE_SEKUNDEN`` entfernt ist."""
    start = float(wort["start"])
    ende = max(float(wort["end"]), start)
    bester: str | None = None
    beste_ueberlappung = 0.0
    naechster: str | None = None
    kleinster_abstand = float("inf")
    for turn in diarization_turns:
        ueberlappung = min(ende, turn["end"]) - max(start, turn["start"])
        if ueberlappung > beste_ueberlappung:
            beste_ueberlappung = ueberlappung
            bester = turn["speaker"]
        abstand = max(turn["start"] - ende, start - turn["end"], 0.0)
        if abstand < kleinster_abstand:
            kleinster_abstand = abstand
            naechster = turn["speaker"]
    if bester is not None:
        return bester
    if naechster is not None and kleinster_abstand <= _MAX_LUECKE_SEKUNDEN:
        return naechster
    return None


def _wortliste_zu_text(woerter: list[dict[str, Any]]) -> str:
    """Setzt Woerter zu Text zusammen. Whisper liefert die Leerzeichen als
    Wortanfang (' Hallo'); fehlen sie durchgehend (manche API-Endpunkte),
    wird mit Leerzeichen verbunden."""
    teile = [str(wort.get("word", "")) for wort in woerter]
    if any(teil[:1].isspace() for teil in teile):
        text = "".join(teile)
    else:
        text = " ".join(teil.strip() for teil in teile)
    return " ".join(text.split())


def _hat_wortzeiten(segment: dict[str, Any]) -> bool:
    woerter = segment.get("words")
    if not isinstance(woerter, list) or not woerter:
        return False
    return all(
        isinstance(wort, dict) and "start" in wort and "end" in wort and str(wort.get("word", "")).strip()
        for wort in woerter
    )


def _einzelwoerter_glaetten(sprecher: list[str | None]) -> list[str | None]:
    """Ein einzelnes Wort zwischen zwei Woertern desselben anderen Sprechers
    ist fast immer ein Zuordnungsfehler an der Grenze, kein Sprecherwechsel."""
    geglaettet = list(sprecher)
    for index in range(1, len(sprecher) - 1):
        davor, danach = geglaettet[index - 1], sprecher[index + 1]
        if davor is not None and davor == danach and sprecher[index] != davor:
            geglaettet[index] = davor
    return geglaettet


def assign_speakers_by_words(
    segments: list[dict[str, Any]],
    diarization_turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Wortgenaue Sprecherzuordnung.

    Jedes Wort geht an den Sprecher, der zu seiner Zeit spricht. Wechselt der
    Sprecher mitten in einem Segment, wird das Segment an dieser Stelle
    geteilt -- ``assign_speakers_by_overlap`` haette das ganze Segment dem
    Sprecher mit der groessten Ueberlappung gegeben und den Rest falsch
    zugeordnet.

    Segmente ohne Wortzeitstempel (z.B. von API-Endpunkten, die nur
    Segmente liefern) fallen auf die Zuordnung nach Ueberlappung zurueck.
    Ein Segment, das nur einen Sprecher enthaelt, bleibt unveraendert.
    """
    ergebnis: list[dict[str, Any]] = []
    for segment in segments:
        if not _hat_wortzeiten(segment):
            ergebnis.extend(assign_speakers_by_overlap([segment], diarization_turns))
            continue

        woerter = segment["words"]
        sprecher = _einzelwoerter_glaetten([_sprecher_fuer_wort(w, diarization_turns) for w in woerter])
        # Woerter ohne Sprecher uebernehmen den Sprecher des Vorgaengers, am
        # Anfang den des ersten bekannten Nachfolgers.
        letzter: str | None = next((s for s in sprecher if s is not None), None)
        aufgefuellt: list[str | None] = []
        for eintrag in sprecher:
            letzter = eintrag if eintrag is not None else letzter
            aufgefuellt.append(letzter)

        if len(set(aufgefuellt)) <= 1:
            kopie = dict(segment)
            kopie["sprecher_id"] = aufgefuellt[0]
            ergebnis.append(kopie)
            continue

        beginn = 0
        for index in range(1, len(woerter) + 1):
            if index < len(woerter) and aufgefuellt[index] == aufgefuellt[beginn]:
                continue
            teil = woerter[beginn:index]
            kopie = dict(segment)
            kopie["start"] = float(teil[0]["start"])
            kopie["end"] = max(float(teil[-1]["end"]), kopie["start"])
            kopie["text"] = _wortliste_zu_text(teil)
            kopie["words"] = teil
            kopie["sprecher_id"] = aufgefuellt[beginn]
            ergebnis.append(kopie)
            beginn = index

    if any("nummer" in segment for segment in segments):
        for nummer, segment in enumerate(ergebnis, start=1):
            segment["nummer"] = nummer
    return ergebnis


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

            # 'best_id' bleibt None, solange es noch keine Zentroide gibt.
            if best_id is not None and best_similarity >= threshold:
                count = counts[best_id]
                centroid = centroids[best_id]
                centroids[best_id] = [
                    (c * count + e) / (count + 1) for c, e in zip(centroid, embedding, strict=False)
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
