# 启动脚本 - 自动检测并使用正确的Python
# 适用于任何Windows电脑

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "多机器人调度系统启动脚本" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 函数：检测Python是否有pip
function Test-PythonWithPip {
    param([string]$pythonExe)

    try {
        $result = & $pythonExe -m pip --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

# 函数：获取Python版本
function Get-PythonVersion {
    param([string]$pythonExe)

    try {
        $version = & $pythonExe --version 2>&1
        return $version
    } catch {
        return "Unknown"
    }
}

# 查找所有Python安装
Write-Host "[INFO] 正在检测Python环境..." -ForegroundColor Yellow
$pythonPath = $null

# 方法1：尝试使用PATH中的python
Write-Host "[CHECK] 检查默认python命令..." -ForegroundColor Gray
$defaultPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($defaultPython -and (Test-PythonWithPip $defaultPython)) {
    $pythonPath = $defaultPython
    Write-Host "[OK] 找到可用的Python: $pythonPath" -ForegroundColor Green
}

# 方法2：如果默认python不可用，搜索所有Python安装
if (-not $pythonPath) {
    Write-Host "[CHECK] 默认python不可用，搜索其他Python安装..." -ForegroundColor Gray

    # 获取所有可能的Python路径
    $possiblePaths = @()

    # 查找where python的所有结果
    try {
        $wherePython = where.exe python 2>$null
        if ($wherePython) {
            $possiblePaths += $wherePython
        }
    } catch {}

    # 查找常见安装位置
    $commonPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python38\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Python39\python.exe",
        "C:\Python38\python.exe"
    )

    $possiblePaths += $commonPaths

    # 测试每个路径
    foreach ($path in $possiblePaths) {
        if ($path -and (Test-Path $path) -and (Test-PythonWithPip $path)) {
            # 排除MSYS2、Cygwin等不适合的Python
            if ($path -notmatch "msys|cygwin|mingw") {
                $pythonPath = $path
                Write-Host "[OK] 找到可用的Python: $pythonPath" -ForegroundColor Green
                break
            } else {
                Write-Host "[SKIP] 跳过 $path (MSYS2/Cygwin Python)" -ForegroundColor Gray
            }
        }
    }
}

# 如果还是找不到，报错
if (-not $pythonPath) {
    Write-Host ""
    Write-Host "[ERROR] 未找到可用的Python环境！" -ForegroundColor Red
    Write-Host ""
    Write-Host "请确保：" -ForegroundColor Yellow
    Write-Host "1. 已安装Python 3.8-3.13（推荐3.11或3.12）" -ForegroundColor White
    Write-Host "2. Python安装时勾选了 'Add Python to PATH'" -ForegroundColor White
    Write-Host "3. Python包含pip模块" -ForegroundColor White
    Write-Host ""
    Write-Host "Python下载地址：" -ForegroundColor Cyan
    Write-Host "https://www.python.org/downloads/" -ForegroundColor White
    Write-Host ""
    Write-Host "或手动指定Python路径：" -ForegroundColor Cyan
    Write-Host ".\start.ps1 -PythonPath 'C:\Path\To\python.exe'" -ForegroundColor White
    Write-Host ""
    exit 1
}

# 显示Python信息
$pythonVersion = Get-PythonVersion $pythonPath
Write-Host ""
Write-Host "Python信息：" -ForegroundColor Cyan
Write-Host "  路径: $pythonPath" -ForegroundColor White
Write-Host "  版本: $pythonVersion" -ForegroundColor White
Write-Host ""

# 检查依赖是否安装
Write-Host "[INFO] 检查依赖安装状态..." -ForegroundColor Yellow
$corePackages = @("fastapi", "uvicorn", "httpx", "pydantic")
$missingPackages = @()

foreach ($package in $corePackages) {
    $result = & $pythonPath -c "import $package" 2>&1
    if ($LASTEXITCODE -ne 0) {
        $missingPackages += $package
    }
}

if ($missingPackages.Count -gt 0) {
    Write-Host ""
    Write-Host "[WARN] 检测到缺失的依赖包：" -ForegroundColor Yellow
    foreach ($pkg in $missingPackages) {
        Write-Host "  - $pkg" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "请先安装依赖：" -ForegroundColor Cyan
    Write-Host "  python install_deps.py" -ForegroundColor White
    Write-Host "或" -ForegroundColor Cyan
    Write-Host "  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
    Write-Host ""

    $continue = Read-Host "是否继续启动？(y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 1
    }
}

# 启动服务
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[INFO] 正在启动服务..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "服务启动后可访问：" -ForegroundColor Cyan
Write-Host "  主页面:     http://localhost:8092" -ForegroundColor Yellow
Write-Host "  机器人管理: http://localhost:8092/static/robot_list.html" -ForegroundColor Yellow
Write-Host "  任务管理:   http://localhost:8092/static/task_list.html" -ForegroundColor Yellow
Write-Host "  地图管理:   http://localhost:8092/static/map_management.html" -ForegroundColor Yellow
Write-Host "  API文档:    http://localhost:8092/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "按 Ctrl+C 停止服务" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 启动服务
& $pythonPath main.py
