@echo off
REM Windows一键部署批处理脚本
REM 双击此文件即可完成自动部署

echo ============================================================
echo         多机器人调度系统 - 一键部署
echo ============================================================
echo.

REM 调用PowerShell部署脚本
powershell.exe -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"

REM 如果脚本执行失败，保持窗口打开
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] 部署失败，请查看上面的错误信息
    echo.
    pause
)
