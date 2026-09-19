from pathlib import Path

from services import environment_service as env


def test_supported_python_versions():
    assert env.is_supported_python_version((3, 10)) is True
    assert env.is_supported_python_version((3, 11)) is True
    assert env.is_supported_python_version((3, 12)) is False
    assert env.is_supported_python_version((3, 9)) is False


def test_python_version_error_message_names_versions():
    message = env.python_version_error_message((3, 12))
    assert "3.12" in message
    assert "3.10" in message and "3.11" in message


def test_detect_nvidia_gpu_true_when_nvidia_smi_present(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    assert env.detect_nvidia_gpu() is True


def test_detect_nvidia_gpu_false_when_absent(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda name: None)
    assert env.detect_nvidia_gpu() is False


def test_select_torch_index_url_differs_for_gpu_and_cpu():
    # Rechenfaehigkeit ausdruecklich vorgeben, damit der Test nicht davon
    # abhaengt, welche Karte im Testrechner steckt.
    gpu_url = env.select_torch_index_url(True, compute_capability=(8, 6))
    cpu_url = env.select_torch_index_url(False)
    assert gpu_url != cpu_url
    assert "cu" in gpu_url
    assert "cpu" in cpu_url


def test_build_pip_install_commands_uses_correct_python_and_index(tmp_path, monkeypatch):
    # Karte fest vorgeben: sonst haengt der Test davon ab, welche GPU im
    # Testrechner steckt (Blackwell bekommt einen anderen Index).
    monkeypatch.setattr(env, "detect_compute_capability", lambda: (8, 6))
    python_exe = tmp_path / "venv" / "Scripts" / "python.exe"
    commands = env.build_pip_install_commands(python_exe, gpu_available=True)
    assert all(command[0] == str(python_exe) for command in commands)
    torch_command = commands[1]
    assert "--index-url" in torch_command
    assert env.TORCH_CUDA_INDEX_URL in torch_command
    # Die Eintraege tragen eine Versionsangabe ("torch~=2.8.0"), deshalb
    # wird auf den Paketnamen geprueft und nicht auf die ganze Zeichenkette.
    assert any(eintrag.startswith("torch") for eintrag in torch_command)
    assert any(eintrag.startswith("torchaudio") for eintrag in torch_command)


def test_build_pip_install_commands_blackwell_variante(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "detect_compute_capability", lambda: (12, 0))
    commands = env.build_pip_install_commands(tmp_path / "python.exe", gpu_available=True)
    assert env.TORCH_CUDA_BLACKWELL_INDEX_URL in commands[1]


def test_build_pip_install_commands_cpu_variant(tmp_path):
    python_exe = tmp_path / "venv" / "bin" / "python"
    commands = env.build_pip_install_commands(python_exe, gpu_available=False)
    torch_command = commands[1]
    assert env.TORCH_CPU_INDEX_URL in torch_command


def test_build_pip_install_commands_never_uses_shell_string():
    commands = env.build_pip_install_commands(Path("python"), gpu_available=False)
    for command in commands:
        assert isinstance(command, list)
        assert all(isinstance(part, str) for part in command)


def test_describe_plan_mentions_device():
    assert "GPU" in env.describe_plan(True)
    assert "CPU" in env.describe_plan(False)


def test_find_alternate_supported_python_via_py_launcher(monkeypatch):
    monkeypatch.setattr(env.sys, "platform", "win32")
    monkeypatch.setattr(env.shutil, "which", lambda name: r"C:\Windows\py.exe" if name == "py" else None)

    def fake_run(command, capture_output, text, timeout):
        assert command[0] == r"C:\Windows\py.exe"
        if command[1] == "-3.10":
            class _Result:
                returncode = 1
                stdout = ""

            return _Result()

        class _Result:
            returncode = 0
            stdout = r"C:\Python311\python.exe" + "\n"

        return _Result()

    monkeypatch.setattr(env.subprocess, "run", fake_run)
    gefunden = env.find_alternate_supported_python()
    assert gefunden == Path(r"C:\Python311\python.exe")


def test_find_alternate_supported_python_returns_none_when_py_launcher_missing(monkeypatch):
    monkeypatch.setattr(env.sys, "platform", "win32")
    monkeypatch.setattr(env.shutil, "which", lambda name: None)
    assert env.find_alternate_supported_python() is None


def test_find_alternate_supported_python_falls_back_to_command_name_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(env.sys, "platform", "linux")
    fake_python = tmp_path / "python3.11"
    fake_python.write_text("dummy", encoding="utf-8")

    def fake_which(name):
        return str(fake_python) if name == "python3.11" else None

    monkeypatch.setattr(env.shutil, "which", fake_which)
    assert env.find_alternate_supported_python() == fake_python


def test_find_alternate_supported_python_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(env.sys, "platform", "linux")
    monkeypatch.setattr(env.shutil, "which", lambda name: None)
    assert env.find_alternate_supported_python() is None


def test_pruefe_py_launcher_version_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda name: "py")

    def fake_run(*args, **kwargs):
        raise env.subprocess.TimeoutExpired(cmd="py", timeout=10)

    monkeypatch.setattr(env.subprocess, "run", fake_run)
    assert env._pruefe_py_launcher_version(3, 11) is None


