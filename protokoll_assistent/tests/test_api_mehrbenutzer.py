"""Servermodus mit mehreren Nutzern: Anmeldung (Passwort und Schluessel), eigene Ordner, Teilen, fremde Auftraege."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from protokoll_assistent.ablauf import freigaben as freigaben_modul
from protokoll_assistent.ablauf.freigaben import Freigaben
from protokoll_assistent.ablauf.nutzer import NutzerFehler, Nutzerverwaltung, passwort_hash, passwort_passt
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.tests.api_hilfen import Umgebung, app_bauen, eigene_konfiguration

PASSWORT = "ein-sicheres-passwort"


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER, mehrbenutzer=True)
    assert u.dienste.nutzer is not None
    u.dienste.nutzer.anlegen("chef", anzeigename="Chefin", admin=True, passwort=PASSWORT)
    u.dienste.nutzer.anlegen("anna", passwort=PASSWORT)
    u.dienste.nutzer.anlegen("ben")
    return u


def _client(u: Umgebung, name: str) -> TestClient:
    client = TestClient(u.client.app)
    client.headers["X-Vermerk-Anfrage"] = "1"
    if name == "ben":
        assert u.dienste.nutzer is not None
        client.headers["Authorization"] = f"Bearer {u.dienste.nutzer.zugang_anlegen('ben', 'Skript')}"
    else:
        antwort = client.post("/api/anmelden", json={"name": name, "passwort": PASSWORT})
        assert antwort.status_code == 200, antwort.text
    return client


def _audio(u: Umgebung, besitzer: str, name: str = "sitzung.wav") -> Path:
    datei = u.tmp / "aufnahmen" / "nutzer" / besitzer / name
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_bytes(b"RIFF")
    return datei


def test_anmelden_mit_passwort_und_schluessel(server: Umgebung) -> None:
    chef = _client(server, "chef")
    info = chef.get("/api/info").json()
    assert info["angemeldet_als"] == "chef" and info["admin"] and info["mehrbenutzer"] and info["anzeigename"] == "Chefin"
    ben = _client(server, "ben")
    assert ben.get("/api/info").json()["admin"] is False
    fremd = TestClient(server.client.app)
    assert fremd.post("/api/anmelden", json={"name": "anna", "passwort": "falsch-falsch"}).status_code == 401
    assert fremd.post("/api/anmelden", json={"name": "ben", "passwort": PASSWORT}).status_code == 401  # ohne Passwort
    assert fremd.post("/api/anmelden", json={"name": "gibtsnicht", "passwort": PASSWORT}).status_code == 401


def test_gesperrter_nutzer_verliert_die_sitzung(server: Umgebung) -> None:
    anna = _client(server, "anna")
    assert anna.get("/api/info").status_code == 200
    assert server.dienste.nutzer is not None
    server.dienste.nutzer.aendern("anna", aktiv=False)
    assert anna.get("/api/info").status_code == 401


def test_widerrufener_schluessel_beendet_die_browser_sitzung(server: Umgebung) -> None:
    anna = _client(server, "anna")
    schluessel = anna.post("/api/ich/zugaenge", json={"bezeichnung": "Laptop"}).json()["schluessel"]
    browser = TestClient(server.client.app)
    assert browser.post("/api/anmelden", json={"schluessel": schluessel}).json() == {"angemeldet_als": "anna"}
    assert browser.get("/api/info").json()["angemeldet_als"] == "anna"
    assert anna.delete("/api/ich/zugaenge/Laptop").json() == {"entfernt": True}
    assert browser.get("/api/info").status_code == 401
    assert anna.get("/api/info").status_code == 200  # mit dem Passwort angemeldet: nicht betroffen


def test_passwortwechsel_beendet_die_anderen_sitzungen(server: Umgebung) -> None:
    """Die Sitzung, mit der das Passwort geaendert wird, bleibt (dort hat eben jemand das bisherige Passwort
    genannt); eine andere -- etwa auf einem vergessenen Rechner -- endet. Ein neues Passwort durch einen Admin
    beendet alle Passwort-Sitzungen des Nutzers."""
    hier, dort = _client(server, "anna"), _client(server, "anna")
    neu = "ein-ganz-neues-passwort"
    antwort = hier.put("/api/ich/passwort", json={"bisher": PASSWORT, "neu": neu})
    assert antwort.json() == {"gespeichert": True}
    assert hier.get("/api/info").status_code == 200
    assert dort.get("/api/info").status_code == 401
    chef = _client(server, "chef")
    assert chef.patch("/api/nutzer/anna", json={"passwort": "vom-admin-gesetzt"}).status_code == 200
    assert hier.get("/api/info").status_code == 401
    assert chef.get("/api/info").status_code == 200


def test_jeder_hat_eigene_besprechungen_und_teilt_gezielt(server: Umgebung) -> None:
    anna, ben = _client(server, "anna"), _client(server, "ben")
    antwort = anna.post("/api/auftraege/transkription", json={"quelle": str(_audio(server, "anna")), "mit_auswertung": True})
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["besitzer"] == "anna" and antwort.json()["platz"] == 0
    server.auftraege_ausfuehren()
    eigene = anna.get("/api/besprechungen").json()
    assert len(eigene) == 1 and eigene[0]["id"].startswith("anna~") and eigene[0]["eigen"]
    assert (server.tmp / "aus" / "nutzer" / "anna").is_dir()
    kennung = eigene[0]["id"]
    assert ben.get("/api/besprechungen").json() == []
    assert ben.get(f"/api/besprechungen/{kennung}").status_code == 404
    # Fremde Datei ueber den Pfad starten: verboten.
    assert ben.post("/api/auftraege/transkription", json={"quelle": str(_audio(server, "anna", "x.wav"))}).status_code == 403

    assert anna.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": ["ben"]}).json() == {"geteilt_mit": ["ben"]}
    geteilt = ben.get("/api/besprechungen").json()
    assert [b["id"] for b in geteilt] == [kennung] and geteilt[0]["eigen"] is False
    assert ben.get(f"/api/besprechungen/{kennung}").json()["protokoll"]["text"].startswith("# Protokoll")
    # Lesen ja, aendern nein.
    assert ben.put(f"/api/besprechungen/{kennung}/protokoll", json={"text": "x"}).status_code == 403
    assert ben.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": []}).status_code == 403
    assert anna.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": ["gibtsnicht"]}).status_code == 400
    assert anna.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": ["alle", "ben"]}).json() == {"geteilt_mit": ["alle"]}
    assert anna.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": []}).json() == {"geteilt_mit": []}
    assert ben.get("/api/besprechungen").json() == []


def test_fremde_auftraege_ohne_inhalt(server: Umgebung) -> None:
    anna, ben, chef = _client(server, "anna"), _client(server, "ben"), _client(server, "chef")
    anna.post("/api/auftraege/transkription", json={"quelle": str(_audio(server, "anna", "geheim-anna.wav"))})
    antwort = ben.post("/api/auftraege/transkription", json={"quelle": str(_audio(server, "ben"))})
    assert antwort.json()["platz"] == 1  # Annas Auftrag kommt zuerst
    fuer_ben = ben.get("/api/auftraege").json()
    annas = next(a for a in fuer_ben if a.get("fremd"))
    assert annas["titel"] == "Andere Verarbeitung" and "geheim" not in str(annas) and annas["besitzer"] is None
    assert ben.delete(f"/api/auftraege/{annas['id']}").status_code == 404
    assert ben.get(f"/api/auftraege/{annas['id']}").json()["fremd"] is True
    # Der Admin sieht die Titel (er verwaltet den Server) und darf abbrechen.
    fuer_chef = chef.get("/api/auftraege").json()
    assert any(a["titel"] == "geheim-anna.wav" for a in fuer_chef)
    assert chef.delete(f"/api/auftraege/{annas['id']}").json() == {"abgebrochen": True}
    zustand = ben.get("/api/zustand").json()
    assert zustand["empfang"] is None


def test_auftraege_ohne_besitzer_sehen_nur_admins(server: Umgebung) -> None:
    """Eingangsordner ohne PROTOKOLL_EINGANG_NUTZER, Geraete ohne Besitzer: Die Ergebnisse gehoeren niemandem --
    Titel, Quellpfad und Ergebnis sehen nur Admins, alle anderen nur "Andere Verarbeitung"."""
    ben, chef = _client(server, "ben"), _client(server, "chef")
    quelle = str(server.tmp / "eingang" / "vorstand-geheim.wav")
    auftrag = server.steuerung.auftraege.einreihen(
        "verarbeitung", "vorstand-geheim.wav", lambda f: {"ausgabe": "vertraulich"}, herkunft="ordner", angaben={"quelle": quelle}
    )
    server.auftraege_ausfuehren()
    fuer_ben = next(a for a in ben.get("/api/auftraege").json() if a["id"] == auftrag.id)
    assert fuer_ben["fremd"] is True and fuer_ben["titel"] == "Andere Verarbeitung"
    assert "geheim" not in str(fuer_ben) and "vertraulich" not in str(fuer_ben)
    assert "geheim" not in str(ben.get(f"/api/auftraege/{auftrag.id}").json())
    assert ben.delete(f"/api/auftraege/{auftrag.id}").status_code == 404
    fuer_chef = next(a for a in chef.get("/api/auftraege").json() if a["id"] == auftrag.id)
    assert fuer_chef["titel"] == "vorstand-geheim.wav" and fuer_chef["ergebnis"] == {"ausgabe": "vertraulich"}


def test_hochladen_in_den_eigenen_ordner(server: Umgebung) -> None:
    anna = _client(server, "anna")
    antwort = anna.post("/api/dateien/hochladen", files={"datei": ("a.wav", b"RIFF", "audio/wav")})
    assert Path(antwort.json()["pfad"]).parent == server.tmp / "aufnahmen" / "nutzer" / "anna"
    assert [d["name"] for d in anna.get("/api/dateien/eingang").json()] == ["a.wav"]
    assert _client(server, "ben").get("/api/dateien/eingang").json() == []


def test_nur_admins_aendern_einstellungen_und_geraete(server: Umgebung) -> None:
    anna, chef = _client(server, "anna"), _client(server, "chef")
    assert anna.patch("/api/einstellungen", json={"sprache": "en"}).status_code == 403
    assert chef.patch("/api/einstellungen", json={"sprache": "en"}).status_code == 200
    assert anna.post("/api/geraete", json={"name": "Raum-1"}).status_code == 403
    assert chef.post("/api/geraete", json={"name": "Raum-1", "besitzer": "gibtsnicht"}).status_code == 400
    neu = chef.post("/api/geraete", json={"name": "Raum-1", "besitzer": "anna"}).json()
    assert neu["token"]
    chef.post("/api/geraete", json={"name": "Raum-2", "besitzer": "ben"})
    assert [g["name"] for g in anna.get("/api/geraete").json()["geraete"]] == ["Raum-1"]
    assert {g["name"] for g in chef.get("/api/geraete").json()["geraete"]} == {"Raum-1", "Raum-2"}
    assert anna.get("/api/system/diagnose").status_code == 403


def test_geraeteaufnahme_landet_beim_besitzer(server: Umgebung) -> None:
    from protokoll_assistent.utils import app_config

    app_config.update_config(geraete_empfang_geraete=[{"name": "Raum-1", "token_sha256": "a" * 64, "besitzer": "anna"}])
    automatik = server.dienste.automatik
    assert automatik is not None and automatik.besitzer_von("Raum-1") == "anna" and automatik.besitzer_von("x") is None
    datei = _audio(server, "anna", "Raum-1_H5.opus")
    auftrag = automatik.aufnahme_bereit(datei, "Raum-1", "H5.opus")
    assert auftrag is not None and auftrag.besitzer == "anna"
    server.auftraege_ausfuehren()
    assert [b["id"].split("~")[0] for b in _client(server, "anna").get("/api/besprechungen").json()] == ["anna"]
    assert _client(server, "ben").get("/api/besprechungen").json() == []


def test_geraete_eines_entfernten_nutzers_werden_allgemein(server: Umgebung) -> None:
    # Sonst kaemen die Aufnahmen weiter in den Ordner eines Nutzers, den es nicht mehr gibt -- niemand saehe sie.
    chef = _client(server, "chef")
    chef.post("/api/geraete", json={"name": "Raum 1", "besitzer": "ben"})
    chef.post("/api/geraete", json={"name": "Küche", "besitzer": "anna"})
    assert chef.delete("/api/nutzer/ben").json() == {"entfernt": True}
    automatik = server.dienste.automatik
    assert automatik is not None
    assert automatik.besitzer_von("Raum 1") is None and automatik.besitzer_von("Küche") == "anna"
    besitzer = {g["name"]: g["besitzer"] for g in chef.get("/api/geraete").json()["geraete"]}
    assert besitzer == {"Raum 1": None, "Küche": "anna"}


def test_nutzerverwaltung_ueber_die_schnittstelle(server: Umgebung) -> None:
    chef, anna = _client(server, "chef"), _client(server, "anna")
    assert anna.get("/api/nutzer").status_code == 403
    assert {n["name"] for n in anna.get("/api/nutzer/namen").json()} == {"chef", "anna", "ben"}
    neu = chef.post("/api/nutzer", json={"name": "carla", "passwort": "kurz"})
    assert neu.status_code == 400
    assert chef.post("/api/nutzer", json={"name": "carla", "anzeigename": "Carla C."}).json()["hat_passwort"] is False
    assert chef.post("/api/nutzer", json={"name": "Carla"}).status_code == 400  # schon vorhanden
    schluessel = chef.post("/api/nutzer/carla/zugaenge", json={"bezeichnung": "Laptop"}).json()["schluessel"]
    assert TestClient(server.client.app).get("/api/info", headers={"Authorization": f"Bearer {schluessel}"}).status_code == 200
    assert chef.patch("/api/nutzer/carla", json={"passwort": PASSWORT, "admin": True}).json()["admin"] is True
    assert chef.delete("/api/nutzer/carla/zugaenge/Laptop").json() == {"entfernt": True}
    assert chef.delete("/api/nutzer/carla/zugaenge/Laptop").status_code == 400
    assert chef.delete("/api/nutzer/chef").status_code == 400  # sich selbst nicht
    assert chef.delete("/api/nutzer/carla").json() == {"entfernt": True}
    assert chef.patch("/api/nutzer/gibtsnicht", json={"admin": True}).status_code == 400


def test_selbstverwaltung(server: Umgebung) -> None:
    anna = _client(server, "anna")
    ich = anna.get("/api/ich").json()
    assert ich["name"] == "anna" and ich["hat_passwort"]
    assert anna.put("/api/ich/passwort", json={"bisher": "falsch", "neu": "noch-ein-passwort"}).status_code == 403
    assert anna.put("/api/ich/passwort", json={"bisher": PASSWORT, "neu": "kurz"}).status_code == 400
    assert anna.put("/api/ich/passwort", json={"bisher": PASSWORT, "neu": "noch-ein-passwort"}).json() == {"gespeichert": True}
    zugang = anna.post("/api/ich/zugaenge", json={"bezeichnung": "Handy"}).json()
    assert len(zugang["schluessel"]) > 30
    assert anna.post("/api/ich/zugaenge", json={"bezeichnung": "Handy"}).status_code == 400
    assert anna.delete("/api/ich/zugaenge/Handy").json() == {"entfernt": True}
    assert anna.delete("/api/ich/zugaenge/Handy").status_code == 400


def test_desktop_kennt_keine_nutzer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path)
    assert u.client.get("/api/nutzer").status_code == 404
    assert u.client.get("/api/ich").json()["name"] == "desktop"
    assert u.client.put("/api/besprechungen/x/freigabe", json={"mit": []}).status_code == 404


def test_ereignisse_fuer_andere_nutzer(server: Umgebung) -> None:
    from protokoll_assistent.api.kontext import Angemeldet
    from protokoll_assistent.api.sichtbarkeit import ereignis_fuer
    from protokoll_assistent.utils import app_config

    app_config.update_config(geraete_empfang_geraete=[{"name": "Raum-1", "token_sha256": "a" * 64, "besitzer": "anna"}])
    d = server.dienste
    anna, ben, chef = Angemeldet("anna", False, "anna"), Angemeldet("ben", False, "ben"), Angemeldet("chef", True, "chef")
    live: dict[str, Any] = {"geraet": "Raum-1", "text": "vertraulich"}
    assert ereignis_fuer(d, anna, "live", live) == live
    assert ereignis_fuer(d, ben, "live", live) is None
    assert ereignis_fuer(d, chef, "live", live) is None  # Inhalte auch nicht fuer Admins
    assert ereignis_fuer(d, chef, "geraet_status", {"geraet": "Raum-1"}) is not None
    assert ereignis_fuer(d, ben, "geraet_status", {"geraet": "Raum-1"}) is None
    assert ereignis_fuer(d, ben, "empfang", {}) is None and ereignis_fuer(d, chef, "empfang", {}) == {}
    assert ereignis_fuer(d, ben, "hinweis", {"quelle": "ollama", "text": "x"}) is None
    assert ereignis_fuer(d, ben, "hinweis", {"quelle": "Raum-1", "text": "x"}) is None
    assert ereignis_fuer(d, anna, "hinweis", {"quelle": "Raum-1", "text": "x"}) is not None
    assert ereignis_fuer(d, ben, "hinweis", {"quelle": "", "text": "allgemein"}) is not None
    eigene_datei = str(server.tmp / "aufnahmen" / "nutzer" / "ben" / "a.wav")
    assert ereignis_fuer(d, ben, "dateien", {"pfad": eigene_datei}) is not None
    assert ereignis_fuer(d, anna, "dateien", {"pfad": eigene_datei}) is None
    auftrag = d.steuerung.auftraege.einreihen("t", "geheim", lambda f: {}, besitzer="anna")
    assert ereignis_fuer(d, ben, "auftrag_meldung", {"id": auftrag.id}) is None
    assert ereignis_fuer(d, anna, "auftrag_meldung", {"id": auftrag.id}) is not None
    assert ereignis_fuer(d, anna, "auftrag_meldung", {"id": "weg"}) is None
    assert ereignis_fuer(d, ben, "einstellungen", {"geaendert": []}) is not None


@pytest.mark.parametrize("name", ["umgebung", "Umgebung", "desktop", "DESKTOP", "alle", "Alle"])
def test_reservierte_namen_werden_keine_nutzer(server: Umgebung, name: str) -> None:
    """Ein Nutzer "umgebung" waere Admin ohne eigenen Ordner, "desktop" der Schluessel des Fensters, "alle" die Freigabe fuer
    alle -- ein Nutzer dieses Namens bekaeme deren Bedeutung."""
    chef = _client(server, "chef")
    antwort = chef.post("/api/nutzer", json={"name": name, "passwort": PASSWORT})
    assert antwort.status_code == 400 and "Programm selbst" in antwort.json()["detail"]
    assert server.dienste.nutzer is not None and server.dienste.nutzer.hole(name) is None


def test_nutzer_nicht_unter_dem_namen_eines_zugangsschluessels(tmp_path: Path) -> None:
    v = Nutzerverwaltung(tmp_path / "nutzer.json", vergebene_namen=lambda: ["Laptop"])
    with pytest.raises(NutzerFehler, match="Zugangsschlüssel"):
        v.anlegen("laptop", admin=True)
    assert v.anlegen("tablet").name == "tablet"


def test_nutzerverwaltung_regeln(tmp_path: Path) -> None:
    v = Nutzerverwaltung(tmp_path / "nutzer.json")
    assert v.leer()
    with pytest.raises(NutzerFehler, match="Anmeldename"):
        v.anlegen("mit leerzeichen")
    with pytest.raises(NutzerFehler, match="Anmeldename"):
        v.anlegen("anna\n")  # "$" bei re.match liesse den Zeilenumbruch durch
    v.anlegen("admin", admin=True, passwort=PASSWORT)
    with pytest.raises(NutzerFehler, match="mindestens einen aktiven Admin"):
        v.aendern("admin", admin=False)
    with pytest.raises(NutzerFehler, match="mindestens einen aktiven Admin"):
        v.entfernen("admin")
    with pytest.raises(NutzerFehler):
        v.passwort_setzen("gibtsnicht", PASSWORT)
    v.passwort_setzen("admin", None)
    assert v.passwort_pruefen("admin", PASSWORT) is None
    (tmp_path / "kaputt.json").write_text("{", encoding="utf-8")
    with pytest.raises(NutzerFehler, match="nicht lesbar"):
        Nutzerverwaltung(tmp_path / "kaputt.json").liste()
    assert not passwort_passt("x", "md5$abc")
    assert not passwort_passt("x", "unsinn")
    assert passwort_passt("geheim", passwort_hash("geheim"))


# ---------------------------------------------------------------- Freigaben (freigaben.json)
def test_freigaben_teilen_sich_eine_sperre_je_datei(tmp_path: Path) -> None:
    """Jede Anfrage baut ihr eigenes ``Freigaben`` (``Dienste.freigaben()``), und FastAPI fuehrt Anfragen parallel
    aus. Geschuetzt ist das Lesen-Aendern-Schreiben nur, wenn alle Objekte derselben Datei dieselbe Sperre haben."""
    datei = tmp_path / "freigaben.json"
    assert Freigaben(datei)._sperre is Freigaben(tmp_path / "." / "freigaben.json")._sperre
    assert Freigaben(datei)._sperre is not Freigaben(tmp_path / "andere.json")._sperre


def test_freigaben_schreiben_unter_eindeutigem_arbeitsnamen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    datei = tmp_path / "freigaben.json"
    arbeitsnamen: list[Path] = []
    echt = freigaben_modul._ersetzen_mit_wiederholung

    def ersetzen(quelle: Path, ziel: Path) -> None:
        arbeitsnamen.append(quelle)
        echt(quelle, ziel)

    monkeypatch.setattr(freigaben_modul, "_ersetzen_mit_wiederholung", ersetzen)
    freigaben = Freigaben(datei)
    freigaben.setzen("anna", "sitzung", ["ben"])
    freigaben.setzen("anna", "andere", [freigaben_modul.ALLE])
    assert len(set(arbeitsnamen)) == 2 and datei.with_name("freigaben.json.tmp") not in arbeitsnamen
    assert freigaben.mit_wem("anna", "sitzung") == ["ben"] and freigaben.darf_lesen("ben", "anna", "andere")
    assert list(tmp_path.glob("*.tmp")) == []

    def scheitern(quelle: Path, ziel: Path) -> None:
        raise PermissionError("gesperrt")

    monkeypatch.setattr(freigaben_modul, "_ersetzen_mit_wiederholung", scheitern)
    with pytest.raises(PermissionError):
        freigaben.setzen("anna", "dritte", ["ben"])
    assert list(tmp_path.glob("*.tmp")) == []  # kein liegengebliebener Arbeitsstand
    assert freigaben.mit_wem("anna", "dritte") == []
