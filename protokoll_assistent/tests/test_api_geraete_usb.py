"""Aufnahmegeraet per USB einrichten ueber die Programmschnittstelle -- mit der Geraete-Attrappe, ohne Anschluss."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.api import routen_geraete, routen_geraete_usb
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.services import firewall_service, geraete_empfang_service
from protokoll_assistent.services import geraete_usb_service as usb
from protokoll_assistent.tests.api_hilfen import ZUGANG, Umgebung, app_bauen, eigene_konfiguration
from protokoll_assistent.tests.test_geraete_usb_service import GeraetAttrappe
from protokoll_assistent.utils import app_config


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Umgebung, GeraetAttrappe]:
    eigene_konfiguration(monkeypatch, tmp_path)
    geraet = GeraetAttrappe(protokollzeilen=False)
    monkeypatch.setattr(routen_geraete_usb, "oeffnen", lambda port: geraet)
    monkeypatch.setattr(usb, "nach_neustart_verbinden", lambda port, oeffnen, **kw: usb.Geraetesitzung(oeffnen(port)))
    monkeypatch.setattr(routen_geraete.geraete_empfang_service, "lokale_adressen", lambda: ["192.168.1.20"])
    monkeypatch.setattr(routen_geraete_usb, "MELDUNG_ABWARTEN_SEKUNDEN", 0.0)
    return app_bauen(tmp_path), geraet


def test_anschluesse(umgebung: tuple[Umgebung, GeraetAttrappe], monkeypatch: pytest.MonkeyPatch) -> None:
    u, _ = umgebung
    monkeypatch.setattr(usb, "anschluesse_finden", lambda: [usb.Anschluss("COM5", "USB JTAG", True)])
    assert u.client.get("/api/geraete/usb/anschluesse").json() == [{"port": "COM5", "beschreibung": "USB JTAG", "vermerk": True}]

    def fehlt() -> list[Any]:
        raise usb.UsbFehler("pyserial fehlt")

    monkeypatch.setattr(usb, "anschluesse_finden", fehlt)
    assert u.client.get("/api/geraete/usb/anschluesse").status_code == 503


def test_erkennen_und_einrichten(umgebung: tuple[Umgebung, GeraetAttrappe]) -> None:
    u, geraet = umgebung
    erkannt = u.client.post("/api/geraete/usb/erkennen", json={"port": "COM5"}).json()
    assert erkannt["geraete_id"] == "1a2b3c4d5e6f" and erkannt["eingerichtet"] is False and erkannt["bekannt_als"] is None
    antwort = u.client.post(
        "/api/geraete/usb/einrichten",
        json={"port": "COM5", "name": "Raum-1", "wlan_ssid": "Buero", "wlan_passwort": "geheim123", "server_url": "http://server:8765", "server_token": "srv-token"},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["pc_url"] == "http://192.168.1.20:8765" and daten["info"]["fuer_pc"] and daten["info"]["fuer_server"]
    assert daten["erreicht"] is False  # die Attrappe meldet sich nie ueber das Netz
    assert geraet.gespeichert["wlan_ssid"] == "Buero" and geraet.gespeichert["pc_token"]
    konfig = app_config.load_config()
    assert konfig["geraete_empfang_aktiv"] is True
    eintrag = konfig["geraete_empfang_geraete"][0]
    assert eintrag["name"] == "Raum-1" and eintrag["geraete_id"] == "1a2b3c4d5e6f"
    assert geraet.gespeichert["pc_token"] not in str(konfig)  # nur der Hash wird gespeichert
    # Noch einmal einrichten: derselbe Eintrag wird ersetzt, nicht verdoppelt.
    assert u.client.post("/api/geraete/usb/erkennen", json={"port": "COM5"}).json()["bekannt_als"] == "Raum-1"
    u.client.post("/api/geraete/usb/einrichten", json={"port": "COM5", "name": "Raum-1", "wlan_ssid": "Buero", "wlan_passwort": "geheim123"})
    assert len(app_config.load_config()["geraete_empfang_geraete"]) == 1


def test_einrichten_fehlerfaelle(umgebung: tuple[Umgebung, GeraetAttrappe], monkeypatch: pytest.MonkeyPatch) -> None:
    u, geraet = umgebung
    basis = {"port": "COM5", "wlan_ssid": "Buero", "wlan_passwort": "geheim123"}
    assert u.client.post("/api/geraete/usb/einrichten", json={**basis, "name": "mit/strich"}).status_code == 400
    assert u.client.post("/api/geraete/usb/einrichten", json={**basis, "name": "R", "wlan_passwort": "kurz"}).status_code in (400, 422)
    app_config.update_config(geraete_empfang_geraete=[{"name": "Raum-1", "token_sha256": "a" * 64, "geraete_id": "anderes"}])
    assert u.client.post("/api/geraete/usb/einrichten", json={**basis, "name": "Raum-1"}).status_code == 409
    geraet.aufnahme = True  # das Geraet nimmt gerade auf: Speichern abgelehnt
    assert u.client.post("/api/geraete/usb/einrichten", json={**basis, "name": "Raum-2"}).status_code == 422
    monkeypatch.setattr(routen_geraete.geraete_empfang_service, "lokale_adressen", lambda: [])
    assert u.client.post("/api/geraete/usb/einrichten", json={**basis, "name": "Raum-3"}).status_code == 422

    def kaputt(port: str) -> Any:
        raise usb.UsbFehler("COM5 laesst sich nicht oeffnen")

    monkeypatch.setattr(routen_geraete_usb, "oeffnen", kaputt)
    assert u.client.post("/api/geraete/usb/erkennen", json={"port": "COM5"}).status_code == 422


def test_nach_neustart_nicht_eingerichtet(umgebung: tuple[Umgebung, GeraetAttrappe], monkeypatch: pytest.MonkeyPatch) -> None:
    u, _ = umgebung
    leer = GeraetAttrappe(protokollzeilen=False)
    monkeypatch.setattr(usb, "nach_neustart_verbinden", lambda port, oeffnen, **kw: usb.Geraetesitzung(leer))
    antwort = u.client.post("/api/geraete/usb/einrichten", json={"port": "COM5", "name": "R", "wlan_ssid": "W", "wlan_passwort": "geheim123"})
    assert antwort.status_code == 422 and "keine Einrichtung" in antwort.text


def test_nur_in_der_windows_anwendung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    u.client.headers["Authorization"] = f"Bearer {ZUGANG}"
    assert u.client.get("/api/geraete/usb/anschluesse").status_code == 403


def _kontakt(zeit: float) -> geraete_empfang_service.Kontakt:
    return geraete_empfang_service.Kontakt("1a2b3c4d5e6f", "1.0.0", "192.168.1.30", zeit)


def test_auf_meldung_warten() -> None:
    uhr = iter([0.0, 0.0, 0.6, 1.2, 1.8, 2.4, 3.0])
    geschlafen: list[float] = []
    stand: dict[str, geraete_empfang_service.Kontakt] = {"Raum-1": _kontakt(50.0)}  # alter Kontakt zaehlt nicht

    def kontakte() -> dict[str, geraete_empfang_service.Kontakt]:
        if len(geschlafen) == 2:
            stand["Raum-1"] = _kontakt(150.0)
        return dict(stand)

    assert routen_geraete_usb.auf_meldung_warten(kontakte, "Raum-1", 100.0, 5.0, geschlafen.append, lambda: next(uhr))
    assert len(geschlafen) == 2
    nie = iter([0.0, 0.0, 1.0, 2.0])
    assert not routen_geraete_usb.auf_meldung_warten(dict, "Raum-1", 100.0, 1.5, lambda s: None, lambda: next(nie))


def test_firewall_freigeben(umgebung: tuple[Umgebung, GeraetAttrappe], monkeypatch: pytest.MonkeyPatch) -> None:
    u, _ = umgebung
    u.dienste.plattform_windows = True
    ports: list[int] = []
    monkeypatch.setattr(firewall_service, "empfang_freigeben", ports.append)
    assert u.client.post("/api/geraete/firewall").json() == {"freigegeben": True}
    assert ports == [8765]
    assert u.client.get("/api/info").json()["faehigkeiten"]["firewall_freigabe"] in (True, False)

    def abgelehnt(port: int) -> None:
        raise firewall_service.FirewallFehler("Die Freigabe wurde nicht erlaubt.")

    monkeypatch.setattr(firewall_service, "empfang_freigeben", abgelehnt)
    antwort = u.client.post("/api/geraete/firewall")
    assert antwort.status_code == 422 and "nicht erlaubt" in antwort.text
    u.dienste.plattform_windows = False
    assert u.client.post("/api/geraete/firewall").status_code == 404


def test_firewall_nicht_im_servermodus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    u.client.headers["Authorization"] = f"Bearer {ZUGANG}"
    assert u.client.post("/api/geraete/firewall").status_code in (403, 404)
