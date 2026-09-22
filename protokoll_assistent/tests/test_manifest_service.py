
from pathlib import Path

import pytest

from protokoll_assistent.services import manifest_service


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


def test_verwerfe_zwischenstaende_raeumt_alles_weg(tmp_path):
    work_dir = manifest_service.get_work_dir_for_file(tmp_path, "abc123")
    (work_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (work_dir / "audio_normalisiert.wav").write_bytes(b"RIFF")
    (work_dir / "transkripte" / "chunk_0001.json").write_text("[]", encoding="utf-8")
    (work_dir / "analysen" / "chunk_0001_analyse.json").write_text("{}", encoding="utf-8")
    (work_dir / "zusammengefuehrt" / "protokoll.json").write_text("{}", encoding="utf-8")
    (work_dir / "chunks" / "chunk_0001.wav").write_bytes(b"RIFF")

    manifest_service.verwerfe_zwischenstaende(work_dir)

    assert not (work_dir / "manifest.json").exists()
    assert not (work_dir / "audio_normalisiert.wav").exists()
    assert not (work_dir / "zusammengefuehrt" / "protokoll.json").exists()
    assert not (work_dir / "analysen" / "chunk_0001_analyse.json").exists()
    # Die Unterordner selbst bleiben bestehen, damit der naechste Lauf ohne
    # Sonderbehandlung hineinschreiben kann.
    for sub in manifest_service.SUBDIRS:
        assert (work_dir / sub).is_dir()


def test_verwerfe_zwischenstaende_laesst_fremde_dateien_in_ruhe(tmp_path):
    work_dir = manifest_service.get_work_dir_for_file(tmp_path, "abc123")
    fremd = work_dir / "notiz_des_nutzers.txt"
    fremd.write_text("nicht anfassen", encoding="utf-8")

    manifest_service.verwerfe_zwischenstaende(work_dir)

    assert fremd.read_text(encoding="utf-8") == "nicht anfassen"


def test_verwerfe_zwischenstaende_auf_leerem_ordner(tmp_path):
    # Erster Lauf ueberhaupt: Es gibt noch nichts zu verwerfen.
    manifest_service.verwerfe_zwischenstaende(tmp_path / "neu")
    assert (tmp_path / "neu" / "chunks").is_dir()


# --------------------------------------------------------------------------
# Manifest schreiben: Wiederholung bei kurzzeitig blockierter Datei (Windows)
# --------------------------------------------------------------------------
def test_manifest_schreiben_wiederholt_bei_blockierter_datei(tmp_path, sample_file, monkeypatch):
    """Ein Virenscanner oder der Suchindex haelt die frisch geschriebene
    Datei kurz offen - 'os.replace' meldet dann WinError 5, obwohl mit den
    Rechten alles stimmt. Ohne Wiederholung reisst das mitten in einer
    langen Verarbeitung den ganzen Lauf ab, und zwar genau beim Sichern des
    Fortschritts."""
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = manifest_service.create_manifest(
        sample_file, "abc123", 1500.0, 600.0, 10.0, 0, [], {"sprache": "de"}
    )

    versuche = {"n": 0}
    echtes_replace = Path.replace

    def sperrig(selbst, ziel):
        versuche["n"] += 1
        if versuche["n"] < 3:
            raise PermissionError(5, "Zugriff verweigert")
        return echtes_replace(selbst, ziel)

    monkeypatch.setattr(Path, "replace", sperrig)
    monkeypatch.setattr(manifest_service.time, "sleep", lambda _s: None)

    manifest_service.save_manifest(work_dir, manifest)

    assert versuche["n"] == 3
    assert manifest_service.load_manifest(work_dir) is not None


def test_manifest_schreiben_gibt_dauerhafte_sperre_weiter(tmp_path, sample_file, monkeypatch):
    """Gegenprobe: Bleibt die Datei gesperrt, wird der Fehler nicht
    verschluckt - ein stillschweigend verlorener Fortschritt waere
    schlimmer als ein sichtbarer Abbruch."""
    work_dir = tmp_path / "arbeit"
    work_dir.mkdir()
    manifest = manifest_service.create_manifest(
        sample_file, "abc123", 1500.0, 600.0, 10.0, 0, [], {"sprache": "de"}
    )

    monkeypatch.setattr(Path, "replace", lambda selbst, ziel: (_ for _ in ()).throw(PermissionError(5, "gesperrt")))
    monkeypatch.setattr(manifest_service.time, "sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        manifest_service.save_manifest(work_dir, manifest)
