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
    monkeypatch.setattr(diagnostics, "run_diagnostics", lambda ordner: erwartet)

    runner = dialogs.DiagnosticsRunner(tmp_path)
    empfangen = []
    runner.finished_with_results.connect(empfangen.append)

    runner.run()  # direkt, ohne echten Thread

    assert empfangen == [erwartet]


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


def test_show_error_nutzt_messagebox(qt_app, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        dialogs.QMessageBox, "critical", lambda parent, titel, text: aufrufe.append((titel, text))
    )
    dialogs.show_error(None, "Titel", "Meldung")
    assert aufrufe == [("Titel", "Meldung")]


