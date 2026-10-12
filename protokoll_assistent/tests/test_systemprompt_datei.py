"""Ein frueher mitgelieferter Standard-Systemprompt (feste JSON-Struktur)
wird beim Start durch den neuen Standard ersetzt -- aber nur, wenn ihn der
Anwender nie veraendert hat.

Hintergrund: 'ensure_system_prompt_file_exists' legte die Prompt-Datei bisher
nur an, wenn sie fehlte. Wer schon eine hatte, behielt den alten Prompt, und
seit die Nachbearbeitung nur noch dem Systemprompt folgt, schrieb das Modell
dann JSON ins Protokoll.

Alle Tests arbeiten in 'tmp_path'; der echte Einstellungsordner bleibt
unberuehrt (CLAUDE.md, Regel 5)."""

from __future__ import annotations

import pytest

from protokoll_assistent.utils import paths

# Wortgleich der mitgelieferte Standard aus 62736dd (zuvor ebenso in
# lokale_windows_app/einstellungen/).
ALTER_STANDARD_1 = '''/no_think

Du bist ein genauer deutschsprachiger Protokoll-Assistent.

Analysiere ausschließlich das bereitgestellte Transkript beziehungsweise die bereitgestellten Teilanalysen. Erfinde keine Informationen und ergänze kein eigenes Fachwissen.

Erhalte Sprecherbezeichnungen und Quellenzeitstempel. Formuliere knapp, sachlich und grammatikalisch korrekt.

Regeln:

1. Jeder Inhalt muss durch das Transkript belegt sein.
2. Fasse inhaltlich zusammengehörende Aussagen zusammen.
3. Wiederhole denselben Sachverhalt nicht mehrfach.
4. Trenne Entscheidungen, Aufgaben, Termine und offene Fragen.
5. Eine Aufgabe benötigt eine ausdrücklich genannte Handlung.
6. Weise eine Aufgabe nur dann einer Person zu, wenn dies eindeutig gesagt wurde.
7. Erfinde keine Verantwortlichen und keine Fristen.
8. Verständnis-, Prüfungs- oder Übungsfragen sind keine offenen organisatorischen Fragen.
9. Korrigiere eindeutige Transkriptionsfehler nur bei zweifelsfreier Bedeutung.
10. Kennzeichne unklare oder widersprüchliche Stellen als unsicher.
11. Bewahre globale Zeitstempel als Quellenangabe.
12. Gib ausschließlich gültiges JSON in der verlangten Struktur aus.

JSON-Struktur:

{
  "titel": "",
  "kurzzusammenfassung": "",
  "teilnehmende_oder_sprecher": [],
  "themen": [
    {
      "thema": "",
      "kernaussagen": [],
      "sprecher": [],
      "zeitraum": "",
      "quellen": []
    }
  ],
  "entscheidungen": [
    {
      "entscheidung": "",
      "sprecher": "",
      "zeitpunkt": "",
      "quelle": ""
    }
  ],
  "aufgaben": [
    {
      "aufgabe": "",
      "verantwortlich": "",
      "frist": "",
      "quelle": ""
    }
  ],
  "termine": [],
  "offene_fragen": [],
  "wichtige_fakten": [],
  "unsichere_transkriptstellen": [],
  "quellenhinweise": []
}
'''

# Der Standard aus 96674cf: Regel 5 ergaenzt, Regel 13 neu.
ALTER_STANDARD_2 = ALTER_STANDARD_1.replace(
    "5. Eine Aufgabe benötigt eine ausdrücklich genannte Handlung.\n",
    "5. Eine Aufgabe benötigt eine ausdrücklich genannte Handlung. Forderungen, Meinungen und "
    "Vorschläge sind keine Aufgaben. Gibt es keine Aufgaben, etwa bei Vorträgen, Diskussionen oder "
    'Interviews, bleibt "aufgaben" leer: [].\n',
).replace(
    "12. Gib ausschließlich gültiges JSON in der verlangten Struktur aus.\n",
    "12. Gib ausschließlich gültiges JSON in der verlangten Struktur aus.\n"
    '13. "termine", "offene_fragen", "wichtige_fakten", "unsichere_transkriptstellen" und '
    '"quellenhinweise" enthalten jeweils kurze Sätze als Text, keine Objekte.\n',
)


