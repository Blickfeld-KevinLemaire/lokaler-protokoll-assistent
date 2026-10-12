"""Tests fuer den Dialog "Gerät per USB einrichten" ('gui/geraete_usb_einrichtung.py').

Das Geraet ist die Attrappe aus 'test_geraete_usb_service.py'. Die Arbeit, die
in der Anwendung in einem eigenen Faden laeuft, wird hier direkt ausgefuehrt --
keine Nebenfaeden in Tests mit Fenstern.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtWidgets import QApplication  # noqa: E402

from protokoll_assistent.gui import geraete_empfang as ge  # noqa: E402
from protokoll_assistent.gui import geraete_usb_einrichtung as gue  # noqa: E402
from protokoll_assistent.services import geraete_empfang_service as empfang  # noqa: E402
from protokoll_assistent.services import geraete_usb_service as usb  # noqa: E402
from protokoll_assistent.tests.test_geraete_usb_service import GeraetAttrappe  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402

ESP = usb.Anschluss("COM7", "USB JTAG/serial debug unit", True)


@pytest.fixture(autouse=True)
def _ohne_wartezeiten(monkeypatch):
    monkeypatch.setattr(usb.time, "sleep", lambda _s: None)
    monkeypatch.setattr(usb, "ANTWORT_SEKUNDEN", 0.01)


def direkt(dialog):
    """Ersetzt den Faden: Erfolg und Fehler laufen wie bei '_Aufgabe'."""

    def ausfuehren(funktion, bei_erfolg):
        try:
            ergebnis = funktion()
        except usb.UsbFehler as fehler:
            dialog._fehlgeschlagen(str(fehler))
            return
        bei_erfolg(ergebnis)

    dialog._im_hintergrund = ausfuehren
    return dialog


@pytest.fixture
def geraet():
    return GeraetAttrappe()


def dialog_bauen(qt_widgets, geraet, vorhandene=None, anschluesse=(ESP,)):
    dialog = gue.UsbEinrichtungDialog(
        vorhandene if vorhandene is not None else [],
        "http://192.168.0.10:8765",
        oeffnen=lambda _port: geraet,
        anschluesse=lambda: list(anschluesse),
    )
    return direkt(qt_widgets(dialog))


def ausfuellen(dialog, wlan="Buero", passwort="geheim123"):
    dialog.wlan_edit.setText(wlan)
    dialog.passwort_edit.setText(passwort)


# --------------------------------------------------------------------------
def test_anschluesse_und_erkennen(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet)
    assert dialog.anschluss_combo.count() == 1 and "(ESP32)" in dialog.anschluss_combo.itemText(0)
    assert not dialog.einrichten_button.isEnabled()
    dialog._erkennen()
    assert "Id 1a2b3c4d5e6f" in dialog.geraet_label.text() and "noch nicht eingerichtet" in dialog.geraet_label.text()
    assert dialog.name_edit.text() == "S3-Audio-5e6f"
    assert dialog.einrichten_button.isEnabled() and dialog.status_label.text() == ""


def test_ohne_anschluss(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet, anschluesse=())
    assert not dialog.erkennen_button.isEnabled() and "Kein serieller Anschluss" in dialog.geraet_label.text()
    dialog._erkennen()  # ohne Auswahl harmlos


def test_ohne_pyserial(qt_widgets, geraet):
    def fehlt():
        raise usb.UsbFehler("Das Paket 'pyserial' fehlt")

    dialog = direkt(qt_widgets(gue.UsbEinrichtungDialog([], "http://x:8765", oeffnen=lambda _p: geraet, anschluesse=fehlt)))
    assert "pyserial" in dialog.status_label.text()


def test_einrichten_schreibt_ins_geraet_und_liefert_den_eintrag(qt_widgets, geraet, monkeypatch):
    monkeypatch.setattr(empfang, "token_erzeugen", lambda: "token-aus-dem-test")
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog._erkennen()
    ausfuellen(dialog)
    dialog.erste_nummer_spin.setValue(29)
    dialog._einrichten()

    assert geraet.gespeichert["pc_url"] == "http://192.168.0.10:8765"
    assert geraet.gespeichert["pc_token"] == "token-aus-dem-test" and geraet.gespeichert["erste_nummer"] == "29"
    assert dialog.ergebnis is not None
    assert dialog.ergebnis["token_sha256"] == empfang.token_hash("token-aus-dem-test")
    assert (dialog.ergebnis["name"], dialog.ergebnis["geraete_id"], dialog.ergebnis["board"]) == ("S3-Audio-5e6f", "1a2b3c4d5e6f", "esp32-s3-audio")
    assert "token-aus-dem-test" not in str(dialog.ergebnis)
    assert dialog.inventar_zeile.startswith("1a2b3c4d5e6f,esp32-s3-audio,S3-Audio-5e6f,1.0.0,")
    assert not dialog.inventar_button.isHidden() and "✅" in dialog.status_label.text()
    dialog.inventar_button.click()
    assert QApplication.clipboard().text() == dialog.inventar_zeile


def test_bekanntes_geraet_behaelt_seinen_namen(qt_widgets, geraet):
    vorhanden = [{"name": "S3-Buero", "token_sha256": "a" * 64, "geraete_id": "1a2b3c4d5e6f"}]
    dialog = dialog_bauen(qt_widgets, geraet, vorhanden)
    dialog._erkennen()
    assert dialog.name_edit.text() == "S3-Buero" and "neu eingerichtet" in dialog.geraet_label.text()
    ausfuellen(dialog)
    dialog._einrichten()
    assert dialog.ergebnis is not None and dialog.ergebnis["name"] == "S3-Buero"


@pytest.mark.parametrize(
    ("name", "wlan", "passwort", "meldung"),
    [
        ("mit leerzeichen", "Buero", "geheim123", "Name"),
        ("C6-Lager", "Buero", "geheim123", "anderes Gerät heißt"),
        ("S3-Neu", "", "geheim123", "WLAN-Name"),
        ("S3-Neu", "Buero", "kurz", "Passwort"),
    ],
)
def test_eingaben_werden_vor_dem_schreiben_geprueft(qt_widgets, geraet, name, wlan, passwort, meldung):
    vorhanden = [{"name": "C6-Lager", "token_sha256": "a" * 64, "geraete_id": "ffffffffffff"}]
    dialog = dialog_bauen(qt_widgets, geraet, vorhanden)
    dialog._erkennen()
    geraet.gesendet.clear()
    dialog.name_edit.setText(name)
    ausfuellen(dialog, wlan, passwort)
    dialog._einrichten()
    assert meldung in dialog.status_label.text() and geraet.gesendet == [] and dialog.ergebnis is None


def test_ablehnung_des_geraets_wird_angezeigt(qt_widgets):
    geraet = GeraetAttrappe(aufnahme=True)
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog._erkennen()
    ausfuellen(dialog)
    dialog._einrichten()
    assert "Aufnahme laeuft" in dialog.status_label.text() and dialog.ergebnis is None
    assert dialog.einrichten_button.isEnabled()  # erneut versuchen moeglich


def test_geraet_meldet_nach_neustart_keine_einrichtung(qt_widgets):
    class Vergesslich(GeraetAttrappe):
        def _bearbeiten(self, zeile):
            antwort = super()._bearbeiten(zeile)
            if zeile.endswith("SPEICHERN"):
                self.gespeichert = {}
            return antwort

    dialog = dialog_bauen(qt_widgets, Vergesslich())
    dialog._erkennen()
    ausfuellen(dialog)
    dialog._einrichten()
    assert "keine Einrichtung" in dialog.status_label.text() and dialog.ergebnis is None


def test_einrichten_ohne_erkanntes_geraet_tut_nichts(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog._einrichten()
    assert geraet.gesendet == []


def test_passwort_anzeigen(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog.passwort_zeigen.setChecked(True)
    assert dialog.passwort_edit.echoMode() == gue.QLineEdit.Normal
    dialog.passwort_zeigen.setChecked(False)
    assert dialog.passwort_edit.echoMode() == gue.QLineEdit.Password


class _LaufendeAufgabe:
    def isRunning(self):
        return True


def test_schliessen_waehrend_das_geraet_beschrieben_wird(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog._aufgabe = _LaufendeAufgabe()
    dialog.reject()
    assert "Bitte warten" in dialog.status_label.text() and dialog.result() == 0
    ereignis = gue.QCloseEvent()
    dialog.closeEvent(ereignis)
    assert not ereignis.isAccepted()


def test_schliessen_nach_erfolg_gilt_als_angenommen(qt_widgets, geraet):
    dialog = dialog_bauen(qt_widgets, geraet)
    dialog.ergebnis = {"name": "x"}
    dialog._schliessen()
    assert dialog.result() == gue.QDialog.Accepted
    leer = dialog_bauen(qt_widgets, geraet)
    leer._schliessen()
    assert leer.result() == gue.QDialog.Rejected
    leer.closeEvent(gue.QCloseEvent())


def test_aufgabe_meldet_erfolg_und_fehler(qt_app):
    ergebnisse: list = []
    gut = gue._Aufgabe(lambda: 42)
    gut.erfolg.connect(ergebnisse.append)
    gut.run()  # direkt, ohne Faden

    def usb_fehler():
        raise usb.UsbFehler("Gerät weg")

    def anderer():
        raise RuntimeError("kaputt")

    for funktion in (usb_fehler, anderer):
        aufgabe = gue._Aufgabe(funktion)
        aufgabe.fehler.connect(ergebnisse.append)
        aufgabe.run()
    assert ergebnisse == [42, "Gerät weg", "Unerwarteter Fehler: kaputt"]


def test_im_hintergrund_startet_einen_faden(qt_widgets, geraet, monkeypatch):
    gestartet: list = []
    monkeypatch.setattr(gue._Aufgabe, "start", lambda self: gestartet.append(self))
    dialog = gue.UsbEinrichtungDialog([], "http://x:8765", oeffnen=lambda _p: geraet, anschluesse=lambda: [ESP])
    qt_widgets(dialog)
    dialog._im_hintergrund(lambda: 1, lambda _e: None)
    assert gestartet == [dialog._aufgabe]


# --------------------------------------------------------------------------
# Reiter "Aufnahmegeräte"
# --------------------------------------------------------------------------
@pytest.fixture
def seite(qt_widgets, tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])
    config = {
        "geraete_empfang_geraete": [
            {"name": "S3-Alt", "token_sha256": "a" * 64, "geraete_id": "1a2b3c4d5e6f"},
            {"name": "C6", "token_sha256": "b" * 64},
        ]
    }
    kontakte = {"S3-Alt": empfang.Kontakt("999999999999", "esp32-s3-audio/1.0.0", "192.168.0.20", 0.0)}
    return qt_widgets(ge.GeraeteSeite(config, kontakte=kontakte))


class _DialogAttrappe:
    def __init__(self, ergebnis):
        self.ergebnis = ergebnis

    def exec(self):
        return 1


def test_seite_zeigt_id_und_warnt_bei_fremder_id(seite):
    assert seite.tabelle.item(0, 3).text() == "1a2b3c4d5e6f"
    assert seite.tabelle.item(0, 2).text().startswith("⚠ andere Id")
    assert seite.tabelle.item(1, 3).text() == ""


def test_usb_einrichtung_ersetzt_das_bekannte_geraet_und_speichert_sofort(seite, monkeypatch):
    neu = {"name": "S3-Neu", "token_sha256": "c" * 64, "geraete_id": "1a2b3c4d5e6f", "board": "esp32-s3-audio"}
    monkeypatch.setattr(seite, "_usb_dialog", lambda: _DialogAttrappe(neu))
    seite._per_usb_einrichten()
    namen = [e["name"] for e in seite.aenderungen()["geraete_empfang_geraete"]]
    assert namen == ["C6", "S3-Neu"]
    assert [e["name"] for e in app_config.load_config()["geraete_empfang_geraete"]] == ["C6", "S3-Neu"]


def test_usb_einrichtung_fuegt_ein_neues_geraet_hinzu(seite, monkeypatch):
    neu = {"name": "C6-Neu", "token_sha256": "d" * 64, "geraete_id": "abcdefabcdef"}
    monkeypatch.setattr(seite, "_usb_dialog", lambda: _DialogAttrappe(neu))
    seite._per_usb_einrichten()
    assert seite.tabelle.rowCount() == 3


def test_abgebrochene_usb_einrichtung_aendert_nichts(seite, monkeypatch):
    monkeypatch.setattr(seite, "_usb_dialog", lambda: _DialogAttrappe(None))
    seite._per_usb_einrichten()
    assert seite.tabelle.rowCount() == 2 and not app_config.get_config_file().exists()


def test_usb_dialog_wird_gebaut(seite, qt_widgets, monkeypatch):
    monkeypatch.setattr(usb, "anschluesse_finden", lambda: [])
    dialog = qt_widgets(seite._usb_dialog())
    assert isinstance(dialog, gue.UsbEinrichtungDialog)
    assert dialog.adresse_edit.text() == "http://192.168.0.10:8765"
