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
    ok2, errors2 = validate_chunk_analysis_json({"irrelevantes_feld": []})
    assert ok2 is False
