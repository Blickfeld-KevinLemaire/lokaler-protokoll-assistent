"""Tests fuer 'services/live_auswertung_service.py': Stufe 1 und 2 der Auswertung waehrend der Aufnahme.

Das Sprachmodell ist eine Attrappe; es laeuft kein Ollama und kein Whisper."""

from __future__ import annotations

import threading

import pytest

from protokoll_assistent.services import chunking_service, pipeline_service, protocol_service
from protokoll_assistent.services import live_auswertung_service as la

SCHLUESSEL = "S3/H5_007.opus"
AUFTRAG = "Liste die ToDos auf."
MODELL = "qwen-test"
LAENGE = chunking_service.DEFAULT_CHUNK_LENGTH_SECONDS
UEBERLAPPUNG = chunking_service.DEFAULT_OVERLAP_SECONDS
SCHRITT = LAENGE - UEBERLAPPUNG


def saetze(bis: float, takt: float = 5.0) -> list[dict]:
    """Ein Satz je ``takt`` Sekunden bis ``bis``: [0-4] 'S0', [5-9] 'S1' ..."""
    return [
        {"start": k * takt, "end": k * takt + 4.0, "text": f"S{k}", "speaker": None}
        for k in range(int(bis // takt))
        if k * takt + 4.0 <= bis
    ]


class Modell:
    """Attrappe des Sprachmodells: merkt sich jede Anfrage."""

    def __init__(self):
        self.anfragen: list[tuple[str, str]] = []
        self.fehler: Exception | None = None
        self.leer_fuer: set[int] = set()  # Abschnittsnummern (1-basiert), fuer die die Antwort leer ist
        self.sperre: threading.Event | None = None
        self.laeuft = threading.Event()

    def __call__(self, prompt: str, system: str) -> str:
        self.laeuft.set()
        if self.sperre is not None:
            assert self.sperre.wait(10)
        if self.fehler is not None:
            raise self.fehler
        self.anfragen.append((prompt, system))
        if "Teilergebnis 1 ---" in prompt:
            return f"Z{len([a for a in self.anfragen if 'Teilergebnis 1 ---' in a[0]])}"
        nummer = int(prompt.split("Abschnitt ")[1].split(" ")[0])
        return "" if nummer in self.leer_fuer else f"A{nummer}"

    @property
    def stufe1(self):
        return [p for p, _ in self.anfragen if "Teilergebnis 1 ---" not in p]

    @property
    def stufe2(self):
        return [p for p, _ in self.anfragen if "Teilergebnis 1 ---" in p]


@pytest.fixture
def modell():
    return Modell()


def bauen(modell, *, gruppe=4, einstellungen="ja", jetzt=None):
    stand = {"e": la.AuswertungsEinstellungen(AUFTRAG, MODELL, modell, gruppe) if einstellungen == "ja" else None}
    kwargs = {"jetzt": jetzt} if jetzt else {}
    auswertung = la.LiveAuswertung(lambda: stand["e"], **kwargs)
    auswertung.stand = stand  # type: ignore[attr-defined]
    return auswertung


@pytest.fixture
def auswertung(modell):
    a = bauen(modell)
    yield a
    a.stoppen()


def fortschritt(a, bis):
    a.fortschritt(SCHLUESSEL, saetze(bis), float(bis))
    assert a.warte_bis_fertig()


def erwartete_kennung_stufe1(index: int, segmente: list[dict]) -> str:
    anfang = index * SCHRITT
    plan = chunking_service.ChunkPlan(index, anfang, anfang + LAENGE, 0.0 if index == 0 else UEBERLAPPUNG, index == 0, False)
    chunk = pipeline_service.baue_protokoll_chunk_texte([plan], segmente, {}, False, fliesstext=True)[0]
    prompt = protocol_service.build_stage1_prompt(index, str(chunk["start_str"]), str(chunk["end_str"]), str(chunk["text"]))
    return protocol_service.eingabe_kennung(prompt, protocol_service.effektiver_systemprompt(AUFTRAG), MODELL)


# --------------------------------------------------------------------------
def test_ohne_kompletten_abschnitt_wird_nichts_gefragt(auswertung, modell):
    fortschritt(auswertung, 595)
    assert modell.anfragen == [] and auswertung.vorab_fuer(SCHLUESSEL) is None and auswertung.anzahl(SCHLUESSEL) == 0


def test_der_erste_abschnitt_wird_ausgewertet_sobald_sein_text_feststeht(auswertung, modell):
    fortschritt(auswertung, 605)
    assert len(modell.stufe1) == 1 and modell.stufe2 == []
    assert "Abschnitt 1 " in modell.stufe1[0] and "S0" in modell.stufe1[0] and "S118" in modell.stufe1[0]
    # Der Auftrag ist der alleinige Systemprompt, wie in der fertigen Auswertung
    assert modell.anfragen[0][1] == AUFTRAG
    vorab = auswertung.vorab_fuer(SCHLUESSEL)
    kennung = erwartete_kennung_stufe1(0, saetze(605))
    assert vorab == {"stufe1": {kennung: "A1"}, "stufe2": {}}
    assert auswertung.anzahl(SCHLUESSEL) == 1


def test_jeder_abschnitt_nur_einmal_auch_bei_wiederholten_meldungen(auswertung, modell):
    for bis in (605, 605, 610, 620):
        fortschritt(auswertung, bis)
    assert len(modell.stufe1) == 1


def test_folgeabschnitte_beginnen_hinter_der_ueberlappung(auswertung, modell):
    fortschritt(auswertung, 1195)  # Abschnitt 0 (0-600) und 1 (590-1190) stehen fest
    assert len(modell.stufe1) == 2
    zweiter = modell.stufe1[1]
    assert "Abschnitt 2 " in zweiter
    assert "S120" in zweiter and "S117" not in zweiter  # Text ab 600 s, nicht ab 590 s (das gehoert zum Vorgaenger)
    assert "S237" in zweiter and "S238" not in zweiter  # bis 1190 s
    # Dieselbe Kennung wie die fertige Auswertung sie fuer diesen Abschnitt berechnet
    assert erwartete_kennung_stufe1(1, saetze(1195)) in auswertung.vorab_fuer(SCHLUESSEL)["stufe1"]  # type: ignore[index]


def test_stufe_2_sobald_eine_gruppe_feststeht(modell):
    a = bauen(modell, gruppe=2)
    try:
        fortschritt(a, 605)
        assert modell.stufe2 == []  # erst ein Teilergebnis
        fortschritt(a, 1195)
        assert len(modell.stufe2) == 1  # Gruppe aus Abschnitt 1 und 2 ist voll
        assert "A1" in modell.stufe2[0] and "A2" in modell.stufe2[0]
        fortschritt(a, 1790)  # Abschnitt 3 (1180-1780) steht fest: neue, noch nicht volle Gruppe -> noch nichts
        assert len(modell.stufe2) == 1
        fortschritt(a, 2375)  # Abschnitt 4 (1770-2370): zweite Gruppe voll
        assert len(modell.stufe2) == 2 and "A3" in modell.stufe2[1] and "A4" in modell.stufe2[1]
        assert len(a.vorab_fuer(SCHLUESSEL)["stufe2"]) == 2  # type: ignore[index]
    finally:
        a.stoppen()


def test_abschnitt_ohne_text_wird_nicht_gefragt_aber_uebersprungen(auswertung, modell):
    # Stille im ersten Abschnitt: nur ab 700 s wird gesprochen
    segmente = [s for s in saetze(1195) if s["start"] >= 700]
    auswertung.fortschritt(SCHLUESSEL, segmente, 1195.0)
    assert auswertung.warte_bis_fertig()
    assert len(modell.stufe1) == 1 and "Abschnitt 2 " in modell.stufe1[0]
    assert auswertung.anzahl(SCHLUESSEL) == 2


def test_leere_antworten_werden_gemerkt_aber_nicht_zusammengefuehrt(modell):
    modell.leer_fuer = {2}
    a = bauen(modell, gruppe=2)
    try:
        fortschritt(a, 1195)
        fortschritt(a, 1790)  # Abschnitte 1 (leer), 2 (A2... Nummer 2 ist leer), 3
        vorab = a.vorab_fuer(SCHLUESSEL)
        assert vorab is not None and "" in vorab["stufe1"].values()
        # Die Gruppe enthaelt nur die nicht leeren Teilergebnisse: A1 und A3
        assert len(modell.stufe2) == 1 and "A1" in modell.stufe2[0] and "A3" in modell.stufe2[0] and "A2" not in modell.stufe2[0]
    finally:
        a.stoppen()


def test_ohne_einstellungen_passiert_nichts_und_spaeter_geht_es_los(modell):
    a = bauen(modell, einstellungen="nein")
    try:
        fortschritt(a, 1195)
        assert modell.anfragen == [] and a.anzahl(SCHLUESSEL) == 0
        a.stand["e"] = la.AuswertungsEinstellungen(AUFTRAG, MODELL, modell)  # type: ignore[attr-defined]
        fortschritt(a, 1200)
        assert len(modell.stufe1) == 2
    finally:
        a.stoppen()


def test_nach_einem_fehler_wird_eine_weile_pausiert_und_dann_weitergemacht(modell):
    zeit = {"t": 1000.0}
    a = bauen(modell, jetzt=lambda: zeit["t"])
    try:
        modell.fehler = RuntimeError("Ollama nicht erreichbar")
        fortschritt(a, 605)
        assert a.anzahl(SCHLUESSEL) == 0 and a.vorab_fuer(SCHLUESSEL) is None
        modell.fehler = None
        fortschritt(a, 610)  # Pause noch nicht vorbei: kein neuer Versuch
        assert modell.anfragen == []
        zeit["t"] += la.FEHLER_PAUSE_SEKUNDEN + 1
        fortschritt(a, 615)
        assert len(modell.stufe1) == 1 and a.anzahl(SCHLUESSEL) == 1
    finally:
        a.stoppen()


def test_nach_dem_ende_kommen_keine_neuen_segmente_mehr_dazu(auswertung, modell):
    fortschritt(auswertung, 605)
    auswertung.beenden(SCHLUESSEL)
    fortschritt(auswertung, 1300)  # wird ignoriert
    assert len(modell.stufe1) == 1  # Abschnitt 2 uebernimmt die fertige Auswertung


def test_nach_dem_ende_rechnet_nur_die_laufende_anfrage_fertig(modell):
    """Mit dem Ende der Aufnahme beginnt keine neue Anfrage mehr: Die Verarbeitung der fertigen Datei laedt gleich
    Whisper auf die Grafikkarte, und eine weitere Anfrage holte das Sprachmodell daneben zurueck ("CUDA out of
    memory" auf 6-GB-Karten). Die gerade laufende rechnet fertig und wird uebernommen; den Rest rechnet die fertige
    Auswertung."""
    modell.sperre = threading.Event()
    a = bauen(modell)
    try:
        a.fortschritt(SCHLUESSEL, saetze(1195), 1195.0)  # Abschnitt 1 und 2 stehen fest
        assert modell.laeuft.wait(5)  # Abschnitt 1 laeuft gerade
        a.beenden(SCHLUESSEL)
        modell.sperre.set()
        a.warte_auf_leerlauf(SCHLUESSEL, 10.0)
        vorab = a.vorab_fuer(SCHLUESSEL)
        assert len(modell.stufe1) == 1 and vorab is not None and len(vorab["stufe1"]) == 1
        assert a.anzahl(SCHLUESSEL) == 1
    finally:
        modell.sperre.set()
        a.stoppen()


def test_vorab_fuer_wartet_auf_die_laufende_anfrage(modell):
    modell.sperre = threading.Event()
    a = bauen(modell)
    try:
        a.fortschritt(SCHLUESSEL, saetze(605), 605.0)
        assert modell.laeuft.wait(5)  # die Anfrage haengt
        a.beenden(SCHLUESSEL)
        assert a.vorab_fuer(SCHLUESSEL, warten=0.0) is None  # ohne Geduld: noch nichts
        modell.sperre.set()
        vorab = a.vorab_fuer(SCHLUESSEL, warten=10.0)
        assert vorab is not None and list(vorab["stufe1"].values()) == ["A1"]
    finally:
        modell.sperre.set()
        a.stoppen()


def test_vorab_fuer_gibt_nach_dem_zeitlimit_auf_was_da_ist(modell):
    modell.sperre = threading.Event()
    a = bauen(modell)
    try:
        a.fortschritt(SCHLUESSEL, saetze(605), 605.0)
        assert modell.laeuft.wait(5)
        assert a.vorab_fuer(SCHLUESSEL, warten=0.2) is None  # nach 0,2 s Geduld: kein Ergebnis, aber auch kein Haengen
    finally:
        modell.sperre.set()
        a.stoppen()


def test_unbekannter_schluessel_und_freigeben(auswertung, modell):
    assert auswertung.vorab_fuer("gibt/es.nicht") is None and auswertung.anzahl("gibt/es.nicht") == 0
    fortschritt(auswertung, 605)
    auswertung.freigeben(SCHLUESSEL)
    assert auswertung.vorab_fuer(SCHLUESSEL) is None
    auswertung.freigeben(SCHLUESSEL)  # harmlos


def test_zwei_aufnahmen_gleichzeitig_bleiben_getrennt(auswertung, modell):
    auswertung.fortschritt("S3/A.opus", saetze(605), 605.0)
    auswertung.fortschritt("S3/B.opus", saetze(1195), 1195.0)
    assert auswertung.warte_bis_fertig()
    assert auswertung.anzahl("S3/A.opus") == 1 and auswertung.anzahl("S3/B.opus") == 2


def test_die_eingabe_enthaelt_das_modell_und_den_auftrag(modell):
    a1 = bauen(modell)
    a2 = la.LiveAuswertung(lambda: la.AuswertungsEinstellungen(AUFTRAG, "anderes-modell", modell))
    a3 = la.LiveAuswertung(lambda: la.AuswertungsEinstellungen("Anderer Auftrag", MODELL, modell))
    try:
        for a in (a1, a2, a3):
            a.fortschritt(SCHLUESSEL, saetze(605), 605.0)
            assert a.warte_bis_fertig()
        kennungen = [set(a.vorab_fuer(SCHLUESSEL)["stufe1"]) for a in (a1, a2, a3)]  # type: ignore[index]
        assert len(set.union(*kennungen)) == 3  # drei verschiedene Eingaben
    finally:
        for a in (a1, a2, a3):
            a.stoppen()


def test_ende_zu_ende_mit_der_fertigen_auswertung(tmp_path, modell):
    """Live berechnet, dann uebernommen: Die fertige Auswertung fragt nur noch den Rest."""
    a = bauen(modell, gruppe=2)
    try:
        fortschritt(a, 1790)  # Abschnitte 1 bis 3 sind live ausgewertet (bis 1780 s)
        live_anfragen = len(modell.anfragen)
        assert live_anfragen == 4  # drei Abschnitte + eine Gruppe (1 und 2)

        # Die fertige Aufnahme ist 2000 s lang; ihr Transkript enthaelt dieselben Saetze wie das Live-Transkript
        segmente = [
            {"start": s["start"], "sprecher_id": None, "text": s["text"]} for s in saetze(2000)
        ]
        plaene = chunking_service.plan_chunks(2000.0)
        chunk_texte = pipeline_service.baue_protokoll_chunk_texte(plaene, segmente, {}, False, fliesstext=True)
        vorab = a.vorab_fuer(SCHLUESSEL)
        neu1, neu2 = protocol_service.vorab_ergebnisse_ablegen(
            vorab, chunk_texte, tmp_path, AUFTRAG, 2, modell=MODELL
        )
        assert (neu1, neu2) == (3, 1)

        ergebnis = protocol_service.run_full_protocol_pipeline(
            chunk_texte, tmp_path, AUFTRAG, modell, group_size=2, modell=MODELL
        )
        nachher = len(modell.anfragen) - live_anfragen
        # 4 Abschnitte (0-600, 590-1190, 1180-1780, 1770-2000) und 2 Gruppen: Abschnitt 4, Gruppe 2 (A3, A4), Endergebnis
        assert nachher == 3 and ergebnis
    finally:
        a.stoppen()


def test_kurze_abschnitte_werden_entsprechend_frueher_ausgewertet(modell):
    a = la.LiveAuswertung(lambda: la.AuswertungsEinstellungen(AUFTRAG, MODELL, modell, 4, abschnitt_sekunden=180.0))
    try:
        a.fortschritt(SCHLUESSEL, saetze(179), 179.0)
        assert a.warte_bis_fertig() and len(modell.stufe1) == 0  # Abschnitt 1 reicht bis 180 s
        a.fortschritt(SCHLUESSEL, saetze(351), 351.0)  # Abschnitt 2: 170-350 s
        assert a.warte_bis_fertig() and len(modell.stufe1) == 2
        assert a.anzahl(SCHLUESSEL) == 2
        # Die Eingabe-Kennung gehoert zu den 180-s-Abschnitten (Abschnitt 2 beginnt hinter der Ueberlappung bei 180 s)
        vorab = a.vorab_fuer(SCHLUESSEL)
        assert vorab is not None and len(vorab["stufe1"]) == 2
    finally:
        a.stoppen()
