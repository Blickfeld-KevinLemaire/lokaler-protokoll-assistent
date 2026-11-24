"""Zugang: jeder Endpunkt geschuetzt (ausser einer festen Liste), Hosts, Anmeldung im Browser, CSRF."""

from __future__ import annotations

from pathlib import Path

import pytest

from protokoll_assistent.api import sicherheit
from protokoll_assistent.api.app import OEFFENTLICHE_PFADE
from protokoll_assistent.api.sicherheit import ROLLE_SERVER, Zugang, zugaenge_aus_konfiguration
from protokoll_assistent.tests.api_hilfen import SCHLUESSEL, ZUGANG, Umgebung, app_bauen, eigene_konfiguration


@pytest.fixture
def umgebung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Umgebung:
    eigene_konfiguration(monkeypatch, tmp_path)
    return app_bauen(tmp_path)


def _beispielpfad(pfad: str) -> str:
    return pfad.replace("{rest:path}", "x").replace("{", "").replace("}", "")


def test_jeder_endpunkt_ausser_den_oeffentlichen_verlangt_anmeldung(umgebung: Umgebung) -> None:
    """Lehre aus einem frueheren Projekt: Ein neuer Endpunkt darf nie aus Versehen offen sein."""
    client = umgebung.client
    client.headers.pop("Authorization")
    geprueft = 0
    # Aus der Schnittstellenbeschreibung, nicht aus 'app.routes': deren Aufbau hat sich bei FastAPI schon
    # einmal geaendert (die Liste wurde verzoegert gefuellt) -- der Test haette dann still nichts geprueft.
    for pfad, methoden in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        if pfad in OEFFENTLICHE_PFADE:
            continue
        for methode in methoden:
            antwort = client.request(methode.upper(), _beispielpfad(pfad))
            assert antwort.status_code == 401, f"{methode} {pfad} -> {antwort.status_code}"
            geprueft += 1
    assert geprueft > 30


def test_oeffentlich_und_falscher_schluessel(umgebung: Umgebung) -> None:
    client = umgebung.client
    assert client.get("/api/gesundheit").json()["status"] == "ok"
    assert client.get("/api/info").status_code == 200
    assert client.get("/api/info", headers={"Authorization": "Bearer falsch"}).status_code == 401
    assert client.get("/api/info", headers={"Authorization": "Basic abc"}).status_code == 401


def test_fremder_host_wird_abgewiesen(umgebung: Umgebung) -> None:
    antwort = umgebung.client.get("/api/gesundheit", headers={"Host": "boese.example"})
    assert antwort.status_code == 400


def test_unbekannter_api_pfad_ist_json_404(umgebung: Umgebung) -> None:
    antwort = umgebung.client.get("/api/gibt/es/nicht")
    assert antwort.status_code == 404 and antwort.json()["detail"] == "Unbekannter Endpunkt."


def test_desktop_ohne_schluessel_geht_nicht() -> None:
    with pytest.raises(ValueError, match="braucht einen Schluessel"):
        Zugang("desktop")
    with pytest.raises(ValueError, match="Unbekannte Rolle"):
        Zugang("gast")


def test_anmeldung_im_browser_mit_cookie_und_csrf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    u = app_bauen(tmp_path, rolle=ROLLE_SERVER)
    client = u.client
    assert client.get("/api/info").status_code == 401
    assert client.post("/api/anmelden", json={"schluessel": "falsch"}).status_code == 401
    antwort = client.post("/api/anmelden", json={"schluessel": ZUGANG})
    assert antwort.status_code == 200 and antwort.json() == {"angemeldet_als": "browser"}
    assert client.get("/api/info").json()["rolle"] == "server"
    # Aendernde Anfrage ueber Cookie ohne Kennzeichnung: abgelehnt.
    assert client.patch("/api/einstellungen", json={"sprache": "en"}).status_code == 403
    assert client.patch("/api/einstellungen", json={"sprache": "en"}, headers={"X-Vermerk-Anfrage": "1"}).status_code == 200
    # Mit Zugangsschluessel als Bearer geht es auch ohne Cookie.
    assert client.get("/api/info", headers={"Authorization": f"Bearer {ZUGANG}"}).status_code == 200
    assert client.post("/api/abmelden").json() == {"abgemeldet": True}
    assert client.get("/api/info").status_code == 401


