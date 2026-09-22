"""Diagnosepruefungen duerfen auch ohne GPU/faster-whisper/pyannote/Ollama nicht
abstuerzen -- fehlende Komponenten muessen als 'nicht verfuegbar' erkannt
werden, statt eine Ausnahme auszuloesen."""

import os

import pytest

from protokoll_assistent.utils import diagnostics


def test_check_python_version_returns_result():
    result = diagnostics.check_python_version()
    assert result.key == "python_version"
    assert isinstance(result.ok, bool)


def test_check_cuda_does_not_crash_without_torch():
    result = diagnostics.check_cuda()
    assert result.key == "cuda"
    assert isinstance(result.ok, bool)


def test_check_cuda_is_not_critical_since_cpu_fallback_is_supported():
    # Portabilitaetsanforderung: die Anwendung muss auch auf einem PC ohne
    # NVIDIA-GPU lauffaehig bleiben (nur langsamer), daher darf ein
    # fehlendes CUDA die Systemdiagnose nicht als kritischen Fehler werten.
    result = diagnostics.check_cuda()
    assert result.critical is False


def test_check_torch_installed_is_critical():
    result = diagnostics.check_torch_installed()
    assert result.key == "torch"
    assert result.critical is True


def test_run_diagnostics_includes_torch_check(tmp_path):
    results = diagnostics.run_diagnostics(output_dir=tmp_path)
    keys = {check.key for check in results}
    assert "torch" in keys


def test_check_ffmpeg_reports_missing_gracefully(monkeypatch):
    from protokoll_assistent.services import ffmpeg_service

    monkeypatch.setattr(ffmpeg_service, "find_ffmpeg", lambda: None)
    result = diagnostics.check_ffmpeg()
    assert result.ok is False
    assert result.critical is True


def test_check_output_dir_writable_true_for_writable_dir(tmp_path):
    result = diagnostics.check_output_dir_writable(tmp_path)
    assert result.ok is True


# 'os.geteuid' gibt es nur unter POSIX. Unter Windows entzieht 'chmod(0o500)'
# einem Ordner ausserdem gar kein Schreibrecht - dieser Test kann dort also
# nicht greifen. Den Fehlerfall deckt stattdessen der Test darunter ab, der
# auf beiden Systemen laeuft.
_IST_POSIX = os.name == "posix"
_IST_ROOT = _IST_POSIX and os.geteuid() == 0


@pytest.mark.skipif(
    not _IST_POSIX or _IST_ROOT,
    reason="Schreibrechte lassen sich nur unter POSIX und nicht als root zuverlaessig entziehen.",
)
def test_check_output_dir_writable_false_for_readonly_dir(tmp_path):
    readonly_dir = tmp_path / "gesperrt"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)
    try:
        result = diagnostics.check_output_dir_writable(readonly_dir / "unterordner" / "datei_ziel")
        assert result.ok is False
    finally:
        readonly_dir.chmod(0o700)


def test_check_output_dir_writable_false_when_parent_is_a_file(tmp_path):
    """Plattformunabhaengiger Fehlerfall: der uebergeordnete Pfad ist eine Datei,
    'mkdir' muss deshalb scheitern."""
    blockierende_datei = tmp_path / "keine_ordner_datei.txt"
    blockierende_datei.write_text("belegt", encoding="utf-8")

    result = diagnostics.check_output_dir_writable(blockierende_datei / "unterordner")

    assert result.ok is False
    assert result.critical is True


