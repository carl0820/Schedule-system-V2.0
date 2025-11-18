# PowerShell Dependency Installation Script - Disable Proxy
# Usage: .\install_deps_simple.ps1

# Set output encoding to UTF-8 to avoid encoding issues
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Dependency Installation Script (Disable Proxy)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Disable proxy
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:NO_PROXY = "*"

Write-Host "`nProxy settings disabled" -ForegroundColor Green

# Mirror source
$mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

Write-Host "`nUsing mirror: $mirror" -ForegroundColor Yellow

# Install dependencies
Write-Host "`nStarting dependency installation..." -ForegroundColor Yellow

pip install -r requirements.txt -i $mirror --trusted-host pypi.tuna.tsinghua.edu.cn

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host "[SUCCESS] Dependencies installed successfully!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "`nYou can run test: python quick_test.py" -ForegroundColor Cyan
} else {
    Write-Host "`n============================================================" -ForegroundColor Red
    Write-Host "[ERROR] Dependency installation failed" -ForegroundColor Red
    Write-Host "Please check network connection or try other mirror sources" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "`nYou can try:" -ForegroundColor Yellow
    Write-Host "1. Use other mirror: pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/" -ForegroundColor Yellow
    Write-Host "2. Use Python script: python install_deps.py" -ForegroundColor Yellow
    Write-Host "3. Check detailed guide: INSTALL.md" -ForegroundColor Yellow
}

