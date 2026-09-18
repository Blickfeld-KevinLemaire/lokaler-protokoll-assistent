# Anwendung-starten.ps1
# Startsperre: prueft, ob 'Einrichtung-Lokal.ps1' vollstaendig erfolgreich
# war, BEVOR die Anwendung gestartet wird. Ist die Einrichtung
# unvollstaendig, wird die Anwendung NICHT gestartet; stattdessen werden
# die fehlenden Komponenten genannt und angeboten, die Einrichtung
# fortzusetzen.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir "_env_helper.ps1")
$VenvPython = Get-ActiveVenvPython -ScriptDir $ScriptDir
$StatusFile = Join-Path $ScriptDir "Einrichtungsstatus.json"

Write-Host "=== Protokoll-Assistent Lokal ===" -ForegroundColor Cyan

function Start-Setup {
    & (Join-Path $ScriptDir "Einrichtung-Lokal.ps1")
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Es wurde noch keine Python-Umgebung gefunden." -ForegroundColor Red
    $answer = Read-Host "Soll die vollstaendige Einrichtung jetzt gestartet werden? [j/N]"
    if ($answer -match '^[jJ]') { Start-Setup }
    exit 1
}

if (-not (Test-Path $StatusFile)) {
    Write-Host "Die Einrichtung wurde noch nicht durchgefuehrt ('Einrichtungsstatus.json' fehlt)." -ForegroundColor Red
    $answer = Read-Host "Soll die Einrichtung jetzt gestartet werden? [j/N]"
    if ($answer -match '^[jJ]') { Start-Setup }
    exit 1
}

Push-Location $ScriptDir
try {
    $missingRaw = & $VenvPython -c "from utils.setup_status import load_status, missing_phases; print(','.join(missing_phases(load_status())))"
} finally {
    Pop-Location
}

if ($missingRaw -and $missingRaw.Trim().Length -gt 0) {
    Write-Host "Die Einrichtung ist UNVOLLSTAENDIG. Fehlende Phasen:" -ForegroundColor Red
    foreach ($phase in $missingRaw.Split(",")) {
        Write-Host "  - $phase"
    }
    $answer = Read-Host "`nSoll die Einrichtung jetzt fortgesetzt werden? [j/N]"
    if ($answer -match '^[jJ]') {
        Start-Setup
    } else {
        Write-Host "Start abgebrochen: Die Anwendung wird erst nach vollstaendiger Einrichtung freigegeben."
    }
    exit 1
}

Write-Host "Einrichtung vollstaendig -- Anwendung wird gestartet." -ForegroundColor Green

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

Push-Location $ScriptDir
try {
    $ollamaOk = & $VenvPython -c "from services import ollama_service as o; print('1' if o.is_service_running() else '0')"
} finally {
    Pop-Location
}
if ($ollamaOk -ne "1") {
    Write-Host "HINWEIS: Der Ollama-Dienst scheint nicht erreichbar zu sein." -ForegroundColor DarkYellow
    Write-Host "Die Transkription funktioniert weiterhin lokal; die automatische"
    Write-Host "Protokollerstellung wird aber fehlschlagen, bis Ollama laeuft."
}

& (Join-Path $ScriptDir "start_lokal.ps1")
exit $LASTEXITCODE
