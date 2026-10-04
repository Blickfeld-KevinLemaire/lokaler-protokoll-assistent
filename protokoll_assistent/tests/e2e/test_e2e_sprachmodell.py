"""Ende-zu-Ende: Nachbearbeitung und Chatbot mit dem echten Sprachmodell.

Grundlage ist das Drehbuch aus ``besprechung.py`` als fertiges Transkript --
die Spracherkennung ist hier bewusst aussen vor, damit ein Fehler eindeutig
dem Sprachmodell zuzuordnen ist. Gebraucht wird nur ein laufendes Ollama.
"""

from __future__ import annotations

import json
import time

import pytest

from protokoll_assistent.services import chat_service, ollama_service, pipeline_service
from protokoll_assistent.tests.e2e import besprechung
from protokoll_assistent.utils import paths

pytestmark = pytest.mark.timeout(1800)


def _text(wert) -> str:
    return json.dumps(wert, ensure_ascii=False)


def test_denkphase_ist_aus_und_die_antwort_kommt_zuegig(sprachmodell):
    """Qwen3.5 denkt ohne 'think: false' vor jeder Antwort lange nach. Ein
    kurzer Auftrag muss deshalb schnell und ohne <think>-Block zurueckkommen."""
    ollama_service.generate_json("Gib {\"ok\": true} zurueck.", "Antworte nur mit JSON.", model=sprachmodell)  # Modell laden

    beginn = time.monotonic()
    antwort = ollama_service.generate_json(
        "Nenne die Hauptstadt von Frankreich als JSON mit dem Schluessel 'stadt'.",
        "Du antwortest ausschliesslich mit einem JSON-Objekt.",
        model=sprachmodell,
    )
    dauer = time.monotonic() - beginn

    assert besprechung.enthaelt_eines(_text(antwort), "paris")
    # Mit Denkphase dauert selbst diese Frage Minuten; ohne sie auf der Grafikkarte
    # Sekunden. 60 s laesst auch einem Rechner ohne Grafikkarte genug Luft.
    assert dauer < 60, f"Antwort brauchte {dauer:.0f} s - laeuft die Denkphase doch?"

    stuecke: list[str] = []
    text = ollama_service.chat_stream(
        [{"role": "user", "content": "Sag in einem Satz, wofuer ein Besprechungsprotokoll gut ist."}],
        sprachmodell,
        stuecke.append,
    )
    assert text.strip() and len(stuecke) > 1  # wirklich gestreamt
    assert "<think>" not in text


def test_protokoll_aus_transkript_enthaelt_beschluesse_aufgaben_und_offene_fragen(
    sprachmodell, transkript, tmp_path, daten_ordner
):
    meldungen: list[str] = []
    ergebnis = pipeline_service.run_protocol(
        pipeline_service.ProtocolSettings(
            transcript_json_path=transkript,
            output_dir=tmp_path / "ausgabe",
            ollama_model=sprachmodell,
            # Der mitgelieferte Systemprompt, nicht ein eventuell lokal bearbeiteter.
            system_prompt=paths.get_default_system_prompt_file().read_text(encoding="utf-8"),
        ),
        pipeline_service.PipelineCallbacks(on_log=meldungen.append),
    )

    assert ergebnis.protokoll_fehler is None, ergebnis.protokoll_fehler
    assert ergebnis.protocol_paths is not None
    json_pfad, md_pfad = ergebnis.protocol_paths
    protokoll = json.loads(json_pfad.read_text(encoding="utf-8"))
    assert md_pfad.read_text(encoding="utf-8").strip()
    assert any("Word-Datei erstellt" in m for m in meldungen), meldungen

    entscheidungen = _text(protokoll.get("entscheidungen"))
    assert besprechung.enthaelt_eines(entscheidungen, *besprechung.UMZUGSTERMIN), entscheidungen
    assert besprechung.enthaelt_eines(_text(protokoll), *besprechung.BUDGET)

    aufgaben = protokoll.get("aufgaben") or []
    assert len(aufgaben) >= 2, aufgaben
    testplan = [a for a in aufgaben if besprechung.enthaelt_eines(_text(a), "testplan")]
    assert testplan, aufgaben
    assert besprechung.enthaelt_eines(_text(testplan[0]), "wagner", "thomas"), testplan
    assert besprechung.enthaelt_eines(_text(testplan[0]), *besprechung.FRIST_TESTPLAN), testplan
    assert any(besprechung.enthaelt_eines(_text(a), "schulz", "katrin") for a in aufgaben), aufgaben

    assert besprechung.enthaelt_eines(_text(protokoll.get("offene_fragen")), "wochenend"), protokoll.get("offene_fragen")
    assert besprechung.enthaelt_eines(_text(protokoll), *besprechung.FOLGETERMIN)


