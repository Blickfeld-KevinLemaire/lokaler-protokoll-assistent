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
        ("openai", True, True, False),
        ("anthropic", True, False, False),
        ("mistral", True, True, False),
        ("azure", True, True, False),
        ("google", True, True, False),
        ("groq", True, False, False),
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


def test_transkription_gibt_es_nur_bei_openrouter():
    """Das Audio geht nur im API-Aufruf selbst mit (JSON mit Base64, wie bei
    OpenRouter). Anbieter, die einen Dateiupload (multipart) verlangen, sind
    bewusst nicht fuer die Transkription eingetragen."""
    mit_transkription = [a.id for a in aa.ANBIETER if a.kann_transkription]
    assert mit_transkription == ["openrouter"]
    openrouter = aa.finde_anbieter("openrouter")
    assert openrouter.transkription_url() == "https://openrouter.ai/api/v1/audio/transcriptions"  # type: ignore[union-attr]
    assert openrouter.diarisierung_anbieter == "azure"  # type: ignore[union-attr]


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
