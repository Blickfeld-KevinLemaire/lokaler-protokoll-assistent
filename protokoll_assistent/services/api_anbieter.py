"""Voreinstellungen fuer die API-Anbieter.

Wer statt der lokalen Verarbeitung eine API nutzt, soll seinen Anbieter in den
Einstellungen auswaehlen koennen und nur noch den Schluessel eintragen
muessen. Diese Tabelle kennt je Anbieter Basis-Adresse, Vorschlaege fuer die
Modellnamen, die Faehigkeiten (Chat, Einbettungen, Transkription) und die
Seiten, auf denen man einen Schluessel erzeugt bzw. die Dokumentation findet.

Die Transkription ist nur bei Anbietern eingetragen, die das Audio -- wie
OpenRouter -- im API-Aufruf selbst entgegennehmen (JSON mit Base64-Audio).
Anbieter, die dafuer einen Dateiupload verlangen (multipart), sind dort
bewusst NICHT aufgefuehrt: Es soll nichts als Datei irgendwohin uebertragen
werden.

Es ist **keine** Voreinstellung aktiv: Solange der Anwender keinen Anbieter
gewaehlt hat, bleiben Endpunkte und Modelle leer -- frueher stand dort
OpenRouter, und Texte bzw. Aufnahmen gingen ohne bewusste Entscheidung an
diesen Vermittler.

Modellnamen aendern sich bei den Anbietern laufend; sie sind deshalb nur
Vorschlaege, im Dialog frei aenderbar, und die Dokumentationsseite des
Anbieters ist jeweils verlinkt. Endpunkte folgen der OpenAI-Schnittstelle
(``/chat/completions``, ``/embeddings``, ``/audio/transcriptions``) -- die
Anfrage wird mit ``Authorization: Bearer <Schluessel>`` beglaubigt.

Die Anwendung kennt Qt nicht; die Datei haelt nur Daten und kleine Funktionen.
"""

from __future__ import annotations

from dataclasses import dataclass

ANBIETER_EIGENER = "eigener"

CHAT_PFAD = "/chat/completions"
EMBEDDING_PFAD = "/embeddings"
TRANSKRIPTION_PFAD = "/audio/transcriptions"

# Platzhalter in der Adresse, den der Anwender ersetzen muss (Azure).
PLATZHALTER_RESSOURCE = "RESSOURCENNAME"


@dataclass(frozen=True)
class ApiAnbieter:
    id: str
    name: str
    basis_url: str
    schluessel_link: str
    doku_link: str
    standort: str
    hinweis: str = ""
    chat_modell: str = ""
    embedding_modell: str = ""
    transkription_modell: str = ""
    # Nur OpenRouter: Name des Anbieters, der die Sprechertrennung liefert.
    diarisierung_anbieter: str = ""

    @property
    def kann_chat(self) -> bool:
        return bool(self.chat_modell)

    @property
    def kann_embeddings(self) -> bool:
        return bool(self.embedding_modell)

    @property
    def kann_transkription(self) -> bool:
        return bool(self.transkription_modell)

    @property
    def hat_platzhalter(self) -> bool:
        return PLATZHALTER_RESSOURCE in self.basis_url

    def chat_url(self) -> str:
        return self.basis_url + CHAT_PFAD

    def embedding_url(self) -> str:
        return self.basis_url + EMBEDDING_PFAD

    def transkription_url(self) -> str:
        return self.basis_url + TRANSKRIPTION_PFAD


