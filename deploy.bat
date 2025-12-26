@echo off
chcp 65001 >nul
cls

echo ============================================================
echo Robot Scheduler - One-Click Deployment
echo ============================================================
echo.

powershell.exe -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Deployment failed. Please check the error message above.
    echo.
    pause
)
