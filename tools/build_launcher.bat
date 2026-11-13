@echo off
REM Build the no-console launcher (2026-11-13).
REM Thin wrapper: real work is tools\build_launcher.py, because csc.exe cannot
REM take a Chinese /out path under the GBK console code page (CS2021 "file name
REM too long or invalid"); Python handles Unicode paths correctly.
REM NOTE: this is only a "no console window" launcher -- the app itself still
REM runs from source (.venv + run.py), nothing is packaged.
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. See deployment doc.
    exit /b 1
)
".venv\Scripts\python.exe" "tools\build_launcher.py" %*
