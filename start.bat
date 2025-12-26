@echo off
chcp 65001 >nul
cls

echo ============================================================
echo Robot Scheduler - Start Service
echo ============================================================
echo.

powershell.exe -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start. Please check the error message above.
    echo.
    pause
)
