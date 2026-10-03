"""Tests fuer ``services/api_anbieter.py`` -- reine Daten, kein Netz."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from protokoll_assistent.services import api_anbieter as aa


def test_jeder_anbieter_ist_vollstaendig_beschrieben():
    kennungen = [a.id for a in aa.ANBIETER]
    assert len(kennungen) == len(set(kennungen))
    for anbieter in aa.ANBIETER:
        assert anbieter.name and anbieter.standort and anbieter.kann_chat
        # Adressen: https, ohne abschliessenden Schraegstrich (daran haengt der Pfad)
        assert anbieter.basis_url.startswith("https://") and not anbieter.basis_url.endswith("/")
        for link in (anbieter.schluessel_link, anbieter.doku_link):
            gesplittet = urlparse(link)
            assert gesplittet.scheme == "https" and gesplittet.netloc


def test_die_gewuenschten_anbieter_sind_dabei():
    kennungen = {a.id for a in aa.ANBIETER}
    assert {"openrouter", "ionos", "openai", "anthropic", "mistral", "azure"} <= kennungen


def test_adressen_folgen_der_openai_schnittstelle():
    openai = aa.finde_anbieter("openai")
    assert openai is not None
    assert openai.chat_url() == "https://api.openai.com/v1/chat/completions"
    assert openai.embedding_url() == "https://api.openai.com/v1/embeddings"
    assert openai.transkription_url() == "https://api.openai.com/v1/audio/transcriptions"


@pytest.mark.parametrize(
    ("kennung", "chat", "embeddings", "transkription"),
    [
        ("openrouter", True, True, True),
        ("ionos", True, True, False),
        ("openai", True, True, True),
        ("anthropic", True, False, False),
        ("mistral", True, True, True),
        ("azure", True, True, True),
        ("google", True, True, False),
        ("groq", True, False, True),
    ],
)
def test_faehigkeiten(kennung, chat, embeddings, transkription):
    anbieter = aa.finde_anbieter(kennung)
    assert anbieter is not None
    assert (anbieter.kann_chat, anbieter.kann_embeddings, anbieter.kann_transkription) == (
        chat,
        embeddings,
        transkription,
    )


def test_nur_openrouter_nutzt_json_mit_base64_audio():
    for anbieter in aa.ANBIETER:
        erwartet = aa.FORMAT_JSON_BASE64 if anbieter.id == "openrouter" else aa.FORMAT_MULTIPART
        assert anbieter.transkription_format == erwartet


def test_azure_hat_einen_platzhalter_der_ersetzt_werden_muss():
    azure = aa.finde_anbieter("azure")
    assert azure is not None and azure.hat_platzhalter
    assert not aa.adresse_vollstaendig(azure.chat_url())
    assert aa.adresse_vollstaendig(azure.chat_url().replace(aa.PLATZHALTER_RESSOURCE, "meine-firma"))
    assert not aa.finde_anbieter("openai").hat_platzhalter  # type: ignore[union-attr]


@pytest.mark.parametrize("adresse", [None, "", "   "])
def test_leere_adressen_sind_unvollstaendig(adresse):
    assert not aa.adresse_vollstaendig(adresse)


def test_anbieter_wird_an_der_adresse_erkannt():
    assert aa.erkenne_anbieter("https://openrouter.ai/api/v1/audio/transcriptions").id == "openrouter"  # type: ignore[union-attr]
    assert aa.erkenne_anbieter("https://api.mistral.ai/v1/chat/completions/").id == "mistral"  # type: ignore[union-attr]
    assert aa.erkenne_anbieter("HTTPS://API.OPENAI.COM/v1").id == "openai"  # type: ignore[union-attr]
    # Azure: Ressourcenname ist vom Anwender eingesetzt
    assert aa.erkenne_anbieter("https://meine-firma.openai.azure.com/openai/v1/chat/completions").id == "azure"  # type: ignore[union-attr]
    assert aa.erkenne_anbieter("https://mein-anbieter.test/v1") is None
    assert aa.erkenne_anbieter("") is None and aa.erkenne_anbieter(None) is None
    # Aehnlicher Name, aber anderer Host: kein Treffer
    assert aa.erkenne_anbieter("https://api.openai.com.evil.test/v1") is None


def test_finde_anbieter():
    assert aa.finde_anbieter("ionos").name.startswith("IONOS")  # type: ignore[union-attr]
    assert aa.finde_anbieter("") is None and aa.finde_anbieter(None) is None
    assert aa.finde_anbieter(aa.ANBIETER_EIGENER) is None


def test_format_und_diarisierung_aus_der_adresse():
    assert aa.transkription_format_fuer("https://api.openai.com/v1/audio/transcriptions") == aa.FORMAT_MULTIPART
    assert aa.transkription_format_fuer("https://openrouter.ai/api/v1/audio/transcriptions") == aa.FORMAT_JSON_BASE64
    # Eigene/unbekannte Adressen: wie bisher JSON mit Base64-Audio
    assert aa.transkription_format_fuer("https://mein-anbieter.test/x") == aa.FORMAT_JSON_BASE64
    assert aa.transkription_format_fuer(None) == aa.FORMAT_JSON_BASE64
    assert aa.diarisierung_fuer("https://api.mistral.ai/v1/audio/transcriptions") == aa.DIARISIERUNG_MISTRAL
    assert aa.diarisierung_fuer("https://api.openai.com/v1/audio/transcriptions") == aa.DIARISIERUNG_MODELL
    assert aa.diarisierung_fuer("https://api.groq.com/openai/v1/audio/transcriptions") == aa.DIARISIERUNG_KEINE
    assert aa.diarisierung_fuer("https://mein-anbieter.test/x") == aa.DIARISIERUNG_OPENROUTER
