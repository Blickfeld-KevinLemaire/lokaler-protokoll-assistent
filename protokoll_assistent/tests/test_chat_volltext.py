"""Chatbot mit dem ganzen Text als Grundlage (``chat_service.beantworte_volltext``)."""

import pytest

from protokoll_assistent.services import chat_service as cs
from protokoll_assistent.tests.test_chat_service import LOKAL, _ergebnis, _ollama, _transkript

VOLLTEXT = cs.ChatEinstellungen("lokal", "qwen3:8b", "bge-m3", kontext=cs.KONTEXT_VOLLTEXT)


def _kein_embed(texte):
    raise AssertionError("Im Volltext-Modus darf nichts eingebettet werden.")


def _lang(tmp_path, zeilen, titel="x"):
    return cs.Dokument(tmp_path / f"{titel}.md", titel, cs.ART_PROTOKOLL, "\n".join(zeilen))


def test_mit_ueberlappung_stellt_das_ende_des_vorigen_abschnitts_voran():
    a = cs.Abschnitt("dok", "eins\nzwei\ndrei", "00:00:01")
    b = cs.Abschnitt("dok", "vier", "00:00:05")
    c = cs.Abschnitt("anderes", "fuenf", None)
    ergebnis = cs.mit_ueberlappung([a, b, c], zeichen=10)
    assert ergebnis[0] == a
    assert ergebnis[1].text == "zwei\ndrei\nvier" and ergebnis[1].zeit == "00:00:05"
    assert ergebnis[2] == c  # neues Dokument: nichts vom vorigen
    assert cs.mit_ueberlappung([a, b], zeichen=0) == [a, b]


def test_volltext_der_passt_geht_in_einem_stueck_an_das_modell(tmp_path):
    dok = cs.lade_dokument(_transkript(tmp_path))
    anfragen = []

    def chat_fn(nachrichten, on_token):
        anfragen.append(nachrichten)
        return "Zusammenfassung: Budget 5000 Euro, Treffen am Freitag."

    status = []
    antwort, quellen = cs.beantworte(
        "Fasse zusammen.",
        [dok],
        [{"role": "user", "content": "vorher"}],
        _kein_embed,
        chat_fn,
        tmp_path / "c",
        "k",
        on_status=status.append,
        kontext=cs.KONTEXT_VOLLTEXT,
    )
    assert len(anfragen) == 1
    assert anfragen[0][0]["content"] == cs.VOLLTEXT_SYSTEMPROMPT
    assert {"role": "user", "content": "vorher"} in anfragen[0]  # Verlauf bleibt
    inhalt = anfragen[0][-1]["content"]
    assert "Das Budget beträgt 5000 Euro." in inhalt and "Wir treffen uns am Freitag." in inhalt
    assert antwort.startswith("Zusammenfassung") and quellen == [dok.titel]
    assert status == ["Antwort wird erzeugt …"]


def test_zu_langer_volltext_wird_in_stuecken_gelesen_und_zusammengefasst(tmp_path):
    zeilen = [f"Zeile {i}: belangloses Gerede ueber das Wetter." for i in range(30)]
    zeilen[17] = "Zeile 17: Das Budget betraegt 5000 Euro."
    dok = _lang(tmp_path, zeilen, "lange_sitzung")
    notizanfragen, abschluss = [], []

    def chat_fn(nachrichten, on_token):
        if nachrichten[0]["content"] == cs.NOTIZ_SYSTEMPROMPT:
            notizanfragen.append(nachrichten[-1]["content"])
            return "- Budget: 5000 Euro" if "Budget" in nachrichten[-1]["content"] else "NICHTS."
        abschluss.append(nachrichten[-1]["content"])
        return "Das Budget betraegt 5000 Euro."

    status = []
    antwort, quellen = cs.beantworte_volltext(
        "Wie hoch ist das Budget?",
        [dok],
        [],
        chat_fn,
        on_status=status.append,
        max_zeichen=400,
        stueck_zeichen=300,
        ueberlappung=60,
    )
    stuecke = cs.mit_ueberlappung(cs.zerlege(dok, 300), 60)
    assert len(stuecke) > 2 and len(notizanfragen) == len(stuecke)
    assert all("Frage: Wie hoch ist das Budget?" in a for a in notizanfragen)
    assert len(abschluss) == 1
    assert "Notizen aus den Abschnitten" in abschluss[0] and "Budget: 5000 Euro" in abschluss[0]
    assert "NICHTS" not in abschluss[0]  # leere Notizen fliegen raus
    assert f"Abschnitt 1 von {len(stuecke)} wird gelesen …" in status
    assert antwort == "Das Budget betraegt 5000 Euro." and quellen == ["lange_sitzung"]


def test_ohne_passende_notizen_bekommt_das_modell_einen_klaren_hinweis(tmp_path):
    dok = _lang(tmp_path, [f"Zeile {i}" for i in range(50)])
    abschluss = []

    def chat_fn(nachrichten, on_token):
        if nachrichten[0]["content"] == cs.NOTIZ_SYSTEMPROMPT:
            return "NICHTS"
        abschluss.append(nachrichten[-1]["content"])
        return "Das steht nicht in den Unterlagen."

    cs.beantworte_volltext("Wer kommt?", [dok], [], chat_fn, max_zeichen=100, stueck_zeichen=80, ueberlappung=0)
    assert "In keinem Abschnitt stand etwas Passendes" in abschluss[0]


