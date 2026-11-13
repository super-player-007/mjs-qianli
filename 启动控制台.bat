@echo off
REM Start the control console (batch entry).
REM 2026-11-13: no more console window -- this script makes sure the small
REM launcher "启动控制台.exe" exists (built from tools\launcher\启动控制台.cs),
REM then starts it. The launcher runs the GUI with pythonw, so NO black window.
REM The .exe is a local build artifact (gitignored); after the first run you can
REM double-click 启动控制台.exe directly.
REM For debugging with visible output use:  .venv\Scripts\python.exe run.py gui
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] .venv not found. See 部署文档.md
    pause
    exit /b 1
)

if not exist "启动控制台.exe" (
    echo First run: building launcher ...
    call tools\build_launcher.bat
)

if not exist "启动控制台.exe" (
    echo [ERROR] launcher build failed; falling back to console mode.
    ".venv\Scripts\python.exe" run.py gui
    pause
    exit /b 1
)

start "" "启动控制台.exe"
exit /b 0
