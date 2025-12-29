# Restart Service Script
# Used to quickly restart the robot scheduling system service

param(
    [switch]$Force = $false,
    [switch]$Background = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Restart Robot Scheduling Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Stop existing service
Write-Host "[1/2] Stopping existing service..." -ForegroundColor Yellow
Write-Host ""

# Get port from config (default 8092)
$PORT = 8092
try {
    $configContent = Get-Content "config.py" -ErrorAction SilentlyContinue | Select-String -Pattern "PORT.*=.*(\d+)"
    if ($configContent) {
        $PORT = [int]($configContent.Matches.Groups[1].Value)
    }
} catch {
    # Use default
}

# Find processes running on port
$procs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($procs) {
    Write-Host "Found running service processes: $($procs -join ', ')" -ForegroundColor Cyan
    
    # Stop processes
    $stoppedCount = 0
    foreach ($procId in $procs) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "[OK] Stopped process $procId" -ForegroundColor Green
            $stoppedCount++
        } catch {
            Write-Host "[ERROR] Failed to stop process $procId : $_" -ForegroundColor Red
        }
    }
    
    # Wait for processes to fully exit
    Write-Host "Waiting for processes to fully exit..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    
    # Verify if stopped
    $remainingProcs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($remainingProcs) {
        Write-Host "[WARN] There are still processes using port $PORT, trying to force stop..." -ForegroundColor Yellow
        foreach ($procId in $remainingProcs) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Start-Sleep -Seconds 1
            } catch {
                Write-Host "[ERROR] Failed to force stop process $procId : $_" -ForegroundColor Red
            }
        }
    }
    
    Write-Host "[OK] Stopped $stoppedCount processes" -ForegroundColor Green
} else {
    Write-Host "[OK] Service is not running, no need to stop" -ForegroundColor Green
}

Write-Host ""

# Step 2: Start new service
Write-Host "[2/2] Starting new service..." -ForegroundColor Yellow
Write-Host ""

# Check Python installation
$pythonPath = $null

# Priority 1: Use Python 3.13 (known working installation)
$python313Path = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"
if (Test-Path $python313Path) {
    $pythonPath = $python313Path
    Write-Host "[OK] Using Python 3.13: $python313Path" -ForegroundColor Green
}
# Priority 2: Try virtual environment
elseif (Test-Path "venv\Scripts\python.exe") {
    $pythonPath = "venv\Scripts\python.exe"
    Write-Host "[OK] Using virtual environment: venv\Scripts\python.exe" -ForegroundColor Green
} elseif (Test-Path "venv\bin\python.exe") {
    $pythonPath = "venv\bin\python.exe"
    Write-Host "[OK] Using virtual environment: venv\bin\python.exe" -ForegroundColor Green
}
# Priority 3: Use system Python
else {
    $pythonPath = "python"
    Write-Host "[WARN] Using system Python (may not work correctly)" -ForegroundColor Yellow
}

# Check if main.py exists
if (-not (Test-Path "main.py")) {
    Write-Host "[ERROR] main.py file not found" -ForegroundColor Red
    Write-Host "   Please make sure you are running this script from the project root directory" -ForegroundColor Red
    exit 1
}

# Additional wait to ensure port is fully released
Write-Host "Ensuring port is fully released..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Final port check before starting
$finalCheck = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
if ($finalCheck) {
    Write-Host ""
    Write-Host "[ERROR] Port $PORT is still in use after cleanup!" -ForegroundColor Red
    Write-Host "Please run diagnose.ps1 to investigate, or try again in 30 seconds" -ForegroundColor Yellow
    exit 1
}

# Start service
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[INFO] Starting service..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service will start on: http://localhost:$PORT" -ForegroundColor Cyan
Write-Host ""
Write-Host "After startup, access:" -ForegroundColor Cyan
Write-Host "  - Homepage:     http://localhost:$PORT" -ForegroundColor White
Write-Host "  - API Docs:     http://localhost:$PORT/docs" -ForegroundColor White
Write-Host "  - Robot List:   http://localhost:$PORT/static/robot_list.html" -ForegroundColor White
Write-Host "  - Task List:    http://localhost:$PORT/static/task_list.html" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop the service" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Change to script directory
Set-Location $PSScriptRoot

# Start service in foreground (blocking mode)
# This ensures we see all output and the service runs in this terminal
& $pythonPath main.py

Write-Host ""
Write-Host "Tip: Use stop_service.ps1 to stop the service" -ForegroundColor Gray
Write-Host "     Use start_service.ps1 to start the service" -ForegroundColor Gray
