"""Ereignisbus: Reihenfolge, Nachholen ab einer Nummer, Luecken."""

from __future__ import annotations

import threading

from protokoll_assistent.ablauf.ereignisse import NEU_LADEN, Ereignis, Ereignisbus


def test_nummern_steigen_und_abo_bekommt_neue_ereignisse() -> None:
    bus = Ereignisbus()
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append)
    a = bus.senden("auftrag", {"id": "1"})
    b = bus.senden("auftrag", {"id": "2"})
    assert (a.nummer, b.nummer) == (1, 2)
    assert [e.nummer for e in empfangen] == [1, 2]
    assert bus.letzte_nummer == 2


def test_nachholen_ab_nummer() -> None:
    bus = Ereignisbus()
    for i in range(5):
        bus.senden("x", {"i": i})
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append, seit=3)
    assert [e.nummer for e in empfangen] == [4, 5]


def test_nichts_nachzuholen_wenn_aktuell() -> None:
    bus = Ereignisbus()
    bus.senden("x")
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append, seit=1)
    assert empfangen == []


def test_luecke_fuehrt_zu_neu_laden() -> None:
    bus = Ereignisbus(puffer_groesse=3)
    for _ in range(10):
        bus.senden("x")
    empfangen: list[Ereignis] = []
    bus.abonnieren(empfangen.append, seit=2)
    assert [e.art for e in empfangen] == [NEU_LADEN]


def test_abmelden_und_kaputtes_abo_stoert_andere_nicht() -> None:
    bus = Ereignisbus()
    empfangen: list[Ereignis] = []

    def kaputt(_ereignis: Ereignis) -> None:
        raise RuntimeError("kaputt")

    bus.abonnieren(kaputt)
    abo = bus.abonnieren(empfangen.append)
    assert bus.anzahl_abos == 2
    bus.senden("x")
    abo.beenden()
    abo.beenden()
    bus.senden("y")
    assert [e.art for e in empfangen] == ["x"]
    assert bus.anzahl_abos == 1


def test_als_dict() -> None:
    ereignis = Ereignis(3, "art", {"a": 1}, 12.5)
    assert ereignis.als_dict() == {"nummer": 3, "art": "art", "daten": {"a": 1}, "zeit": 12.5}


def test_reihenfolge_bei_gleichzeitigen_sendern() -> None:
    bus = Ereignisbus()
    empfangen: list[int] = []
    bus.abonnieren(lambda e: empfangen.append(e.nummer))

    def senden() -> None:
        for _ in range(200):
            bus.senden("x")

    faeden = [threading.Thread(target=senden) for _ in range(4)]
    for faden in faeden:
        faden.start()
    for faden in faeden:
        faden.join()
    assert empfangen == sorted(empfangen)
    assert len(empfangen) == 800
