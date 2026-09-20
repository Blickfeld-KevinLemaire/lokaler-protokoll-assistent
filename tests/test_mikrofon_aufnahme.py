"""Tests fuer die Mikrofonaufnahme (Voice Recording) der Cloud-Variante.

Es wird nirgends ein echtes Audiogeraet angesprochen: 'liste_aufnahmegeraete'
bekommt Fake-Abfragefunktionen uebergeben, 'MikrofonAufnahme' einen Fake-
Stream. Das entspricht dem im Projekt ueblichen Muster, ML-/Hardware-Aufrufe
als Parameter zu uebergeben, damit sie in Tests ersetzt werden koennen.
"""

from __future__ import annotations

import array
import json
import re
import time
import wave
from typing import ClassVar

import pytest

import mikrofon_aufnahme as ma


def _fake_query_devices():
    return [
        {"name": "Lautsprecher", "index": 0, "hostapi": 0, "max_input_channels": 0, "default_samplerate": 48000.0},
        {
            "name": "ReSpeaker USB Mic Array",
            "index": 1,
            "hostapi": 0,
            "max_input_channels": 6,
            "default_samplerate": 16000.0,
        },
        {"name": "Headset-Mikrofon", "index": 2, "hostapi": 1, "max_input_channels": 1, "default_samplerate": 44100.0},
    ]


def _fake_query_hostapis():
    return [{"name": "Windows WASAPI"}, {"name": "Windows DirectSound"}]


# --------------------------------------------------------------------------
# Geraeteliste
# --------------------------------------------------------------------------
def test_liste_aufnahmegeraete_filtert_ausgabegeraete():
    geraete = ma.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    assert [g.name for g in geraete] == ["ReSpeaker USB Mic Array", "Headset-Mikrofon"]
    assert geraete[0].anzeigename == "ReSpeaker USB Mic Array (Windows WASAPI)"


def test_liste_aufnahmegeraete_ohne_geraete():
    assert ma.liste_aufnahmegeraete(lambda: [], _fake_query_hostapis) == []


# --------------------------------------------------------------------------
# Startauswahl / Fallback
# --------------------------------------------------------------------------
def test_waehle_startgeraet_ohne_geraete():
    geraet, hinweis = ma.waehle_startgeraet([], gespeichert=None)
    assert geraet is None
    assert hinweis is None


def test_waehle_startgeraet_gespeichertes_geraet_gefunden():
    geraete = ma.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, hinweis = ma.waehle_startgeraet(
        geraete, gespeichert="ReSpeaker USB Mic Array (Windows WASAPI)"
    )
    assert geraet is not None
    assert geraet.name == "ReSpeaker USB Mic Array"
    assert hinweis is None


def test_waehle_startgeraet_faellt_auf_standardgeraet_zurueck():
    geraete = ma.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, hinweis = ma.waehle_startgeraet(
        geraete, gespeichert="Nicht mehr angeschlossenes Geraet", standard_index=2
    )
    assert geraet is not None
    assert geraet.name == "Headset-Mikrofon"
    assert hinweis is not None
    assert "nicht mehr verfuegbar" in hinweis


def test_waehle_startgeraet_ohne_gespeichertes_geraet_nimmt_standard():
    geraete = ma.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, hinweis = ma.waehle_startgeraet(geraete, gespeichert=None, standard_index=2)
    assert geraet is not None
    assert geraet.name == "Headset-Mikrofon"
    assert hinweis is None


def test_waehle_startgeraet_ohne_treffer_fuer_standardindex_nimmt_erstes():
    geraete = ma.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, _hinweis = ma.waehle_startgeraet(geraete, gespeichert=None, standard_index=99)
    assert geraet is not None
    assert geraet.name == "ReSpeaker USB Mic Array"


# --------------------------------------------------------------------------
# Konfiguration (rechnerspezifisch gespeicherte Geraeteauswahl)
# --------------------------------------------------------------------------
def test_geraet_speichern_und_laden(monkeypatch, tmp_path):
    konfig_datei = tmp_path / "mikrofon_konfiguration.json"
    monkeypatch.setattr(ma, "KONFIG_DATEI", konfig_datei)

    assert ma.lade_gespeichertes_geraet() is None

    ma.speichere_geraet("Headset-Mikrofon (Windows DirectSound)")

    assert json.loads(konfig_datei.read_text(encoding="utf-8")) == {
        "anzeigename": "Headset-Mikrofon (Windows DirectSound)"
    }
    assert ma.lade_gespeichertes_geraet() == "Headset-Mikrofon (Windows DirectSound)"


