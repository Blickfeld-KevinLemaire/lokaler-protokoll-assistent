@echo off
setlocal enabledelayedexpansion

set "REPO_URL=https://github.com/kevinweisbrod/lokaler-protokoll-assistent.git"
set "REPO_BRANCH=claude/dreamy-carson-ybtbg4"
set "MERKDATEI=%~dp0.protokoll_assistent_ordner.txt"

echo ============================================================
echo  Protokoll-Assistent - Einrichtung
echo ============================================================
echo.

if exist "%~dp0setup_fenster.py" (
    echo Projektordner bereits vorhanden, Einrichtung wird fortgesetzt ...
    set "ZIELORDNER=%~dp0"
    goto :check_python
)

rem Zielordner festlegen: Kommandozeilenargument, sonst zuletzt verwendeter
rem Ordner, sonst Vorschlag im Benutzerprofil. Jeder Anwender kann hier
rem seinen eigenen Ordner waehlen.
set "STANDARDORDNER=%USERPROFILE%\Protokoll-Assistent"
if exist "%MERKDATEI%" (
    set /p STANDARDORDNER=<"%MERKDATEI%"
)

if not "%~1"=="" (
    set "ZIELORDNER=%~1"
) else (
    echo In welchen Ordner soll das Projekt heruntergeladen werden?
    set /p "ZIELORDNER=Projektordner [!STANDARDORDNER!]: "
    if "!ZIELORDNER!"=="" set "ZIELORDNER=!STANDARDORDNER!"
)

echo !ZIELORDNER!>"%MERKDATEI%"

where git >nul 2>nul
if errorlevel 1 (
    echo Git wurde nicht gefunden. Es wird die Download-Seite fuer Git geoeffnet.
    start "" "https://git-scm.com/download/win"
    echo Bitte Git installieren und dieses Skript danach erneut starten.
    pause
    exit /b 1
)

if exist "%ZIELORDNER%" (
    echo Projektordner existiert bereits: %ZIELORDNER%
    echo Aktualisiere per "git pull" ...
    git -C "%ZIELORDNER%" pull
) else (
    echo Lade Projekt nach %ZIELORDNER% ...
    git clone -b "%REPO_BRANCH%" "%REPO_URL%" "%ZIELORDNER%"
)

if errorlevel 1 (
    echo.
    echo FEHLER beim Herunterladen des Projekts. Falls sich ein Anmeldefenster
    echo geoeffnet hat, bitte dort bei GitHub anmelden und danach erneut starten.
    pause
    exit /b 1
)

:check_python
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    goto :run_setup
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :run_setup
)

echo Python wurde nicht gefunden. Es wird die Download-Seite geoeffnet.
start "" "https://www.python.org/downloads/"
echo Bitte Python installieren ^(Haken bei "Add Python to PATH" setzen^)
echo und dieses Skript danach erneut starten.
pause
exit /b 1

:run_setup
cd /d "%ZIELORDNER%"
%PYTHON_CMD% setup_fenster.py
exit /b 0
