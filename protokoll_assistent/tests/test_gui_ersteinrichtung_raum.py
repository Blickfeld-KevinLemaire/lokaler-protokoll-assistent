"""Tests fuer den Schritt "Vermerk Raum" der Ersteinrichtung
('gui/ersteinrichtung_raum.py' und seine Einbindung in 'gui/ersteinrichtung.py').

Das Geraet ist die Attrappe aus 'test_geraete_usb_service.py'. Die Arbeit, die
in der Anwendung in einem eigenen Faden laeuft, wird hier direkt ausgefuehrt --
keine Nebenfaeden in Tests mit Fenstern. Die Arbeiter des Assistenten (allen
voran die Ermittlung der Hardware nach dem Ueberspringen) sind die Attrappen aus
'test_gui_ersteinrichtung.py'.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent.gui import ersteinrichtung as ee  # noqa: E402
from protokoll_assistent.gui import ersteinrichtung_raum as er  # noqa: E402
from protokoll_assistent.services import geraete_empfang_service as empfang  # noqa: E402
from protokoll_assistent.services import geraete_usb_service as usb  # noqa: E402
from protokoll_assistent.tests.test_geraete_usb_service import GeraetAttrappe  # noqa: E402
from protokoll_assistent.tests.test_gui_ersteinrichtung import (  # noqa: E402
    _Einrichtung,
    _Ermittlung,
    _Mitschrift,
)
from protokoll_assistent.utils import app_config  # noqa: E402

ESP = usb.Anschluss("COM7", "USB JTAG/serial debug unit", True)
ANDERES = usb.Anschluss("COM1", "Kommunikationsanschluss", False)


@pytest.fixture(autouse=True)
def _ohne_wartezeiten(monkeypatch):
    monkeypatch.setattr(usb.time, "sleep", lambda _s: None)
    monkeypatch.setattr(usb, "ANTWORT_SEKUNDEN", 2.0)
    # Keine echte Netzwerkabfrage im Test.
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])


@pytest.fixture(autouse=True)
def _keine_echten_arbeiter(monkeypatch):
    """Nach dem Schritt kommt "Ihr Computer" und startet die Ermittlung --
    echt waere das ein Faden mit PowerShell, nvidia-smi und HTTP an Ollama, der
    den Prozess beim Abbau des Dialogs abstuerzen laesst."""
    for klasse in (_Ermittlung, _Einrichtung, _Mitschrift):
        klasse.instanzen = []
    monkeypatch.setattr(ee, "ErmittlungsWorker", _Ermittlung)
    monkeypatch.setattr(ee, "EinrichtungsWorker", _Einrichtung)
    monkeypatch.setattr(ee, "MitschriftWorker", _Mitschrift)


@pytest.fixture
def konfig(tmp_path, monkeypatch):
    datei = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: datei)
    return datei


@pytest.fixture
def geraet():
    return GeraetAttrappe()


def seite_bauen(qt_widgets, geraet, anschluesse=(ESP,)):
    seite = qt_widgets(
        er.VermerkRaumSeite(oeffnen=lambda _port: geraet, anschluesse=lambda: list(anschluesse))
    )

    def ausfuehren(funktion, bei_erfolg):
        try:
            ergebnis = funktion()
        except usb.UsbFehler as fehler:
            seite._fehlgeschlagen(str(fehler))
            return
        bei_erfolg(ergebnis)

    seite._im_hintergrund = ausfuehren
    return seite


def bis_zum_wlan(seite):
    seite.primaer_button.click()  # Frage -> Anschliessen (sucht und erkennt selbst)
    assert seite.unterseiten.currentIndex() == er.U_ANSCHLIESSEN
    seite.primaer_button.click()  # Anschliessen -> WLAN
    assert seite.unterseiten.currentIndex() == er.U_WLAN


# --------------------------------------------------------------------------
def test_beginnt_mit_der_frage_und_laesst_sich_ueberspringen(qt_widgets, konfig, geraet):
    seite = seite_bauen(qt_widgets, geraet)
    assert seite.unterseiten.currentIndex() == er.U_FRAGE
    uebersprungen = []
    seite.weiter.connect(lambda: uebersprungen.append(True))
    seite.ueberspringen_button.click()
    assert uebersprungen == [True]
    assert geraet.gesendet == []  # nichts am Geraet angefasst
    assert app_config.load_config()["geraete_empfang_geraete"] == []
    assert app_config.load_config()["geraete_empfang_aktiv"] is False


def test_zurueck_von_der_frage_meldet_dem_assistenten(qt_widgets, konfig, geraet):
    seite = seite_bauen(qt_widgets, geraet)
    zurueck = []
    seite.zurueck.connect(lambda: zurueck.append(True))
    seite.zurueck_button.click()
    assert zurueck == [True]


def test_ein_esp32_wird_automatisch_erkannt(qt_widgets, konfig, geraet):
    seite = seite_bauen(qt_widgets, geraet, anschluesse=(ANDERES, ESP))
    seite.primaer_button.click()
    assert seite.anschluss_combo.currentData() == "COM7"
    assert "Id 1a2b3c4d5e6f" in seite.geraet_label.text()
    assert seite.primaer_button.isEnabled()


def test_mehrere_oder_kein_esp32_verlangen_die_auswahl(qt_widgets, konfig, geraet):
    seite = seite_bauen(qt_widgets, geraet, anschluesse=(ANDERES,))
    seite.primaer_button.click()
    assert not seite.primaer_button.isEnabled() and geraet.gesendet == []
    assert "Anschluss" in seite.geraet_label.text()
    seite.erkennen_button.click()
    assert seite.primaer_button.isEnabled()


def test_ohne_anschluss_gibt_es_einen_hinweis(qt_widgets, konfig, geraet):
    seite = seite_bauen(qt_widgets, geraet, anschluesse=())
    seite.primaer_button.click()
    assert seite.geraet_label.text() == er.KEIN_ANSCHLUSS
    assert not seite.primaer_button.isEnabled() and not seite.erkennen_button.isEnabled()
    assert seite.ueberspringen_button.isEnabled()


def test_ohne_pyserial_bleibt_der_schritt_nutzbar(qt_widgets, konfig, geraet):
    def fehlt():
        raise usb.UsbFehler("Das Paket 'pyserial' fehlt")

    seite = qt_widgets(er.VermerkRaumSeite(oeffnen=lambda _p: geraet, anschluesse=fehlt))
    seite.primaer_button.click()
    assert "pyserial" in seite.status_label.text()
    assert seite.ueberspringen_button.isEnabled()


def test_einrichten_schreibt_ins_geraet_und_speichert_die_konfiguration(qt_widgets, konfig, geraet, monkeypatch):
    monkeypatch.setattr(empfang, "token_erzeugen", lambda: "token-aus-dem-test")
    seite = seite_bauen(qt_widgets, geraet)
    gemeldet = []
    seite.eingerichtet.connect(lambda: gemeldet.append(True))
    bis_zum_wlan(seite)
    assert seite.name_edit.text() == "S3-Audio-5e6f"
    # Adresse ermittelt: vorausgefuellt, aber sichtbar und aenderbar.
    assert not seite.adresse_edit.isHidden() and not seite.adresse_edit.isReadOnly()
    assert seite.adresse_edit.text() == "http://192.168.0.10:8765"
    seite.wlan_edit.setText("Buero")
    seite.passwort_edit.setText("geheim123")
    seite.primaer_button.click()

    assert geraet.gespeichert["wlan_ssid"] == "Buero"
    assert geraet.gespeichert["pc_url"] == "http://192.168.0.10:8765"
    assert geraet.gespeichert["pc_token"] == "token-aus-dem-test"
    assert gemeldet == [True]
    assert seite.unterseiten.currentIndex() == er.U_FERTIG
    assert "S3-Audio-5e6f" in seite.fertig_label.text() and "token-aus-dem-test" not in seite.fertig_label.text()

    gespeichert = app_config.load_config()
    assert gespeichert["geraete_empfang_aktiv"] is True
    (eintrag,) = gespeichert["geraete_empfang_geraete"]
    assert eintrag["token_sha256"] == empfang.token_hash("token-aus-dem-test")
    assert (eintrag["name"], eintrag["geraete_id"], eintrag["board"]) == ("S3-Audio-5e6f", "1a2b3c4d5e6f", "esp32-s3-audio")
    assert "token-aus-dem-test" not in str(gespeichert)

    weiter = []
    seite.weiter.connect(lambda: weiter.append(True))
    seite.primaer_button.click()  # Fertig -> Weiter
    assert weiter == [True]


def test_ohne_ermittelbare_adresse_wird_sie_abgefragt(qt_widgets, konfig, geraet, monkeypatch):
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: [])
    seite = seite_bauen(qt_widgets, geraet)
    bis_zum_wlan(seite)
    assert not seite.adresse_edit.isHidden() and seite.adresse_edit.text() == ""
    seite.wlan_edit.setText("Buero")
    seite.passwort_edit.setText("geheim123")
    seite.primaer_button.click()
    assert "Adresse" in seite.status_label.text() and geraet.gespeichert == {}
    seite.adresse_edit.setText("http://10.0.0.5:8765")
    seite.primaer_button.click()
    assert geraet.gespeichert["pc_url"] == "http://10.0.0.5:8765"


def test_bei_mehreren_adressen_laesst_sich_die_richtige_eintragen(qt_widgets, konfig, geraet, monkeypatch):
    # Die erste Adresse gehoert oft zu einem VPN-, Hyper-V- oder WSL-Adapter.
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["172.20.0.1", "192.168.0.10"])
    seite = seite_bauen(qt_widgets, geraet)
    bis_zum_wlan(seite)
    assert seite.adresse_edit.text() == "http://172.20.0.1:8765"
    assert "http://172.20.0.1:8765" in seite.adresse_hinweis.text()
    assert "http://192.168.0.10:8765" in seite.adresse_hinweis.text()
    seite.adresse_edit.setText("http://192.168.0.10:8765")
    seite.wlan_edit.setText("Buero")
    seite.passwort_edit.setText("geheim123")
    seite.primaer_button.click()
    assert geraet.gespeichert["pc_url"] == "http://192.168.0.10:8765"


@pytest.mark.parametrize(
    ("name", "wlan", "passwort", "meldung"),
    [
        ("mit leerzeichen", "Buero", "geheim123", "Name"),
        ("C6-Lager", "Buero", "geheim123", "anderes Gerät heißt"),
        ("S3-Neu", "", "geheim123", "WLAN-Name"),
        ("S3-Neu", "Buero", "kurz", "Passwort"),
    ],
)
def test_eingaben_werden_vor_dem_schreiben_geprueft(qt_widgets, konfig, geraet, name, wlan, passwort, meldung):
    app_config.update_config(
        geraete_empfang_geraete=[{"name": "C6-Lager", "token_sha256": "a" * 64, "geraete_id": "ffffffffffff"}]
    )
    seite = seite_bauen(qt_widgets, geraet)
    bis_zum_wlan(seite)
    geraet.gesendet.clear()
    seite.name_edit.setText(name)
    seite.wlan_edit.setText(wlan)
    seite.passwort_edit.setText(passwort)
    seite.primaer_button.click()
    assert meldung in seite.status_label.text()
    assert geraet.gesendet == [] and seite.ergebnis is None
    assert seite.unterseiten.currentIndex() == er.U_WLAN


def test_ablehnung_des_geraets_wird_angezeigt_und_nichts_gespeichert(qt_widgets, konfig):
    geraet = GeraetAttrappe(aufnahme=True)
    seite = seite_bauen(qt_widgets, geraet)
    bis_zum_wlan(seite)
    seite.wlan_edit.setText("Buero")
    seite.passwort_edit.setText("geheim123")
    seite.primaer_button.click()
    assert "Aufnahme laeuft" in seite.status_label.text() and seite.ergebnis is None
    assert seite.primaer_button.isEnabled()  # erneut versuchen moeglich
    assert app_config.load_config()["geraete_empfang_geraete"] == []


def test_bekanntes_geraet_wird_ersetzt_statt_doppelt_eingetragen(qt_widgets, konfig, geraet):
    app_config.update_config(
        geraete_empfang_geraete=[
            {"name": "Alt", "token_sha256": "a" * 64, "geraete_id": "1a2b3c4d5e6f"},
            {"name": "Andere", "token_sha256": "b" * 64, "geraete_id": "ffffffffffff"},
        ]
    )
    seite = seite_bauen(qt_widgets, geraet)
    bis_zum_wlan(seite)
    seite.wlan_edit.setText("Buero")
    seite.passwort_edit.setText("geheim123")
    seite.primaer_button.click()
    namen = [e["name"] for e in app_config.load_config()["geraete_empfang_geraete"]]
    assert namen == ["Andere", "S3-Audio-5e6f"]


# --------------------------------------------------------------------------
# Einbindung in den Assistenten
# --------------------------------------------------------------------------
@pytest.fixture
def assistent(qt_widgets, konfig, monkeypatch):
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: False)
    return qt_widgets(ee.ErsteinrichtungDialog())


def test_der_schritt_steht_direkt_nach_dem_willkommen(assistent):
    assert ee.ErsteinrichtungDialog.SCHRITTE[:2] == ("Willkommen", "Vermerk Raum")
    assert assistent.S_WILLKOMMEN + 1 == assistent.S_RAUM and assistent.S_RAUM + 1 == assistent.S_RECHNER
    assistent.los_button.click()
    assert assistent.stack.currentIndex() == assistent.S_RAUM


def test_ueberspringen_fuehrt_zum_naechsten_schritt_und_zurueck_zum_willkommen(assistent):
    assistent.los_button.click()
    assistent.raum_seite.ueberspringen_button.click()
    assert assistent.stack.currentIndex() == assistent.S_RECHNER
    assert [e.gestartet for e in _Ermittlung.instanzen] == [True]  # die Attrappe, kein Faden
    assistent._gehe_zu(assistent.S_RAUM)
    assistent.raum_seite.zurueck_button.click()
    assert assistent.stack.currentIndex() == assistent.S_WILLKOMMEN


def test_ohne_raum_springt_der_assistent_ueber_den_schritt(qt_widgets, konfig, monkeypatch):
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: False)
    dialog = qt_widgets(ee.ErsteinrichtungDialog(mit_raum=False))
    texte = [label.text() for label in dialog._schritt_labels.values()]
    assert "Vermerk Raum" not in " ".join(texte) and texte[0] == "1. Willkommen" and texte[1] == "2. Ihr Computer"
    dialog.los_button.click()
    assert dialog.stack.currentIndex() == dialog.S_RECHNER
    assert [e.gestartet for e in _Ermittlung.instanzen] == [True]


def test_beim_schliessen_startet_der_empfang_wenn_ein_geraet_eingerichtet_wurde(qt_widgets, konfig, monkeypatch):
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: False)

    class Eltern(ee.QWidget):
        angewendet = 0

        def _geraete_empfang_anwenden(self):
            Eltern.angewendet += 1

    eltern = qt_widgets(Eltern())
    dialog = qt_widgets(ee.ErsteinrichtungDialog(eltern))
    dialog.reject()  # ohne Geraet: nichts anwenden
    assert Eltern.angewendet == 0
    dialog = qt_widgets(ee.ErsteinrichtungDialog(eltern))
    dialog.raum_seite.eingerichtet.emit()
    dialog.done(ee.ErsteinrichtungDialog.NEUSTART)  # Neustart: die neue Instanz uebernimmt
    assert Eltern.angewendet == 0
    dialog = qt_widgets(ee.ErsteinrichtungDialog(eltern))
    dialog.raum_seite.eingerichtet.emit()
    dialog.reject()  # "Spaeter einrichten" nach dem Geraet: Empfang trotzdem starten
    assert Eltern.angewendet == 1


class _LaufendeAufgabe:
    def __init__(self):
        self.laeuft = True

    def isRunning(self):
        return self.laeuft


def test_waehrend_ins_geraet_geschrieben_wird_bleibt_der_assistent_offen(assistent):
    assistent.show()
    assistent.los_button.click()
    aufgabe = _LaufendeAufgabe()
    assistent.raum_seite._aufgabe = aufgabe  # "Schreibe ins Gerät …"
    assistent.nicht_mehr_fragen.setChecked(True)

    assistent.reject()  # Esc oder "Später einrichten"
    assert assistent.isVisible()
    assert "Bitte warten" in assistent.raum_seite.status_label.text()
    assert not assistent.close()  # Schliessen ueber das Fensterkreuz
    assert assistent.isVisible()
    assert app_config.load_config()["einrichtung_abgeschlossen"] is False  # noch nichts gespeichert

    aufgabe.laeuft = False  # fertig geschrieben: jetzt darf er zu
    assert assistent.close()
    assert not assistent.isVisible()
    assert app_config.load_config()["einrichtung_abgeschlossen"] is True
