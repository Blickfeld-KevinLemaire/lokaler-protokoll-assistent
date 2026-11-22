"""Aus Konfiguration und Wunsch wird ein Pipeline-Lauf -- oder ein verstaendlicher Ablauffehler."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.ablauf import verarbeitungswege as wege
from protokoll_assistent.ablauf.verarbeitungswege import (
    Ablauffehler,
    AuswertungsWunsch,
    Schluesselablage,
    TranskriptionsWunsch,
)
from protokoll_assistent.services import api_protocol_service, model_service, ollama_service, secret_store
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben


@pytest.fixture(autouse=True)
def kein_schluesselspeicher(monkeypatch: pytest.MonkeyPatch) -> None:
    def fehlt(_name: str) -> str | None:
        raise secret_store.SecretStoreUnavailableError("kein keyring")

    monkeypatch.setattr(secret_store, "load_api_key", fehlt)


def _audio(tmp_path: Path, inhalt: bytes = b"RIFF") -> Path:
    datei = tmp_path / "besprechung.wav"
    datei.write_bytes(inhalt)
    return datei


API_KONFIG: dict[str, Any] = {
    "transkription_modus": "api",
    "api_transkription_endpunkt": "https://api.example.com/v1/audio/transcriptions",
    "api_transkription_modell": "whisper-1",
    "api_transkription_anbieter": "OpenAI",
    "nachbearbeitung_modus": "api",
    "api_nachbearbeitung_endpunkt": "https://api.example.com/v1/chat/completions",
    "api_nachbearbeitung_modell": "gpt",
}


def test_lokal_ohne_laufzeit(tmp_path: Path) -> None:
    wunsch = TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus")
    with pytest.raises(Ablauffehler) as info:
        wege.transkription_vorbereiten(wunsch, {}, Schluesselablage({}), laufzeit_verfuegbar=lambda: False)
    assert info.value.code == wege.CODE_LOKALE_EINRICHTUNG
    assert info.value.als_dict()["titel"] == "Noch nicht bereit" and info.value.bereich == "transkription"


def test_lokal_mit_laufzeit(tmp_path: Path) -> None:
    wunsch = TranskriptionsWunsch(
        _audio(tmp_path), tmp_path / "aus", min_sprecher=2, max_sprecher=3, fortsetzen=False, offline=True,
        vorab_live={"bestaetigt_bis": 3},
    )
    lauf = wege.transkription_vorbereiten(wunsch, {"whisper_modell": "small"}, Schluesselablage({}), laufzeit_verfuegbar=lambda: True)
    assert lauf.modus == "lokal" and lauf.transcribe_fn is None
    e = lauf.einstellungen
    assert (e.whisper_model, e.resume_mode, e.allow_download, e.min_speakers, e.max_speakers) == (
        "small", "neu_beginnen", False, 2, 3,
    )
    assert e.vorab_live is None  # bei "neu beginnen" nicht
    assert not e.run_protocol


def test_eingabefehler(tmp_path: Path) -> None:
    schluessel = Schluesselablage({})
    with pytest.raises(Ablauffehler, match="nicht gefunden"):
        wege.transkription_vorbereiten(TranskriptionsWunsch(tmp_path / "fehlt.wav", tmp_path), {}, schluessel)
    with pytest.raises(Ablauffehler, match="keine Daten"):
        wege.transkription_vorbereiten(TranskriptionsWunsch(_audio(tmp_path, b""), tmp_path), {}, schluessel)
    datei_statt_ordner = tmp_path / "datei"
    datei_statt_ordner.write_text("x", encoding="utf-8")
    with pytest.raises(Ablauffehler, match="Ausgabeordner"):
        wege.transkription_vorbereiten(TranskriptionsWunsch(_audio(tmp_path), datei_statt_ordner), {}, schluessel)


def test_api_ohne_anbieter_und_ohne_schluessel(tmp_path: Path) -> None:
    wunsch = TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus")
    with pytest.raises(Ablauffehler) as info:
        wege.transkription_vorbereiten(wunsch, {"transkription_modus": "api"}, Schluesselablage({}))
    assert info.value.code == wege.CODE_EINSTELLUNGEN
    with pytest.raises(Ablauffehler) as info:
        wege.transkription_vorbereiten(wunsch, API_KONFIG, Schluesselablage({}))
    assert info.value.code == wege.CODE_SCHLUESSEL


def test_api_mit_schluessel_aus_umgebung(tmp_path: Path) -> None:
    wunsch = TranskriptionsWunsch(_audio(tmp_path), tmp_path / "aus", vorab_live={"x": 1})
    schluessel = Schluesselablage({"VERMERK_API_SCHLUESSEL_TRANSKRIPTION": "geheim"})
    lauf = wege.transkription_vorbereiten(wunsch, API_KONFIG, schluessel)
    assert lauf.modus == "api"
    assert lauf.transcribe_fn is not None and lauf.diarize_fn is not None
    assert lauf.transcribe_fn.keywords["api_key"] == "geheim"  # type: ignore[attr-defined]
    assert lauf.einstellungen.vorab_live is None  # ueber die API nicht


def test_schluesselablage(monkeypatch: pytest.MonkeyPatch) -> None:
    ablage = Schluesselablage({})
    assert not ablage.vorhanden("chatbot")
    ablage.fuer_sitzung("chatbot", "s1")
    assert ablage.hole("chatbot") == "s1"
    ablage.fuer_sitzung("chatbot", "")
    assert ablage.hole("chatbot") is None
    monkeypatch.setattr(secret_store, "load_api_key", lambda name: "gemerkt")
    assert ablage.hole("chatbot") == "gemerkt"
    assert ablage.name_fuer_chat({"chatbot_api_eigener_schluessel": True}) == "chatbot"
    assert ablage.name_fuer_chat({"api_nachbearbeitung_eigener_schluessel": True}) == "nachbearbeitung"
    assert ablage.name_fuer_chat({}) == "transkription"


def test_whisper_modell() -> None:
    assert wege.ermittle_whisper_modell({}) == model_service.WHISPER_MODEL_NAME
    assert wege.ermittle_whisper_modell({"whisper_modell": "large-v3"}) == "large-v3"


def test_api_auswertung_uebersetzt_fehler(monkeypatch: pytest.MonkeyPatch) -> None:
    def scheitert(*_a: Any, **_k: Any) -> str:
        raise api_protocol_service.ApiProtocolError("HTTP 401")

    monkeypatch.setattr(api_protocol_service, "generate_text", scheitert)
    with pytest.raises(ollama_service.OllamaError, match="401"):
        wege.api_auswertung_funktion("https://x", "m", "k")("p", "s")
    monkeypatch.setattr(api_protocol_service, "generate_text", lambda *a, **k: "Antwort")
    assert wege.api_auswertung_funktion("https://x", "m", "k")("p", "s") == "Antwort"


def test_auswertung_lokal_und_modell_fehlt(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / "a_lokal_transkript_1.json")
    wunsch = AuswertungsWunsch(transkript, tmp_path / "aus", systemprompt="  Bitte kurz.  ", ohne_sprecher=True)
    lauf = wege.auswertung_vorbereiten(wunsch, {"ollama_modell": "qwen"}, Schluesselablage({}), modell_fehlt=lambda m: False)
    assert lauf.modus == "lokal" and lauf.generate_fn is None
    assert lauf.einstellungen.system_prompt == "Bitte kurz."
    assert lauf.einstellungen.ollama_model == "qwen" and lauf.einstellungen.ohne_sprecher
    with pytest.raises(Ablauffehler) as info:
        wege.auswertung_vorbereiten(wunsch, {}, Schluesselablage({}), modell_fehlt=lambda m: True)
    assert info.value.code == wege.CODE_MODELL_FEHLT
    with pytest.raises(Ablauffehler, match="nicht gefunden"):
        wege.auswertung_vorbereiten(AuswertungsWunsch(tmp_path / "nein.json", tmp_path), {}, Schluesselablage({}))


def test_auswertung_api(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / "a_lokal_transkript_1.json")
    wunsch = AuswertungsWunsch(transkript, tmp_path / "aus")
    with pytest.raises(Ablauffehler) as info:
        wege.auswertung_vorbereiten(wunsch, {"nachbearbeitung_modus": "api"}, Schluesselablage({}))
    assert info.value.code == wege.CODE_EINSTELLUNGEN
    with pytest.raises(Ablauffehler) as info:
        wege.auswertung_vorbereiten(wunsch, API_KONFIG, Schluesselablage({}))
    assert info.value.code == wege.CODE_SCHLUESSEL
    lauf = wege.auswertung_vorbereiten(wunsch, API_KONFIG, Schluesselablage({"VERMERK_API_SCHLUESSEL_TRANSKRIPTION": "k"}))
    assert lauf.modus == "api" and lauf.generate_fn is not None
    assert lauf.einstellungen.protokoll_modell_kennung == f"api:{API_KONFIG['api_nachbearbeitung_endpunkt']}|gpt"
    assert lauf.einstellungen.system_prompt is None


def test_lokale_laufzeit_verfuegbar_ist_bool() -> None:
    assert isinstance(wege.lokale_laufzeit_verfuegbar(), bool)
