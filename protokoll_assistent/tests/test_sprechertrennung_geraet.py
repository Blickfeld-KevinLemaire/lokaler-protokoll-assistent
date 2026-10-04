"""Sprechertrennung unter Windows standardmaessig auf der CPU (Schutz vor dem
HYPERVISOR_ERROR-Absturz, siehe model_service.geraet_fuer_sprechertrennung)."""

import pytest

from protokoll_assistent.services import model_service

VARIABLE = model_service.SPRECHERTRENNUNG_GPU_VARIABLE


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(model_service.sys, "platform", "win32")
    monkeypatch.delenv(VARIABLE, raising=False)


def test_unter_windows_rechnet_pyannote_ohne_freigabe_auf_der_cpu(windows):
    assert model_service.geraet_fuer_sprechertrennung("cuda") == "cpu"


@pytest.mark.parametrize(("wert", "erwartet"), [("1", "cuda"), (" 1 ", "cuda"), ("0", "cpu"), ("ja", "cpu"), ("", "cpu")])
def test_gpu_nur_mit_ausdruecklicher_freigabe(windows, monkeypatch, wert, erwartet):
    monkeypatch.setenv(VARIABLE, wert)
    assert model_service.geraet_fuer_sprechertrennung("cuda") == erwartet


def test_cpu_bleibt_cpu(windows, monkeypatch):
    monkeypatch.setenv(VARIABLE, "1")
    assert model_service.geraet_fuer_sprechertrennung("cpu") == "cpu"


def test_linux_behaelt_die_gpu(monkeypatch):
    # Servermodus im Container: dort gibt es den Windows-Hypervisor nicht.
    monkeypatch.setattr(model_service.sys, "platform", "linux")
    monkeypatch.delenv(VARIABLE, raising=False)
    assert model_service.geraet_fuer_sprechertrennung("cuda") == "cuda"


def test_gpu_speicher_freigeben_ohne_torch_ist_harmlos():
    model_service.gpu_speicher_freigeben()  # in der Entwicklungsumgebung gibt es kein torch
