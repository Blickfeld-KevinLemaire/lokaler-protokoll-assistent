"""Tests fuer den Ablauf einer Sprachfrage (services/frage_service.py), mit Attrappen statt Whisper und Sprachmodell."""

from __future__ import annotations

import threading

import pytest

from protokoll_assistent.services import frage_service as fs


class Schritte:
    def __init__(self):
        self.erkannt: list[tuple[bytes, str]] = []
        self.gefragt: list[tuple[str, str, str, str]] = []
        self.gesprochen: list[str] = []
        self.text = "Was macht Fritz?"
        self.antwort = "Fritz schreibt das Angebot."
        self.fehler: Exception | None = None
        self.sperre: threading.Event | None = None

    def erkennen(self, ton: bytes, endung: str) -> str:
        self.erkannt.append((ton, endung))
        if self.sperre is not None:
            assert self.sperre.wait(10)
        if self.fehler:
            raise self.fehler
        return self.text

    def antworten(self, frage: str, geraet: str, datei: str, ausgabe: str) -> str:
        self.gefragt.append((frage, geraet, datei, ausgabe))
        return self.antwort

    def sprechen(self, text: str) -> bytes:
        self.gesprochen.append(text)
        return b"RIFF-ton"


@pytest.fixture
def schritte():
    return Schritte()


def bauen(schritte, *, mit_ton=True, **kwargs):
    return fs.FragenDienst(
        erkennen=schritte.erkennen,
        antworten=schritte.antworten,
        sprechen=schritte.sprechen if mit_ton else None,
        **kwargs,
    )


def test_eine_frage_durchlaeuft_verstehen_antworten_sprechen(schritte):
    dienst = bauen(schritte)
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"OggS-frage", ".opus", "ton")
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", kennung) == {
            "zustand": "fertig",
            "frage": "Was macht Fritz?",
            "antwort": "Fritz schreibt das Angebot.",
            "ton_bytes": len(b"RIFF-ton"),
        }
        assert dienst.ton("S3", kennung) == b"RIFF-ton"
        assert schritte.erkannt == [(b"OggS-frage", ".opus")]
        assert schritte.gefragt == [("Was macht Fritz?", "S3", "H5_007.opus", "ton")]
        assert schritte.gesprochen == ["Fritz schreibt das Angebot."]
    finally:
        dienst.stoppen()


def test_ohne_sprachausgabe_endet_die_frage_mit_dem_text(schritte):
    dienst = bauen(schritte, mit_ton=False)
    try:
        assert dienst.spricht is False
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        stand = dienst.stand("S3", kennung)
        assert stand["zustand"] == "fertig" and stand["antwort"] == "Fritz schreibt das Angebot."
        assert stand["ton_bytes"] == 0
        assert dienst.ton("S3", kennung) is None
    finally:
        dienst.stoppen()


def test_stand_zeigt_den_fortschritt_und_der_ton_kommt_erst_am_ende(schritte):
    schritte.sperre = threading.Event()
    dienst = bauen(schritte)
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.stand("S3", kennung)["zustand"] == "verstehen"
        assert dienst.ton("S3", kennung) is None
        schritte.sperre.set()
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", kennung)["zustand"] == "fertig"
    finally:
        if schritte.sperre is not None:
            schritte.sperre.set()
        dienst.stoppen()


def test_eine_frage_gehoert_nur_dem_geraet_das_sie_gestellt_hat(schritte):
    dienst = bauen(schritte)
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        assert dienst.stand("C6", kennung) is None and dienst.ton("C6", kennung) is None
        assert dienst.stand("S3", "0123456789abcdef") is None
    finally:
        dienst.stoppen()


@pytest.mark.parametrize("fehler", [RuntimeError("Ollama nicht erreichbar"), ValueError("kaputt")])
def test_fehler_werden_gemeldet_und_halten_die_naechste_frage_nicht_auf(schritte, fehler):
    dienst = bauen(schritte)
    try:
        schritte.fehler = fehler
        erste = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        stand = dienst.stand("S3", erste)
        assert stand["zustand"] == "fehler" and str(fehler) in stand["meldung"]
        schritte.fehler = None
        zweite = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", zweite)["zustand"] == "fertig"
    finally:
        dienst.stoppen()


def test_nicht_verstandene_frage_und_leere_antwort_sind_fehler(schritte):
    dienst = bauen(schritte)
    try:
        schritte.text = "  "
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", kennung)["zustand"] == "fehler"
        schritte.text, schritte.antwort = "Frage?", " "
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", kennung)["zustand"] == "fehler"
    finally:
        dienst.stoppen()


