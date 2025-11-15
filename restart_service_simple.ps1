# 简单重启服务脚本
# 快速停止并重启服务

Write-Host "正在重启服务..." -ForegroundColor Cyan

# 停止运行在端口 8000 的进程
$procs = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($procs) {
    Stop-Process -Id $procs -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "已停止旧服务" -ForegroundColor Green
}

# 启动新服务
Write-Host "正在启动新服务..." -ForegroundColor Yellow

# 使用虚拟环境中的 Python（如果存在）
$pythonPath = if (Test-Path "venv\bin\python.exe") { "venv\bin\python.exe" } elseif (Test-Path "venv\Scripts\python.exe") { "venv\Scripts\python.exe" } else { "python" }
Start-Process $pythonPath -ArgumentList "main.py"

Start-Sleep -Seconds 2
Write-Host "服务已启动！" -ForegroundColor Green
Write-Host "访问地址: http://localhost:8000/docs" -ForegroundColor Cyan

