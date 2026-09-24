"""Tests fuer 'gui/settings_dialog.py'.

'secret_store' wird durch einen einfachen In-Memory-Speicher ersetzt - kein
Test spricht die echte Windows-Anmeldeinformationsverwaltung an (dafuer
gibt es 'test_secret_store.py'). Die Systemprompt-Vorlagenverwaltung liegt
inline im Hauptfenster (siehe 'test_gui_main_window.py') und wird hier
nicht getestet."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent.gui import settings_dialog as sd  # noqa: E402
from protokoll_assistent.services import secret_store  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402


@pytest.fixture
def schluessel_speicher(monkeypatch):
    gespeichert: dict[str, str] = {}

    def speichern(name, wert):
        gespeichert[name] = wert

    def lesen(name):
        return gespeichert.get(name)

    def loeschen(name):
        gespeichert.pop(name, None)

    monkeypatch.setattr(secret_store, "save_api_key", speichern)
    monkeypatch.setattr(secret_store, "load_api_key", lesen)
    monkeypatch.setattr(secret_store, "delete_api_key", loeschen)
    return gespeichert


@pytest.fixture
def isolierte_konfiguration(tmp_path, monkeypatch):
    konfig_datei = tmp_path / "konfiguration.json"
    monkeypatch.setattr(app_config, "get_config_file", lambda: konfig_datei)
    return {"konfig": konfig_datei}


@pytest.fixture
def dialog(qt_widgets, isolierte_konfiguration, schluessel_speicher):
    return qt_widgets(sd.SettingsDialog())


# --------------------------------------------------------------------------
# Aufbau / Vorbelegung
# --------------------------------------------------------------------------
def test_dialog_baut_sich_auf(dialog):
    assert dialog.windowTitle() == "Einstellungen"
    assert dialog.transkription_lokal_radio.isChecked()
    assert dialog.nachbearbeitung_lokal_radio.isChecked()


def test_vorbelegung_aus_gespeicherter_konfiguration(qt_widgets, isolierte_konfiguration, schluessel_speicher):
    app_config.save_config(
        {
            **app_config.DEFAULTS,
            "transkription_modus": "api",
            "api_transkription_endpunkt": "https://mein-anbieter.test/v1/audio",
            "nachbearbeitung_modus": "api",
        }
    )
    dialog = qt_widgets(sd.SettingsDialog())

    assert dialog.transkription_api_radio.isChecked()
    assert dialog.api_transkription_endpunkt_edit.text() == "https://mein-anbieter.test/v1/audio"
    assert dialog.nachbearbeitung_api_radio.isChecked()


def test_gespeicherter_schluessel_wird_vorausgefuellt(qt_widgets, isolierte_konfiguration, schluessel_speicher):
    schluessel_speicher["transkription"] = "vorhandener-schluessel"
    dialog = qt_widgets(sd.SettingsDialog())
    assert dialog.api_transkription_schluessel_edit.text() == "vorhandener-schluessel"


def test_aufbau_stuerzt_nicht_ab_wenn_schluesselspeicher_nicht_verfuegbar(
    qt_widgets, isolierte_konfiguration, monkeypatch
):
    # Fehlt auf dem Rechner ein funktionierendes Keyring-Backend (Windows-
    # Anmeldeinformationsverwaltung deaktiviert/nicht erreichbar o.ae.), darf
    # allein das Oeffnen der Einstellungen nicht abstuerzen - der Anwender
    # kann einen Schluessel dann weiterhin von Hand eintragen.
    def werfen(name):
        raise secret_store.SecretStoreUnavailableError("kein Backend verfuegbar")

    monkeypatch.setattr(secret_store, "load_api_key", werfen)

    dialog = qt_widgets(sd.SettingsDialog())

    assert dialog.api_transkription_schluessel_edit.text() == ""
    assert dialog.api_nachbearbeitung_schluessel_edit.text() == ""


# --------------------------------------------------------------------------
# Umschalten lokal/API
# --------------------------------------------------------------------------
def test_umschalten_auf_api_zeigt_api_seite(dialog):
    dialog.transkription_api_radio.setChecked(True)
    assert dialog.transkription_seiten.currentIndex() == 1

    dialog.transkription_lokal_radio.setChecked(True)
    assert dialog.transkription_seiten.currentIndex() == 0


def test_nachbearbeitung_umschalten(dialog):
    dialog.nachbearbeitung_api_radio.setChecked(True)
    assert dialog.nachbearbeitung_seiten.currentIndex() == 1


def test_eigener_schluessel_checkbox_aktiviert_feld(dialog):
    assert not dialog.api_nachbearbeitung_schluessel_edit.isEnabled()
    dialog.api_nachbearbeitung_eigener_schluessel_checkbox.setChecked(True)
    assert dialog.api_nachbearbeitung_schluessel_edit.isEnabled()


# --------------------------------------------------------------------------
# Speichern
# --------------------------------------------------------------------------
def test_speichern_schreibt_konfiguration(dialog, isolierte_konfiguration):
    dialog.transkription_api_radio.setChecked(True)
    dialog.api_transkription_endpunkt_edit.setText("https://neuer-endpunkt.test")
    dialog.api_transkription_modell_edit.setText("modell-neu")

    dialog._speichern_und_schliessen()

    gespeichert = app_config.load_config()
    assert gespeichert["transkription_modus"] == "api"
    assert gespeichert["api_transkription_endpunkt"] == "https://neuer-endpunkt.test"
    assert gespeichert["api_transkription_modell"] == "modell-neu"


def test_speichern_merkt_schluessel_wenn_angehakt(dialog, schluessel_speicher):
    dialog.transkription_api_radio.setChecked(True)
    dialog.api_transkription_schluessel_edit.setText("geheimer-schluessel")
    dialog.api_transkription_merken_checkbox.setChecked(True)

    dialog._speichern_und_schliessen()

    assert schluessel_speicher["transkription"] == "geheimer-schluessel"


def test_speichern_entfernt_schluessel_wenn_nicht_mehr_angehakt(dialog, schluessel_speicher):
    schluessel_speicher["transkription"] = "alter-schluessel"
    dialog.api_transkription_merken_checkbox.setChecked(False)

    dialog._speichern_und_schliessen()

    assert "transkription" not in schluessel_speicher


def test_speichern_merkt_sich_eingegebenen_schluessel_auch_ohne_dauerhaftes_speichern(dialog):
    # Ohne "merken" bleibt der Schluessel fuer den Rest der Sitzung trotzdem
    # nutzbar - siehe 'MainWindow._session_api_keys'.
    dialog.api_transkription_schluessel_edit.setText("nur-diese-sitzung")
    dialog.api_transkription_merken_checkbox.setChecked(False)

    dialog._speichern_und_schliessen()

    assert dialog.eingegebene_schluessel["transkription"] == "nur-diese-sitzung"


def test_speichern_meldet_nicht_verfuegbaren_schluesselspeicher(dialog, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    def werfen(*a, **k):
        raise secret_store.SecretStoreUnavailableError("keyring fehlt")

    monkeypatch.setattr(secret_store, "save_api_key", werfen)
    gewarnt = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: gewarnt.append(a)))

    dialog.api_transkription_schluessel_edit.setText("geheim")
    dialog.api_transkription_merken_checkbox.setChecked(True)
    dialog._speichern_und_schliessen()

    assert gewarnt


# --------------------------------------------------------------------------
# Systemdiagnose
# --------------------------------------------------------------------------
def test_systemdiagnose_oeffnet_dialog(dialog, monkeypatch):
    from protokoll_assistent.gui import dialogs

    monkeypatch.setattr(dialogs.DiagnosticsDialog, "exec", lambda self: None)
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: None)

    dialog._open_diagnostics()  # darf nicht werfen


def test_lokal_einrichten_oeffnet_dialog(dialog, monkeypatch):
    # Die vollstaendige Einrichtung (Downloads, Systemtest, Modellwahl) ist
    # jetzt ein gezielter Schritt aus den Einstellungen heraus, kein
    # Startzwang mehr vor dem Hauptfenster (siehe 'app.py').
    from protokoll_assistent.gui import wizard

    monkeypatch.setattr(wizard.LokalEinrichtungDialog, "exec", lambda self: None)
    monkeypatch.setattr(wizard.InstallPage, "start", lambda self: None)

    dialog._open_lokal_einrichtung()  # darf nicht werfen


def test_systemdiagnose_prueft_den_ausgabeordner(qt_widgets, isolierte_konfiguration, schluessel_speicher, tmp_path, monkeypatch):
    """'DiagnosticsDialog' bekommt seinen ersten Parameter als
    'output_dir': Damit prueft die Diagnose freien Platz und
    Schreibbarkeit. Mit dem Anwendungsordner beantwortet sie die Frage fuer
    das falsche Laufwerk, sobald die Ausgabe woanders liegt."""
    from protokoll_assistent.gui import dialogs

    ausgabe = tmp_path / "ausgabe-auf-anderem-laufwerk"
    ausgabe.mkdir()
    app_config.save_config({**app_config.DEFAULTS, "ausgabeordner": str(ausgabe)})
    dialog = qt_widgets(sd.SettingsDialog())

    uebergeben = []
    monkeypatch.setattr(dialogs.DiagnosticsDialog, "exec", lambda self: None)
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: None)
    monkeypatch.setattr(
        dialogs.DiagnosticsDialog,
        "__init__",
        lambda self, output_dir, parent=None: uebergeben.append(output_dir),
    )

    dialog._open_diagnostics()

    assert uebergeben == [ausgabe]


def test_systemdiagnose_nimmt_ohne_einstellung_den_standardausgabeordner(
    dialog, tmp_path, monkeypatch
):
    from protokoll_assistent.gui import dialogs
    from protokoll_assistent.utils import paths

    standard = tmp_path / "standardausgabe"
    standard.mkdir()
    monkeypatch.setattr(paths, "get_default_output_dir", lambda: standard)

    uebergeben = []
    monkeypatch.setattr(dialogs.DiagnosticsDialog, "exec", lambda self: None)
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: None)
    monkeypatch.setattr(
        dialogs.DiagnosticsDialog,
        "__init__",
        lambda self, output_dir, parent=None: uebergeben.append(output_dir),
    )

    dialog._open_diagnostics()

    assert uebergeben == [standard]
