"""Tests fuer die Geraetewahl in ``services.model_service``.

Hintergrund: ``torch.cuda.is_available()`` allein ist keine verlaessliche
Aussage. Passt der installierte CUDA-Build nicht zur Kartengeneration,
meldet es ``True``, und erst die erste echte Rechnung scheitert. Genau das
wurde am 19.09.2026 auf einer Blackwell-Karte gemessen. Die Tests hier
bilden beide Faelle mit einem eingeschobenen Torch-Ersatz nach -- ohne
echtes PyTorch und ohne GPU.
"""

from __future__ import annotations

import sys

import pytest

from protokoll_assistent.services import model_service


class _CudaAttrappe:
    def __init__(self, verfuegbar: bool, rechnen_klappt: bool) -> None:
        self._verfuegbar = verfuegbar
        self._rechnen_klappt = rechnen_klappt

    def is_available(self) -> bool:
        return self._verfuegbar

    def get_device_name(self, _index: int) -> str:
        return "Testkarte 9000"


class _Tensor:
    def __init__(self, klappt: bool) -> None:
        self._klappt = klappt

    def __add__(self, _anderes):
        if not self._klappt:
            raise RuntimeError(
                "CUDA error: no kernel image is available for execution on the device"
            )
        return self

    def sum(self):
        return self

    def item(self) -> float:
        return 0.0


class _TorchAttrappe:
    def __init__(self, verfuegbar: bool = True, rechnen_klappt: bool = True) -> None:
        self.cuda = _CudaAttrappe(verfuegbar, rechnen_klappt)
        self._rechnen_klappt = rechnen_klappt

    def zeros(self, *_groesse, device: str | None = None):
        return _Tensor(self._rechnen_klappt)


@pytest.fixture
def torch_ersatz(monkeypatch):
    def einsetzen(verfuegbar: bool = True, rechnen_klappt: bool = True):
        monkeypatch.setitem(
            sys.modules, "torch", _TorchAttrappe(verfuegbar, rechnen_klappt)
        )

    return einsetzen


def test_gpu_wird_genutzt_wenn_sie_wirklich_rechnet(torch_ersatz):
    torch_ersatz(verfuegbar=True, rechnen_klappt=True)
    assert model_service.cuda_kann_wirklich_rechnen() is True
    assert model_service.get_device_and_compute_type("cuda") == ("cuda", "float16")


def test_cpu_wenn_cuda_meldet_ja_aber_nicht_rechnen_kann(torch_ersatz):
    # Der Fall, der auf einer Blackwell-Karte mit cu126-Build auftritt.
    torch_ersatz(verfuegbar=True, rechnen_klappt=False)
    assert model_service.cuda_kann_wirklich_rechnen() is False
    assert model_service.get_device_and_compute_type("cuda") == ("cpu", "int8")


def test_cpu_wenn_keine_cuda_karte_da_ist(torch_ersatz):
    torch_ersatz(verfuegbar=False)
    assert model_service.get_device_and_compute_type("cuda") == ("cpu", "int8")


def test_cpu_wenn_ausdruecklich_cpu_angefordert(torch_ersatz):
    torch_ersatz(verfuegbar=True, rechnen_klappt=True)
    assert model_service.get_device_and_compute_type("cpu") == ("cpu", "int8")


def test_ohne_torch_kein_absturz(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert model_service.cuda_kann_wirklich_rechnen() is False
    assert model_service.get_device_and_compute_type("cuda") == ("cpu", "int8")


def test_beschreibung_nennt_den_kartennamen(torch_ersatz):
    torch_ersatz(verfuegbar=True, rechnen_klappt=True)
    assert model_service.get_gpu_description() == "Testkarte 9000"


def test_beschreibung_erklaert_unbenutzbare_karte(torch_ersatz):
    torch_ersatz(verfuegbar=True, rechnen_klappt=False)
    beschreibung = model_service.get_gpu_description()
    assert "Testkarte 9000" in beschreibung
    assert "nicht benutzbar" in beschreibung
    assert "CPU" in beschreibung


def test_beschreibung_ohne_karte(torch_ersatz):
    # Deckt auch AMD-/Intel-Karten ab: Sie landen hier, weil die
    # Beschleunigung ueber CUDA laeuft. Die Meldung soll das erklaeren,
    # statt nur "keine GPU" zu behaupten.
    torch_ersatz(verfuegbar=False)
    beschreibung = model_service.get_gpu_description()
    assert "NVIDIA" in beschreibung
    assert "CPU" in beschreibung
