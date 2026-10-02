"""Tests fuer ``services/rechner_analyse_service.py`` -- ohne Hardware, ohne Programme."""

from __future__ import annotations

from pathlib import Path

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
        gpu_fn=lambda: ("RTX 3060", 12.0),
        kerne_fn=lambda: 6,
        platz_fn=lambda ordner: 123.0 if ordner == tmp_path else None,
    )
    assert profil == RechnerProfil(15.9, 6, "RTX 3060", 12.0, 123.0)
    assert profil.hat_gpu


def test_nvidia_smi_ausgabe_wird_gelesen():
    assert ra._gpu_aus_ausgabe("NVIDIA GeForce RTX 3060, 12288\n") == ("NVIDIA GeForce RTX 3060", 12.0)
    assert ra._gpu_aus_ausgabe("Karte, mit Komma, 8192\nZweite, 4096") == ("Karte, mit Komma", 8.0)
    assert ra._gpu_aus_ausgabe("") == (None, None)
    assert ra._gpu_aus_ausgabe("kaputt, abc") == (None, None)


def test_gpu_ohne_nvidia_smi(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: None)
    assert ra._gpu() == (None, None)


def test_gpu_ueber_nvidia_smi(monkeypatch):
    class _Ergebnis:
        returncode = 0
        stdout = "RTX 4090, 24564\n"

    monkeypatch.setattr(ra.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(ra.subprocess, "run", lambda *a, **k: _Ergebnis())
    name, vram = ra._gpu()
    assert name == "RTX 4090" and round(vram or 0) == 24


def test_gpu_bei_fehlern_des_programms(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: "nvidia-smi")

    def werfen(*a, **k):
        raise OSError("weg")

    monkeypatch.setattr(ra.subprocess, "run", werfen)
    assert ra._gpu() == (None, None)

    class _Fehler:
        returncode = 9
        stdout = ""

    monkeypatch.setattr(ra.subprocess, "run", lambda *a, **k: _Fehler())
    assert ra._gpu() == (None, None)


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
    assert "unbekannt" in ohne and "keine NVIDIA-Karte" in ohne and "Freier Platz" not in ohne


# --------------------------------------------------------------------------
# Bewerten
# --------------------------------------------------------------------------
def test_gaming_pc_alles_gut():
    analyse = ra.analysiere(GAMING_PC)
    assert _stufe(analyse, "large-v3") == GUT
    assert _stufe(analyse, "qwen3:14b") == GUT
    assert analyse.empfehlung[ra.BEREICH_TRANSKRIPTION] == "large-v3-turbo"
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3:8b"
    assert analyse.empfehlung[ra.BEREICH_SUCHE] == "bge-m3"
    assert analyse.hinweise == []


def test_normaler_laptop_ohne_grafikkarte():
    analyse = ra.analysiere(NORMALER_LAPTOP)
    assert _stufe(analyse, "large-v3-turbo") == GUT
    assert _stufe(analyse, "large-v3") == NICHT  # dauert doppelt so lang wie die Aufnahme
    assert _stufe(analyse, "qwen3:8b") == MAESSIG
    assert _stufe(analyse, "qwen3:4b") == GUT
    assert _stufe(analyse, "qwen3:14b") == NICHT
    # Das kleine Modell kommt zum Zug, weil der Standard nur maessig laeuft.
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3:4b"
    assert any("Keine NVIDIA-Grafikkarte" in h for h in analyse.hinweise)


def test_schwacher_laptop_mit_vier_kernen():
    analyse = ra.analysiere(SCHWACHER_LAPTOP)
    assert _stufe(analyse, "large-v3-turbo") == GUT  # 3,8 * 0,6 = 2,3-fach
    assert _stufe(analyse, "large-v3") == NICHT
    assert _stufe(analyse, "qwen3:4b") == MAESSIG  # wenige Kerne
    assert _stufe(analyse, "qwen3:8b") == NICHT  # 8 GB RAM reichen nicht fuer 6,7 + 3 GB
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] == "qwen3:4b"


def test_alter_pc_bekommt_nur_hinweise():
    analyse = ra.analysiere(ALTER_PC)
    assert analyse.empfehlung[ra.BEREICH_NACHBEARBEITUNG] is None
    assert all(_stufe(analyse, o) == NICHT for o in ("qwen3:4b", "qwen3:8b", "gemma3:12b"))
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
    profil = RechnerProfil(ram_gb=16, cpu_kerne=8, gpu_name="Alte Karte", vram_gb=3.5)
    analyse = ra.analysiere(profil)
    assert _stufe(analyse, "large-v3-turbo") == MAESSIG  # 3,0 GB noetig, 4,5 GB fuer "gut"
    assert _stufe(analyse, "large-v3") != GUT  # 6 GB noetig -> weicht auf den Prozessor aus


def test_unbekannter_arbeitsspeicher_wird_nicht_als_zu_wenig_gewertet():
    analyse = ra.analysiere(RechnerProfil(ram_gb=None, cpu_kerne=8))
    assert _stufe(analyse, "qwen3:4b") == GUT


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
