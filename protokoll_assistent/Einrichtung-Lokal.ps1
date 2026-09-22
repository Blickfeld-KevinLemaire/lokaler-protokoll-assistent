# Einrichtung-Lokal.ps1
# FORTGESCHRITTENER/MANUELLER Weg mit expliziter Status-Datei
# ('Einrichtungsstatus.json') und Offline-Nachweis -- fuer Faelle, in denen
# Sie die Einrichtung unabhaengig vom GUI-Assistenten und nachvollziehbar
# protokolliert durchfuehren moechten (z.B. IT-Rollout auf mehreren PCs).
#
# Auf einem einzelnen, neuen PC reicht in der Regel einfach
# '.\Start-Protokoll-Assistent.ps1' -- die Anwendung richtet sich dann beim
# ersten Start automatisch selbst ein (inkl. eigener 'runtime\venv') und
# fuehrt direkt in der Oberflaeche durch Einrichtung, Systemtest und
# Eingabeordner-Auswahl.
#
# Ablauf in 5 nachvollziehbaren Phasen:
# Phase 1: Systempruefung (Windows, Python 3.10, NVIDIA-GPU/-Treiber, CUDA,
#          RAM, Speicherplatz, FFmpeg/ffprobe, Ollama)
# Phase 2: Python-Umgebung (PySide6, PyInstaller, pyannote-Korrektur) --
#          delegiert an setup_lokal.ps1 und setzt daher eine bereits
#          vorhandene '.venv-whisperx' voraus (siehe dortige Hinweise).
# Phase 3: Lokale Modelle herunterladen (WhisperX, Alignment, pyannote,
#          Ollama-Modell qwen3:8b) -- modelle_herunterladen
# Phase 4: Offline-Funktionspruefung (alles laeuft ohne Internetzugriff)
# Phase 5: Abschluss -- Einrichtungsstatus.json wird als vollstaendig markiert
#
# Bereits erfolgreich abgeschlossene Phasen werden NICHT wiederholt (auch
# nicht bereits heruntergeladene Modelle oder installierte Pakete), ausser
# der Parameter -Force wird angegeben. Nach einem Fehler kann dieses Skript
# einfach erneut ausgefuehrt werden -- es setzt automatisch bei der zuletzt
# fehlgeschlagenen Phase fort.

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir "_env_helper.ps1")
$VenvDir = Get-ActiveVenvDir -ScriptDir $ScriptDir
$VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir

function Test-PhaseDone {
    param([string]$Phase)
    if (-not (Test-Path $VenvPython)) { return $false }
    Push-Location $ScriptDir
    try {
        $result = & $VenvPython -c "from utils.setup_status import load_status, missing_phases; print('0' if '$Phase' in missing_phases(load_status()) else '1')" 2>$null
    } catch {
        $result = "0"
    } finally {
        Pop-Location
    }
    return $result -eq "1"
}

function Set-PhaseDone {
    param([string]$Phase)
    Push-Location $ScriptDir
    try {
        & $VenvPython -c "from utils.setup_status import load_status, save_status, mark_phase; s=load_status(); mark_phase(s,'$Phase', True); save_status(s)"
    } finally {
        Pop-Location
    }
}

Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host " PROTOKOLL-ASSISTENT LOKAL -- VOLLSTAENDIGE EINRICHTUNG" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "Diese Einrichtung arbeitet in 5 nachvollziehbaren Phasen und kann nach"
Write-Host "einem Fehler jederzeit erneut gestartet werden -- bereits erfolgreiche"
Write-Host "Phasen werden dabei nicht wiederholt (ausser mit -Force)."

# --- Phase 1: Systempruefung -------------------------------------------
Write-Host "`n--- PHASE 1: SYSTEMPRUEFUNG ---" -ForegroundColor Yellow
if (-not $Force -and (Test-PhaseDone "systempruefung")) {
    Write-Host "Bereits erfolgreich abgeschlossen -- wird uebersprungen."
} else {
    $bootstrapPython = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
    Push-Location $ScriptDir
    try {
        & $bootstrapPython -m protokoll_assistent.systempruefung
        $phase1ExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($phase1ExitCode -ne 0) {
        Write-Host "`nPhase 1 ist fehlgeschlagen. Bitte die oben genannten Voraussetzungen beheben." -ForegroundColor Red
        Write-Host "Fuehren Sie 'Einrichtung-Lokal.ps1' danach erneut aus."
        exit 1
    }
}

# --- Phase 2: Python-Umgebung -------------------------------------------
Write-Host "`n--- PHASE 2: PYTHON-UMGEBUNG ---" -ForegroundColor Yellow
if (-not $Force -and (Test-PhaseDone "python_umgebung")) {
    Write-Host "Bereits erfolgreich abgeschlossen -- wird uebersprungen."
} else {
    & (Join-Path $ScriptDir "setup_lokal.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nPhase 2 ist fehlgeschlagen." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Host "`nFEHLER: '.venv-whisperx' wurde auch nach Phase 2 nicht gefunden." -ForegroundColor Red
        exit 1
    }
    Set-PhaseDone "python_umgebung"
}

# --- Phase 3: Lokale Modelle ---------------------------------------------
Write-Host "`n--- PHASE 3: LOKALE MODELLE HERUNTERLADEN ---" -ForegroundColor Yellow
if (-not $Force -and (Test-PhaseDone "modelle")) {
    Write-Host "Bereits erfolgreich abgeschlossen -- wird uebersprungen (kein erneuter Download)."
} else {
    Push-Location $ScriptDir
    try {
        & $VenvPython -m protokoll_assistent.modelle_herunterladen
        $phase3ExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($phase3ExitCode -ne 0) {
        Write-Host "`nPhase 3 ist fehlgeschlagen. Bitte die oben genannten Fehler beheben und" -ForegroundColor Red
        Write-Host "'Einrichtung-Lokal.ps1' erneut ausfuehren (bereits geladene Modelle werden"
        Write-Host "dabei nicht erneut heruntergeladen)."
        exit 1
    }
}

# --- Phase 4: Offline-Pruefung --------------------------------------------
Write-Host "`n--- PHASE 4: OFFLINE-FUNKTIONSPRUEFUNG ---" -ForegroundColor Yellow
Push-Location $ScriptDir
try {
    & $VenvPython -m protokoll_assistent.systempruefung --offline-check
    $phase4ExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($phase4ExitCode -ne 0) {
    Write-Host "`nPhase 4 ist fehlgeschlagen. Die Anwendung wird noch NICHT freigegeben." -ForegroundColor Red
    Write-Host "Bitte die oben genannten Punkte beheben und 'Einrichtung-Lokal.ps1' erneut ausfuehren."
    exit 1
}

# --- Phase 5: Abschluss ----------------------------------------------------
Write-Host "`n--- PHASE 5: ABSCHLUSS ---" -ForegroundColor Yellow
Set-PhaseDone "abschluss"

Write-Host "`n=======================================================================" -ForegroundColor Green
Write-Host " EINRICHTUNG VOLLSTAENDIG ABGESCHLOSSEN" -ForegroundColor Green
Write-Host "=======================================================================" -ForegroundColor Green
Write-Host "Sie koennen die Anwendung jetzt starten mit:"
Write-Host "  .\Anwendung-starten.ps1"
