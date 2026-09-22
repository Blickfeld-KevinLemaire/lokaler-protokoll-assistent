"""Hintergrundverarbeitung ueber QThread, damit die Oberflaeche waehrend
der Transkription/Nachbearbeitung nicht einfriert.

Die Worker nehmen optionale
'transcribe_chunk_fn'/'diarize_fn'/'protocol_generate_fn' entgegen und
reichen sie unveraendert an 'services.pipeline_service' durch. Damit laesst
sich dieselbe Ablaufsteuerung (Chunk-Planung, Fortsetzbarkeit,
Zusammenfuehrung, Export) sowohl mit den lokalen ML-Aufrufen (Parameter
bleiben 'None', pipeline_service verwendet dann seine eigenen Standard-
implementierungen) als auch mit den API-Funktionen aus
'services/api_transcription_service.py'/'api_protocol_service.py'
verwenden - siehe 'gui/main_window.py' fuer die Auswahl je nach
Einstellung."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from protokoll_assistent.services import pipeline_service
from protokoll_assistent.utils.logging_setup import get_logger

logger = get_logger()

TranscribeChunkFn = Callable[[Path], list[dict[str, Any]]]
DiarizeFn = Callable[[Path, int | None, int | None], list[dict[str, Any]]]
ProtocolGenerateFn = Callable[[str, str], dict[str, Any]]


class TranscriptionWorker(QThread):
    """Eigenstaendiger erster Schritt: nur Transkription
    (``pipeline_service.run_transcription``), ohne Protokollauswertung."""

    stage_changed = Signal(str, str)
    chunk_progress = Signal(int, int)
    overall_progress = Signal(float)
    preview_updated = Signal(str)
    log_message = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        settings: pipeline_service.PipelineSettings,
        parent=None,
        transcribe_chunk_fn: TranscribeChunkFn | None = None,
        diarize_fn: DiarizeFn | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._transcribe_chunk_fn = transcribe_chunk_fn
        self._diarize_fn = diarize_fn
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
            result = pipeline_service.run_transcription(
                self._settings,
                callbacks,
                transcribe_chunk_fn=self._transcribe_chunk_fn,
                diarize_fn=self._diarize_fn,
            )
            self.finished_ok.emit(result)
        except pipeline_service.PipelineCancelled:
            self.cancelled.emit()
        except pipeline_service.PipelineError as error:
            logger.error("Transkription fehlgeschlagen: %s", error)
            self.failed.emit(str(error))
        except Exception as error:  # unerwarteter Fehler -- keine Tracebacks in der GUI
            logger.exception("Unerwarteter Fehler in der Transkription")
            self.failed.emit(
                "Unerwarteter Fehler. Details wurden in der Logdatei gespeichert. "
                f"Kurzbeschreibung: {error}"
            )


class ProtocolWorker(QThread):
    """Eigenstaendiger zweiter Schritt: Protokollauswertung eines bereits
    vorliegenden Transkripts (``pipeline_service.run_protocol``)."""

    stage_changed = Signal(str, str)
    overall_progress = Signal(float)
    log_message = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        settings: pipeline_service.ProtocolSettings,
        parent=None,
        protocol_generate_fn: ProtocolGenerateFn | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._protocol_generate_fn = protocol_generate_fn
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        callbacks = pipeline_service.PipelineCallbacks(
            on_stage=lambda key, detail: self.stage_changed.emit(key, detail),
            on_overall_progress=lambda fraction: self.overall_progress.emit(fraction),
            on_log=lambda message: self.log_message.emit(message),
            should_cancel=self._should_cancel,
        )
        try:
            result = pipeline_service.run_protocol(
                self._settings, callbacks, protocol_generate_fn=self._protocol_generate_fn
            )
            self.finished_ok.emit(result)
        except pipeline_service.PipelineCancelled:
            self.cancelled.emit()
        except pipeline_service.PipelineError as error:
            logger.error("Nachbearbeitung fehlgeschlagen: %s", error)
            self.failed.emit(str(error))
        except Exception as error:  # unerwarteter Fehler -- keine Tracebacks in der GUI
            logger.exception("Unerwarteter Fehler in der Nachbearbeitung")
            self.failed.emit(
                "Unerwarteter Fehler. Details wurden in der Logdatei gespeichert. "
                f"Kurzbeschreibung: {error}"
            )


class DateiHashWorker(QThread):
    """Berechnet den SHA-256 einer Quelldatei im Hintergrund (siehe
    der Hash
    bestimmt den Arbeitsordner, und die Berechnung kostet bei
    mehrstuendigen Aufnahmen Sekunden)."""

    fertig = Signal(str, str)
    fehlgeschlagen = Signal(str, str)

    def __init__(self, pfad: Path, parent=None):
        super().__init__(parent)
        self._pfad = pfad

    def run(self) -> None:
        from protokoll_assistent.services import manifest_service

        try:
            hashwert = manifest_service.compute_file_hash(self._pfad)
        except OSError as fehler:
            self.fehlgeschlagen.emit(str(self._pfad), str(fehler))
            return
        self.fertig.emit(str(self._pfad), hashwert)