@pytest.fixture
def einstellungen(monkeypatch, tmp_path):
    ordner = tmp_path / "einstellungen"
    ordner.mkdir()
    monkeypatch.setattr(paths, "get_settings_dir", lambda: ordner)
    return ordner


def test_beide_alten_standards_sind_bekannt():
    assert ALTER_STANDARD_2 != ALTER_STANDARD_1
    assert "13. " in ALTER_STANDARD_2 and "Forderungen, Meinungen" in ALTER_STANDARD_2
    assert paths.ist_frueherer_standard_systemprompt(ALTER_STANDARD_1)
    assert paths.ist_frueherer_standard_systemprompt(ALTER_STANDARD_2)
    assert not paths.ist_frueherer_standard_systemprompt("")
    assert not paths.ist_frueherer_standard_systemprompt("Liste nur die Termine auf.")


@pytest.mark.parametrize("alter_standard", [ALTER_STANDARD_1, ALTER_STANDARD_2], ids=["62736dd", "96674cf"])
def test_unveraenderter_alter_standard_wird_ersetzt(einstellungen, alter_standard):
    (einstellungen / "systemprompt_protokoll.default.txt").write_text("", encoding="utf-8")
    datei = einstellungen / "systemprompt_protokoll.txt"
    datei.write_text(alter_standard, encoding="utf-8")

    paths.ensure_system_prompt_file_exists()

    assert datei.read_text(encoding="utf-8") == ""


def test_alter_standard_mit_windows_zeilenenden_und_bom_wird_erkannt(einstellungen):
    (einstellungen / "systemprompt_protokoll.default.txt").write_text("NEUER STANDARD", encoding="utf-8")
    datei = einstellungen / "systemprompt_protokoll.txt"
    datei.write_bytes(("\ufeff" + ALTER_STANDARD_2.replace("\n", "  \r\n")).encode("utf-8"))

    paths.ensure_system_prompt_file_exists()

    assert datei.read_text(encoding="utf-8") == "NEUER STANDARD"


def test_bearbeiteter_prompt_bleibt_unangetastet(einstellungen):
    (einstellungen / "systemprompt_protokoll.default.txt").write_text("", encoding="utf-8")
    datei = einstellungen / "systemprompt_protokoll.txt"
    eigener = ALTER_STANDARD_2.replace("Formuliere knapp", "Formuliere ausfuehrlich")
    datei.write_text(eigener, encoding="utf-8")

    paths.ensure_system_prompt_file_exists()

    assert datei.read_text(encoding="utf-8") == eigener


def test_eigener_kurzer_prompt_bleibt_unangetastet(einstellungen):
    (einstellungen / "systemprompt_protokoll.default.txt").write_text("", encoding="utf-8")
    datei = einstellungen / "systemprompt_protokoll.txt"
    datei.write_text("Liste nur die ToDos auf.", encoding="utf-8")

    paths.ensure_system_prompt_file_exists()

    assert datei.read_text(encoding="utf-8") == "Liste nur die ToDos auf."


def test_fehlende_datei_wird_aus_dem_standard_angelegt(einstellungen):
    (einstellungen / "systemprompt_protokoll.default.txt").write_text("STANDARD", encoding="utf-8")

    paths.ensure_system_prompt_file_exists()

    assert (einstellungen / "systemprompt_protokoll.txt").read_text(encoding="utf-8") == "STANDARD"


def test_veraltete_standarddatei_wird_nicht_uebernommen(einstellungen):
    """Liegt auch die Referenzkopie noch in der alten Fassung vor, wird nicht
    der alte Prompt erneut eingetragen, sondern der neue (leere) Standard."""
    (einstellungen / "systemprompt_protokoll.default.txt").write_text(ALTER_STANDARD_1, encoding="utf-8")
    datei = einstellungen / "systemprompt_protokoll.txt"
    datei.write_text(ALTER_STANDARD_1, encoding="utf-8")

    paths.ensure_system_prompt_file_exists()

    assert datei.read_text(encoding="utf-8") == ""
    # Die Referenzkopie beschreibt die Anwendung nie.
    assert (einstellungen / "systemprompt_protokoll.default.txt").read_text(encoding="utf-8") == ALTER_STANDARD_1
