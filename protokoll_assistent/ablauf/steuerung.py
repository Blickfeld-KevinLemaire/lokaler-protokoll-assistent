"""Die Ablaufsteuerung: ein Objekt, das Programmschnittstelle und Servermodus gemeinsam benutzen.

Sie haelt den Ereignisbus, die eine Auftragswarteschlange und die
Schluesselablage und startet Transkriptionen und Auswertungen als Auftraege.
Was nach einem Auftrag folgt (Auswertung im Anschluss, Meldung an ein
Aufnahmegeraet), haengt als ``nach_ende`` am Auftrag -- nicht an einem Fenster.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf import auftraege as auftraege_modul
from protokoll_assistent.ablauf.auftraege import Auftrag, Auftragsverwaltung, Fortschritt, Nachfolger, Status
from protokoll_assistent.ablauf.ereignisse import Ereignisbus
from protokoll_assistent.ablauf.verarbeitungswege import (
    Ablauffehler,
    AuswertungsWunsch,
    Schluesselablage,
    TranskriptionsWunsch,
    auswertung_vorbereiten,
    lokale_laufzeit_verfuegbar,
    transkription_vorbereiten,
)
from protokoll_assistent.services import ollama_service, pipeline_service
from protokoll_assistent.utils import app_config
from protokoll_assistent.utils.paths import get_default_output_dir, get_recordings_dir

ART_TRANSKRIPTION = "transkription"
ART_AUSWERTUNG = "auswertung"
NUTZER_ORDNER = "nutzer"

TranskriptionsFn = Callable[..., pipeline_service.TranscriptionResult]
ProtokollFn = Callable[..., pipeline_service.ProtocolResult]


@dataclass
class Abhaengigkeiten:
    """Was sich in Tests ersetzen laesst: Konfiguration, Pipeline, Pruefungen."""

    konfiguration_laden: Callable[[], dict[str, Any]] = app_config.load_config
    run_transcription: TranskriptionsFn = pipeline_service.run_transcription
    run_protocol: ProtokollFn = pipeline_service.run_protocol
    laufzeit_verfuegbar: Callable[[], bool] = lokale_laufzeit_verfuegbar
    modell_fehlt: Callable[[str], bool] = ollama_service.modell_fehlt


def transkriptions_ergebnis(ergebnis: pipeline_service.TranscriptionResult) -> dict[str, Any]:
    pfade = ergebnis.export_paths
    return {
        "transkript_json": str(pfade.json),
        "transkript_txt": str(pfade.txt),
        "untertitel_srt": str(pfade.srt),
        "untertitel_vtt": str(pfade.vtt),
        "arbeitsordner": str(ergebnis.work_dir),
        "sprecher": dict(ergebnis.speaker_names),
        "dauer_sekunden": ergebnis.total_duration,
        "diarisierung_fehler": ergebnis.diarisierung_fehler,
    }


def auswertungs_ergebnis(ergebnis: pipeline_service.ProtocolResult) -> dict[str, Any]:
    pfade = ergebnis.protocol_paths
    return {
        "protokoll_json": str(pfade[0]) if pfade else None,
        "protokoll_md": str(pfade[1]) if pfade else None,
        "arbeitsordner": str(ergebnis.work_dir),
        "protokoll_fehler": ergebnis.protokoll_fehler,
    }


class Steuerung:
    def __init__(
        self,
        *,
        bus: Ereignisbus | None = None,
        schluessel: Schluesselablage | None = None,
        abhaengigkeiten: Abhaengigkeiten | None = None,
    ):
        self.bus = bus or Ereignisbus()
        self.schluessel = schluessel or Schluesselablage()
        self.abh = abhaengigkeiten or Abhaengigkeiten()
        self.auftraege = Auftragsverwaltung(self.bus)
        # Servermodus mit mehreren Nutzern: Jeder hat einen eigenen Unterordner (``nutzer/<name>``) fuer
        # Aufnahmen und Ergebnisse. In der Windows-Anwendung bleibt alles, wie es war.
        self.mehrbenutzer = False

    # ------------------------------------------------------------------
    def starten(self) -> None:
        self.auftraege.starten()

    def beenden(self) -> None:
        self.auftraege.beenden()

    def konfiguration(self) -> dict[str, Any]:
        return self.abh.konfiguration_laden()

    def ausgabe_basis(self) -> Path:
        gespeichert = self.konfiguration().get("ausgabeordner")
        return Path(gespeichert) if gespeichert else get_default_output_dir()

    def ausgabeordner(self, besitzer: str | None = None) -> Path:
        """Wohin die Ergebnisse kommen. Mit Besitzer (Servermodus) in dessen eigenen Ordner."""
        basis = self.ausgabe_basis()
        return basis / NUTZER_ORDNER / besitzer if self.mehrbenutzer and besitzer else basis

    def aufnahmeordner(self, besitzer: str | None = None) -> Path:
        basis = get_recordings_dir()
        return basis / NUTZER_ORDNER / besitzer if self.mehrbenutzer and besitzer else basis

    def hinweis(self, text: str, *, stufe: str = "info", quelle: str = "") -> None:
        """Eine Meldung fuer die Oberflaeche, die zu keinem Auftrag gehoert."""
        self.bus.senden("hinweis", {"text": text, "stufe": stufe, "quelle": quelle})

    # ------------------------------------------------------------------
    # Transkription
    # ------------------------------------------------------------------
    def transkription_starten(
        self,
        wunsch: TranskriptionsWunsch,
        *,
        systemprompt: str | None = None,
        herkunft: str = "oberflaeche",
        vorrang: int = auftraege_modul.VORRANG_NORMAL,
        nach_ende: Nachfolger | None = None,
        fortschritt_spiegeln: Callable[[str, float | None, str], None] | None = None,
        besitzer: str | None = None,
    ) -> Auftrag:
        """Prueft sofort (``Ablauffehler``) und reiht dann ein. ``mit_auswertung`` im Wunsch schliesst nach
        einer erfolgreichen Transkription die Auswertung als eigenen Auftrag an."""
        lauf = transkription_vorbereiten(
            wunsch, self.konfiguration(), self.schluessel, laufzeit_verfuegbar=self.abh.laufzeit_verfuegbar
        )

        def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
            callbacks = fortschritt.callbacks()
            if fortschritt_spiegeln is not None:
                callbacks = _gespiegelt(callbacks, fortschritt_spiegeln)
            ergebnis = self.abh.run_transcription(lauf.einstellungen, callbacks, lauf.transcribe_fn, lauf.diarize_fn)
            return transkriptions_ergebnis(ergebnis)

        def danach(auftrag: Auftrag) -> None:
            if wunsch.mit_auswertung and auftrag.status is Status.FERTIG and auftrag.ergebnis:
                try:
                    self.auswertung_starten(
                        AuswertungsWunsch(
                            transkript=Path(auftrag.ergebnis["transkript_json"]),
                            ausgabe=wunsch.ausgabe,
                            systemprompt=systemprompt,
                        ),
                        herkunft=herkunft,
                        vorrang=vorrang,
                        besitzer=besitzer,
                    )
                except Ablauffehler as fehler:
                    self.hinweis(f"{fehler.titel}: {fehler.text}", stufe="fehler")
            if nach_ende is not None:
                nach_ende(auftrag)

        return self.auftraege.einreihen(
            ART_TRANSKRIPTION,
            wunsch.quelle.name,
            ausfuehren,
            herkunft=herkunft,
            vorrang=vorrang,
            angaben={"quelle": str(wunsch.quelle), "modus": lauf.modus, "mit_auswertung": wunsch.mit_auswertung},
            nach_ende=danach,
            besitzer=besitzer,
        )

    # ------------------------------------------------------------------
    # Auswertung
    # ------------------------------------------------------------------
    def auswertung_starten(
        self,
        wunsch: AuswertungsWunsch,
        *,
        herkunft: str = "oberflaeche",
        vorrang: int = auftraege_modul.VORRANG_NORMAL,
        nach_ende: Nachfolger | None = None,
        fortschritt_spiegeln: Callable[[str, float | None, str], None] | None = None,
        besitzer: str | None = None,
    ) -> Auftrag:
        lauf = auswertung_vorbereiten(wunsch, self.konfiguration(), self.schluessel, modell_fehlt=self.abh.modell_fehlt)

        def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
            callbacks = fortschritt.callbacks()
            if fortschritt_spiegeln is not None:
                callbacks = _gespiegelt(callbacks, fortschritt_spiegeln)
            ergebnis = self.abh.run_protocol(lauf.einstellungen, callbacks, lauf.generate_fn)
            return auswertungs_ergebnis(ergebnis)

        return self.auftraege.einreihen(
            ART_AUSWERTUNG,
            wunsch.transkript.name,
            ausfuehren,
            herkunft=herkunft,
            vorrang=vorrang,
            angaben={"transkript": str(wunsch.transkript), "modus": lauf.modus},
            nach_ende=nach_ende,
            besitzer=besitzer,
        )

    def abbrechen(self, auftrag_id: str) -> bool:
        return self.auftraege.abbrechen(auftrag_id)


def _gespiegelt(
    callbacks: pipeline_service.PipelineCallbacks, spiegeln: Callable[[str, float | None, str], None]
) -> pipeline_service.PipelineCallbacks:
    """Fortschritt zusaetzlich an jemanden weitergeben (z. B. den Status fuer ein Aufnahmegeraet)."""
    stand = {"stufe": "", "text": ""}

    def stufe(schluessel: str, text: str) -> None:
        stand["stufe"], stand["text"] = schluessel, text
        callbacks.on_stage(schluessel, text)
        spiegeln(schluessel, None, text)

    def gesamt(anteil: float) -> None:
        callbacks.on_overall_progress(anteil)
        spiegeln(stand["stufe"], anteil, stand["text"])

    return pipeline_service.PipelineCallbacks(
        on_stage=stufe,
        on_chunk_progress=callbacks.on_chunk_progress,
        on_overall_progress=gesamt,
        on_preview=callbacks.on_preview,
        on_log=callbacks.on_log,
        should_cancel=callbacks.should_cancel,
    )
