"""Erzeugt die Logo-Dateien der Anwendung aus der EPS-Vorlage.

Die Vorlage ``resources/branding/vermerk_logo_hauptlogo.eps`` ist von
Ghostscript geschrieben: ihr Inhaltsstrom besteht aus einfachen Pfaden
(``m``, ``l``, ``c``, ``h``, ``f``) und Farben (``rg``) ohne Kompression. Dieses
Skript liest sie, zeichnet sie selbst (ohne Pillow oder Ghostscript, damit es
ueberall laeuft) und schreibt:

* ``vermerk_logo.svg``/``.png``       das grosse Logo (Bildmarke und Schriftzug)
* ``vermerk_logo_hell.png``           dasselbe fuer dunkle Hintergruende
* ``vermerk_icon.svg``/``.png``       nur die Bildmarke, quadratisch
* ``vermerk_icon.ico``                Windows-Symbol (16 bis 256 Pixel)

Aufruf (im Projektstamm)::

    python -m protokoll_assistent.tools.logo_erzeugen

Die erzeugten Dateien liegen im Repository; das Skript wird nur gebraucht,
wenn sich das Logo aendert.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

Punkt = tuple[float, float]
# (Farbe, Teilpfade, gerade-ungerade-Fuellung)
Form = tuple[tuple[float, float, float], list[list[Punkt]], bool]

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
QUELLE = RESOURCES / "branding" / "vermerk_logo_hauptlogo.eps"
# Die ersten Fuellungen sind die Bildmarke (zwei Balken und die Tonwelle); danach
# folgt der Schriftzug in einer anderen Farbe.
ANZAHL_FORMEN_BILDMARKE = 7
ICO_GROESSEN = (16, 24, 32, 48, 64, 128, 256)


def inhaltsstrom_lesen(eps: bytes) -> str:
    """Der Seiteninhalt der EPS: der erste Strom nach 'EndPageSetup'."""
    start = eps.index(b"%%EndPageSetup")
    anfang = eps.index(b"stream", start) + len(b"stream")
    ende = eps.index(b"endstream", anfang)
    return eps[anfang:ende].decode("latin-1")


def formen_lesen(inhalt: str) -> list[Form]:
    """Liest Pfade und Fuellfarben. Unterstuetzt wird, was Ghostscript hier
    schreibt: ``cm`` nur als gleichmaessige Skalierung am Anfang, ``rg`` fuer die
    Fuellfarbe, ``f``/``f*`` zum Fuellen (Nicht-Null-Regel bzw. gerade-ungerade
    Regel), ``re`` fuer Rechtecke. Alles andere wird ueberlesen."""
    skala = 1.0
    farbe = (0.0, 0.0, 0.0)
    zahlen: list[float] = []
    teilpfade: list[list[Punkt]] = []
    aktuell: list[Punkt] = []
    formen: list[Form] = []

    def abschliessen() -> None:
        nonlocal aktuell
        if len(aktuell) > 2:
            teilpfade.append(aktuell)
        aktuell = []

    for wort in inhalt.split():
        try:
            zahlen.append(float(wort))
            continue
        except ValueError:
            pass
        if wort == "cm" and len(zahlen) >= 6:
            skala = zahlen[-6]
        elif wort == "rg" and len(zahlen) >= 3:
            farbe = (zahlen[-3], zahlen[-2], zahlen[-1])
        elif wort == "m" and len(zahlen) >= 2:
            abschliessen()
            aktuell = [(zahlen[-2] * skala, zahlen[-1] * skala)]
        elif wort == "l" and len(zahlen) >= 2 and aktuell:
            aktuell.append((zahlen[-2] * skala, zahlen[-1] * skala))
        elif wort == "c" and len(zahlen) >= 6 and aktuell:
            x1, y1, x2, y2, x3, y3 = (z * skala for z in zahlen[-6:])
            x0, y0 = aktuell[-1]
            schritte = 16
            for i in range(1, schritte + 1):
                t = i / schritte
                u = 1 - t
                aktuell.append(
                    (
                        u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                        u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                    )
                )
        elif wort == "re" and len(zahlen) >= 4:
            abschliessen()
            x, y, b, h = (z * skala for z in zahlen[-4:])
            teilpfade.append([(x, y), (x + b, y), (x + b, y + h), (x, y + h)])
        elif wort == "h":
            abschliessen()
        elif wort in {"f", "f*"}:
            abschliessen()
            if teilpfade:
                formen.append((farbe, list(teilpfade), wort == "f*"))
            teilpfade.clear()
        elif wort in {"n", "q", "Q"}:
            if wort == "n":
                abschliessen()
                teilpfade.clear()
        zahlen.clear()
    return formen


def begrenzung(formen: list[Form]) -> tuple[float, float, float, float]:
    xs = [p[0] for _, pfade, _ in formen for pfad in pfade for p in pfad]
    ys = [p[1] for _, pfade, _ in formen for pfad in pfade for p in pfad]
    return min(xs), min(ys), max(xs), max(ys)


def hex_farbe(farbe: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in farbe)


def helligkeit(farbe: tuple[float, float, float]) -> float:
    return 0.2126 * farbe[0] + 0.7152 * farbe[1] + 0.0722 * farbe[2]


def fuer_dunklen_hintergrund(formen: list[Form]) -> list[Form]:
    """Dunkle Flaechen werden weiss, helle (hier das Hellblau) bleiben."""
    return [((1.0, 1.0, 1.0) if helligkeit(f) < 0.35 else f, pfade, eo) for f, pfade, eo in formen]


def als_svg(formen: list[Form], rand: float = 0.0, quadratisch: bool = False) -> str:
    x0, y0, x1, y1 = begrenzung(formen)
    breite, hoehe = x1 - x0, y1 - y0
    if quadratisch:
        seite = max(breite, hoehe)
        ox = x0 - (seite - breite) / 2 - seite * rand
        oy = y0 - (seite - hoehe) / 2 - seite * rand
        breite = hoehe = seite * (1 + 2 * rand)
    else:
        ox, oy = x0 - rand, y0 - rand
        breite, hoehe = breite + 2 * rand, hoehe + 2 * rand
    teile = []
    for farbe, pfade, gerade_ungerade in formen:
        daten = ""
        for pfad in pfade:
            punkte = [f"{x - ox:.2f},{oy + hoehe - y:.2f}" for x, y in pfad]
            daten += "M" + "L".join(punkte) + "Z"
        regel = ' fill-rule="evenodd"' if gerade_ungerade else ""
        teile.append(f'<path fill="{hex_farbe(farbe)}"{regel} d="{daten}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {breite:.2f} {hoehe:.2f}">\n'
        + "\n".join(teile)
        + "\n</svg>\n"
    )


def zeichnen(
    formen: list[Form], breite: int, hoehe: int, massstab: float, ox: float, oy: float, fein: int = 4
) -> bytes:
    """Zeichnet die Formen mit Kantenglaettung (``fein`` Teilzeilen je Pixel,
    Deckung in x genau) und liefert RGBA-Bytes mit gerader Alpha.

    ``ox``/``oy`` sind die Logo-Koordinaten der linken unteren Ecke."""
    rot = [0.0] * (breite * hoehe)
    gruen = [0.0] * (breite * hoehe)
    blau = [0.0] * (breite * hoehe)
    alpha = [0.0] * (breite * hoehe)

    for farbe, pfade, gerade_ungerade in formen:
        kanten: list[tuple[float, float, float, float, int]] = []
        for pfad in pfade:
            punkte = [((x - ox) * massstab, (hoehe - (y - oy) * massstab)) for x, y in pfad]
            for i, (xa, ya) in enumerate(punkte):
                xb, yb = punkte[(i + 1) % len(punkte)]
                if ya == yb:
                    continue
                kanten.append((xa, ya, xb, yb, 1) if ya < yb else (xb, yb, xa, ya, -1))
        if not kanten:
            continue
        zeile_von = max(0, int(min(k[1] for k in kanten)))
        zeile_bis = min(hoehe - 1, int(max(k[3] for k in kanten)))
        for zeile in range(zeile_von, zeile_bis + 1):
            diff = [0.0] * (breite + 2)
            teil = [0.0] * (breite + 2)
            gefuellt = False
            for s in range(fein):
                yy = zeile + (s + 0.5) / fein
                kreuzungen = sorted(
                    (xa + (yy - ya) * (xb - xa) / (yb - ya), richtung)
                    for xa, ya, xb, yb, richtung in kanten
                    if ya <= yy < yb
                )
                wicklung = 0
                for (xk, richtung), (xn, _) in zip(kreuzungen, kreuzungen[1:], strict=False):
                    wicklung += richtung
                    if (wicklung % 2 == 0) if gerade_ungerade else (wicklung == 0):
                        continue
                    a, b = max(xk, 0.0), min(xn, float(breite))
                    if b <= a:
                        continue
                    gefuellt = True
                    ia, ib = int(a), int(b)
                    if ia == ib:
                        teil[ia] += (b - a) / fein
                    else:
                        teil[ia] += (ia + 1 - a) / fein
                        teil[ib] += (b - ib) / fein
                        diff[ia + 1] += 1 / fein
                        diff[ib] -= 1 / fein
            if not gefuellt:
                continue
            lauf = 0.0
            basis = zeile * breite
            for x in range(breite):
                lauf += diff[x]
                deckung = min(1.0, lauf + teil[x])
                if deckung <= 0.0:
                    continue
                i = basis + x
                rest = 1.0 - deckung
                rot[i] = farbe[0] * deckung + rot[i] * rest
                gruen[i] = farbe[1] * deckung + gruen[i] * rest
                blau[i] = farbe[2] * deckung + blau[i] * rest
                alpha[i] = deckung + alpha[i] * rest

    ausgabe = bytearray()
    for i in range(breite * hoehe):
        a = alpha[i]
        if a <= 0.0:
            ausgabe += b"\x00\x00\x00\x00"
        else:
            ausgabe += bytes(
                (round(rot[i] / a * 255), round(gruen[i] / a * 255), round(blau[i] / a * 255), round(a * 255))
            )
    return bytes(ausgabe)


def als_png(rgba: bytes, breite: int, hoehe: int) -> bytes:
    def block(art: bytes, daten: bytes) -> bytes:
        return struct.pack(">I", len(daten)) + art + daten + struct.pack(">I", zlib.crc32(art + daten))

    zeilen = b"".join(b"\x00" + rgba[y * breite * 4 : (y + 1) * breite * 4] for y in range(hoehe))
    return (
        b"\x89PNG\r\n\x1a\n"
        + block(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 6, 0, 0, 0))
        + block(b"IDAT", zlib.compress(zeilen, 9))
        + block(b"IEND", b"")
    )


def als_ico(pngs: dict[int, bytes]) -> bytes:
    """ICO mit PNG-Bildern (ab Windows Vista ueblich)."""
    kopf = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    eintraege = b""
    daten = b""
    for groesse, png in sorted(pngs.items()):
        wert = 0 if groesse >= 256 else groesse
        eintraege += struct.pack("<BBBBHHII", wert, wert, 0, 0, 1, 32, len(png), offset + len(daten))
        daten += png
    return kopf + eintraege + daten


def png_von(formen: list[Form], hoehe_oder_breite: int, quadratisch: bool, rand: float = 0.0) -> tuple[bytes, int, int]:
    x0, y0, x1, y1 = begrenzung(formen)
    b, h = x1 - x0, y1 - y0
    if quadratisch:
        seite = max(b, h)
        massstab = hoehe_oder_breite / (seite * (1 + 2 * rand))
        ox = x0 - (seite - b) / 2 - seite * rand
        oy = y0 - (seite - h) / 2 - seite * rand
        breite = hoehe = hoehe_oder_breite
    else:
        luft = b * rand
        massstab = hoehe_oder_breite / (b + 2 * luft)
        ox, oy = x0 - luft, y0 - luft
        breite, hoehe = hoehe_oder_breite, max(1, round((h + 2 * luft) * massstab))
    rgba = zeichnen(formen, breite, hoehe, massstab, ox, oy)
    return als_png(rgba, breite, hoehe), breite, hoehe


def erzeugen(quelle: Path = QUELLE, ziel: Path = RESOURCES) -> list[Path]:
    alle = formen_lesen(inhaltsstrom_lesen(quelle.read_bytes()))
    marke = alle[:ANZAHL_FORMEN_BILDMARKE]
    ziel.mkdir(parents=True, exist_ok=True)
    geschrieben: list[Path] = []

    def schreibe(name: str, inhalt: bytes | str) -> None:
        pfad = ziel / name
        if isinstance(inhalt, str):
            pfad.write_text(inhalt, encoding="utf-8")
        else:
            pfad.write_bytes(inhalt)
        geschrieben.append(pfad)

    schreibe("vermerk_logo.svg", als_svg(alle, rand=12))
    schreibe("vermerk_icon.svg", als_svg(marke, rand=0.08, quadratisch=True))
    schreibe("vermerk_logo.png", png_von(alle, 1200, quadratisch=False, rand=0.02)[0])
    schreibe("vermerk_logo_hell.png", png_von(fuer_dunklen_hintergrund(alle), 1200, quadratisch=False, rand=0.02)[0])
    schreibe("vermerk_icon.png", png_von(marke, 512, quadratisch=True, rand=0.08)[0])
    schreibe(
        "vermerk_icon.ico",
        als_ico({g: png_von(marke, g, quadratisch=True, rand=0.06)[0] for g in ICO_GROESSEN}),
    )
    return geschrieben


def main(argumente: list[str] | None = None) -> int:
    argumente = sys.argv[1:] if argumente is None else argumente
    quelle = Path(argumente[0]) if argumente else QUELLE
    ziel = Path(argumente[1]) if len(argumente) > 1 else RESOURCES
    for pfad in erzeugen(quelle, ziel):
        print(f"geschrieben: {pfad}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

