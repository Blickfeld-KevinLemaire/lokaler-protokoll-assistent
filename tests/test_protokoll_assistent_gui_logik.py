"""Tests fuer die Funktionen von ``protokoll_assistent_gui.py``, die ohne
Fenster auskommen (Transkription, Zusammenfuegen, Sprechernamen, Export).

Die Fensterklasse ``ProtokollGUI`` selbst wird in
``test_protokoll_assistent_gui_fenster.py`` geprueft.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from pathlib import Path

import pytest

import protokoll_assistent_gui as gui


@pytest.fixture
def gui_ordner(tmp_path, monkeypatch):
    """Biegt die Ausgabeordner des GUI-Moduls auf ein temporaeres Verzeichnis um."""
    ordner = {
        "OUTPUT_DIR": tmp_path / "ausgabe",
        "CHECKPOINT_DIR": tmp_path / "zwischenstaende",
        "ERGEBNIS_DIR": tmp_path / "ergebnis",
        "INPUT_DIR": tmp_path / "eingabe",
    }
    for pfad in ordner.values():
        pfad.mkdir(parents=True, exist_ok=True)
    for name, pfad in ordner.items():
        monkeypatch.setattr(gui, name, pfad)
    return ordner


class _FakeAntwort:
    def __init__(self, nutzlast: bytes):
        self._nutzlast = nutzlast

    def read(self):
        return self._nutzlast

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _http_fehler(code: int, koerper: bytes):
    def werfen(request, timeout):
        raise urllib.error.HTTPError(
            url="u", code=code, msg="m", hdrs=None, fp=io.BytesIO(koerper)
        )

    return werfen


# --------------------------------------------------------------------------
# find_ffmpeg / ensure_ffmpeg_on_path
# --------------------------------------------------------------------------
def test_find_ffmpeg_nimmt_path_zuerst(monkeypatch):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "/pfad/ffmpeg")
    assert gui.find_ffmpeg() == "/pfad/ffmpeg"


def test_find_ffmpeg_nutzt_umgebungsvariable(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    eigenes = tmp_path / "ffmpeg.exe"
    eigenes.write_bytes(b"\x00")
    monkeypatch.setenv("FFMPEG_PATH", str(eigenes))
    monkeypatch.setattr(gui, "FFMPEG_SUCHPFADE", [])
    assert gui.find_ffmpeg() == str(eigenes)


def test_find_ffmpeg_ignoriert_ungueltige_umgebungsvariable(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    monkeypatch.setenv("FFMPEG_PATH", str(tmp_path / "gibtesnicht.exe"))
    monkeypatch.setattr(gui, "FFMPEG_SUCHPFADE", [])
    assert gui.find_ffmpeg() is None


def test_find_ffmpeg_durchsucht_standardpfade(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    kandidat = tmp_path / "ffmpeg.exe"
    kandidat.write_bytes(b"\x00")
    monkeypatch.setattr(gui, "FFMPEG_SUCHPFADE", [str(tmp_path / "fehlt"), str(kandidat)])
    assert gui.find_ffmpeg() == str(kandidat)


def test_ensure_ffmpeg_on_path_ergaenzt_pfad(monkeypatch, tmp_path):
    ffmpeg = tmp_path / "bin" / "ffmpeg.exe"
    ffmpeg.parent.mkdir()
    ffmpeg.write_bytes(b"\x00")
    monkeypatch.setattr(gui, "find_ffmpeg", lambda: str(ffmpeg))
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    monkeypatch.setenv("PATH", "")

    assert gui.ensure_ffmpeg_on_path() == str(ffmpeg)
    assert str(ffmpeg.parent.resolve()) in gui.os.environ["PATH"]


def test_ensure_ffmpeg_on_path_laesst_vorhandenen_pfad_in_ruhe(monkeypatch):
    monkeypatch.setattr(gui, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "/usr/bin/ffmpeg")
    vorher = gui.os.environ.get("PATH", "")
    assert gui.ensure_ffmpeg_on_path() == "/usr/bin/ffmpeg"
    assert gui.os.environ.get("PATH", "") == vorher


def test_ensure_ffmpeg_on_path_ohne_fund(monkeypatch):
    monkeypatch.setattr(gui, "find_ffmpeg", lambda: None)
    assert gui.ensure_ffmpeg_on_path() is None


# --------------------------------------------------------------------------
# get_audio_duration_seconds
# --------------------------------------------------------------------------
def test_dauer_ohne_ffprobe(monkeypatch):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    assert gui.get_audio_duration_seconds(Path("a.mp3")) is None


def test_dauer_wird_gelesen(monkeypatch):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffprobe")
    monkeypatch.setattr(
        gui.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": " 123.5 \n"})(),
    )
    assert gui.get_audio_duration_seconds(Path("a.mp3")) == 123.5


def test_dauer_bei_ffprobe_fehler(monkeypatch):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffprobe")
    monkeypatch.setattr(
        gui.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})()
    )
    assert gui.get_audio_duration_seconds(Path("a.mp3")) is None


def test_dauer_bei_unlesbarer_ausgabe(monkeypatch):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffprobe")
    monkeypatch.setattr(
        gui.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "keine Zahl"})(),
    )
    assert gui.get_audio_duration_seconds(Path("a.mp3")) is None


# --------------------------------------------------------------------------
# split_audio_into_chunks
# --------------------------------------------------------------------------
def test_split_ohne_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: None)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        gui.split_audio_into_chunks(Path("a.mp3"), tmp_path, 900, lambda _m: None)


def test_split_legt_abschnitte_an(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffmpeg")
    meldungen: list[str] = []

    def fake_run(command, **_kwargs):
        (tmp_path / "abschnitt_0001.mp3").write_bytes(b"\x00")
        (tmp_path / "abschnitt_0000.mp3").write_bytes(b"\x00")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(gui.subprocess, "run", fake_run)
    chunks = gui.split_audio_into_chunks(Path("a.mp3"), tmp_path, 900, meldungen.append)

    assert [p.name for p in chunks] == ["abschnitt_0000.mp3", "abschnitt_0001.mp3"]
    assert "15 Minuten" in meldungen[0]


def test_split_meldet_ffmpeg_fehler(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffmpeg")
    monkeypatch.setattr(
        gui.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "defekt"})(),
    )
    with pytest.raises(RuntimeError, match="defekt"):
        gui.split_audio_into_chunks(Path("a.mp3"), tmp_path, 900, lambda _m: None)


def test_split_ohne_ergebnis(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.shutil, "which", lambda _n: "ffmpeg")
    monkeypatch.setattr(
        gui.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0, "stderr": ""})()
    )
    with pytest.raises(RuntimeError, match="keine Abschnitte"):
        gui.split_audio_into_chunks(Path("a.mp3"), tmp_path, 900, lambda _m: None)


# --------------------------------------------------------------------------
# build_transcription_request
# --------------------------------------------------------------------------
def test_build_transcription_request_mit_anbieter(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ton")
    anfrage = gui.build_transcription_request(audio, "mp3", "modell-x", "azure")

    assert base64.b64decode(anfrage["input_audio"]["data"]) == b"ton"
    assert anfrage["model"] == "modell-x"
    assert anfrage["provider"]["options"]["azure"]["diarization"]["enabled"] is True


def test_build_transcription_request_ohne_anbieter(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ton")
    anfrage = gui.build_transcription_request(audio, "mp3", "m", "   ")
    assert "provider" not in anfrage


# --------------------------------------------------------------------------
# call_transcription_endpoint
# --------------------------------------------------------------------------
def test_transkriptions_endpunkt_erfolg(monkeypatch):
    erfasst = {}

    def fake_urlopen(request, timeout):
        erfasst["url"] = request.full_url
        erfasst["auth"] = request.headers["Authorization"]
        return _FakeAntwort(json.dumps({"text": "ok"}).encode())

    monkeypatch.setattr(gui.urllib.request, "urlopen", fake_urlopen)
    assert gui.call_transcription_endpoint("https://x/y", {}, "k") == {"text": "ok"}
    assert erfasst["url"] == "https://x/y"
    assert erfasst["auth"] == "Bearer k"


def test_transkriptions_endpunkt_http_fehler(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", _http_fehler(500, b"kaputt"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        gui.call_transcription_endpoint("https://x", {}, "k")


def test_transkriptions_endpunkt_nicht_erreichbar(monkeypatch):
    def werfen(request, timeout):
        raise urllib.error.URLError("weg")

    monkeypatch.setattr(gui.urllib.request, "urlopen", werfen)
    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        gui.call_transcription_endpoint("https://x", {}, "k")


def test_transkriptions_endpunkt_zeitlimit(monkeypatch):
    def werfen(request, timeout):
        raise TimeoutError

    monkeypatch.setattr(gui.urllib.request, "urlopen", werfen)
    with pytest.raises(RuntimeError, match="Zeitlimit"):
        gui.call_transcription_endpoint("https://x", {}, "k")


def test_transkriptions_endpunkt_kein_objekt(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(b"[]"))
    with pytest.raises(RuntimeError, match="kein JSON-Objekt"):
        gui.call_transcription_endpoint("https://x", {}, "k")


def test_transkriptions_endpunkt_fehlerfeld(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"error": "nope"}).encode()),
    )
    with pytest.raises(RuntimeError, match="nope"):
        gui.call_transcription_endpoint("https://x", {}, "k")


# --------------------------------------------------------------------------
# save_transcript
# --------------------------------------------------------------------------
def test_save_transcript_schreibt_endpunkt_in_kopfzeile(gui_ordner):
    txt, js = gui.save_transcript(
        Path("sitzung.mp3"),
        {"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}], "duration": 1},
        "modell-x",
        "https://endpunkt",
    )
    assert "Endpunkt: https://endpunkt" in txt.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["modell"] == "modell-x"


def test_save_transcript_ohne_sprache(gui_ordner):
    with pytest.raises(RuntimeError, match="keine Sprache erkannt"):
        gui.save_transcript(Path("a.mp3"), {"segments": []}, "m", "e")


def test_save_transcript_dauer_aus_segmenten(gui_ordner):
    _txt, js = gui.save_transcript(
        Path("a.mp3"),
        {"segments": [{"start": 0, "end": 4.25, "text": "Hi", "speaker": "A"}]},
        "m",
        "e",
    )
    assert json.loads(js.read_text(encoding="utf-8"))["dauer_sekunden"] == 4.25


def test_save_transcript_kaputtes_usage_feld(gui_ordner):
    _txt, js = gui.save_transcript(
        Path("a.mp3"),
        {"segments": [{"start": 0, "end": 1, "text": "Hi", "speaker": "A"}], "usage": 5},
        "m",
        "e",
    )
    assert json.loads(js.read_text(encoding="utf-8"))["nutzung"] == {}


# --------------------------------------------------------------------------
# transcribe_in_chunks
# --------------------------------------------------------------------------
def _chunk_umgebung(monkeypatch, gui_ordner, tmp_path, antworten):
    """Bereitet prepare_audio/split/call so vor, dass kein echtes FFmpeg noetig ist."""
    monkeypatch.setattr(gui.kern, "prepare_audio", lambda q, d: (q, "mp3"))

    def fake_split(audio, work_dir, chunk_seconds, log):
        pfade = []
        for i in range(len(antworten)):
            p = Path(work_dir) / f"abschnitt_{i:04d}.mp3"
            p.write_bytes(b"\x00")
            pfade.append(p)
        log("geteilt")
        return pfade

    monkeypatch.setattr(gui, "split_audio_into_chunks", fake_split)
    folge = iter(antworten)
    monkeypatch.setattr(
        gui, "call_transcription_endpoint", lambda url, daten, key: next(folge)
    )


def test_transcribe_in_chunks_versetzt_zeiten_und_kennzeichnet_teile(
    monkeypatch, gui_ordner, tmp_path
):
    antworten = [
        {
            "segments": [{"start": 0, "end": 10, "text": "Teil eins", "speaker": "A"}],
            "language": "de",
        },
        {"segments": [{"start": 0, "end": 10, "text": "Teil zwei", "speaker": "A"}]},
    ]
    _chunk_umgebung(monkeypatch, gui_ordner, tmp_path, antworten)

    quelle = tmp_path / "lang.mp3"
    quelle.write_bytes(b"\x00")
    meldungen: list[str] = []

    ergebnis = gui.transcribe_in_chunks(
        quelle, "k", 900, "https://e", "m", "azure", meldungen.append, lambda _f, _t: None
    )

    assert ergebnis["anzahl_abschnitte"] == 2
    assert ergebnis["sprache"] == "de"
    # Der zweite Abschnitt ist um genau eine Chunk-Laenge nach hinten versetzt.
    assert ergebnis["segmente"][1]["start_sekunden"] == 900.0
    assert ergebnis["segmente"][0]["sprecher"] == "Sprecher 1 (Teil 1)"
    assert ergebnis["segmente"][1]["sprecher"] == "Sprecher 1 (Teil 2)"
    assert [s["nummer"] for s in ergebnis["segmente"]] == [1, 2]
    assert ergebnis["dauer_sekunden"] == 910.0


def test_transcribe_in_chunks_nutzt_zwischenstand(monkeypatch, gui_ordner, tmp_path):
    quelle = tmp_path / "lang.mp3"
    quelle.write_bytes(b"\x00")

    zwischenstand = gui_ordner["CHECKPOINT_DIR"] / "lang_teil01_rohantwort.json"
    zwischenstand.write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": "aus Datei", "speaker": "A"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(gui.kern, "prepare_audio", lambda q, d: (q, "mp3"))

    def fake_split(audio, work_dir, chunk_seconds, log):
        p = Path(work_dir) / "abschnitt_0000.mp3"
        p.write_bytes(b"\x00")
        return [p]

    monkeypatch.setattr(gui, "split_audio_into_chunks", fake_split)

    def darf_nicht(*_a, **_k):
        raise AssertionError("Es haette kein Netzaufruf passieren duerfen.")

    monkeypatch.setattr(gui, "call_transcription_endpoint", darf_nicht)

    ergebnis = gui.transcribe_in_chunks(
        quelle, "k", 900, "https://e", "m", "azure", lambda _m: None, lambda _f, _t: None
    )
    assert ergebnis["segmente"][0]["inhalt"] == "aus Datei"
    assert not zwischenstand.exists()


def test_transcribe_in_chunks_uebernimmt_woerter_und_sprecher(monkeypatch, gui_ordner, tmp_path):
    antworten = [
        {
            "segments": [{"start": 0, "end": 5, "text": "Hallo", "speaker": "A"}],
            "words": [{"word": "Hallo", "start": 0, "end": 1, "speaker": "A"}],
        }
    ]
    _chunk_umgebung(monkeypatch, gui_ordner, tmp_path, antworten)
    quelle = tmp_path / "l.mp3"
    quelle.write_bytes(b"\x00")

    ergebnis = gui.transcribe_in_chunks(
        quelle, "k", 600, "https://e", "m", "azure", lambda _m: None, lambda _f, _t: None
    )
    assert ergebnis["woerter"][0]["sprecher"].endswith("(Teil 1)")
    assert ergebnis["sprecher"][0]["sprecher_id"].startswith("teil1:")
    assert ergebnis["sprache"] == gui.kern.LANGUAGE or ergebnis["sprache"]


# --------------------------------------------------------------------------
# save_merged_transcript
# --------------------------------------------------------------------------
def test_save_merged_transcript(gui_ordner):
    zusammengefasst = {
        "segmente": [
            {
                "start": "00:00:00.000",
                "ende": "00:00:05.000",
                "text": "Sprecher 1 (Teil 1): Hallo",
            }
        ],
        "woerter": [],
        "sprecher": [{"sprecher_id": "teil1:A", "bezeichnung": "Sprecher 1 (Teil 1)"}],
        "dauer_sekunden": 5.0,
        "sprache": "de",
        "anzahl_abschnitte": 1,
    }
    txt, js = gui.save_merged_transcript(Path("lang.mp3"), zusammengefasst, "m", "https://e")
    inhalt = txt.read_text(encoding="utf-8")
    assert "Aufgeteilt in 1 Abschnitte" in inhalt
    assert "Teil N" in inhalt
    assert json.loads(js.read_text(encoding="utf-8"))["aufgeteilt_in_abschnitte"] == 1


def test_save_merged_transcript_ohne_segmente(gui_ordner):
    with pytest.raises(RuntimeError, match="keine Sprache erkannt"):
        gui.save_merged_transcript(Path("a.mp3"), {"segmente": []}, "m", "e")


# --------------------------------------------------------------------------
# erkenne_namen_vorschlag
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("satz", "erwartet"),
    [
        ("Hallo, ich bin Mueller und leite das Projekt.", "Mueller"),
        ("Ich heiße Schmidt.", "Schmidt"),
        ("ich heisse Weber", "Weber"),
        ("Mein Name ist Fischer, guten Tag.", "Fischer"),
        ("Hier ist Meier.", "Meier"),
        ("Hier spricht Braun", "Braun"),
        ("Ich bin der Krause", "Krause"),
    ],
)
def test_erkenne_namen_vorschlag_findet_namen(satz, erwartet):
    assert gui.erkenne_namen_vorschlag(satz) == erwartet


@pytest.mark.parametrize(
    "satz",
    [
        "ich bin noch dazugekommen",  # Kleinschreibung -> kein Name
        "Wir besprechen jetzt das Budget.",
        "",
    ],
)
def test_erkenne_namen_vorschlag_ohne_treffer(satz):
    assert gui.erkenne_namen_vorschlag(satz) is None


# --------------------------------------------------------------------------
# sprecher_einfuehrungen_sammeln
# --------------------------------------------------------------------------
def test_sprecher_einfuehrungen_sammeln():
    segmente = [
        {"sprecher": "Sprecher 1", "inhalt": "Ich bin Mueller.", "start_sekunden": 5},
        {"sprecher": "Sprecher 1", "inhalt": "Noch etwas.", "start_sekunden": 20},
        {"sprecher": "Sprecher 2", "inhalt": "Guten Tag.", "start_sekunden": 30},
    ]
    ergebnis = gui.sprecher_einfuehrungen_sammeln(segmente, 180)

    assert list(ergebnis) == ["Sprecher 1", "Sprecher 2"]
    assert ergebnis["Sprecher 1"]["vorschlag"] == "Mueller"
    assert ergebnis["Sprecher 1"]["beispiel"] == "Ich bin Mueller."
    assert ergebnis["Sprecher 2"]["vorschlag"] is None


def test_sprecher_einfuehrungen_ausserhalb_des_zeitfensters():
    segmente = [{"sprecher": "Sprecher 1", "inhalt": "Ich bin Mueller.", "start_sekunden": 9999}]
    assert gui.sprecher_einfuehrungen_sammeln(segmente, 180)["Sprecher 1"]["vorschlag"] is None


def test_sprecher_einfuehrungen_ohne_sprecherfeld():
    ergebnis = gui.sprecher_einfuehrungen_sammeln([{"inhalt": "Text", "start_sekunden": 1}], 180)
    assert "Sprecher unbekannt" in ergebnis


# --------------------------------------------------------------------------
# wende_sprechernamen_an / speichere_transkript_mit_namen
# --------------------------------------------------------------------------
def test_wende_sprechernamen_an():
    segmente = [{"sprecher": "Sprecher 1", "inhalt": "Hallo"}]
    woerter = [{"sprecher": "Sprecher 1", "wort": "Hallo"}]
    sprecher = [{"sprecher_id": "A", "bezeichnung": "Sprecher 1"}]

    gui.wende_sprechernamen_an(segmente, woerter, sprecher, {"Sprecher 1": "Mueller"})

    assert segmente[0]["sprecher"] == "Mueller"
    assert segmente[0]["text"] == "Mueller: Hallo"
    assert woerter[0]["sprecher"] == "Mueller"
    assert sprecher[0]["bezeichnung"] == "Mueller"


def test_wende_sprechernamen_an_laesst_unbekannte_unveraendert():
    segmente = [{"sprecher": "Sprecher 9", "inhalt": "Hi"}]
    gui.wende_sprechernamen_an(segmente, [], [], {"Sprecher 1": "Mueller"})
    assert segmente[0]["sprecher"] == "Sprecher 9"


def test_speichere_transkript_mit_namen_behaelt_kopfzeilen(tmp_path):
    txt = tmp_path / "t.txt"
    js = tmp_path / "t.json"
    txt.write_text(
        "PROTOKOLL-ASSISTENT\nQuelldatei: a.mp3\n\n"
        "[00:00:00.000 --> 00:00:01.000] Sprecher 1: Hallo\n",
        encoding="utf-8",
    )
    js.write_text(
        json.dumps(
            {
                "segmente": [
                    {
                        "sprecher": "Sprecher 1",
                        "inhalt": "Hallo",
                        "start": "00:00:00.000",
                        "ende": "00:00:01.000",
                    }
                ],
                "woerter": [],
                "sprecher": [{"sprecher_id": "A", "bezeichnung": "Sprecher 1"}],
            }
        ),
        encoding="utf-8",
    )

    gui.speichere_transkript_mit_namen(txt, js, {"Sprecher 1": "Mueller"})

    neuer_text = txt.read_text(encoding="utf-8")
    assert "Quelldatei: a.mp3" in neuer_text
    assert "Mueller: Hallo" in neuer_text
    assert "Sprecher 1: Hallo" not in neuer_text
    assert json.loads(js.read_text(encoding="utf-8"))["sprecher"][0]["bezeichnung"] == "Mueller"


# --------------------------------------------------------------------------
# scan_audio_files / open_in_file_manager
# --------------------------------------------------------------------------
def test_scan_audio_files_ohne_ordner(tmp_path):
    assert gui.scan_audio_files(tmp_path / "gibtesnicht") == []


def test_scan_audio_files_filtert_und_sortiert(tmp_path):
    for name in ("b.mp3", "a.wav", "notiz.txt"):
        (tmp_path / name).write_bytes(b"\x00")
    (tmp_path / "unterordner.mp3").mkdir()
    assert [p.name for p in gui.scan_audio_files(tmp_path)] == ["a.wav", "b.mp3"]


def test_open_in_file_manager_schluckt_fehler(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "platform", "linux")

    def werfen(*_a, **_k):
        raise OSError("kein Dateimanager")

    monkeypatch.setattr(gui.subprocess, "run", werfen)
    gui.open_in_file_manager(tmp_path)  # darf nicht werfen


def test_open_in_file_manager_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    aufrufe = []
    monkeypatch.setattr(gui.subprocess, "run", lambda cmd, check: aufrufe.append(cmd))
    gui.open_in_file_manager(tmp_path)
    assert aufrufe[0][0] == "xdg-open"


def test_open_in_file_manager_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "platform", "darwin")
    aufrufe = []
    monkeypatch.setattr(gui.subprocess, "run", lambda cmd, check: aufrufe.append(cmd))
    gui.open_in_file_manager(tmp_path)
    assert aufrufe[0][0] == "open"


def test_open_in_file_manager_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "platform", "win32")
    aufrufe = []
    monkeypatch.setattr(gui.os, "startfile", aufrufe.append, raising=False)
    gui.open_in_file_manager(tmp_path)
    assert aufrufe == [str(tmp_path)]


# --------------------------------------------------------------------------
# call_local_model
# --------------------------------------------------------------------------
def test_call_local_model_erfolg(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"response": " Zusammenfassung "}).encode()),
    )
    meldungen: list[str] = []
    assert gui.call_local_model("text", "prompt", "llama3.1", meldungen.append) == "Zusammenfassung"
    assert "llama3.1" in meldungen[0]


def test_call_local_model_http_fehler(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", _http_fehler(404, b"nicht da"))
    with pytest.raises(RuntimeError, match="ollama pull"):
        gui.call_local_model("t", "p", "llama3.1", lambda _m: None)


def test_call_local_model_nicht_erreichbar(monkeypatch):
    def werfen(r, timeout):
        raise urllib.error.URLError("aus")

    monkeypatch.setattr(gui.urllib.request, "urlopen", werfen)
    with pytest.raises(RuntimeError, match="Ollama"):
        gui.call_local_model("t", "p", "m", lambda _m: None)


def test_call_local_model_kein_objekt(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(b'"x"'))
    with pytest.raises(RuntimeError, match="kein JSON-Objekt"):
        gui.call_local_model("t", "p", "m", lambda _m: None)


def test_call_local_model_leere_antwort(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"response": "  "}).encode()),
    )
    with pytest.raises(RuntimeError, match="keine Antwort"):
        gui.call_local_model("t", "p", "m", lambda _m: None)


# --------------------------------------------------------------------------
# call_api_model
# --------------------------------------------------------------------------
def _chat_antwort(inhalt: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": inhalt}}]}).encode()


def test_call_api_model_erfolg(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(_chat_antwort(" fertig "))
    )
    meldungen: list[str] = []
    ergebnis = gui.call_api_model("t", "p", "k", "gpt", "https://e", meldungen.append)
    assert ergebnis == "fertig"
    assert "https://e" in meldungen[0]


def test_call_api_model_http_fehler(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", _http_fehler(401, b"kein Zugriff"))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


def test_call_api_model_nicht_erreichbar(monkeypatch):
    def werfen(r, timeout):
        raise urllib.error.URLError("weg")

    monkeypatch.setattr(gui.urllib.request, "urlopen", werfen)
    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


def test_call_api_model_kein_objekt(monkeypatch):
    monkeypatch.setattr(gui.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(b"[]"))
    with pytest.raises(RuntimeError, match="kein JSON-Objekt"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


def test_call_api_model_fehlerfeld(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"error": "boom"}).encode()),
    )
    with pytest.raises(RuntimeError, match="boom"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


def test_call_api_model_unerwartete_struktur(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request,
        "urlopen",
        lambda r, timeout: _FakeAntwort(json.dumps({"choices": []}).encode()),
    )
    with pytest.raises(RuntimeError, match="Unerwartete Antwort"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


def test_call_api_model_leere_antwort(monkeypatch):
    monkeypatch.setattr(
        gui.urllib.request, "urlopen", lambda r, timeout: _FakeAntwort(_chat_antwort("   "))
    )
    with pytest.raises(RuntimeError, match="keine Antwort"):
        gui.call_api_model("t", "p", "k", "m", "https://e", lambda _m: None)


# --------------------------------------------------------------------------
# save_processed_result
# --------------------------------------------------------------------------
def test_save_processed_result_lokal(gui_ordner):
    txt, js = gui.save_processed_result(
        "sitzung", "sitzung.mp3", " Fasse zusammen ", "lokal", "llama3.1", " Ergebnis "
    )
    inhalt = txt.read_text(encoding="utf-8")
    assert "Lokales Modell: llama3.1" in inhalt
    assert inhalt.rstrip().endswith("Ergebnis")

    daten = json.loads(js.read_text(encoding="utf-8"))
    assert daten["verarbeitung"] == "lokal"
    assert daten["endpunkt"] is None
    assert daten["systemprompt"] == "Fasse zusammen"


def test_save_processed_result_api(gui_ordner):
    txt, js = gui.save_processed_result(
        "sitzung", "sitzung.mp3", "prompt", "api", "gpt", "Ergebnis", "https://e"
    )
    assert "API-Modell: gpt (Endpunkt: https://e)" in txt.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["endpunkt"] == "https://e"


def test_save_processed_result_legt_ordner_an(tmp_path, monkeypatch):
    ziel = tmp_path / "neu" / "ergebnis"
    monkeypatch.setattr(gui, "ERGEBNIS_DIR", ziel)
    gui.save_processed_result("a", "a.mp3", "p", "lokal", "m", "text")
    assert ziel.is_dir()
