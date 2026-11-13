@echo off
REM Build the launcher (2026-11-13).
REM Compiles tools\launcher\launcher.cs into "启动控制台.exe" using the
REM .NET Framework compiler shipped with Windows (no Visual Studio needed).
REM NOTE: this is only a "no console window" launcher -- the app itself
REM still runs from source (.venv + run.py), nothing is packaged.
setlocal
cd /d "%~dp0.."

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] csc.exe not found: .NET Framework 4.x is required.
    exit /b 1
)

"%CSC%" /nologo /target:winexe /optimize+ /codepage:65001 ^
    /r:System.Windows.Forms.dll ^
    /out:"启动控制台.exe" ^
    "tools\launcher\启动控制台.cs"
if errorlevel 1 (
    echo [ERROR] compile failed
    exit /b 1
)
echo OK: 启动控制台.exe
