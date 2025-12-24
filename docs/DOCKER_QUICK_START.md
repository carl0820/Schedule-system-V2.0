# Docker 快速部署指南

## 一、前提条件

### 1. 安装 Docker Desktop

**Windows:**
- 下载地址：https://www.docker.com/products/docker-desktop/
- 安装后启动 Docker Desktop

**Linux:**
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 启动 Docker 服务
sudo systemctl start docker
sudo systemctl enable docker
```

**macOS:**
- 下载地址：https://www.docker.com/products/docker-desktop/
- 安装后启动 Docker Desktop

### 2. 验证安装

```bash
docker --version
docker-compose --version
```

## 二、快速部署步骤

### 方法1：使用 Docker Compose（推荐）

#### 步骤1：克隆代码

```bash
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0
```

#### 步骤2：构建并启动

```bash
# 构建镜像并启动容器
docker-compose up -d --build
```

#### 步骤3：查看日志

```bash
# 查看服务日志
docker-compose logs -f

# 查看最后50行日志
docker-compose logs --tail=50
```

#### 步骤4：访问服务

- 服务地址：http://localhost:8092
- API 文档：http://localhost:8092/docs
- 健康检查：http://localhost:8092/health

### 方法2：使用 Docker 命令

#### 步骤1：克隆代码

```bash
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0
```

#### 步骤2：构建镜像

```bash
docker build -t robot-scheduler:latest .
```

#### 步骤3：运行容器

```bash
docker run -d \
  --name robot-scheduler \
  -p 8092:8092 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/data/maps:/app/data/maps \
  robot-scheduler:latest
```

**Windows PowerShell:**
```powershell
docker run -d `
  --name robot-scheduler `
  -p 8092:8092 `
  -v ${PWD}/logs:/app/logs `
  -v ${PWD}/data:/app/data `
  -v ${PWD}/data/maps:/app/data/maps `
  robot-scheduler:latest
```

## 三、配置说明

### 1. 端口配置

默认端口：`8092`

如需修改端口，编辑 `docker-compose.yml`：

```yaml
services:
  robot-scheduler:
    ports:
      - "8092:8092"  # 修改为 "新端口:8092"
```

### 2. 数据持久化

以下目录已挂载到宿主机，数据会持久保存：

- `./logs` → 日志文件
- `./data` → 任务数据库和配置
- `./data/maps` → 地图文件

### 3. 环境变量

可以在 `docker-compose.yml` 中设置环境变量：

```yaml
services:
  robot-scheduler:
    environment:
      - HOST=0.0.0.0
      - PORT=8092
      # 如果需要连接宿主机的Redis或PostgreSQL
      # - REDIS_HOST=host.docker.internal
      # - POSTGRES_HOST=host.docker.internal
```

## 四、常用命令

### 查看容器状态

```bash
# 查看运行中的容器
docker ps

# 查看所有容器（包括停止的）
docker ps -a

# 查看容器日志
docker logs robot-scheduler

# 实时查看日志
docker logs -f robot-scheduler
```

### 管理容器

```bash
# 停止容器
docker-compose stop
# 或
docker stop robot-scheduler

# 启动容器
docker-compose start
# 或
docker start robot-scheduler

# 重启容器
docker-compose restart
# 或
docker restart robot-scheduler

# 停止并删除容器
docker-compose down
# 或
docker stop robot-scheduler
docker rm robot-scheduler
```

### 更新代码

```bash
# 1. 停止容器
docker-compose down

# 2. 拉取最新代码
git pull

# 3. 重新构建并启动
docker-compose up -d --build
```

### 进入容器（调试用）

```bash
# 进入容器
docker exec -it robot-scheduler bash

# 查看容器内文件
docker exec -it robot-scheduler ls -la /app

# 查看容器资源使用
docker stats robot-scheduler
```

## 五、网络配置

### 1. VPN 网络访问

如果机器人需要通过 VPN 连接，确保 Docker 容器可以访问 VPN 网络：

**Windows:**
- Docker Desktop 默认可以访问宿主机的 VPN 网络
- 如果无法访问，检查 Docker Desktop 的网络设置

**Linux:**
- 确保 Docker 网络配置正确
- 可能需要配置 Docker 网络模式为 `host` 或使用 `--network host`

### 2. 防火墙配置

确保端口 8092 未被防火墙阻止：

**Windows:**
```powershell
# 检查端口是否被占用
netstat -ano | findstr :8092

