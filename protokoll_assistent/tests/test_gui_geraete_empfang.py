"""Tests fuer 'gui/geraete_empfang.py': Steuerung des Empfangs und Reiter "Aufnahmegeräte".

Der echte HTTP-Dienst wird hier nie gestartet (dafuer gibt es
'test_geraete_empfang_service.py'): Die Steuerung bekommt eine Attrappe, und
Meldungen ueber neue Aufnahmen werden direkt ausgeloest -- keine Nebenfaeden
in Tests mit Fenstern.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtWidgets import QApplication  # noqa: E402

from protokoll_assistent.gui import geraete_empfang as ge  # noqa: E402
from protokoll_assistent.services import geraete_empfang_service as empfang  # noqa: E402
from protokoll_assistent.services import live_service as ls  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402

HASH = empfang.token_hash("token")


class _DienstAttrappe:
    instanzen: ClassVar[list[_DienstAttrappe]] = []
    fehler: ClassVar[OSError | None] = None

    def __init__(self, ziel, geraete, *, port, bei_neuer_aufnahme):
        self.ziel, self.geraete, self.port, self.melden = ziel, tuple(geraete), port, bei_neuer_aufnahme
        self.gestartet = self.gestoppt = False
        _DienstAttrappe.instanzen.append(self)

    def starten(self):
        if _DienstAttrappe.fehler is not None:
            raise _DienstAttrappe.fehler
        self.gestartet = True

    def stoppen(self):
        self.gestoppt = True

    def kontakte(self):
        return {"S3": empfang.Kontakt("1a2b3c4d5e6f", "esp32-s3-audio/1.0.0", "192.168.0.20", 0.0)}


@pytest.fixture(autouse=True)
def _attrappe_zuruecksetzen():
    _DienstAttrappe.instanzen.clear()
    _DienstAttrappe.fehler = None


def konfig(aktiv=True, port=8765, geraete=None):
    return {
        "geraete_empfang_aktiv": aktiv,
        "geraete_empfang_port": port,
        "geraete_empfang_geraete": [{"name": "S3", "token_sha256": HASH}] if geraete is None else geraete,
    }


@pytest.fixture
def steuerung(qt_app):
    return ge.EmpfangsSteuerung(dienst_fabrik=_DienstAttrappe)


# --------------------------------------------------------------------------
# Steuerung
# --------------------------------------------------------------------------
def test_aus_startet_nichts(steuerung, tmp_path):
    steuerung.anwenden(tmp_path, konfig(aktiv=False))
    assert not steuerung.laeuft and _DienstAttrappe.instanzen == []
    assert steuerung.beschreibung() == "" and steuerung.kontakte() == {}


def test_ohne_geraete_startet_nichts(steuerung, tmp_path):
    steuerung.anwenden(tmp_path, konfig(geraete=[]))
    assert not steuerung.laeuft


def test_an_startet_mit_zielordner_und_port(steuerung, tmp_path):
    steuerung.anwenden(tmp_path, konfig(port=9000))
    dienst = _DienstAttrappe.instanzen[0]
    assert dienst.gestartet and (dienst.ziel, dienst.port) == (tmp_path, 9000)
    assert dienst.geraete == (empfang.Geraet("S3", HASH),)
    assert steuerung.laeuft
    assert steuerung.beschreibung() == f"Aufnahmegeräte: Empfang an (Port 9000, 1 Gerät) → {tmp_path}"
    assert steuerung.kontakte()["S3"].geraete_id == "1a2b3c4d5e6f"


def test_unveraendert_startet_nicht_neu_geaendert_schon(steuerung, tmp_path):
    steuerung.anwenden(tmp_path, konfig())
    steuerung.anwenden(tmp_path, konfig())
    assert len(_DienstAttrappe.instanzen) == 1
    steuerung.anwenden(tmp_path / "anderer", konfig())
    erster, zweiter = _DienstAttrappe.instanzen
    assert erster.gestoppt and zweiter.gestartet and zweiter.ziel == tmp_path / "anderer"
    steuerung.anwenden(tmp_path / "anderer", konfig(aktiv=False))
    assert zweiter.gestoppt and not steuerung.laeuft


def test_mehrere_geraete_in_der_beschreibung(steuerung, tmp_path):
    zwei = [{"name": "S3", "token_sha256": HASH}, {"name": "C6", "token_sha256": empfang.token_hash("b")}]
    steuerung.anwenden(tmp_path, konfig(geraete=zwei))
    assert "2 Geräte" in steuerung.beschreibung()


def test_belegter_port_wird_gemeldet_und_spaeter_neu_versucht(steuerung, tmp_path):
    _DienstAttrappe.fehler = OSError(10048, "Adresse wird bereits verwendet")
    steuerung.anwenden(tmp_path, konfig())
    assert not steuerung.laeuft
    assert "Port 8765 ist nicht nutzbar (Adresse wird bereits verwendet)" in steuerung.beschreibung()
    _DienstAttrappe.fehler = None
    steuerung.anwenden(tmp_path, konfig())
    assert steuerung.laeuft and "nicht nutzbar" not in steuerung.beschreibung()


@pytest.mark.parametrize(("wert", "erwartet"), [(9000, 9000), ("9001", 9001), (0, 8765), (70000, 8765), ("x", 8765), (None, 8765)])
def test_port_aus_der_konfiguration(wert, erwartet):
    assert ge._port(wert) == erwartet


def test_meldung_wird_als_signal_weitergegeben(steuerung, tmp_path):
    empfangen: list[tuple[str, str]] = []
    steuerung.neue_aufnahme.connect(lambda pfad, geraet: empfangen.append((pfad, geraet)))
    steuerung.anwenden(tmp_path, konfig())
    _DienstAttrappe.instanzen[0].melden(tmp_path / "S3_H5.opus", "S3")
    assert empfangen == [(str(tmp_path / "S3_H5.opus"), "S3")]


def test_konfiguration_wird_sonst_aus_der_datei_gelesen(steuerung, tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "load_config", lambda: konfig())
    steuerung.anwenden(tmp_path)
    assert steuerung.laeuft


def test_kontakt_text():
    assert ge.kontakt_text(None) == "–"
    text = ge.kontakt_text(empfang.Kontakt("1a2b3c4d5e6f", "c6/1.0", "192.168.0.7", 0.0))
    assert text.endswith("192.168.0.7, Id 1a2b3c4d5e6f, c6/1.0")
    assert ge.kontakt_text(empfang.Kontakt(None, None, "10.0.0.1", 0.0)).endswith("10.0.0.1")


# --------------------------------------------------------------------------
# Reiter "Aufnahmegeräte"
# --------------------------------------------------------------------------
@pytest.fixture
def seite(qt_widgets, monkeypatch):
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])
    kontakte = {"S3": empfang.Kontakt("1a2b3c4d5e6f", "esp32-s3-audio/1.0.0", "192.168.0.20", 0.0)}
    config = {
        **konfig(aktiv=False, port=9100),
        "geraete_empfang_geraete": [{"name": "S3", "token_sha256": HASH, "angelegt": "2026-10-01"}, "kaputt"],
    }
    return qt_widgets(ge.GeraeteSeite(config, kontakte=kontakte))


def test_seite_zeigt_den_stand(seite):
    assert not seite.aktiv_checkbox.isChecked() and seite.port_spin.value() == 9100
    assert seite.tabelle.rowCount() == 1
    assert [seite.tabelle.item(0, spalte).text() for spalte in range(2)] == ["S3", "2026-10-01"]
    assert "Id 1a2b3c4d5e6f" in seite.tabelle.item(0, 2).text()
    assert seite.adressen_label.text() == "Adresse für die Geräte: http://192.168.0.10:9100"
    seite.port_spin.setValue(9200)
    assert seite.adressen_label.text().endswith(":9200")
    assert seite.basis_url() == "http://192.168.0.10:9200"


def test_seite_ohne_ermittelbare_adresse(qt_widgets, monkeypatch):
    monkeypatch.setattr(empfang, "lokale_adressen", list)
    seite = qt_widgets(ge.GeraeteSeite({}))
    assert "ipconfig" in seite.adressen_label.text()
    assert seite.basis_url() == "http://<Adresse dieses PCs>:8765"
    assert seite.tabelle.rowCount() == 0 and seite.port_spin.value() == 8765


def test_geraet_hinzufuegen_zeigt_token_einmal_und_speichert_nur_den_hash(seite, monkeypatch):
    gezeigt: list[tuple[str, str]] = []
    monkeypatch.setattr(seite, "_name_erfragen", lambda: "C6-Kueche")
    monkeypatch.setattr(seite, "_token_zeigen", lambda name, token: gezeigt.append((name, token)))
    seite._hinzufuegen()

    [(name, token)] = gezeigt
    assert name == "C6-Kueche" and len(token) == 43
    seite.aktiv_checkbox.setChecked(True)
    aenderungen = seite.aenderungen()
    assert aenderungen["geraete_empfang_aktiv"] is True and aenderungen["geraete_empfang_port"] == 9100
    neu = aenderungen["geraete_empfang_geraete"][-1]
    assert neu["name"] == "C6-Kueche" and neu["token_sha256"] == empfang.token_hash(token)
    assert token not in str(aenderungen)
    assert seite.tabelle.rowCount() == 2 and seite.tabelle.item(1, 2).text() == "–"


@pytest.mark.parametrize(("name", "warnung"), [("S3 mit Leerzeichen", "Erlaubt"), ("s3", "gibt es schon")])
def test_ungueltiger_oder_doppelter_name_wird_abgelehnt(seite, monkeypatch, name, warnung):
    warnungen: list[str] = []
    monkeypatch.setattr(seite, "_name_erfragen", lambda: name)
    monkeypatch.setattr(seite, "_token_zeigen", lambda *_: pytest.fail("kein Token fuer einen abgelehnten Namen"))
    monkeypatch.setattr(ge.QMessageBox, "warning", lambda _p, _t, text: warnungen.append(text))
    seite._hinzufuegen()
    assert warnung in warnungen[0] and seite.tabelle.rowCount() == 1


def test_abgebrochene_namenseingabe_aendert_nichts(seite, monkeypatch):
    monkeypatch.setattr(seite, "_name_erfragen", lambda: None)
    seite._hinzufuegen()
    assert seite.tabelle.rowCount() == 1


def test_name_erfragen(seite, monkeypatch):
    monkeypatch.setattr(ge.QInputDialog, "getText", lambda *a, **k: ("  S3-Buero  ", True))
    assert seite._name_erfragen() == "S3-Buero"
    monkeypatch.setattr(ge.QInputDialog, "getText", lambda *a, **k: ("egal", False))
    assert seite._name_erfragen() is None


def test_token_zeigen_oeffnet_den_dialog(seite, monkeypatch):
    geoeffnet: list[str] = []
    monkeypatch.setattr(ge.TokenDialog, "exec", lambda self: geoeffnet.append(self.token_feld.text()) or 1)
    seite._token_zeigen("S3", "das-token")
    assert geoeffnet == ["das-token"]


def test_geraet_entfernen(seite):
    seite.tabelle.selectRow(0)
    seite._entfernen()
    assert seite.tabelle.rowCount() == 0 and seite.aenderungen()["geraete_empfang_geraete"] == []
    seite._entfernen()  # ohne Auswahl harmlos


def test_token_dialog_zeigt_zeilen_fuer_die_firmware_und_kopiert_sie(qt_widgets):
    dialog = qt_widgets(ge.TokenDialog("S3", "abc-token", "http://192.168.0.10:8765"))
    assert dialog.token_feld.text() == "abc-token" and dialog.token_feld.isReadOnly()
    zeilen = dialog.konfiguration_feld.toPlainText()
    assert '#define VERMERK_PC_BASE_URL  "http://192.168.0.10:8765"' in zeilen
    assert '#define VERMERK_PC_TOKEN     "abc-token"' in zeilen
    dialog._kopieren()
    assert QApplication.clipboard().text() == zeilen


# --------------------------------------------------------------------------
# Einstellungsdialog
# --------------------------------------------------------------------------
def test_einstellungsdialog_speichert_die_geraete(qt_widgets, tmp_path, monkeypatch):
    from protokoll_assistent.gui import settings_dialog as sd
    from protokoll_assistent.services import ollama_service, secret_store

    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    monkeypatch.setattr(ollama_service, "list_models", lambda *a, **k: [])
    monkeypatch.setattr(secret_store, "load_api_key", lambda name: None)
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: None)
    monkeypatch.setattr(secret_store, "delete_api_key", lambda name: None)
    monkeypatch.setattr(empfang, "lokale_adressen", list)

    # Ohne Elternfenster: keine Kontakte, kein Fehler.
    assert qt_widgets(sd.SettingsDialog()).geraete_seite._kontakte == {}

    dialog = qt_widgets(sd.SettingsDialog())
    dialog.geraete_seite.aktiv_checkbox.setChecked(True)
    dialog.geraete_seite._geraete.append({"name": "S3", "token_sha256": HASH, "angelegt": "2026-10-12"})
    dialog._speichern_und_schliessen()
    gespeichert = app_config.load_config()
    assert gespeichert["geraete_empfang_aktiv"] is True
    assert gespeichert["geraete_empfang_geraete"] == [{"name": "S3", "token_sha256": HASH, "angelegt": "2026-10-12"}]
    tab_titel = [dialog.findChild(sd.QTabWidget).tabText(i) for i in range(dialog.findChild(sd.QTabWidget).count())]
    assert "Aufnahmegeräte" in tab_titel



# --------------------------------------------------------------------------
# Live-Transkription und Status
# --------------------------------------------------------------------------
class _LiveDienst(_DienstAttrappe):
    instanzen: ClassVar[list] = []

    def __init__(self, ziel, geraete, *, port, bei_neuer_aufnahme, **weitere):
        super().__init__(ziel, geraete, port=port, bei_neuer_aufnahme=bei_neuer_aufnahme)
        self.weitere = weitere
        _LiveDienst.instanzen.append(self)


class _LiveAttrappe:
    def __init__(self):
        self.ereignisse: list[tuple] = []
        self.bereit_rufen = True

    def teil_gewachsen(self, geraet, datei, pfad):
        self.ereignisse.append(("teil", geraet, datei, pfad))

    def verwerfen(self, geraet, datei):
        self.ereignisse.append(("verworfen", geraet, datei))

    def abgeschlossen(self, geraet, datei, ziel, bei_bereit):
        self.ereignisse.append(("ende", geraet, datei, ziel))
        if self.bereit_rufen:
            bei_bereit()


def _live_steuerung(qt_app, live, status):
    _LiveDienst.instanzen.clear()
    return ge.EmpfangsSteuerung(dienst_fabrik=_LiveDienst, live=live, status=status)


def test_ohne_live_bekommt_der_dienst_keine_zusaetzlichen_rueckrufe(steuerung, tmp_path):
    steuerung.anwenden(tmp_path, konfig())
    assert not hasattr(_DienstAttrappe.instanzen[-1], "weitere")  # alte Aufrufart: nur Name, Port und Meldung


def test_live_verbindet_dienst_mit_live_arbeiter_und_status(qt_app, tmp_path):
    live, status = _LiveAttrappe(), ls.StatusRegister()
    steuerung = _live_steuerung(qt_app, live, status)
    steuerung.anwenden(tmp_path, konfig())
    weitere = _LiveDienst.instanzen[-1].weitere
    assert set(weitere) == {
        "status_fn", "auftraege_fn", "bei_zusammenfassung", "bei_keine_zusammenfassung", "bei_teil", "bei_abschluss", "bei_verworfen"
    }

    status.setze("S3", "H5.opus", ls.AUSWERTUNG)
    assert weitere["status_fn"]("S3", "H5.opus")["zustand"] == "auswertung"

    weitere["bei_teil"]("S3", "H5.opus", tmp_path / "a.teil")
    bereit = []
    steuerung.aufnahme_bereit.connect(lambda *a: bereit.append(a))
    weitere["bei_abschluss"]("S3", "H5.opus", tmp_path / "S3_H5.opus")
    assert live.ereignisse == [("teil", "S3", "H5.opus", tmp_path / "a.teil"), ("ende", "S3", "H5.opus", tmp_path / "S3_H5.opus")]
    assert status.hole("S3", "H5.opus")["zustand"] == "wartet"
    # Erst wenn der Live-Arbeiter "bereit" meldet, darf die Verarbeitung der fertigen Datei beginnen.
    assert bereit == [(str(tmp_path / "S3_H5.opus"), "S3", "H5.opus")]
    # Ein Upload von vorn (oder eine Wiederholung) verwirft den Live-Stand unter diesem Namen
    weitere["bei_verworfen"]("S3", "H5.opus")
    assert live.ereignisse[-1] == ("verworfen", "S3", "H5.opus")


def test_abgeschaltete_live_verarbeitung_laesst_nur_den_status_zu(qt_app, tmp_path):
    steuerung = _live_steuerung(qt_app, _LiveAttrappe(), ls.StatusRegister())
    steuerung.anwenden(tmp_path, {**konfig(), "geraete_live_aktiv": False})
    assert set(_LiveDienst.instanzen[-1].weitere) == {
        "status_fn", "auftraege_fn", "bei_zusammenfassung", "bei_keine_zusammenfassung"
    }


def test_umschalten_der_live_verarbeitung_startet_den_dienst_neu(qt_app, tmp_path):
    steuerung = _live_steuerung(qt_app, _LiveAttrappe(), ls.StatusRegister())
    steuerung.anwenden(tmp_path, konfig())
    steuerung.anwenden(tmp_path, konfig())
    assert len(_LiveDienst.instanzen) == 1  # unveraendert: kein Neustart
    steuerung.anwenden(tmp_path, {**konfig(), "geraete_live_aktiv": False})
    assert len(_LiveDienst.instanzen) == 2 and _LiveDienst.instanzen[0].gestoppt


def test_beschreibung_bleibt_wie_sie_war_mit_live(qt_app, tmp_path):
    steuerung = _live_steuerung(qt_app, _LiveAttrappe(), ls.StatusRegister())
    steuerung.anwenden(tmp_path, konfig())
    assert steuerung.beschreibung().startswith("Aufnahmegeräte: Empfang an (Port 8765, 1 Gerät)")


def test_seite_zeigt_und_liefert_live_einstellungen(qt_widgets, monkeypatch):
    monkeypatch.setattr(ge, "alle_vorlagen", lambda: {"ToDos": "text", "Entscheidungen": "text"})
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])
    standard = qt_widgets(ge.GeraeteSeite({}))
    assert standard.live_checkbox.isChecked()  # Standard: an
    assert standard.auftrag_combo.currentData() == ""
    assert [standard.auftrag_combo.itemText(i) for i in range(standard.auftrag_combo.count())] == [
        "(normale Zusammenfassung)",
        "ToDos",
        "Entscheidungen",
    ]
    assert standard.aenderungen()["geraete_live_aktiv"] is True and standard.aenderungen()["geraete_live_auftrag"] == ""

    seite = qt_widgets(ge.GeraeteSeite({"geraete_live_aktiv": False, "geraete_live_auftrag": "Entscheidungen"}))
    assert not seite.live_checkbox.isChecked() and seite.auftrag_combo.currentData() == "Entscheidungen"
    seite.live_checkbox.setChecked(True)
    seite.auftrag_combo.setCurrentIndex(seite.auftrag_combo.findData("ToDos"))
    aenderungen = seite.aenderungen()
    assert aenderungen["geraete_live_aktiv"] is True and aenderungen["geraete_live_auftrag"] == "ToDos"


def test_fehlende_vorlage_bleibt_sichtbar_statt_stillschweigend_ersetzt(qt_widgets, monkeypatch):
    monkeypatch.setattr(ge, "alle_vorlagen", lambda: {"ToDos": "text"})
    seite = qt_widgets(ge.GeraeteSeite({"geraete_live_auftrag": "Geloescht"}))
    assert seite.auftrag_combo.currentData() == "Geloescht"
    assert "nicht mehr vorhanden" in seite.auftrag_combo.currentText()
    assert seite.aenderungen()["geraete_live_auftrag"] == "Geloescht"


def test_seite_zeigt_und_liefert_den_schalter_fuer_die_vorab_auswertung(qt_widgets, monkeypatch):
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])
    standard = qt_widgets(ge.GeraeteSeite({}))
    assert standard.auswertung_vorab_checkbox.isChecked()  # Standard: an
    assert standard.aenderungen()["geraete_live_auswertung_vorab"] is True
    seite = qt_widgets(ge.GeraeteSeite({"geraete_live_auswertung_vorab": False}))
    assert not seite.auswertung_vorab_checkbox.isChecked()
    seite.auswertung_vorab_checkbox.setChecked(True)
    assert seite.aenderungen()["geraete_live_auswertung_vorab"] is True


def test_seite_zeigt_und_liefert_die_laenge_der_auswertungsabschnitte(qt_widgets, monkeypatch):
    monkeypatch.setattr(empfang, "lokale_adressen", lambda: ["192.168.0.10"])
    standard = qt_widgets(ge.GeraeteSeite({}))
    assert standard.abschnitt_spin.value() == 180 and standard.aenderungen()["geraete_live_abschnitt_sekunden"] == 180
    seite = qt_widgets(ge.GeraeteSeite({"geraete_live_abschnitt_sekunden": 90}))
    assert seite.abschnitt_spin.value() == 90
    seite.abschnitt_spin.setValue(240)
    assert seite.aenderungen()["geraete_live_abschnitt_sekunden"] == 240


def test_auftraege_wuensche_und_freigabe_des_geraets(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "alle_vorlagen", lambda: {"ToDos": "a", "Agenda": "b"})
    wuensche = ls.WunschRegister()
    _LiveDienst.instanzen.clear()
    steuerung = ge.EmpfangsSteuerung(
        dienst_fabrik=_LiveDienst, live=_LiveAttrappe(), status=ls.StatusRegister(), wuensche=wuensche
    )
    steuerung.anwenden(tmp_path, konfig())
    weitere = _LiveDienst.instanzen[-1].weitere
    assert weitere["auftraege_fn"]() == ["ToDos", "Agenda"]

    weitere["bei_wunsch"]("S3", "H5.opus", "Agenda", True)
    assert wuensche.hole("S3", "H5.opus") == ls.Wunsch("Agenda", True)

    freigaben = []
    steuerung.zusammenfassung_gewuenscht.connect(lambda *a: freigaben.append(a))
    assert weitere["bei_zusammenfassung"]("S3", "H5.opus") is True
    assert freigaben == [("S3", "H5.opus")]

    abgelehnt = []
    steuerung.zusammenfassung_abgelehnt.connect(lambda *a: abgelehnt.append(a))
    assert weitere["bei_keine_zusammenfassung"]("S3", "H5.opus") is True
    assert abgelehnt == [("S3", "H5.opus")]


def test_neue_aufnahme_am_geraet_meldet_dass_es_weitergezogen_ist(qt_app, tmp_path):
    _LiveDienst.instanzen.clear()
    steuerung = ge.EmpfangsSteuerung(
        dienst_fabrik=_LiveDienst, live=_LiveAttrappe(), status=ls.StatusRegister(), wuensche=ls.WunschRegister()
    )
    steuerung.anwenden(tmp_path, konfig())
    wunsch = _LiveDienst.instanzen[-1].weitere["bei_wunsch"]
    weiter = []
    steuerung.geraet_weitergezogen.connect(lambda *a: weiter.append(a))
    wunsch("S3", "H5_001.opus", None, True)
    wunsch("S3", "H5_001.opus", None, True)  # weitere Stuecke derselben Aufnahme
    wunsch("C6", "H5_009.opus", None, True)  # ein anderes Geraet
    assert weiter == []
    wunsch("S3", "H5_002.opus", None, True)
    assert weiter == [("S3", "H5_002.opus")]


def test_fragendienst_wird_an_den_empfang_gereicht(qt_app, tmp_path):
    fragen = object()
    _LiveDienst.instanzen.clear()
    steuerung = ge.EmpfangsSteuerung(
        dienst_fabrik=_LiveDienst, live=_LiveAttrappe(), status=ls.StatusRegister(), fragen=fragen
    )
    steuerung.anwenden(tmp_path, konfig())
    assert _LiveDienst.instanzen[-1].weitere["fragen"] is fragen
    ohne = _live_steuerung(qt_app, _LiveAttrappe(), ls.StatusRegister())
    ohne.anwenden(tmp_path, konfig())
    assert "fragen" not in _LiveDienst.instanzen[-1].weitere
