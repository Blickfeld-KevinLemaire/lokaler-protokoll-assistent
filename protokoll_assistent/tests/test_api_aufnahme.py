"""Mikrofonaufnahme ueber die Programmschnittstelle -- mit einem falschen recording_service, ohne Audiogeraet."""

from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.ablauf import aufnahme as aufnahme_modul
from protokoll_assistent.ablauf.aufnahme import Aufnahmesteuerung
from protokoll_assistent.ablauf.ereignisse import Ereignis, Ereignisbus
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.tests.api_hilfen import ZUGANG, Umgebung, app_bauen, eigene_konfiguration


@dataclass(frozen=True)
class Geraet:
    index: int
    name: str

    @property
    def anzeigename(self) -> str:
        return f"{self.name} (MME)"


class FalscheAufnahme:
    fehler_nach: int | None = None

    def __init__(self, geraet: Geraet, ziel: Path):
        self.geraet = geraet
        self.ziel = ziel
        self.ist_pausiert = False
        self.dauer_sekunden = 0.0
        self.pegel = 0.25
        self._abfragen = 0

    @property
    def fehler(self) -> str | None:
        self._abfragen += 1
        if self.fehler_nach is not None and self._abfragen > self.fehler_nach:
            return "Datenträger voll"
        return None

    def start(self) -> None:
        self.ziel.write_bytes(b"RIFF")

    def pause(self) -> None:
        self.ist_pausiert = True

    def fortsetzen(self) -> None:
        self.ist_pausiert = False

    def stop(self) -> Path:
        return self.ziel


def falsches_modul(geraete: list[Geraet]) -> types.ModuleType:
    modul = types.ModuleType("recording_service")
    modul.liste_aufnahmegeraete = lambda: list(geraete)  # type: ignore[attr-defined]
    modul.standard_eingabe_index = lambda: geraete[0].index if geraete else None  # type: ignore[attr-defined]

    def waehle(liste: list[Geraet], gespeichert: str | None, standard: int | None) -> tuple[Geraet | None, None]:
        if not liste:
            return None, None
        return next((g for g in liste if g.anzeigename == gespeichert), liste[0]), None

    modul.waehle_startgeraet = waehle  # type: ignore[attr-defined]
    modul.erzeuge_dateiname = lambda: "Aufnahme_test.wav"  # type: ignore[attr-defined]
    modul.MikrofonAufnahme = FalscheAufnahme  # type: ignore[attr-defined]
    return modul


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path)
    gemerkt: list[str] = []
    u.dienste.aufnahme = Aufnahmesteuerung(
        u.steuerung.bus,
        lambda: tmp_path / "aufnahmen",
        modul_laden=lambda: falsches_modul([Geraet(1, "Headset"), Geraet(2, "Konferenzmikrofon")]),
        konfiguration=lambda: {"aufnahmegeraet": "Konferenzmikrofon (MME)"},
        merken=gemerkt.append,
    )
    return u


def test_aufnahme_ablauf(umgebung: Umgebung) -> None:
    client = umgebung.client
    assert client.get("/api/info").json()["faehigkeiten"]["mikrofon"] in (True, False)
    geraete = client.get("/api/aufnahme/geraete").json()
    assert geraete == [
        {"name": "Headset (MME)", "standard": True, "gewaehlt": False},
        {"name": "Konferenzmikrofon (MME)", "standard": False, "gewaehlt": True},
    ]
    assert client.get("/api/aufnahme").json()["laeuft"] is False
    stand = client.post("/api/aufnahme/start", json={}).json()
    assert stand["laeuft"] and stand["geraet"] == "Konferenzmikrofon (MME)"  # das gemerkte Geraet
    assert client.post("/api/aufnahme/start", json={}).status_code == 409
    assert client.post("/api/aufnahme/pause").json()["pausiert"] is True
    assert client.post("/api/aufnahme/fortsetzen").json()["pausiert"] is False
    ende = client.post("/api/aufnahme/stopp").json()
    assert ende["name"] == "Aufnahme_test.wav" and Path(ende["pfad"]).is_file()
    assert client.post("/api/aufnahme/stopp").status_code == 409
    assert client.post("/api/aufnahme/pause").status_code == 409
    assert client.post("/api/aufnahme/fortsetzen").status_code == 409


