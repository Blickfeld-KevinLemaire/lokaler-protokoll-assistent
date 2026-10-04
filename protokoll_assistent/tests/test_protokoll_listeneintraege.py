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


def test_markdown_und_word_zeigen_keine_rohen_objekte():
    protokoll = {"titel": "T", "kurzzusammenfassung": "K", "offene_fragen": OFFENE_FRAGEN, "wichtige_fakten": [{"fakt": "2 Grad"}]}

    markdown = export_service.render_protocol_markdown(protokoll)
    assert "{" not in markdown and "'frage'" not in markdown
    assert "- Wie sieht ein internationales CO2-Regime aus? (status: offen, quelle: 00:21:45)" in markdown
    assert "- 2 Grad" in markdown

    dokument = de.als_markdown(de.protokoll_dokument(protokoll))
    assert "{" not in dokument and "Wie sieht ein internationales CO2-Regime aus?" in dokument
