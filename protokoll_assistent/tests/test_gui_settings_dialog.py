"""Tests fuer 'gui/settings_dialog.py'.

'secret_store' wird durch einen einfachen In-Memory-Speicher ersetzt - kein
Test spricht die echte Windows-Anmeldeinformationsverwaltung an (dafuer
gibt es 'test_secret_store.py'). Die Systemprompt-Vorlagenverwaltung liegt
inline im Hauptfenster (siehe 'test_gui_main_window.py') und wird hier
nicht getestet."""

from __future__ import annotations

from typing import ClassVar

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent.gui import ollama_modellwahl as omw  # noqa: E402
from protokoll_assistent.gui import settings_dialog as sd  # noqa: E402
from protokoll_assistent.services import ollama_service, secret_store  # noqa: E402
from protokoll_assistent.utils import app_config  # noqa: E402


@pytest.fixture(autouse=True)
def ollama_nicht_erreichbar(monkeypatch):
    """Kein Test fragt einen echten Ollama-Dienst: Standard ist "nicht erreichbar"."""

    def unerreichbar(base_url=ollama_service.OLLAMA_BASE_URL, timeout=5):
        raise ollama_service.OllamaError("kein Dienst im Test")

    monkeypatch.setattr(ollama_service, "list_models", unerreichbar)


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
    monkeypatch.setattr(wizard.RechnerAnalysePage, "start", lambda self: None)
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


# --------------------------------------------------------------------------
# Schluessel: Meldung nur, wenn der Anwender wirklich merken will
# --------------------------------------------------------------------------
def _speicher_nicht_verfuegbar(monkeypatch):
    def werfen(*a, **k):
        raise secret_store.SecretStoreUnavailableError("keyring fehlt")

    for name in ("save_api_key", "load_api_key", "delete_api_key"):
        monkeypatch.setattr(secret_store, name, werfen)


def test_ohne_merken_keine_meldung_auch_wenn_keyring_fehlt(qt_widgets, isolierte_konfiguration, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _speicher_nicht_verfuegbar(monkeypatch)
    gewarnt = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: gewarnt.append(a)))
    dialog = qt_widgets(sd.SettingsDialog())  # Aufbau darf ebenfalls nichts melden
    dialog.api_transkription_schluessel_edit.setText("nur-fuer-diese-sitzung")
    dialog.api_transkription_merken_checkbox.setChecked(False)
    dialog.api_nachbearbeitung_merken_checkbox.setChecked(False)

    dialog._speichern_und_schliessen()

    assert gewarnt == []
    assert dialog.eingegebene_schluessel["transkription"] == "nur-fuer-diese-sitzung"


def test_mit_merken_und_fehlendem_keyring_gibt_es_die_meldung(qt_widgets, isolierte_konfiguration, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _speicher_nicht_verfuegbar(monkeypatch)
    gewarnt = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: gewarnt.append(a)))
    dialog = qt_widgets(sd.SettingsDialog())
    dialog.api_transkription_schluessel_edit.setText("geheim")
    dialog.api_transkription_merken_checkbox.setChecked(True)

    dialog._speichern_und_schliessen()

    assert len(gewarnt) == 1


def test_mit_merken_aber_ohne_eingegebenen_schluessel_keine_meldung(qt_widgets, isolierte_konfiguration, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _speicher_nicht_verfuegbar(monkeypatch)
    gewarnt = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: gewarnt.append(a)))
    dialog = qt_widgets(sd.SettingsDialog())
    dialog.api_transkription_merken_checkbox.setChecked(True)

    dialog._speichern_und_schliessen()

    assert gewarnt == []


# --------------------------------------------------------------------------
# Ollama-Modell: Auswahl, Status, Herunterladen
# --------------------------------------------------------------------------
def test_ollama_standard_ist_vorausgewaehlt(dialog):
    assert dialog.ollama_modell() == ollama_service.DEFAULT_MODEL
    ids = [dialog.ollama_wahl.combo.itemData(i) for i in range(dialog.ollama_wahl.combo.count())]
    assert ids[: len(ollama_service.OLLAMA_MODELLE)] == [o.id for o in ollama_service.OLLAMA_MODELLE]
    assert ids[-1] == omw.EIGENES_MODELL
    assert not dialog.ollama_wahl.edit.isVisibleTo(dialog)
    assert dialog.ollama_wahl.hinweis_label.text()  # Beschreibung des Standardmodells


