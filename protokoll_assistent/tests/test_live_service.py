"""Tests fuer 'services/ogg_opus.py' und 'services/live_service.py'.

Ohne Whisper, ohne ffmpeg: Der Transkribierer und der Audio-Schnitt sind
Attrappen, und die Ogg-Dateien werden von Hand gebaut.
"""

from __future__ import annotations

import json
import threading

import pytest

from protokoll_assistent.services import live_service as ls
from protokoll_assistent.services import ogg_opus


# --------------------------------------------------------------------------
# Ogg-Opus von Hand
# --------------------------------------------------------------------------
def _seite(granul: int, nutzlast: bytes, *, serie: int = 1, nummer: int = 0, typ: int = 0) -> bytes:
    segmente = []
    rest = len(nutzlast)
    while rest >= 255:
        segmente.append(255)
        rest -= 255
    segmente.append(rest)
    kopf = (
        b"OggS"
        + bytes([0, typ])
        + granul.to_bytes(8, "little")
        + serie.to_bytes(4, "little")
        + nummer.to_bytes(4, "little")
        + bytes(4)  # Pruefsumme: wird hier nicht gelesen
        + bytes([len(segmente)])
        + bytes(segmente)
    )
    return kopf + nutzlast


def opus_bytes(sekunden: float, *, vorlauf: int = 312, seiten_je_sekunde: int = 1) -> bytes:
    """Eine Ogg-Opus-Datei mit Kopfseiten und Datenseiten, die ``sekunden`` lang ist."""
    kopf = b"OpusHead" + bytes([1, 1]) + vorlauf.to_bytes(2, "little") + (16000).to_bytes(4, "little") + bytes(3)
    daten = _seite(0, kopf, nummer=0, typ=2) + _seite(0, b"OpusTags" + bytes(20), nummer=1)
    anzahl = int(sekunden * seiten_je_sekunde)
    for n in range(1, anzahl + 1):
        granul = vorlauf + round(n * 48000 / seiten_je_sekunde)
        daten += _seite(granul, bytes([n % 256]) * 300, nummer=n + 1)
    return daten


def test_dauer_einer_vollstaendigen_datei(tmp_path):
    datei = tmp_path / "a.opus"
    datei.write_bytes(opus_bytes(40.0))
    assert ogg_opus.opus_dauer_sekunden(datei) == pytest.approx(40.0)


def test_dauer_einer_abgeschnittenen_datei_zaehlt_nur_vollstaendige_seiten(tmp_path):
    ganz = opus_bytes(40.0)
    datei = tmp_path / "a.opus"
    datei.write_bytes(ganz[:-100])  # die letzte Seite fehlt zum Teil
    assert ogg_opus.opus_dauer_sekunden(datei) == pytest.approx(39.0)


def test_seite_ohne_abgeschlossenes_paket_wird_uebergangen(tmp_path):
    # Granulposition -1: Auf dieser Seite endet kein Paket (ein Paket ueber mehrere Seiten).
    daten = opus_bytes(10.0) + _seite(0xFFFFFFFFFFFFFFFF, b"x" * 50, nummer=99)
    datei = tmp_path / "a.opus"
    datei.write_bytes(daten)
    assert ogg_opus.opus_dauer_sekunden(datei) == pytest.approx(10.0)


def test_nur_die_kopfseiten_ergeben_noch_keine_dauer_oder_null(tmp_path):
    datei = tmp_path / "a.opus"
    datei.write_bytes(opus_bytes(0.0))
    assert ogg_opus.opus_dauer_sekunden(datei) == 0.0


def test_kein_opus_und_fehlende_datei(tmp_path):
    assert ogg_opus.opus_dauer_sekunden(tmp_path / "gibt-es-nicht.opus") is None
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF" + bytes(100))
    assert ogg_opus.opus_dauer_sekunden(wav) is None


def test_ein_oggs_in_der_nutzlast_stoert_nicht(tmp_path):
    nutzlast = b"xx" + b"OggS" + b"\x00" * 40
    daten = opus_bytes(5.0) + _seite(48000 * 5 + 312 + 48000, nutzlast, nummer=50)
    datei = tmp_path / "a.opus"
    datei.write_bytes(daten)
    assert ogg_opus.opus_dauer_sekunden(datei) == pytest.approx(6.0)


