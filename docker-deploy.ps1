# Docker 快速部署脚本 (PowerShell)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  多机器人调度系统 - Docker 部署" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Docker 是否安装
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 错误: Docker 未安装" -ForegroundColor Red
    Write-Host "   请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    exit 1
}

# 检查 docker-compose 是否安装
if (-not (Get-Command docker-compose -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 错误: docker-compose 未安装" -ForegroundColor Red
    Write-Host "   Docker Desktop 通常包含 docker-compose" -ForegroundColor Yellow
    exit 1
}

# 创建必要的目录
Write-Host "📁 创建必要的目录..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "data\maps" | Out-Null

# 构建镜像
Write-Host ""
Write-Host "🔨 构建 Docker 镜像..." -ForegroundColor Green
docker-compose build

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 构建失败" -ForegroundColor Red
    exit 1
}

# 启动服务
Write-Host ""
Write-Host "🚀 启动服务..." -ForegroundColor Green
docker-compose up -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 启动失败" -ForegroundColor Red
    exit 1
}

# 等待服务启动
Write-Host ""
Write-Host "⏳ 等待服务启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# 检查服务状态
Write-Host ""
Write-Host "📊 检查服务状态..." -ForegroundColor Green
$container = docker ps --filter "name=robot-scheduler" --format "{{.Names}}"

if ($container -eq "robot-scheduler") {
    Write-Host "✅ 服务已启动" -ForegroundColor Green
    Write-Host ""
    Write-Host "📝 服务信息:" -ForegroundColor Cyan
    Write-Host "   - 容器名称: robot-scheduler" -ForegroundColor White
    Write-Host "   - 访问地址: http://localhost:8092" -ForegroundColor White
    Write-Host "   - API文档: http://localhost:8092/docs" -ForegroundColor White
    Write-Host ""
    Write-Host "📋 常用命令:" -ForegroundColor Cyan
    Write-Host "   - 查看日志: docker-compose logs -f" -ForegroundColor White
    Write-Host "   - 停止服务: docker-compose down" -ForegroundColor White
    Write-Host "   - 重启服务: docker-compose restart" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "❌ 服务启动失败" -ForegroundColor Red
    Write-Host "   查看日志: docker-compose logs" -ForegroundColor Yellow
    exit 1
}

