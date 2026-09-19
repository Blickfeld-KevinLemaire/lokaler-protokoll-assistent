"""Tests fuer die Sprechertrennung.

Die beiden Faelle hier sind echte Fehler, die am 19.09.2026 auf einer
Maschine mit pyannote.audio 4.0.7 aufgetreten sind: Die Pipeline liefert
dort kein 'Annotation' mehr, sondern ein 'DiarizeOutput'. Ohne die
Fallunterscheidung bricht die Sprechertrennung ab mit
"'DiarizeOutput' object has no attribute 'itertracks'".

Der Fehler war in keiner automatischen Pruefung sichtbar: Er braucht ein
Modell mit Zugangsbeschraenkung, ein Hugging-Face-Token und echtes Audio.
"""

from __future__ import annotations

from services import diarization_service


class _Segment:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _Annotation:
    """Bildet 'pyannote.core.Annotation' nach (pyannote 3 und 4)."""

    def __init__(self, spuren):
        self._spuren = spuren

    def itertracks(self, yield_label: bool = False):
        for start, ende, sprecher in self._spuren:
            yield _Segment(start, ende), None, sprecher


class _DiarizeOutput:
    """Bildet die Rueckgabe von pyannote.audio 4.x nach."""

    def __init__(self, annotation):
        self.speaker_diarization = annotation
        self.exclusive_speaker_diarization = annotation
        self.speaker_embeddings = None


def _pipeline(rueckgabe):
    def aufruf(_waveform, **_kwargs):
        return rueckgabe

    return aufruf


SPUREN = [(1.5, 2.5, "SPEAKER_01"), (0.0, 1.0, "SPEAKER_00")]


def test_pyannote4_diarizeoutput_wird_ausgepackt():
    ergebnis = _DiarizeOutput(_Annotation(SPUREN))

    abschnitte = diarization_service.diarize_waveform(_pipeline(ergebnis), {})

    assert [a["speaker"] for a in abschnitte] == ["SPEAKER_00", "SPEAKER_01"]
    assert abschnitte[0]["start"] == 0.0


def test_pyannote3_annotation_geht_weiterhin():
    # Aeltere Fassungen geben die Annotation direkt zurueck.
    abschnitte = diarization_service.diarize_waveform(_pipeline(_Annotation(SPUREN)), {})

    assert [a["speaker"] for a in abschnitte] == ["SPEAKER_00", "SPEAKER_01"]


def test_abschnitte_sind_nach_startzeit_sortiert():
    abschnitte = diarization_service.diarize_waveform(_pipeline(_DiarizeOutput(_Annotation(SPUREN))), {})

    startzeiten = [a["start"] for a in abschnitte]
    assert startzeiten == sorted(startzeiten)


def test_sprecherzahl_wird_durchgereicht():
    gesehen = {}

    def aufruf(_waveform, **kwargs):
        gesehen.update(kwargs)
        return _DiarizeOutput(_Annotation([]))

    diarization_service.diarize_waveform(aufruf, {}, min_speakers=2, max_speakers=5)

    assert gesehen == {"min_speakers": 2, "max_speakers": 5}