def test_dauer_nur_aus_dem_dateiende_auch_bei_grosser_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(ogg_opus, "_SUCHFENSTER", 4096)
    datei = tmp_path / "a.opus"
    datei.write_bytes(opus_bytes(120.0))  # deutlich groesser als das Suchfenster
    assert ogg_opus.opus_dauer_sekunden(datei) == pytest.approx(120.0)


# --------------------------------------------------------------------------
# Status fuers Geraet
# --------------------------------------------------------------------------
def test_status_setzen_und_holen():
    register = ls.StatusRegister(jetzt=lambda: 1000.4)
    assert register.hole("S3", "a.opus") is None
    register.setze("S3", "a.opus", ls.TRANSKRIPTION, 0.4567, "laeuft")
    assert register.hole("S3", "a.opus") == {
        "zustand": "transkription",
        "fortschritt": 0.457,
        "meldung": "laeuft",
        "aktualisiert": 1000,
    }
    register.setze("S3", "a.opus", ls.FERTIG)
    assert register.hole("S3", "a.opus") == {"zustand": "fertig", "aktualisiert": 1000}


def test_status_begrenzt_fortschritt_und_verlangt_bekannten_zustand():
    register = ls.StatusRegister()
    register.setze("S3", "a.opus", ls.AUSWERTUNG, 7.0)
    assert register.hole("S3", "a.opus")["fortschritt"] == 1.0  # type: ignore[index]
    with pytest.raises(ValueError, match="Unbekannter Zustand"):
        register.setze("S3", "a.opus", "kaputt")


def test_status_vergisst_die_aeltesten():
    register = ls.StatusRegister(max_eintraege=2)
    for nummer in range(3):
        register.setze("S3", f"{nummer}.opus", ls.EMPFANG)
    assert register.hole("S3", "0.opus") is None and register.hole("S3", "2.opus") is not None


def test_status_ist_aus_mehreren_faeden_benutzbar():
    register = ls.StatusRegister()

    def schreiben(name):
        for n in range(200):
            register.setze("S3", f"{name}{n % 5}.opus", ls.EMPFANG, n / 200)

    faeden = [threading.Thread(target=schreiben, args=(name,)) for name in "abcd"]
    for faden in faeden:
        faden.start()
    for faden in faeden:
        faden.join()
    assert register.hole("S3", "a0.opus") is not None


# --------------------------------------------------------------------------
# Hilfen fuer Segmente
# --------------------------------------------------------------------------
def seg(start, ende, text="x"):
    return {"start": start, "end": ende, "text": text, "speaker": None}


def test_minuten_sekunden_und_vorschau():
    assert ls.minuten_sekunden(0) == "00:00" and ls.minuten_sekunden(75.9) == "01:15" and ls.minuten_sekunden(3725) == "62:05"
    assert ls.minuten_sekunden(-3) == "00:00"
    text = ls.vorschau_text([seg(0.0, 4.0, "Hallo"), seg(5.0, 9.0, "  "), seg(65.2, 70.0, "Zweite Minute")])
    assert text == "[00:00] Hallo\n[01:05] Zweite Minute"
    assert ls.vorschau_text([]) == ""


def test_bestaetigen_ohne_sprache_rueckt_bis_kurz_vor_das_fensterende_vor():
    fest, punkt = ls.bestaetigen([], 10.0, 40.0, erzwingen=False)
    assert fest == [] and punkt == 40.0 - ls.STILLE_RESERVE_SEKUNDEN
    assert ls.bestaetigen([], 10.0, 10.5, erzwingen=False)[1] == 10.0  # nie vor den Start zurueck


def test_bestaetigen_laesst_das_letzte_segment_am_fensterende_aus():
    segmente = [seg(10, 14), seg(15, 19), seg(20, 24.4)]
    fest, punkt = ls.bestaetigen(segmente, 10.0, 24.5, erzwingen=False)
    assert fest == segmente[:2] and punkt == 19


