"""Tests fuer 'services/einrichtungsplan_service.py': Was geht auf diesem
Computer, und was kostet es?"""

from __future__ import annotations

import pytest

from protokoll_assistent.services import einrichtungsplan_service as eps
from protokoll_assistent.services import model_service, ollama_service, rechner_analyse_service
from protokoll_assistent.services.rechner_analyse_service import GUT, MAESSIG, NICHT, RechnerProfil


def _analyse(**profil):
    return rechner_analyse_service.analysiere(RechnerProfil(**profil))


LAPTOP_6GB = {"ram_gb": 63.5, "cpu_kerne": 16, "gpu_name": "NVIDIA RTX PRO 500 Blackwell", "vram_gb": 6.0, "freier_platz_gb": 400}
OHNE_GRAFIK = {"ram_gb": 16, "cpu_kerne": 8, "gpu_name": None, "vram_gb": None, "freier_platz_gb": 200}
WENIG_RAM = {"ram_gb": 8, "cpu_kerne": 8, "gpu_name": None, "vram_gb": None, "freier_platz_gb": 200}
SCHWACH = {"ram_gb": 4, "cpu_kerne": 2, "gpu_name": None, "vram_gb": None, "freier_platz_gb": 50}


def _stufen(moeglichkeiten):
    return {s.schritt: s.stufe for s in moeglichkeiten.schritte}


def test_laptop_mit_nvidia_schafft_alles_selbst():
    m = eps.schaetze(_analyse(**LAPTOP_6GB))
    assert m.empfehlung == eps.EMPFEHLUNG_LOKAL
    assert set(_stufen(m).values()) == {GUT}
    texte = {s.schritt: s.text for s in m.schritte}
    assert texte[eps.SCHRITT_MITSCHRIFT].startswith("etwa 3–5 Minuten")  # gemessen: 2:53 fuer 66 min
    assert "20–30 Minuten" in texte[eps.SCHRITT_PROTOKOLL]
    assert "Sekunden je Frage" in texte[eps.SCHRITT_CHAT]


def test_ohne_grafikkarte_geht_alles_aber_langsam_und_der_anwender_entscheidet():
    m = eps.schaetze(_analyse(**OHNE_GRAFIK))
    stufen = _stufen(m)
    assert stufen[eps.SCHRITT_SPRECHER] == MAESSIG
    assert stufen[eps.SCHRITT_PROTOKOLL] == MAESSIG
    assert m.empfehlung is None  # keine Vorauswahl: lokal geht, online waere schneller
    texte = {s.schritt: s.text for s in m.schritte}
    assert "Prozessor" in texte[eps.SCHRITT_MITSCHRIFT]
    assert "Stunden" in texte[eps.SCHRITT_PROTOKOLL]
    assert "Minuten je Frage" in texte[eps.SCHRITT_CHAT]


def test_zu_schwacher_rechner_empfiehlt_online():
    m = eps.schaetze(_analyse(**SCHWACH))
    assert m.empfehlung == eps.EMPFEHLUNG_API
    assert set(_stufen(m).values()) == {NICHT}


def test_wenig_ram_ohne_grafik_empfiehlt_gemischt():
    # 8 GB, keine Grafikkarte: Mitschrift laeuft, das Protokoll ist aber nur
    # "maessig" und der Arbeitsspeicher knapp -> Protokoll besser online.
    m = eps.schaetze(_analyse(**WENIG_RAM))
    stufen = _stufen(m)
    assert stufen[eps.SCHRITT_MITSCHRIFT] != NICHT
    assert stufen[eps.SCHRITT_PROTOKOLL] == MAESSIG
    assert m.empfehlung == eps.EMPFEHLUNG_GEMISCHT
    assert "Arbeitsspeicher" in m.begruendung


RX_9070_XT = {"ram_gb": 32, "cpu_kerne": 16, "gpu_name": "AMD Radeon RX 9070 XT", "vram_gb": 15.9, "freier_platz_gb": 500}
RX_6800 = {"ram_gb": 32, "cpu_kerne": 16, "gpu_name": "AMD Radeon RX 6800 XT", "vram_gb": 16.0, "freier_platz_gb": 500}


