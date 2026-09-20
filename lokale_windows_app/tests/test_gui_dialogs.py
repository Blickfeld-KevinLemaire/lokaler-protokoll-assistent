"""Tests fuer die Zusatzdialoge, den Hintergrund-Arbeiter und das Theme."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtWidgets import QDialog  # noqa: E402

from gui import dialogs, strings, theme  # noqa: E402
from gui import worker as worker_modul  # noqa: E402
from services import pipeline_service  # noqa: E402
from utils import paths  # noqa: E402


# --------------------------------------------------------------------------
# strings / theme
# --------------------------------------------------------------------------
def test_datenschutzhinweis_sagt_lokal():
    assert "lokal" in strings.PRIVACY_NOTICE.lower()
    assert "keine" in strings.PRIVACY_NOTICE.lower()


def test_theme_wird_angewendet(qt_app):
    class _AppAttrappe:
        def __init__(self):
            self.stil = None
            self.qss = None

        def setStyle(self, name):
            self.stil = name

        def setStyleSheet(self, qss):
            self.qss = qss

    attrappe = _AppAttrappe()
    theme.apply_theme(attrappe)

    assert attrappe.stil == "Fusion"
    assert theme.ACCENT in attrappe.qss
    assert "QProgressBar" in attrappe.qss


# --------------------------------------------------------------------------
# SystemPromptDialog
# --------------------------------------------------------------------------
@pytest.fixture
def prompt_dateien(tmp_path, monkeypatch):
    aktuell = tmp_path / "systemprompt_protokoll.txt"
    standard = tmp_path / "systemprompt_protokoll.default.txt"
    standard.write_text("Der Standardprompt.", encoding="utf-8")
    monkeypatch.setattr(paths, "get_system_prompt_file", lambda: aktuell)
    monkeypatch.setattr(paths, "get_default_system_prompt_file", lambda: standard)
    monkeypatch.setattr(dialogs, "get_system_prompt_file", lambda: aktuell)
    monkeypatch.setattr(dialogs, "get_default_system_prompt_file", lambda: standard)
    return aktuell, standard


def test_prompt_dialog_zeigt_standard_wenn_keiner_gespeichert(prompt_dateien, qt_widgets):
    dialog = qt_widgets(dialogs.SystemPromptDialog())
    assert dialog.editor.toPlainText() == "Der Standardprompt."


def test_prompt_dialog_zeigt_gespeicherten_prompt(prompt_dateien, qt_widgets):
    aktuell, _standard = prompt_dateien
    aktuell.write_text("Mein eigener Prompt.", encoding="utf-8")

    dialog = qt_widgets(dialogs.SystemPromptDialog())

    assert dialog.editor.toPlainText() == "Mein eigener Prompt."


def test_prompt_dialog_ohne_jede_datei(prompt_dateien, qt_widgets):
    _aktuell, standard = prompt_dateien
    standard.unlink()

    dialog = qt_widgets(dialogs.SystemPromptDialog())

    assert dialog.editor.toPlainText() == ""


def test_prompt_dialog_zuruecksetzen(prompt_dateien, qt_widgets):
    aktuell, _standard = prompt_dateien
    aktuell.write_text("Etwas anderes.", encoding="utf-8")
    dialog = qt_widgets(dialogs.SystemPromptDialog())

    dialog._reset_to_default()

    assert dialog.editor.toPlainText() == "Der Standardprompt."


def test_prompt_dialog_zuruecksetzen_ohne_standarddatei(prompt_dateien, qt_widgets):
    _aktuell, standard = prompt_dateien
    dialog = qt_widgets(dialogs.SystemPromptDialog())
    dialog.editor.setPlainText("unveraendert")
    standard.unlink()

    dialog._reset_to_default()

    assert dialog.editor.toPlainText() == "unveraendert"


def test_prompt_dialog_speichern(prompt_dateien, qt_widgets):
    aktuell, _standard = prompt_dateien
    dialog = qt_widgets(dialogs.SystemPromptDialog())
    dialog.editor.setPlainText("Neuer Prompt.")

    dialog._save_and_close()

    assert aktuell.read_text(encoding="utf-8") == "Neuer Prompt."
    assert dialog.result() == QDialog.DialogCode.Accepted


# --------------------------------------------------------------------------
# render_check_item
# --------------------------------------------------------------------------
class _Pruefung:
    def __init__(self, ok, critical=False, detail="Detailtext", label="Bezeichnung"):
        self.ok = ok
        self.critical = critical
        self.detail = detail
        self.label = label


@pytest.mark.parametrize(
    ("pruefung", "erwartetes_symbol"),
    [
        (_Pruefung(ok=True), "OK"),
        (_Pruefung(ok=False, critical=True), "FEHLT"),
        (_Pruefung(ok=False, critical=False), "HINWEIS"),
    ],
)
def test_render_check_item_symbole(qt_app, pruefung, erwartetes_symbol):
    item = dialogs.render_check_item(pruefung)
    assert item.text().startswith(f"[{erwartetes_symbol}]")
    assert "Detailtext" in item.text()


def test_render_check_item_faerbt_unterschiedlich(qt_app):
    ok = dialogs.render_check_item(_Pruefung(ok=True)).foreground().color().name()
    kritisch = dialogs.render_check_item(
        _Pruefung(ok=False, critical=True)
    ).foreground().color().name()
    hinweis = dialogs.render_check_item(
        _Pruefung(ok=False, critical=False)
    ).foreground().color().name()

    assert len({ok, kritisch, hinweis}) == 3


# --------------------------------------------------------------------------
# DiagnosticsRunner / DiagnosticsDialog
# --------------------------------------------------------------------------
def test_diagnostics_runner_meldet_ergebnisse(qt_app, tmp_path, monkeypatch):
    from utils import diagnostics

    erwartet = [_Pruefung(ok=True)]
    monkeypatch.setattr(diagnostics, "run_diagnostics", lambda ordner: erwartet)

    runner = dialogs.DiagnosticsRunner(tmp_path)
    empfangen = []
    runner.finished_with_results.connect(empfangen.append)

    runner.run()  # direkt, ohne echten Thread

    assert empfangen == [erwartet]


def test_diagnostics_dialog_zeigt_ergebnisse(qt_app, qt_widgets, tmp_path, monkeypatch):
    # Der Dialog startet sonst einen echten Hintergrund-Thread.
    gestartet = []
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: gestartet.append(True))

    dialog = qt_widgets(dialogs.DiagnosticsDialog(tmp_path))
    assert gestartet == [True]
    assert "läuft" in dialog.status_label.text()

    dialog._show_results(
        [
            _Pruefung(ok=True, label="Python"),
            _Pruefung(ok=False, critical=True, label="CUDA"),
        ]
    )

    assert "abgeschlossen" in dialog.status_label.text()
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 0).text() == "Python"
    assert dialog.table.item(1, 1).text().startswith("[FEHLT]")


def test_show_error_nutzt_messagebox(qt_app, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        dialogs.QMessageBox, "critical", lambda parent, titel, text: aufrufe.append((titel, text))
    )
    dialogs.show_error(None, "Titel", "Meldung")
    assert aufrufe == [("Titel", "Meldung")]


# --------------------------------------------------------------------------
# PipelineWorker
# --------------------------------------------------------------------------
@pytest.fixture
def worker(qt_app):
    return worker_modul.PipelineWorker(settings=object())


def test_worker_abbruch_wird_gemerkt(worker):
    assert worker._should_cancel() is False
    worker.request_cancel()
    assert worker._should_cancel() is True


def test_worker_meldet_erfolg(worker, monkeypatch):
    ergebnis = {"fertig": True}
    monkeypatch.setattr(pipeline_service, "run_pipeline", lambda s, c: ergebnis)

    empfangen = []
    worker.finished_ok.connect(empfangen.append)

    worker.run()

    assert empfangen == [ergebnis]


def test_worker_reicht_rueckrufe_als_signale_durch(worker, monkeypatch):
    def fake_run(settings, callbacks):
        callbacks.on_stage("transkription", "laeuft")
        callbacks.on_chunk_progress(2, 5)
        callbacks.on_overall_progress(0.4)
        callbacks.on_preview("Vorschau")
        callbacks.on_log("Eine Zeile")
        assert callbacks.should_cancel() is False
        return "fertig"

    monkeypatch.setattr(pipeline_service, "run_pipeline", fake_run)

    stufen, chunks, fortschritt, vorschau, protokoll = [], [], [], [], []
    worker.stage_changed.connect(lambda k, d: stufen.append((k, d)))
    worker.chunk_progress.connect(lambda c, t: chunks.append((c, t)))
    worker.overall_progress.connect(fortschritt.append)
    worker.preview_updated.connect(vorschau.append)
    worker.log_message.connect(protokoll.append)

    worker.run()

    assert stufen == [("transkription", "laeuft")]
    assert chunks == [(2, 5)]
    assert fortschritt == [pytest.approx(0.4)]
    assert vorschau == ["Vorschau"]
    assert protokoll == ["Eine Zeile"]


def test_worker_meldet_abbruch(worker, monkeypatch):
    def abbrechen(_s, _c):
        raise pipeline_service.PipelineCancelled()

    monkeypatch.setattr(pipeline_service, "run_pipeline", abbrechen)

    abgebrochen = []
    worker.cancelled.connect(lambda: abgebrochen.append(True))

    worker.run()

    assert abgebrochen == [True]


def test_worker_meldet_pipeline_fehler(worker, monkeypatch):
    def werfen(_s, _c):
        raise pipeline_service.PipelineError("Modell fehlt")

    monkeypatch.setattr(pipeline_service, "run_pipeline", werfen)

    fehler = []
    worker.failed.connect(fehler.append)

    worker.run()

    assert fehler == ["Modell fehlt"]


def test_worker_zeigt_bei_unerwartetem_fehler_keinen_traceback(worker, monkeypatch):
    def werfen(_s, _c):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline_service, "run_pipeline", werfen)

    fehler = []
    worker.failed.connect(fehler.append)

    worker.run()

    assert len(fehler) == 1
    assert "Logdatei" in fehler[0]
    assert "Traceback" not in fehler[0]


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
    monkeypatch.setattr(pipeline_service, "run_transcription", lambda s, c: ergebnis)

    empfangen = []
    transkriptions_arbeiter.finished_ok.connect(empfangen.append)

    transkriptions_arbeiter.run()

    assert empfangen == [ergebnis]


def test_transkriptions_arbeiter_reicht_rueckrufe_als_signale_durch(transkriptions_arbeiter, monkeypatch):
    def fake_run(settings, callbacks):
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
    def abbrechen(_s, _c):
        raise pipeline_service.PipelineCancelled()

    monkeypatch.setattr(pipeline_service, "run_transcription", abbrechen)

    abgebrochen = []
    transkriptions_arbeiter.cancelled.connect(lambda: abgebrochen.append(True))

    transkriptions_arbeiter.run()

    assert abgebrochen == [True]


def test_transkriptions_arbeiter_meldet_pipeline_fehler(transkriptions_arbeiter, monkeypatch):
    def werfen(_s, _c):
        raise pipeline_service.PipelineError("Modell fehlt")

    monkeypatch.setattr(pipeline_service, "run_transcription", werfen)

    fehler = []
    transkriptions_arbeiter.failed.connect(fehler.append)

    transkriptions_arbeiter.run()

    assert fehler == ["Modell fehlt"]


def test_transkriptions_arbeiter_zeigt_bei_unerwartetem_fehler_keinen_traceback(
    transkriptions_arbeiter, monkeypatch
):
    def werfen(_s, _c):
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
    monkeypatch.setattr(pipeline_service, "run_protocol", lambda s, c: ergebnis)

    empfangen = []
    protokoll_arbeiter.finished_ok.connect(empfangen.append)

    protokoll_arbeiter.run()

    assert empfangen == [ergebnis]


def test_protokoll_arbeiter_reicht_rueckrufe_als_signale_durch(protokoll_arbeiter, monkeypatch):
    def fake_run(settings, callbacks):
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
    def abbrechen(_s, _c):
        raise pipeline_service.PipelineCancelled()

    monkeypatch.setattr(pipeline_service, "run_protocol", abbrechen)

    abgebrochen = []
    protokoll_arbeiter.cancelled.connect(lambda: abgebrochen.append(True))

    protokoll_arbeiter.run()

    assert abgebrochen == [True]


def test_protokoll_arbeiter_meldet_pipeline_fehler(protokoll_arbeiter, monkeypatch):
    def werfen(_s, _c):
        raise pipeline_service.PipelineError("Ollama nicht erreichbar")

    monkeypatch.setattr(pipeline_service, "run_protocol", werfen)

    fehler = []
    protokoll_arbeiter.failed.connect(fehler.append)

    protokoll_arbeiter.run()

    assert fehler == ["Ollama nicht erreichbar"]


def test_protokoll_arbeiter_zeigt_bei_unerwartetem_fehler_keinen_traceback(protokoll_arbeiter, monkeypatch):
    def werfen(_s, _c):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline_service, "run_protocol", werfen)

    fehler = []
    protokoll_arbeiter.failed.connect(fehler.append)

    protokoll_arbeiter.run()

    assert len(fehler) == 1
    assert "Logdatei" in fehler[0]
    assert "Traceback" not in fehler[0]
