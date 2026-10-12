from protokoll_assistent.utils.json_validation import extract_json_object


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
