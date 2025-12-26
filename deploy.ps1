# 一键部署脚本 - Windows快速部署
# 自动完成：检测Python → 安装依赖 → 启动服务

param(
    [switch]$SkipDependencies = $false
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "        多机器人调度系统 - 一键部署脚本                    " -ForegroundColor Cyan
Write-Host "        Robot Scheduler - One-Click Deployment             " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 函数：检测Python是否有pip
function Test-PythonWithPip {
    param([string]$pythonExe)
    try {
        $result = & $pythonExe -m pip --version 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# 函数：获取Python版本
function Get-PythonVersion {
    param([string]$pythonExe)
    try {
        $version = & $pythonExe --version 2>&1
        return $version -replace "Python ", ""
    } catch {
        return "Unknown"
    }
}

# 步骤1：检测Python环境
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[步骤 1/3] 检测Python环境" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$pythonPath = $null

# 尝试使用PATH中的python
$defaultPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($defaultPython -and (Test-PythonWithPip $defaultPython)) {
    $pythonPath = $defaultPython
    Write-Host "[OK] 找到可用的Python: $pythonPath" -ForegroundColor Green
}

# 如果默认python不可用，搜索所有可能的Python安装
if (-not $pythonPath) {
    Write-Host "[INFO] 搜索Python安装..." -ForegroundColor Yellow

    $possiblePaths = @()

    # 查找where python的所有结果
    try {
        $wherePython = where.exe python 2>$null
        if ($wherePython) {
            if ($wherePython -is [array]) {
                $possiblePaths += $wherePython
            } else {
                $possiblePaths += @($wherePython)
            }
        }
    } catch {}

    # 查找常见安装位置
    $pythonVersions = @("313", "312", "311", "310", "39", "38")
    foreach ($ver in $pythonVersions) {
        $possiblePaths += "$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe"
        $possiblePaths += "C:\Python$ver\python.exe"
    }

    # 测试每个路径
    foreach ($path in $possiblePaths) {
        if ($path -and (Test-Path $path -ErrorAction SilentlyContinue) -and (Test-PythonWithPip $path)) {
            # 排除MSYS2、Cygwin等
            if ($path -notmatch "msys|cygwin|mingw") {
                $pythonPath = $path
                Write-Host "[OK] 找到可用的Python: $pythonPath" -ForegroundColor Green
                break
            }
        }
    }
}

# 如果找不到Python，提示安装
if (-not $pythonPath) {
    Write-Host ""
    Write-Host "[ERROR] 未找到可用的Python环境！" -ForegroundColor Red
    Write-Host ""
    Write-Host "请执行以下步骤：" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. 下载Python 3.8-3.13（推荐3.11或3.12）" -ForegroundColor White
    Write-Host "   下载地址: https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "2. 安装时务必勾选 'Add Python to PATH'" -ForegroundColor White
    Write-Host ""
    Write-Host "3. 安装完成后重新运行此脚本" -ForegroundColor White
    Write-Host ""
    exit 1
}

$pythonVersion = Get-PythonVersion $pythonPath
Write-Host ""
Write-Host "Python环境信息：" -ForegroundColor Cyan
Write-Host "  路径: $pythonPath" -ForegroundColor White
Write-Host "  版本: $pythonVersion" -ForegroundColor White
Write-Host ""

# 步骤2：安装依赖
if (-not $SkipDependencies) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "[步骤 2/3] 安装依赖包" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    # 禁用代理
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""

    # 升级pip
    Write-Host "[INFO] 升级pip..." -ForegroundColor Yellow
    & $pythonPath -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] pip升级成功" -ForegroundColor Green
    } else {
        Write-Host "[WARN] pip升级失败，使用当前版本" -ForegroundColor Yellow
    }

    # 安装核心依赖
    Write-Host ""
    Write-Host "[INFO] 安装核心依赖（fastapi, uvicorn, httpx, pydantic, requests）..." -ForegroundColor Yellow
    $corePackages = "fastapi>=0.104.1 uvicorn>=0.24.0 httpx>=0.25.2 pydantic>=2.5.0 requests>=2.31.0"

    & $pythonPath -m pip install $corePackages.Split() -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 核心依赖安装成功" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] 核心依赖安装失败" -ForegroundColor Red
        Write-Host ""
        Write-Host "请手动安装：" -ForegroundColor Yellow
        Write-Host "  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
        Write-Host ""
        exit 1
    }

    # 安装其他依赖
    Write-Host ""
    Write-Host "[INFO] 安装其他依赖..." -ForegroundColor Yellow
    & $pythonPath -m pip install -r requirements.txt --only-binary=:all: -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 所有依赖安装成功" -ForegroundColor Green
    } else {
        Write-Host "[WARN] 部分依赖安装失败（可能是可选依赖）" -ForegroundColor Yellow
    }

    Write-Host ""
} else {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "[步骤 2/3] 跳过依赖安装 (-SkipDependencies)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# 验证核心依赖
Write-Host "[INFO] 验证核心依赖..." -ForegroundColor Yellow
$corePackages = @("fastapi", "uvicorn", "httpx", "pydantic")
$allInstalled = $true

foreach ($package in $corePackages) {
    $result = & $pythonPath -c "import $package" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $package" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $package" -ForegroundColor Red
        $allInstalled = $false
    }
}

if (-not $allInstalled) {
    Write-Host ""
    Write-Host "[ERROR] 部分核心依赖未安装！" -ForegroundColor Red
    Write-Host ""
    Write-Host "请运行：" -ForegroundColor Yellow
    Write-Host "  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
    Write-Host ""
    exit 1
}

# 步骤3：启动服务
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[步骤 3/3] 启动服务" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[SUCCESS] 部署完成！正在启动服务..." -ForegroundColor Green
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
