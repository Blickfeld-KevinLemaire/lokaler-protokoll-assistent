"""Tests fuer die Transkription ueber faster-whisper.

Frueher lief das ueber WhisperX; dabei gab es fuer dieses Modul keine
Tests. Mit dem Wechsel auf faster-whisper aendert sich die Ergebnisform
(Generator statt Liste, Objekte statt Dictionaries), deshalb wird die
Umwandlung hier mit einem Ersatzmodell abgesichert - ohne echtes Modell,
ohne GPU und ohne Audiodatei.
"""

from __future__ import annotations

from protokoll_assistent.services import transcription_service


class _Wort:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end


class _Segment:
    def __init__(self, start: float, end: float, text: str, words: list[_Wort] | None) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _Info:
    def __init__(self, language: str) -> None:
        self.language = language


class _ModellAttrappe:
    """Bildet faster-whisper nach: gibt einen Generator und ein Info-Objekt."""

    def __init__(self, segmente: list[_Segment], sprache: str = "de") -> None:
        self._segmente = segmente
        self._sprache = sprache
        self.letzte_kwargs: dict = {}

    def transcribe(self, _audio, **kwargs):
        self.letzte_kwargs = kwargs
        return (segment for segment in self._segmente), _Info(self._sprache)


def test_generator_wird_zu_einer_liste():
    # Der Generator von faster-whisper wird nur einmal durchlaufen. Wird er
    # nicht ausgewertet, waere das Ergebnis beim zweiten Zugriff leer.
    modell = _ModellAttrappe(
        [
            _Segment(0.0, 1.5, " Erster Satz.", [_Wort(" Erster", 0.0, 0.5)]),
            _Segment(1.5, 3.0, " Zweiter Satz.", None),
        ]
    )

    ergebnis = transcription_service.transcribe_audio_array(modell, object())

    assert isinstance(ergebnis["segments"], list)
    assert len(ergebnis["segments"]) == 2
    assert ergebnis["segments"][0]["text"] == " Erster Satz."
    assert ergebnis["language"] == "de"


def test_segmente_ohne_woerter_brechen_nicht():
    # 'segment.words' ist None, wenn keine Wortzeitstempel vorliegen.
    modell = _ModellAttrappe([_Segment(0.0, 1.0, "Text", None)])

    ergebnis = transcription_service.transcribe_audio_array(modell, object())

    assert ergebnis["segments"][0]["words"] == []


def test_wortzeitstempel_werden_angefordert():
    modell = _ModellAttrappe([])

    transcription_service.transcribe_audio_array(modell, object())

    assert modell.letzte_kwargs["word_timestamps"] is True
    assert modell.letzte_kwargs["vad_filter"] is True


def test_sprache_wird_durchgereicht():
    modell = _ModellAttrappe([], sprache="en")

    ergebnis = transcription_service.transcribe_audio_array(modell, object(), language="de")

    assert modell.letzte_kwargs["language"] == "de"
    # Die erkannte Sprache kommt aus dem Ergebnis, nicht aus der Vorgabe.
    assert ergebnis["language"] == "en"


def test_ohne_sprachvorgabe_wird_erkannt():
    modell = _ModellAttrappe([], sprache="fr")

    ergebnis = transcription_service.transcribe_audio_array(modell, object())

    assert "language" not in modell.letzte_kwargs
    assert ergebnis["language"] == "fr"


def test_segments_to_plain_vereinfacht_und_trimmt():
    ergebnis = {
        "segments": [
            {"start": 1.0, "end": 2.0, "text": "  Mit Leerzeichen  ", "words": [{"word": "a"}]},
        ]
    }

    einfach = transcription_service.segments_to_plain(ergebnis)

    assert einfach == [
        {
            "start": 1.0,
            "end": 2.0,
            "text": "Mit Leerzeichen",
            "speaker": None,
            "words": [{"word": "a"}],
        }
    ]


def test_align_funktionen_gibt_es_nicht_mehr():
    """Der Alignment-Schritt ist mit WhisperX entfallen.

    Bleiben die Funktionen als Blindgaenger stehen, ruft sie irgendwann
    wieder jemand auf.
    """
    assert not hasattr(transcription_service, "load_align_model")
    assert not hasattr(transcription_service, "align_segments")


class _StapelModellAttrappe:
    """Bildet 'BatchedInferencePipeline' nach: kennt 'batch_size'."""

    def __init__(self) -> None:
        self.letzte_kwargs: dict = {}

    def transcribe(self, _audio, word_timestamps=True, vad_filter=True, language=None, batch_size=8):
        self.letzte_kwargs = {
            "word_timestamps": word_timestamps,
            "vad_filter": vad_filter,
            "language": language,
            "batch_size": batch_size,
        }
        return iter(()), _Info("de")


class _EinfachesModellAttrappe:
    """Bildet 'WhisperModel' nach: kennt 'batch_size' NICHT."""

    def __init__(self) -> None:
        self.letzte_kwargs: dict = {}

    def transcribe(self, _audio, word_timestamps=True, vad_filter=True, language=None):
        self.letzte_kwargs = {
            "word_timestamps": word_timestamps,
            "vad_filter": vad_filter,
            "language": language,
        }
        return iter(()), _Info("de")


def test_batch_size_wird_an_stapelfaehige_modelle_uebergeben():
    # Der Wert kommt von der Oberflaeche ueber PipelineSettings bis
    # hierher - bisher wurde er schlicht nicht benutzt.
    modell = _StapelModellAttrappe()

    transcription_service.transcribe_audio_array(modell, object(), batch_size=16)

    assert modell.letzte_kwargs["batch_size"] == 16


def test_batch_size_wird_einfachen_modellen_nicht_untergeschoben():
    # 'WhisperModel.transcribe' kennt den Parameter nicht: Blind
    # uebergeben braeche die Transkription beim ersten Chunk mit einem
    # TypeError ab.
    modell = _EinfachesModellAttrappe()

    transcription_service.transcribe_audio_array(modell, object(), batch_size=16)

    assert "batch_size" not in modell.letzte_kwargs


def test_modell_mit_freier_signatur_bekommt_batch_size():
    modell = _ModellAttrappe([])  # transcribe(self, _audio, **kwargs)

    transcription_service.transcribe_audio_array(modell, object(), batch_size=4)

    assert modell.letzte_kwargs["batch_size"] == 4