def test_chatbot_beantwortet_frage_aus_dem_transkript_mit_quelle(sprachmodell, einbettungsmodell, transkript, tmp_path):
    einstellungen = chat_service.ChatEinstellungen("lokal", sprachmodell, einbettungsmodell)
    assert chat_service.fehlendes_modell(einstellungen) is None
    embed_fn, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
    dokument = chat_service.lade_dokument(transkript)

    antwort, quellen = chat_service.beantworte(
        "Bis wann soll der Testplan fertig sein, und wer schreibt ihn?",
        [dokument],
        [],
        embed_fn,
        chat_fn,
        tmp_path / "vektoren",
        einstellungen.modell_kennung,
        chat_modell=sprachmodell,
    )

    assert besprechung.enthaelt_eines(antwort, *besprechung.FRIST_TESTPLAN, "freitag"), antwort
    assert besprechung.enthaelt_eines(antwort, "wagner", "thomas"), antwort
    assert quellen, "Die Antwort nennt keine Quelle."


def test_chatbot_fasst_mit_ganzem_text_die_besprechung_zusammen(sprachmodell, transkript, tmp_path):
    """Volltext-Modus: Der ganze Text passt in eine Anfrage; kein Einbettungsmodell."""
    einstellungen = chat_service.ChatEinstellungen(
        "lokal", sprachmodell, "gibt-es-nicht", kontext=chat_service.KONTEXT_VOLLTEXT
    )
    assert chat_service.fehlendes_modell(einstellungen) is None  # Einbettung wird nicht gebraucht
    _embed, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
    status: list[str] = []

    antwort, quellen = chat_service.beantworte(
        "Fasse die Besprechung zusammen: Was wurde beschlossen, und wer macht was bis wann?",
        [chat_service.lade_dokument(transkript)],
        [],
        _embed,
        chat_fn,
        tmp_path / "vektoren",
        einstellungen.modell_kennung,
        on_status=status.append,
        kontext=chat_service.KONTEXT_VOLLTEXT,
    )

    assert status == ["Antwort wird erzeugt …"]  # ein Aufruf, nicht in Stuecken
    assert besprechung.enthaelt_eines(antwort, *besprechung.UMZUGSTERMIN), antwort
    assert besprechung.enthaelt_eines(antwort, "testplan"), antwort
    assert besprechung.enthaelt_eines(antwort, "schulung", "angebot"), antwort
    assert quellen == [transkript.stem]


def test_chatbot_liest_zu_langen_text_in_stuecken(sprachmodell, transkript):
    """Erzwungenes Stueckeln: kleine Grenzen, damit die Besprechung in mehreren
    Teilen gelesen wird. Die Frist steht nur in einem davon."""
    einstellungen = chat_service.ChatEinstellungen("lokal", sprachmodell, "", kontext=chat_service.KONTEXT_VOLLTEXT)
    _embed, chat_fn = chat_service.funktionen_aus_einstellungen(einstellungen)
    status: list[str] = []

    antwort, _quellen = chat_service.beantworte_volltext(
        "Bis wann soll der Testplan fertig sein?",
        [chat_service.lade_dokument(transkript)],
        [],
        chat_fn,
        on_status=status.append,
        # Der Text hat knapp 1.300 Zeichen: passt nicht in "eine Anfrage" (1.200),
        # die knappen Notizen aber schon. Mit 1.000 wurden ausfuehrliche Notizen
        # hinten gekuerzt -- und mit ihnen die Frist (04.10.2026).
        max_zeichen=1200,
        stueck_zeichen=450,
        ueberlappung=100,
    )

    gelesen = [s for s in status if s.startswith("Abschnitt ")]
    assert len(gelesen) >= 3, status
    assert besprechung.enthaelt_eines(antwort, *besprechung.FRIST_TESTPLAN, "freitag"), antwort
