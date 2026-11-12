"""Tests fuer die Mikrofonaufnahme (Voice Recording) der lokalen Variante.

Es wird nirgends ein echtes Audiogeraet angesprochen: 'liste_aufnahmegeraete'
bekommt Fake-Abfragefunktionen uebergeben, 'MikrofonAufnahme' einen Fake-
Stream - dasselbe Muster wie bei den anderen Diensten in 'services/', die
ihre ML-/Hardware-Aufrufe als Parameter entgegennehmen.
"""

from __future__ import annotations

import array
import re
import time
import wave
from typing import ClassVar

import pytest

from protokoll_assistent.services import recording_service as rs


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


def test_liste_aufnahmegeraete_filtert_ausgabegeraete():
    geraete = rs.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    assert [g.name for g in geraete] == ["ReSpeaker USB Mic Array", "Headset-Mikrofon"]
    assert geraete[0].anzeigename == "ReSpeaker USB Mic Array (Windows WASAPI)"


def test_waehle_startgeraet_faellt_auf_standardgeraet_zurueck():
    geraete = rs.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, hinweis = rs.waehle_startgeraet(
        geraete, gespeichert="Nicht mehr angeschlossenes Geraet", standard_index=2
    )
    assert geraet is not None
    assert geraet.name == "Headset-Mikrofon"
    assert hinweis is not None
    assert "nicht mehr verfuegbar" in hinweis


def test_waehle_startgeraet_gespeichertes_geraet_gefunden():
    geraete = rs.liste_aufnahmegeraete(_fake_query_devices, _fake_query_hostapis)
    geraet, hinweis = rs.waehle_startgeraet(
        geraete, gespeichert="ReSpeaker USB Mic Array (Windows WASAPI)"
    )
    assert geraet is not None
    assert geraet.name == "ReSpeaker USB Mic Array"
    assert hinweis is None


def test_waehle_startgeraet_ohne_geraete():
    assert rs.waehle_startgeraet([], gespeichert=None) == (None, None)


def test_standard_eingabe_index_ohne_geraet(monkeypatch):
    class _FakeDefault:
        device = (-1, -1)

    monkeypatch.setattr(rs.sd, "default", _FakeDefault())
    assert rs.standard_eingabe_index() is None


def test_erzeuge_dateiname_format():
    assert re.fullmatch(r"Aufnahme_\d{8}_\d{6}\.wav", rs.erzeuge_dateiname())


class _FakeStream:
    """Ruft den Callback synchron beim Start auf - kein echtes Geraet noetig."""

    instanzen: ClassVar[list[_FakeStream]] = []

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.gestoppt = False
        self.geschlossen = False
        _FakeStream.instanzen.append(self)

    def start(self):
        chunk = array.array("h", [1000, -2000, 3000, -4000]).tobytes()
        self.callback(chunk, 4, None, None)

    def stop(self):
        self.gestoppt = True

    def close(self):
        self.geschlossen = True


@pytest.fixture
def geraet():
    return rs.Aufnahmegeraet(index=1, name="Test-Mikro", hostapi_name="WASAPI", default_samplerate=16000.0)


def test_aufnahme_schreibt_wav_mit_erwarteten_parametern(geraet, tmp_path):
    zielpfad = tmp_path / "test.wav"
    aufnahme = rs.MikrofonAufnahme(geraet, zielpfad, stream_klasse=_FakeStream)
    aufnahme.start()
    time.sleep(0.05)
    ergebnis = aufnahme.stop()

    assert ergebnis == zielpfad
    with wave.open(str(ergebnis), "rb") as wav_datei:
        assert wav_datei.getnchannels() == 1
        assert wav_datei.getsampwidth() == 2
        assert wav_datei.getframerate() == 16000
        assert wav_datei.getnframes() == 4


def test_aufnahme_pause_schreibt_keine_frames(geraet, tmp_path):
    aufnahme = rs.MikrofonAufnahme(geraet, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    time.sleep(0.05)
    dauer_vor_pause = aufnahme.dauer_sekunden

    aufnahme.pause()
    stille = array.array("h", [0, 0, 0, 0]).tobytes()
    aufnahme._callback(stille, 4, None, None)
    time.sleep(0.05)
    assert aufnahme.dauer_sekunden == dauer_vor_pause

    aufnahme.fortsetzen()
    aufnahme._callback(stille, 4, None, None)
    time.sleep(0.05)
    assert aufnahme.dauer_sekunden > dauer_vor_pause

    aufnahme.stop()


def test_aufnahme_stop_schliesst_stream(geraet, tmp_path):
    _FakeStream.instanzen.clear()
    aufnahme = rs.MikrofonAufnahme(geraet, tmp_path / "test.wav", stream_klasse=_FakeStream)
    aufnahme.start()
    aufnahme.stop()

    stream = _FakeStream.instanzen[0]
    assert stream.gestoppt
    assert stream.geschlossen


# --------------------------------------------------------------------------
# Fehler beim Schreiben und beim Oeffnen des Geraets
# --------------------------------------------------------------------------
def test_schreibfehler_wird_gemerkt_und_beim_stoppen_gemeldet(geraet, tmp_path, monkeypatch):
    # Frueher endete der Schreibfaden lautlos: Die Aufnahme "lief" weiter und fuellte nur noch den Arbeitsspeicher.
    aufnahme = rs.MikrofonAufnahme(geraet, tmp_path / "voll.wav", stream_klasse=_FakeStream)

    def voll(self, daten):
        raise OSError(28, "Kein Speicherplatz mehr")

    monkeypatch.setattr(wave.Wave_write, "writeframes", voll)
    aufnahme.start()
    ende = time.monotonic() + 5
    while aufnahme.fehler is None and time.monotonic() < ende:
        time.sleep(0.01)
    assert "Speicherplatz" in (aufnahme.fehler or "")

    # Nach dem Fehler wird nichts mehr eingereiht.
    stream = _FakeStream.instanzen[-1]
    stream.callback(array.array("h", [1, 2, 3, 4]).tobytes(), 4, None, None)
    assert aufnahme._queue.qsize() == 0

    with pytest.raises(OSError, match="nicht vollständig geschrieben"):
        aufnahme.stop()
    assert stream.gestoppt and stream.geschlossen


def test_nicht_oeffenbares_geraet_hinterlaesst_keine_leere_gesperrte_datei(geraet, tmp_path):
    class _Belegt:
        def __init__(self, **kwargs):
            raise RuntimeError("Geraet belegt")

    zielpfad = tmp_path / "leer.wav"
    aufnahme = rs.MikrofonAufnahme(geraet, zielpfad, stream_klasse=_Belegt)
    with pytest.raises(RuntimeError, match="belegt"):
        aufnahme.start()
    assert not zielpfad.exists()
    assert aufnahme._schreiber is not None and not aufnahme._schreiber.is_alive()
