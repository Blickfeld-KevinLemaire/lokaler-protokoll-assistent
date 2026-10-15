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


def test_generate_text_liefert_freitext_ohne_json_format(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"response": "## Termine\n- 12.10. Abgabe"})

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", fake_urlopen)
    result = ollama_service.generate_text("Frage", "System", model="qwen3:8b")
    assert result == "## Termine\n- 12.10. Abgabe"
    assert "format" not in captured["body"]
    assert captured["body"]["system"] == "System"
    assert captured["body"]["options"]["temperature"] == 0.0
    assert captured["body"]["stream"] is False


def test_generate_text_raises_ollama_error_on_http_error(monkeypatch):
    def raise_http_error(request, timeout=None):
        raise urllib.error.HTTPError("url", 500, "Serverfehler", {}, None)

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_text("Frage", "System")


def test_generate_text_meldet_abgeschnittene_antwort(monkeypatch):
    """Erreicht das Modell die Laengen- oder Kontextgrenze, meldet Ollama
    'done_reason: length'. Der Text ist dann unvollstaendig und darf nicht als
    Ergebnis (und damit als Zwischenstand) durchgehen."""
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(
            {"response": "## Termine\n- 12.10. Abg", "done": True, "done_reason": "length"}
        ),
    )
    with pytest.raises(ollama_service.OllamaError, match="abgeschnitten"):
        ollama_service.generate_text("Frage", "System")
    with pytest.raises(ollama_service.OllamaError, match="abgeschnitten"):
        ollama_service.generate_json("Frage", "System")


def test_generate_text_nimmt_vollstaendige_antwort_an(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"response": "Fertig.", "done": True, "done_reason": "stop"}),
    )
    assert ollama_service.generate_text("Frage", "System") == "Fertig."


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
    assert captured["body"]["think"] is False  # Qwen3.5 versteht '/no_think' nicht mehr
    # Ohne num_ctx gilt Ollamas Standard (4096) und lange Abschnitte werden still gekuerzt.
    assert captured["body"]["options"]["num_ctx"] == ollama_service.PROTOKOLL_KONTEXTSTUFEN[0]

    ollama_service.generate_json("x" * 40_000, "System")  # Gesamtprotokoll einer langen Besprechung
    assert captured["body"]["options"]["num_ctx"] == ollama_service.PROTOKOLL_NUM_CTX
    ollama_service.generate_json("Frage", "System", num_ctx=4096)  # ausdruecklich gesetzt gilt
    assert captured["body"]["options"]["num_ctx"] == 4096


def test_kontext_reicht_fuer_die_groesste_protokollstufe():
    """Stufe 3 bekommt bis zu MAX_KONTEXT_ZEICHEN Eingabe (gemessen gut 3 Zeichen
    je Token) und muss danach noch das ganze Protokoll schreiben koennen. Passt
    beides nicht in den Kontext, bricht die Antwort mitten im JSON ab -- genau so
    ist es mit 16384 Tokens bei einer Stunde Material passiert."""
    from protokoll_assistent.services import protocol_service

    systemprompt = "s" * 2_000
    eingabe = "e" * protocol_service.MAX_KONTEXT_ZEICHEN
    bedarf = (len(systemprompt) + len(eingabe)) / 3 + ollama_service.PROTOKOLL_ANTWORT_TOKENS
    assert bedarf <= ollama_service.kontext_fuer_protokoll(systemprompt, eingabe) == ollama_service.PROTOKOLL_NUM_CTX
    # Ein 10-Minuten-Abschnitt (gut 12.000 Zeichen) kommt mit der kleinen Stufe aus.
    assert ollama_service.kontext_fuer_protokoll(systemprompt, "a" * 12_000) == ollama_service.PROTOKOLL_KONTEXTSTUFEN[0]


