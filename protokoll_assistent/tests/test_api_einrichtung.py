"""Ersteinrichtung ueber die Programmschnittstelle: Stand, Rechner, Kosten, Entscheidung, Auftraege (FFmpeg, Ollama,
Modelle), Anbieter, Spaeter und Abschluss. Kein Netz, keine Registry, keine Grafikkarte, kein Programmaufruf:
Jeder Dienstaufruf, der so etwas taete, ist hier ersetzt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent import bootstrap
from protokoll_assistent.api import routen_einrichtung
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.services import (
    ffmpeg_service,
    model_download_service,
    ollama_einrichtung_service,
    ollama_service,
    rechner_analyse_service,
    secret_store,
)
from protokoll_assistent.services.ollama_einrichtung_service import OllamaStatus, SignaturErgebnis
from protokoll_assistent.services.rechner_analyse_service import RechnerProfil
from protokoll_assistent.tests.api_hilfen import Umgebung, app_bauen, eigene_konfiguration
from protokoll_assistent.utils import app_config

# Laptop mit NVIDIA-Karte (8 GB) und 32 GB Arbeitsspeicher: Mitschrift und Protokoll laufen hier gut.
PROFIL = RechnerProfil(ram_gb=32.0, cpu_kerne=16, gpu_name="NVIDIA GeForce RTX 4060 Laptop GPU", vram_gb=8.0, freier_platz_gb=200.0)


class Rechner:
    """Was die Einrichtung auf diesem (gespielten) Rechner vorfindet."""

    def __init__(self) -> None:
        self.ffmpeg: Path | None = None
        self.ollama = OllamaStatus(installiert=False)
        self.ollama_modelle: list[str] = []
        self.laufzeit_auf_platte = False
        self.analysen = 0
        self.profil = PROFIL


@pytest.fixture
def rechner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Rechner:
    r = Rechner()
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: r.ffmpeg)
    monkeypatch.setattr(ffmpeg_service, "find_ffprobe", lambda: r.ffmpeg)
    monkeypatch.setattr(ollama_einrichtung_service, "ermittle_status", lambda **_k: r.ollama)

    def modelle_auflisten(*_a: Any, **_k: Any) -> list[str]:
        return list(r.ollama_modelle)

    monkeypatch.setattr(ollama_service, "list_models", modelle_auflisten)
    monkeypatch.setattr(routen_einrichtung, "laufzeit_eingerichtet", lambda: r.laufzeit_auf_platte)
    monkeypatch.setattr(model_download_service, "whisper_schon_geladen", lambda name: False)
    monkeypatch.setattr(model_download_service, "pyannote_schon_geladen", lambda: False)

    def analyse(ordner: Path) -> rechner_analyse_service.Analyse:
        r.analysen += 1
        return rechner_analyse_service.analysiere(r.profil)

    monkeypatch.setattr(routen_einrichtung, "analyse_ermitteln", analyse)
    monkeypatch.setattr(routen_einrichtung, "installer_ordner", lambda: tmp_path / "installer")
    # Nichts in die Registry des Entwicklerrechners (OLLAMA_IGPU_ENABLE).
    monkeypatch.setattr(ollama_einrichtung_service, "igpu_freischalten", lambda log, **_k: False)
    return r


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rechner: Rechner) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path)
    # Frische Installation: Dieser Dienst laeuft (noch) nicht in der Rechenumgebung.
    u.steuerung.abh.laufzeit_verfuegbar = lambda: False
    return u


def _auftrag(u: Umgebung, auftrag_id: str) -> dict[str, Any]:
    gefunden = u.steuerung.auftraege.hole(auftrag_id)
    assert gefunden is not None
    return gefunden.als_dict()


def _naechster_start_laedt(konfig: dict[str, Any]) -> bool:
    """Wuerde der naechste Start des Dienstes die Rechenumgebung laden (``api.__main__.rechenumgebung_vorbereiten``)?"""
    return bootstrap.laufzeit_beim_start_einrichten(konfig, fenster_moeglich=True, laufzeit_vorhanden=False)


# ---------------------------------------------------------------- Stand
def test_stand_einer_frischen_installation(umgebung: Umgebung) -> None:
    vorher = app_config.load_config()
    stand = umgebung.client.get("/api/einrichtung/stand").json()
    assert stand["einrichtung_abgeschlossen"] is False and stand["naechster_schritt"] == "willkommen"
    assert stand["arbeitsweise"] == {"transkription": "lokal", "nachbearbeitung": "lokal", "chatbot": "lokal"}
    assert set(stand["offen"]) == {"ffmpeg", "ollama", "sprachmodell", "einbettung", "laufzeit", "whisper", "pyannote"}
    assert stand["rechenumgebung_fehlt"] is True and stand["neustart_noetig"] is False
    assert stand["vorhanden"]["ollama"] is False and stand["vorhanden"]["hf_token"] is False
    assert stand["auftraege"] == [] and stand["geraete"] == 0
    # Nachsehen schreibt nichts.
    assert app_config.load_config() == vorher
    assert not _naechster_start_laedt(app_config.load_config())


def test_stand_mit_laufendem_ollama(umgebung: Umgebung, rechner: Rechner, monkeypatch: pytest.MonkeyPatch) -> None:
    rechner.ffmpeg = umgebung.tmp / "ffmpeg.exe"
    rechner.ollama = OllamaStatus(installiert=True, version="0.40.4", dienst_laeuft=True)
    rechner.ollama_modelle = [ollama_service.DEFAULT_MODEL, "bge-m3:latest"]
    stand = umgebung.client.get("/api/einrichtung/stand").json()
    assert stand["vorhanden"]["ollama_version"] == "0.40.4"
    assert stand["vorhanden"]["sprachmodell"] and stand["vorhanden"]["einbettung"]
    assert set(stand["offen"]) == {"laufzeit", "whisper", "pyannote"}

    def kaputt(*_a: Any, **_k: Any) -> list[str]:
        raise ollama_service.OllamaError("antwortet nicht")

    monkeypatch.setattr(ollama_service, "list_models", kaputt)
    assert umgebung.client.get("/api/einrichtung/stand").json()["vorhanden"]["ollama_modelle"] == []


def test_nur_in_der_windows_anwendung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rechner: Rechner) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    antwort = u.client.get("/api/einrichtung/stand", headers={"Authorization": "Bearer zugang-fuer-den-browser"})
    assert antwort.status_code == 403


# ---------------------------------------------------------------- Ihr Computer
def test_rechner_liefert_zahlen_und_empfehlung(umgebung: Umgebung, rechner: Rechner) -> None:
    antwort = umgebung.client.get("/api/einrichtung/rechner").json()
    assert [s["kennung"] for s in antwort["schritte"]] == ["mitschrift", "sprecher", "protokoll", "chat"]
    mitschrift = antwort["schritte"][0]
    assert mitschrift["stufe"] == "gut" and mitschrift["ort"] == "Grafikkarte"
    assert mitschrift["einheit"] == "minuten_je_stunde_aufnahme" and 0 < mitschrift["dauer_von"] <= mitschrift["dauer_bis"]
    assert antwort["schritte"][3]["einheit"] == "sekunden_je_frage"
    assert antwort["empfehlung"] == "lokal" and antwort["begruendung"]
    assert antwort["profil"]["nvidia_cuda"] is True and antwort["profil"]["arbeitsspeicher_gb"] == 32.0
    assert antwort["empfohlene_modelle"]["transkription"] and antwort["empfohlene_modelle"]["nachbearbeitung"]
    assert sum(m["empfohlen"] for m in antwort["sprachmodelle"]) == 1
    assert antwort["whisper_modelle"] and antwort["einbettungsmodelle"]
    # Einmal je Dienst ermittelt; mit ?neu=true erneut.
    umgebung.client.get("/api/einrichtung/rechner")
    assert rechner.analysen == 1
    umgebung.client.get("/api/einrichtung/rechner?neu=true")
    assert rechner.analysen == 2


def test_rechner_ohne_kenntnis_der_hardware(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    def scheitert(ordner: Path) -> rechner_analyse_service.Analyse:
        raise OSError("PowerShell fehlt")

    monkeypatch.setattr(routen_einrichtung, "analyse_ermitteln", scheitert)
    antwort = umgebung.client.get("/api/einrichtung/rechner")
    assert antwort.status_code == 200 and antwort.json()["profil"]["grafikkarte"] is None


# ---------------------------------------------------------------- Was noetig ist
def test_kosten_fuer_alles_lokal_und_als_vorschau(umgebung: Umgebung, rechner: Rechner) -> None:
    client = umgebung.client
    kosten = client.get("/api/einrichtung/kosten").json()
    kennungen = [b["kennung"] for b in kosten["bausteine"]]
    assert kennungen == ["ffmpeg", "ollama", "sprachmodell", "einbettung", "laufzeit", "whisper", "pyannote"]
    assert kosten["zustimmung_noetig"] and kosten["neustart_noetig"] and kosten["ollama_lizenz"]["lizenz_url"]
    assert kosten["download_gb"] > 5 and kosten["download_minuten_von"] < kosten["download_minuten_bis"]
    assert kosten["platz_knapp"] is False and kosten["annahme_mbit"] == 50
    # Vorschau "alles online": nur FFmpeg -- gespeichert wird dabei nichts.
    online = client.get("/api/einrichtung/kosten?transkription=api&nachbearbeitung=api&chatbot=api").json()
    assert [b["kennung"] for b in online["bausteine"]] == ["ffmpeg"] and online["ollama_lizenz"] is None
    assert online["neustart_noetig"] is False
    assert app_config.load_config()["transkription_modus"] == "lokal"
    rechner.ffmpeg = umgebung.tmp / "ffmpeg.exe"
    nichts = client.get("/api/einrichtung/kosten?transkription=api&nachbearbeitung=api&chatbot=api").json()
    assert nichts["download_gb"] == 0 and nichts["zustimmung_noetig"] is False
    assert client.get("/api/einrichtung/kosten?transkription=irgendwo").status_code == 422


def test_kosten_warnt_bei_knappem_platz(umgebung: Umgebung, rechner: Rechner) -> None:
    rechner.profil = RechnerProfil(ram_gb=16.0, cpu_kerne=8, freier_platz_gb=3.0)
    assert umgebung.client.get("/api/einrichtung/kosten").json()["platz_knapp"] is True


# ---------------------------------------------------------------- Arbeitsweise
def test_entscheidung_lokal_ohne_zustimmung_laedt_nie(umgebung: Umgebung) -> None:
    client = umgebung.client
    empfehlung = client.get("/api/einrichtung/rechner").json()["empfohlene_modelle"]
    gross = rechner_analyse_service.GROSSES_SPRACHMODELL
    stand = client.post(
        "/api/einrichtung/entscheidung",
        json={"transkription": "lokal", "nachbearbeitung": "lokal", "chatbot": "lokal", "sprachmodell": gross},
    ).json()
    konfig = app_config.load_config()
    assert konfig["whisper_modell"] == empfehlung["transkription"]
    assert konfig["ollama_modell"] == gross and konfig["chatbot_ollama_modell"] == gross
    assert konfig["lokale_einrichtung_zurueckgestellt"] is True and konfig["einrichtung_fortsetzen"] == ""
    assert stand["neustart_noetig"] is False and stand["rechenumgebung_fehlt"] is True
    assert not _naechster_start_laedt(konfig)
    # Auch nach einer schon einmal abgeschlossenen Einrichtung (Aufruf aus den Einstellungen) nicht.
    app_config.update_config(einrichtung_abgeschlossen=True)
    client.post("/api/einrichtung/entscheidung", json={"transkription": "lokal", "nachbearbeitung": "api", "chatbot": "api"})
    assert not _naechster_start_laedt(app_config.load_config())


def test_entscheidung_lokal_mit_zustimmung_startet_neu(umgebung: Umgebung) -> None:
    stand = umgebung.client.post(
        "/api/einrichtung/entscheidung",
        json={
            "transkription": "lokal",
            "nachbearbeitung": "lokal",
            "chatbot": "lokal",
            "whisper_modell": "small",
            "zustimmung_rechenumgebung": True,
        },
    ).json()
    konfig = app_config.load_config()
    assert konfig["einrichtung_fortsetzen"] == "transkription" and konfig["lokale_einrichtung_zurueckgestellt"] is False
    assert konfig["whisper_modell"] == "small"
    assert stand["neustart_noetig"] is True and stand["naechster_schritt"] == "neustart"
    assert _naechster_start_laedt(konfig)


def test_entscheidung_online_und_gemischt(umgebung: Umgebung) -> None:
    client = umgebung.client
    app_config.update_config(einrichtung_fortsetzen="transkription")
    stand = client.post(
        "/api/einrichtung/entscheidung", json={"transkription": "api", "nachbearbeitung": "api", "chatbot": "api"}
    ).json()
    konfig = app_config.load_config()
    assert (konfig["transkription_modus"], konfig["nachbearbeitung_modus"], konfig["chatbot_modus"]) == ("api", "api", "api")
    assert konfig["einrichtung_fortsetzen"] == "" and konfig["whisper_modell"] is None
    assert stand["online_ohne_anbieter"] == ["transkription", "nachbearbeitung", "chatbot"]
    assert stand["offen"] == ["ffmpeg"]
    # Sprachmodell nur, wenn das Protokoll lokal laeuft; eine eigene Wahl aus den Einstellungen bleibt.
    app_config.update_config(chatbot_ollama_modell="eigenes:7b")
    client.post(
        "/api/einrichtung/entscheidung",
        json={"transkription": "api", "nachbearbeitung": "lokal", "chatbot": "lokal", "sprachmodell": rechner_analyse_service.GROSSES_SPRACHMODELL},
    )
    konfig = app_config.load_config()
    assert konfig["ollama_modell"] == rechner_analyse_service.GROSSES_SPRACHMODELL
    assert konfig["chatbot_ollama_modell"] == "eigenes:7b"


def test_entscheidung_mit_vorhandener_rechenumgebung(umgebung: Umgebung, rechner: Rechner) -> None:
    client = umgebung.client
    lokal = {"transkription": "lokal", "nachbearbeitung": "lokal", "chatbot": "lokal"}
    rechner.laufzeit_auf_platte = True
    stand = client.post("/api/einrichtung/entscheidung", json=lokal).json()
    # Schon auf der Platte: kein Download, nur der Wechsel hinein -- dafuer muss der Dienst neu starten.
    assert stand["neustart_noetig"] is True and stand["rechenumgebung_fehlt"] is False
    assert app_config.load_config()["lokale_einrichtung_zurueckgestellt"] is False
    umgebung.steuerung.abh.laufzeit_verfuegbar = lambda: True
    stand = client.post("/api/einrichtung/entscheidung", json=lokal).json()
    assert stand["neustart_noetig"] is False and app_config.load_config()["einrichtung_fortsetzen"] == ""


def test_entscheidung_prueft_die_eingaben(umgebung: Umgebung) -> None:
    client = umgebung.client
    basis = {"transkription": "lokal", "nachbearbeitung": "lokal", "chatbot": "lokal"}
    assert client.post("/api/einrichtung/entscheidung", json={**basis, "whisper_modell": "riesig"}).status_code == 400
    assert client.post("/api/einrichtung/entscheidung", json={**basis, "sprachmodell": "gibtsnicht:1b"}).status_code == 400
    assert client.post("/api/einrichtung/entscheidung", json={**basis, "chatbot": "ueberspringen"}).status_code == 422
    assert app_config.load_config()["lokale_einrichtung_zurueckgestellt"] is False  # nichts geschrieben


# ---------------------------------------------------------------- Ollama
class FalscherInstaller:
    def __init__(self, tmp: Path, *, signatur_ok: bool = True, dienst_kommt: bool = True, download_fehler: str = ""):
        self.tmp = tmp
        self.signatur_ok = signatur_ok
        self.dienst_kommt = dienst_kommt
        self.download_fehler = download_fehler
        self.installiert: list[Path] = []
        self.datei: Path | None = None

    def einbauen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e = ollama_einrichtung_service
        monkeypatch.setattr(e, "lade_installer", self.laden)
        monkeypatch.setattr(e, "pruefe_signatur", self.pruefen)
        monkeypatch.setattr(e, "installiere_still", self.installiert.append)
        monkeypatch.setattr(e, "warte_auf_dienst", lambda **_k: self.dienst_kommt)

    def laden(self, ziel: Path, fortschritt: Any = None, **_k: Any) -> Path:
        if self.download_fehler:
            raise ollama_einrichtung_service.OllamaEinrichtungFehler(self.download_fehler)
        fortschritt(50, 100)
        fortschritt(100, 100)
        self.datei = self.tmp / "OllamaSetup.exe"
        self.datei.write_bytes(b"MZ")
        return self.datei

    def pruefen(self, pfad: Path) -> SignaturErgebnis:
        if self.signatur_ok:
            return SignaturErgebnis(True, "O=Ollama Inc.", "Signatur gültig: Ollama Inc.")
        return SignaturErgebnis(False, "O=Jemand", "Der Ollama-Installer ist von jemand anderem signiert (O=Jemand).")


def test_ollama_nur_mit_zustimmung(umgebung: Umgebung) -> None:
    client = umgebung.client
    antwort = client.post("/api/einrichtung/ollama", json={"zustimmung": False})
    assert antwort.status_code == 400 and "Zustimmung" in antwort.json()["detail"]
    assert client.post("/api/einrichtung/ollama", json={}).status_code == 422
    assert umgebung.steuerung.auftraege.liste() == []


def test_ollama_laden_pruefen_installieren(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    installer = FalscherInstaller(umgebung.tmp)
    installer.einbauen(monkeypatch)
    auftrag = umgebung.client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()
    assert auftrag["art"] == "einrichtung_ollama" and auftrag["status"] == "wartet"
    # Ein zweiter Aufruf reiht nichts Neues ein.
    assert umgebung.client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()["id"] == auftrag["id"]
    assert [a["id"] for a in umgebung.client.get("/api/einrichtung/stand").json()["auftraege"]] == [auftrag["id"]]
    umgebung.auftraege_ausfuehren()
    fertig = _auftrag(umgebung, auftrag["id"])
    assert fertig["status"] == "fertig" and fertig["fortschritt"] == 1.0
    assert any("Echtheit" in m for m in fertig["meldungen"]) and any("Signatur gültig" in m for m in fertig["meldungen"])
    assert installer.installiert == [installer.datei]
    assert installer.datei is not None and not installer.datei.exists()  # der Installer wird wieder entfernt


def test_ollama_mit_falscher_signatur_wird_nicht_ausgefuehrt(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    installer = FalscherInstaller(umgebung.tmp, signatur_ok=False)
    installer.einbauen(monkeypatch)
    auftrag = umgebung.client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()
    umgebung.auftraege_ausfuehren()
    gescheitert = _auftrag(umgebung, auftrag["id"])
    assert gescheitert["status"] == "fehler" and "jemand anderem signiert" in gescheitert["fehler"]
    assert installer.installiert == []
    assert installer.datei is not None and not installer.datei.exists()


def test_ollama_download_scheitert(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    FalscherInstaller(umgebung.tmp, download_fehler="Keine Verbindung zu ollama.com.").einbauen(monkeypatch)
    auftrag = umgebung.client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()
    umgebung.auftraege_ausfuehren()
    assert _auftrag(umgebung, auftrag["id"])["fehler"] == "Keine Verbindung zu ollama.com."


def test_ollama_installiert_aber_ohne_dienst(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch, rechner: Rechner) -> None:
    installer = FalscherInstaller(umgebung.tmp, dienst_kommt=False)
    installer.einbauen(monkeypatch)
    rechner.ollama = OllamaStatus(installiert=True, version="0.40.4", dienst_laeuft=False)
    auftrag = umgebung.client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()
    umgebung.auftraege_ausfuehren()
    gescheitert = _auftrag(umgebung, auftrag["id"])
    assert gescheitert["status"] == "fehler" and "antwortet aber nicht" in gescheitert["fehler"]
    assert installer.datei is None  # schon installiert: nie neu geladen


# ---------------------------------------------------------------- FFmpeg
def test_ffmpeg_laden(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch, rechner: Rechner) -> None:
    client = umgebung.client
    assert client.post("/api/einrichtung/ffmpeg", json={"zustimmung": False}).status_code == 400

    def laden(progress_cb: Any = None, **_k: Any) -> Path | None:
        progress_cb("FFmpeg wird geladen …")
        rechner.ffmpeg = umgebung.tmp / "ffmpeg.exe"
        return rechner.ffmpeg

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", laden)
    auftrag = client.post("/api/einrichtung/ffmpeg", json={"zustimmung": True}).json()
    assert client.post("/api/einrichtung/ffmpeg", json={"zustimmung": True}).json()["id"] == auftrag["id"]
    umgebung.auftraege_ausfuehren()
    assert _auftrag(umgebung, auftrag["id"])["status"] == "fertig"

    rechner.ffmpeg = None
    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", lambda progress_cb=None, **_k: None)
    auftrag = client.post("/api/einrichtung/ffmpeg", json={"zustimmung": True}).json()
    umgebung.auftraege_ausfuehren()
    assert "FFmpeg ließ sich nicht einrichten" in _auftrag(umgebung, auftrag["id"])["fehler"]


# ---------------------------------------------------------------- Modelle
def test_modelle_laedt_was_die_arbeitsweise_braucht(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch, rechner: Rechner) -> None:
    rechner.ollama = OllamaStatus(installiert=True, dienst_laeuft=True)
    geladen: list[str] = []

    def ziehen(name: str, progress_cb: Any = None, **_k: Any) -> None:
        progress_cb("pulling", 10, 20)
        geladen.append(name)
        rechner.ollama_modelle.append(name)

    monkeypatch.setattr(ollama_service, "pull_model", ziehen)
    monkeypatch.setattr(ollama_service, "is_model_available", lambda name, *a, **k: name in rechner.ollama_modelle)
    assert umgebung.client.post("/api/einrichtung/modelle", json={"zustimmung": False}).status_code == 400
    auftrag = umgebung.client.post("/api/einrichtung/modelle", json={"zustimmung": True}).json()
    assert auftrag["angaben"]["ollama_modelle"] == [ollama_service.DEFAULT_MODEL, "bge-m3"]
    umgebung.auftraege_ausfuehren()
    fertig = _auftrag(umgebung, auftrag["id"])
    assert fertig["status"] == "fertig" and geladen == [ollama_service.DEFAULT_MODEL, "bge-m3"]
    assert fertig["angaben"]["teile"] == {f"modell:{ollama_service.DEFAULT_MODEL}": True, "modell:bge-m3": True}
    # Danach fehlt nichts mehr: kein Auftrag ohne Inhalt.
    assert umgebung.client.post("/api/einrichtung/modelle", json={"zustimmung": True}).status_code == 400


def test_modelle_einzelne_fehlschlaege(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    neustarts: list[bool] = []

    def ziehen(name: str, progress_cb: Any = None, **_k: Any) -> None:
        if name == "kaputt":
            raise ollama_service.OllamaError("Verbindung abgerissen")

    monkeypatch.setattr(ollama_service, "pull_model", ziehen)
    monkeypatch.setattr(ollama_service, "dienst_starten", lambda *a, **k: neustarts.append(True) or True)
    monkeypatch.setattr(ollama_service, "is_model_available", lambda name, *a, **k: name != "halb")
    auftrag = umgebung.client.post(
        "/api/einrichtung/modelle", json={"zustimmung": True, "sprachmodelle": ["kaputt", "gut", "halb", " "]}
    ).json()
    umgebung.auftraege_ausfuehren()
    gescheitert = _auftrag(umgebung, auftrag["id"])
    assert gescheitert["status"] == "fehler" and "kaputt" in gescheitert["fehler"] and "halb" in gescheitert["fehler"]
    assert gescheitert["angaben"]["teile"] == {"modell:kaputt": False, "modell:gut": True, "modell:halb": False}
    assert len(neustarts) == 2  # drei Versuche, dazwischen je ein Neustart von Ollama


def test_mitschrift_braucht_die_rechenumgebung(umgebung: Umgebung) -> None:
    antwort = umgebung.client.post("/api/einrichtung/modelle", json={"zustimmung": True, "sprachmodelle": [], "whisper": True})
    assert antwort.status_code == 409 and "neu starten" in antwort.json()["detail"]


def test_mitschrift_mit_sprechererkennung(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    umgebung.steuerung.abh.laufzeit_verfuegbar = lambda: True
    app_config.update_config(einrichtung_fortsetzen="transkription")
    client = umgebung.client
    basis = {"zustimmung": True, "sprachmodelle": []}
    assert client.post("/api/einrichtung/modelle", json=basis).status_code == 400
    assert client.post("/api/einrichtung/modelle", json={**basis, "sprechertrennung": True}).status_code == 400  # kein Token
    assert client.post("/api/einrichtung/modelle", json={**basis, "whisper": True, "whisper_modell": "riesig"}).status_code == 400
    gemerkt: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: gemerkt.update({name: wert}))
    aufrufe: dict[str, Any] = {}

    def whisper(log: Any, model_name: str | None = None) -> bool:
        log("Whisper-Modell verfuegbar.")
        aufrufe["whisper"] = model_name
        return True

    def pyannote(log: Any, get_token: Any = None) -> bool:
        aufrufe["token"] = get_token()
        return True

    monkeypatch.setattr(model_download_service, "download_whisper_and_alignment", whisper)
    monkeypatch.setattr(model_download_service, "download_pyannote", pyannote)
    token = "hf_geheim_0123456789"
    auftrag = client.post(
        "/api/einrichtung/modelle",
        json={**basis, "whisper": True, "whisper_modell": "small", "sprechertrennung": True, "hf_token": token},
    ).json()
    assert auftrag["angaben"]["hf_token_gemerkt"] is True and gemerkt == {"hf_token": token}
    umgebung.auftraege_ausfuehren()
    fertig = _auftrag(umgebung, auftrag["id"])
    assert fertig["status"] == "fertig" and fertig["angaben"]["teile"] == {"whisper": True, "pyannote": True}
    assert aufrufe == {"whisper": "small", "token": token}
    konfig = app_config.load_config()
    assert konfig["whisper_modell"] == "small" and konfig["einrichtung_fortsetzen"] == ""
    # Der Schluessel taucht nirgends auf: weder im Auftrag noch in den Ereignissen noch in den Einstellungen.
    assert token not in str(fertig) and token not in str(konfig)
    gesehen: list[dict[str, Any]] = []
    umgebung.steuerung.bus.abonnieren(lambda e: gesehen.append(e.als_dict()), seit=0).beenden()
    assert gesehen and token not in str(gesehen)


def test_mitschrift_ohne_schluesselspeicher_und_mit_fehlschlag(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    umgebung.steuerung.abh.laufzeit_verfuegbar = lambda: True
    monkeypatch.setattr(model_download_service, "download_pyannote", lambda log, get_token=None: False)
    auftrag = umgebung.client.post(
        "/api/einrichtung/modelle", json={"zustimmung": True, "sprachmodelle": [], "sprechertrennung": True, "hf_token": "hf_x"}
    ).json()
    assert auftrag["angaben"]["hf_token_gemerkt"] is False  # kein Schluesselspeicher: nur fuer diese Sitzung
    umgebung.auftraege_ausfuehren()
    assert _auftrag(umgebung, auftrag["id"])["fehler"] == "Nicht geklappt: pyannote"


# ---------------------------------------------------------------- Anbieter
def test_anbieter_eintragen(umgebung: Umgebung) -> None:
    client = umgebung.client
    antwort = client.post(
        "/api/einrichtung/anbieter", json={"bereich": "transkription", "anbieter": "openrouter", "schluessel": "sk-1", "merken": True}
    ).json()
    assert antwort["endpunkt"] and antwort["adresse_vollstaendig"] and antwort["schluessel_vorhanden"]
    assert antwort["gemerkt"] is False  # kein Schluesselspeicher im Test: nur fuer die Sitzung
    konfig = app_config.load_config()
    assert konfig["api_transkription_voreinstellung"] == "openrouter" and konfig["api_transkription_schluessel_merken"] is True
    assert "sk-1" not in str(konfig)

    client.post("/api/einrichtung/anbieter", json={"bereich": "nachbearbeitung", "anbieter": "mistral", "schluessel": "sk-2"})
    konfig = app_config.load_config()
    assert konfig["api_nachbearbeitung_voreinstellung"] == "mistral" and konfig["api_nachbearbeitung_eigener_schluessel"] is True
    assert konfig["api_nachbearbeitung_endpunkt"] and konfig["api_nachbearbeitung_modell"]

    azure = client.post("/api/einrichtung/anbieter", json={"bereich": "chatbot", "anbieter": "azure"}).json()
    assert azure["adresse_vollstaendig"] is False and azure["schluessel_vorhanden"] is False
    konfig = app_config.load_config()
    assert konfig["chatbot_api_voreinstellung"] == "azure" and konfig["chatbot_api_embedding_endpunkt"]
    assert konfig["chatbot_api_eigener_schluessel"] is False

    eigen = client.post(
        "/api/einrichtung/anbieter",
        json={"bereich": "chatbot", "anbieter": "eigener", "endpunkt": "https://ki.example/v1/chat/completions", "modell": "m", "schluessel": "sk-3"},
    ).json()
    assert eigen["modell"] == "m" and eigen["schluessel_vorhanden"]
    assert app_config.load_config()["chatbot_api_eigener_schluessel"] is True


def test_anbieter_fehler(umgebung: Umgebung) -> None:
    client = umgebung.client
    assert client.post("/api/einrichtung/anbieter", json={"bereich": "chatbot", "anbieter": "gibtsnicht"}).status_code == 404
    assert client.post("/api/einrichtung/anbieter", json={"bereich": "transkription", "anbieter": "ionos"}).status_code == 400
    assert client.post("/api/einrichtung/anbieter", json={"bereich": "chatbot", "anbieter": "anthropic"}).status_code == 400
    assert client.post("/api/einrichtung/anbieter", json={"bereich": "nachbearbeitung", "anbieter": "eigener"}).status_code == 400
    assert client.post("/api/einrichtung/anbieter", json={"bereich": "irgendwas", "anbieter": "openai"}).status_code == 422


# ---------------------------------------------------------------- Spaeter, Abschluss
def test_spaeter_einrichten(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    client = umgebung.client
    FalscherInstaller(umgebung.tmp).einbauen(monkeypatch)
    vorher = app_config.load_config()
    auftrag = client.post("/api/einrichtung/ollama", json={"zustimmung": True}).json()
    stand = client.post("/api/einrichtung/spaeter", json={}).json()
    assert app_config.load_config() == vorher and stand["einrichtung_abgeschlossen"] is False
    assert _auftrag(umgebung, auftrag["id"])["status"] == "abgebrochen"  # was noch wartete, faellt heraus
    stand = client.post("/api/einrichtung/spaeter", json={"nicht_mehr_fragen": True}).json()
    konfig = app_config.load_config()
    assert stand["einrichtung_abgeschlossen"] is True and konfig["lokale_einrichtung_zurueckgestellt"] is True
    assert not _naechster_start_laedt(konfig)


def test_spaeter_nach_zustimmung(umgebung: Umgebung) -> None:
    app_config.update_config(einrichtung_fortsetzen="transkription")
    umgebung.client.post("/api/einrichtung/spaeter", json={"nicht_mehr_fragen": True})
    konfig = app_config.load_config()
    assert konfig["lokale_einrichtung_zurueckgestellt"] is False and konfig["einrichtung_fortsetzen"] == ""


def test_abschliessen_ohne_zustimmung(umgebung: Umgebung) -> None:
    stand = umgebung.client.post("/api/einrichtung/abschliessen").json()
    konfig = app_config.load_config()
    assert stand["einrichtung_abgeschlossen"] is True and stand["naechster_schritt"] == "fertig"
    assert konfig["lokale_einrichtung_zurueckgestellt"] is True and stand["neustart_noetig"] is False
    assert not _naechster_start_laedt(konfig)
    assert umgebung.client.get("/api/info").json()["einrichtung_abgeschlossen"] is True


def test_abschliessen_mit_zustimmung_und_online(umgebung: Umgebung) -> None:
    client = umgebung.client
    client.post(
        "/api/einrichtung/entscheidung",
        json={"transkription": "lokal", "nachbearbeitung": "api", "chatbot": "api", "zustimmung_rechenumgebung": True},
    )
    stand = client.post("/api/einrichtung/abschliessen").json()
    konfig = app_config.load_config()
    assert stand["neustart_noetig"] is True and konfig["einrichtung_fortsetzen"] == "transkription"
    assert konfig["lokale_einrichtung_zurueckgestellt"] is False and _naechster_start_laedt(konfig)
    assert stand["online_ohne_anbieter"] == ["nachbearbeitung", "chatbot"]


def test_nach_dem_neustart_weiter_mit_der_mitschrift(umgebung: Umgebung) -> None:
    app_config.update_config(einrichtung_fortsetzen="transkription")
    umgebung.steuerung.abh.laufzeit_verfuegbar = lambda: True
    stand = umgebung.client.get("/api/einrichtung/stand").json()
    assert stand["naechster_schritt"] == "mitschrift" and stand["neustart_noetig"] is False
    stand = umgebung.client.post("/api/einrichtung/abschliessen").json()
    assert app_config.load_config()["einrichtung_fortsetzen"] == "" and stand["rechenumgebung_fehlt"] is False
