from utils import app_config


def test_load_config_defaults_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    config = app_config.load_config()
    assert config == app_config.DEFAULTS


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    config_file = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: config_file)
    app_config.save_config({"eingabeordner": r"D:\Aufnahmen", "geraetepraeferenz": "cpu"})
    reloaded = app_config.load_config()
    assert reloaded["eingabeordner"] == r"D:\Aufnahmen"
    assert reloaded["geraetepraeferenz"] == "cpu"
    assert reloaded["ausgabeordner"] is None  # nicht gesetzte Felder bleiben Standard


def test_update_config_merges_existing_values(monkeypatch, tmp_path):
    config_file = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: config_file)
    app_config.update_config(eingabeordner="C:\\Eingabe")
    app_config.update_config(ausgabeordner="C:\\Ausgabe")
    final = app_config.load_config()
    assert final["eingabeordner"] == "C:\\Eingabe"
    assert final["ausgabeordner"] == "C:\\Ausgabe"


def test_update_config_rejects_unknown_key(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    with pytest.raises(KeyError):
        app_config.update_config(unbekannt="wert")


def test_corrupted_config_file_falls_back_to_defaults(monkeypatch, tmp_path):
    config_file = tmp_path / "konfiguration.json"
    config_file.write_text("{kaputt", encoding="utf-8")
    monkeypatch.setattr(app_config, "get_config_file", lambda: config_file)
    assert app_config.load_config() == app_config.DEFAULTS


def test_no_hf_token_key_exists_in_defaults():
    assert "hf_token" not in app_config.DEFAULTS
    assert "token" not in {key.lower() for key in app_config.DEFAULTS}
