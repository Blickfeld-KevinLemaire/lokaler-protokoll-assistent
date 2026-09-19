# python-laufzeit-holen.ps1
#
# Laedt die Python-Laufzeitumgebung herunter, die dem Installer beiliegt.
#
# Warum ueberhaupt: Die vollstaendig lokale Anwendung laeuft als Python-Code
# und braucht einen Interpreter. Anwender sollen dafuer aber NICHT selbst
# Python installieren muessen - also liefern wir einen mit.
#
# Verwendet werden die eigenstaendigen Builds von 'python-build-standalone'
# (dieselben, die auch 'uv' benutzt). Sie brauchen keine Installation und
# laufen aus einem beliebigen Ordner.
#
# Version und Pruefsumme sind bewusst fest eingetragen: ein Build soll immer
# dasselbe Ergebnis liefern, und eine Laufzeitumgebung aus dem Netz wird nur
# verwendet, wenn ihre Pruefsumme stimmt.
#
# Aufruf (im Projektstamm):
#     pwsh installer\python-laufzeit-holen.ps1
# Ergebnis:
#     dist-python\python\python.exe   (samt Standardbibliothek)

[CmdletBinding()]
param(
    # Zielordner; der Installer erwartet das Ergebnis unter 'dist-python'.
    [string]$Zielordner = (Join-Path $PSScriptRoot "..\dist-python")
)

$ErrorActionPreference = "Stop"

# --- Fest eingetragene Fassung -------------------------------------------
# Aktualisieren: neue Veroeffentlichung unter
# https://github.com/astral-sh/python-build-standalone/releases suchen,
# Datum und Version hier eintragen und die Pruefsumme aus der Datei
# 'SHA256SUMS' derselben Veroeffentlichung uebernehmen.
$Veroeffentlichung = "20260901"
$PythonVersion     = "3.11.16"
$Dateiname         = "cpython-$PythonVersion+$Veroeffentlichung-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$ErwartetePruefsumme = "06cbe479e039f5b9cb5640c286d790074d63f549f92a32d599a3748293bd4510"
$Quelle = "https://github.com/astral-sh/python-build-standalone/releases/download/$Veroeffentlichung/$Dateiname"

# --- Herunterladen --------------------------------------------------------
$Zielordner = [System.IO.Path]::GetFullPath($Zielordner)
$null = New-Item -ItemType Directory -Force -Path $Zielordner
$archiv = Join-Path $Zielordner $Dateiname

if (Test-Path $archiv) {
    Write-Host "Archiv liegt bereits vor: $archiv"
} else {
    Write-Host "Lade Python $PythonVersion ($Veroeffentlichung) ..."
    # Ohne Fortschrittsanzeige: die ist in der CI nur Rauschen und macht
    # 'Invoke-WebRequest' unter Windows PowerShell spuerbar langsamer.
    $alterFortschritt = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $Quelle -OutFile $archiv -UseBasicParsing
    } finally {
        $ProgressPreference = $alterFortschritt
    }
}

# --- Pruefsumme kontrollieren --------------------------------------------
$tatsaechlich = (Get-FileHash -Path $archiv -Algorithm SHA256).Hash.ToLowerInvariant()
if ($tatsaechlich -ne $ErwartetePruefsumme) {
    Remove-Item $archiv -Force
    throw "Pruefsumme stimmt nicht. Erwartet $ErwartetePruefsumme, erhalten $tatsaechlich. Archiv wurde geloescht."
}
Write-Host "Pruefsumme in Ordnung."

# --- Auspacken ------------------------------------------------------------
$pythonOrdner = Join-Path $Zielordner "python"
if (Test-Path $pythonOrdner) {
    Remove-Item $pythonOrdner -Recurse -Force
}

# 'tar' gehoert seit Windows 10 zum Betriebssystem.
Write-Host "Packe aus nach $pythonOrdner ..."
tar -xzf $archiv -C $Zielordner
if ($LASTEXITCODE -ne 0) {
    throw "Das Archiv konnte nicht ausgepackt werden (tar-Exitcode $LASTEXITCODE)."
}

$exe = Join-Path $pythonOrdner "python.exe"
if (-not (Test-Path $exe)) {
    throw "Im ausgepackten Archiv fehlt python.exe: $exe"
}

$version = & $exe --version 2>&1
Write-Host "Bereit: $exe ($version)"
