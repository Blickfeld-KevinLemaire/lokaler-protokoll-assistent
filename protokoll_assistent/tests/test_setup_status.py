import json

from protokoll_assistent.utils import setup_status


def test_load_status_missing_file_returns_default(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_status, "get_setup_status_file", lambda: tmp_path / "Einrichtungsstatus.json")
    status = setup_status.load_status()
    assert status == {"phasen": {}, "abgeschlossen": False}


def test_mark_phase_and_save_roundtrip(monkeypatch, tmp_path):
    status_file = tmp_path / "Einrichtungsstatus.json"
    monkeypatch.setattr(setup_status, "get_setup_status_file", lambda: status_file)

    status = setup_status.load_status()
    setup_status.mark_phase(status, "systempruefung", True, {"python_version": "3.10.11"})
    setup_status.save_status(status)

    reloaded = json.loads(status_file.read_text(encoding="utf-8"))
    assert reloaded["phasen"]["systempruefung"]["erfolgreich"] is True
    assert reloaded["abgeschlossen"] is False  # weitere Phasen fehlen noch


def test_is_fully_set_up_requires_all_phases(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_status, "get_setup_status_file", lambda: tmp_path / "status.json")
    status = setup_status.load_status()
    for phase in setup_status.PHASES:
        assert not setup_status.is_fully_set_up(status)
        setup_status.mark_phase(status, phase, True)
    assert setup_status.is_fully_set_up(status)
    assert setup_status.missing_phases(status) == []


def test_missing_phases_lists_only_unfinished():
    status = {"phasen": {"systempruefung": {"erfolgreich": True}}, "abgeschlossen": False}
    missing = setup_status.missing_phases(status)
    assert "systempruefung" not in missing
    assert "python_umgebung" in missing


def test_mark_phase_rejects_unknown_phase():
    import pytest

    status = {"phasen": {}, "abgeschlossen": False}
    with pytest.raises(ValueError):
        setup_status.mark_phase(status, "unbekannt", True)


def test_no_token_ever_stored_in_status(monkeypatch, tmp_path):
    status_file = tmp_path / "status.json"
    monkeypatch.setattr(setup_status, "get_setup_status_file", lambda: status_file)
    status = setup_status.load_status()
    setup_status.mark_phase(status, "modelle", True, {"pyannote_ok": True, "whisper_ok": True})
    setup_status.save_status(status)
    content = status_file.read_text(encoding="utf-8")
    assert "HF_TOKEN" not in content
    assert "hf_token" not in content.lower() or "token" not in json.loads(content)["phasen"]["modelle"]["details"]
