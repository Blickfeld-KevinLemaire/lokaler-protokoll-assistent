"""Tests fuer die Zusatzdialoge, den Hintergrund-Arbeiter und das Theme."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")


from protokoll_assistent.gui import dialogs, strings, theme  # noqa: E402


# --------------------------------------------------------------------------
# strings / theme
# --------------------------------------------------------------------------
def test_datenschutzhinweis_sagt_lokal():
    assert "lokal" in strings.PRIVACY_NOTICE.lower()
    assert "keine" in strings.PRIVACY_NOTICE.lower()


def test_theme_wird_angewendet(qt_app):
    class _AppAttrappe:
        def __init__(self):
            self.stil = None
            self.qss = None

        def setStyle(self, name):
            self.stil = name

        def setStyleSheet(self, qss):
            self.qss = qss

    attrappe = _AppAttrappe()
    theme.apply_theme(attrappe)

    assert attrappe.stil == "Fusion"
    assert theme.ACCENT in attrappe.qss
    assert "QProgressBar" in attrappe.qss


# --------------------------------------------------------------------------
# render_check_item
# --------------------------------------------------------------------------
class _Pruefung:
    def __init__(self, ok, critical=False, detail="Detailtext", label="Bezeichnung"):
        self.ok = ok
        self.critical = critical
        self.detail = detail
        self.label = label


@pytest.mark.parametrize(
    ("pruefung", "erwartetes_symbol"),
    [
        (_Pruefung(ok=True), "OK"),
        (_Pruefung(ok=False, critical=True), "FEHLT"),
        (_Pruefung(ok=False, critical=False), "HINWEIS"),
    ],
)
def test_render_check_item_symbole(qt_app, pruefung, erwartetes_symbol):
    item = dialogs.render_check_item(pruefung)
    assert item.text().startswith(f"[{erwartetes_symbol}]")
    assert "Detailtext" in item.text()


def test_render_check_item_faerbt_unterschiedlich(qt_app):
    ok = dialogs.render_check_item(_Pruefung(ok=True)).foreground().color().name()
    kritisch = dialogs.render_check_item(
        _Pruefung(ok=False, critical=True)
    ).foreground().color().name()
    hinweis = dialogs.render_check_item(
        _Pruefung(ok=False, critical=False)
    ).foreground().color().name()

    assert len({ok, kritisch, hinweis}) == 3


# --------------------------------------------------------------------------
# DiagnosticsRunner / DiagnosticsDialog
# --------------------------------------------------------------------------
def test_diagnostics_runner_meldet_ergebnisse(qt_app, tmp_path, monkeypatch):
    from protokoll_assistent.utils import diagnostics

    erwartet = [_Pruefung(ok=True)]
    monkeypatch.setattr(diagnostics, "run_diagnostics", lambda ordner, on_check_started: erwartet)

    runner = dialogs.DiagnosticsRunner(tmp_path)
    empfangen = []
    runner.finished_with_results.connect(empfangen.append)

    runner.run()  # direkt, ohne echten Thread

    assert empfangen == [erwartet]


def test_diagnostics_runner_meldet_laufende_pruefung(qt_app, tmp_path, monkeypatch):
    from protokoll_assistent.utils import diagnostics

    def fake_run_diagnostics(ordner, on_check_started):
        on_check_started("Python-Version")
        on_check_started("FFmpeg")
        return [_Pruefung(ok=True)]

    monkeypatch.setattr(diagnostics, "run_diagnostics", fake_run_diagnostics)

    runner = dialogs.DiagnosticsRunner(tmp_path)
    gemeldet = []
    runner.check_started.connect(gemeldet.append)

    runner.run()

    assert gemeldet == ["Python-Version", "FFmpeg"]


def test_diagnostics_dialog_zeigt_ergebnisse(qt_app, qt_widgets, tmp_path, monkeypatch):
    # Der Dialog startet sonst einen echten Hintergrund-Thread.
    gestartet = []
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: gestartet.append(True))

    dialog = qt_widgets(dialogs.DiagnosticsDialog(tmp_path))
    assert gestartet == [True]
    assert "läuft" in dialog.status_label.text()

    dialog._show_results(
        [
            _Pruefung(ok=True, label="Python"),
            _Pruefung(ok=False, critical=True, label="CUDA"),
        ]
    )

    assert "abgeschlossen" in dialog.status_label.text()
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 0).text() == "Python"
    assert dialog.table.item(1, 1).text().startswith("[FEHLT]")


def test_diagnostics_dialog_zeigt_laufende_pruefung(qt_app, qt_widgets, tmp_path, monkeypatch):
    # Ohne diese laufende Rueckmeldung stand waehrend der gesamten Pruefung
    # nur ein einziger, unveraenderter "laeuft ..."-Text da -- das sah wie
    # ein Haengenbleiben aus, obwohl im Hintergrund gearbeitet wurde.
    monkeypatch.setattr(dialogs.DiagnosticsRunner, "start", lambda self: None)

    dialog = qt_widgets(dialogs.DiagnosticsDialog(tmp_path))
    dialog._on_check_started("pyannote.audio")

    assert "pyannote.audio" in dialog.status_label.text()


def test_show_error_nutzt_messagebox(qt_app, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        dialogs.QMessageBox, "critical", lambda parent, titel, text: aufrufe.append((titel, text))
    )
    dialogs.show_error(None, "Titel", "Meldung")
    assert aufrufe == [("Titel", "Meldung")]




# --------------------------------------------------------------------------
# SprecherprofileDialog
# --------------------------------------------------------------------------
def test_profildialog_listet_benennt_um_und_loescht(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from protokoll_assistent.services import sprecherprofil_service as sp

    sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    dialog = dialogs.SprecherprofileDialog(ordner=tmp_path)
    assert dialog.liste.count() == 1 and "Anna" in dialog.liste.item(0).text()

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Anna Muster", True)))
    dialog._umbenennen()
    assert [p["name"] for p in sp.lade_profile(tmp_path)] == ["Anna Muster"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    dialog._loeschen()
    assert len(sp.lade_profile(tmp_path)) == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    dialog._loeschen()
    assert sp.lade_profile(tmp_path) == []
    assert not dialog.loeschen_button.isEnabled()
    dialog._umbenennen()  # ohne Auswahl: darf nicht werfen
    dialog._loeschen()


def test_profildialog_meldet_umbenennfehler(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from protokoll_assistent.services import sprecherprofil_service as sp

    sp.profil_speichern("Anna", [1.0, 0.0], tmp_path)
    sp.profil_speichern("Ben", [0.0, 1.0], tmp_path)
    dialog = dialogs.SprecherprofileDialog(ordner=tmp_path)
    fehler = []
    monkeypatch.setattr(dialogs, "show_error", lambda parent, titel, text: fehler.append(titel))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Ben", True)))
    dialog.liste.setCurrentRow(0)
    dialog._umbenennen()
    assert fehler == ["Umbenennen nicht möglich"]
