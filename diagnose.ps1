# Diagnostic Script for Port 9092 Issues
# Helps identify why the service cannot bind to port 9092

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Port 9092 Diagnostic Tool" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Check if port 9092 is in use
Write-Host "[TEST 1] Checking if port 9092 is currently in use..." -ForegroundColor Yellow
try {
    $connections = Get-NetTCPConnection -LocalPort 9092 -ErrorAction SilentlyContinue
    if ($connections) {
        Write-Host "[ISSUE FOUND] Port 9092 is currently in use!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Processes using port 9092:" -ForegroundColor Yellow
        foreach ($conn in $connections) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  - PID: $($conn.OwningProcess)" -ForegroundColor White
                Write-Host "    Name: $($proc.ProcessName)" -ForegroundColor White
                Write-Host "    Path: $($proc.Path)" -ForegroundColor Gray
                Write-Host "    State: $($conn.State)" -ForegroundColor Gray
                Write-Host ""
            }
        }

        Write-Host "SOLUTION: Run the following command to stop these processes:" -ForegroundColor Cyan
        foreach ($conn in $connections) {
            Write-Host "  Stop-Process -Id $($conn.OwningProcess) -Force" -ForegroundColor White
        }
    } else {
        Write-Host "[OK] Port 9092 is not in use" -ForegroundColor Green
    }
} catch {
    Write-Host "[OK] Port 9092 appears to be available" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Test 2: Check Python processes
Write-Host "[TEST 2] Checking for running Python processes..." -ForegroundColor Yellow
try {
    $pythonProcs = Get-Process python* -ErrorAction SilentlyContinue
    if ($pythonProcs) {
        Write-Host "[INFO] Found $($pythonProcs.Count) Python process(es):" -ForegroundColor Yellow
        foreach ($proc in $pythonProcs) {
            Write-Host "  - PID: $($proc.Id), Name: $($proc.ProcessName), Start: $($proc.StartTime)" -ForegroundColor White
        }
        Write-Host ""
        Write-Host "If these are old chatbot processes, stop them with:" -ForegroundColor Cyan
        Write-Host "  Get-Process python* | Stop-Process -Force" -ForegroundColor White
    } else {
        Write-Host "[OK] No Python processes running" -ForegroundColor Green
    }
} catch {
    Write-Host "[OK] No Python processes found" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Test 3: Check if we can listen on port 9092
Write-Host "[TEST 3] Testing if we can bind to port 9092..." -ForegroundColor Yellow
try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, 9092)
    $listener.Start()
    $listener.Stop()
    Write-Host "[OK] Successfully bound to port 9092 (test passed)" -ForegroundColor Green
} catch {
    Write-Host "[ISSUE FOUND] Cannot bind to port 9092!" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  1. Port is in TIME_WAIT state (wait 30-60 seconds)" -ForegroundColor White
    Write-Host "  2. Another service is using the port" -ForegroundColor White
    Write-Host "  3. Windows firewall is blocking the port" -ForegroundColor White
    Write-Host "  4. Insufficient permissions (try running as Administrator)" -ForegroundColor White
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Test 4: Check firewall rules
Write-Host "[TEST 4] Checking Windows Firewall rules for port 9092..." -ForegroundColor Yellow
try {
    $firewallRules = Get-NetFirewallPortFilter -ErrorAction SilentlyContinue |
                     Where-Object { $_.LocalPort -eq 9092 }

    if ($firewallRules) {
        Write-Host "[INFO] Found firewall rules for port 9092:" -ForegroundColor Yellow
        foreach ($rule in $firewallRules) {
            $parentRule = Get-NetFirewallRule -AssociatedNetFirewallPortFilter $rule -ErrorAction SilentlyContinue
            if ($parentRule) {
                Write-Host "  - Rule: $($parentRule.DisplayName)" -ForegroundColor White
                Write-Host "    Enabled: $($parentRule.Enabled)" -ForegroundColor Gray
                Write-Host "    Action: $($parentRule.Action)" -ForegroundColor Gray
                Write-Host ""
            }
        }
    } else {
        Write-Host "[INFO] No specific firewall rules found for port 9092" -ForegroundColor Gray
        Write-Host "      (This is usually OK - Windows will prompt when needed)" -ForegroundColor Gray
    }
} catch {
    Write-Host "[SKIP] Cannot check firewall rules (insufficient permissions)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Test 5: Check Python installation
Write-Host "[TEST 5] Verifying Python installation..." -ForegroundColor Yellow
$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

if (Test-Path $pythonPath) {
    Write-Host "[OK] Python found at: $pythonPath" -ForegroundColor Green
    try {
        $version = & $pythonPath --version 2>&1
        Write-Host "     Version: $version" -ForegroundColor Gray
    } catch {
        Write-Host "[WARN] Cannot execute Python" -ForegroundColor Yellow
    }
} else {
    Write-Host "[ISSUE] Python not found at: $pythonPath" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Diagnostic Complete" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. If port 9092 is in use, stop the conflicting process" -ForegroundColor White
Write-Host "2. If bind test failed, wait 60 seconds and try again" -ForegroundColor White
Write-Host "3. Try running PowerShell as Administrator" -ForegroundColor White
Write-Host "4. Use start_safe.ps1 to automatically handle port conflicts" -ForegroundColor White
Write-Host ""
