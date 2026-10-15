"""Tests fuer die Sprachausgabe (services/sprachausgabe_service.py): Text sprechbar machen, Saetze, Abtastrate, WAV."""

from __future__ import annotations

import array
import io
import wave

import pytest

from protokoll_assistent.services import sprachausgabe_service as sa


def test_sprechtext_entfernt_markdown_listenpunkte_quellen_und_links():
    text = (
        "**Fritz** hat drei Aufgaben:\n- Angebot schreiben (Protokoll, 10:32)\n- [Budget](http://x.de) pruefen\n"
        "1. Termin klaeren - bis Freitag"
    )
    ergebnis = sa.sprechtext(text)
    assert "*" not in ergebnis and "http" not in ergebnis and "10:32" not in ergebnis and "- " not in ergebnis
    assert "Fritz hat drei Aufgaben" in ergebnis and "Budget pruefen" in ergebnis
    assert "Termin klaeren, bis Freitag" in ergebnis


def test_saetze_teilen_an_satzende_und_zeilenumbruch_und_ignorieren_leeres():
    assert sa.saetze("Erster Satz. Zweiter Satz! Dritter?\nVierter") == [
        "Erster Satz.",
        "Zweiter Satz!",
        "Dritter?",
        "Vierter",
    ]
    assert sa.saetze("  \n ... \n") == []  # nichts Sprechbares


def test_zu_lange_saetze_werden_an_kommas_geteilt():
    satz = ", ".join(["wort"] * 60)
    teile = sa.saetze(satz, max_zeichen=80)
    assert len(teile) > 1 and all(len(t) <= 80 for t in teile)
    assert " ".join(teile).count("wort") == 60


def _pcm(werte):
    return array.array("h", werte).tobytes()


def test_umrechnen_aendert_die_laenge_im_verhaeltnis_der_raten():
    pcm = _pcm(range(2400))  # 2400 Werte bei 24 kHz = 0,1 s
    ergebnis = sa.umrechnen(pcm, 24000, 16000)
    assert len(ergebnis) // 2 == 1600
    werte = array.array("h")
    werte.frombytes(ergebnis)
    assert werte[0] == 0 and abs(werte[-1] - 2399) <= 1 and list(werte) == sorted(werte)  # bleibt steigend
    assert sa.umrechnen(pcm, 16000, 16000) == pcm
    with pytest.raises(sa.SprachausgabeFehler):
        sa.umrechnen(pcm, 0, 16000)


def test_wav_hat_das_erwartete_format():
    daten = sa.wav(_pcm([0, 100, -100, 0]), 16000)
    with wave.open(io.BytesIO(daten)) as datei:
        assert (datei.getnchannels(), datei.getsampwidth(), datei.getframerate(), datei.getnframes()) == (
            1,
            2,
            16000,
            4,
        )


def test_sprechen_setzt_saetze_mit_pausen_zusammen():
    gehoert: list[str] = []

    def engine(satz: str):
        gehoert.append(satz)
        return _pcm([1000] * 2400), 24000  # 0,1 s bei 24 kHz

    ton = sa.sprechen("Erster Satz. Zweiter Satz.", engine)
    assert gehoert == ["Erster Satz.", "Zweiter Satz."]
    with wave.open(io.BytesIO(ton)) as datei:
        sekunden = datei.getnframes() / datei.getframerate()
    assert sekunden == pytest.approx(2 * (0.1 + sa.SATZ_PAUSE_SEKUNDEN), abs=0.01)


def test_sprechen_bricht_an_der_satzgrenze_bei_zu_langer_antwort_ab():
    def engine(satz: str):
        return _pcm([1] * 16000), 16000  # 1 s je Satz

    ton = sa.sprechen("Eins. Zwei. Drei. Vier. Fuenf.", engine, max_sekunden=2.5)
    with wave.open(io.BytesIO(ton)) as datei:
        assert datei.getnframes() / datei.getframerate() < 5


def test_fehler_der_engine_und_leerer_text_werden_gemeldet():
    def kaputt(_satz: str):
        raise RuntimeError("Modell fehlt")

    with pytest.raises(sa.SprachausgabeFehler, match="Modell fehlt"):
        sa.sprechen("Ein Satz.", kaputt)
    with pytest.raises(sa.SprachausgabeFehler, match="nichts zu sprechen"):
        sa.sprechen("**", lambda s: (b"", 16000))
