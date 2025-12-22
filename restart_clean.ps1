# 清理并重启服务脚本

Write-Host "停止服务..." -ForegroundColor Yellow
$processes = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "chatbot" -or $_.Path -match "chatbot" }
if ($processes) {
    $processes | Stop-Process -Force
    Write-Host "已停止 $($processes.Count) 个进程" -ForegroundColor Green
}

Write-Host "`n清理Python缓存..." -ForegroundColor Yellow
Get-ChildItem -Path "d:\chatbot" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path "d:\chatbot" -Recurse -Filter "*.pyc" | Remove-Item -Force
Write-Host "缓存清理完成" -ForegroundColor Green

Write-Host "`n等待3秒..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

Write-Host "`n启动服务..." -ForegroundColor Yellow
Write-Host "请在新终端运行: python main.py" -ForegroundColor Cyan
Write-Host "`n或者在此终端运行:" -ForegroundColor Cyan
Write-Host "cd d:\chatbot" -ForegroundColor White
Write-Host "python main.py" -ForegroundColor White
