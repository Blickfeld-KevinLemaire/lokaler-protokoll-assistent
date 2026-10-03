"""Transkription ueber eine externe API-Schnittstelle (z. B. OpenRouter),
als Ersatz fuer eine lokale Whisper-Installation.

Das Anfrage-/Antwortformat ist wortgleich mit dem, das die bisherige
Schnittstellen-Anwendung ('protokoll_assistent_gui.py'/'protokoll_assistent_v2.py')
bereits benutzt und geprueft hat: JSON mit Base64-kodiertem Audio,
'response_format: verbose_json', Sprechertrennung ueber ein
'provider.options.<anbieter>.diarization.enabled'-Feld im selben Request.

Neu ist nur die Verpackung: 'transcribe_chunk_via_api' erfuellt exakt die
Form 'transcribe_chunk_fn: Callable[[Path], list[dict]]', die
'services.pipeline_service' bereits fuer die
lokale Transkription verwendet -- die komplette Chunk-Planung,
Fortsetzbarkeit, Zusammenfuehrung und der Export bleiben dadurch
unveraendert dieselben, unabhaengig davon, ob ein Chunk lokal oder ueber
diese API transkribiert wurde.

Sprechertrennung im API-Modus laeuft NICHT ueber den separaten
'diarize_fn'-Mechanismus (der fuer eine EIGENSTAENDIGE, globale Diarisierung
auf dem Gesamtaudio gedacht ist, wie pyannote sie lokal macht) - die
Sprecherzuordnung kommt hier bereits pro Segment vom selben Request wie die
Transkription. 'diarize_via_api_speakers' baut daraus nachtraeglich
synthetische 'turns' im von 'speaker_merge_service.assign_speakers_by_overlap'
erwarteten Format: eine turn je Segment mit IDENTISCHEM Zeitfenster, wodurch
die Ueberlappungs-Zuordnung trivial korrekt ist (die groesstmoegliche
Ueberlappung ist die volle eigene Dauer des Segments). Dazu werden die
bereits geschriebenen Chunk-Transkript-Dateien im Arbeitsordner erneut
gelesen -- robust auch bei einer fortgesetzten Verarbeitung, bei der
'transcribe_chunk_fn' fuer laengst fertige Chunks gar nicht mehr aufgerufen
wird, die Datei aber trotzdem vorliegt.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from protokoll_assistent.services import api_anbieter

MAX_DIRECT_AUDIO_SIZE = 36 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 900.0


class ApiTranscriptionError(RuntimeError):
    pass


def pruefe_uebertragungsgroesse(audio_path: Path) -> None:
    """Bricht klar ab, statt eine zu grosse Anfrage erst nach minutenlangem
    Hochladen mit einer nichtssagenden HTTP-Meldung scheitern zu lassen."""
    groesse = audio_path.stat().st_size
    if groesse <= MAX_DIRECT_AUDIO_SIZE:
        return
    raise ApiTranscriptionError(
        f"Der Chunk '{audio_path.name}' ist mit {groesse / 1024 / 1024:.0f} MB zu gross "
        f"fuer eine einzelne Uebertragung (Grenze: {MAX_DIRECT_AUDIO_SIZE / 1024 / 1024:.0f} MB). "
        # Bewusst KEIN Verweis auf "die Einstellungen": Die Chunk-Laenge
        # steht in 'services.chunking_service' und ist in dieser Anwendung
        # nicht einstellbar.
        "Das sollte bei der festen Chunk-Laenge nicht vorkommen -- bitte die "
        "Aufnahme pruefen und den Fehler melden."
    )


def build_request(
    audio_bytes: bytes,
    audio_format: str,
    model_name: str,
    provider_name: str,
    diarization_enabled: bool,
) -> dict[str, Any]:
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    request_data: dict[str, Any] = {
        "model": model_name,
        "input_audio": {"data": audio_base64, "format": audio_format},
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
    }
    if diarization_enabled and provider_name.strip():
        request_data["provider"] = {
            "options": {provider_name.strip(): {"diarization": {"enabled": True}}}
        }
    return request_data


def call_endpoint(
    request_data: dict[str, Any],
    endpoint_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body = json.dumps(request_data, ensure_ascii=False).encode("utf-8")
    return _senden(body, "application/json; charset=utf-8", endpoint_url, api_key, timeout)


def build_multipart(
    felder: list[tuple[str, str]],
    datei_feld: str,
    dateiname: str,
    inhalt: bytes,
    mime: str,
) -> tuple[bytes, str]:
    """Baut einen multipart/form-data-Koerper (ohne zusaetzliche Pakete).

    Rueckgabe: Koerper und Wert fuer den ``Content-Type``-Kopf. Felder sind
    Paare, damit ein Feldname mehrfach vorkommen kann."""
    grenze = f"----ProtokollAssistent{uuid.uuid4().hex}"
    teile: list[bytes] = []
    for name, wert in felder:
        teile.append(
            f'--{grenze}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{wert}\r\n'.encode()
        )
    teile.append(
        (
            f'--{grenze}\r\nContent-Disposition: form-data; name="{datei_feld}"; '
            f'filename="{dateiname}"\r\nContent-Type: {mime}\r\n\r\n'
        ).encode()
    )
    teile.append(inhalt)
    teile.append(f"\r\n--{grenze}--\r\n".encode())
    return b"".join(teile), f"multipart/form-data; boundary={grenze}"


def build_multipart_fields(
    model_name: str,
    diarisierung: str,
    diarization_enabled: bool,
) -> list[tuple[str, str]]:
    """Formularfelder je nach Anbieter.

    * OpenAI-Schnittstelle (OpenAI, Azure, Groq, Scaleway): ``verbose_json``
      mit Segment-Zeitstempeln. Ein Modell mit "diarize" im Namen
      (``gpt-4o-transcribe-diarize``) liefert stattdessen ``diarized_json``
      mit Sprechern und braucht ``chunking_strategy``.
    * Mistral (Voxtral): kennt kein ``response_format``, dafuer ``diarize``.
    """
    felder: list[tuple[str, str]] = [("model", model_name)]
    if diarisierung == api_anbieter.DIARISIERUNG_MISTRAL:
        felder.append(("timestamp_granularities", "segment"))
        if diarization_enabled:
            felder.append(("diarize", "true"))
        return felder
    if "diarize" in model_name.lower():
        felder.append(("response_format", "diarized_json"))
        felder.append(("chunking_strategy", "auto"))
        return felder
    felder.append(("response_format", "verbose_json"))
    felder.append(("timestamp_granularities[]", "segment"))
    return felder


def call_endpoint_multipart(
    felder: list[tuple[str, str]],
    audio_path: Path,
    endpoint_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body, content_type = build_multipart(felder, "file", audio_path.name, audio_path.read_bytes(), "audio/wav")
    return _senden(body, content_type, endpoint_url, api_key, timeout)


def _senden(
    body: bytes,
    content_type: str,
    endpoint_url: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint_url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1500]
        raise ApiTranscriptionError(f"Transkriptions-Endpunkt-Fehler HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise ApiTranscriptionError(
            f"Transkriptions-Endpunkt ist nicht erreichbar ({endpoint_url}): {error}"
        ) from error
    except TimeoutError as error:
        raise ApiTranscriptionError("Die Transkription hat das Zeitlimit ueberschritten.") from error
    except ValueError as error:
        raise ApiTranscriptionError(f"{endpoint_url} hat keine gueltige JSON-Antwort geliefert.") from error

    if not isinstance(result, dict):
        raise ApiTranscriptionError(f"{endpoint_url} hat kein JSON-Objekt geliefert.")
    if result.get("error"):
        raise ApiTranscriptionError(f"Der Endpunkt meldet einen Fehler: {result['error']}")
    return result


def _value_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def group_words_to_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Baut Segmente aus Einzelwoertern, falls der Endpunkt nur 'words'
    statt 'segments' liefert (identische Heuristik wie in der bisherigen
    Schnittstellen-Anwendung: neues Segment bei Sprecherwechsel, > 1.5s
    Pause oder > 350 Zeichen; Satzende schliesst ein Segment ab)."""
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for word_data in words:
        if not isinstance(word_data, dict):
            continue
        word = str(word_data.get("word", "")).strip()
        if not word:
            continue

        speaker = word_data.get("speaker")
        start = _value_float(word_data.get("start"))
        end = _value_float(word_data.get("end"), start)
        starts_new = (
            current is None
            or current.get("speaker") != speaker
            or start - _value_float(current.get("end")) > 1.5
            or len(str(current.get("text", ""))) > 350
        )

        if starts_new:
            if current is not None:
                segments.append(current)
            current = {"start": start, "end": end, "text": word, "speaker": speaker}
        else:
            assert current is not None  # noqa: S101 - nur Typ-Einengung, 'starts_new' garantiert das
            separator = "" if word[:1] in ",.;:!?" else " "
            current["text"] = f"{current['text']}{separator}{word}"
            current["end"] = end

        if current and word.endswith((".", "!", "?")):
            segments.append(current)
            current = None

    if current is not None:
        segments.append(current)
    return segments


