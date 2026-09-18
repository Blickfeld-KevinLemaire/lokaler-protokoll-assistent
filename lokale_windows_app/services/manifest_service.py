"""Manifest- und Arbeitsordnerverwaltung fuer fortsetzbare Langzeitverarbeitung.

Fuer jede Quelldatei wird ein eigener Arbeitsordner
``arbeitsdaten/<dateihash>/`` mit Unterordnern und einem ``manifest.json``
angelegt. Das Manifest haelt den Bearbeitungsstatus jedes Chunks fest,
sodass eine unterbrochene Verarbeitung spaeter fortgesetzt werden kann,
ohne bereits erfolgreich verarbeitete Chunks erneut zu berechnen.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"

STATUS_AUSSTEHEND = "ausstehend"
STATUS_IN_BEARBEITUNG = "in_bearbeitung"
STATUS_ABGESCHLOSSEN = "abgeschlossen"
STATUS_FEHLGESCHLAGEN = "fehlgeschlagen"

SUBDIRS = ("chunks", "transkripte", "analysen", "zusammengefuehrt")


def compute_file_hash(path: Path, chunk_size: int = 1 << 20) -> str:
    """Stabiler SHA-256-Hash ueber den vollstaendigen Dateiinhalt."""
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        while True:
            block = file_obj.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def get_work_dir_for_file(base_work_dir: Path, file_hash: str) -> Path:
    work_dir = base_work_dir / file_hash
    for sub in SUBDIRS:
        (work_dir / sub).mkdir(parents=True, exist_ok=True)
    return work_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def create_manifest(
    source_path: Path,
    file_hash: str,
    total_duration: float,
    chunk_length: float,
    overlap: float,
    chunk_count: int,
    chunk_bounds: list[dict[str, float]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    timestamp = _now_iso()
    return {
        "manifest_version": MANIFEST_VERSION,
        "dateihash": file_hash,
        "quelldatei_name": source_path.name,
        "quelldatei_groesse_bytes": source_path.stat().st_size,
        "gesamtdauer_sekunden": total_duration,
        "chunk_laenge_sekunden": chunk_length,
        "ueberlappung_sekunden": overlap,
        "anzahl_chunks": chunk_count,
        "chunks": [
            {
                "index": bound["index"],
                "global_start": bound["global_start"],
                "global_end": bound["global_end"],
                "status": STATUS_AUSSTEHEND,
                "fehler": None,
                "aktualisiert": timestamp,
            }
            for bound in chunk_bounds
        ],
        "einstellungen": settings,
        "erstellt": timestamp,
        "aktualisiert": timestamp,
        "diarisierung_status": STATUS_AUSSTEHEND,
        "protokoll_status": STATUS_AUSSTEHEND,
    }


def manifest_path(work_dir: Path) -> Path:
    return work_dir / MANIFEST_FILENAME


def load_manifest(work_dir: Path) -> dict[str, Any] | None:
    path = manifest_path(work_dir)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(work_dir: Path, manifest: dict[str, Any]) -> None:
    """Atomarer Schreibvorgang, damit ein Absturz waehrend des Schreibens
    kein beschaedigtes Manifest hinterlaesst."""
    manifest["aktualisiert"] = _now_iso()
    path = manifest_path(work_dir)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(work_dir), delete=False, suffix=".tmp"
    ) as tmp_file:
        json.dump(manifest, tmp_file, ensure_ascii=False, indent=2)
        temp_name = tmp_file.name
    os.replace(temp_name, path)


def update_chunk_status(
    manifest: dict[str, Any],
    chunk_index: int,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    for chunk in manifest["chunks"]:
        if chunk["index"] == chunk_index:
            chunk["status"] = status
            chunk["fehler"] = error
            chunk["aktualisiert"] = _now_iso()
            break
    else:
        raise KeyError(f"Chunk {chunk_index} ist im Manifest nicht enthalten.")
    return manifest


def find_resumable_state(manifest: dict[str, Any]) -> dict[str, Any]:
    fertige_chunks = [c["index"] for c in manifest["chunks"] if c["status"] == STATUS_ABGESCHLOSSEN]
    fehlgeschlagene = [c for c in manifest["chunks"] if c["status"] == STATUS_FEHLGESCHLAGEN]
    offene = [
        c["index"]
        for c in manifest["chunks"]
        if c["status"] in (STATUS_AUSSTEHEND, STATUS_IN_BEARBEITUNG, STATUS_FEHLGESCHLAGEN)
    ]
    naechster_chunk = min(offene) if offene else None
    return {
        "fertige_chunks": sorted(fertige_chunks),
        "naechster_chunk": naechster_chunk,
        "letzter_fehler": fehlgeschlagene[-1] if fehlgeschlagene else None,
        "vollstaendig": naechster_chunk is None,
    }


def is_fully_processed(manifest: dict[str, Any]) -> bool:
    return all(c["status"] == STATUS_ABGESCHLOSSEN for c in manifest["chunks"])


def chunk_transcript_path(work_dir: Path, chunk_index: int) -> Path:
    return work_dir / "transkripte" / f"chunk_{chunk_index + 1:04d}.json"


def chunk_audio_path(work_dir: Path, chunk_index: int) -> Path:
    return work_dir / "chunks" / f"chunk_{chunk_index + 1:04d}.wav"


def chunk_analysis_path(work_dir: Path, chunk_index: int) -> Path:
    return work_dir / "analysen" / f"chunk_{chunk_index + 1:04d}_analyse.json"


def merged_dir(work_dir: Path) -> Path:
    return work_dir / "zusammengefuehrt"
