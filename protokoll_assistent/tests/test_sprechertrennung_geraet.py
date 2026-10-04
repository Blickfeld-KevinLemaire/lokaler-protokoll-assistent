"""Sprechertrennung: Geraetewahl, eigener Prozess, Grafikspeicher fuer Whisper.

Hintergrund: Im Prozess neben Whisper loeste pyannote auf der GPU dreimal einen
Bluescreen HYPERVISOR_ERROR aus; in einem eigenen Prozess lief es stabil
(siehe services/diarisierung_prozess.py)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from protokoll_assistent.services import (
    diarisierung_prozess,
    diarization_service,
    model_service,
    ollama_service,
    pipeline_service,
    transcription_service,
)

VARIABLE = model_service.SPRECHERTRENNUNG_GERAET_VARIABLE
TURNS = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}, {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"}]
EMBEDDINGS = {"SPEAKER_00": [0.1, 0.2], "SPEAKER_01": [0.3, 0.4]}


# --------------------------------------------------------------------------
# Geraetewahl
# --------------------------------------------------------------------------
def test_geraet_folgt_whisper_ohne_vorgabe(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    assert model_service.geraet_fuer_sprechertrennung("cuda") == "cuda"
    assert model_service.geraet_fuer_sprechertrennung("cpu") == "cpu"


@pytest.mark.parametrize(("wert", "erwartet"), [("cpu", "cpu"), (" CPU ", "cpu"), ("cuda", "cuda"), ("quatsch", "cuda")])
def test_umgebungsvariable_erzwingt_das_geraet(monkeypatch, wert, erwartet):
    monkeypatch.setenv(VARIABLE, wert)
    assert model_service.geraet_fuer_sprechertrennung("cuda") == erwartet


def test_ohne_torch_kein_grafikspeicher_und_freigeben_ist_harmlos():
    assert model_service.freier_grafikspeicher() is None  # Entwicklungsumgebung ohne torch
    model_service.gpu_speicher_freigeben()


# --------------------------------------------------------------------------
# Eigener Prozess
# --------------------------------------------------------------------------
def _lauf(ergebnis=None, returncode=0, stderr=""):
    aufrufe = []

    def lauf(befehl, **kwargs):
        aufrufe.append((befehl, kwargs))
        if ergebnis is not None:
            Path(befehl[4]).write_text(ergebnis, encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    return lauf, aufrufe


def test_eigener_prozess_liefert_turns_und_embeddings(tmp_path):
    lauf, aufrufe = _lauf(json.dumps({"turns": TURNS, "embeddings": EMBEDDINGS}))
    turns, embeddings = diarisierung_prozess.diarisiere_in_eigenem_prozess(
        tmp_path / "a.wav", 2, 3, "cuda", python="py", lauf_fn=lauf
    )
    assert (turns, embeddings) == (TURNS, EMBEDDINGS)
    befehl, kwargs = aufrufe[0]
    assert befehl[:3] == ["py", "-m", "protokoll_assistent.services.diarisierung_prozess"]
    assert befehl[5:] == ["--geraet", "cuda", "--min", "2", "--max", "3"]
    assert kwargs["cwd"] == _projektwurzel()  # wie jeder Modulstart (CLAUDE.md, Regel 9)


def _projektwurzel():
    from protokoll_assistent.utils.paths import get_project_root

    return get_project_root()


def test_ohne_sprechervorgabe_keine_grenzen_im_aufruf(tmp_path):
    lauf, aufrufe = _lauf(json.dumps({"turns": [], "embeddings": {}}))
    diarisierung_prozess.diarisiere_in_eigenem_prozess(tmp_path / "a.wav", None, None, lauf_fn=lauf)
    assert "--min" not in aufrufe[0][0] and "--max" not in aufrufe[0][0]


@pytest.mark.parametrize(
    ("lauf", "meldung"),
    [
        (_lauf(None, returncode=3, stderr="Zeile 1\nCUDA error: out of memory")[0], "Code 3.*out of memory"),
        (_lauf(None, returncode=0)[0], "gescheitert"),  # kein Ergebnis geschrieben
        (_lauf("{kaputt")[0], "unlesbar"),
        (_lauf(json.dumps({"turns": []}))[0], "unlesbar"),  # embeddings fehlen
    ],
)
def test_eigener_prozess_fehler_werden_lesbar_gemeldet(tmp_path, lauf, meldung):
    with pytest.raises(diarisierung_prozess.DiarisierungsprozessFehler, match=meldung):
        diarisierung_prozess.diarisiere_in_eigenem_prozess(tmp_path / "a.wav", None, None, lauf_fn=lauf)


@pytest.mark.parametrize("fehler", [OSError("kein python"), subprocess.TimeoutExpired("py", 1)])
def test_eigener_prozess_startet_nicht_oder_haengt(tmp_path, fehler):
    def lauf(befehl, **kwargs):
        raise fehler

    with pytest.raises(diarisierung_prozess.DiarisierungsprozessFehler, match="lief nicht"):
        diarisierung_prozess.diarisiere_in_eigenem_prozess(tmp_path / "a.wav", None, None, lauf_fn=lauf)


def test_main_im_eigenen_prozess_schreibt_das_ergebnis(tmp_path, monkeypatch):
    geladen = []
    monkeypatch.setattr(model_service, "load_pyannote_pipeline", lambda geraet: geladen.append(geraet) or "pipeline")
    monkeypatch.setattr(transcription_service, "load_audio_array", lambda pfad: [0.0])
    monkeypatch.setattr(diarization_service, "build_waveform_dict", lambda audio: {"waveform": audio})

    def diarize(pipeline, wellenform, mini, maxi, embeddings_out):
        assert (pipeline, mini, maxi) == ("pipeline", 2, None)
        embeddings_out.update(EMBEDDINGS)
        return TURNS

    monkeypatch.setattr(diarization_service, "diarize_waveform", diarize)
    ausgabe = tmp_path / "ergebnis.json"
    assert diarisierung_prozess.main([str(tmp_path / "a.wav"), str(ausgabe), "--min", "2", "--geraet", "cuda"]) == 0
    assert geladen == ["cuda"]
    assert json.loads(ausgabe.read_text(encoding="utf-8")) == {"turns": TURNS, "embeddings": EMBEDDINGS}


# --------------------------------------------------------------------------
# Pipeline: welcher Weg wird genommen
# --------------------------------------------------------------------------
def _settings(tmp_path):
    return pipeline_service.PipelineSettings(source_path=tmp_path / "a.wav", output_dir=tmp_path, min_speakers=None, max_speakers=4)


def _cpu_weg(monkeypatch):
    geladen = []
    monkeypatch.setattr(model_service, "load_pyannote_pipeline", lambda geraet: geladen.append(geraet) or "p")
    monkeypatch.setattr(transcription_service, "load_audio_array", lambda pfad: [0.0])
    monkeypatch.setattr(diarization_service, "build_waveform_dict", lambda audio: {})
    monkeypatch.setattr(
        diarization_service, "diarize_waveform", lambda p, w, mi, ma, embeddings_out: embeddings_out.update({"C": [1.0]}) or ["cpu-turn"]
    )
    return geladen


def test_pipeline_trennt_auf_der_gpu_im_eigenen_prozess(tmp_path, monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    gestartet = []
    monkeypatch.setattr(
        diarisierung_prozess, "diarisiere_in_eigenem_prozess", lambda *a: gestartet.append(a) or (TURNS, EMBEDDINGS)
    )
    geladen = _cpu_weg(monkeypatch)
    meldungen: list[str] = []
    callbacks = pipeline_service.PipelineCallbacks(on_log=meldungen.append)

    ergebnis = pipeline_service._sprechertrennung(tmp_path / "a.wav", _settings(tmp_path), "cuda", callbacks)

    assert ergebnis == (TURNS, EMBEDDINGS)
    assert gestartet == [(tmp_path / "a.wav", None, 4, "cuda")]
    assert geladen == []  # pyannote wird NICHT im eigenen Prozess geladen
    assert any("eigenen Prozess" in m for m in meldungen)


def test_pipeline_faellt_auf_die_cpu_zurueck_wenn_der_prozess_scheitert(tmp_path, monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)

    def scheitert(*a):
        raise diarisierung_prozess.DiarisierungsprozessFehler("Prozess weg")

    monkeypatch.setattr(diarisierung_prozess, "diarisiere_in_eigenem_prozess", scheitert)
    geladen = _cpu_weg(monkeypatch)
    meldungen: list[str] = []

    ergebnis = pipeline_service._sprechertrennung(
        tmp_path / "a.wav", _settings(tmp_path), "cuda", pipeline_service.PipelineCallbacks(on_log=meldungen.append)
    )

    assert ergebnis == (["cpu-turn"], {"C": [1.0]}) and geladen == ["cpu"]
    assert any("Prozess weg" in m and "CPU" in m for m in meldungen)


def test_pipeline_auf_der_cpu_ohne_eigenen_prozess(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "cpu")
    monkeypatch.setattr(diarisierung_prozess, "diarisiere_in_eigenem_prozess", lambda *a: pytest.fail("kein Prozess erwartet"))
    geladen = _cpu_weg(monkeypatch)
    pipeline_service._sprechertrennung(tmp_path / "a.wav", _settings(tmp_path), "cuda", pipeline_service.PipelineCallbacks())
    assert geladen == ["cpu"]


# --------------------------------------------------------------------------
# Grafikspeicher fuer Whisper
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("device", "frei", "entladen_erwartet"),
    [
        ("cpu", 0, False),  # Whisper auf der CPU braucht keinen Grafikspeicher
        ("cuda", None, False),  # keine GPU erkennbar
        ("cuda", 5 * 1024**3, False),  # genug frei: Ollama darf geladen bleiben
        ("cuda", 1 * 1024**3, True),  # zu wenig: Ollama entlaedt
    ],
)
def test_ollama_entlaedt_nur_wenn_der_grafikspeicher_fehlt(monkeypatch, device, frei, entladen_erwartet):
    aufgerufen = []
    monkeypatch.setattr(model_service, "freier_grafikspeicher", lambda: frei)
    monkeypatch.setattr(ollama_service, "modelle_entladen", lambda: aufgerufen.append(True) or ["qwen3.5:4b-q4_K_M"])
    meldungen: list[str] = []
    pipeline_service._grafikspeicher_fuer_whisper_freimachen(device, pipeline_service.PipelineCallbacks(on_log=meldungen.append))
    assert bool(aufgerufen) is entladen_erwartet
    assert any("qwen3.5" in m for m in meldungen) is entladen_erwartet


def test_modelle_entladen_schickt_keep_alive_null_je_geladenem_modell(monkeypatch):
    monkeypatch.setattr(
        ollama_service, "_get_json", lambda url, timeout: {"models": [{"name": "qwen3.5:4b-q4_K_M"}, {"model": "bge-m3"}, "kaputt"]}
    )
    gesendet = []

    class _Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def oeffnen(request, timeout=None):
        gesendet.append(json.loads(request.data.decode("utf-8")))
        if gesendet[-1]["model"] == "bge-m3":
            raise OSError("weg")
        return _Antwort()

    assert ollama_service.modelle_entladen(opener=oeffnen) == ["qwen3.5:4b-q4_K_M"]
    assert gesendet == [{"model": "qwen3.5:4b-q4_K_M", "keep_alive": 0}, {"model": "bge-m3", "keep_alive": 0}]


def test_modelle_entladen_ohne_ollama_tut_nichts(monkeypatch):
    def nicht_erreichbar(url, timeout):
        raise OSError("kein Dienst")

    monkeypatch.setattr(ollama_service, "_get_json", nicht_erreichbar)
    assert ollama_service.modelle_entladen() == []
