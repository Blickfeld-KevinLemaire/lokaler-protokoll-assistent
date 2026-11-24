"""Eingangsordner des Servermodus: Dateien werden Auftraege in der gemeinsamen Warteschlange."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.ablauf.auftraege import Status
from protokoll_assistent.api import __main__ as start
from protokoll_assistent.api.sicherheit import ROLLE_SERVER
from protokoll_assistent.server import verarbeitung
from protokoll_assistent.server.eingang_wache import EingangsWache
from protokoll_assistent.server.einstellungen import ServerEinstellungen
from protokoll_assistent.tests.ablauf_hilfen import alle_auftraege_ausfuehren, steuerung_fuer_test
from protokoll_assistent.tests.api_hilfen import eigene_konfiguration


def _alt_machen(datei: Path) -> None:
    vorher = time.time() - 3600
    os.utime(datei, (vorher, vorher))


class Verarbeitung:
    def __init__(self) -> None:
        self.aufrufe: list[tuple[Path, Path]] = []
        self.status = verarbeitung.STATUS_FERTIG

    def __call__(self, datei: Path, einstellungen: ServerEinstellungen, **kw: Any) -> verarbeitung.Ergebnis:
        self.aufrufe.append((datei, einstellungen.ausgang))
        kw["protokollieren"]("laeuft")
        return verarbeitung.Ergebnis(self.status, datei, einstellungen.ausgang, fehler="kaputt" if self.status != verarbeitung.STATUS_FERTIG else None)


def _wache(tmp_path: Path, **kw: Any) -> tuple[EingangsWache, Verarbeitung, list[Any], Any]:
    steuerung, _ = steuerung_fuer_test({"ausgabeordner": str(tmp_path / "aus")})
    einstellungen = ServerEinstellungen(
        eingang=tmp_path / "ein", ausgang=tmp_path / "ausgang", stabil_sekunden=0, webhook_url="https://hook.example/x"
    )
    einstellungen.eingang.mkdir(parents=True)
    verarbeiten = Verarbeitung()
    webhooks: list[Any] = []
    wache = EingangsWache(
        steuerung,
        einstellungen,
        tmp_path / "zustand.json",
        verarbeiten=verarbeiten,
        webhook=lambda url, nutzlast, token: webhooks.append(nutzlast) or None,
        **kw,
    )
    return wache, verarbeiten, webhooks, steuerung


def test_datei_wird_auftrag_und_danach_verschoben(tmp_path: Path) -> None:
    wache, verarbeiten, webhooks, steuerung = _wache(tmp_path)
    datei = wache.einstellungen.eingang / "sitzung.wav"
    datei.write_bytes(b"RIFF")
    _alt_machen(datei)
    wache.einmal()  # erste Abfrage: Groesse merken
    auftraege = wache.einmal()
    assert len(auftraege) == 1 and auftraege[0].herkunft == "ordner"
    assert wache.einmal() == []  # nicht doppelt einreihen, solange er wartet
    alle_auftraege_ausfuehren(steuerung)
    assert auftraege[0].status is Status.FERTIG
    assert verarbeiten.aufrufe == [(datei, tmp_path / "aus")]  # Ergebnisse in den Ausgabeordner der Steuerung
    assert (wache.einstellungen.eingang / "verarbeitet" / "sitzung.wav").is_file()
    assert webhooks and webhooks[0]["status"] == verarbeitung.STATUS_FERTIG


def test_fehler_landet_im_fehlerordner(tmp_path: Path) -> None:
    wache, verarbeiten, webhooks, steuerung = _wache(tmp_path)
    verarbeiten.status = verarbeitung.STATUS_FEHLER
    datei = wache.einstellungen.eingang / "kaputt.wav"
    datei.write_bytes(b"RIFF")
    _alt_machen(datei)
    wache.einmal()
    auftrag = wache.einmal()[0]
    alle_auftraege_ausfuehren(steuerung)
    assert (auftrag.status, auftrag.fehler) == (Status.FEHLER, "kaputt")
    assert (wache.einstellungen.eingang / "fehler" / "kaputt.wav").is_file()
    assert webhooks[0]["status"] == verarbeitung.STATUS_FEHLER


def _eingereihte_datei(wache: EingangsWache, name: str) -> tuple[Path, Any]:
    datei = wache.einstellungen.eingang / name
    datei.write_bytes(b"RIFF")
    _alt_machen(datei)
    wache.einmal()  # erste Abfrage: Groesse merken
    return datei, wache.einmal()[0]


def test_beim_herunterfahren_abgebrochen_bleibt_im_eingang(tmp_path: Path) -> None:
    wache, _verarbeiten, webhooks, steuerung = _wache(tmp_path, besitzer="anna")
    datei, auftrag = _eingereihte_datei(wache, "lang.wav")
    assert auftrag.besitzer == "anna"
    wache.stoppen()  # so faehrt der Dienst herunter: erst die Wache, dann die Warteschlange
    steuerung.abbrechen(auftrag.id)
    assert datei.is_file() and not (wache.einstellungen.eingang / "fehler").exists() and webhooks == []
    assert len(wache.einmal()) == 1  # beim naechsten Start wieder dabei


def test_von_hand_abgebrochen_wird_nicht_wieder_eingereiht(tmp_path: Path) -> None:
    wache, _verarbeiten, webhooks, steuerung = _wache(tmp_path)
    datei, auftrag = _eingereihte_datei(wache, "lang.wav")
    steuerung.abbrechen(auftrag.id)
    assert auftrag.status is Status.ABGEBROCHEN
    assert not datei.exists() and (wache.einstellungen.eingang / "fehler" / "lang.wav").is_file()
    assert wache.einmal() == [] and wache.einmal() == []
    assert webhooks == [{"status": verarbeitung.STATUS_ABGEBROCHEN, "datei": "lang.wav", "fehler": None}]


def test_laufend_abgebrochen_endet_als_abgebrochen(tmp_path: Path) -> None:
    """Die Verarbeitung meldet einen Abbruch als Ergebnis -- der Auftrag darf dann nicht als "fertig" enden und die
    Datei nicht unter "verarbeitet" landen."""
    wache, verarbeiten, _webhooks, steuerung = _wache(tmp_path)
    verarbeiten.status = verarbeitung.STATUS_ABGEBROCHEN
    datei, auftrag = _eingereihte_datei(wache, "lang.wav")
    alle_auftraege_ausfuehren(steuerung)
    assert auftrag.status is Status.ABGEBROCHEN
    assert (wache.einstellungen.eingang / "fehler" / "lang.wav").is_file() and not datei.exists()
    assert wache.einmal() == []


def test_waehrend_des_abschlusses_nicht_doppelt_eingereiht(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zwischen dem Ende des Auftrags und dem Verschieben liegt die Datei noch im Eingang. Eine Abfrage in genau
    diesem Moment (die Wache laeuft in ihrem eigenen Faden) darf sie nicht ein zweites Mal einreihen."""
    wache, _verarbeiten, _webhooks, steuerung = _wache(tmp_path)
    datei, auftrag = _eingereihte_datei(wache, "sitzung.wav")
    zwischendurch: list[Any] = []
    merken = wache._zustand.merke

    def merke(schluessel: str, status: str, ausgabe: str | None = None) -> None:
        zwischendurch.extend(wache.einmal())
        merken(schluessel, status, ausgabe)

    monkeypatch.setattr(wache._zustand, "merke", merke)
    alle_auftraege_ausfuehren(steuerung)
    assert auftrag.status is Status.FERTIG and zwischendurch == []
    assert (wache.einstellungen.eingang / "verarbeitet" / "sitzung.wav").is_file() and not datei.exists()
    assert wache._eingereiht == set()


