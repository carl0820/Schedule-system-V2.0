# PowerShell依赖安装脚本 - 禁用代理
# 使用方法: .\install_deps_simple.ps1

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "依赖安装脚本 (禁用代理)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 禁用代理
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:NO_PROXY = "*"

Write-Host "`n已禁用代理设置" -ForegroundColor Green

# 镜像源
$mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

Write-Host "`n使用镜像源: $mirror" -ForegroundColor Yellow

# 安装依赖
Write-Host "`n开始安装依赖..." -ForegroundColor Yellow

pip install -r requirements.txt -i $mirror --trusted-host pypi.tuna.tsinghua.edu.cn --no-proxy

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host "[SUCCESS] 依赖安装完成！" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "`n可以运行测试: python quick_test.py" -ForegroundColor Cyan
} else {
    Write-Host "`n============================================================" -ForegroundColor Red
    Write-Host "[ERROR] 依赖安装失败，请检查网络连接或尝试其他镜像源" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "`n可以尝试:" -ForegroundColor Yellow
    Write-Host "1. 使用其他镜像源: pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/" -ForegroundColor Yellow
    Write-Host "2. 使用Python脚本: python install_deps.py" -ForegroundColor Yellow
    Write-Host "3. 查看详细说明: INSTALL.md" -ForegroundColor Yellow
}

