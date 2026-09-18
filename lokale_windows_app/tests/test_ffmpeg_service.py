import os
import zipfile

import pytest

from services import ffmpeg_service


def test_find_ffmpeg_uses_system_path_first(monkeypatch):
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda name: "/usr/bin/ffmpeg" if "ffmpeg" in name else None)
    found = ffmpeg_service.find_ffmpeg()
    assert str(found) == "/usr/bin/ffmpeg"


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