def test_volle_anfrage_der_stufen_2_und_3_passt_in_den_kontext():
    """Nicht nur die Teilergebnisse, die ganze Anfrage zaehlt: Rahmentext und
    Trenner je Teilergebnis kommen dazu. Bei vollem Zeichenbudget (die
    Verdichtung laesst nie mehr zu) muss das samt Antwort in den Kontext passen."""
    from protokoll_assistent.services import protocol_service

    systemprompt = "s" * 2_000
    for anzahl in (2, 4, 40):
        teile = ["t" * (protocol_service.MAX_KONTEXT_ZEICHEN // anzahl)] * anzahl
        for prompt in (protocol_service.build_stage2_prompt(teile), protocol_service.build_stage3_prompt(teile)):
            bedarf = (len(systemprompt) + len(prompt)) / ollama_service.ZEICHEN_JE_TOKEN
            assert bedarf + ollama_service.PROTOKOLL_ANTWORT_TOKENS <= ollama_service.PROTOKOLL_NUM_CTX


def test_ensure_ollama_or_offer_installer_returns_true_when_already_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "find_ollama_executable", object)
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
    # LFM2.5 steht als leichtere Alternative direkt hinter dem Standard.
    assert ids[1] == "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"
    assert len(ids) == len(set(ids)) >= 5
    # Quantisierung ausdruecklich festgelegt (LFM schreibt sie gross: Q4_K_M).
    assert all("q4" in modell_id.lower() for modell_id in ids)
    assert ollama_service.get_modell_option("qwen3.5:9b-q4_K_M").groesse_gb < 7
    assert ollama_service.get_modell_option("gibt-es-nicht") is None


def test_lfm_option_nutzt_den_chat_endpunkt():
    option = ollama_service.get_modell_option("hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M")
    assert option is not None and option.chat_endpunkt is True
    assert option.groesse_gb == 1.6
    # Die uebrigen Modelle laufen weiter ueber '/api/generate'.
    assert ollama_service.get_modell_option(ollama_service.DEFAULT_MODEL).chat_endpunkt is False


def test_generate_text_nutzt_api_chat_fuer_chat_modelle(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        # '/api/chat' liefert Denkphase und Antwort getrennt; nur 'content' zaehlt.
        return _FakeResponse({"message": {"thinking": "erst nachdenken ...", "content": "## Protokoll\n- fertig"}})

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", fake_urlopen)
    ergebnis = ollama_service.generate_text("Frage", "System", model="hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M")
    assert ergebnis == "## Protokoll\n- fertig"  # das 'thinking' wird verworfen
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Frage"},
    ]
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False
    assert captured["body"]["options"]["temperature"] == 0.0


def test_generate_text_chat_modell_meldet_abgeschnittene_antwort(monkeypatch):
    monkeypatch.setattr(
        ollama_service.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(
            {"message": {"content": "## Protokoll\n- ha"}, "done": True, "done_reason": "length"}
        ),
    )
    with pytest.raises(ollama_service.OllamaError, match="abgeschnitten"):
        ollama_service.generate_text("Frage", "System", model="hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M")


def test_generate_text_bleibt_fuer_qwen_bei_api_generate(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"response": "Fertig."})

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", fake_urlopen)
    assert ollama_service.generate_text("Frage", "System", model=ollama_service.DEFAULT_MODEL) == "Fertig."
    assert captured["url"].endswith("/api/generate")
    assert "messages" not in captured["body"] and captured["body"]["prompt"] == "Frage"


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
    assert gesehen["body"]["think"] is False


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


# --------------------------------------------------------------------------
# Dienst im Hintergrund halten
# --------------------------------------------------------------------------
class _Uhr:
    def __init__(self):
        self.jetzt = 1000.0

    def __call__(self) -> float:
        return self.jetzt

    def schlafen(self, sekunden: float) -> None:
        self.jetzt += sekunden


@pytest.fixture
def start_erlaubt(monkeypatch):
    monkeypatch.setattr(ollama_service, "AUTO_START", True)
    monkeypatch.setattr(ollama_service, "_letzter_startversuch", None)


def test_laeuft_der_dienst_wird_nichts_gestartet(start_erlaubt):
    gestartet = []
    assert ollama_service.dienst_starten(laeuft_fn=lambda *a: True, popen_fn=lambda *a, **k: gestartet.append(a))
    assert gestartet == []


def test_start_ist_in_tests_und_fuer_fremde_adressen_aus(monkeypatch):
    gestartet = []
    nie = lambda *a, **k: gestartet.append(a)  # noqa: E731
    kein_dienst = lambda *a: False  # noqa: E731
    assert not ollama_service.dienst_starten(laeuft_fn=kein_dienst, popen_fn=nie)  # AUTO_START ist aus (conftest)
    monkeypatch.setattr(ollama_service, "AUTO_START", True)
    assert not ollama_service.dienst_starten("http://ollama:11434", laeuft_fn=kein_dienst, popen_fn=nie)
    assert not ollama_service.dienst_starten("http://192.168.0.5:11434", laeuft_fn=kein_dienst, popen_fn=nie)
    assert gestartet == []
    assert ollama_service.ist_lokale_adresse("http://127.0.0.1:11434") and ollama_service.ist_lokale_adresse("http://localhost:11434")