def normalize_segments(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Bringt die Endpunkt-Antwort in dieselbe einfache Segmentform, die
    'transcription_service.segments_to_plain()' auch fuer die lokale
    Transkription liefert: {'start','end','text','speaker','words'}
    (chunk-relative Zeiten -- die globale Zeitumrechnung uebernimmt wie
    beim lokalen Pfad 'merge_service')."""
    raw_segments = response.get("segments", [])
    raw_words = response.get("words", [])
    if not isinstance(raw_segments, list):
        raw_segments = []
    if not isinstance(raw_words, list):
        raw_words = []
    if not raw_segments and raw_words:
        raw_segments = group_words_to_segments(raw_words)

    plain: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        text = str(raw_segment.get("text", "")).strip()
        if not text:
            continue
        start = _value_float(raw_segment.get("start"))
        end = _value_float(raw_segment.get("end"), start)
        plain.append(
            {
                "start": start,
                "end": end,
                "text": text,
                # 'speaker' (OpenRouter, OpenAI), 'speaker_id' (Mistral)
                "speaker": raw_segment.get("speaker") or raw_segment.get("speaker_id"),
                "words": [],
            }
        )
    return plain


def transcribe_chunk_via_api(
    chunk_wav_path: Path,
    *,
    endpoint_url: str,
    api_key: str,
    model_name: str,
    provider_name: str,
    diarization_enabled: bool,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Erfuellt exakt 'transcribe_chunk_fn: Callable[[Path], list[dict]]' -
    ein Drop-in-Ersatz fuer die lokale Whisper-Transkription eines Chunks.

    Das Uebertragungsformat ergibt sich aus der Adresse
    (``api_anbieter.transkription_format_fuer``): OpenRouter und alle
    eigenen/bekannten Altadressen bekommen JSON mit Base64-Audio wie bisher,
    die uebrigen Anbieter einen Dateiupload per multipart/form-data."""
    pruefe_uebertragungsgroesse(chunk_wav_path)
    if api_anbieter.transkription_format_fuer(endpoint_url) == api_anbieter.FORMAT_MULTIPART:
        felder = build_multipart_fields(
            model_name, api_anbieter.diarisierung_fuer(endpoint_url), diarization_enabled
        )
        response = call_endpoint_multipart(felder, chunk_wav_path, endpoint_url, api_key, timeout=timeout)
    else:
        request_data = build_request(
            chunk_wav_path.read_bytes(),
            audio_format="wav",
            model_name=model_name,
            provider_name=provider_name,
            diarization_enabled=diarization_enabled,
        )
        response = call_endpoint(request_data, endpoint_url, api_key, timeout=timeout)
    segmente = normalize_segments(response)
    if not segmente and str(response.get("text", "")).strip():
        # Nur Fliesstext, keine Zeitstempel (z. B. gpt-4o-transcribe ohne
        # Segmente): Daraus laesst sich weder ein Protokoll mit Zeiten noch
        # eine Sprecherzuordnung bauen -- lieber klar abbrechen.
        raise ApiTranscriptionError(
            f"Das Modell '{model_name}' liefert nur Fliesstext ohne Zeitstempel. "
            "Bitte in den Einstellungen ein Modell mit Segment-Zeitstempeln waehlen "
            "(z. B. 'whisper-1', 'gpt-4o-transcribe-diarize' oder 'voxtral-mini-latest')."
        )
    return segmente


def diarize_via_api_speakers(
    normalized_path: Path,
    min_speakers: int | None,
    max_speakers: int | None,
) -> list[dict[str, Any]]:
    """Ersatz fuer 'diarize_fn' im API-Modus: es findet keine eigene,
    globale Diarisierung statt (der Provider liefert Sprecher bereits je
    Segment zusammen mit der Transkription, siehe 'transcribe_chunk_via_api').

    Liest die bereits geschriebenen Chunk-Transkripte aus dem Arbeitsordner
    (aus 'normalized_path.parent' ableitbar, siehe
    'services.pipeline_service._run_transcription_stage') erneut ein und
    baut daraus synthetische Diarisierungs-'turns': eine turn je Segment
    mit identischem, auf globale Zeit umgerechnetem Zeitfenster. Das macht
    'assign_speakers_by_overlap' anschliessend zu einer reinen
    Durchreichung des vom Provider gelieferten Sprechers - und funktioniert
    auch bei fortgesetzter Verarbeitung, wo fuer bereits fertige Chunks gar
    kein neuer API-Aufruf mehr stattfindet."""
    # Spaeter Import: erst wenn diese Funktion tatsaechlich als
    # 'diarize_fn' aufgerufen wird.
    from protokoll_assistent.services import manifest_service

    work_dir = normalized_path.parent
    manifest = manifest_service.load_manifest(work_dir)
    if manifest is None:
        return []

    turns: list[dict[str, Any]] = []
    for chunk in manifest["chunks"]:
        transcript_path = manifest_service.chunk_transcript_path(work_dir, chunk["index"])
        if not transcript_path.is_file():
            continue
        local_segments = json.loads(transcript_path.read_text(encoding="utf-8"))
        offset = chunk["global_start"]
        for segment in local_segments:
            speaker = segment.get("speaker")
            if not speaker:
                continue
            turns.append(
                {
                    "start": segment["start"] + offset,
                    "end": segment["end"] + offset,
                    "speaker": speaker,
                }
            )
    return turns