def test_bestaetigen_nimmt_alles_wenn_danach_noch_stille_kommt():
    segmente = [seg(10, 14), seg(15, 19)]
    fest, punkt = ls.bestaetigen(segmente, 10.0, 24.5, erzwingen=False)  # 5,5 s Stille nach dem letzten
    assert fest == segmente and punkt == 19


def test_bestaetigen_ein_einziges_unsicheres_segment_bringt_keinen_fortschritt_ausser_erzwungen():
    segmente = [seg(10, 24.4)]
    assert ls.bestaetigen(segmente, 10.0, 24.5, erzwingen=False) == ([], 10.0)
    fest, punkt = ls.bestaetigen(segmente, 10.0, 24.5, erzwingen=True)
    assert fest == segmente and punkt == 24.4


# --------------------------------------------------------------------------
# Live-Transkription
# --------------------------------------------------------------------------
def saetze(start, ende, takt=5.0, laenge=4.0):
    """Wie Whisper bei regelmaessiger Sprache: ein Satz je ``takt`` Sekunden; was am Fensterende noch laeuft,
    wird abgeschnitten. Globale Zeitstempel."""
    ergebnis = []
    k = int(start // takt) if start % takt == 0 else int(start // takt) + 1
    while k * takt < ende:
        s, e = k * takt, k * takt + laenge
        ergebnis.append(seg(s, min(e, ende), f"S{k}"))
        k += 1
    return ergebnis


class _Welt:
    """Gemeinsamer Zustand der Attrappen: wie lang die Aufnahme gerade ist, was geschnitten wurde, was Whisper sagt."""

    def __init__(self):
        self.dauer: float | None = 0.0
        self.geschnitten: list[tuple[float, float]] = []
        self.fabrik_aufrufe = 0
        self.fehler_beim_laden: Exception | None = None
        self.sprache = saetze  # (start, ende) -> Segmente mit globalen Zeitstempeln
        self._fenster = (0.0, 0.0)

    def dauer_fn(self, _pfad):
        return self.dauer

    def extrahieren(self, quelle, ziel, start, ende):
        assert quelle.is_file()  # eine Momentaufnahme der wachsenden Datei
        self.geschnitten.append((start, ende))
        self._fenster = (start, ende)
        ziel.write_bytes(b"wav")

    def fabrik(self):
        self.fabrik_aufrufe += 1
        if self.fehler_beim_laden is not None:
            raise self.fehler_beim_laden

        def transkribiere(_wav):
            start, ende = self._fenster
            # Whisper liefert Zeitstempel relativ zum Fenster
            return [{**s, "start": s["start"] - start, "end": s["end"] - start} for s in self.sprache(start, ende)]

        return transkribiere


@pytest.fixture
def welt():
    return _Welt()


@pytest.fixture
def teil(tmp_path):
    datei = tmp_path / ".empfang" / "abc.teil"
    datei.parent.mkdir()
    datei.write_bytes(b"OggS-wachsende-aufnahme")
    return datei


@pytest.fixture
def live(tmp_path, welt):
    status = ls.StatusRegister()
    ereignisse: list[tuple] = []
    live = ls.LiveTranskription(
        tmp_path / "arbeit",
        welt.fabrik,
        status=status,
        bei_aenderung=lambda *a: ereignisse.append(a),
        dauer_fn=welt.dauer_fn,
        extrahieren=welt.extrahieren,
    )
    live.status = status  # type: ignore[attr-defined]
    live.ereignisse = ereignisse  # type: ignore[attr-defined]
    yield live
    live.stoppen()


def wachsen(live, welt, teil, dauer, datei="H5_007.opus"):
    welt.dauer = dauer
    live.teil_gewachsen("S3", datei, teil)
    assert live.warte_bis_fertig()


def test_ohne_genug_neues_audio_passiert_nichts(live, welt, teil):
    wachsen(live, welt, teil, ls.NEU_MIN_SEKUNDEN - 0.5)
    assert welt.geschnitten == [] and welt.fabrik_aufrufe == 0  # das Modell wird noch nicht einmal geladen


def test_das_erste_fenster_beginnt_sobald_zwanzig_sekunden_da_sind(live, welt, teil):
    wachsen(live, welt, teil, 25.0)
    assert welt.geschnitten == [(0.0, 24.5)]


def test_bestaetigt_wird_alles_ausser_dem_letzten_moeglicherweise_abgeschnittenen_satz(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 25.0)  # Saetze 0-4, 5-9, 10-14, 15-19, 20-24.5 (abgeschnitten)
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    assert live.warte_bis_fertig()
    vorab = live.vorab_fuer(ziel)
    assert vorab is not None and vorab["bestaetigt_bis"] == 19.0
    assert [s["text"] for s in vorab["segmente"]] == ["S0", "S1", "S2", "S3"]


def test_das_naechste_fenster_beginnt_am_sicheren_punkt_und_nichts_wird_doppelt(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 25.0)
    wachsen(live, welt, teil, 45.0)
    assert welt.geschnitten == [(0.0, 24.5), (19.0, 44.5)]  # das abgeschnittene Ende wird neu mitgerechnet
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    live.warte_bis_fertig()
    vorab = live.vorab_fuer(ziel)
    texte = [s["text"] for s in vorab["segmente"]]
    assert texte == [f"S{k}" for k in range(8)] and vorab["bestaetigt_bis"] == 39.0
    starts = [s["start"] for s in vorab["segmente"]]
    assert starts == sorted(set(starts))
    assert welt.fabrik_aufrufe == 1  # das Modell wird einmal geladen


def test_mehrere_fenster_hintereinander_wenn_viel_neues_audio_auf_einmal_kommt(live, welt, teil):
    wachsen(live, welt, teil, 200.0)
    assert len(welt.geschnitten) >= 4
    for (s1, e1), (s2, _e2) in zip(welt.geschnitten, welt.geschnitten[1:], strict=False):
        assert s2 > s1 and s2 <= e1  # jedes Fenster knuepft am vorigen an
        assert e1 - s1 <= ls.FENSTER_MAX_SEKUNDEN + 1e-6


def test_stille_rueckt_vor_ohne_segmente(live, welt, teil, tmp_path):
    welt.sprache = lambda start, ende: []
    wachsen(live, welt, teil, 40.0)
    wachsen(live, welt, teil, 70.0)
    assert welt.geschnitten[0] == (0.0, 39.5)
    assert welt.geschnitten[1][0] == pytest.approx(39.5 - ls.STILLE_RESERVE_SEKUNDEN)  # Reserve fuer einen Wortanfang
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    live.warte_bis_fertig()
    assert live.vorab_fuer(ziel) is None  # nichts gesagt: nichts vorab


def test_langer_monolog_wird_irgendwann_trotzdem_bestaetigt(live, welt, teil, tmp_path):
    welt.sprache = lambda start, ende: [seg(start, ende, "Monolog")]  # ein Segment ueber das ganze Fenster
    wachsen(live, welt, teil, 25.0)
    wachsen(live, welt, teil, 46.0)  # Fenster jetzt 0-45 = so lang wie erlaubt: gilt als bestaetigt
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    live.warte_bis_fertig()
    vorab = live.vorab_fuer(ziel)
    assert vorab is not None and vorab["bestaetigt_bis"] == 45.0
    assert welt.geschnitten == [(0.0, 24.5), (0.0, 45.0)]


def test_ohne_neues_audio_wird_ein_ergebnisloses_fenster_nicht_wiederholt(live, welt, teil):
    welt.sprache = lambda start, ende: [seg(start, ende, "Monolog")]  # kein Fortschritt moeglich
    wachsen(live, welt, teil, 25.0)
    anzahl = len(welt.geschnitten)
    for _ in range(3):
        wachsen(live, welt, teil, 25.0)   # dieselbe Dauer: nichts Neues
        wachsen(live, welt, teil, 30.0)   # zu wenig neues Audio seit dem letzten Fenster
    assert len(welt.geschnitten) == anzahl


def test_andere_dateiformate_und_fremde_namen_werden_ignoriert(live, welt, teil):
    wachsen(live, welt, teil, 200.0, datei="H5_007.wav")
    wachsen(live, welt, teil, 200.0, datei="H5_008.mp3")
    assert welt.geschnitten == []


def test_status_und_meldung_nennen_wie_weit_die_transkription_ist(live, welt, teil):
    wachsen(live, welt, teil, 25.0)
    eintrag = live.status.hole("S3", "H5_007.opus")  # type: ignore[attr-defined]
    assert eintrag["zustand"] == "empfang" and "bis 00:19 transkribiert" in eintrag["meldung"]
    geraet, datei, text, bis = live.ereignisse[-1]  # type: ignore[attr-defined]
    assert (geraet, datei, bis) == ("S3", "H5_007.opus", 19.0)
    assert text.splitlines()[0] == "[00:00] S0" and text.splitlines()[-1] == "[00:15] S3"


def test_kein_text_ereignis_und_kein_fehler_wenn_nichts_bestaetigt_wurde(live, welt, teil):
    welt.sprache = lambda start, ende: [seg(start, ende, "Monolog")]
    wachsen(live, welt, teil, 25.0)
    assert live.ereignisse == []  # type: ignore[attr-defined]


def test_fehler_in_der_anzeige_stoert_die_transkription_nicht(tmp_path, welt, teil):
    def kaputt(*_a):
        raise RuntimeError("Anzeige weg")

    live = ls.LiveTranskription(
        tmp_path / "arbeit", welt.fabrik, bei_aenderung=kaputt, dauer_fn=welt.dauer_fn, extrahieren=welt.extrahieren
    )
    try:
        wachsen(live, welt, teil, 25.0)
        wachsen(live, welt, teil, 50.0)
        assert len(welt.geschnitten) == 2
    finally:
        live.stoppen()


def test_abschluss_gibt_die_bestaetigten_segmente_frei_und_beginnt_kein_neues_fenster(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 45.0)
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"fertig")
    bereit = threading.Event()
    live.abgeschlossen("S3", "H5_007.opus", ziel, bereit.set)
    assert bereit.wait(5)
    vorab = live.vorab_fuer(ziel)
    assert vorab is not None and vorab["bestaetigt_bis"] == 39.0 and len(vorab["segmente"]) == 8
    assert live.vorab_fuer(tmp_path / "andere.opus") is None
    # Nach dem Abschluss beginnt kein neues Fenster mehr.
    welt.dauer = 500.0
    live.teil_gewachsen("S3", "H5_007.opus", teil)
    live.warte_bis_fertig()
    assert live.vorab_fuer(ziel)["bestaetigt_bis"] == 39.0  # type: ignore[index]
    # Eine Kopie: Aenderungen am Ergebnis veraendern den Zwischenstand nicht.
    vorab["segmente"].clear()
    assert len(live.vorab_fuer(ziel)["segmente"]) == 8  # type: ignore[index]