def test_dienst_wird_unsichtbar_als_server_gestartet_und_abgewartet(start_erlaubt, tmp_path):
    uhr = _Uhr()
    aufrufe = []
    antworten = iter([False, False, False, False, True])  # vor der Sperre, in der Sperre, dann nach 2 s

    def starte(befehl, **kwargs):
        aufrufe.append((befehl, kwargs))

    programm = tmp_path / "ollama.exe"
    assert ollama_service.dienst_starten(
        ausfuehrbar_fn=lambda: programm,
        popen_fn=starte,
        laeuft_fn=lambda *a: next(antworten),
        schlafen_fn=uhr.schlafen,
        uhr_fn=uhr,
    )
    befehl, kwargs = aufrufe[0]
    assert befehl == [str(programm), "serve"]  # nur der Dienst, nicht die Oberflaeche
    assert kwargs["creationflags"] == (
        ollama_service.LOSGELOEST | ollama_service.NEUE_PROZESSGRUPPE | ollama_service.KEIN_FENSTER
    )
    assert uhr.jetzt > 1000.0


def test_antwortet_der_dienst_nie_wird_nach_der_wartezeit_aufgegeben(start_erlaubt, tmp_path):
    uhr = _Uhr()
    assert not ollama_service.dienst_starten(
        ausfuehrbar_fn=lambda: tmp_path / "ollama.exe",
        popen_fn=lambda *a, **k: None,
        laeuft_fn=lambda *a: False,
        schlafen_fn=uhr.schlafen,
        uhr_fn=uhr,
        warten=5.0,
    )
    assert 1005.0 <= uhr.jetzt < 1010.0


def test_nach_einem_fehlschlag_gibt_es_eine_pause_vor_dem_naechsten_start(start_erlaubt, tmp_path):
    uhr = _Uhr()
    gestartet = []
    argumente = {
        "ausfuehrbar_fn": lambda: tmp_path / "ollama.exe",
        "popen_fn": lambda *a, **k: gestartet.append(a),
        "laeuft_fn": lambda *a: False,
        "schlafen_fn": uhr.schlafen,
        "uhr_fn": uhr,
        "warten": 2.0,
    }
    assert not ollama_service.dienst_starten(**argumente)
    assert not ollama_service.dienst_starten(**argumente)  # zu bald: kein zweiter Start
    assert len(gestartet) == 1
    uhr.jetzt += ollama_service.START_PAUSE_SEKUNDEN
    assert not ollama_service.dienst_starten(**argumente)
    assert len(gestartet) == 2


def test_ohne_programm_oder_bei_startfehler_gibt_es_false(start_erlaubt, tmp_path):
    uhr = _Uhr()
    gemeinsam = {"laeuft_fn": lambda *a: False, "schlafen_fn": uhr.schlafen, "uhr_fn": uhr}
    assert not ollama_service.dienst_starten(ausfuehrbar_fn=lambda: None, popen_fn=pytest.fail, **gemeinsam)

    def verboten(*_a, **_k):
        raise PermissionError("AppLocker")

    uhr.jetzt += 100
    assert not ollama_service.dienst_starten(ausfuehrbar_fn=lambda: tmp_path / "ollama.exe", popen_fn=verboten, **gemeinsam)


def test_anfrage_startet_den_dienst_bei_verweigerter_verbindung_und_wiederholt_einmal(monkeypatch):
    versuche = []

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return b'{"response": "Hallo", "done_reason": "stop"}'

    def urlopen(request, timeout):
        versuche.append(request.full_url)
        if len(versuche) == 1:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "verweigert"))
        return Antwort()

    gestartet = []
    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ollama_service, "dienst_starten", lambda url, **k: gestartet.append(url) or True)
    assert ollama_service.generate_text("Frage", "System", model="m") == "Hallo"
    assert gestartet == ["http://127.0.0.1:11434"] and len(versuche) == 2


def test_anfrage_meldet_den_fehler_wenn_der_dienst_nicht_startet(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "verweigert"))

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ollama_service, "dienst_starten", lambda url, **k: False)
    with pytest.raises(ollama_service.OllamaError, match="nicht erreichbar"):
        ollama_service.generate_text("Frage", "System", model="m")


def test_andere_fehler_starten_den_dienst_nicht(monkeypatch):
    def timeout_fehler(request, timeout):
        raise urllib.error.URLError(TimeoutError("zu langsam"))

    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", timeout_fehler)
    monkeypatch.setattr(ollama_service, "dienst_starten", lambda *a, **k: pytest.fail("kein Start bei Zeitueberschreitung"))
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.generate_text("Frage", "System", model="m")


def test_mit_eigenem_oeffner_wird_nie_gestartet(monkeypatch):
    monkeypatch.setattr(ollama_service, "dienst_starten", lambda *a, **k: pytest.fail("Tests starten nichts"))

    def oeffner(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "verweigert"))

    with pytest.raises(ollama_service.OllamaError):
        ollama_service.embed("m", ["a"], opener=oeffner)
