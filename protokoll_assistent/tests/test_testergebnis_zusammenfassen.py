"""Tests fuer 'tools/testergebnis_zusammenfassen.py' -- mit echter pytest-Ausgabe.

Statt einer nachgebauten JUnit-Datei laeuft pytest in einem eigenen Prozess
ueber eine kleine Testdatei (bestanden, fehlgeschlagen, uebersprungen, Fehler im
Aufbau). So faellt auf, wenn pytest sein Ausgabeformat aendert.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from protokoll_assistent.tools import testergebnis_zusammenfassen as tz


@pytest.fixture(scope="module")
def junit_datei(tmp_path_factory) -> Path:
    ordner = tmp_path_factory.mktemp("lauf")
    (ordner / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (ordner / "test_beispiel.py").write_text(
        textwrap.dedent(
            """
            import pytest

            def test_gut():
                assert True

            def test_schlecht():
                wert = 1
                assert wert == 2, "eins ist nicht zwei | mit Strich"

            @pytest.mark.skip(reason="absichtlich")
            def test_ausgelassen():
                pass

            @pytest.fixture
            def kaputt():
                raise RuntimeError("Aufbau scheitert")

            def test_aufbau(kaputt):
                pass
            """
        ),
        encoding="utf-8",
    )
    ziel = ordner / "ergebnis.xml"
    subprocess.run(  # noqa: S603 -- fester Aufruf von pytest mit eigenen Argumenten
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(ordner / "pytest.ini"),
         f"--rootdir={ordner}", f"--junitxml={ziel}", str(ordner / "test_beispiel.py")],
        cwd=ordner,
        capture_output=True,
        check=False,
    )
    assert ziel.is_file()
    return ziel


def test_lesen_zaehlt_und_findet_die_fehlschlaege(junit_datei):
    ergebnis = tz.lesen(junit_datei)
    assert (ergebnis.gesamt, ergebnis.fehlgeschlagen, ergebnis.fehler, ergebnis.uebersprungen) == (4, 1, 1, 1)
    namen = {f.test.split("::")[-1]: f for f in ergebnis.fehlschlaege}
    assert set(namen) == {"test_schlecht", "test_aufbau"}
    assert namen["test_schlecht"].art == "fehlgeschlagen"
    assert "eins ist nicht zwei" in namen["test_schlecht"].meldung
    assert namen["test_aufbau"].art == "Fehler" and "Aufbau scheitert" in namen["test_aufbau"].meldung


def test_zusammenfassung_bei_fehlschlaegen(junit_datei):
    text = tz.zusammenfassung(tz.lesen(junit_datei), "Tests (Windows, Python 3.11)")
    assert text.startswith("### Tests (Windows, Python 3.11): 2 Test(s) nicht bestanden")
    assert "1 bestanden, 1 fehlgeschlagen, 1 mit Fehler, 1 uebersprungen" in text
    assert "test_schlecht` (fehlgeschlagen)" in text
    assert "zwei \\| mit Strich" in text  # | ist maskiert, sonst zerfiele die Tabelle


def test_zusammenfassung_wenn_alles_gruen():
    ergebnis = tz.Ergebnis(gesamt=5, fehlgeschlagen=0, fehler=0, uebersprungen=1, fehlschlaege=[])
    assert tz.zusammenfassung(ergebnis, "Tests") == "### Tests: alle Tests bestanden\n\n4 bestanden, 1 uebersprungen.\n"


def test_annotationen_mit_datei_und_zeile():
    ergebnis = tz.Ergebnis(
        1, 1, 0, 0,
        [tz.Fehlschlag("protokoll_assistent.tests.test_x::test_y", "fehlgeschlagen", "a, b: 100%\nzwei", "protokoll_assistent/tests/test_x.py", 12)],
    )
    [zeile] = tz.annotationen(ergebnis)
    assert zeile.startswith("::error file=protokoll_assistent/tests/test_x.py,line=12,title=Test fehlgeschlagen::")
    assert zeile.endswith("test_y: a, b: 100%25%0Azwei")


def test_ort_aus_dem_traceback(tmp_path):
    xml = """<testsuites><testsuite><testcase classname="protokoll_assistent.tests.test_a" name="test_b">
    <failure message="assert 1 == 2">protokoll_assistent\\tests\\test_a.py:7: in test_b
    AssertionError</failure></testcase>
    <testcase classname="x" name="ohne_ort"><failure>nur Text
    letzte Zeile</failure></testcase></testsuite></testsuites>"""
    datei = tmp_path / "e.xml"
    datei.write_text(xml, encoding="utf-8")
    erster, zweiter = tz.lesen(datei).fehlschlaege
    assert (erster.datei, erster.zeile) == ("protokoll_assistent/tests/test_a.py", 7)
    assert (zweiter.datei, zweiter.zeile, zweiter.meldung) == ("x.py", None, "letzte Zeile")


def test_main_schreibt_in_die_zusammenfassung(junit_datei, tmp_path, monkeypatch, capsys):
    ziel = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(ziel))
    assert tz.main([str(junit_datei), "Tests 3.11"]) == 0
    assert "### Tests 3.11: 2 Test(s) nicht bestanden" in ziel.read_text(encoding="utf-8")
    assert capsys.readouterr().out.count("::error ") == 2


def test_main_ohne_github(junit_datei, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert tz.main([str(junit_datei)]) == 0
    assert "### Tests:" in capsys.readouterr().out


def test_main_ohne_oder_mit_kaputter_datei(tmp_path, capsys):
    assert tz.main([str(tmp_path / "fehlt.xml")]) == 0
    assert "pytest ist vermutlich gar nicht gelaufen" in capsys.readouterr().out
    kaputt = tmp_path / "kaputt.xml"
    kaputt.write_text("<nicht xml", encoding="utf-8")
    assert tz.main([str(kaputt)]) == 0
    assert "nicht lesbar" in capsys.readouterr().out
