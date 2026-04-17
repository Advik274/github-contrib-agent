@echo off
:: GitHub Contribution Agent - Windows Startup Script
:: Place this file's shortcut in:
:: C:\Users\%USERNAME%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup

set AGENT_DIR=%~dp0
cd /d "%AGENT_DIR%"

:: Start agent silently in background (no console window)
start "" /B pythonw main.py

echo GitHub Agent started in background.