def test_abschluss_ohne_live_sitzung_meldet_sofort_bereit(live, tmp_path):
    bereit = []
    live.abgeschlossen("S3", "H5_009.opus", tmp_path / "x.opus", lambda: bereit.append(True))
    assert bereit == [True]
    assert live.vorab_fuer(tmp_path / "x.opus") is None


def test_abschluss_wartet_auf_das_laufende_fenster(tmp_path, teil):
    """Die Verarbeitung der fertigen Datei darf erst nach dem gerade laufenden Fenster beginnen."""
    freigabe = threading.Event()
    laeuft = threading.Event()

    def fabrik():
        def transkribiere(_wav):
            laeuft.set()
            assert freigabe.wait(5)
            return [seg(0.0, 4.0, "a"), seg(5.0, 9.0, "b"), seg(10.0, 14.0, "c")]

        return transkribiere

    live = ls.LiveTranskription(
        tmp_path / "arbeit",
        fabrik,
        dauer_fn=lambda _p: 40.0,
        extrahieren=lambda q, z, a, b: z.write_bytes(b"w"),
    )
    try:
        live.teil_gewachsen("S3", "H5_007.opus", teil)
        assert laeuft.wait(5)
        ziel = tmp_path / "S3_H5_007.opus"
        ziel.write_bytes(b"x")
        bereit = threading.Event()
        live.abgeschlossen("S3", "H5_007.opus", ziel, bereit.set)
        assert not bereit.wait(0.2)  # das Fenster laeuft noch
        freigabe.set()
        assert bereit.wait(5)
        assert live.vorab_fuer(ziel)["bestaetigt_bis"] == 14.0  # type: ignore[index]
    finally:
        freigabe.set()
        live.stoppen()