def test_check_hf_token_reflects_environment(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert diagnostics.check_hf_token().ok is False
    monkeypatch.setenv("HF_TOKEN", "geheim")
    assert diagnostics.check_hf_token().ok is True


def test_check_ollama_installed_does_not_crash_without_ollama(monkeypatch):
    from protokoll_assistent.services import ollama_service

    monkeypatch.setattr(ollama_service, "find_ollama_executable", lambda: None)
    result = diagnostics.check_ollama_installed()
    assert result.ok is False


def test_run_diagnostics_returns_all_checks_without_crashing(tmp_path):
    results = diagnostics.run_diagnostics(output_dir=tmp_path)
    keys = {check.key for check in results}
    assert "python_version" in keys
    assert "ffmpeg" in keys
    assert "ollama_model" in keys
    assert all(isinstance(check.ok, bool) for check in results)


def test_format_report_produces_readable_lines(tmp_path):
    results = diagnostics.run_diagnostics(output_dir=tmp_path)
    report = diagnostics.format_report(results)
    assert isinstance(report, str)
    assert len(report.splitlines()) == len(results)


# ---------------------------------------------------------------------------
# CUDA-Meldung deckt sich mit dem, was die Verarbeitung tatsaechlich tut
# ---------------------------------------------------------------------------
class _TorchAttrappe:
    """Bildet nur so viel von torch nach, wie check_cuda() anfasst."""

    def __init__(self, verfuegbar: bool, name: str = "Testkarte") -> None:
        self._verfuegbar = verfuegbar
        self._name = name
        self.cuda = self

    def is_available(self) -> bool:
        return self._verfuegbar

    def get_device_name(self, _index: int) -> str:
        return self._name


def _torch_ersetzen(monkeypatch, torch_attrappe):
    import sys

    monkeypatch.setitem(sys.modules, "torch", torch_attrappe)


def test_cuda_meldung_ohne_karte(monkeypatch):
    _torch_ersetzen(monkeypatch, _TorchAttrappe(verfuegbar=False))

    ergebnis = diagnostics.check_cuda()

    assert ergebnis.ok is False
    assert "Keine CUDA-GPU erkannt" in ergebnis.detail


def test_cuda_meldung_mit_benutzbarer_karte(monkeypatch):
    from protokoll_assistent.services import model_service

    _torch_ersetzen(monkeypatch, _TorchAttrappe(verfuegbar=True, name="RTX 4070"))
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: True)

    ergebnis = diagnostics.check_cuda()

    assert ergebnis.ok is True
    assert "RTX 4070" in ergebnis.detail


def test_cuda_meldung_bei_unpassendem_torch_build(monkeypatch):
    # Der Kernfall: 'torch.cuda.is_available()' sagt True, die Karte laesst
    # sich aber nicht benutzen (cu126-Build auf einer Blackwell-Karte).
    # Frueher meldete die Diagnose hier "CUDA verfuegbar", waehrend das
    # Hauptfenster im selben Lauf "nicht benutzbar ... CPU-Verarbeitung"
    # anzeigte - zwei Auskuenfte fuer denselben Rechner.
    from protokoll_assistent.services import model_service

    _torch_ersetzen(monkeypatch, _TorchAttrappe(verfuegbar=True, name="RTX PRO 500"))
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: False)

    ergebnis = diagnostics.check_cuda()

    assert ergebnis.ok is False
    assert "RTX PRO 500" in ergebnis.detail
    assert "nicht benutzbar" in ergebnis.detail
    assert "CPU" in ergebnis.detail
    # Weiterhin kein kritischer Fehler: CPU-Betrieb ist vorgesehen.
    assert ergebnis.critical is False


def test_cuda_meldung_deckt_sich_mit_der_geraetewahl(monkeypatch):
    # Gegenprobe ueber beide Seiten: Was die Diagnose sagt, muss zu dem
    # passen, was 'get_device_and_compute_type' danach tatsaechlich waehlt.
    from protokoll_assistent.services import model_service

    _torch_ersetzen(monkeypatch, _TorchAttrappe(verfuegbar=True, name="RTX PRO 500"))
    monkeypatch.setattr(model_service, "cuda_kann_wirklich_rechnen", lambda: False)

    ergebnis = diagnostics.check_cuda()
    geraet, _rechenart = model_service.get_device_and_compute_type("cuda")

    assert ergebnis.ok is (geraet == "cuda")
