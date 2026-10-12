import pytest

from protokoll_assistent.services import protocol_service


def _fake_generate_factory(responses_by_call=None, raise_on_prompt_containing=None):
    """Erstellt eine generate_fn-Stub-Funktion ohne echtes Ollama."""
    calls = {"count": 0, "prompts": [], "systems": []}

    def generate(prompt: str, system: str) -> str:
        calls["count"] += 1
        calls["prompts"].append(prompt)
        calls["systems"].append(system)
        if raise_on_prompt_containing and raise_on_prompt_containing in prompt:
            raise RuntimeError("Simulierter Verbindungsfehler zu Ollama")
        if responses_by_call and calls["count"] in responses_by_call:
            return responses_by_call[calls["count"]]
        if "Endergebnis" in prompt:
            return "ENDERGEBNIS"
        return f"Text aus Aufruf {calls['count']}"

    return generate, calls


def _chunks(anzahl: int) -> list[dict]:
    return [
        {"index": i, "start_str": f"00:{i*10:02d}:00", "end_str": f"00:{i*10+10:02d}:00", "text": f"Chunk {i}"}
        for i in range(anzahl)
    ]


def test_stage1_result_is_cached_and_not_recomputed(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    path = tmp_path / "chunk_0001.md"

    first = protocol_service.run_stage1_chunk_analysis(
        0, "Text", "00:00:00", "00:10:00", "System", generate_fn, path
    )
    assert calls["count"] == 1
    assert path.is_file()

    second = protocol_service.run_stage1_chunk_analysis(
        0, "Text", "00:00:00", "00:10:00", "System", generate_fn, path
    )
    assert calls["count"] == 1  # kein erneuter Aufruf
    assert first == second


def test_generate_checked_wiederholt_eine_leere_antwort_einmal():
    generate_fn, calls = _fake_generate_factory(responses_by_call={1: "   ", 2: "Brauchbar"})
    assert protocol_service.generate_checked("Prompt", "System", generate_fn) == "Brauchbar"
    assert calls["count"] == 2


def test_generate_checked_meldet_fehler_nach_zweiter_leerer_antwort():
    generate_fn, calls = _fake_generate_factory(responses_by_call={1: "", 2: "\n"})
    with pytest.raises(protocol_service.ProtocolValidationError):
        protocol_service.generate_checked("Prompt", "System", generate_fn)
    assert calls["count"] == 2


def test_antwort_bereinigen_entfernt_denkbloecke():
    roh = "<think>ueberlege ich\nmehrzeilig</think>\n\nDas Ergebnis.\n"
    assert protocol_service.antwort_bereinigen(roh) == "Das Ergebnis."


def test_ein_abschnitt_braucht_nur_einen_aufruf_und_keine_zwischenstufen(tmp_path):
    generate_fn, calls = _fake_generate_factory(responses_by_call={1: "Nur dieses Ergebnis"})
    result = protocol_service.run_full_protocol_pipeline(_chunks(1), tmp_path, "Mein Auftrag", generate_fn)
    assert result == "Nur dieses Ergebnis"
    assert calls["count"] == 1
    assert calls["systems"] == ["Mein Auftrag"]


def test_full_pipeline_hierarchical_stages_produce_text_result(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    stage_progress = []
    result = protocol_service.run_full_protocol_pipeline(
        _chunks(4),
        tmp_path,
        "Mein Auftrag",
        generate_fn,
        group_size=2,
        progress_cb=lambda stage, current, total: stage_progress.append(stage),
    )
    assert result == "ENDERGEBNIS"
    # 4 Abschnitts-Auswertungen + 2 Gruppen-Zusammenfuehrungen + 1 Endergebnis = 7 Aufrufe.
    assert calls["count"] == 7
    kennung = protocol_service.prompt_kennung("Mein Auftrag")
    assert (tmp_path / "analysen" / kennung / "chunk_0001.md").is_file()
    assert (tmp_path / "zusammengefuehrt" / kennung / "ergebnis.md").is_file()
    assert "stufe1_chunk_analyse" in stage_progress
    assert "stufe3_gesamtprotokoll" in stage_progress


def test_nur_ein_zusammengefuehrtes_teilergebnis_wird_nicht_nochmal_umformuliert(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    result = protocol_service.run_full_protocol_pipeline(_chunks(2), tmp_path, "Auftrag", generate_fn, group_size=4)
    # 2 Abschnitte + 1 Zusammenfuehrung, kein drittes "Endergebnis".
    assert calls["count"] == 3
    assert result == "Text aus Aufruf 3"


def test_der_systemprompt_ist_in_jeder_stufe_der_alleinige_auftrag(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(4), tmp_path, "Liste nur die Termine auf.", generate_fn, group_size=2)
    assert set(calls["systems"]) == {"Liste nur die Termine auf."}


def test_die_stufenanfragen_geben_keine_gliederung_vor(tmp_path):
    """Keine der Anfragen darf eine feste Besprechungsstruktur vorgeben --
    sonst setzt sich diese gegen den Systemprompt durch."""
    generate_fn, calls = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(4), tmp_path, "Liste nur die Termine auf.", generate_fn, group_size=2)
    for prompt in calls["prompts"]:
        for verboten in ("entscheidungen", "aufgaben", "offene_fragen", "kernaussagen", "JSON", "kurzzusammenfassung"):
            assert verboten not in prompt


def test_ohne_systemprompt_fasst_das_modell_frei_zusammen(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(1), tmp_path, "   ", generate_fn)
    assert calls["systems"] == [protocol_service.OHNE_VORGABE_SYSTEMPROMPT]
    for verboten in ("Entscheidung", "Aufgabe", "Meeting", "JSON"):
        assert verboten not in protocol_service.OHNE_VORGABE_SYSTEMPROMPT


def test_anderer_systemprompt_verwendet_kein_altes_ergebnis_wieder(tmp_path):
    """Gleiches Transkript, anderer Auftrag: Das Ergebnis zum alten Auftrag
    darf nicht zurueckkommen."""
    erstes, _ = _fake_generate_factory(responses_by_call={1: "ERGEBNIS ZUM ALTEN AUFTRAG"})
    alt = protocol_service.run_full_protocol_pipeline(_chunks(1), tmp_path, "Alter Auftrag", erstes)
    assert alt == "ERGEBNIS ZUM ALTEN AUFTRAG"

    zweites, calls = _fake_generate_factory(responses_by_call={1: "ERGEBNIS ZUM NEUEN AUFTRAG"})
    neu = protocol_service.run_full_protocol_pipeline(_chunks(1), tmp_path, "Neuer Auftrag", zweites)
    assert neu == "ERGEBNIS ZUM NEUEN AUFTRAG"
    assert calls["count"] == 1

    # Derselbe Auftrag noch einmal: das gespeicherte Ergebnis wird wiederverwendet.
    drittes, calls3 = _fake_generate_factory()
    wieder = protocol_service.run_full_protocol_pipeline(_chunks(1), tmp_path, "Neuer Auftrag", drittes)
    assert wieder == "ERGEBNIS ZUM NEUEN AUFTRAG"
    assert calls3["count"] == 0


def test_leeres_transkript_wird_gemeldet(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    with pytest.raises(protocol_service.ProtocolValidationError):
        protocol_service.run_full_protocol_pipeline([], tmp_path, "Auftrag", generate_fn)
    assert calls["count"] == 0


def test_faulty_single_chunk_does_not_lose_previous_progress(tmp_path):
    generate_fn, calls = _fake_generate_factory(raise_on_prompt_containing="Abschnitt 2 ")
    chunk_texts = _chunks(2)
    kennung = protocol_service.prompt_kennung("System")

    with pytest.raises(RuntimeError):
        protocol_service.run_full_protocol_pipeline(chunk_texts, tmp_path, "System", generate_fn, group_size=2)

    # Abschnitt 1 wurde bereits erfolgreich ausgewertet und gespeichert.
    chunk0_path = tmp_path / "analysen" / kennung / "chunk_0001.md"
    assert chunk0_path.is_file()
    assert not (tmp_path / "analysen" / kennung / "chunk_0002.md").is_file()

    calls_before_retry = calls["count"]

    # Ein erneuter Lauf (z.B. nach Behebung des Fehlers) darf Abschnitt 1 NICHT
    # erneut anfragen -- nur der fehlgeschlagene Abschnitt 2 wird nachgeholt.
    generate_fn2, calls2 = _fake_generate_factory()
    chunk0_before = chunk0_path.read_text(encoding="utf-8")
    protocol_service.run_full_protocol_pipeline(chunk_texts, tmp_path, "System", generate_fn2, group_size=2)
    assert calls2["count"] < calls_before_retry + 3  # nur Abschnitt 2 + Zusammenfuehrung, nicht Abschnitt 1 erneut
    assert chunk0_path.read_text(encoding="utf-8") == chunk0_before


def test_verdichtung_laeuft_in_runden_bis_es_passt(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    stufen = []
    # Winziges Budget: jede Runde ist "zu gross", bis nur noch ein Teilergebnis uebrig ist.
    ergebnis = protocol_service.run_full_protocol_pipeline(
        _chunks(8),
        tmp_path,
        "System",
        generate_fn,
        group_size=2,
        progress_cb=lambda stage, current, total: stufen.append(stage),
        max_kontext_zeichen=1,
    )
    # 8 Abschnitte + (4 + 2 + 1) Verdichtungen; das eine Teilergebnis ist das Endergebnis
    assert calls["count"] == 8 + 7
    assert ergebnis.startswith("Text aus Aufruf")
    assert "stufe2_zwischenzusammenfuehrung" in stufen
    assert "stufe2_verdichtung_runde_2" in stufen
    assert "stufe2_verdichtung_runde_3" in stufen
    kennung = protocol_service.prompt_kennung("System")
    assert (tmp_path / "zusammengefuehrt" / kennung / "zwischenergebnis_r02_0001.md").is_file()


def test_verdichtung_stoppt_wenn_es_passt(tmp_path):
    generate_fn, calls = _fake_generate_factory()
    ergebnis = protocol_service.run_full_protocol_pipeline(_chunks(8), tmp_path, "System", generate_fn, group_size=2)
    # Standardbudget ist gross genug: 8 + 4 (eine Runde) + 1 Endergebnis
    assert calls["count"] == 13
    assert ergebnis == "ENDERGEBNIS"
    kennung = protocol_service.prompt_kennung("System")
    assert not list((tmp_path / "zusammengefuehrt" / kennung).glob("zwischenergebnis_r*"))


def test_verdichtung_hoechstens_acht_runden(tmp_path):
    generate_fn, _ = _fake_generate_factory()
    # Gruppengroesse 1 wuerde nie schrumpfen; ab Runde 2 gilt mindestens 2.
    protocol_service.run_full_protocol_pipeline(
        _chunks(3), tmp_path, "System", generate_fn, group_size=1, max_kontext_zeichen=1
    )
    kennung = protocol_service.prompt_kennung("System")
    runden = {p.name.split("_")[1] for p in (tmp_path / "zusammengefuehrt" / kennung).glob("zwischenergebnis_r*")}
    assert len(runden) <= protocol_service.MAX_VERDICHTUNGSRUNDEN


def test_verdichtung_wiederaufnahme_fragt_fertige_runden_nicht_erneut(tmp_path):
    generate_fn, _ = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(4), tmp_path, "System", generate_fn, group_size=2)
    kennung = protocol_service.prompt_kennung("System")
    (tmp_path / "zusammengefuehrt" / kennung / "ergebnis.md").unlink()
    generate_fn2, calls2 = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(4), tmp_path, "System", generate_fn2, group_size=2)
    assert calls2["count"] == 1  # nur das Endergebnis


def test_abgeschnittene_antwort_wird_nicht_als_zwischenstand_gespeichert(tmp_path, monkeypatch):
    """Ollama meldet 'done_reason: length' -- der unvollstaendige Text darf
    nicht gespeichert werden, sonst kaeme er beim naechsten Lauf als fertiges
    Ergebnis zurueck."""
    import io
    import json

    from protokoll_assistent.services import ollama_service

    antwort = json.dumps({"response": "Halber Sa", "done": True, "done_reason": "length"}).encode("utf-8")
    monkeypatch.setattr(ollama_service.urllib.request, "urlopen", lambda request, timeout=None: io.BytesIO(antwort))

    with pytest.raises(ollama_service.OllamaError, match="abgeschnitten"):
        protocol_service.run_full_protocol_pipeline(_chunks(2), tmp_path, "Auftrag")
    assert not list(tmp_path.rglob("*.md"))


def test_antwort_bereinigen_ungeschlossener_denkblock_ist_keine_antwort():
    """Ein geoeffneter, nie geschlossener Denkblock ist reines Nachdenken --
    das darf nicht als Ergebnis im Protokoll landen."""
    assert protocol_service.antwort_bereinigen("<think>Ich ueberlege noch, was wichtig ist ...") == ""
    assert protocol_service.antwort_bereinigen("  <THINK>\nnur Gedanken") == ""


def test_antwort_bereinigen_verwaister_schluss_tag():
    """Manche Vorlagen oeffnen den Denkblock schon im Prompt; die Antwort
    beginnt dann mitten im Nachdenken und enthaelt nur das schliessende Tag."""
    assert protocol_service.antwort_bereinigen("ueberlege ich\nnoch</think>\n\nDas Ergebnis.") == "Das Ergebnis."


def test_antwort_bereinigen_laesst_normalen_text_unveraendert():
    assert protocol_service.antwort_bereinigen("  ## Termine\n- 12.10. Abgabe\n") == "## Termine\n- 12.10. Abgabe"


def test_generate_checked_wiederholt_reines_nachdenken():
    generate_fn, calls = _fake_generate_factory(responses_by_call={1: "<think>abgebrochen", 2: "Brauchbar"})
    assert protocol_service.generate_checked("Prompt", "System", generate_fn) == "Brauchbar"
    assert calls["count"] == 2


def test_leerer_abschnitt_wird_gespeichert_und_uebersprungen(tmp_path):
    """Mit einem filternden Auftrag ('nur ToDos') kann ein Abschnitt zu Recht
    nichts liefern. Das bricht den Lauf nicht ab: Nach einem zweiten Versuch
    gilt das leere Ergebnis, wird gespeichert und beim Zusammenfuehren
    uebersprungen."""
    generate_fn, calls = _fake_generate_factory(responses_by_call={2: "", 3: "  "})
    ergebnis = protocol_service.run_full_protocol_pipeline(_chunks(3), tmp_path, "Nur ToDos", generate_fn, group_size=4)

    # Abschnitt 1, Abschnitt 2 zweimal (leer), Abschnitt 3, eine Zusammenfuehrung.
    assert calls["count"] == 5
    assert ergebnis == "Text aus Aufruf 5"
    zusammenfuehrung = calls["prompts"][4]
    assert "Text aus Aufruf 1" in zusammenfuehrung and "Text aus Aufruf 4" in zusammenfuehrung
    assert "Teilergebnis 3" not in zusammenfuehrung  # nur die zwei nicht leeren

    kennung = protocol_service.prompt_kennung("Nur ToDos")
    leer = tmp_path / "analysen" / kennung / "chunk_0002.md"
    assert leer.is_file() and leer.read_text(encoding="utf-8") == ""

    # Wiederaufnahme: der leere Abschnitt wird nicht erneut angefragt.
    (tmp_path / "zusammengefuehrt" / kennung / "ergebnis.md").unlink()
    generate_fn2, calls2 = _fake_generate_factory()
    protocol_service.run_full_protocol_pipeline(_chunks(3), tmp_path, "Nur ToDos", generate_fn2, group_size=4)
    assert calls2["count"] == 0


def test_alle_abschnitte_leer_wird_gemeldet(tmp_path):
    generate_fn, calls = _fake_generate_factory(responses_by_call={n: "" for n in range(1, 7)})
    with pytest.raises(protocol_service.ProtocolValidationError, match="keinem der 3 Abschnitte"):
        protocol_service.run_full_protocol_pipeline(_chunks(3), tmp_path, "Nur ToDos", generate_fn)
    assert calls["count"] == 6  # je Abschnitt ein zweiter Versuch, keine Zusammenfuehrung


def test_leere_zusammenfuehrung_bleibt_ein_fehler(tmp_path):
    generate_fn, _ = _fake_generate_factory(responses_by_call={3: "", 4: ""})
    with pytest.raises(protocol_service.ProtocolValidationError):
        protocol_service.run_full_protocol_pipeline(_chunks(2), tmp_path, "Auftrag", generate_fn, group_size=4)
    kennung = protocol_service.prompt_kennung("Auftrag")
    assert not (tmp_path / "zusammengefuehrt" / kennung / "zwischenergebnis_0001.md").is_file()