def test_ohne_mikrofon_und_ohne_paket(tmp_path: Path) -> None:
    bus = Ereignisbus()
    ohne = Aufnahmesteuerung(bus, lambda: tmp_path, modul_laden=lambda: falsches_modul([]))
    with pytest.raises(aufnahme_modul.AufnahmeFehler, match="kein Mikrofon"):
        ohne.starten()

    def fehlt() -> types.ModuleType:
        raise ImportError("sounddevice")

    kaputt = Aufnahmesteuerung(bus, lambda: tmp_path, modul_laden=fehlt)
    assert kaputt.verfuegbar is False
    with pytest.raises(aufnahme_modul.AufnahmeFehler):
        kaputt.geraete()

    def abfrage_scheitert() -> list[Any]:
        raise OSError("PortAudio")

    modul = falsches_modul([Geraet(1, "x")])
    modul.liste_aufnahmegeraete = abfrage_scheitert  # type: ignore[attr-defined]
    with pytest.raises(aufnahme_modul.AufnahmeFehler, match="abfragen"):
        Aufnahmesteuerung(bus, lambda: tmp_path, modul_laden=lambda: modul).geraete()
    with pytest.raises(aufnahme_modul.AufnahmeFehler, match="abfragen"):
        Aufnahmesteuerung(bus, lambda: tmp_path, modul_laden=lambda: modul).starten()


def test_pegel_als_ereignis_und_abbruch_bei_schreibfehler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aufnahme_modul, "MELDE_ABSTAND_SEKUNDEN", 0.01)
    monkeypatch.setattr(FalscheAufnahme, "fehler_nach", 3)
    bus = Ereignisbus()
    ereignisse: list[Ereignis] = []
    bus.abonnieren(ereignisse.append)
    steuerung = Aufnahmesteuerung(bus, lambda: tmp_path, modul_laden=lambda: falsches_modul([Geraet(1, "x")]))
    assert steuerung.verfuegbar
    steuerung.starten()
    faden = steuerung._melder
    assert faden is not None
    faden.join(5)
    arten = [e.art for e in ereignisse]
    assert "aufnahme" in arten and "hinweis" in arten
    assert steuerung.stand()["laeuft"] is False


def test_mikrofon_oeffnen_scheitert(tmp_path: Path) -> None:
    modul = falsches_modul([Geraet(1, "x")])

    class Kaputt(FalscheAufnahme):
        def start(self) -> None:
            raise OSError("belegt")

    modul.MikrofonAufnahme = Kaputt  # type: ignore[attr-defined]
    with pytest.raises(aufnahme_modul.AufnahmeFehler, match="öffnen"):
        Aufnahmesteuerung(Ereignisbus(), lambda: tmp_path, modul_laden=lambda: modul).starten()


def test_nicht_im_servermodus_und_nicht_ohne_steuerung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    desktop = app_bauen(tmp_path)
    assert desktop.client.get("/api/aufnahme").status_code == 404
    server = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    server.client.headers["Authorization"] = f"Bearer {ZUGANG}"
    assert server.client.get("/api/aufnahme").status_code == 403


def test_zustand_enthaelt_die_aufnahme(umgebung: Umgebung) -> None:
    assert umgebung.client.get("/api/zustand").json()["aufnahme"]["laeuft"] is False
    umgebung.client.post("/api/aufnahme/start", json={})
    assert umgebung.client.get("/api/zustand").json()["aufnahme"]["laeuft"] is True
    umgebung.client.post("/api/aufnahme/stopp")
