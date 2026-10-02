"""Tests fuer 'tools/logo_erzeugen.py' (Logo aus der EPS-Vorlage)."""

import struct
import zlib

import pytest

from protokoll_assistent.tools import logo_erzeugen as le

# Zwei Quadrate: eins mit Loch (gerade-ungerade-Fuellung), eins gefuellt. Die
# Zahlen sind, wie in der EPS, in Zehntel-Einheiten ('0.1 0 0 0.1 0 0 cm').
STROM = """q 0.1 0 0 0.1 0 0 cm
0.1 0.2 0.3 rg
0 0 m 100 0 l 100 100 l 0 100 l h
f
1 1 1 rg
200 0 m 300 0 l 300 100 l 200 100 l h
220 20 m 280 20 l 280 80 l 220 80 l h
f*
0 0 50 50 re
f
Q"""


def test_formen_lesen_erkennt_farbe_regel_und_rechtecke():
    formen = le.formen_lesen(STROM)
    assert len(formen) == 3
    assert formen[0][0] == (0.1, 0.2, 0.3) and formen[0][2] is False
    assert formen[1][0] == (1.0, 1.0, 1.0) and formen[1][2] is True and len(formen[1][1]) == 2
    assert formen[0][1][0][1] == (10.0, 0.0)  # mit der Skalierung 0,1
    assert le.begrenzung(formen) == (0.0, 0.0, 30.0, 10.0)


def test_kurven_werden_in_linienzuege_umgewandelt():
    formen = le.formen_lesen("0.1 0 0 0.1 0 0 cm 0 0 0 rg 0 0 m 0 100 100 100 100 0 c h f")
    assert len(formen[0][1][0]) == 17  # Startpunkt + 16 Schritte


def test_hex_farbe_und_helligkeit_und_dunkle_fassung():
    assert le.hex_farbe((0.0, 0.5, 1.0)) == "#0080ff"
    formen = [((0.03, 0.09, 0.15), [[(0, 0), (1, 0), (1, 1)]], False), ((0.29, 0.72, 0.96), [[(0, 0), (1, 0), (1, 1)]], False)]
    dunkel = le.fuer_dunklen_hintergrund(formen)
    assert dunkel[0][0] == (1.0, 1.0, 1.0)  # Dunkles wird weiss
    assert dunkel[1][0] == (0.29, 0.72, 0.96)  # Hellblau bleibt


def test_svg_enthaelt_alle_pfade_und_die_fuellregel():
    svg = le.als_svg(le.formen_lesen(STROM))
    assert svg.count("<path") == 3
    assert 'fill-rule="evenodd"' in svg
    quadratisch = le.als_svg(le.formen_lesen(STROM), rand=0.1, quadratisch=True)
    breite, hoehe = (float(x) for x in quadratisch.split('viewBox="0 0 ')[1].split('"')[0].split())
    assert breite == pytest.approx(hoehe)


def test_zeichnen_fuellt_flaechen_und_laesst_loecher_frei():
    formen = le.formen_lesen(STROM)[1:2]  # Quadrat mit Loch, 10 x 10 Einheiten
    rgba = le.zeichnen(formen, 10, 10, 1.0, 20.0, 0.0)

    def alpha(x, y):
        return rgba[(y * 10 + x) * 4 + 3]

    assert alpha(0, 0) == 255  # Rand gefuellt
    assert alpha(5, 5) == 0  # Loch
    assert rgba[:3] == bytes((255, 255, 255))


def test_zeichnen_glaettet_kanten():
    # Ein Dreieck: Pixel an der schraegen Kante sind nur teilweise gedeckt.
    formen = [((0.0, 0.0, 0.0), [[(0.0, 0.0), (8.0, 0.0), (0.0, 8.0)]], False)]
    rgba = le.zeichnen(formen, 8, 8, 1.0, 0.0, 0.0)
    werte = {rgba[(y * 8 + x) * 4 + 3] for y in range(8) for x in range(8)}
    assert 0 in werte and 255 in werte and any(0 < w < 255 for w in werte)


def _png_pruefen(daten, breite, hoehe):
    assert daten[:8] == b"\x89PNG\r\n\x1a\n"
    b, h = struct.unpack(">II", daten[16:24])
    assert (b, h) == (breite, hoehe)
    idat = daten.index(b"IDAT")
    laenge = struct.unpack(">I", daten[idat - 4 : idat])[0]
    zeilen = zlib.decompress(daten[idat + 4 : idat + 4 + laenge])
    assert len(zeilen) == hoehe * (1 + breite * 4)


def test_png_und_ico_sind_gueltig():
    formen = le.formen_lesen(STROM)
    png, _, _ = le.png_von(formen, 64, quadratisch=True, rand=0.05)
    _png_pruefen(png, 64, 64)
    breit, b2, h2 = le.png_von(formen, 90, quadratisch=False, rand=0.05)
    _png_pruefen(breit, b2, h2)
    assert b2 > h2

    ico = le.als_ico({16: png, 256: png})
    assert struct.unpack("<HHH", ico[:6]) == (0, 1, 2)
    assert ico[6] == 16 and ico[6 + 16] == 0  # 256 wird als 0 gespeichert


def test_erzeugen_aus_der_echten_vorlage(tmp_path):
    geschrieben = le.erzeugen(ziel=tmp_path)
    assert {p.name for p in geschrieben} == {
        "vermerk_logo.svg",
        "vermerk_icon.svg",
        "vermerk_logo.png",
        "vermerk_logo_hell.png",
        "vermerk_icon.png",
        "vermerk_icon.ico",
    }
    assert (tmp_path / "vermerk_icon.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "vermerk_logo.svg").read_text(encoding="utf-8").count("<path") == 9


def test_main_schreibt_in_den_zielordner(tmp_path, capsys):
    assert le.main([str(le.QUELLE), str(tmp_path)]) == 0
    assert "vermerk_icon.ico" in capsys.readouterr().out
