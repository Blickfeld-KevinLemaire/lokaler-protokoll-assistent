"""Direkte Tests fuer 'gui/worker.py' (TranscriptionWorker/ProtocolWorker/
DateiHashWorker), unabhaengig vom Hauptfenster. 'pipeline_service' wird
durchgehend gefaked - kein Test spricht echte ML-Modelle an."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent.gui import worker as worker_modul  # noqa: E402
from protokoll_assistent.services import manifest_service, pipeline_service  # noqa: E402


# --------------------------------------------------------------------------
# TranscriptionWorker
# --------------------------------------------------------------------------
@pytest.fixture
def transkriptions_arbeiter(qt_app):
    return worker_modul.TranscriptionWorker(settings=object())


def test_transkriptions_arbeiter_abbruch_wird_gemerkt(transkriptions_arbeiter):
    assert transkriptions_arbeiter._should_cancel() is False
    transkriptions_arbeiter.request_cancel()
    assert transkriptions_arbeiter._should_cancel() is True


def test_transkriptions_arbeiter_meldet_erfolg(transkriptions_arbeiter, monkeypatch):
    ergebnis = {"fertig": True}
    monkeypatch.setattr(pipeline_service, "run_transcription", lambda s, c, **kw: ergebnis)

    empfangen = []
    transkriptions_arbeiter.finished_ok.connect(empfangen.append)
    transkriptions_arbeiter.run()

    assert empfangen == [ergebnis]


def test_transkriptions_arbeiter_reicht_api_funktionen_durch(qt_app, monkeypatch):
    aufgezeichnet = {}

    def fake_run(settings, callbacks, transcribe_chunk_fn=None, diarize_fn=None):
        aufgezeichnet["transcribe_chunk_fn"] = transcribe_chunk_fn
        aufgezeichnet["diarize_fn"] = diarize_fn
        return "ok"

    monkeypatch.setattr(pipeline_service, "run_transcription", fake_run)

    def chunk_fn(pfad):
        return []

    def diarize_fn(pfad, mn, mx):
        return []

    arbeiter = worker_modul.TranscriptionWorker(
        settings=object(), transcribe_chunk_fn=chunk_fn, diarize_fn=diarize_fn
    )
    arbeiter.run()

    assert aufgezeichnet["transcribe_chunk_fn"] is chunk_fn
    assert aufgezeichnet["diarize_fn"] is diarize_fn


def test_transkriptions_arbeiter_reicht_rueckrufe_als_signale_durch(transkriptions_arbeiter, monkeypatch):
    def fake_run(settings, callbacks, **kw):
        callbacks.on_stage("transkription", "laeuft")
        callbacks.on_chunk_progress(2, 5)
        callbacks.on_overall_progress(0.4)
        callbacks.on_preview("Vorschau")
        callbacks.on_log("Eine Zeile")
        assert callbacks.should_cancel() is False
        return "fertig"

    monkeypatch.setattr(pipeline_service, "run_transcription", fake_run)

    stufen, chunks, fortschritt, vorschau, protokoll = [], [], [], [], []
    transkriptions_arbeiter.stage_changed.connect(lambda k, d: stufen.append((k, d)))
    transkriptions_arbeiter.chunk_progress.connect(lambda c, t: chunks.append((c, t)))
    transkriptions_arbeiter.overall_progress.connect(fortschritt.append)
    transkriptions_arbeiter.preview_updated.connect(vorschau.append)
    transkriptions_arbeiter.log_message.connect(protokoll.append)

    transkriptions_arbeiter.run()

    assert stufen == [("transkription", "laeuft")]
    assert chunks == [(2, 5)]
    assert fortschritt == [pytest.approx(0.4)]
    assert vorschau == ["Vorschau"]
    assert protokoll == ["Eine Zeile"]


def test_transkriptions_arbeiter_meldet_abbruch(transkriptions_arbeiter, monkeypatch):
    def abbrechen(_s, _c, **kw):
        raise pipeline_service.PipelineCancelled()

    monkeypatch.setattr(pipeline_service, "run_transcription", abbrechen)

    abgebrochen = []
    transkriptions_arbeiter.cancelled.connect(lambda: abgebrochen.append(True))
    transkriptions_arbeiter.run()

    assert abgebrochen == [True]


def test_transkriptions_arbeiter_meldet_pipeline_fehler(transkriptions_arbeiter, monkeypatch):
    def werfen(_s, _c, **kw):
        raise pipeline_service.PipelineError("Modell fehlt")

    monkeypatch.setattr(pipeline_service, "run_transcription", werfen)

    fehler = []
    transkriptions_arbeiter.failed.connect(fehler.append)
    transkriptions_arbeiter.run()

    assert fehler == ["Modell fehlt"]


def test_transkriptions_arbeiter_zeigt_bei_unerwartetem_fehler_keinen_traceback(
    transkriptions_arbeiter, monkeypatch
):
    def werfen(_s, _c, **kw):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline_service, "run_transcription", werfen)

    fehler = []
    transkriptions_arbeiter.failed.connect(fehler.append)
    transkriptions_arbeiter.run()

    assert len(fehler) == 1
    assert "Logdatei" in fehler[0]
    assert "Traceback" not in fehler[0]


# --------------------------------------------------------------------------
# ProtocolWorker
# --------------------------------------------------------------------------
@pytest.fixture
def protokoll_arbeiter(qt_app):
    return worker_modul.ProtocolWorker(settings=object())


def test_protokoll_arbeiter_abbruch_wird_gemerkt(protokoll_arbeiter):
    assert protokoll_arbeiter._should_cancel() is False
    protokoll_arbeiter.request_cancel()
    assert protokoll_arbeiter._should_cancel() is True


def test_protokoll_arbeiter_meldet_erfolg(protokoll_arbeiter, monkeypatch):
    ergebnis = {"fertig": True}
    monkeypatch.setattr(pipeline_service, "run_protocol", lambda s, c, **kw: ergebnis)

    empfangen = []
    protokoll_arbeiter.finished_ok.connect(empfangen.append)
    protokoll_arbeiter.run()

    assert empfangen == [ergebnis]


def test_protokoll_arbeiter_reicht_generate_fn_durch(qt_app, monkeypatch):
    aufgezeichnet = {}

    def fake_run(settings, callbacks, protocol_generate_fn=None):
        aufgezeichnet["protocol_generate_fn"] = protocol_generate_fn
        return "ok"

    monkeypatch.setattr(pipeline_service, "run_protocol", fake_run)

    def generate_fn(prompt, system):
        return {}

    arbeiter = worker_modul.ProtocolWorker(settings=object(), protocol_generate_fn=generate_fn)
    arbeiter.run()

    assert aufgezeichnet["protocol_generate_fn"] is generate_fn


def test_protokoll_arbeiter_reicht_rueckrufe_als_signale_durch(protokoll_arbeiter, monkeypatch):
    def fake_run(settings, callbacks, **kw):
        callbacks.on_stage("protokoll_auswertung", "laeuft")
        callbacks.on_overall_progress(0.7)
        callbacks.on_log("Eine Zeile")
        assert callbacks.should_cancel() is False
        return "fertig"

    monkeypatch.setattr(pipeline_service, "run_protocol", fake_run)

    stufen, fortschritt, protokoll = [], [], []
    protokoll_arbeiter.stage_changed.connect(lambda k, d: stufen.append((k, d)))
    protokoll_arbeiter.overall_progress.connect(fortschritt.append)
    protokoll_arbeiter.log_message.connect(protokoll.append)

    protokoll_arbeiter.run()

    assert stufen == [("protokoll_auswertung", "laeuft")]
    assert fortschritt == [pytest.approx(0.7)]
    assert protokoll == ["Eine Zeile"]


def test_protokoll_arbeiter_meldet_abbruch(protokoll_arbeiter, monkeypatch):
    def abbrechen(_s, _c, **kw):
        raise pipeline_service.PipelineCancelled()

    monkeypatch.setattr(pipeline_service, "run_protocol", abbrechen)

    abgebrochen = []
    protokoll_arbeiter.cancelled.connect(lambda: abgebrochen.append(True))
    protokoll_arbeiter.run()

    assert abgebrochen == [True]


def test_protokoll_arbeiter_meldet_pipeline_fehler(protokoll_arbeiter, monkeypatch):
    def werfen(_s, _c, **kw):
        raise pipeline_service.PipelineError("Ollama nicht erreichbar")

    monkeypatch.setattr(pipeline_service, "run_protocol", werfen)

    fehler = []
    protokoll_arbeiter.failed.connect(fehler.append)
    protokoll_arbeiter.run()

    assert fehler == ["Ollama nicht erreichbar"]


def test_protokoll_arbeiter_zeigt_bei_unerwartetem_fehler_keinen_traceback(protokoll_arbeiter, monkeypatch):
    def werfen(_s, _c, **kw):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline_service, "run_protocol", werfen)

    fehler = []
    protokoll_arbeiter.failed.connect(fehler.append)
    protokoll_arbeiter.run()

    assert len(fehler) == 1
    assert "Logdatei" in fehler[0]
    assert "Traceback" not in fehler[0]


# --------------------------------------------------------------------------
# DateiHashWorker
# --------------------------------------------------------------------------
def test_hash_arbeiter_meldet_ergebnis(qt_app, tmp_path):
    datei = tmp_path / "audio.wav"
    datei.write_bytes(b"\x00" * 32)

    ergebnisse = []
    arbeiter = worker_modul.DateiHashWorker(datei)
    arbeiter.fertig.connect(lambda pfad, wert: ergebnisse.append((pfad, wert)))
    arbeiter.run()

    assert ergebnisse == [(str(datei), manifest_service.compute_file_hash(datei))]


def test_hash_arbeiter_meldet_lesefehler(qt_app, tmp_path):
    fehler = []
    arbeiter = worker_modul.DateiHashWorker(tmp_path / "gibtesnicht.mp3")
    arbeiter.fehlgeschlagen.connect(lambda pfad, text: fehler.append(text))
    arbeiter.run()

    assert len(fehler) == 1


# --------------------------------------------------------------------------
# OllamaPullWorker
# --------------------------------------------------------------------------
def test_ollama_pull_arbeiter_meldet_fortschritt_und_ende(qt_app):
    from protokoll_assistent.services import ollama_service  # noqa: F401

    def pull(modell, progress_cb):
        progress_cb("pulling", 5, 10)

    arbeiter = worker_modul.OllamaPullWorker("qwen3:4b", pull_fn=pull)
    fortschritt, fertig = [], []
    arbeiter.fortschritt.connect(lambda *a: fortschritt.append(a))
    arbeiter.fertig.connect(fertig.append)

    arbeiter.run()

    assert fortschritt == [("pulling", 5, 10)]
    assert fertig == ["qwen3:4b"]


def test_ollama_pull_arbeiter_meldet_ollama_fehler_lesbar(qt_app):
    from protokoll_assistent.services import ollama_service

    def pull(modell, progress_cb):
        raise ollama_service.OllamaError("nicht erreichbar")

    arbeiter = worker_modul.OllamaPullWorker("m", pull_fn=pull)
    fehler = []
    arbeiter.fehlgeschlagen.connect(lambda *a: fehler.append(a))
    arbeiter.run()
    assert fehler == [("m", "nicht erreichbar")]


def test_ollama_pull_arbeiter_faengt_unerwartete_fehler(qt_app):
    def pull(modell, progress_cb):
        raise ValueError("kaputt")

    arbeiter = worker_modul.OllamaPullWorker("m", pull_fn=pull)
    fehler = []
    arbeiter.fehlgeschlagen.connect(lambda *a: fehler.append(a))
    arbeiter.run()
    assert fehler and "kaputt" in fehler[0][1]


def test_ollama_pull_arbeiter_nutzt_standardmaessig_den_dienst(qt_app, monkeypatch):
    from protokoll_assistent.services import ollama_service

    aufrufe = []
    monkeypatch.setattr(ollama_service, "pull_model", lambda modell, progress_cb: aufrufe.append(modell))
    arbeiter = worker_modul.OllamaPullWorker("qwen3:8b")
    arbeiter.run()
    assert aufrufe == ["qwen3:8b"]


# --------------------------------------------------------------------------
# ChatWorker
# --------------------------------------------------------------------------
def _chat_arbeiter(tmp_path, embed_fn=None, chat_fn=None, dokumente=None, einstellungen=None):
    from protokoll_assistent.services import chat_service

    pfad = tmp_path / "a_lokal_transkript_1.json"
    pfad.write_text('{"segmente": [{"start_sekunden": 1.0, "text": "Das Budget ist 5000 Euro."}]}', encoding="utf-8")
    return worker_modul.ChatWorker(
        "Wie hoch ist das Budget?",
        dokumente if dokumente is not None else [pfad],
        [],
        einstellungen or chat_service.ChatEinstellungen("lokal", "qwen3:8b", "bge-m3"),
        tmp_path / "cache",
        embed_fn=embed_fn,
        chat_fn=chat_fn,
    )


def test_chat_arbeiter_liefert_antwort_und_quellen(qt_app, tmp_path):
    def chat(nachrichten, on_token):
        on_token("Antwort")
        return "Antwort"

    arbeiter = _chat_arbeiter(tmp_path, lambda texte: [[1.0, 0.0] for _ in texte], chat)
    status, tokens, fertig = [], [], []
    arbeiter.status.connect(status.append)
    arbeiter.token.connect(tokens.append)
    arbeiter.fertig.connect(lambda antwort, quellen: fertig.append((antwort, quellen)))

    arbeiter.run()

    assert tokens == ["Antwort"] and status
    assert fertig and fertig[0][0] == "Antwort" and fertig[0][1][0].startswith("a_lokal_transkript_1")


def test_chat_arbeiter_meldet_bekannte_fehler_lesbar(qt_app, tmp_path):
    from protokoll_assistent.services import ollama_service

    def embed(texte):
        raise ollama_service.OllamaError("Ollama ist nicht erreichbar")

    arbeiter = _chat_arbeiter(tmp_path, embed, lambda n, t: "x")
    fehler = []
    arbeiter.fehlgeschlagen.connect(fehler.append)
    arbeiter.run()
    assert fehler == ["Ollama ist nicht erreichbar"]

    fehlt = _chat_arbeiter(tmp_path, dokumente=[tmp_path / "gibt-es-nicht.json"])
    fehler2 = []
    fehlt.fehlgeschlagen.connect(fehler2.append)
    fehlt.run()
    assert "nicht gelesen" in fehler2[0]


def test_chat_arbeiter_faengt_unerwartete_fehler(qt_app, tmp_path):
    def chat(nachrichten, on_token):
        raise ValueError("kaputt")

    arbeiter = _chat_arbeiter(tmp_path, lambda texte: [[1.0] for _ in texte], chat)
    fehler = []
    arbeiter.fehlgeschlagen.connect(fehler.append)
    arbeiter.run()
    assert fehler and "kaputt" in fehler[0]


def test_chat_arbeiter_bildet_ohne_hereingereichte_funktionen_die_aus_den_einstellungen(qt_app, tmp_path, monkeypatch):
    from protokoll_assistent.services import chat_service

    monkeypatch.setattr(
        chat_service, "funktionen_aus_einstellungen", lambda e: (lambda texte: [[1.0] for _ in texte], lambda n, t: "ok")
    )
    arbeiter = _chat_arbeiter(tmp_path)
    fertig = []
    arbeiter.fertig.connect(lambda antwort, quellen: fertig.append(antwort))
    arbeiter.run()
    assert fertig == ["ok"]


# --------------------------------------------------------------------------
# ChatCheckWorker
# --------------------------------------------------------------------------
def test_chat_check_arbeiter_liefert_die_pruefungen(qt_app):
    from protokoll_assistent.utils.diagnostics import DiagnosticCheck

    ergebnis = [DiagnosticCheck("a", "A", True, "ok")]
    arbeiter = worker_modul.ChatCheckWorker(object(), check_fn=lambda e: ergebnis)
    erhalten = []
    arbeiter.fertig.connect(erhalten.append)
    arbeiter.run()
    assert erhalten == [ergebnis]


def test_chat_check_arbeiter_macht_aus_einem_unerwarteten_fehler_eine_pruefung(qt_app):
    def werfen(e):
        raise ValueError("kaputt")

    arbeiter = worker_modul.ChatCheckWorker(object(), check_fn=werfen)
    erhalten = []
    arbeiter.fertig.connect(erhalten.append)
    arbeiter.run()
    assert erhalten[0][0].ok is False and "kaputt" in erhalten[0][0].detail


def test_chat_check_arbeiter_nutzt_standardmaessig_den_systemcheck(qt_app, monkeypatch):
    from protokoll_assistent.services import chat_service

    monkeypatch.setattr(chat_service, "systemcheck", lambda e: ["gerufen"])
    arbeiter = worker_modul.ChatCheckWorker(object())
    erhalten = []
    arbeiter.fertig.connect(erhalten.append)
    arbeiter.run()
    assert erhalten == [["gerufen"]]
