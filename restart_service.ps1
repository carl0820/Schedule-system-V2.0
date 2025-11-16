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

# Find processes running on port 8000
$procs = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

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
    $remainingProcs = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($remainingProcs) {
        Write-Host "[WARN] There are still processes using port 8000, trying to force stop..." -ForegroundColor Yellow
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

# Check virtual environment
$pythonPath = $null
if (Test-Path "venv\Scripts\python.exe") {
    $pythonPath = "venv\Scripts\python.exe"
    Write-Host "[OK] Using virtual environment: venv\Scripts\python.exe" -ForegroundColor Green
} elseif (Test-Path "venv\bin\python.exe") {
    $pythonPath = "venv\bin\python.exe"
    Write-Host "[OK] Using virtual environment: venv\bin\python.exe" -ForegroundColor Green
} else {
    $pythonPath = "python"
    Write-Host "[WARN] Virtual environment not found, using system Python" -ForegroundColor Yellow
}

# Check if main.py exists
if (-not (Test-Path "main.py")) {
    Write-Host "[ERROR] main.py file not found" -ForegroundColor Red
    Write-Host "   Please make sure you are running this script from the project root directory" -ForegroundColor Red
    exit 1
}

# Start service
try {
    if ($Background) {
        # Run in background (no window)
        $process = Start-Process -FilePath $pythonPath -ArgumentList "main.py" -WindowStyle Hidden -PassThru
        Write-Host "[OK] Service started in background (Process ID: $($process.Id))" -ForegroundColor Green
    } else {
        # Run in foreground (show window)
        $process = Start-Process -FilePath $pythonPath -ArgumentList "main.py" -PassThru
        Write-Host "[OK] Service started (Process ID: $($process.Id))" -ForegroundColor Green
    }
    
    # Wait for service to start
    Write-Host "Waiting for service to initialize..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
    
    # Check if service started successfully
    $checkProcs = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($checkProcs) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  Service restarted successfully!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Process ID: $($checkProcs -join ', ')" -ForegroundColor Cyan
        Write-Host "  Service URL: http://localhost:8000" -ForegroundColor Cyan
        Write-Host "  API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
        Write-Host "  Homepage: http://localhost:8000/" -ForegroundColor Cyan
        Write-Host ""
        
        # Try to check service health
        try {
            $response = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            Write-Host "[OK] Service health check: OK" -ForegroundColor Green
        } catch {
            Write-Host "[WARN] Service health check: Not responding (may still be starting)" -ForegroundColor Yellow
        }
    } else {
        Write-Host ""
        Write-Host "[WARN] Service process started but port 8000 is not listening yet" -ForegroundColor Yellow
        Write-Host "   Please wait a moment, or check the log file logs\app.log" -ForegroundColor Yellow
    }
} catch {
    Write-Host ""
    Write-Host "[ERROR] Failed to start service" -ForegroundColor Red
    Write-Host "   Error: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Tip: Use stop_service.ps1 to stop the service" -ForegroundColor Gray
Write-Host "     Use start_service.ps1 to start the service" -ForegroundColor Gray
