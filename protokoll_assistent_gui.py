"""Grafische Oberflaeche fuer den Protokoll-Assistenten.

Nutzt die bestehende Konsolen-Logik aus protokoll_assistent_v2.py als
Bibliothek (diese Datei bleibt unveraendert und weiterhin eigenstaendig
lauffaehig). Ergaenzt wird eine zweite Stufe: ein lokales KI-Modell
(z. B. ueber Ollama) verarbeitet das fertige Transkript gemaess einem
frei formulierbaren Systemprompt (Zusammenfassung, Agenda, Prioritaeten
usw.), ohne dass dafuer weitere Daten das Geraet verlassen.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protokoll_assistent_v2 as kern  # Konsolenversion wird als Bibliothek wiederverwendet
import oberflaeche_theme as theme

APP_DIR = kern.APP_DIR
INPUT_DIR = kern.INPUT_DIR
OUTPUT_DIR = kern.OUTPUT_DIR
CHECKPOINT_DIR = kern.CHECKPOINT_DIR
SETTINGS_DIR = kern.SETTINGS_DIR
ERGEBNIS_DIR = APP_DIR / "Ergebnis des Meetings wie gewünscht"

LOCAL_MODEL_URL = os.environ.get(
    "PROTOKOLL_LOKALES_MODELL_URL", "http://localhost:11434/api/generate"
)
DEFAULT_LOCAL_MODEL = os.environ.get("PROTOKOLL_LOKALES_MODELL", "llama3.1")
LOCAL_MODEL_TIMEOUT_SECONDS = 1800

OPENROUTER_CHAT_URL = os.environ.get(
    "PROTOKOLL_API_ENDPUNKT", "https://openrouter.ai/api/v1/chat/completions"
)
DEFAULT_API_MODEL = os.environ.get("PROTOKOLL_API_MODELL", "openai/gpt-4o-mini")
API_MODEL_TIMEOUT_SECONDS = 600

DEFAULT_TRANSKRIPTION_ENDPUNKT = os.environ.get(
    "PROTOKOLL_TRANSKRIPTION_ENDPUNKT", kern.OPENROUTER_URL
)
DEFAULT_TRANSKRIPTION_MODELL = os.environ.get("PROTOKOLL_TRANSKRIPTION_MODELL", kern.MODEL_NAME)
DEFAULT_TRANSKRIPTION_ANBIETER = os.environ.get(
    "PROTOKOLL_TRANSKRIPTION_ANBIETER", kern.PROVIDER_NAME
)

DEFAULT_SYSTEMPROMPT = (
    "Fasse das folgende Besprechungstranskript in klarer, gut strukturierter "
    "Form zusammen. Nenne die wichtigsten Themen, getroffene Entscheidungen "
    "und offene Aufgaben mit Verantwortlichen, falls erkennbar."
)

SYSTEMPROMPT_VORLAGEN = {
    "Zusammenfassung": DEFAULT_SYSTEMPROMPT,
    "Agenda": (
        "Erstelle aus dem folgenden Besprechungstranskript eine strukturierte "
        "Agenda im Nachhinein: Liste die behandelten Themen in der besprochenen "
        "Reihenfolge auf, mit je 1-2 Saetzen Inhalt."
    ),
    "Prioritaetenliste": (
        "Erstelle aus dem folgenden Besprechungstranskript eine priorisierte "
        "Aufgabenliste. Sortiere nach Dringlichkeit, nenne wenn moeglich "
        "Verantwortliche und Termine."
    ),
}

CHUNK_SCHWELLE_MINUTEN = int(os.environ.get("PROTOKOLL_CHUNK_SCHWELLE_MINUTEN", "40"))
CHUNK_LAENGE_MINUTEN = int(os.environ.get("PROTOKOLL_CHUNK_LAENGE_MINUTEN", "15"))
CHUNK_SCHWELLE_SEKUNDEN = CHUNK_SCHWELLE_MINUTEN * 60
CHUNK_LAENGE_SEKUNDEN = CHUNK_LAENGE_MINUTEN * 60

SPRECHER_FENSTER_MINUTEN = int(os.environ.get("PROTOKOLL_SPRECHER_FENSTER_MINUTEN", "3"))
SPRECHER_FENSTER_SEKUNDEN = SPRECHER_FENSTER_MINUTEN * 60

SELBSTVORSTELLUNG_MUSTER = [
    # Die Schluesselwoerter sind gross-/kleinschreibungsunabhaengig ("(?i:...)"),
    # der eigentliche Name muss aber gross geschrieben sein - das schuetzt vor
    # Fehltreffern wie "ich bin noch dazugekommen" -> "Noch".
    re.compile(r"(?i:ich\s+(?:bin|hei(?:ß|ss)e))\s+(?i:der|die|das)?\s*([A-ZÄÖÜ][\wäöüß-]+)"),
    re.compile(r"(?i:mein\s+name\s+ist)\s+([A-ZÄÖÜ][\wäöüß-]+)"),
    re.compile(r"(?i:hier\s+(?:ist|spricht))\s+([A-ZÄÖÜ][\wäöüß-]+)"),
]

FFMPEG_SUCHPFADE = [
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/snap/bin/ffmpeg",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
]


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path
    for candidate in FFMPEG_SUCHPFADE:
        if Path(candidate).is_file():
            return candidate
    return None


def ensure_ffmpeg_on_path() -> str | None:
    """Findet FFmpeg auch ausserhalb von PATH, ohne protokoll_assistent_v2.py zu aendern."""
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path and not shutil.which("ffmpeg"):
        ffmpeg_dir = str(Path(ffmpeg_path).resolve().parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg_path


def get_audio_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    ergebnis = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if ergebnis.returncode != 0:
        return None
    try:
        return float(ergebnis.stdout.strip())
    except ValueError:
        return None


def split_audio_into_chunks(
    audio_path: Path, work_dir: Path, chunk_seconds: int, log: Callable[[str], None]
) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg wird zum Aufteilen langer Aufnahmen benoetigt.")

    muster = work_dir / "abschnitt_%04d.mp3"
    befehl = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-reset_timestamps", "1",
        "-c", "copy",
        str(muster),
    ]
    log(f"Teile Aufnahme in Abschnitte von je {chunk_seconds // 60} Minuten ...")
    ergebnis = subprocess.run(
        befehl, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if ergebnis.returncode != 0:
        details = ergebnis.stderr.strip()[-800:]
        raise RuntimeError(f"FFmpeg konnte die Aufnahme nicht aufteilen: {details}")

    chunks = sorted(work_dir.glob("abschnitt_*.mp3"))
    if not chunks:
        raise RuntimeError("Das Aufteilen der Aufnahme ergab keine Abschnitte.")
    return chunks


def build_transcription_request(
    audio_path: Path,
    audio_format: str,
    model_name: str,
    provider_name: str,
    diarisierung_aktiv: bool = True,
) -> dict[str, Any]:
    """Wie kern.build_request, aber mit frei waehlbarem Modell und Anbieter
    statt der fest einprogrammierten Konsolen-Konstanten.

    Das Format (JSON mit Base64-Audio, optionales 'provider.options.<name>.
    diarization'-Feld) entspricht dem OpenRouter-Schema. Es funktioniert mit
    jedem Endpunkt, der dieses Format ebenfalls versteht - z. B. auch bei
    direkter Anbindung an Microsoft Azure oder einen anderen Anbieter, der
    dieselbe Anfragestruktur akzeptiert.

    Ist ``diarisierung_aktiv`` False, wird das Provider-/Diarisierungsfeld
    unabhaengig vom eingetragenen Anbieter weggelassen - das Ergebnis enthaelt
    dann keine Sprecherzuordnung, z. B. wenn nur der Inhalt zaehlen soll und
    die Aussagen anonym bleiben sollen."""
    audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    request_data: dict[str, Any] = {
        "model": model_name,
        "input_audio": {"data": audio_base64, "format": audio_format},
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
    }
    if diarisierung_aktiv and provider_name.strip():
        request_data["provider"] = {
            "options": {provider_name.strip(): {"diarization": {"enabled": True}}}
        }
    return request_data


def call_transcription_endpoint(
    endpoint_url: str, request_data: dict[str, Any], api_key: str
) -> dict[str, Any]:
    body = json.dumps(request_data, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=kern.REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"Transkriptions-Endpunkt-Fehler HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Transkriptions-Endpunkt ist nicht erreichbar ({endpoint_url}): {error}"
        ) from error
    except TimeoutError as error:
        raise RuntimeError("Die Transkription hat das Zeitlimit ueberschritten.") from error

    if not isinstance(result, dict):
        raise RuntimeError(f"{endpoint_url} hat kein JSON-Objekt geliefert.")
    if result.get("error"):
        raise RuntimeError(f"Der Endpunkt meldet einen Fehler: {result['error']}")
    return result


def save_transcript(
    source: Path,
    api_result: dict[str, Any],
    model_name: str,
    endpoint_url: str,
    diarisierung_aktiv: bool = True,
) -> tuple[Path, Path]:
    """Wie kern.save_transcript, aber mit dem tatsaechlich verwendeten
    Modell/Endpunkt statt der fest einprogrammierten Konsolen-Konstante.

    Ist ``diarisierung_aktiv`` False, enthaelt das Transkript bewusst keine
    Sprecherzuordnung (anonymes Ergebnis - nur der Inhalt zaehlt)."""
    output_txt = OUTPUT_DIR / f"{source.stem}_mai2_transkript.txt"
    output_json = OUTPUT_DIR / f"{source.stem}_mai2_transkript.json"
    segments, words, speakers = kern.normalize_transcript(api_result)
    if not segments:
        raise RuntimeError("Die Datei wurde verarbeitet, aber es wurde keine Sprache erkannt.")

    duration = kern.value_float(api_result.get("duration"))
    if not duration:
        duration = max(kern.value_float(segment.get("ende_sekunden")) for segment in segments)
    language = str(api_result.get("language", kern.LANGUAGE or "automatisch erkannt"))
    usage = api_result.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    if diarisierung_aktiv:
        transcript_lines = [
            f"[{segment['start']} --> {segment['ende']}] {segment['text']}" for segment in segments
        ]
        titel = "PROTOKOLL-ASSISTENT - VOLLTRANSKRIPT MIT SPRECHERTRENNUNG"
        sprecher_zeile = f"Erkannte Sprecher: {len(speakers)}"
        hinweis_zeile = "Hinweis: Sprecherbezeichnungen sind technische IDs und keine echten Namen."
    else:
        transcript_lines = [
            f"[{segment['start']} --> {segment['ende']}] {segment['inhalt']}" for segment in segments
        ]
        titel = "PROTOKOLL-ASSISTENT - VOLLTRANSKRIPT (ANONYM, OHNE SPRECHERTRENNUNG)"
        sprecher_zeile = "Sprechertrennung: deaktiviert - kein Sprecherbezug enthalten."
        hinweis_zeile = (
            "Hinweis: Auf Wunsch wurde keine Sprecherzuordnung angefragt - nur der "
            "Inhalt wurde erfasst."
        )

    header = [
        titel,
        f"Quelldatei: {source.name}",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Transkriptionsmodell: {model_name}",
        f"Endpunkt: {endpoint_url}",
        f"Erkannte Sprache: {language}",
        sprecher_zeile,
        hinweis_zeile,
        "",
    ]
    output_txt.write_text("\n".join(header + transcript_lines) + "\n", encoding="utf-8")

    result = {
        "quelldatei": source.name,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "modell": model_name,
        "endpunkt": endpoint_url,
        "sprache": language,
        "dauer_sekunden": round(duration, 3),
        "sprechertrennung_aktiv": diarisierung_aktiv,
        "anzahl_sprecher": len(speakers) if diarisierung_aktiv else 0,
        "sprecher": speakers if diarisierung_aktiv else [],
        "anzahl_segmente": len(segments),
        "segmente": segments,
        "woerter": words,
        "nutzung": usage,
    }
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_txt, output_json


def transcribe_in_chunks(
    source: Path,
    api_key: str,
    chunk_seconds: int,
    endpoint_url: str,
    model_name: str,
    provider_name: str,
    log: Callable[[str], None],
    progress: Callable[[float, str], None],
    diarisierung_aktiv: bool = True,
) -> dict[str, Any]:
    """Teilt lange Aufnahmen in Abschnitte, transkribiert sie einzeln und fuegt
    das Ergebnis zeitlich sortiert wieder zusammen.

    Wichtig: Die Sprechertrennung laeuft pro Abschnitt unabhaengig. Ob "Sprecher 1"
    in Abschnitt 2 dieselbe Person ist wie "Sprecher 1" in Abschnitt 1, kann die
    Cloud-Diarisierung ueber getrennte Anfragen hinweg nicht garantieren. Deshalb
    werden die Sprecherbezeichnungen bewusst mit "(Teil N)" gekennzeichnet, statt
    eine durchgaengige Identitaet vorzutaeuschen.
    """
    with tempfile.TemporaryDirectory(prefix="protokoll_audio_") as temp_name:
        temp_dir = Path(temp_name)
        progress(0.12, "Audio wird vorbereitet ...")
        vorbereitetes_audio, _ = kern.prepare_audio(source, temp_dir)
        chunk_pfade = split_audio_into_chunks(vorbereitetes_audio, temp_dir, chunk_seconds, log)
        anzahl = len(chunk_pfade)
        log(f"{anzahl} Abschnitte werden einzeln transkribiert.")

        alle_segmente: list[dict[str, Any]] = []
        alle_woerter: list[dict[str, Any]] = []
        alle_sprecher: list[dict[str, str]] = []
        gesamtdauer = 0.0
        sprache: str | None = None

        for index, chunk_pfad in enumerate(chunk_pfade, start=1):
            versatz = (index - 1) * chunk_seconds
            progress(
                0.15 + 0.55 * ((index - 1) / anzahl),
                f"Abschnitt {index}/{anzahl} wird uebertragen ...",
            )

            checkpoint = CHECKPOINT_DIR / f"{source.stem}_teil{index:02d}_rohantwort.json"
            if checkpoint.exists():
                log(f"Abschnitt {index}/{anzahl}: vorhandene Antwort wird weiterverwendet.")
                api_result = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
            else:
                request_data = build_transcription_request(
                    chunk_pfad, "mp3", model_name, provider_name, diarisierung_aktiv
                )
                api_result = call_transcription_endpoint(endpoint_url, request_data, api_key)
                checkpoint.write_text(
                    json.dumps(api_result, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            if api_result.get("language") and sprache is None:
                sprache = str(api_result.get("language"))

            segmente, woerter, sprecher = kern.normalize_transcript(api_result)
            for eintrag in segmente:
                eintrag["start_sekunden"] = round(eintrag["start_sekunden"] + versatz, 3)
                eintrag["ende_sekunden"] = round(eintrag["ende_sekunden"] + versatz, 3)
                eintrag["start"] = kern.format_timestamp(eintrag["start_sekunden"])
                eintrag["ende"] = kern.format_timestamp(eintrag["ende_sekunden"])
                if diarisierung_aktiv:
                    eintrag["sprecher"] = f"{eintrag['sprecher']} (Teil {index})"
                    eintrag["text"] = f"{eintrag['sprecher']}: {eintrag['inhalt']}"
                else:
                    eintrag["text"] = eintrag["inhalt"]
                eintrag["nummer"] = len(alle_segmente) + 1
                alle_segmente.append(eintrag)
                gesamtdauer = max(gesamtdauer, eintrag["ende_sekunden"])

            for eintrag in woerter:
                eintrag["start_sekunden"] = round(eintrag["start_sekunden"] + versatz, 3)
                eintrag["ende_sekunden"] = round(eintrag["ende_sekunden"] + versatz, 3)
                if diarisierung_aktiv:
                    eintrag["sprecher"] = f"{eintrag['sprecher']} (Teil {index})"
                alle_woerter.append(eintrag)

            if diarisierung_aktiv:
                for eintrag in sprecher:
                    alle_sprecher.append(
                        {
                            "sprecher_id": f"teil{index}:{eintrag['sprecher_id']}",
                            "bezeichnung": f"{eintrag['bezeichnung']} (Teil {index})",
                        }
                    )

            checkpoint.unlink(missing_ok=True)
            log(f"Abschnitt {index}/{anzahl} fertig.")

        progress(0.72, "Abschnitte werden zusammengefuegt ...")
        return {
            "segmente": alle_segmente,
            "woerter": alle_woerter,
            "sprecher": alle_sprecher,
            "dauer_sekunden": gesamtdauer,
            "sprache": sprache or kern.LANGUAGE or "automatisch erkannt",
            "anzahl_abschnitte": anzahl,
        }


def save_merged_transcript(
    source: Path,
    zusammengefasst: dict[str, Any],
    model_name: str,
    endpoint_url: str,
    diarisierung_aktiv: bool = True,
) -> tuple[Path, Path]:
    segmente = zusammengefasst["segmente"]
    if not segmente:
        raise RuntimeError("Die Aufnahme wurde verarbeitet, aber es wurde keine Sprache erkannt.")

    output_txt = OUTPUT_DIR / f"{source.stem}_mai2_transkript.txt"
    output_json = OUTPUT_DIR / f"{source.stem}_mai2_transkript.json"

    transcript_lines = [
        f"[{segment['start']} --> {segment['ende']}] {segment['text']}" for segment in segmente
    ]
    if diarisierung_aktiv:
        titel = "PROTOKOLL-ASSISTENT - VOLLTRANSKRIPT MIT SPRECHERTRENNUNG"
        hinweis_zeile = (
            "Hinweis: Sprecherbezeichnungen sind technische IDs, keine echten Namen, und "
            "nur innerhalb eines Abschnitts konsistent (siehe Klammerzusatz 'Teil N')."
        )
    else:
        titel = "PROTOKOLL-ASSISTENT - VOLLTRANSKRIPT (ANONYM, OHNE SPRECHERTRENNUNG)"
        hinweis_zeile = (
            "Hinweis: Auf Wunsch wurde keine Sprecherzuordnung angefragt - nur der "
            "Inhalt wurde erfasst."
        )
    header = [
        titel,
        f"Quelldatei: {source.name}",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Transkriptionsmodell: {model_name}",
        f"Endpunkt: {endpoint_url}",
        f"Erkannte Sprache: {zusammengefasst['sprache']}",
        f"Aufgeteilt in {zusammengefasst['anzahl_abschnitte']} Abschnitte "
        f"(je ca. {CHUNK_LAENGE_MINUTEN} Minuten)",
        hinweis_zeile,
        "",
    ]
    output_txt.write_text("\n".join(header + transcript_lines) + "\n", encoding="utf-8")

    ergebnis = {
        "quelldatei": source.name,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "modell": model_name,
        "endpunkt": endpoint_url,
        "sprache": zusammengefasst["sprache"],
        "dauer_sekunden": round(zusammengefasst["dauer_sekunden"], 3),
        "aufgeteilt_in_abschnitte": zusammengefasst["anzahl_abschnitte"],
        "abschnittslaenge_minuten": CHUNK_LAENGE_MINUTEN,
        "sprechertrennung_aktiv": diarisierung_aktiv,
        "anzahl_sprecher": len(zusammengefasst["sprecher"]) if diarisierung_aktiv else 0,
        "sprecher": zusammengefasst["sprecher"] if diarisierung_aktiv else [],
        "anzahl_segmente": len(segmente),
        "segmente": segmente,
        "woerter": zusammengefasst["woerter"],
    }
    output_json.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_txt, output_json


def erkenne_namen_vorschlag(text: str) -> str | None:
    for muster in SELBSTVORSTELLUNG_MUSTER:
        treffer = muster.search(text)
        if treffer:
            return treffer.group(1).strip(".,!? ").capitalize()
    return None


def sprecher_einfuehrungen_sammeln(
    segmente: list[dict[str, Any]], fenster_sekunden: float
) -> dict[str, dict[str, Any]]:
    """Liefert je Sprecherlabel ein Textbeispiel sowie - falls innerhalb des
    Zeitfensters eine Selbstvorstellung erkannt wurde - einen Namensvorschlag.

    Die Reihenfolge der Rueckgabe entspricht der Reihenfolge des ersten
    Auftretens im Transkript.
    """
    ergebnis: dict[str, dict[str, Any]] = {}
    for segment in segmente:
        label = str(segment.get("sprecher", "Sprecher unbekannt"))
        eintrag = ergebnis.setdefault(label, {"beispiel": "", "vorschlag": None})
        inhalt = str(segment.get("inhalt", ""))
        start_sekunden = kern.value_float(segment.get("start_sekunden"))
        if not eintrag["beispiel"]:
            eintrag["beispiel"] = inhalt
        if eintrag["vorschlag"] is None and start_sekunden <= fenster_sekunden:
            vorschlag = erkenne_namen_vorschlag(inhalt)
            if vorschlag:
                eintrag["vorschlag"] = vorschlag
    return ergebnis


def wende_sprechernamen_an(
    segmente: list[dict[str, Any]],
    woerter: list[dict[str, Any]],
    sprecher: list[dict[str, str]],
    zuordnung: dict[str, str],
) -> None:
    """Ersetzt generische Sprecherlabels durch vom Anwender vergebene Namen (in place)."""
    for segment in segmente:
        alt = str(segment.get("sprecher", ""))
        neu = zuordnung.get(alt, alt)
        segment["sprecher"] = neu
        segment["text"] = f"{neu}: {segment.get('inhalt', '')}"
    for wort in woerter:
        alt = str(wort.get("sprecher", ""))
        wort["sprecher"] = zuordnung.get(alt, alt)
    for eintrag in sprecher:
        alt = str(eintrag.get("bezeichnung", ""))
        eintrag["bezeichnung"] = zuordnung.get(alt, alt)


def speichere_transkript_mit_namen(
    output_txt: Path, output_json: Path, zuordnung: dict[str, str]
) -> None:
    """Schreibt ein bereits gespeichertes Transkript mit umbenannten Sprechern neu.

    Die Kopfzeilen der TXT-Datei (Quelldatei, Erstellungsdatum, Hinweise, ...)
    bleiben erhalten; nur die eigentlichen Transkriptzeilen sowie die
    Sprecherangaben in der JSON-Datei werden ersetzt.
    """
    daten = json.loads(output_json.read_text(encoding="utf-8-sig"))
    segmente = daten.get("segmente", [])
    woerter = daten.get("woerter", [])
    sprecher = daten.get("sprecher", [])
    wende_sprechernamen_an(segmente, woerter, sprecher, zuordnung)
    daten["sprecher"] = sprecher

    alte_zeilen = output_txt.read_text(encoding="utf-8").splitlines()
    kopf_ende = next((i for i, zeile in enumerate(alte_zeilen) if zeile == ""), len(alte_zeilen))
    kopf = alte_zeilen[: kopf_ende + 1]
    neue_zeilen = [
        f"[{segment['start']} --> {segment['ende']}] {segment['text']}" for segment in segmente
    ]
    output_txt.write_text("\n".join(kopf + neue_zeilen) + "\n", encoding="utf-8")
    output_json.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in kern.SUPPORTED_EXTENSIONS
    )


def open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass


def call_local_model(
    transcript_text: str, system_prompt: str, model_name: str, log: Callable[[str], None]
) -> str:
    payload = {
        "model": model_name,
        "system": system_prompt,
        "prompt": transcript_text,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        LOCAL_MODEL_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    log(f"Lokales Modell '{model_name}' wird angefragt ({LOCAL_MODEL_URL}) ...")
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_MODEL_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"Das lokale Modell '{model_name}' meldet HTTP {error.code}: {details}\n"
            f"Ist das Modell installiert? Ggf. mit 'ollama pull {model_name}' nachladen."
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            "Das lokale KI-Modell ist nicht erreichbar. Bitte pruefen, ob Ollama "
            f"laeuft (https://ollama.com) und unter {LOCAL_MODEL_URL} erreichbar ist. "
            f"Technische Details: {error}"
        ) from error

    if not isinstance(result, dict):
        raise RuntimeError("Das lokale Modell hat kein JSON-Objekt geliefert.")
    text = str(result.get("response", "")).strip()
    if not text:
        raise RuntimeError("Das lokale Modell hat keine Antwort geliefert.")
    return text


def call_api_model(
    transcript_text: str,
    system_prompt: str,
    api_key: str,
    model_name: str,
    endpoint_url: str,
    log: Callable[[str], None],
) -> str:
    """Ruft ein Chat-Completions-kompatibles API-Modell auf.

    Funktioniert mit jedem Anbieter, der die verbreitete OpenAI-kompatible
    '/chat/completions'-Schnittstelle anbietet (OpenRouter, OpenAI, IONOS AI
    Model Hub, u. v. a.) -- der Anwender traegt dafuer den passenden
    Endpunkt und Modellnamen selbst ein.
    """
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript_text},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    log(f"API-Modell '{model_name}' wird angefragt ({endpoint_url}) ...")
    try:
        with urllib.request.urlopen(request, timeout=API_MODEL_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"API-Fehler HTTP {error.code} von {endpoint_url}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Der Endpunkt ist nicht erreichbar ({endpoint_url}): {error}") from error

    if not isinstance(result, dict):
        raise RuntimeError(f"{endpoint_url} hat kein JSON-Objekt geliefert.")
    if result.get("error"):
        raise RuntimeError(f"Der Endpunkt meldet einen Fehler: {result['error']}")
    try:
        text = str(result["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unerwartete Antwort von {endpoint_url}: {result}") from error
    if not text:
        raise RuntimeError("Das API-Modell hat keine Antwort geliefert.")
    return text


def save_processed_result(
    basisname: str,
    quelle_name: str,
    system_prompt: str,
    engine: str,
    model_name: str,
    result_text: str,
    endpoint_url: str | None = None,
) -> tuple[Path, Path]:
    ERGEBNIS_DIR.mkdir(parents=True, exist_ok=True)
    output_txt = ERGEBNIS_DIR / f"{basisname}_protokoll.txt"
    output_json = ERGEBNIS_DIR / f"{basisname}_protokoll.json"

    if engine == "lokal":
        verarbeitung_text = f"Lokales Modell: {model_name}"
    else:
        verarbeitung_text = f"API-Modell: {model_name} (Endpunkt: {endpoint_url})"
    header = [
        "PROTOKOLL-ASSISTENT - ERGEBNIS DER NACHBEARBEITUNG",
        f"Quelle: {quelle_name}",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        verarbeitung_text,
        "",
        "Verwendeter Systemprompt:",
        system_prompt.strip(),
        "",
        "-" * 72,
        "",
    ]
    output_txt.write_text("\n".join(header) + result_text.strip() + "\n", encoding="utf-8")

    payload = {
        "quelle": quelle_name,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verarbeitung": engine,
        "modell": model_name,
        "endpunkt": endpoint_url if engine == "api" else None,
        "systemprompt": system_prompt.strip(),
        "ergebnis": result_text.strip(),
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_txt, output_json


class ProtokollGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Protokoll-Assistent")
        root.geometry("1000x970")
        root.minsize(820, 700)

        self.aktuelles_theme = theme.anwenden(root)

        self.selected_folder: Path | None = None
        self.audio_files: list[Path] = []
        self.transkript_pfad: Path | None = None
        self.message_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = False
        self.sprecher_dialog_event = threading.Event()
        self.sprecher_namen_ergebnis: dict[str, str] = {}
        self.worker_thread: threading.Thread | None = None
        self.last_output_paths: list[Path] = []

        for directory in (INPUT_DIR, OUTPUT_DIR, CHECKPOINT_DIR, SETTINGS_DIR, ERGEBNIS_DIR):
            directory.mkdir(parents=True, exist_ok=True)

        self._build_widgets()
        self._poll_queue()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self) -> None:
        padding = {"padx": 10, "pady": 6}

        kopfzeile = ttk.Frame(self.root)
        kopfzeile.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(
            kopfzeile, text="Protokoll-Assistent", font=("Segoe UI", 16, "bold")
        ).pack(side="left")
        if theme.HAT_SV_TTK:
            self.dunkel_var = tk.BooleanVar(value=(self.aktuelles_theme == "dark"))
            ttk.Checkbutton(
                kopfzeile,
                text="Dunkles Design",
                style="Switch.TCheckbutton",
                variable=self.dunkel_var,
                command=self._theme_umschalten,
            ).pack(side="right")

        folder_frame = ttk.LabelFrame(self.root, text="1. Aufnahme auswaehlen")
        folder_frame.pack(fill="x", **padding)

        row1 = ttk.Frame(folder_frame)
        row1.pack(fill="x", padx=8, pady=6)
        ttk.Button(row1, text="Ordner auswaehlen ...", command=self.choose_folder).pack(
            side="left"
        )
        self.folder_label_var = tk.StringVar(value="Kein Ordner ausgewaehlt")
        ttk.Label(row1, textvariable=self.folder_label_var).pack(side="left", padx=10)

        row2 = ttk.Frame(folder_frame)
        row2.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row2, text="Datei:").pack(side="left")
        self.file_var = tk.StringVar()
        self.file_combo = ttk.Combobox(
            row2, textvariable=self.file_var, state="readonly", width=60
        )
        self.file_combo.pack(side="left", padx=8, fill="x", expand=True)

        api_frame = ttk.LabelFrame(self.root, text="2. Transkriptions-API")
        api_frame.pack(fill="x", **padding)
        row3 = ttk.Frame(api_frame)
        row3.pack(fill="x", padx=8, pady=6)
        ttk.Label(row3, text="API-Schluessel:").pack(side="left")
        self.api_key_var = tk.StringVar(value=os.environ.get("OPENROUTER_API_KEY", ""))
        self.api_key_entry = ttk.Entry(row3, textvariable=self.api_key_var, show="*", width=50)
        self.api_key_entry.pack(side="left", padx=8, fill="x", expand=True)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row3, text="anzeigen", variable=self.show_key_var, command=self._toggle_key_visibility
        ).pack(side="left")

        row_transkription_endpoint = ttk.Frame(api_frame)
        row_transkription_endpoint.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row_transkription_endpoint, text="Endpunkt (Basis-URL):").pack(side="left")
        self.transkription_endpoint_var = tk.StringVar(value=DEFAULT_TRANSKRIPTION_ENDPUNKT)
        ttk.Entry(
            row_transkription_endpoint, textvariable=self.transkription_endpoint_var, width=45
        ).pack(side="left", padx=8, fill="x", expand=True)

        row_transkription_modell = ttk.Frame(api_frame)
        row_transkription_modell.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row_transkription_modell, text="Modellname:").pack(side="left")
        self.transkription_modell_var = tk.StringVar(value=DEFAULT_TRANSKRIPTION_MODELL)
        ttk.Entry(
            row_transkription_modell, textvariable=self.transkription_modell_var, width=30
        ).pack(side="left", padx=8)
        self.transkription_anbieter_label = ttk.Label(
            row_transkription_modell, text="Anbieter (Sprechertrennung):"
        )
        self.transkription_anbieter_label.pack(side="left", padx=(16, 0))
        self.transkription_anbieter_var = tk.StringVar(value=DEFAULT_TRANSKRIPTION_ANBIETER)
        self.transkription_anbieter_entry = ttk.Entry(
            row_transkription_modell, textvariable=self.transkription_anbieter_var, width=12
        )
        self.transkription_anbieter_entry.pack(side="left", padx=8)

        row_diarisierung = ttk.Frame(api_frame)
        row_diarisierung.pack(fill="x", padx=8, pady=(0, 6))
        self.diarisierung_aktiv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row_diarisierung,
            text="Sprechertrennung aktivieren",
            variable=self.diarisierung_aktiv_var,
            command=self._diarisierung_geaendert,
        ).pack(side="left")
        ttk.Label(
            row_diarisierung,
            text=(
                "Deaktivieren, wenn nur der Inhalt zaehlt und die Aussagen anonym "
                "bleiben sollen - das Transkript enthaelt dann keine Sprecherzuordnung."
            ),
            foreground="#555555",
        ).pack(side="left", padx=8)

        ttk.Label(
            api_frame,
            text=(
                "Der Schluessel wird nur im Arbeitsspeicher dieser Sitzung gehalten, "
                "niemals in eine Datei oder in den Code geschrieben. Endpunkt, Modell "
                "und Anbieter sind frei aenderbar - Standard ist OpenRouter mit "
                "microsoft/mai-transcribe-2, ebenso moeglich ist z. B. eine direkte "
                "Anbindung an Microsoft Azure oder einen anderen Anbieter, der dasselbe "
                "Anfrageformat (JSON mit Base64-Audio) versteht. 'Anbieter' leer lassen, "
                "wenn der Endpunkt keine Provider-Weiterleitung fuer die Sprechertrennung "
                "benoetigt. Der Schluessel dient bei der Nachbearbeitung ausserdem als "
                "Standard-Schluessel, falls dort kein eigener eingetragen wird."
            ),
            foreground="#555555",
            wraplength=880,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 6))

        transkription_action = ttk.Frame(self.root)
        transkription_action.pack(fill="x", **padding)
        self.start_button = ttk.Button(
            transkription_action, text="Transkription starten", command=self.start_transkription
        )
        self.start_button.pack(side="left")
        self.open_output_button = ttk.Button(
            transkription_action,
            text="Transkript-Ordner oeffnen",
            command=lambda: open_in_file_manager(OUTPUT_DIR),
        )
        self.open_output_button.pack(side="left", padx=8)
        self.sprecher_benennen_var = tk.BooleanVar(value=True)
        self.sprecher_benennen_checkbox = ttk.Checkbutton(
            transkription_action,
            text="Sprecher danach benennen",
            variable=self.sprecher_benennen_var,
        )
        self.sprecher_benennen_checkbox.pack(side="left", padx=8)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=(4, 0))
        ttk.Label(
            self.root,
            text="Nachbearbeitung (separater Schritt - jederzeit fuer ein vorhandenes Transkript)",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=10, pady=(8, 0))

        transkript_frame = ttk.LabelFrame(self.root, text="3. Transkript auswaehlen")
        transkript_frame.pack(fill="x", **padding)
        row_transkript = ttk.Frame(transkript_frame)
        row_transkript.pack(fill="x", padx=8, pady=6)
        ttk.Button(
            row_transkript, text="Transkript auswaehlen ...", command=self.waehle_transkript
        ).pack(side="left")
        ttk.Button(
            row_transkript, text="Sprecher umbenennen ...", command=self.sprecher_umbenennen
        ).pack(side="left", padx=8)
        self.transkript_label_var = tk.StringVar(value="Noch kein Transkript ausgewaehlt")
        ttk.Label(
            transkript_frame, textvariable=self.transkript_label_var, wraplength=700
        ).pack(anchor="w", padx=8, pady=(0, 6))

        model_frame = ttk.LabelFrame(self.root, text="4. Sprachmodell fuer die Nachbearbeitung")
        model_frame.pack(fill="x", **padding)
        row_engine = ttk.Frame(model_frame)
        row_engine.pack(fill="x", padx=8, pady=(6, 0))
        self.engine_var = tk.StringVar(value="lokal")
        ttk.Radiobutton(
            row_engine,
            text="Lokal (z. B. Ollama)",
            value="lokal",
            variable=self.engine_var,
            command=self._engine_geaendert,
        ).pack(side="left")
        ttk.Radiobutton(
            row_engine,
            text="API-Modell (frei waehlbarer Endpunkt)",
            value="api",
            variable=self.engine_var,
            command=self._engine_geaendert,
        ).pack(side="left", padx=16)

        row4 = ttk.Frame(model_frame)
        row4.pack(fill="x", padx=8, pady=6)
        ttk.Label(row4, text="Modellname:").pack(side="left")
        self.model_var = tk.StringVar(value=DEFAULT_LOCAL_MODEL)
        ttk.Entry(row4, textvariable=self.model_var, width=30).pack(side="left", padx=8)

        row_endpoint = ttk.Frame(model_frame)
        row_endpoint.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row_endpoint, text="API-Endpunkt (Basis-URL):").pack(side="left")
        self.endpoint_var = tk.StringVar(value=OPENROUTER_CHAT_URL)
        self.endpoint_entry = ttk.Entry(row_endpoint, textvariable=self.endpoint_var, width=55)
        self.endpoint_entry.pack(side="left", padx=8, fill="x", expand=True)
        self.endpoint_entry.config(state="disabled")

        row_api_key_nachbearbeitung = ttk.Frame(model_frame)
        row_api_key_nachbearbeitung.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row_api_key_nachbearbeitung, text="API-Schluessel fuer diesen Endpunkt:").pack(
            side="left"
        )
        self.api_key_nachbearbeitung_var = tk.StringVar()
        self.api_key_nachbearbeitung_entry = ttk.Entry(
            row_api_key_nachbearbeitung,
            textvariable=self.api_key_nachbearbeitung_var,
            show="*",
            width=40,
        )
        self.api_key_nachbearbeitung_entry.pack(side="left", padx=8, fill="x", expand=True)
        self.api_key_nachbearbeitung_entry.config(state="disabled")
        ttk.Label(
            row_api_key_nachbearbeitung,
            text="(leer = Schluessel oben verwenden)",
            foreground="#555555",
        ).pack(side="left")

        self.model_hinweis_var = tk.StringVar(
            value=(
                "Das Modell laeuft lokal (z. B. via Ollama, https://ollama.com) und "
                "verarbeitet nur Daten, die bereits auf diesem Geraet liegen."
            )
        )
        ttk.Label(
            model_frame,
            textvariable=self.model_hinweis_var,
            foreground="#555555",
            wraplength=880,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 6))

        prompt_frame = ttk.LabelFrame(
            self.root, text="5. Was soll mit dem Transkript geschehen? (Systemprompt)"
        )
        prompt_frame.pack(fill="both", expand=False, **padding)
        row5 = ttk.Frame(prompt_frame)
        row5.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(row5, text="Vorlage:").pack(side="left")
        self.template_var = tk.StringVar()
        template_combo = ttk.Combobox(
            row5,
            textvariable=self.template_var,
            state="readonly",
            values=list(SYSTEMPROMPT_VORLAGEN.keys()),
            width=25,
        )
        template_combo.pack(side="left", padx=8)
        template_combo.bind("<<ComboboxSelected>>", self._apply_template)

        self.systemprompt_text = tk.Text(prompt_frame, height=5, wrap="word")
        self.systemprompt_text.pack(fill="x", padx=8, pady=6)
        self.systemprompt_text.insert("1.0", DEFAULT_SYSTEMPROMPT)

        nachbearbeitung_action = ttk.Frame(self.root)
        nachbearbeitung_action.pack(fill="x", **padding)
        self.nachbearbeitung_button = ttk.Button(
            nachbearbeitung_action,
            text="Nachbearbeitung starten",
            command=self.start_nachbearbeitung,
        )
        self.nachbearbeitung_button.pack(side="left")
        self.open_ergebnis_button = ttk.Button(
            nachbearbeitung_action,
            text="Ergebnisordner oeffnen",
            command=lambda: open_in_file_manager(ERGEBNIS_DIR),
        )
        self.open_ergebnis_button.pack(side="left", padx=8)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            self.root, maximum=1.0, variable=self.progress_var
        )
        self.progress_bar.pack(fill="x", padx=10, pady=(0, 2))
        self.progress_label_var = tk.StringVar(value="Bereit.")
        ttk.Label(self.root, textvariable=self.progress_label_var).pack(
            anchor="w", padx=10, pady=(0, 6)
        )

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text="Ablauf / Protokoll")
        self.log_text = scrolledtext.ScrolledText(log_tab, wrap="word", height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        result_tab = ttk.Frame(notebook)
        notebook.add(result_tab, text="Ergebnis")
        self.result_text = scrolledtext.ScrolledText(result_tab, wrap="word", height=8, state="disabled")
        self.result_text.pack(fill="both", expand=True)

        self._text_widgets_faerben()

    def _text_widgets_faerben(self) -> None:
        for widget in (self.systemprompt_text, self.log_text, self.result_text):
            theme.text_widget_faerben(widget, self.aktuelles_theme)

    def _theme_umschalten(self) -> None:
        neues_theme = "dark" if self.dunkel_var.get() else "light"
        if theme.HAT_SV_TTK:
            theme.sv_ttk.set_theme(neues_theme)
        self.aktuelles_theme = neues_theme
        self._text_widgets_faerben()

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.config(show="" if self.show_key_var.get() else "*")

    def _apply_template(self, _event: object = None) -> None:
        template = SYSTEMPROMPT_VORLAGEN.get(self.template_var.get())
        if template:
            self.systemprompt_text.delete("1.0", "end")
            self.systemprompt_text.insert("1.0", template)

    def _engine_geaendert(self) -> None:
        aktuelle = self.model_var.get().strip()
        if self.engine_var.get() == "api":
            if aktuelle in ("", DEFAULT_LOCAL_MODEL):
                self.model_var.set(DEFAULT_API_MODEL)
            self.endpoint_entry.config(state="normal")
            self.api_key_nachbearbeitung_entry.config(state="normal")
            self.model_hinweis_var.set(
                "Wird an den oben eingetragenen API-Endpunkt gesendet (Standard: "
                "OpenRouter; ebenso moeglich sind z. B. OpenAI, IONOS AI Model Hub "
                "oder jeder andere Anbieter mit OpenAI-kompatibler "
                "'/chat/completions'-Schnittstelle - Endpunkt und Modellname bitte "
                "beim jeweiligen Anbieter nachschlagen). Verwendet den "
                "API-Schluessel fuer diesen Endpunkt (oder, falls leer gelassen, "
                "den OpenRouter-Schluessel unter Punkt 2) - dabei verlaesst das "
                "Transkript das Geraet."
            )
        else:
            if aktuelle in ("", DEFAULT_API_MODEL):
                self.model_var.set(DEFAULT_LOCAL_MODEL)
            self.endpoint_entry.config(state="disabled")
            self.api_key_nachbearbeitung_entry.config(state="disabled")
            self.model_hinweis_var.set(
                "Das Modell laeuft lokal (z. B. via Ollama, https://ollama.com) und "
                "verarbeitet nur Daten, die bereits auf diesem Geraet liegen."
            )

    def _diarisierung_geaendert(self) -> None:
        aktiv = self.diarisierung_aktiv_var.get()
        self.transkription_anbieter_entry.config(state="normal" if aktiv else "disabled")
        if not aktiv:
            self.sprecher_benennen_var.set(False)
        self.sprecher_benennen_checkbox.config(state="normal" if aktiv else "disabled")

    # ------------------------------------------------------------ Auswahl

    def choose_folder(self) -> None:
        start_dir = str(INPUT_DIR) if INPUT_DIR.exists() else str(APP_DIR)
        folder = filedialog.askdirectory(
            title="Ordner mit der Aufnahme auswaehlen", initialdir=start_dir
        )
        if not folder:
            return
        self.selected_folder = Path(folder)
        self.audio_files = scan_audio_files(self.selected_folder)

        if not self.audio_files:
            self.folder_label_var.set(f"{self.selected_folder} (keine unterstuetzte Datei gefunden)")
            self.file_combo["values"] = []
            self.file_var.set("")
            return

        self.folder_label_var.set(str(self.selected_folder))
        self.file_combo["values"] = [path.name for path in self.audio_files]
        self.file_var.set(self.audio_files[0].name)

    def waehle_transkript(self) -> None:
        start_dir = str(OUTPUT_DIR) if OUTPUT_DIR.exists() else str(APP_DIR)
        datei = filedialog.askopenfilename(
            title="Transkript auswaehlen",
            initialdir=start_dir,
            filetypes=[("Transkript", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if not datei:
            return
        self._setze_transkript(Path(datei))

    def _setze_transkript(self, pfad: Path) -> None:
        self.transkript_pfad = pfad
        self.transkript_label_var.set(str(pfad))

    def sprecher_umbenennen(self) -> None:
        if not self.transkript_pfad or not self.transkript_pfad.is_file():
            messagebox.showwarning(
                "Kein Transkript ausgewaehlt", "Bitte zuerst ein Transkript auswaehlen."
            )
            return

        json_pfad = self.transkript_pfad.with_suffix(".json")
        if not json_pfad.is_file():
            messagebox.showwarning(
                "Keine JSON-Datei gefunden",
                f"Zur Textdatei wurde keine passende JSON-Datei gefunden ({json_pfad.name}).",
            )
            return

        daten = json.loads(json_pfad.read_text(encoding="utf-8-sig"))
        einfuehrungen = sprecher_einfuehrungen_sammeln(
            daten.get("segmente", []), SPRECHER_FENSTER_SEKUNDEN
        )
        echte_sprecher = {
            label: info for label, info in einfuehrungen.items() if label != "Sprecher unbekannt"
        }
        if not echte_sprecher:
            messagebox.showinfo(
                "Keine Sprecher gefunden",
                "In diesem Transkript wurden keine Sprecherlabels gefunden.",
            )
            return

        zuordnung = self._zeige_sprecher_dialog(echte_sprecher)
        if not zuordnung:
            return
        speichere_transkript_mit_namen(self.transkript_pfad, json_pfad, zuordnung)
        self._append_log(
            "Sprechernamen uebernommen: "
            + ", ".join(f"{alt} -> {neu}" for alt, neu in zuordnung.items())
        )
        messagebox.showinfo("Fertig", "Die Sprechernamen wurden im Transkript aktualisiert.")

    def _zeige_sprecher_dialog(self, einfuehrungen: dict[str, dict[str, Any]]) -> dict[str, str]:
        fenster = tk.Toplevel(self.root)
        fenster.title("Sprecher benennen")
        fenster.transient(self.root)
        fenster.grab_set()

        ttk.Label(
            fenster,
            text=(
                "Erkannte Sprecher aus den ersten Minuten. Namen eintragen (ein "
                "Vorschlag ist bereits eingetragen, falls eine Selbstvorstellung "
                "erkannt wurde) oder leer lassen, um die technische Bezeichnung "
                "zu behalten."
            ),
            wraplength=520,
            justify="left",
        ).pack(padx=16, pady=(16, 8), fill="x")

        eingabe_vars: dict[str, tk.StringVar] = {}
        for label, info in einfuehrungen.items():
            zeile = ttk.Frame(fenster)
            zeile.pack(fill="x", padx=16, pady=4)
            ttk.Label(zeile, text=label, width=16).pack(side="left")
            var = tk.StringVar(value=info.get("vorschlag") or "")
            ttk.Entry(zeile, textvariable=var, width=20).pack(side="left", padx=8)
            beispiel = str(info.get("beispiel") or "").strip()[:70]
            ttk.Label(
                zeile, text=f'"{beispiel}"', foreground="#777777", wraplength=260
            ).pack(side="left")
            eingabe_vars[label] = var

        ergebnis: dict[str, str] = {}

        def bestaetigen() -> None:
            ergebnis.update(
                {
                    label: var.get().strip()
                    for label, var in eingabe_vars.items()
                    if var.get().strip()
                }
            )
            fenster.destroy()

        knopf_zeile = ttk.Frame(fenster)
        knopf_zeile.pack(fill="x", padx=16, pady=16)
        ttk.Button(knopf_zeile, text="Uebernehmen", command=bestaetigen).pack(side="left")
        ttk.Button(knopf_zeile, text="Ueberspringen", command=fenster.destroy).pack(
            side="left", padx=8
        )
        fenster.protocol("WM_DELETE_WINDOW", fenster.destroy)

        fenster.update_idletasks()
        fenster.geometry(f"+{self.root.winfo_rootx() + 60}+{self.root.winfo_rooty() + 60}")
        self.root.wait_window(fenster)
        return ergebnis

    def _frage_sprecher_namen(self, einfuehrungen: dict[str, dict[str, Any]]) -> dict[str, str]:
        self.sprecher_dialog_event.clear()
        self.message_queue.put(("sprecher_dialog", einfuehrungen))
        self.sprecher_dialog_event.wait()
        return self.sprecher_namen_ergebnis

    # -------------------------------------------------------------- Start

    def _ist_beschaeftigt(self) -> bool:
        return bool(self.worker_thread and self.worker_thread.is_alive())

    def start_transkription(self) -> None:
        if self._ist_beschaeftigt():
            return

        if not self.audio_files or not self.file_var.get():
            messagebox.showwarning(
                "Keine Datei ausgewaehlt",
                "Bitte zuerst einen Ordner mit einer Audio- oder Videodatei auswaehlen.",
            )
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning(
                "API-Schluessel fehlt", "Bitte den API-Schluessel fuer die Transkription eingeben."
            )
            return

        endpoint_url = self.transkription_endpoint_var.get().strip()
        modell = self.transkription_modell_var.get().strip()
        if not endpoint_url or not modell:
            messagebox.showwarning(
                "Angaben fehlen",
                "Bitte Endpunkt (Basis-URL) und Modellname fuer die Transkription eintragen.",
            )
            return
        anbieter = self.transkription_anbieter_var.get().strip()
        diarisierung_aktiv = self.diarisierung_aktiv_var.get()

        source = self.selected_folder / self.file_var.get()  # type: ignore[operator]
        sprecher_benennen = self.sprecher_benennen_var.get() and diarisierung_aktiv

        self.start_button.config(state="disabled")
        self.nachbearbeitung_button.config(state="disabled")
        self.progress_var.set(0.0)
        self.progress_label_var.set("Start ...")
        self._set_text_widget(self.log_text, "")

        self.worker_thread = threading.Thread(
            target=self._run_transkription,
            args=(source, api_key, endpoint_url, modell, anbieter, sprecher_benennen, diarisierung_aktiv),
            daemon=True,
        )
        self.worker_thread.start()

    def start_nachbearbeitung(self) -> None:
        if self._ist_beschaeftigt():
            return

        if not self.transkript_pfad or not self.transkript_pfad.is_file():
            messagebox.showwarning(
                "Kein Transkript ausgewaehlt",
                "Bitte zuerst ein Transkript auswaehlen (oder eine Transkription "
                "durchfuehren - das Ergebnis wird hier automatisch eingetragen).",
            )
            return

        modell = self.model_var.get().strip()
        if not modell:
            messagebox.showwarning("Modell fehlt", "Bitte einen Modellnamen angeben.")
            return

        engine = self.engine_var.get()
        endpoint_url = self.endpoint_var.get().strip()
        api_key = (
            self.api_key_nachbearbeitung_var.get().strip() or self.api_key_var.get().strip()
        )
        if engine == "api":
            if not api_key:
                messagebox.showwarning(
                    "API-Schluessel fehlt",
                    "Bitte einen API-Schluessel fuer diesen Endpunkt eintragen (oder "
                    "den OpenRouter-Schluessel unter Punkt 2 hinterlegen).",
                )
                return
            if not endpoint_url:
                messagebox.showwarning(
                    "API-Endpunkt fehlt",
                    "Bitte den API-Endpunkt (Basis-URL) eintragen, z. B. den "
                    "Chat-Completions-Endpunkt von OpenRouter, OpenAI oder IONOS.",
                )
                return

        systemprompt = self.systemprompt_text.get("1.0", "end").strip()
        if not systemprompt:
            messagebox.showwarning(
                "Systemprompt fehlt",
                "Bitte beschreiben, was mit dem Transkript geschehen soll.",
            )
            return

        self.start_button.config(state="disabled")
        self.nachbearbeitung_button.config(state="disabled")
        self.progress_var.set(0.0)
        self.progress_label_var.set("Start Nachbearbeitung ...")
        self._set_text_widget(self.result_text, "")

        self.worker_thread = threading.Thread(
            target=self._run_nachbearbeitung,
            args=(self.transkript_pfad, engine, modell, api_key, endpoint_url, systemprompt),
            daemon=True,
        )
        self.worker_thread.start()

    # ---------------------------------------------------------- Pipeline

    def _log(self, message: str) -> None:
        self.message_queue.put(("log", message))

    def _progress(self, fraction: float, text: str) -> None:
        self.message_queue.put(("progress", (fraction, text)))

    def _ask_confirmation(self, nachricht: str) -> bool:
        self.confirm_event.clear()
        self.message_queue.put(("confirm", nachricht))
        self.confirm_event.wait()
        return self.confirm_result

    def _run_transkription(
        self,
        source: Path,
        api_key: str,
        endpoint_url: str,
        modell: str,
        anbieter: str,
        sprecher_benennen: bool,
        diarisierung_aktiv: bool = True,
    ) -> None:
        try:
            self._log(f"Eingabedatei: {source.name}")
            self._log(f"Transkriptionsmodell: {modell} (Endpunkt: {endpoint_url})")
            if diarisierung_aktiv:
                self._log(f"Sprechertrennung: aktiviert (Anbieter: {anbieter or '-'})")
            else:
                self._log("Sprechertrennung: deaktiviert - Ergebnis bleibt anonym.")

            self._progress(0.05, "Datenschutzabfrage ...")
            nachricht = (
                f"Die Aufnahme '{source.name}' wird zur Transkription an\n'{endpoint_url}'"
                "\nuebertragen.\n\nUebertragung jetzt starten?"
            )
            if not self._ask_confirmation(nachricht):
                self._log("Abbruch: Uebertragung wurde nicht bestaetigt. Es wurden keine Daten gesendet.")
                return

            ffmpeg_path = ensure_ffmpeg_on_path()
            if ffmpeg_path:
                self._log(f"FFmpeg gefunden: {ffmpeg_path}")
            else:
                self._log(
                    "Hinweis: FFmpeg wurde nicht gefunden. Fuer Video- oder grosse "
                    "Audiodateien bitte FFmpeg installieren (https://ffmpeg.org)."
                )

            dauer_sekunden = get_audio_duration_seconds(source)
            if dauer_sekunden:
                self._log(f"Erkannte Laenge der Aufnahme: {kern.format_timestamp(dauer_sekunden)}")

            if dauer_sekunden and dauer_sekunden > CHUNK_SCHWELLE_SEKUNDEN:
                self._log(
                    f"Aufnahme ist laenger als {CHUNK_SCHWELLE_MINUTEN} Minuten - wird in "
                    f"Abschnitte von je {CHUNK_LAENGE_MINUTEN} Minuten aufgeteilt, transkribiert "
                    "und danach wieder zusammengefuegt."
                )
                self._log(
                    "Hinweis: Die Sprechernummerierung kann an Abschnittsgrenzen neu beginnen "
                    "(siehe Klammerzusatz 'Teil N' in den Sprecherbezeichnungen)."
                )
                zusammengefasst = transcribe_in_chunks(
                    source,
                    api_key,
                    CHUNK_LAENGE_SEKUNDEN,
                    endpoint_url,
                    modell,
                    anbieter,
                    self._log,
                    self._progress,
                    diarisierung_aktiv,
                )
                self._progress(0.85, "Transkript wird gespeichert ...")
                output_txt, output_json = save_merged_transcript(
                    source, zusammengefasst, modell, endpoint_url, diarisierung_aktiv
                )
            else:
                checkpoint = CHECKPOINT_DIR / f"{source.stem}_mai_transcribe_2_rohantwort.json"
                if checkpoint.exists():
                    self._log("Vorhandene Modellantwort wird weiterverarbeitet (kein neuer Upload).")
                    api_result = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
                else:
                    self._progress(0.15, "Audio wird vorbereitet ...")
                    with tempfile.TemporaryDirectory(prefix="protokoll_audio_") as temp_name:
                        audio_path, audio_format = kern.prepare_audio(source, Path(temp_name))
                        request_data = build_transcription_request(
                            audio_path, audio_format, modell, anbieter, diarisierung_aktiv
                        )
                        self._progress(0.35, f"Uebertragung an {endpoint_url} ...")
                        self._log("Cloud-Transkription gestartet ...")
                        api_result = call_transcription_endpoint(endpoint_url, request_data, api_key)
                    checkpoint.write_text(
                        json.dumps(api_result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )

                self._progress(0.85, "Transkript wird gespeichert ...")
                output_txt, output_json = save_transcript(
                    source, api_result, modell, endpoint_url, diarisierung_aktiv
                )
                checkpoint.unlink(missing_ok=True)

            self._log(f"Transkript gespeichert: {output_txt.name}")
            self._log(f"Transkript (JSON) gespeichert: {output_json.name}")

            if sprecher_benennen:
                daten = json.loads(output_json.read_text(encoding="utf-8-sig"))
                einfuehrungen = sprecher_einfuehrungen_sammeln(
                    daten.get("segmente", []), SPRECHER_FENSTER_SEKUNDEN
                )
                echte_sprecher = {
                    label: info
                    for label, info in einfuehrungen.items()
                    if label != "Sprecher unbekannt"
                }
                if echte_sprecher:
                    self._log(
                        f"Sprecher aus den ersten {SPRECHER_FENSTER_MINUTEN} Minuten werden "
                        "zur Benennung vorgeschlagen ..."
                    )
                    self._progress(0.95, "Sprecher benennen ...")
                    zuordnung = self._frage_sprecher_namen(echte_sprecher)
                    if zuordnung:
                        speichere_transkript_mit_namen(output_txt, output_json, zuordnung)
                        self._log(
                            "Sprechernamen uebernommen: "
                            + ", ".join(f"{alt} -> {neu}" for alt, neu in zuordnung.items())
                        )
                    else:
                        self._log(
                            "Sprecherbenennung uebersprungen - technische Bezeichnungen "
                            "bleiben erhalten."
                        )

            self._log(
                "Transkription abgeschlossen. Die Nachbearbeitung (Zusammenfassung, Agenda, "
                "...) kann jetzt weiter unten separat gestartet werden."
            )
            self._progress(1.0, "Transkription fertig.")
            self.message_queue.put(("transkript_fertig", output_txt))
        except KeyboardInterrupt:
            self._log("Abbruch durch Benutzer.")
        except Exception as error:  # noqa: BLE001 - Fehler sollen sichtbar in der GUI landen
            self._log(f"FEHLER: {error}")
            self.message_queue.put(("error", str(error)))
        finally:
            self.message_queue.put(("job_fertig", None))

    def _run_nachbearbeitung(
        self,
        transkript_pfad: Path,
        engine: str,
        modell: str,
        api_key: str,
        endpoint_url: str,
        systemprompt: str,
    ) -> None:
        try:
            self._log(f"Nachbearbeitung fuer: {transkript_pfad.name}")
            transcript_text = transkript_pfad.read_text(encoding="utf-8")

            basisname = transkript_pfad.stem
            suffix = "_mai2_transkript"
            if basisname.endswith(suffix):
                basisname = basisname[: -len(suffix)]

            if engine == "api":
                self._progress(0.1, "Datenschutzabfrage ...")
                nachricht = (
                    f"Das Transkript '{transkript_pfad.name}' wird zur Nachbearbeitung an "
                    f"'{endpoint_url}' uebertragen (Modell: {modell}).\n\nUebertragung jetzt starten?"
                )
                if not self._ask_confirmation(nachricht):
                    self._log("Abbruch: Uebertragung wurde nicht bestaetigt.")
                    return
                self._progress(0.35, f"API-Modell '{modell}' wird angefragt ...")
                result_text = call_api_model(
                    transcript_text, systemprompt, api_key, modell, endpoint_url, self._log
                )
            else:
                self._progress(0.25, f"Lokales Modell '{modell}' wird angefragt ...")
                self._log(
                    "Transkript wird lokal verarbeitet - hierfuer werden keine weiteren "
                    "Daten an Dritte uebertragen."
                )
                result_text = call_local_model(transcript_text, systemprompt, modell, self._log)

            self._progress(0.85, "Ergebnis wird gespeichert ...")
            protokoll_txt, protokoll_json = save_processed_result(
                basisname,
                transkript_pfad.name,
                systemprompt,
                engine,
                modell,
                result_text,
                endpoint_url=endpoint_url if engine == "api" else None,
            )
            self._log(f"Ergebnis gespeichert in '{ERGEBNIS_DIR.name}': {protokoll_txt.name}")
            self._log(f"Ergebnis (JSON) gespeichert in '{ERGEBNIS_DIR.name}': {protokoll_json.name}")

            self._progress(1.0, "Fertig.")
            self.message_queue.put(
                ("nachbearbeitung_ergebnis", (result_text, [protokoll_txt, protokoll_json]))
            )
        except Exception as error:  # noqa: BLE001 - Fehler sollen sichtbar in der GUI landen
            self._log(f"FEHLER: {error}")
            self.message_queue.put(("error", str(error)))
        finally:
            self.message_queue.put(("job_fertig", None))

    # -------------------------------------------------------------- Queue

    def _set_text_widget(self, widget: tk.Text, content: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.config(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _show_confirm_dialog(self, nachricht: str) -> None:
        answer = messagebox.askyesno("Datenschutzhinweis", nachricht)
        self.confirm_result = bool(answer)
        self.confirm_event.set()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    fraction, text = payload
                    self.progress_var.set(fraction)
                    self.progress_label_var.set(text)
                elif kind == "confirm":
                    self._show_confirm_dialog(payload)
                elif kind == "sprecher_dialog":
                    self.sprecher_namen_ergebnis = self._zeige_sprecher_dialog(payload)
                    self.sprecher_dialog_event.set()
                elif kind == "transkript_fertig":
                    self._setze_transkript(payload)
                elif kind == "nachbearbeitung_ergebnis":
                    result_text, paths = payload
                    self._set_text_widget(self.result_text, result_text)
                    self.last_output_paths = paths
                elif kind == "error":
                    messagebox.showerror("Fehler", payload)
                elif kind == "job_fertig":
                    self.start_button.config(state="normal")
                    self.nachbearbeitung_button.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main() -> int:
    root = tk.Tk()
    ProtokollGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
