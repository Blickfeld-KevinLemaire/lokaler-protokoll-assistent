"""Auftragsverwaltung: Vorrang, Abbruch, Fehler, gedrosselte Meldungen."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from protokoll_assistent.ablauf import auftraege
from protokoll_assistent.ablauf.auftraege import Auftragsverwaltung, Fortschritt, Status
from protokoll_assistent.ablauf.ereignisse import Ereignis, Ereignisbus
from protokoll_assistent.services import pipeline_service


class Uhr:
    def __init__(self) -> None:
        self.zeit = 1000.0

    def __call__(self) -> float:
        return self.zeit


@pytest.fixture
def bus() -> Ereignisbus:
    return Ereignisbus()


@pytest.fixture
def verwaltung(bus: Ereignisbus) -> Auftragsverwaltung:
    return Auftragsverwaltung(bus, jetzt=Uhr())


def test_reihenfolge_nach_vorrang_und_alter(verwaltung: Auftragsverwaltung) -> None:
    reihenfolge: list[str] = []

    def merken(name: str) -> Any:
        def funktion(_f: Fortschritt) -> dict[str, Any]:
            reihenfolge.append(name)
            return {"name": name}

        return funktion

    verwaltung.einreihen("t", "a", merken("a"))
    verwaltung.einreihen("t", "nachholen", merken("nachholen"), vorrang=auftraege.VORRANG_NACHHOLEN)
    verwaltung.einreihen("t", "b", merken("b"))
    verwaltung.einreihen("t", "freigabe", merken("freigabe"), vorrang=auftraege.VORRANG_FREIGABE)
    while verwaltung.ausfuehren_im_aufrufer():
        pass
    assert reihenfolge == ["freigabe", "a", "b", "nachholen"]
    assert all(a.status is Status.FERTIG for a in verwaltung.liste())
    assert [a.titel for a in verwaltung.liste()] == ["a", "nachholen", "b", "freigabe"]


def test_fehler_und_abbruch_der_pipeline(verwaltung: Auftragsverwaltung) -> None:
    def fehler(_f: Fortschritt) -> dict[str, Any]:
        raise ValueError("kaputt")

    def abbruch(_f: Fortschritt) -> dict[str, Any]:
        raise pipeline_service.PipelineCancelled

    def leer(_f: Fortschritt) -> None:
        raise RuntimeError

    a = verwaltung.einreihen("t", "fehler", fehler)
    b = verwaltung.einreihen("t", "abbruch", abbruch)
    c = verwaltung.einreihen("t", "leer", leer)
    while verwaltung.ausfuehren_im_aufrufer():
        pass
    assert (a.status, a.fehler) == (Status.FEHLER, "kaputt")
    assert b.status is Status.ABGEBROCHEN
    assert (c.status, c.fehler) == (Status.FEHLER, "RuntimeError")
    assert not verwaltung.ausfuehren_im_aufrufer()


def test_wartenden_abbrechen_ruft_nachfolger(verwaltung: Auftragsverwaltung) -> None:
    gesehen: list[Status] = []
    a = verwaltung.einreihen("t", "a", lambda f: {}, nach_ende=lambda auftrag: gesehen.append(auftrag.status))
    assert verwaltung.abbrechen(a.id)
    assert a.status is Status.ABGEBROCHEN
    assert gesehen == [Status.ABGEBROCHEN]
    assert not verwaltung.abbrechen(a.id)
    assert not verwaltung.abbrechen("gibt-es-nicht")
    assert not verwaltung.ausfuehren_im_aufrufer()


def test_laufenden_abbrechen_im_faden(bus: Ereignisbus) -> None:
    verwaltung = Auftragsverwaltung(bus)
    gestartet = threading.Event()

    def lang(f: Fortschritt) -> None:
        gestartet.set()
        while not f.abbruch_gewuenscht():
            gestartet.wait(0.01)
        return None

    verwaltung.starten()
    verwaltung.starten()  # zweimal harmlos
    try:
        auftrag = verwaltung.einreihen("t", "lang", lang)
        assert gestartet.wait(5)
        assert verwaltung.laufender() is auftrag
        assert verwaltung.abbrechen(auftrag.id)
        assert verwaltung.warten_bis_leer(5)
        assert auftrag.status is Status.ABGEBROCHEN
    finally:
        verwaltung.beenden()


def test_nachfolger_kann_folgeauftrag_einreihen(bus: Ereignisbus) -> None:
    verwaltung = Auftragsverwaltung(bus)
    reihenfolge: list[str] = []

    def zweiter(_f: Fortschritt) -> dict[str, Any]:
        reihenfolge.append("zweiter")
        return {}

    def nach_ende(auftrag: auftraege.Auftrag) -> None:
        reihenfolge.append(f"nach {auftrag.titel}")
        verwaltung.einreihen("t", "zweiter", zweiter)

    verwaltung.starten()
    try:
        verwaltung.einreihen("t", "erster", lambda f: reihenfolge.append("erster") or {}, nach_ende=nach_ende)
        assert verwaltung.warten_bis_leer(5)
    finally:
        verwaltung.beenden()
    assert reihenfolge == ["erster", "nach erster", "zweiter"]


def test_fehler_im_nachfolger_wird_gemeldet(verwaltung: Auftragsverwaltung, bus: Ereignisbus) -> None:
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append)

    def kaputt(_auftrag: auftraege.Auftrag) -> None:
        raise RuntimeError("Folgefehler")

    verwaltung.einreihen("t", "a", lambda f: {}, nach_ende=kaputt)
    verwaltung.ausfuehren_im_aufrufer()
    assert any(e.art == "fehler" and "Folgefehler" in e.daten["text"] for e in empfangen)


def test_fortschritt_meldungen_und_drosselung(bus: Ereignisbus) -> None:
    uhr = Uhr()
    verwaltung = Auftragsverwaltung(bus, jetzt=uhr)
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append)

    def arbeit(f: Fortschritt) -> dict[str, Any]:
        cb = f.callbacks()
        cb.on_stage("transkription", "Transkription")
        cb.on_chunk_progress(1, 4)  # innerhalb des Abstands: gedrosselt
        cb.on_overall_progress(0.25)
        uhr.zeit += 1
        cb.on_preview("Hallo")
        cb.on_log("Zeile")
        f.angaben(quelle="a.wav")
        assert not cb.should_cancel()
        assert f.auftrag_id
        return {"ok": True}

    auftrag = verwaltung.einreihen("t", "a", arbeit)
    verwaltung.ausfuehren_im_aufrufer()
    assert auftrag.stufe == "transkription"
    assert auftrag.abschnitt == (1, 4)
    assert auftrag.vorschau == "Hallo"
    assert auftrag.meldungen == ["Zeile"]
    assert auftrag.angaben == {"quelle": "a.wav"}
    assert auftrag.fortschritt == 1.0
    assert auftrag.ergebnis == {"ok": True}
    arten = [e.art for e in empfangen]
    assert "auftrag_meldung" in arten
    vorschauen = [e.daten.get("vorschau") for e in empfangen if e.art == "auftrag"]
    assert "Hallo" in vorschauen
    daten = auftrag.als_dict()
    assert daten["status"] == "fertig" and daten["abschnitt"] == [1, 4]


def test_nachmelden_schickt_gedrosseltes(bus: Ereignisbus) -> None:
    verwaltung = Auftragsverwaltung(bus, jetzt=Uhr())
    empfangen: list[Ereignis] = []

    def arbeit(f: Fortschritt) -> dict[str, Any]:
        f.stufe("a", "A")
        bus.abonnieren(empfangen.append)
        f.gesamt(0.5)  # gedrosselt
        verwaltung.nachmelden()
        return {}

    verwaltung.einreihen("t", "a", arbeit)
    verwaltung.ausfuehren_im_aufrufer()
    assert any(e.art == "auftrag" and e.daten["fortschritt"] == 0.5 for e in empfangen)


def test_erledigte_werden_begrenzt(verwaltung: Auftragsverwaltung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auftraege, "MAX_ERLEDIGTE", 2)
    for i in range(4):
        verwaltung.einreihen("t", str(i), lambda f: {})
        verwaltung.ausfuehren_im_aufrufer()
    assert len(verwaltung.liste()) == 2


def test_warten_bis_leer_mit_zeitlimit(verwaltung: Auftragsverwaltung) -> None:
    verwaltung.einreihen("t", "a", lambda f: {})
    assert not verwaltung.warten_bis_leer(0.05)
    assert verwaltung.laeuft_etwas()
    assert verwaltung.hole("nein") is None
