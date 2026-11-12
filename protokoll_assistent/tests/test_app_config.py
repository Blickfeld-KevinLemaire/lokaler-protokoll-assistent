"""Tests fuer 'utils/app_config.py'.

Die Konfigurationsdatei liegt in jedem Test im Temp-Verzeichnis - es wird
nie die echte Datei neben der Anwendung gelesen oder geschrieben.

Wichtig an diesem Modul: 'app.py' ruft 'load_config()' auf MODULEBENE auf,
also noch bevor es ein Fenster gibt. Alles, was hier wirft, bricht den
Start ohne jede sichtbare Meldung ab (gestartet wird ueblicherweise mit
'pythonw', also ohne Konsole)."""

from __future__ import annotations

import pytest

from protokoll_assistent.utils import app_config


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


# --------------------------------------------------------------------------
# Schreiben und beschaedigte Dateien
# --------------------------------------------------------------------------
def test_speichern_ist_atomar_und_hinterlaesst_keine_arbeitsdatei(konfig_datei, monkeypatch):
    ersetzt = []
    echt = app_config._ersetzen_mit_wiederholung

    def ersetzen(temp, ziel):
        # Die fertige Datei entsteht erst durch das Ersetzen: Ein Absturz mittendrin laesst die alte unversehrt.
        assert temp.parent == ziel.parent and temp.suffix == ".tmp"
        ersetzt.append(ziel.name)
        echt(temp, ziel)

    monkeypatch.setattr(app_config, "_ersetzen_mit_wiederholung", ersetzen)
    app_config.update_config(geraete_empfang_port=9000)
    assert ersetzt == ["konfiguration.json"]
    assert [p.name for p in konfig_datei.parent.iterdir()] == ["konfiguration.json"]
    assert app_config.load_config()["geraete_empfang_port"] == 9000


def test_ersetzen_wiederholt_bei_gesperrter_datei(tmp_path, monkeypatch):
    """Ein Virenscanner haelt die frische Datei kurz offen (CLAUDE.md, Regel 1)."""
    from pathlib import Path

    temp, ziel = tmp_path / "a.tmp", tmp_path / "a.json"
    temp.write_text("{}", encoding="utf-8")
    versuche = []
    echt = Path.replace

    def gesperrt(self, target):
        versuche.append(1)
        if len(versuche) < 3:
            raise PermissionError(5, "Zugriff verweigert")
        return echt(self, target)

    monkeypatch.setattr(Path, "replace", gesperrt)
    monkeypatch.setattr(app_config.time, "sleep", lambda sekunden: None)
    app_config._ersetzen_mit_wiederholung(temp, ziel)
    assert len(versuche) == 3 and ziel.is_file() and not temp.exists()


def test_ersetzen_gibt_auf_und_raeumt_auf(tmp_path, monkeypatch):
    from pathlib import Path

    temp, ziel = tmp_path / "a.tmp", tmp_path / "a.json"
    temp.write_text("{}", encoding="utf-8")

    def gesperrt(self, target):
        raise PermissionError(5, "Zugriff verweigert")

    monkeypatch.setattr(Path, "replace", gesperrt)
    monkeypatch.setattr(app_config.time, "sleep", lambda sekunden: None)
    with pytest.raises(PermissionError):
        app_config._ersetzen_mit_wiederholung(temp, ziel)
    assert not temp.exists()


@pytest.mark.parametrize("inhalt", ['{"geraete_empfang_port": 90', "[1, 2, 3]", ""])
def test_beschaedigte_datei_wird_beiseitegelegt_statt_ueberschrieben(konfig_datei, inhalt):
    # Frueher galten still die Standardwerte, und das naechste Speichern ueberschrieb die Datei endgueltig --
    # samt angemeldeter Aufnahmegeraete und API-Einstellungen.
    konfig_datei.write_text(inhalt, encoding="utf-8")
    assert app_config.load_config() == app_config.DEFAULTS
    gesichert = konfig_datei.with_name("konfiguration.defekt.json")
    assert gesichert.read_text(encoding="utf-8") == inhalt
    assert not konfig_datei.exists()
    app_config.update_config(geraete_empfang_port=9001)
    assert gesichert.read_text(encoding="utf-8") == inhalt


def test_von_hand_mit_bom_gespeicherte_datei_wird_gelesen(konfig_datei):
    konfig_datei.write_bytes(b"\xef\xbb\xbf" + b'{"geraete_empfang_port": 9002}')
    assert app_config.load_config()["geraete_empfang_port"] == 9002
    assert not konfig_datei.with_name("konfiguration.defekt.json").exists()
