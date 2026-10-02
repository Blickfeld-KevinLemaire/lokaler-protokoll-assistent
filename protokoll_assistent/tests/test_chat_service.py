import json
import os
import time
from pathlib import Path

import pytest

from protokoll_assistent.services import chat_service as cs


def _transkript(ordner: Path, name="sitzung", zeit="20260101_100000", segmente=None) -> Path:
    daten = {
        "sprecher_zuordnung": [{"sprecher_id": "SPEAKER_00", "anzeigename": "Anna"}],
        "segmente": segmente
        or [
            {"start_sekunden": 5.0, "sprecher_id": "SPEAKER_00", "sprecher": "Anna", "text": "Das Budget beträgt 5000 Euro."},
            {"start_sekunden": 70.0, "sprecher_id": "SPEAKER_00", "text": "Wir treffen uns am Freitag."},
            {"start_sekunden": 90.0, "sprecher_id": "SPEAKER_00", "text": "  "},
        ],
    }
    pfad = ordner / f"{name}_lokal_transkript_{zeit}.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


def _protokoll(ordner: Path, name="sitzung", zeit="20260101_110000") -> Path:
    pfad = ordner / f"{name}_protokoll_{zeit}.md"
    pfad.write_text("# Protokoll\n\nBeschluss: Budget freigegeben.\n", encoding="utf-8")
    return pfad


def test_finde_dokumente_nur_transkripte_und_zusammenfassungen_neueste_zuerst(tmp_path):
    a = _transkript(tmp_path, "alt")
    b = _protokoll(tmp_path, "neu")
    (tmp_path / "sitzung_protokoll_20260101_110000.json").write_text("{}", encoding="utf-8")  # JSON zaehlt nicht
    (tmp_path / "notizen.txt").write_text("x", encoding="utf-8")
    os.utime(a, (time.time() - 100, time.time() - 100))
    assert cs.finde_dokumente(tmp_path) == [b, a]
    assert cs.finde_dokumente(tmp_path / "gibt-es-nicht") == []


def test_lade_dokument_transkript_und_protokoll(tmp_path):
    t = cs.lade_dokument(_transkript(tmp_path))
    assert t.art == cs.ART_TRANSKRIPT
    assert t.text.splitlines() == ["[00:00:05.000] Anna: Das Budget beträgt 5000 Euro.", "[00:01:10.000] Anna: Wir treffen uns am Freitag."]
    p = cs.lade_dokument(_protokoll(tmp_path))
    assert p.art == cs.ART_PROTOKOLL and "Budget freigegeben" in p.text


def test_lade_dokument_fehlerfaelle(tmp_path):
    with pytest.raises(cs.ChatFehler, match="nicht gelesen"):
        cs.lade_dokument(tmp_path / "fehlt.json")
    kaputt = tmp_path / "a_lokal_transkript_1.json"
    kaputt.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(cs.ChatFehler, match="gueltiges Transkript"):
        cs.lade_dokument(kaputt)
    falsch = tmp_path / "b_lokal_transkript_1.json"
    falsch.write_text("[1]", encoding="utf-8")
    with pytest.raises(cs.ChatFehler, match="kein Transkript"):
        cs.lade_dokument(falsch)


def test_anzeigename():
    assert cs.anzeigename(Path("sitzung_lokal_transkript_20260101_103000.json")) == "Transkript - sitzung (01.01.2026 10:30)"
    assert cs.anzeigename(Path("sitzung_protokoll_20260101_110000.md")) == "Zusammenfassung - sitzung (01.01.2026 11:00)"
    assert cs.anzeigename(Path("x_protokoll_ohne.md")) == "Zusammenfassung - x"


