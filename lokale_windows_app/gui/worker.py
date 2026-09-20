"""Hintergrundverarbeitung ueber QThread, damit die Oberflaeche waehrend
der Transkription/Diarisierung/Protokollauswertung nicht einfriert."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from services import manifest_service, pipeline_service
from utils.logging_setup import get_logger

logger = get_logger()


class DateiHashWorker(QThread):
    """Berechnet den SHA-256 einer Quelldatei im Hintergrund.

    Der Hash bestimmt den Arbeitsordner und damit, ob es zu einer Datei
    schon einen Zwischenstand gibt. Er wurde bisher direkt im
    Oberflaechen-Faden berechnet -- bei den mehrstuendigen Aufnahmen, fuer
    die diese Anwendung gedacht ist, stand das Fenster dabei jedes Mal
    mehrere Sekunden still, sobald jemand eine Datei anklickte.
    """

    fertig = Signal(str, str)  # (Dateipfad, Hash)
    fehlgeschlagen = Signal(str, str)  # (Dateipfad, Fehlertext)

    def __init__(self, pfad: Path, parent=None):
        super().__init__(parent)
        self._pfad = pfad

    def run(self) -> None:
        try:
            hashwert = manifest_service.compute_file_hash(self._pfad)
        except OSError as fehler:
            self.fehlgeschlagen.emit(str(self._pfad), str(fehler))
            return
        self.fertig.emit(str(self._pfad), hashwert)


class PipelineWorker(QThread):
    stage_changed = Signal(str, str)
    chunk_progress = Signal(int, int)
    overall_progress = Signal(float)
    preview_updated = Signal(str)
    log_message = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: pipeline_service.PipelineSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        callbacks = pipeline_service.PipelineCallbacks(
            on_stage=lambda key, detail: self.stage_changed.emit(key, detail),
            on_chunk_progress=lambda current, total: self.chunk_progress.emit(current, total),
            on_overall_progress=lambda fraction: self.overall_progress.emit(fraction),
            on_preview=lambda text: self.preview_updated.emit(text),
            on_log=lambda message: self.log_message.emit(message),
            should_cancel=self._should_cancel,
        )
        try:
            result = pipeline_service.run_pipeline(self._settings, callbacks)
            self.finished_ok.emit(result)
        except pipeline_service.PipelineCancelled:
            self.cancelled.emit()
        except pipeline_service.PipelineError as error:
            logger.error("Verarbeitung fehlgeschlagen: %s", error)
            self.failed.emit(str(error))
        except Exception as error:  # unerwarteter Fehler -- keine Tracebacks in der GUI
            logger.exception("Unerwarteter Fehler in der Verarbeitung")
            self.failed.emit(
                "Unerwarteter Fehler. Details wurden in der Logdatei gespeichert. "
                f"Kurzbeschreibung: {error}"
            )
