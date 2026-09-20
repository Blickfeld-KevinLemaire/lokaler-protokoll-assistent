from utils.json_validation import (
    extract_json_object,
    validate_chunk_analysis_json,
    validate_protocol_json,
)

VALID_PROTOCOL = {
    "titel": "Teambesprechung",
    "kurzzusammenfassung": "Kurze Zusammenfassung.",
    "teilnehmende_oder_sprecher": ["Sprecher 1", "Sprecher 2"],
    "themen": [],
    "entscheidungen": [],
    "aufgaben": [],
    "termine": [],
    "offene_fragen": [],
    "wichtige_fakten": [],
    "unsichere_transkriptstellen": [],
    "quellenhinweise": [],
}


def test_valid_protocol_passes():
    ok, errors = validate_protocol_json(VALID_PROTOCOL)
    assert ok is True
    assert errors == []


def test_missing_field_fails():
    broken = dict(VALID_PROTOCOL)
    del broken["aufgaben"]
    ok, errors = validate_protocol_json(broken)
    assert ok is False
    assert any("aufgaben" in error for error in errors)


def test_wrong_type_fails():
    broken = dict(VALID_PROTOCOL)
    broken["themen"] = "sollte eine Liste sein"
    ok, errors = validate_protocol_json(broken)
    assert ok is False
    assert any("themen" in error for error in errors)


def test_non_dict_fails():
    ok, errors = validate_protocol_json(["nicht", "erlaubt"])
    assert ok is False
    assert errors


def test_error_status_object_is_rejected():
    broken = dict(VALID_PROTOCOL)
    broken["error"] = "irgendein Fehler"
    ok, errors = validate_protocol_json(broken)
    assert ok is False
    assert any("error" in message for message in errors)


def test_extract_json_object_direct():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_from_fenced_code_block():
    text = "Hier ist die Antwort:\n```json\n{\"a\": 1, \"b\": 2}\n```\nDanke."
    assert extract_json_object(text) == {"a": 1, "b": 2}


def test_extract_json_object_with_surrounding_prose():
    text = 'Sicher, hier ist das JSON: {"a": {"nested": true}} -- Ende.'
    assert extract_json_object(text) == {"a": {"nested": True}}


def test_extract_json_object_returns_none_for_garbage():
    assert extract_json_object("das ist kein JSON") is None


def test_chunk_analysis_requires_at_least_one_content_field():
    ok, errors = validate_chunk_analysis_json({"kernaussagen": ["Punkt 1"]})
    assert ok is True
    assert errors == []
    ok2, errors2 = validate_chunk_analysis_json({"irrelevantes_feld": []})
    assert ok2 is False
    assert errors2


# ---------------------------------------------------------------------------
# Geschweifte Klammern innerhalb von Zeichenketten
# ---------------------------------------------------------------------------
def test_klammer_in_zeichenkette_beendet_die_suche_nicht():
    # Die Klammerzaehlung darf Zeichenketten nicht mitzaehlen: Sonst gilt
    # das Objekt an der Klammer IM Text als zu Ende, der Ausschnitt laesst
    # sich nicht lesen, und die ganze Auswertung scheitert - samt
    # Reparaturversuch, der genauso endet.
    antwort = 'Hier das Ergebnis:\n{"hinweis": "schliess die } Klammer", "aufgaben": []}'
    assert extract_json_object(antwort) == {
        "hinweis": "schliess die } Klammer",
        "aufgaben": [],
    }


def test_oeffnende_klammer_in_zeichenkette():
    antwort = 'Antwort:\n{"hinweis": "ein { offen", "aufgaben": []}'
    assert extract_json_object(antwort) == {
        "hinweis": "ein { offen",
        "aufgaben": [],
    }


def test_maskiertes_anfuehrungszeichen_verwirrt_nicht():
    antwort = 'Text davor {"zitat": "er sagte \\"} jetzt\\" und ging", "themen": []}'
    ergebnis = extract_json_object(antwort)
    assert ergebnis is not None
    assert ergebnis["themen"] == []


def test_verschachtelte_objekte_werden_vollstaendig_gelesen():
    antwort = 'Bitte sehr: {"aufgabe": {"wer": "Anna", "was": "melden"}, "termine": []}'
    assert extract_json_object(antwort) == {
        "aufgabe": {"wer": "Anna", "was": "melden"},
        "termine": [],
    }


def test_erklaerender_satz_mit_klammern_vor_dem_json():
    # Nach einer nicht lesbaren Klammerung wird weitergesucht statt
    # aufgegeben.
    antwort = 'Format {so ungefaehr} - hier das Ergebnis: {"themen": ["A"]}'
    assert extract_json_object(antwort) == {"themen": ["A"]}


def test_ohne_gueltiges_objekt_weiterhin_none():
    assert extract_json_object("gar kein JSON hier") is None
    assert extract_json_object('{"unvollstaendig": ') is None
