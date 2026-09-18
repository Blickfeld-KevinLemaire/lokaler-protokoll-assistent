# Start-Protokoll-Assistent.ps1
#
# Einfachster Startweg auf JEDEM Windows-PC (nicht nur auf dem urspruenglichen
# Referenzrechner): sucht ein vorhandenes Python 3.10/3.11 und startet
# 'app.py'. Die Anwendung selbst kuemmert sich beim ersten Start automatisch
# um alles Weitere:
#   - legt bei Bedarf eine eigene, private Python-Umgebung an
#     ('runtime\venv') und installiert dort PyTorch (passend zu GPU/CPU),
#     WhisperX, pyannote.audio, PySide6 usw.,
#   - laedt fehlendes FFmpeg/Ollama bei Bedarf automatisch herunter,
#   - laedt die benoetigten KI-Modelle herunter,
#   - fuehrt einen Systemtest durch,
#   - laesst Sie anschliessend Ihren Eingabeordner waehlen.
#
# Ist bereits eine '.venv-whisperx' vorbereitet (Referenzrechner), wird
# diese automatisch erkannt und direkt verwendet -- kein erneuter Download.
#
# Einzige Voraussetzung: Python 3.10 oder 3.11 muss auf diesem PC bereits
# installiert sein (https://www.python.org/downloads/ -- Haken bei "Add
# python.exe to PATH" beim Installieren setzen).

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    foreach ($candidate in @("py -3.11", "py -3.10", "python3.11", "python3.10", "python")) {
        $parts = $candidate.Split(" ")
        $exe = $parts[0]
        $exeArgs = $parts[1..($parts.Length - 1)]
        $found = Get-Command $exe -ErrorAction SilentlyContinue
        if ($found) {
            try {
                $versionOutput = & $exe @exeArgs --version 2>&1
                if ($versionOutput -match "Python 3\.(10|11)") {
                    return , ($exe, $exeArgs)
                }
            } catch {
                continue
            }
        }
    }
    return $null
}

Write-Host "=== Protokoll-Assistent Lokal ===" -ForegroundColor Cyan

$pythonMatch = Find-Python
if (-not $pythonMatch) {
    Write-Host "FEHLER: Es wurde kein Python 3.10 oder 3.11 gefunden." -ForegroundColor Red
    Write-Host "Bitte von https://www.python.org/downloads/ installieren"
    Write-Host "(beim Installieren 'Add python.exe to PATH' aktivieren) und erneut starten."
    exit 1
}
$pythonExe, $pythonArgs = $pythonMatch
Write-Host "Verwende Python: $pythonExe $($pythonArgs -join ' ')"

Push-Location $ScriptDir
try {
    & $pythonExe @pythonArgs (Join-Path $ScriptDir "app.py")
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
