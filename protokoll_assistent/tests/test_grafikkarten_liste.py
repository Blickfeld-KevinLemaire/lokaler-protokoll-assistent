"""Liste der Grafikkarten ausser NVIDIA: ROCm-Ziele, Intel Arc, Prozessorgrafik."""

import pytest

from protokoll_assistent.services import grafikkarten_liste as gl


@pytest.mark.parametrize(
    ("name", "ziel"),
    [
        ("AMD Radeon RX 9070 XT", "gfx1201"),
        ("AMD Radeon RX 9070", "gfx1201"),
        ("AMD Radeon RX 9070 GRE", "gfx1201"),
        ("AMD Radeon AI PRO R9700", "gfx1201"),
        ("AMD Radeon RX 9060 XT", "gfx1200"),
        ("AMD Radeon RX 7900 XTX", "gfx1100"),
        ("AMD Radeon PRO W7800", "gfx1100"),
        ("AMD Radeon RX 7800 XT", "gfx1101"),
        ("AMD Radeon RX 7700", "gfx1101"),
        ("AMD Radeon RX 7600 XT", "gfx1102"),
        ("AMD Radeon RX 7600S", "gfx1102"),
        ("AMD Radeon RX 6950 XT", "gfx1030"),
        ("AMD Radeon RX 6800", "gfx1030"),
        ("AMD Radeon(TM) 890M Graphics", "gfx1150"),
        ("AMD Radeon(TM) 8060S Graphics", "gfx1151"),
        # nicht in der ROCm-Liste (Ollama nutzt sie ueber Vulkan)
        ("AMD Radeon RX 6800S", None),  # anderer Chip (gfx1032) als die RX 6800
        ("AMD Radeon RX 6700 XT", None),
        ("AMD Radeon RX 580", None),
        ("AMD Radeon(TM) 780M Graphics", None),
        ("AMD Radeon(TM) Graphics", None),
        (None, None),
        ("", None),
    ],
)
def test_kartenname_wird_seinem_rocm_ziel_zugeordnet(name, ziel):
    assert gl.gfx_ziel(name) == ziel


def test_transkription_nur_wo_auch_amds_bibliotheken_kernel_haben():
    # CTranslate2 kennt gfx1030, AMDs rocBLAS fuer Windows aber nicht: RX 6800 nur fuer Ollama.
    assert gl.ollama_rocm("AMD Radeon RX 6800 XT")
    assert not gl.whisper_rocm("AMD Radeon RX 6800 XT")
    assert gl.whisper_rocm("AMD Radeon RX 9070 XT") and gl.ollama_rocm("AMD Radeon RX 9070 XT")
    assert gl.WHISPER_ROCM_ZIELE <= gl.OLLAMA_ROCM_ZIELE


@pytest.mark.parametrize(
    ("name", "einzelkarte"),
    [
        ("Intel(R) Arc(TM) A770 Graphics", True),
        ("Intel(R) Arc(TM) A380 Graphics", True),
        ("Intel(R) Arc(TM) A770M Graphics", True),
        ("Intel(R) Arc(TM) B580 Graphics", True),
        ("Intel(R) Arc(TM) Pro B60 Graphics", True),
        ("Intel(R) Arc(TM) Graphics", False),  # Meteor Lake: Prozessorgrafik
        ("Intel(R) Arc(TM) 140V GPU (16GB)", False),  # Lunar Lake
        ("Intel(R) Arc(TM) B390 GPU", False),  # Panther Lake
        ("Intel(R) Iris(R) Xe Graphics", False),
        (None, False),
    ],
)
def test_intel_arc_einzelkarte_oder_prozessorgrafik(name, einzelkarte):
    assert gl.ist_intel_arc_einzelkarte(name) is einzelkarte


@pytest.mark.parametrize(
    ("name", "nutzbar"),
    [
        ("Intel(R) Arc(TM) Graphics", True),
        ("Intel(R) Arc(TM) 140V GPU (16GB)", True),
        ("Intel(R) Arc(TM) 130V GPU (8GB)", True),
        ("Intel(R) Arc(TM) 140T GPU (16GB)", True),
        ("Intel(R) Arc(TM) B390 GPU", True),
        ("Intel(R) Iris(R) Xe Graphics", False),
        ("Intel(R) UHD Graphics 770", False),
        ("AMD Radeon(TM) 780M Graphics", True),
        ("AMD Radeon(TM) 680M", True),
        ("AMD Radeon(TM) 890M Graphics", True),
        ("AMD Radeon(TM) 8060S Graphics", True),
        ("AMD Radeon(TM) Graphics", False),  # Vega oder die kleine RDNA-2-Grafik der Desktop-Ryzen
        ("AMD Radeon(TM) Vega 8 Graphics", False),
        (None, False),
    ],
)
def test_nutzbare_prozessorgrafik(name, nutzbar):
    assert gl.ist_nutzbare_prozessorgrafik(name) is nutzbar
