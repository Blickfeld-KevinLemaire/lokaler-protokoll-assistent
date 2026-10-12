"""Fasst ein pytest-Ergebnis (JUnit-XML) fuer GitHub Actions zusammen.

Warum es dieses Skript gibt
---------------------------
Schlaegt in der CI ein Test fehl, stand sein Name bisher nur tief im Rohprotokoll
des Jobs. Dieses Skript schreibt nach jedem Testlauf

* eine Tabelle in die Zusammenfassung des Laufs (``GITHUB_STEP_SUMMARY``):
  welche Tests fehlschlugen, mit Meldung -- oder dass alle bestanden;
* je fehlgeschlagenem Test eine Fehler-Annotation (``::error``). GitHub zeigt
  sie direkt in der Liste der Pruefungen eines Pull Requests und an der
  betroffenen Zeile im Code.

Aufruf (in der CI nach ``pytest --junitxml=testergebnis.xml``)::

    uv run python -m protokoll_assistent.tools.testergebnis_zusammenfassen testergebnis.xml

Das Skript gibt immer 0 zurueck: Ob der Lauf rot ist, entscheidet pytest.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET  # noqa: S405 -- liest nur die eigene pytest-Ausgabe
from dataclasses import dataclass
from pathlib import Path

_ORT = re.compile(r"(protokoll_assistent[\\/][^\s:]+\.py):(\d+)")
_MAX_MELDUNG = 300


@dataclass(frozen=True)
class Fehlschlag:
    test: str
    art: str  # "fehlgeschlagen" | "Fehler"
    meldung: str
    datei: str | None
    zeile: int | None


@dataclass(frozen=True)
class Ergebnis:
    gesamt: int
    fehlgeschlagen: int
    fehler: int
    uebersprungen: int
    fehlschlaege: list[Fehlschlag]


def lesen(pfad: Path) -> Ergebnis:
    wurzel = ET.parse(pfad).getroot()  # noqa: S314 -- eigene, vertrauenswuerdige Datei
    gesamt = fehlgeschlagen = fehler = uebersprungen = 0
    fehlschlaege: list[Fehlschlag] = []
    for fall in wurzel.iter("testcase"):
        gesamt += 1
        if fall.find("skipped") is not None:
            uebersprungen += 1
            continue
        for kind, art in (("failure", "fehlgeschlagen"), ("error", "Fehler")):
            befund = fall.find(kind)
            if befund is None:
                continue
            if kind == "failure":
                fehlgeschlagen += 1
            else:
                fehler += 1
            klasse = fall.get("classname", "")
            name = fall.get("name", "?")
            text = befund.text or ""
            orte = _ORT.findall(text)
            datei, zeile = (orte[-1][0].replace("\\", "/"), int(orte[-1][1])) if orte else (None, None)
            if datei is None and klasse:
                datei = klasse.replace(".", "/") + ".py"
            meldung = befund.get("message") or (text.strip().splitlines() or [""])[-1].strip()
            fehlschlaege.append(
                Fehlschlag(f"{klasse}::{name}" if klasse else name, art, meldung[:_MAX_MELDUNG], datei, zeile)
            )
            break
    return Ergebnis(gesamt, fehlgeschlagen, fehler, uebersprungen, fehlschlaege)


def zusammenfassung(ergebnis: Ergebnis, titel: str) -> str:
    bestanden = ergebnis.gesamt - ergebnis.fehlgeschlagen - ergebnis.fehler - ergebnis.uebersprungen
    if not ergebnis.fehlschlaege:
        return (
            f"### {titel}: alle Tests bestanden\n\n"
            f"{bestanden} bestanden, {ergebnis.uebersprungen} uebersprungen.\n"
        )
    zeilen = [
        f"### {titel}: {len(ergebnis.fehlschlaege)} Test(s) nicht bestanden",
        "",
        f"{bestanden} bestanden, {ergebnis.fehlgeschlagen} fehlgeschlagen, {ergebnis.fehler} mit Fehler, "
        f"{ergebnis.uebersprungen} uebersprungen.",
        "",
        "| Test | Ort | Meldung |",
        "|---|---|---|",
    ]
    for f in ergebnis.fehlschlaege:
        ort = f"`{f.datei}:{f.zeile}`" if f.datei and f.zeile else (f"`{f.datei}`" if f.datei else "")
        meldung = f.meldung.replace("|", "\\|").replace("\n", " ")
        zeilen.append(f"| `{f.test}` ({f.art}) | {ort} | {meldung} |")
    return "\n".join(zeilen) + "\n"


def _maskieren(text: str, eigenschaft: bool = False) -> str:
    """Workflow-Befehle von GitHub: %, CR und LF (in Eigenschaften auch : und ,)."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if eigenschaft:
        text = text.replace(":", "%3A").replace(",", "%2C")
    return text


def annotationen(ergebnis: Ergebnis) -> list[str]:
    zeilen = []
    for f in ergebnis.fehlschlaege:
        teile = []
        if f.datei:
            teile.append(f"file={_maskieren(f.datei, True)}")
        if f.zeile:
            teile.append(f"line={f.zeile}")
        teile.append(f"title={_maskieren('Test ' + f.art, True)}")
        zeilen.append(f"::error {','.join(teile)}::{_maskieren(f.test + ': ' + f.meldung)}")
    return zeilen


def main(argv: list[str] | None = None) -> int:
    argumente = sys.argv[1:] if argv is None else argv
    pfad = Path(argumente[0] if argumente else "testergebnis.xml")
    titel = argumente[1] if len(argumente) > 1 else "Tests"
    if not pfad.is_file():
        print(f"{pfad} fehlt -- pytest ist vermutlich gar nicht gelaufen (siehe Rohprotokoll).")
        return 0
    try:
        ergebnis = lesen(pfad)
    except ET.ParseError as fehler:
        print(f"{pfad} ist nicht lesbar: {fehler}")
        return 0
    for zeile in annotationen(ergebnis):
        print(zeile)
    text = zusammenfassung(ergebnis, titel)
    ziel = os.environ.get("GITHUB_STEP_SUMMARY")
    if ziel:
        with Path(ziel).open("a", encoding="utf-8") as datei:
            datei.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
