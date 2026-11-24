"""Regressionstest: Geraet und PC starten gleichzeitig -- es darf nie zwei Verarbeitungen parallel geben.

So ist es passiert: Eine Aufnahme von einem Waveshare-Geraet wurde gerade
transkribiert, am PC wurde eine zweite Transkription gestartet, beide liefen
gleichzeitig, und der Grafikspeicher lief mit einem Fehler voll. Seit der
Ablaufsteuerung gibt es genau einen Arbeitsfaden fuer alle Auftraege.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from protokoll_assistent.ablauf.auftraege import Status
from protokoll_assistent.ablauf.geraete_automatik import Abhaengigkeiten, GeraeteAutomatik
from protokoll_assistent.ablauf.verarbeitungswege import TranskriptionsWunsch
from protokoll_assistent.services import pipeline_service
from protokoll_assistent.tests.ablauf_hilfen import FalschePipeline, steuerung_fuer_test


class ZaehlendePipeline(FalschePipeline):
    """Wie die falsche Pipeline, merkt sich aber, wie viele Laeufe gleichzeitig rechnen."""

    def __init__(self) -> None:
        super().__init__()
        self._sperre = threading.Lock()
        self.gleichzeitig = 0
        self.hoechstens = 0
        self.reihenfolge: list[str] = []
        self.erster_laeuft = threading.Event()
        self.weiter = threading.Event()

    def _rechnen(self, name: str) -> None:
        with self._sperre:
            self.gleichzeitig += 1
            self.hoechstens = max(self.hoechstens, self.gleichzeitig)
            self.reihenfolge.append(name)
        self.erster_laeuft.set()
        self.weiter.wait(5)
        time.sleep(0.02)
        with self._sperre:
            self.gleichzeitig -= 1

    def run_transcription(self, settings: pipeline_service.PipelineSettings, *args: Any, **kwargs: Any) -> Any:
        self._rechnen(settings.source_path.name)
        return super().run_transcription(settings, *args, **kwargs)

    def run_protocol(self, settings: pipeline_service.ProtocolSettings, *args: Any, **kwargs: Any) -> Any:
        self._rechnen(f"auswertung:{settings.transcript_json_path.name}")
        return super().run_protocol(settings, *args, **kwargs)


def test_geraet_und_pc_gleichzeitig_laufen_nacheinander(tmp_path: Path) -> None:
    pipeline = ZaehlendePipeline()
    konfig: dict[str, Any] = {"ausgabeordner": str(tmp_path / "aus"), "geraete_live_auswertung_vorab": False}
    steuerung, _ = steuerung_fuer_test(konfig, pipeline)
    automatik = GeraeteAutomatik(
        steuerung,
        Abhaengigkeiten(
            nebenher_moeglich=lambda c: True,
            transkribierer_fabrik=lambda m, s, d: lambda: lambda wav: [],
            arbeitsordner=lambda: tmp_path / "arbeit",
            standard_ziel=lambda: tmp_path / "ein",
        ),
    )
    geraete_datei = tmp_path / "ein" / "Raum-1_H5_001.opus"
    pc_datei = tmp_path / "pc" / "besprechung.wav"
    for datei in (geraete_datei, pc_datei):
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(b"audio")

    steuerung.starten()
    try:
        # 1. Das Geraet liefert eine Aufnahme -- sie beginnt sofort.
        automatik.aufnahme_bereit(geraete_datei, "Raum-1", "H5_001.opus")
        assert pipeline.erster_laeuft.wait(5)
        # 2. Waehrenddessen startet jemand am PC eine Transkription mit anschliessender Zusammenfassung.
        pc = steuerung.transkription_starten(TranskriptionsWunsch(pc_datei, tmp_path / "aus", mit_auswertung=True))
        assert pc.status is Status.WARTET
        assert steuerung.auftraege.platz(pc.id) == 1  # wartet hinter der laufenden Geraeteaufnahme
        pipeline.weiter.set()
        assert steuerung.auftraege.warten_bis_leer(10)
    finally:
        steuerung.beenden()
        automatik.stoppen()

    assert pipeline.hoechstens == 1, "Zwei Verarbeitungen liefen gleichzeitig"
    # Die Zusammenfassung der Geraeteaufnahme hat Vorrang vor dem wartenden PC-Auftrag.
    assert pipeline.reihenfolge[0] == "Raum-1_H5_001.opus"
    assert pipeline.reihenfolge[1].startswith("auswertung:Raum-1_H5_001")
    assert pipeline.reihenfolge[2] == "besprechung.wav"
    assert pipeline.reihenfolge[3].startswith("auswertung:besprechung")
    assert all(a.status is Status.FERTIG for a in steuerung.auftraege.liste())


def test_platz_in_der_warteschlange(tmp_path: Path) -> None:
    steuerung, _ = steuerung_fuer_test({})
    erster = steuerung.auftraege.einreihen("t", "a", lambda f: {})
    zweiter = steuerung.auftraege.einreihen("t", "b", lambda f: {}, vorrang=5)
    assert steuerung.auftraege.platz(zweiter.id) == 0  # nichts laeuft, hoeherer Vorrang
    assert steuerung.auftraege.platz(erster.id) == 1
    steuerung.auftraege.ausfuehren_im_aufrufer()
    assert steuerung.auftraege.platz(zweiter.id) is None
    assert steuerung.auftraege.platz("gibtsnicht") is None
