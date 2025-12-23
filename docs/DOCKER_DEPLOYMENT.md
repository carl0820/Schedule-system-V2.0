# Docker 部署指南

## 📋 目录

- [概述](#概述)
- [前提条件](#前提条件)
- [快速开始](#快速开始)
- [详细步骤](#详细步骤)
- [网络配置](#网络配置)
- [数据持久化](#数据持久化)
- [常见问题](#常见问题)
- [生产环境部署](#生产环境部署)

## 概述

使用 Docker 部署多机器人调度系统可以带来以下优势：

- ✅ **环境一致性**：确保所有依赖都正确安装
- ✅ **隔离性**：不影响宿主机环境
- ✅ **可移植性**：可以在任何支持 Docker 的系统上运行
- ✅ **易于部署**：一键启动，无需手动配置环境
- ✅ **易于维护**：版本管理和回滚更简单

## 前提条件

### 1. 安装 Docker

**Windows:**
- 下载并安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
- 确保启用 WSL 2 后端（推荐）

**Linux:**
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 或使用包管理器
sudo apt-get update
sudo apt-get install docker.io docker-compose
```

**macOS:**
- 下载并安装 [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)

### 2. 验证 Docker 安装

```bash
docker --version
docker-compose --version
```

### 3. 确保网络连通

- 确保宿主机可以访问机器人网络（VPN已连接）
- 确保宿主机可以访问互联网（用于下载依赖）

## 快速开始

### 方法1：使用 Docker Compose（推荐）

```bash
# 1. 克隆或下载项目代码
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0

# 2. 构建并启动服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 访问服务
# 浏览器打开: http://localhost:8092/docs
```

### 方法2：使用 Docker 命令

```bash
# 1. 构建镜像
docker build -t robot-scheduler:latest .

# 2. 运行容器
docker run -d \
  --name robot-scheduler \
  -p 8092:8092 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data \
  robot-scheduler:latest

# 3. 查看日志
docker logs -f robot-scheduler
```

## 详细步骤

### 步骤1：准备项目文件

确保项目目录包含以下文件：
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `main.py`
- `app/` 目录（应用代码）

### 步骤2：构建镜像

```bash
# 使用 docker-compose（推荐）
docker-compose build

# 或使用 docker 命令
docker build -t robot-scheduler:latest .
```

### 步骤3：启动服务

```bash
# 使用 docker-compose（推荐）
docker-compose up -d

# 或使用 docker 命令
docker run -d \
  --name robot-scheduler \
  -p 8092:8092 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data \
  robot-scheduler:latest
```

### 步骤4：验证部署

```bash
# 检查容器状态
docker ps

# 查看日志
docker-compose logs -f
# 或
docker logs -f robot-scheduler

# 访问 API 文档
# 浏览器打开: http://localhost:8092/docs

# 健康检查
curl http://localhost:8092/health
```

### 步骤5：停止服务

```bash
# 使用 docker-compose
docker-compose down

# 或使用 docker 命令
docker stop robot-scheduler
docker rm robot-scheduler
```

## 网络配置

### Windows Docker Desktop

Windows 上的 Docker Desktop 默认使用 NAT 网络，容器可以访问宿主机的 VPN 网络。

**配置方法：**

1. **使用默认 bridge 网络**（推荐）：
   - 容器默认可以访问宿主机的 VPN 网络
   - 如果遇到问题，可能需要配置 `extra_hosts`

2. **配置代理**（如果 VPN 使用代理）：
   ```yaml
   # docker-compose.yml
   environment:
     - HTTP_PROXY=http://proxy:port
     - HTTPS_PROXY=http://proxy:port
     - NO_PROXY=localhost,127.0.0.1,10.160.0.0/16
   ```

3. **访问宿主机服务**：
   - 使用 `host.docker.internal` 访问宿主机服务
   - 或使用宿主机的实际 IP 地址

### Linux Docker

Linux 上可以使用 `host` 网络模式，容器直接使用宿主机的网络栈：

```yaml
# docker-compose.yml
network_mode: host
```

**注意**：`host` 网络模式在 Windows 和 macOS 的 Docker Desktop 中不支持。

### 测试网络连通性

```bash
# 进入容器
docker exec -it robot-scheduler bash

# 测试连接机器人
curl http://10.160.129.149:1448/api/core/system/v1/robot/info
```

## 数据持久化

### 挂载的目录

以下目录会被挂载到宿主机，确保数据持久化：

- `./logs` → `/app/logs`：日志文件
- `./data` → `/app/data`：任务数据库和配置文件
- `./data/maps` → `/app/data/maps`：地图文件

### 备份数据

```bash
# 备份数据目录
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf backup-20231222.tar.gz
```

## 常见问题

### 1. 容器无法访问机器人网络

**问题**：容器内无法连接到机器人（10.160.x.x）

**解决方案**：
- 确保 VPN 在宿主机上已连接
- 检查 Docker 网络配置
- 尝试使用宿主机的实际 IP 地址而不是 localhost
- 在 Linux 上使用 `network_mode: host`

### 2. 端口冲突

**问题**：端口 8092 已被占用

**解决方案**：
```yaml
# 修改 docker-compose.yml 中的端口映射
ports:
  - "8093:8092"  # 宿主机端口:容器端口
```

### 3. 权限问题

**问题**：容器无法写入日志或数据文件

**解决方案**：
```bash
# 确保目录权限正确
chmod -R 777 logs data
```

### 4. 构建失败

**问题**：Docker 构建时依赖安装失败

**解决方案**：
```bash
# 清理缓存重新构建
docker-compose build --no-cache

# 或使用国内镜像源（已在 Dockerfile 中配置）
```

### 5. 容器启动失败

**问题**：容器启动后立即退出

**解决方案**：
```bash
# 查看详细日志
docker logs robot-scheduler

# 检查配置文件
docker exec -it robot-scheduler cat /app/config.py
```

## 生产环境部署

### 1. 使用环境变量配置

创建 `.env` 文件：

```env
HOST=0.0.0.0
PORT=8092
DEBUG=false
```

修改 `docker-compose.yml`：

```yaml
environment:
  - HOST=${HOST:-0.0.0.0}
  - PORT=${PORT:-8092}
  - DEBUG=${DEBUG:-false}
```

### 2. 使用 Docker Swarm（可选）

```bash
# 初始化 Swarm
docker swarm init

# 部署服务
docker stack deploy -c docker-compose.yml robot-scheduler
```

### 3. 使用 Kubernetes（可选）

创建 `k8s-deployment.yaml`：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: robot-scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: robot-scheduler
  template:
    metadata:
      labels:
        app: robot-scheduler
    spec:
      containers:
      - name: robot-scheduler
        image: robot-scheduler:latest
        ports:
        - containerPort: 8092
        volumeMounts:
        - name: logs
          mountPath: /app/logs
        - name: data
          mountPath: /app/data
      volumes:
      - name: logs
        hostPath:
          path: /path/to/logs
      - name: data
        hostPath:
          path: /path/to/data
```

### 4. 监控和日志

```bash
# 查看容器资源使用
docker stats robot-scheduler

# 查看实时日志
docker-compose logs -f --tail=100

# 导出日志
docker-compose logs > logs/container.log
```

## 更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建镜像
docker-compose build

# 3. 重启服务
docker-compose up -d

# 4. 查看日志确认启动成功
docker-compose logs -f
```

## 卸载

```bash
# 停止并删除容器
docker-compose down

# 删除镜像（可选）
docker rmi robot-scheduler:latest

# 删除数据（谨慎操作）
# rm -rf data/ logs/
```

## 参考资源

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [项目 README](../README.md)
- [API 文档](API.md)

