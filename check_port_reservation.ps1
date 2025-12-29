# Check Windows Port Reservations
# This script checks if port 8092 is in the reserved port range

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Windows Port Reservation Check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[CHECK 1] Checking Windows reserved port ranges..." -ForegroundColor Yellow
try {
    # Get all reserved port ranges
    $reservedPorts = netsh interface ipv4 show excludedportrange protocol=tcp

    Write-Host ""
    Write-Host "Reserved Port Ranges:" -ForegroundColor White
    Write-Host $reservedPorts
    Write-Host ""

    # Check if 8092 is in any reserved range
    $inReservedRange = $false
    $reservedPorts -split "`n" | ForEach-Object {
        if ($_ -match '^\s*(\d+)\s+(\d+)\s+') {
            $start = [int]$Matches[1]
            $end = [int]$Matches[2]
            if (8092 -ge $start -and 8092 -le $end) {
                $inReservedRange = $true
                Write-Host "[ISSUE FOUND] Port 8092 is in reserved range: $start - $end" -ForegroundColor Red
            }
        }
    }

    if (-not $inReservedRange) {
        Write-Host "[OK] Port 8092 is NOT in any reserved range" -ForegroundColor Green
    }
} catch {
    Write-Host "[ERROR] Failed to check port reservations: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[CHECK 2] Checking Hyper-V dynamic port range..." -ForegroundColor Yellow
try {
    $dynamicPorts = netsh int ipv4 show dynamicport tcp
    Write-Host ""
    Write-Host "Dynamic Port Range:" -ForegroundColor White
    Write-Host $dynamicPorts
    Write-Host ""
} catch {
    Write-Host "[ERROR] Failed to check dynamic ports: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SOLUTIONS" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($inReservedRange) {
    Write-Host "Port 8092 is reserved by Windows. Solutions:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Option 1: Change service port to an unreserved port" -ForegroundColor Cyan
    Write-Host "  Edit config.py, change PORT from 8092 to 8093 or 9092" -ForegroundColor White
    Write-Host ""
    Write-Host "Option 2: Exclude port 8092 from reserved range (requires Admin)" -ForegroundColor Cyan
    Write-Host "  Run as Administrator:" -ForegroundColor White
    Write-Host "  netsh int ipv4 add excludedportrange protocol=tcp startport=8092 numberofports=1" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "Port 8092 is not reserved. Other possible causes:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Try a different port (edit config.py):" -ForegroundColor Cyan
    Write-Host "   PORT = 8093  # or 9092, 9000, etc." -ForegroundColor White
    Write-Host ""
    Write-Host "2. Check if another service is configured to use 8092" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "3. Run PowerShell as Administrator" -ForegroundColor Cyan
    Write-Host ""
}

Write-Host "============================================================" -ForegroundColor Cyan
