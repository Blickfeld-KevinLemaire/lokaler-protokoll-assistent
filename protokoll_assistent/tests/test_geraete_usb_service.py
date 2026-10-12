"""Tests fuer die Einrichtung der Aufnahmegeraete ueber USB (``services/geraete_usb_service.py``).

Statt eines echten Geraets antwortet eine Attrappe nach der Schnittstelle
(``GERAETE-SCHNITTSTELLE.md``, Abschnitt "Einrichtung über USB"). Es wird kein
serieller Anschluss geoeffnet.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from protokoll_assistent.services import geraete_usb_service as usb
from protokoll_assistent.services.geraete_usb_service import Einrichtung, Geraetesitzung, UsbFehler

TOKEN = "usb-token-fuer-tests-0123456789abcdefghijklm"


class GeraetAttrappe:
    """Ein Geraet am USB-Kabel: beantwortet die Anweisungen wie die Firmware."""

    def __init__(self, *, echo=False, protokollzeilen=True, stumm_fuer=0, aufnahme=False):
        self.echo, self.protokollzeilen, self.stumm_fuer, self.aufnahme = echo, protokollzeilen, stumm_fuer, aufnahme
        self.gespeichert: dict[str, str] = {}
        self.vorgemerkt: dict[str, str] = {}
        self.ausgang: list[bytes] = []
        self.gesendet: list[str] = []
        self.neu_gestartet = False
        self.geschlossen = False

    # -- serielle Schnittstelle --------------------------------------
    def write(self, daten: bytes) -> int:
        zeile = daten.decode("ascii").rstrip("\n")
        self.gesendet.append(zeile)
        if self.echo:
            self.ausgang.append(daten)
        if self.protokollzeilen:
            self.ausgang.append(b"I (1234) VERMERK: Aufnahme bereit\r\n")
        if self.stumm_fuer > 0:
            self.stumm_fuer -= 1
            return len(daten)
        antwort = self._bearbeiten(zeile)
        if antwort:
            self.ausgang.append(f"#VERMERK {antwort}\r\n".encode())
        return len(daten)

    def readline(self) -> bytes:
        return self.ausgang.pop(0) if self.ausgang else b""

    def close(self) -> None:
        self.geschlossen = True

    # -- Firmware-Verhalten ------------------------------------------
    def _bearbeiten(self, zeile: str) -> str | None:
        if not zeile.startswith("#VERMERK "):
            return None
        teile = zeile[len("#VERMERK "):].split(" ")
        befehl = teile[0]
        if befehl == "INFO":
            w = self.gespeichert
            return "INFO " + json.dumps(
                {
                    "geraete_id": "1a2b3c4d5e6f",
                    "board": "esp32-s3-audio",
                    "firmware": "1.0.0",
                    "eingerichtet": bool(w),
                    "wlan_hex": w.get("wlan_ssid", "").encode().hex(),
                    "pc_url_hex": w.get("pc_url", "").encode().hex(),
                    "server_url_hex": w.get("server_url", "").encode().hex(),
                    "token_pc": bool(w.get("pc_token")),
                    "token_server": bool(w.get("server_token")),
                },
                separators=(",", ":"),
            )
        if befehl == "SETZE":
            schluessel, wert = teile[1], bytes.fromhex(teile[2] if len(teile) > 2 else "").decode()
            if schluessel == "wlan_passwort" and wert and len(wert) < 8:
                return "FEHLER wlan_passwort zu kurz"
            self.vorgemerkt[schluessel] = wert
            return f"OK SETZE {schluessel}"
        if befehl == "SPEICHERN":
            if self.aufnahme:
                return "FEHLER SPEICHERN Aufnahme laeuft"
            self.gespeichert, self.vorgemerkt = dict(self.vorgemerkt), {}
            self.neu_gestartet = True
            return "OK SPEICHERN"
        if befehl == "VERWERFEN":
            self.vorgemerkt = {}
            return "OK VERWERFEN"
        if befehl == "LOESCHEN":
            self.gespeichert = {}
            return "OK LOESCHEN"
        return None


class Uhr:
    """Jeder Blick auf die Uhr kostet 0,1 s -- so laufen Zeitlimits ohne Warten ab."""

    def __init__(self):
        self.zeit = 0.0

    def __call__(self) -> float:
        self.zeit += 0.1
        return self.zeit


def einrichtung(**aenderungen) -> Einrichtung:
    werte = {"wlan_ssid": "Büro-WLAN \"5G\"", "wlan_passwort": "geheim123", "pc_url": "http://192.168.0.10:8765", "pc_token": TOKEN}
    return Einrichtung(**{**werte, **aenderungen})


# --------------------------------------------------------------------------
# Pruefung und Befehle
# --------------------------------------------------------------------------
def test_gueltige_einrichtung():
    assert einrichtung().fehler() == []
    assert einrichtung(wlan_passwort="").fehler() == []  # offenes WLAN
    assert einrichtung(pc_url="", pc_token="", server_url="http://server:8765", server_token=TOKEN).fehler() == []


@pytest.mark.parametrize(
    ("aenderung", "text"),
    [
        ({"wlan_ssid": ""}, "WLAN-Name"),
        ({"wlan_ssid": "x" * 33}, "WLAN-Name"),
        ({"wlan_ssid": "ä" * 17}, "WLAN-Name"),  # 34 Bytes
        ({"wlan_passwort": "kurz"}, "Passwort"),
        ({"wlan_passwort": "x" * 64}, "Passwort"),
        ({"pc_url": "https://pc:8765"}, "http://"),
        ({"pc_url": "http://"}, "http://"),
        ({"pc_url": "http://" + "x" * 90}, "96"),
        ({"pc_url": "http://pc:8765/"}, "ohne / am Ende"),
        ({"pc_url": "http://bür.o:8765"}, "http://Rechner"),
        ({"pc_url": "http://pc:8765/pfad"}, "http://Rechner"),
        ({"wlan_passwort": "pässwort1"}, "ASCII"),
        ({"wlan_ssid": "a\x00b"}, "WLAN-Name"),
        ({"pc_token": ""}, "Token"),
        ({"pc_token": "mit leerzeichen"}, "Token"),
        ({"pc_url": "", "pc_token": ""}, "Mindestens ein Ziel"),
        ({"erste_nummer": 0}, "erste Aufnahmenummer"),
    ],
)
def test_ungueltige_einrichtung(aenderung, text):
    assert any(text in m for m in einrichtung(**aenderung).fehler())


def test_befehle_sind_hex_und_vollstaendig():
    befehle = dict(einrichtung(erste_nummer=29).befehle())
    assert befehle["wlan_ssid"] == "#VERMERK SETZE wlan_ssid " + "Büro-WLAN \"5G\"".encode().hex()
    assert befehle["server_url"] == "#VERMERK SETZE server_url "  # leer: ersetzt die vorherige Einrichtung
    assert befehle["erste_nummer"].endswith("3239")  # "29"
    assert "erste_nummer" not in dict(einrichtung().befehle())
    assert all(z.isascii() and " " not in z.split(" ", 3)[-1] for z in befehle.values())


# --------------------------------------------------------------------------
# Ablauf mit dem Geraet
# --------------------------------------------------------------------------
@pytest.mark.parametrize("echo", [False, True])
def test_info_uebergeht_protokollzeilen_und_echo(echo):
    geraet = GeraetAttrappe(echo=echo)
    info = Geraetesitzung(geraet, jetzt=Uhr()).info()
    assert (info.geraete_id, info.board, info.firmware, info.eingerichtet) == ("1a2b3c4d5e6f", "esp32-s3-audio", "1.0.0", False)


def test_info_wiederholt_waehrend_das_geraet_startet():
    geraet = GeraetAttrappe(stumm_fuer=2)
    assert Geraetesitzung(geraet, jetzt=Uhr()).info().geraete_id == "1a2b3c4d5e6f"
    assert geraet.gesendet.count("#VERMERK INFO") == 3


def test_stummes_geraet_meldet_einen_fehler():
    with pytest.raises(UsbFehler, match="antwortet nicht"):
        Geraetesitzung(GeraetAttrappe(stumm_fuer=10), jetzt=Uhr()).info()


@pytest.mark.parametrize("antwort", ["{kaputt", '{"board":"x"}', '{"geraete_id":5}'])
def test_unbrauchbare_info(antwort):
    class Kaputt(GeraetAttrappe):
        def _bearbeiten(self, zeile):
            return "INFO " + antwort if zeile.endswith("INFO") else None

    with pytest.raises(UsbFehler, match="Antwort"):
        Geraetesitzung(Kaputt(), jetzt=Uhr()).info(versuche=1)


def test_einrichten_schreibt_alles_und_speichert():
    geraet = GeraetAttrappe()
    sitzung = Geraetesitzung(geraet, jetzt=Uhr())
    sitzung.einrichten(einrichtung())
    assert geraet.neu_gestartet
    assert geraet.gespeichert["wlan_ssid"] == "Büro-WLAN \"5G\"" and geraet.gespeichert["pc_token"] == TOKEN
    assert geraet.gesendet[0] == "#VERMERK VERWERFEN" and geraet.gesendet[-1] == "#VERMERK SPEICHERN"
    info = sitzung.info()
    assert info.eingerichtet and info.wlan == "Büro-WLAN \"5G\"" and info.pc_url == "http://192.168.0.10:8765"
    assert info.token_pc and not info.token_server
    # Token und Passwort tauchen in der Antwort nie auf.
    assert all(TOKEN not in z.decode() and "geheim123" not in z.decode() for z in geraet.ausgang)


def test_einrichten_prueft_vorher():
    geraet = GeraetAttrappe()
    with pytest.raises(UsbFehler, match="Passwort"):
        Geraetesitzung(geraet, jetzt=Uhr()).einrichten(einrichtung(wlan_passwort="kurz"))
    assert geraet.gesendet == []


def test_ablehnung_des_geraets_wird_gemeldet():
    class Streng(GeraetAttrappe):
        def _bearbeiten(self, zeile):
            if "SETZE pc_url" in zeile:
                return "FEHLER pc_url zu lang"
            return super()._bearbeiten(zeile)

    with pytest.raises(UsbFehler, match="lehnt 'pc_url' ab: zu lang"):
        Geraetesitzung(Streng(), jetzt=Uhr()).einrichten(einrichtung())


def test_speichern_waehrend_einer_aufnahme():
    geraet = GeraetAttrappe(aufnahme=True)
    with pytest.raises(UsbFehler, match="SPEICHERN' ab: Aufnahme laeuft"):
        Geraetesitzung(geraet, jetzt=Uhr()).einrichten(einrichtung())
    assert geraet.gespeichert == {}


def test_loeschen_und_schliessen():
    geraet = GeraetAttrappe()
    sitzung = Geraetesitzung(geraet, jetzt=Uhr())
    sitzung.einrichten(einrichtung())
    sitzung.loeschen()
    assert not sitzung.info().eingerichtet
    sitzung.schliessen()
    assert geraet.geschlossen


@pytest.mark.parametrize("wo", ["write", "readline"])
def test_abgerissene_verbindung(wo):
    geraet = GeraetAttrappe()

    def kaputt(*_a):
        raise OSError("Geraet entfernt")

    setattr(geraet, wo, kaputt)
    with pytest.raises(UsbFehler, match="gescheitert"):
        Geraetesitzung(geraet, jetzt=Uhr()).info(versuche=1)


def test_nach_neustart_wieder_verbinden():
    versuche: list[str] = []
    geraet = GeraetAttrappe()

    def oeffnen(port):
        versuche.append(port)
        if len(versuche) < 3:
            raise UsbFehler("COM5 gibt es gerade nicht")
        return geraet

    sitzung = usb.nach_neustart_verbinden("COM5", oeffnen, jetzt=Uhr(), schlafen=lambda _s: None)
    assert versuche == ["COM5"] * 3 and sitzung.info().geraete_id == "1a2b3c4d5e6f"


def test_nach_neustart_nicht_wieder_da():
    def nie(_port):
        raise UsbFehler("weg")

    with pytest.raises(UsbFehler, match="nicht wieder erreichbar"):
        usb.nach_neustart_verbinden("COM5", nie, zeitlimit=2, jetzt=Uhr(), schlafen=lambda _s: None)


def test_inventarzeile():
    info = usb.GeraeteInfo("1a2b3c4d5e6f", "esp32-c6", "esp32-c6/1.0.0", True, "", "", "", True, False)
    assert usb.inventarzeile(info, "C6-Lager", "2026-10-12") == "1a2b3c4d5e6f,esp32-c6,C6-Lager,1.0.0,2026-10-12,im-einsatz,,,"


# --------------------------------------------------------------------------
# pyserial
# --------------------------------------------------------------------------
def _pyserial_attrappe(monkeypatch, ports=(), oeffnen_fehler=None):
    serial = types.ModuleType("serial")
    tools = types.ModuleType("serial.tools")
    list_ports = types.ModuleType("serial.tools.list_ports")
    geoeffnet: list = []

    class SerialException(Exception):
        pass

    class Serial:
        def __init__(self):
            self.port = None
            self.dtr = self.rts = True

        def open(self):
            if oeffnen_fehler:
                raise SerialException(oeffnen_fehler)
            geoeffnet.append(self)

    serial.Serial = Serial
    serial.SerialException = SerialException
    list_ports.comports = lambda: list(ports)
    serial.tools = tools
    tools.list_ports = list_ports
    monkeypatch.setitem(sys.modules, "serial", serial)
    monkeypatch.setitem(sys.modules, "serial.tools", tools)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", list_ports)
    return geoeffnet


def test_anschluesse_espressif_zuerst(monkeypatch):
    port = types.SimpleNamespace
    _pyserial_attrappe(
        monkeypatch,
        [port(device="COM3", description="Bluetooth", vid=None), port(device="COM7", description="USB JTAG/serial debug unit", vid=0x303A)],
    )
    assert [(a.port, a.espressif) for a in usb.anschluesse_finden()] == [("COM7", True), ("COM3", False)]


def test_oeffnen_mit_dtr_und_rts_aus(monkeypatch):
    geoeffnet = _pyserial_attrappe(monkeypatch)
    verbindung = usb.verbindung_oeffnen("COM7")
    assert geoeffnet == [verbindung]
    assert (verbindung.port, verbindung.dtr, verbindung.rts, verbindung.baudrate) == ("COM7", False, False, 115200)


def test_oeffnen_gescheitert(monkeypatch):
    _pyserial_attrappe(monkeypatch, oeffnen_fehler="Zugriff verweigert")
    with pytest.raises(UsbFehler, match="serieller Monitor"):
        usb.verbindung_oeffnen("COM7")


def test_ohne_pyserial(monkeypatch):
    for name in ("serial", "serial.tools", "serial.tools.list_ports"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(UsbFehler, match="pyserial"):
        usb.anschluesse_finden()
    with pytest.raises(UsbFehler, match="pyserial"):
        usb.verbindung_oeffnen("COM7")
