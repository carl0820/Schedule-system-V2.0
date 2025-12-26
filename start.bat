@echo off
REM Windows批处理启动脚本
REM 双击此文件即可启动服务

echo ============================================================
echo             多机器人调度系统启动
echo ============================================================
echo.

REM 调用PowerShell脚本
powershell.exe -ExecutionPolicy Bypass -File "%~dp0start.ps1"

REM 如果脚本执行失败，保持窗口打开
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] 启动失败，请查看上面的错误信息
    echo.
    pause
)
