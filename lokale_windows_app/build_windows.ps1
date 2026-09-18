# build_windows.ps1
# Erstellt die Windows-EXE als One-Directory-Build (nicht One-File, da
# WhisperX/PyTorch/CUDA dafuer ungeeignet gross sind).
#
# WICHTIG: Dieser Build kann nicht in der Entwicklungsumgebung (ohne Windows
# und ohne GPU) getestet werden. Bitte nach dem Build unbedingt lokal
# gemaess README.md pruefen.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir "_env_helper.ps1")
$VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir

if (-not (Test-Path $VenvPython)) {
    Write-Host "FEHLER: Es wurde keine virtuelle Umgebung gefunden." -ForegroundColor Red
    Write-Host "Bitte zuerst '.\Start-Protokoll-Assistent.ps1' einmal ausfuehren, damit sich"
    Write-Host "die Anwendung selbst einrichtet."
    exit 1
}

Write-Host "Stelle sicher, dass PyInstaller in dieser Umgebung installiert ist ..."
& $VenvPython -m pip install --quiet pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: PyInstaller konnte nicht installiert werden." -ForegroundColor Red
    exit 1
}

Write-Host "=== Windows-Build (One-Directory) wird erstellt ===" -ForegroundColor Cyan
Push-Location $ScriptDir
try {
    & $VenvPython -m PyInstaller --noconfirm protokoll_assistent_lokal.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller ist mit Exit-Code $LASTEXITCODE fehlgeschlagen."
    }
} finally {
    Pop-Location
}

$ExePath = Join-Path $ScriptDir "dist\Protokoll-Assistent-Lokal\Protokoll-Assistent-Lokal.exe"
Write-Host "`n=== Build abgeschlossen ===" -ForegroundColor Green
Write-Host "Ausfuehrbare Datei: $ExePath"
Write-Host ""
Write-Host "Hinweise:"
Write-Host "  - Modelldateien werden NICHT in den Build kopiert. Die EXE verwendet"
Write-Host "    Ihren vorhandenen Hugging-Face-/Ollama-Cache auf diesem Rechner."
Write-Host "  - Bitte testen Sie die EXE einmal lokal (siehe README.md), bevor Sie"
Write-Host "    sie weitergeben oder produktiv verwenden."
Write-Host "  - Kopieren Sie NICHT den 'dist'-Ordner auf einen anderen Rechner ohne"
Write-Host "    die gleichen Modelle/Caches -- die Anwendung transkribiert nur lokal"
Write-Host "    vorhandene Modelle, laedt aber im Offline-Modus nichts automatisch nach."
