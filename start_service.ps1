# Start Service Script
# Used to quickly start the robot scheduling system service

param(
    [switch]$Background = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Start Robot Scheduling Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get port from config (default 8092, as Windows reserves 7992-8091)
$PORT = 8092
try {
    $configContent = Get-Content "config.py" -ErrorAction SilentlyContinue | Select-String -Pattern "PORT.*=.*(\d+)"
    if ($configContent) {
        $PORT = [int]($configContent.Matches.Groups[1].Value)
    }
} catch {
    # Use default
}

# Check if service is already running
$existingProcs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($existingProcs) {
    Write-Host "[WARN] Port $PORT is already in use (Process ID: $($existingProcs -join ', '))" -ForegroundColor Yellow
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
    # Try to find Python 3.x in common locations
    $pythonCandidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    
    $foundPython = $null
    foreach ($candidate in $pythonCandidates) {
        if (Test-Path $candidate) {
            $foundPython = $candidate
            break
        }
    }
    
    if ($foundPython) {
        $pythonPath = $foundPython
        Write-Host "[OK] Using Python: $pythonPath" -ForegroundColor Green
    } else {
        $pythonPath = "python"
        Write-Host "[WARN] Virtual environment not found, using system Python" -ForegroundColor Yellow
        Write-Host "[INFO] If you encounter issues, please specify Python path explicitly" -ForegroundColor Yellow
    }
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
    Write-Host "  (This may take 10-30 seconds while loading robots and maps)" -ForegroundColor Gray
    
    # Wait for port to be listening (with timeout)
    $maxWait = 30  # Maximum wait time in seconds
    $waited = 0
    $checkInterval = 2  # Check every 2 seconds
    
    while ($waited -lt $maxWait) {
        $portCheck = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
        if ($portCheck) {
            Write-Host "  [OK] Port $PORT is now listening" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds $checkInterval
        $waited += $checkInterval
        Write-Host "  Waiting... ($waited/$maxWait seconds)" -ForegroundColor Gray
    }
    
    # Additional wait for service to fully initialize (after port is listening)
    Start-Sleep -Seconds 3
    
    # Check if service started successfully
    $checkProcs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($checkProcs) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  Service started successfully!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Process ID: $($checkProcs -join ', ')" -ForegroundColor Cyan
        Write-Host "  Service URL: http://localhost:$PORT" -ForegroundColor Cyan
        Write-Host "  API Docs: http://localhost:$PORT/docs" -ForegroundColor Cyan
        Write-Host "  Homepage: http://localhost:$PORT/" -ForegroundColor Cyan
        Write-Host ""
        
        # Try to check service health
        try {
            $response = Invoke-RestMethod -Uri "http://localhost:$PORT/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.status -eq "healthy") {
                Write-Host "[OK] Service health check: OK" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Service health check: Unexpected response" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "[WARN] Service health check: Not responding (may still be starting)" -ForegroundColor Yellow
        }
    } else {
        Write-Host ""
        Write-Host "[WARN] Service process started but port $PORT is not listening yet" -ForegroundColor Yellow
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
