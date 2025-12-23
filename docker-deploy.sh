#!/bin/bash
# Docker 快速部署脚本

set -e

echo "=========================================="
echo "  多机器人调度系统 - Docker 部署"
echo "=========================================="
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: Docker 未安装"
    echo "   请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 docker-compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ 错误: docker-compose 未安装"
    echo "   请先安装 docker-compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# 创建必要的目录
echo "📁 创建必要的目录..."
mkdir -p logs data/maps
chmod -R 755 logs data

# 构建镜像
echo ""
echo "🔨 构建 Docker 镜像..."
docker-compose build

# 启动服务
echo ""
echo "🚀 启动服务..."
docker-compose up -d

# 等待服务启动
echo ""
echo "⏳ 等待服务启动..."
sleep 5

# 检查服务状态
echo ""
echo "📊 检查服务状态..."
if docker ps | grep -q robot-scheduler; then
    echo "✅ 服务已启动"
    echo ""
    echo "📝 服务信息:"
    echo "   - 容器名称: robot-scheduler"
    echo "   - 访问地址: http://localhost:8092"
    echo "   - API文档: http://localhost:8092/docs"
    echo ""
    echo "📋 常用命令:"
    echo "   - 查看日志: docker-compose logs -f"
    echo "   - 停止服务: docker-compose down"
    echo "   - 重启服务: docker-compose restart"
    echo ""
else
    echo "❌ 服务启动失败"
    echo "   查看日志: docker-compose logs"
    exit 1
fi

