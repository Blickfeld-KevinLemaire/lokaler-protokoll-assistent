"""Welche Grafikkarten ausser NVIDIA unter Windows beschleunigen -- und wobei.

Zwei Wege, abgelesen bzw. gemessen am 18.11.2026:

**ROCm (AMD)** -- Ollama und die Transkription. Die Liste stammt nicht aus
Ollamas Dokumentation (die fuehrt fuer Windows nur RX 7000 und PRO W7000),
sondern aus dem, wofuer die mitgelieferten Bibliotheken uebersetzt sind:

* Ollama 0.40.16 (signiert von Ollama Inc.), ``lib/ollama/rocm_v7_1/ggml-hip.dll``:
  gfx1030, gfx1100-1102, gfx1150/1151, gfx1200/1201.
* Transkription: CTranslate2 4.9.0 (ROCm-Raeder) ist fuer gfx1030-1035,
  gfx1100-1103, gfx1150/1151, gfx1200/1201 gebaut; AMDs ROCm-7.2.1-Bibliotheken
  fuer Windows bringen aber nur Kernel fuer gfx1100-1102, gfx1150/1151 und
  gfx1200/1201 mit. Es gilt die Schnittmenge. Gemessen auf einer RX 9070 XT:
  large-v3-turbo in 18-facher Echtzeit, Wort fuer Wort derselbe Text wie auf der CPU.

**Vulkan** -- nur Ollama. Ollama bringt unter Windows ein Vulkan-Backend mit und
nutzt es fuer jede Karte, die ROCm/CUDA nicht abdecken: aeltere und kleinere
Radeon-Karten, Intel Arc und Prozessorgrafik. Gemessen auf derselben RX 9070 XT
mit abgeschaltetem ROCm: Qwen 4B und 9B liefen vollstaendig auf der Karte, beim
Lesen eines 8.000-Token-Transkripts gleich schnell wie mit ROCm, beim Schreiben
10-30 % schneller. Auf Intel-Hardware ist das NICHT gemessen; Berichte nennen
Abstuerze und Rueckfaelle auf den Prozessor mit einzelnen Arc-Treibern.

Prozessorgrafik verwirft Ollama, solange ``OLLAMA_IGPU_ENABLE`` nicht gesetzt ist
(siehe ``ollama_service.umgebung_fuer_dienst``). Nutzbar ist nur moderne
Prozessorgrafik (AMD RDNA 2 und neuer, Intel Arc); Intel UHD/Iris Xe und aeltere
Vega-Grafik bringen gegenueber dem Prozessor nichts.

Die Sprechertrennung (pyannote/PyTorch) rechnet ausser auf NVIDIA immer auf dem
Prozessor: PyTorch fuer AMD gibt es unter Windows nur als Vorschau fuer Python 3.12.

**Pflege:** Mit einer neuen Ollama- oder ROCm-Fassung die gfx-Listen neu ablesen
(``amdgcn-amd-amdhsa--gfx...`` in den DLLs) und ``STAND`` anpassen.
"""

from __future__ import annotations

import re

STAND = "18.11.2026"

OLLAMA_ROCM_ZIELE = frozenset({"gfx1030", "gfx1100", "gfx1101", "gfx1102", "gfx1150", "gfx1151", "gfx1200", "gfx1201"})
WHISPER_ROCM_ZIELE = frozenset({"gfx1100", "gfx1101", "gfx1102", "gfx1150", "gfx1151", "gfx1200", "gfx1201"})

