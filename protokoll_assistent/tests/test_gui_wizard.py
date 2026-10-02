"""Tests fuer den Einrichtungsassistenten (``gui/wizard.py``).

Es wird nie wirklich etwas heruntergeladen: die Hintergrund-Threads werden
entweder direkt (ohne Thread) aufgerufen oder durch Attrappen ersetzt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from PySide6.QtWidgets import QFileDialog, QInputDialog  # noqa: E402

from protokoll_assistent.gui import wizard  # noqa: E402
from protokoll_assistent.services import model_service  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402


class _Pruefung:
    def __init__(self, ok, critical=False, label="Bezeichnung", detail="Detail"):
        self.ok = ok
        self.critical = critical
        self.label = label
        self.detail = detail


@pytest.fixture
def isolierte_konfiguration(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    return tmp_path


@pytest.fixture
def aufnahmeordner(tmp_path):
    ordner = tmp_path / "aufnahmen"
    ordner.mkdir()
    (ordner / "b.mp3").write_bytes(b"\x00")
    (ordner / "a.wav").write_bytes(b"\x00")
    (ordner / "notiz.txt").write_text("x", encoding="utf-8")
    return ordner


# --------------------------------------------------------------------------
# WelcomePage
# --------------------------------------------------------------------------
def test_willkommensseite(qt_widgets, isolierte_konfiguration):
    seite = qt_widgets(wizard.WelcomePage())
    ausgeloest = []
    seite.continue_requested.connect(lambda: ausgeloest.append(True))

    knopf = next(
        k for k in seite.findChildren(wizard.QPushButton) if k.text() == "Los geht's"
    )
    knopf.click()

    assert ausgeloest == [True]


# --------------------------------------------------------------------------
# InstallWorker
# --------------------------------------------------------------------------
@pytest.fixture
def install_worker(qt_app):
    return wizard.InstallWorker()


def test_install_worker_token_abfrage(install_worker):
    angefragt = []
    install_worker.request_token.connect(lambda: angefragt.append(True))
    # Genau so laeuft es in der Anwendung: 'request_token' ist mit
    # 'InstallPage._ask_for_token' verbunden, das noch waehrend des 'emit'
    # antwortet. Deshalb braucht es hier keinen zweiten Faden - der koennte
    # beim Aufraeumen ein Widget einsammeln und den Prozess abbrechen.
    install_worker.request_token.connect(lambda: install_worker.provide_token("geheim"))

    assert install_worker._get_token() == "geheim"
    assert angefragt == [True]


def test_install_worker_laeuft_durch(install_worker, monkeypatch, tmp_path):
    from protokoll_assistent.services import ffmpeg_service, model_download_service, ollama_service
    from protokoll_assistent.utils import app_config

    # Die Konfiguration liegt im Temp-Ordner, nie in der echten Datei.
    konfig = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: konfig)
    app_config.update_config(ollama_modell="qwen3:14b")

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", lambda progress_cb: None)
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: Path("ffmpeg.exe"))
    monkeypatch.setattr(ffmpeg_service, "find_ffprobe", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ollama_service, "ensure_ollama_or_offer_installer", lambda ordner, progress_cb: True
    )
    monkeypatch.setattr(
        model_download_service, "download_pyannote", lambda log, get_token: True
    )
    geladene_ollama_modelle = []
    monkeypatch.setattr(
        model_download_service,
        "download_ollama_model",
        lambda log, model=None: geladene_ollama_modelle.append(model) or True,
    )

    ergebnisse, meldungen = [], []
    install_worker.finished_ok.connect(ergebnisse.append)
    install_worker.log_line.connect(meldungen.append)

    install_worker.run()

    assert ergebnisse == [{"ffmpeg": True, "ollama": True, "pyannote": True, "ollama_modell": True}]
    assert any("FFmpeg" in m for m in meldungen)
    # Heruntergeladen wird das in den Einstellungen gewaehlte Modell.
    assert geladene_ollama_modelle == ["qwen3:14b"]


def test_install_worker_meldet_fehler_ohne_traceback(install_worker, monkeypatch):
    from protokoll_assistent.services import ffmpeg_service

    def werfen(progress_cb):
        raise RuntimeError("Netzwerk weg")

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", werfen)

    fehler = []
    install_worker.failed.connect(fehler.append)

    install_worker.run()

    assert fehler == ["Netzwerk weg"]


# --------------------------------------------------------------------------
# InstallPage
# --------------------------------------------------------------------------
@pytest.fixture
def install_seite(qt_widgets, isolierte_konfiguration, monkeypatch):
    # Der echte Thread darf nie starten.
    monkeypatch.setattr(wizard.InstallWorker, "start", lambda self: None)
    return qt_widgets(wizard.InstallPage())


def test_install_seite_start_setzt_zustand(install_seite):
    install_seite.start()
    assert install_seite._worker is not None
    assert not install_seite.continue_button.isEnabled()
    assert not install_seite.retry_button.isVisibleTo(install_seite)


def test_install_seite_start_ignoriert_zweiten_lauf(install_seite, monkeypatch):
    install_seite.start()
    erster = install_seite._worker
    monkeypatch.setattr(type(erster), "isRunning", lambda self: True)

    install_seite.start()

    assert install_seite._worker is erster


def test_install_seite_erfolg(install_seite):
    install_seite.start()
    install_seite._on_finished({"pyannote": True, "ollama_modell": True})

    assert install_seite.continue_button.isEnabled()
    assert "abgeschlossen" in install_seite.log_edit.toPlainText()


def test_install_seite_erfolg_mit_luecken(install_seite):
    install_seite.start()
    install_seite._on_finished({"pyannote": False, "ollama_modell": True})

    text = install_seite.log_edit.toPlainText()
    assert "pyannote" in text
    assert "später über die Systemdiagnose" in text
    assert install_seite.continue_button.isEnabled()


def test_install_seite_fehler_bietet_wiederholung(install_seite):
    install_seite.start()
    install_seite._on_failed("Kein Netz")

    assert "FEHLER: Kein Netz" in install_seite.log_edit.toPlainText()
    assert install_seite.retry_button.isVisibleTo(install_seite)
    assert install_seite.continue_button.isEnabled()


def test_install_seite_fragt_token_ab(install_seite, monkeypatch):
    install_seite.start()
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("  mein-token  ", True))
    )
    gegeben = []
    monkeypatch.setattr(
        type(install_seite._worker), "provide_token", lambda self, t: gegeben.append(t)
    )

    install_seite._ask_for_token()

    assert gegeben == ["mein-token"]


def test_install_seite_token_abgebrochen(install_seite, monkeypatch):
    install_seite.start()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    gegeben = []
    monkeypatch.setattr(
        type(install_seite._worker), "provide_token", lambda self, t: gegeben.append(t)
    )

    install_seite._ask_for_token()

    assert gegeben == [None]


def test_install_seite_token_ohne_arbeiter(install_seite, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("t", True)))
    install_seite._worker = None
    install_seite._ask_for_token()  # darf nicht werfen


# --------------------------------------------------------------------------
# DiagnosticsPage
# --------------------------------------------------------------------------
@pytest.fixture
def diagnose_seite(qt_widgets, isolierte_konfiguration, monkeypatch):
    monkeypatch.setattr(wizard.DiagnosticsRunner, "start", lambda self: None)
    return qt_widgets(wizard.DiagnosticsPage())


def test_diagnose_seite_start(diagnose_seite):
    diagnose_seite.start()
    assert not diagnose_seite.retry_button.isEnabled()
    assert "läuft" in diagnose_seite.summary_label.text()


def test_diagnose_seite_alles_gut(diagnose_seite):
    diagnose_seite._show_results([_Pruefung(ok=True, label="Python")])

    assert diagnose_seite.continue_button.isEnabled()
    assert "erfolgreich" in diagnose_seite.summary_label.text()
    assert diagnose_seite.table.rowCount() == 1
    assert diagnose_seite.last_results


def test_diagnose_seite_kritische_luecke_blockiert(diagnose_seite):
    diagnose_seite._show_results(
        [_Pruefung(ok=True, label="Python"), _Pruefung(ok=False, critical=True, label="FFmpeg")]
    )

    assert not diagnose_seite.continue_button.isEnabled()
    assert "FFmpeg" in diagnose_seite.summary_label.text()


def test_diagnose_seite_unkritische_luecke_erlaubt_weiter(diagnose_seite):
    diagnose_seite._show_results([_Pruefung(ok=False, critical=False, label="GPU")])
    assert diagnose_seite.continue_button.isEnabled()


def test_diagnose_seite_zeigt_laufende_pruefung(diagnose_seite):
    # Ohne diese Rueckmeldung stand waehrend der gesamten (bei einer frischen
    # Einrichtung ggf. mehrminuetigen) Pruefung nur ein einziger,
    # unveraenderter "laeuft ..."-Text da.
    diagnose_seite._on_check_started("pyannote.audio")
    assert "pyannote.audio" in diagnose_seite.summary_label.text()


# --------------------------------------------------------------------------
# WhisperDownloadWorker
# --------------------------------------------------------------------------
def test_whisper_worker_erfolg(qt_app, monkeypatch):
    from protokoll_assistent.services import model_download_service

    monkeypatch.setattr(
        model_download_service, "download_whisper_and_alignment", lambda log, model_name: True
    )
    worker = wizard.WhisperDownloadWorker("large-v2")
    ergebnisse = []
    worker.finished_ok.connect(ergebnisse.append)

    worker.run()

    assert ergebnisse == [True]


def test_whisper_worker_fehler_ohne_traceback(qt_app, monkeypatch):
    from protokoll_assistent.services import model_download_service

    def werfen(log, model_name):
        raise RuntimeError("Modell nicht gefunden")

    monkeypatch.setattr(model_download_service, "download_whisper_and_alignment", werfen)
    worker = wizard.WhisperDownloadWorker("quatsch")
    ergebnisse, meldungen = [], []
    worker.finished_ok.connect(ergebnisse.append)
    worker.log_line.connect(meldungen.append)

    worker.run()

    assert ergebnisse == [False]
    assert any("Modell nicht gefunden" in m for m in meldungen)
    assert not any("Traceback" in m for m in meldungen)


# --------------------------------------------------------------------------
# ModelChoicePage
# --------------------------------------------------------------------------
@pytest.fixture
def modell_seite(qt_widgets, isolierte_konfiguration, monkeypatch):
    monkeypatch.setattr(wizard.WhisperDownloadWorker, "start", lambda self: None)
    return qt_widgets(wizard.ModelChoicePage())


def test_modell_seite_startet_ohne_freigabe(modell_seite):
    assert not modell_seite.continue_button.isEnabled()


def test_modell_seite_empfehlung(modell_seite, monkeypatch):
    empfohlen = model_service.WHISPER_MODEL_NAME
    monkeypatch.setattr(
        model_service, "whisper_empfehlung_aus_diagnose", lambda ergebnisse: empfohlen
    )

    modell_seite.apply_recommendation([_Pruefung(ok=True)])

    assert "Empfehlung für diesen Computer" in modell_seite.recommendation_label.text()
    assert modell_seite.model_combo.currentData() == empfohlen


def test_modell_seite_empfehlung_beachtet_gespeicherte_wahl(modell_seite, monkeypatch):
    optionen = [
        modell_seite.model_combo.itemData(i) for i in range(modell_seite.model_combo.count())
    ]
    gespeichert = next(o for o in optionen if o and o != wizard.EIGENE_MODELL_ID)
    app_config.save_config({"whisper_modell": gespeichert})
    monkeypatch.setattr(
        model_service, "whisper_empfehlung_aus_diagnose", lambda e: "irgendwas-anderes"
    )

    modell_seite.apply_recommendation([])

    assert modell_seite.model_combo.currentData() == gespeichert


def test_modell_seite_eigene_id(modell_seite):
    index = modell_seite.model_combo.findData(wizard.EIGENE_MODELL_ID)
    modell_seite.model_combo.setCurrentIndex(index)
    modell_seite._on_selection_changed()

    assert modell_seite.custom_model_edit.isVisibleTo(modell_seite)
    assert "Freie Eingabe" in modell_seite.hinweis_label.text()

    modell_seite.custom_model_edit.setText("  mein/modell  ")
    assert modell_seite._selected_model_name() == "mein/modell"


def test_modell_seite_eigene_id_leer(modell_seite):
    index = modell_seite.model_combo.findData(wizard.EIGENE_MODELL_ID)
    modell_seite.model_combo.setCurrentIndex(index)
    modell_seite.custom_model_edit.setText("   ")
    assert modell_seite._selected_model_name() is None


def test_modell_seite_download_ohne_id(modell_seite):
    index = modell_seite.model_combo.findData(wizard.EIGENE_MODELL_ID)
    modell_seite.model_combo.setCurrentIndex(index)
    modell_seite.custom_model_edit.setText("")

    modell_seite._start_download()

    assert "Bitte zuerst eine Modell-ID" in modell_seite.log_edit.toPlainText()
    assert modell_seite._worker is None


def test_modell_seite_download_startet(modell_seite):
    modell_seite._start_download()
    assert modell_seite._worker is not None
    assert not modell_seite.download_button.isEnabled()


def test_modell_seite_download_ignoriert_zweiten_lauf(modell_seite, monkeypatch):
    modell_seite._start_download()
    erster = modell_seite._worker
    monkeypatch.setattr(type(erster), "isRunning", lambda self: True)

    modell_seite._start_download()

    assert modell_seite._worker is erster


def test_modell_seite_download_erfolgreich(modell_seite):
    modell_seite._on_download_finished(True)
    assert "einsatzbereit" in modell_seite.log_edit.toPlainText()
    assert modell_seite.continue_button.isEnabled()
    assert modell_seite.download_button.isEnabled()


def test_modell_seite_download_fehlgeschlagen(modell_seite):
    modell_seite._on_download_finished(False)
    assert "konnte nicht geladen werden" in modell_seite.log_edit.toPlainText()
    # Weitermachen bleibt erlaubt - die Diagnose kann es spaeter pruefen.
    assert modell_seite.continue_button.isEnabled()


def test_modell_seite_bestaetigen_speichert_wahl(modell_seite, isolierte_konfiguration):
    ausgeloest = []
    modell_seite.continue_requested.connect(lambda: ausgeloest.append(True))

    modell_seite._confirm()

    assert ausgeloest == [True]
    assert app_config.load_config()["whisper_modell"] == modell_seite._selected_model_name()


def test_modell_seite_bestaetigen_ohne_wahl(modell_seite, isolierte_konfiguration):
    index = modell_seite.model_combo.findData(wizard.EIGENE_MODELL_ID)
    modell_seite.model_combo.setCurrentIndex(index)
    modell_seite.custom_model_edit.setText("")

    ausgeloest = []
    modell_seite.continue_requested.connect(lambda: ausgeloest.append(True))

    modell_seite._confirm()

    assert ausgeloest == [True]


# --------------------------------------------------------------------------
# InputFolderPage
# --------------------------------------------------------------------------
def test_ordnerseite_ohne_gespeicherten_ordner(qt_widgets, isolierte_konfiguration):
    seite = qt_widgets(wizard.InputFolderPage())
    assert not seite.continue_button.isEnabled()


def test_ordnerseite_uebernimmt_gespeicherten_ordner(
    qt_widgets, isolierte_konfiguration, aufnahmeordner
):
    app_config.save_config({"eingabeordner": str(aufnahmeordner)})
    seite = qt_widgets(wizard.InputFolderPage())

    assert seite.continue_button.isEnabled()
    assert [seite.file_list.item(i).text() for i in range(seite.file_list.count())] == [
        "a.wav",
        "b.mp3",
    ]


def test_ordnerseite_ignoriert_verschwundenen_ordner(
    qt_widgets, isolierte_konfiguration, tmp_path
):
    app_config.save_config({"eingabeordner": str(tmp_path / "gibtesnicht")})
    seite = qt_widgets(wizard.InputFolderPage())
    assert not seite.continue_button.isEnabled()


def test_ordnerseite_auswahl_ueber_dialog(
    qt_widgets, isolierte_konfiguration, aufnahmeordner, monkeypatch
):
    seite = qt_widgets(wizard.InputFolderPage())
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(aufnahmeordner))
    )

    seite._choose_folder()

    assert seite._folder == aufnahmeordner
    assert app_config.load_config()["eingabeordner"] == str(aufnahmeordner)


def test_ordnerseite_auswahl_abgebrochen(qt_widgets, isolierte_konfiguration, monkeypatch):
    seite = qt_widgets(wizard.InputFolderPage())
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    seite._choose_folder()

    assert seite._folder is None


def test_ordnerseite_mit_unlesbarem_ordner(qt_widgets, isolierte_konfiguration, tmp_path):
    seite = qt_widgets(wizard.InputFolderPage())
    seite._set_folder(tmp_path / "gibtesnicht")
    assert seite.file_list.count() == 0
    assert seite.continue_button.isEnabled()


def test_ordnerseite_bestaetigen_ohne_ordner(qt_widgets, isolierte_konfiguration):
    seite = qt_widgets(wizard.InputFolderPage())
    ausgeloest = []
    seite.folder_confirmed.connect(lambda o, d: ausgeloest.append((o, d)))

    seite._confirm()

    assert ausgeloest == []


def test_ordnerseite_bestaetigen_ohne_dateiauswahl(
    qt_widgets, isolierte_konfiguration, aufnahmeordner
):
    seite = qt_widgets(wizard.InputFolderPage())
    seite._set_folder(aufnahmeordner)
    ausgeloest = []
    seite.folder_confirmed.connect(lambda o, d: ausgeloest.append((o, d)))

    seite._confirm()

    assert ausgeloest == [(str(aufnahmeordner), "")]


def test_ordnerseite_bestaetigen_mit_dateiauswahl(
    qt_widgets, isolierte_konfiguration, aufnahmeordner
):
    seite = qt_widgets(wizard.InputFolderPage())
    seite._set_folder(aufnahmeordner)
    seite.file_list.setCurrentRow(1)  # b.mp3
    ausgeloest = []
    seite.folder_confirmed.connect(lambda o, d: ausgeloest.append((o, d)))

    seite._confirm()

    assert ausgeloest == [(str(aufnahmeordner), "b.mp3")]


# --------------------------------------------------------------------------
# SetupWizard
# --------------------------------------------------------------------------
@pytest.fixture
def assistent(qt_widgets, isolierte_konfiguration, monkeypatch):
    # Keine Seite darf beim Blaettern echte Arbeit anstossen.
    monkeypatch.setattr(wizard.RechnerAnalysePage, "start", lambda self: None)
    monkeypatch.setattr(wizard.InstallPage, "start", lambda self: None)
    monkeypatch.setattr(wizard.DiagnosticsPage, "start", lambda self: None)
    monkeypatch.setattr(wizard.ModelChoicePage, "apply_recommendation", lambda self, e: None)
    return qt_widgets(wizard.SetupWizard())


def test_assistent_startet_auf_seite_eins(assistent):
    assert assistent.stack.currentIndex() == 0
    assert assistent._step_labels[0].objectName() == "StepIndicatorActive"


def test_assistent_zeigt_datenschutzhinweis(assistent):
    treffer = [
        kind
        for kind in assistent.findChildren(wizard.QLabel)
        if kind.objectName() == "PrivacyBanner"
    ]
    assert treffer
    assert treffer[0].text() == wizard.PRIVACY_NOTICE


@pytest.mark.parametrize("ziel", [1, 2, 3, 4, 5])
def test_assistent_blaettert_weiter(assistent, ziel):
    assistent._go_to(ziel)
    assert assistent.stack.currentIndex() == ziel
    assert assistent._step_labels[ziel].objectName() == "StepIndicatorActive"
    assert assistent._step_labels[0].objectName() == "StepIndicator"


def test_assistent_kette_bis_zum_ende(assistent, aufnahmeordner):
    fertig = []
    assistent.setup_finished.connect(lambda o, d: fertig.append((o, d)))

    assistent.welcome_page.continue_requested.emit()
    assert assistent.stack.currentIndex() == 1
    assert assistent.stack.currentWidget() is assistent.analyse_page
    assistent.analyse_page.continue_requested.emit()
    assert assistent.stack.currentIndex() == 2
    assistent.install_page.continue_requested.emit()
    assert assistent.stack.currentIndex() == 3
    assistent.diagnostics_page.continue_requested.emit()
    assert assistent.stack.currentIndex() == 4
    assistent.model_page.continue_requested.emit()
    assert assistent.stack.currentIndex() == 5

    assistent.folder_page._set_folder(aufnahmeordner)
    assistent.folder_page._confirm()

    assert fertig == [(str(aufnahmeordner), "")]


def test_assistent_startet_seiten_beim_blaettern(qt_widgets, isolierte_konfiguration, monkeypatch):
    gestartet: list[str] = []
    monkeypatch.setattr(wizard.RechnerAnalysePage, "start", lambda self: gestartet.append("analyse"))
    monkeypatch.setattr(wizard.InstallPage, "start", lambda self: gestartet.append("install"))
    monkeypatch.setattr(wizard.DiagnosticsPage, "start", lambda self: gestartet.append("diagnose"))
    monkeypatch.setattr(
        wizard.ModelChoicePage, "apply_recommendation", lambda self, e: gestartet.append("modell")
    )

    assistent = qt_widgets(wizard.SetupWizard())
    assistent._go_to(1)
    assistent._go_to(2)
    assistent._go_to(3)
    assistent._go_to(4)

    assert gestartet == ["analyse", "install", "diagnose", "modell"]


# --------------------------------------------------------------------------
# LokalEinrichtungDialog
# --------------------------------------------------------------------------
@pytest.fixture
def einrichtung_dialog(qt_widgets, isolierte_konfiguration, monkeypatch):
    # Keine Seite darf beim Blaettern echte Arbeit anstossen.
    monkeypatch.setattr(wizard.RechnerAnalysePage, "start", lambda self: None)
    monkeypatch.setattr(wizard.InstallPage, "start", lambda self: None)
    monkeypatch.setattr(wizard.DiagnosticsPage, "start", lambda self: None)
    monkeypatch.setattr(wizard.ModelChoicePage, "apply_recommendation", lambda self, e: None)
    return qt_widgets(wizard.LokalEinrichtungDialog())


def test_einrichtung_dialog_startet_mit_der_rechner_analyse(einrichtung_dialog):
    # Anders als 'SetupWizard': keine Willkommens- oder Ordnerseite -- die
    # Anwendung steht ja bereits, wenn dieser Dialog aus den Einstellungen
    # heraus geoeffnet wird. Als Erstes wird der Rechner analysiert, noch
    # bevor etwas heruntergeladen wird.
    assert einrichtung_dialog.stack.currentIndex() == 0
    assert einrichtung_dialog.stack.currentWidget() is einrichtung_dialog.analyse_page


def test_einrichtung_dialog_startet_seiten_beim_blaettern(qt_widgets, isolierte_konfiguration, monkeypatch):
    gestartet: list[str] = []
    monkeypatch.setattr(wizard.RechnerAnalysePage, "start", lambda self: gestartet.append("analyse"))
    monkeypatch.setattr(wizard.InstallPage, "start", lambda self: gestartet.append("install"))
    monkeypatch.setattr(wizard.DiagnosticsPage, "start", lambda self: gestartet.append("diagnose"))
    monkeypatch.setattr(
        wizard.ModelChoicePage, "apply_recommendation", lambda self, e: gestartet.append("modell")
    )

    dialog = qt_widgets(wizard.LokalEinrichtungDialog())
    assert gestartet == ["analyse"]
    dialog._go_to(1)
    dialog._go_to(2)
    dialog._go_to(3)

    assert gestartet == ["analyse", "install", "diagnose", "modell"]


def test_einrichtung_dialog_kette_bis_zum_ende(einrichtung_dialog):
    beendet = []
    einrichtung_dialog.accepted.connect(lambda: beendet.append(True))

    einrichtung_dialog.analyse_page.continue_requested.emit()
    assert einrichtung_dialog.stack.currentIndex() == 1
    einrichtung_dialog.install_page.continue_requested.emit()
    assert einrichtung_dialog.stack.currentIndex() == 2
    einrichtung_dialog.diagnostics_page.continue_requested.emit()
    assert einrichtung_dialog.stack.currentIndex() == 3
    einrichtung_dialog.model_page.continue_requested.emit()

    assert beendet == [True]


# --------------------------------------------------------------------------
# Rechner-Analyse
# --------------------------------------------------------------------------
def _analyse(profil=None):
    from protokoll_assistent.services import rechner_analyse_service as ra

    return ra.analysiere(profil or ra.RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300))


@pytest.fixture
def analyse_seite(qt_widgets, isolierte_konfiguration, monkeypatch):
    # Der echte Thread darf nie starten.
    monkeypatch.setattr(wizard.RechnerAnalyseWorker, "start", lambda self: None)
    return qt_widgets(wizard.RechnerAnalysePage())


def test_analyse_worker_liefert_die_analyse(qt_app, tmp_path, monkeypatch):
    from protokoll_assistent.services import rechner_analyse_service as ra

    monkeypatch.setattr(ra, "ermittle_profil", lambda ordner: ra.RechnerProfil(ram_gb=8, cpu_kerne=4))
    arbeiter = wizard.RechnerAnalyseWorker(tmp_path)
    erhalten = []
    arbeiter.fertig.connect(erhalten.append)

    arbeiter.run()

    assert len(erhalten) == 1 and erhalten[0].profil.ram_gb == 8


def test_analyse_seite_startet_gesperrt(analyse_seite):
    analyse_seite.start()
    assert analyse_seite._worker is not None
    assert not analyse_seite.continue_button.isEnabled()
    assert "analysiert" in analyse_seite.profil_label.text()


def test_analyse_seite_ignoriert_zweiten_lauf(analyse_seite, monkeypatch):
    analyse_seite.start()
    erster = analyse_seite._worker
    monkeypatch.setattr(type(erster), "isRunning", lambda self: True)

    analyse_seite.start()

    assert analyse_seite._worker is erster


def test_analyse_seite_zeigt_modelle_und_hinweise(analyse_seite):
    analyse = _analyse()
    analyse_seite._zeige_analyse(analyse)

    assert analyse_seite.continue_button.isEnabled()
    assert analyse_seite.table.rowCount() == len(analyse.bewertungen)
    namen = [analyse_seite.table.item(z, 0).text() for z in range(analyse_seite.table.rowCount())]
    assert any("empfohlen" in n and "Turbo" in n for n in namen)
    stufen = {analyse_seite.table.item(z, 1).text() for z in range(analyse_seite.table.rowCount())}
    assert {"Läuft gut", "Eher nicht geeignet"} <= stufen
    assert "Arbeitsspeicher: 16.0 GB" in analyse_seite.profil_label.text()
    assert "Keine NVIDIA-Grafikkarte" in analyse_seite.hinweis_label.text()
    assert "qwen3:4b" in analyse_seite.hinweis_label.text()


def test_analyse_seite_bestaetigen_stellt_empfohlenes_modell_ein(analyse_seite):
    analyse_seite._zeige_analyse(_analyse())  # 16 GB / 8 Kerne -> qwen3:4b
    ausgeloest = []
    analyse_seite.continue_requested.connect(lambda: ausgeloest.append(True))

    analyse_seite._bestaetigen()

    konfig = app_config.load_config()
    assert konfig["ollama_modell"] == "qwen3:4b"
    assert konfig["chatbot_ollama_modell"] == "qwen3:4b"
    assert ausgeloest == [True]


def test_analyse_seite_ueberschreibt_keine_bewusste_wahl(analyse_seite):
    app_config.update_config(ollama_modell="gemma3:12b")
    analyse_seite._zeige_analyse(_analyse())

    analyse_seite.uebernehme_empfehlung()

    konfig = app_config.load_config()
    assert konfig["ollama_modell"] == "gemma3:12b"  # eigene Wahl bleibt
    assert konfig["chatbot_ollama_modell"] == "qwen3:4b"  # noch nie angefasst


def test_analyse_seite_aendert_nichts_wenn_der_standard_empfohlen_wird(analyse_seite):
    from protokoll_assistent.services import rechner_analyse_service as ra

    analyse_seite._zeige_analyse(
        _analyse(ra.RechnerProfil(ram_gb=32, cpu_kerne=12, gpu_name="RTX", vram_gb=12))
    )
    vorher = app_config.load_config()
    analyse_seite.uebernehme_empfehlung()
    assert app_config.load_config() == vorher


def test_analyse_seite_ohne_analyse_oder_ohne_empfehlung(analyse_seite):
    from protokoll_assistent.services import rechner_analyse_service as ra

    analyse_seite.uebernehme_empfehlung()  # noch keine Analyse: darf nichts tun
    analyse_seite._zeige_analyse(_analyse(ra.RechnerProfil(ram_gb=2, cpu_kerne=1)))
    vorher = app_config.load_config()
    analyse_seite.uebernehme_empfehlung()  # nichts empfehlbar: Einstellung bleibt
    assert app_config.load_config() == vorher


# --------------------------------------------------------------------------
# Werkzeuge nachladen
# --------------------------------------------------------------------------
def _werkzeuge(monkeypatch, ffmpeg_da, ollama_da):
    from protokoll_assistent.services import ffmpeg_service, ollama_service

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", lambda progress_cb: None)
    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: Path("ffmpeg.exe") if ffmpeg_da else None)
    monkeypatch.setattr(ffmpeg_service, "find_ffprobe", lambda: Path("ffprobe.exe") if ffmpeg_da else None)
    monkeypatch.setattr(
        ollama_service, "ensure_ollama_or_offer_installer", lambda ordner, progress_cb: ollama_da
    )


def test_werkzeuge_nachladen_meldet_gelungenes(monkeypatch):
    _werkzeuge(monkeypatch, True, True)
    meldungen = []
    assert wizard.werkzeuge_nachladen(meldungen.append) == {"ffmpeg": True, "ollama": True}
    assert not any("fehlt weiterhin" in m for m in meldungen)


def test_werkzeuge_nachladen_meldet_fehlschlaege(monkeypatch):
    _werkzeuge(monkeypatch, False, False)
    meldungen = []
    assert wizard.werkzeuge_nachladen(meldungen.append) == {"ffmpeg": False, "ollama": False}
    text = "\n".join(meldungen)
    assert "FFmpeg fehlt weiterhin" in text and "Ollama ist noch nicht einsatzbereit" in text


def test_nachlade_worker_laedt_auch_das_modell(qt_app, monkeypatch, isolierte_konfiguration):
    from protokoll_assistent.services import model_download_service

    _werkzeuge(monkeypatch, True, True)
    app_config.update_config(ollama_modell="qwen3:4b")
    geladen = []
    monkeypatch.setattr(
        model_download_service, "download_ollama_model", lambda log, modell: geladen.append(modell) or True
    )
    arbeiter = wizard.NachladenWorker()
    ergebnisse = []
    arbeiter.finished_ok.connect(ergebnisse.append)

    arbeiter.run()

    assert geladen == ["qwen3:4b"]
    assert ergebnisse == [{"ffmpeg": True, "ollama": True, "ollama_modell": True}]


def test_nachlade_worker_ueberspringt_das_modell_ohne_ollama(qt_app, monkeypatch, isolierte_konfiguration):
    from protokoll_assistent.services import model_download_service

    _werkzeuge(monkeypatch, True, False)
    monkeypatch.setattr(
        model_download_service, "download_ollama_model", lambda *a, **k: pytest.fail("darf nicht laden")
    )
    arbeiter = wizard.NachladenWorker()
    ergebnisse = []
    arbeiter.finished_ok.connect(ergebnisse.append)

    arbeiter.run()

    assert ergebnisse == [{"ffmpeg": True, "ollama": False}]


def test_nachlade_worker_meldet_unerwartete_fehler(qt_app, monkeypatch):
    from protokoll_assistent.services import ffmpeg_service

    def werfen(progress_cb):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(ffmpeg_service, "ensure_ffmpeg_available", werfen)
    arbeiter = wizard.NachladenWorker()
    meldungen, ergebnisse = [], []
    arbeiter.log_line.connect(meldungen.append)
    arbeiter.finished_ok.connect(ergebnisse.append)

    arbeiter.run()

    assert meldungen[-1] == "FEHLER: kaputt" and ergebnisse == [{}]


def test_diagnose_seite_bietet_nachladen_nur_bei_nachladbarem(diagnose_seite):
    class _Mit(_Pruefung):
        def __init__(self, key, **kwargs):
            super().__init__(**kwargs)
            self.key = key

    diagnose_seite._show_results([_Mit("ffmpeg", ok=False, critical=True, label="FFmpeg")])
    assert diagnose_seite.nachladen_button.isVisibleTo(diagnose_seite)
    assert "Fehlendes nachladen" in diagnose_seite.summary_label.text()

    diagnose_seite._show_results([_Mit("cuda", ok=False, critical=False, label="GPU")])
    assert not diagnose_seite.nachladen_button.isVisibleTo(diagnose_seite)

    diagnose_seite._show_results([_Pruefung(ok=True, label="ohne Schluessel")])  # Attrappen ohne 'key'
    assert not diagnose_seite.nachladen_button.isVisibleTo(diagnose_seite)


def test_diagnose_seite_nachladen_ablauf(diagnose_seite, monkeypatch):
    monkeypatch.setattr(wizard.NachladenWorker, "start", lambda self: None)

    diagnose_seite._nachladen()
    assert diagnose_seite._nachlade_worker is not None
    assert diagnose_seite.nachlade_log.isVisibleTo(diagnose_seite)
    assert not diagnose_seite.nachladen_button.isEnabled()
    assert "nachgeladen" in diagnose_seite.summary_label.text()

    # Ein zweiter Klick waehrend des Laufs startet nichts Neues.
    erster = diagnose_seite._nachlade_worker
    monkeypatch.setattr(type(erster), "isRunning", lambda self: True)
    diagnose_seite._nachladen()
    assert diagnose_seite._nachlade_worker is erster

    # Fertig mit Luecke: Grund im Protokoll, danach wird neu geprueft.
    diagnose_seite._nachladen_fertig({"ffmpeg": False, "ollama": True})
    text = diagnose_seite.nachlade_log.toPlainText()
    assert "Nicht gelungen: FFmpeg" in text
    assert diagnose_seite.nachladen_button.isEnabled()
    assert "läuft" in diagnose_seite.summary_label.text()  # 'start' hat neu geprueft

    diagnose_seite._nachladen_fertig({"ffmpeg": True})
    assert "Fertig." in diagnose_seite.nachlade_log.toPlainText()
