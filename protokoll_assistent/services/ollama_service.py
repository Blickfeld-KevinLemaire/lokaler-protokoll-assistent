"""Client fuer den lokalen Ollama-Dienst (keine Cloud-API, keine OpenRouter-Verbindung).

Es wird ausschliesslich ``http://127.0.0.1:11434`` verwendet. Die
Kommunikation erfolgt ueber die Python-Standardbibliothek (``urllib``),
damit keine zusaetzliche Abhaengigkeit noetig ist.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protokoll_assistent.utils.json_validation import extract_json_object


# Im Container laeuft Ollama als eigener Dienst: Adresse ueber 'OLLAMA_URL'
# (z. B. http://ollama:11434). Ohne Angabe wie bisher der lokale Dienst.
def basis_url_aus_umgebung(umgebung: Mapping[str, str]) -> str:
    return umgebung.get("OLLAMA_URL", "").strip().rstrip("/") or "http://127.0.0.1:11434"


OLLAMA_BASE_URL = basis_url_aus_umgebung(os.environ)
DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
DEFAULT_TIMEOUT_SECONDS = 900
# Kontextgroesse fuer die Protokollauswertung. Ollamas Standard (4096 Tokens)
# reicht fuer einen 10-Minuten-Abschnitt samt Systemprompt nicht: Ollama
# verwirft dann still den Anfang des Transkripts (im server.log als
# 'truncated = 1'), und das Protokoll entsteht aus unvollstaendigem Text.
#
# Die Groesse richtet sich nach dem Aufruf: Eingabe (gut 3 Zeichen je Token)
# plus Platz fuer die Antwort, aufgerundet auf eine Stufe. Ein fester grosser
# Wert waere bequemer, kostet aber auf kleinen Grafikkarten viel: Mit 32K passte
# das 4B-Modell auf 6 GB nicht mehr ganz in den Grafikspeicher und schrieb nur
# halb so schnell (21 statt 42 Tokens/s). So laufen die vielen
# Abschnittsanalysen mit 16K, nur das Gesamtprotokoll braucht 32K: Seine
# Eingabe darf bis zu protocol_service.MAX_KONTEXT_ZEICHEN lang sein (gemessen
# ~12.000 Tokens), und die Antwort hatte bei einer Stunde Material ~10.200.
PROTOKOLL_KONTEXTSTUFEN = (16384, 32768)
PROTOKOLL_NUM_CTX = PROTOKOLL_KONTEXTSTUFEN[-1]
PROTOKOLL_ANTWORT_TOKENS = 10_240
ZEICHEN_JE_TOKEN = 3


def kontext_fuer_protokoll(system: str, prompt: str) -> int:
    """Kleinste Kontextstufe, in die Eingabe und Antwort passen."""
    bedarf = (len(system) + len(prompt)) / ZEICHEN_JE_TOKEN + PROTOKOLL_ANTWORT_TOKENS
    return next((stufe for stufe in PROTOKOLL_KONTEXTSTUFEN if stufe >= bedarf), PROTOKOLL_NUM_CTX)

# Offizieller Windows-Installer. Wird nur heruntergeladen/gestartet, wenn
# 'ollama' auf dem Zielrechner nirgends gefunden wurde -- macht die
# Anwendung auch auf einem PC ohne vorinstalliertes Ollama benutzbar. Da
# der Installer eine Rechteerhoehung/Nutzerinteraktion verlangt, kann er
# nicht lautlos im Hintergrund durchlaufen; die Anwendung laedt ihn herunter
# und startet ihn, der Nutzer schliesst die Installation selbst ab.
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"

DownloadFn = Callable[[str, Path], None]


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaModellOption:
    id: str
    label: str
    groesse_gb: float
    hinweis: str


# Kuratierte Auswahl fuer die Protokollauswertung. Wie bei den Whisper-Modellen
# ist das keine Einschraenkung: In den Einstellungen laesst sich jeder Name aus
# der Ollama-Bibliothek (https://ollama.com/library) eintragen. Die Namen legen
# die Q4-Fassung ausdruecklich fest (statt des Ollama-Standards, der sich
# aendern kann); die Groessen sind deren gerundete Downloadgroessen.
OLLAMA_MODELLE: list[OllamaModellOption] = [
    OllamaModellOption(
        id=DEFAULT_MODEL,
        label="Qwen3.5 4B (empfohlener Standard)",
        groesse_gb=3.3,
        hinweis=(
            "Nachfolger von Qwen3 8B: trotz halber Groesse leistungsfaehiger, solide auf Deutsch. "
            "Ab etwa 6 GB Grafikspeicher oder 16 GB RAM."
        ),
    ),
    OllamaModellOption(
        id="qwen3.5:9b-q4_K_M",
        label="Qwen3.5 9B (genauer, braucht mehr Speicher)",
        groesse_gb=6.6,
        hinweis=(
            "Bessere Qualitaet bei langen oder schwierigen Besprechungen; liegt in Tests vor dem "
            "frueheren Qwen3 14B. Ab etwa 10 GB Grafikspeicher oder 32 GB RAM."
        ),
    ),
    OllamaModellOption(
        id="qwen3.8:27b-q4_K_M",
        label="Qwen3.8 27B (sehr genau, nur mit grosser Grafikkarte)",
        groesse_gb=18.0,
        hinweis=(
            "Hoechste Qualitaet in dieser Auswahl. Braucht etwa 24 GB Grafikspeicher; "
            "auf dem Prozessor allein zu langsam."
        ),
    ),
    OllamaModellOption(
        id="gemma4:12b-it-q4_K_M",
        label="Gemma 4 12B (Google)",
        groesse_gb=8.0,
        hinweis="Sehr gute Mehrsprachigkeit und Textqualitaet. Ab etwa 10 GB Grafikspeicher oder 32 GB RAM.",
    ),
]


# Einbettungsmodelle fuer die Suche in Transkripten ("Frag mein Meeting"). Sie
# erzeugen keine Texte, sondern Zahlenvektoren; Aehnliches liegt nah beieinander.
OLLAMA_EMBEDDING_MODELLE: list[OllamaModellOption] = [
    OllamaModellOption(
        id="bge-m3",
        label="BGE-M3 (mehrsprachig, empfohlen fuer Deutsch)",
        groesse_gb=1.2,
        hinweis="Starke mehrsprachige Suche, gut fuer deutsche Besprechungen. Verarbeitet lange Abschnitte.",
    ),
    OllamaModellOption(
        id="nomic-embed-text",
        label="Nomic Embed Text (klein und schnell)",
        groesse_gb=0.3,
        hinweis="Sehr klein und schnell, vor allem fuer Englisch optimiert; auf Deutsch weniger treffsicher.",
    ),
    OllamaModellOption(
        id="mxbai-embed-large",
        label="MixedBread Embed Large",
        groesse_gb=0.7,
        hinweis="Gute Qualitaet bei maessigem Speicherbedarf, ueberwiegend englisch trainiert.",
    ),
    OllamaModellOption(
        id="embeddinggemma",
        label="EmbeddingGemma (Google, mehrsprachig)",
        groesse_gb=0.6,
        hinweis="Kleines mehrsprachiges Modell von Google.",
    ),
]


def get_modell_option(model_id: str) -> OllamaModellOption | None:
    return next(
        (option for option in [*OLLAMA_MODELLE, *OLLAMA_EMBEDDING_MODELLE] if option.id == model_id), None
    )


def find_ollama_executable():
    """Sucht das Ollama-Programm: erst im PATH, dann an den ueblichen
    Installationsorten unter Windows.

    Der Installer traegt Ollama in den PATH ein, aber nur fuer *neu
    gestartete* Programme. Direkt nach einer Installation aus der
    laufenden Anwendung heraus fand ``shutil.which`` es deshalb nicht --
    der Systemtest meldete "nicht gefunden", obwohl es installiert war."""
    from pathlib import Path

    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        return Path(found)
    for variable, unterordner in (
        ("LOCALAPPDATA", Path("Programs") / "Ollama"),
        ("PROGRAMFILES", Path("Ollama")),
    ):
        basis = os.environ.get(variable)
        if basis:
            kandidat = Path(basis) / unterordner / "ollama.exe"
            if kandidat.is_file():
                return kandidat
    return None


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_service_running(base_url: str = OLLAMA_BASE_URL, timeout: float = 3) -> bool:
    try:
        _get_json(f"{base_url}/api/tags", timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False


def list_models(base_url: str = OLLAMA_BASE_URL, timeout: float = 5) -> list[str]:
    try:
        data = _get_json(f"{base_url}/api/tags", timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as error:
        raise OllamaError(f"Ollama ist unter {base_url} nicht erreichbar: {error}") from error
    models = data.get("models", [])
    return [entry.get("name", "") for entry in models if isinstance(entry, dict)]


def modelle_entladen(base_url: str = OLLAMA_BASE_URL, opener: OeffneFn | None = None, timeout: float = 30) -> list[str]:
    """Nimmt alle gerade geladenen Modelle aus dem Speicher (``keep_alive: 0``)
    und liefert ihre Namen. Ollama haelt ein Modell sonst noch Minuten nach dem
    letzten Aufruf im Grafikspeicher -- auf einer 6-GB-Karte fehlt dieser Platz
    dann Whisper. Ist Ollama nicht erreichbar, gibt es nichts zu entladen."""
    try:
        geladen = [
            str(eintrag.get("name") or eintrag.get("model") or "")
            for eintrag in _get_json(f"{base_url}/api/ps", timeout=5).get("models", [])
            if isinstance(eintrag, dict)
        ]
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    entladen = []
    for name in (n for n in geladen if n):
        try:
            with _post_json(f"{base_url}/api/generate", {"model": name, "keep_alive": 0}, timeout, opener):
                entladen.append(name)
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return entladen


def is_model_available(model: str = DEFAULT_MODEL, base_url: str = OLLAMA_BASE_URL) -> bool:
    """Prueft, ob genau dieses Modell bei Ollama liegt.

    Ist eine Fassung angegeben ("qwen3:8b"), muss sie uebereinstimmen.
    Frueher genuegte der Name vor dem Doppelpunkt: Mit einem
    installierten 'qwen3:0.6b' galt auch 'qwen3:8b' als vorhanden. Der
    Assistent liess den Download dann aus und die Systemdiagnose meldete
    "Modell vorhanden" -- bis die Verarbeitung nach der fertigen
    Transkription am ersten '/api/generate' scheiterte.

    Ohne Fassung ("qwen3") zaehlt weiterhin jede installierte Fassung
    dieses Namens: Dann hat der Aufrufer sich bewusst nicht festgelegt.
    """
    try:
        available = list_models(base_url)
    except OllamaError:
        return False
    if ":" in model:
        return model in available
    return any(name == model or name.split(":")[0] == model for name in available)


def modell_fehlt(model: str, base_url: str = OLLAMA_BASE_URL) -> bool:
    """True nur, wenn Ollama erreichbar ist und das Modell wirklich nicht hat.
    Ist Ollama nicht erreichbar, bleibt die Antwort False: Dann ist der
    Fehler ein anderer und wird an der Stelle gemeldet, an der er auftritt."""
    try:
        list_models(base_url)
    except OllamaError:
        return False
    return not is_model_available(model, base_url)


PullFortschrittFn = Callable[[str, int, int], None]
OeffneFn = Callable[..., Any]


def pull_model(
    model: str,
    progress_cb: PullFortschrittFn | None = None,
    base_url: str = OLLAMA_BASE_URL,
    opener: OeffneFn | None = None,
    timeout: float = 3600,
) -> None:
    """Laedt ein Modell ueber ``/api/pull`` herunter.

    ``progress_cb(status, fertig_bytes, gesamt_bytes)`` wird fuer jede Meldung
    von Ollama aufgerufen; die Zahlen sind 0, solange Ollama keine nennt (z.B.
    bei "verifying sha256 digest"). Fehler werden als ``OllamaError`` mit lesbarer
    Meldung gemeldet. Nur die Standardbibliothek, kein Programmaufruf: Es
    genuegt der laufende Dienst, die Programmdatei muss nicht im Suchpfad liegen.
    """
    name = model.strip()
    if not name:
        raise OllamaError("Bitte einen Modellnamen angeben.")
    log = progress_cb or (lambda status, fertig, gesamt: None)
    body = json.dumps({"model": name, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/pull",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    oeffnen = opener or urllib.request.urlopen
    try:
        with oeffnen(request, timeout=timeout) as response:
            for zeile in response:
                text = zeile.decode("utf-8", errors="replace").strip() if isinstance(zeile, bytes) else str(zeile).strip()
                if not text:
                    continue
                try:
                    meldung = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(meldung, dict):
                    continue
                if meldung.get("error"):
                    raise OllamaError(f"Ollama konnte '{name}' nicht laden: {meldung['error']}")
                log(str(meldung.get("status", "")), int(meldung.get("completed") or 0), int(meldung.get("total") or 0))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:500]
        raise OllamaError(f"Ollama-Fehler HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise OllamaError(
            f"Ollama ist nicht erreichbar ({error.reason}). Bitte Ollama starten bzw. installieren."
        ) from error
    except (OSError, TimeoutError) as error:
        raise OllamaError(f"Der Download wurde unterbrochen: {error}") from error


def _post_json(url: str, payload: dict[str, Any], timeout: float, opener: OeffneFn | None) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    return (opener or urllib.request.urlopen)(request, timeout=timeout)


def _ollama_fehler(error: Exception) -> OllamaError:
    if isinstance(error, urllib.error.HTTPError):
        details = error.read().decode("utf-8", errors="replace")[:500]
        return OllamaError(f"Ollama-Fehler HTTP {error.code}: {details}")
    if isinstance(error, urllib.error.URLError):
        return OllamaError(f"Ollama ist nicht erreichbar ({error.reason}). Bitte Ollama starten bzw. installieren.")
    return OllamaError(f"Die Anfrage an Ollama wurde unterbrochen: {error}")


def embed(
    model: str,
    texts: list[str],
    base_url: str = OLLAMA_BASE_URL,
    opener: OeffneFn | None = None,
    timeout: float = 300,
) -> list[list[float]]:
    """Berechnet Einbettungsvektoren ueber ``/api/embed`` (ein Vektor je Text)."""
    if not texts:
        return []
    try:
        with _post_json(f"{base_url}/api/embed", {"model": model, "input": texts}, timeout, opener) as response:
            daten = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise _ollama_fehler(error) from error
    except ValueError as error:
        raise OllamaError("Die Antwort von Ollama (Einbettungen) war kein gueltiges JSON.") from error
    vektoren = daten.get("embeddings") if isinstance(daten, dict) else None
    if not isinstance(vektoren, list) or len(vektoren) != len(texts):
        raise OllamaError(
            f"Ollama hat fuer das Modell '{model}' keine passenden Einbettungen geliefert. "
            "Ist es ein Einbettungsmodell und installiert?"
        )
    return [[float(x) for x in vektor] for vektor in vektoren]


def chat_stream(
    messages: list[dict[str, str]],
    model: str,
    on_token: Callable[[str], None] | None = None,
    base_url: str = OLLAMA_BASE_URL,
    opener: OeffneFn | None = None,
    num_ctx: int = 8192,
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Chat ueber ``/api/chat`` mit Textstrom. ``on_token`` bekommt jedes Stueck
    der Antwort sofort; zurueck kommt der vollstaendige Text. ``num_ctx`` ist
    bewusst groesser als Ollamas Standard (2048): Die Auszuege aus den
    Transkripten wuerden sonst stillschweigend abgeschnitten.

    ``think: False`` schaltet die Denkphase ab. Qwen3.5 denkt sonst vor jeder
    Antwort und versteht das '/no_think' im Systemprompt nicht mehr (das
    galt nur fuer Qwen3). Modelle ohne Denkphase stoert die Angabe nicht:
    Ollama lehnt nur ``think: True`` bei ihnen ab."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {"num_ctx": num_ctx, "temperature": temperature},
    }
    teile: list[str] = []
    try:
        with _post_json(f"{base_url}/api/chat", payload, timeout, opener) as response:
            for zeile in response:
                text = zeile.decode("utf-8", errors="replace").strip() if isinstance(zeile, bytes) else str(zeile).strip()
                if not text:
                    continue
                try:
                    meldung = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(meldung, dict):
                    continue
                if meldung.get("error"):
                    raise OllamaError(f"Ollama meldet einen Fehler: {meldung['error']}")
                stueck = (meldung.get("message") or {}).get("content") or ""
                if stueck:
                    teile.append(stueck)
                    if on_token:
                        on_token(stueck)
                if meldung.get("done"):
                    break
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise _ollama_fehler(error) from error
    return "".join(teile)


def generate_json(
    prompt: str,
    system: str,
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.0,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    """Ruft ``/api/generate`` mit ``format: json`` und Temperatur 0 auf und
    liefert das geparste JSON-Objekt aus der Modellantwort zurueck. Die
    Denkphase ist abgeschaltet, Begruendung bei ``chat_stream``. Ohne
    ``num_ctx`` waehlt ``kontext_fuer_protokoll`` die Kontextgroesse."""
    num_ctx = num_ctx or kontext_fuer_protokoll(system, prompt)
    body = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        raise OllamaError(f"Ollama-Fehler HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise OllamaError(f"Ollama ist nicht erreichbar: {error}") from error
    except TimeoutError as error:
        raise OllamaError("Die Anfrage an das lokale Modell hat das Zeitlimit ueberschritten.") from error

    raw_text = result.get("response", "")
    parsed = extract_json_object(raw_text)
    if parsed is None:
        raise OllamaError(
            "Die Antwort des lokalen Modells konnte nicht als JSON gelesen werden."
        )
    return parsed


def _default_download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as response, destination.open("wb") as out_file:
        import shutil as _shutil

        _shutil.copyfileobj(response, out_file)


def download_ollama_installer(
    destination_dir: Path, download_fn: DownloadFn | None = None, url: str = OLLAMA_INSTALLER_URL
) -> Path:
    """Laedt den offiziellen Ollama-Windows-Installer herunter."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "OllamaSetup.exe"
    (download_fn or _default_download)(url, destination)
    return destination


