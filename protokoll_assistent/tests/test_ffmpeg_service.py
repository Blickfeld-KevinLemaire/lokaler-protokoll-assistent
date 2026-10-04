import os
import zipfile
from pathlib import Path

import pytest

from protokoll_assistent.services import ffmpeg_service


def test_find_ffmpeg_uses_system_path_first(monkeypatch):
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda name: "/usr/bin/ffmpeg" if "ffmpeg" in name else None)
    found = ffmpeg_service.find_ffmpeg()
    # Path-Vergleich statt String-Vergleich: unter Windows normalisiert
    # pathlib die Trenner zu "\\", der Test soll aber ueberall laufen.
    assert found == Path("/usr/bin/ffmpeg")


def test_find_ffmpeg_falls_back_to_winget_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda name: None)
    winget_dir = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_abc123" / "ffmpeg-7.0" / "bin"
    winget_dir.mkdir(parents=True)
    (winget_dir / "ffmpeg.exe").write_text("dummy")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    found = ffmpeg_service.find_ffmpeg()
    assert found is not None
    assert found.name == "ffmpeg.exe"


def test_find_ffmpeg_falls_back_to_tools_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    tools_dir = tmp_path / "tools" / "ffmpeg" / "bin"
    tools_dir.mkdir(parents=True)
    (tools_dir / "ffmpeg.exe").write_text("dummy")
    monkeypatch.setattr(ffmpeg_service, "get_tools_ffmpeg_dir", lambda: tmp_path / "tools" / "ffmpeg")
    found = ffmpeg_service.find_ffmpeg()
    assert found is not None
    assert found.name == "ffmpeg.exe"


def test_find_ffmpeg_returns_none_when_not_found_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(ffmpeg_service, "get_tools_ffmpeg_dir", lambda: tmp_path / "nirgendwo")
    assert ffmpeg_service.find_ffmpeg() is None


def test_ensure_ffmpeg_on_path_prepends_directory(monkeypatch, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("dummy")
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: fake_ffmpeg)
    monkeypatch.setenv("PATH", "/existing/path")
    ffmpeg_service.ensure_ffmpeg_on_path()
    assert str(tmp_path) in os.environ["PATH"].split(os.pathsep)


def test_extract_chunk_wav_rejects_invalid_range(tmp_path):
    with pytest.raises(ValueError):
        ffmpeg_service.extract_chunk_wav(tmp_path / "in.wav", tmp_path / "out.wav", 10.0, 5.0)


def _make_fake_ffmpeg_zip(zip_path, nested="ffmpeg-master-latest-win64-gpl/bin"):
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(f"{nested}/ffmpeg.exe", b"dummy-ffmpeg-binary")
        archive.writestr(f"{nested}/ffprobe.exe", b"dummy-ffprobe-binary")
        archive.writestr(f"{nested}/LICENSE.txt", b"license text -- should be ignored")


def test_extract_ffmpeg_zip_finds_nested_executables(tmp_path):
    zip_path = tmp_path / "ffmpeg.zip"
    _make_fake_ffmpeg_zip(zip_path)
    target_dir = tmp_path / "tools_ffmpeg"

    result = ffmpeg_service.extract_ffmpeg_zip(zip_path, target_dir)

    assert result == target_dir / "ffmpeg.exe"
    assert (target_dir / "ffmpeg.exe").read_bytes() == b"dummy-ffmpeg-binary"
    assert (target_dir / "ffprobe.exe").read_bytes() == b"dummy-ffprobe-binary"
    assert not (target_dir / "LICENSE.txt").exists()


def test_extract_ffmpeg_zip_raises_when_ffmpeg_missing(tmp_path):
    zip_path = tmp_path / "leer.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("readme.txt", b"kein ffmpeg hier")
    with pytest.raises(RuntimeError):
        ffmpeg_service.extract_ffmpeg_zip(zip_path, tmp_path / "ziel")


def test_download_portable_ffmpeg_uses_injected_download_fn(tmp_path):
    zip_source = tmp_path / "quelle.zip"
    _make_fake_ffmpeg_zip(zip_source)

    def fake_download(url, destination):
        destination.write_bytes(zip_source.read_bytes())

    target_dir = tmp_path / "tools_ffmpeg"
    result = ffmpeg_service.download_portable_ffmpeg(target_dir=target_dir, download_fn=fake_download)
    assert result == target_dir / "ffmpeg.exe"


