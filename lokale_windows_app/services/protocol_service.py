"""Mehrstufige, nachvollziehbare und fortsetzbare Protokollauswertung ueber
das lokale Ollama-Modell.

Stufe 1: jeder Transkript-Chunk wird einzeln analysiert.
Stufe 2: benachbarte Chunk-Analysen werden gruppenweise konsolidiert.
Stufe 3: alle konsolidierten Zwischenanalysen werden zum finalen,
strukturierten Protokoll zusammengefuehrt.

Jede Stufe wird als eigene Datei gespeichert. Ist eine Datei bereits
vorhanden, wird sie wiederverwendet statt erneut angefragt -- ein Fehler in
einem einzelnen Chunk zwingt also nicht zur kompletten Wiederholung.

Jede Modellantwort wird validiert (``utils.json_validation``). Ist sie
ungueltig, wird genau EIN gezielter Reparaturversuch unternommen. Schlaegt
auch dieser fehl, wird die Rohantwort gespeichert und ein
``ProtocolValidationError`` ausgeloest, ohne vorhandene gueltige Ergebnisse
zu ueberschreiben.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from services import ollama_service
from utils.json_validation import validate_chunk_analysis_json, validate_protocol_json

GenerateFn = Callable[[str, str], dict[str, Any]]
Validator = Callable[[Any], tuple[bool, list[str]]]


class ProtocolValidationError(RuntimeError):
    pass


def default_generate_fn(prompt: str, system: str) -> dict[str, Any]:
    return ollama_service.generate_json(prompt, system)


def _load_or_compute(path: Path, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    result = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def generate_validated(
    prompt: str,
    system: str,
    generate_fn: GenerateFn,
    validator: Validator,
    raw_dump_dir: Path,
    raw_dump_name: str,
) -> dict[str, Any]:
    raw = generate_fn(prompt, system)
    ok, errors = validator(raw)
    if ok:
        return raw

    raw_dump_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = raw_dump_dir / f"{raw_dump_name}_ungueltig_{timestamp}.json"
    dump_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    repair_prompt = (
        "Deine vorherige Antwort war nicht gueltig: "
        + "; ".join(errors)
        + "\n\nAntworte erneut AUSSCHLIESSLICH mit gueltigem JSON in der geforderten "
        "Struktur, ohne zusaetzlichen Text oder Erklaerungen.\n\nUrspruengliche Anfrage:\n"
        + prompt
    )
    repaired = generate_fn(repair_prompt, system)
    ok2, errors2 = validator(repaired)
    if ok2:
        return repaired

    dump_path_2 = raw_dump_dir / f"{raw_dump_name}_reparatur_fehlgeschlagen_{timestamp}.json"
    dump_path_2.write_text(json.dumps(repaired, ensure_ascii=False, indent=2), encoding="utf-8")
    raise ProtocolValidationError(
        "Die Antwort des lokalen Modells war auch nach einem gezielten Reparatur"
        "versuch ungueltig: " + "; ".join(errors2)
    )


def build_stage1_prompt(chunk_index: int, start_str: str, end_str: str, text: str) -> str:
    return (
        f"Analysiere den folgenden Transkriptabschnitt (Abschnitt {chunk_index + 1}, "
        f"Zeitraum {start_str} - {end_str}) und gib eine strukturierte JSON-Teilanalyse "
        "mit den Feldern 'kernaussagen', 'entscheidungen', 'aufgaben', 'termine', "
        "'offene_fragen' und 'quellen' zurueck. Verwende ausschliesslich Angaben aus "
        f"diesem Abschnitt.\n\nTranskriptabschnitt:\n{text}"
    )


def run_stage1_chunk_analysis(
    chunk_index: int,
    chunk_text: str,
    start_str: str,
    end_str: str,
    system_prompt: str,
    generate_fn: GenerateFn,
    analysis_path: Path,
    raw_dump_dir: Path,
) -> dict[str, Any]:
    def compute() -> dict[str, Any]:
        prompt = build_stage1_prompt(chunk_index, start_str, end_str, chunk_text)
        return generate_validated(
            prompt,
            system_prompt,
            generate_fn,
            validate_chunk_analysis_json,
            raw_dump_dir,
            f"chunk_{chunk_index + 1:04d}",
        )

    return _load_or_compute(analysis_path, compute)


def build_stage2_prompt(group_analyses: list[dict[str, Any]]) -> str:
    return (
        "Fuehre die folgenden benachbarten Teilanalysen zu einer konsolidierten "
        "Zwischenanalyse zusammen. Entferne Dopplungen aus Ueberlappungsbereichen, "
        "erhalte aber alle Entscheidungen, Aufgaben, Fristen und offenen Fragen "
        "vollstaendig sowie die Quellenzeitstempel. Gib gueltiges JSON mit denselben "
        "Feldern wie die Teilanalysen zurueck.\n\nTeilanalysen:\n"
        + json.dumps(group_analyses, ensure_ascii=False, indent=2)
    )


def run_stage2_merge(
    group_analyses: list[dict[str, Any]],
    group_index: int,
    system_prompt: str,
    generate_fn: GenerateFn,
    output_path: Path,
    raw_dump_dir: Path,
) -> dict[str, Any]:
    def compute() -> dict[str, Any]:
        prompt = build_stage2_prompt(group_analyses)
        return generate_validated(
            prompt,
            system_prompt,
            generate_fn,
            validate_chunk_analysis_json,
            raw_dump_dir,
            f"gruppe_{group_index + 1:04d}",
        )

    return _load_or_compute(output_path, compute)


def build_stage3_prompt(consolidated_analyses: list[dict[str, Any]]) -> str:
    return (
        "Erstelle aus den folgenden konsolidierten Zwischenanalysen das finale "
        "strukturierte Protokoll gemaess der vorgegebenen JSON-Struktur. Kennzeichne "
        "Widersprueche oder Unsicherheiten im Feld 'unsichere_transkriptstellen'. "
        "Ergaenze keine Informationen, die nicht in den Analysen vorkommen.\n\n"
        "Konsolidierte Zwischenanalysen:\n"
        + json.dumps(consolidated_analyses, ensure_ascii=False, indent=2)
    )


def run_stage3_final_protocol(
    consolidated_analyses: list[dict[str, Any]],
    system_prompt: str,
    generate_fn: GenerateFn,
    output_path: Path,
    raw_dump_dir: Path,
) -> dict[str, Any]:
    def compute() -> dict[str, Any]:
        prompt = build_stage3_prompt(consolidated_analyses)
        return generate_validated(
            prompt,
            system_prompt,
            generate_fn,
            validate_protocol_json,
            raw_dump_dir,
            "protokoll",
        )

    return _load_or_compute(output_path, compute)


def run_full_protocol_pipeline(
    chunk_texts: list[dict[str, Any]],
    work_dir: Path,
    system_prompt: str,
    generate_fn: GenerateFn | None = None,
    group_size: int = 4,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """``chunk_texts``: Liste von ``{"index", "start_str", "end_str", "text"}``.

    Fuehrt alle drei Stufen aus und gibt das finale Protokoll-JSON zurueck.
    Bereits vorhandene Zwischenstaende werden wiederverwendet.
    """
    generate_fn = generate_fn or default_generate_fn
    analysen_dir = work_dir / "analysen"
    zusammen_dir = work_dir / "zusammengefuehrt"
    raw_dump_dir = zusammen_dir / "rohantworten"
    analysen_dir.mkdir(parents=True, exist_ok=True)
    zusammen_dir.mkdir(parents=True, exist_ok=True)

    stage1_results = []
    for chunk in chunk_texts:
        if progress_cb:
            progress_cb("stufe1_chunk_analyse", chunk["index"], len(chunk_texts))
        path = analysen_dir / f"chunk_{chunk['index'] + 1:04d}_analyse.json"
        result = run_stage1_chunk_analysis(
            chunk["index"],
            chunk["text"],
            chunk["start_str"],
            chunk["end_str"],
            system_prompt,
            generate_fn,
            path,
            raw_dump_dir,
        )
        stage1_results.append(result)

    groups = [stage1_results[i : i + group_size] for i in range(0, len(stage1_results), group_size)]
    consolidated = []
    for group_index, group in enumerate(groups):
        if progress_cb:
            progress_cb("stufe2_zwischenzusammenfuehrung", group_index, len(groups))
        path = zusammen_dir / f"zwischenanalyse_{group_index + 1:04d}.json"
        if len(group) == 1:
            if not path.is_file():
                path.write_text(json.dumps(group[0], ensure_ascii=False, indent=2), encoding="utf-8")
            result = json.loads(path.read_text(encoding="utf-8"))
        else:
            result = run_stage2_merge(group, group_index, system_prompt, generate_fn, path, raw_dump_dir)
        consolidated.append(result)

    if progress_cb:
        progress_cb("stufe3_gesamtprotokoll", 0, 1)
    final_path = zusammen_dir / "protokoll.json"
    return run_stage3_final_protocol(consolidated, system_prompt, generate_fn, final_path, raw_dump_dir)
