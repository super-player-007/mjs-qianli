@echo off
REM Start the control console (2026-11-13).
REM A .bat always gets a console window, so this file only flashes briefly and
REM then hands over to a tiny WinExe launcher (deliverable: launcher exe built
REM next to this script) which runs the GUI with pythonw -- no console window.
REM First run: the launcher exe is built automatically by tools\launch_gui.py
REM (needs .NET Framework 4.x, ships with Windows; source: tools\launcher).
REM After the first run you can double-click the launcher exe directly.
REM Debug with visible output:  .venv\Scripts\python.exe run.py gui
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] .venv not found. See deployment doc.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "tools\launch_gui.py"
exit /b 0