def test_ollama_andere_auswahl_wird_gespeichert(dialog):
    dialog.ollama_wahl.combo.setCurrentIndex(dialog.ollama_wahl.combo.findData("qwen3:4b"))
    assert dialog.ollama_modell() == "qwen3:4b"
    dialog._speichern_und_schliessen()
    assert app_config.load_config()["ollama_modell"] == "qwen3:4b"


def test_ollama_eigener_name_wird_vorbelegt_und_gespeichert(qt_widgets, isolierte_konfiguration, schluessel_speicher):
    app_config.update_config(ollama_modell="phi4")
    dialog = qt_widgets(sd.SettingsDialog())
    assert dialog.ollama_wahl.combo.currentData() == omw.EIGENES_MODELL
    assert dialog.ollama_wahl.edit.text() == "phi4"
    assert dialog.ollama_modell() == "phi4"
    assert dialog.ollama_wahl.hinweis_label.text() == ""

    dialog.ollama_wahl.edit.setText("  qwen3:30b ")
    dialog._speichern_und_schliessen()
    assert app_config.load_config()["ollama_modell"] == "qwen3:30b"


def test_ollama_leerer_eigener_name_faellt_auf_den_standard_zurueck(dialog):
    dialog.ollama_wahl.combo.setCurrentIndex(dialog.ollama_wahl.combo.findData(omw.EIGENES_MODELL))
    dialog.ollama_wahl.edit.setText("   ")
    dialog.ollama_wahl.aktualisieren()
    assert "Modellnamen" in dialog.ollama_wahl.status_label.text()
    assert not dialog.ollama_wahl.download_button.isEnabled()
    dialog._speichern_und_schliessen()
    assert app_config.load_config()["ollama_modell"] == ollama_service.DEFAULT_MODEL


def test_ollama_status_nicht_erreichbar_installiert_und_fehlend(dialog, monkeypatch):
    dialog.ollama_wahl.aktualisieren()
    assert "nicht erreichbar" in dialog.ollama_wahl.status_label.text()
    assert dialog.ollama_wahl.download_button.isEnabled()  # ein Versuch bleibt moeglich

    monkeypatch.setattr(ollama_service, "list_models", lambda base_url=None, timeout=5: ["qwen3:8b", "gemma3:4b"])
    dialog.ollama_wahl.aktualisieren()
    assert "installiert" in dialog.ollama_wahl.status_label.text() and "✓" in dialog.ollama_wahl.status_label.text()
    assert not dialog.ollama_wahl.download_button.isEnabled()

    dialog.ollama_wahl.combo.setCurrentIndex(dialog.ollama_wahl.combo.findData("qwen3:14b"))
    assert "noch nicht installiert" in dialog.ollama_wahl.status_label.text()
    assert "gemma3:4b" in dialog.ollama_wahl.status_label.text()  # bereits Vorhandenes wird genannt
    assert dialog.ollama_wahl.download_button.isEnabled()


class _PullArbeiterAttrappe:
    instanzen: ClassVar[list] = []

    class _Signal:
        def __init__(self):
            self.empfaenger = []

        def connect(self, funktion):
            self.empfaenger.append(funktion)

        def emit(self, *args):
            for funktion in self.empfaenger:
                funktion(*args)

    def __init__(self, modell, parent=None):
        self.modell = modell
        self.gestartet = False
        self.fortschritt = self._Signal()
        self.fertig = self._Signal()
        self.fehlgeschlagen = self._Signal()
        _PullArbeiterAttrappe.instanzen.append(self)

    def start(self):
        self.gestartet = True


