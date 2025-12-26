# 启动脚本 - 使用正确的Python 3.13
$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "启动多机器人调度系统" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[INFO] Python路径: $pythonPath" -ForegroundColor Green
$version = & $pythonPath --version
Write-Host "[INFO] Python版本: $version" -ForegroundColor Green
Write-Host ""

Write-Host "[INFO] 正在启动服务..." -ForegroundColor Yellow
Write-Host ""
Write-Host "服务启动后可访问：" -ForegroundColor Cyan
Write-Host "  主页面: http://localhost:8092" -ForegroundColor Yellow
Write-Host "  机器人管理: http://localhost:8092/static/robot_list.html" -ForegroundColor Yellow
Write-Host "  任务管理: http://localhost:8092/static/task_list.html" -ForegroundColor Yellow
Write-Host "  API文档: http://localhost:8092/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "按 Ctrl+C 停止服务" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 启动服务
& $pythonPath main.py
