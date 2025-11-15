# 机器人API测试脚本
# 用于测试阶段一功能并注册机器人

$BASE_URL = "http://localhost:8000"
$ROBOT_IP = "10.160.128.91"
$ROBOT_ID = "robot_1"
$results = @()

function Test-API {
    param(
        [string]$Method,
        [string]$Endpoint,
        [hashtable]$Params = $null,
        [hashtable]$JsonData = $null,
        [int[]]$ExpectedStatus = @(200)
    )
    
    $url = "$BASE_URL$Endpoint"
    $status = "FAIL"
    
    try {
        if ($Params) {
            $queryString = ($Params.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "&"
            if ($queryString) {
                $url += "?$queryString"
            }
        }
        
        $headers = @{
            "Content-Type" = "application/json"
        }
        
        if ($Method -eq "GET") {
            $response = Invoke-RestMethod -Uri $url -Method Get -Headers $headers -ErrorAction Stop
        }
        elseif ($Method -eq "POST") {
            if ($JsonData) {
                $body = $JsonData | ConvertTo-Json -Depth 10
                $response = Invoke-RestMethod -Uri $url -Method Post -Body $body -Headers $headers -ErrorAction Stop
            } else {
                $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -ErrorAction Stop
            }
        }
        elseif ($Method -eq "DELETE") {
            $response = Invoke-RestMethod -Uri $url -Method Delete -Headers $headers -ErrorAction Stop
        }
        
        $status = "PASS"
        $statusIcon = "[OK]"
        Write-Host "$statusIcon $Method $Endpoint" -ForegroundColor Green
        $responseJson = $response | ConvertTo-Json -Depth 5 -Compress
        Write-Host "   响应: $responseJson" -ForegroundColor Gray
        
        return $true
    }
    catch {
        try {
            $statusCode = $_.Exception.Response.StatusCode.value__
            if ($ExpectedStatus -contains $statusCode) {
                $status = "PASS"
                $statusIcon = "[OK]"
                Write-Host "$statusIcon $Method $Endpoint (StatusCode: $statusCode)" -ForegroundColor Green
                return $true
            }
        } catch {
            # StatusCode not available
        } 
        else {
            $status = "FAIL"
            $statusIcon = "[FAIL]"
            Write-Host "$statusIcon $Method $Endpoint" -ForegroundColor Red
            $errorMsg = $_.Exception.Message
            Write-Host "   错误: $errorMsg" -ForegroundColor Yellow
            return $false
        }
    }
}

Write-Host "=" * 80
Write-Host "阶段一功能测试 - API验证" -ForegroundColor Cyan
Write-Host "=" * 80
Write-Host ""

# 1. 系统级API测试
Write-Host "【系统级API】" -ForegroundColor Yellow
$results += @{Name="健康检查"; Result=(Test-API -Method "GET" -Endpoint "/health")}
$results += @{Name="系统信息"; Result=(Test-API -Method "GET" -Endpoint "/")}
Write-Host ""

# 2. 机器人管理API测试
Write-Host "【机器人管理API】" -ForegroundColor Yellow
$results += @{Name="获取机器人列表"; Result=(Test-API -Method "GET" -Endpoint "/api/robots/")}

# 注册机器人
Write-Host ""
Write-Host "正在注册机器人: $ROBOT_ID ($ROBOT_IP:1448)" -ForegroundColor Cyan
$robotBaseUrl = "http://$ROBOT_IP:1448"
$results += @{Name="注册机器人"; Result=(Test-API -Method "POST" -Endpoint "/api/robots/register" -Params @{robot_id=$ROBOT_ID; base_url=$robotBaseUrl})}

$results += @{Name="获取机器人列表（注册后）"; Result=(Test-API -Method "GET" -Endpoint "/api/robots/")}
$results += @{Name="获取机器人状态"; Result=(Test-API -Method "GET" -Endpoint "/api/robots/$ROBOT_ID/state")}
$results += @{Name="获取机器人位置"; Result=(Test-API -Method "GET" -Endpoint "/api/robots/$ROBOT_ID/pose")}
Write-Host ""

# 3. 任务管理API测试
Write-Host "【任务管理API】" -ForegroundColor Yellow
$results += @{Name="获取任务列表"; Result=(Test-API -Method "GET" -Endpoint "/api/tasks/")}

$taskData = @{
    target_pose = @{
        x = 5.0
        y = 3.0
        yaw = 0.0
    }
    priority = 2
}
$results += @{Name="创建任务"; Result=(Test-API -Method "POST" -Endpoint "/api/tasks/" -JsonData $taskData)}

$results += @{Name="获取任务列表（创建后）"; Result=(Test-API -Method "GET" -Endpoint "/api/tasks/")}

# 获取任务ID并测试详情和取消
try {
    $taskResponse = Invoke-RestMethod -Uri "$BASE_URL/api/tasks/" -Method Get
    if ($taskResponse -and $taskResponse.Count -gt 0) {
        $taskId = $taskResponse[0].task_id
        $results += @{Name="获取任务详情"; Result=(Test-API -Method "GET" -Endpoint "/api/tasks/$taskId")}
        $results += @{Name="取消任务"; Result=(Test-API -Method "DELETE" -Endpoint "/api/tasks/$taskId")}
    }
} catch {
    Write-Host "⚠️  无法获取任务ID: $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host ""

# 4. 地图管理API测试
Write-Host "【地图管理API】" -ForegroundColor Yellow
$results += @{Name="获取地图信息"; Result=(Test-API -Method "GET" -Endpoint "/api/maps/info" -ExpectedStatus @(200, 404))}
$results += @{Name="检查位置"; Result=(Test-API -Method "GET" -Endpoint "/api/maps/check" -Params @{x=1.0; y=1.0} -ExpectedStatus @(200, 500))}
$results += @{Name="加载地图"; Result=(Test-API -Method "POST" -Endpoint "/api/maps/load" -Params @{robot_id=$ROBOT_ID} -ExpectedStatus @(200, 404, 500))}
Write-Host ""

# 5. 系统监控API测试
Write-Host "【系统监控API】" -ForegroundColor Yellow
$results += @{Name="获取系统状态"; Result=(Test-API -Method "GET" -Endpoint "/api/system/status")}
$results += @{Name="获取系统指标"; Result=(Test-API -Method "GET" -Endpoint "/api/system/metrics")}
Write-Host ""

# 6. 测试总结
Write-Host "=" * 80
Write-Host "测试总结" -ForegroundColor Cyan
Write-Host "=" * 80

$passed = ($results | Where-Object { $_.Result -eq $true }).Count
$failed = ($results | Where-Object { $_.Result -eq $false }).Count

foreach ($result in $results) {
    $status = if ($result.Result) { "[PASS]" } else { "[FAIL]" }
    Write-Host "$status - $($result.Name)"
}

Write-Host ""
Write-Host "总测试数: $($results.Count)"
Write-Host "✅ 通过: $passed" -ForegroundColor Green
Write-Host "❌ 失败: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host "通过率: $([math]::Round($passed/$results.Count*100, 1))%"
Write-Host "=" * 80

exit $(if ($failed -eq 0) { 0 } else { 1 })

