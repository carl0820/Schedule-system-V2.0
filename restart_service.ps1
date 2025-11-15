# 重启服务脚本
# 用于在 Windows PowerShell 中重启 FastAPI 服务

param(
    [string]$Port = "8000"
)

# 创建分隔线
$separator = -join (1..80 | ForEach-Object { '=' })
Write-Host $separator
Write-Host "重启机器人调度系统服务" -ForegroundColor Cyan
Write-Host $separator
Write-Host ""

# 1. 查找并停止运行在指定端口的进程
Write-Host "[1/3] 查找运行在端口 $Port 的进程..." -ForegroundColor Yellow
$processes = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($processes) {
    Write-Host "找到进程: $($processes -join ', ')" -ForegroundColor Green
    foreach ($processId in $processes) {
        try {
            $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($null -ne $proc) {
                Write-Host "  停止进程 PID: $processId ($($proc.ProcessName))" -ForegroundColor Yellow
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
            }
        } catch {
            Write-Host "  无法停止进程 PID: $processId - $_" -ForegroundColor Red
        }
    }
    Write-Host "已停止所有相关进程" -ForegroundColor Green
} else {
    Write-Host "未找到运行在端口 $Port 的进程" -ForegroundColor Yellow
}

Write-Host ""

# 2. 等待端口释放
Write-Host "[2/3] 等待端口 $Port 释放..." -ForegroundColor Yellow
$maxWait = 10
$waited = 0
while ($waited -lt $maxWait) {
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connection) {
        Write-Host "端口 $Port 已释放" -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds 1
    $waited++
    Write-Host "  等待中... ($waited/$maxWait 秒)" -ForegroundColor Gray
}

Write-Host ""

# 3. 启动服务
Write-Host "[3/3] 启动服务..." -ForegroundColor Yellow
Write-Host "正在启动 FastAPI 服务..." -ForegroundColor Cyan

# 检查虚拟环境并确定 Python 路径
$pythonPath = "python"
$venvScripts = ".\venv\Scripts\python.exe"
$venvBin = ".\venv\bin\python.exe"

if (Test-Path $venvScripts) {
    $pythonPath = $venvScripts
    Write-Host "检测到虚拟环境 (Scripts)，使用: $pythonPath" -ForegroundColor Green
} elseif (Test-Path $venvBin) {
    $pythonPath = $venvBin
    Write-Host "检测到虚拟环境 (bin)，使用: $pythonPath" -ForegroundColor Green
} else {
    Write-Host "未找到虚拟环境，使用系统 Python" -ForegroundColor Yellow
}

# 启动服务（后台运行）
$process = Start-Process $pythonPath -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", $Port, "--reload" -PassThru -NoNewWindow

if ($null -ne $process) {
    Write-Host "服务已启动，PID: $($process.Id)" -ForegroundColor Green
    Write-Host ""
    Write-Host "服务地址: http://localhost:$Port" -ForegroundColor Cyan
    Write-Host "API 文档: http://localhost:$Port/docs" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "按 Ctrl+C 停止服务" -ForegroundColor Yellow
    Write-Host ""
    
    # 等待几秒检查服务是否正常启动
    Start-Sleep -Seconds 3
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "[OK] 服务健康检查通过" -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARN] 服务可能还在启动中，请稍后检查" -ForegroundColor Yellow
    }
} else {
    Write-Host "[FAIL] 启动服务失败" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host $separator
Write-Host "服务重启完成！" -ForegroundColor Green
Write-Host $separator