def test_ollama_herunterladen_zeigt_fortschritt_und_aktualisiert_den_status(dialog, monkeypatch):
    _PullArbeiterAttrappe.instanzen.clear()
    monkeypatch.setattr(omw, "OllamaPullWorker", _PullArbeiterAttrappe)
    dialog.ollama_wahl.combo.setCurrentIndex(dialog.ollama_wahl.combo.findData("qwen3:4b"))

    dialog.ollama_wahl.herunterladen()
    arbeiter = _PullArbeiterAttrappe.instanzen[-1]
    assert arbeiter.gestartet and arbeiter.modell == "qwen3:4b"
    assert not dialog.ollama_wahl.download_button.isEnabled()
    assert not dialog.ollama_wahl.combo.isEnabled()  # waehrend des Downloads gesperrt
    dialog.ollama_wahl.herunterladen()  # zweiter Klick: darf keinen zweiten Arbeiter starten
    assert len(_PullArbeiterAttrappe.instanzen) == 1

    arbeiter.fortschritt.emit("pulling abc", 500_000_000, 2_000_000_000)
    assert dialog.ollama_wahl.fortschritt.value() == 25
    assert "0.5 von 2.0 GB" in dialog.ollama_wahl.status_label.text()
    arbeiter.fortschritt.emit("verifying sha256 digest", 0, 0)
    assert dialog.ollama_wahl.status_label.text() == "verifying sha256 digest"

    monkeypatch.setattr(ollama_service, "list_models", lambda base_url=None, timeout=5: ["qwen3:4b"])
    arbeiter.fertig.emit("qwen3:4b")
    assert dialog.ollama_wahl.combo.isEnabled()
    assert "✓" in dialog.ollama_wahl.status_label.text()


def test_ollama_download_fehler_wird_angezeigt_und_erneuter_versuch_ist_moeglich(dialog, monkeypatch):
    _PullArbeiterAttrappe.instanzen.clear()
    monkeypatch.setattr(omw, "OllamaPullWorker", _PullArbeiterAttrappe)
    dialog.ollama_wahl.herunterladen()
    _PullArbeiterAttrappe.instanzen[-1].fehlgeschlagen.emit("qwen3:8b", "kein Speicherplatz")
    assert "kein Speicherplatz" in dialog.ollama_wahl.status_label.text()
    assert dialog.ollama_wahl.download_button.isEnabled()
    assert dialog.ollama_wahl.combo.isEnabled()


# --------------------------------------------------------------------------
# Reiter "Chatbot"
# --------------------------------------------------------------------------
def test_chatbot_reiter_ist_vorhanden_und_vorbelegt(dialog):
    from PySide6.QtWidgets import QTabWidget

    tabs = dialog.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Transkription", "Nachbearbeitung", "Chatbot"]
    assert dialog.chatbot_lokal_radio.isChecked()
    assert dialog.chatbot_chat_wahl.modell() == ollama_service.DEFAULT_MODEL
    assert dialog.chatbot_embedding_wahl.modell() == "bge-m3"
    ids = [dialog.chatbot_embedding_wahl.combo.itemData(i) for i in range(dialog.chatbot_embedding_wahl.combo.count())]
    assert ids[: len(ollama_service.OLLAMA_EMBEDDING_MODELLE)] == [o.id for o in ollama_service.OLLAMA_EMBEDDING_MODELLE]
    assert dialog.chatbot_seiten.currentIndex() == 0


def test_chatbot_umschalten_auf_api_zeigt_die_api_seite_und_speichert(dialog, schluessel_speicher):
    dialog.chatbot_api_radio.setChecked(True)
    assert dialog.chatbot_seiten.currentIndex() == 1
    dialog.chatbot_chat_wahl.combo.setCurrentIndex(dialog.chatbot_chat_wahl.combo.findData("qwen3:4b"))
    dialog.chatbot_embedding_wahl.combo.setCurrentIndex(dialog.chatbot_embedding_wahl.combo.findData("nomic-embed-text"))
    dialog.chatbot_api_endpunkt_edit.setText(" https://api.test/chat ")
    dialog.chatbot_api_modell_edit.setText("modell-x")
    dialog.chatbot_api_embedding_endpunkt_edit.setText("https://api.test/emb")
    dialog.chatbot_api_embedding_modell_edit.setText("emb-x")
    dialog.chatbot_api_eigener_schluessel_checkbox.setChecked(True)
    dialog.chatbot_api_schluessel_edit.setText("chat-geheim")
    dialog.chatbot_api_merken_checkbox.setChecked(True)

    dialog._speichern_und_schliessen()

    gespeichert = app_config.load_config()
    assert gespeichert["chatbot_modus"] == "api"
    assert gespeichert["chatbot_ollama_modell"] == "qwen3:4b"
    assert gespeichert["chatbot_embedding_modell"] == "nomic-embed-text"
    assert gespeichert["chatbot_api_endpunkt"] == "https://api.test/chat"
    assert gespeichert["chatbot_api_modell"] == "modell-x"
    assert gespeichert["chatbot_api_embedding_endpunkt"] == "https://api.test/emb"
    assert gespeichert["chatbot_api_embedding_modell"] == "emb-x"
    assert gespeichert["chatbot_api_eigener_schluessel"] is True
    assert schluessel_speicher["chatbot"] == "chat-geheim"
    assert dialog.eingegebene_schluessel["chatbot"] == "chat-geheim"


