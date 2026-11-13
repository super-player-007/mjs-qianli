@echo off
cd /d %~dp0
.venv\Scripts\python.exe run.py gui
if errorlevel 1 (
  echo.
  echo [ERROR] GUI exited with error. Check the message above.
  pause
)
