import json

from protokoll_assistent.services import export_service


def _sample_segments():
    return [
        {"nummer": 1, "start": 2.78, "end": 17.18, "sprecher_id": "SPEAKER_00", "text": "Hallo zusammen."},
        {"nummer": 2, "start": 35.3, "end": 37.16, "sprecher_id": "SPEAKER_01", "text": "Guten Tag."},
        {"nummer": 3, "start": 40.0, "end": 45.0, "sprecher_id": "SPEAKER_00", "text": "Weiter geht's."},
    ]


def test_build_speaker_names_default_numbering():
    names = export_service.build_speaker_names(["SPEAKER_00", "SPEAKER_03"])
    assert names == {"SPEAKER_00": "Sprecher 1", "SPEAKER_03": "Sprecher 2"}


def test_build_speaker_names_respects_overrides():
    names = export_service.build_speaker_names(
        ["SPEAKER_00", "SPEAKER_03"], {"SPEAKER_03": "Tom Buhrow"}
    )
    assert names["SPEAKER_03"] == "Tom Buhrow"
    assert names["SPEAKER_00"] == "Sprecher 1"


def test_txt_content_matches_expected_format():
    segments = export_service.attach_speaker_names(
        _sample_segments(), {"SPEAKER_00": "Sprecher 1", "SPEAKER_01": "Sprecher 2"}
    )
    content = export_service.build_txt_content("aufnahme.mp3", "2026-01-01T10:00:00+01:00", "faster-whisper large-v3-turbo", "de", 2, segments)
    assert "PROTOKOLL-ASSISTENT" in content
    assert "[00:00:02.780 --> 00:00:17.180] Sprecher 1: Hallo zusammen." in content
    assert "[00:00:35.300 --> 00:00:37.160] Sprecher 2: Guten Tag." in content


def test_srt_content_uses_comma_separated_milliseconds():
    segments = export_service.attach_speaker_names(_sample_segments()[:1], {"SPEAKER_00": "Sprecher 1"})
    content = export_service.build_srt_content(segments)
    assert content.startswith("1\n00:00:02,780 --> 00:00:17,180\nSprecher 1: Hallo zusammen.")


def test_vtt_content_starts_with_webvtt_header():
    segments = export_service.attach_speaker_names(_sample_segments()[:1], {"SPEAKER_00": "Sprecher 1"})
    content = export_service.build_vtt_content(segments)
    assert content.startswith("WEBVTT\n\n00:00:02.780 --> 00:00:17.180\nSprecher 1: Hallo zusammen.")


def test_compute_speaker_stats_counts_and_durations():
    stats = export_service.compute_speaker_stats(_sample_segments())
    assert stats["SPEAKER_00"]["segmente"] == 2
    assert stats["SPEAKER_00"]["sprechdauer_sekunden"] == (17.18 - 2.78) + (45.0 - 40.0)
    assert stats["SPEAKER_01"]["segmente"] == 1


def test_write_transcript_exports_creates_all_four_files_uniquely(tmp_path):
    speaker_names = export_service.build_speaker_names(["SPEAKER_00", "SPEAKER_01"])
    paths = export_service.write_transcript_exports(
        tmp_path,
        "aufnahme.mp3",
        "aufnahme",
        "20260101_100000",
        "2026-01-01T10:00:00+01:00",
        "faster-whisper large-v3-turbo",
        "de",
        "cuda (RTX 3060 Ti)",
        12.5,
        _sample_segments(),
        speaker_names,
    )
    assert paths.txt.is_file() and paths.json.is_file() and paths.srt.is_file() and paths.vtt.is_file()
    data = json.loads(paths.json.read_text(encoding="utf-8"))
    assert data["anzahl_sprecher"] == 2
    assert data["anzahl_segmente"] == 3
    assert data["verarbeitung"] == "vollständig lokal"


def test_write_transcript_exports_does_not_collide_with_existing_run(tmp_path):
    speaker_names = export_service.build_speaker_names(["SPEAKER_00"])
    first = export_service.write_transcript_exports(
        tmp_path, "a.mp3", "a", "20260101_100000", "iso", "modell", "de", "cpu", 1.0,
        _sample_segments(), speaker_names,
    )
    second = export_service.write_transcript_exports(
        tmp_path, "a.mp3", "a", "20260101_100000", "iso", "modell", "de", "cpu", 1.0,
        _sample_segments(), speaker_names,
    )
    assert first.txt != second.txt  # eindeutige Dateinamen statt stillem Ueberschreiben
    assert first.txt.exists() and second.txt.exists()


