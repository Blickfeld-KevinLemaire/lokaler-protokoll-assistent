"""Tests fuer die Whisper-Modellempfehlung und die Speicherwarnung.

Reine Entscheidungslogik (keine echte Hardware/kein Torch noetig).

Seit den Messungen vom 19.09.2026 wird IMMER 'large-v3-turbo' empfohlen:
Es weicht nur 5,2 % von 'large-v3' ab, braucht 2,26 statt 5,29 GB und
laeuft selbst ohne Grafikkarte mit 3,8-facher Echtzeit. Reicht der
Speicher knapp nicht, gibt es einen Hinweis statt eines stillen Wechsels
auf ein schwaecheres Modell."""

from __future__ import annotations

from protokoll_assistent.services import model_service


def test_whisper_modelle_katalog_ist_absteigend_nach_anspruch_sortiert():
    anspruch = [option.min_vram_gb for option in model_service.WHISPER_MODELLE]
    assert anspruch == sorted(anspruch, reverse=True)


def test_whisper_modelle_katalog_hat_eindeutige_ids():
    ids = [option.id for option in model_service.WHISPER_MODELLE]
    assert len(ids) == len(set(ids))


def test_empfehlung_ist_immer_turbo_unabhaengig_von_der_hardware():
    # Von der dicksten Karte bis zum Rechner ohne Grafikkarte: immer Turbo.
    faelle = [(24.0, 64.0), (8.0, 32.0), (6.0, 16.0), (1.5, 8.0), (0.1, 4.0),
              (None, 32.0), (None, 8.0), (None, None), (0.0, 32.0)]
    for vram, ram in faelle:
        assert model_service.empfehle_whisper_modell(vram, ram) == "large-v3-turbo", (vram, ram)


def test_empfehlung_entspricht_der_dokumentierten_standardkonstante():
    # Frueher widersprachen sich beide: die Konstante sagte Turbo, die
    # Heuristik empfahl ab 10 GB 'large-v3'.
    assert model_service.empfehle_whisper_modell(24.0, 64.0) == model_service.WHISPER_MODEL_NAME


def test_keine_warnung_wenn_der_grafikspeicher_reicht():
    assert model_service.speicherwarnung(6.0, 32.0) is None


def test_warnung_wenn_der_grafikspeicher_knapp_ist():
    warnung = model_service.speicherwarnung(2.0, 32.0)
    assert warnung is not None
    assert "schliessen" in warnung
    assert "small" in warnung


def test_keine_warnung_wenn_der_arbeitsspeicher_reicht():
    assert model_service.speicherwarnung(None, 16.0) is None


def test_warnung_wenn_der_arbeitsspeicher_knapp_ist():
    warnung = model_service.speicherwarnung(None, 3.0)
    assert warnung is not None
    assert "Arbeitsspeicher" in warnung
    assert "schliessen" in warnung


def test_vorhandene_grafikkarte_hat_vorrang_vor_dem_arbeitsspeicher():
    # Genug VRAM, wenig RAM -> die Transkription laeuft auf der GPU, also
    # ist der Arbeitsspeicher nicht der Engpass.
    assert model_service.speicherwarnung(8.0, 2.0) is None


def test_ohne_jede_angabe_keine_warnung():
    assert model_service.speicherwarnung(None, None) is None


class _FakeCheck:
    def __init__(self, key: str, extra: dict | None = None):
        self.key = key
        self.extra = extra or {}


def test_empfehlung_aus_diagnose_liest_vram_und_ram_aus_den_checks():
    checks = [
        _FakeCheck("python_version"),
        _FakeCheck("vram", {"vram_gb": 8.0}),
        _FakeCheck("ram", {"ram_gb": 32.0}),
    ]
    assert model_service.whisper_empfehlung_aus_diagnose(checks) == "large-v3-turbo"


def test_empfehlung_aus_diagnose_ohne_vram_check_bleibt_turbo():
    checks = [_FakeCheck("ram", {"ram_gb": 32.0})]
    assert model_service.whisper_empfehlung_aus_diagnose(checks) == "large-v3-turbo"


def test_empfehlung_aus_diagnose_ohne_jeden_hinweis_stuerzt_nicht_ab():
    assert model_service.whisper_empfehlung_aus_diagnose([]) == "large-v3-turbo"


def test_warnung_aus_diagnose_liest_die_werte_aus_den_checks():
    checks = [_FakeCheck("vram", {"vram_gb": 1.0}), _FakeCheck("ram", {"ram_gb": 32.0})]
    warnung = model_service.speicherwarnung_aus_diagnose(checks)
    assert warnung is not None and "1.0 GB" in warnung


def test_warnung_aus_diagnose_ohne_checks_ist_still():
    assert model_service.speicherwarnung_aus_diagnose([]) is None


def test_get_whisper_model_option_findet_bekanntes_modell():
    option = model_service.get_whisper_model_option("large-v3-turbo")
    assert option is not None
    assert option.id == "large-v3-turbo"


def test_get_whisper_model_option_liefert_none_fuer_unbekanntes_modell():
    assert model_service.get_whisper_model_option("kein-solches-modell") is None
