"""Tests fuer 'utils/app_config.py' der vereinten Anwendung.

Nach demselben Muster wie 'lokale_windows_app/tests/test_app_config.py'.
Die Konfigurationsdatei liegt in jedem Test im Temp-Verzeichnis - es wird
nie die echte Datei neben der Anwendung gelesen oder geschrieben.

Wichtig an diesem Modul: 'app.py' ruft 'load_config()' auf MODULEBENE auf,
also noch bevor es ein Fenster gibt. Alles, was hier wirft, bricht den
Start ohne jede sichtbare Meldung ab (gestartet wird ueblicherweise mit
'pythonw', also ohne Konsole)."""

from __future__ import annotations

import pytest

from protokoll_assistent_vereint.utils import app_config


@pytest.fixture
def konfig_datei(tmp_path, monkeypatch):
    datei = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: datei)
    return datei


def test_ohne_datei_gelten_die_standardwerte(konfig_datei):
    assert app_config.load_config() == app_config.DEFAULTS
    assert not konfig_datei.exists()


def test_speichern_und_lesen(konfig_datei):
    app_config.save_config({**app_config.DEFAULTS, "ollama_modell": "qwen3:14b"})

    assert app_config.load_config()["ollama_modell"] == "qwen3:14b"


def test_update_config_meldet_unbekannten_schluessel(konfig_datei):
    with pytest.raises(KeyError, match="Unbekannter Konfigurationsschluessel"):
        app_config.update_config(gibt_es_nicht=1)


def test_unbekannte_schluessel_in_der_datei_werden_ignoriert(konfig_datei):
    konfig_datei.write_text('{"ollama_modell": "abc", "veraltet": 1}', encoding="utf-8")

    konfiguration = app_config.load_config()

    assert konfiguration["ollama_modell"] == "abc"
    assert "veraltet" not in konfiguration


def test_kaputte_datei_faellt_auf_die_standardwerte_zurueck(konfig_datei):
    konfig_datei.write_text("{kein gueltiges JSON", encoding="utf-8")

    assert app_config.load_config() == app_config.DEFAULTS


@pytest.mark.parametrize("inhalt", ["[1, 2, 3]", '"nur ein Text"', "42", "null"])
def test_gueltiges_json_ohne_objekt_faellt_auf_die_standardwerte_zurueck(konfig_datei, inhalt):
    """Gueltiges JSON, aber kein Objekt - etwa nach einem misslungenen
    Eingriff von Hand. Ohne Pruefung scheitert '.items()' mit einem
    'AttributeError', und zwar in 'app.py' noch vor dem ersten Fenster."""
    konfig_datei.write_text(inhalt, encoding="utf-8")

    assert app_config.load_config() == app_config.DEFAULTS


def test_fehlende_schluessel_werden_mit_standardwerten_ergaenzt(konfig_datei):
    """Eine Datei aus einer aelteren Fassung kennt neue Schluessel nicht."""
    konfig_datei.write_text('{"ollama_modell": "abc"}', encoding="utf-8")

    konfiguration = app_config.load_config()

    assert konfiguration["transkription_modus"] == app_config.DEFAULTS["transkription_modus"]
    assert set(konfiguration) == set(app_config.DEFAULTS)


def test_es_wird_nie_ein_schluessel_gespeichert(konfig_datei):
    """Gegenprobe zur Zusage im Modul-Docstring: In dieser Datei steht nur,
    OB gemerkt werden soll - der Schluessel selbst gehoert in
    'services/secret_store.py'."""
    app_config.save_config({**app_config.DEFAULTS, "api_transkription_schluessel_merken": True})

    inhalt = konfig_datei.read_text(encoding="utf-8")

    assert "schluessel_merken" in inhalt
    for verdaechtig in ("api_key", "password", "token", "secret"):
        assert verdaechtig not in inhalt.lower()