# ---------------------------------------------------------------------------
# Paketlisten als Dateien (damit Dependabot und pip-audit sie sehen)
# ---------------------------------------------------------------------------
def test_requirements_dateien_liegen_neben_der_anwendung():
    assert env.TORCH_REQUIREMENTS_FILE.is_file()
    assert env.RUNTIME_REQUIREMENTS_FILE.is_file()


def test_read_requirements_ueberspringt_kommentare_und_leerzeilen(tmp_path):
    datei = tmp_path / "requirements-test.txt"
    datei.write_text(
        "# Kommentarzeile\n"
        "\n"
        "paket-a>=1.0\n"
        "   \n"
        "paket-b==2.3  # Kommentar am Zeilenende\n",
        encoding="utf-8",
    )

    assert env.read_requirements(datei) == ["paket-a>=1.0", "paket-b==2.3"]


def test_read_requirements_kommt_mit_bom_zurecht(tmp_path):
    # Editoren unter Windows schreiben gern eine Byte-Order-Mark.
    datei = tmp_path / "requirements-bom.txt"
    datei.write_text("paket-a>=1.0\n", encoding="utf-8-sig")

    assert env.read_requirements(datei) == ["paket-a>=1.0"]


def test_paketlisten_sind_nicht_leer():
    # Ein Tippfehler im Dateinamen wuerde sonst still zu einer leeren
    # Installation fuehren.
    assert any(paket.startswith("torch") for paket in env.TORCH_PACKAGES)
    assert any(paket.lower().startswith("whisperx") for paket in env.RUNTIME_PACKAGES)


def test_pip_befehle_enthalten_die_pakete_aus_den_dateien():
    commands = env.build_pip_install_commands(Path("python"), gpu_available=True)
    torch_befehl, runtime_befehl = commands[1], commands[2]
    for paket in env.TORCH_PACKAGES:
        assert paket in torch_befehl
    for paket in env.RUNTIME_PACKAGES:
        assert paket in runtime_befehl


# ---------------------------------------------------------------------------
# Kartengeneration -> passender CUDA-Index
# ---------------------------------------------------------------------------
class _SmiErgebnis:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_alte_karten_bekommen_den_aelteren_index():
    # Pascal, Turing, Ampere, Ada: Kernel fuer sie gibt es im neuen Index
    # nicht mehr.
    for rechenfaehigkeit in [(6, 1), (7, 5), (8, 6), (8, 9), (9, 0)]:
        url = env.select_torch_index_url(True, compute_capability=rechenfaehigkeit)
        assert url == env.TORCH_CUDA_INDEX_URL, rechenfaehigkeit


def test_blackwell_bekommt_den_neueren_index():
    # sm_120 gibt es erst ab CUDA 12.8 - der aeltere Index hat dafuer keine
    # Kernel.
    for rechenfaehigkeit in [(12, 0), (12, 1), (13, 0)]:
        url = env.select_torch_index_url(True, compute_capability=rechenfaehigkeit)
        assert url == env.TORCH_CUDA_BLACKWELL_INDEX_URL, rechenfaehigkeit


def test_unbekannte_rechenfaehigkeit_nimmt_den_breiteren_index(monkeypatch):
    # Im Zweifel den Index, der auf mehr Karten laeuft.
    monkeypatch.setattr(env, "detect_compute_capability", lambda: None)
    assert env.select_torch_index_url(True) == env.TORCH_CUDA_INDEX_URL


def test_ohne_gpu_immer_der_cpu_index():
    assert env.select_torch_index_url(False, compute_capability=(12, 0)) == env.TORCH_CPU_INDEX_URL


def test_detect_compute_capability_liest_nvidia_smi(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(env.subprocess, "run", lambda *_a, **_k: _SmiErgebnis(stdout="12.0\n"))
    assert env.detect_compute_capability() == (12, 0)


def test_detect_compute_capability_nimmt_die_erste_karte(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(env.subprocess, "run", lambda *_a, **_k: _SmiErgebnis(stdout="8.6\n12.0\n"))
    assert env.detect_compute_capability() == (8, 6)


def test_detect_compute_capability_ohne_nvidia_smi(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _name: None)
    assert env.detect_compute_capability() is None


def test_detect_compute_capability_bei_fehler(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(env.subprocess, "run", lambda *_a, **_k: _SmiErgebnis(returncode=9))
    assert env.detect_compute_capability() is None


def test_detect_compute_capability_bei_unerwarteter_ausgabe(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(env.subprocess, "run", lambda *_a, **_k: _SmiErgebnis(stdout="N/A\n"))
    assert env.detect_compute_capability() is None


def test_detect_compute_capability_bei_abbruch(monkeypatch):
    def werfen(*_a, **_k):
        raise OSError("nvidia-smi laesst sich nicht starten")

    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(env.subprocess, "run", werfen)
    assert env.detect_compute_capability() is None


def test_torch_hat_eine_versionsangabe():
    """Ohne Versionsangabe holt der erste pip-Aufruf die neueste Fassung aus
    dem CUDA-Index, und der zweite ersetzt sie durch eine CPU-Fassung von
    PyPI - die GPU-Unterstuetzung waere still weg. Am 19.09.2026 in einer
    echten Installation gemessen: 2.14.0+cu126 wurde zu 2.8.0+cpu."""
    for paket in env.TORCH_PACKAGES:
        assert any(zeichen in paket for zeichen in "~=<>"), paket
