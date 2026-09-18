# start_lokal.ps1
# Direkter Startweg ohne Einrichtungsstatus-Pruefung (siehe stattdessen
# 'Anwendung-starten.ps1' fuer die gefuehrte Startsperre). Nuetzlich fuer
# die Entwicklung bzw. wenn die Einrichtung bereits nachweislich
# vollstaendig ist.
#
# Verwendet automatisch die passende virtuelle Umgebung: eine bereits
# vorhandene '.venv-whisperx' (Referenzrechner) hat Vorrang, sonst die
# selbst verwaltete 'runtime\venv'. Existiert noch KEINE der beiden, wird
# einfach 'app.py' mit dem System-Python gestartet -- die Anwendung legt
# die Umgebung dann beim ersten Start selbst an (siehe 'bootstrap.py').

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir "_env_helper.ps1")

$VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    Write-Host "Hinweis: Noch keine vorbereitete Umgebung gefunden -- 'app.py' richtet" -ForegroundColor DarkYellow
    Write-Host "sich beim ersten Start automatisch ein (kann einige Minuten dauern)."
    $PythonExe = "python"
}

$env:PYTHONIOENCODING = "utf-8"
Push-Location $ScriptDir
try {
    & $PythonExe (Join-Path $ScriptDir "app.py")
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