def test_unbekannte_endung_wird_abgelehnt(schritte):
    dienst = bauen(schritte)
    with pytest.raises(ValueError):
        dienst.einreichen("S3", "H5_007.opus", b"x", ".exe")


def test_alte_und_ueberzaehlige_fragen_werden_verworfen(schritte):
    jetzt = [1000.0]
    dienst = bauen(schritte, jetzt=lambda: jetzt[0], max_eintraege=2, max_alter=60)
    try:
        erste = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        zweite = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        dritte = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")  # verdraengt die aelteste
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", erste) is None and dienst.stand("S3", zweite) is not None
        jetzt[0] += 120
        dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")  # raeumt auf: zweite und dritte sind zu alt
        assert dienst.warte_bis_fertig()
        assert dienst.stand("S3", zweite) is None and dienst.stand("S3", dritte) is None
    finally:
        dienst.stoppen()


def test_unbearbeitete_fragen_stapeln_sich_nicht_unbegrenzt(schritte):
    schritte.sperre = threading.Event()  # die erste Frage haengt im Verstehen, der Rest wartet
    dienst = bauen(schritte, max_eintraege=2)
    try:
        dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        with pytest.raises(fs.Ueberlastet):
            dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        schritte.sperre.set()
        assert dienst.warte_bis_fertig()
        assert dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")  # erledigte machen wieder Platz
        assert dienst.warte_bis_fertig()
    finally:
        schritte.sperre.set()
        dienst.stoppen()


def test_bereit_fuer_fragt_die_oberflaeche(schritte):
    dienst = bauen(schritte, bereit=lambda geraet, datei: datei == "H5_007.opus")
    assert dienst.bereit_fuer("S3", "H5_007.opus") and not dienst.bereit_fuer("S3", "H5_008.opus")
    assert bauen(schritte).bereit_fuer("S3", "egal.opus")


def test_standard_ist_die_anzeige_fuers_display_auch_wenn_eine_sprachausgabe_da_ist(schritte):
    schritte.antwort = "1. Angebot schreiben (Fritz)\n2. Termin klären"
    dienst = bauen(schritte, anzeige=str.upper)
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        stand = dienst.stand("S3", kennung)
        assert stand["zustand"] == "fertig" and stand["ton_bytes"] == 0
        assert stand["anzeige"] == "1. ANGEBOT SCHREIBEN (FRITZ)\n2. TERMIN KLÄREN"
        assert schritte.gesprochen == [] and schritte.gefragt[0][3] == "anzeige"
        assert dienst.ton("S3", kennung) is None
    finally:
        dienst.stoppen()


def test_mit_ton_gibt_es_beides_anzeige_und_ton(schritte):
    dienst = bauen(schritte, anzeige=str.upper)
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav", "ton")
        assert dienst.warte_bis_fertig()
        stand = dienst.stand("S3", kennung)
        assert stand["anzeige"] == "FRITZ SCHREIBT DAS ANGEBOT." and stand["ton_bytes"] > 0
    finally:
        dienst.stoppen()


def test_was_das_display_braucht_steht_vorn_und_passt_in_den_puffer_des_geraets(schritte):
    """Das Geraet liest den Stand in einen festen Puffer: Eine ausufernde Antwort darf die Anzeige nicht verdraengen."""
    schritte.text = "Was hat Jörg übernommen?"
    schritte.antwort = "\n".join(f"{i}. " + "Punkt " * 30 for i in range(1, 40))  # haelt sich nicht an den Prompt
    dienst = bauen(schritte, mit_ton=False, anzeige=lambda t: t.replace("ö", "oe").replace("ü", "ue"))
    try:
        kennung = dienst.einreichen("S3", "H5_007.opus", b"x", ".wav")
        assert dienst.warte_bis_fertig()
        stand = dienst.stand("S3", kennung)
        assert list(stand) == ["zustand", "frage", "anzeige", "meldung", "ton_bytes", "antwort"]
        assert stand["frage"] == "Was hat Joerg uebernommen?"  # ASCII fuer die Schrift des Geraets
        assert len(stand["anzeige"]) <= fs.ANZEIGE_MAX_ZEICHEN and stand["anzeige"].endswith("...")
        zeilen = stand["anzeige"][: -len("...")].split("\n")
        assert all(z.rstrip() == f"{i}. " + ("Punkt " * 30).rstrip() for i, z in enumerate(zeilen, 1))  # ganze Zeilen
        assert stand["antwort"] == schritte.antwort.strip()  # ungekuerzt, am Ende
    finally:
        dienst.stoppen()


def test_unbekannte_ausgabe_wird_abgelehnt(schritte):
    dienst = bauen(schritte)
    with pytest.raises(ValueError):
        dienst.einreichen("S3", "H5_007.opus", b"x", ".wav", "fernseher")