def launch_installer(installer_path: Path) -> subprocess.Popen:
    """Startet den Installer nicht-blockierend (verlangt Nutzerinteraktion/
    ggf. Rechteerhoehung -- kann daher nicht lautlos automatisiert werden)."""
    return subprocess.Popen([str(installer_path)])


def ensure_ollama_or_offer_installer(
    destination_dir: Path,
    download_fn: DownloadFn | None = None,
    auto_launch: bool = True,
    progress_cb: Callable[[str], None] | None = None,
) -> bool:
    """Prueft, ob Ollama vorhanden ist. Falls nicht, wird der offizielle
    Installer heruntergeladen und (falls ``auto_launch``) gestartet.

    Gibt ``True`` zurueck, wenn Ollama bereits vorhanden war (nichts zu tun),
    sonst ``False`` -- der Nutzer muss die gestartete Installation manuell
    abschliessen, danach kann diese Pruefung erneut ausgefuehrt werden.
    """
    log = progress_cb or (lambda message: None)

    if find_ollama_executable() is not None:
        log("Ollama ist bereits installiert.")
        return True

    log("Ollama wurde nicht gefunden -- lade offiziellen Installer herunter ...")
    try:
        installer_path = download_ollama_installer(destination_dir, download_fn=download_fn)
    except OSError as error:
        log(f"Ollama-Installer konnte nicht heruntergeladen werden: {error}")
        return False

    log(f"Installer heruntergeladen: {installer_path}")
    if auto_launch:
        log("Installer wird gestartet -- bitte die Installation im geoeffneten Fenster abschliessen.")
        launch_installer(installer_path)
    return False