def test_chatbot_gespeicherte_werte_werden_vorbelegt(qt_widgets, isolierte_konfiguration, schluessel_speicher):
    schluessel_speicher["chatbot"] = "alt"
    app_config.update_config(chatbot_modus="api", chatbot_embedding_modell="eigenes-embedding", chatbot_api_eigener_schluessel=True)
    dialog = qt_widgets(sd.SettingsDialog())
    assert dialog.chatbot_api_radio.isChecked()
    assert dialog.chatbot_embedding_wahl.combo.currentData() == omw.EIGENES_MODELL
    assert dialog.chatbot_embedding_wahl.modell() == "eigenes-embedding"
    assert dialog.chatbot_api_schluessel_edit.text() == "alt"
    assert dialog.chatbot_api_schluessel_edit.isEnabled()


def test_chatbot_leere_modellnamen_fallen_auf_die_standards_zurueck(dialog):
    dialog.chatbot_embedding_wahl.combo.setCurrentIndex(dialog.chatbot_embedding_wahl.combo.findData(omw.EIGENES_MODELL))
    dialog.chatbot_embedding_wahl.edit.setText("  ")
    dialog._speichern_und_schliessen()
    assert app_config.load_config()["chatbot_embedding_modell"] == "bge-m3"


# --------------------------------------------------------------------------
# API-Anbieter: Auswahl statt Voreinstellung
# --------------------------------------------------------------------------
def test_ab_werk_ist_kein_anbieter_gewaehlt_und_die_felder_sind_leer(dialog):
    for wahl in (
        dialog.api_transkription_anbieter_wahl,
        dialog.api_nachbearbeitung_anbieter_wahl,
        dialog.chatbot_api_anbieter_wahl,
    ):
        assert wahl.anbieter_id() == ""
        assert wahl.combo.currentText() == "Bitte Anbieter wählen …"
    assert dialog.api_transkription_endpunkt_edit.text() == ""
    assert dialog.api_transkription_modell_edit.text() == ""
    assert dialog.api_transkription_anbieter_edit.text() == ""
    assert dialog.api_nachbearbeitung_endpunkt_edit.text() == ""
    assert dialog.chatbot_api_endpunkt_edit.text() == ""
    assert dialog.chatbot_api_embedding_endpunkt_edit.text() == ""


def test_transkription_anbieter_waehlen_fuellt_adresse_und_modell(dialog):
    wahl = dialog.api_transkription_anbieter_wahl
    wahl.combo.setCurrentIndex(wahl.combo.findData("openrouter"))
    assert dialog.api_transkription_endpunkt_edit.text() == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert dialog.api_transkription_modell_edit.text() == "microsoft/mai-transcribe-2"
    assert dialog.api_transkription_anbieter_edit.text() == "azure"  # Sprechertrennung nur bei OpenRouter


def test_transkription_bietet_nur_openrouter_und_eigenen_endpunkt(dialog):
    """Kein Dateiupload: Es gibt nur Anbieter, die das Audio im API-Aufruf selbst nehmen."""
    wahl = dialog.api_transkription_anbieter_wahl
    angebotene = [wahl.combo.itemData(i) for i in range(wahl.combo.count())]
    assert angebotene == ["", "openrouter", "eigener"]


def test_nachbearbeitung_anbieter_waehlen_fuellt_chat_adresse_und_modell(dialog):
    wahl = dialog.api_nachbearbeitung_anbieter_wahl
    wahl.combo.setCurrentIndex(wahl.combo.findData("anthropic"))
    assert dialog.api_nachbearbeitung_endpunkt_edit.text() == "https://api.anthropic.com/v1/chat/completions"
    assert dialog.api_nachbearbeitung_modell_edit.text() == "claude-sonnet-5-5"