def test_ohne_whisper_wird_live_abgeschaltet_und_nichts_blockiert(live, welt, teil, tmp_path):
    welt.fehler_beim_laden = ModuleNotFoundError("faster_whisper")
    wachsen(live, welt, teil, 40.0)
    assert live.deaktiviert
    bereit = []
    live.abgeschlossen("S3", "H5_007.opus", tmp_path / "S3_H5_007.opus", lambda: bereit.append(True))
    live.warte_bis_fertig()
    assert bereit == [True]
    wachsen(live, welt, teil, 300.0, datei="H5_008.opus")  # wird nicht mehr angenommen
    assert welt.fabrik_aufrufe == 1


def test_wurde_die_datei_inzwischen_umbenannt_ist_das_kein_fehler(live, welt, tmp_path):
    wachsen(live, welt, tmp_path / "gibt-es-nicht.teil", 40.0)
    assert not live.deaktiviert and welt.geschnitten == []


def test_freigeben_loescht_den_zwischenstand(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 40.0)
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    live.warte_bis_fertig()
    staging = list((tmp_path / "arbeit" / "live").iterdir())
    assert len(staging) == 1
    gesichert = json.loads((staging[0] / "live.json").read_text(encoding="utf-8"))
    assert gesichert["bestaetigt_bis"] == live.vorab_fuer(ziel)["bestaetigt_bis"]  # type: ignore[index]
    live.freigeben(ziel)
    assert not staging[0].exists() and live.vorab_fuer(ziel) is None