def test_zerlege_bildet_abschnitte_mit_zeit_und_teilt_lange_zeilen():
    text = "\n".join(f"[00:0{i}:00.000] Anna: " + "wort " * 30 for i in range(5))
    dok = cs.Dokument(Path("a.json"), "a", cs.ART_TRANSKRIPT, text)
    abschnitte = cs.zerlege(dok, max_zeichen=400)
    assert len(abschnitte) >= 2
    assert abschnitte[0].zeit == "00:00:00"
    assert all(len(a.text) <= 400 + 10 for a in abschnitte)
    lang = cs.zerlege(cs.Dokument(Path("b.md"), "b", cs.ART_PROTOKOLL, "x" * 1000), max_zeichen=300)
    assert len(lang) == 4 and lang[0].zeit is None
    assert cs.zerlege(cs.Dokument(Path("c.md"), "c", cs.ART_PROTOKOLL, "\n \n"), 100) == []


class _Einbetter:
    """Bildet Texte auf einfache Vektoren ab: [Budget, Freitag, Rest]."""

    def __init__(self):
        self.aufrufe = 0

    def __call__(self, texte):
        self.aufrufe += 1
        return [[float("budget" in t.lower()), float("freitag" in t.lower()), 0.1] for t in texte]


def test_index_wird_zwischengespeichert_und_suche_findet_die_passende_stelle(tmp_path):
    dok = cs.lade_dokument(_transkript(tmp_path))
    einbetter = _Einbetter()
    cache = tmp_path / "cache"
    meldungen = []
    index = cs.baue_index([dok], einbetter, cache, "lokal:m", lambda titel, f, g: meldungen.append((titel, f, g)))
    assert einbetter.aufrufe == 1 and meldungen
    assert len(list(cache.glob("*.json"))) == 1

    cs.baue_index([dok], einbetter, cache, "lokal:m")  # aus dem Zwischenspeicher
    assert einbetter.aufrufe == 1
    cs.baue_index([dok], einbetter, cache, "lokal:anderes-modell")  # anderes Modell -> neu
    assert einbetter.aufrufe == 2

    treffer = cs.suche(index, [1.0, 0.0, 0.1], anzahl=1)
    assert "Budget" in treffer[0][1].text
    assert cs.suche(index, [1.0, 0.0], anzahl=3) == []  # andere Vektorlaenge wird uebersprungen


def test_kaputter_zwischenspeicher_wird_ersetzt(tmp_path):
    dok = cs.lade_dokument(_transkript(tmp_path))
    einbetter = _Einbetter()
    cache = tmp_path / "cache"
    cs.baue_index([dok], einbetter, cache, "k")
    for datei in cache.glob("*.json"):
        datei.write_text("{kaputt", encoding="utf-8")
    cs.baue_index([dok], einbetter, cache, "k")
    assert einbetter.aufrufe == 2


def test_nachrichten_enthalten_auszuege_verlauf_und_no_think_nur_fuer_qwen3():
    abschnitt = cs.Abschnitt("Transkript sitzung", "Das Budget beträgt 5000 Euro.", "00:00:05")
    verlauf = [{"role": "user", "content": f"f{i}"} for i in range(10)]
    nachrichten = cs.baue_nachrichten("Wie hoch ist das Budget?", [(0.9, abschnitt)], verlauf, "qwen3:8b")
    assert nachrichten[0]["role"] == "system" and "/no_think" in nachrichten[0]["content"]
    assert len(nachrichten) == 1 + cs.MAX_VERLAUF_NACHRICHTEN + 1
    assert "ab 00:00:05" in nachrichten[-1]["content"] and "Wie hoch ist das Budget?" in nachrichten[-1]["content"]
    ohne = cs.baue_nachrichten("f", [], [], "gemma3:4b")
    assert "/no_think" not in ohne[0]["content"] and "(keine)" in ohne[-1]["content"]


def test_bereinige_antwort_und_quellenliste():
    assert cs.bereinige_antwort("<think>\nhmm\n</think>\n Antwort ") == "Antwort"
    a1 = cs.Abschnitt("T1", "x", "00:00:05")
    a2 = cs.Abschnitt("T1", "y", "00:00:05")
    a3 = cs.Abschnitt("P", "z", None)
    assert cs.quellenliste([(1.0, a1), (0.9, a2), (0.8, a3)]) == ["T1 ab 00:00:05", "P"]


