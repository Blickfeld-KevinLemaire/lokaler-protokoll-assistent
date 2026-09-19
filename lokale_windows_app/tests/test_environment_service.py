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
    gpu_url = env.select_torch_index_url(True)
    cpu_url = env.select_torch_index_url(False)
    assert gpu_url != cpu_url
    assert "cu" in gpu_url
    assert "cpu" in cpu_url


def test_build_pip_install_commands_uses_correct_python_and_index(tmp_path):
    python_exe = tmp_path / "venv" / "Scripts" / "python.exe"
    commands = env.build_pip_install_commands(python_exe, gpu_available=True)
    assert all(command[0] == str(python_exe) for command in commands)
    torch_command = commands[1]
    assert "--index-url" in torch_command
    assert env.TORCH_CUDA_INDEX_URL in torch_command
    assert "torch" in torch_command
    assert "torchaudio" in torch_command


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