def test_aufraeumen_entfernt_nur_alte_zwischenstaende(tmp_path):
    basis = tmp_path / "arbeit" / "live"
    alt, neu = basis / "alt", basis / "neu"
    alt.mkdir(parents=True)
    neu.mkdir()
    import os
    import time

    zeit = time.time() - 8 * 24 * 3600
    os.utime(alt, (zeit, zeit))
    live = ls.LiveTranskription(tmp_path / "arbeit", lambda: (lambda _w: []))
    assert not alt.exists() and neu.exists()
    assert live.aufraeumen() == 0


# --------------------------------------------------------------------------
# Ende zu Ende: echter HTTP-Dienst, echte Dauerberechnung, Attrappe fuer Whisper und ffmpeg
# --------------------------------------------------------------------------
def test_aufnahme_ueber_http_wird_laufend_transkribiert(tmp_path, welt):
    import hashlib
    import http.client

    from protokoll_assistent.services import geraete_empfang_service as empfang

    token = "e2e-token-0123456789abcdefghijklmnopqrstuvwxyz"
    status = ls.StatusRegister()
    live = ls.LiveTranskription(tmp_path / "arbeit", welt.fabrik, status=status, extrahieren=welt.extrahieren)
    bereit = threading.Event()
    dienst = empfang.GeraeteEmpfang(
        tmp_path / "eingang",
        (empfang.Geraet("S3", empfang.token_hash(token)),),
        port=0,
        adresse="127.0.0.1",
        bei_teil=live.teil_gewachsen,
        bei_abschluss=lambda g, d, z: live.abgeschlossen(g, d, z, bereit.set),
        status_fn=status.hole,
    )
    dienst.ablage._freier_platz = lambda _p: 10**12
    dienst.starten()

    daten = opus_bytes(130.0)
    name = "H5_007.opus"

    def anfrage(methode, pfad, inhalt=None, **kopf):
        verbindung = http.client.HTTPConnection("127.0.0.1", dienst.port, timeout=10)
        verbindung.request(methode, pfad, body=inhalt, headers={"Authorization": f"Bearer {token}", **kopf})
        antwort = verbindung.getresponse()
        text = antwort.read()
        verbindung.close()
        return antwort.status, json.loads(text)

    try:
        stueck = 5000  # etwa 15 Sekunden Audio (je Sekunde eine Ogg-Seite von ca. 330 Bytes)
        for start in range(0, len(daten), stueck):
            teil = daten[start : start + stueck]
            assert anfrage("PUT", f"/api/v1/aufnahmen/{name}", teil, **{"X-Offset": str(start)})[0] == 200
        assert live.warte_bis_fertig(15)
        assert len(welt.geschnitten) >= 3  # laufend, nicht erst am Ende
        # Waehrend der Aufnahme: der Status zeigt, wie weit es ist.
        zustand = anfrage("GET", f"/api/v1/aufnahmen/{name}/status")[1]
        assert zustand["zustand"] == "empfang" and "transkribiert" in zustand["meldung"]

        sha = hashlib.sha256(daten).hexdigest()
        status_code, antwort = anfrage(
            "PUT",
            f"/api/v1/aufnahmen/{name}",
            b"",
            **{"X-Offset": str(len(daten)), "X-Gesamtgroesse": str(len(daten)), "X-SHA256": sha},
        )
        assert status_code == 200 and antwort["fertig"] is True
        assert bereit.wait(10)

        ziel = dienst.ablage.ziel / antwort["datei"]
        vorab = live.vorab_fuer(ziel)
        assert vorab is not None and vorab["bestaetigt_bis"] > 100.0  # fast alles ist schon transkribiert
        assert ziel.read_bytes() == daten
    finally:
        dienst.stoppen()
        live.stoppen()


