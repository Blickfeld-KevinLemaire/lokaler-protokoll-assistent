"""Einstellungen, Schluessel, Vorlagen, Geraete, Chat, Ollama und der Startbaustein der Programmschnittstelle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.api import __main__ as start
from protokoll_assistent.api import routen_chat, routen_ollama
from protokoll_assistent.api.sicherheit import ROLLE_DESKTOP, ROLLE_SERVER, UMGEBUNG_SCHLUESSEL
from protokoll_assistent.services import chat_service, ollama_service, secret_store
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben
from protokoll_assistent.tests.api_hilfen import Umgebung, app_bauen, eigene_konfiguration
from protokoll_assistent.utils import app_config


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    return app_bauen(tmp_path)


# ---------------------------------------------------------------- Einstellungen
def test_einstellungen_lesen_und_aendern(umgebung: Umgebung) -> None:
    client = umgebung.client
    gelesen = client.get("/api/einstellungen").json()
    assert "server_zugaenge" not in gelesen and "geraete_empfang_geraete" not in gelesen
    assert client.patch("/api/einstellungen", json={"gibtsnicht": 1}).status_code == 400
    assert client.patch("/api/einstellungen", json={"server_zugaenge": []}).status_code == 400
    aufgerufen: list[dict[str, Any]] = []
    umgebung.dienste.nach_einstellungen.append(aufgerufen.append)
    neu = client.patch("/api/einstellungen", json={"sprache": "en", "ausgabeordner": str(umgebung.tmp / "neu")}).json()
    assert neu["sprache"] == "en" and aufgerufen and aufgerufen[0]["sprache"] == "en"
    assert app_config.load_config()["sprache"] == "en"


def test_schluessel_nur_als_ja_nein(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    client = umgebung.client
    assert client.get("/api/einstellungen/schluessel").json() == {"transkription": False, "nachbearbeitung": False, "chatbot": False}
    assert client.put("/api/einstellungen/schluessel/gibtsnicht", json={"wert": "x"}).status_code == 404
    antwort = client.put("/api/einstellungen/schluessel/chatbot", json={"wert": "geheim", "merken": True}).json()
    assert antwort == {"vorhanden": True, "gemerkt": False}  # kein Schluesselspeicher im Test: nur fuer die Sitzung
    assert "geheim" not in client.get("/api/einstellungen/schluessel").text
    assert client.delete("/api/einstellungen/schluessel/chatbot").json() == {"vorhanden": False}
    assert client.delete("/api/einstellungen/schluessel/gibtsnicht").status_code == 404
    gespeichert: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "save_api_key", lambda n, w: gespeichert.update({n: w}))
    monkeypatch.setattr(secret_store, "load_api_key", lambda n: gespeichert.get(n))
    monkeypatch.setattr(secret_store, "delete_api_key", lambda n: gespeichert.pop(n, None))
    assert client.put("/api/einstellungen/schluessel/transkription", json={"wert": "k", "merken": True}).json()["gemerkt"]
    assert client.delete("/api/einstellungen/schluessel/transkription").json() == {"vorhanden": False}


def test_anbieter_vorlagen_und_systemprompt(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from protokoll_assistent.utils import systemprompt_vorlagen

    client = umgebung.client
    anbieter = client.get("/api/einstellungen/anbieter").json()
    assert anbieter and {"id", "name", "chat", "transkription"} <= set(anbieter[0])
    monkeypatch.setattr(systemprompt_vorlagen, "get_systemprompt_vorlagen_dir", lambda: tmp_path / "vorlagen")
    (tmp_path / "vorlagen").mkdir()
    assert client.put("/api/einstellungen/vorlagen/Kurz", json={"text": "Fasse kurz zusammen."}).json() == {"gespeichert": True}
    assert client.put("/api/einstellungen/vorlagen/A%2FB", json={"text": "x"}).status_code in (400, 404)
    vorlagen = client.get("/api/einstellungen/vorlagen").json()
    assert {"name": "Kurz", "text": "Fasse kurz zusammen.", "eigene": True} in vorlagen
    assert client.get("/api/einstellungen/systemprompt").json() == {"text": ""}
    assert client.put("/api/einstellungen/systemprompt", json={"text": "Bitte knapp."}).json() == {"gespeichert": True}
    assert client.get("/api/einstellungen/systemprompt").json() == {"text": "Bitte knapp."}


# ---------------------------------------------------------------- Geraete
def test_geraete_anlegen_zeigt_token_einmal(umgebung: Umgebung) -> None:
    client = umgebung.client
    assert client.post("/api/geraete", json={"name": "mit/strich"}).status_code == 400
    neu = client.post("/api/geraete", json={"name": "Raum-1"}).json()
    assert neu["token"] and neu["token"] in neu["konfiguration"]
    assert client.post("/api/geraete", json={"name": "raum-1"}).status_code == 409
    assert client.post("/api/geraete", json={"name": "Raum-2", "besitzer": "anna"}).status_code == 400  # keine Nutzer
    stand = client.get("/api/geraete").json()
    assert [g["name"] for g in stand["geraete"]] == ["Raum-1"] and neu["token"] not in json.dumps(stand)
    assert "token_sha256" not in json.dumps(stand)
    assert client.delete("/api/geraete/Raum-1").json() == {"entfernt": True}
    assert client.delete("/api/geraete/Raum-1").status_code == 404


def test_ohne_geraeteautomatik(umgebung: Umgebung) -> None:
    umgebung.dienste.automatik = None
    assert umgebung.client.get("/api/geraete").status_code == 404
    assert umgebung.client.get("/api/zustand").json()["empfang"] is None


# ---------------------------------------------------------------- Chat
def _chat_vorbereiten(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    transkript_json_schreiben(umgebung.tmp / "aus" / "m_lokal_transkript_20260101_100000.json")
    aufrufe: list[Any] = []

    def beantworte(frage: str, dokumente: list[Any], verlauf: list[Any], *args: Any, on_status: Any = None, on_token: Any = None, **kw: Any) -> tuple[str, list[str]]:
        aufrufe.append((frage, [d.titel for d in dokumente], verlauf))
        on_status("Suche")
        on_token("Hal")
        on_token("lo")
        return "Hallo", ["Transkript m"]

    monkeypatch.setattr(chat_service, "beantworte", beantworte)
    monkeypatch.setattr(chat_service, "funktionen_aus_einstellungen", lambda e: (None, None))
    return aufrufe


def test_chat_strom_und_verlauf(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    aufrufe = _chat_vorbereiten(umgebung, monkeypatch)
    client = umgebung.client
    antwort = client.post("/api/chat", json={"frage": "Was wurde beschlossen?"})
    assert antwort.status_code == 200 and "event: token" in antwort.text and "event: fertig" in antwort.text
    fertig = json.loads(antwort.text.split("event: fertig\ndata: ")[1].split("\n")[0])
    assert fertig["antwort"] == "Hallo"
    verlaeufe = client.get("/api/chat/verlaeufe").json()
    assert len(verlaeufe) == 1 and verlaeufe[0]["fragen"] == 1
    kennung = fertig["verlauf_id"]
    zweite = client.post("/api/chat", json={"frage": "Und wer?", "verlauf_id": kennung})
    assert "event: fertig" in zweite.text
    assert aufrufe[1][2][0]["role"] == "user"  # der bisherige Verlauf geht mit
    assert len(client.get(f"/api/chat/verlaeufe/{kennung}").json()["nachrichten"]) == 4
    assert client.post("/api/chat", json={"frage": "x", "verlauf_id": "20990101_000000"}).status_code == 404
    assert client.delete(f"/api/chat/verlaeufe/{kennung}").json() == {"geloescht": True}
    assert client.get(f"/api/chat/verlaeufe/{kennung}").status_code == 404


def test_chat_fehler_ohne_unterlagen_und_unerwartet(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    antwort = umgebung.client.post("/api/chat", json={"frage": "Hallo?"})
    assert "event: fehler" in antwort.text and "noch keine" in antwort.text
    _chat_vorbereiten(umgebung, monkeypatch)

    def kaputt(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("weg")

    monkeypatch.setattr(chat_service, "beantworte", kaputt)
    assert "Unerwarteter Fehler: weg" in umgebung.client.post("/api/chat", json={"frage": "x"}).text


def test_chat_einstellungen_api(umgebung: Umgebung) -> None:
    app_config.update_config(chatbot_modus="api", chatbot_api_modell="m", chatbot_api_endpunkt="https://x.example/v1/chat/completions")
    umgebung.steuerung.schluessel.fuer_sitzung("transkription", "k")
    einstellungen = routen_chat.chat_einstellungen(umgebung.dienste)
    assert (einstellungen.modus, einstellungen.api_schluessel, einstellungen.chat_modell) == ("api", "k", "m")
    app_config.update_config(chatbot_modus="lokal")
    assert routen_chat.chat_einstellungen(umgebung.dienste).modus == "lokal"


# ---------------------------------------------------------------- Ollama
def test_ollama_modelle_und_laden(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_service, "is_service_running", lambda timeout=3: True)
    monkeypatch.setattr(ollama_service, "list_models", lambda timeout=5: ["qwen3.5:4b"])
    stand = umgebung.client.get("/api/ollama/modelle").json()
    assert stand["laeuft"] and stand["installiert"] == ["qwen3.5:4b"] and stand["empfohlen"]

    def scheitert(timeout: float = 5) -> list[str]:
        raise ollama_service.OllamaError("x")

    monkeypatch.setattr(routen_ollama.ollama_service, "list_models", scheitert)
    assert umgebung.client.get("/api/ollama/modelle").json()["installiert"] == []

    def ziehen(name: str, progress_cb: Any = None, **kw: Any) -> None:
        progress_cb("lade", 50, 100)
        progress_cb("pruefe", 0, 0)

    monkeypatch.setattr(ollama_service, "pull_model", ziehen)
    auftrag = umgebung.client.post("/api/ollama/laden", json={"modell": " qwen3.5:4b "}).json()
    assert auftrag["art"] == "modell_laden" and auftrag["titel"] == "qwen3.5:4b"
    umgebung.auftraege_ausfuehren()
    assert umgebung.steuerung.auftraege.hole(auftrag["id"]).status.value == "fertig"  # type: ignore[union-attr]


# ---------------------------------------------------------------- Start
def test_desktop_schluessel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    assert start.desktop_schluessel(False, 1234, {UMGEBUNG_SCHLUESSEL: " k "}) == "k"
    with pytest.raises(SystemExit, match="fehlt"):
        start.desktop_schluessel(False, 1234, {})
    erzeugt = start.desktop_schluessel(True, 1234, {})
    datei = json.loads(start.zugang_datei().read_text(encoding="utf-8"))
    assert datei == {"port": 1234, "schluessel": erzeugt}


def test_zugang_und_nutzer_anlegen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    assert start.main(["zugang-anlegen", "mit/strich"]) == 2
    assert start.main(["zugang-anlegen", "Laptop"]) == 0
    schluessel = capsys.readouterr().out.strip().splitlines()[-1]
    eintrag = app_config.load_config()["server_zugaenge"][0]
    assert eintrag["name"] == "Laptop" and schluessel not in json.dumps(eintrag)
    assert start.main(["nutzer-anlegen", "chef", "--admin"]) == 0
    assert "Admin" in capsys.readouterr().out
    assert start.main(["nutzer-anlegen", "chef"]) == 2
    assert start.dienste_erstellen(ROLLE_SERVER, None, mehrbenutzer=True).nutzer is not None


def test_openapi_ausgabe_ist_utf8(capfdbinary: pytest.CaptureFixture[bytes]) -> None:
    assert start.main(["openapi"]) == 0
    beschreibung = json.loads(capfdbinary.readouterr().out.decode("utf-8"))
    assert "/api/auftraege/transkription" in beschreibung["paths"]


def test_eingecheckte_schnittstellenbeschreibung_ist_aktuell() -> None:
    """``oberflaeche/openapi.json`` ist der Vertrag mit der Oberflaeche. Passt er nicht zum Code, neu erzeugen:
    ``uv run python -m protokoll_assistent.api openapi > oberflaeche/openapi.json``."""
    datei = Path(__file__).resolve().parents[2] / "oberflaeche" / "openapi.json"
    app = start.app_erstellen(start.dienste_erstellen(ROLLE_DESKTOP, "x"))
    assert json.loads(datei.read_text(encoding="utf-8")) == json.loads(start.openapi_text(app.openapi()))


def test_socket_binden_und_belegter_port() -> None:
    sock = start.socket_binden("127.0.0.1", 0)
    try:
        port = sock.getsockname()[1]
        assert port > 0
        with pytest.raises(OSError):
            start.socket_binden("127.0.0.1", port)
    finally:
        sock.close()


def test_port_datei_wird_atomar_geschrieben(tmp_path: Path) -> None:
    ziel = tmp_path / "unter" / "port.json"
    start.port_datei_schreiben(ziel, {"port": 1, "pid": 2})
    assert json.loads(ziel.read_text(encoding="utf-8")) == {"port": 1, "pid": 2}
    assert list(ziel.parent.glob("*.tmp")) == []


def test_eltern_wache_bemerkt_beendeten_prozess() -> None:
    kurz = subprocess.run([sys.executable, "-c", "pass"], check=True)
    assert kurz.returncode == 0
    beendet = threading.Event()
    # Eine PID, die es nicht (mehr) gibt: Die Wache meldet sofort das Ende.
    pid = 2**22 - 3 if os.name == "nt" else os.getppid() + 999_999
    faden = start.eltern_wache(pid, beendet.set)
    assert beendet.wait(5)
    faden.join(1)


def test_oberflaeche_ordner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    monkeypatch.setenv("VERMERK_OBERFLAECHE", str(tmp_path))
    assert start.oberflaeche_ordner() == tmp_path


# ---------------------------------------------------------------- Wuensche der Oberflaeche
def test_anmeldung_oeffentlich_und_zustand_mit_uhr(umgebung: Umgebung) -> None:
    client = umgebung.client
    client.headers.pop("Authorization")
    assert client.get("/api/anmeldung").json() == {"mehrbenutzer": False}
    client.headers["Authorization"] = f"Bearer {start.UMGEBUNG_SCHLUESSEL}"  # falsch: Name statt Wert
    assert client.get("/api/zustand").status_code == 401


def test_zustand_hat_die_uhr_des_dienstes(umgebung: Umgebung) -> None:
    import time

    jetzt = umgebung.client.get("/api/zustand").json()["jetzt"]
    assert abs(jetzt - time.time()) < 60


def test_neustart_auf_wunsch(umgebung: Umgebung) -> None:
    assert umgebung.client.post("/api/system/neustart").status_code == 501
    gerufen: list[bool] = []
    umgebung.dienste.neustart_anfordern = lambda: gerufen.append(True)
    assert umgebung.client.post("/api/system/neustart").json() == {"neustart": True}
    assert gerufen == [True]


def test_exporte_lassen_sich_herunterladen(umgebung: Umgebung) -> None:
    antwort = umgebung.client.post("/api/auftraege/transkription", json={"quelle": str(umgebung.audio())})
    assert antwort.status_code == 201
    umgebung.auftraege_ausfuehren()
    kennung = umgebung.client.get("/api/besprechungen").json()[0]["id"]
    export = umgebung.client.post(f"/api/besprechungen/{kennung}/export", json={"inhalt": "transkript", "formate": ["md", "txt"]}).json()
    namen = [d["name"] for d in export["dateien"]]
    dateien = {d["name"] for d in umgebung.client.get(f"/api/besprechungen/{kennung}").json()["dateien"]}
    assert set(namen) <= dateien
    assert umgebung.client.get(f"/api/besprechungen/{kennung}/dateien/{namen[0]}").status_code == 200


def test_modell_laden_meldet_platz(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_service, "pull_model", lambda name, progress_cb=None, **kw: None)
    assert umgebung.client.post("/api/ollama/laden", json={"modell": "m"}).json()["platz"] == 0
    assert umgebung.client.get("/api/einstellungen/anbieter").json()[0].keys() >= {"diarisierung_anbieter"}
