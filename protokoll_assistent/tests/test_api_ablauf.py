"""Info, Zustand, Ereignisstrom, Auftraege, Dateien, Besprechungen, Export."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.ablauf.ereignisse import Ereignis
from protokoll_assistent.api import routen_system
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben
from protokoll_assistent.tests.api_hilfen import ZUGANG, Umgebung, app_bauen, eigene_konfiguration


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    return app_bauen(tmp_path)


def _verarbeitet(u: Umgebung) -> str:
    """Eine Besprechung durch Transkription und Auswertung schicken; gibt ihre Kennung zurueck."""
    antwort = u.client.post("/api/auftraege/transkription", json={"quelle": str(u.audio()), "mit_auswertung": True})
    assert antwort.status_code == 201, antwort.text
    u.auftraege_ausfuehren()
    besprechungen = u.client.get("/api/besprechungen").json()
    assert len(besprechungen) == 1
    return str(besprechungen[0]["id"])


def test_info_und_zustand(umgebung: Umgebung) -> None:
    info = umgebung.client.get("/api/info").json()
    assert info["rolle"] == "desktop" and info["angemeldet_als"] == "desktop"
    assert info["faehigkeiten"]["dateipfade"] and info["faehigkeiten"]["geraete_empfang"]
    zustand = umgebung.client.get("/api/zustand").json()
    assert zustand["auftraege"] == [] and zustand["empfang"]["aktiv"] is False
    assert isinstance(zustand["letzte_nummer"], int)


def test_ereignisstrom(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    umgebung.steuerung.bus.senden("hinweis", {"text": "Hallo"})
    aufrufe = iter([False, True])

    async def getrennt(self: Any) -> bool:
        return next(aufrufe)

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", getrennt)
    antwort = umgebung.client.get("/api/ereignisse", params={"seit": 0})
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("text/event-stream")
    assert "event: hinweis" in antwort.text and '"text":"Hallo"' in antwort.text


def test_ereignisstrom_herzschlag_und_last_event_id(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routen_system, "HERZSCHLAG_SEKUNDEN", 0.01)
    aufrufe = iter([False, True])

    async def getrennt(self: Any) -> bool:
        return next(aufrufe)

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", getrennt)
    antwort = umgebung.client.get("/api/ereignisse", headers={"Last-Event-ID": "0"})
    assert ": herzschlag" in antwort.text


def test_sse_zeile_ist_text() -> None:
    zeile = routen_system.sse_zeile(Ereignis(7, "auftrag", {"ä": 1}, 1.0))
    assert zeile.startswith("id: 7\nevent: auftrag\ndata: ") and zeile.endswith("\n\n") and "ä" in zeile


def test_transkription_und_auswertung_ueber_die_schnittstelle(umgebung: Umgebung) -> None:
    kennung = _verarbeitet(umgebung)
    auftraege = umgebung.client.get("/api/auftraege").json()
    assert [(a["art"], a["status"]) for a in auftraege] == [("transkription", "fertig"), ("auswertung", "fertig")]
    einer = umgebung.client.get(f"/api/auftraege/{auftraege[0]['id']}").json()
    assert einer["ergebnis"]["transkript_json"].endswith(".json")
    details = umgebung.client.get(f"/api/besprechungen/{kennung}").json()
    assert details["hat_protokoll"] and details["protokoll"]["text"].startswith("# Protokoll")
    assert details["sprecher"][0]["name"] == "Sprecher 1" and details["segmente"][0]["text"] == "Hallo zusammen."
    # Die Daten (JSON, Markdown) und Begleitdateien bleiben unter „Dateien“ verborgen.
    assert not {d["art"] for d in details["dateien"]} & {"json", "txt", "md", "srt", "vtt"}


def test_auswertung_einzeln_und_abbrechen(umgebung: Umgebung) -> None:
    transkript = transkript_json_schreiben(umgebung.tmp / "aus" / "x_lokal_transkript_20260101_100000.json")
    antwort = umgebung.client.post("/api/auftraege/auswertung", json={"transkript": str(transkript), "systemprompt": "Kurz"})
    assert antwort.status_code == 201
    auftrag_id = antwort.json()["id"]
    assert umgebung.client.delete(f"/api/auftraege/{auftrag_id}").json() == {"abgebrochen": True}
    assert umgebung.client.delete("/api/auftraege/gibtsnicht").status_code == 404
    assert umgebung.client.get("/api/auftraege/gibtsnicht").status_code == 404


def test_ablauffehler_wird_422_mit_code(umgebung: Umgebung) -> None:
    antwort = umgebung.client.post("/api/auftraege/transkription", json={"quelle": str(umgebung.tmp / "fehlt.wav")})
    assert antwort.status_code == 422
    assert antwort.json()["titel"] == "Datei nicht gefunden"
    antwort = umgebung.client.post("/api/auftraege/auswertung", json={"transkript": str(umgebung.tmp / "fehlt.json")})
    assert antwort.status_code == 422
    antwort = umgebung.client.post(
        "/api/auftraege/transkription", json={"quelle": str(umgebung.audio()), "min_sprecher": 5, "max_sprecher": 2}
    )
    assert antwort.status_code == 400


def test_servermodus_nur_freigegebene_ordner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    u.client.headers["Authorization"] = f"Bearer {ZUGANG}"
    fremd = tmp_path / "geheim" / "a.wav"
    fremd.parent.mkdir()
    fremd.write_bytes(b"RIFF")
    assert u.client.post("/api/auftraege/transkription", json={"quelle": str(fremd)}).status_code == 403
    erlaubt = u.client.post("/api/auftraege/transkription", json={"quelle": str(u.audio())})
    assert erlaubt.status_code == 201
    assert u.client.post("/api/system/ordner-oeffnen", json={"pfad": str(tmp_path)}).status_code == 403
    assert u.client.patch("/api/einstellungen", json={"ausgabeordner": str(tmp_path)}).status_code == 403


def test_hochladen_und_eingang(umgebung: Umgebung) -> None:
    client = umgebung.client
    antwort = client.post("/api/dateien/hochladen", files={"datei": ("../../Böse Datei!.WAV", b"RIFFdaten", "audio/wav")})
    assert antwort.status_code == 201
    daten = antwort.json()
    assert daten["name"] == "Böse Datei.wav" and Path(daten["pfad"]).parent == umgebung.tmp / "aufnahmen"
    zweite = client.post("/api/dateien/hochladen", files={"datei": ("Böse Datei!.wav", b"x", "audio/wav")})
    assert zweite.json()["name"] == "Böse Datei_1.wav"
    assert client.post("/api/dateien/hochladen", files={"datei": ("a.exe", b"MZ", "x")}).status_code == 415
    assert client.post("/api/dateien/hochladen", files={"datei": ("leer.wav", b"", "audio/wav")}).status_code == 400
    eingang = client.get("/api/dateien/eingang").json()
    assert {e["name"] for e in eingang} == {"Böse Datei.wav", "Böse Datei_1.wav"}


def test_eingang_mit_eingabeordner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eingabe = tmp_path / "eingabe"
    eingabe.mkdir()
    (eingabe / "a.mp3").write_bytes(b"ID3")
    (eingabe / "notiz.txt").write_text("x", encoding="utf-8")
    eigene_konfiguration(monkeypatch, tmp_path, eingabeordner=str(eingabe))
    u = app_bauen(tmp_path)
    assert [e["name"] for e in u.client.get("/api/dateien/eingang").json()] == ["a.mp3"]


def test_protokoll_bearbeiten_und_sprecher_umbenennen(umgebung: Umgebung) -> None:
    kennung = _verarbeitet(umgebung)
    client = umgebung.client
    assert client.put(f"/api/besprechungen/{kennung}/protokoll", json={"text": "# Neu\n"}).json()["gespeichert"]
    assert client.get(f"/api/besprechungen/{kennung}").json()["protokoll"]["text"] == "# Neu\n"
    antwort = client.put(f"/api/besprechungen/{kennung}/sprecher", json={"namen": {"SPEAKER_00": "Anna", "X": " "}})
    assert antwort.status_code == 200
    details = client.get(f"/api/besprechungen/{kennung}").json()
    assert details["sprecher"][0]["name"] == "Anna"


def test_protokoll_speichern_ohne_protokoll(umgebung: Umgebung) -> None:
    transkript_json_schreiben(umgebung.tmp / "aus" / "y_lokal_transkript_20260101_100000.json")
    kennung = "y_lokal_transkript_20260101_100000"
    assert umgebung.client.put(f"/api/besprechungen/{kennung}/protokoll", json={"text": "x"}).status_code == 409
    assert umgebung.client.post(f"/api/besprechungen/{kennung}/export", json={"inhalt": "beides", "formate": ["md"]}).status_code == 409
    assert umgebung.client.get("/api/besprechungen/gibtsnicht").status_code == 404


def test_dateien_herunterladen_nur_aus_der_besprechung(umgebung: Umgebung) -> None:
    kennung = _verarbeitet(umgebung)
    client = umgebung.client
    details = client.get(f"/api/besprechungen/{kennung}").json()
    assert details["dateien"] == []  # verborgen, aber herunterladbar
    md = next(p.name for p in (umgebung.tmp / "aus").glob("*_protokoll_*.md"))
    antwort = client.get(f"/api/besprechungen/{kennung}/dateien/{md}")
    assert antwort.status_code == 200 and antwort.headers["content-type"].startswith("text/markdown")
    (umgebung.tmp / "aus" / "fremd.txt").write_text("geheim", encoding="utf-8")
    assert client.get(f"/api/besprechungen/{kennung}/dateien/fremd.txt").status_code == 404
    assert client.get(f"/api/besprechungen/{kennung}/dateien/..%2Fkonfiguration.json").status_code == 404


def test_export_in_alle_textformate(umgebung: Umgebung) -> None:
    kennung = _verarbeitet(umgebung)
    formate = umgebung.client.get("/api/besprechungen/export/formate").json()
    assert {"docx", "pdf", "odt", "md"} <= {f["id"] for f in formate}
    antwort = umgebung.client.post(
        f"/api/besprechungen/{kennung}/export", json={"inhalt": "beides", "formate": ["md", "pdf", "odt", "docx", "srt"]}
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    namen = {Path(d["pfad"]).suffix for d in daten["dateien"]}
    assert namen == {".md", ".pdf", ".odt", ".docx"}
    assert any("srt" in f.lower() for f in daten["fehler"])
    pdf = next(Path(d["pfad"]) for d in daten["dateien"] if d["pfad"].endswith(".pdf"))
    assert pdf.read_bytes().startswith(b"%PDF")
    odt = next(Path(d["pfad"]) for d in daten["dateien"] if d["pfad"].endswith(".odt"))
    with zipfile.ZipFile(odt) as archiv:
        assert archiv.namelist()[0] == "mimetype"
        assert "Hallo zusammen." in archiv.read("content.xml").decode("utf-8")
    fehl = umgebung.client.post(f"/api/besprechungen/{kennung}/export", json={"inhalt": "transkript", "formate": ["gibtsnicht"]})
    assert fehl.status_code == 422


def test_oberflaeche_und_rueckfall_auf_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<html>VERMERK</html>", encoding="utf-8")
    (build / "app.js").write_text("console.log(1)", encoding="utf-8")
    u = app_bauen(tmp_path, oberflaeche=build)
    client = u.client
    client.headers.pop("Authorization")
    assert "VERMERK" in client.get("/").text
    assert client.get("/app.js").text == "console.log(1)"
    assert "VERMERK" in client.get("/besprechungen/abc").text
    assert client.get("/api/irgendwas").status_code == 404


def test_diagnose_und_laufzeit(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    from protokoll_assistent.utils import diagnostics

    monkeypatch.setattr(
        diagnostics, "run_diagnostics", lambda output_dir=None, **kw: [diagnostics.DiagnosticCheck("a", "A", True, "gut")]
    )
    assert umgebung.client.get("/api/system/diagnose").json() == [
        {"id": "a", "name": "A", "ok": True, "text": "gut", "kritisch": False}
    ]
    laufzeit = umgebung.client.get("/api/system/laufzeit").json()
    assert set(laufzeit) == {"lokale_transkription", "eingefroren", "python"}
    assert umgebung.client.post("/api/system/ordner-oeffnen", json={"pfad": str(umgebung.tmp / "nein")}).status_code == 404


def test_ordner_oeffnen_ausserhalb_von_windows(umgebung: Umgebung) -> None:
    umgebung.dienste.plattform_windows = False
    assert umgebung.client.post("/api/system/ordner-oeffnen", json={"pfad": str(umgebung.tmp)}).status_code == 501


def test_bibliothek_ordnet_aeltere_protokolle_zu(tmp_path: Path) -> None:
    from protokoll_assistent.ablauf import bibliothek

    aus = tmp_path / "aus"
    transkript_json_schreiben(aus / "m_lokal_transkript_20260101_100000.json")
    transkript_json_schreiben(aus / "m_lokal_transkript_20260102_100000.json")
    (aus / "m_protokoll_20260101_110000.json").write_text(json.dumps({"quelldatei_stamm": "m", "ergebnis": "alt"}), encoding="utf-8")
    (aus / "m_protokoll_20260103_110000.json").write_text(
        json.dumps({"quelldatei_stamm": "m", "ergebnis": "neu", "transkript_datei": "m_lokal_transkript_20260101_100000.json"}),
        encoding="utf-8",
    )
    (aus / "kaputt_lokal_transkript_20260101_100000.json").write_text("{", encoding="utf-8")
    (aus / "verwaist_protokoll_20260101_110000.json").write_text("{}", encoding="utf-8")
    liste = bibliothek.besprechungen(aus)
    assert [b.id for b in liste] == ["m_lokal_transkript_20260102_100000", "m_lokal_transkript_20260101_100000"]
    aelter = liste[1]
    assert sorted(p.zeit for p in aelter.protokolle) == ["20260101_110000", "20260103_110000"]
    assert bibliothek.details(aelter)["protokoll"]["text"] == "neu"
    assert bibliothek.besprechungen(tmp_path / "gibtsnicht") == []