# Kartenname (so, wie Windows ihn meldet) -> LLVM-Ziel. Die Muster sind auf
# Kleinbuchstaben ohne "(TM)"/"(R)" geschrieben. Ein Buchstabe direkt hinter der
# Nummer gehoert zu einem anderen Chip (RX 6800S ist gfx1032, nicht gfx1030).
_ENDE = r"(?![0-9a-z])"
_AMD_ROCM: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(muster), ziel)
    for muster, ziel in (
        # RDNA 4
        (rf"rx 9070( xt| gre)?{_ENDE}", "gfx1201"),
        (rf"ai pro r9700{_ENDE}|r9600d{_ENDE}", "gfx1201"),
        (rf"rx 9060( xt)?( lp)?{_ENDE}", "gfx1200"),
        # RDNA 3
        (rf"rx 7900( xtx| xt| gre)?{_ENDE}|rx 7900m{_ENDE}|pro w7900|pro w7800", "gfx1100"),
        (rf"rx 7800( xt)?{_ENDE}|rx 7800m{_ENDE}|rx 7700( xt)?{_ENDE}|pro w7700", "gfx1101"),
        (rf"rx 76[05]0( xt| gre)?{_ENDE}|rx 7600[sm]{_ENDE}|rx 7700s{_ENDE}|pro w7600|pro w7500", "gfx1102"),
        # RDNA 2 (nur Ollama)
        (
            rf"rx 6800( xt)?{_ENDE}|rx 6900( xt| xtx)?{_ENDE}|rx 6950( xt)?{_ENDE}|pro w6800|pro w6900x|pro v620",
            "gfx1030",
        ),
        # Ryzen AI (Prozessorgrafik)
        (rf"\b8[89]0m{_ENDE}", "gfx1150"),
        (rf"\b80[4-6]0s{_ENDE}", "gfx1151"),
    )
)

# Prozessorgrafik, die Ollama ueber Vulkan sinnvoll nutzt: AMD RDNA 2/3/3.5 (Radeon 610M-890M, 8040S-8060S)
# und Intel Arc (Meteor Lake "Arc Graphics", Lunar Lake 130V/140V, Arrow Lake 140T, Panther Lake B370/B390).
_AMD_PROZESSORGRAFIK = re.compile(rf"\b(6[1-9]0m|7[0-9]0m|8[0-9]0m|80[4-6]0s){_ENDE}")
_INTEL_ARC_PROZESSORGRAFIK = re.compile(rf"\barc (graphics|1[34]0[vt]|b3[0-9]0){_ENDE}")
# Intel-Arc-Einzelkarten: A310-A770 (auch mobil, "A770M"), B570/B580, Arc Pro A40-A60/B50/B60.
_INTEL_ARC_EINZELKARTE = re.compile(rf"\barc (pro )?(a[3-7][0-9]0m?|b5[0-9]0|[ab][4-6]0){_ENDE}")


def _normalisiert(name: str) -> str:
    klein = name.lower().replace("(tm)", "").replace("(r)", "").replace("™", "")
    return re.sub(r"\s+", " ", klein).strip()


def gfx_ziel(name: str | None) -> str | None:
    """LLVM-Ziel einer AMD-Karte mit ROCm-Unterstuetzung, ``None`` wenn sie nicht in der Liste steht."""
    if not name:
        return None
    text = _normalisiert(name)
    return next((ziel for muster, ziel in _AMD_ROCM if muster.search(text)), None)


def ollama_rocm(name: str | None) -> bool:
    return gfx_ziel(name) in OLLAMA_ROCM_ZIELE


def whisper_rocm(name: str | None) -> bool:
    return gfx_ziel(name) in WHISPER_ROCM_ZIELE


def ist_intel_arc_einzelkarte(name: str | None) -> bool:
    return bool(name) and _INTEL_ARC_EINZELKARTE.search(_normalisiert(name or "")) is not None


def ist_nutzbare_prozessorgrafik(name: str | None) -> bool:
    """Moderne Prozessorgrafik, die Ollama (mit OLLAMA_IGPU_ENABLE) beschleunigt."""
    if not name:
        return False
    text = _normalisiert(name)
    if "intel" in text:
        return _INTEL_ARC_PROZESSORGRAFIK.search(text) is not None
    return _AMD_PROZESSORGRAFIK.search(text) is not None