# --------------------------------------------------------------------------
# Zusammenspiel mit der Teilauswertung
# --------------------------------------------------------------------------
class _AuswertungAttrappe:
    def __init__(self):
        self.ereignisse: list[tuple] = []
        self.ausgewertet = 0

    def fortschritt(self, schluessel, segmente, bis):
        self.ereignisse.append(("fortschritt", schluessel, len(segmente), bis))

    def beenden(self, schluessel):
        self.ereignisse.append(("beenden", schluessel))

    def anzahl(self, schluessel):
        return self.ausgewertet

    def vorab_fuer(self, schluessel, warten=0.0):
        self.ereignisse.append(("vorab", schluessel, warten))
        return {"stufe1": {"k": "text"}, "stufe2": {}}

    def freigeben(self, schluessel):
        self.ereignisse.append(("freigeben", schluessel))

    def warte_auf_leerlauf(self, schluessel, zeitlimit):
        self.ereignisse.append(("leerlauf", schluessel))

    def stoppen(self):
        self.ereignisse.append(("stoppen",))


def test_bestaetigte_segmente_gehen_an_die_teilauswertung(tmp_path, welt, teil):
    auswertung = _AuswertungAttrappe()
    status = ls.StatusRegister()
    live = ls.LiveTranskription(
        tmp_path / "arbeit",
        welt.fabrik,
        status=status,
        dauer_fn=welt.dauer_fn,
        extrahieren=welt.extrahieren,
        auswertung=auswertung,  # type: ignore[arg-type]
    )
    try:
        wachsen(live, welt, teil, 25.0)
        assert auswertung.ereignisse == [("fortschritt", "S3/H5_007.opus#1", 4, 19.0)]
        auswertung.ausgewertet = 2
        wachsen(live, welt, teil, 50.0)
        meldung = status.hole("S3", "H5_007.opus")["meldung"]  # type: ignore[index]
        assert "transkribiert, 2 Abschnitte ausgewertet" in meldung
        auswertung.ausgewertet = 1
        wachsen(live, welt, teil, 75.0)
        assert "1 Abschnitt ausgewertet" in status.hole("S3", "H5_007.opus")["meldung"]  # type: ignore[index]

        ziel = tmp_path / "S3_H5_007.opus"
        ziel.write_bytes(b"x")
        live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
        live.warte_bis_fertig()
        assert ("beenden", "S3/H5_007.opus#1") in auswertung.ereignisse
        # vor der Verarbeitung der fertigen Datei: eine laufende Anfrage abwarten (Grafikspeicher)
        assert ("leerlauf", "S3/H5_007.opus#1") in auswertung.ereignisse
        assert live.auswertung_fuer(ziel, warten=7.0) == {"stufe1": {"k": "text"}, "stufe2": {}}
        assert ("vorab", "S3/H5_007.opus#1", 7.0) in auswertung.ereignisse
        assert live.auswertung_fuer(tmp_path / "andere.opus") is None
        live.freigeben(ziel)
        assert ("freigeben", "S3/H5_007.opus#1") in auswertung.ereignisse
    finally:
        live.stoppen()
    assert ("stoppen",) in auswertung.ereignisse


