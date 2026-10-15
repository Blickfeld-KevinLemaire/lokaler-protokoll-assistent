"""Tests fuer den Empfang der WLAN-Aufnahmegeraete (``services/geraete_empfang_service.py``).

Die Ablage wird direkt geprueft; die HTTP-Schicht ueber einen echten Dienst auf
127.0.0.1 mit einem vom System vergebenen Port -- so laeuft auch genau der
Code, den die Geraete erreichen. Es verlaesst nichts den Rechner.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from protokoll_assistent.services import frage_service
from protokoll_assistent.services import geraete_empfang_service as empfang
from protokoll_assistent.services.geraete_empfang_service import Ablage, Geraet, GeraeteEmpfang

TOKEN = "geraete-token-fuer-tests-0123456789abcdefghijk"
TOKEN_ZWEI = "zweites-geraete-token-0123456789abcdefghijklm"


def sha(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def leser(daten: bytes):
    """Wie 'rfile.read': liefert die Daten in den angeforderten Bloecken."""
    position = 0

    def lesen(anzahl: int) -> bytes:
        nonlocal position
        block = daten[position : position + anzahl]
        position += len(block)
        return block

    return lesen


def nie_lesen(_anzahl: int) -> bytes:
    raise AssertionError("Der Inhalt einer abgelehnten Anfrage darf nicht gelesen werden.")


@pytest.fixture
def ablage(tmp_path: Path) -> Ablage:
    return Ablage(tmp_path / "eingang", freier_platz=lambda _pfad: 10**12)


def hochladen(ablage: Ablage, geraet: str, datei: str, daten: bytes, stueck: int = 7) -> empfang.Antwort:
    for start in range(0, len(daten), stueck):
        teil = daten[start : start + stueck]
        antwort = ablage.anhaengen(geraet, datei, start, len(teil), leser(teil))
        assert antwort.status == 200, antwort
    return ablage.anhaengen(geraet, datei, len(daten), 0, leser(b""), len(daten), sha(daten))


# --------------------------------------------------------------------------
# Token und Geraete
# --------------------------------------------------------------------------
def test_token_ist_lang_zufaellig_und_url_sicher():
    token = empfang.token_erzeugen()
    assert len(token) == 43 and token != empfang.token_erzeugen()
    assert all(z.isalnum() or z in "-_" for z in token)
    assert empfang.token_hash(token) == hashlib.sha256(token.encode()).hexdigest()


def test_geraete_aus_text():
    h1, h2 = empfang.token_hash("a"), empfang.token_hash("b")
    geraete = empfang.geraete_aus_text(f" S3-Audio:{h1.upper()} , C6:{h2},")
    assert geraete == (Geraet("S3-Audio", h1), Geraet("C6", h2))
    assert empfang.geraete_aus_text("") == ()


@pytest.mark.parametrize(
    ("text", "meldung"),
    [
        ("S3-Audio", "Name:SHA256"),
        ("S3 Audio:" + "a" * 64, "Name:SHA256"),
        ("S3:abc", "SHA-256"),
        ("S3:" + "a" * 64 + ",s3:" + "b" * 64, "mehrfach"),
    ],
)
def test_geraete_aus_text_meldet_fehler(text, meldung):
    with pytest.raises(ValueError, match=meldung):
        empfang.geraete_aus_text(text)


def test_geraete_aus_konfiguration_uebergeht_unbrauchbares():
    h = empfang.token_hash("x")
    eintraege = [
        {"name": "S3", "token_sha256": h},
        {"name": "s3", "token_sha256": h},  # doppelt
        {"name": "../boese", "token_sha256": h},
        {"name": "C6", "token_sha256": "kurz"},
        "kein Objekt",
    ]
    assert empfang.geraete_aus_konfiguration(eintraege) == (Geraet("S3", h),)


def test_geraet_zum_token():
    geraete = (Geraet("A", empfang.token_hash(TOKEN)), Geraet("B", empfang.token_hash(TOKEN_ZWEI)))
    assert empfang.geraet_zum_token(TOKEN_ZWEI, geraete) == geraete[1]
    assert empfang.geraet_zum_token("falsch", geraete) is None
    assert empfang.geraet_zum_token("", geraete) is None


@pytest.mark.parametrize(
    ("name", "gueltig"),
    [
        ("H5_007.opus", True),
        ("H5_007.OPUS", True),
        ("aufnahme-1.wav", True),
        ("NUL.opus", True),  # wird mit Geraetenamen davor abgelegt, siehe unten
        ("../H5_007.opus", False),
        ("ordner/H5.opus", False),
        ("H5.exe", False),
        ("H5", False),
        (".opus", False),
        ("x" * 64 + ".opus", True),
        ("x" * 65 + ".opus", False),
        ("H5%2F.opus", False),
    ],
)
def test_dateiname_gueltig(name, gueltig):
    assert empfang.dateiname_gueltig(name) is gueltig


def test_lokale_adressen_liefert_keine_loopback_adressen():
    adressen = empfang.lokale_adressen()
    assert all(isinstance(a, str) and not a.startswith("127.") for a in adressen)


def test_lokale_adressen_ohne_netz(monkeypatch):
    def kaputt(*_args, **_kwargs):
        raise OSError("kein Netz")

    monkeypatch.setattr(empfang.socket, "socket", kaputt)
    monkeypatch.setattr(empfang.socket, "getaddrinfo", kaputt)
    assert empfang.lokale_adressen() == []


# --------------------------------------------------------------------------
# Ablage
# --------------------------------------------------------------------------
def test_vollstaendiger_upload_legt_die_datei_auf_einen_schlag_ab(tmp_path):
    gemeldet: list[tuple[Path, str]] = []
    ablage = Ablage(tmp_path / "eingang", freier_platz=lambda _p: 10**12, bei_neuer_aufnahme=lambda p, g: gemeldet.append((p, g)))
    daten = os.urandom(100)

    antwort = hochladen(ablage, "S3-Audio", "H5_007.opus", daten)

    ziel = tmp_path / "eingang" / "S3-Audio_H5_007.opus"
    assert antwort.daten == {"naechstes_byte": 100, "fertig": True, "datei": ziel.name}
    assert ziel.read_bytes() == daten
    assert gemeldet == [(ziel, "S3-Audio")]
    assert list((tmp_path / "eingang" / ".empfang").glob("*.teil")) == []
    # Nach dem Abschluss beginnt derselbe Name wieder bei 0.
    assert ablage.stand("S3-Audio", "H5_007.opus").daten == {"naechstes_byte": 0, "fertig": False}


def test_stand_zeigt_den_fortschritt_fuer_die_wiederaufnahme(ablage):
    assert ablage.stand("S3", "H5_001.opus").daten["naechstes_byte"] == 0
    ablage.anhaengen("S3", "H5_001.opus", 0, 5, leser(b"12345"))
    assert ablage.stand("S3", "H5_001.opus").daten == {"naechstes_byte": 5, "fertig": False}
    # Anderes Geraet, gleicher Name: eigener Stand.
    assert ablage.stand("C6", "H5_001.opus").daten["naechstes_byte"] == 0


def test_falscher_offset_wird_abgelehnt_ohne_den_inhalt_zu_lesen(ablage):
    ablage.anhaengen("S3", "H5_001.opus", 0, 5, leser(b"12345"))
    antwort = ablage.anhaengen("S3", "H5_001.opus", 3, 5, nie_lesen)
    assert antwort.status == 409
    assert antwort.daten["naechstes_byte"] == 5 and antwort.daten["fertig"] is False
    assert b'"naechstes_byte":5' in antwort.als_bytes() and b" " not in antwort.als_bytes().split(b'"fehler"')[0]


def test_unvollstaendiges_stueck_wird_zurueckgenommen(ablage):
    ablage.anhaengen("S3", "H5_001.opus", 0, 4, leser(b"abcd"))
    antwort = ablage.anhaengen("S3", "H5_001.opus", 4, 10, leser(b"efg"))  # Verbindung bricht ab
    assert antwort.status == 400 and antwort.daten["naechstes_byte"] == 4
    assert ablage.stand("S3", "H5_001.opus").daten["naechstes_byte"] == 4
    assert ablage.anhaengen("S3", "H5_001.opus", 4, 3, leser(b"efg")).daten["naechstes_byte"] == 7


def test_schreibfehler_wird_als_unvollstaendig_gemeldet(ablage):
    def kaputt(_anzahl):
        raise OSError("Platte voll")

    antwort = ablage.anhaengen("S3", "H5_001.opus", 0, 4, kaputt)
    assert antwort.status == 400
    assert ablage.stand("S3", "H5_001.opus").daten["naechstes_byte"] == 0


def test_falsche_pruefsumme_verwirft_den_teilstand(ablage):
    ablage.anhaengen("S3", "H5_001.opus", 0, 4, leser(b"abcd"))
    antwort = ablage.anhaengen("S3", "H5_001.opus", 4, 0, leser(b""), 4, sha(b"ABCD"))
    assert antwort.status == 422 and antwort.daten["naechstes_byte"] == 0
    assert ablage.stand("S3", "H5_001.opus").daten["naechstes_byte"] == 0
    assert not (ablage.ziel / "S3_H5_001.opus").exists()


def test_falsche_gesamtgroesse_verwirft_den_teilstand(ablage):
    ablage.anhaengen("S3", "H5_001.opus", 0, 4, leser(b"abcd"))
    antwort = ablage.anhaengen("S3", "H5_001.opus", 4, 0, leser(b""), 5, sha(b"abcd"))
    assert antwort.status == 422 and "Groesse" in antwort.daten["fehler"]
    assert ablage.stand("S3", "H5_001.opus").daten["naechstes_byte"] == 0


def test_abschluss_im_letzten_stueck_mit_inhalt(ablage):
    antwort = ablage.anhaengen("S3", "H5_001.opus", 0, 4, leser(b"abcd"), 4, sha(b"abcd"))
    assert antwort.daten["fertig"] is True
    assert (ablage.ziel / "S3_H5_001.opus").read_bytes() == b"abcd"


def test_wiederholte_aufnahme_erzeugt_keine_zweite_datei(ablage):
    daten = b"dieselbe aufnahme"
    erste = hochladen(ablage, "S3", "H5_001.opus", daten)
    zweite = hochladen(ablage, "S3", "H5_001.opus", daten)
    assert erste.daten == zweite.daten
    assert sorted(p.name for p in ablage.ziel.iterdir() if p.is_file()) == ["S3_H5_001.opus"]


def test_gleicher_name_mit_anderem_inhalt_bekommt_eine_nummer(ablage):
    hochladen(ablage, "S3", "H5_001.opus", b"erste")
    antwort = hochladen(ablage, "S3", "H5_001.opus", b"zweite, andere")
    assert antwort.daten["datei"] == "S3_H5_001_2.opus"
    assert (ablage.ziel / "S3_H5_001.opus").read_bytes() == b"erste"
    assert (ablage.ziel / "S3_H5_001_2.opus").read_bytes() == b"zweite, andere"


def test_zwei_geraete_mit_gleichem_dateinamen_kommen_sich_nicht_in_die_quere(ablage):
    ablage.anhaengen("S3", "H5_001.opus", 0, 3, leser(b"aaa"))
    ablage.anhaengen("C6", "H5_001.opus", 0, 3, leser(b"bbb"))
    ablage.anhaengen("S3", "H5_001.opus", 3, 0, leser(b""), 3, sha(b"aaa"))
    ablage.anhaengen("C6", "H5_001.opus", 3, 0, leser(b""), 3, sha(b"bbb"))
    assert (ablage.ziel / "S3_H5_001.opus").read_bytes() == b"aaa"
    assert (ablage.ziel / "C6_H5_001.opus").read_bytes() == b"bbb"


def test_reservierter_windows_name_wird_sicher_abgelegt(ablage):
    hochladen(ablage, "S3", "NUL.opus", b"inhalt")
    assert (ablage.ziel / "S3_NUL.opus").read_bytes() == b"inhalt"


@pytest.mark.parametrize(
    ("argumente", "status", "text"),
    [
        (("../x.opus", 0, 1, b"x", None, None), 400, "Dateiname"),
        (("H5.opus", -1, 1, b"x", None, None), 400, "negativ"),
        (("H5.opus", 0, 1, b"x", 1, None), 400, "zusammen"),
        (("H5.opus", 0, 1, b"x", None, "a" * 64), 400, "zusammen"),
        (("H5.opus", 0, 1, b"x", 1, "ABC"), 400, "Hex"),
        (("H5.opus", 0, 0, b"", -1, "a" * 64), 400, "negativ"),
        (("H5.opus", 0, empfang.TEIL_MAX_BYTES + 1, b"", None, None), 413, "Stueck"),
    ],
)
def test_ungueltige_anfragen(ablage, argumente, status, text):
    datei, offset, laenge, _daten, gesamt, pruefsumme = argumente
    antwort = ablage.anhaengen("S3", datei, offset, laenge, nie_lesen, gesamt, pruefsumme)
    assert antwort.status == status and text in antwort.daten["fehler"]


def test_zu_grosse_aufnahme_wird_abgelehnt(tmp_path):
    ablage = Ablage(tmp_path, max_datei_bytes=10, freier_platz=lambda _p: 10**12)
    assert ablage.anhaengen("S3", "H5.opus", 8, 3, nie_lesen).status in (409, 413)
    assert ablage.anhaengen("S3", "H5.opus", 0, 11, nie_lesen).status == 413
    assert ablage.anhaengen("S3", "H5.opus", 0, 1, nie_lesen, 11, "a" * 64).status == 413


def test_zu_wenig_platz(tmp_path):
    ablage = Ablage(tmp_path, platz_reserve_bytes=100, freier_platz=lambda _p: 150)
    assert ablage.anhaengen("S3", "H5.opus", 0, 10, leser(b"0123456789")).status == 200
    # Die angekuendigte Gesamtgroesse zaehlt, nicht nur das Stueck.
    antwort = ablage.anhaengen("S3", "H5.opus", 10, 1, nie_lesen, 200, "a" * 64)
    assert antwort.status == 507


def test_platzabfrage_scheitert(tmp_path):
    def kaputt(_pfad):
        raise OSError("nicht erreichbar")

    ablage = Ablage(tmp_path, freier_platz=kaputt)
    assert ablage.anhaengen("S3", "H5.opus", 0, 1, nie_lesen).status == 507


def test_fehler_in_der_meldung_stoert_den_empfang_nicht(tmp_path):
    def kaputt(_pfad, _geraet):
        raise RuntimeError("Anzeige weg")

    ablage = Ablage(tmp_path, freier_platz=lambda _p: 10**12, bei_neuer_aufnahme=kaputt)
    assert hochladen(ablage, "S3", "H5.opus", b"abc").daten["fertig"] is True


def test_kaputte_merkliste_gilt_als_leer(ablage):
    hochladen(ablage, "S3", "H5.opus", b"abc")
    (ablage.ziel / ".empfang" / "fertig.json").write_text("[kein objekt", encoding="utf-8")
    hochladen(ablage, "S3", "H5.opus", b"abc")  # nicht mehr als Wiederholung erkennbar
    assert (ablage.ziel / "S3_H5_2.opus").exists()
    (ablage.ziel / ".empfang" / "fertig.json").write_text("[]", encoding="utf-8")
    assert ablage._fertig_laden() == {}


def test_merkliste_ist_begrenzt(ablage, monkeypatch):
    monkeypatch.setattr(empfang, "MAX_FERTIG_EINTRAEGE", 2)
    for nummer in range(3):
        hochladen(ablage, "S3", f"H5_{nummer}.opus", b"x%d" % nummer)
    eintraege = ablage._fertig_laden()
    assert len(eintraege) == 2 and not any("/H5_0.opus/" in k for k in eintraege)


def test_aufraeumen_entfernt_nur_alte_teilstaende(tmp_path):
    jetzt = time.time()
    ablage = Ablage(tmp_path, freier_platz=lambda _p: 10**12, jetzt=lambda: jetzt)
    ablage.anhaengen("S3", "alt.opus", 0, 1, leser(b"a"))
    ablage.anhaengen("S3", "neu.opus", 0, 1, leser(b"n"))
    alt = next(p for p in (tmp_path / ".empfang").glob("*.teil") if p.read_bytes() == b"a")
    os.utime(alt, (jetzt - 8 * 24 * 3600, jetzt - 8 * 24 * 3600))
    assert ablage.aufraeumen() == 1
    assert ablage.stand("S3", "neu.opus").daten["naechstes_byte"] == 1
    assert ablage.stand("S3", "alt.opus").daten["naechstes_byte"] == 0
    assert Ablage(tmp_path / "gibt-es-nicht").aufraeumen() == 0


def test_ordner_sichern_unter_linux(tmp_path, monkeypatch):
    aufrufe: list[str] = []
    monkeypatch.setattr(empfang.os, "name", "posix")
    monkeypatch.setattr(empfang.os, "open", lambda pfad, _flags: aufrufe.append("open") or 99)
    monkeypatch.setattr(empfang.os, "fsync", lambda handle: aufrufe.append(f"fsync {handle}"))
    monkeypatch.setattr(empfang.os, "close", lambda handle: aufrufe.append(f"close {handle}"))
    empfang._ordner_sichern(tmp_path)
    assert aufrufe == ["open", "fsync 99", "close 99"]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
@pytest.fixture
def dienst(tmp_path: Path) -> Iterator[GeraeteEmpfang]:
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)), Geraet("C6", empfang.token_hash(TOKEN_ZWEI)))
    laufend = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1")
    laufend.ablage._freier_platz = lambda _p: 10**12
    laufend.starten()
    try:
        yield laufend
    finally:
        laufend.stoppen()


def anfrage(
    dienst: GeraeteEmpfang, methode: str, pfad: str, inhalt: bytes | None = None, token: str | None = TOKEN, **kopf: str
) -> tuple[int, dict, http.client.HTTPResponse]:
    verbindung = http.client.HTTPConnection("127.0.0.1", dienst.port, timeout=10)
    kopfzeilen = {k.replace("_", "-"): v for k, v in kopf.items()}
    if token is not None:
        kopfzeilen["Authorization"] = f"Bearer {token}"
    verbindung.request(methode, pfad, body=inhalt, headers=kopfzeilen)
    antwort = verbindung.getresponse()
    text = antwort.read()
    verbindung.close()
    return antwort.status, json.loads(text) if text else {}, antwort


def roh(dienst: GeraeteEmpfang, anfragetext: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", dienst.port), timeout=10) as verbindung:
        verbindung.sendall(anfragetext)
        empfangen = b""
        while chunk := verbindung.recv(4096):
            empfangen += chunk
    return empfangen


def test_hallo_meldet_dienst_kompakt(dienst):
    status, daten, antwort = anfrage(dienst, "GET", "/api/v1/hallo")
    assert status == 200 and antwort.getheader("Content-Type") == "application/json"
    assert daten == {"dienst": "protokoll-assistent", "schnittstelle": 1, "geraet": "S3-Audio", "teil_max_bytes": empfang.TEIL_MAX_BYTES}
    text = roh(dienst, f"GET /api/v1/hallo HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nConnection: close\r\n\r\n".encode())
    # Genau so sucht die Firmware danach.
    assert b'"dienst":"protokoll-assistent"' in text and b'"schnittstelle":1' in text


@pytest.mark.parametrize("token", [None, "falsch", ""])
def test_ohne_gueltiges_token_401(dienst, token):
    status, daten, _ = anfrage(dienst, "GET", "/api/v1/hallo", token=token)
    assert status == 401 and "Token" in daten["fehler"]


def test_andere_anmeldeart_wird_abgelehnt(dienst):
    verbindung = http.client.HTTPConnection("127.0.0.1", dienst.port, timeout=10)
    verbindung.request("GET", "/api/v1/hallo", headers={"Authorization": f"Basic {TOKEN}"})
    assert verbindung.getresponse().status == 401
    verbindung.close()


def test_unbekannte_pfade_und_methoden(dienst):
    assert anfrage(dienst, "GET", "/")[0] == 404
    assert anfrage(dienst, "PUT", "/upload", b"x", X_Offset="0")[0] == 404
    assert anfrage(dienst, "POST", "/upload", b"x")[0] == 404
    assert anfrage(dienst, "PATCH", "/upload", b"x")[0] == 405
    assert anfrage(dienst, "DELETE", "/api/v1/aufnahmen/H5.opus")[0] == 405


def test_upload_ueber_http_mit_wiederaufnahme(dienst):
    daten = os.urandom(3000)
    pfad = "/api/v1/aufnahmen/H5_007.opus"
    assert anfrage(dienst, "GET", pfad)[1] == {"naechstes_byte": 0, "fertig": False}
    assert anfrage(dienst, "PUT", pfad, daten[:1000], X_Offset="0")[1] == {"naechstes_byte": 1000, "fertig": False}
    # Das Geraet glaubt, es sei weiter: 409 mit dem richtigen Stand.
    status, antwort, _ = anfrage(dienst, "PUT", pfad, daten[2000:], X_Offset="2000")
    assert status == 409 and antwort["naechstes_byte"] == 1000
    assert anfrage(dienst, "GET", pfad + "?egal=1")[1]["naechstes_byte"] == 1000
    assert anfrage(dienst, "PUT", pfad, daten[1000:], X_Offset="1000")[1]["naechstes_byte"] == 3000
    status, antwort, _ = anfrage(
        dienst, "PUT", pfad, b"", X_Offset="3000", X_Gesamtgroesse="3000", X_SHA256=sha(daten).upper()
    )
    assert status == 200 and antwort == {"naechstes_byte": 3000, "fertig": True, "datei": "S3-Audio_H5_007.opus"}
    assert (dienst.ablage.ziel / "S3-Audio_H5_007.opus").read_bytes() == daten


def test_geraetename_kommt_aus_dem_token(dienst):
    anfrage(dienst, "PUT", "/api/v1/aufnahmen/H5.opus", b"c6", token=TOKEN_ZWEI, X_Offset="0", X_Gesamtgroesse="2", X_SHA256=sha(b"c6"))
    assert (dienst.ablage.ziel / "C6_H5.opus").read_bytes() == b"c6"


@pytest.mark.parametrize(
    "kopf",
    [
        {"X_Offset": "abc"},
        {"X_Offset": "0", "X_Gesamtgroesse": "viel", "X_SHA256": "a" * 64},
        {},
    ],
)
def test_ungueltige_kopfzeilen_400(dienst, kopf):
    status, daten, _ = anfrage(dienst, "PUT", "/api/v1/aufnahmen/H5.opus", b"x", **kopf)
    assert status == 400 and daten["fehler"]


def test_ohne_content_length_oder_mit_chunked_411(dienst):
    kopf = f"Host: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Offset: 0\r\nConnection: close\r\n"
    ohne = roh(dienst, f"PUT /api/v1/aufnahmen/H5.opus HTTP/1.1\r\n{kopf}\r\n".encode())
    assert ohne.startswith(b"HTTP/1.1 411")
    chunked = roh(
        dienst,
        f"PUT /api/v1/aufnahmen/H5.opus HTTP/1.1\r\n{kopf}Transfer-Encoding: chunked\r\n\r\n1\r\nx\r\n0\r\n\r\n".encode(),
    )
    assert chunked.startswith(b"HTTP/1.1 411")


def test_abgelehnter_inhalt_wird_abgeholt_und_die_verbindung_bleibt_nutzbar(dienst):
    anfrage(dienst, "PUT", "/api/v1/aufnahmen/H5.opus", b"abc", X_Offset="0")
    # Zwei Anfragen auf derselben Verbindung; die erste wird mit 409 abgelehnt.
    # Ihr Inhalt wird trotzdem gelesen und verworfen -- sonst saehe das Geraet
    # bei einem grossen Stueck nur einen Verbindungsabbruch statt der Antwort.
    inhalt = b"x" * 300_000
    kopf = (
        f"PUT /api/v1/aufnahmen/H5.opus HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n"
        f"X-Offset: 9\r\nContent-Length: {len(inhalt)}\r\n\r\n"
    )
    zweite = f"GET /api/v1/aufnahmen/H5.opus HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nConnection: close\r\n\r\n"
    text = roh(dienst, kopf.encode() + inhalt + zweite.encode())
    assert text.startswith(b"HTTP/1.1 409") and b'"naechstes_byte":3' in text
    assert text.count(b"HTTP/1.1 200") == 1  # die zweite Anfrage wurde beantwortet


def test_zu_grosser_ungelesener_inhalt_schliesst_die_verbindung(dienst):
    # Groesser als teil_max_bytes wird nichts abgeholt: Die Verbindung muss zu,
    # sonst wuerde der Inhalt als naechste Anfrage gedeutet.
    kopf = (
        f"PUT /api/v1/aufnahmen/H5.opus HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n"
        f"X-Offset: 0\r\nContent-Length: {empfang.TEIL_MAX_BYTES + 1}\r\n\r\nGET /"
    )
    text = roh(dienst, kopf.encode())
    assert text.startswith(b"HTTP/1.1 413") and b"Connection: close" in text
    assert text.count(b"HTTP/1.1") == 1


def test_unangemeldeter_inhalt_wird_nicht_abgeholt(dienst):
    kopf = "PUT /api/v1/aufnahmen/H5.opus HTTP/1.1\r\nHost: x\r\nX-Offset: 0\r\nContent-Length: 5\r\n\r\nGET /"
    text = roh(dienst, kopf.encode())
    assert text.startswith(b"HTTP/1.1 401") and text.count(b"HTTP/1.1") == 1


def test_mehrere_anfragen_auf_einer_verbindung(dienst):
    verbindung = http.client.HTTPConnection("127.0.0.1", dienst.port, timeout=10)
    for _ in range(3):
        verbindung.request("GET", "/api/v1/hallo", headers={"Authorization": f"Bearer {TOKEN}"})
        antwort = verbindung.getresponse()
        assert antwort.status == 200
        antwort.read()
    verbindung.close()


def test_zu_viele_verbindungen_503(tmp_path, monkeypatch):
    monkeypatch.setattr(empfang, "MAX_VERBINDUNGEN", 1)
    laufend = GeraeteEmpfang(tmp_path, [Geraet("S3", empfang.token_hash(TOKEN))], port=0, adresse="127.0.0.1")
    laufend.starten()
    try:
        with socket.create_connection(("127.0.0.1", laufend.port), timeout=10) as belegt:
            belegt.sendall(b"GET /api/v1/hallo HTTP/1.1\r\n")  # unvollstaendig: haelt den Platz
            # Warten, bis der Faden den Platz wirklich belegt hat -- eine feste
            # Wartezeit reicht unter Last nicht.
            server = laufend._server
            assert server is not None
            ende = time.monotonic() + 10
            while server.plaetze._value > 0 and time.monotonic() < ende:  # type: ignore[attr-defined]
                time.sleep(0.01)
            status, daten, _ = anfrage(laufend, "GET", "/api/v1/hallo")
        assert status == 503 and daten["fehler"]
    finally:
        laufend.stoppen()


def test_starten_und_stoppen(tmp_path):
    laufend = GeraeteEmpfang(tmp_path / "neu", [], port=0, adresse="127.0.0.1")
    assert not laufend.laeuft and laufend.port == 0
    laufend.starten()
    laufend.starten()  # zweimal ist harmlos
    assert laufend.laeuft and laufend.port > 0 and (tmp_path / "neu").is_dir()
    belegter_port = laufend.port
    zweiter = GeraeteEmpfang(tmp_path, [], port=belegter_port, adresse="127.0.0.1")
    with pytest.raises(OSError):
        zweiter.starten()
    laufend.stoppen()
    laufend.stoppen()
    assert not laufend.laeuft


def test_starten_raeumt_alte_teilstaende_weg(tmp_path):
    ordner = tmp_path / ".empfang"
    ordner.mkdir()
    alt = ordner / "abc.teil"
    alt.write_bytes(b"x")
    os.utime(alt, (1, 1))
    laufend = GeraeteEmpfang(tmp_path, [], port=0, adresse="127.0.0.1")
    laufend.starten()
    laufend.stoppen()
    assert not alt.exists()


# --------------------------------------------------------------------------
# Geraete-Id und Firmware (nur zur Zuordnung)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [("1A:2B:3C:4D:5E:6F", "1a2b3c4d5e6f"), ("1a2b3c4d5e6f", "1a2b3c4d5e6f"), ("1a-2b-3c-4d-5e-6f", "1a2b3c4d5e6f"),
     ("xyz", None), ("", None), (None, None), ("1a2b3c4d5e6f00", None)],
)
def test_geraete_id_lesen(wert, erwartet):
    assert empfang.geraete_id_lesen(wert) == erwartet


@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [("esp32-s3-audio/1.0.0", "esp32-s3-audio/1.0.0"), (" c6/2.1+g1a2b ", "c6/2.1+g1a2b"), ("a b", None), ("x" * 65, None), (None, None)],
)
def test_firmware_lesen(wert, erwartet):
    assert empfang.firmware_lesen(wert) == erwartet


def test_kontakt_wird_gemerkt_und_aenderungen_protokolliert(dienst, caplog):
    caplog.set_level("INFO", logger=empfang.__name__)
    for _ in range(2):
        anfrage(dienst, "GET", "/api/v1/hallo", X_Geraete_Id="1A2B3C4D5E6F", X_Firmware="esp32-s3-audio/1.0.0")
    kontakt = dienst.kontakte()["S3-Audio"]
    assert (kontakt.geraete_id, kontakt.firmware, kontakt.adresse) == ("1a2b3c4d5e6f", "esp32-s3-audio/1.0.0", "127.0.0.1")
    assert sum("Geraet S3-Audio: Id 1a2b3c4d5e6f" in r.getMessage() for r in caplog.records) == 1

    anfrage(dienst, "GET", "/api/v1/hallo", X_Geraete_Id="aaaaaaaaaaaa", X_Firmware="esp32-s3-audio/1.0.0")
    assert any("anderen Geraet" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)


def test_ohne_kennung_wird_trotzdem_angenommen(dienst):
    assert anfrage(dienst, "GET", "/api/v1/hallo", X_Geraete_Id="kaputt")[0] == 200
    assert dienst.kontakte()["S3-Audio"].geraete_id is None


def test_abgewiesene_anfragen_hinterlassen_keinen_kontakt(dienst):
    anfrage(dienst, "GET", "/api/v1/hallo", token="falsch", X_Geraete_Id="1a2b3c4d5e6f")
    assert dienst.kontakte() == {}


# --------------------------------------------------------------------------
# Sanftes Schliessen
# --------------------------------------------------------------------------
def test_abgelehnte_anfragen_mit_inhalt_kommen_immer_an(dienst):
    """Unter Last setzte TCP die Verbindung zurueck, bevor die Antwort gelesen
    war (404/405/401 mit ungelesenem Inhalt) -- ein Test schlug so gelegentlich
    fehl. Viele Wiederholungen machen den Zufall sichtbar."""
    for _ in range(40):
        assert anfrage(dienst, "PUT", "/upload", b"x" * 2000, X_Offset="0")[0] == 404
        assert anfrage(dienst, "POST", "/upload", b"x" * 2000)[0] == 413  # zu gross fuer einen Befehl
        assert anfrage(dienst, "PATCH", "/upload", b"x" * 2000)[0] == 405
        assert anfrage(dienst, "PUT", "/api/v1/aufnahmen/H5.opus", b"x" * 2000, token="falsch", X_Offset="0")[0] == 401


class _Verbindung:
    def __init__(self, bloecke, fehler_bei_shutdown=False):
        self.bloecke = list(bloecke)
        self.fehler_bei_shutdown = fehler_bei_shutdown
        self.ablauf: list[str] = []

    def shutdown(self, _art):
        if self.fehler_bei_shutdown:
            raise OSError("schon zu")
        self.ablauf.append("shutdown")

    def settimeout(self, _sekunden):
        pass

    def recv(self, _anzahl):
        self.ablauf.append("recv")
        return self.bloecke.pop(0) if self.bloecke else b""


def test_sanft_schliessen_liest_bis_zum_ende_der_gegenseite():
    verbindung = _Verbindung([b"rest", b"mehr", b""])
    empfang._sanft_schliessen(verbindung)
    assert verbindung.ablauf == ["shutdown", "recv", "recv", "recv"]


def test_sanft_schliessen_ist_begrenzt(monkeypatch):
    monkeypatch.setattr(empfang, "NACHLAUF_MAX_BYTES", 10)
    verbindung = _Verbindung([b"x" * 8] * 100)
    empfang._sanft_schliessen(verbindung)
    assert verbindung.ablauf.count("recv") == 2  # nach 16 Bytes Schluss


def test_sanft_schliessen_ist_zeitlich_begrenzt(monkeypatch):
    zeiten = iter([0.0, 0.5, 3.0])
    monkeypatch.setattr(empfang.time, "monotonic", lambda: next(zeiten))
    verbindung = _Verbindung([b"x"] * 100)
    empfang._sanft_schliessen(verbindung)
    assert verbindung.ablauf.count("recv") == 1


def test_sanft_schliessen_bei_schon_geschlossener_verbindung():
    verbindung = _Verbindung([], fehler_bei_shutdown=True)
    empfang._sanft_schliessen(verbindung)
    assert verbindung.ablauf == []


# --------------------------------------------------------------------------
# Live-Verarbeitung: Rueckrufe und Status
# --------------------------------------------------------------------------
def test_rueckrufe_melden_stuecke_und_abschluss_mit_dem_namen_des_geraets(tmp_path):
    ereignisse: list[tuple] = []
    ablage = Ablage(
        tmp_path / "eingang",
        freier_platz=lambda _p: 10**12,
        bei_teil=lambda geraet, datei, pfad: ereignisse.append(("teil", geraet, datei, pfad.read_bytes())),
        bei_abschluss=lambda geraet, datei, ziel: ereignisse.append(("ende", geraet, datei, ziel.name)),
    )
    assert ablage.anhaengen("S3", "H5_7.opus", 0, 3, leser(b"abc")).status == 200
    assert ablage.anhaengen("S3", "H5_7.opus", 3, 3, leser(b"def")).status == 200
    assert ablage.anhaengen("S3", "H5_7.opus", 6, 0, leser(b""), 6, sha(b"abcdef")).daten["fertig"] is True
    # Das Stueck wird gemeldet, nachdem es geschrieben wurde; 'datei' ist der Name des Geraets,
    # der Abschluss nennt zusaetzlich den Dateinamen am PC.
    assert ereignisse == [
        ("teil", "S3", "H5_7.opus", b"abc"),
        ("teil", "S3", "H5_7.opus", b"abcdef"),
        ("ende", "S3", "H5_7.opus", "S3_H5_7.opus"),
    ]


def test_leeres_stueck_und_abgelehnte_stuecke_melden_nichts(tmp_path):
    ereignisse = []
    ablage = Ablage(
        tmp_path / "eingang",
        freier_platz=lambda _p: 10**12,
        bei_teil=lambda *a: ereignisse.append(a),
    )
    ablage.anhaengen("S3", "H5.opus", 0, 0, leser(b""))  # leer
    assert ablage.anhaengen("S3", "H5.opus", 5, 1, nie_lesen).status == 409  # falscher Offset
    assert ereignisse == []


def test_wiederholte_aufnahme_meldet_den_abschluss_nicht_noch_einmal(tmp_path):
    abschluesse = []
    ablage = Ablage(
        tmp_path / "eingang",
        freier_platz=lambda _p: 10**12,
        bei_abschluss=lambda *a: abschluesse.append(a),
    )
    hochladen(ablage, "S3", "H5.opus", b"abc")
    hochladen(ablage, "S3", "H5.opus", b"abc")
    assert len(abschluesse) == 1


def test_fehler_in_den_rueckrufen_stoeren_den_empfang_nicht(tmp_path):
    def kaputt(*_a):
        raise RuntimeError("Live-Verarbeitung weg")

    ablage = Ablage(tmp_path / "eingang", freier_platz=lambda _p: 10**12, bei_teil=kaputt, bei_abschluss=kaputt)
    assert hochladen(ablage, "S3", "H5.opus", b"abcdef", stueck=2).daten["fertig"] is True


def test_status_ueber_http(tmp_path):
    zustaende = {("S3-Audio", "H5_007.opus"): {"zustand": "auswertung", "fortschritt": 0.8}}
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    dienst = GeraeteEmpfang(
        tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", status_fn=lambda g, d: zustaende.get((g, d))
    )
    dienst.starten()
    try:
        pfad = "/api/v1/aufnahmen/H5_007.opus/status"
        assert anfrage(dienst, "GET", pfad)[:2] == (200, {"zustand": "auswertung", "fortschritt": 0.8})
        # Unbekannt: nichts zu melden (Neustart der Software), kein Fehler.
        assert anfrage(dienst, "GET", "/api/v1/aufnahmen/H5_008.opus/status")[:2] == (200, {"zustand": "unbekannt"})
        assert anfrage(dienst, "GET", "/api/v1/aufnahmen/mit%20leerzeichen.opus/status")[0] == 400
        assert anfrage(dienst, "GET", pfad, token=None)[0] == 401
        assert anfrage(dienst, "PUT", pfad, b"", X_Offset="0")[0] == 400  # kein Upload-Ziel
        # Der Stand fuer die Wiederaufnahme bleibt, wie er war.
        assert anfrage(dienst, "GET", "/api/v1/aufnahmen/H5_007.opus")[1] == {"naechstes_byte": 0, "fertig": False}
    finally:
        dienst.stoppen()


def test_status_ohne_live_verarbeitung_ist_unbekannt(dienst):
    assert anfrage(dienst, "GET", "/api/v1/aufnahmen/H5_007.opus/status")[:2] == (200, {"zustand": "unbekannt"})


def test_neubeginn_verwerfen_und_wiederholung_werden_gemeldet(tmp_path):
    """Was bisher unter einem Namen ankam, gilt nicht mehr: ein Upload ab Byte 0, ein verworfener Teilstand (422),
    die Wiederholung einer schon abgelegten Aufnahme. Die Live-Verarbeitung verwirft dann ihren Stand -- sonst
    geriete das Transkript der vorigen Aufnahme in die naechste unter demselben Namen."""
    verworfen: list[tuple] = []
    ablage = Ablage(tmp_path / "eingang", freier_platz=lambda _p: 10**12, bei_verworfen=lambda *a: verworfen.append(a))
    assert ablage.anhaengen("S3", "H5.opus", 0, 3, leser(b"abc")).status == 200
    assert verworfen == [("S3", "H5.opus")]  # beginnt bei Byte 0
    assert ablage.anhaengen("S3", "H5.opus", 3, 3, leser(b"def")).status == 200
    assert len(verworfen) == 1  # ein Folgestueck verwirft nichts
    assert ablage.anhaengen("S3", "H5.opus", 6, 0, leser(b""), 6, sha(b"anders")).status == 422
    assert len(verworfen) == 2
    hochladen(ablage, "S3", "H5.opus", b"abc", stueck=3)  # von vorn: Byte 0
    assert len(verworfen) == 3
    hochladen(ablage, "S3", "H5.opus", b"abc", stueck=3)  # Bestaetigung verloren: Byte 0 und Wiederholung
    assert verworfen == [("S3", "H5.opus")] * 5


def test_stand_nennt_kein_halb_angekommenes_stueck(tmp_path):
    """Bricht die Verbindung mitten in einem Stueck ab, wartet die Software womoeglich noch auf dessen Rest, waehrend
    das Geraet schon neu verbunden nachfragt. Die Datei enthaelt dann schon einen Teil des Stuecks -- der Stand darf
    ihn nicht mitzaehlen, denn das Stueck wird danach verworfen (gefunden im QEMU-Abbruch-Fall: das Geraet setzte
    bei Byte 362144 statt 262144 an)."""
    ablage = Ablage(tmp_path / "eingang", freier_platz=lambda _p: 10**12)
    assert ablage.anhaengen("S3", "H5.opus", 0, 4, leser(b"abcd")).status == 200
    teil = ablage._teil_pfad(ablage._schluessel("S3", "H5.opus"))
    erster_block = b"x" * 20000  # groesser als der Schreibpuffer: steht sofort in der Datei
    beobachtet: list[tuple[int, int]] = []
    aufrufe = 0

    def lesen(_anzahl: int) -> bytes:
        nonlocal aufrufe
        aufrufe += 1
        if aufrufe == 1:
            return erster_block
        # Der Rest des Stuecks fehlt noch; das Geraet fragt inzwischen nach dem Stand ...
        beobachtet.append((teil.stat().st_size, ablage.stand("S3", "H5.opus").daten["naechstes_byte"]))
        return b""  # ... und die Verbindung ist weg

    assert ablage.anhaengen("S3", "H5.opus", 4, 30000, lesen).status == 400
    datei_groesse, gemeldet = beobachtet[0]
    assert datei_groesse > 4  # der halbe Rest stand wirklich schon in der Datei
    assert gemeldet == 4  # gemeldet wird nur, was vollstaendig angekommen ist
    assert ablage.stand("S3", "H5.opus").daten["naechstes_byte"] == 4
    assert ablage.anhaengen("S3", "H5.opus", 4, 2, leser(b"ef")).status == 200  # dort geht es weiter


# --------------------------------------------------------------------------
# Auftraege, Wuensche des Geraets, Freigabe der Zusammenfassung
# --------------------------------------------------------------------------
def test_auftrag_lesen_prozentcodiert_und_begrenzt():
    assert empfang.auftrag_lesen("Meeting%20Protokoll") == "Meeting Protokoll"
    assert empfang.auftrag_lesen("Aufgaben%20f%C3%BCr%20Fritz") == "Aufgaben für Fritz"
    assert empfang.auftrag_lesen(None) is None and empfang.auftrag_lesen("") is None and empfang.auftrag_lesen("  ") is None
    assert empfang.auftrag_lesen("%FF%FE") is None  # kein gueltiges UTF-8
    assert empfang.auftrag_lesen("a%0Ab") is None  # Steuerzeichen
    assert empfang.auftrag_lesen("x" * (empfang.AUFTRAG_MAX_ZEICHEN + 1)) is None


def test_auftraege_ueber_http(tmp_path):
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    # 58 Zeichen, aber mit sechs Umlauten 64 Byte: passt nicht ins Geraet und fehlt deshalb
    namen = ["ToDos", "Entscheidungen", "ToDos", "x" * 200, "", "ä" * 6 + "x" * 52, "Agenda"]
    dienst = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", auftraege_fn=lambda: namen)
    dienst.starten()
    try:
        assert anfrage(dienst, "GET", "/api/v1/auftraege")[:2] == (
            200,
            {
                "auftraege": ["ToDos", "Entscheidungen", "Agenda"],
                "anzeige": ["ToDos", "Entscheidungen", "Agenda"],
            },
        )
        assert anfrage(dienst, "GET", "/api/v1/auftraege", token=None)[0] == 401
    finally:
        dienst.stoppen()


def test_hoechstens_so_viele_auftraege_wie_die_firmware_fasst(tmp_path):
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    namen = [f"Vorlage {i}" for i in range(20)]
    dienst = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", auftraege_fn=lambda: namen)
    dienst.starten()
    try:
        assert anfrage(dienst, "GET", "/api/v1/auftraege")[1]["auftraege"] == namen[: empfang.MAX_AUFTRAEGE]
    finally:
        dienst.stoppen()


def test_ohne_vorlagen_ist_die_liste_leer(dienst):
    assert anfrage(dienst, "GET", "/api/v1/auftraege")[:2] == (200, {"auftraege": [], "anzeige": []})


def test_auftragsnamen_mit_umlauten_haben_eine_anzeige_ohne_umlaute(tmp_path):
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    namen = ["Aufgaben für Fritz", "Größe Runde"]
    dienst = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", auftraege_fn=lambda: namen)
    dienst.starten()
    try:
        antwort = anfrage(dienst, "GET", "/api/v1/auftraege")[1]
        assert antwort["auftraege"] == namen  # gesendet wird der echte Name
        assert antwort["anzeige"] == ["Aufgaben fuer Fritz", "Groesse Runde"]
    finally:
        dienst.stoppen()


def test_wunsch_des_geraets_wird_beim_upload_gemeldet(tmp_path):
    wuensche: list[tuple] = []
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    dienst = GeraeteEmpfang(
        tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", bei_wunsch=lambda *a: wuensche.append(a)
    )
    dienst.ablage._freier_platz = lambda _p: 10**12
    dienst.starten()
    try:
        pfad = "/api/v1/aufnahmen/H5_007.opus"
        anfrage(dienst, "PUT", pfad, b"abc", X_Offset="0", X_Auftrag="Aufgaben%20f%C3%BCr%20Fritz", X_Rueckfrage="1")
        anfrage(dienst, "PUT", pfad, b"def", X_Offset="3")  # ohne Kopfzeilen: nichts zu melden
        anfrage(dienst, "PUT", pfad, b"ghi", X_Offset="6", X_Rueckfrage="0", X_Auftrag="%FF")  # nichts Brauchbares
        assert wuensche == [("S3-Audio", "H5_007.opus", "Aufgaben für Fritz", True)]
    finally:
        dienst.stoppen()


def test_fehler_beim_merken_des_wunsches_stoert_den_upload_nicht(tmp_path):
    def kaputt(*_a):
        raise RuntimeError("weg")

    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    dienst = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", bei_wunsch=kaputt)
    dienst.ablage._freier_platz = lambda _p: 10**12
    dienst.starten()
    try:
        status, antwort, _ = anfrage(
            dienst, "PUT", "/api/v1/aufnahmen/H5_007.opus", b"abc", X_Offset="0", X_Rueckfrage="1"
        )
        assert status == 200 and antwort["naechstes_byte"] == 3
    finally:
        dienst.stoppen()


def _freigabe_dienst(tmp_path, zustaende, freigaben, ergebnis=True):
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)),)
    return GeraeteEmpfang(
        tmp_path / "eingang",
        geraete,
        port=0,
        adresse="127.0.0.1",
        status_fn=lambda g, d: zustaende.get((g, d)),
        bei_zusammenfassung=lambda g, d: freigaben.append((g, d)) or ergebnis,
    )


def test_freigabe_der_zusammenfassung_nur_wenn_das_transkript_steht(tmp_path):
    zustaende = {
        ("S3-Audio", "H5_001.opus"): {"zustand": "transkript"},
        ("S3-Audio", "H5_002.opus"): {"zustand": "transkription"},
        ("S3-Audio", "H5_003.opus"): {"zustand": "auswertung"},
        ("S3-Audio", "H5_004.opus"): {"zustand": "fertig"},
    }
    freigaben: list[tuple] = []
    dienst = _freigabe_dienst(tmp_path, zustaende, freigaben)
    dienst.starten()
    try:
        def post(name):
            return anfrage(dienst, "POST", f"/api/v1/aufnahmen/{name}/zusammenfassung")[:2]

        assert post("H5_001.opus") == (202, {"zustand": "auswertung"})
        assert freigaben == [("S3-Audio", "H5_001.opus")]
        status, antwort = post("H5_002.opus")
        assert status == 409 and antwort["zustand"] == "transkription"
        # Wiederholungen sind harmlos und loesen nichts erneut aus
        assert post("H5_003.opus") == (202, {"zustand": "auswertung"})
        assert post("H5_004.opus") == (200, {"zustand": "fertig"})
        assert post("H5_099.opus")[0] == 404  # unbekannt
        assert anfrage(dienst, "POST", "/api/v1/aufnahmen/mit%20leerzeichen.opus/zusammenfassung")[0] == 400
        assert anfrage(dienst, "POST", "/api/v1/aufnahmen/H5_001.opus/zusammenfassung", token=None)[0] == 401
        assert len(freigaben) == 1
    finally:
        dienst.stoppen()


def test_freigabe_wird_abgelehnt_wenn_die_software_sie_nicht_annimmt(tmp_path):
    zustaende = {("S3-Audio", "H5_001.opus"): {"zustand": "transkript"}}
    dienst = _freigabe_dienst(tmp_path, zustaende, [], ergebnis=False)
    dienst.starten()
    try:
        status, antwort, _ = anfrage(dienst, "POST", "/api/v1/aufnahmen/H5_001.opus/zusammenfassung")
        assert status == 409 and antwort["zustand"] == "transkript"
    finally:
        dienst.stoppen()


def test_freigabe_ohne_unterstuetzung_und_zu_grosse_anfragen(dienst):
    assert anfrage(dienst, "POST", "/api/v1/aufnahmen/H5_001.opus/zusammenfassung")[0] == 404
    gross = b"x" * (empfang.POST_MAX_BYTES + 1)
    assert anfrage(dienst, "POST", "/api/v1/aufnahmen/H5_001.opus/zusammenfassung", gross)[0] == 413


# --------------------------------------------------------------------------
# Fragen per Sprache
# --------------------------------------------------------------------------
class _FragenAttrappe:
    def __init__(self, *, bereit=True, spricht=True):
        self.bereit = bereit
        self.spricht = spricht
        self.eingereicht: list[tuple] = []
        self.zustand = {"zustand": "fertig", "frage": "Was macht Fritz?", "antwort": "Er schreibt.", "ton_bytes": 4}
        self.wav = b"RIFF"

    def bereit_fuer(self, geraet, datei):
        return self.bereit

    def einreichen(self, geraet, datei, ton, endung, ausgabe):
        self.eingereicht.append((geraet, datei, ton, endung, ausgabe))
        return "0123456789abcdef"

    def stand(self, geraet, kennung):
        return self.zustand if (geraet, kennung) == ("S3-Audio", "0123456789abcdef") else None

    def ton(self, geraet, kennung):
        return self.wav if self.stand(geraet, kennung) else None


def _fragen_dienst(tmp_path, fragen):
    geraete = (Geraet("S3-Audio", empfang.token_hash(TOKEN)), Geraet("C6", empfang.token_hash(TOKEN_ZWEI)))
    dienst = GeraeteEmpfang(tmp_path / "eingang", geraete, port=0, adresse="127.0.0.1", fragen=fragen)
    dienst.starten()
    return dienst


def _roh_holen(dienst, pfad, token=TOKEN):
    verbindung = http.client.HTTPConnection("127.0.0.1", dienst.port, timeout=10)
    verbindung.request("GET", pfad, headers={"Authorization": f"Bearer {token}"})
    antwort = verbindung.getresponse()
    inhalt = antwort.read()
    verbindung.close()
    return antwort.status, antwort.getheader("Content-Type"), inhalt


def test_frage_einreichen_stand_und_ton_ueber_http(tmp_path):
    fragen = _FragenAttrappe()
    dienst = _fragen_dienst(tmp_path, fragen)
    try:
        status, antwort, _ = anfrage(
            dienst, "POST", "/api/v1/aufnahmen/H5_007.opus/frage", b"RIFF-frage", Content_Type="audio/wav"
        )
        assert (status, antwort) == (202, {"frage_id": "0123456789abcdef", "ton": False})  # Standard: Anzeige
        status, antwort, _ = anfrage(
            dienst, "POST", "/api/v1/aufnahmen/H5_007.opus/frage", b"OggS",
            Content_Type="audio/ogg; codecs=opus", X_Ausgabe="ton",
        )
        assert antwort["ton"] is True
        assert fragen.eingereicht == [
            ("S3-Audio", "H5_007.opus", b"RIFF-frage", ".wav", "anzeige"),
            ("S3-Audio", "H5_007.opus", b"OggS", ".opus", "ton"),
        ]

        assert anfrage(dienst, "GET", "/api/v1/fragen/0123456789abcdef")[:2] == (200, fragen.zustand)
        assert _roh_holen(dienst, "/api/v1/fragen/0123456789abcdef/ton") == (200, "audio/wav", b"RIFF")
    finally:
        dienst.stoppen()


def test_frage_fehlerfaelle_ueber_http(tmp_path):
    fragen = _FragenAttrappe()
    dienst = _fragen_dienst(tmp_path, fragen)
    try:
        pfad = "/api/v1/aufnahmen/H5_007.opus/frage"
        assert anfrage(dienst, "POST", pfad, b"x")[0] == 415  # kein Content-Type
        assert anfrage(dienst, "POST", pfad, b"x", Content_Type="text/plain")[0] == 415
        assert anfrage(dienst, "POST", pfad, b"", Content_Type="audio/wav")[0] == 400  # kein Ton
        assert anfrage(dienst, "POST", pfad, b"x", Content_Type="audio/wav", X_Ausgabe="fernseher")[0] == 400
        assert anfrage(dienst, "POST", pfad, b"x", token=None, Content_Type="audio/wav")[0] == 401
        assert anfrage(dienst, "POST", "/api/v1/aufnahmen/mit%20leerzeichen.opus/frage", b"x", Content_Type="audio/wav")[0] == 400
        zu_gross = b"x" * (empfang.FRAGE_MAX_BYTES + 1)
        assert anfrage(dienst, "POST", pfad, zu_gross, Content_Type="audio/wav")[0] == 413
        fragen.bereit = False
        assert anfrage(dienst, "POST", pfad, b"x", Content_Type="audio/wav")[0] == 409  # noch kein Transkript
        assert fragen.eingereicht == []
        fragen.bereit = True

        def voll(*_args):
            raise frage_service.Ueberlastet("Es warten schon zu viele Fragen.")

        fragen.einreichen = voll  # type: ignore[method-assign]
        assert anfrage(dienst, "POST", pfad, b"x", Content_Type="audio/wav")[0] == 503  # spaeter noch einmal
    finally:
        dienst.stoppen()


def test_fremde_und_unbekannte_fragen_sind_nicht_zu_sehen(tmp_path):
    fragen = _FragenAttrappe()
    dienst = _fragen_dienst(tmp_path, fragen)
    try:
        assert anfrage(dienst, "GET", "/api/v1/fragen/0123456789abcdef", token=TOKEN_ZWEI)[0] == 404  # anderes Geraet
        assert _roh_holen(dienst, "/api/v1/fragen/0123456789abcdef/ton", TOKEN_ZWEI)[0] == 404
        assert anfrage(dienst, "GET", "/api/v1/fragen/ffffffffffffffff")[0] == 404
        assert anfrage(dienst, "GET", "/api/v1/fragen/nicht-hex")[0] == 404
        assert anfrage(dienst, "GET", "/api/v1/fragen/0123456789abcdef", token=None)[0] == 401
    finally:
        dienst.stoppen()


def test_ton_gibt_es_erst_wenn_die_frage_fertig_ist(tmp_path):
    fragen = _FragenAttrappe()
    fragen.zustand = {"zustand": "antworten", "frage": "Was macht Fritz?"}
    dienst = _fragen_dienst(tmp_path, fragen)
    try:
        status, _typ, inhalt = _roh_holen(dienst, "/api/v1/fragen/0123456789abcdef/ton")
        assert status == 409 and json.loads(inhalt)["zustand"] == "antworten"
        fragen.zustand = {"zustand": "fertig", "antwort": "Text", "ton_bytes": 0}
        fragen.wav = b""
        assert _roh_holen(dienst, "/api/v1/fragen/0123456789abcdef/ton")[0] == 404  # ohne Sprachausgabe kein Ton
    finally:
        dienst.stoppen()


def test_ohne_fragendienst_gibt_es_keine_fragen(dienst):
    assert anfrage(dienst, "POST", "/api/v1/aufnahmen/H5_007.opus/frage", b"x", Content_Type="audio/wav")[0] == 404
    assert anfrage(dienst, "GET", "/api/v1/fragen/0123456789abcdef")[0] == 404
