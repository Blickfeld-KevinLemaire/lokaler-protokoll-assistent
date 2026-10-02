import io
import json
import urllib.error

import pytest

from protokoll_assistent.services import api_chat_service as api


class _Antwort:
    def __init__(self, daten):
        self._daten = daten if isinstance(daten, bytes) else json.dumps(daten).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._daten


def _opener(daten, gesehen=None):
    def oeffnen(request, timeout=None):
        if gesehen is not None:
            gesehen["url"] = request.full_url
            gesehen["auth"] = request.get_header("Authorization")
            gesehen["body"] = json.loads(request.data.decode("utf-8"))
        return _Antwort(daten)

    return oeffnen


def test_chat_liefert_den_antworttext():
    gesehen = {}
    antwort = api.chat(
        [{"role": "user", "content": "hi"}],
        "m",
        endpoint_url="https://x/chat",
        api_key="geheim",
        opener=_opener({"choices": [{"message": {"content": "Hallo"}}]}, gesehen),
    )
    assert antwort == "Hallo"
    assert gesehen["auth"] == "Bearer geheim" and gesehen["body"]["model"] == "m"


def test_chat_fehlerfaelle():
    kwargs = {"endpoint_url": "https://x/chat", "api_key": "k"}
    with pytest.raises(api.ApiChatError, match="Unerwartete Antwort"):
        api.chat([], "m", opener=_opener({"choices": []}), **kwargs)
    with pytest.raises(api.ApiChatError, match="meldet einen Fehler"):
        api.chat([], "m", opener=_opener({"error": "kaputt"}), **kwargs)
    with pytest.raises(api.ApiChatError, match="kein JSON-Objekt"):
        api.chat([], "m", opener=_opener([1]), **kwargs)
    with pytest.raises(api.ApiChatError, match="Unlesbare"):
        api.chat([], "m", opener=_opener(b"kein json"), **kwargs)

    def http(request, timeout=None):
        raise urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b"Schluessel falsch"))

    with pytest.raises(api.ApiChatError, match="HTTP 401"):
        api.chat([], "m", opener=http, **kwargs)

    def url(request, timeout=None):
        raise urllib.error.URLError("weg")

    with pytest.raises(api.ApiChatError, match="nicht erreichbar"):
        api.chat([], "m", opener=url, **kwargs)

    def zeit(request, timeout=None):
        raise TimeoutError()

    with pytest.raises(api.ApiChatError, match="Zeitlimit"):
        api.chat([], "m", opener=zeit, **kwargs)


def test_embed_sortiert_nach_index_und_prueft_anzahl():
    daten = {"data": [{"index": 1, "embedding": [3, 4]}, {"index": 0, "embedding": [1, 2]}]}
    kwargs = {"endpoint_url": "https://x/emb", "api_key": "k"}
    assert api.embed(["a", "b"], "m", opener=_opener(daten), **kwargs) == [[1.0, 2.0], [3.0, 4.0]]
    assert api.embed([], "m", **kwargs) == []
    with pytest.raises(api.ApiChatError, match="2 Einbettungen fuer 1"):
        api.embed(["a"], "m", opener=_opener(daten), **kwargs)
    with pytest.raises(api.ApiChatError, match="Unerwartete Antwort"):
        api.embed(["a"], "m", opener=_opener({"daten": 1}), **kwargs)
