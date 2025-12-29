# Safe Startup Script
# Ensures port is free before starting service

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Robot Scheduler - Safe Startup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Stop any Python processes that might be using port 8092
Write-Host "[STEP 1/3] Checking for conflicting processes..." -ForegroundColor Yellow

# Try multiple times to check port
$maxAttempts = 3
$portIsFree = $false

for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
        $portCheck = Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue
        if ($portCheck) {
            Write-Host "[WARN] Port 8092 is in use (attempt $i/$maxAttempts)" -ForegroundColor Yellow

            # Stop processes using the port
            foreach ($conn in $portCheck) {
                $pid = $conn.OwningProcess
                try {
                    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Host "  Stopping process: $($proc.ProcessName) (PID: $pid)" -ForegroundColor Gray
                        Stop-Process -Id $pid -Force -ErrorAction Stop
                    }
                } catch {
                    Write-Host "  Failed to stop PID $pid" -ForegroundColor Red
                }
            }

            # Wait for processes to fully stop
            Start-Sleep -Seconds 2
        } else {
            $portIsFree = $true
            Write-Host "[OK] Port 8092 is available" -ForegroundColor Green
            break
        }
    } catch {
        # Error checking port, assume it's free
        $portIsFree = $true
        break
    }
}

if (-not $portIsFree) {
    Write-Host ""
    Write-Host "[ERROR] Failed to free port 8092 after $maxAttempts attempts" -ForegroundColor Red
    Write-Host "Please manually stop processes using port 8092 and try again" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Step 2: Verify Python installation
Write-Host "[STEP 2/3] Verifying Python installation..." -ForegroundColor Yellow

$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $pythonPath)) {
    Write-Host "[ERROR] Python not found at: $pythonPath" -ForegroundColor Red
    Write-Host "Please install Python 3.13 or update the path in this script" -ForegroundColor Yellow
    exit 1
}

# Get Python version
try {
    $pythonVersion = & $pythonPath --version 2>&1
    Write-Host "[OK] Found Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to execute Python" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 3: Start service
Write-Host "[STEP 3/3] Starting service..." -ForegroundColor Yellow
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service will start on: http://localhost:8092" -ForegroundColor Cyan
Write-Host ""
Write-Host "Available URLs after startup:" -ForegroundColor Cyan
Write-Host "  - Homepage:     http://localhost:8092" -ForegroundColor White
Write-Host "  - API Docs:     http://localhost:8092/docs" -ForegroundColor White
Write-Host "  - Robot List:   http://localhost:8092/static/robot_list.html" -ForegroundColor White
Write-Host "  - Task List:    http://localhost:8092/static/task_list.html" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop the service" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Change to script directory
Set-Location $PSScriptRoot

# Start service
& $pythonPath main.py
