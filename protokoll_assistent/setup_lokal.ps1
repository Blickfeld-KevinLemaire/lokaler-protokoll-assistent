# setup_lokal.ps1
# Manueller/fortgeschrittener Weg NUR fuer einen Rechner, der bereits eine
# vollstaendig eingerichtete '.venv-whisperx' mitbringt (WhisperX, PyTorch,
# pyannote). Auf einem neuen PC OHNE eine solche Umgebung ist dieses Skript
# NICHT noetig: einfach '.\Start-Protokoll-Assistent.ps1' ausfuehren -- die
# Anwendung richtet sich dann automatisch selbst ein (siehe 'bootstrap.py').
#
# Verwendet AUSSCHLIESSLICH die bereits vorhandene virtuelle Umgebung
# '.venv-whisperx' neben diesem Ordner ('protokoll-assistent\.venv-whisperx').
# Es wird NICHTS in die globale Python-Installation installiert.
# Vorhandene WhisperX-/PyTorch-/CUDA-Pakete werden NICHT ersetzt, da
# requirements-anwendung.txt sie bewusst nicht auflistet.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvDir = Join-Path $ProjectRoot ".venv-whisperx"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "=== Protokoll-Assistent: Einrichtung der Python-Umgebung ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Host "FEHLER: Virtuelle Umgebung nicht gefunden unter:" -ForegroundColor Red
    Write-Host "  $VenvPython"
    Write-Host "Bitte zuerst '.venv-whisperx' gemaess Ihrer bestehenden WhisperX-Einrichtung anlegen"
    Write-Host "(Python 3.10.11, WhisperX, PyTorch mit CUDA, pyannote.audio)."
    exit 1
}
Write-Host "Verwende vorhandene virtuelle Umgebung: $VenvDir"

Write-Host "`nInstalliere GUI-/Build-Abhaengigkeiten (PySide6, PyInstaller) ..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Host "FEHLER: pip-Upgrade fehlgeschlagen." -ForegroundColor Red; exit 1 }

& $VenvPython -m pip install -r (Join-Path $ScriptDir "requirements-anwendung.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: 'pip install -r requirements-anwendung.txt' ist fehlgeschlagen." -ForegroundColor Red
    exit 1
}

Write-Host "`nPruefe pyannote-Kompatibilitaetskorrektur (kurze Audioteile / NaN-Absicherung) ..."
# Aus der Projektwurzel heraus und als Modul - sonst findet Python das
# Paket 'protokoll_assistent' nicht.
Push-Location $ProjectRoot
try {
    & $VenvPython -m protokoll_assistent.utils.pyannote_patch --venv $VenvDir
    # Hinweis: Ein Exit-Code ungleich 0 bedeutet meist nur, dass die betroffene
    # Zeile nicht eindeutig gefunden wurde (z.B. andere pyannote-Version) -- das
    # ist kein Abbruchgrund fuer die gesamte Einrichtung.

    Write-Host "`nFuehre Systempruefung aus ..."
    & $VenvPython -m protokoll_assistent.systempruefung
} finally {
    Pop-Location
}

Write-Host "`n=== Einrichtung der Python-Umgebung abgeschlossen ===" -ForegroundColor Green
Write-Host "Fuer die vollstaendige, gefuehrte Einrichtung (inkl. Modell-Download und"
Write-Host "Offline-Pruefung) verwenden Sie stattdessen: .\Einrichtung-Lokal.ps1"
