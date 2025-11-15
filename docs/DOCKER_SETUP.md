# Docker 部署指南

## 概述

使用 Docker 部署多机器人调度系统，可以解决环境一致性和依赖安装问题。

## 前提条件

1. 安装 Docker Desktop（Windows）或 Docker Engine（Linux）
2. 确保 Docker 可以访问网络（如果需要安装依赖）

## 构建和运行

### 方法1：使用 Docker Compose（推荐）

```bash
# 构建并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 方法2：使用 Docker 命令

```bash
# 构建镜像
docker build -t robot-scheduler:latest .

# 运行容器
docker run -d \
  --name robot-scheduler \
  -p 8000:8000 \
  -v ./logs:/app/logs \
  -v ./data:/app/data \
  robot-scheduler:latest

# 查看日志
docker logs -f robot-scheduler

# 停止容器
docker stop robot-scheduler
docker rm robot-scheduler
```

## VPN 网络配置

### Windows Docker Desktop

Windows 上的 Docker Desktop 默认使用 NAT 网络，容器可以访问宿主机的 VPN 网络，但可能需要额外配置：

1. **使用默认 bridge 网络**（推荐）：
   - 容器默认可以访问宿主机的 VPN 网络
   - 如果遇到问题，可能需要配置 `extra_hosts`

2. **配置代理**（如果 VPN 使用代理）：
   ```yaml
   environment:
     - HTTP_PROXY=http://proxy:port
     - HTTPS_PROXY=http://proxy:port
     - NO_PROXY=localhost,127.0.0.1,10.160.0.0/16
   ```

3. **访问宿主机**：
   - 使用 `host.docker.internal` 访问宿主机服务
   - 或使用宿主机的实际 IP 地址

### Linux Docker

Linux 上可以使用 `host` 网络模式，容器直接使用宿主机的网络栈：

```yaml
network_mode: host
```

**注意**：`host` 网络模式在 Windows 和 macOS 的 Docker Desktop 中不支持。

## 验证部署

1. **检查服务状态**：
   ```bash
   docker ps
   ```

2. **访问 API 文档**：
   打开浏览器访问：http://localhost:8000/docs

3. **查看日志**：
   ```bash
   docker logs robot-scheduler
   ```

## 常见问题

### 1. 容器无法访问机器人网络

**问题**：容器内无法连接到机器人（10.160.x.x）

**解决方案**：
- 确保 VPN 在宿主机上已连接
- 检查 Docker 网络配置
- 尝试使用宿主机的实际 IP 地址而不是 localhost

### 2. requests 库未安装

**问题**：日志显示 "requests library not available"

**解决方案**：
- 检查 Dockerfile 中的 requirements.txt 是否包含 requests
- 重新构建镜像：`docker-compose build --no-cache`

### 3. 端口冲突

**问题**：端口 8000 已被占用

**解决方案**：
- 修改 docker-compose.yml 中的端口映射：`"8080:8000"`
- 或停止占用端口的其他服务

## 优势

1. **环境一致性**：确保所有依赖都正确安装
2. **隔离性**：不影响宿主机环境
3. **可移植性**：可以在任何支持 Docker 的系统上运行
4. **易于部署**：一键启动，无需手动配置环境

## 劣势

1. **网络复杂性**：VPN 网络配置可能更复杂
2. **性能开销**：Docker 有一定的性能开销
3. **Windows 限制**：某些网络功能在 Windows 上受限

## 建议

对于当前的 VPN 连接问题，**建议优先使用 requests fallback 机制**（已实现），因为：

1. **更简单**：不需要额外的 Docker 配置
2. **更直接**：直接使用宿主机的网络栈
3. **已验证**：PowerShell 的 curl 可以工作，说明网络层正常

如果 requests fallback 仍然无法解决问题，再考虑使用 Docker。