# 添加防火墙规则（如果需要）
New-NetFirewallRule -DisplayName "Robot Scheduler" -Direction Inbound -LocalPort 8092 -Protocol TCP -Action Allow
```

**Linux:**
```bash
# 检查端口是否被占用
netstat -tuln | grep 8092

# 开放端口（如果需要）
sudo ufw allow 8092/tcp
```

## 六、验证部署

### 1. 健康检查

```bash
# 使用 curl
curl http://localhost:8092/health

# 使用浏览器
# 访问 http://localhost:8092/health
```

预期响应：
```json
{"status":"healthy"}
```

### 2. API 文档

访问 http://localhost:8092/docs 查看 API 文档

### 3. 查看日志

```bash
# 查看服务日志
docker-compose logs --tail=50

# 查看应用日志
cat logs/app.log | tail -50
```

## 七、常见问题

### 1. 端口被占用

**错误信息：**
```
Error: bind: address already in use
```

**解决方法：**
```bash
# 查找占用端口的进程
# Windows
netstat -ano | findstr :8092

# Linux/Mac
lsof -i :8092

# 修改 docker-compose.yml 中的端口映射
ports:
  - "8093:8092"  # 使用其他端口
```

### 2. 容器无法启动

**查看日志：**
```bash
docker-compose logs robot-scheduler
```

**常见原因：**
- 端口被占用
- 配置文件错误
- 依赖服务未启动

### 3. 无法访问服务

**检查步骤：**
1. 确认容器正在运行：`docker ps`
2. 确认端口映射正确：`docker port robot-scheduler`
3. 检查防火墙设置
4. 查看容器日志：`docker logs robot-scheduler`

### 4. 数据丢失

**原因：**
- 未挂载数据卷
- 容器被删除且未使用数据卷

**解决方法：**
- 确保使用 `-v` 参数挂载数据目录
- 定期备份 `data` 和 `logs` 目录

### 5. 网络连接问题

**如果容器无法访问机器人：**

**Windows:**
- 检查 Docker Desktop 的网络设置
- 确保 VPN 连接正常
- 尝试使用 `host.docker.internal` 访问宿主机服务

**Linux:**
- 检查 Docker 网络配置
- 可能需要使用 `--network host` 模式

## 八、生产环境部署建议

### 1. 使用 Docker Compose

推荐使用 `docker-compose.yml` 进行部署，便于管理。

### 2. 配置自动重启

在 `docker-compose.yml` 中已配置：
```yaml
restart: unless-stopped
```

### 3. 日志管理

- 日志文件会自动轮转（通过 RotatingFileHandler）
- 定期清理旧日志文件

### 4. 数据备份

定期备份以下目录：
- `data/tasks.db` - 任务数据库
- `data/robots.json` - 机器人配置
- `data/maps/` - 地图文件

### 5. 监控

- 使用 `docker stats` 监控资源使用
- 配置健康检查：`http://localhost:8092/health`
- 监控日志文件大小

## 九、完整部署示例

### Windows PowerShell

```powershell
# 1. 克隆代码
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0

# 2. 构建并启动
docker-compose up -d --build

# 3. 查看日志
docker-compose logs -f

# 4. 访问服务
# 浏览器打开 http://localhost:8092/docs
```

### Linux/Mac

```bash
# 1. 克隆代码
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0

# 2. 构建并启动
docker-compose up -d --build

# 3. 查看日志
docker-compose logs -f

# 4. 访问服务
# 浏览器打开 http://localhost:8092/docs
```

## 十、更新服务

### 方法1：使用 Git 更新

```bash
# 1. 停止服务
docker-compose down

# 2. 拉取最新代码
git pull

# 3. 重新构建并启动
docker-compose up -d --build
```

### 方法2：重新克隆

```bash
# 1. 备份数据
cp -r data data_backup
cp -r logs logs_backup

# 2. 删除旧代码
cd ..
rm -rf Schedule-system-V2.0

# 3. 重新克隆
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0

# 4. 恢复数据（如果需要）
# cp -r ../data_backup/* data/
# cp -r ../logs_backup/* logs/

# 5. 构建并启动
docker-compose up -d --build
```

## 十一、卸载

```bash
# 停止并删除容器
docker-compose down

# 删除镜像（可选）
docker rmi robot-scheduler:latest

# 删除数据（谨慎操作）
# rm -rf data logs
```

## 十二、技术支持

如遇问题，请：
1. 查看日志：`docker-compose logs`
2. 检查 GitHub Issues：https://github.com/carl0820/Schedule-system-V2.0/issues
3. 查看文档：`docs/DOCKER_DEPLOYMENT.md`