def test_zu_viele_fehlversuche(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eigene_konfiguration(monkeypatch, tmp_path)
    client = app_bauen(tmp_path, rolle=ROLLE_SERVER).client
    for _ in range(sicherheit.FEHLVERSUCHE_PRO_MINUTE):
        client.post("/api/anmelden", json={"schluessel": "falsch"})
    assert client.post("/api/anmelden", json={"schluessel": ZUGANG}).status_code == 429


def test_sitzung_laeuft_ab() -> None:
    uhr = [1000.0]
    zugang = Zugang(ROLLE_SERVER, zugaenge=lambda: {"a": sicherheit.schluessel_hash("k")}, jetzt=lambda: uhr[0])
    ergebnis = zugang.anmelden("k", "1.2.3.4")
    assert ergebnis is not None
    token, name = ergebnis
    assert name == "a"

    class Anfrage:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.cookies = {sicherheit.COOKIE_NAME: token}
            self.method = "GET"

    assert zugang.wer(Anfrage()) == "a"  # type: ignore[arg-type]
    uhr[0] += sicherheit.SITZUNG_SEKUNDEN + 1
    assert zugang.wer(Anfrage()) is None  # type: ignore[arg-type]
    assert zugang.wer(Anfrage()) is None  # type: ignore[arg-type]
    zugang.abmelden(None)
    assert zugang.anmelden("", "1.2.3.4") is None


def test_entfernter_zugangsschluessel_beendet_die_browser_sitzung() -> None:
    """Netzfreigabe ohne Nutzerverwaltung: Wird ein Zugangsschluessel entfernt (oder ersetzt), endet auch die damit
    im Browser angelegte Sitzung -- nicht erst nach Ablauf der 12 Stunden."""
    zugaenge = {"laptop": sicherheit.schluessel_hash("k"), "tablet": sicherheit.schluessel_hash("t")}
    zugang = Zugang(ROLLE_SERVER, zugaenge=lambda: dict(zugaenge))
    ergebnis = zugang.anmelden("k", "1.2.3.4")
    assert ergebnis is not None

    class Anfrage:
        headers: dict[str, str] = {}
        cookies = {sicherheit.COOKIE_NAME: ergebnis[0]}
        method = "GET"

    assert zugang.wer(Anfrage()) == "laptop"  # type: ignore[arg-type]
    zugaenge["laptop"] = sicherheit.schluessel_hash("neu")  # neu angelegt: der alte Schluessel gilt nicht mehr
    assert zugang.wer(Anfrage()) is None  # type: ignore[arg-type]
    zugaenge["laptop"] = sicherheit.schluessel_hash("k")
    assert zugang.wer(Anfrage()) is None  # type: ignore[arg-type]  # die Sitzung ist verworfen
    zugang.sitzung_behalten(ergebnis[0], "laptop")  # ohne Nutzerverwaltung: nichts zu tun


def test_zugaenge_aus_konfiguration() -> None:
    zugaenge = zugaenge_aus_konfiguration(
        [{"name": "a", "token_sha256": "A" * 64}, {"name": "", "token_sha256": "b" * 64}, {"name": "c"}, "unsinn"],
        "aus-der-umgebung",
    )
    assert zugaenge == {"a": "a" * 64, "umgebung": sicherheit.schluessel_hash("aus-der-umgebung")}
    assert len(sicherheit.schluessel_erzeugen()) >= 40
    assert SCHLUESSEL not in sicherheit.schluessel_hash(SCHLUESSEL)
