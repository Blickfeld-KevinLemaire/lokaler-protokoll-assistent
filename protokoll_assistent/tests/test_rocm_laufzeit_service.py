"""Rechenumgebung fuer AMD-Karten: Erkennung, Archiv mit CTranslate2, pip-Aufrufe -- ohne Netz."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from protokoll_assistent.services import environment_service, model_service
from protokoll_assistent.services import rocm_laufzeit_service as rls

# Das echte (nicht von conftest ersetzte) 'amd_karte_erkannt' -- beim Import dieses Moduls noch unveraendert.
ECHTE_ERKENNUNG = rls.amd_karte_erkannt
FASSUNGEN = ((3, 10), (3, 11))


def test_amd_karte_wird_erkannt():
    assert ECHTE_ERKENNUNG(lambda: [("AMD Radeon RX 9070 XT", 15.9)])
    assert ECHTE_ERKENNUNG(lambda: [("Intel(R) UHD Graphics", 0.1), ("AMD Radeon RX 7800 XT", 16.0)])


@pytest.mark.parametrize(
    "karten",
    [
        [],
        [("AMD Radeon RX 6800 XT", 16.0)],  # nur Ollama, keine Transkription
        [("AMD Radeon RX 6700 XT", 12.0)],  # nicht in der Liste
        [("AMD Radeon(TM) 890M Graphics", 0.5)],  # zu wenig zugewiesener Speicher
        [("NVIDIA GeForce RTX 4070", 12.0)],
    ],
)
def test_keine_passende_amd_karte(karten):
    assert not ECHTE_ERKENNUNG(lambda: karten)


def _archiv(namen: list[str]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as zip_datei:
        for name in namen:
            zip_datei.writestr(f"temp-windows/{name}", f"rad {name}")
    return puffer.getvalue()


RAEDER = [f"ctranslate2-{rls.CTRANSLATE2_VERSION}-cp3{n}-cp3{n}-win_amd64.whl" for n in (9, 10, 11, 12)]


@pytest.fixture
def archiv(monkeypatch):
    inhalt = _archiv(RAEDER)
    monkeypatch.setattr(rls, "CTRANSLATE2_ARCHIV_SHA256", hashlib.sha256(inhalt).hexdigest())
    return inhalt


def test_raeder_werden_geladen_geprueft_und_ausgepackt(tmp_path, archiv):
    geladen = []

    def lade(url, ziel: Path):
        geladen.append(url)
        ziel.write_bytes(archiv)

    ordner = rls.raeder_bereitstellen(tmp_path / "raeder", FASSUNGEN, lade_fn=lade)

    assert geladen == [rls.CTRANSLATE2_ARCHIV_URL]
    assert sorted(p.name for p in ordner.glob("*.whl")) == sorted(RAEDER[1:3])  # nur cp310 und cp311
    # Ein zweiter Lauf nutzt das gepruefte Archiv und laedt nichts.
    rls.raeder_bereitstellen(tmp_path / "raeder", FASSUNGEN, lade_fn=lambda *a: pytest.fail("kein Download"))


def test_falsche_pruefsumme_wird_verworfen(tmp_path, archiv):
    with pytest.raises(rls.RocmEinrichtungsFehler, match="Prüfsumme"):
        rls.raeder_bereitstellen(tmp_path, FASSUNGEN, lade_fn=lambda url, ziel: ziel.write_bytes(b"manipuliert"))
    assert list(tmp_path.iterdir()) == []


def test_fehlende_python_fassung_im_archiv(tmp_path, monkeypatch):
    inhalt = _archiv(RAEDER[:1])
    monkeypatch.setattr(rls, "CTRANSLATE2_ARCHIV_SHA256", hashlib.sha256(inhalt).hexdigest())
    with pytest.raises(rls.RocmEinrichtungsFehler, match="fehlen"):
        rls.raeder_bereitstellen(tmp_path, FASSUNGEN, lade_fn=lambda url, ziel: ziel.write_bytes(inhalt))


def test_amd_pakete_kommen_nach_den_normalen_mit_festen_pruefsummen(tmp_path):
    python = tmp_path / "python.exe"
    befehle = environment_service.build_pip_install_commands(python, False, rocm_raeder=tmp_path / "raeder")
    assert len(befehle) == 5
    rocm, ctranslate = befehle[3], befehle[4]
    assert all("#sha256=" in paket for paket in rls.ROCM_PAKETE) and rocm[-3:] == rls.ROCM_PAKETE
    assert "--no-index" in ctranslate and "--force-reinstall" in ctranslate
    assert ctranslate[-1] == f"ctranslate2=={rls.CTRANSLATE2_VERSION}"
    # Ohne AMD bleibt alles wie bisher.
    assert len(environment_service.build_pip_install_commands(python, False)) == 3


def test_amd_aendert_die_einrichtungskennung(tmp_path):
    url = environment_service.TORCH_CPU_INDEX_URL
    assert environment_service.einrichtungs_kennung(url) != environment_service.einrichtungs_kennung(url, True)
    environment_service.kennung_festhalten(tmp_path, url, amd_rocm=True)
    assert environment_service.einrichtung_ist_aktuell(tmp_path, url, amd_rocm=True)
    assert not environment_service.einrichtung_ist_aktuell(tmp_path, url)  # CPU-Umgebung -> neu einrichten


def test_plan_nennt_amd():
    assert "AMD-Grafikkarte (ROCm)" in environment_service.describe_plan(False, amd_rocm=True)
    assert "ROCm" not in environment_service.describe_plan(False)


# --------------------------------------------------------------------------
# Zur Laufzeit: Whisper auf der AMD-Karte
# --------------------------------------------------------------------------
class _Ctranslate2:
    def __init__(self, geraete=1, typen=("float16", "float32")):
        self.geraete, self.typen = geraete, typen

    def get_cuda_device_count(self):
        return self.geraete

    def get_supported_compute_types(self, geraet):
        return set(self.typen)


def _umgebung(monkeypatch, *, rocm=True, ct2=None):
    import sys

    monkeypatch.setattr(rls, "laufzeit_aktiv", lambda: rocm)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2 or _Ctranslate2())
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: False)


def test_whisper_rechnet_auf_der_amd_karte(monkeypatch):
    _umgebung(monkeypatch)
    assert model_service.amd_whisper_kann_rechnen()
    assert model_service.get_device_and_compute_type("cuda") == ("cuda", "float16")
    assert model_service.get_device_and_compute_type("cpu") == ("cpu", "int8")


@pytest.mark.parametrize(
    "einstellung",
    [{"rocm": False}, {"ct2": _Ctranslate2(geraete=0)}, {"ct2": _Ctranslate2(typen=("float32",))}],
)
def test_ohne_rocm_oder_karte_bleibt_es_bei_der_cpu(monkeypatch, einstellung):
    _umgebung(monkeypatch, **einstellung)
    assert not model_service.amd_whisper_kann_rechnen()
    assert model_service.get_device_and_compute_type("cuda") == ("cpu", "int8")


def test_kaputte_rocm_umgebung_faellt_auf_die_cpu_zurueck(monkeypatch):
    class Kaputt(_Ctranslate2):
        def get_cuda_device_count(self):
            raise RuntimeError("hipErrorNoDevice")

    _umgebung(monkeypatch, ct2=Kaputt())
    assert not model_service.amd_whisper_kann_rechnen()


def test_grafikspeicher_kommt_bei_amd_ueber_hip(monkeypatch):
    _umgebung(monkeypatch)
    monkeypatch.setattr(model_service, "_hip_speicher", lambda: (6 * 1024**3, 16 * 1024**3))
    assert model_service.freier_grafikspeicher() == 6 * 1024**3
    assert model_service.gesamter_grafikspeicher() == 16 * 1024**3


def test_beschreibung_der_amd_karte(monkeypatch):
    import sys
    import types

    _umgebung(monkeypatch)
    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", torch)  # auf AMD: der CPU-Build
    assert "AMD-Grafikkarte (ROCm)" in model_service.get_gpu_description()
    monkeypatch.setattr(rls, "laufzeit_aktiv", lambda: False)
    assert "keine nutzbare Grafikkarte" in model_service.get_gpu_description()


def test_hip_speicher_ueber_die_treiberbibliothek():
    class Hip:
        def __init__(self, code):
            self.code = code

        def hipMemGetInfo(self, frei, gesamt):  # noqa: N802 - Name der HIP-Funktion
            frei._obj.value, gesamt._obj.value = 3, 16  # ctypes.byref(...) -> das c_size_t dahinter
            return self.code

    assert model_service._hip_speicher(lambda name: Hip(0)) == (3, 16)
    assert model_service._hip_speicher(lambda name: Hip(1)) is None

    def fehlt(name):
        raise OSError(name)

    assert model_service._hip_speicher(fehlt) is None
