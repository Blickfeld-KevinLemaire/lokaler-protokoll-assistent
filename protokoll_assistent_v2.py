from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
INPUT_DIR = APP_DIR / "eingabe"
OUTPUT_DIR = APP_DIR / "ausgabe"
CHECKPOINT_DIR = APP_DIR / "zwischenstaende"
SETTINGS_DIR = APP_DIR / "einstellungen"
TERMS_FILE = SETTINGS_DIR / "fachbegriffe.txt"

OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
MODEL_NAME = "microsoft/mai-transcribe-2"
PROVIDER_NAME = "azure"
LANGUAGE = os.environ.get("PROTOKOLL_SPRACHE", "de").strip()
TRANSCRIBE_STYLE = "clean"
REQUEST_TIMEOUT_SECONDS = 900
MAX_DIRECT_AUDIO_SIZE = 36 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".mov",
    ".mkv",
    ".webm",
}

DIRECT_AUDIO_FORMATS = {
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".wav": "wav",
    ".aac": "aac",
    ".flac": "flac",
    ".ogg": "ogg",
    ".webm": "webm",
}


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def value_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def find_input_file() -> Path:
    files = sorted(
        path
        for path in INPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not files:
        extensions = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise FileNotFoundError(
            "Keine Audio- oder Videodatei im Ordner 'eingabe' gefunden.\n"
            f"Unterstuetzte Endungen: {extensions}"
        )

    if len(files) == 1:
        return files[0]

    print("Mehrere Eingabedateien gefunden:\n")
    for index, path in enumerate(files, start=1):
        print(f"  {index}: {path.name}")

    while True:
        answer = input("\nWelche Datei soll verarbeitet werden? Nummer eingeben: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(files):
            return files[int(answer) - 1]
        print("Bitte eine gueltige Nummer eingeben.")


def get_api_key() -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Die Umgebungsvariable OPENROUTER_API_KEY fehlt. "
            "Der API-Schluessel darf nicht in die Python-Datei geschrieben werden."
        )
    return api_key


def confirm_cloud_upload(source: Path) -> None:
    if os.environ.get("PROTOKOLL_UPLOAD_BESTAETIGT", "").strip() == "1":
        return

    print("\nDATENSCHUTZHINWEIS:")
    print("Die Aufnahme wird zur Transkription an OpenRouter und Microsoft Azure uebertragen.")
    print(f"Datei: {source.name}")
    answer = input("Uebertragung jetzt starten? [j/N]: ").strip().casefold()
    if answer not in {"j", "ja", "y", "yes"}:
        raise KeyboardInterrupt


def load_terms() -> list[str]:
    if not TERMS_FILE.exists():
        return []

    terms: list[str] = []
    seen: set[str] = set()
    for raw_line in TERMS_FILE.read_text(encoding="utf-8-sig").splitlines():
        term = raw_line.strip()
        if not term or term.startswith("#"):
            continue
        marker = term.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        terms.append(term)
    return terms[:1000]


def prepare_audio(source: Path, temporary_dir: Path) -> tuple[Path, str]:
    suffix = source.suffix.lower()
    if suffix == ".mp3" and source.stat().st_size <= MAX_DIRECT_AUDIO_SIZE:
        return source, "mp3"

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        reason = "Video" if suffix not in DIRECT_AUDIO_FORMATS else "grosse Audiodatei"
        raise RuntimeError(
            f"Fuer {reason} wird FFmpeg benoetigt, aber 'ffmpeg' wurde nicht gefunden."
        )

    converted = temporary_dir / f"{source.stem}_protokoll_audio.mp3"
    print("Audio wird fuer die Uebertragung vorbereitet ...")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "32k",
        str(converted),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not converted.exists():
        details = completed.stderr.strip()[-1000:]
        raise RuntimeError(f"FFmpeg konnte die Aufnahme nicht vorbereiten: {details}")
    return converted, "mp3"


def build_request(
    audio_path: Path,
    audio_format: str,
    terms: list[str],
) -> dict[str, Any]:
    audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")

    return {
        "model": MODEL_NAME,
        "input_audio": {
            "data": audio_base64,
            "format": audio_format,
        },
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
        "provider": {
            "options": {
                PROVIDER_NAME: {
                    "diarization": {
                        "enabled": True,
                    }
                }
            }
        },
    }


def call_openrouter(request_data: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(request_data, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "X-Title": "BLICKFELD Protokoll-Assistent",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"OpenRouter-Fehler HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"OpenRouter ist nicht erreichbar: {error}") from error
    except TimeoutError as error:
        raise RuntimeError(
            "Die Transkription hat das Zeitlimit ueberschritten. "
            "Die Aufnahme wurde nicht automatisch geteilt, damit die Sprecher-IDs stabil bleiben."
        ) from error

    if not isinstance(result, dict):
        raise RuntimeError("OpenRouter hat kein JSON-Objekt geliefert.")
    if result.get("error"):
        raise RuntimeError(f"OpenRouter meldet einen Fehler: {result['error']}")
    return result


def group_words_to_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for word_data in words:
        if not isinstance(word_data, dict):
            continue
        word = str(word_data.get("word", "")).strip()
        if not word:
            continue

        speaker = word_data.get("speaker")
        start = value_float(word_data.get("start"))
        end = value_float(word_data.get("end"), start)
        starts_new = (
            current is None
            or current.get("speaker") != speaker
            or start - value_float(current.get("end")) > 1.5
            or len(str(current.get("text", ""))) > 350
        )

        if starts_new:
            if current is not None:
                segments.append(current)
            current = {
                "start": start,
                "end": end,
                "text": word,
                "speaker": speaker,
            }
        else:
            separator = "" if word[:1] in ",.;:!?" else " "
            current["text"] = f"{current['text']}{separator}{word}"
            current["end"] = end

        if current and word.endswith((".", "!", "?")):
            segments.append(current)
            current = None

    if current is not None:
        segments.append(current)
    return segments


def raw_speaker_key(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "__unbekannt__"
    return str(value).strip()


def normalize_transcript(
    api_result: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    raw_segments = api_result.get("segments", [])
    raw_words = api_result.get("words", [])
    if not isinstance(raw_segments, list):
        raw_segments = []
    if not isinstance(raw_words, list):
        raw_words = []
    if not raw_segments and raw_words:
        raw_segments = group_words_to_segments(raw_words)
    if not raw_segments:
        text = str(api_result.get("text", "")).strip()
        if text:
            raw_segments = [{"start": 0.0, "end": api_result.get("duration", 0), "text": text}]

    speaker_names: dict[str, str] = {}

    def speaker_name(raw_value: Any) -> str:
        key = raw_speaker_key(raw_value)
        if key == "__unbekannt__":
            return "Sprecher unbekannt"
        if key not in speaker_names:
            speaker_names[key] = f"Sprecher {len(speaker_names) + 1}"
        return speaker_names[key]

    normalized_segments: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        content = str(raw_segment.get("text", "")).strip()
        if not content:
            continue
        start = value_float(raw_segment.get("start"))
        end = value_float(raw_segment.get("end"), start)
        raw_speaker = raw_segment.get("speaker")
        label = speaker_name(raw_speaker)
        normalized_segments.append(
            {
                "nummer": len(normalized_segments) + 1,
                "start_sekunden": round(start, 3),
                "ende_sekunden": round(end, 3),
                "start": format_timestamp(start),
                "ende": format_timestamp(end),
                "sprecher_id": None if raw_speaker is None else str(raw_speaker),
                "sprecher": label,
                "inhalt": content,
                # Bestehende Auswertungsversionen lesen das Feld "text".
                # Deshalb steht die Sprecherangabe bewusst direkt darin.
                "text": f"{label}: {content}",
            }
        )

    normalized_words: list[dict[str, Any]] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        word = str(raw_word.get("word", "")).strip()
        if not word:
            continue
        raw_speaker = raw_word.get("speaker")
        start = value_float(raw_word.get("start"))
        end = value_float(raw_word.get("end"), start)
        normalized_words.append(
            {
                "wort": word,
                "start_sekunden": round(start, 3),
                "ende_sekunden": round(end, 3),
                "sprecher_id": None if raw_speaker is None else str(raw_speaker),
                "sprecher": speaker_name(raw_speaker),
            }
        )

    speakers = [
        {"sprecher_id": key, "bezeichnung": name}
        for key, name in speaker_names.items()
    ]
    return normalized_segments, normalized_words, speakers


def save_transcript(source: Path, api_result: dict[str, Any]) -> tuple[Path, Path]:
    # Die neue Cloud-Transkription ueberschreibt niemals ein vorhandenes
    # Whisper-Transkript. Der Suffix bleibt mit der bestehenden Auswertung kompatibel.
    output_txt = OUTPUT_DIR / f"{source.stem}_mai2_transkript.txt"
    output_json = OUTPUT_DIR / f"{source.stem}_mai2_transkript.json"
    segments, words, speakers = normalize_transcript(api_result)
    if not segments:
        raise RuntimeError("Die Datei wurde verarbeitet, aber es wurde keine Sprache erkannt.")
    if not speakers:
        print(
            "WARNUNG: Das Modell hat keine Sprecher-IDs geliefert. "
            "Das Transkript wird gespeichert, aber die Sprechertrennung muss geprueft werden."
        )

    duration = value_float(api_result.get("duration"))
    if not duration:
        duration = max(value_float(segment.get("ende_sekunden")) for segment in segments)
    language = str(api_result.get("language", LANGUAGE or "automatisch erkannt"))
    usage = api_result.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    transcript_lines = [
        f"[{segment['start']} --> {segment['ende']}] {segment['text']}"
        for segment in segments
    ]
    header = [
        "PROTOKOLL-ASSISTENT - VOLLTRANSKRIPT MIT SPRECHERTRENNUNG",
        f"Quelldatei: {source.name}",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Transkriptionsmodell: {MODEL_NAME}",
        f"Erkannte Sprache: {language}",
        f"Erkannte Sprecher: {len(speakers)}",
        "Hinweis: Sprecherbezeichnungen sind technische IDs und keine echten Namen.",
        "",
    ]
    output_txt.write_text("\n".join(header + transcript_lines) + "\n", encoding="utf-8")

    result = {
        "quelldatei": source.name,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "modell": MODEL_NAME,
        "anbieter": "OpenRouter / Microsoft Azure",
        "transkriptionsstil": "standard",
        "sprache": language,
        "dauer_sekunden": round(duration, 3),
        "anzahl_sprecher": len(speakers),
        "sprecher": speakers,
        "anzahl_segmente": len(segments),
        "segmente": segments,
        "woerter": words,
        "nutzung": usage,
    }
    output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_txt, output_json


def transcribe(source: Path) -> tuple[Path, Path]:
    api_key = get_api_key()
    confirm_cloud_upload(source)
    terms = load_terms()
    checkpoint = CHECKPOINT_DIR / f"{source.stem}_mai_transcribe_2_rohantwort.json"

    print(f"\nEingabedatei: {source.name}")
    print(f"Modell: {MODEL_NAME}")
    print("Sprechertrennung: aktiviert")
    print("Fachbegriffe: fuer stabilen Betrieb voruebergehend deaktiviert")

    if checkpoint.exists():
        print("Vorhandene Modellantwort wird weiterverarbeitet; kein neuer API-Aufruf.")
        api_result = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
    else:
        with tempfile.TemporaryDirectory(prefix="protokoll_audio_") as temp_name:
            audio_path, audio_format = prepare_audio(source, Path(temp_name))
            request_data = build_request(audio_path, audio_format, terms)
            print("Cloud-Transkription gestartet ...")
            api_result = call_openrouter(request_data, api_key)
        checkpoint.write_text(
            json.dumps(api_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    output_txt, output_json = save_transcript(source, api_result)
    checkpoint.unlink(missing_ok=True)
    return output_txt, output_json


def main() -> int:
    print("=" * 72)
    print("PROTOKOLL-ASSISTENT V2 - MAI-TRANSCRIBE-2 MIT SPRECHERTRENNUNG")
    print("=" * 72)

    for directory in (INPUT_DIR, OUTPUT_DIR, CHECKPOINT_DIR, SETTINGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    try:
        source = find_input_file()
        output_txt, output_json = transcribe(source)
    except KeyboardInterrupt:
        print("\nAbbruch durch Benutzer. Es wurde keine neue Uebertragung gestartet.")
        return 130
    except Exception as error:
        print(f"\nFEHLER: {error}")
        print("Eine vorhandene Rohantwort bleibt im Ordner 'zwischenstaende'.")
        return 1

    print("\nTranskription erfolgreich abgeschlossen.")
    print(f"Textdatei: {output_txt}")
    print(f"JSON-Datei: {output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