def test_ohne_teilauswertung_gibt_es_keine_vorab_ergebnisse(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 25.0)
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    live.warte_bis_fertig()
    assert live.auswertung_fuer(ziel) is None


# --------------------------------------------------------------------------
# Derselbe Name ein zweites Mal, Fehler in einem Fenster
# --------------------------------------------------------------------------
def test_neue_aufnahme_unter_demselben_namen_beginnt_eine_neue_sitzung(live, welt, teil, tmp_path):
    """Ein Geraet kann einen Namen wieder benutzen (Zaehlung neu begonnen). Das Transkript der vorigen Aufnahme
    darf nie in die neue geraten -- sonst galt sie als "schon live transkribiert" und Whisper lief nie."""
    wachsen(live, welt, teil, 50.0)
    alt = tmp_path / "S3_H5_007.opus"
    alt.write_bytes(b"alt")
    live.abgeschlossen("S3", "H5_007.opus", alt, lambda: None)
    assert live.warte_bis_fertig()

    wachsen(live, welt, teil, 10.0)  # die neue Aufnahme, noch zu kurz fuer ein Fenster
    neu = tmp_path / "S3_H5_007_2.opus"
    neu.write_bytes(b"neu")
    live.abgeschlossen("S3", "H5_007.opus", neu, lambda: None)
    assert live.warte_bis_fertig()
    assert live.vorab_fuer(neu) is None
    assert live.vorab_fuer(alt) is not None  # die vorige wird womoeglich noch verarbeitet


def test_verworfener_upload_nimmt_seine_segmente_mit(live, welt, teil, tmp_path):
    wachsen(live, welt, teil, 50.0)
    live.verwerfen("S3", "H5_007.opus")  # 422: das Geraet beginnt von vorn
    wachsen(live, welt, teil, 10.0)
    ziel = tmp_path / "S3_H5_007.opus"
    ziel.write_bytes(b"x")
    live.abgeschlossen("S3", "H5_007.opus", ziel, lambda: None)
    assert live.warte_bis_fertig()
    assert live.vorab_fuer(ziel) is None


def test_wiederholter_upload_nimmt_fertig_nicht_zurueck(live, welt, teil):
    """Ging die Bestaetigung verloren, laedt das Geraet die Aufnahme noch einmal ganz hoch. Der Status muss dabei
    "fertig" bleiben, sonst zeigte das Geraet nie "Transkription erfolgreich"."""
    live.status.setze("S3", "H5_007.opus", ls.FERTIG, 1.0, "Transkription erfolgreich")
    wachsen(live, welt, teil, 25.0)
    assert live.status.hole("S3", "H5_007.opus")["zustand"] == ls.FERTIG


def test_ein_fehler_in_einem_fenster_schaltet_die_live_transkription_nicht_ab(tmp_path, welt, teil):
    status = ls.StatusRegister()
    versuche: list[tuple[float, float]] = []

    def einmal_kaputt(quelle, ziel, start, ende):
        versuche.append((start, ende))
        if len(versuche) == 1:
            raise RuntimeError("ffmpeg: Datei kurz gesperrt")
        welt.extrahieren(quelle, ziel, start, ende)

    live = ls.LiveTranskription(
        tmp_path / "arbeit", welt.fabrik, status=status, dauer_fn=welt.dauer_fn, extrahieren=einmal_kaputt
    )
    try:
        wachsen(live, welt, teil, 25.0)
        assert not live.deaktiviert and status.hole("S3", "H5_007.opus") is None
        wachsen(live, welt, teil, 30.0)  # ohne 20 s neues Audio kein neuer Versuch
        assert len(versuche) == 1
        wachsen(live, welt, teil, 50.0)
        assert status.hole("S3", "H5_007.opus")["zustand"] == ls.EMPFANG  # type: ignore[index]
    finally:
        live.stoppen()