def test_chatbot_anbieter_waehlen_fuellt_chat_und_einbettung(dialog):
    wahl = dialog.chatbot_api_anbieter_wahl
    angebotene = {wahl.combo.itemData(i) for i in range(wahl.combo.count())}
    assert "ionos" in angebotene
    assert not {"anthropic", "groq"} & angebotene  # ohne Einbettungen taugen sie hier nicht

    wahl.combo.setCurrentIndex(wahl.combo.findData("ionos"))
    assert dialog.chatbot_api_endpunkt_edit.text() == "https://openai.inference.de-txl.ionos.com/v1/chat/completions"
    assert dialog.chatbot_api_embedding_endpunkt_edit.text() == "https://openai.inference.de-txl.ionos.com/v1/embeddings"
    assert dialog.chatbot_api_modell_edit.text() and dialog.chatbot_api_embedding_modell_edit.text() == "BAAI/bge-m3"


def test_eigener_endpunkt_laesst_die_felder_unveraendert(dialog):
    dialog.api_nachbearbeitung_endpunkt_edit.setText("https://mein.test/v1/chat/completions")
    wahl = dialog.api_nachbearbeitung_anbieter_wahl
    wahl.combo.setCurrentIndex(wahl.combo.findData("eigener"))
    assert dialog.api_nachbearbeitung_endpunkt_edit.text() == "https://mein.test/v1/chat/completions"


def test_anbieterwahl_wird_gespeichert(dialog):
    wahl = dialog.api_nachbearbeitung_anbieter_wahl
    wahl.combo.setCurrentIndex(wahl.combo.findData("openai"))
    dialog.api_transkription_anbieter_wahl.combo.setCurrentIndex(
        dialog.api_transkription_anbieter_wahl.combo.findData("openrouter")
    )
    dialog.chatbot_api_anbieter_wahl.combo.setCurrentIndex(dialog.chatbot_api_anbieter_wahl.combo.findData("google"))

    dialog._speichern_und_schliessen()

    gespeichert = app_config.load_config()
    assert gespeichert["api_nachbearbeitung_voreinstellung"] == "openai"
    assert gespeichert["api_nachbearbeitung_endpunkt"] == "https://api.openai.com/v1/chat/completions"
    assert gespeichert["api_nachbearbeitung_modell"] == "gpt-4o-mini"
    assert gespeichert["api_transkription_voreinstellung"] == "openrouter"
    assert gespeichert["api_transkription_endpunkt"] == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert gespeichert["chatbot_api_voreinstellung"] == "google"


def test_gespeicherter_anbieter_wird_beim_oeffnen_gewaehlt_ohne_felder_zu_ueberschreiben(
    qt_widgets, isolierte_konfiguration, schluessel_speicher
):
    app_config.update_config(
        api_nachbearbeitung_voreinstellung="openai",
        api_nachbearbeitung_endpunkt="https://api.openai.com/v1/chat/completions",
        api_nachbearbeitung_modell="gpt-4.1",  # vom Anwender angepasst
    )
    dialog = qt_widgets(sd.SettingsDialog())
    assert dialog.api_nachbearbeitung_anbieter_wahl.anbieter_id() == "openai"
    assert dialog.api_nachbearbeitung_modell_edit.text() == "gpt-4.1"


def test_alte_einstellung_ohne_gespeicherte_wahl_wird_an_der_adresse_erkannt(
    qt_widgets, isolierte_konfiguration, schluessel_speicher
):
    app_config.update_config(
        api_transkription_endpunkt="https://openrouter.ai/api/v1/audio/transcriptions",
        api_nachbearbeitung_endpunkt="https://mein.test/v1/chat/completions",
    )
    dialog = qt_widgets(sd.SettingsDialog())
    assert dialog.api_transkription_anbieter_wahl.anbieter_id() == "openrouter"
    assert dialog.api_nachbearbeitung_anbieter_wahl.anbieter_id() == "eigener"
    assert dialog.chatbot_api_anbieter_wahl.anbieter_id() == ""
