# 修复端口8000绑定问题的脚本
# 用于解决Windows权限错误 (WinError 10013)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  修复端口8000绑定问题" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查端口占用
Write-Host "[1/4] 检查端口8000占用情况..." -ForegroundColor Yellow
$connections = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($connections) {
    Write-Host "[WARN] 端口8000已被占用:" -ForegroundColor Yellow
    $connections | Format-Table LocalAddress, LocalPort, State, OwningProcess -AutoSize
    
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    Write-Host "占用端口的进程ID: $($pids -join ', ')" -ForegroundColor Yellow
    
    $response = Read-Host "是否要停止这些进程? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        foreach ($pid in $pids) {
            try {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "[OK] 已停止进程 $pid" -ForegroundColor Green
            } catch {
                Write-Host "[ERROR] 无法停止进程 $pid: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "[OK] 端口8000未被占用" -ForegroundColor Green
}

# 2. 检查Windows保留端口范围
Write-Host ""
Write-Host "[2/4] 检查Windows保留端口范围..." -ForegroundColor Yellow
$excludedRanges = netsh interface ipv4 show excludedportrange protocol=tcp
Write-Host $excludedRanges

# 检查8000是否在保留范围内
$inRange = $false
$excludedRanges | Select-String -Pattern "(\d+)\s+-\s+(\d+)" | ForEach-Object {
    if ($_.Matches) {
        $start = [int]$_.Matches.Groups[1].Value
        $end = [int]$_.Matches.Groups[2].Value
        if (8000 -ge $start -and 8000 -le $end) {
            $inRange = $true
            Write-Host "[WARN] 端口8000在Windows保留范围内: $start - $end" -ForegroundColor Yellow
        }
    }
}

if ($inRange) {
    Write-Host "[INFO] 建议使用其他端口，如8001或8002" -ForegroundColor Yellow
}

# 3. 检查防火墙规则
Write-Host ""
Write-Host "[3/4] 检查防火墙规则..." -ForegroundColor Yellow
$firewallRules = Get-NetFirewallRule | Where-Object { $_.DisplayName -like "*8000*" -or $_.DisplayName -like "*uvicorn*" }
if ($firewallRules) {
    Write-Host "[INFO] 找到相关防火墙规则:" -ForegroundColor Yellow
    $firewallRules | Format-Table DisplayName, Enabled, Direction -AutoSize
} else {
    Write-Host "[INFO] 未找到相关防火墙规则" -ForegroundColor Gray
}

# 4. 提供解决方案
Write-Host ""
Write-Host "[4/4] 解决方案建议:" -ForegroundColor Yellow
Write-Host "1. 如果端口被占用，已尝试停止相关进程" -ForegroundColor White
Write-Host "2. 如果端口在保留范围内，请使用其他端口:" -ForegroundColor White
Write-Host "   - 创建 .env 文件，设置 PORT=8001" -ForegroundColor White
Write-Host "   - 或修改 config.py 中的 PORT 值" -ForegroundColor White
Write-Host "3. 如果仍有问题，尝试以管理员身份运行PowerShell" -ForegroundColor White
Write-Host "4. 检查防病毒软件是否阻止了端口绑定" -ForegroundColor White

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

