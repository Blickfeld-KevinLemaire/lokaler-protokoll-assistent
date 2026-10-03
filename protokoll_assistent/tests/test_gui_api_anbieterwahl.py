"""Tests fuer 'gui/api_anbieterwahl.py'."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 ist nicht installiert.")

from protokoll_assistent.gui import api_anbieterwahl as aw  # noqa: E402
from protokoll_assistent.services import api_anbieter  # noqa: E402


def test_voreinstellung_ermitteln():
    assert aw.voreinstellung_ermitteln("mistral", "https://egal") == "mistral"  # gespeicherte Wahl zaehlt
    assert aw.voreinstellung_ermitteln("", "") == ""
    assert aw.voreinstellung_ermitteln(None, None) == ""
    assert aw.voreinstellung_ermitteln("", "https://api.openai.com/v1/chat/completions") == "openai"
    assert aw.voreinstellung_ermitteln("", "https://mein.test/v1") == "eigener"


def test_anbieter_passt_je_faehigkeit():
    anthropic = api_anbieter.finde_anbieter("anthropic")
    groq = api_anbieter.finde_anbieter("groq")
    mistral = api_anbieter.finde_anbieter("mistral")
    assert aw.anbieter_passt(anthropic, aw.FAEHIGKEIT_CHAT)
    assert not aw.anbieter_passt(anthropic, aw.FAEHIGKEIT_CHATBOT)
    assert not aw.anbieter_passt(anthropic, aw.FAEHIGKEIT_TRANSKRIPTION)
    assert aw.anbieter_passt(groq, aw.FAEHIGKEIT_TRANSKRIPTION) and not aw.anbieter_passt(groq, aw.FAEHIGKEIT_CHATBOT)
    assert all(aw.anbieter_passt(mistral, f) for f in (aw.FAEHIGKEIT_CHAT, aw.FAEHIGKEIT_CHATBOT, aw.FAEHIGKEIT_TRANSKRIPTION))


def test_beschreibung_nennt_standort_hinweis_und_links():
    html = aw.beschreibung_html(api_anbieter.finde_anbieter("ionos"))
    assert "IONOS AI Model Hub" in html and "Deutschland" in html
    assert 'href="https://docs.ionos.com' in html and "API-Schlüssel anlegen" in html and "Dokumentation" in html
    assert "Bietet: Chat, Einbettungen" in html and "Transkription" not in html.split("Bietet:")[1].split("<br>")[0]
    azure = aw.beschreibung_html(api_anbieter.finde_anbieter("azure"))
    assert "RESSOURCENNAME" in azure and "Deployment" in azure


def test_wahl_startet_ohne_vorauswahl(qt_widgets):
    wahl = qt_widgets(aw.ApiAnbieterWahl(aw.FAEHIGKEIT_CHAT))
    assert wahl.anbieter_id() == "" and wahl.anbieter() is None
    assert "noch kein Anbieter" in wahl.info_label.text()
    assert wahl.combo.itemData(0) == "" and wahl.combo.itemData(wahl.combo.count() - 1) == "eigener"


def test_setze_loest_kein_signal_aus_aber_die_auswahl_schon(qt_widgets):
    wahl = qt_widgets(aw.ApiAnbieterWahl(aw.FAEHIGKEIT_CHAT))
    gemeldet = []
    wahl.anbieter_gewaehlt.connect(gemeldet.append)

    wahl.setze("openai")
    assert wahl.anbieter_id() == "openai" and gemeldet == []
    assert wahl.info_label.openExternalLinks() and "OpenAI" in wahl.info_label.text()

    wahl.combo.setCurrentIndex(wahl.combo.findData("mistral"))
    assert [a.id for a in gemeldet] == ["mistral"]

    wahl.combo.setCurrentIndex(wahl.combo.findData("eigener"))
    assert gemeldet[-1] is None and "Eigener Endpunkt" in wahl.info_label.text()

    wahl.setze("gibt-es-nicht")  # unbekannt: zurueck auf "nichts gewaehlt"
    assert wahl.anbieter_id() == ""
