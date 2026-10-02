import json
import urllib.error

import pytest

from protokoll_assistent.services import ollama_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_is_service_running_true_when_tags_reachable(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": []}),
    )
    assert ollama_service.is_service_running() is True


def test_is_service_running_false_on_connection_error(monkeypatch):
    def raise_error(request, timeout=None):
        raise urllib.error.URLError("Verbindung verweigert")

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_error)
    assert ollama_service.is_service_running() is False


def test_is_model_available_matches_exact_and_base_name(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": [{"name": "qwen3:8b"}]}),
    )
    assert ollama_service.is_model_available("qwen3:8b") is True
    assert ollama_service.is_model_available("qwen3") is True
    assert ollama_service.is_model_available("llama3:8b") is False


def test_is_model_available_false_when_service_down(monkeypatch):
    def raise_error(request, timeout=None):
        raise urllib.error.URLError("nicht erreichbar")

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_error)
    assert ollama_service.is_model_available() is False


def test_generate_json_parses_response_field(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": '{"titel": "Test"}'}),
    )
    result = ollama_service.generate_json("Frage", "System")
    assert result == {"titel": "Test"}


def test_generate_json_raises_on_unparsable_response(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": "das ist kein JSON"}),
    )
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_json("Frage", "System")


def test_generate_json_raises_ollama_error_on_http_error(monkeypatch):
    def raise_http_error(request, timeout=None):
        raise urllib.error.HTTPError("url", 500, "Serverfehler", {}, None)

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_json("Frage", "System")


def test_generate_json_sends_temperature_zero_and_json_format(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"response": "{}"})

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", fake_urlopen)
    ollama_service.generate_json("Frage", "System", model="qwen3:8b")
    assert captured["body"]["options"]["temperature"] == 0.0
    assert captured["body"]["format"] == "json"
    assert captured["body"]["model"] == "qwen3:8b"
    assert captured["body"]["stream"] is False


def test_ensure_ollama_or_offer_installer_returns_true_when_already_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: object())
    download_calls = []
    monkeypatch.setattr(
        ollama_service, "download_ollama_installer", lambda *a, **kw: download_calls.append((a, kw))
    )
    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path)
    assert result is True
    assert download_calls == []


def test_ensure_ollama_or_offer_installer_downloads_and_launches_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    installer_path = tmp_path / "OllamaSetup.exe"
    monkeypatch.setattr(
        ollama_service, "download_ollama_installer", lambda destination_dir, download_fn=None: installer_path
    )
    launch_calls = []
    monkeypatch.setattr(ollama_service, "launch_installer", lambda path: launch_calls.append(path))

    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, auto_launch=True)

    assert result is False
    assert launch_calls == [installer_path]


def test_ensure_ollama_or_offer_installer_skips_launch_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    monkeypatch.setattr(
        ollama_service,
        "download_ollama_installer",
        lambda destination_dir, download_fn=None: tmp_path / "OllamaSetup.exe",
    )
    launch_calls = []
    monkeypatch.setattr(ollama_service, "launch_installer", lambda path: launch_calls.append(path))

    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, auto_launch=False)

    assert result is False
    assert launch_calls == []


def test_ensure_ollama_or_offer_installer_handles_download_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)

    def failing_download(destination_dir, download_fn=None):
        raise OSError("Netzwerkfehler")

    monkeypatch.setattr(ollama_service, "download_ollama_installer", failing_download)
    messages = []
    result = ollama_service.ensure_ollama_or_offer_installer(tmp_path, progress_cb=messages.append)
    assert result is False
    assert any("nicht heruntergeladen" in message for message in messages)


def test_download_ollama_installer_uses_injected_download_fn(tmp_path):
    def fake_download(url, destination):
        destination.write_bytes(b"fake-installer-bytes")

    result = ollama_service.download_ollama_installer(tmp_path, download_fn=fake_download)
    assert result == tmp_path / "OllamaSetup.exe"
    assert result.read_bytes() == b"fake-installer-bytes"


def test_is_model_available_verlangt_die_angegebene_fassung(monkeypatch):
    # Frueher genuegte der Name vor dem Doppelpunkt. Mit einem
    # installierten 'qwen3:0.6b' galt auch 'qwen3:8b' als vorhanden -- der
    # Einrichtungsassistent liess den Download aus, die Systemdiagnose
    # meldete Erfolg, und erst nach der fertigen Transkription scheiterte
    # die Protokollauswertung am ersten Modellaufruf.
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"models": [{"name": "qwen3:0.6b"}]}),
    )
    assert ollama_service.is_model_available("qwen3:8b") is False
    assert ollama_service.is_model_available("qwen3:0.6b") is True
    # Ohne Fassungsangabe legt sich der Aufrufer bewusst nicht fest.
    assert ollama_service.is_model_available("qwen3") is True