def test_ensure_ffmpeg_available_skips_download_when_already_found(monkeypatch, tmp_path):
    existing = tmp_path / "ffmpeg"
    existing.write_text("dummy")
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: existing)
    download_calls = []
    monkeypatch.setattr(
        ffmpeg_service, "download_portable_ffmpeg", lambda **kwargs: download_calls.append(kwargs)
    )
    result = ffmpeg_service.ensure_ffmpeg_available()
    assert result == existing
    assert download_calls == []


def test_ensure_ffmpeg_available_downloads_when_missing_and_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(
        ffmpeg_service, "download_portable_ffmpeg", lambda **kwargs: tmp_path / "ffmpeg.exe"
    )
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_on_path", lambda: tmp_path / "ffmpeg.exe")
    result = ffmpeg_service.ensure_ffmpeg_available(auto_download=True)
    assert result == tmp_path / "ffmpeg.exe"


def test_ensure_ffmpeg_available_returns_none_without_auto_download(monkeypatch):
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)
    assert ffmpeg_service.ensure_ffmpeg_available(auto_download=False) is None


def test_ensure_ffmpeg_available_handles_download_failure_gracefully(monkeypatch):
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)

    def failing_download(**kwargs):
        raise RuntimeError("Netzwerkfehler")

    monkeypatch.setattr(ffmpeg_service, "download_portable_ffmpeg", failing_download)
    messages = []
    result = ffmpeg_service.ensure_ffmpeg_available(auto_download=True, progress_cb=messages.append)
    assert result is None
    assert any("fehlgeschlagen" in message for message in messages)


class _FFmpegAttrappe:
    """Ersetzt den FFmpeg-Aufruf und merkt sich den Ausgabepfad.

    Der letzte Eintrag der Argumentliste ist bei beiden Aufrufen der
    Zielpfad -- daran laesst sich pruefen, dass FFmpeg NICHT direkt auf die
    endgueltige Datei schreibt.
    """

    def __init__(self, returncode: int = 0, schreibt: bool = True) -> None:
        self.returncode = returncode
        self._schreibt = schreibt
        self.ausgabepfad: Path | None = None

    def __call__(self, command, **kwargs):
        self.ausgabepfad = Path(command[-1])
        if self._schreibt:
            self.ausgabepfad.write_bytes(b"RIFF-testdaten")
        return type("Abgeschlossen", (), {"returncode": self.returncode, "stderr": "fehler"})()


def test_normalize_audio_schreibt_erst_unter_arbeitsnamen(monkeypatch, tmp_path):
    # Bricht der Rechner mitten im Schreiben ab, darf keine abgeschnittene
    # 'audio_normalisiert.wav' zurueckbleiben: Der naechste Lauf pruefte nur
    # mit exists() und wuerde sie stillschweigend weiterverwenden.
    ffmpeg = _FFmpegAttrappe()
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "audio_normalisiert.wav"

    ffmpeg_service.normalize_audio(tmp_path / "quelle.mp3", ziel, ffmpeg_path=Path("ffmpeg"))

    assert ffmpeg.ausgabepfad is not None
    assert ffmpeg.ausgabepfad != ziel
    assert ffmpeg.ausgabepfad.suffix == ".wav"  # FFmpeg erkennt das Format an der Endung
    assert ziel.is_file()
    assert not ffmpeg.ausgabepfad.exists()  # umbenannt, nicht kopiert


def test_normalize_audio_hinterlaesst_bei_fehler_keine_zieldatei(monkeypatch, tmp_path):
    ffmpeg = _FFmpegAttrappe(returncode=1)
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "audio_normalisiert.wav"

    with pytest.raises(RuntimeError):
        ffmpeg_service.normalize_audio(tmp_path / "quelle.mp3", ziel, ffmpeg_path=Path("ffmpeg"))

    assert not ziel.exists()
    assert not (tmp_path / "audio_normalisiert.unfertig.wav").exists()


