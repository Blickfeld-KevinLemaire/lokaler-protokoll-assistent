import json

import pytest

from protokoll_assistent.services import chat_verlauf_service as cv


def _nachrichten():
    return [
        {"role": "user", "content": "Frage?", "quellen": []},
        {"role": "assistant", "content": "Antwort.", "quellen": ["T ab 00:00:05"]},
    ]


def test_titel_wird_gekuerzt_und_einzeilig():
    assert cv.titel_aus_frage("  Wie\n hoch   ist es?  ") == "Wie hoch ist es?"
    lang = cv.titel_aus_frage("x" * 200)
    assert len(lang) == cv.MAX_TITEL and lang.endswith("…")
    assert cv.titel_aus_frage("   ") == ""


def test_speichern_laden_und_sortieren(tmp_path):
    a = cv.neuer_verlauf(tmp_path, "Erste Frage")
    a.nachrichten, a.dokumente = _nachrichten(), ["x.json"]
    cv.speichern(tmp_path, a)
    b = cv.neuer_verlauf(tmp_path, "")
    assert b.titel == "Neuer Chat" and b.id != a.id
    b.erstellt = b.aktualisiert = "2020-01-01T00:00:00+00:00"
    cv.speichern(tmp_path, b)
    b.aktualisiert = "2099-01-01T00:00:00+00:00"  # speichern setzt die Zeit neu - hier nur Reihenfolge pruefen

    geladen = cv.lade(tmp_path, a.id)
    assert geladen is not None and geladen.nachrichten == _nachrichten() and geladen.dokumente == ["x.json"]
    alle = cv.lade_alle(tmp_path)
    assert {v.id for v in alle} == {a.id, b.id}
    assert alle[0].aktualisiert >= alle[1].aktualisiert
    assert not list(tmp_path.glob("*.tmp"))  # keine Arbeitsdateien uebrig


def test_gleiche_sekunde_ergibt_verschiedene_kennungen(tmp_path):
    ids = set()
    for _ in range(3):
        v = cv.neuer_verlauf(tmp_path, "F")
        cv.speichern(tmp_path, v)
        ids.add(v.id)
    assert len(ids) == 3


def test_ungueltige_kennungen_werden_abgelehnt(tmp_path):
    v = cv.Verlauf("../boese", "t", "", "")
    with pytest.raises(ValueError):
        cv.speichern(tmp_path, v)
    assert cv.lade(tmp_path, "../x") is None
    assert cv.loesche(tmp_path, "../x") is False


def test_beschaedigte_und_fremde_dateien_werden_uebersprungen(tmp_path):
    ok = cv.neuer_verlauf(tmp_path, "gut")
    cv.speichern(tmp_path, ok)
    (tmp_path / "20260101_000000.json").write_text("{kaputt", encoding="utf-8")
    (tmp_path / "20260101_000001.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "20260101_000002.json").write_text(json.dumps({"id": "unsinn"}), encoding="utf-8")
    assert [v.id for v in cv.lade_alle(tmp_path)] == [ok.id]
    assert cv.lade_alle(tmp_path / "gibt-es-nicht") == []
    assert cv.lade(tmp_path, "20260101_000000") is None


def test_fremde_nachrichten_rollen_werden_nicht_geladen(tmp_path):
    kennung = "20260101_120000"
    (tmp_path / f"{kennung}.json").write_text(
        json.dumps({"id": kennung, "nachrichten": [{"role": "fehler", "content": "x"}, {"role": "user", "content": "f"}, 5]}),
        encoding="utf-8",
    )
    v = cv.lade(tmp_path, kennung)
    assert v is not None and [n["role"] for n in v.nachrichten] == ["user"] and v.titel == "Chat"


def test_loeschen_und_umbenennen(tmp_path):
    v = cv.neuer_verlauf(tmp_path, "Alt")
    cv.speichern(tmp_path, v)
    assert cv.umbenennen(tmp_path, v.id, "  Neuer   Titel ") is True
    assert cv.lade(tmp_path, v.id).titel == "Neuer Titel"
    assert cv.umbenennen(tmp_path, v.id, "   ") is False
    assert cv.umbenennen(tmp_path, "20200101_000000", "x") is False
    assert cv.loesche(tmp_path, v.id) is True
    assert cv.loesche(tmp_path, v.id) is False


def test_chatverlaeufe_ordner_liegt_im_programmordner(monkeypatch, tmp_path):
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    assert paths.get_chatverlaeufe_dir() == tmp_path / "chatverlaeufe"