def test_geraet_laden_bei_kaputter_datei(monkeypatch, tmp_path):
    konfig_datei = tmp_path / "mikrofon_konfiguration.json"
    konfig_datei.write_text("{kein gueltiges json", encoding="utf-8")
    monkeypatch.setattr(ma, "KONFIG_DATEI", konfig_datei)

    assert ma.lade_gespeichertes_geraet() is None


def test_standard_eingabe_index_ohne_geraet(monkeypatch):
    class _FakeDefault:
        device = (-1, -1)

    monkeypatch.setattr(ma.sd, "default", _FakeDefault())
    assert ma.standard_eingabe_index() is None


def test_standard_eingabe_index_mit_geraet(monkeypatch):
    class _FakeDefault:
        device = (2, 3)

    monkeypatch.setattr(ma.sd, "default", _FakeDefault())
    assert ma.standard_eingabe_index() == 2


def test_erzeuge_dateiname_format():
    name = ma.erzeuge_dateiname()
    assert re.fullmatch(r"Aufnahme_\d{8}_\d{6}\.wav", name)


# --------------------------------------------------------------------------
# MikrofonAufnahme (Aufnahme-Lebenszyklus)
# --------------------------------------------------------------------------
class _FakeStream:
    """Ruft den Callback synchron beim Start auf - kein echtes Geraet noetig."""

    instanzen: ClassVar[list[_FakeStream]] = []

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.gestartet = False
        self.gestoppt = False
        self.geschlossen = False
        _FakeStream.instanzen.append(self)

    def start(self):
        self.gestartet = True
        chunk = array.array("h", [1000, -2000, 3000, -4000]).tobytes()
        self.callback(chunk, 4, None, None)

    def stop(self):
        self.gestoppt = True

    def close(self):
        self.geschlossen = True


@pytest.fixture
def geraet():
    return ma.Aufnahmegeraet(index=1, name="Test-Mikro", hostapi_name="WASAPI", default_samplerate=16000.0)


def test_aufnahme_schreibt_wav_mit_erwarteten_parametern(geraet, tmp_path):
    zielpfad = tmp_path / "test.wav"
    aufnahme = ma.MikrofonAufnahme(geraet, zielpfad, stream_klasse=_FakeStream)
    aufnahme.start()
    time.sleep(0.05)
    ergebnis = aufnahme.stop()

    assert ergebnis == zielpfad
    assert ergebnis.is_file()
    with wave.open(str(ergebnis), "rb") as wav_datei:
        assert wav_datei.getnchannels() == 1
        assert wav_datei.getsampwidth() == 2
        assert wav_datei.getframerate() == 16000
        assert wav_datei.getnframes() == 4


def test_aufnahme_pegel_wird_aus_rohdaten_berechnet(geraet, tmp_path):
    aufnahme = ma.MikrofonAufnahme(geraet, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    time.sleep(0.05)
    assert aufnahme.pegel == pytest.approx(4000 / 32768, abs=1e-6)
    aufnahme.stop()


def test_aufnahme_pause_schreibt_keine_frames(geraet, tmp_path):
    aufnahme = ma.MikrofonAufnahme(geraet, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    time.sleep(0.05)
    dauer_vor_pause = aufnahme.dauer_sekunden

    aufnahme.pause()
    assert aufnahme.ist_pausiert
    stille = array.array("h", [0, 0, 0, 0]).tobytes()
    aufnahme._callback(stille, 4, None, None)
    time.sleep(0.05)
    assert aufnahme.dauer_sekunden == dauer_vor_pause

    aufnahme.fortsetzen()
    assert not aufnahme.ist_pausiert
    aufnahme._callback(stille, 4, None, None)
    time.sleep(0.05)
    assert aufnahme.dauer_sekunden > dauer_vor_pause

    aufnahme.stop()


def test_aufnahme_stop_schliesst_stream(geraet, tmp_path):
    _FakeStream.instanzen.clear()
    aufnahme = ma.MikrofonAufnahme(geraet, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    aufnahme.stop()

    assert len(_FakeStream.instanzen) == 1
    stream = _FakeStream.instanzen[0]
    assert stream.gestoppt
    assert stream.geschlossen


def test_aufnahme_ohne_samplerate_faellt_auf_standard_zurueck(tmp_path):
    geraet_ohne_rate = ma.Aufnahmegeraet(index=1, name="X", hostapi_name="Y", default_samplerate=0.0)
    aufnahme = ma.MikrofonAufnahme(geraet_ohne_rate, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    aufnahme.stop()
    with wave.open(str(tmp_path / "test.wav"), "rb") as wav_datei:
        assert wav_datei.getframerate() == ma.STANDARD_SAMPLERATE
