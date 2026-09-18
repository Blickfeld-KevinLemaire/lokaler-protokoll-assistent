@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "hauptanwendung.py"
) else (
    start "" python "hauptanwendung.py"
)
