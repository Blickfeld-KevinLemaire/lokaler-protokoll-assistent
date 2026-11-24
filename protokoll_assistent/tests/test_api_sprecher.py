"""Sprecher: bekannte Stimmen, Hoerprobe, Profil merken, Export, Profile verwalten -- ohne ffmpeg und ohne Modelle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.api import routen_sprecher
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.services import manifest_service, sprecher_export_service, sprecherprofil_service
from protokoll_assistent.tests.ablauf_hilfen import transkript_json_schreiben
from protokoll_assistent.tests.api_hilfen import Umgebung, app_bauen, eigene_konfiguration
from protokoll_assistent.utils import paths

STIMME = [0.1, 0.9, 0.3]


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Umgebung, str]:
    eigene_konfiguration(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "get_work_dir", lambda: tmp_path / "arbeit")
    monkeypatch.setattr(paths, "get_sprecherprofile_dir", lambda: tmp_path / "profile")
    routen_sprecher._hash_zwischenspeicher.clear()
    audio = tmp_path / "aufnahmen" / "sitzung.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"RIFF-audio")
    transkript = transkript_json_schreiben(tmp_path / "aus" / "sitzung_lokal_transkript_20260101_100000.json")
    daten = json.loads(transkript.read_text(encoding="utf-8"))
    daten["audio_pfad"] = str(audio)
    transkript.write_text(json.dumps(daten), encoding="utf-8")
    arbeit = manifest_service.get_work_dir_for_file(tmp_path / "arbeit", manifest_service.compute_file_hash(audio))
    sprecherprofil_service.speichere_lauf_embeddings(arbeit, {"SPEAKER_00": STIMME})
    return app_bauen(tmp_path), transkript.stem


def test_profil_merken_und_wiedererkennen(umgebung: tuple[Umgebung, str]) -> None:
    u, kennung = umgebung
    client = u.client
    leer = client.get(f"/api/besprechungen/{kennung}/sprecher/vorschlaege").json()
    assert leer == {"vorschlaege": {}, "stimmen_vorhanden": True}
    assert client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_99/profil", json={"name": "X"}).status_code == 404
    profil = client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/profil", json={"name": "Anna"}).json()
    assert profil["name"] == "Anna"
    # Derselbe Name noch einmal: das Profil wird ergaenzt, nicht verdoppelt.
    assert client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/profil", json={"name": "anna"}).status_code == 201
    assert client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/profil", json={"name": "  "}).status_code in (400, 422)
    erkannt = client.get(f"/api/besprechungen/{kennung}/sprecher/vorschlaege").json()["vorschlaege"]
    assert erkannt == {"SPEAKER_00": {"name": "Anna", "sicher": True}}
    liste = client.get("/api/sprecherprofile").json()
    assert [p["name"] for p in liste] == ["Anna"] and "embedding" not in liste[0]
    assert client.patch(f"/api/sprecherprofile/{profil['id']}", json={"name": "Anna B."}).json() == {"gespeichert": True}
    assert client.patch("/api/sprecherprofile/gibtsnicht", json={"name": "x"}).status_code == 400
    assert client.delete(f"/api/sprecherprofile/{profil['id']}").json() == {"geloescht": True}
    assert client.delete(f"/api/sprecherprofile/{profil['id']}").status_code == 404


def test_stimme_aus_dem_arbeitsordner_der_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # So legt die Pipeline es an: 'audio_pfad' ist die normalisierte Fassung IM Arbeitsordner (dessen Name der Hash
    # der Quelldatei ist), daneben Manifest und Stimmabdruecke. Frueher wurde der Hash der normalisierten Datei
    # gebildet -- ein anderer, leerer Ordner: "Stimme merken" scheiterte immer mit 409.
    eigene_konfiguration(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "get_work_dir", lambda: tmp_path / "arbeit")
    monkeypatch.setattr(paths, "get_sprecherprofile_dir", lambda: tmp_path / "profile")
    routen_sprecher._hash_zwischenspeicher.clear()
    arbeit = manifest_service.get_work_dir_for_file(tmp_path / "arbeit", "hash-der-quelldatei")
    (arbeit / manifest_service.MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    normalisiert = arbeit / "audio_normalisiert.wav"
    normalisiert.write_bytes(b"RIFF-normalisiert")
    sprecherprofil_service.speichere_lauf_embeddings(arbeit, {"SPEAKER_00": STIMME})
    transkript = transkript_json_schreiben(tmp_path / "aus" / "sitzung_lokal_transkript_20260101_100000.json")
    daten = json.loads(transkript.read_text(encoding="utf-8"))
    daten["audio_pfad"] = str(normalisiert)
    transkript.write_text(json.dumps(daten), encoding="utf-8")
    client = app_bauen(tmp_path).client
    kennung = transkript.stem
    assert client.get(f"/api/besprechungen/{kennung}/sprecher/vorschlaege").json()["stimmen_vorhanden"] is True
    assert client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/profil", json={"name": "Anna"}).status_code == 201
    assert sorted(p.name for p in (tmp_path / "arbeit").iterdir()) == ["hash-der-quelldatei"]


def test_ohne_audiodatei_keine_stimme(umgebung: tuple[Umgebung, str], tmp_path: Path) -> None:
    u, kennung = umgebung
    (tmp_path / "aufnahmen" / "sitzung.wav").unlink()
    assert u.client.get(f"/api/besprechungen/{kennung}/sprecher/vorschlaege").json()["stimmen_vorhanden"] is False
    assert u.client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/profil", json={"name": "A"}).status_code == 409


def test_hoerprobe_und_export(umgebung: tuple[Umgebung, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    u, kennung = umgebung
    erzeugt: list[Path] = []

    def hoerprobe(json_pfad: Path, sprecher_id: str, ziel: Path, **kw: Any) -> Path:
        erzeugt.append(ziel)
        ziel.write_bytes(b"RIFF-probe")
        return ziel

    monkeypatch.setattr(sprecher_export_service, "hoerprobe_erstellen", hoerprobe)
    antwort = u.client.get(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/hoerprobe")
    assert antwort.status_code == 200 and antwort.content == b"RIFF-probe" and antwort.headers["content-type"] == "audio/wav"
    u.client.get(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/hoerprobe")
    assert len(erzeugt) == 1  # zwischengespeichert
    assert u.client.get(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_99/hoerprobe").status_code == 404

    def export(json_pfad: Path, sprecher_id: str, ordner: Path, **kw: Any) -> tuple[Path, Path]:
        wav, txt = ordner / "sitzung_Sprecher 1.wav", ordner / "sitzung_Sprecher 1.txt"
        wav.write_bytes(b"RIFF")
        txt.write_text("Hallo", encoding="utf-8")
        return wav, txt

    monkeypatch.setattr(sprecher_export_service, "sprecher_exportieren", export)
    namen = [d["name"] for d in u.client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/export").json()["dateien"]]
    assert namen == ["sitzung_Sprecher 1.wav", "sitzung_Sprecher 1.txt"]
    dateien = {d["name"] for d in u.client.get(f"/api/besprechungen/{kennung}").json()["dateien"]}
    assert set(namen) <= dateien
    assert u.client.get(f"/api/besprechungen/{kennung}/dateien/sitzung_Sprecher 1.wav").headers["content-type"] == "audio/wav"

    def kaputt(*_a: Any, **_k: Any) -> Any:
        raise sprecher_export_service.SprecherExportFehler("keine Abschnitte")

    monkeypatch.setattr(sprecher_export_service, "sprecher_exportieren", kaputt)
    monkeypatch.setattr(sprecher_export_service, "hoerprobe_erstellen", kaputt)
    assert u.client.post(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/export").status_code == 422
    (tmp_path / "aus" / f"{kennung}.json").touch()  # neuer als die Hoerprobe: wird neu erzeugt
    import os
    import time

    spaeter = time.time() + 5
    os.utime(tmp_path / "aus" / f"{kennung}.json", (spaeter, spaeter))
    assert u.client.get(f"/api/besprechungen/{kennung}/sprecher/SPEAKER_00/hoerprobe").status_code == 422


def test_profile_je_nutzer_im_servermodus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from protokoll_assistent.api.kontext import Angemeldet

    monkeypatch.setattr(paths, "get_sprecherprofile_dir", lambda: tmp_path / "profile")
    assert routen_sprecher.profil_ordner(Angemeldet("anna", False, "anna")) == tmp_path / "profile" / "nutzer" / "anna"
    assert routen_sprecher.profil_ordner(Angemeldet("desktop", True, None)) == tmp_path / "profile"
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER, mehrbenutzer=True)
    assert u.dienste.nutzer is not None
    u.dienste.nutzer.anlegen("anna", admin=True)
    schluessel = u.dienste.nutzer.zugang_anlegen("anna", "x")
    assert u.client.get("/api/sprecherprofile", headers={"Authorization": f"Bearer {schluessel}"}).json() == []
