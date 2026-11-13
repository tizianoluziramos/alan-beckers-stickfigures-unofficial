@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero instala el modo Desktop AI siguiendo desktop_ai\README.md
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m desktop_ai
if errorlevel 1 pause
