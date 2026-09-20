"""FFmpeg-/ffprobe-Erkennung, Audionormalisierung und Chunk-Aufteilung.

Suchreihenfolge fuer FFmpeg/ffprobe (verbindlich):
1. System-PATH,
2. WinGet-Paketverzeichnis unter %LOCALAPPDATA%,
3. optionaler Ordner ``tools\\ffmpeg`` neben der Anwendung.

Das vorhandene FFmpeg wird niemals veraendert oder deinstalliert -- es wird
ausschliesslich lesend gesucht und aufgerufen. Alle Aufrufe verwenden
Argumentlisten (kein ``shell=True``), damit keine nicht validierten
Benutzereingaben in eine Shell interpretiert werden koennen.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from utils.paths import get_tools_ffmpeg_dir

# Stabiler "latest"-Redirect-Link (aendert sich inhaltlich, aber nicht in
# der URL selbst) auf einen offiziellen, statisch gelinkten Windows-Build.
# Wird NUR verwendet, wenn auf dem Zielrechner weder im PATH, noch ueber
# WinGet, noch unter 'tools\\ffmpeg' bereits ein FFmpeg gefunden wurde --
# macht die Anwendung auch auf einem PC ohne vorinstalliertes FFmpeg
# eigenstaendig lauffaehig. Das vorhandene System-FFmpeg wird dadurch nie
# veraendert oder ersetzt.
FFMPEG_PORTABLE_DOWNLOAD_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

DownloadFn = Callable[[str, Path], None]


def _winget_packages_dir() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"


def _search_winget_for(executable_name: str) -> Path | None:
    packages_dir = _winget_packages_dir()
    if not packages_dir or not packages_dir.is_dir():
        return None
    matches = sorted(packages_dir.glob(f"**/{executable_name}"))
    return matches[0] if matches else None


def _search_tools_dir_for(executable_name: str) -> Path | None:
    tools_dir = get_tools_ffmpeg_dir()
    if not tools_dir.is_dir():
        return None
    matches = sorted(tools_dir.glob(f"**/{executable_name}"))
    return matches[0] if matches else None


def _find_executable(name_unix: str, name_windows: str) -> Path | None:
    on_path = shutil.which(name_unix) or shutil.which(name_windows)
    if on_path:
        return Path(on_path)

    from_winget = _search_winget_for(name_windows)
    if from_winget:
        return from_winget

    from_tools = _search_tools_dir_for(name_windows) or _search_tools_dir_for(name_unix)
    if from_tools:
        return from_tools

    return None


def find_ffmpeg() -> Path | None:
    return _find_executable("ffmpeg", "ffmpeg.exe")


def find_ffprobe() -> Path | None:
    return _find_executable("ffprobe", "ffprobe.exe")


def ensure_ffmpeg_on_path() -> Path | None:
    """Stellt sicher, dass ``ffmpeg``/``ffprobe`` im PATH des aktuellen Prozesses
    auffindbar sind (die Normalisierung ruft ``ffmpeg`` per Subprozessname auf).
    Gibt den gefundenen ffmpeg-Pfad zurueck, oder ``None`` falls nicht gefunden.
    """
    found = find_ffmpeg()
    if not found:
        return None
    directory = str(found.parent)
    current_path = os.environ.get("PATH", "")
    if directory not in current_path.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + current_path
    return found


def _default_download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as response, destination.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)


def extract_ffmpeg_zip(zip_path: Path, target_dir: Path) -> Path:
    """Entpackt ``ffmpeg.exe``/``ffprobe.exe`` (egal in welcher Unterordner-
    Tiefe im ZIP) nach ``target_dir``. Gibt den Pfad zur extrahierten
    ``ffmpeg.exe`` zurueck."""
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted_ffmpeg: Path | None = None
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            member_name = Path(member).name
            if member_name.lower() not in ("ffmpeg.exe", "ffprobe.exe"):
                continue
            destination = target_dir / member_name
            with archive.open(member) as source_file, destination.open("wb") as out_file:
                shutil.copyfileobj(source_file, out_file)
            if member_name.lower() == "ffmpeg.exe":
                extracted_ffmpeg = destination

    if extracted_ffmpeg is None:
        raise RuntimeError(
            "Im heruntergeladenen FFmpeg-Paket wurde keine 'ffmpeg.exe' gefunden."
        )
    return extracted_ffmpeg


def download_portable_ffmpeg(
    target_dir: Path | None = None,
    download_fn: DownloadFn | None = None,
    url: str = FFMPEG_PORTABLE_DOWNLOAD_URL,
) -> Path:
    """Laedt einen portablen FFmpeg-Build herunter und legt ihn unter
    ``tools\\ffmpeg`` ab. Wird nur aufgerufen, wenn FFmpeg auf dem Zielrechner
    nirgends gefunden werden konnte (siehe ``ensure_ffmpeg_available``)."""
    target_dir = target_dir or get_tools_ffmpeg_dir()
    download_fn = download_fn or _default_download

    with tempfile.TemporaryDirectory(prefix="ffmpeg_download_") as temp_dir:
        zip_path = Path(temp_dir) / "ffmpeg.zip"
        download_fn(url, zip_path)
        return extract_ffmpeg_zip(zip_path, target_dir)


def ensure_ffmpeg_available(
    auto_download: bool = True,
    download_fn: DownloadFn | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> Path | None:
    """Sucht FFmpeg in der vorgeschriebenen Reihenfolge; laedt es bei Bedarf
    (und mit Erlaubnis) als portablen Build herunter. Das vorhandene FFmpeg
    des Systems wird dabei nie anfasst -- ein Download landet ausschliesslich
    unter 'tools\\ffmpeg' neben der Anwendung."""
    log = progress_cb or (lambda message: None)

    found = find_ffmpeg()
    if found:
        log(f"FFmpeg gefunden: {found}")
        return found

    if not auto_download:
        return None

    log("FFmpeg wurde nicht gefunden -- lade portable Version herunter ...")
    try:
        ffmpeg_path = download_portable_ffmpeg(download_fn=download_fn)
    except (OSError, RuntimeError) as error:
        log(f"FFmpeg-Download fehlgeschlagen: {error}")
        return None

    log(f"FFmpeg heruntergeladen nach: {ffmpeg_path}")
    return ensure_ffmpeg_on_path()


def _unfertiger_pfad(ziel: Path) -> Path:
    """Arbeitsname, unter dem FFmpeg waehrend des Schreibens ausgibt.

    Die Endung bleibt erhalten, damit FFmpeg das Ausgabeformat weiterhin
    daran erkennt.
    """
    return ziel.with_name(f"{ziel.stem}.unfertig{ziel.suffix}")


def _fertigstellen(unfertig: Path, ziel: Path) -> None:
    """Benennt die fertige Datei an ihren endgueltigen Platz um.

    Erst nach diesem Schritt existiert der Zielpfad. Bricht der Rechner
    vorher ab, bleibt nur die unfertige Datei liegen -- die Aufrufer
    pruefen mit ``exists()``, ob ein Schritt schon erledigt ist, und
    wuerden eine abgeschnittene Datei sonst stillschweigend
    weiterverwenden (zu kurzes Transkript ohne jede Fehlermeldung).
    """
    unfertig.replace(ziel)


def _unfertige_reste_entfernen(unfertig: Path) -> None:
    unfertig.unlink(missing_ok=True)


def get_tool_version(executable: Path) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        first_line = (completed.stdout or completed.stderr or "").splitlines()
        return first_line[0].strip() if first_line else "unbekannte Version"
    except (OSError, subprocess.SubprocessError) as error:
        return f"Version nicht ermittelbar ({error})"


def probe_duration_seconds(source: Path, ffprobe_path: Path | None = None) -> float:
    ffprobe_path = ffprobe_path or find_ffprobe()
    if not ffprobe_path:
        raise RuntimeError("ffprobe wurde nicht gefunden.")
    command = [
        str(ffprobe_path),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        str(source),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe konnte die Datei nicht lesen: {completed.stderr.strip()[-800:]}")
    try:
        data = json.loads(completed.stdout)
        return float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"ffprobe-Ausgabe konnte nicht ausgewertet werden: {error}") from error


def normalize_audio(
    source: Path,
    destination_wav: Path,
    ffmpeg_path: Path | None = None,
    sample_rate: int = 16000,
) -> Path:
    """Normalisiert Audio/Video reproduzierbar zu Mono/16kHz-WAV."""
    ffmpeg_path = ffmpeg_path or find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg wurde nicht gefunden.")
    destination_wav.parent.mkdir(parents=True, exist_ok=True)
    unfertig = _unfertiger_pfad(destination_wav)
    _unfertige_reste_entfernen(unfertig)
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(unfertig),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3600)
    if completed.returncode != 0 or not unfertig.exists():
        _unfertige_reste_entfernen(unfertig)
        raise RuntimeError(f"FFmpeg konnte die Datei nicht normalisieren: {completed.stderr.strip()[-1000:]}")
    _fertigstellen(unfertig, destination_wav)
    return destination_wav


def extract_chunk_wav(
    normalized_source: Path,
    destination_wav: Path,
    start_seconds: float,
    end_seconds: float,
    ffmpeg_path: Path | None = None,
    sample_rate: int = 16000,
) -> Path:
    """Schneidet einen Zeitbereich aus der normalisierten WAV-Datei aus.

    Es wird bewusst re-encodiert (kein Stream-Copy), damit der Schnitt
    sample-genau auf die geplanten Chunk-Grenzen faellt.
    """
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds muss groesser als start_seconds sein.")
    ffmpeg_path = ffmpeg_path or find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg wurde nicht gefunden.")
    destination_wav.parent.mkdir(parents=True, exist_ok=True)
    unfertig = _unfertiger_pfad(destination_wav)
    _unfertige_reste_entfernen(unfertig)
    duration = end_seconds - start_seconds
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", f"{start_seconds:.3f}",
        "-i", str(normalized_source),
        "-t", f"{duration:.3f}",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(unfertig),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)
    if completed.returncode != 0 or not unfertig.exists():
        _unfertige_reste_entfernen(unfertig)
        raise RuntimeError(f"FFmpeg konnte den Chunk nicht erstellen: {completed.stderr.strip()[-1000:]}")
    _fertigstellen(unfertig, destination_wav)
    return destination_wav