def test_extract_chunk_wav_schreibt_erst_unter_arbeitsnamen(monkeypatch, tmp_path):
    ffmpeg = _FFmpegAttrappe()
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "chunk_0001.wav"

    ffmpeg_service.extract_chunk_wav(
        tmp_path / "quelle.wav", ziel, 0.0, 600.0, ffmpeg_path=Path("ffmpeg")
    )

    assert ffmpeg.ausgabepfad != ziel
    assert ziel.is_file()


def test_extract_chunk_wav_hinterlaesst_bei_fehler_keine_zieldatei(monkeypatch, tmp_path):
    ffmpeg = _FFmpegAttrappe(returncode=1)
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "chunk_0001.wav"

    with pytest.raises(RuntimeError):
        ffmpeg_service.extract_chunk_wav(
            tmp_path / "quelle.wav", ziel, 0.0, 600.0, ffmpeg_path=Path("ffmpeg")
        )

    assert not ziel.exists()


def test_alte_unfertige_datei_wird_vor_dem_schreiben_entfernt(monkeypatch, tmp_path):
    # Rest eines abgebrochenen Laufs: darf den neuen Lauf nicht stoeren.
    rest = tmp_path / "audio_normalisiert.unfertig.wav"
    rest.write_bytes(b"abgeschnittener Rest")
    ffmpeg = _FFmpegAttrappe()
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "audio_normalisiert.wav"

    ffmpeg_service.normalize_audio(tmp_path / "quelle.mp3", ziel, ffmpeg_path=Path("ffmpeg"))

    assert ziel.read_bytes() == b"RIFF-testdaten"


def test_extract_speaker_audio_baut_atrim_concat_ueber_skriptdatei(monkeypatch, tmp_path):
    gesehen = {}

    def attrappe(command, **kwargs):
        skript = Path(command[command.index("-filter_complex_script") + 1])
        gesehen["filter"] = skript.read_text(encoding="utf-8")
        Path(command[-1]).write_bytes(b"RIFF-testdaten")
        return type("Abgeschlossen", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", attrappe)
    ziel = tmp_path / "sprecher.wav"

    ffmpeg_service.extract_speaker_audio(
        tmp_path / "q.wav", ziel, [(1.0, 2.5), (10.0, 12.0), (5.0, 5.0)], ffmpeg_path=Path("ffmpeg")
    )

    assert ziel.is_file()
    assert "atrim=start=1.000:end=2.500" in gesehen["filter"]
    assert "atrim=start=10.000:end=12.000" in gesehen["filter"]
    assert "concat=n=2:v=0:a=1[aus]" in gesehen["filter"]  # der leere Abschnitt entfaellt
    assert not list(tmp_path.glob("*.filter.txt"))  # Skriptdatei aufgeraeumt


def test_extract_speaker_audio_ohne_abschnitte_und_bei_fehler(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        ffmpeg_service.extract_speaker_audio(tmp_path / "q.wav", tmp_path / "o.wav", [], ffmpeg_path=Path("f"))

    ffmpeg = _FFmpegAttrappe(returncode=1)
    monkeypatch.setattr(ffmpeg_service.subprocess, "run", ffmpeg)
    ziel = tmp_path / "o.wav"
    with pytest.raises(RuntimeError):
        ffmpeg_service.extract_speaker_audio(tmp_path / "q.wav", ziel, [(0.0, 3.0)], ffmpeg_path=Path("f"))
    assert not ziel.exists()
    assert not list(tmp_path.glob("*.filter.txt"))


def test_extract_speaker_audio_ohne_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        ffmpeg_service.extract_speaker_audio(tmp_path / "q.wav", tmp_path / "o.wav", [(0.0, 1.0)])


def test_ensure_ffmpeg_available_meldet_kaputtes_paket_statt_abzustuerzen(monkeypatch):
    # Ein abgebrochener Download liefert kein gueltiges ZIP (BadZipFile ist weder
    # OSError noch RuntimeError) -- das darf die Einrichtung nicht abreissen.
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)

    def kaputt(**kwargs):
        raise zipfile.BadZipFile("File is not a zip file")

    monkeypatch.setattr(ffmpeg_service, "download_portable_ffmpeg", kaputt)
    meldungen = []
    assert ffmpeg_service.ensure_ffmpeg_available(progress_cb=meldungen.append) is None
    assert any("not a zip" in m for m in meldungen)
