"""Umbenennen (nur der Anzeigename), Loeschen (in einen Papierkorb) und „Dokument öffnen“ einer Besprechung."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from protokoll_assistent.ablauf import bibliothek
from protokoll_assistent.ablauf.ereignisse import Ereignis
from protokoll_assistent.ablauf.freigaben import Freigaben
from protokoll_assistent.api import routen_besprechungen
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.services import export_service, papierkorb_service
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben
from protokoll_assistent.tests.api_hilfen import Umgebung, app_bauen, eigene_konfiguration

PASSWORT = "ein-sicheres-passwort"
STAMM = "sitzung_lokal_transkript_20260101_100000"


# --------------------------------------------------------------------------
# Bibliothek
# --------------------------------------------------------------------------
def _einzige(ordner: Path) -> bibliothek.Besprechung:
    [b] = bibliothek.besprechungen(ordner)
    return b


def test_umbenennen_aendert_nur_den_anzeigenamen(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / f"{STAMM}.json")
    # Ein aelteres Protokoll ohne 'transkript_datei' (Zuordnung ueber den Quellnamen) und Exporte nach dem Quellnamen.
    (tmp_path / "sitzung_protokoll_20260101_110000.json").write_text(
        json.dumps({"quelldatei_stamm": "sitzung", "ergebnis": "# Alt"}), encoding="utf-8"
    )
    export = tmp_path / "sitzung_transkript.pdf"
    export.write_bytes(b"%PDF")
    sprecher = tmp_path / "sitzung_Anna.wav"
    sprecher.write_bytes(b"RIFF")

    b = _einzige(tmp_path)
    assert bibliothek.umbenennen(b, "  Vorstand – Dezember  ") == "Vorstand – Dezember"
    neu = _einzige(tmp_path)
    assert (neu.id, neu.titel, neu.stamm) == (STAMM, "Vorstand – Dezember", "sitzung")
    assert [p.zeit for p in neu.protokolle] == ["20260101_110000"]
    assert export in neu.dateien() and sprecher in neu.dateien()
    assert neu.als_dict()["titel"] == "Vorstand – Dezember"
    # Keine Datei umbenannt, keine Arbeitsdatei liegen geblieben.
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [transkript.name, "sitzung_protokoll_20260101_110000.json", export.name, sprecher.name]
    )
    daten = json.loads(transkript.read_text(encoding="utf-8"))
    assert daten["anzeigename"] == "Vorstand – Dezember" and daten["quelldatei_stamm"] == "sitzung"

    # Wieder wie die Datei: Das Feld entfaellt.
    bibliothek.umbenennen(neu, "sitzung")
    assert "anzeigename" not in json.loads(transkript.read_text(encoding="utf-8"))
    assert _einzige(tmp_path).titel == "sitzung"


@pytest.mark.parametrize(
    ("name", "teil"),
    [("", "leer"), ("   ", "leer"), ("x" * 121, "120"), ("a\nb", "Steuerzeichen"), ("a\x00b", "Steuerzeichen"), ("a‮b", "Steuerzeichen")],
)
def test_ungueltige_namen(name: str, teil: str) -> None:
    with pytest.raises(bibliothek.BibliothekFehler, match=teil):
        bibliothek.name_pruefen(name)


def test_name_mit_umlauten_und_zeichen_geht() -> None:
    assert bibliothek.name_pruefen("Ä/Ö: „Team“ 👩‍💻") == "Ä/Ö: „Team“ 👩‍💻"
    assert bibliothek.name_pruefen("x" * 120) == "x" * 120


def test_ungueltiger_name_in_der_datei_wird_ignoriert(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / f"{STAMM}.json")
    daten = json.loads(transkript.read_text(encoding="utf-8"))
    for wert in ("", 42, "a\nb"):
        transkript.write_text(json.dumps({**daten, "anzeigename": wert}), encoding="utf-8")
        assert _einzige(tmp_path).titel == "sitzung"


def test_umbenennen_kaputtes_transkript(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / f"{STAMM}.json")
    b = _einzige(tmp_path)
    transkript.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(bibliothek.BibliothekFehler, match="beschädigt"):
        bibliothek.umbenennen(b, "Neu")
    transkript.unlink()
    with pytest.raises(bibliothek.BibliothekFehler, match="lesen"):
        bibliothek.umbenennen(b, "Neu")


def test_umbenennen_scheitert_beim_ersetzen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transkript_json_schreiben(tmp_path / f"{STAMM}.json")
    b = _einzige(tmp_path)

    def gesperrt(quelle: Path, ziel: Path) -> None:
        raise PermissionError(5, "Zugriff verweigert")

    monkeypatch.setattr(bibliothek, "_ersetzen_mit_wiederholung", gesperrt)
    with pytest.raises(bibliothek.BibliothekFehler, match="Speichern"):
        bibliothek.umbenennen(b, "Neu")
    assert [p.name for p in tmp_path.iterdir()] == [f"{STAMM}.json"]  # Arbeitsdatei wieder weg


def test_neue_namen_fuer_sprecher_behalten_den_anzeigenamen(tmp_path: Path) -> None:
    transkript = transkript_json_schreiben(tmp_path / f"{STAMM}.json")
    bibliothek.umbenennen(_einzige(tmp_path), "Vorstand")
    export_service.reexport_with_new_names(transkript, {"SPEAKER_00": "Anna"})
    assert _einzige(tmp_path).titel == "Vorstand"


def _sitzung_mit_allem(ordner: Path) -> dict[str, Path]:
    transkript = transkript_json_schreiben(ordner / f"{STAMM}.json")
    protokoll = ordner / "sitzung_protokoll_20260101_110000.json"
    protokoll.write_text(json.dumps({"ergebnis": "# P", "transkript_datei": transkript.name}), encoding="utf-8")
    dateien = {
        "transkript": transkript,
        "txt": transkript.with_suffix(".txt"),
        "docx": protokoll.with_suffix(".docx"),
        "protokoll": protokoll,
        "md": protokoll.with_suffix(".md"),
        "export": ordner / "sitzung_gesamt.pdf",
        "sprecher": ordner / "sitzung_Anna.wav",
    }
    for name, pfad in dateien.items():
        if name not in ("transkript", "protokoll"):
            pfad.write_bytes(b"x")
    return dateien


def test_loeschen_in_den_ausweich_papierkorb(tmp_path: Path) -> None:
    aus = tmp_path / "aus"
    dateien = _sitzung_mit_allem(aus)
    fremd = aus / "andere_lokal_transkript_20260102_100000.json"
    transkript_json_schreiben(fremd)
    ziel = bibliothek.loeschen(
        bibliothek.finde(aus, STAMM),  # type: ignore[arg-type]
        aus,
        jetzt=datetime(2026, 11, 24, 9, 30, 0),
    )
    assert ziel == aus / ".papierkorb" / f"20261124_093000_{STAMM}"
    assert sorted(p.name for p in ziel.iterdir()) == sorted(p.name for p in dateien.values())
    assert not any(p.exists() for p in dateien.values())
    # Die andere Besprechung bleibt, und der Papierkorb erscheint nicht als Besprechung.
    assert [b.id for b in bibliothek.besprechungen(aus)] == [fremd.stem]
    # Ein zweites Mal zur selben Sekunde: eigener Ordner.
    _sitzung_mit_allem(aus)
    zweites = bibliothek.loeschen(bibliothek.finde(aus, STAMM), aus, jetzt=datetime(2026, 11, 24, 9, 30, 0))  # type: ignore[arg-type]
    assert zweites == aus / ".papierkorb" / f"20261124_093000_{STAMM}_2"


def test_loeschen_laesst_dateien_anderer_besprechungen_liegen(tmp_path: Path) -> None:
    """'sitzung_2_…' beginnt wie 'sitzung_…': Die Sprecher-Exporte von 'sitzung' fingen sonst auch Dateien von
    'sitzung_2' ein. Und wurde dieselbe Aufnahme zweimal transkribiert, gehoeren die Exporte beiden."""
    _sitzung_mit_allem(tmp_path)
    zwei = transkript_json_schreiben(tmp_path / "sitzung_2_lokal_transkript_20260102_100000.json")
    zwei.with_suffix(".txt").write_text("x", encoding="utf-8")
    (tmp_path / "sitzung_2_Bernd.wav").write_bytes(b"x")
    nochmal = transkript_json_schreiben(tmp_path / "sitzung_lokal_transkript_20260103_100000.json")
    b = bibliothek.finde(tmp_path, STAMM)
    assert b is not None
    namen = {p.name for p in bibliothek.zu_loeschen(b, bibliothek.besprechungen(tmp_path))}
    assert f"{STAMM}.json" in namen and "sitzung_protokoll_20260101_110000.md" in namen
    assert not namen & {zwei.with_suffix(".txt").name, "sitzung_2_Bernd.wav", nochmal.name}
    # Den Export 'sitzung_gesamt.pdf' beansprucht auch die zweite Transkription derselben Aufnahme.
    assert "sitzung_gesamt.pdf" not in namen


def test_loeschen_in_den_papierkorb_von_windows(tmp_path: Path) -> None:
    dateien = _sitzung_mit_allem(tmp_path)
    erhalten: list[list[Path]] = []

    def papierkorb(pfade: list[Path]) -> None:
        erhalten.append(list(pfade))
        for p in pfade:
            p.unlink()

    assert bibliothek.loeschen(_einzige(tmp_path), tmp_path, papierkorb=papierkorb) is None
    [liste] = erhalten
    assert set(liste) == set(dateien.values()) and liste[-1] == dateien["transkript"]
    assert list(tmp_path.iterdir()) == []


def test_scheitert_der_papierkorb_geht_der_rest_in_den_ordner(tmp_path: Path) -> None:
    dateien = _sitzung_mit_allem(tmp_path)

    def halb(pfade: list[Path]) -> None:
        pfade[0].unlink()
        raise papierkorb_service.PapierkorbFehler("abgelehnt")

    ziel = bibliothek.loeschen(_einzige(tmp_path), tmp_path, papierkorb=halb)
    assert ziel is not None and len(list(ziel.iterdir())) == len(dateien) - 1
    assert bibliothek.besprechungen(tmp_path) == []


def test_loeschen_scheitert_und_nimmt_alles_zurueck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dateien = _sitzung_mit_allem(tmp_path)
    echt = bibliothek._verschieben
    aufrufe: list[Path] = []

    def geoeffnet(quelle: Path, ziel: Path) -> None:
        aufrufe.append(quelle)
        if len(aufrufe) == 3:
            raise PermissionError(32, "Die Datei wird von einem anderen Prozess verwendet")
        echt(quelle, ziel)

    monkeypatch.setattr(bibliothek, "_verschieben", geoeffnet)
    with pytest.raises(bibliothek.BibliothekFehler, match="anderen Programm geöffnet"):
        bibliothek.loeschen(_einzige(tmp_path), tmp_path)
    assert all(p.exists() for p in dateien.values())
    assert not any((tmp_path / ".papierkorb").iterdir())
    assert _einzige(tmp_path).id == STAMM


def test_verschieben_ueberschreibt_nichts(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("a", encoding="utf-8")
    (tmp_path / "b").write_text("b", encoding="utf-8")
    with pytest.raises(FileExistsError):
        bibliothek._verschieben(tmp_path / "a", tmp_path / "b")


def test_eigener_ordner_der_aufnahme_verschwindet_mit(tmp_path: Path) -> None:
    """Servermodus: je Aufnahme ein Unterordner mit 'ergebnis.json' daneben."""
    unter = tmp_path / "sitzung_20260101_100000"
    _sitzung_mit_allem(unter)
    (unter / "ergebnis.json").write_text("{}", encoding="utf-8")
    ziel = bibliothek.loeschen(_einzige(tmp_path), tmp_path)
    assert not unter.exists()
    assert ziel is not None and (ziel / "ergebnis.json").is_file()
    assert bibliothek.besprechungen(tmp_path) == []


def test_unterordner_mit_weiterem_transkript_bleibt(tmp_path: Path) -> None:
    unter = tmp_path / "sitzung_20260101_100000"
    _sitzung_mit_allem(unter)
    (unter / "ergebnis.json").write_text("{}", encoding="utf-8")
    (unter / "notizen").mkdir()
    andere = transkript_json_schreiben(unter / "anders_lokal_transkript_20260102_100000.json")
    bibliothek.loeschen(bibliothek.finde(tmp_path, STAMM), tmp_path)  # type: ignore[arg-type]
    assert (unter / "ergebnis.json").is_file() and andere.is_file()
    # Ohne weiteres Transkript, aber mit einem Unterordner: der Ordner bleibt (nur Dateien gehen in den Papierkorb).
    andere.unlink()
    _sitzung_mit_allem(unter)
    bibliothek.loeschen(_einzige(tmp_path), tmp_path)
    assert unter.is_dir() and [p.name for p in unter.iterdir()] == ["notizen"]


def test_papierkorb_von_windows_ausserhalb_von_windows(tmp_path: Path) -> None:
    datei = tmp_path / "a.txt"
    datei.write_text("a", encoding="utf-8")
    papierkorb_service.in_papierkorb([])
    with pytest.raises(papierkorb_service.PapierkorbFehler):
        papierkorb_service.in_papierkorb([datei], windows=False)
    assert datei.exists()
    assert papierkorb_service.quellliste([datei]) == f"{datei}\0\0"
    assert papierkorb_service.SCHALTER == 0x0454


# --------------------------------------------------------------------------
# Programmschnittstelle (Windows-Anwendung)
# --------------------------------------------------------------------------
@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    return app_bauen(tmp_path)


def _verarbeitet(u: Umgebung) -> dict[str, Any]:
    antwort = u.client.post("/api/auftraege/transkription", json={"quelle": str(u.audio()), "mit_auswertung": True})
    assert antwort.status_code == 201, antwort.text
    u.auftraege_ausfuehren()
    [eintrag] = u.client.get("/api/besprechungen").json()
    return dict(eintrag)


def _ereignisse(u: Umgebung) -> list[Ereignis]:
    gesehen: list[Ereignis] = []
    u.steuerung.bus.abonnieren(gesehen.append)
    return gesehen


def test_umbenennen_ueber_die_schnittstelle(umgebung: Umgebung) -> None:
    eintrag = _verarbeitet(umgebung)
    kennung = eintrag["id"]
    gesehen = _ereignisse(umgebung)
    antwort = umgebung.client.put(f"/api/besprechungen/{kennung}/name", json={"name": " Jour fixe "})
    assert antwort.status_code == 200 and antwort.json() == {"titel": "Jour fixe"}
    [neu] = umgebung.client.get("/api/besprechungen").json()
    assert (neu["id"], neu["titel"], neu["hat_protokoll"]) == (kennung, "Jour fixe", True)
    assert umgebung.client.get(f"/api/besprechungen/{kennung}").json()["titel"] == "Jour fixe"
    assert [(e.art, e.daten) for e in gesehen] == [("besprechungen", {"grund": "umbenannt"})]
    assert umgebung.client.put(f"/api/besprechungen/{kennung}/name", json={"name": "  "}).status_code == 400
    assert umgebung.client.put(f"/api/besprechungen/{kennung}/name", json={"name": "a\tb"}).status_code == 400
    assert umgebung.client.put("/api/besprechungen/gibtsnicht/name", json={"name": "x"}).status_code == 404


def test_umbenennen_meldet_schreibfehler(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    kennung = _verarbeitet(umgebung)["id"]

    def kaputt(besprechung: bibliothek.Besprechung, name: str) -> str:
        raise bibliothek.BibliothekFehler("Speichern ging nicht: voll")

    monkeypatch.setattr(bibliothek, "umbenennen", kaputt)
    antwort = umgebung.client.put(f"/api/besprechungen/{kennung}/name", json={"name": "Neu"})
    assert antwort.status_code == 500 and "voll" in antwort.json()["detail"]


def test_loeschen_unter_windows_in_den_papierkorb(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    eintrag = _verarbeitet(umgebung)
    audio = umgebung.tmp / "aufnahmen" / "besprechung.wav"
    umgebung.dienste.plattform_windows = True
    weg: list[Path] = []

    def papierkorb(pfade: list[Path]) -> None:
        for p in pfade:
            weg.append(p)
            p.unlink()

    monkeypatch.setattr(papierkorb_service, "in_papierkorb", papierkorb)
    gesehen = _ereignisse(umgebung)
    antwort = umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}")
    assert antwort.status_code == 200 and antwort.json() == {"geloescht": True, "papierkorb": "windows"}
    assert Path(eintrag["transkript"]) in weg and any(p.name.endswith(".md") for p in weg)
    assert umgebung.client.get("/api/besprechungen").json() == []
    assert umgebung.client.get(f"/api/besprechungen/{eintrag['id']}").status_code == 404
    assert audio.is_file()  # Die Aufnahme selbst bleibt.
    assert [(e.art, e.daten) for e in gesehen] == [("besprechungen", {"grund": "geloescht"})]
    assert umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}").status_code == 404


def test_loeschen_ohne_windows_in_den_ordner(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    eintrag = _verarbeitet(umgebung)
    umgebung.dienste.plattform_windows = False

    def nie(pfade: list[Path]) -> None:  # pragma: no cover - darf nicht aufgerufen werden
        raise AssertionError("kein Papierkorb von Windows ausserhalb von Windows")

    monkeypatch.setattr(papierkorb_service, "in_papierkorb", nie)
    antwort = umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}")
    assert antwort.json() == {"geloescht": True, "papierkorb": "ordner"}
    [ordner] = (umgebung.tmp / "aus" / ".papierkorb").iterdir()
    assert (ordner / Path(eintrag["transkript"]).name).is_file()
    assert umgebung.client.get("/api/besprechungen").json() == []


def test_loeschen_waehrend_einer_zusammenfassung(umgebung: Umgebung) -> None:
    eintrag = _verarbeitet(umgebung)
    start = umgebung.client.post("/api/auftraege/auswertung", json={"transkript": eintrag["transkript"]})
    assert start.status_code == 201
    antwort = umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}")
    assert antwort.status_code == 409 and "Zusammenfassung" in antwort.json()["detail"]
    # Umbenennen geht trotzdem: Es schreibt nur den Namen.
    assert umgebung.client.put(f"/api/besprechungen/{eintrag['id']}/name", json={"name": "Neu"}).status_code == 200
    umgebung.auftraege_ausfuehren()
    umgebung.dienste.plattform_windows = False
    assert umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}").status_code == 200


def test_loeschen_scheitert_an_geoeffneter_datei(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    eintrag = _verarbeitet(umgebung)
    umgebung.dienste.plattform_windows = False

    def geoeffnet(*_a: Any, **_k: Any) -> Path:
        raise bibliothek.BibliothekFehler("„x.docx“ ließ sich nicht löschen.")

    monkeypatch.setattr(bibliothek, "loeschen", geoeffnet)
    antwort = umgebung.client.delete(f"/api/besprechungen/{eintrag['id']}")
    assert antwort.status_code == 409 and "x.docx" in antwort.json()["detail"]


def test_dokument_oeffnen(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    eintrag = _verarbeitet(umgebung)
    kennung = eintrag["id"]
    geoeffnet: list[Path] = []
    monkeypatch.setattr(routen_besprechungen, "_mit_standardprogramm_oeffnen", geoeffnet.append)
    umgebung.dienste.plattform_windows = True
    transkript = Path(eintrag["transkript"])
    for word in (transkript.with_suffix(".docx"), *transkript.parent.glob("*_protokoll_*.docx")):
        word.unlink(missing_ok=True)
    assert umgebung.client.get("/api/besprechungen").json()[0]["dokument"] is None
    assert umgebung.client.post(f"/api/besprechungen/{kennung}/dokument-oeffnen").status_code == 404

    word = transkript.with_suffix(".docx")
    word.write_bytes(b"PK")
    assert umgebung.client.get("/api/besprechungen").json()[0]["dokument"] == str(word)
    antwort = umgebung.client.post(f"/api/besprechungen/{kennung}/dokument-oeffnen")
    assert antwort.status_code == 200 and geoeffnet == [word]
    umgebung.dienste.plattform_windows = False
    assert umgebung.client.post(f"/api/besprechungen/{kennung}/dokument-oeffnen").status_code == 501
    assert umgebung.client.post("/api/besprechungen/gibtsnicht/dokument-oeffnen").status_code == 404


def test_dokument_oeffnen_nicht_auf_dem_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    transkript_json_schreiben(tmp_path / "aus" / f"{STAMM}.json").with_suffix(".docx").write_bytes(b"PK")
    client = TestClient(u.client.app)
    client.headers["X-Vermerk-Anfrage"] = "1"
    assert client.post("/api/anmelden", json={"schluessel": "zugang-fuer-den-browser"}).status_code == 200
    assert client.get("/api/besprechungen").json()[0]["id"] == STAMM
    assert client.post(f"/api/besprechungen/{STAMM}/dokument-oeffnen").status_code == 403


# --------------------------------------------------------------------------
# Servermodus mit mehreren Nutzern
# --------------------------------------------------------------------------
@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER, mehrbenutzer=True)
    assert u.dienste.nutzer is not None
    u.dienste.nutzer.anlegen("chef", admin=True, passwort=PASSWORT)
    u.dienste.nutzer.anlegen("anna", passwort=PASSWORT)
    u.dienste.nutzer.anlegen("ben", passwort=PASSWORT)
    return u


def _client(u: Umgebung, name: str) -> TestClient:
    client = TestClient(u.client.app)
    client.headers["X-Vermerk-Anfrage"] = "1"
    assert client.post("/api/anmelden", json={"name": name, "passwort": PASSWORT}).status_code == 200
    return client


def test_umbenennen_und_loeschen_nur_durch_den_besitzer(server: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(papierkorb_service, "in_papierkorb", lambda pfade: (_ for _ in ()).throw(AssertionError))
    anna, ben, chef = _client(server, "anna"), _client(server, "ben"), _client(server, "chef")
    aus = server.tmp / "aus" / "nutzer" / "anna"
    unter = aus / "sitzung_20260101_100000"
    transkript = transkript_json_schreiben(unter / f"{STAMM}.json")
    (unter / "ergebnis.json").write_text("{}", encoding="utf-8")
    kennung = f"anna~{STAMM}"
    assert anna.put(f"/api/besprechungen/{kennung}/freigabe", json={"mit": ["ben"]}).status_code == 200

    # Geteilt: lesen ja, umbenennen und loeschen nein. Nicht geteilt: gibt es gar nicht.
    assert ben.put(f"/api/besprechungen/{kennung}/name", json={"name": "Fremd"}).status_code == 403
    assert ben.delete(f"/api/besprechungen/{kennung}").status_code == 403
    assert chef.put(f"/api/besprechungen/{kennung}/name", json={"name": "Fremd"}).status_code == 404
    assert chef.delete(f"/api/besprechungen/{kennung}").status_code == 404

    assert anna.put(f"/api/besprechungen/{kennung}/name", json={"name": "Vorstand"}).status_code == 200
    [geteilt] = ben.get("/api/besprechungen").json()
    assert (geteilt["id"], geteilt["titel"], geteilt["eigen"]) == (kennung, "Vorstand", False)
    assert anna.get("/api/besprechungen").json()[0]["geteilt_mit"] == ["ben"]

    assert anna.delete(f"/api/besprechungen/{kennung}").json() == {"geloescht": True, "papierkorb": "ordner"}
    assert ben.get("/api/besprechungen").json() == [] and anna.get("/api/besprechungen").json() == []
    assert Freigaben(server.tmp / "aus" / "freigaben.json").mit_wem("anna", STAMM) == []
    assert not unter.exists() and not transkript.exists()
    [ablage] = (aus / ".papierkorb").iterdir()
    assert sorted(p.name for p in ablage.iterdir()) == ["ergebnis.json", transkript.name]


def test_admin_loescht_ergebnis_ohne_besitzer(server: Umgebung) -> None:
    transkript = transkript_json_schreiben(server.tmp / "aus" / "vorstand_20260101_100000" / f"{STAMM}.json")
    chef, anna = _client(server, "chef"), _client(server, "anna")
    kennung = f"~{STAMM}"
    assert anna.delete(f"/api/besprechungen/{kennung}").status_code == 404
    assert chef.put(f"/api/besprechungen/{kennung}/name", json={"name": "Vorstand"}).json() == {"titel": "Vorstand"}
    assert chef.delete(f"/api/besprechungen/{kennung}").status_code == 200
    assert not transkript.exists() and chef.get("/api/besprechungen").json() == []
    assert (server.tmp / "aus" / ".papierkorb").is_dir()