def test_beantworte_gesamter_ablauf(tmp_path):
    dok = cs.lade_dokument(_transkript(tmp_path))
    gesehen = {}

    def chat_fn(nachrichten, on_token):
        gesehen["nachrichten"] = nachrichten
        on_token("<think>x</think>Es sind ")
        on_token("5000 Euro.")
        return "<think>x</think>Es sind 5000 Euro."

    status, tokens = [], []
    antwort, quellen = cs.beantworte(
        "Wie hoch ist das Budget?", [dok], [], _Einbetter(), chat_fn, tmp_path / "c", "k", "qwen3:8b", status.append, tokens.append
    )
    assert antwort == "Es sind 5000 Euro."
    assert quellen and quellen[0].startswith("sitzung_lokal_transkript_20260101_100000")
    assert "Budget" in gesehen["nachrichten"][-1]["content"]
    assert any("Antwort wird erzeugt" in s for s in status) and tokens


def test_beantworte_fehlerfaelle(tmp_path):
    dok = cs.lade_dokument(_transkript(tmp_path))
    leeres_dok = cs.Dokument(tmp_path / "x.md", "x", cs.ART_PROTOKOLL, "")
    with pytest.raises(cs.ChatFehler, match="Frage"):
        cs.beantworte("  ", [dok], [], _Einbetter(), lambda n, t: "a", tmp_path / "c", "k")
    with pytest.raises(cs.ChatFehler, match="auswaehlen"):
        cs.beantworte("f", [], [], _Einbetter(), lambda n, t: "a", tmp_path / "c", "k")
    with pytest.raises(cs.ChatFehler, match="kein Text"):
        cs.beantworte("f", [leeres_dok], [], _Einbetter(), lambda n, t: "a", tmp_path / "c", "k")
    with pytest.raises(cs.ChatFehler, match="keine Antwort"):
        cs.beantworte("f", [dok], [], _Einbetter(), lambda n, t: "<think>nur denken</think>", tmp_path / "c", "k")


def test_funktionen_aus_einstellungen_lokal_und_api(monkeypatch):
    aufrufe = {}
    monkeypatch.setattr(cs.ollama_service, "embed", lambda modell, texte: aufrufe.setdefault("embed", (modell, texte)) and [[1.0]])
    monkeypatch.setattr(
        cs.ollama_service, "chat_stream", lambda n, m, on_token=None: aufrufe.setdefault("chat", (m, on_token)) and "ok"
    )
    lokal = cs.ChatEinstellungen("lokal", "qwen3:8b", "bge-m3")
    assert lokal.modell_kennung == "lokal:bge-m3"
    embed, chat = cs.funktionen_aus_einstellungen(lokal)
    assert embed(["a"]) == [[1.0]] and chat([], None) == "ok"
    assert aufrufe["embed"][0] == "bge-m3" and aufrufe["chat"][0] == "qwen3:8b"

    with pytest.raises(cs.ChatFehler, match="API-Schluessel"):
        cs.funktionen_aus_einstellungen(cs.ChatEinstellungen("api", "m", "e", "u", "v", ""))

    monkeypatch.setattr(cs.api_chat_service, "embed", lambda texte, modell, **k: [[2.0]])
    monkeypatch.setattr(cs.api_chat_service, "chat", lambda n, modell, **k: "api-antwort")
    api = cs.ChatEinstellungen("api", "m", "e", "https://x/chat", "https://x/emb", "geheim")
    embed, chat = cs.funktionen_aus_einstellungen(api)
    tokens = []
    assert embed(["a"]) == [[2.0]] and chat([], tokens.append) == "api-antwort" and tokens == ["api-antwort"]
