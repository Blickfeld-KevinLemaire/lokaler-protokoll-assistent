"""Tests fuer ``services/rechner_analyse_service.py`` -- ohne Hardware, ohne Programme."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protokoll_assistent.services import rechner_analyse_service as ra
from protokoll_assistent.services.rechner_analyse_service import GUT, MAESSIG, NICHT, RechnerProfil

# Vor dem Ersetzen durch conftest festgehalten (dort liefert die Registry fuer alle Tests keine Karten).
ECHTE_REGISTRY = ra.grafikkarten_aus_registry

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
    # Bei knappem Arbeitsspeicher (8 GB, < 16) ist das leichtere LFM2.5 die
    # realistische lokale Wahl -- beide nur "maessig", darum entscheidet die Reihenfolge.
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"


def test_mittelgrosses_modell_laeuft_auf_dem_prozessor_nur_maessig(monkeypatch):
    # Die Auswahl hat derzeit nichts zwischen 3,5 und 6 GB; eingetragen werden kann es trotzdem.
    mittel = ra.ollama_service.OllamaModellOption("mittel:8b", "Mittel 8B", 5.0, "")
    monkeypatch.setattr(ra.ollama_service, "OLLAMA_MODELLE", [mittel])
    analyse = ra.analysiere(NORMALER_LAPTOP)
    assert _stufe(analyse, "mittel:8b") == MAESSIG


def test_unter_rund_sechs_gb_gibt_es_kein_lokales_sprachmodell():
    # Selbst das kleinste Modell (LFM2.5: 1,6 + 1,5 + 3 GB, also ~6,1 GB) passt
    # darunter nicht mehr; Qwen 4B (3,3 + 1,5 + 3) faellt schon frueher aus.
    analyse = ra.analysiere(RechnerProfil(ram_gb=5.5, cpu_kerne=8))
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == NICHT
    assert _stufe(analyse, "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M") == NICHT
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] is None
    assert any("kein lokales Sprachmodell" in h for h in analyse.hinweise)


def test_lfm_laeuft_mit_16_gb_ohne_grafik_gut():
    analyse = ra.analysiere(NORMALER_LAPTOP)  # 16 GB, 8 Kerne, keine Grafikkarte
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == GUT
    assert _stufe(analyse, "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M") == GUT


def test_kleines_modell_auf_8_gb_ist_nur_maessig():
    # 8 GB, viele Kerne: Nicht die Kerne, sondern der knappe Arbeitsspeicher
    # druecken auf "maessig" (Windows und Programme belegen schon 5-6 GB).
    analyse = ra.analysiere(RechnerProfil(ram_gb=8, cpu_kerne=8, freier_platz_gb=100))
    for modell in ("qwen3.5:4b-q4_K_M", "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"):
        assert _stufe(analyse, modell) == MAESSIG
    text = next(b.text for b in analyse.bewertungen if b.modell_id == "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M")
    assert "Arbeitsspeicher ist knapp" in text


def test_knapper_ram_empfiehlt_lfm_viel_ram_empfiehlt_qwen():
    # 8 GB (< 16) ohne Grafikkarte: beide nur "maessig", das leichtere LFM2.5 wird empfohlen.
    knapp = ra.analysiere(RechnerProfil(ram_gb=8, cpu_kerne=8, freier_platz_gb=100))
    assert knapp.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"
    # 32 GB ohne Grafikkarte: genug Platz, Qwen 4B (beste Qualitaet) wird empfohlen.
    reichlich = ra.analysiere(RechnerProfil(ram_gb=32, cpu_kerne=8, freier_platz_gb=300))
    assert reichlich.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:4b-q4_K_M"


def test_lfm_traegt_die_nachbearbeitung_wo_qwen_nicht_mehr_passt():
    # Zwischen ~6,1 und ~7,8 GB faellt Qwen 4B aus, das leichtere LFM2.5 passt noch.
    analyse = ra.analysiere(RechnerProfil(ram_gb=7, cpu_kerne=8, freier_platz_gb=100))
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == NICHT
    assert _stufe(analyse, "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M") == MAESSIG
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"


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


def test_radeon_ausserhalb_der_rocm_liste_hilft_der_transkription_nicht():
    # CTranslate2 rechnet nur ueber CUDA oder ROCm (Liste): Die RX 6700 XT aendert an der Transkription nichts.
    mit = ra.analysiere(RADEON_PC)
    ohne = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300))
    for modell in ("large-v3", "large-v3-turbo", "small"):
        assert _stufe(mit, modell) == _stufe(ohne, modell)


def test_radeon_ausserhalb_der_rocm_liste_beschleunigt_ollama_ueber_vulkan():
    analyse = ra.analysiere(RADEON_PC)
    assert RADEON_PC.ollama_gpu and RADEON_PC.ollama_ueber_vulkan
    # 9B passt (6,6 + 1,5 GB) in 12 GB, auf dem Prozessor waere es "nicht".
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == GUT
    text = next(b.text for b in analyse.bewertungen if b.modell_id == "qwen3.5:9b-q4_K_M")
    assert "Vulkan" in text
    # Was nicht in den Grafikspeicher passt, wird nicht schoengerechnet.
    klein = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="AMD Radeon RX 6500 XT", vram_gb=4))
    assert _stufe(klein, "qwen3.5:9b-q4_K_M") == NICHT
    # Unter 3 GB zaehlt eine Karte nicht als Beschleuniger.
    assert not RechnerProfil(gpu_name="AMD Radeon RX 550", vram_gb=2).ollama_gpu


def test_intel_arc_einzelkarte_beschleunigt_ollama_ueber_vulkan():
    b580 = RechnerProfil(ram_gb=32, cpu_kerne=12, gpu_name="Intel(R) Arc(TM) B580 Graphics", vram_gb=12)
    assert not b580.gpu_integriert and b580.ollama_ueber_vulkan and not b580.whisper_gpu
    analyse = ra.analysiere(b580)
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == GUT
    assert not next(b for b in analyse.bewertungen if b.modell_id == "large-v3-turbo").auf_grafikkarte


def test_intel_arc_prozessorgrafik_rechnet_im_geteilten_speicher():
    lunar_lake = RechnerProfil(ram_gb=32, cpu_kerne=8, gpu_name="Intel(R) Arc(TM) 140V GPU (16GB)", vram_gb=0.1)
    assert lunar_lake.gpu_integriert and lunar_lake.intel_arc_prozessorgrafik
    assert lunar_lake.grafikspeicher_gb == 16.0  # Haelfte des Arbeitsspeichers, nicht die gemeldeten 128 MB
    assert lunar_lake.ollama_ueber_vulkan and lunar_lake.braucht_igpu_freigabe
    analyse = ra.analysiere(lunar_lake)
    assert _stufe(analyse, "qwen3.5:4b-q4_K_M") == GUT
    assert "16.0 GB geteiltem Speicher" in ra.beschreibe_profil(lunar_lake)
    # Ohne bekannten Arbeitsspeicher laesst sich nichts zusagen.
    assert not RechnerProfil(gpu_name="Intel(R) Arc(TM) Graphics", vram_gb=0.1).ollama_gpu


def test_integrierte_grafik_beschleunigt_nichts():
    analyse = ra.analysiere(ONBOARD_LAPTOP)
    ohne = ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, freier_platz_gb=300))
    assert [b.stufe for b in analyse.bewertungen] == [b.stufe for b in ohne.bewertungen]
    hinweis = next(h for h in analyse.hinweise if "Iris" in h)
    assert "integriert" in hinweis and "beschleunigt hier nichts" in hinweis


def test_hinweise_je_grafikkarte():
    radeon = "\n".join(ra.analysiere(RADEON_PC).hinweise)  # RX 6700 XT steht nicht in der ROCm-Liste
    assert "AMD Radeon RX 6700 XT" in radeon and "Ollama über Vulkan" in radeon
    assert "Transkription läuft auf dem Prozessor" in radeon
    arc = "\n".join(
        ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="Intel(R) Arc(TM) A750", vram_gb=8)).hinweise
    )
    assert "Arc" in arc and "Ollama über Vulkan" in arc
    unbekannt = "\n".join(ra.analysiere(RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="AMD Radeon RX 550", vram_gb=2)).hinweise)
    assert "NVIDIA-, AMD- und Intel-Arc-Karten" in unbekannt
    assert not any("Grafik" in h for h in ra.analysiere(GAMING_PC).hinweise)  # NVIDIA: nichts zu bemerken
    assert not any("Grafik" in h for h in ra.analysiere(RX_9070_XT_PC).hinweise)  # ebenso


def test_profilbeschreibung_je_grafikkarte():
    assert "beschleunigt Transkription, Sprechererkennung, Protokoll" in ra.beschreibe_profil(GAMING_PC)
    amd = ra.beschreibe_profil(RX_9070_XT_PC)
    assert "beschleunigt Transkription, Protokoll" in amd and "Sprechererkennung läuft auf dem Prozessor" in amd
    rx6800 = ra.beschreibe_profil(RechnerProfil(gpu_name="AMD Radeon RX 6800 XT", vram_gb=16))
    assert "beschleunigt Protokoll" in rx6800 and "Transkription und Sprechererkennung laufen auf dem Prozessor" in rx6800
    assert "Vulkan" in ra.beschreibe_profil(RADEON_PC)
    assert "teilt sich den Arbeitsspeicher" in ra.beschreibe_profil(ONBOARD_LAPTOP)
    arc = ra.beschreibe_profil(RechnerProfil(gpu_name="Intel(R) Arc(TM) A750", vram_gb=8))
    assert "Ollama über Vulkan" in arc
    assert "wird nicht genutzt" in ra.beschreibe_profil(RechnerProfil(gpu_name="AMD Radeon RX 550", vram_gb=2))
    ohne_speicher = ra.beschreibe_profil(RechnerProfil(gpu_name="AMD Radeon(TM) Graphics"))
    assert " mit " not in ohne_speicher
    knappe_igpu = ra.beschreibe_profil(RechnerProfil(gpu_name="AMD Radeon(TM) 890M Graphics", vram_gb=0.5))
    assert "zu wenig fest zugewiesener Grafikspeicher" in knappe_igpu


# --------------------------------------------------------------------------
# AMD-Karten aus der Liste (amd_grafikkarten)
# --------------------------------------------------------------------------
RX_9070_XT_PC = RechnerProfil(
    ram_gb=32, cpu_kerne=16, gpu_name="AMD Radeon RX 9070 XT", vram_gb=15.9, freier_platz_gb=500
)


def test_rx_9070_xt_beschleunigt_transkription_und_protokoll():
    analyse = ra.analysiere(RX_9070_XT_PC)
    assert RX_9070_XT_PC.amd_rocm and RX_9070_XT_PC.ollama_gpu and not RX_9070_XT_PC.cuda_gpu
    turbo = next(b for b in analyse.bewertungen if b.modell_id == "large-v3-turbo")
    assert turbo.stufe == GUT and turbo.auf_grafikkarte
    assert _stufe(analyse, "qwen3.5:9b-q4_K_M") == GUT
    # 16 GB fassen das 9B-Modell samt Kontext UND Whisper: dann ist 9B die Empfehlung.
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:9b-q4_K_M"
    suche = next(b for b in analyse.bewertungen if b.modell_id == "bge-m3")
    assert suche.auf_grafikkarte


def test_grosses_modell_erst_wenn_es_neben_whisper_passt():
    # 12 GB (RTX 4070): 9B laeuft gut, Standard bleibt aber 4B -- daneben passte Whisper nicht mehr.
    assert ra.grafikspeicher_fuer_grosses_modell(GAMING_PC) > 12
    assert ra.analysiere(GAMING_PC).empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:4b-q4_K_M"
    rtx_16 = RechnerProfil(ram_gb=32, cpu_kerne=12, gpu_name="NVIDIA GeForce RTX 5070 Ti", vram_gb=16)
    assert ra.analysiere(rtx_16).empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:9b-q4_K_M"
    # Ohne Whisper auf der Karte (RX 6800: nur Ollama) reicht weniger.
    rx6800 = RechnerProfil(gpu_name="AMD Radeon RX 6800", vram_gb=16)
    assert ra.grafikspeicher_fuer_grosses_modell(rx6800) < ra.grafikspeicher_fuer_grosses_modell(rtx_16)


def test_rx_6800_nur_ollama_auf_der_karte():
    profil = RechnerProfil(ram_gb=32, cpu_kerne=8, gpu_name="AMD Radeon RX 6800 XT", vram_gb=16)
    analyse = ra.analysiere(profil)
    assert profil.ollama_gpu and not profil.whisper_gpu
    turbo = next(b for b in analyse.bewertungen if b.modell_id == "large-v3-turbo")
    assert not turbo.auf_grafikkarte
    hinweis = "\n".join(analyse.hinweise)
    assert "laufen auf der Grafikkarte (Ollama)" in hinweis and "Transkription läuft auf dem Prozessor" in hinweis


def test_ryzen_ai_grafik_mit_genug_speicher_wird_genutzt():
    strix_halo = RechnerProfil(ram_gb=128, cpu_kerne=16, gpu_name="AMD Radeon(TM) 8060S Graphics", vram_gb=64)
    assert strix_halo.gpu_integriert and strix_halo.prozessorgrafik_nutzbar and strix_halo.braucht_igpu_freigabe
    assert strix_halo.ollama_gpu and strix_halo.amd_rocm and not strix_halo.ollama_ueber_vulkan
    assert ra.analysiere(strix_halo).empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3.5:9b-q4_K_M"


def test_ryzen_ai_grafik_mit_wenig_speicher_bekommt_einen_bios_hinweis():
    knapp = RechnerProfil(ram_gb=32, cpu_kerne=12, gpu_name="AMD Radeon(TM) 890M Graphics", vram_gb=0.5)
    assert knapp.prozessorgrafik_nutzbar and not knapp.ollama_gpu and not knapp.whisper_gpu
    hinweis = "\n".join(ra.analysiere(knapp).hinweise)
    assert "BIOS/UEFI" in hinweis and "0.5 GB" in hinweis


def test_radeon_780m_ueber_vulkan_wenn_genug_zugewiesen():
    phoenix = RechnerProfil(ram_gb=32, cpu_kerne=8, gpu_name="AMD Radeon(TM) 780M Graphics", vram_gb=8)
    assert phoenix.ollama_ueber_vulkan and phoenix.braucht_igpu_freigabe and not phoenix.whisper_gpu


def test_grafikkarten_aus_der_registry():
    import types

    class Schluessel:
        def __init__(self, werte=None, unter=()):
            self.werte, self.unter = werte or {}, list(unter)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    adapter = {
        "0000": Schluessel({"DriverDesc": "AMD Radeon RX 9070 XT", "HardwareInformation.qwMemorySize": 16 * 1024**3}),
        "0001": Schluessel({"DriverDesc": "Microsoft Basic Display Adapter"}),
        "0002": Schluessel({"DriverDesc": "AMD Radeon(TM) Graphics", "HardwareInformation.qwMemorySize": (512 * 1024**2).to_bytes(8, "little")}),
        "0003": Schluessel({}),  # ohne Namen
    }
    klasse = Schluessel(unter=[*adapter, "Properties"])

    def oeffnen(eltern, name, *args):
        if eltern == "HKLM":
            return klasse
        return adapter[name]

    def aufzaehlen(schluessel, nummer):
        if nummer >= len(schluessel.unter):
            raise OSError
        return schluessel.unter[nummer]

    def abfragen(schluessel, name):
        if name not in schluessel.werte:
            raise OSError(name)
        return schluessel.werte[name], 0

    winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM", OpenKey=oeffnen, EnumKey=aufzaehlen, QueryValueEx=abfragen
    )
    assert ECHTE_REGISTRY(winreg) == [
        ("AMD Radeon RX 9070 XT", 16.0),
        ("AMD Radeon(TM) Graphics", 0.5),
    ]

    def kein_schluessel(*args):
        raise OSError

    assert ECHTE_REGISTRY(types.SimpleNamespace(HKEY_LOCAL_MACHINE="HKLM", OpenKey=kein_schluessel)) == []
