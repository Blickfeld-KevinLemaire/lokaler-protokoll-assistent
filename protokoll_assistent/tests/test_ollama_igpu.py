"""Prozessorgrafik und Vulkan-Karten fuer Ollama freischalten (OLLAMA_IGPU_ENABLE, OLLAMA_VULKAN) -- ohne
Registry, ohne Ollama."""

import pytest

from protokoll_assistent.services import ollama_einrichtung_service as oes
from protokoll_assistent.services import ollama_service

# Vor dem Ersetzen durch conftest festgehalten.
ECHTE_FREIGABE = ollama_service.braucht_igpu_freigabe

STRIX_HALO = [("AMD Radeon(TM) 8060S Graphics", 64.0)]


@pytest.mark.parametrize(
    ("karten", "erwartet"),
    [
        (STRIX_HALO, True),
        ([("AMD Radeon(TM) 890M Graphics", 8.0)], True),
        ([("AMD Radeon(TM) 890M Graphics", 0.5)], False),  # zu wenig zugewiesen
        ([("AMD Radeon(TM) 890M Graphics", 8.0), ("AMD Radeon RX 7800 XT", 16.0)], False),  # die Einzelkarte rechnet
        ([("AMD Radeon(TM) 780M Graphics", 8.0)], True),  # ueber Vulkan
        ([("Intel(R) Arc(TM) 140V GPU (16GB)", 0.1)], True),  # rechnet im geteilten Arbeitsspeicher
        ([("Intel(R) Iris(R) Xe Graphics", 0.1)], False),
        ([("AMD Radeon RX 9070 XT", 16.0)], False),  # keine Prozessorgrafik: Ollama nutzt sie ohnehin
        ([], False),
    ],
)
def test_freigabe_nur_fuer_nutzbare_prozessorgrafik_als_beste_karte(karten, erwartet):
    assert ECHTE_FREIGABE(lambda: karten, lambda: 32.0) is erwartet


def test_umgebung_fuer_den_dienst(monkeypatch):
    monkeypatch.setattr(ollama_service, "braucht_igpu_freigabe", lambda karten_fn=None, ram_fn=None: True)
    assert ollama_service.umgebung_fuer_dienst({"PATH": "x"}) == {"PATH": "x", "OLLAMA_IGPU_ENABLE": "1"}
    # Eine eigene Vorgabe des Anwenders bleibt.
    assert ollama_service.umgebung_fuer_dienst({"OLLAMA_IGPU_ENABLE": "0"}) == {"OLLAMA_IGPU_ENABLE": "0"}
    monkeypatch.setattr(ollama_service, "braucht_igpu_freigabe", lambda karten_fn=None, ram_fn=None: False)
    assert ollama_service.umgebung_fuer_dienst({"PATH": "x"}) == {"PATH": "x"}


def test_vulkan_fuer_karten_ausserhalb_von_cuda_und_rocm():
    def umgebung(karte):
        return ollama_service.umgebung_fuer_dienst({}, lambda: [karte], lambda: 32.0)

    assert umgebung(("Intel(R) Arc(TM) B580 Graphics", 12.0)) == {"OLLAMA_VULKAN": "1"}
    assert umgebung(("AMD Radeon RX 6700 XT", 12.0)) == {"OLLAMA_VULKAN": "1"}
    assert umgebung(("AMD Radeon(TM) 780M Graphics", 8.0)) == {"OLLAMA_IGPU_ENABLE": "1", "OLLAMA_VULKAN": "1"}
    assert umgebung(("AMD Radeon RX 9070 XT", 16.0)) == {}  # ROCm
    assert umgebung(("NVIDIA GeForce RTX 4070", 12.0)) == {}  # CUDA
    assert ollama_service.umgebung_fuer_dienst({"OLLAMA_VULKAN": "0"}, lambda: [("AMD Radeon RX 6700 XT", 12.0)]) == {
        "OLLAMA_VULKAN": "0"
    }


def test_dienst_startet_mit_der_umgebung(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_service, "AUTO_START", True)
    monkeypatch.setattr(ollama_service, "braucht_igpu_freigabe", lambda karten_fn=None, ram_fn=None: True)
    monkeypatch.setattr(ollama_service._start, "letzter_versuch", None)
    aufrufe = []
    laeuft = iter([False, False, True])
    ollama_service.dienst_starten(
        ausfuehrbar_fn=lambda: tmp_path / "ollama.exe",
        popen_fn=lambda befehl, **kwargs: aufrufe.append(kwargs),
        laeuft_fn=lambda *a: next(laeuft),
        schlafen_fn=lambda s: None,
        warten=5,
    )
    assert aufrufe[0]["env"]["OLLAMA_IGPU_ENABLE"] == "1"


def test_dauerhaft_freischalten(monkeypatch):
    # Die Funktion setzt die Variable auch im eigenen Prozess; so raeumt monkeypatch sie hinterher wieder weg.
    monkeypatch.setenv("OLLAMA_IGPU_ENABLE", "")
    gesetzt, meldungen = [], []
    freigeschaltet = oes.igpu_freischalten(
        meldungen.append, braucht_fn=lambda: True, setze_fn=lambda n, w: gesetzt.append((n, w))
    )
    assert freigeschaltet
    assert gesetzt == [("OLLAMA_IGPU_ENABLE", "1")]
    assert any("Prozessorgrafik" in m for m in meldungen)
    # Schon gesetzt: nichts mehr zu tun.
    assert not oes.igpu_freischalten(meldungen.append, braucht_fn=lambda: True, setze_fn=lambda n, w: pytest.fail())


def test_freischalten_unnoetig_oder_gescheitert(monkeypatch):
    assert not oes.igpu_freischalten(print, braucht_fn=lambda: False, setze_fn=lambda n, w: pytest.fail())

    def verweigert(name, wert):
        raise OSError("Zugriff verweigert")

    monkeypatch.setenv("OLLAMA_IGPU_ENABLE", "")
    meldungen: list[str] = []
    assert not oes.igpu_freischalten(meldungen.append, braucht_fn=lambda: True, setze_fn=verweigert)
    assert "Zugriff verweigert" in meldungen[0]


def test_laufendes_ollama_muss_einmal_neu_starten():
    meldungen: list[str] = []
    status = oes.OllamaStatus(installiert=True, pfad=None, version="0.40.16", dienst_laeuft=True)
    assert oes.installiere_ollama(None, meldungen.append, status_fn=lambda: status, igpu_fn=lambda log: True)
    assert any("einmal beenden" in m for m in meldungen)
