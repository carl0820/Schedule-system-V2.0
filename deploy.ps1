# One-Click Deployment Script for Windows
# Auto-complete: Detect Python -> Install dependencies -> Start service

param(
    [switch]$SkipDependencies = $false
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Robot Scheduler - One-Click Deployment Script          " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Function: Test if Python has pip
function Test-PythonWithPip {
    param([string]$pythonExe)
    try {
        $result = & $pythonExe -m pip --version 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# Function: Get Python version
function Get-PythonVersion {
    param([string]$pythonExe)
    try {
        $version = & $pythonExe --version 2>&1
        return $version -replace "Python ", ""
    } catch {
        return "Unknown"
    }
}

# Step 1: Detect Python environment
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[Step 1/3] Detecting Python Environment" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$pythonPath = $null

# Try using python from PATH
$defaultPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($defaultPython -and (Test-PythonWithPip $defaultPython)) {
    $pythonPath = $defaultPython
    Write-Host "[OK] Found usable Python: $pythonPath" -ForegroundColor Green
}

# If default python is not available, search for all possible Python installations
if (-not $pythonPath) {
    Write-Host "[INFO] Searching for Python installations..." -ForegroundColor Yellow

    $possiblePaths = @()

    # Find all results from where python
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

    # Search common installation locations
    $pythonVersions = @("313", "312", "311", "310", "39", "38")
    foreach ($ver in $pythonVersions) {
        $possiblePaths += "$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe"
        $possiblePaths += "C:\Python$ver\python.exe"
    }

    # Test each path
    foreach ($path in $possiblePaths) {
        if ($path -and (Test-Path $path -ErrorAction SilentlyContinue) -and (Test-PythonWithPip $path)) {
            # Exclude MSYS2, Cygwin, etc.
            if ($path -notmatch "msys|cygwin|mingw") {
                $pythonPath = $path
                Write-Host "[OK] Found usable Python: $pythonPath" -ForegroundColor Green
                break
            }
        }
    }
}

# If Python is not found, show installation instructions
if (-not $pythonPath) {
    Write-Host ""
    Write-Host "[ERROR] No usable Python environment found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please follow these steps:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Download Python 3.8-3.13 (recommended: 3.11 or 3.12)" -ForegroundColor White
    Write-Host "   Download: https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "2. During installation, check 'Add Python to PATH'" -ForegroundColor White
    Write-Host ""
    Write-Host "3. After installation, run this script again" -ForegroundColor White
    Write-Host ""
    exit 1
}

$pythonVersion = Get-PythonVersion $pythonPath
Write-Host ""
Write-Host "Python Environment:" -ForegroundColor Cyan
Write-Host "  Path: $pythonPath" -ForegroundColor White
Write-Host "  Version: $pythonVersion" -ForegroundColor White
Write-Host ""

# Step 2: Install dependencies
if (-not $SkipDependencies) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "[Step 2/3] Installing Dependencies" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    # Disable proxy
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""

    # Upgrade pip
    Write-Host "[INFO] Upgrading pip..." -ForegroundColor Yellow
    & $pythonPath -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] pip upgraded successfully" -ForegroundColor Green
    } else {
        Write-Host "[WARN] pip upgrade failed, using current version" -ForegroundColor Yellow
    }

    # Install core dependencies
    Write-Host ""
    Write-Host "[INFO] Installing core dependencies (fastapi, uvicorn, httpx, pydantic, requests)..." -ForegroundColor Yellow
    $corePackages = "fastapi>=0.104.1 uvicorn>=0.24.0 httpx>=0.25.2 pydantic>=2.5.0 requests>=2.31.0"

    & $pythonPath -m pip install $corePackages.Split() -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Core dependencies installed successfully" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Core dependencies installation failed" -ForegroundColor Red
        Write-Host ""
        Write-Host "Please install manually:" -ForegroundColor Yellow
        Write-Host "  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
        Write-Host ""
        exit 1
    }

    # Install other dependencies
    Write-Host ""
    Write-Host "[INFO] Installing other dependencies..." -ForegroundColor Yellow
    & $pythonPath -m pip install -r requirements.txt --only-binary=:all: -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] All dependencies installed successfully" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Some dependencies installation failed (may be optional)" -ForegroundColor Yellow
    }

    Write-Host ""
} else {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "[Step 2/3] Skipping dependency installation (-SkipDependencies)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# Verify core dependencies
Write-Host "[INFO] Verifying core dependencies..." -ForegroundColor Yellow
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
    Write-Host "[ERROR] Some core dependencies are not installed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please run:" -ForegroundColor Yellow
    Write-Host "  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
    Write-Host ""
    exit 1
}

# Step 3: Start service
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[Step 3/3] Starting Service" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[SUCCESS] Deployment complete! Starting service..." -ForegroundColor Green
Write-Host ""
Write-Host "After service starts, access:" -ForegroundColor Cyan
Write-Host "  Homepage:        http://localhost:8092" -ForegroundColor Yellow
Write-Host "  Robot Mgmt:      http://localhost:8092/static/robot_list.html" -ForegroundColor Yellow
Write-Host "  Task Mgmt:       http://localhost:8092/static/task_list.html" -ForegroundColor Yellow
Write-Host "  Map Mgmt:        http://localhost:8092/static/map_management.html" -ForegroundColor Yellow
Write-Host "  API Docs:        http://localhost:8092/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop the service" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Start service
& $pythonPath main.py