# Reihenfolge = Reihenfolge im Auswahlfeld: erst die Anbieter, die bei der
# Aufgabe (Protokolle aus Besprechungen, personenbezogene Daten) naheliegen --
# Rechenzentren in Deutschland/EU --, dann die grossen Direktanbieter.
ANBIETER: tuple[ApiAnbieter, ...] = (
    ApiAnbieter(
        id="ionos",
        name="IONOS AI Model Hub",
        basis_url="https://openai.inference.de-txl.ionos.com/v1",
        schluessel_link="https://docs.ionos.com/cloud/ai/ai-model-hub/ai-model-hub",
        doku_link="https://docs.ionos.com/cloud/ai/ai-model-hub/ai-model-hub",
        standort="Rechenzentrum in Deutschland (Berlin)",
        hinweis="Der Zugangstoken wird im IONOS-Konto erzeugt. Keine Sprache-zu-Text-Funktion über diese Schnittstelle.",
        chat_modell="meta-llama/Llama-3.3-70B-Instruct",
        embedding_modell="BAAI/bge-m3",
    ),
    ApiAnbieter(
        id="stackit",
        name="STACKIT AI Model Serving",
        basis_url="https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1",
        schluessel_link="https://docs.stackit.cloud/products/data-and-ai/ai-model-serving/basics/introduction/",
        doku_link="https://docs.stackit.cloud/products/data-and-ai/ai-model-serving/tutorials/integrate-stackit-ai-model-serving-with-other-applications/",
        standort="Rechenzentren in Deutschland (Region eu01)",
        hinweis="Authentifizierung mit einem „Auth Token“ des AI Model Serving. Keine Sprache-zu-Text-Funktion.",
        chat_modell="google/gemma-3-27b-it",
        embedding_modell="intfloat/e5-mistral-7b-instruct",
    ),
    ApiAnbieter(
        id="mistral",
        name="Mistral AI",
        basis_url="https://api.mistral.ai/v1",
        schluessel_link="https://console.mistral.ai/api-keys",
        doku_link="https://docs.mistral.ai/capabilities/audio_transcription",
        standort="Anbieter aus Frankreich (EU)",
        hinweis="Chat und Einbettungen. Keine Transkription über diese Anwendung (sie erwartet das OpenRouter-Format).",
        chat_modell="mistral-small-latest",
        embedding_modell="mistral-embed",
    ),
    ApiAnbieter(
        id="scaleway",
        name="Scaleway Generative APIs",
        basis_url="https://api.scaleway.ai/v1",
        schluessel_link="https://console.scaleway.com/iam/api-keys",
        doku_link="https://www.scaleway.com/en/docs/generative-apis/reference-content/openai-compatibility/",
        standort="Anbieter aus Frankreich (EU)",
        hinweis="Chat und Einbettungen. Keine Transkription über diese Anwendung.",
        chat_modell="llama-3.3-70b-instruct",
        embedding_modell="bge-multilingual-gemma2",
    ),
    ApiAnbieter(
        id="azure",
        name="Microsoft Azure OpenAI",
        basis_url=f"https://{PLATZHALTER_RESSOURCE}.openai.azure.com/openai/v1",
        schluessel_link="https://portal.azure.com/",
        doku_link="https://learn.microsoft.com/en-us/azure/foundry/openai/reference",
        standort="Region frei wählbar (z. B. Deutschland, Schweden)",
        hinweis=(
            f"In der Adresse „{PLATZHALTER_RESSOURCE}“ durch den Namen der eigenen Azure-Ressource ersetzen. "
            "Als Modellname gilt der Name der Bereitstellung („Deployment“), nicht der Modellname. "
            "Keine Transkription über diese Anwendung."
        ),
        chat_modell="gpt-4o-mini",
        embedding_modell="text-embedding-3-small",
    ),
    ApiAnbieter(
        id="openai",
        name="OpenAI",
        basis_url="https://api.openai.com/v1",
        schluessel_link="https://platform.openai.com/api-keys",
        doku_link="https://developers.openai.com/docs/guides/speech-to-text",
        standort="Anbieter aus den USA",
        hinweis="Chat und Einbettungen. Keine Transkription über diese Anwendung.",
        chat_modell="gpt-4o-mini",
        embedding_modell="text-embedding-3-small",
    ),
    ApiAnbieter(
        id="anthropic",
        name="Anthropic (Claude)",
        basis_url="https://api.anthropic.com/v1",
        schluessel_link="https://platform.claude.com/settings/keys",
        doku_link="https://platform.claude.com/docs/en/api/openai-sdk",
        standort="Anbieter aus den USA",
        hinweis=(
            "Nur Chat (Protokoll, Frag mein Meeting) über die OpenAI-kompatible Schnittstelle. "
            "Keine Einbettungen und keine Transkription."
        ),
        chat_modell="claude-sonnet-5-5",
    ),
    ApiAnbieter(
        id="google",
        name="Google Gemini",
        basis_url="https://generativelanguage.googleapis.com/v1beta/openai",
        schluessel_link="https://aistudio.google.com/apikey",
        doku_link="https://ai.google.dev/gemini-api/docs/openai",
        standort="Anbieter aus den USA",
        hinweis="Chat und Einbettungen über die OpenAI-kompatible Schnittstelle. Keine Transkription.",
        chat_modell="gemini-2.5-flash",
        embedding_modell="gemini-embedding-001",
    ),
    ApiAnbieter(
        id="groq",
        name="Groq",
        basis_url="https://api.groq.com/openai/v1",
        schluessel_link="https://console.groq.com/keys",
        doku_link="https://console.groq.com/docs/speech-to-text",
        standort="Anbieter aus den USA",
        hinweis="Nur Chat (sehr schnell). Keine Einbettungen und keine Transkription über diese Anwendung.",
        chat_modell="llama-3.3-70b-versatile",
    ),
    ApiAnbieter(
        id="openrouter",
        name="OpenRouter",
        basis_url="https://openrouter.ai/api/v1",
        schluessel_link="https://openrouter.ai/keys",
        doku_link="https://openrouter.ai/docs/guides/overview/multimodal/stt",
        standort="Vermittler: leitet an den jeweiligen Modellanbieter weiter",
        hinweis="Ein Schlüssel für viele Modelle verschiedener Anbieter. Transkription mit Sprechertrennung über Azure.",
        chat_modell="openai/gpt-4o-mini",
        embedding_modell="openai/text-embedding-3-small",
        transkription_modell="microsoft/mai-transcribe-2",
        diarisierung_anbieter="azure",
    ),
)


def finde_anbieter(anbieter_id: str | None) -> ApiAnbieter | None:
    return next((a for a in ANBIETER if a.id == anbieter_id), None)


def erkenne_anbieter(endpunkt: str | None) -> ApiAnbieter | None:
    """Welcher Anbieter gehoert zu dieser gespeicherten Adresse?

    Dient dazu, bei einer schon vorhandenen Einstellung den passenden Anbieter
    im Auswahlfeld anzuzeigen, und zum Ableiten des Uebertragungsformats.
    ``None`` fuer eigene/unbekannte Adressen."""
    if not endpunkt:
        return None
    adresse = endpunkt.strip().rstrip("/").lower()
    for anbieter in ANBIETER:
        basis = anbieter.basis_url.lower()
        if adresse == basis or adresse.startswith(basis + "/"):
            return anbieter
    # Azure: die Ressource ist vom Anwender eingesetzt, der Rest der Adresse fest.
    if ".openai.azure.com/openai/v1" in adresse:
        return finde_anbieter("azure")
    return None


def adresse_vollstaendig(endpunkt: str | None) -> bool:
    """Ist eine Adresse eingetragen, ohne offenen Platzhalter?"""
    if not endpunkt or not endpunkt.strip():
        return False
    return PLATZHALTER_RESSOURCE not in endpunkt