def test_generate_json_liest_antwort_mit_klammer_in_zeichenkette(monkeypatch):
    # Durchgehender Weg: So kommt die Antwort wirklich bei
    # protocol_service an -- als Fliesstext um das JSON herum.
    rohantwort = 'Gerne:\n{"kernaussagen": ["Platzhalter } im Text"], "aufgaben": []}'
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": rohantwort}),
    )

    ergebnis = ollama_service.generate_json("Frage", "System")

    assert ergebnis["kernaussagen"] == ["Platzhalter } im Text"]


# --------------------------------------------------------------------------
# Modellliste und Modell herunterladen
# --------------------------------------------------------------------------
def test_modellliste_beginnt_mit_dem_standard_und_hat_eindeutige_namen():
    ids = [option.id for option in ollama_service.OLLAMA_MODELLE]
    assert ids[0] == ollama_service.DEFAULT_MODEL
    assert len(ids) == len(set(ids)) >= 5
    assert ollama_service.get_modell_option("qwen3:4b").groesse_gb < 3
    assert ollama_service.get_modell_option("gibt-es-nicht") is None


class _PullAntwort:
    def __init__(self, zeilen):
        self._zeilen = zeilen

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._zeilen)


def _opener(zeilen, gesehen=None):
    def oeffnen(request, timeout=None):
        if gesehen is not None:
            gesehen["body"] = json.loads(request.data.decode("utf-8"))
            gesehen["url"] = request.full_url
        return _PullAntwort(zeilen)

    return oeffnen


def test_pull_model_meldet_fortschritt_und_ignoriert_unlesbare_zeilen():
    zeilen = [
        b'{"status": "pulling manifest"}\n',
        b"\n",
        b"kein json\n",
        b'["kein objekt"]\n',
        b'{"status": "pulling abc", "total": 1000, "completed": 250}\n',
        b'{"status": "success"}\n',
        '{"status": "als text"}\n',
    ]
    meldungen, gesehen = [], {}
    ollama_service.pull_model(
        " qwen3:4b ", lambda s, c, t: meldungen.append((s, c, t)), opener=_opener(zeilen, gesehen)
    )
    assert meldungen == [
        ("pulling manifest", 0, 0),
        ("pulling abc", 250, 1000),
        ("success", 0, 0),
        ("als text", 0, 0),
    ]
    assert gesehen["body"] == {"model": "qwen3:4b", "stream": True}
    assert gesehen["url"].endswith("/api/pull")


def test_pull_model_ohne_fortschrittsfunktion_und_ohne_namen():
    ollama_service.pull_model("x", opener=_opener([b'{"status": "success"}\n']))
    with pytest.raises(ollama_service.OllamaError, match="Modellnamen"):
        ollama_service.pull_model("   ")


def test_pull_model_fehlermeldung_von_ollama():
    with pytest.raises(ollama_service.OllamaError, match="file does not exist"):
        ollama_service.pull_model("gibtsnicht", opener=_opener([b'{"error": "file does not exist"}\n']))


def test_pull_model_netzwerkfehler_werden_lesbar_gemeldet():
    def nicht_erreichbar(request, timeout=None):
        raise urllib.error.URLError("Verbindung verweigert")

    with pytest.raises(ollama_service.OllamaError, match="nicht erreichbar"):
        ollama_service.pull_model("qwen3:8b", opener=nicht_erreichbar)

    def abgebrochen(request, timeout=None):
        raise ConnectionResetError("zurueckgesetzt")

    with pytest.raises(ollama_service.OllamaError, match="unterbrochen"):
        ollama_service.pull_model("qwen3:8b", opener=abgebrochen)

    import io

    def http_fehler(request, timeout=None):
        raise urllib.error.HTTPError("u", 500, "Fehler", {}, io.BytesIO(b"kaputt"))

    with pytest.raises(ollama_service.OllamaError, match="HTTP 500"):
        ollama_service.pull_model("qwen3:8b", opener=http_fehler)


def test_modell_fehlt_nur_wenn_ollama_erreichbar_ist(monkeypatch):
    def unerreichbar(base_url=ollama_service.OLLAMA_BASE_URL, timeout=5):
        raise ollama_service.OllamaError("weg")

    monkeypatch.setattr(ollama_service, "list_models", unerreichbar)
    assert ollama_service.modell_fehlt("qwen3:8b") is False  # anderer Fehler, nicht "Modell fehlt"

    monkeypatch.setattr(ollama_service, "list_models", lambda base_url=ollama_service.OLLAMA_BASE_URL, timeout=5: ["qwen3:4b"])
    assert ollama_service.modell_fehlt("qwen3:8b") is True
    assert ollama_service.modell_fehlt("qwen3:4b") is False


# --------------------------------------------------------------------------
# Einbettungen und Chat
# --------------------------------------------------------------------------
class _JsonAntwort:
    def __init__(self, daten):
        self._daten = json.dumps(daten).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._daten


