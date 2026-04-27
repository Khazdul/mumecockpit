@echo off
setlocal

:: Detect admin rights.  net session requires an open admin share connection;
:: it exits non-zero for standard users and works without network access.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

:: Elevated -- hand off to the PowerShell installer.
:: %~dp0 resolves to the directory containing this .bat file so both files
:: can live anywhere together without path assumptions.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0install-windows.ps1"

pause
