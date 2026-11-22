"""Aufbau einer Test-App der Programmschnittstelle: eigene Konfigurationsdatei, falsche Pipeline, kein Netz."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from protokoll_assistent.ablauf.geraete_automatik import Abhaengigkeiten as GeraeteAbh
from protokoll_assistent.ablauf.geraete_automatik import GeraeteAutomatik
from protokoll_assistent.ablauf.steuerung import Abhaengigkeiten, Steuerung
from protokoll_assistent.ablauf.verarbeitungswege import Schluesselablage
from protokoll_assistent.api import routen_chat, routen_einstellungen
from protokoll_assistent.api.app import app_erstellen
from protokoll_assistent.api.kontext import Dienste
from protokoll_assistent.api.sicherheit import ROLLE_DESKTOP, Zugang, schluessel_hash, zugaenge_aus_konfiguration
from protokoll_assistent.services import secret_store
from protokoll_assistent.tests.ablauf_hilfen import FalschePipeline
from protokoll_assistent.utils import app_config, paths

SCHLUESSEL = "test-schluessel-0123456789"
ZUGANG = "zugang-fuer-den-browser"


class FalscherEmpfang:
    def __init__(self, *args: Any, **kwargs: Any):
        self.args = args

    def starten(self) -> None:
        pass

    def stoppen(self) -> None:
        pass

    def kontakte(self) -> dict[str, Any]:
        return {}


@dataclass
class Umgebung:
    client: TestClient
    dienste: Dienste
    pipeline: FalschePipeline
    tmp: Path

    @property
    def steuerung(self) -> Steuerung:
        return self.dienste.steuerung

    def auftraege_ausfuehren(self) -> None:
        while self.steuerung.auftraege.ausfuehren_im_aufrufer():
            pass

    def audio(self, name: str = "besprechung.wav") -> Path:
        datei = self.tmp / "aufnahmen" / name
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(b"RIFF....")
        return datei


def eigene_konfiguration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **werte: Any) -> None:
    """Rule 5: nie in die echte konfiguration.json -- alle Pfade in den Testordner."""
    einstellungen = tmp_path / "einstellungen"
    einstellungen.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_config, "get_config_file", lambda: einstellungen / "konfiguration.json")
    monkeypatch.setattr(paths, "get_settings_dir", lambda: einstellungen)
    monkeypatch.setattr(routen_einstellungen, "get_system_prompt_file", lambda: einstellungen / "systemprompt.txt")
    monkeypatch.setattr(routen_chat, "get_chatverlaeufe_dir", lambda: tmp_path / "chats")
    monkeypatch.setattr(routen_chat, "get_work_dir", lambda: tmp_path / "arbeit")

    def kein_speicher(*_a: Any, **_k: Any) -> None:
        raise secret_store.SecretStoreUnavailableError("kein keyring im Test")

    monkeypatch.setattr(secret_store, "load_api_key", kein_speicher)
    monkeypatch.setattr(secret_store, "save_api_key", kein_speicher)
    monkeypatch.setattr(secret_store, "delete_api_key", kein_speicher)
    app_config.save_config({**app_config.DEFAULTS, "ausgabeordner": str(tmp_path / "aus"), **werte})


def app_bauen(tmp_path: Path, *, rolle: str = ROLLE_DESKTOP, oberflaeche: Path | None = None) -> Umgebung:
    pipeline = FalschePipeline()
    steuerung = Steuerung(
        schluessel=Schluesselablage(umgebung={}),
        abhaengigkeiten=Abhaengigkeiten(
            konfiguration_laden=app_config.load_config,
            run_transcription=pipeline.run_transcription,
            run_protocol=pipeline.run_protocol,
            laufzeit_verfuegbar=lambda: True,
            modell_fehlt=lambda modell: False,
        ),
    )
    automatik = GeraeteAutomatik(
        steuerung,
        GeraeteAbh(
            dienst_fabrik=FalscherEmpfang,
            nebenher_moeglich=lambda c: True,
            transkribierer_fabrik=lambda m, s, d: lambda: lambda wav: [],
            arbeitsordner=lambda: tmp_path / "arbeit",
            standard_ziel=lambda: tmp_path / "aufnahmen",
        ),
    )
    zugang = Zugang(
        rolle,
        start_schluessel=SCHLUESSEL if rolle == ROLLE_DESKTOP else None,
        zugaenge=lambda: zugaenge_aus_konfiguration([{"name": "browser", "token_sha256": schluessel_hash(ZUGANG)}]),
    )
    dienste = Dienste(steuerung=steuerung, automatik=automatik, zugang=zugang, hochlade_ordner=lambda: tmp_path / "aufnahmen")
    dienste.nach_einstellungen.append(automatik.anwenden)
    app = app_erstellen(dienste, erlaubte_hosts=["testserver", "127.0.0.1"], oberflaeche=oberflaeche)
    client = TestClient(app)
    if rolle == ROLLE_DESKTOP:
        client.headers["Authorization"] = f"Bearer {SCHLUESSEL}"
    return Umgebung(client, dienste, pipeline, tmp_path)
