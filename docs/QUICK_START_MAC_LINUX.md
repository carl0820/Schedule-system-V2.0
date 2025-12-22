# 🚀 快速开始指南 (Mac/Linux)

> 5分钟快速部署多机器人调度系统

## 第一步：下载代码

从GitHub下载或克隆代码到本地：

```bash
# 方法1: 下载ZIP并解压
# 访问: https://github.com/carl0820/schedule-system-based-on-REST
# 点击 "Code" → "Download ZIP"

# 方法2: 使用Git克隆（推荐）
git clone https://github.com/carl0820/schedule-system-based-on-REST.git
cd schedule-system-based-on-REST
```

## 第二步：安装依赖

打开终端，进入项目目录，运行：

```bash
# 推荐：使用Python安装脚本（自动处理网络问题）
python install_deps.py

# 或使用 python3（如果系统默认是 Python 2）
python3 install_deps.py
```

如果脚本不可用，手动安装：

```bash
# 使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或直接安装（不推荐，可能污染系统环境）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 第三步：启动服务

```bash
# 如果使用虚拟环境，先激活
source venv/bin/activate

# 方法1: 使用启动脚本（推荐，首次使用需要添加执行权限）
chmod +x start_service.sh
./start_service.sh

# 方法2: 直接运行
python main.py

# 方法3: 使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 第四步：访问系统

打开浏览器访问：
- **首页**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

## 完成！

现在你可以：
1. 注册机器人（点击"机器人管理"）
2. 加载地图（点击"地图管理"）
3. 创建任务（在首页选择POI点或输入坐标）

---

## 常用命令

### 使用启动脚本（推荐）

首次使用需要添加执行权限：

```bash
chmod +x start_service.sh stop_service.sh restart_service.sh
```

然后就可以使用：

```bash
# 启动服务
./start_service.sh

# 停止服务
./stop_service.sh

# 重启服务
./restart_service.sh
```

### 启动服务
```bash
# 使用虚拟环境
source venv/bin/activate
python main.py

# 后台运行（使用 nohup）
nohup python main.py > logs/service.log 2>&1 &

# 或使用 screen（推荐，可以重新连接）
screen -S robot_scheduler
python main.py
# 按 Ctrl+A 然后 D 来分离会话
# 使用 screen -r robot_scheduler 重新连接
```

### 停止服务
```bash
# 查找进程
ps aux | grep "python main.py"

# 停止服务（替换 <PID> 为实际进程ID）
kill <PID>

# 或使用端口查找并停止
lsof -ti:8000 | xargs kill

# 强制停止
kill -9 <PID>
```

### 重启服务
```bash
# 停止服务
lsof -ti:8000 | xargs kill

# 等待2秒
sleep 2

# 启动服务
source venv/bin/activate
python main.py
```

### 查看日志
```bash
# 查看应用日志
tail -f logs/app.log

# 查看死锁日志
tail -f logs/deadlock.log

# 查看最近50行
tail -n 50 logs/app.log

# 使用 less 查看（可以上下滚动）
less logs/app.log
```

---

## 需要帮助？

- **详细文档**: 查看 `docs/QUICK_START_GUIDE.md`
- **常见问题**: 查看下面的"常见问题"部分
- **API文档**: http://localhost:8000/docs

---

## 系统要求

- **操作系统**: macOS 10.14+ / Linux (Ubuntu 18.04+, CentOS 7+, Debian 10+, 等)
- **Python**: 3.8 - 3.13（推荐 3.11 或 3.12）
- **内存**: 4GB+ RAM（推荐 8GB+）
- **网络**: 与机器人网络连通

---

## 常见问题

### Q1: Python 未找到

**错误**: `command not found: python`

**解决方案**:
```bash
# 检查 Python 版本
python3 --version

# 如果只有 python3，使用 python3 命令
python3 install_deps.py
python3 main.py

# 或创建别名（添加到 ~/.bashrc 或 ~/.zshrc）
alias python=python3
```

### Q2: 端口被占用

**错误**: `Address already in use` 或 `端口已被使用`

**解决方案**:
```bash
# 查找占用端口的进程
lsof -i :8000

# 或使用 netstat (Linux)
netstat -tulpn | grep :8000

# 停止进程（替换 <PID> 为实际进程ID）
kill <PID>

# 或强制停止
kill -9 <PID>
```

### Q3: 权限问题

**错误**: `Permission denied`

**解决方案**:
```bash
# 给脚本添加执行权限（如果需要）
chmod +x install_deps.py

# 或使用 python 直接运行（推荐）
python install_deps.py

# 如果 pip 安装失败，使用 sudo（不推荐，可能污染系统）
sudo pip install -r requirements.txt
```

### Q4: 虚拟环境激活失败

**错误**: `source: command not found` (某些 shell)

**解决方案**:
```bash
# bash/zsh (大多数系统)
source venv/bin/activate

# fish shell
source venv/bin/activate.fish

# csh/tcsh
source venv/bin/activate.csh

# 或使用点命令（bash/zsh）
. venv/bin/activate
```

### Q5: 依赖安装失败

**错误**: `pip install` 失败，网络超时或连接错误

**解决方案**:
```bash
# 使用安装脚本（自动处理网络问题）
python install_deps.py

# 禁用代理
unset HTTP_PROXY
unset HTTPS_PROXY
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 使用其他镜像源
# 阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

# 腾讯云镜像
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
```

### Q6: 服务启动后立即退出

**解决方案**:
```bash
# 查看日志文件
tail -n 50 logs/app.log

# 检查Python语法
python -m py_compile main.py

# 检查依赖是否完整
python -c "import fastapi, uvicorn, httpx; print('OK')"

# 前台运行查看详细错误
python main.py
```

### Q7: 无法访问机器人

**错误**: 机器人注册成功但无法获取状态

**解决方案**:
```bash
# 检查网络连接
ping <机器人IP>

# 检查机器人服务是否运行
curl http://<机器人IP>:1448/api/core/system/v1/robot/info

# 检查防火墙设置（Linux）
sudo ufw status
sudo ufw allow 8000/tcp  # 如果需要

# macOS 防火墙通常在"系统偏好设置"中配置
```

---

## 下一步

### 1. 注册机器人

1. 访问 http://localhost:8000
2. 点击 "机器人管理"
3. 注册你的机器人

### 2. 加载地图

1. 访问 http://localhost:8000/map-management
2. 从机器人加载地图
3. 设置默认地图

### 3. 创建任务

1. 访问 http://localhost:8000
2. 在左侧面板选择POI点或输入坐标
3. 点击 "创建任务"
4. 观察机器人执行任务

### 4. 查看文档

- **API文档**: http://localhost:8000/docs
- **技术文档**: 查看 `docs/` 目录
- **死锁验证指南**: `docs/DEADLOCK_VERIFICATION_GUIDE.md`

---

## 快速命令参考

```bash
# 进入项目目录
cd ~/schedule-system-based-on-REST

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
python install_deps.py

# 启动服务
python main.py

# 停止服务
lsof -ti:8000 | xargs kill

# 查看日志
tail -f logs/app.log

# 查看死锁日志
tail -f logs/deadlock.log

# 检查服务状态
lsof -i :8000
```

---

## 获取帮助

- **GitHub Issues**: https://github.com/carl0820/schedule-system-based-on-REST/issues
- **查看日志**: `logs/app.log` 和 `logs/deadlock.log`
- **API文档**: http://localhost:8000/docs

---

**祝使用愉快！** 🚀

