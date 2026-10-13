"""Orchestrierung der vollstaendigen lokalen Verarbeitung.

Ablauf: Datei pruefen -> Audio normalisieren -> Chunks planen -> Modell laden
-> Chunks sequenziell transkribieren+ausrichten -> globale Diarisierung ->
Zusammenfuehren (globale Zeitstempel + Overlap-Dedup) -> Sprecherzuordnung ->
TXT/JSON/SRT/VTT-Export -> mehrstufige lokale Ollama-Protokollauswertung ->
Protokoll-Export -> Verarbeitungsbericht.

Die eigentlichen ML-Aufrufe (Transkription, Diarisierung, Ollama) sind ueber
Parameter austauschbar, damit die Ablaufsteuerung -- Fortsetzen nach Abbruch,
Ueberspringen fertiger Chunks, Fehlerbehandlung eines einzelnen Chunks --
unabhaengig von GPU/faster-whisper/pyannote/Ollama getestet werden kann. Ohne
Angabe werden die echten lokalen Implementierungen verwendet.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from protokoll_assistent.services import (
    chunking_service,
    diarisierung_prozess,
    diarization_service,
    dokument_export_service,
    export_service,
    ffmpeg_service,
    manifest_service,
    merge_service,
    model_service,
    ollama_service,
    protocol_service,
    speaker_merge_service,
    sprecherprofil_service,
    transcription_service,
)
from protokoll_assistent.utils.logging_setup import get_logger
from protokoll_assistent.utils.timeformat import format_timestamp

logger = get_logger()

STAGE_LABELS = {
    "datei_pruefung": "Datei wird geprüft",
    "audio_normalisierung": "Audio wird vorbereitet",
    "chunk_planung": "Chunks werden geplant",
    "modell_laden": "Modell wird geladen",
    "transkription": "Transkription läuft",
    "ausrichtung": "Zeitstempel werden ausgerichtet",
    "diarisierung": "Sprecher werden getrennt",
    "zusammenfuehrung": "Chunks werden zusammengeführt",
    "export_transkript": "Ausgabedateien werden erstellt",
    "transkript_laden": "Transkript wird geladen",
    "protokoll_auswertung": "Lokale Protokollauswertung läuft",
    "export_protokoll": "Protokolldateien werden erstellt",
    "protokoll_fehlgeschlagen": "Protokollauswertung fehlgeschlagen",
    "abgeschlossen": "Verarbeitung abgeschlossen",
}

# Die Live-Vorschau waehrend der Verarbeitung ist nur ein erster Eindruck -
# bei langen Aufnahmen waere der volle Text unhandlich, und fuer eine
# Vorschau reichen die ersten zwei Minuten.
PREVIEW_MAX_SECONDS = 120.0


def build_preview_text(segments: list[dict[str, Any]], diarization_enabled: bool) -> str:
    """Baut den Text fuer die Live-Vorschau (nicht die Export-Dateien).

    Ohne Sprechertrennung gibt es keine Sprecher zuzuordnen - eine
    Sprecherangabe waere dort nur 'None', und sekundengenaue Zeitstempel
    pro Satz sind ohne Sprecherbezug ebenfalls keine hilfreiche Information.
    Der Export (TXT/JSON/SRT/VTT) ist davon unberuehrt und bleibt
    vollstaendig."""
    begrenzt = [s for s in segments if s["start"] < PREVIEW_MAX_SECONDS]
    if not diarization_enabled:
        return " ".join(s["text"].strip() for s in begrenzt)
    return "\n".join(
        f"[{format_timestamp(s['start'])}] {s.get('sprecher_id')}: {s['text']}" for s in begrenzt
    )


class PipelineCancelled(RuntimeError):
    pass


class PipelineError(RuntimeError):
    pass


@dataclass
class PipelineSettings:
    source_path: Path
    output_dir: Path
    language: str | None = "de"
    min_speakers: int | None = None
    max_speakers: int | None = None
    allow_download: bool = False
    batch_size: int = 4
    device_preference: str = "cuda"
    resume_mode: Literal["fortsetzen", "neu_beginnen"] = "fortsetzen"
    run_protocol: bool = True
    ollama_model: str = ollama_service.DEFAULT_MODEL
    whisper_model: str = model_service.WHISPER_MODEL_NAME
    protocol_group_size: int = 4
    enable_diarization: bool = True
    # Waehrend einer Geraeteaufnahme schon transkribierte Segmente (siehe 'live_service'):
    # {"bestaetigt_bis": Sekunden, "segmente": [...]} mit globalen Zeitstempeln. Alles bis dahin
    # gilt als sicher und wird nicht noch einmal transkribiert; ein Chunk, der nur zum Teil
    # abgedeckt ist, bekommt nur noch seinen Rest transkribiert. 'None' = nichts vorab.
    vorab_live: dict[str, Any] | None = None


@dataclass
class PipelineCallbacks:
    on_stage: Callable[[str, str], None] = lambda key, detail: None
    on_chunk_progress: Callable[[int, int], None] = lambda current, total: None
    on_overall_progress: Callable[[float], None] = lambda fraction: None
    on_preview: Callable[[str], None] = lambda text: None
    on_log: Callable[[str], None] = lambda message: None
    should_cancel: Callable[[], bool] = lambda: False


@dataclass
class PipelineResult:
    work_dir: Path
    export_paths: export_service.ExportPaths
    protocol_paths: tuple[Path, Path] | None
    report_paths: tuple[Path, Path]
    speaker_names: dict[str, str]
    segments: list[dict[str, Any]]
    manifest: dict[str, Any]
    # Gesetzt, wenn die Protokollauswertung angefordert war, aber
    # fehlgeschlagen ist. 'protocol_paths' ist dann None, und das Transkript
    # steht trotzdem zur Verfuegung.
    protokoll_fehler: str | None = None


@dataclass
class TranscriptionResult:
    """Ergebnis des ersten, eigenstaendigen Schritts (nur Transkription).

    Kann direkt an 'run_protocol' weitergereicht werden (ueber
    'export_paths.json'), oder die Oberflaeche laesst den Anwender
    stattdessen ein anderes, frueher erzeugtes Transkript auswaehlen -
    """

    work_dir: Path
    export_paths: export_service.ExportPaths
    speaker_names: dict[str, str]
    segments: list[dict[str, Any]]
    manifest: dict[str, Any]
    total_duration: float
    run_timestamp: str
    timings: dict[str, float]
    # Nur gesetzt, wenn ueber 'run_transcription' (eigenstaendiger Schritt)
    # aufgerufen - 'run_pipeline' schreibt den gemeinsamen Bericht erst nach
    # der anschliessenden Protokollauswertung und laesst dieses Feld leer.
    report_paths: tuple[Path, Path] | None = None


@dataclass
class ProtocolSettings:
    transcript_json_path: Path
    output_dir: Path
    ollama_model: str = ollama_service.DEFAULT_MODEL
    protocol_group_size: int = 4
    # Bleibt dieses Feld 'None', wird der Systemprompt wie bisher aus
    # 'get_system_prompt_file()' gelesen -- fuer die lokale Anwendung aendert
    # sich also nichts. Ein Aufrufer, der den Prompt fuer EINEN Lauf direkt
    # mitgibt (das Hauptfenster laesst ihn bearbeiten),
    # setzt ihn hier. Ohne diesen Weg muesste ein solcher Aufrufer den Text
    # erst in die gemeinsame Einstellungsdatei schreiben und damit den
    # gespeicherten Systemprompt der lokalen Anwendung ueberschreiben.
    system_prompt: str | None = None
    # Kennung des Modells, das die Nachbearbeitung rechnet. Die
    # Zwischenstaende gelten je Modell; ohne Angabe zaehlt 'ollama_model'.
    # Wer ein anderes Modell ueber 'protocol_generate_fn' anbindet (API),
    # setzt hier dessen Kennung.
    protokoll_modell_kennung: str | None = None
    # Teilergebnisse der Auswertung, die schon waehrend der Aufnahme berechnet wurden (siehe
    # 'live_auswertung_service'): eine Funktion, die ``{"stufe1": {...}, "stufe2": {...}}`` liefert (oder 'None').
    # Sie wird erst in der Auswertung selbst aufgerufen und darf dort warten, bis eine noch laufende
    # Teilauswertung fertig ist. Nur Ergebnisse, deren Eingabe genau zur jetzigen passt, werden uebernommen.
    vorab_auswertung: Callable[[], dict[str, dict[str, str]] | None] | None = None
    # Den Auswertungstext ohne Sprecherangaben bauen (reiner Fliesstext je Abschnitt). Noetig, damit er zu
    # dem passt, was schon waehrend der Aufnahme ausgewertet wurde: Die Sprechertrennung gibt es erst am Ende.
    ohne_sprecher: bool = False
    # Laenge der Abschnitte, die das Sprachmodell einzeln auswertet (Sekunden). 'None': Standard (600 s). Kuerzere
    # Abschnitte verkuerzen die Wartezeit, wenn die Auswertung schon waehrend der Aufnahme vorbereitet wurde.
    abschnitt_sekunden: float | None = None


@dataclass
class ProtocolResult:
    work_dir: Path
    protocol_paths: tuple[Path, Path] | None
    report_paths: tuple[Path, Path]
    # Gesetzt, wenn die Protokollauswertung fehlgeschlagen ist.
    protokoll_fehler: str | None = None


def _check_cancel(callbacks: PipelineCallbacks) -> None:
    if callbacks.should_cancel():
        raise PipelineCancelled("Verarbeitung durch Benutzer abgebrochen.")


def validate_source_file(source_path: Path) -> None:
    if not source_path.exists():
        raise PipelineError(f"Datei nicht gefunden: {source_path}")
    if not source_path.is_file():
        raise PipelineError(f"Kein gültiger Dateipfad: {source_path}")
    if source_path.stat().st_size == 0:
        raise PipelineError(f"Datei ist leer: {source_path.name}")


def _build_protocol_chunk_texts(
    chunk_plans: list[chunking_service.ChunkPlan],
    merged_segments: list[dict[str, Any]],
    speaker_names: dict[str, str],
    diarization_enabled: bool = True,
    fliesstext: bool = False,
) -> list[dict[str, Any]]:
    """Baut je Chunk den zugehoerigen (bereits global datierten und
    deduplizierten) Transkriptausschnitt fuer die Ollama-Auswertung.

    Die Chunks ueberlappen sich um ``overlap_with_previous`` Sekunden. Ein
    Segment aus diesem Ueberlappungsfenster gehoert bereits zum
    VORHERIGEN Chunk -- ``merge_service`` hat dort gerade erst die
    Dubletten entfernt. Wuerde hier schlicht auf ``global_start`` geprueft,
    bekaeme das Modell dieselben Saetze zweimal vorgelegt und zaehlte
    Aussagen, Entscheidungen und Aufgaben doppelt. Deshalb beginnt das
    Fenster jedes Folge-Chunks erst hinter der Ueberlappung; die Fenster
    schliessen luecken- und ueberschneidungsfrei aneinander an.

    Ohne Sprechertrennung gibt es keine Sprecher zuzuordnen - dann sind
    weder Sprecherangabe noch sekundengenaue Zeitstempel eine hilfreiche
    Information, nur reiner Fliesstext (genau wie in 'build_preview_text').

    ``fliesstext`` (nur ohne Sprecher): alle Segmente eines Chunks als eine Zeile, Leerraum vereinheitlicht.
    Die wortgenaue Sprecherzuordnung teilt ein Segment dort, wo der Sprecher wechselt; zeilenweise ergaebe
    dasselbe Gesprochene dann einen anderen Text als waehrend der Aufnahme (vor der Sprechertrennung) -- und
    die dort schon berechneten Teilergebnisse passten nie (siehe ``live_auswertung_service``).
    """
    chunk_texts = []
    for plan in chunk_plans:
        fenster_start = plan.global_start + plan.overlap_with_previous
        lines = []
        for segment in merged_segments:
            if fenster_start <= segment["start"] < plan.global_end:
                if diarization_enabled:
                    # 'sprecher_id' darf fehlen - dict.get(None) ist erlaubt
                    # und liefert dann den Standardwert.
                    sprecher_id = segment.get("sprecher_id")
                    name = speaker_names.get(sprecher_id, "Sprecher unbekannt")  # type: ignore[arg-type]
                    lines.append(f"[{format_timestamp(segment['start'])}] {name}: {segment['text']}")
                elif fliesstext:
                    woerter = " ".join(str(segment["text"]).split())
                    if woerter:
                        lines.append(woerter)
                else:
                    lines.append(segment["text"])
        if not lines:
            # Ein Chunk ohne eigenen Text (Stille, oder vollstaendig von der
            # Ueberlappung des Vorgaengers abgedeckt) wird nicht angefragt --
            # das Modell haette dazu nichts zu sagen.
            continue
        chunk_texts.append(
            {
                "index": plan.index,
                "start_str": format_timestamp(fenster_start),
                "end_str": format_timestamp(plan.global_end),
                "text": (" " if fliesstext and not diarization_enabled else "\n").join(lines),
            }
        )
    return chunk_texts


def baue_protokoll_chunk_texte(
    chunk_plans: list[chunking_service.ChunkPlan],
    merged_segments: list[dict[str, Any]],
    speaker_names: dict[str, str],
    diarization_enabled: bool = True,
    fliesstext: bool = False,
) -> list[dict[str, Any]]:
    """Der Text je Chunk fuer die Auswertung (oeffentlich: ``live_auswertung_service`` baut ihn vorab genauso)."""
    return _build_protocol_chunk_texts(chunk_plans, merged_segments, speaker_names, diarization_enabled, fliesstext)


def _automatisches_word(callbacks: PipelineCallbacks, transkript_json: Path, protokoll_json: Path | None = None) -> None:
    """Legt die zusammengefasste Word-Datei neben die uebrigen Ausgaben.

    Das geschieht bei jeder Verarbeitung von selbst (mit Protokoll: Protokoll
    und Transkript in einem Dokument). Scheitert es, wird das nur
    protokolliert -- das Transkript bzw. Protokoll ist ja fertig und darf
    daran nicht verloren gehen."""
    try:
        ziel = dokument_export_service.automatisches_word(transkript_json, protokoll_json)
    except dokument_export_service.ExportFehler as fehler:
        callbacks.on_log(f"Die Word-Datei wurde nicht erstellt: {fehler}")
        return
    if ziel is not None:
        callbacks.on_log(f"Word-Datei erstellt: {ziel.name}")


def _grafikspeicher_fuer_whisper_freimachen(device: str, callbacks: PipelineCallbacks) -> None:
    """Reicht der freie Grafikspeicher nicht fuer Whisper, nimmt Ollama seine
    Modelle heraus. Ist genug frei, bleibt alles geladen -- dann muss Ollama
    das Sprachmodell fuer das Protokoll nicht neu laden. Das Entladen ist nur
    der Ausweg fuer knappe Karten (6 GB); auf grossen Karten passiert nichts."""
    if device != "cuda":
        return
    frei = model_service.freier_grafikspeicher()
    if frei is None:
        return
    # torch meldet unter Windows zu viel freien Speicher, solange Ollama ein
    # Modell haelt (gemessen: 6,9 GB "frei" bei 5,6 GB Ollama auf einer 8-GB-
    # Karte; Whisper scheiterte dann mit "CUDA out of memory"). Deshalb gilt
    # hoechstens, was nach Abzug der Ollama-Modelle von der Karte bleibt.
    gesamt = model_service.gesamter_grafikspeicher()
    if gesamt is not None:
        frei = min(frei, gesamt - ollama_service.belegter_grafikspeicher())
    if frei >= model_service.WHISPER_GRAFIKSPEICHER_BYTES:
        return
    entladen = ollama_service.modelle_entladen()
    if entladen:
        callbacks.on_log(
            f"Grafikspeicher fuer die Transkription freigemacht (frei waren {frei / 1024**3:.1f} GB): "
            f"Ollama hat {', '.join(entladen)} entladen und laedt es fuer das Protokoll wieder."
        )


def _sprechertrennung(
    audio: Path, settings: PipelineSettings, device: str, callbacks: PipelineCallbacks
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """pyannote auf dem passenden Geraet. Auf der GPU immer in einem eigenen
    Prozess (siehe ``diarisierung_prozess``); scheitert der, auf der CPU hier."""
    geraet = model_service.geraet_fuer_sprechertrennung(device)
    if geraet == "cuda":
        callbacks.on_log("Sprechertrennung laeuft in einem eigenen Prozess auf der Grafikkarte.")
        try:
            return diarisierung_prozess.diarisiere_in_eigenem_prozess(
                audio, settings.min_speakers, settings.max_speakers, "cuda"
            )
        except diarisierung_prozess.DiarisierungsprozessFehler as fehler:
            callbacks.on_log(f"{fehler} -- die Sprechertrennung laeuft stattdessen auf der CPU.")
    pipeline = model_service.load_pyannote_pipeline("cpu")
    waveform_dict = diarization_service.build_waveform_dict(transcription_service.load_audio_array(audio))
    embeddings: dict[str, list[float]] = {}
    turns = diarization_service.diarize_waveform(
        pipeline, waveform_dict, settings.min_speakers, settings.max_speakers, embeddings_out=embeddings
    )
    return turns, embeddings


# Ein Chunk gilt als vollstaendig live transkribiert, wenn der sichere Punkt hoechstens so weit vor seinem
# Ende liegt (Rundungsunterschiede der Dauer).
_LIVE_ENDE_TOLERANZ_SEKUNDEN = 1.0
# Ein Chunk wird nur dann aus Live-Segmenten und einem Rest zusammengesetzt, wenn die Live-Segmente mindestens
# so viel davon abdecken; sonst lohnt es nicht (er wird ganz neu transkribiert).
_LIVE_TEIL_MIN_SEKUNDEN = 30.0

_LIVE_VOLL = "voll"
_LIVE_TEIL = "teil"
_LIVE_KEINE = "keine"


def _chunk_fertig(manifest: dict[str, Any], work_dir: Path, plan: chunking_service.ChunkPlan) -> bool:
    status = next(c for c in manifest["chunks"] if c["index"] == plan.index)
    return (
        status["status"] == manifest_service.STATUS_ABGESCHLOSSEN
        and manifest_service.chunk_transcript_path(work_dir, plan.index).exists()
    )


def _live_lesen(vorab: dict[str, Any] | None) -> tuple[float, list[dict[str, Any]]]:
    """``(sicherer Punkt, Segmente)`` aus ``PipelineSettings.vorab_live``; ``(0.0, [])``, wenn es nichts
    Brauchbares ist."""
    if not vorab or not isinstance(vorab.get("segmente"), list):
        return 0.0, []
    try:
        bis = float(vorab["bestaetigt_bis"])
    except (KeyError, TypeError, ValueError):
        return 0.0, []
    segmente = [
        s
        for s in vorab["segmente"]
        if isinstance(s, dict) and isinstance(s.get("start"), int | float) and isinstance(s.get("end"), int | float)
    ]
    return (bis, segmente) if bis > 0 and segmente else (0.0, [])


def _live_abdeckung(plan: chunking_service.ChunkPlan, live_bis: float) -> str:
    """Wie viel dieses Chunks decken die Live-Segmente ab: ``voll``, ``teil`` oder ``keine``?"""
    if live_bis <= 0:
        return _LIVE_KEINE
    if plan.global_end <= live_bis + _LIVE_ENDE_TOLERANZ_SEKUNDEN:
        return _LIVE_VOLL
    if live_bis - plan.global_start >= _LIVE_TEIL_MIN_SEKUNDEN:
        return _LIVE_TEIL
    return _LIVE_KEINE


def _live_segmente_des_chunks(
    segmente: list[dict[str, Any]], plan: chunking_service.ChunkPlan
) -> list[dict[str, Any]]:
    """Die Live-Segmente, die in diesem Chunk beginnen, mit Chunk-Zeitstempeln (wie die Segmente eines
    transkribierten Chunks). Segmente aus der Ueberlappung mit dem Vorgaenger stehen in beiden; das
    Zusammenfuehren entfernt die Dubletten wie bisher."""
    im_chunk = [s for s in segmente if plan.global_start <= float(s["start"]) < plan.global_end]
    return merge_service.to_global_segments(im_chunk, -plan.global_start)


def _run_transcription_stage(
    settings: PipelineSettings,
    callbacks: PipelineCallbacks,
    transcribe_chunk_fn: Callable[[Path], list[dict[str, Any]]] | None,
    diarize_fn: Callable[[Path, int | None, int | None], list[dict[str, Any]]] | None,
) -> TranscriptionResult:
    """Kern der Transkription: Datei pruefen bis Export der Transkript-
    Dateien (TXT/JSON/SRT/VTT). Emittiert absichtlich KEIN 'abgeschlossen'
    und schreibt KEINEN Verarbeitungsbericht - das entscheidet der
    jeweilige oeffentliche Einstiegspunkt: 'run_transcription' fuer sich
    allein, 'run_pipeline' erst nach der anschliessenden
    Protokollauswertung. 'TranscriptionResult.report_paths' bleibt hier
    deshalb None.
    """
    started_at = time.monotonic()
    timings: dict[str, float] = {}

    callbacks.on_stage("datei_pruefung", STAGE_LABELS["datei_pruefung"])
    validate_source_file(settings.source_path)
    _check_cancel(callbacks)

    from protokoll_assistent.utils.paths import get_work_dir

    base_work_dir = get_work_dir()
    file_hash = manifest_service.compute_file_hash(settings.source_path)
    work_dir = manifest_service.get_work_dir_for_file(base_work_dir, file_hash)

    existing_manifest = manifest_service.load_manifest(work_dir)
    if settings.resume_mode == "neu_beginnen":
        # Nur das Manifest zu vergessen genuegt nicht: Die Chunk-Transkripte,
        # die Ollama-Teilanalysen und das fertige Protokoll werden ueber
        # ihren Dateinamen wiederverwendet. Ohne dieses Aufraeumen liefert
        # "Vollstaendig neu beginnen" das alte Protokoll zurueck, ohne das
        # Modell auch nur einmal zu fragen.
        manifest_service.verwerfe_zwischenstaende(work_dir)
        existing_manifest = None
        callbacks.on_log("Vollstaendiger Neubeginn -- vorhandene Zwischenstaende wurden verworfen.")

    callbacks.on_stage("audio_normalisierung", STAGE_LABELS["audio_normalisierung"])
    ffmpeg_service.ensure_ffmpeg_on_path()
    normalized_path = work_dir / "audio_normalisiert.wav"
    stage_start = time.monotonic()
    if not normalized_path.exists():
        ffmpeg_service.normalize_audio(settings.source_path, normalized_path)
    total_duration = ffmpeg_service.probe_duration_seconds(normalized_path)
    timings["audio_normalisierung"] = time.monotonic() - stage_start
    _check_cancel(callbacks)

    callbacks.on_stage("chunk_planung", STAGE_LABELS["chunk_planung"])
    chunk_plans = chunking_service.plan_chunks(total_duration)

    if existing_manifest is None:
        manifest = manifest_service.create_manifest(
            settings.source_path,
            file_hash,
            total_duration,
            chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS,
            chunking_service.DEFAULT_OVERLAP_SECONDS,
            len(chunk_plans),
            [
                {"index": plan.index, "global_start": plan.global_start, "global_end": plan.global_end}
                for plan in chunk_plans
            ],
            {
                "sprache": settings.language,
                "min_sprecher": settings.min_speakers,
                "max_sprecher": settings.max_speakers,
                "modell": settings.whisper_model,
                "sprechertrennung_aktiv": settings.enable_diarization,
            },
        )
        manifest_service.save_manifest(work_dir, manifest)
    else:
        manifest = existing_manifest

    resume_state = manifest_service.find_resumable_state(manifest)
    callbacks.on_log(
        f"{len(resume_state['fertige_chunks'])} von {len(chunk_plans)} Chunks bereits abgeschlossen."
    )

    callbacks.on_stage("modell_laden", STAGE_LABELS["modell_laden"])
    device, compute_type = model_service.get_device_and_compute_type(settings.device_preference)
    model_service.prepare_offline_mode(settings.allow_download)

    live_bis, live_segmente = _live_lesen(settings.vorab_live)
    if live_segmente:
        callbacks.on_log(
            f"Live transkribiert: {len(live_segmente)} Segmente bis {format_timestamp(live_bis)} (nur der Rest wird noch transkribiert)."
        )
    # Das Modell nur laden, wenn noch Audio zu transkribieren ist -- nach einer Live-Transkription kann das
    # ausnahmsweise keines mehr sein.
    chunks_offen = [
        plan
        for plan in chunk_plans
        if not _chunk_fertig(manifest, work_dir, plan) and _live_abdeckung(plan, live_bis) != _LIVE_VOLL
    ]

    whisper_model = None
    if transcribe_chunk_fn is None and chunks_offen:
        _grafikspeicher_fuer_whisper_freimachen(device, callbacks)
        whisper_model = transcription_service.load_whisper_model(
            settings.whisper_model, device, compute_type, settings.language
        )

        def transcribe_chunk_fn(chunk_wav_path: Path) -> list[dict[str, Any]]:  # noqa: F811
            audio_array = transcription_service.load_audio_array(chunk_wav_path)
            result = transcription_service.transcribe_audio_array(
                whisper_model, audio_array, settings.batch_size, settings.language
            )
            # Frueher lief hier zusaetzlich 'whisperx.align'. Der Schritt ist
            # mit dem Wegfall von WhisperX entfallen: faster-whisper liefert
            # die Wortzeitstempel selbst, und die dabei erzeugten Wortdaten
            # wurden im Projekt ohnehin nirgends gelesen.
            return transcription_service.segments_to_plain(result)

    callbacks.on_stage("transkription", STAGE_LABELS["transkription"])
    chunk_segment_lists: list[list[dict[str, Any]]] = []
    for plan in chunk_plans:
        _check_cancel(callbacks)
        callbacks.on_chunk_progress(plan.index + 1, len(chunk_plans))
        transcript_path = manifest_service.chunk_transcript_path(work_dir, plan.index)
        chunk_status = next(c for c in manifest["chunks"] if c["index"] == plan.index)

        if chunk_status["status"] == manifest_service.STATUS_ABGESCHLOSSEN and transcript_path.exists():
            chunk_segment_lists.append(json.loads(transcript_path.read_text(encoding="utf-8")))
            callbacks.on_overall_progress((plan.index + 1) / len(chunk_plans) * 0.5)
            continue

        abdeckung = _live_abdeckung(plan, live_bis)
        if abdeckung == _LIVE_VOLL:
            callbacks.on_log(f"Chunk {plan.index + 1}: schon waehrend der Aufnahme transkribiert.")
            live_lokal = _live_segmente_des_chunks(live_segmente, plan)
            transcript_path.write_text(json.dumps(live_lokal, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_service.update_chunk_status(manifest, plan.index, manifest_service.STATUS_ABGESCHLOSSEN)
            manifest_service.save_manifest(work_dir, manifest)
            chunk_segment_lists.append(live_lokal)
            callbacks.on_overall_progress((plan.index + 1) / len(chunk_plans) * 0.5)
            continue

        manifest_service.update_chunk_status(manifest, plan.index, manifest_service.STATUS_IN_BEARBEITUNG)
        manifest_service.save_manifest(work_dir, manifest)
        try:
            if transcribe_chunk_fn is None:
                # Nicht erreichbar: Ein Chunk ohne Transkript steht in 'chunks_offen', dann ist das Modell geladen.
                raise PipelineError("Es ist kein Transkribierer verfuegbar.")
            if abdeckung == _LIVE_TEIL:
                # Ein Teil des Chunks ist live transkribiert: nur den Rest ab dem sicheren Punkt rechnen.
                callbacks.on_log(
                    f"Chunk {plan.index + 1}: bis {format_timestamp(live_bis)} live transkribiert, "
                    f"Rest bis {format_timestamp(plan.global_end)} wird jetzt transkribiert."
                )
                rest_wav = manifest_service.chunk_audio_path(work_dir, plan.index).with_name(
                    f"chunk_{plan.index + 1:04d}_rest.wav"
                )
                ffmpeg_service.extract_chunk_wav(normalized_path, rest_wav, live_bis, plan.global_end)
                rest = transcribe_chunk_fn(rest_wav)
                live_teil = [
                    s
                    for s in _live_segmente_des_chunks(live_segmente, plan)
                    if float(s["start"]) + plan.global_start < live_bis
                ]
                rest_lokal = merge_service.to_global_segments(rest, live_bis - plan.global_start)
                local_segments = sorted(live_teil + rest_lokal, key=lambda s: float(s["start"]))
            else:
                chunk_wav = manifest_service.chunk_audio_path(work_dir, plan.index)
                if not chunk_wav.exists():
                    ffmpeg_service.extract_chunk_wav(
                        normalized_path, chunk_wav, plan.global_start, plan.global_end
                    )
                local_segments = transcribe_chunk_fn(chunk_wav)
            transcript_path.write_text(
                json.dumps(local_segments, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            manifest_service.update_chunk_status(manifest, plan.index, manifest_service.STATUS_ABGESCHLOSSEN)
            manifest_service.save_manifest(work_dir, manifest)
            chunk_segment_lists.append(local_segments)
        except PipelineCancelled:
            raise
        except Exception as error:
            manifest_service.update_chunk_status(
                manifest, plan.index, manifest_service.STATUS_FEHLGESCHLAGEN, str(error)
            )
            manifest_service.save_manifest(work_dir, manifest)
            raise PipelineError(
                f"Chunk {plan.index + 1} von {len(chunk_plans)} ist fehlgeschlagen: {error}"
            ) from error

        callbacks.on_overall_progress((plan.index + 1) / len(chunk_plans) * 0.5)

    callbacks.on_stage("diarisierung", STAGE_LABELS["diarisierung"])
    # Stimmabdruecke eines frueheren Laufs im selben Arbeitsordner duerfen nicht
    # stehen bleiben, wenn dieser Lauf keine liefert (API-Modus, ohne Sprechertrennung).
    sprecherprofil_service.speichere_lauf_embeddings(work_dir, {})
    if not settings.enable_diarization:
        callbacks.on_log(
            "Sprechertrennung deaktiviert -- Transkript wird ohne Sprecherzuordnung erstellt."
        )
        diarization_turns: list[dict[str, Any]] = []
    elif diarize_fn is None:
        # Whisper wird hier nicht mehr gebraucht: vom Grafikspeicher nehmen,
        # bevor pyannote rechnet (die Closure oben haelt sonst das Modell).
        whisper_model = None
        model_service.gpu_speicher_freigeben()
        diarization_turns, sprecher_embeddings = _sprechertrennung(normalized_path, settings, device, callbacks)
        # Fuer die dauerhaften Sprecherprofile; im Arbeitsordner, nicht in
        # der Ausgabe. Ein Lauf ohne Embeddings loescht den alten Stand.
        sprecherprofil_service.speichere_lauf_embeddings(work_dir, sprecher_embeddings)
    else:
        diarization_turns = diarize_fn(normalized_path, settings.min_speakers, settings.max_speakers)
    manifest["diarisierung_status"] = manifest_service.STATUS_ABGESCHLOSSEN
    manifest_service.save_manifest(work_dir, manifest)
    _check_cancel(callbacks)

    callbacks.on_stage("zusammenfuehrung", STAGE_LABELS["zusammenfuehrung"])
    merged_segments = merge_service.merge_chunk_transcripts(chunk_plans, chunk_segment_lists)
    merged_segments = speaker_merge_service.assign_speakers_by_words(merged_segments, diarization_turns)
    callbacks.on_preview(build_preview_text(merged_segments, settings.enable_diarization))

    callbacks.on_stage("export_transkript", STAGE_LABELS["export_transkript"])
    speaker_order = export_service.speaker_ids_in_order_of_appearance(merged_segments)
    speaker_names = export_service.build_speaker_names(speaker_order)
    run_timestamp = export_service.make_run_timestamp()
    created_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    device_desc = model_service.get_gpu_description()
    processing_duration = time.monotonic() - started_at
    export_paths = export_service.write_transcript_exports(
        settings.output_dir,
        settings.source_path.name,
        settings.source_path.stem,
        run_timestamp,
        created_iso,
        f"faster-whisper {settings.whisper_model}",
        settings.language or "automatisch erkannt",
        device_desc,
        processing_duration,
        merged_segments,
        speaker_names,
        settings.enable_diarization,
        diarization_turns,
        normalized_path,
    )
    manifest["protokoll_status"] = manifest_service.STATUS_AUSSTEHEND
    manifest_service.save_manifest(work_dir, manifest)
    _automatisches_word(callbacks, export_paths.json)

    return TranscriptionResult(
        work_dir=work_dir,
        export_paths=export_paths,
        speaker_names=speaker_names,
        segments=merged_segments,
        manifest=manifest,
        total_duration=total_duration,
        run_timestamp=run_timestamp,
        timings=timings,
    )


def run_transcription(
    settings: PipelineSettings,
    callbacks: PipelineCallbacks | None = None,
    transcribe_chunk_fn: Callable[[Path], list[dict[str, Any]]] | None = None,
    diarize_fn: Callable[[Path, int | None, int | None], list[dict[str, Any]]] | None = None,
) -> TranscriptionResult:
    """Eigenstaendiger erster Schritt: nur Transkription (+ optionale
    Diarisierung), ohne Ollama-Protokollauswertung.

    Das Ergebnis (TXT/JSON/SRT/VTT) kann direkt an 'run_protocol'
    weitergereicht werden, oder die Oberflaeche laesst den Anwender
    stattdessen ein anderes, frueher erzeugtes Transkript auswaehlen -
    (erst Transkription, dann getrennt
    eine - auch andere - Transkriptdatei zur Nachbearbeitung waehlen).
    """
    callbacks = callbacks or PipelineCallbacks()
    started_at = time.monotonic()
    result = _run_transcription_stage(settings, callbacks, transcribe_chunk_fn, diarize_fn)

    timings = {**result.timings, "gesamt": time.monotonic() - started_at}
    report = export_service.build_processing_report(
        result.manifest, {"whisperx": settings.whisper_model, "ollama": None}, timings
    )
    report_paths = export_service.write_processing_report(result.work_dir, report)

    callbacks.on_stage("abgeschlossen", STAGE_LABELS["abgeschlossen"])
    callbacks.on_overall_progress(1.0)

    return replace(result, report_paths=report_paths)


def load_transcript_for_protocol(
    transcript_json_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, str], bool, str]:
    """Liest ein von dieser Anwendung exportiertes Transkript-JSON wieder
    ein (siehe 'export_service.build_json_result').

    Liefert (segments, speaker_names, diarization_enabled, source_stem).
    'segments' bekommt dieselben Schluessel wie waehrend einer laufenden
    Transkription ('start'/'end' statt 'start_sekunden'/'ende_sekunden'),
    damit '_build_protocol_chunk_texts' unveraendert wiederverwendet
    werden kann.
    """
    try:
        daten = json.loads(transcript_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PipelineError(f"Transkript konnte nicht gelesen werden: {error}") from error

    rohsegmente = daten.get("segmente", [])
    if not rohsegmente:
        raise PipelineError(f"Transkript enthaelt keine Segmente: {transcript_json_path.name}")

    segments = [
        {
            "start": segment["start_sekunden"],
            "end": segment["ende_sekunden"],
            "sprecher_id": segment.get("sprecher_id"),
            "text": segment["text"],
        }
        for segment in rohsegmente
    ]
    speaker_names = {
        eintrag["sprecher_id"]: eintrag["anzeigename"] for eintrag in daten.get("sprecher_zuordnung", [])
    }
    diarization_enabled = bool(daten.get("sprechertrennung_aktiv", True))
    source_stem = str(daten.get("quelldatei_stamm") or transcript_json_path.stem)
    return segments, speaker_names, diarization_enabled, source_stem


def run_protocol(
    settings: ProtocolSettings,
    callbacks: PipelineCallbacks | None = None,
    protocol_generate_fn: Callable[[str, str], str] | None = None,
) -> ProtocolResult:
    """Eigenstaendiger zweiter Schritt: Ollama-Protokollauswertung eines
    bereits vorliegenden Transkripts (siehe 'load_transcript_for_protocol').

    Unabhaengig davon, ob das Transkript gerade eben ueber
    'run_transcription' entstanden ist oder ueber die Dateiauswahl ein
    frueherer Lauf geladen wurde: Der Zwischenspeicher-Ordner fuer die
    Ollama-Teilanalysen wird ueber den Hash der TRANSKRIPT-Datei selbst
    bestimmt (nicht der urspruenglichen Audiodatei) - das macht die
    Nachbearbeitung vollstaendig eigenstaendig fortsetzbar, auch wenn die
    Audiodatei gar nicht mehr vorliegt.
    """
    callbacks = callbacks or PipelineCallbacks()
    started_at = time.monotonic()

    callbacks.on_stage("transkript_laden", STAGE_LABELS["transkript_laden"])
    segments, speaker_names, diarization_enabled, source_stem = load_transcript_for_protocol(
        settings.transcript_json_path
    )
    _check_cancel(callbacks)

    from protokoll_assistent.utils.paths import get_work_dir

    file_hash = manifest_service.compute_file_hash(settings.transcript_json_path)
    work_dir = manifest_service.get_work_dir_for_file(get_work_dir(), file_hash)

    total_duration = max((segment["end"] for segment in segments), default=0.0)
    abschnitt = (
        chunking_service.auswertungs_abschnitt(settings.abschnitt_sekunden)
        if settings.abschnitt_sekunden is not None
        else chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS
    )
    # In die Kennung der Zwischenstaende geht die Laenge nur ein, wenn sie vom Standard abweicht (aeltere
    # Zwischenstaende bleiben so gueltig).
    abschnitt_kennung = None if abschnitt == chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS else abschnitt
    chunk_plans = chunking_service.plan_chunks(max(total_duration, 1.0), chunk_length=abschnitt)

    callbacks.on_stage("protokoll_auswertung", STAGE_LABELS["protokoll_auswertung"])
    from protokoll_assistent.utils.paths import get_system_prompt_file

    if settings.system_prompt is None:
        system_prompt = get_system_prompt_file().read_text(encoding="utf-8")
    else:
        system_prompt = settings.system_prompt
    chunk_texts = _build_protocol_chunk_texts(
        chunk_plans,
        segments,
        speaker_names,
        diarization_enabled and not settings.ohne_sprecher,
        fliesstext=settings.ohne_sprecher,
    )
    modell_kennung = settings.protokoll_modell_kennung or settings.ollama_model
    if settings.vorab_auswertung is not None:
        try:
            vorab = settings.vorab_auswertung()
            neu1, neu2 = protocol_service.vorab_ergebnisse_ablegen(
                vorab,
                chunk_texts,
                work_dir,
                system_prompt,
                settings.protocol_group_size,
                modell=modell_kennung,
                abschnitt_sekunden=abschnitt_kennung,
                ohne_sprecher=settings.ohne_sprecher,
            )
            if neu1 or neu2:
                callbacks.on_log(
                    f"Schon waehrend der Aufnahme ausgewertet: {neu1} Abschnitte und {neu2} Zusammenfuehrungen "
                    "werden uebernommen."
                )
        except Exception as fehler:  # Die Vorab-Auswertung ist eine Beschleunigung, nie Voraussetzung.
            callbacks.on_log(f"Vorab-Auswertung nicht verwendet: {fehler}")

    def default_ollama_generate(prompt: str, system: str) -> str:
        return ollama_service.generate_text(prompt, system, model=settings.ollama_model)

    generate_fn = protocol_generate_fn or default_ollama_generate

    protocol_paths = None
    protokoll_fehler: str | None = None
    run_timestamp = export_service.make_run_timestamp()
    try:
        protocol = protocol_service.run_full_protocol_pipeline(
            chunk_texts,
            work_dir,
            system_prompt,
            generate_fn,
            settings.protocol_group_size,
            progress_cb=lambda stage, current, total: callbacks.on_stage(
                "protokoll_auswertung",
                f"{STAGE_LABELS['protokoll_auswertung']} ({stage}: {current + 1}/{max(total, 1)})",
            ),
            modell=modell_kennung,
            abschnitt_sekunden=abschnitt_kennung,
            ohne_sprecher=settings.ohne_sprecher,
        )
        protokoll_status = manifest_service.STATUS_ABGESCHLOSSEN
        callbacks.on_stage("export_protokoll", STAGE_LABELS["export_protokoll"])
        protocol_paths = export_service.write_protocol_exports(
            settings.output_dir, protocol, source_stem, run_timestamp, system_prompt
        )
    except (protocol_service.ProtocolValidationError, ollama_service.OllamaError) as error:
        # Das Transkript bleibt in jedem Fall erhalten -- nur die
        # Protokollauswertung ist gescheitert.
        protokoll_fehler = str(error)
        protokoll_status = manifest_service.STATUS_FEHLGESCHLAGEN
        callbacks.on_stage(
            "protokoll_fehlgeschlagen",
            f"{STAGE_LABELS['protokoll_fehlgeschlagen']}: {protokoll_fehler}",
        )
        callbacks.on_log(f"Protokollauswertung fehlgeschlagen: {error}")

    timings = {"gesamt": time.monotonic() - started_at}
    report = export_service.build_processing_report(
        {
            "quelldatei_name": settings.transcript_json_path.name,
            "anzahl_chunks": len(chunk_plans),
            "chunks": [
                {"index": plan.index, "status": manifest_service.STATUS_ABGESCHLOSSEN, "fehler": None}
                for plan in chunk_plans
            ],
            "diarisierung_status": manifest_service.STATUS_ABGESCHLOSSEN if diarization_enabled else None,
            "protokoll_status": protokoll_status,
        },
        {"ollama": settings.ollama_model},
        timings,
    )
    report_paths = export_service.write_processing_report(work_dir, report)
    if protocol_paths is not None:
        _automatisches_word(callbacks, settings.transcript_json_path, protocol_paths[0])

    callbacks.on_stage("abgeschlossen", STAGE_LABELS["abgeschlossen"])
    callbacks.on_overall_progress(1.0)

    return ProtocolResult(
        work_dir=work_dir,
        protocol_paths=protocol_paths,
        report_paths=report_paths,
        protokoll_fehler=protokoll_fehler,
    )


def run_pipeline(
    settings: PipelineSettings,
    callbacks: PipelineCallbacks | None = None,
    transcribe_chunk_fn: Callable[[Path], list[dict[str, Any]]] | None = None,
    diarize_fn: Callable[[Path, int | None, int | None], list[dict[str, Any]]] | None = None,
    protocol_generate_fn: Callable[[str, str], str] | None = None,
) -> PipelineResult:
    """Kombinierter Einschritt-Ablauf: Transkription direkt gefolgt von der
    Protokollauswertung desselben Laufs, im selben Arbeitsordner. Bleibt
    fuer bestehende Aufrufer erhalten; die Oberflaeche nutzt seit der
    Trennung in zwei Schritte stattdessen 'run_transcription' und
    'run_protocol' einzeln (siehe deren Docstrings)."""
    callbacks = callbacks or PipelineCallbacks()
    started_at = time.monotonic()
    stage_result = _run_transcription_stage(settings, callbacks, transcribe_chunk_fn, diarize_fn)
    work_dir = stage_result.work_dir
    export_paths = stage_result.export_paths
    speaker_names = stage_result.speaker_names
    merged_segments = stage_result.segments
    manifest = stage_result.manifest
    chunk_plans = chunking_service.plan_chunks(stage_result.total_duration)
    run_timestamp = stage_result.run_timestamp

    protocol_paths = None
    protokoll_fehler: str | None = None
    if settings.run_protocol:
        callbacks.on_stage("protokoll_auswertung", STAGE_LABELS["protokoll_auswertung"])
        _check_cancel(callbacks)
        from protokoll_assistent.utils.paths import get_system_prompt_file

        system_prompt = get_system_prompt_file().read_text(encoding="utf-8")
        chunk_texts = _build_protocol_chunk_texts(
            chunk_plans, merged_segments, speaker_names, settings.enable_diarization
        )

        def default_ollama_generate(prompt: str, system: str) -> str:
            return ollama_service.generate_text(prompt, system, model=settings.ollama_model)

        generate_fn = protocol_generate_fn or default_ollama_generate
        try:
            protocol = protocol_service.run_full_protocol_pipeline(
                chunk_texts,
                work_dir,
                system_prompt,
                generate_fn,
                settings.protocol_group_size,
                progress_cb=lambda stage, current, total: callbacks.on_stage(
                    "protokoll_auswertung",
                    f"{STAGE_LABELS['protokoll_auswertung']} ({stage}: {current + 1}/{max(total, 1)})",
                ),
                # Der kombinierte Ablauf (Servermodus) rechnet nur mit Ollama.
                modell=settings.ollama_model,
            )
            manifest["protokoll_status"] = manifest_service.STATUS_ABGESCHLOSSEN
            callbacks.on_stage("export_protokoll", STAGE_LABELS["export_protokoll"])
            protocol_paths = export_service.write_protocol_exports(
                settings.output_dir, protocol, settings.source_path.stem, run_timestamp, system_prompt
            )
        except (protocol_service.ProtocolValidationError, ollama_service.OllamaError) as error:
            # Das Transkript ist fertig und bleibt erhalten -- nur die
            # Protokollauswertung ist gescheitert. Das muss die Oberflaeche
            # erfahren: 'on_log' landet dort lediglich in einem Tooltip, und
            # die Stufe "abgeschlossen" weiter unten wuerde den Fehlschlag
            # sonst als Erfolg darstellen.
            protokoll_fehler = str(error)
            manifest["protokoll_status"] = manifest_service.STATUS_FEHLGESCHLAGEN
            manifest_service.save_manifest(work_dir, manifest)
            callbacks.on_stage(
                "protokoll_fehlgeschlagen",
                f"{STAGE_LABELS['protokoll_fehlgeschlagen']}: {protokoll_fehler}",
            )
            callbacks.on_log(f"Protokollauswertung fehlgeschlagen: {error}")

    manifest_service.save_manifest(work_dir, manifest)

    timings = {**stage_result.timings, "gesamt": time.monotonic() - started_at}
    report = export_service.build_processing_report(
        manifest,
        {
            "whisperx": settings.whisper_model,
            "ollama": settings.ollama_model if settings.run_protocol else None,
        },
        timings,
    )
    report_paths = export_service.write_processing_report(work_dir, report)
    if protocol_paths is not None:
        _automatisches_word(callbacks, export_paths.json, protocol_paths[0])

    callbacks.on_stage("abgeschlossen", STAGE_LABELS["abgeschlossen"])
    callbacks.on_overall_progress(1.0)

    return PipelineResult(
        work_dir=work_dir,
        export_paths=export_paths,
        protocol_paths=protocol_paths,
        report_paths=report_paths,
        speaker_names=speaker_names,
        segments=merged_segments,
        manifest=manifest,
        protokoll_fehler=protokoll_fehler,
    )
