# 多机器人调度系统 - 快速部署指南

## 📋 目录

1. [系统要求](#系统要求)
2. [快速开始（5分钟）](#快速开始5分钟)
3. [详细安装步骤](#详细安装步骤)
4. [配置说明](#配置说明)
5. [启动服务](#启动服务)
6. [验证安装](#验证安装)
7. [常见问题](#常见问题)
8. [下一步](#下一步)

---

## 系统要求

### 最低配置（1-4台机器人）
- **操作系统**: Windows 10/11 (64位)
- **CPU**: 2核心，2.0 GHz
- **内存**: 4 GB RAM
- **存储**: 1 GB 可用空间
- **网络**: 100 Mbps（与机器人网络连通）

### 推荐配置（4-8台机器人）
- **操作系统**: Windows 10/11 (64位)
- **CPU**: 4核心，2.5 GHz 或更高
- **内存**: 8 GB RAM
- **存储**: 2 GB 可用空间
- **网络**: 1 Gbps（与机器人网络连通）

### 软件要求
- **Python**: 3.8 - 3.13（推荐 3.11 或 3.12）
- **Git**: 可选（用于从GitHub克隆代码）

---

## 快速开始（5分钟）

### 步骤1: 下载代码

**方法1: 从GitHub下载（推荐）**

1. 访问: https://github.com/carl0820/schedule-system-based-on-REST
2. 点击 "Code" → "Download ZIP"
3. 解压到本地目录（例如: `D:\chatbot`）

**方法2: 使用Git克隆**

```powershell
git clone https://github.com/carl0820/schedule-system-based-on-REST.git
cd schedule-system-based-on-REST
```

### 步骤2: 安装Python依赖

打开PowerShell，进入项目目录：

```powershell
cd D:\chatbot  # 替换为你的项目路径

# 方法1: 使用安装脚本（推荐，自动处理网络问题）
.\install_deps_simple.ps1

# 方法2: 使用Python脚本（跨平台）
python install_deps.py

# 方法3: 手动安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 步骤3: 启动服务

```powershell
# 使用启动脚本（推荐）
.\start_service.ps1

# 或直接运行
python main.py
```

### 步骤4: 访问系统

打开浏览器访问：
- **首页**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

---

## 详细安装步骤

### 1. 检查Python版本

打开PowerShell，运行：

```powershell
python --version
```

**要求**: Python 3.8 - 3.13

**如果没有Python**:
1. 访问 https://www.python.org/downloads/
2. 下载并安装Python 3.11或3.12
3. **重要**: 安装时勾选 "Add Python to PATH"

### 2. 准备项目目录

```powershell
# 创建项目目录（如果还没有）
mkdir D:\chatbot
cd D:\chatbot

# 将代码解压到此目录
# 或使用Git克隆
git clone https://github.com/carl0820/schedule-system-based-on-REST.git .
```

### 3. 安装依赖

#### 方法1: 使用安装脚本（推荐）

```powershell
# 运行安装脚本（自动处理网络问题和镜像源）
.\install_deps_simple.ps1
```

#### 方法2: 使用Python脚本

```powershell
# 运行Python安装脚本
python install_deps.py
```

#### 方法3: 手动安装

```powershell
# 使用清华镜像源（国内推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果遇到网络问题，禁用代理
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

#### 方法4: 使用虚拟环境（推荐用于生产环境）

```powershell
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 验证安装

```powershell
# 检查关键依赖是否安装成功
python -c "import fastapi, uvicorn, httpx; print('依赖安装成功！')"
```

如果看到 "依赖安装成功！"，说明安装完成。

---

## 配置说明

### 基本配置（可选）

系统有默认配置，通常**无需修改**即可使用。如需自定义，可以：

1. **创建 `.env` 文件**（可选）

```powershell
# 在项目根目录创建 .env 文件
# 复制以下内容并根据需要修改

APP_NAME=多机器人调度系统
APP_VERSION=1.3.0
DEBUG=False

# 服务器配置
HOST=0.0.0.0
PORT=8000

# 数据库配置（可选，当前版本未使用）
REDIS_HOST=localhost
REDIS_PORT=6379
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 机器人配置

机器人配置通过Web界面进行，无需手动编辑配置文件。

1. 启动服务后，访问 http://localhost:8000
2. 点击 "机器人管理"
3. 点击 "注册机器人"
4. 输入机器人ID和IP地址（例如: `robot1`, `http://10.160.128.91:1448`）

---

## 启动服务

### 方法1: 使用启动脚本（推荐）

```powershell
# 启动服务（后台运行）
.\start_service.ps1

# 查看服务状态
Get-Process -Name python | Where-Object { $_.CommandLine -like "*uvicorn*" }
```

### 方法2: 直接运行

```powershell
# 前台运行（可以看到日志）
python main.py
```

### 方法3: 使用uvicorn

```powershell
# 开发模式（自动重载）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 停止服务

```powershell
# 使用停止脚本
.\stop_service.ps1

# 或手动停止
# 找到Python进程并结束
Get-Process -Name python | Stop-Process
```

### 重启服务

```powershell
# 使用重启脚本（推荐）
.\restart_service_simple.ps1
```

---

## 验证安装

### 1. 检查服务是否运行

打开浏览器访问：
- http://localhost:8000/health

应该看到：
```json
{
  "status": "healthy",
  "version": "1.3.0"
}
```

### 2. 检查API文档

访问：
- http://localhost:8000/docs

应该看到Swagger UI界面，可以测试API。

### 3. 检查Web界面

访问：
- http://localhost:8000

应该看到系统首页，包含：
- 系统状态
- 地图可视化
- 导航菜单

### 4. 注册机器人测试

1. 访问 http://localhost:8000
2. 点击 "机器人管理"
3. 点击 "注册机器人"
4. 输入：
   - 机器人ID: `robot1`
   - IP地址: `http://你的机器人IP:1448`
5. 点击 "注册"
6. 检查机器人是否出现在列表中

---

## 常见问题

### Q1: Python未找到

**错误**: `python: 无法将"python"项识别为 cmdlet、函数、脚本文件或可运行程序`

**解决方案**:
1. 确认已安装Python
2. 检查Python是否添加到PATH:
   ```powershell
   python --version
   ```
3. 如果未添加，重新安装Python并勾选 "Add Python to PATH"
4. 或使用完整路径: `C:\Python311\python.exe`

### Q2: 依赖安装失败

**错误**: `pip install` 失败，网络超时或连接错误

**解决方案**:
1. 使用安装脚本（自动处理网络问题）:
   ```powershell
   .\install_deps_simple.ps1
   ```
2. 禁用代理:
   ```powershell
   $env:HTTP_PROXY=""
   $env:HTTPS_PROXY=""
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
3. 使用其他镜像源:
   ```powershell
   # 阿里云镜像
   pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
   
   # 腾讯云镜像
   pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
   ```

### Q3: 端口被占用

**错误**: `Address already in use` 或 `端口已被使用`

**解决方案**:
1. 查找占用端口的进程:
   ```powershell
   netstat -ano | findstr :8000
   ```
2. 结束进程:
   ```powershell
   taskkill /PID <进程ID> /F
   ```
3. 或修改端口（在 `config.py` 或 `.env` 中）:
   ```python
   PORT = 8001  # 改为其他端口
   ```

### Q4: 无法访问机器人

**错误**: 机器人注册成功但无法获取状态

**解决方案**:
1. 检查网络连接:
   ```powershell
   ping <机器人IP>
   ```
2. 检查机器人服务是否运行:
   - 访问 `http://<机器人IP>:1448/api/core/system/v1/robot/info`
   - 应该返回机器人信息
3. 检查防火墙设置:
   - 确保Windows防火墙允许Python访问网络
   - 或临时关闭防火墙测试

### Q5: 服务启动后立即退出

**解决方案**:
1. 查看日志文件:
   ```powershell
   Get-Content logs\app.log -Tail 50
   ```
2. 检查Python语法:
   ```powershell
   python -m py_compile main.py
   ```
3. 检查依赖是否完整:
   ```powershell
   python -c "import fastapi, uvicorn, httpx; print('OK')"
   ```

### Q6: 地图不显示

**解决方案**:
1. 确保至少注册了一台机器人
2. 确保机器人处于在线状态
3. 在地图管理页面加载地图:
   - 访问 http://localhost:8000/map-management
   - 点击 "从机器人加载地图"
   - 选择机器人并加载

### Q7: 死锁检测不工作

**解决方案**:
1. 检查死锁日志:
   ```powershell
   Get-Content logs\deadlock.log -Tail 50
   ```
2. 确保有执行中的任务（死锁检测只在有任务时启动）
3. 检查死锁配置:
   - 访问 http://localhost:8000/deadlock-config
   - 查看配置参数是否正确

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

```powershell
# 进入项目目录
cd D:\chatbot

# 安装依赖
.\install_deps_simple.ps1

# 启动服务
.\start_service.ps1

# 停止服务
.\stop_service.ps1

# 重启服务
.\restart_service_simple.ps1

# 查看日志
Get-Content logs\app.log -Tail 50

# 查看死锁日志
Get-Content logs\deadlock.log -Tail 50

# 检查服务状态
Get-Process -Name python | Where-Object { $_.CommandLine -like "*uvicorn*" }
```

---

## 获取帮助

- **GitHub Issues**: https://github.com/carl0820/schedule-system-based-on-REST/issues
- **查看日志**: `logs/app.log` 和 `logs/deadlock.log`
- **API文档**: http://localhost:8000/docs

---

## 版本信息

- **当前版本**: v1.3.0
- **发布日期**: 2025-11-17
- **Python要求**: 3.8 - 3.13
- **系统要求**: Windows 10/11

---

**祝使用愉快！** 🚀

