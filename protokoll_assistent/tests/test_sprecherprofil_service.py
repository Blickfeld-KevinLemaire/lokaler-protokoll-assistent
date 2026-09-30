import json

import pytest

from protokoll_assistent.services import sprecherprofil_service as sp


def test_ohne_datei_oder_mit_kaputter_datei_gibt_es_keine_profile(tmp_path):
    assert sp.lade_profile(tmp_path) == []
    (tmp_path / sp.PROFILDATEI).write_text("{kaputt", encoding="utf-8")
    assert sp.lade_profile(tmp_path) == []
    (tmp_path / sp.PROFILDATEI).write_text('{"profile": 5}', encoding="utf-8")
    assert sp.lade_profile(tmp_path) == []


def test_profil_speichern_und_wieder_laden(tmp_path):
    ziel = tmp_path / "neu"  # Ordner entsteht erst beim Speichern
    profil = sp.profil_speichern("  Anna   Beispiel ", [1.0, 0.0], ziel)
    assert profil["name"] == "Anna Beispiel"
    geladen = sp.lade_profile(ziel)
    assert [p["name"] for p in geladen] == ["Anna Beispiel"]
    assert not list(ziel.glob("*.tmp"))


def test_gleicher_name_mittelt_das_embedding(tmp_path):
    sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    profil = sp.profil_speichern("anna", [0.0, 1.0], tmp_path)
    assert profil["anzahl_proben"] == 2
    assert profil["embedding"] == [0.5, 0.5]
    assert len(sp.lade_profile(tmp_path)) == 1


def test_speichern_lehnt_leeren_namen_leeres_embedding_und_falsche_laenge_ab(tmp_path):
    with pytest.raises(sp.ProfilFehler):
        sp.profil_speichern("   ", [1.0], tmp_path)
    with pytest.raises(sp.ProfilFehler):
        sp.profil_speichern("Anna", [], tmp_path)
    sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    with pytest.raises(sp.ProfilFehler, match="anderes Modell"):
        sp.profil_speichern("Anna", [1.0, 0.0, 0.0], tmp_path)


def test_umbenennen_und_loeschen(tmp_path):
    a = sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    b = sp.profil_speichern("Ben", [0.0, 1.0], tmp_path)
    sp.profil_umbenennen(a["id"], "Anna Muster", tmp_path)
    assert {p["name"] for p in sp.lade_profile(tmp_path)} == {"Anna Muster", "Ben"}
    with pytest.raises(sp.ProfilFehler, match="bereits"):
        sp.profil_umbenennen(a["id"], "ben", tmp_path)
    with pytest.raises(sp.ProfilFehler, match="existiert nicht"):
        sp.profil_umbenennen("gibtsnicht", "X", tmp_path)
    assert sp.profil_loeschen(b["id"], tmp_path) is True
    assert sp.profil_loeschen(b["id"], tmp_path) is False
    assert [p["name"] for p in sp.lade_profile(tmp_path)] == ["Anna Muster"]


def _profile(tmp_path):
    sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    sp.profil_speichern("Ben", [0.0, 1.0], tmp_path)
    return sp.lade_profile(tmp_path)


def test_vorschlaege_nach_schwelle_und_sicherheit(tmp_path):
    profile = _profile(tmp_path)
    embeddings = {
        "S0": [1.0, 0.05],  # fast identisch mit Anna -> sicher
        "S1": [0.8, 0.6],  # 0,8 Aehnlichkeit mit Anna, aber Anna ist schon vergeben
        "S2": [-1.0, 0.1],  # passt zu niemandem
    }
    ergebnis = sp.finde_vorschlaege(embeddings, profile)
    assert ergebnis["S0"]["name"] == "Anna" and ergebnis["S0"]["sicher"] is True
    assert "S1" not in ergebnis  # Ben liegt bei 0,6 < Schwelle, Anna ist vergeben
    assert "S2" not in ergebnis


def test_vorschlag_knapp_ueber_schwelle_ist_unsicher(tmp_path):
    profile = _profile(tmp_path)
    # Aehnlichkeit mit Anna ~0,75: ueber 0,72, aber unter 0,80.
    ergebnis = sp.finde_vorschlaege({"S0": [0.75, 0.6614]}, profile)
    assert ergebnis["S0"]["sicher"] is False
    assert ergebnis["S0"]["aehnlichkeit"] == pytest.approx(0.75, abs=0.01)


def test_ein_profil_geht_nur_an_den_aehnlichsten_sprecher(tmp_path):
    profile = _profile(tmp_path)
    ergebnis = sp.finde_vorschlaege({"S0": [0.9, 0.3], "S1": [1.0, 0.0]}, profile)
    assert ergebnis["S1"]["name"] == "Anna"
    assert "S0" not in ergebnis


def test_profile_anderer_laenge_werden_uebersprungen(tmp_path):
    profile = _profile(tmp_path)
    assert sp.finde_vorschlaege({"S0": [1.0, 0.0, 0.0]}, profile) == {}


def test_lauf_embeddings_rundreise_und_fehlerfaelle(tmp_path):
    assert sp.lade_lauf_embeddings(tmp_path) == {}
    sp.speichere_lauf_embeddings(tmp_path / "arbeit", {"S0": [1, 2]})
    assert sp.lade_lauf_embeddings(tmp_path / "arbeit") == {"S0": [1.0, 2.0]}
    (tmp_path / sp.EMBEDDINGS_DATEI).write_text("[]", encoding="utf-8")
    assert sp.lade_lauf_embeddings(tmp_path) == {}
    (tmp_path / sp.EMBEDDINGS_DATEI).write_text(json.dumps({"S0": [], "S1": [1]}), encoding="utf-8")
    assert sp.lade_lauf_embeddings(tmp_path) == {"S1": [1.0]}
