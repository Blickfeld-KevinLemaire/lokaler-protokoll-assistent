# check_pyannote_fix.ps1
# Prueft und -- falls eindeutig moeglich -- korrigiert die pyannote-
# Kompatibilitaetsabsicherung fuer sehr kurze Audioteile
# (siehe utils/pyannote_patch.py fuer die Details der Korrektur).
#
# Wird NICHT automatisch bei jedem Anwendungsstart aufgerufen, sondern nur
# gezielt hier bzw. waehrend der Einrichtung (Einrichtung-Lokal.ps1 / setup_lokal.ps1).
#
# Zusaetzliche Parameter werden unveraendert an utils/pyannote_patch.py
# weitergereicht, z.B.:
#   .\check_pyannote_fix.ps1 -DryRun   -> nur pruefen, nichts veraendern

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir "_env_helper.ps1")
$VenvDir = Get-ActiveVenvDir -ScriptDir $ScriptDir
$VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir

if (-not (Test-Path $VenvPython)) {
    Write-Host "FEHLER: Es wurde keine virtuelle Umgebung gefunden unter:" -ForegroundColor Red
    Write-Host "  $VenvDir"
    Write-Host "Bitte zuerst '.\Start-Protokoll-Assistent.ps1' einmal ausfuehren."
    exit 1
}

$patchArgs = @("--venv", $VenvDir)
if ($DryRun) { $patchArgs += "--dry-run" }

# Aus der Projektwurzel heraus und als Modul (siehe setup_lokal.ps1).
Push-Location (Split-Path -Parent $ScriptDir)
try {
    & $VenvPython -m protokoll_assistent.utils.pyannote_patch @patchArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
