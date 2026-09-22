# _env_helper.ps1
# Gemeinsame Hilfsfunktion fuer alle anderen .ps1-Skripte: ermittelt, welche
# virtuelle Umgebung verwendet werden soll -- entspricht der Logik aus
# utils/paths.py::get_active_venv_dir (eine bereits vorhandene
# '.venv-whisperx' NEBEN der Anwendung hat Vorrang, andernfalls die
# selbst verwaltete 'runtime\venv', die 'bootstrap.py' bei Bedarf
# automatisch anlegt). Macht die Anwendung unabhaengig von einem einzelnen,
# manuell vorbereiteten Rechner.
#
# Verwendung in einem anderen Skript:
#   . (Join-Path $ScriptDir "_env_helper.ps1")
#   $VenvDir = Get-ActiveVenvDir -ScriptDir $ScriptDir
#   $VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir

function Get-ActiveVenvDir {
    param([string]$ScriptDir)
    $ProjectRoot = Split-Path -Parent $ScriptDir
    $LegacyDir = Join-Path $ProjectRoot ".venv-whisperx"
    if (Test-Path (Join-Path $LegacyDir "Scripts\python.exe")) {
        return $LegacyDir
    }
    return Join-Path $ScriptDir "runtime\venv"
}

function Get-ActiveVenvPython {
    param([string]$ScriptDir)
    return Join-Path (Get-ActiveVenvDir -ScriptDir $ScriptDir) "Scripts\python.exe"
}
