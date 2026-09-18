import json

import pytest

from services import manifest_service


@pytest.fixture()
def sample_file(tmp_path):
    path = tmp_path / "quelle.wav"
    path.write_bytes(b"x" * 1000)
    return path


def test_compute_file_hash_stable(sample_file):
    first = manifest_service.compute_file_hash(sample_file)
    second = manifest_service.compute_file_hash(sample_file)
    assert first == second
    assert len(first) == 64  # sha256 hex digest


def test_compute_file_hash_changes_with_content(sample_file):
    original = manifest_service.compute_file_hash(sample_file)
    sample_file.write_bytes(b"y" * 1000)
    changed = manifest_service.compute_file_hash(sample_file)
    assert original != changed


def test_work_dir_creates_expected_subdirs(tmp_path, sample_file):
    file_hash = manifest_service.compute_file_hash(sample_file)
    work_dir = manifest_service.get_work_dir_for_file(tmp_path, file_hash)
    for sub in manifest_service.SUBDIRS:
        assert (work_dir / sub).is_dir()


def _make_manifest(sample_file, work_dir):
    chunk_bounds = [
        {"index": 0, "global_start": 0.0, "global_end": 600.0},
        {"index": 1, "global_start": 590.0, "global_end": 1190.0},
        {"index": 2, "global_start": 1180.0, "global_end": 1500.0},
    ]
    manifest = manifest_service.create_manifest(
        sample_file, "abc123", 1500.0, 600.0, 10.0, 3, chunk_bounds, {"sprache": "de"}
    )
    manifest_service.save_manifest(work_dir, manifest)
    return manifest


def test_save_and_load_manifest_roundtrip(tmp_path, sample_file):
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    original = _make_manifest(sample_file, work_dir)
    loaded = manifest_service.load_manifest(work_dir)
    assert loaded is not None
    assert loaded["dateihash"] == original["dateihash"]
    assert loaded["anzahl_chunks"] == 3


def test_load_manifest_returns_none_when_missing(tmp_path):
    assert manifest_service.load_manifest(tmp_path) is None


def test_resume_detects_finished_and_next_chunk(tmp_path, sample_file):
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = _make_manifest(sample_file, work_dir)

    manifest_service.update_chunk_status(manifest, 0, manifest_service.STATUS_ABGESCHLOSSEN)
    manifest_service.update_chunk_status(manifest, 1, manifest_service.STATUS_FEHLGESCHLAGEN, "Testfehler")
    manifest_service.save_manifest(work_dir, manifest)

    state = manifest_service.find_resumable_state(manifest)
    assert state["fertige_chunks"] == [0]
    assert state["naechster_chunk"] == 1
    assert state["letzter_fehler"]["index"] == 1
    assert state["letzter_fehler"]["fehler"] == "Testfehler"
    assert state["vollstaendig"] is False


def test_already_finished_chunks_are_not_recomputed_on_resume(tmp_path, sample_file):
    """Simuliert einen Abbruch nach Chunk 0: Chunk 0 bleibt abgeschlossen und
    darf beim Fortsetzen nicht erneut als 'naechster_chunk' erscheinen."""
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = _make_manifest(sample_file, work_dir)
    manifest_service.update_chunk_status(manifest, 0, manifest_service.STATUS_ABGESCHLOSSEN)
    manifest_service.save_manifest(work_dir, manifest)

    reloaded = manifest_service.load_manifest(work_dir)
    state = manifest_service.find_resumable_state(reloaded)
    assert 0 in state["fertige_chunks"]
    assert state["naechster_chunk"] == 1


def test_is_fully_processed(tmp_path, sample_file):
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = _make_manifest(sample_file, work_dir)
    assert manifest_service.is_fully_processed(manifest) is False
    for index in range(3):
        manifest_service.update_chunk_status(manifest, index, manifest_service.STATUS_ABGESCHLOSSEN)
    assert manifest_service.is_fully_processed(manifest) is True


def test_save_manifest_is_atomic_leaves_no_tmp_files(tmp_path, sample_file):
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    _make_manifest(sample_file, work_dir)
    tmp_files = list(work_dir.glob("*.tmp"))
    assert tmp_files == []
    assert manifest_service.manifest_path(work_dir).is_file()


def test_update_unknown_chunk_raises(tmp_path, sample_file):
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = _make_manifest(sample_file, work_dir)
    with pytest.raises(KeyError):
        manifest_service.update_chunk_status(manifest, 99, manifest_service.STATUS_ABGESCHLOSSEN)
