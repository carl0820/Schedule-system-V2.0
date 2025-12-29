# Service Startup Script
# Uses correct Python version (Python 3.13) to start the service
# Fixed encoding to avoid display issues

$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

if (Test-Path $pythonPath) {
    Write-Host "Starting service with Python 3.13..." -ForegroundColor Green
    Set-Location $PSScriptRoot
    & $pythonPath main.py
} else {
    Write-Host "ERROR: Python 3.13 not found" -ForegroundColor Red
    Write-Host "Please check Python installation path: $pythonPath" -ForegroundColor Yellow
    exit 1
}
