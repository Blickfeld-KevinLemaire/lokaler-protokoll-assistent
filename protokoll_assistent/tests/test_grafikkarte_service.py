"""Grafikkarte im Container: Pflicht statt stillem Ausweichen auf den Prozessor (services/grafikkarte_service.py).

Hintergrund: Auf einem Server mit Grafikkarte rechnete die Verarbeitung unbemerkt auf dem Prozessor, wenn die Karte
nicht nutzbar war -- sie dauerte nur ein Vielfaches. Gemessen am 25.11.2026: Im NVIDIA-Image scheiterte die
Sprechertrennung auf der Karte an einem unpassenden torchaudio, auf einer DGX Spark (ARM64) war CTranslate2 nur fuer
den Prozessor gebaut, und unter Fedora liess SELinux die ROCm-Laufzeit abstuerzen. Alle drei Faelle fielen erst
durch diese Pruefung auf."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from protokoll_assistent.services import (
    diarisierung_prozess,
    grafikkarte_probe,
    grafikkarte_service,
    grafikkarte_vorgabe,
    model_service,
    ollama_service,
    pipeline_service,
)
from protokoll_assistent.services.grafikkarte_vorgabe import (
    ART_VARIABLE,
    PFLICHT_VARIABLE,
    Erwartung,
    GrafikkarteFehlt,
)


@pytest.fixture(autouse=True)
def ohne_vorgabe(monkeypatch):
    """Keine Vorgabe aus der Umgebung des Entwicklers: Jeder Test setzt sie selbst."""
    monkeypatch.delenv(ART_VARIABLE, raising=False)
    monkeypatch.delenv(PFLICHT_VARIABLE, raising=False)
    monkeypatch.delenv(model_service.SPRECHERTRENNUNG_GERAET_VARIABLE, raising=False)


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------
def test_ohne_angabe_ist_nichts_pflicht():
    assert grafikkarte_vorgabe.art({}) == "keine"
    assert grafikkarte_vorgabe.pflicht({}) is False
    assert grafikkarte_vorgabe.erwartet({}) == Erwartung()


@pytest.mark.parametrize("wert", ["", "1", "ja", "AN", "true"])
def test_mit_karte_ist_die_pflicht_vorgabe(wert):
    umgebung = {ART_VARIABLE: " NVIDIA ", PFLICHT_VARIABLE: wert}
    assert grafikkarte_vorgabe.art(umgebung) == "nvidia"
    assert grafikkarte_vorgabe.pflicht(umgebung) is True
    assert grafikkarte_vorgabe.erwartet(umgebung) == Erwartung(True, True, True)


@pytest.mark.parametrize("wert", ["0", "nein", "aus", "off"])
def test_pflicht_laesst_sich_abschalten(wert):
    umgebung = {ART_VARIABLE: "amd", PFLICHT_VARIABLE: wert}
    assert grafikkarte_vorgabe.pflicht(umgebung) is False
    assert not grafikkarte_vorgabe.erwartet(umgebung).irgendeine


def test_intel_verlangt_nur_das_sprachmodell_auf_der_karte():
    assert grafikkarte_vorgabe.erwartet({ART_VARIABLE: "intel"}) == Erwartung(sprachmodell=True)


@pytest.mark.parametrize(
    "umgebung", [{ART_VARIABLE: "tpu"}, {ART_VARIABLE: "nvidia", PFLICHT_VARIABLE: "vielleicht"}]
)
def test_unbekannte_werte_fallen_auf(umgebung):
    with pytest.raises(grafikkarte_vorgabe.EinstellungFalsch):
        grafikkarte_vorgabe.pflicht(umgebung)
    # Zur Laufzeit erzwingt ein unbekannter Wert nichts (er faellt schon beim Start auf).
    assert grafikkarte_vorgabe.erwartet(umgebung) == Erwartung()


# --------------------------------------------------------------------------
# Startpruefung und Bericht
# --------------------------------------------------------------------------
def _ok():
    return True, "rechnet"


def _nein():
    return False, "kaputt"


def test_ohne_karte_wird_nichts_geprueft():
    assert grafikkarte_service.startpruefung({}, whisper_auf_karte=_nein, torch_auf_karte=_nein) == []


def test_alles_auf_der_karte_ist_kein_fehler():
    punkte = grafikkarte_service.startpruefung(
        {ART_VARIABLE: "nvidia"}, whisper_auf_karte=_ok, torch_auf_karte=_ok, sprachmodell_auf_karte=_ok
    )
    assert [p.schritt for p in punkte] == ["Transkription", "Sprechertrennung", "Sprachmodell"]
    assert grafikkarte_service.fehlertext(punkte, "nvidia") is None
    assert grafikkarte_service.bericht(punkte, "nvidia", True).count("[OK    ]") == 3


def test_fehlende_karte_nennt_schritt_und_abhilfe():
    punkte = grafikkarte_service.startpruefung({ART_VARIABLE: "amd"}, whisper_auf_karte=_nein, torch_auf_karte=_ok)
    text = grafikkarte_service.fehlertext(punkte, "amd")
    assert text is not None and "Transkription" in text and "Sprechertrennung" not in text.split(".")[0]
    assert "docker-compose.amd.yml" in text and "RENDER_GID" in text and f"{PFLICHT_VARIABLE}=0" in text
    assert "[FEHLER] Transkription" in grafikkarte_service.bericht(punkte, "amd", True)


def test_bei_intel_ist_die_cpu_fuer_whisper_kein_fehler():
    punkte = grafikkarte_service.startpruefung(
        {ART_VARIABLE: "intel"}, whisper_auf_karte=_nein, torch_auf_karte=_nein, sprachmodell_auf_karte=_ok
    )
    assert grafikkarte_service.fehlertext(punkte, "intel") is None
    bericht = grafikkarte_service.bericht(punkte, "intel", True)
    assert "[CPU   ] Transkription" in bericht and "[OK    ] Sprachmodell" in bericht


def test_nicht_pruefbares_sprachmodell_ist_offen_und_kein_kartenfehler():
    punkte = grafikkarte_service.startpruefung(
        {ART_VARIABLE: "nvidia"},
        whisper_auf_karte=_ok,
        torch_auf_karte=_ok,
        sprachmodell_auf_karte=lambda: (None, "Ollama nicht erreichbar"),
    )
    assert punkte[-1].offen and not punkte[-1].fehler
    assert grafikkarte_service.fehlertext(punkte, "nvidia") is None
    assert "[OFFEN ] Sprachmodell" in grafikkarte_service.bericht(punkte, "nvidia", True)


# --------------------------------------------------------------------------
# pruefen_und_melden (Start des Dienstes, grafikkarte-pruefen)
# --------------------------------------------------------------------------
@pytest.fixture
def proben(monkeypatch):
    """Ergebnisse der Proben im eigenen Prozess, je Schritt einstellbar."""
    ergebnisse = {"transkription": (True, "CT2 rechnet"), "sprechertrennung": (True, "torch rechnet")}
    monkeypatch.setattr(grafikkarte_probe, "im_eigenen_prozess", lambda schritt: ergebnisse[schritt])
    return ergebnisse


@pytest.fixture
def sprachmodell(monkeypatch):
    ergebnis = {"wert": (True, "im Grafikspeicher")}
    monkeypatch.setattr(grafikkarte_service, "sprachmodell_pruefer", lambda modell: lambda: ergebnis["wert"])
    return ergebnis


def _melden(umgebung, modell="qwen", streng=False):
    zeilen: list[str] = []
    ok = grafikkarte_service.pruefen_und_melden(modell, streng=streng, ausgabe=zeilen.append, umgebung=umgebung)
    return ok, "\n".join(zeilen)


def test_image_ohne_karte_startet_immer(proben):
    ok, text = _melden({})
    assert ok and "ohne Grafikkarte" in text


def test_unbekannte_kartenart_startet_nicht(proben):
    ok, text = _melden({ART_VARIABLE: "tpu"})
    assert not ok and "tpu" in text


def test_karte_nutzbar_startet(proben, sprachmodell):
    ok, text = _melden({ART_VARIABLE: "nvidia"})
    assert ok and "Pflicht: an" in text and "FEHLER" not in text


def test_karte_nicht_nutzbar_mit_pflicht_startet_nicht(proben, sprachmodell):
    proben["sprechertrennung"] = (False, "stuerzt ab")
    ok, text = _melden({ART_VARIABLE: "nvidia"})
    assert not ok and "Sprechertrennung nicht nutzbar" in text


def test_ohne_pflicht_startet_der_dienst_mit_hinweis(proben, sprachmodell):
    proben["transkription"] = (False, "keine Karte")
    ok, text = _melden({ART_VARIABLE: "nvidia", PFLICHT_VARIABLE: "0"})
    assert ok and "startet trotzdem" in text


def test_sprachmodell_noch_nicht_pruefbar_haelt_den_start_nicht_auf(proben, sprachmodell):
    sprachmodell["wert"] = (None, "Modell noch nicht vorhanden")
    ok, text = _melden({ART_VARIABLE: "nvidia"})
    assert ok and "Noch nicht pruefbar" in text


def test_grafikkarte_pruefen_meldet_nicht_pruefbares_als_fehler(proben, sprachmodell):
    sprachmodell["wert"] = (None, "Ollama nicht erreichbar")
    ok, text = _melden({ART_VARIABLE: "nvidia"}, streng=True)
    assert not ok and "Nicht pruefbar" in text
    # ... aber nicht als Kartenfehler mit Treiber-Abhilfe:
    assert "Container Toolkit" not in text


def test_ohne_modell_wird_das_sprachmodell_nicht_geprueft(proben, monkeypatch):
    monkeypatch.setattr(grafikkarte_service, "sprachmodell_pruefer", lambda modell: pytest.fail("nicht pruefen"))
    ok, text = _melden({ART_VARIABLE: "nvidia"}, modell=None)
    assert ok and "Sprachmodell" not in text


# --------------------------------------------------------------------------
# Sprachmodell bei Ollama
# --------------------------------------------------------------------------
@pytest.fixture
def ollama(monkeypatch):
    zustand = {"laeuft": True, "fehlt": False, "laden": None, "belegung": (100, 100)}
    monkeypatch.setattr(ollama_service, "is_service_running", lambda *a, **k: zustand["laeuft"])
    monkeypatch.setattr(ollama_service, "modell_fehlt", lambda *a, **k: zustand["fehlt"])

    def laden(modell, *a, **k):
        if zustand["laden"]:
            raise ollama_service.OllamaError(zustand["laden"])

    monkeypatch.setattr(ollama_service, "modell_laden", laden)
    monkeypatch.setattr(ollama_service, "modell_belegung", lambda *a, **k: zustand["belegung"])
    return zustand


@pytest.mark.parametrize(
    ("aenderung", "erwartet"),
    [
        ({"laeuft": False}, (None, "nicht erreichbar")),
        ({"fehlt": True}, (None, "nicht vorhanden")),
        ({"laden": "kaputt"}, (None, "nicht laden")),
        ({"belegung": None}, (None, "nicht in Ollamas Liste")),
        ({"belegung": (100, 0)}, (False, "Prozessor")),
        ({}, (True, "im Grafikspeicher")),
    ],
)
def test_sprachmodell_pruefer(ollama, aenderung, erwartet):
    ollama.update(aenderung)
    ergebnis, text = grafikkarte_service.sprachmodell_pruefer("qwen")()
    assert ergebnis is erwartet[0] and erwartet[1] in text


def test_sprachmodell_text_unterscheidet_ganz_teilweise_gar_nicht():
    gb = 1024**3
    assert grafikkarte_vorgabe.sprachmodell_text("m", 4 * gb, 0)[0] is False
    ok, text = grafikkarte_vorgabe.sprachmodell_text("m", 4 * gb, 2 * gb)
    assert ok and "50 %" in text
    assert grafikkarte_vorgabe.sprachmodell_text("m", 4 * gb, 4 * gb) == (True, "m: 4.0 GB im Grafikspeicher")


def test_sprachmodell_nachpruefen():
    umgebung = {ART_VARIABLE: "intel"}
    with pytest.raises(GrafikkarteFehlt, match="Prozessor"):
        grafikkarte_vorgabe.sprachmodell_nachpruefen("m", lambda name: (10, 0), umgebung)
    grafikkarte_vorgabe.sprachmodell_nachpruefen("m", lambda name: (10, 10), umgebung)
    grafikkarte_vorgabe.sprachmodell_nachpruefen("m", lambda name: None, umgebung)  # nicht mehr geladen
    grafikkarte_vorgabe.sprachmodell_nachpruefen("m", lambda name: pytest.fail("nicht fragen"), {})


def test_ollama_antwort_auf_dem_prozessor_wird_zum_fehler_der_auswertung(monkeypatch):
    monkeypatch.setattr(ollama_service, "_generate_request", lambda body, url, timeout: "Antwort")
    monkeypatch.setattr(ollama_service, "modell_belegung", lambda name, url: (10, 0))
    assert ollama_service.generate_text("p", "s", model="qwen") == "Antwort"  # ohne Vorgabe: wie bisher
    monkeypatch.setenv(ART_VARIABLE, "nvidia")
    with pytest.raises(ollama_service.OllamaError, match="Prozessor"):
        ollama_service.generate_text("p", "s", model="qwen")
    monkeypatch.setattr(ollama_service, "_generate_request", lambda body, url, timeout: '{"a": 1}')
    with pytest.raises(ollama_service.OllamaError, match="Prozessor"):
        ollama_service.generate_json("p", "s", model="qwen")


def test_modell_belegung_aus_api_ps(monkeypatch):
    eintraege = {"models": [{"name": "andere:1b", "size": 1, "size_vram": 1}, {"model": "qwen:latest", "size": 9, "size_vram": 4}]}
    monkeypatch.setattr(ollama_service, "_get_json", lambda url, timeout: eintraege)
    assert ollama_service.modell_belegung("qwen") == (9, 4)  # ohne Fassung meint Ollama ':latest'
    assert ollama_service.modell_belegung("fehlt:1b") is None
    eintraege["models"] = [{"name": "qwen:latest", "size": "x"}]
    assert ollama_service.modell_belegung("qwen") is None

    def weg(url, timeout):
        raise OSError("aus")

    monkeypatch.setattr(ollama_service, "_get_json", weg)
    assert ollama_service.modell_belegung("qwen") is None


def test_modell_laden(monkeypatch):
    gesendet = []

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ollama_service, "_post_json", lambda url, daten, timeout, opener: gesendet.append((url, daten)) or Antwort())
    ollama_service.modell_laden("qwen", base_url="http://o")
    assert gesendet == [("http://o/api/generate", {"model": "qwen"})]

    def weg(*a):
        raise OSError("aus")

    monkeypatch.setattr(ollama_service, "_post_json", weg)
    with pytest.raises(ollama_service.OllamaError):
        ollama_service.modell_laden("qwen")


# --------------------------------------------------------------------------
# Laufzeit: Transkription und Sprechertrennung
# --------------------------------------------------------------------------
def test_transkription_pruefen():
    grafikkarte_vorgabe.transkription_pruefen("cuda", {ART_VARIABLE: "nvidia"})
    grafikkarte_vorgabe.transkription_pruefen("cpu", {ART_VARIABLE: "intel"})
    grafikkarte_vorgabe.transkription_pruefen("cpu", {})
    with pytest.raises(GrafikkarteFehlt, match="Transkription"):
        grafikkarte_vorgabe.transkription_pruefen("cpu", {ART_VARIABLE: "amd"})


def test_sprechertrennung_pruefen_nennt_den_grund():
    with pytest.raises(GrafikkarteFehlt, match=r"\(Prozess weg\)"):
        grafikkarte_vorgabe.sprechertrennung_pruefen("cpu", {ART_VARIABLE: "nvidia"}, grund="Prozess weg")
    grafikkarte_vorgabe.sprechertrennung_pruefen("cpu", {ART_VARIABLE: "intel"})


def _settings(tmp_path):
    return pipeline_service.PipelineSettings(source_path=tmp_path / "a.wav", output_dir=tmp_path)


def test_pipeline_weicht_mit_pflicht_nicht_auf_die_cpu_aus(tmp_path, monkeypatch):
    monkeypatch.setenv(ART_VARIABLE, "nvidia")
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: True)

    def scheitert(*a):
        raise diarisierung_prozess.DiarisierungsprozessFehler("libtorchaudio.so laedt nicht")

    monkeypatch.setattr(diarisierung_prozess, "diarisiere_in_eigenem_prozess", scheitert)
    monkeypatch.setattr(model_service, "load_pyannote_pipeline", lambda geraet: pytest.fail("nicht auf der CPU"))
    with pytest.raises(GrafikkarteFehlt, match="libtorchaudio"):
        pipeline_service._sprechertrennung(tmp_path / "a.wav", _settings(tmp_path), "cuda", pipeline_service.PipelineCallbacks())


def test_pipeline_ohne_nutzbare_karte_bricht_vor_der_sprechertrennung_ab(tmp_path, monkeypatch):
    monkeypatch.setenv(ART_VARIABLE, "amd")
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: False)
    with pytest.raises(GrafikkarteFehlt, match="Sprechertrennung"):
        pipeline_service._sprechertrennung(tmp_path / "a.wav", _settings(tmp_path), "cuda", pipeline_service.PipelineCallbacks())


def test_ausdruecklich_cpu_fuer_die_sprechertrennung_gilt_auch_mit_pflicht(tmp_path, monkeypatch):
    monkeypatch.setenv(ART_VARIABLE, "nvidia")
    monkeypatch.setenv(model_service.SPRECHERTRENNUNG_GERAET_VARIABLE, "cpu")
    monkeypatch.setattr(model_service, "load_pyannote_pipeline", lambda geraet: "p")
    monkeypatch.setattr(pipeline_service.transcription_service, "load_audio_array", lambda pfad: [0.0])
    monkeypatch.setattr(pipeline_service.diarization_service, "build_waveform_dict", lambda audio: {})
    monkeypatch.setattr(
        pipeline_service.diarization_service, "diarize_waveform", lambda p, w, mi, ma, embeddings_out: ["turn"]
    )
    ergebnis = pipeline_service._sprechertrennung(
        tmp_path / "a.wav", _settings(tmp_path), "cuda", pipeline_service.PipelineCallbacks()
    )
    assert ergebnis[0] == ["turn"]


# --------------------------------------------------------------------------
# Probe im eigenen Prozess
# --------------------------------------------------------------------------
def _lauf(returncode=0, stdout="", stderr=""):
    aufrufe = []

    def lauf(befehl, **kwargs):
        aufrufe.append(befehl)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return lauf, aufrufe


def test_probe_liefert_das_ergebnis_des_kindprozesses():
    lauf, aufrufe = _lauf(stdout="Laden ...\n" + json.dumps({"ok": True, "meldung": "rechnet"}))
    assert grafikkarte_probe.im_eigenen_prozess("transkription", lauf_fn=lauf, python="py") == (True, "rechnet")
    assert aufrufe[0] == ["py", "-m", "protokoll_assistent.services.grafikkarte_probe", "transkription"]


@pytest.mark.parametrize("code", [-11, 139])
def test_absturz_der_probe_wird_zur_meldung(code):
    ok, text = grafikkarte_probe.im_eigenen_prozess("transkription", lauf_fn=_lauf(returncode=code)[0])
    assert not ok and "Signal 11 (SIGSEGV)" in text and "SELinux" in text


def test_probe_mit_fehlercode_nennt_die_letzten_zeilen():
    ok, text = grafikkarte_probe.im_eigenen_prozess("x", lauf_fn=_lauf(returncode=1, stderr="a\nb\nImportError: c")[0])
    assert not ok and "Code 1" in text and "ImportError: c" in text
    ok, text = grafikkarte_probe.im_eigenen_prozess("x", lauf_fn=_lauf(returncode=0, stdout="kein json")[0])
    assert not ok and "Code 0" in text


@pytest.mark.parametrize(
    ("fehler", "erwartet"), [(subprocess.TimeoutExpired("py", 1), "nicht zurueck"), (OSError("weg"), "nicht starten")]
)
def test_probe_haengt_oder_startet_nicht(fehler, erwartet):
    def lauf(befehl, **kwargs):
        raise fehler

    ok, text = grafikkarte_probe.im_eigenen_prozess("transkription", lauf_fn=lauf)
    assert not ok and erwartet in text


def test_probe_main(monkeypatch, capsys):
    monkeypatch.setattr(model_service, "whisper_auf_grafikkarte", lambda: (True, "CT2"))
    monkeypatch.setattr(model_service, "torch_auf_grafikkarte", lambda: (False, "torch"))
    assert grafikkarte_probe.main(["transkription"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"ok": True, "meldung": "CT2"}
    assert grafikkarte_probe.main(["sprechertrennung"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"ok": False, "meldung": "torch"}
    assert grafikkarte_probe.main(["quatsch"]) == 2


# --------------------------------------------------------------------------
# Die echten Pruefungen in model_service (mit nachgebauten Modulen)
# --------------------------------------------------------------------------
class _Speicher:
    """Nachbau von ctranslate2.StorageView: rechnet auf der "Karte" so, wie es eingestellt ist."""

    def __init__(self, werte, falsch=False):
        self.werte, self.falsch = werte, falsch

    @classmethod
    def from_array(cls, werte):
        return cls(werte)

    def to_device(self, geraet):
        return self

    def to(self, typ):
        return _Speicher(self.werte * 2 if _CT2.falsch else self.werte)


class _CT2:
    anzahl = 1
    typen = ("float16", "float32")
    falsch = False
    StorageView = _Speicher
    Device = SimpleNamespace(cuda="cuda", cpu="cpu")
    DataType = SimpleNamespace(float16="f16", float32="f32")

    @classmethod
    def get_cuda_device_count(cls):
        return cls.anzahl

    @classmethod
    def get_supported_compute_types(cls, geraet):
        return cls.typen


class _Werte(list):
    """Genug von numpy fuer die Probe: arange(16).reshape(4, 4), * 2, allclose, array."""

    def reshape(self, *form):
        return self

    def __mul__(self, faktor):
        return _Werte(w * faktor for w in self)


_NUMPY = SimpleNamespace(
    float32="float32",
    arange=lambda n, dtype=None: _Werte(range(n)),
    array=lambda speicher: speicher.werte,
    allclose=lambda a, b: list(a) == list(b),
)


@pytest.fixture
def ct2(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "numpy", _NUMPY)
    monkeypatch.setitem(sys.modules, "ctranslate2", _CT2)
    monkeypatch.setattr(_CT2, "anzahl", 1)
    monkeypatch.setattr(_CT2, "typen", ("float16",))
    monkeypatch.setattr(_CT2, "falsch", False)
    return _CT2


def test_whisper_auf_grafikkarte(ct2, monkeypatch):
    assert model_service.whisper_auf_grafikkarte() == (True, "CTranslate2 rechnet auf der Karte (1 gefunden, float16)")
    monkeypatch.setattr(ct2, "falsch", True)
    assert model_service.whisper_auf_grafikkarte() == (False, "CTranslate2 rechnet auf der Karte falsch")
    monkeypatch.setattr(ct2, "typen", ("float32",))
    assert "float16" in model_service.whisper_auf_grafikkarte()[1]
    monkeypatch.setattr(ct2, "anzahl", 0)
    ok, text = model_service.whisper_auf_grafikkarte()
    assert not ok and "ARM" in text

    def kaputt():
        raise RuntimeError("cudart fehlt")

    monkeypatch.setattr(ct2, "get_cuda_device_count", kaputt)
    ok, text = model_service.whisper_auf_grafikkarte()
    assert not ok and "cudart fehlt" in text


def _torch(hip=None, cuda=None):
    return SimpleNamespace(
        version=SimpleNamespace(hip=hip, cuda=cuda), cuda=SimpleNamespace(get_device_name=lambda i: "Radeon 8060S")
    )


def test_torch_auf_grafikkarte(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "torch", _torch(hip="7.2"))
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: True)
    assert model_service.torch_auf_grafikkarte() == (True, "PyTorch (ROCm 7.2) rechnet auf Radeon 8060S")
    monkeypatch.setitem(sys.modules, "torch", _torch(cuda="12.8"))
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: False)
    assert model_service.torch_auf_grafikkarte() == (False, "PyTorch (CUDA 12.8) kann auf keiner Karte rechnen")
    monkeypatch.setitem(sys.modules, "torch", _torch())
    assert "nur Prozessor" in model_service.torch_auf_grafikkarte()[1]
    monkeypatch.setitem(sys.modules, "torch", None)  # nicht installiert
    assert model_service.torch_auf_grafikkarte() == (False, "PyTorch ist nicht installiert")


# --------------------------------------------------------------------------
# Start: Servermodus und grafikkarte-pruefen
# --------------------------------------------------------------------------
def test_modell_fuer_die_pruefung():
    from protokoll_assistent.api import __main__ as start

    assert start.sprachmodell_fuer_pruefung({"nachbearbeitung_modus": "api"}, {}) is None
    assert start.sprachmodell_fuer_pruefung({"ollama_modell": "gemma"}, {"PROTOKOLL_OLLAMA_MODELL": "x"}) == "gemma"
    assert start.sprachmodell_fuer_pruefung({}, {"PROTOKOLL_OLLAMA_MODELL": " x "}) == "x"
    assert start.sprachmodell_fuer_pruefung({}, {}) == ollama_service.DEFAULT_MODEL


def test_grafikkarte_pruefen_als_befehl(monkeypatch, tmp_path):
    from protokoll_assistent.api import __main__ as start
    from protokoll_assistent.utils import app_config

    monkeypatch.setattr(app_config, "get_config_file", lambda: tmp_path / "konfiguration.json")
    aufrufe = []

    def pruefen(modell, *, streng, ausgabe, umgebung=None):
        aufrufe.append((modell, streng))
        return modell != "kaputt"

    monkeypatch.setattr(grafikkarte_service, "pruefen_und_melden", pruefen)
    assert start.main(["grafikkarte-pruefen"]) == 0
    assert aufrufe == [(ollama_service.DEFAULT_MODEL, True)]
    app_config.update_config(ollama_modell="kaputt")
    assert start.grafikkarte_pruefen(streng=False) == start.GRAFIKKARTE_FEHLT_EXIT_CODE


def test_alter_serverstart_bricht_ohne_karte_ab(monkeypatch, tmp_path):
    from protokoll_assistent.server import __main__ as server_start

    monkeypatch.setattr(grafikkarte_service, "pruefen_und_melden", lambda *a, **k: False)
    umgebung = {"PROTOKOLL_EINGANG": str(tmp_path / "e"), "PROTOKOLL_AUSGANG": str(tmp_path / "a")}
    assert server_start.main(["--einmal"], umgebung) == 4
