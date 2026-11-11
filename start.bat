@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" monitor.py
) else (
    python monitor.py
)
pause
