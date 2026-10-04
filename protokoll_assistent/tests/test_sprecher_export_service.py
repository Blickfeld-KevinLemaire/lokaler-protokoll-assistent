import json
from pathlib import Path

import pytest

from protokoll_assistent.services import sprecher_export_service as se


def _json(tmp_path: Path, mit_audio: bool = True, turns=True) -> Path:
    audio = tmp_path / "audio_normalisiert.wav"
    if mit_audio:
        audio.write_bytes(b"RIFF")
    daten = {
        "quelldatei_stamm": "sitzung",
        "audio_pfad": str(audio),
        "sprecher_zuordnung": [
            {"sprecher_id": "SPEAKER_00", "anzeigename": "Anna: Leitung?"},
            {"sprecher_id": "SPEAKER_01", "anzeigename": "Ben"},
        ],
        "sprecher_turns": (
            [
                {"sprecher_id": "SPEAKER_00", "start_sekunden": 0.0, "ende_sekunden": 10.0},
                {"sprecher_id": "SPEAKER_01", "start_sekunden": 10.0, "ende_sekunden": 11.0},
                {"sprecher_id": "SPEAKER_00", "start_sekunden": 30.0, "ende_sekunden": 60.0},
            ]
            if turns
            else []
        ),
        "segmente": [
            {"start_sekunden": 1.0, "sprecher_id": "SPEAKER_00", "text": "Hallo"},
            {"start_sekunden": 10.5, "sprecher_id": "SPEAKER_01", "text": "Guten Tag"},
        ],
    }
    pfad = tmp_path / "t.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


def _schneider(aufrufe):
    def schneiden(audio, ziel, abschnitte):
        aufrufe.append((audio, ziel, abschnitte))
        ziel.write_bytes(b"WAV")
        return ziel

    return schneiden


def test_hoerprobe_waehlt_laengste_abschnitte_bis_zur_grenze():
    abschnitte = [(0.0, 5.0), (10.0, 40.0), (50.0, 53.0), (60.0, 60.5)]
    assert se.hoerprobe_auswaehlen(abschnitte, 20.0) == [(10.0, 30.0)]
    assert se.hoerprobe_auswaehlen(abschnitte, 33.0) == [(0.0, 3.0), (10.0, 40.0)]


def test_hoerprobe_nimmt_kurze_abschnitte_wenn_es_nur_solche_gibt():
    assert se.hoerprobe_auswaehlen([(0.0, 0.5), (3.0, 3.8)], 20.0) == [(0.0, 0.5), (3.0, 3.8)]


def test_hoerprobe_erstellen_schneidet_aus_der_audiodatei(tmp_path):
    aufrufe = []
    ziel = tmp_path / "probe.wav"
    se.hoerprobe_erstellen(_json(tmp_path), "SPEAKER_00", ziel, 15.0, _schneider(aufrufe))
    audio, gewaehlt_ziel, abschnitte = aufrufe[0]
    assert audio == tmp_path / "audio_normalisiert.wav"
    assert gewaehlt_ziel == ziel
    assert sum(e - s for s, e in abschnitte) == pytest.approx(15.0)


def test_fehler_ohne_abschnitte_ohne_audio_und_ohne_pfad(tmp_path):
    (tmp_path / "leer").mkdir()
    with pytest.raises(se.SprecherExportFehler, match="keine Sprecherabschnitte"):
        se.hoerprobe_erstellen(_json(tmp_path / "leer", turns=False), "SPEAKER_00", tmp_path / "p.wav")
    ohne_audio = tmp_path / "ohne"
    ohne_audio.mkdir()
    with pytest.raises(se.SprecherExportFehler, match="nicht gefunden"):
        se.hoerprobe_erstellen(_json(ohne_audio, mit_audio=False), "SPEAKER_00", tmp_path / "p.wav")
    pfad = _json(tmp_path)
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    daten["audio_pfad"] = None
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    with pytest.raises(se.SprecherExportFehler, match="älteren Version"):
        se.hoerprobe_erstellen(pfad, "SPEAKER_00", tmp_path / "p.wav")


def test_sprecher_exportieren_schreibt_audio_und_text_und_nummeriert_durch(tmp_path):
    aufrufe = []
    json_pfad = _json(tmp_path)
    ziel = tmp_path / "aus"
    wav, txt = se.sprecher_exportieren(json_pfad, "SPEAKER_00", ziel, _schneider(aufrufe))
    assert wav.name == "sitzung_Anna_ Leitung_.wav"  # unzulaessige Zeichen ersetzt
    assert txt.read_text(encoding="utf-8") == "[00:00:01.000] Hallo\n"
    assert aufrufe[0][2] == [(0.0, 10.0), (30.0, 60.0)]

    wav2, _ = se.sprecher_exportieren(json_pfad, "SPEAKER_00", ziel, _schneider(aufrufe))
    assert wav2.name == "sitzung_Anna_ Leitung__2.wav"


def test_sprecher_exportieren_ohne_abschnitte(tmp_path):
    with pytest.raises(se.SprecherExportFehler):
        se.sprecher_exportieren(_json(tmp_path), "SPEAKER_09", tmp_path / "x")
