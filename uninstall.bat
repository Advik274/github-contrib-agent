@echo off
title GitHub Contribution Agent — Uninstall
color 0C

echo.
echo  ==========================================
echo   Uninstall GitHub Contribution Agent
echo  ==========================================
echo.

:: Remove from Windows startup
echo  [..] Removing from Windows startup...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GitHubContributionAgent" /f >nul 2>&1

if errorlevel 1 (
    echo  [INFO] Not in startup (or already removed)
) else (
    echo  [OK] Removed from Windows startup!
)

:: Ask about data removal
echo.
echo  ==========================================
echo   Clean Up Data
echo  ==========================================
echo.
echo  Do you want to remove all data files?
echo   - Config files
echo   - Logs
echo   - Processed history
echo.
echo   [Y] Yes - Delete all data
echo   [N] No  - Keep data (for reinstallation)
echo.

choice /c YN /n /m "Select option (Y/N): "
set CLEAN_DATA=%errorlevel%

if %CLEAN_DATA%==1 (
    echo.
    echo  [..] Removing data files...
    
    if exist "config" (
        rmdir /s /q "config" 2>nul
        echo  [OK] Removed config folder
    )
    
    if exist "logs" (
        rmdir /s /q "logs" 2>nul
        echo  [OK] Removed logs folder
    )
    
    if exist "data" (
        rmdir /s /q "data" 2>nul
        echo  [OK] Removed data folder
    )
    
    echo  [OK] All data cleaned!
)

:: Ask about removing exe folder
echo.
echo  ==========================================
echo   Remove Executable
echo  ==========================================
echo.
echo  Do you want to delete the built exe folder?
echo   (dist\github_agent)
echo.
echo   [Y] Yes - Delete exe folder
echo   [N] No  - Keep exe folder
echo.

choice /c YN /n /m "Select option (Y/N): "
set CLEAN_EXE=%errorlevel%

if %CLEAN_EXE%==1 (
    echo.
    echo  [..] Removing exe folder...
    
    if exist "dist" (
        rmdir /s /q "dist" 2>nul
        echo  [OK] Removed dist folder
    )
    
    echo  [OK] Exe folder cleaned!
)

echo.
echo  ==========================================
echo   Uninstall Complete!
echo  ==========================================
echo.
echo  The agent has been removed from startup.
if %CLEAN_DATA%==2 (
    echo  Config and data files were preserved.
    echo  You can reinstall anytime by running install.bat
) else (
    echo  All data has been deleted.
)
echo.
pause
