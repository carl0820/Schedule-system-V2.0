# Startup Script - Auto-detect and use correct Python
# Works on any Windows PC

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Robot Scheduler Startup Script" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Function: Test if Python has pip
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

# Function: Get Python version
function Get-PythonVersion {
    param([string]$pythonExe)

    try {
        $version = & $pythonExe --version 2>&1
        return $version
    } catch {
        return "Unknown"
    }
}

# Find all Python installations
Write-Host "[INFO] Detecting Python environment..." -ForegroundColor Yellow
$pythonPath = $null

# Method 1: Try using python from PATH
Write-Host "[CHECK] Checking default python command..." -ForegroundColor Gray
$defaultPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($defaultPython -and (Test-PythonWithPip $defaultPython)) {
    $pythonPath = $defaultPython
    Write-Host "[OK] Found usable Python: $pythonPath" -ForegroundColor Green
}

# Method 2: If default python is not available, search for all Python installations
if (-not $pythonPath) {
    Write-Host "[CHECK] Default python not available, searching other Python installations..." -ForegroundColor Gray

    # Get all possible Python paths
    $possiblePaths = @()

    # Find all results from where python
    try {
        $wherePython = where.exe python 2>$null
        if ($wherePython) {
            $possiblePaths += $wherePython
        }
    } catch {}

    # Search common installation locations
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

    # Test each path
    foreach ($path in $possiblePaths) {
        if ($path -and (Test-Path $path) -and (Test-PythonWithPip $path)) {
            # Exclude MSYS2, Cygwin, etc.
            if ($path -notmatch "msys|cygwin|mingw") {
                $pythonPath = $path
                Write-Host "[OK] Found usable Python: $pythonPath" -ForegroundColor Green
                break
            } else {
                Write-Host "[SKIP] Skipping $path (MSYS2/Cygwin Python)" -ForegroundColor Gray
            }
        }
    }
}

# If still not found, show error
if (-not $pythonPath) {
    Write-Host ""
    Write-Host "[ERROR] No usable Python environment found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please ensure:" -ForegroundColor Yellow
    Write-Host "1. Python 3.8-3.13 is installed (recommended: 3.11 or 3.12)" -ForegroundColor White
    Write-Host "2. Python was installed with 'Add Python to PATH' option" -ForegroundColor White
    Write-Host "3. Python includes pip module" -ForegroundColor White
    Write-Host ""
    Write-Host "Download Python:" -ForegroundColor Cyan
    Write-Host "https://www.python.org/downloads/" -ForegroundColor White
    Write-Host ""
    Write-Host "Or manually specify Python path:" -ForegroundColor Cyan
    Write-Host "powershell -File start.ps1 -PythonPath 'C:\Path\To\python.exe'" -ForegroundColor White
    Write-Host ""
    exit 1
}

# Show Python info
$pythonVersion = Get-PythonVersion $pythonPath
Write-Host ""
Write-Host "Python Information:" -ForegroundColor Cyan
Write-Host "  Path: $pythonPath" -ForegroundColor White
Write-Host "  Version: $pythonVersion" -ForegroundColor White
Write-Host ""

# Check dependency installation status
Write-Host "[INFO] Checking dependency installation..." -ForegroundColor Yellow
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
    Write-Host "[WARN] Missing dependencies detected:" -ForegroundColor Yellow
    foreach ($pkg in $missingPackages) {
        Write-Host "  - $pkg" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Please install dependencies first:" -ForegroundColor Cyan
    Write-Host "  python install_deps.py" -ForegroundColor White
    Write-Host "or" -ForegroundColor Cyan
    Write-Host "  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor White
    Write-Host ""

    $continue = Read-Host "Continue to start anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 1
    }
}

# Check if port 9092 is already in use
Write-Host ""
Write-Host "[INFO] Checking if port 9092 is available..." -ForegroundColor Yellow
try {
    $portCheck = Get-NetTCPConnection -LocalPort 9092 -ErrorAction SilentlyContinue
    if ($portCheck) {
        Write-Host ""
        Write-Host "[ERROR] Port 9092 is already in use!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Process using port 9092:" -ForegroundColor Yellow
        foreach ($conn in $portCheck) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  PID $($conn.OwningProcess): $($proc.ProcessName)" -ForegroundColor White
            }
        }
        Write-Host ""
        Write-Host "Options:" -ForegroundColor Cyan
        Write-Host "1. Use restart_service.ps1 to automatically stop and restart" -ForegroundColor White
        Write-Host "2. Manually stop the process and try again" -ForegroundColor White
        Write-Host ""
        $stopNow = Read-Host "Stop existing service and start new one? (y/N)"
        if ($stopNow -eq "y" -or $stopNow -eq "Y") {
            Write-Host ""
            Write-Host "[INFO] Stopping existing service..." -ForegroundColor Yellow
            foreach ($conn in $portCheck) {
                try {
                    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
                    Write-Host "[OK] Stopped process $($conn.OwningProcess)" -ForegroundColor Green
                } catch {
                    Write-Host "[ERROR] Failed to stop process $($conn.OwningProcess)" -ForegroundColor Red
                }
            }
            Start-Sleep -Seconds 2
        } else {
            exit 1
        }
    }
} catch {
    # Port check failed, continue anyway
}

# Start service
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[INFO] Starting service..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "After service starts, access:" -ForegroundColor Cyan
Write-Host "  Homepage:        http://localhost:9092" -ForegroundColor Yellow
Write-Host "  Robot Mgmt:      http://localhost:9092/static/robot_list.html" -ForegroundColor Yellow
Write-Host "  Task Mgmt:       http://localhost:9092/static/task_list.html" -ForegroundColor Yellow
Write-Host "  Map Mgmt:        http://localhost:9092/static/map_management.html" -ForegroundColor Yellow
Write-Host "  API Docs:        http://localhost:9092/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop service" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Start service
& $pythonPath main.py
