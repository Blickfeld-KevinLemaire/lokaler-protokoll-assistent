"""Client fuer den lokalen Ollama-Dienst (keine Cloud-API, keine OpenRouter-Verbindung).

Es wird ausschliesslich ``http://127.0.0.1:11434`` verwendet. Die
Kommunikation erfolgt ueber die Python-Standardbibliothek (``urllib``),
damit keine zusaetzliche Abhaengigkeit noetig ist.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from utils.json_validation import extract_json_object

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TIMEOUT_SECONDS = 900

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


def find_ollama_executable():
    from pathlib import Path

    found = shutil.which("ollama") or shutil.which("ollama.exe")
    return Path(found) if found else None


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


def generate_json(
    prompt: str,
    system: str,
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.0,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Ruft ``/api/generate`` mit ``format: json`` und Temperatur 0 auf und
    liefert das geparste JSON-Objekt aus der Modellantwort zurueck."""
    body = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
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
