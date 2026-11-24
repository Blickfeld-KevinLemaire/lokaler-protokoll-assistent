"""Gemeinsame Vorbereitungen fuer die Tests (Dienste, Ablauf, Programmschnittstelle, Servermodus).

Die Tests brauchen weder Bildschirm noch Netz noch Grafikkarte (CLAUDE.md, Regel 4).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _keine_echten_tokens(monkeypatch):
    """Kein Test darf versehentlich einen echten Hugging-Face-Token benutzen --
    weder aus der Umgebung noch aus der .env im Projektordner noch aus der
    Windows-Anmeldeinformationsverwaltung."""
    from protokoll_assistent.utils import hf_env

    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hf_env, "_env_datei", lambda: Path(__file__).parent / "gibt-es-nicht.env")
    monkeypatch.setattr(hf_env, "_token_aus_anmeldeinfos", lambda: "")


@pytest.fixture(autouse=True)
def _kein_echter_ollama_start(monkeypatch):
    """Kein Test darf einen echten Ollama-Dienst starten (``ollama_service.dienst_starten``): Auf einem Entwicklerrechner
    mit Ollama wuerde sonst ein Prozess zurueckbleiben."""
    from protokoll_assistent.services import ollama_service

    monkeypatch.setattr(ollama_service, "AUTO_START", False)


@pytest.fixture(autouse=True)
def _keine_echte_grafikkarte_fuer_ollama(monkeypatch):
    """Ob Ollama Prozessorgrafik freigeschaltet bekommt, haengt an der echten Grafikkarte (Registry). Auf einem
    solchen Entwicklerrechner schriebe ein Test sonst OLLAMA_IGPU_ENABLE in dessen Benutzerkonto."""
    from protokoll_assistent.services import ollama_service, rechner_analyse_service

    monkeypatch.setattr(rechner_analyse_service, "grafikkarten_aus_registry", lambda winreg_modul=None: [])
    monkeypatch.delenv(ollama_service.IGPU_VARIABLE, raising=False)
    monkeypatch.delenv(ollama_service.VULKAN_VARIABLE, raising=False)


@pytest.fixture(autouse=True)
def _keine_echte_amd_karte_fuer_die_rechenumgebung(monkeypatch):
    """Auf einem Rechner mit passender AMD-Karte richtete 'bootstrap' sonst die ROCm-Umgebung ein -- und laedt
    dafuer das CTranslate2-Archiv von GitHub (so beim ersten Lauf auf einer RX 9070 XT passiert)."""
    from protokoll_assistent.services import rocm_laufzeit_service

    monkeypatch.setattr(rocm_laufzeit_service, "amd_karte_erkannt", lambda karten_fn=None: False)


@pytest.fixture(autouse=True)
def _empfang_nur_auf_loopback(monkeypatch):
    """Der Empfang fuer die Aufnahmegeraete darf in Tests nur auf 127.0.0.1
    lauschen. Bindet ein Test versehentlich an alle Schnittstellen (so ist es
    beim Bau der Fenstertests einmal passiert), schlaegt er hier fehl -- statt
    einen offenen Port und unter Windows eine Firewall-Abfrage zu hinterlassen."""
    from protokoll_assistent.services import geraete_empfang_service

    original = geraete_empfang_service._Server.__init__

    def nur_loopback(self, adresse, empfang):
        assert adresse[0] == "127.0.0.1", f"Test bindet den Empfang an {adresse[0]} statt an 127.0.0.1"
        original(self, adresse, empfang)

    monkeypatch.setattr(geraete_empfang_service._Server, "__init__", nur_loopback)