def test_rx_9070_xt_schafft_alles_selbst_und_sagt_wo_was_laeuft():
    m = eps.schaetze(_analyse(**RX_9070_XT))
    assert m.empfehlung == eps.EMPFEHLUNG_LOKAL
    stufen = _stufen(m)
    for schritt in (eps.SCHRITT_MITSCHRIFT, eps.SCHRITT_PROTOKOLL, eps.SCHRITT_CHAT):
        assert stufen[schritt] == GUT
    texte = {s.schritt: s.text for s in m.schritte}
    assert texte[eps.SCHRITT_MITSCHRIFT].endswith("(Grafikkarte)")
    assert "(Prozessor)" in texte[eps.SCHRITT_SPRECHER]  # pyannote: PyTorch fuer AMD gibt es unter Windows nicht
    assert texte[eps.SCHRITT_PROTOKOLL].endswith("(Grafikkarte)")
    assert texte[eps.SCHRITT_CHAT].endswith("(Grafikkarte)")
    # Gemessen: 79 min Aufnahme in 3 min mit Qwen 9B -- nicht die 20-30 min des 6-GB-Laptops.
    assert texte[eps.SCHRITT_PROTOKOLL].startswith("etwa 2–5 Minuten")


@pytest.mark.parametrize(
    ("profil", "minuten"),
    [
        (RechnerProfil(gpu_name="NVIDIA RTX PRO 500 Blackwell", vram_gb=6.0), (20, 30)),  # gemessen
        (RechnerProfil(gpu_name="NVIDIA GeForce RTX 3060", vram_gb=8.0), (20, 30)),
        (RechnerProfil(gpu_name="AMD Radeon RX 6700 XT", vram_gb=10.0), (5, 15)),  # nicht gemessen
        (RechnerProfil(gpu_name="NVIDIA GeForce RTX 4070", vram_gb=12.0), (2, 5)),
        (RechnerProfil(gpu_name="AMD Radeon RX 9070 XT", vram_gb=15.9), (2, 5)),  # gemessen
        # Prozessorgrafik rechnet im Arbeitsspeicher: wie eine kleine Karte, auch mit 64 GB Zuteilung.
        (RechnerProfil(ram_gb=128, gpu_name="AMD Radeon(TM) 8060S Graphics", vram_gb=64.0), (20, 30)),
        (RechnerProfil(ram_gb=32, gpu_name="Intel(R) Arc(TM) 140V GPU (16GB)", vram_gb=0.1), (20, 30)),
    ],
)
def test_protokolldauer_nach_groesse_der_karte(profil, minuten):
    assert eps.protokoll_minuten_auf_der_grafikkarte(profil) == minuten


def test_rx_6800_protokoll_auf_der_karte_mitschrift_auf_dem_prozessor():
    m = eps.schaetze(_analyse(**RX_6800))
    texte = {s.schritt: s.text for s in m.schritte}
    assert texte[eps.SCHRITT_MITSCHRIFT].endswith("(Prozessor)")
    assert _stufen(m)[eps.SCHRITT_PROTOKOLL] == GUT and texte[eps.SCHRITT_PROTOKOLL].endswith("(Grafikkarte)")


def test_amd_rechenumgebung_als_baustein():
    teile = eps.bausteine_fuer(
        transkription_lokal=True, nachbearbeitung_lokal=False, chat_lokal=False, cuda_gpu=False, amd_rocm=True,
        whisper_modell=model_service.WHISPER_MODEL_NAME, sprachmodell=ollama_service.DEFAULT_MODEL,
        einbettungsmodell="bge-m3",
    )
    laufzeit = next(t for t in teile if t.kennung == "laufzeit")
    assert "ROCm" in laufzeit.name and laufzeit.download_gb == eps.LAUFZEIT_AMD_DOWNLOAD_GB
    assert "Sprechererkennung auf dem Prozessor" in laufzeit.hinweis


def test_16gb_ohne_grafik_bleibt_neutral():
    # 16 GB (nicht knapp): lokal geht, online waere schneller -- keine Vorauswahl.
    assert eps.schaetze(_analyse(**OHNE_GRAFIK)).empfehlung is None


def test_mitschrift_geht_protokoll_nicht_empfiehlt_gemischt(monkeypatch):
    analyse = _analyse(**OHNE_GRAFIK)
    analyse.empfehlung[rechner_analyse_service.BEREICH_NACHBEARBEITUNG] = None
    m = eps.schaetze(analyse)
    assert m.empfehlung == eps.EMPFEHLUNG_GEMISCHT
    assert _stufen(m)[eps.SCHRITT_CHAT] == NICHT


