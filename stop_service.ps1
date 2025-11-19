# Stop Service Script
# Used to quickly stop the robot scheduling system service

param(
    [switch]$Force = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stop Robot Scheduling Service" -ForegroundColor Cyan
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

# Find processes running on port
$procs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if (-not $procs) {
    Write-Host "[OK] Service is not running (port $PORT is not in use)" -ForegroundColor Green
    exit 0
}

# Display process information
Write-Host "Found running service processes:" -ForegroundColor Yellow
foreach ($procId in $procs) {
    try {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Process ID: $procId" -ForegroundColor Cyan
            Write-Host "  Process Name: $($proc.ProcessName)" -ForegroundColor Cyan
            $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $procId").CommandLine
            if ($cmdLine) {
                Write-Host "  Command Line: $cmdLine" -ForegroundColor Gray
            }
        }
    } catch {
        Write-Host "  Process ID: $procId (unable to get details)" -ForegroundColor Yellow
    }
}
Write-Host ""

# Confirm stop
if (-not $Force) {
    $response = Read-Host "Are you sure you want to stop these services? (Y/n)"
    if ($response -eq 'n' -or $response -eq 'N') {
        Write-Host "Stop operation cancelled" -ForegroundColor Yellow
        exit 0
    }
}

# Stop processes
Write-Host "Stopping service..." -ForegroundColor Yellow
$stoppedCount = 0
$failedCount = 0

foreach ($procId in $procs) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "[OK] Stopped process $procId" -ForegroundColor Green
        $stoppedCount++
    } catch {
        Write-Host "[ERROR] Failed to stop process $procId : $_" -ForegroundColor Red
        $failedCount++
    }
}

# Wait for processes to fully exit
Start-Sleep -Seconds 2

# Verify if stopped
$remainingProcs = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($remainingProcs) {
    Write-Host ""
    Write-Host "[WARN] There are still processes using port $PORT (Process ID: $($remainingProcs -join ', '))" -ForegroundColor Yellow
    Write-Host "   You may need to stop these processes manually" -ForegroundColor Yellow
    
    if (-not $Force) {
        $response = Read-Host "Do you want to force stop these processes? (y/N)"
        if ($response -eq 'y' -or $response -eq 'Y') {
            foreach ($procId in $remainingProcs) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                    Write-Host "[OK] Force stopped process $procId" -ForegroundColor Green
                } catch {
                    Write-Host "[ERROR] Failed to force stop process $procId : $_" -ForegroundColor Red
                }
            }
        }
    }
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Service stopped successfully" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Stopped processes: $stoppedCount" -ForegroundColor Cyan
    if ($failedCount -gt 0) {
        Write-Host "  Failed processes: $failedCount" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Tip: Use start_service.ps1 to start the service" -ForegroundColor Gray
Write-Host "     Use restart_service.ps1 to restart the service" -ForegroundColor Gray
