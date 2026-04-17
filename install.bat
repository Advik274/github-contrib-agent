@echo off
title GitHub Contribution Agent — Installer
color 0A

echo.
echo  ==========================================
echo   GitHub Contribution Agent — Setup
echo  ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% found

:: Create venv
if not exist ".venv" (
    echo  [..] Creating virtual environment...
    python -m venv .venv
    echo  [OK] Virtual environment created
) else (
    echo  [OK] Virtual environment already exists
)

:: Activate and install
echo  [..] Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet --upgrade
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

:: Ask about Windows startup
echo.
echo  ==========================================
echo   Auto-Start on Windows Boot
echo  ==========================================
echo.
echo  Do you want the agent to start automatically
echo  when Windows boots?
echo.
echo   [Y] Yes - Start with Windows
echo   [N] No  - Manual start only
echo.

choice /c YN /n /m "Select option (Y/N): "
set AUTO_START=%errorlevel%

:: Build standalone exe
echo.
echo  ==========================================
echo   Building Standalone Executable
echo  ==========================================
echo.

:: Install pyinstaller
pip install pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo  [ERROR] Failed to install PyInstaller
    pause
    exit /b 1
)
echo  [OK] PyInstaller installed

:: Create directories for build
if not exist "build" mkdir build
if not exist "dist"  mkdir dist

:: Build the exe
echo  [..] Building standalone executable...
echo      This may take a few minutes...
pyinstaller build.spec --clean >nul 2>&1

if errorlevel 1 (
    echo  [ERROR] Build failed!
    echo      Falling back to Python-based installation.
    echo      Run 'python main.py' to start the agent.
    goto :finish
)

:: Copy VERSION file
if exist "VERSION" (
    copy "VERSION" "dist\github_agent\VERSION" >nul 2>&1
)

:: Create README for exe folder
echo GitHub Contribution Agent > "dist\github_agent\README.txt"
echo ========================== >> "dist\github_agent\README.txt"
echo. >> "dist\github_agent\README.txt"
echo First run: The agent will launch the setup wizard. >> "dist\github_agent\README.txt"
echo Config, logs, and data are stored in this folder. >> "dist\github_agent\README.txt"
echo. >> "dist\github_agent\README.txt"
echo Right-click tray icon for options. >> "dist\github_agent\README.txt"

echo  [OK] Standalone exe built successfully!

:: Add to Windows startup if selected
if %AUTO_START%==1 (
    echo.
    echo  [..] Adding to Windows startup...
    
    :: Get absolute path to the exe
    set EXE_PATH=%~dp0dist\github_agent\github_agent.exe
    set EXE_PATH=%EXE_PATH:\=\\%
    
    :: Add registry entry
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GitHubContributionAgent" /t REG_SZ /d "\"%EXE_PATH%\"" /f >nul 2>&1
    
    if errorlevel 1 (
        echo  [WARNING] Could not add to startup. You can add manually:
        echo           Press Win+R, type 'shell:startup'
        echo           Create shortcut to dist\github_agent\github_agent.exe
    ) else (
        echo  [OK] Added to Windows startup!
    )
)

:finish
echo.
echo  ==========================================
echo   Installation Complete!
echo  ==========================================
echo.
if %AUTO_START%==1 (
    echo  [OK] Agent will auto-start on Windows boot
) else (
    echo  [INFO] Agent not set to auto-start
)
echo.
echo  Standalone exe: dist\github_agent\github_agent.exe
echo  Run this exe to start the agent.
echo.
echo  You can also run 'start_agent.bat' to launch
echo  the Python version directly.
echo.
pause
