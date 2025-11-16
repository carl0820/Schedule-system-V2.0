# Start Service Script
# Used to quickly start the robot scheduling system service

param(
    [switch]$Background = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Start Robot Scheduling Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if service is already running
$existingProcs = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($existingProcs) {
    Write-Host "[WARN] Port 8000 is already in use (Process ID: $($existingProcs -join ', '))" -ForegroundColor Yellow
    Write-Host "   Service may already be running, please use stop_service.ps1 to stop it first" -ForegroundColor Yellow
    Write-Host ""
    $response = Read-Host "Do you want to force stop and restart? (y/N)"
    if ($response -ne 'y' -and $response -ne 'Y') {
        Write-Host "Start cancelled" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "Stopping existing service..." -ForegroundColor Yellow
    Stop-Process -Id $existingProcs -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "[OK] Stopped existing service" -ForegroundColor Green
    Write-Host ""
}

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
Write-Host ""
Write-Host "Starting service..." -ForegroundColor Yellow

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
        Write-Host "  Service started successfully!" -ForegroundColor Green
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
Write-Host "     Use restart_service.ps1 to restart the service" -ForegroundColor Gray
