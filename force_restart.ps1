# 强制清理并重启服务脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Force Clean & Restart Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 停止所有Python进程
Write-Host "[Step 1/4] Stopping all Python processes..." -ForegroundColor Yellow
Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Write-Host "  [OK] All Python processes stopped" -ForegroundColor Green
Write-Host ""

# 2. 清理Python缓存
Write-Host "[Step 2/4] Cleaning Python cache..." -ForegroundColor Yellow
$pycacheCount = 0
$pycCount = 0

# 删除 __pycache__ 目录
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -Path $_.FullName -Recurse -Force
    $pycacheCount++
}

# 删除 .pyc 文件
Get-ChildItem -Path . -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -Path $_.FullName -Force
    $pycCount++
}

Write-Host "  [OK] Removed $pycacheCount __pycache__ directories and $pycCount .pyc files" -ForegroundColor Green
Write-Host ""

# 3. 验证代码修改
Write-Host "[Step 3/4] Verifying code changes..." -ForegroundColor Yellow
$fixMarker = Select-String -Path "app\services\task_scheduler.py" -Pattern "【修复】每10次循环都输出心跳" -SimpleMatch
if ($fixMarker) {
    Write-Host "  [OK] Code fix marker found at line $($fixMarker.LineNumber)" -ForegroundColor Green
} else {
    Write-Host "  [ERROR] Code fix marker NOT found!" -ForegroundColor Red
    Write-Host "   The file may not have been saved correctly" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 4. 启动服务
Write-Host "[Step 4/4] Starting service..." -ForegroundColor Yellow
Write-Host ""

# 使用与 start_service.ps1 相同的逻辑找到Python
$pythonPath = $null
if (Test-Path "venv\Scripts\python.exe") {
    $pythonPath = "venv\Scripts\python.exe"
    Write-Host "  Using virtual environment: venv\Scripts\python.exe" -ForegroundColor Cyan
} elseif (Test-Path "venv\bin\python.exe") {
    $pythonPath = "venv\bin\python.exe"
    Write-Host "  Using virtual environment: venv\bin\python.exe" -ForegroundColor Cyan
} else {
    $pythonPath = "python"
    Write-Host "  Using system Python" -ForegroundColor Cyan
}

Write-Host "  Command: $pythonPath main.py" -ForegroundColor Gray
Write-Host ""

# 启动服务（前台运行，显示输出）
Write-Host "Starting service (press Ctrl+C to stop)..." -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Gray
Write-Host ""

# 直接运行，不使用 Start-Process，这样可以看到输出
& $pythonPath main.py
