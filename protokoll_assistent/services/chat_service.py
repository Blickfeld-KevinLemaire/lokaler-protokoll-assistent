"""Chat mit den eigenen Besprechungen ("Frag mein Meeting").

Der Ablauf ist die uebliche Suche mit anschliessender Antwort (RAG), bewusst
klein gehalten und ohne zusaetzliche Pakete:

1. Ausgewaehlte Transkripte und Protokolle werden in Abschnitte zerlegt.
2. Jeder Abschnitt bekommt einen Einbettungsvektor (lokal ueber Ollama oder
   ueber eine API). Die Vektoren werden je Datei und Modell zwischengespeichert,
   damit eine Frage nicht jedes Mal alles neu berechnet.
3. Die Frage wird ebenfalls eingebettet; die aehnlichsten Abschnitte kommen als
   Auszuege in den Prompt.
4. Das Chatmodell antwortet ausschliesslich anhand dieser Auszuege.

Die Idee (Chat mit eigenen Dokumenten) kennt man aus Werkzeugen wie Open WebUI;
der Code hier ist eigen und kennt weder Qt noch ein Netz: Einbettung und Chat
werden als Funktionen hereingereicht und sind im Test austauschbar.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.services import api_chat_service, ollama_service
from protokoll_assistent.services.speaker_merge_service import cosine_similarity
from protokoll_assistent.utils.timeformat import format_timestamp

EmbedFn = Callable[[list[str]], list[list[float]]]
# (Nachrichten, Funktion fuer Textstuecke) -> vollstaendige Antwort
ChatFn = Callable[[list[dict[str, str]], Callable[[str], None] | None], str]

ART_TRANSKRIPT = "Transkript"
ART_PROTOKOLL = "Zusammenfassung"

MAX_ABSCHNITT_ZEICHEN = 1200
STANDARD_TREFFER = 6
MAX_VERLAUF_NACHRICHTEN = 6
EMBED_STAPEL = 16

SYSTEMPROMPT = (
    "Du bist ein sorgfaeltiger deutschsprachiger Assistent fuer Besprechungen. "
    "Beantworte die Frage ausschliesslich anhand der folgenden Auszuege aus Transkripten und "
    "Zusammenfassungen. Steht die Antwort nicht darin, sage ausdruecklich, dass du sie den "
    "Unterlagen nicht entnehmen kannst - erfinde nichts und ergaenze kein eigenes Wissen. "
    "Behalte Sprecherbezeichnungen bei. Nenne die Quellen am Ende in der Form (Dokument, Uhrzeit). "
    "Antworte knapp und auf Deutsch."
)


class ChatFehler(RuntimeError):
    """Fehler mit einer Meldung, die der Anwender lesen kann."""


@dataclass(frozen=True)
class Dokument:
    pfad: Path
    titel: str
    art: str
    text: str


@dataclass(frozen=True)
class Abschnitt:
    dokument: str
    text: str
    zeit: str | None = None


@dataclass
class Index:
    abschnitte: list[Abschnitt]
    vektoren: list[list[float]]


@dataclass(frozen=True)
class ChatEinstellungen:
    """Alles, was der Chat aus den Einstellungen braucht (ohne Qt)."""

    modus: str  # "lokal" | "api"
    chat_modell: str
    embedding_modell: str
    api_endpunkt: str = ""
    api_embedding_endpunkt: str = ""
    api_schluessel: str = ""

    @property
    def modell_kennung(self) -> str:
        """Kennung fuer den Zwischenspeicher der Vektoren: Vektoren verschiedener
        Modelle sind nicht vergleichbar."""
        return f"{self.modus}:{self.embedding_modell}"


def funktionen_aus_einstellungen(einstellungen: ChatEinstellungen) -> tuple[EmbedFn, ChatFn]:
    """Liefert ``(embed_fn, chat_fn)`` fuer lokal (Ollama) oder API."""
    if einstellungen.modus == "api":
        if not einstellungen.api_schluessel:
            raise ChatFehler("Fuer den Chatbot im API-Modus fehlt der API-Schluessel (Einstellungen, Reiter Chatbot).")

        def embed_api(texte: list[str]) -> list[list[float]]:
            return api_chat_service.embed(
                texte,
                einstellungen.embedding_modell,
                endpoint_url=einstellungen.api_embedding_endpunkt,
                api_key=einstellungen.api_schluessel,
            )

        def chat_api(nachrichten: list[dict[str, str]], on_token: Callable[[str], None] | None) -> str:
            antwort = api_chat_service.chat(
                nachrichten,
                einstellungen.chat_modell,
                endpoint_url=einstellungen.api_endpunkt,
                api_key=einstellungen.api_schluessel,
            )
            if on_token:
                on_token(antwort)
            return antwort

        return embed_api, chat_api

    def embed_lokal(texte: list[str]) -> list[list[float]]:
        return ollama_service.embed(einstellungen.embedding_modell, texte)

    def chat_lokal(nachrichten: list[dict[str, str]], on_token: Callable[[str], None] | None) -> str:
        return ollama_service.chat_stream(nachrichten, einstellungen.chat_modell, on_token=on_token)

    return embed_lokal, chat_lokal


# ---------------------------------------------------------------------------
# Dokumente
# ---------------------------------------------------------------------------
def finde_dokumente(ausgabeordner: Path) -> list[Path]:
    """Transkripte (JSON) und Zusammenfassungen (Markdown) im Ausgabeordner,
    neueste zuerst."""
    if not ausgabeordner.is_dir():
        return []
    treffer = [
        *ausgabeordner.glob("*_lokal_transkript_*.json"),
        *ausgabeordner.glob("*_protokoll_*.md"),
    ]
    return sorted(treffer, key=lambda p: p.stat().st_mtime, reverse=True)


def _transkript_text(daten: dict[str, Any]) -> str:
    namen = {
        e.get("sprecher_id"): e.get("anzeigename") for e in daten.get("sprecher_zuordnung", []) if isinstance(e, dict)
    }
    zeilen = []
    for segment in daten.get("segmente", []):
        sprecher = segment.get("sprecher") or namen.get(segment.get("sprecher_id")) or ""
        beginn = format_timestamp(float(segment.get("start_sekunden", 0.0)))
        text = str(segment.get("text", "")).strip()
        if text:
            zeilen.append(f"[{beginn}] {sprecher + ': ' if sprecher else ''}{text}")
    return "\n".join(zeilen)


def lade_dokument(pfad: Path) -> Dokument:
    try:
        roh = pfad.read_text(encoding="utf-8")
    except OSError as error:
        raise ChatFehler(f"Die Datei '{pfad.name}' konnte nicht gelesen werden: {error}") from error
    if pfad.suffix.lower() == ".json":
        try:
            daten = json.loads(roh)
        except ValueError as error:
            raise ChatFehler(f"'{pfad.name}' ist kein gueltiges Transkript (JSON).") from error
        if not isinstance(daten, dict) or "segmente" not in daten:
            raise ChatFehler(f"'{pfad.name}' enthaelt kein Transkript.")
        return Dokument(pfad, pfad.stem, ART_TRANSKRIPT, _transkript_text(daten))
    return Dokument(pfad, pfad.stem, ART_PROTOKOLL, roh)


def anzeigename(pfad: Path) -> str:
    """Lesbarer Name fuer die Auswahlliste, z. B. 'Zusammenfassung - sitzung'."""
    stamm = pfad.stem
    if "_lokal_transkript_" in stamm:
        art, name = ART_TRANSKRIPT, stamm.split("_lokal_transkript_")[0]
        rest = stamm.split("_lokal_transkript_")[1]
    else:
        art, name = ART_PROTOKOLL, stamm.split("_protokoll_")[0]
        rest = stamm.split("_protokoll_")[-1]
    zeit = re.match(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", rest)
    zusatz = f" ({zeit[3]}.{zeit[2]}.{zeit[1]} {zeit[4]}:{zeit[5]})" if zeit else ""
    return f"{art} - {name}{zusatz}"


_ZEIT = re.compile(r"^\[(\d{2}:\d{2}:\d{2})")


def zerlege(dokument: Dokument, max_zeichen: int = MAX_ABSCHNITT_ZEICHEN) -> list[Abschnitt]:
    """Teilt das Dokument zeilenweise in Abschnitte bis ``max_zeichen``. Die Zeit
    eines Abschnitts ist die der ersten Transkriptzeile darin."""
    abschnitte: list[Abschnitt] = []
    aktuell: list[str] = []
    laenge = 0
    zeit: str | None = None

    def abschliessen() -> None:
        nonlocal aktuell, laenge, zeit
        if aktuell:
            abschnitte.append(Abschnitt(dokument.titel, "\n".join(aktuell), zeit))
        aktuell, laenge, zeit = [], 0, None

    for zeile in dokument.text.splitlines():
        if not zeile.strip():
            continue
        # Sehr lange Einzelzeilen werden hart geteilt.
        stuecke = [zeile[i : i + max_zeichen] for i in range(0, len(zeile), max_zeichen)]
        for stueck in stuecke:
            if laenge + len(stueck) + 1 > max_zeichen and aktuell:
                abschliessen()
            treffer = _ZEIT.match(stueck)
            if not aktuell:
                zeit = treffer[1] if treffer else None
            aktuell.append(stueck)
            laenge += len(stueck) + 1
    abschliessen()
    return abschnitte


# ---------------------------------------------------------------------------
# Index (Einbettungen mit Zwischenspeicher)
# ---------------------------------------------------------------------------
def _cache_pfad(cache_dir: Path, dokument: Dokument, modell_kennung: str) -> Path:
    schluessel = hashlib.sha256(
        f"{dokument.pfad.name}\0{modell_kennung}\0{MAX_ABSCHNITT_ZEICHEN}\0".encode() + dokument.text.encode("utf-8")
    ).hexdigest()
    return cache_dir / f"{schluessel}.json"


def _vektoren_berechnen(
    texte: list[str], embed_fn: EmbedFn, fortschritt: Callable[[int, int], None] | None
) -> list[list[float]]:
    vektoren: list[list[float]] = []
    for start in range(0, len(texte), EMBED_STAPEL):
        vektoren.extend(embed_fn(texte[start : start + EMBED_STAPEL]))
        if fortschritt:
            fortschritt(min(start + EMBED_STAPEL, len(texte)), len(texte))
    return vektoren


def _stapelmelder(
    fortschritt: Callable[[str, int, int], None] | None, titel: str
) -> Callable[[int, int], None] | None:
    if fortschritt is None:
        return None

    def melden(fertig: int, gesamt: int) -> None:
        fortschritt(titel, fertig, gesamt)

    return melden


def baue_index(
    dokumente: list[Dokument],
    embed_fn: EmbedFn,
    cache_dir: Path,
    modell_kennung: str,
    fortschritt: Callable[[str, int, int], None] | None = None,
) -> Index:
    """Bettet alle Abschnitte ein; bereits berechnete Dateien kommen aus dem
    Zwischenspeicher. ``fortschritt(dokumenttitel, fertig, gesamt)``."""
    index = Index([], [])
    cache_dir.mkdir(parents=True, exist_ok=True)
    for dokument in dokumente:
        pfad = _cache_pfad(cache_dir, dokument, modell_kennung)
        gespeichert: dict[str, Any] | None = None
        if pfad.is_file():
            try:
                gespeichert = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                gespeichert = None
        if isinstance(gespeichert, dict) and gespeichert.get("abschnitte") and gespeichert.get("vektoren"):
            abschnitte = [Abschnitt(dokument.titel, a["text"], a.get("zeit")) for a in gespeichert["abschnitte"]]
            vektoren = gespeichert["vektoren"]
        else:
            abschnitte = zerlege(dokument)
            stapel_cb = _stapelmelder(fortschritt, dokument.titel)
            vektoren = _vektoren_berechnen([a.text for a in abschnitte], embed_fn, stapel_cb)
            if abschnitte:
                pfad.write_text(
                    json.dumps(
                        {"abschnitte": [{"text": a.text, "zeit": a.zeit} for a in abschnitte], "vektoren": vektoren}
                    ),
                    encoding="utf-8",
                )
        index.abschnitte.extend(abschnitte)
        index.vektoren.extend(vektoren)
    return index


def suche(index: Index, frage_vektor: list[float], anzahl: int = STANDARD_TREFFER) -> list[tuple[float, Abschnitt]]:
    """Die ``anzahl`` aehnlichsten Abschnitte, beste zuerst. Vektoren anderer
    Laenge (anderes Modell) werden uebersprungen."""
    bewertet = [
        (cosine_similarity(frage_vektor, vektor), abschnitt)
        for abschnitt, vektor in zip(index.abschnitte, index.vektoren, strict=True)
        if len(vektor) == len(frage_vektor)
    ]
    bewertet.sort(key=lambda eintrag: eintrag[0], reverse=True)
    return bewertet[:anzahl]


# ---------------------------------------------------------------------------
# Prompt und Antwort
# ---------------------------------------------------------------------------
_DENKEN = re.compile(r"<think>.*?</think>", re.DOTALL)


def bereinige_antwort(text: str) -> str:
    """Entfernt die "Denkphase" mancher Modelle (<think> ...)."""
    return _DENKEN.sub("", text).strip()


def baue_nachrichten(
    frage: str,
    treffer: list[tuple[float, Abschnitt]],
    verlauf: list[dict[str, str]],
    modell: str = "",
) -> list[dict[str, str]]:
    auszuege = "\n\n".join(
        f"[{nummer}] {abschnitt.dokument}" + (f", ab {abschnitt.zeit}" if abschnitt.zeit else "") + f"\n{abschnitt.text}"
        for nummer, (_, abschnitt) in enumerate(treffer, start=1)
    )
    system = SYSTEMPROMPT + ("\n\n/no_think" if modell.lower().startswith("qwen3") else "")
    nachrichten = [{"role": "system", "content": system}]
    nachrichten.extend(verlauf[-MAX_VERLAUF_NACHRICHTEN:])
    nachrichten.append(
        {"role": "user", "content": f"Auszuege aus den Unterlagen:\n\n{auszuege or '(keine)'}\n\nFrage: {frage}"}
    )
    return nachrichten


def quellenliste(treffer: list[tuple[float, Abschnitt]]) -> list[str]:
    """Eindeutige, lesbare Quellenangaben der verwendeten Abschnitte."""
    gesehen: list[str] = []
    for _, abschnitt in treffer:
        eintrag = abschnitt.dokument + (f" ab {abschnitt.zeit}" if abschnitt.zeit else "")
        if eintrag not in gesehen:
            gesehen.append(eintrag)
    return gesehen


def beantworte(
    frage: str,
    dokumente: list[Dokument],
    verlauf: list[dict[str, str]],
    embed_fn: EmbedFn,
    chat_fn: ChatFn,
    cache_dir: Path,
    modell_kennung: str,
    chat_modell: str = "",
    on_status: Callable[[str], None] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> tuple[str, list[str]]:
    """Ganzer Ablauf einer Frage. Liefert ``(antwort, quellen)``."""
    meldung = on_status or (lambda text: None)
    if not frage.strip():
        raise ChatFehler("Bitte eine Frage eingeben.")
    if not dokumente:
        raise ChatFehler("Bitte links mindestens ein Transkript oder eine Zusammenfassung auswaehlen.")

    meldung("Unterlagen werden vorbereitet …")
    def vorbereitung(titel: str, fertig: int, gesamt: int) -> None:
        meldung(f"Unterlagen werden vorbereitet: {titel} ({fertig}/{gesamt})")

    index = baue_index(dokumente, embed_fn, cache_dir, modell_kennung, fortschritt=vorbereitung)
    if not index.abschnitte:
        raise ChatFehler("In den ausgewaehlten Unterlagen steht kein Text.")

    meldung("Passende Stellen werden gesucht …")
    frage_vektor = embed_fn([frage])[0]
    treffer = suche(index, frage_vektor)

    meldung("Antwort wird erzeugt …")
    nachrichten = baue_nachrichten(frage, treffer, verlauf, chat_modell)
    antwort = bereinige_antwort(chat_fn(nachrichten, on_token))
    if not antwort:
        raise ChatFehler("Das Modell hat keine Antwort geliefert.")
    return antwort, quellenliste(treffer)
