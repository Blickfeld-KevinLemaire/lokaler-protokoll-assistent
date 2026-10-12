"""Mehrstufige, nachvollziehbare und fortsetzbare Nachbearbeitung eines
Transkripts ueber ein Sprachmodell (lokal ueber Ollama oder per API).

Der Systemprompt ist der **alleinige Auftrag**: Was das Modell mit dem
Transkript tun soll und in welcher Form es antwortet, bestimmt allein er.
Der Code gibt weder eine Gliederung noch ein Ausgabeformat vor. Ist kein
Systemprompt hinterlegt, fasst das Modell so zusammen, wie es fuer den
Inhalt am sinnvollsten ist (``OHNE_VORGABE_SYSTEMPROMPT``).

Passt das Transkript in einen Abschnitt, genuegt ein einziger Aufruf.
Andernfalls laeuft die Auswertung in drei Stufen:

Stufe 1: der Auftrag wird auf jeden Transkript-Abschnitt einzeln angewendet.
Stufe 2: benachbarte Teilergebnisse werden gruppenweise zusammengefuehrt.
         Passt das Ergebnis danach noch nicht in den Kontext der Stufe 3, wird
         in weiteren Runden erneut verdichtet (hoechstens
         ``MAX_VERDICHTUNGSRUNDEN`` insgesamt).
Stufe 3: alle zusammengefuehrten Teilergebnisse werden zum Endergebnis
         vereint -- wieder genau so, wie es der Auftrag verlangt.

Jede Stufe wird als eigene Datei gespeichert. Ist eine Datei bereits
vorhanden, wird sie wiederverwendet statt erneut angefragt -- ein Fehler in
einem einzelnen Abschnitt zwingt also nicht zur kompletten Wiederholung.
Die Zwischenstaende gelten **je Systemprompt** (Unterordner mit einer
Kennung des Prompts): Wer den Auftrag aendert, bekommt ein neues Ergebnis
und nicht das zum alten Auftrag gespeicherte zurueck.

Eine leere Modellantwort wird genau EINMAL erneut angefragt. Bleibt auch
sie leer, wird ein ``ProtocolValidationError`` ausgeloest, ohne vorhandene
Zwischenstaende zu ueberschreiben. Ausnahme Stufe 1: Ein filternder Auftrag
("nur ToDos") kann fuer einen Abschnitt zu Recht nichts liefern. Dort gilt
das leere Ergebnis nach dem zweiten Versuch, wird gespeichert und beim
Zusammenfuehren uebersprungen; nur wenn ALLE Abschnitte leer bleiben, ist
das ein Fehler.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from protokoll_assistent.services import ollama_service

# Stufe 2 laeuft immer mindestens einmal. Danach wird weiter verdichtet, solange
# die Teilergebnisse zusammen laenger als dieser Wert sind (Zeichen; gemessen gut
# 3 Zeichen je Token) und mehr als eines uebrig ist. Muss samt Antwort in
# ollama_service.PROTOKOLL_NUM_CTX passen -- das prueft
# test_ollama_service.test_kontext_reicht_fuer_die_groesste_protokollstufe.
MAX_KONTEXT_ZEICHEN = 40_000
MAX_VERDICHTUNGSRUNDEN = 8

GenerateFn = Callable[[str, str], str]

# Gilt nur, wenn der Anwender keinen Systemprompt eingegeben hat. Bewusst
# ohne Gliederung, ohne Abschnittsnamen und ohne Ausgabeformat.
OHNE_VORGABE_SYSTEMPROMPT = (
    "Du bist ein genauer deutschsprachiger Assistent. Fasse das bereitgestellte "
    "Besprechungstranskript so zusammen, wie es fuer den Inhalt am sinnvollsten ist. "
    "Beschraenke dich auf das, was im Transkript steht, und erfinde nichts dazu."
)

_DENKBLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_DENKBLOCK_ENDE = re.compile(r"</think>", re.IGNORECASE)
_DENKBLOCK_ANFANG = re.compile(r"<think>", re.IGNORECASE)


class ProtocolValidationError(RuntimeError):
    pass


def default_generate_fn(prompt: str, system: str) -> str:
    return ollama_service.generate_text(prompt, system)


def effektiver_systemprompt(system_prompt: str | None) -> str:
    """Der Auftrag, der tatsaechlich an das Modell geht: der Systemprompt des
    Anwenders -- oder, wenn er leer ist, die neutrale Vorgabe."""
    text = (system_prompt or "").strip()
    return text or OHNE_VORGABE_SYSTEMPROMPT


def prompt_kennung(system_prompt: str | None) -> str:
    """Kurze, stabile Kennung des Auftrags. Benennt den Unterordner der
    Zwischenstaende, damit ein anderer Systemprompt nie ein Ergebnis
    wiederverwendet, das zu einem anderen Auftrag entstanden ist."""
    return hashlib.sha256(effektiver_systemprompt(system_prompt).encode("utf-8")).hexdigest()[:12]


def antwort_bereinigen(text: str) -> str:
    """Entfernt Denkbloecke (``<think>...</think>``), die manche Modelle in
    die Antwort schreiben, sowie Leerraum an den Raendern.

    Auch unvollstaendige Denkbloecke: Steht nach dem Entfernen der
    geschlossenen Bloecke noch ein ``</think>`` im Text, hat die Vorlage des
    Modells den Block schon im Prompt geoeffnet -- alles davor ist Nachdenken
    und entfaellt. Ein ``<think>`` ohne Ende macht den Rest zu Nachdenken;
    steht es am Anfang, ist die Antwort leer (und wird wie eine leere Antwort
    behandelt)."""
    bereinigt = _DENKBLOCK.sub("", str(text))
    enden = list(_DENKBLOCK_ENDE.finditer(bereinigt))
    if enden:
        bereinigt = bereinigt[enden[-1].end() :]
    anfang = _DENKBLOCK_ANFANG.search(bereinigt)
    if anfang:
        bereinigt = bereinigt[: anfang.start()]
    return bereinigt.strip()


def _load_or_compute(path: Path, compute: Callable[[], str]) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    result = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result, encoding="utf-8")
    return result


def generate_checked(prompt: str, system: str, generate_fn: GenerateFn, leer_erlaubt: bool = False) -> str:
    """Fragt das Modell an. Eine leere Antwort wird einmal wiederholt. Bleibt
    sie leer, ist das ein Fehler -- ausser mit ``leer_erlaubt`` (Stufe 1),
    dann ist das Ergebnis ein leerer Text."""
    antwort = antwort_bereinigen(generate_fn(prompt, system))
    if antwort:
        return antwort
    antwort = antwort_bereinigen(generate_fn(prompt, system))
    if antwort or leer_erlaubt:
        return antwort
    raise ProtocolValidationError("Das Modell hat auch nach einem zweiten Versuch keine Antwort geliefert.")


def build_single_prompt(start_str: str, end_str: str, text: str) -> str:
    return f"Transkript (Zeitraum {start_str} - {end_str}):\n\n{text}"


def build_stage1_prompt(chunk_index: int, start_str: str, end_str: str, text: str) -> str:
    return (
        f"Das ist Abschnitt {chunk_index + 1} eines laengeren Transkripts "
        f"(Zeitraum {start_str} - {end_str}). Fuehre den Auftrag aus dem Systemprompt "
        "ausschliesslich fuer diesen Abschnitt aus und verwende nur Angaben aus ihm. "
        "Halte dich an Form und Aufbau, die der Auftrag verlangt.\n\n"
        f"Transkriptabschnitt:\n{text}"
    )


def run_stage1_chunk_analysis(
    chunk_index: int,
    chunk_text: str,
    start_str: str,
    end_str: str,
    system_prompt: str,
    generate_fn: GenerateFn,
    analysis_path: Path,
) -> str:
    def compute() -> str:
        prompt = build_stage1_prompt(chunk_index, start_str, end_str, chunk_text)
        return generate_checked(prompt, system_prompt, generate_fn, leer_erlaubt=True)

    return _load_or_compute(analysis_path, compute)


def build_stage2_prompt(group_results: list[str]) -> str:
    teile = "\n\n".join(f"--- Teilergebnis {nummer} ---\n{text}" for nummer, text in enumerate(group_results, 1))
    return (
        "Die folgenden Teilergebnisse stammen aus aufeinanderfolgenden Abschnitten "
        "desselben Transkripts und wurden nach dem Auftrag aus dem Systemprompt erstellt. "
        "Fuehre sie zu EINEM Teilergebnis zusammen -- in derselben Form und mit demselben "
        "Aufbau, den der Auftrag verlangt. Entferne Dopplungen aus Ueberlappungsbereichen, "
        "lasse aber keine inhaltliche Angabe weg und ergaenze nichts.\n\n" + teile
    )


def run_stage2_merge(
    group_results: list[str],
    system_prompt: str,
    generate_fn: GenerateFn,
    output_path: Path,
) -> str:
    def compute() -> str:
        return generate_checked(build_stage2_prompt(group_results), system_prompt, generate_fn)

    return _load_or_compute(output_path, compute)


def build_stage3_prompt(consolidated: list[str]) -> str:
    teile = "\n\n".join(f"--- Teilergebnis {nummer} ---\n{text}" for nummer, text in enumerate(consolidated, 1))
    return (
        "Die folgenden Teilergebnisse stammen aus aufeinanderfolgenden Teilen desselben "
        "Transkripts und wurden nach dem Auftrag aus dem Systemprompt erstellt. Erstelle "
        "daraus das Endergebnis, genau so wie der Auftrag es verlangt. Fuege keine Gliederung, "
        "Ueberschriften oder Abschnitte hinzu, die der Auftrag nicht verlangt, und ergaenze "
        "keine Informationen, die nicht in den Teilergebnissen vorkommen.\n\n" + teile
    )


def run_stage3_final_protocol(
    consolidated: list[str],
    system_prompt: str,
    generate_fn: GenerateFn,
    output_path: Path,
) -> str:
    def compute() -> str:
        return generate_checked(build_stage3_prompt(consolidated), system_prompt, generate_fn)

    return _load_or_compute(output_path, compute)


def _verdichtungsrunde(
    teilergebnisse: list[str],
    runde: int,
    gruppengroesse: int,
    zusammen_dir: Path,
    system_prompt: str,
    generate_fn: GenerateFn,
    progress_cb: Callable[[str, int, int], None] | None,
) -> list[str]:
    """Eine Verdichtungsrunde: fasst je ``gruppengroesse`` benachbarte
    Teilergebnisse zu einem zusammen. Runde 1 heisst wie bisher Stufe 2, weitere
    Runden tragen die Rundennummer im Namen der Datei."""
    gruppen = [teilergebnisse[i : i + gruppengroesse] for i in range(0, len(teilergebnisse), gruppengroesse)]
    stufe = "stufe2_zwischenzusammenfuehrung" if runde == 1 else f"stufe2_verdichtung_runde_{runde}"
    ergebnis = []
    for index, gruppe in enumerate(gruppen):
        if progress_cb:
            progress_cb(stufe, index, len(gruppen))
        if runde == 1:
            name = f"zwischenergebnis_{index + 1:04d}.md"
        else:
            name = f"zwischenergebnis_r{runde:02d}_{index + 1:04d}.md"
        pfad = zusammen_dir / name
        if len(gruppe) == 1:
            if not pfad.is_file():
                pfad.write_text(gruppe[0], encoding="utf-8")
            ergebnis.append(pfad.read_text(encoding="utf-8"))
        else:
            ergebnis.append(run_stage2_merge(gruppe, system_prompt, generate_fn, pfad))
    return ergebnis


def run_full_protocol_pipeline(
    chunk_texts: list[dict[str, object]],
    work_dir: Path,
    system_prompt: str | None,
    generate_fn: GenerateFn | None = None,
    group_size: int = 4,
    progress_cb: Callable[[str, int, int], None] | None = None,
    max_kontext_zeichen: int = MAX_KONTEXT_ZEICHEN,
) -> str:
    """``chunk_texts``: Liste von ``{"index", "start_str", "end_str", "text"}``.

    Wendet den Systemprompt als Auftrag auf das Transkript an und gibt das
    Ergebnis als Text zurueck -- in der Form, die der Auftrag verlangt.
    Bereits vorhandene Zwischenstaende zum selben Auftrag werden
    wiederverwendet. ``system_prompt`` darf leer sein (siehe
    ``OHNE_VORGABE_SYSTEMPROMPT``).
    """
    generate_fn = generate_fn or default_generate_fn
    auftrag = effektiver_systemprompt(system_prompt)
    kennung = prompt_kennung(system_prompt)
    analysen_dir = work_dir / "analysen" / kennung
    zusammen_dir = work_dir / "zusammengefuehrt" / kennung
    analysen_dir.mkdir(parents=True, exist_ok=True)
    zusammen_dir.mkdir(parents=True, exist_ok=True)
    final_path = zusammen_dir / "ergebnis.md"

    if not chunk_texts:
        raise ProtocolValidationError("Das Transkript enthaelt keinen Text, der ausgewertet werden koennte.")

    if len(chunk_texts) == 1:
        # Das ganze Transkript passt in einen Abschnitt: ein Aufruf, keine
        # Zwischenstufen -- der Auftrag wird unmittelbar auf den Text angewendet.
        chunk = chunk_texts[0]
        if progress_cb:
            progress_cb("stufe3_gesamtprotokoll", 0, 1)
        prompt = build_single_prompt(str(chunk["start_str"]), str(chunk["end_str"]), str(chunk["text"]))
        return _load_or_compute(final_path, lambda: generate_checked(prompt, auftrag, generate_fn))

    stage1_results = []
    for chunk in chunk_texts:
        index = int(str(chunk["index"]))
        if progress_cb:
            progress_cb("stufe1_chunk_analyse", index, len(chunk_texts))
        path = analysen_dir / f"chunk_{index + 1:04d}.md"
        stage1_results.append(
            run_stage1_chunk_analysis(
                index,
                str(chunk["text"]),
                str(chunk["start_str"]),
                str(chunk["end_str"]),
                auftrag,
                generate_fn,
                path,
            )
        )

    # Leere Abschnittsergebnisse (nichts Passendes zum Auftrag) bleiben
    # gespeichert, werden aber nicht zusammengefuehrt.
    consolidated = [text for text in stage1_results if text.strip()]
    if not consolidated:
        raise ProtocolValidationError(
            f"Das Modell hat in keinem der {len(stage1_results)} Abschnitte etwas zum Auftrag gefunden "
            "(alle Teilergebnisse sind leer). Bitte den Systemprompt pruefen."
        )
    runde = 1
    while True:
        gruppengroesse = group_size if runde == 1 else max(group_size, 2)
        consolidated = _verdichtungsrunde(
            consolidated, runde, gruppengroesse, zusammen_dir, auftrag, generate_fn, progress_cb
        )
        if len(consolidated) <= 1 or runde >= MAX_VERDICHTUNGSRUNDEN:
            break
        if sum(len(text) for text in consolidated) <= max_kontext_zeichen:
            break
        runde += 1

    if progress_cb:
        progress_cb("stufe3_gesamtprotokoll", 0, 1)
    if len(consolidated) == 1:
        # Es gibt nur ein zusammengefuehrtes Teilergebnis: Eine weitere Runde
        # wuerde es nur umformulieren und dabei vom Auftrag abkommen lassen.
        return _load_or_compute(final_path, lambda: consolidated[0])
    return run_stage3_final_protocol(consolidated, auftrag, generate_fn, final_path)
