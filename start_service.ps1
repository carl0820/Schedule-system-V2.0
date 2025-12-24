# 启动服务脚本
# 使用正确的Python版本（Python 3.13）启动服务

$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

if (Test-Path $pythonPath) {
    Write-Host "使用 Python 3.13 启动服务..." -ForegroundColor Green
    Set-Location $PSScriptRoot
    & $pythonPath main.py
} else {
    Write-Host "错误: 未找到 Python 3.13" -ForegroundColor Red
    Write-Host "请检查 Python 安装路径: $pythonPath" -ForegroundColor Yellow
    exit 1
}
