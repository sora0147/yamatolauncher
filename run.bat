@echo off
setlocal
cd /d "%~dp0"

where py.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 launcher.py %*
) else (
    python launcher.py %*
)

if ERRORLEVEL 1 pause