@pytest.mark.parametrize(
    ("von", "bis", "text"),
    [
        (3, 5, "etwa 3–5 Minuten"),
        (4.2, 4.4, "etwa 4 Minuten"),
        (0.2, 0.4, "etwa 1 Minute"),
        (61, 89, "etwa 61–89 Minuten"),  # unter anderthalb Stunden bleibt es bei Minuten
        (60, 90, "etwa 1–2 Stunden"),
        (60, 180, "etwa 1–3 Stunden"),
        (91, 91, "etwa 2 Stunden"),
        (50, 75, "etwa 50–75 Minuten"),
    ],
)
def test_dauer_in_worten(von, bis, text):
    assert eps.formatiere_dauer(von, bis) == text


def _kennungen(bausteine):
    return [b.kennung for b in bausteine]


def _bausteine(**wahl):
    standard = {
        "transkription_lokal": True,
        "nachbearbeitung_lokal": True,
        "chat_lokal": True,
        "cuda_gpu": True,
        "whisper_modell": model_service.WHISPER_MODEL_NAME,
        "sprachmodell": ollama_service.DEFAULT_MODEL,
        "einbettungsmodell": "bge-m3",
    }
    return eps.bausteine_fuer(**{**standard, **wahl})


def test_alles_lokal_braucht_alle_bausteine():
    bausteine = _bausteine()
    assert _kennungen(bausteine) == ["ffmpeg", "ollama", "sprachmodell", "einbettung", "laufzeit", "whisper", "pyannote"]
    groessen = {b.kennung: b.download_gb for b in bausteine}
    assert groessen["sprachmodell"] == ollama_service.get_modell_option(ollama_service.DEFAULT_MODEL).groesse_gb
    assert groessen["laufzeit"] == eps.LAUFZEIT_GPU_DOWNLOAD_GB
    assert next(b for b in bausteine if b.kennung == "laufzeit").platz_gb == eps.LAUFZEIT_GPU_PLATZ_GB
    assert "Hugging Face" in next(b for b in bausteine if b.kennung == "pyannote").hinweis
    assert "mit Windows" in next(b for b in bausteine if b.kennung == "ollama").hinweis


def test_alles_online_braucht_nur_ffmpeg():
    assert _kennungen(_bausteine(transkription_lokal=False, nachbearbeitung_lokal=False, chat_lokal=False)) == ["ffmpeg"]


def test_nur_chat_lokal_braucht_ollama_sprach_und_suchmodell():
    kennungen = _kennungen(_bausteine(transkription_lokal=False, nachbearbeitung_lokal=False))
    assert kennungen == ["ffmpeg", "ollama", "sprachmodell", "einbettung"]


def test_ohne_grafikkarte_kleinere_rechenumgebung_und_kleineres_whisper():
    bausteine = {b.kennung: b for b in _bausteine(cuda_gpu=False, whisper_modell="small", nachbearbeitung_lokal=False, chat_lokal=False)}
    assert bausteine["laufzeit"].download_gb == eps.LAUFZEIT_CPU_DOWNLOAD_GB
    assert bausteine["whisper"].download_gb == eps.WHISPER_SMALL_GB


def test_unbekannte_modelle_bekommen_eine_vorsichtige_groesse():
    bausteine = {b.kennung: b for b in _bausteine(sprachmodell="eigenes:7b", einbettungsmodell="eigene-suche")}
    assert bausteine["sprachmodell"].download_gb == 4.0
    assert bausteine["einbettung"].download_gb == 1.2


def test_summe_zaehlt_nur_was_fehlt():
    bausteine = _bausteine(vorhanden={"ffmpeg": True, "ollama": True, "laufzeit": True})
    download, platz = eps.summe(bausteine)
    fehlend = [b for b in bausteine if b.kennung not in ("ffmpeg", "ollama", "laufzeit")]
    assert download == pytest.approx(sum(b.download_gb for b in fehlend))
    assert platz == pytest.approx(sum(b.platz_gb for b in fehlend))
    assert eps.summe([]) == (0, 0)


def test_downloaddauer():
    # 1 GB bei 50 Mbit/s: 8192 Mbit / 50 = 164 s
    assert eps.download_minuten(1.0) == pytest.approx(8192 / 50 / 60)
    assert eps.download_minuten(1.0, mbit_je_sekunde=100) == pytest.approx(8192 / 100 / 60)
