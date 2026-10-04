"""Mehrstufige, nachvollziehbare und fortsetzbare Protokollauswertung ueber
das lokale Ollama-Modell.

Stufe 1: jeder Transkript-Chunk wird einzeln analysiert.
Stufe 2: benachbarte Chunk-Analysen werden gruppenweise konsolidiert. Passt
das Ergebnis danach noch nicht in den Kontext der Stufe 3, wird in weiteren
Runden erneut verdichtet (hoechstens ``MAX_VERDICHTUNGSRUNDEN`` insgesamt).
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

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.services import ollama_service
from protokoll_assistent.utils.json_validation import validate_chunk_analysis_json, validate_protocol_json

# Stufe 2 laeuft immer mindestens einmal. Danach wird weiter verdichtet, solange
# die Zwischenanalysen zusammen laenger als dieser Wert sind (Zeichen der
# JSON-Darstellung; gemessen gut 3 Zeichen je Token) und mehr als eine uebrig
# ist. Muss samt Antwort in ollama_service.PROTOKOLL_NUM_CTX passen -- das
# prueft test_ollama_service.test_kontext_reicht_fuer_die_groesste_protokollstufe.
MAX_KONTEXT_ZEICHEN = 40_000
MAX_VERDICHTUNGSRUNDEN = 8

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


PROTOKOLL_STRUKTUR = """\
{
  "titel": "",
  "kurzzusammenfassung": "",
  "teilnehmende_oder_sprecher": [],
  "themen": [{"thema": "", "kernaussagen": [], "sprecher": [], "zeitraum": "", "quellen": []}],
  "entscheidungen": [{"entscheidung": "", "sprecher": "", "zeitpunkt": "", "quelle": ""}],
  "aufgaben": [{"aufgabe": "", "verantwortlich": "", "frist": "", "quelle": ""}],
  "termine": [],
  "offene_fragen": [],
  "wichtige_fakten": [],
  "unsichere_transkriptstellen": [],
  "quellenhinweise": []
}"""


def build_stage3_prompt(consolidated_analyses: list[dict[str, Any]]) -> str:
    # Die Struktur steht hier und nicht nur im Systemprompt: Eine Vorlage
    # ersetzt den Systemprompt vollstaendig und kennt sie sonst nicht.
    return (
        "Erstelle aus den folgenden konsolidierten Zwischenanalysen das finale "
        "strukturierte Protokoll gemaess der vorgegebenen JSON-Struktur. Kennzeichne "
        "Widersprueche oder Unsicherheiten im Feld 'unsichere_transkriptstellen'. "
        "Ergaenze keine Informationen, die nicht in den Analysen vorkommen.\n\n"
        "Antworte ausschliesslich mit gueltigem JSON in genau dieser Struktur "
        "(alle Felder muessen vorhanden sein, leere Felder bleiben leer):\n"
        + PROTOKOLL_STRUKTUR
        + "\n\nKonsolidierte Zwischenanalysen:\n"
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


def _prompt_hash_pfad(final_path: Path) -> Path:
    return final_path.with_name("protokoll.prompt.sha256")


def _prompt_hash(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def _protokoll_verwerfen_wenn_prompt_geaendert(final_path: Path, system_prompt: str) -> None:
    """Ein fertiges Protokoll gehoert zu dem Systemprompt (der Vorlage), mit dem
    es erzeugt wurde. Wechselt der Anwender die Vorlage und startet erneut,
    muss die letzte Stufe neu laufen -- sonst bekaeme er stillschweigend das
    Ergebnis der alten Vorlage. Stufe 1 und 2 bleiben erhalten: Sie haben feste
    Felder und sind aufwendig; nur das Gesamtprotokoll richtet sich nach der Vorlage."""
    if not final_path.is_file():
        return
    hash_pfad = _prompt_hash_pfad(final_path)
    try:
        gemerkt = hash_pfad.read_text(encoding="utf-8").strip()
    except OSError:
        gemerkt = ""
    if gemerkt != _prompt_hash(system_prompt):
        final_path.unlink()


def _prompt_merken(final_path: Path, system_prompt: str) -> None:
    _prompt_hash_pfad(final_path).write_text(_prompt_hash(system_prompt), encoding="utf-8")


def _verdichtungsrunde(
    analysen: list[dict[str, Any]],
    runde: int,
    gruppengroesse: int,
    zusammen_dir: Path,
    system_prompt: str,
    generate_fn: GenerateFn,
    raw_dump_dir: Path,
    progress_cb: Callable[[str, int, int], None] | None,
) -> list[dict[str, Any]]:
    """Eine Verdichtungsrunde: fasst je ``gruppengroesse`` benachbarte
    Analysen zu einer zusammen. Runde 1 behaelt die urspruenglichen
    Dateinamen (``zwischenanalyse_0001.json``), damit vorhandene
    Zwischenstaende aus aelteren Laeufen weiter genutzt werden."""
    gruppen = [analysen[i : i + gruppengroesse] for i in range(0, len(analysen), gruppengroesse)]
    stufe = "stufe2_zwischenzusammenfuehrung" if runde == 1 else f"stufe2_verdichtung_runde_{runde}"
    ergebnis = []
    for index, gruppe in enumerate(gruppen):
        if progress_cb:
            progress_cb(stufe, index, len(gruppen))
        if runde == 1:
            name = f"zwischenanalyse_{index + 1:04d}.json"
        else:
            name = f"zwischenanalyse_r{runde:02d}_{index + 1:04d}.json"
        pfad = zusammen_dir / name
        if len(gruppe) == 1:
            if not pfad.is_file():
                pfad.write_text(json.dumps(gruppe[0], ensure_ascii=False, indent=2), encoding="utf-8")
            ergebnis.append(json.loads(pfad.read_text(encoding="utf-8")))
        else:
            ergebnis.append(run_stage2_merge(gruppe, index, system_prompt, generate_fn, pfad, raw_dump_dir))
    return ergebnis


def run_full_protocol_pipeline(
    chunk_texts: list[dict[str, Any]],
    work_dir: Path,
    system_prompt: str,
    generate_fn: GenerateFn | None = None,
    group_size: int = 4,
    progress_cb: Callable[[str, int, int], None] | None = None,
    max_kontext_zeichen: int = MAX_KONTEXT_ZEICHEN,
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

    consolidated = stage1_results
    runde = 1
    while True:
        gruppengroesse = group_size if runde == 1 else max(group_size, 2)
        consolidated = _verdichtungsrunde(
            consolidated,
            runde,
            gruppengroesse,
            zusammen_dir,
            system_prompt,
            generate_fn,
            raw_dump_dir,
            progress_cb,
        )
        if len(consolidated) <= 1 or runde >= MAX_VERDICHTUNGSRUNDEN:
            break
        if len(json.dumps(consolidated, ensure_ascii=False, indent=2)) <= max_kontext_zeichen:
            break
        runde += 1

    if progress_cb:
        progress_cb("stufe3_gesamtprotokoll", 0, 1)
    final_path = zusammen_dir / "protokoll.json"
    _protokoll_verwerfen_wenn_prompt_geaendert(final_path, system_prompt)
    protokoll = run_stage3_final_protocol(consolidated, system_prompt, generate_fn, final_path, raw_dump_dir)
    _prompt_merken(final_path, system_prompt)
    return protokoll
