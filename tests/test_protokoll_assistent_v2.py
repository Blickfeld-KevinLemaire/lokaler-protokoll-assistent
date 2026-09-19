"""Tests fuer die Konsolenvariante (Cloud-Transkription ueber OpenRouter).

Es wird nie ein echter Netzwerkaufruf gemacht: ``call_openrouter`` bzw.
``urllib.request.urlopen`` werden in jedem Test ersetzt.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from pathlib import Path

import pytest

import protokoll_assistent_v2 as kern


# --------------------------------------------------------------------------
# format_timestamp / value_float
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sekunden", "erwartet"),
    [
        (0, "00:00:00.000"),
        (1.5, "00:00:01.500"),
        (61.25, "00:01:01.250"),
        (3661.001, "01:01:01.001"),
        (-5, "00:00:00.000"),  # negative Werte werden auf 0 geklemmt
    ],
)
def test_format_timestamp(sekunden, erwartet):
    assert kern.format_timestamp(sekunden) == erwartet


@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [("3.5", 3.5), (7, 7.0), (None, 0.0), ("keine Zahl", 0.0), ([], 0.0)],
)
def test_value_float_faellt_auf_default_zurueck(wert, erwartet):
    assert kern.value_float(wert) == erwartet


def test_value_float_eigener_default():
    assert kern.value_float(None, default=9.0) == 9.0


# --------------------------------------------------------------------------
# find_input_file
# --------------------------------------------------------------------------
def test_find_input_file_ohne_dateien_meldet_fehler(isolierte_app_ordner):
    with pytest.raises(FileNotFoundError, match="Keine Audio- oder Videodatei"):
        kern.find_input_file()


def test_find_input_file_ignoriert_fremde_endungen(isolierte_app_ordner):
    (isolierte_app_ordner["INPUT_DIR"] / "notizen.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        kern.find_input_file()


def test_find_input_file_einzelne_datei(isolierte_app_ordner):
    audio = isolierte_app_ordner["INPUT_DIR"] / "sitzung.mp3"
    audio.write_bytes(b"\x00")
    assert kern.find_input_file() == audio


def test_find_input_file_fragt_bei_mehreren_dateien(isolierte_app_ordner, monkeypatch, capsys):
    for name in ("b_zweite.mp3", "a_erste.wav"):
        (isolierte_app_ordner["INPUT_DIR"] / name).write_bytes(b"\x00")

    antworten = iter(["", "99", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(antworten))

    gewaehlt = kern.find_input_file()

    # Sortiert: a_erste.wav, b_zweite.mp3 -> Nummer 2 ist b_zweite.mp3
    assert gewaehlt.name == "b_zweite.mp3"
    assert "Bitte eine gueltige Nummer eingeben." in capsys.readouterr().out


# --------------------------------------------------------------------------
# get_api_key / confirm_cloud_upload
# --------------------------------------------------------------------------
def test_get_api_key_fehlt(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        kern.get_api_key()


def test_get_api_key_wird_getrimmt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  abc123  ")
    assert kern.get_api_key() == "abc123"


def test_confirm_cloud_upload_per_umgebungsvariable(monkeypatch):
    monkeypatch.setenv("PROTOKOLL_UPLOAD_BESTAETIGT", "1")
    kern.confirm_cloud_upload(Path("aufnahme.mp3"))  # darf nicht fragen, nicht werfen


@pytest.mark.parametrize("antwort", ["j", "ja", "Y", "yes"])
def test_confirm_cloud_upload_zustimmung(monkeypatch, antwort):
    monkeypatch.setattr("builtins.input", lambda _prompt: antwort)
    kern.confirm_cloud_upload(Path("aufnahme.mp3"))


@pytest.mark.parametrize("antwort", ["", "n", "nein", "irgendwas"])
def test_confirm_cloud_upload_ablehnung_bricht_ab(monkeypatch, antwort):
    monkeypatch.setattr("builtins.input", lambda _prompt: antwort)
    with pytest.raises(KeyboardInterrupt):
        kern.confirm_cloud_upload(Path("aufnahme.mp3"))


# --------------------------------------------------------------------------
# load_terms
# --------------------------------------------------------------------------
def test_load_terms_ohne_datei(isolierte_app_ordner):
    assert kern.load_terms() == []


def test_load_terms_ueberspringt_kommentare_und_duplikate(isolierte_app_ordner):
    kern.TERMS_FILE.write_text(
        "# Kommentar\n\nProjekt Alpha\nprojekt alpha\nMueller\n  \n",
        encoding="utf-8",
    )
    assert kern.load_terms() == ["Projekt Alpha", "Mueller"]


def test_load_terms_begrenzt_auf_1000(isolierte_app_ordner):
    kern.TERMS_FILE.write_text("\n".join(f"Begriff{i}" for i in range(1500)), encoding="utf-8")
    assert len(kern.load_terms()) == 1000


def test_load_terms_kommt_mit_bom_zurecht(isolierte_app_ordner):
    kern.TERMS_FILE.write_bytes("﻿Mueller\n".encode())
    assert kern.load_terms() == ["Mueller"]


# --------------------------------------------------------------------------
# prepare_audio
# --------------------------------------------------------------------------
def test_prepare_audio_kleine_mp3_wird_direkt_genommen(tmp_path):
    quelle = tmp_path / "kurz.mp3"
    quelle.write_bytes(b"\x00" * 100)
    pfad, format_name = kern.prepare_audio(quelle, tmp_path)
    assert pfad == quelle
    assert format_name == "mp3"


def test_prepare_audio_ohne_ffmpeg_meldet_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(kern.shutil, "which", lambda _name: None)
    quelle = tmp_path / "aufnahme.mp4"
    quelle.write_bytes(b"\x00")
    with pytest.raises(RuntimeError, match="FFmpeg"):
        kern.prepare_audio(quelle, tmp_path)


def test_prepare_audio_konvertiert_mit_ffmpeg(tmp_path, monkeypatch):
    quelle = tmp_path / "aufnahme.mp4"
    quelle.write_bytes(b"\x00")
    monkeypatch.setattr(kern.shutil, "which", lambda _name: "ffmpeg")

    aufrufe = []

    def fake_run(command, capture_output, text, check):
        aufrufe.append(command)
        Path(command[-1]).write_bytes(b"mp3")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(kern.subprocess, "run", fake_run)
    pfad, format_name = kern.prepare_audio(quelle, tmp_path)

    assert format_name == "mp3"
    assert pfad.name == "aufnahme_protokoll_audio.mp3"
    assert "-vn" in aufrufe[0]
    assert "16000" in aufrufe[0]


def test_prepare_audio_meldet_ffmpeg_fehler(tmp_path, monkeypatch):
    quelle = tmp_path / "aufnahme.mkv"
    quelle.write_bytes(b"\x00")
    monkeypatch.setattr(kern.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(
        kern.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "kaputt"})(),
    )
    with pytest.raises(RuntimeError, match="kaputt"):
        kern.prepare_audio(quelle, tmp_path)


# --------------------------------------------------------------------------
# build_request
# --------------------------------------------------------------------------
def test_build_request_kodiert_audio_als_base64(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"hallo")
    anfrage = kern.build_request(audio, "mp3", [])

    assert base64.b64decode(anfrage["input_audio"]["data"]) == b"hallo"
    assert anfrage["model"] == kern.MODEL_NAME
    assert anfrage["input_audio"]["format"] == "mp3"
    assert anfrage["provider"]["options"][kern.PROVIDER_NAME]["diarization"]["enabled"] is True


# --------------------------------------------------------------------------
# call_openrouter
# --------------------------------------------------------------------------
class _FakeAntwort:
    def __init__(self, nutzlast: bytes):
        self._nutzlast = nutzlast

    def read(self):
        return self._nutzlast

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_call_openrouter_erfolg(monkeypatch):
    erfasst = {}

    def fake_urlopen(request, timeout):
        erfasst["header"] = request.headers
        erfasst["timeout"] = timeout
        return _FakeAntwort(json.dumps({"text": "hallo"}).encode("utf-8"))

    monkeypatch.setattr(kern.urllib.request, "urlopen", fake_urlopen)
    ergebnis = kern.call_openrouter({"model": "m"}, "geheim")

    assert ergebnis == {"text": "hallo"}
    assert erfasst["header"]["Authorization"] == "Bearer geheim"
    assert erfasst["timeout"] == kern.REQUEST_TIMEOUT_SECONDS


def test_call_openrouter_http_fehler(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url="u", code=429, msg="Too Many", hdrs=None, fp=io.BytesIO(b"limit erreicht")
        )

    monkeypatch.setattr(kern.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        kern.call_openrouter({}, "k")


def test_call_openrouter_nicht_erreichbar(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("kein Netz")

    monkeypatch.setattr(kern.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        kern.call_openrouter({}, "k")


def test_call_openrouter_zeitlimit(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError

    monkeypatch.setattr(kern.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Zeitlimit"):
        kern.call_openrouter({}, "k")


def test_call_openrouter_kein_objekt(monkeypatch):
    monkeypatch.setattr(
        kern.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(b"[1, 2]")
    )
    with pytest.raises(RuntimeError, match="kein JSON-Objekt"):
        kern.call_openrouter({}, "k")


def test_call_openrouter_fehlerfeld(monkeypatch):
    monkeypatch.setattr(
        kern.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"error": "boom"}).encode()),
    )
    with pytest.raises(RuntimeError, match="boom"):
        kern.call_openrouter({}, "k")


# --------------------------------------------------------------------------
# group_words_to_segments
# --------------------------------------------------------------------------
def test_group_words_faellt_bei_sprecherwechsel_auseinander():
    woerter = [
        {"word": "Hallo", "start": 0.0, "end": 0.4, "speaker": "A"},
        {"word": "zusammen", "start": 0.4, "end": 0.9, "speaker": "A"},
        {"word": "Moin", "start": 1.0, "end": 1.4, "speaker": "B"},
    ]
    segmente = kern.group_words_to_segments(woerter)
    assert [s["speaker"] for s in segmente] == ["A", "B"]
    assert segmente[0]["text"] == "Hallo zusammen"


def test_group_words_trennt_bei_langer_pause():
    woerter = [
        {"word": "eins", "start": 0.0, "end": 0.2, "speaker": "A"},
        {"word": "zwei", "start": 5.0, "end": 5.2, "speaker": "A"},
    ]
    assert len(kern.group_words_to_segments(woerter)) == 2


def test_group_words_schliesst_bei_satzende_ab():
    woerter = [
        {"word": "Fertig.", "start": 0.0, "end": 0.3, "speaker": "A"},
        {"word": "Weiter", "start": 0.4, "end": 0.6, "speaker": "A"},
    ]
    segmente = kern.group_words_to_segments(woerter)
    assert len(segmente) == 2
    assert segmente[0]["text"] == "Fertig."


def test_group_words_haengt_satzzeichen_ohne_leerzeichen_an():
    woerter = [
        {"word": "Hallo", "start": 0.0, "end": 0.2, "speaker": "A"},
        {"word": ",", "start": 0.2, "end": 0.25, "speaker": "A"},
        {"word": "Welt", "start": 0.3, "end": 0.5, "speaker": "A"},
    ]
    assert kern.group_words_to_segments(woerter)[0]["text"] == "Hallo, Welt"


def test_group_words_ignoriert_muell():
    woerter = ["kein dict", {"word": "   "}, {"kein_word_feld": 1}]
    assert kern.group_words_to_segments(woerter) == []


def test_group_words_trennt_bei_sehr_langem_text():
    woerter = [
        {"word": "wort", "start": i * 0.1, "end": i * 0.1 + 0.05, "speaker": "A"}
        for i in range(100)
    ]
    assert len(kern.group_words_to_segments(woerter)) > 1


# --------------------------------------------------------------------------
# raw_speaker_key / normalize_transcript
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [
        (None, "__unbekannt__"),
        ("", "__unbekannt__"),
        ("   ", "__unbekannt__"),
        (" A ", "A"),
        (2, "2"),
    ],
)
def test_raw_speaker_key(wert, erwartet):
    assert kern.raw_speaker_key(wert) == erwartet


def test_normalize_transcript_vergibt_fortlaufende_sprechernamen():
    segmente, woerter, sprecher = kern.normalize_transcript(
        {
            "segments": [
                {"start": 0, "end": 1, "text": "Hallo", "speaker": "SPEAKER_01"},
                {"start": 1, "end": 2, "text": "Moin", "speaker": "SPEAKER_02"},
                {"start": 2, "end": 3, "text": "Ja", "speaker": "SPEAKER_01"},
            ]
        }
    )
    assert [s["sprecher"] for s in segmente] == ["Sprecher 1", "Sprecher 2", "Sprecher 1"]
    assert [s["nummer"] for s in segmente] == [1, 2, 3]
    assert segmente[0]["text"] == "Sprecher 1: Hallo"
    assert len(sprecher) == 2
    assert woerter == []


def test_normalize_transcript_unbekannter_sprecher():
    segmente, _woerter, sprecher = kern.normalize_transcript(
        {"segments": [{"start": 0, "end": 1, "text": "Hallo"}]}
    )
    assert segmente[0]["sprecher"] == "Sprecher unbekannt"
    assert segmente[0]["sprecher_id"] is None
    assert sprecher == []


def test_normalize_transcript_baut_segmente_aus_woertern():
    segmente, woerter, _sprecher = kern.normalize_transcript(
        {"words": [{"word": "Hallo", "start": 0, "end": 1, "speaker": "A"}]}
    )
    assert segmente[0]["inhalt"] == "Hallo"
    assert woerter[0]["wort"] == "Hallo"


def test_normalize_transcript_faellt_auf_reinen_text_zurueck():
    segmente, _w, _s = kern.normalize_transcript({"text": "Nur Text", "duration": 12})
    assert len(segmente) == 1
    assert segmente[0]["inhalt"] == "Nur Text"


def test_normalize_transcript_ignoriert_falsche_typen():
    segmente, woerter, _s = kern.normalize_transcript(
        {"segments": "kein array", "words": "auch nicht"}
    )
    assert segmente == []
    assert woerter == []


def test_normalize_transcript_ueberspringt_leere_segmente():
    segmente, _w, _s = kern.normalize_transcript(
        {"segments": [{"text": "   "}, "kein dict", {"text": "echt"}]}
    )
    assert len(segmente) == 1


def test_normalize_transcript_ueberspringt_leere_woerter():
    _s, woerter, _sp = kern.normalize_transcript(
        {"segments": [{"text": "da"}], "words": [{"word": "  "}, "kein dict"]}
    )
    assert woerter == []


# --------------------------------------------------------------------------
# save_transcript
# --------------------------------------------------------------------------
def test_save_transcript_schreibt_txt_und_json(isolierte_app_ordner):
    quelle = Path("besprechung.mp3")
    txt, js = kern.save_transcript(
        quelle,
        {
            "segments": [{"start": 0, "end": 2, "text": "Hallo", "speaker": "A"}],
            "duration": 2,
            "language": "de",
            "usage": {"tokens": 5},
        },
    )
    assert txt.name == "besprechung_mai2_transkript.txt"
    inhalt = txt.read_text(encoding="utf-8")
    assert "VOLLTRANSKRIPT MIT SPRECHERTRENNUNG" in inhalt
    assert "Sprecher 1: Hallo" in inhalt

    daten = json.loads(js.read_text(encoding="utf-8"))
    assert daten["anzahl_sprecher"] == 1
    assert daten["dauer_sekunden"] == 2.0
    assert daten["nutzung"] == {"tokens": 5}


def test_save_transcript_ohne_sprache_meldet_fehler(isolierte_app_ordner):
    with pytest.raises(RuntimeError, match="keine Sprache erkannt"):
        kern.save_transcript(Path("leer.mp3"), {"segments": []})


def test_save_transcript_warnt_ohne_sprecher(isolierte_app_ordner, capsys):
    kern.save_transcript(Path("a.mp3"), {"segments": [{"start": 0, "end": 1, "text": "Hi"}]})
    assert "WARNUNG" in capsys.readouterr().out


def test_save_transcript_berechnet_dauer_aus_segmenten(isolierte_app_ordner):
    _txt, js = kern.save_transcript(
        Path("a.mp3"), {"segments": [{"start": 0, "end": 9.5, "text": "Hi", "speaker": "A"}]}
    )
    assert json.loads(js.read_text(encoding="utf-8"))["dauer_sekunden"] == 9.5


def test_save_transcript_repariert_kaputtes_usage_feld(isolierte_app_ordner):
    _txt, js = kern.save_transcript(
        Path("a.mp3"),
        {"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}], "usage": "kaputt"},
    )
    assert json.loads(js.read_text(encoding="utf-8"))["nutzung"] == {}


# --------------------------------------------------------------------------
# transcribe
# --------------------------------------------------------------------------
def test_transcribe_nutzt_vorhandenen_zwischenstand(isolierte_app_ordner, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("PROTOKOLL_UPLOAD_BESTAETIGT", "1")
    quelle = isolierte_app_ordner["INPUT_DIR"] / "sitzung.mp3"
    quelle.write_bytes(b"\x00")

    zwischenstand = (
        isolierte_app_ordner["CHECKPOINT_DIR"] / "sitzung_mai_transcribe_2_rohantwort.json"
    )
    zwischenstand.write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}]}),
        encoding="utf-8",
    )

    def darf_nicht_aufgerufen_werden(*_a, **_k):
        raise AssertionError("Es haette kein API-Aufruf passieren duerfen.")

    monkeypatch.setattr(kern, "call_openrouter", darf_nicht_aufgerufen_werden)

    txt, _js = kern.transcribe(quelle)

    assert txt.exists()
    assert not zwischenstand.exists()  # wird nach Erfolg aufgeraeumt


def test_transcribe_ruft_api_und_legt_zwischenstand_an(isolierte_app_ordner, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("PROTOKOLL_UPLOAD_BESTAETIGT", "1")
    quelle = isolierte_app_ordner["INPUT_DIR"] / "sitzung.mp3"
    quelle.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(
        kern,
        "call_openrouter",
        lambda daten, schluessel: {
            "segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}]
        },
    )
    txt, js = kern.transcribe(quelle)
    assert txt.exists()
    assert js.exists()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_erfolg(isolierte_app_ordner, monkeypatch, capsys):
    quelle = isolierte_app_ordner["INPUT_DIR"] / "a.mp3"
    quelle.write_bytes(b"\x00")
    monkeypatch.setattr(kern, "transcribe", lambda s: (Path("t.txt"), Path("t.json")))
    assert kern.main() == 0
    assert "erfolgreich abgeschlossen" in capsys.readouterr().out


def test_main_abbruch_durch_benutzer(isolierte_app_ordner, monkeypatch, capsys):
    (isolierte_app_ordner["INPUT_DIR"] / "a.mp3").write_bytes(b"\x00")

    def abbruch(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr(kern, "transcribe", abbruch)
    assert kern.main() == 130
    assert "Abbruch durch Benutzer" in capsys.readouterr().out


def test_main_fehler(isolierte_app_ordner, monkeypatch, capsys):
    (isolierte_app_ordner["INPUT_DIR"] / "a.mp3").write_bytes(b"\x00")

    def fehler(_s):
        raise RuntimeError("etwas ging schief")

    monkeypatch.setattr(kern, "transcribe", fehler)
    assert kern.main() == 1
    assert "etwas ging schief" in capsys.readouterr().out
