@echo off
title GitHub Contribution Agent — Builder
color 0A

echo.
echo  ==========================================
echo   Building Standalone Executable
echo  ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

:: Create venv if needed
if not exist ".venv" (
    echo  [..] Creating virtual environment...
    python -m venv .venv
    echo  [OK] Virtual environment created
)

:: Install dependencies
echo  [..] Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet --upgrade
pip install pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo  [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo  [OK] Dependencies installed

:: Create directories
if not exist "config" mkdir config
if not exist "logs"  mkdir logs
if not exist "data"  mkdir data
if not exist "build" mkdir build
if not exist "dist"  mkdir dist

:: Build the exe
echo.
echo  [..] Building standalone executable...
echo      This may take a few minutes...
echo.

pyinstaller build.spec --clean

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed!
    pause
    exit /b 1
)

:: Copy VERSION file to dist
if exist "VERSION" (
    copy "VERSION" "dist\github_agent\VERSION" >nul 2>&1
)

:: Create a simple README for the exe folder
echo GitHub Contribution Agent > "dist\github_agent\README.txt"
echo ========================== >> "dist\github_agent\README.txt"
echo. >> "dist\github_agent\README.txt"
echo First run: The agent will launch the setup wizard. >> "dist\github_agent\README.txt"
echo Config, logs, and data are stored in this folder. >> "dist\github_agent\README.txt"
echo. >> "dist\github_agent\README.txt"
echo Right-click tray icon for options. >> "dist\github_agent\README.txt"

echo.
echo  ==========================================
echo   Build Complete!
echo  ==========================================
echo.
echo  Your standalone exe is in:
echo   dist\github_agent\github_agent.exe
echo.
echo  Copy the entire 'github_agent' folder to any location.
echo  Run github_agent.exe to start the agent.
echo.
pause