def test_wache_faden(tmp_path: Path) -> None:
    wache, _v, _w, _s = _wache(tmp_path)
    wache.einstellungen = ServerEinstellungen(eingang=tmp_path / "ein", ausgang=tmp_path / "x", abfrage_sekunden=0.01)
    wache.starten()
    wache.starten()
    wache.stoppen()
    assert wache._faden is not None
    wache._faden.join(2)


def test_eingang_einrichten_aus_der_umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path, ausgabeordner=None)
    monkeypatch.setattr(start.paths, "get_work_dir", lambda: tmp_path / "arbeit")
    dienste = start.dienste_erstellen(ROLLE_SERVER, None, mehrbenutzer=True)
    hinweise: list[str] = []
    dienste.steuerung.bus.abonnieren(lambda e: hinweise.append(e.daten.get("text", "")) if e.art == "hinweis" else None)
    assert start.eingang_einrichten(dienste, {}) is None
    assert start.eingang_einrichten(dienste, {"PROTOKOLL_EINGANG": str(tmp_path / "e"), "PROTOKOLL_GERAET": "gpu"}) is None
    assert any("Eingangsordner" in h for h in hinweise)
    wache = start.eingang_einrichten(
        dienste,
        {"PROTOKOLL_EINGANG": str(tmp_path / "e"), "PROTOKOLL_AUSGANG": str(tmp_path / "a"), "PROTOKOLL_EINGANG_NUTZER": "gibtsnicht"},
    )
    assert wache is not None and wache.besitzer is None
    assert any("gibtsnicht" in h for h in hinweise)
    assert dienste.steuerung.konfiguration()["ausgabeordner"] == str(tmp_path / "a")
    assert dienste.nutzer is not None
    dienste.nutzer.anlegen("anna", admin=True)
    wache = start.eingang_einrichten(dienste, {"PROTOKOLL_EINGANG": str(tmp_path / "e"), "PROTOKOLL_EINGANG_NUTZER": "anna"})
    assert wache is not None and wache.besitzer == "anna"


def test_eingang_nutzer_erst_nach_dem_start_angelegt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """README: Container starten, danach den ersten Admin anlegen. Der Nutzer aus PROTOKOLL_EINGANG_NUTZER fehlte beim
    Start -- bisher gehoerten deshalb alle Aufnahmen bis zum naechsten Neustart niemandem. Ausserdem bestimmt die
    Schreibweise der Nutzerliste den Ordner ("Anna" in der .env, Nutzer "anna")."""
    eigene_konfiguration(monkeypatch, tmp_path)
    monkeypatch.setattr(start.paths, "get_work_dir", lambda: tmp_path / "arbeit")
    dienste = start.dienste_erstellen(ROLLE_SERVER, None, mehrbenutzer=True)
    umgebung = {"PROTOKOLL_EINGANG": str(tmp_path / "e"), "PROTOKOLL_STABIL_SEKUNDEN": "0", "PROTOKOLL_EINGANG_NUTZER": "Anna"}
    wache = start.eingang_einrichten(dienste, umgebung)
    assert wache is not None and wache.besitzer is None
    wache.einstellungen.eingang.mkdir(parents=True)
    verarbeiten = Verarbeitung()
    wache._verarbeiten = verarbeiten
    assert dienste.nutzer is not None
    dienste.nutzer.anlegen("anna")  # erst jetzt, im laufenden Betrieb
    _datei, auftrag = _eingereihte_datei(wache, "sitzung.wav")
    assert auftrag.besitzer == "anna"
    alle_auftraege_ausfuehren(dienste.steuerung)
    assert verarbeiten.aufrufe[0][1] == dienste.steuerung.ausgabeordner("anna")
    assert dienste.steuerung.ausgabeordner("anna").name == "anna"
