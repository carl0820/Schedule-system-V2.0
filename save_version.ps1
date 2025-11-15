# 快速保存版本并推送到 GitHub
# 使用方法: .\save_version.ps1 "提交信息"

param(
    [Parameter(Mandatory=$true)]
    [string]$Message
)

Write-Host "正在保存版本..." -ForegroundColor Green

# 添加所有更改
git add -A

# 检查是否有更改
$status = git status --porcelain
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "没有需要提交的更改" -ForegroundColor Yellow
    exit 0
}

# 提交更改
Write-Host "提交更改: $Message" -ForegroundColor Cyan
git commit -m $Message

if ($LASTEXITCODE -ne 0) {
    Write-Host "提交失败！" -ForegroundColor Red
    exit 1
}

# 推送到 GitHub
Write-Host "推送到 GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 版本已成功保存并推送到 GitHub！" -ForegroundColor Green
} else {
    Write-Host "✗ 推送失败！" -ForegroundColor Red
    exit 1
}