def test_reexport_with_new_names_does_not_require_retranscription(tmp_path):
    speaker_names = export_service.build_speaker_names(["SPEAKER_00", "SPEAKER_01"])
    paths = export_service.write_transcript_exports(
        tmp_path, "aufnahme.mp3", "aufnahme", "20260101_100000", "2026-01-01T10:00:00+01:00",
        "faster-whisper large-v3-turbo", "de", "cuda", 5.0, _sample_segments(), speaker_names,
    )
    new_paths = export_service.reexport_with_new_names(
        paths.json, {"SPEAKER_00": "Klaus Dauderstädt", "SPEAKER_01": "Tom Buhrow"}
    )
    txt_content = new_paths.txt.read_text(encoding="utf-8")
    assert "Klaus Dauderstädt: Hallo zusammen." in txt_content
    assert "Tom Buhrow: Guten Tag." in txt_content
    data = json.loads(new_paths.json.read_text(encoding="utf-8"))
    names = {entry["sprecher_id"]: entry["anzeigename"] for entry in data["sprecher_zuordnung"]}
    assert names["SPEAKER_00"] == "Klaus Dauderstädt"


def test_write_transcript_exports_with_diarization_disabled_omits_speakers(tmp_path):
    segments_without_speaker = [
        {"nummer": 1, "start": 2.78, "end": 17.18, "sprecher_id": None, "text": "Hallo zusammen."},
        {"nummer": 2, "start": 35.3, "end": 37.16, "sprecher_id": None, "text": "Guten Tag."},
    ]
    paths = export_service.write_transcript_exports(
        tmp_path,
        "aufnahme.mp3",
        "aufnahme",
        "20260101_100000",
        "2026-01-01T10:00:00+01:00",
        "faster-whisper large-v3-turbo",
        "de",
        "cpu",
        5.0,
        segments_without_speaker,
        {},
        False,
    )
    data = json.loads(paths.json.read_text(encoding="utf-8"))
    assert data["sprechertrennung_aktiv"] is False
    assert data["anzahl_sprecher"] == 0
    assert data["sprecher_zuordnung"] == []

    txt_content = paths.txt.read_text(encoding="utf-8")
    assert "OHNE SPRECHERTRENNUNG" in txt_content
    assert "Sprechertrennung: deaktiviert" in txt_content
    assert "[00:00:02.780 --> 00:00:17.180] Hallo zusammen." in txt_content
    assert "Sprecher unbekannt" not in txt_content


def test_render_protocol_markdown_includes_sections():
    protocol = {
        "titel": "Wochenmeeting",
        "kurzzusammenfassung": "Kurzfassung.",
        "entscheidungen": [{"entscheidung": "Budget freigegeben", "sprecher": "Sprecher 1", "zeitpunkt": "", "quelle": "00:05:00"}],
        "aufgaben": [{"aufgabe": "Bericht schreiben", "verantwortlich": "Sprecher 2", "frist": "Freitag", "quelle": "00:10:00"}],
        "termine": [],
        "offene_fragen": ["Wer uebernimmt die Praesentation?"],
        "wichtige_fakten": [],
        "unsichere_transkriptstellen": [],
        "quellenhinweise": [],
        "themen": [],
    }
    markdown = export_service.render_protocol_markdown(protocol)
    assert "# Wochenmeeting" in markdown
    assert "Budget freigegeben" in markdown
    assert "Bericht schreiben" in markdown
    assert "Wer uebernimmt die Praesentation?" in markdown


# ---------------------------------------------------------------------------
# Anonyme Ausgabe (Sprechertrennung abgeschaltet)
# ---------------------------------------------------------------------------
def _anonyme_segmente():
    return export_service.attach_speaker_names(
        [{"nummer": 1, "start": 0.0, "end": 2.0, "sprecher_id": None, "text": "Hallo Welt."}], {}
    )


