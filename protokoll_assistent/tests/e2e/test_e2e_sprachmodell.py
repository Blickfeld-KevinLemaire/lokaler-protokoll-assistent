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
from protokoll_assistent.utils import systemprompt_vorlagen

pytestmark = pytest.mark.timeout(1800)


def test_denkphase_ist_aus_und_die_antwort_kommt_zuegig(sprachmodell):
    """Qwen3.5 denkt ohne 'think: false' vor jeder Antwort lange nach. Ein
    kurzer Auftrag muss deshalb schnell und ohne <think>-Block zurueckkommen.
    Wie in der Nachbearbeitung ueber 'generate_text' (Freitext)."""
    ollama_service.generate_text("Antworte nur mit: ok", "Antworte knapp.", model=sprachmodell)  # Modell laden

    beginn = time.monotonic()
    antwort = ollama_service.generate_text(
        "Nenne die Hauptstadt von Frankreich. Antworte mit einem Wort.",
        "Du antwortest knapp auf Deutsch.",
        model=sprachmodell,
    )
    dauer = time.monotonic() - beginn

    assert besprechung.enthaelt_eines(antwort, "paris"), antwort
    assert "<think>" not in antwort
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
            # Seit die Nachbearbeitung nur dem Systemprompt folgt, legt eine
            # Abschnittsvorlage fest, was ins Protokoll gehoert (der
            # mitgelieferte Standard ist leer).
            system_prompt=systemprompt_vorlagen.ABSCHNITTSVORLAGEN["Formelles Protokoll"],
        ),
        pipeline_service.PipelineCallbacks(on_log=meldungen.append),
    )

    assert ergebnis.protokoll_fehler is None, ergebnis.protokoll_fehler
    assert ergebnis.protocol_paths is not None
    json_pfad, md_pfad = ergebnis.protocol_paths
    text = json.loads(json_pfad.read_text(encoding="utf-8"))["ergebnis"]
    assert md_pfad.read_text(encoding="utf-8").strip() == text.strip()
    assert any("Word-Datei erstellt" in m for m in meldungen), meldungen
    assert not text.lstrip().startswith("{"), text  # Freitext, kein JSON

    assert besprechung.enthaelt_eines(text, *besprechung.UMZUGSTERMIN), text
    assert besprechung.enthaelt_eines(text, *besprechung.BUDGET), text
    assert besprechung.enthaelt_eines(text, "testplan"), text
    assert besprechung.enthaelt_eines(text, "wagner", "thomas"), text
    assert besprechung.enthaelt_eines(text, *besprechung.FRIST_TESTPLAN), text
    assert besprechung.enthaelt_eines(text, "schulz", "katrin"), text
    assert besprechung.enthaelt_eines(text, "wochenend"), text
    assert besprechung.enthaelt_eines(text, *besprechung.FOLGETERMIN), text


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