def test_zu_lange_notizen_werden_verdichtet(tmp_path):
    dok = _lang(tmp_path, [f"Zeile {i} " + "x" * 50 for i in range(40)])
    runden = {"verdichtet": 0}

    def chat_fn(nachrichten, on_token):
        if nachrichten[0]["content"] != cs.NOTIZ_SYSTEMPROMPT:
            return "fertig"
        if "Abschnitt (Notizen)" in nachrichten[-1]["content"]:
            runden["verdichtet"] += 1
            return "kurz"
        return "n" * 150  # jede Notiz lang

    status = []
    cs.beantworte_volltext(
        "Fasse zusammen.", [dok], [], chat_fn, on_status=status.append, max_zeichen=800, stueck_zeichen=200, ueberlappung=0
    )
    assert runden["verdichtet"] >= 1 and "Notizen werden verdichtet …" in status


def test_verdichtung_bricht_ab_wenn_das_modell_nicht_kuerzt(tmp_path):
    dok = _lang(tmp_path, [f"Zeile {i} " + "x" * 50 for i in range(40)])
    abschluss = []

    def chat_fn(nachrichten, on_token):
        if nachrichten[0]["content"] == cs.NOTIZ_SYSTEMPROMPT:
            return "n" * 300  # wird nie kuerzer
        abschluss.append(nachrichten[-1]["content"])
        return "fertig"

    antwort, _ = cs.beantworte_volltext("F?", [dok], [], chat_fn, max_zeichen=800, stueck_zeichen=200, ueberlappung=0)
    assert antwort == "fertig"
    assert "weitere Notizen aus Platzgruenden weggelassen" in abschluss[0]  # sichtbar gekuerzt statt endlos


def test_volltext_fehlerfaelle(tmp_path):
    with pytest.raises(cs.ChatFehler, match="kein Text"):
        cs.beantworte_volltext("f", [_lang(tmp_path, ["  "])], [], lambda n, t: "a")
    with pytest.raises(cs.ChatFehler, match="keine Antwort"):
        cs.beantworte_volltext("f", [_lang(tmp_path, ["Text"])], [], lambda n, t: "<think>nur denken</think>")


def test_volltext_braucht_kein_einbettungsmodell(monkeypatch):
    assert not VOLLTEXT.braucht_einbettung and LOKAL.braucht_einbettung
    _ollama(monkeypatch, ["qwen3:8b"])
    assert cs.fehlendes_modell(VOLLTEXT) is None
    _ollama(monkeypatch, [])
    assert cs.fehlendes_modell(VOLLTEXT) == "qwen3:8b"

    _ollama(monkeypatch, ["qwen3:8b"])
    ergebnis = _ergebnis(cs.systemcheck(VOLLTEXT, _kein_embed, lambda n, t: "OK"))
    assert "embedding_modell" not in ergebnis and "embedding_test" not in ergebnis
    assert all(c.ok for c in ergebnis.values())


def test_api_ohne_einbettungs_endpunkt_nur_im_volltext_modus():
    ohne_einbettung = cs.ChatEinstellungen("api", "m", "e", "https://x/chat", "", "schluessel", kontext=cs.KONTEXT_VOLLTEXT)
    cs.funktionen_aus_einstellungen(ohne_einbettung)  # kein Fehler
    ergebnis = _ergebnis(cs.systemcheck(ohne_einbettung, _kein_embed, lambda n, t: "OK"))
    assert "api_anbieter" not in ergebnis and ergebnis["chat_test"].ok
    with pytest.raises(cs.ChatFehler, match="kein Anbieter"):
        cs.funktionen_aus_einstellungen(cs.ChatEinstellungen("api", "m", "e", "https://x/chat", "", "schluessel"))


def test_angehaengtes_nichts_wird_von_echten_notizen_entfernt():
    """Qwen3.5 schrieb Notizen und danach noch "NICHTS" -- die Notizen zaehlen."""
    notiz = cs._notiz(lambda nachrichten, on_token: "- Thomas schreibt den Testplan\n\nNICHTS", "F", "A", "Text")
    assert notiz == "[A]\n- Thomas schreibt den Testplan"
    assert cs._notiz(lambda nachrichten, on_token: "NICHTS.", "F", "A", "Text") is None


def test_notizen_kommen_mit_dem_hinweis_dass_sie_sich_ergaenzen(tmp_path):
    anfragen = []

    def chat(nachrichten, on_token):
        anfragen.append(nachrichten)
        return "- Frist: 24. Oktober" if nachrichten[0]["content"] == cs.NOTIZ_SYSTEMPROMPT else "Bis 24. Oktober."

    dokument = _lang(tmp_path, ["Zeile mit Text"] * 30)
    cs.beantworte_volltext("Frist?", [dokument], [], chat, max_zeichen=100, stueck_zeichen=120, ueberlappung=10)
    assert cs.NOTIZEN_HINWEIS in anfragen[-1][-1]["content"]
