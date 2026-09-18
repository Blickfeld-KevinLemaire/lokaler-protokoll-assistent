"""Tests fuer die hardwarebasierte Whisper-Modellempfehlung.

Reine Entscheidungslogik (keine echte Hardware/kein Torch noetig) -- die
Empfehlung soll bei mehr erkannter GPU-/VRAM-Leistung ein staerkeres
Modell vorschlagen, bei weniger Leistung ein genuegsameres, und bei reinem
CPU-Betrieb (kein VRAM erkannt) auf die RAM-Menge ausweichen."""

from __future__ import annotations

from services import model_service


def test_whisper_modelle_katalog_ist_absteigend_nach_anspruch_sortiert():
    anspruch = [option.min_vram_gb for option in model_service.WHISPER_MODELLE]
    assert anspruch == sorted(anspruch, reverse=True)


def test_whisper_modelle_katalog_hat_eindeutige_ids():
    ids = [option.id for option in model_service.WHISPER_MODELLE]
    assert len(ids) == len(set(ids))


def test_empfehlung_bei_viel_vram_ist_das_staerkste_modell():
    assert model_service.empfehle_whisper_modell(24.0, None) == "large-v3"


def test_empfehlung_bei_mittlerem_vram_ist_turbo_variante():
    assert model_service.empfehle_whisper_modell(8.0, None) == "large-v3-turbo"


def test_empfehlung_bei_wenig_vram_ist_ein_kleines_modell():
    assert model_service.empfehle_whisper_modell(1.5, None) == "base"


def test_empfehlung_bei_sehr_wenig_vram_ist_das_kleinste_modell():
    assert model_service.empfehle_whisper_modell(0.1, None) == "tiny"


def test_empfehlung_ohne_gpu_aber_viel_ram_ist_small():
    assert model_service.empfehle_whisper_modell(None, 32.0) == "small"


def test_empfehlung_ohne_gpu_und_wenig_ram_ist_base():
    assert model_service.empfehle_whisper_modell(None, 8.0) == "base"


def test_empfehlung_ohne_jegliche_information_faellt_sicher_auf_base_zurueck():
    assert model_service.empfehle_whisper_modell(None, None) == "base"


def test_empfehlung_null_vram_wird_wie_kein_gpu_behandelt():
    # torch.cuda.get_device_properties liefert nie exakt 0, aber die
    # Funktion soll auch mit diesem Randfall nicht abstuerzen.
    assert model_service.empfehle_whisper_modell(0.0, 32.0) == "small"


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


def test_empfehlung_aus_diagnose_ohne_vram_check_faellt_auf_ram_zurueck():
    checks = [_FakeCheck("ram", {"ram_gb": 32.0})]
    assert model_service.whisper_empfehlung_aus_diagnose(checks) == "small"


def test_empfehlung_aus_diagnose_ohne_jeden_hinweis_stuerzt_nicht_ab():
    assert model_service.whisper_empfehlung_aus_diagnose([]) == "base"


def test_get_whisper_model_option_findet_bekanntes_modell():
    option = model_service.get_whisper_model_option("large-v3-turbo")
    assert option is not None
    assert option.id == "large-v3-turbo"


def test_get_whisper_model_option_liefert_none_fuer_unbekanntes_modell():
    assert model_service.get_whisper_model_option("kein-solches-modell") is None