def test_srt_ohne_sprechertrennung_nennt_keinen_sprecher():
    # Die TXT-Datei verspricht im Kopf "kein Sprecherbezug enthalten" -
    # dann darf in den Untertiteln nicht vor jedem Satz "Sprecher
    # unbekannt:" stehen.
    inhalt = export_service.build_srt_content(_anonyme_segmente(), diarization_enabled=False)
    assert "Sprecher" not in inhalt
    assert inhalt.endswith("Hallo Welt.\n\n")


def test_vtt_ohne_sprechertrennung_nennt_keinen_sprecher():
    inhalt = export_service.build_vtt_content(_anonyme_segmente(), diarization_enabled=False)
    assert "Sprecher" not in inhalt
    assert "Hallo Welt." in inhalt


def test_srt_mit_sprechertrennung_nennt_den_sprecher_weiterhin():
    segmente = export_service.attach_speaker_names(
        _sample_segments()[:1], {"SPEAKER_00": "Anna"}
    )
    inhalt = export_service.build_srt_content(segmente, diarization_enabled=True)
    assert "Anna: Hallo zusammen." in inhalt


def test_export_reicht_die_einstellung_bis_in_srt_und_vtt(tmp_path):
    # Vollstaendiger Weg durch write_transcript_exports: frueher kannten
    # nur TXT und JSON die Einstellung.
    pfade = export_service.write_transcript_exports(
        tmp_path,
        "aufnahme.mp3",
        "aufnahme",
        "20260101_120000",
        "2026-01-01T12:00:00+01:00",
        "faster-whisper large-v3-turbo",
        "de",
        "Testhardware",
        12.5,
        [{"nummer": 1, "start": 0.0, "end": 2.0, "sprecher_id": None, "text": "Hallo Welt."}],
        {},
        diarization_enabled=False,
    )

    assert "Sprecher" not in pfade.srt.read_text(encoding="utf-8")
    assert "Sprecher" not in pfade.vtt.read_text(encoding="utf-8")
    assert "kein Sprecherbezug enthalten" in pfade.txt.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sprechernummern bleiben beim Umbenennen stabil
# ---------------------------------------------------------------------------
def test_umbenennen_eines_sprechers_nummeriert_die_uebrigen_nicht_um():
    # Wer einen von drei Sprechern benennt, muss die anderen beiden
    # danach unter denselben Nummern wiederfinden.
    ohne = export_service.build_speaker_names(["S0", "S1", "S2"])
    assert ohne == {"S0": "Sprecher 1", "S1": "Sprecher 2", "S2": "Sprecher 3"}

    mit = export_service.build_speaker_names(["S0", "S1", "S2"], {"S0": "Anna"})
    assert mit == {"S0": "Anna", "S1": "Sprecher 2", "S2": "Sprecher 3"}


def test_umbenennen_in_der_mitte_laesst_die_nummern_stehen():
    namen = export_service.build_speaker_names(["S0", "S1", "S2"], {"S1": "Bernd"})
    assert namen == {"S0": "Sprecher 1", "S1": "Bernd", "S2": "Sprecher 3"}


def test_leerer_name_gilt_nicht_als_vergeben():
    namen = export_service.build_speaker_names(["S0", "S1"], {"S0": "   "})
    assert namen == {"S0": "Sprecher 1", "S1": "Sprecher 2"}


def test_reexport_behaelt_die_nummern_der_nicht_benannten_sprecher(tmp_path):
    segmente = [
        {"nummer": 1, "start": 0.0, "end": 1.0, "sprecher_id": "SPEAKER_00", "text": "eins"},
        {"nummer": 2, "start": 1.0, "end": 2.0, "sprecher_id": "SPEAKER_01", "text": "zwei"},
        {"nummer": 3, "start": 2.0, "end": 3.0, "sprecher_id": "SPEAKER_02", "text": "drei"},
    ]
    pfade = export_service.write_transcript_exports(
        tmp_path,
        "aufnahme.mp3",
        "aufnahme",
        "20260101_120000",
        "2026-01-01T12:00:00+01:00",
        "faster-whisper large-v3-turbo",
        "de",
        "Testhardware",
        1.0,
        segmente,
        export_service.build_speaker_names(["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]),
    )

    neu = export_service.reexport_with_new_names(pfade.json, {"SPEAKER_00": "Anna"})
    inhalt = neu.txt.read_text(encoding="utf-8")

    assert "Anna: eins" in inhalt
    assert "Sprecher 2: zwei" in inhalt
    assert "Sprecher 3: drei" in inhalt
