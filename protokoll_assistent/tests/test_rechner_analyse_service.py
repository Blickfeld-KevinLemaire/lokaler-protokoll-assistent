"""Tests fuer ``services/rechner_analyse_service.py`` -- ohne Hardware, ohne Programme."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import rechner_analyse_service as ra
from protokoll_assistent.services.rechner_analyse_service import GUT, MAESSIG, NICHT, RechnerProfil


def _stufe(analyse: ra.Analyse, modell_id: str) -> str:
    return next(b.stufe for b in analyse.bewertungen if b.modell_id == modell_id)


# Typische Rechner
SCHWACHER_LAPTOP = RechnerProfil(ram_gb=8, cpu_kerne=4, freier_platz_gb=100)
NORMALER_LAPTOP = RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300)
GAMING_PC = RechnerProfil(ram_gb=32, cpu_kerne=12, gpu_name="RTX 4070", vram_gb=12, freier_platz_gb=500)
ALTER_PC = RechnerProfil(ram_gb=4, cpu_kerne=2, freier_platz_gb=50)


# --------------------------------------------------------------------------
# Hardware ermitteln
# --------------------------------------------------------------------------
def test_profil_aus_austauschbaren_quellen(tmp_path):
    profil = ra.ermittle_profil(
        tmp_path,
        ram_fn=lambda: 15.9,
        gpu_fn=lambda: [("Intel(R) UHD Graphics", 0.1), ("NVIDIA GeForce RTX 3060", 12.0)],
        kerne_fn=lambda: 6,
        platz_fn=lambda ordner: 123.0 if ordner == tmp_path else None,
    )
    # Von mehreren Karten zaehlt die leistungsfaehigste.
    assert profil == RechnerProfil(15.9, 6, "NVIDIA GeForce RTX 3060", 12.0, 123.0)
    assert profil.cuda_gpu


def test_profil_ohne_grafikkarte(tmp_path):
    profil = ra.ermittle_profil(tmp_path, ram_fn=lambda: 8, gpu_fn=list, kerne_fn=lambda: 4, platz_fn=lambda o: 50.0)
    assert profil.gpu_name is None and not profil.hat_grafikkarte and not profil.cuda_gpu


@pytest.mark.parametrize(
    ("name", "hersteller", "integriert"),
    [
        ("NVIDIA GeForce RTX 4070", ra.HERSTELLER_NVIDIA, False),
        ("Quadro T1000", ra.HERSTELLER_NVIDIA, False),
        ("AMD Radeon RX 6600", ra.HERSTELLER_AMD, False),
        ("AMD Radeon PRO W6600", ra.HERSTELLER_AMD, False),
        ("AMD Radeon(TM) Graphics", ra.HERSTELLER_AMD, True),
        ("AMD Radeon 780M Graphics", ra.HERSTELLER_AMD, True),
        ("Intel(R) Arc(TM) A770 Graphics", ra.HERSTELLER_INTEL, False),
        ("Intel(R) UHD Graphics 620", ra.HERSTELLER_INTEL, True),
        ("Intel(R) Iris(R) Xe Graphics", ra.HERSTELLER_INTEL, True),
        ("Irgendeine Karte", ra.HERSTELLER_SONSTIGE, True),
    ],
)
def test_hersteller_und_bauart_nach_dem_namen(name, hersteller, integriert):
    assert ra.gpu_hersteller(name) == hersteller
    assert ra.gpu_ist_integriert(name) is integriert


def test_hersteller_ohne_name():
    assert ra.gpu_hersteller(None) is None
    assert ra.gpu_hersteller("") is None
    assert RechnerProfil().gpu_hersteller is None and not RechnerProfil().gpu_integriert


def test_beste_grafikkarte_wird_gewaehlt():
    nvidia = ("NVIDIA GeForce GTX 1650", 4.0)
    radeon = ("AMD Radeon RX 7900 XT", 20.0)
    onboard = ("Intel(R) UHD Graphics", 2.0)
    assert ra.waehle_grafikkarte([onboard, radeon, nvidia]) == nvidia  # NVIDIA vor der groesseren Radeon
    assert ra.waehle_grafikkarte([onboard, radeon]) == radeon
    assert ra.waehle_grafikkarte([onboard, ("AMD Radeon(TM) Graphics", 1.0)]) == onboard
    assert ra.waehle_grafikkarte([]) is None


def test_nvidia_smi_ausgabe_wird_gelesen():
    assert ra._karten_aus_smi_ausgabe("NVIDIA GeForce RTX 3060, 12288\n") == [("NVIDIA GeForce RTX 3060", 12.0)]
    assert ra._karten_aus_smi_ausgabe("Karte, mit Komma, 8192\nZweite, 4096") == [
        ("Karte, mit Komma", 8.0),
        ("Zweite", 4.0),
    ]
    assert ra._karten_aus_smi_ausgabe("") == []
    assert ra._karten_aus_smi_ausgabe("kaputt, abc") == []
    assert ra._karten_aus_smi_ausgabe(", 1024") == [("NVIDIA", 1.0)]


def test_windows_adapter_mit_speicher_aus_der_registry():
    text = json.dumps(
        {
            "cim": [
                {"Name": "AMD Radeon RX 6600", "AdapterRAM": 4293918720},  # 32 Bit: unbrauchbar
                {"Name": "Intel(R) UHD Graphics", "AdapterRAM": 1073741824},
                {"Name": "Microsoft Basic Display Adapter", "AdapterRAM": 0},
                {"Name": "Parsec Virtual Display Adapter", "AdapterRAM": 0},
                {"Name": None},
                "kein Objekt",
            ],
            "reg": [
                {"DriverDesc": "AMD Radeon RX 6600", "Mem": 8 * 1024**3},
                {"DriverDesc": "Intel(R) UHD Graphics", "Mem": None},
                "kein Objekt",
            ],
        }
    )
    assert ra._karten_aus_powershell_ausgabe(text) == [
        ("AMD Radeon RX 6600", 8.0),
        ("Intel(R) UHD Graphics", 1.0),  # ersatzweise AdapterRAM
    ]


def test_windows_adapter_einzelobjekte_und_bytefolgen():
    # PowerShell liefert ein einzelnes Element als Objekt, manche Treiber den
    # Speicher als Bytefolge (REG_BINARY, little endian).
    sechs_gb = list((6 * 1024**3).to_bytes(8, "little"))
    text = json.dumps({"cim": {"Name": "AMD Radeon RX 6600", "AdapterRAM": None}, "reg": {"DriverDesc": "AMD Radeon RX 6600", "Mem": sechs_gb}})
    assert ra._karten_aus_powershell_ausgabe(text) == [("AMD Radeon RX 6600", 6.0)]


def test_windows_adapter_mit_unbrauchbarer_ausgabe():
    assert ra._karten_aus_powershell_ausgabe("kein json") == []
    assert ra._karten_aus_powershell_ausgabe("[1, 2]") == []
    assert ra._karten_aus_powershell_ausgabe("{}") == []
    assert ra._karten_aus_powershell_ausgabe('{"cim": [{"Name": "Karte", "AdapterRAM": 0}]}') == [("Karte", None)]


def test_keine_grafikkarten_ohne_programme(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: None)
    assert ra._grafikkarten_nvidia_smi() == []
    assert ra._grafikkarten_windows() == []
    assert ra._grafikkarten() == []


class _Lauf:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_grafikkarten_ueber_nvidia_smi(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: name)
    monkeypatch.setattr(ra.subprocess, "run", lambda *a, **k: _Lauf("RTX 4090, 24564\n"))
    name, vram = ra._grafikkarten_nvidia_smi()[0]
    assert name == "RTX 4090" and round(vram or 0) == 24


def test_grafikkarten_ueber_windows(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: name if name == "powershell" else None)
    ausgabe = json.dumps({"cim": [{"Name": "AMD Radeon RX 6600", "AdapterRAM": 0}], "reg": []})
    monkeypatch.setattr(ra.subprocess, "run", lambda *a, **k: _Lauf(ausgabe))
    assert ra._grafikkarten() == [("AMD Radeon RX 6600", None)]


def test_nvidia_wird_nicht_doppelt_gezaehlt(monkeypatch):
    monkeypatch.setattr(ra, "_grafikkarten_nvidia_smi", lambda: [("NVIDIA GeForce RTX 3060", 12.0)])
    monkeypatch.setattr(
        ra,
        "_grafikkarten_windows",
        lambda: [("NVIDIA GeForce RTX 3060", 4.0), ("Intel(R) UHD Graphics", 1.0)],  # AdapterRAM ist ungenau
    )
    assert ra._grafikkarten() == [("NVIDIA GeForce RTX 3060", 12.0), ("Intel(R) UHD Graphics", 1.0)]


def test_nvidia_ohne_smi_kommt_aus_windows(monkeypatch):
    monkeypatch.setattr(ra, "_grafikkarten_nvidia_smi", list)
    monkeypatch.setattr(ra, "_grafikkarten_windows", lambda: [("NVIDIA GeForce GTX 1050", 4.0)])
    assert ra._grafikkarten() == [("NVIDIA GeForce GTX 1050", 4.0)]


@pytest.mark.parametrize("funktion", ["_grafikkarten_nvidia_smi", "_grafikkarten_windows"])
def test_grafikkarten_bei_fehlern_des_programms(monkeypatch, funktion):
    monkeypatch.setattr(ra.shutil, "which", lambda name: name)

    def werfen(*a, **k):
        raise OSError("weg")

    monkeypatch.setattr(ra.subprocess, "run", werfen)
    assert getattr(ra, funktion)() == []

    monkeypatch.setattr(ra.subprocess, "run", lambda *a, **k: _Lauf("x", returncode=9))
    assert getattr(ra, funktion)() == []


def test_freier_platz(tmp_path, monkeypatch):
    assert ra._freier_platz_gb(tmp_path) > 0

    def werfen(pfad):
        raise OSError("weg")

    monkeypatch.setattr(ra.shutil, "disk_usage", werfen)
    assert ra._freier_platz_gb(Path("x")) is None


def test_ram_ueber_psutil_oder_unbekannt(monkeypatch):
    # Auf dem Entwicklungsrechner gibt es psutil; ohne psutil und ohne Windows
    # bleibt der Wert unbekannt, statt zu raten.
    import builtins

    echt = builtins.__import__

    def ohne_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError(name)
        return echt(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", ohne_psutil)
    monkeypatch.delattr(ra.ctypes, "windll", raising=False)
    assert ra._ram_gb() is None


def test_ram_ueber_psutil(monkeypatch):
    import sys
    import types

    attrappe = types.SimpleNamespace(virtual_memory=lambda: types.SimpleNamespace(total=16 * 1024**3))
    monkeypatch.setitem(sys.modules, "psutil", attrappe)
    assert ra._ram_gb() == 16.0


def test_profilbeschreibung():
    text = ra.beschreibe_profil(GAMING_PC)
    assert "32.0 GB" in text and "RTX 4070" in text and "Prozessorkerne: 12" in text
    ohne = ra.beschreibe_profil(RechnerProfil())
    assert "unbekannt" in ohne and "keine erkannt" in ohne and "Freier Platz" not in ohne


# --------------------------------------------------------------------------
# Bewerten
# --------------------------------------------------------------------------
def test_gaming_pc_alles_gut():
    analyse = ra.analysiere(GAMING_PC)
    assert _stufe(analyse, "large-v3") == GUT
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == GUT
    assert analyse.empfehlung[ra.BEREICH_TRANSKRIPTION] == "large-v3-turbo"
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:4b-q4_K_M"
    assert analyse.empfehlung[ra.BEREICH_SUCHE] == "bge-m3"
    assert analyse.hinweise == []


def test_normaler_laptop_ohne_grafikkarte():
    analyse = ra.analysiere(NORMALER_LAPTOP)
    assert _stufe(analyse, "large-v3-turbo") == GUT
    assert _stufe(analyse, "large-v3") == NICHT  # dauert doppelt so lang wie die Aufnahme
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == GUT
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == NICHT
    assert _stufe(analyse, "qwen3.8:27b-q4_K_M") == NICHT
    # Der Standard ist klein genug, um auch auf dem Prozessor gut zu laufen.
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:4b-q4_K_M"
    assert any("Keine Grafikkarte erkannt" in h for h in analyse.hinweise)


def test_schwacher_laptop_mit_vier_kernen():
    analyse = ra.analysiere(SCHWACHER_LAPTOP)
    assert _stufe(analyse, "large-v3-turbo") == GUT  # 3,8 * 0,6 = 2,3-fach
    assert _stufe(analyse, "large-v3") == NICHT
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == MAESSIG  # wenige Kerne
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == NICHT  # 8 GB RAM reichen nicht fuer 8,1 + 3 GB
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:4b-q4_K_M"


def test_mittelgrosses_modell_laeuft_auf_dem_prozessor_nur_maessig(monkeypatch):
    # Die Auswahl hat derzeit nichts zwischen 3,5 und 6 GB; eingetragen werden kann es trotzdem.
    mittel = ra.ollama_service.OllamaModellOption("mittel:8b", "Mittel 8B", 5.0, "")
    monkeypatch.setattr(ra.ollama_service, "OLLAMA_MODELLE", [mittel])
    analyse = ra.analysiere(NORMALER_LAPTOP)
    assert _stufe(analyse, "mittel:8b") == MAESSIG


def test_unter_7_8_gb_gibt_es_kein_lokales_sprachmodell():
    # Der Standard braucht 3,3 + 1,5 + 3 GB; ein kleineres Modell hat die Auswahl nicht mehr.
    analyse = ra.analysiere(RechnerProfil(ram_gb=7.5, cpu_kerne=8))
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == NICHT
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] is None
    assert any("kein lokales Sprachmodell" in h for h in analyse.hinweise)


def test_alter_pc_bekommt_nur_hinweise():
    analyse = ra.analysiere(ALTER_PC)
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] is None
    assert all(_stufe(analyse, o) == NICHT for o in ("qwen3.5:4b-q4_K_M", "gemma4:12b-it-q4_K_M"))
    text = "\n".join(analyse.hinweise)
    assert "knapp ausgestattet" in text
    assert "kein lokales Sprachmodell" in text and "API" in text


def test_transkription_faellt_auf_small_zurueck_wenn_turbo_ausfaellt():
    # 6 GB und 2 Kerne: Turbo laeuft nur ca. 1,1-fach (maessig) -> bleibt die Empfehlung.
    knapp = ra.analysiere(RechnerProfil(ram_gb=6, cpu_kerne=2))
    assert _stufe(knapp, "large-v3-turbo") == MAESSIG
    assert knapp.empfehlung[ra.BEREICH_TRANSKRIPTION] == "large-v3-turbo"
    # Mit 5 GB reicht der Speicher fuer Turbo nicht mehr, fuer 'small' (1,5 GB) schon.
    winzig = ra.analysiere(RechnerProfil(ram_gb=5, cpu_kerne=2))
    assert _stufe(winzig, "large-v3-turbo") == NICHT
    assert winzig.empfehlung[ra.BEREICH_TRANSKRIPTION] == "small"


def test_keine_transkription_moeglich():
    analyse = ra.analysiere(RechnerProfil(ram_gb=2, cpu_kerne=1))
    assert analyse.empfehlung[ra.BEREICH_TRANSKRIPTION] is None
    assert any("Transkription" in h and "API" in h for h in analyse.hinweise)


def test_knapper_grafikspeicher_ist_maessig():
    profil = RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="NVIDIA GeForce GTX 1050", vram_gb=3.5)
    analyse = ra.analysiere(profil)
    assert _stufe(analyse, "large-v3-turbo") == MAESSIG  # 3,0 GB noetig, 4,5 GB fuer "gut"
    assert _stufe(analyse, "large-v3") != GUT  # 6 GB noetig -> weicht auf den Prozessor aus


def test_unbekannter_arbeitsspeicher_wird_nicht_als_zu_wenig_gewertet():
    analyse = ra.analysiere(RechnerProfil(ram_gb=None, cpu_kerne=8))
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == GUT


def test_wenig_platz_wird_gemeldet():
    analyse = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=6))
    assert any("Freier Platz: 6 GB" in h for h in analyse.hinweise)
    genug = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=200))
    assert not any("Freier Platz" in h for h in genug.hinweise)


def test_alle_modelle_der_auswahllisten_werden_bewertet():
    from protokoll_assistent.services import model_service, ollama_service

    analyse = ra.analysiere(NORMALER_LAPTOP)
    erwartet = (
        len(model_service.WHISPER_MODELLE)
        + len(ollama_service.OLLAMA_MODELLE)
        + len(ollama_service.OLLAMA_EMBEDDING_MODELLE)
    )
    assert len(analyse.bewertungen) == erwartet
    assert {b.stufe for b in analyse.bewertungen} <= {GUT, MAESSIG, NICHT}


def test_einbettung_nicht_geeignet_bei_extrem_wenig_speicher():
    analyse = ra.analysiere(RechnerProfil(ram_gb=4.5, cpu_kerne=2))
    assert _stufe(analyse, "bge-m3") == NICHT
    assert _stufe(analyse, "nomic-embed-text") == GUT
    assert analyse.empfehlung[ra.BEREICH_SUCHE] == "nomic-embed-text"


def _ohne_psutil(monkeypatch):
    import builtins

    echt = builtins.__import__

    def sperre(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError(name)
        return echt(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sperre)


def test_ram_ueber_die_windows_schnittstelle(monkeypatch):
    import types

    def fuellen(zeiger):
        zeiger._obj.ullTotalPhys = 8 * 1024**3
        return 1

    windll = types.SimpleNamespace(kernel32=types.SimpleNamespace(GlobalMemoryStatusEx=fuellen))
    monkeypatch.setattr(ra.ctypes, "windll", windll, raising=False)
    _ohne_psutil(monkeypatch)
    assert ra._ram_gb() == 8.0


def test_ram_wenn_die_windows_schnittstelle_versagt(monkeypatch):
    import types

    windll = types.SimpleNamespace(kernel32=types.SimpleNamespace(GlobalMemoryStatusEx=lambda zeiger: 0))
    monkeypatch.setattr(ra.ctypes, "windll", windll, raising=False)
    _ohne_psutil(monkeypatch)
    assert ra._ram_gb() is None


# --------------------------------------------------------------------------
# Grafikkarten anderer Hersteller
# --------------------------------------------------------------------------
RADEON_PC = RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="AMD Radeon RX 6700 XT", vram_gb=12, freier_platz_gb=300)
ONBOARD_LAPTOP = RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="Intel(R) Iris(R) Xe Graphics", vram_gb=0.1, freier_platz_gb=300)


def test_radeon_hilft_der_transkription_nicht():
    # faster-whisper rechnet nur ueber CUDA: Die Radeon aendert an der Transkription nichts.
    mit = ra.analysiere(RADEON_PC)
    ohne = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300))
    for modell in ("large-v3", "large-v3-turbo", "small"):
        assert _stufe(mit, modell) == _stufe(ohne, modell)


def test_radeon_kann_die_nachbearbeitung_beschleunigen_aber_nie_sicher():
    analyse = ra.analysiere(RADEON_PC)
    # 9B passt (6,6 + 1,5 GB) in 12 GB, auf dem Prozessor waere es "nicht".
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == MAESSIG
    text = next(b.text for b in analyse.bewertungen if b.modell_id == "qwen3.5:9b-q4_K_M")
    assert "Radeon" in text and "unterstützt" in text
    # Wo der Prozessor ohnehin gut genug ist, bleibt es bei "gut".
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == GUT
    # Was nicht in den Grafikspeicher passt, wird nicht schoengerechnet.
    klein = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="AMD Radeon RX 6500 XT", vram_gb=4))
    assert _stufe(klein, "qwen3.5:9b-q4_K_M") == NICHT


def test_integrierte_grafik_beschleunigt_nichts():
    analyse = ra.analysiere(ONBOARD_LAPTOP)
    ohne = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300))
    assert [b.stufe for b in analyse.bewertungen] == [b.stufe for b in ohne.bewertungen]
    hinweis = next(h for h in analyse.hinweise if "Iris" in h)
    assert "integriert" in hinweis and "beschleunigt hier nichts" in hinweis


def test_hinweise_je_grafikkarte():
    radeon = "\n".join(ra.analysiere(RADEON_PC).hinweise)
    assert "AMD Radeon RX 6700 XT" in radeon and "nur NVIDIA-Karten" in radeon and "Ollama" in radeon
    arc = "\n".join(
        ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="Intel(R) Arc(TM) A750", vram_gb=8)).hinweise
    )
    assert "Arc" in arc and "nur mit NVIDIA" in arc
    assert not any("Grafik" in h for h in ra.analysiere(GAMING_PC).hinweise)  # NVIDIA: nichts zu bemerken


def test_profilbeschreibung_je_grafikkarte():
    assert "beschleunigt Transkription und Nachbearbeitung" in ra.beschreibe_profil(GAMING_PC)
    assert "je nach Kartenmodell möglich" in ra.beschreibe_profil(RADEON_PC)
    assert "teilt sich den Arbeitsspeicher" in ra.beschreibe_profil(ONBOARD_LAPTOP)
    arc = ra.beschreibe_profil(RechnerProfil(gpu_name="Intel(R) Arc(TM) A750", vram_gb=8))
    assert "wird nicht genutzt" in arc
    ohne_speicher = ra.beschreibe_profil(RechnerProfil(gpu_name="AMD Radeon(TM) Graphics"))
    assert " mit " not in ohne_speicher
