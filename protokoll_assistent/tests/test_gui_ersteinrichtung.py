"""Tests fuer die Ersteinrichtung ('gui/ersteinrichtung.py').

Kein Test startet einen Thread, laedt etwas oder fragt die Hardware ab: Die
drei Arbeiter werden durch Attrappen ersetzt, deren Signale der Test selbst
ausloest (CLAUDE.md, Regel 5)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest import mock

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent import bootstrap  # noqa: E402
from protokoll_assistent.gui import ersteinrichtung as ee  # noqa: E402
from protokoll_assistent.services import (  # noqa: E402
    einrichtungsplan_service,
    ollama_service,
    rechner_analyse_service,
    secret_store,
)
from protokoll_assistent.services.rechner_analyse_service import RechnerProfil  # noqa: E402
from protokoll_assistent.utils import app_config, hf_env  # noqa: E402

LAPTOP = RechnerProfil(ram_gb=32, cpu_kerne=16, gpu_name="NVIDIA GeForce RTX 4060", vram_gb=8.0, freier_platz_gb=300)
OHNE_GRAFIK = RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300)
SCHWACH = RechnerProfil(ram_gb=4, cpu_kerne=2, freier_platz_gb=300)


class _Signal:
    def __init__(self):
        self.empfaenger = []

    def connect(self, funktion):
        self.empfaenger.append(funktion)

    def emit(self, *args):
        for funktion in self.empfaenger:
            funktion(*args)


class _Attrappe:
    instanzen: ClassVar[list] = []
    SIGNALE: ClassVar[tuple] = ()

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.gestartet = False
        self.abgebrochen = False
        for name in self.SIGNALE:
            setattr(self, name, _Signal())
        type(self).instanzen.append(self)

    def start(self):
        self.gestartet = True

    def isRunning(self):
        return self.gestartet

    def abbrechen(self):
        self.abgebrochen = True


class _Ermittlung(_Attrappe):
    instanzen: ClassVar[list] = []
    SIGNALE = ("fertig",)


class _Einrichtung(_Attrappe):
    instanzen: ClassVar[list] = []
    SIGNALE = ("schritt", "fortschritt", "log_line", "fertig")


class _Mitschrift(_Attrappe):
    instanzen: ClassVar[list] = []
    SIGNALE = ("log_line", "fertig")


@pytest.fixture
def konfig(tmp_path, monkeypatch):
    datei = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: datei)
    return datei


@pytest.fixture
def dialog(qt_widgets, konfig, monkeypatch):
    for klasse in (_Ermittlung, _Einrichtung, _Mitschrift):
        klasse.instanzen = []
    monkeypatch.setattr(ee, "ErmittlungsWorker", _Ermittlung)
    monkeypatch.setattr(ee, "EinrichtungsWorker", _Einrichtung)
    monkeypatch.setattr(ee, "MitschriftWorker", _Mitschrift)
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: False)
    gespeichert: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: gespeichert.__setitem__(name, wert))
    fenster = qt_widgets(ee.ErsteinrichtungDialog())
    fenster.gespeichert = gespeichert
    return fenster


def _bis_zur_arbeitsweise(dialog, profil=LAPTOP, vorhanden=None):
    dialog.los_button.click()
    assert dialog.stack.currentIndex() == dialog.S_RECHNER
    _Ermittlung.instanzen[-1].fertig.emit(rechner_analyse_service.analysiere(profil), vorhanden or {})
    dialog.rechner_weiter_button.click()
    assert dialog.stack.currentIndex() == dialog.S_ARBEITSWEISE


# --------------------------------------------------------------------------
# 1. und 2.: Willkommen, Ihr Computer
# --------------------------------------------------------------------------
def test_beginnt_mit_der_erklaerung_und_laedt_nichts(dialog):
    assert dialog.stack.currentIndex() == dialog.S_WILLKOMMEN
    assert _Ermittlung.instanzen == [] and _Einrichtung.instanzen == []


def test_rechner_seite_zeigt_je_schritt_eine_einschaetzung(dialog):
    dialog.los_button.click()
    assert not dialog.rechner_weiter_button.isEnabled()  # erst nach der Analyse
    _Ermittlung.instanzen[-1].fertig.emit(rechner_analyse_service.analysiere(LAPTOP), {})
    texte = {schritt: bewertung.text() for schritt, (_n, bewertung) in dialog.schritt_zeilen.items()}
    assert texte[einrichtungsplan_service.SCHRITT_MITSCHRIFT].startswith("✓ geht gut")
    assert "Minuten" in texte[einrichtungsplan_service.SCHRITT_PROTOKOLL]
    assert "alles auf diesem Computer" in dialog.empfehlung_label.text()
    assert dialog.details_tabelle.rowCount() > 0 and dialog.details_tabelle.isHidden()
    dialog.details_button.click()
    assert not dialog.details_tabelle.isHidden()
    assert dialog.rechner_weiter_button.isEnabled()
    # Zurueck und wieder vor: keine zweite Analyse
    dialog._gehe_zu(dialog.S_WILLKOMMEN)
    dialog.los_button.click()
    assert len(_Ermittlung.instanzen) == 1


# --------------------------------------------------------------------------
# 3. Arbeitsweise
# --------------------------------------------------------------------------
def test_starker_rechner_waehlt_lokal_vor(dialog):
    _bis_zur_arbeitsweise(dialog, LAPTOP)
    assert dialog.weg_lokal.isChecked()
    assert dialog.datenschutz_label.isHidden()
    assert dialog.arbeitsweise() == {"transkription": "lokal", "nachbearbeitung": "lokal", "chatbot": "lokal"}


def test_ohne_klare_empfehlung_keine_vorauswahl(dialog):
    _bis_zur_arbeitsweise(dialog, OHNE_GRAFIK)
    assert not any(k.isChecked() for k in (dialog.weg_lokal, dialog.weg_online, dialog.weg_gemischt))
    assert not dialog.arbeitsweise_weiter_button.isEnabled()


def test_online_wird_nie_vorausgewaehlt(dialog):
    _bis_zur_arbeitsweise(dialog, SCHWACH)  # Empfehlung: online
    assert not dialog.weg_online.isChecked()
    dialog.weg_online.setChecked(True)
    assert not dialog.datenschutz_label.isHidden()  # sobald online im Spiel ist: Hinweis
    assert dialog.arbeitsweise_weiter_button.isEnabled()


def test_gemischt_und_empfehlungen_landen_in_der_konfiguration(dialog):
    _bis_zur_arbeitsweise(dialog, LAPTOP)
    dialog.weg_gemischt.setChecked(True)
    assert not dialog.einzeln.isHidden()
    dialog.wahl["nachbearbeitung"].setCurrentIndex(dialog.wahl["nachbearbeitung"].findData("api"))
    assert not dialog.datenschutz_label.isHidden()
    dialog.arbeitsweise_weiter_button.click()

    konfig = app_config.load_config()
    assert (konfig["transkription_modus"], konfig["nachbearbeitung_modus"], konfig["chatbot_modus"]) == (
        "lokal", "api", "lokal",
    )
    assert konfig["whisper_modell"] == "large-v3-turbo"
    assert dialog.stack.currentIndex() == dialog.S_KOSTEN


def test_empfohlenes_sprachmodell_ersetzt_nur_den_standard(dialog, monkeypatch):
    app_config.update_config(chatbot_ollama_modell="eigenes:7b")
    _bis_zur_arbeitsweise(dialog, LAPTOP)
    dialog.analyse.empfehlung[rechner_analyse_service.BEREICH_NACHBEARBEITUNG] = "qwen3.5:9b-q4_K_M"
    dialog.arbeitsweise_weiter_button.click()
    konfig = app_config.load_config()
    assert konfig["ollama_modell"] == "qwen3.5:9b-q4_K_M"
    assert konfig["chatbot_ollama_modell"] == "eigenes:7b"  # eine bewusste Wahl bleibt


# --------------------------------------------------------------------------
# 4. Was noetig ist
# --------------------------------------------------------------------------
def test_kosten_brauchen_zustimmung(dialog):
    _bis_zur_arbeitsweise(dialog, LAPTOP)
    dialog.arbeitsweise_weiter_button.click()
    kennungen = [b.kennung for b in dialog.bausteine]
    assert kennungen == ["ffmpeg", "ollama", "sprachmodell", "einbettung", "laufzeit", "whisper", "pyannote"]
    assert "GB Download" in dialog.summe_label.text()
    assert not dialog.lizenz_label.isHidden()
    assert not dialog.einrichten_button.isEnabled()  # nichts ohne Zustimmung
    dialog.zustimmung.setChecked(True)
    assert dialog.einrichten_button.isEnabled()


def test_vorhandenes_wird_markiert_und_nicht_mitgezaehlt(dialog):
    vorhanden = {"ffmpeg": True, "ollama": True, "laufzeit": False, "modelle": {ollama_service.DEFAULT_MODEL, "bge-m3:latest"}}
    _bis_zur_arbeitsweise(dialog, LAPTOP, vorhanden)
    dialog.arbeitsweise_weiter_button.click()
    da = {b.kennung for b in dialog.bausteine if b.vorhanden}
    assert da == {"ffmpeg", "ollama", "sprachmodell", "einbettung"}
    assert dialog.kosten_tabelle.item(0, 1).text() == "bereits vorhanden ✓"
    assert dialog.lizenz_label.isHidden()  # Ollama ist schon da


def test_wenig_platz_wird_gewarnt(dialog):
    _bis_zur_arbeitsweise(dialog, RechnerProfil(ram_gb=32, cpu_kerne=16, gpu_name="NVIDIA RTX", vram_gb=8.0, freier_platz_gb=5))
    dialog.arbeitsweise_weiter_button.click()
    assert "Platz schaffen" in dialog.summe_label.text()


def test_ist_alles_da_braucht_es_keine_zustimmung(dialog):
    vorhanden = {"ffmpeg": True}
    _bis_zur_arbeitsweise(dialog, LAPTOP, vorhanden)
    dialog.weg_online.setChecked(True)
    dialog.arbeitsweise_weiter_button.click()
    assert "schon vorhanden" in dialog.summe_label.text()
    assert dialog.zustimmung.isHidden()
    assert dialog.einrichten_button.isEnabled() and dialog.einrichten_button.text() == "Weiter"
    dialog.einrichten_button.click()  # keine Aufgaben: gleich fertig
    assert _Einrichtung.instanzen == []
    dialog.einrichtung_weiter_button.click()
    assert dialog.stack.currentIndex() == dialog.S_FERTIG
    assert not dialog.anbieter_button.isHidden()


# --------------------------------------------------------------------------
# 5. Einrichtung und Neustart
# --------------------------------------------------------------------------
def _bis_zur_einrichtung(dialog, profil=LAPTOP, vorhanden=None):
    _bis_zur_arbeitsweise(dialog, profil, vorhanden)
    dialog.arbeitsweise_weiter_button.click()
    dialog.zustimmung.setChecked(True)
    dialog.einrichten_button.click()
    assert dialog.stack.currentIndex() == dialog.S_EINRICHTUNG
    return _Einrichtung.instanzen[-1]


def test_einrichtung_laedt_was_fehlt_der_reihe_nach(dialog):
    app_config.update_config(lokale_einrichtung_zurueckgestellt=True)
    arbeiter = _bis_zur_einrichtung(dialog)
    assert arbeiter.gestartet
    assert arbeiter.args[0] == ["ffmpeg", "ollama"]
    assert arbeiter.args[1] == [ollama_service.DEFAULT_MODEL, "bge-m3"]
    assert app_config.load_config()["lokale_einrichtung_zurueckgestellt"] is False  # zugestimmt

    arbeiter.schritt.emit("ollama", "laeuft")
    assert dialog.aufgaben_labels["ollama"].text() == "läuft …"
    arbeiter.fortschritt.emit(512 * 1024**2, 1024 * 1024**2)
    assert dialog.einrichtung_fortschritt.value() == 500
    arbeiter.fortschritt.emit(0, 0)
    assert dialog.einrichtung_fortschritt.maximum() == 0  # unbestimmt
    arbeiter.log_line.emit("Ollama wird installiert ...")
    assert "installiert" in dialog.einrichtung_log.toPlainText()
    arbeiter.schritt.emit("ollama", "ok")
    assert dialog.aufgaben_labels["ollama"].text() == "✓ fertig"


def test_ohne_rechenumgebung_startet_das_programm_neu(dialog, monkeypatch):
    arbeiter = _bis_zur_einrichtung(dialog)
    arbeiter.fertig.emit({"ffmpeg": True, "ollama": True})
    assert not dialog.neustart_button.isHidden()
    assert dialog.einrichtung_weiter_button.isHidden()
    assert "neu" in dialog.einrichtung_status.text()

    gestartet = []
    monkeypatch.setattr(bootstrap, "neustart_kommando", lambda: (["app.exe"], Path("C:/app"), {"A": "1"}))
    monkeypatch.setattr(ee, "_starte_prozess", lambda *a: gestartet.append(a))
    dialog.neustart_button.click()

    assert gestartet == [(["app.exe"], Path("C:/app"), {"A": "1"})]
    assert dialog.result() == dialog.NEUSTART
    konfig = app_config.load_config()
    assert konfig["einrichtung_fortsetzen"] == ee.FORTSETZEN_TRANSKRIPTION
    assert konfig["transkription_modus"] == "lokal"


def test_neustart_scheitert_verstaendlich(dialog, monkeypatch):
    arbeiter = _bis_zur_einrichtung(dialog)
    arbeiter.fertig.emit({})

    def kaputt(*a):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(ee, "_starte_prozess", kaputt)
    with mock.patch.object(ee.QMessageBox, "warning") as warnung:
        dialog.neustart_button.click()
    assert "Zugriff verweigert" in warnung.call_args[0][2]
    assert app_config.load_config()["einrichtung_fortsetzen"] == ""
    assert dialog.result() != dialog.NEUSTART


def test_fehler_lassen_sich_wiederholen_oder_ueberspringen(dialog, monkeypatch):
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: True)
    arbeiter = _bis_zur_einrichtung(dialog)
    arbeiter.fertig.emit({"ffmpeg": True, "ollama": False, f"modell:{ollama_service.DEFAULT_MODEL}": False})
    assert not dialog.erneut_button.isHidden()
    assert "Nicht alles" in dialog.einrichtung_status.text()
    assert dialog.einrichtung_weiter_button.isEnabled()  # ueberspringen geht

    arbeiter.gestartet = False
    dialog.erneut_button.click()
    assert len(_Einrichtung.instanzen) == 2

    _Einrichtung.instanzen[-1].fertig.emit({"ollama": True})
    dialog.einrichtung_weiter_button.click()
    assert dialog.stack.currentIndex() == dialog.S_MITSCHRIFT  # lokal: weiter zur Mitschrift


def test_abbrechen_waehrend_der_einrichtung_stoppt_den_arbeiter(dialog):
    arbeiter = _bis_zur_einrichtung(dialog)
    dialog.reject()
    assert arbeiter.abgebrochen
    assert app_config.load_config()["einrichtung_abgeschlossen"] is False  # kommt wieder


# --------------------------------------------------------------------------
# 6. Mitschrift (nach dem Neustart)
# --------------------------------------------------------------------------
@pytest.fixture
def fortsetzung(qt_widgets, konfig, monkeypatch):
    _Mitschrift.instanzen = []
    monkeypatch.setattr(ee, "MitschriftWorker", _Mitschrift)
    monkeypatch.setattr(ee, "ErmittlungsWorker", _Ermittlung)
    gespeichert: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "save_api_key", lambda name, wert: gespeichert.__setitem__(name, wert))
    app_config.update_config(einrichtung_fortsetzen=ee.FORTSETZEN_TRANSKRIPTION, whisper_modell="small")
    fenster = qt_widgets(ee.ErsteinrichtungDialog(start_bei=ee.FORTSETZEN_TRANSKRIPTION))
    fenster.gespeichert = gespeichert
    return fenster


def test_fortsetzung_beginnt_bei_der_mitschrift(fortsetzung):
    assert fortsetzung.stack.currentIndex() == fortsetzung.S_MITSCHRIFT
    assert fortsetzung.whisper_wahl.currentData() == "small"
    assert not fortsetzung.token_bereich.isHidden()  # noch kein Zugang hinterlegt


def test_token_wird_gemerkt_aber_nie_in_die_konfiguration_geschrieben(fortsetzung, konfig):
    fortsetzung.token_edit.setText("hf_geheim123")
    fortsetzung.mitschrift_laden_button.click()

    arbeiter = _Mitschrift.instanzen[-1]
    assert arbeiter.args[:3] == ("small", "hf_geheim123", True)
    assert fortsetzung.gespeichert == {hf_env.SCHLUESSEL_NAME: "hf_geheim123"}
    assert "hf_geheim123" not in konfig.read_text(encoding="utf-8")
    assert "hf_geheim123" not in fortsetzung.mitschrift_log.toPlainText()

    arbeiter.fertig.emit({"whisper": True, "pyannote": True})
    assert app_config.load_config()["einrichtung_fortsetzen"] == ""  # kein weiterer Neustart
    assert not fortsetzung.mitschrift_weiter_button.isHidden()


def test_ohne_merken_nur_fuer_die_sitzung(fortsetzung):
    fortsetzung.token_edit.setText("hf_geheim123")
    fortsetzung.token_merken.setChecked(False)
    fortsetzung.mitschrift_laden_button.click()
    assert fortsetzung.gespeichert == {}
    assert _Mitschrift.instanzen[-1].args[1] == "hf_geheim123"


def test_kein_speicher_verfuegbar_ist_kein_abbruch(fortsetzung, monkeypatch):
    def nicht_verfuegbar(name, wert):
        raise secret_store.SecretStoreUnavailableError("Kein Speicher.")

    monkeypatch.setattr(secret_store, "save_api_key", nicht_verfuegbar)
    fortsetzung.token_edit.setText("hf_x")
    fortsetzung.mitschrift_laden_button.click()
    assert "nur für diese Sitzung" in fortsetzung.mitschrift_log.toPlainText()
    assert _Mitschrift.instanzen[-1].gestartet


def test_ohne_token_und_ohne_sprechererkennung(fortsetzung):
    fortsetzung.sprecher_checkbox.setChecked(False)
    assert fortsetzung.token_bereich.isHidden()
    fortsetzung.mitschrift_laden_button.click()
    assert _Mitschrift.instanzen[-1].args[1:3] == (None, False)
    _Mitschrift.instanzen[-1].fertig.emit({"whisper": False})
    assert fortsetzung.mitschrift_laden_button.text() == "Erneut versuchen"


def test_vorhandener_zugang_wird_nicht_erneut_abgefragt(qt_widgets, konfig, monkeypatch):
    monkeypatch.setattr(hf_env, "has_hf_token", lambda: True)
    fenster = qt_widgets(ee.ErsteinrichtungDialog(start_bei=ee.FORTSETZEN_TRANSKRIPTION))
    assert fenster.token_bereich.isHidden()
    assert not fenster.token_vorhanden_label.isHidden()


# --------------------------------------------------------------------------
# 7. Fertig, Schliessen
# --------------------------------------------------------------------------
def test_loslegen_schliesst_die_einrichtung_ab(dialog):
    app_config.update_config(einrichtung_fortsetzen="transkription", lokale_einrichtung_zurueckgestellt=True)
    dialog.ergebnisse = {"ffmpeg": True, f"modell:{ollama_service.DEFAULT_MODEL}": False}
    dialog._gehe_zu(dialog.S_FERTIG)
    assert ollama_service.DEFAULT_MODEL in dialog.fertig_label.text()  # was fehlt, steht da
    assert dialog.anbieter_button.isHidden()  # alles lokal
    dialog.loslegen_button.click()
    konfig = app_config.load_config()
    assert konfig["einrichtung_abgeschlossen"] is True
    assert konfig["einrichtung_fortsetzen"] == ""
    assert konfig["lokale_einrichtung_zurueckgestellt"] is False


def test_anbieter_eintragen_oeffnet_die_einstellungen_des_hauptfensters(qt_widgets, konfig, monkeypatch):
    from PySide6.QtWidgets import QWidget

    geoeffnet = []

    class _Hauptfenster(QWidget):
        def _open_settings(self):
            geoeffnet.append(True)

    eltern = qt_widgets(_Hauptfenster())
    fenster = ee.ErsteinrichtungDialog(eltern)
    app_config.update_config(nachbearbeitung_modus="api")
    fenster._gehe_zu(fenster.S_FERTIG)
    assert "Protokoll" in fenster.fertig_label.text()
    fenster.anbieter_button.click()
    assert geoeffnet == [True]
    assert app_config.load_config()["einrichtung_abgeschlossen"] is True


def test_spaeter_einrichten_kommt_wieder(dialog):
    dialog.spaeter_button.click()
    konfig = app_config.load_config()
    assert konfig["einrichtung_abgeschlossen"] is False
    assert konfig["lokale_einrichtung_zurueckgestellt"] is False


def test_nicht_mehr_fragen_ohne_zustimmung_laedt_nie_ungefragt(dialog):
    dialog.nicht_mehr_fragen.setChecked(True)
    dialog.spaeter_button.click()
    konfig = app_config.load_config()
    assert konfig["einrichtung_abgeschlossen"] is True
    assert konfig["lokale_einrichtung_zurueckgestellt"] is True
    # ... und app.py richtet deshalb beim naechsten Start nichts ein:
    assert not bootstrap.laufzeit_beim_start_einrichten(konfig, fenster_moeglich=True, laufzeit_vorhanden=False)


def test_nicht_mehr_fragen_nach_zustimmung_stellt_nichts_zurueck(dialog):
    _bis_zur_einrichtung(dialog)
    dialog.nicht_mehr_fragen.setChecked(True)
    dialog.reject()
    assert app_config.load_config()["lokale_einrichtung_zurueckgestellt"] is False


# --------------------------------------------------------------------------
# Arbeiter (ohne Thread: run() direkt)
# --------------------------------------------------------------------------
def test_ermittlungsworker_liefert_analyse_und_vorhandenes(qt_app):
    ergebnis = []
    worker = ee.ErmittlungsWorker(
        Path("."), analyse_fn=lambda o: "analyse", vorhanden_fn=lambda: {"ffmpeg": True}
    )
    worker.fertig.connect(lambda a, v: ergebnis.append((a, v)))
    worker.run()
    assert ergebnis == [("analyse", {"ffmpeg": True})]


def test_ermittlungsworker_scheitert_nie(qt_app):
    def kaputt(*a):
        raise RuntimeError("WMI weg")

    ergebnis = []
    worker = ee.ErmittlungsWorker(Path("."), analyse_fn=kaputt, vorhanden_fn=kaputt)
    worker.fertig.connect(lambda a, v: ergebnis.append((a, v)))
    worker.run()
    analyse, vorhanden = ergebnis[0]
    assert analyse.profil == RechnerProfil() and vorhanden == {}


def test_ermittlungsworker_prueft_was_da_ist(qt_app, monkeypatch):
    from protokoll_assistent.services import ffmpeg_service, ollama_einrichtung_service

    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: Path("ffmpeg.exe"))
    monkeypatch.setattr(
        ollama_einrichtung_service, "ermittle_status",
        lambda: ollama_einrichtung_service.OllamaStatus(True, dienst_laeuft=True),
    )
    monkeypatch.setattr(ollama_service, "list_models", lambda timeout: ["bge-m3:latest"])
    monkeypatch.setattr(ee, "laufzeit_vorhanden", lambda: False)
    assert ee.ErmittlungsWorker._vorhanden() == {
        "ffmpeg": True, "ollama": True, "laufzeit": False, "modelle": {"bge-m3:latest"},
    }

    def unerreichbar(timeout):
        raise ollama_service.OllamaError("weg")

    monkeypatch.setattr(ollama_service, "list_models", unerreichbar)
    assert ee._ollama_modelle() == set()


def _einrichtung_ausfuehren(**fns):
    zustaende, ergebnis = [], []
    worker = ee.EinrichtungsWorker(fns.pop("aufgaben"), fns.pop("modelle"), **fns)
    worker.schritt.connect(lambda k, z: zustaende.append((k, z)))
    worker.fertig.connect(ergebnis.append)
    worker.run()
    return zustaende, ergebnis[0]


def test_einrichtungsworker_kompletter_ablauf(qt_app):
    gezogen = []
    zustaende, ergebnis = _einrichtung_ausfuehren(
        aufgaben=["ffmpeg", "ollama"], modelle=["a", "b"],
        ffmpeg_fn=lambda log: True, ollama_fn=lambda log: True,
        pull_fn=lambda modell, progress_cb: gezogen.append(modell) or progress_cb("pulling", 5, 10),
    )
    assert ergebnis == {"ffmpeg": True, "ollama": True, "modell:a": True, "modell:b": True}
    assert gezogen == ["a", "b"]
    assert zustaende[:2] == [("ffmpeg", "laeuft"), ("ffmpeg", "ok")]


def test_einrichtungsworker_ohne_ollama_keine_modelle(qt_app):
    from protokoll_assistent.services import ollama_einrichtung_service

    def scheitert(log):
        raise ollama_einrichtung_service.OllamaEinrichtungFehler("Signatur falsch")

    zustaende, ergebnis = _einrichtung_ausfuehren(
        aufgaben=["ollama"], modelle=["a"], ollama_fn=scheitert, pull_fn=pytest.fail,
    )
    assert ergebnis == {"ollama": False, "modell:a": False}
    assert ("modell:a", "fehler") in zustaende


def test_einrichtungsworker_unerwartete_fehler(qt_app):
    def kaputt(log):
        raise ValueError("huch")

    log = []
    worker = ee.EinrichtungsWorker(["ffmpeg"], [], ffmpeg_fn=kaputt)
    worker.log_line.connect(log.append)
    ergebnis = []
    worker.fertig.connect(ergebnis.append)
    worker.run()
    assert ergebnis == [{"ffmpeg": False}] and "huch" in log[0]


def test_einrichtungsworker_abbrechen(qt_app):
    worker = ee.EinrichtungsWorker([], ["a"], pull_fn=pytest.fail)
    worker.abbrechen()
    ergebnis = []
    worker.fertig.connect(ergebnis.append)
    worker.run()
    assert ergebnis == [{"modell:a": False}]


def test_einrichtungsworker_echte_schritte(qt_app, monkeypatch, tmp_path):
    from protokoll_assistent.services import ffmpeg_service, ollama_einrichtung_service
    from protokoll_assistent.utils import paths

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", lambda progress_cb: None)
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(ffmpeg_service, "find_ffprobe", lambda: None)
    assert ee.EinrichtungsWorker._ffmpeg(lambda m: None) is False  # ffprobe fehlt

    aufrufe = []
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ollama_einrichtung_service, "installiere_ollama",
        lambda ordner, log, fortschritt, abbrechen_fn: aufrufe.append(ordner) or True,
    )
    assert ee.EinrichtungsWorker([], [])._ollama(lambda m: None) is True
    assert aufrufe == [tmp_path / "runtime" / "installer"]


def test_mitschriftworker(qt_app):
    tokens = []

    def pyannote(log, get_token):
        tokens.append(get_token())
        return True

    ergebnis = []
    worker = ee.MitschriftWorker("small", "hf_x", True, whisper_fn=lambda log, model_name: model_name == "small", pyannote_fn=pyannote)
    worker.fertig.connect(ergebnis.append)
    worker.run()
    assert ergebnis == [{"whisper": True, "pyannote": True}] and tokens == ["hf_x"]


def test_mitschriftworker_meldet_fehler_ohne_traceback(qt_app):
    def kaputt(log, model_name):
        raise RuntimeError("kein Netz")

    ergebnis, log = [], []
    worker = ee.MitschriftWorker("small", None, False, whisper_fn=kaputt)
    worker.log_line.connect(log.append)
    worker.fertig.connect(ergebnis.append)
    worker.run()
    assert ergebnis == [{}] and "kein Netz" in log[0]


def test_laufzeit_vorhanden(monkeypatch, tmp_path):
    import importlib.util

    from protokoll_assistent.utils import paths

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(paths, "get_active_venv_python", lambda: tmp_path / "python.exe")
    assert ee.laufzeit_vorhanden() is False
    (tmp_path / "python.exe").write_bytes(b"")
    assert ee.laufzeit_vorhanden() is True


def test_prozessstart_ist_losgeloest(monkeypatch, tmp_path):
    import subprocess

    gestartet = []
    monkeypatch.setattr(subprocess, "Popen", lambda befehl, **kwargs: gestartet.append((befehl, kwargs)))
    ee._starte_prozess(["app.exe"], tmp_path, {"A": "1"})
    befehl, kwargs = gestartet[0]
    assert befehl == ["app.exe"] and kwargs["cwd"] == str(tmp_path) and kwargs["env"] == {"A": "1"}