def test_embedding_modelle_sind_in_der_optionsliste_auffindbar():
    ids = [o.id for o in ollama_service.OLLAMA_EMBEDDING_MODELLE]
    assert ids[0] == "bge-m3" and len(set(ids)) == len(ids)
    assert ollama_service.get_modell_option("nomic-embed-text") is not None


def test_embed_liefert_vektoren_und_prueft_die_anzahl():
    gesehen = {}

    def oeffnen(request, timeout=None):
        gesehen["body"] = json.loads(request.data.decode("utf-8"))
        gesehen["url"] = request.full_url
        return _JsonAntwort({"embeddings": [[1, 2], [3, 4]]})

    assert ollama_service.embed("bge-m3", ["a", "b"], opener=oeffnen) == [[1.0, 2.0], [3.0, 4.0]]
    assert gesehen["url"].endswith("/api/embed") and gesehen["body"] == {"model": "bge-m3", "input": ["a", "b"]}
    assert ollama_service.embed("bge-m3", []) == []
    with pytest.raises(ollama_service.OllamaError, match="Einbettungsmodell"):
        ollama_service.embed("x", ["a"], opener=lambda r, timeout=None: _JsonAntwort({"embeddings": []}))
    with pytest.raises(ollama_service.OllamaError, match="Einbettungsmodell"):
        ollama_service.embed("x", ["a"], opener=lambda r, timeout=None: _JsonAntwort([1]))


def test_embed_fehler_werden_lesbar_gemeldet():
    def nicht_erreichbar(request, timeout=None):
        raise urllib.error.URLError("weg")

    with pytest.raises(ollama_service.OllamaError, match="nicht erreichbar"):
        ollama_service.embed("m", ["a"], opener=nicht_erreichbar)

    class _Kaputt(_JsonAntwort):
        def read(self):
            return b"kein json"

    with pytest.raises(ollama_service.OllamaError, match="gueltiges JSON"):
        ollama_service.embed("m", ["a"], opener=lambda r, timeout=None: _Kaputt({}))


def test_chat_stream_sammelt_stuecke_und_meldet_sie_sofort():
    zeilen = [
        b'{"message": {"content": "Hal"}, "done": false}\n',
        b"\n",
        b"kein json\n",
        b'["x"]\n',
        b'{"message": {"content": "lo"}, "done": false}\n',
        b'{"message": {"content": ""}, "done": true}\n',
        b'{"message": {"content": "nach dem Ende"}}\n',
    ]
    gesehen, stuecke = {}, []

    def oeffnen(request, timeout=None):
        gesehen["body"] = json.loads(request.data.decode("utf-8"))
        return _PullAntwort(zeilen)

    antwort = ollama_service.chat_stream([{"role": "user", "content": "x"}], "qwen3:8b", stuecke.append, opener=oeffnen)
    assert antwort == "Hallo" and stuecke == ["Hal", "lo"]
    assert gesehen["body"]["stream"] is True and gesehen["body"]["options"]["num_ctx"] >= 4096


def test_chat_stream_fehler():
    with pytest.raises(ollama_service.OllamaError, match="model not found"):
        ollama_service.chat_stream([], "m", opener=lambda r, timeout=None: _PullAntwort([b'{"error": "model not found"}\n']))

    def abgebrochen(request, timeout=None):
        raise ConnectionResetError("weg")

    with pytest.raises(ollama_service.OllamaError, match="unterbrochen"):
        ollama_service.chat_stream([], "m", opener=abgebrochen)
    # ohne Rueckruf und mit Text statt Bytes
    assert ollama_service.chat_stream([], "m", opener=lambda r, timeout=None: _PullAntwort(['{"message": {"content": "a"}}\n'])) == "a"


# --------------------------------------------------------------------------
# find_ollama_executable: Installationsorte unter Windows
# --------------------------------------------------------------------------
def _ohne_path(monkeypatch):
    monkeypatch.setattr(ollama_service.shutil, "which", lambda name: None)


def test_find_ollama_executable_nimmt_den_path(monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"
    monkeypatch.setattr(ollama_service.shutil, "which", lambda name: str(exe) if name == "ollama" else None)
    assert ollama_service.find_ollama_executable() == exe


def test_find_ollama_executable_findet_installation_ausserhalb_des_path(monkeypatch, tmp_path):
    # Direkt nach der Installation kennt der laufende Prozess den neuen PATH noch nicht.
    _ohne_path(monkeypatch)
    ziel = tmp_path / "Programs" / "Ollama"
    ziel.mkdir(parents=True)
    (ziel / "ollama.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    assert ollama_service.find_ollama_executable() == ziel / "ollama.exe"


def test_find_ollama_executable_ohne_fund(monkeypatch, tmp_path):
    _ohne_path(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    assert ollama_service.find_ollama_executable() is None
