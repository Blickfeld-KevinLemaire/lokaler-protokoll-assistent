"""Erzeugung aller Ausgabedateien: TXT, JSON, SRT, VTT, Protokoll-JSON/-MD,
Verarbeitungsbericht und (optional) DOCX.

Segmente tragen intern immer die technische ``sprecher_id`` (z.B.
``SPEAKER_00``). Anzeigenamen werden erst beim Export aufgeloest. Dadurch
kann nach einer Umbenennung TXT/JSON/SRT/VTT neu erzeugt werden, ohne die
Audiodatei erneut zu transkribieren -- es wird lediglich das bereits
gespeicherte JSON mit den technischen IDs erneut gelesen
(``reexport_with_new_names``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.utils.timeformat import format_srt_timestamp, format_timestamp, format_vtt_timestamp

UNBENANNTER_SPRECHER = "Sprecher unbekannt"


def make_run_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def compute_speaker_stats(segments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for segment in segments:
        speaker_id = segment.get("sprecher_id") or "UNBEKANNT"
        entry = stats.setdefault(
            speaker_id, {"segmente": 0, "sprechdauer_sekunden": 0.0, "chunk_vorkommen": set()}
        )
        entry["segmente"] += 1
        entry["sprechdauer_sekunden"] += max(0.0, segment["end"] - segment["start"])
        if segment.get("chunk_index") is not None:
            entry["chunk_vorkommen"].add(segment["chunk_index"])
    for entry in stats.values():
        entry["chunk_vorkommen"] = sorted(entry["chunk_vorkommen"])
    return stats


def build_speaker_names(
    speaker_ids_in_order: list[str], name_overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """Weist Anzeigenamen zu. Manuell vergebene Namen bleiben erhalten;
    nicht benannte IDs heissen nach ihrem Platz in der Reihenfolge des
    ersten Auftretens 'Sprecher 1', 'Sprecher 2', ...

    Die Nummer haengt bewusst NICHT davon ab, wie viele andere Sprecher
    benannt wurden: Ein eigener Zaehler nur fuer die unbenannten haette
    aus 'Sprecher 2' ein 'Sprecher 1' gemacht, sobald der erste Sprecher
    einen echten Namen bekommt. Wer einen von fuenf Sprechern benennt,
    findet die uebrigen vier danach unter unveraenderten Nummern wieder.
    """
    name_overrides = name_overrides or {}
    names: dict[str, str] = {}
    for position, speaker_id in enumerate(speaker_ids_in_order, start=1):
        override = name_overrides.get(speaker_id, "").strip()
        names[speaker_id] = override or f"Sprecher {position}"
    return names


def speaker_ids_in_order_of_appearance(segments: list[dict[str, Any]]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        speaker_id = segment.get("sprecher_id")
        if speaker_id and speaker_id not in seen:
            seen.add(speaker_id)
            order.append(speaker_id)
    return order


def attach_speaker_names(
    segments: list[dict[str, Any]], speaker_names: dict[str, str]
) -> list[dict[str, Any]]:
    enriched = []
    for segment in segments:
        speaker_id = segment.get("sprecher_id")
        name = speaker_names.get(speaker_id, UNBENANNTER_SPRECHER) if speaker_id else UNBENANNTER_SPRECHER
        entry = dict(segment)
        entry["sprecher"] = name
        enriched.append(entry)
    return enriched


def build_txt_content(
    source_name: str,
    created_iso: str,
    model_name: str,
    language: str,
    speaker_count: int,
    segments: list[dict[str, Any]],
    diarization_enabled: bool = True,
) -> str:
    if diarization_enabled:
        titel = "PROTOKOLL-ASSISTENT – LOKALES VOLLTRANSKRIPT MIT SPRECHERTRENNUNG"
        sprecher_zeile = f"Erkannte Sprecher: {speaker_count}"
    else:
        titel = "PROTOKOLL-ASSISTENT – LOKALES VOLLTRANSKRIPT (ANONYM, OHNE SPRECHERTRENNUNG)"
        sprecher_zeile = "Sprechertrennung: deaktiviert - kein Sprecherbezug enthalten."
    header = [
        titel,
        f"Quelldatei: {source_name}",
        f"Erstellt: {created_iso}",
        f"Transkriptionsmodell: {model_name}",
        "Verarbeitung: vollständig lokal",
        f"Erkannte Sprache: {language}",
        sprecher_zeile,
        "",
    ]
    if diarization_enabled:
        lines = [
            f"[{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}] "
            f"{segment['sprecher']}: {segment['text']}"
            for segment in segments
        ]
    else:
        lines = [
            f"[{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}] "
            f"{segment['text']}"
            for segment in segments
        ]
    return "\n".join(header + lines) + "\n"


def _untertitelzeile(segment: dict[str, Any], diarization_enabled: bool) -> str:
    """Textzeile eines Untertitels -- mit Sprecher nur dann, wenn die
    Sprechertrennung ueberhaupt gelaufen ist.

    Ohne diese Unterscheidung stand in SRT und VTT vor jedem Satz
    'Sprecher unbekannt: ', waehrend die TXT-Datei im Kopf ausdruecklich
    "kein Sprecherbezug enthalten" versprach.
    """
    if not diarization_enabled:
        return str(segment["text"])
    return f"{segment['sprecher']}: {segment['text']}"


def build_srt_content(segments: list[dict[str, Any]], diarization_enabled: bool = True) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}\n"
            f"{_untertitelzeile(segment, diarization_enabled)}\n"
        )
    return "\n".join(blocks) + "\n"


def build_vtt_content(segments: list[dict[str, Any]], diarization_enabled: bool = True) -> str:
    lines = ["WEBVTT", ""]
    for segment in segments:
        lines.append(f"{format_vtt_timestamp(segment['start'])} --> {format_vtt_timestamp(segment['end'])}")
        lines.append(_untertitelzeile(segment, diarization_enabled))
        lines.append("")
    return "\n".join(lines) + "\n"


def build_json_result(
    source_name: str,
    source_stem: str,
    run_timestamp: str,
    created_iso: str,
    model_name: str,
    language: str,
    device_desc: str,
    processing_duration_seconds: float,
    segments: list[dict[str, Any]],
    speaker_names: dict[str, str],
    speaker_stats: dict[str, dict[str, Any]],
    diarization_enabled: bool = True,
) -> dict[str, Any]:
    speakers_list = []
    for speaker_id, name in speaker_names.items():
        stat = speaker_stats.get(speaker_id, {"segmente": 0, "sprechdauer_sekunden": 0.0, "chunk_vorkommen": []})
        speakers_list.append(
            {
                "sprecher_id": speaker_id,
                "anzeigename": name,
                "anzahl_segmente": stat["segmente"],
                "sprechdauer_sekunden": round(stat["sprechdauer_sekunden"], 3),
                "chunk_vorkommen": stat.get("chunk_vorkommen", []),
            }
        )

    exported_segments = []
    for segment in segments:
        exported_segments.append(
            {
                "nummer": segment.get("nummer"),
                "start_sekunden": round(segment["start"], 3),
                "ende_sekunden": round(segment["end"], 3),
                "start": format_timestamp(segment["start"]),
                "ende": format_timestamp(segment["end"]),
                "sprecher_id": segment.get("sprecher_id"),
                "sprecher": segment["sprecher"],
                "text": segment["text"],
                "moegliche_ueberschneidung": bool(segment.get("moegliche_ueberschneidung", False)),
            }
        )

    gesamttext = "\n".join(f"{segment['sprecher']}: {segment['text']}" for segment in segments)

    return {
        "quelldatei": source_name,
        "quelldatei_stamm": source_stem,
        "lauf_zeitstempel": run_timestamp,
        "erstellt": created_iso,
        "modell": model_name,
        "sprache": language,
        "verarbeitungsgeraet": device_desc,
        "verarbeitungsdauer_sekunden": round(processing_duration_seconds, 3),
        "verarbeitung": "vollständig lokal",
        "sprechertrennung_aktiv": diarization_enabled,
        "anzahl_sprecher": len(speaker_names) if diarization_enabled else 0,
        "sprecher_zuordnung": speakers_list if diarization_enabled else [],
        "anzahl_segmente": len(exported_segments),
        "segmente": exported_segments,
        "gesamttext": gesamttext,
        "hinweis": (
            "Sprecherbezeichnungen sind technische IDs bzw. frei vergebene Namen, "
            "keine automatisch verifizierten Identitaeten."
        ),
    }


@dataclass
class ExportPaths:
    txt: Path
    json: Path
    srt: Path
    vtt: Path


def resolve_unique_base(output_dir: Path, base: str) -> str:
    candidate = base
    counter = 2
    while any((output_dir / f"{candidate}{ext}").exists() for ext in (".txt", ".json", ".srt", ".vtt")):
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def resolve_export_paths(output_dir: Path, source_stem: str, run_timestamp: str) -> ExportPaths:
    base = resolve_unique_base(output_dir, f"{source_stem}_lokal_transkript_{run_timestamp}")
    return ExportPaths(
        txt=output_dir / f"{base}.txt",
        json=output_dir / f"{base}.json",
        srt=output_dir / f"{base}.srt",
        vtt=output_dir / f"{base}.vtt",
    )


def write_transcript_exports(
    output_dir: Path,
    source_name: str,
    source_stem: str,
    run_timestamp: str,
    created_iso: str,
    model_name: str,
    language: str,
    device_desc: str,
    processing_duration_seconds: float,
    segments_raw: list[dict[str, Any]],
    speaker_names: dict[str, str],
    diarization_enabled: bool = True,
) -> ExportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = attach_speaker_names(segments_raw, speaker_names)
    stats = compute_speaker_stats(segments_raw)
    paths = resolve_export_paths(output_dir, source_stem, run_timestamp)

    json_result = build_json_result(
        source_name,
        source_stem,
        run_timestamp,
        created_iso,
        model_name,
        language,
        device_desc,
        processing_duration_seconds,
        enriched,
        speaker_names,
        stats,
        diarization_enabled,
    )

    paths.txt.write_text(
        build_txt_content(
            source_name, created_iso, model_name, language, len(speaker_names), enriched, diarization_enabled
        ),
        encoding="utf-8",
    )
    paths.json.write_text(json.dumps(json_result, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.srt.write_text(build_srt_content(enriched, diarization_enabled), encoding="utf-8")
    paths.vtt.write_text(build_vtt_content(enriched, diarization_enabled), encoding="utf-8")
    return paths


def rebuild_segments_from_json(json_data: dict[str, Any]) -> list[dict[str, Any]]:
    segments = []
    for segment in json_data["segmente"]:
        segments.append(
            {
                "nummer": segment.get("nummer"),
                "start": segment["start_sekunden"],
                "end": segment["ende_sekunden"],
                "sprecher_id": segment.get("sprecher_id"),
                "text": segment["text"],
                "moegliche_ueberschneidung": segment.get("moegliche_ueberschneidung", False),
            }
        )
    return segments


def reexport_with_new_names(json_path: Path, name_overrides: dict[str, str]) -> ExportPaths:
    """Erzeugt TXT/JSON/SRT/VTT aus einem bereits vorhandenen JSON-Export neu,
    unter Verwendung neuer Sprechernamen -- ohne erneute Transkription.
    Ueberschreibt bewusst dieselben (bereits vorhandenen) Dateien desselben
    Laufs, da dies eine explizite, vom Benutzer ausgeloeste Aktion ist."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    diarization_enabled = data.get("sprechertrennung_aktiv", True)
    segments = rebuild_segments_from_json(data)
    order = speaker_ids_in_order_of_appearance(segments)
    speaker_names = build_speaker_names(order, name_overrides)

    output_dir = json_path.parent
    source_stem = data["quelldatei_stamm"]
    run_timestamp = data["lauf_zeitstempel"]
    enriched = attach_speaker_names(segments, speaker_names)
    stats = compute_speaker_stats(segments)

    json_result = build_json_result(
        data["quelldatei"],
        source_stem,
        run_timestamp,
        data["erstellt"],
        data["modell"],
        data["sprache"],
        data["verarbeitungsgeraet"],
        data["verarbeitungsdauer_sekunden"],
        enriched,
        speaker_names,
        stats,
        diarization_enabled,
    )

    base = f"{source_stem}_lokal_transkript_{run_timestamp}"
    paths = ExportPaths(
        txt=output_dir / f"{base}.txt",
        json=json_path,
        srt=output_dir / f"{base}.srt",
        vtt=output_dir / f"{base}.vtt",
    )
    paths.txt.write_text(
        build_txt_content(
            data["quelldatei"],
            data["erstellt"],
            data["modell"],
            data["sprache"],
            len(speaker_names),
            enriched,
            diarization_enabled,
        ),
        encoding="utf-8",
    )
    paths.json.write_text(json.dumps(json_result, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.srt.write_text(build_srt_content(enriched, diarization_enabled), encoding="utf-8")
    paths.vtt.write_text(build_vtt_content(enriched, diarization_enabled), encoding="utf-8")
    return paths


def render_protocol_markdown(protocol: dict[str, Any]) -> str:
    lines = [f"# {protocol.get('titel') or 'Protokoll'}", "", protocol.get("kurzzusammenfassung", ""), ""]

    def section(title: str, items: list[Any], formatter) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        for item in items:
            lines.append(formatter(item))
        lines.append("")

    section(
        "Themen",
        protocol.get("themen", []),
        lambda t: f"- **{t.get('thema', '')}** ({t.get('zeitraum', '')}): "
        + "; ".join(t.get("kernaussagen", [])),
    )
    section(
        "Entscheidungen",
        protocol.get("entscheidungen", []),
        lambda e: f"- {e.get('entscheidung', '')} "
        f"(Sprecher: {e.get('sprecher', '') or 'unklar'}, Zeitpunkt: {e.get('zeitpunkt', '') or 'unklar'}, "
        f"Quelle: {e.get('quelle', '')})",
    )
    section(
        "Aufgaben",
        protocol.get("aufgaben", []),
        lambda a: f"- {a.get('aufgabe', '')} "
        f"(Verantwortlich: {a.get('verantwortlich', '') or 'unklar'}, Frist: {a.get('frist', '') or 'unklar'}, "
        f"Quelle: {a.get('quelle', '')})",
    )
    section("Termine", protocol.get("termine", []), lambda item: f"- {item}")
    section("Offene Fragen", protocol.get("offene_fragen", []), lambda item: f"- {item}")
    section("Wichtige Fakten", protocol.get("wichtige_fakten", []), lambda item: f"- {item}")
    section(
        "Unsichere Transkriptstellen",
        protocol.get("unsichere_transkriptstellen", []),
        lambda item: f"- {item}",
    )
    section("Quellenhinweise", protocol.get("quellenhinweise", []), lambda item: f"- {item}")
    return "\n".join(lines) + "\n"


def write_protocol_exports(
    output_dir: Path, protocol: dict[str, Any], source_stem: str, run_timestamp: str
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{source_stem}_protokoll_{run_timestamp}.json"
    md_path = output_dir / f"{source_stem}_protokoll_{run_timestamp}.md"
    json_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_protocol_markdown(protocol), encoding="utf-8")
    return json_path, md_path


def write_protocol_docx(protocol: dict[str, Any], output_path: Path) -> bool:
    """Optionaler DOCX-Export. Liefert ``False``, wenn ``python-docx`` nicht
    installiert ist (das Paket ist gemaess Auftrag optional)."""
    try:
        import docx  # type: ignore
    except ImportError:
        return False

    document = docx.Document()
    document.add_heading(protocol.get("titel") or "Protokoll", level=1)
    if protocol.get("kurzzusammenfassung"):
        document.add_paragraph(protocol["kurzzusammenfassung"])

    def add_section(title: str, items: list[Any], formatter) -> None:
        if not items:
            return
        document.add_heading(title, level=2)
        for item in items:
            document.add_paragraph(formatter(item), style="List Bullet")

    add_section(
        "Entscheidungen",
        protocol.get("entscheidungen", []),
        lambda e: f"{e.get('entscheidung', '')} (Verantwortlich: {e.get('sprecher', '') or 'unklar'})",
    )
    add_section(
        "Aufgaben",
        protocol.get("aufgaben", []),
        lambda a: f"{a.get('aufgabe', '')} (Verantwortlich: {a.get('verantwortlich', '') or 'unklar'}, "
        f"Frist: {a.get('frist', '') or 'unklar'})",
    )
    add_section("Offene Fragen", protocol.get("offene_fragen", []), lambda item: str(item))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return True


def build_processing_report(
    manifest: dict[str, Any], models_used: dict[str, Any], timings: dict[str, Any]
) -> dict[str, Any]:
    return {
        "quelldatei": manifest["quelldatei_name"],
        "anzahl_chunks": manifest["anzahl_chunks"],
        "chunk_status": [
            {"index": chunk["index"], "status": chunk["status"], "fehler": chunk["fehler"]}
            for chunk in manifest["chunks"]
        ],
        "diarisierung_status": manifest.get("diarisierung_status"),
        "protokoll_status": manifest.get("protokoll_status"),
        "modelle": models_used,
        "laufzeiten_sekunden": timings,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def write_processing_report(work_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    zusammen_dir = work_dir / "zusammengefuehrt"
    zusammen_dir.mkdir(parents=True, exist_ok=True)
    json_path = zusammen_dir / "verarbeitungsbericht.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Verarbeitungsbericht",
        "",
        f"Quelldatei: {report['quelldatei']}",
        f"Anzahl Chunks: {report['anzahl_chunks']}",
        "",
        "## Chunk-Status",
    ]
    for chunk in report["chunk_status"]:
        suffix = f" -- Fehler: {chunk['fehler']}" if chunk["fehler"] else ""
        lines.append(f"- Chunk {chunk['index'] + 1}: {chunk['status']}{suffix}")
    md_path = json_path.with_suffix(".md")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
