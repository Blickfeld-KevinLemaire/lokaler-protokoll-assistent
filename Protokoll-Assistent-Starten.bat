@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "protokoll_assistent_gui.py"
) else (
    start "" python "protokoll_assistent_gui.py"
)
