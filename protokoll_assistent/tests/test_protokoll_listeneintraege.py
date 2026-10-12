"""Listeneintraege im Protokoll (offene Fragen, Fakten ...) als lesbarer Text --
auch wenn das Modell statt Zeichenketten Objekte liefert."""

from protokoll_assistent.services import dokument_export_service as de
from protokoll_assistent.services import export_service

# So kam es von qwen3.5:4b bei einer echten Podiumsdiskussion zurueck.
OFFENE_FRAGEN = [
    "Wer zahlt die Schulung?",
    {"frage": "Wie sieht ein internationales CO2-Regime aus?", "status": "offen", "quelle": "00:21:45"},
    {"frage": "Welches Wachstum ist gemeint?", "kontext": "", "quelle": None},
    {},
]


def test_listeneintrag_als_text():
    assert export_service.listeneintrag_als_text("Text") == "Text"
    assert (
        export_service.listeneintrag_als_text(OFFENE_FRAGEN[1])
        == "Wie sieht ein internationales CO2-Regime aus? (status: offen, quelle: 00:21:45)"
    )
    assert export_service.listeneintrag_als_text(OFFENE_FRAGEN[2]) == "Welches Wachstum ist gemeint?"  # leere Angaben fallen weg
    assert export_service.listeneintrag_als_text({}) == ""
    assert export_service.listeneintrag_als_text(["a", {"b": "c"}]) == "a; c"
    assert export_service.listeneintrag_als_text(42) == "42"


def test_aelteres_protokoll_mit_fester_gliederung_zeigt_keine_rohen_objekte():
    protokoll = {"titel": "T", "kurzzusammenfassung": "K", "offene_fragen": OFFENE_FRAGEN, "wichtige_fakten": [{"fakt": "2 Grad"}]}

    dokument = de.als_markdown(de.protokoll_dokument(protokoll))
    assert "{" not in dokument and "'frage'" not in dokument
    assert "- Wie sieht ein internationales CO2-Regime aus? (status: offen, quelle: 00:21:45)" in dokument
    assert "- 2 Grad" in dokument
