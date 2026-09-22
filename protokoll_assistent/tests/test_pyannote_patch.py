import py_compile

from protokoll_assistent.utils import pyannote_patch

FAKE_POOLING_PY = '''"""Dummy-Modul, das die relevante Funktion aus pyannote/audio nachbildet."""
import torch


class StatsPool(torch.nn.Module):
    def forward(self, sequences, weights=None):
        mean = sequences.mean(dim=-1)
        std = sequences.std(dim=-1, correction=1)
        return torch.cat([mean, std], dim=-1)
'''


def _write_fake_pooling_file(tmp_path):
    target = tmp_path / "pooling.py"
    target.write_text(FAKE_POOLING_PY, encoding="utf-8")
    return target


def test_apply_patch_replaces_unique_original_line(tmp_path):
    target = _write_fake_pooling_file(tmp_path)
    result = pyannote_patch.apply_patch(target)
    assert result.changed is True
    new_content = target.read_text(encoding="utf-8")
    assert pyannote_patch.MARKER in new_content
    assert "torch.zeros_like(mean)" in new_content
    # gueltiges Python bleibt gueltiges Python
    py_compile.compile(str(target), doraise=True)


def test_apply_patch_creates_backup(tmp_path):
    target = _write_fake_pooling_file(tmp_path)
    pyannote_patch.apply_patch(target)
    backups = list(tmp_path.glob("pooling.py.backup_*"))
    assert len(backups) == 1
    assert "std = sequences.std(dim=-1, correction=1)" in backups[0].read_text(encoding="utf-8")


def test_apply_patch_is_idempotent(tmp_path):
    target = _write_fake_pooling_file(tmp_path)
    first = pyannote_patch.apply_patch(target)
    assert first.changed is True
    content_after_first = target.read_text(encoding="utf-8")

    second = pyannote_patch.apply_patch(target)
    assert second.changed is False
    assert "bereits vorhanden" in second.message
    # Es wurde kein zweites Mal veraendert.
    assert target.read_text(encoding="utf-8") == content_after_first
    # Es entstand keine zweite Sicherungskopie.
    backups = list(tmp_path.glob("pooling.py.backup_*"))
    assert len(backups) == 1


def test_apply_patch_refuses_when_line_not_found(tmp_path):
    target = tmp_path / "pooling.py"
    target.write_text("print('kein Treffer hier')\n", encoding="utf-8")
    result = pyannote_patch.apply_patch(target)
    assert result.changed is False
    assert "nicht gefunden" in result.message
    assert target.read_text(encoding="utf-8") == "print('kein Treffer hier')\n"


def test_apply_patch_refuses_when_line_appears_multiple_times(tmp_path):
    target = tmp_path / "pooling.py"
    duplicated = FAKE_POOLING_PY + "\n        std = sequences.std(dim=-1, correction=1)\n"
    target.write_text(duplicated, encoding="utf-8")
    result = pyannote_patch.apply_patch(target)
    assert result.changed is False
    assert "nicht eindeutig" in result.message


def test_apply_patch_missing_file_reports_clear_message(tmp_path):
    result = pyannote_patch.apply_patch(tmp_path / "fehlt.py")
    assert result.changed is False
    assert "nicht gefunden" in result.message


def test_dry_run_does_not_modify_file(tmp_path):
    target = _write_fake_pooling_file(tmp_path)
    original = target.read_text(encoding="utf-8")
    result = pyannote_patch.apply_patch(target, dry_run=True)
    assert result.changed is True
    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("pooling.py.backup_*")) == []


def test_find_pooling_file_posix_layout(tmp_path):
    venv_dir = tmp_path / ".venv-whisperx"
    nested = venv_dir / "lib" / "python3.10" / "site-packages" / "pyannote" / "audio" / "models" / "blocks"
    nested.mkdir(parents=True)
    (nested / "pooling.py").write_text(FAKE_POOLING_PY, encoding="utf-8")
    found = pyannote_patch.find_pooling_file(venv_dir)
    assert found is not None
    assert found.name == "pooling.py"


def test_find_pooling_file_returns_none_when_missing(tmp_path):
    assert pyannote_patch.find_pooling_file(tmp_path) is None
