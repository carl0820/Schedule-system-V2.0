# Service Check Script
# Used to check if the service is running correctly

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Service Status Check" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
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

# Check if port is listening
$portCheck = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
if ($portCheck) {
    Write-Host "[OK] Port $PORT is listening" -ForegroundColor Green
    Write-Host "  Process ID: $($portCheck.OwningProcess -join ', ')" -ForegroundColor Cyan
} else {
    Write-Host "[WARN] Port $PORT is not listening" -ForegroundColor Yellow
}

Write-Host ""

# Check Python processes
$pythonProcs = Get-Process python* -ErrorAction SilentlyContinue
if ($pythonProcs) {
    Write-Host "[INFO] Python processes running:" -ForegroundColor Cyan
    foreach ($proc in $pythonProcs) {
        Write-Host "  PID: $($proc.Id), Path: $($proc.Path)" -ForegroundColor Gray
    }
} else {
    Write-Host "[WARN] No Python processes found" -ForegroundColor Yellow
}

Write-Host ""

# Try to access the service
try {
    $response = Invoke-WebRequest -Uri "http://localhost:$PORT/health" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "[OK] Service is responding" -ForegroundColor Green
    Write-Host "  Status: $($response.StatusCode)" -ForegroundColor Cyan
    try {
        $health = $response.Content | ConvertFrom-Json
        Write-Host "  Health: $($health.status)" -ForegroundColor Cyan
    } catch {
        Write-Host "  Response: $($response.Content.Substring(0, [Math]::Min(100, $response.Content.Length)))" -ForegroundColor Gray
    }
} catch {
    Write-Host "[ERROR] Service is not responding" -ForegroundColor Red
    Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Check log file
if (Test-Path "logs\app.log") {
    $logSize = (Get-Item "logs\app.log").Length
    $logLines = (Get-Content "logs\app.log" -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "[INFO] Log file status:" -ForegroundColor Cyan
    Write-Host "  Size: $([math]::Round($logSize/1KB, 2)) KB" -ForegroundColor Gray
    Write-Host "  Lines: $logLines" -ForegroundColor Gray
    
    # Check for recent errors
    $recentErrors = Get-Content "logs\app.log" -Tail 50 -ErrorAction SilentlyContinue | Select-String -Pattern "ERROR|Exception|Traceback" | Select-Object -Last 5
    if ($recentErrors) {
        Write-Host ""
        Write-Host "[WARN] Recent errors in log:" -ForegroundColor Yellow
        foreach ($error in $recentErrors) {
            Write-Host "  $($error.Line.Trim())" -ForegroundColor Red
        }
    }
} else {
    Write-Host "[WARN] Log file not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan

