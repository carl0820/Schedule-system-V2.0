# Windows 快速部署指南（无需Docker）

> 适用于没有安装Docker的Windows 10/11环境，5-10分钟完成部署

## 📋 前提条件

- **操作系统**: Windows 10 或 Windows 11
- **Python**: 3.8 - 3.13（推荐 3.11 或 3.12）
- **内存**: 4GB+ RAM（推荐 8GB+）
- **网络**: 与机器人在同一网络或可访问机器人IP

## 🚀 快速部署步骤

### 步骤一：检查Python环境

打开PowerShell或命令提示符（CMD），检查Python版本：

```powershell
python --version
```

**预期输出**：
```
Python 3.11.x
```

**⚠️ 重要：多Python环境检查**

如果你的系统安装了多个Python（如MSYS2、Anaconda、Python.org等），请检查所有Python位置：

```powershell
# 查找所有Python安装
where python

# 示例输出可能包含：
# C:\msys64\ucrt64\bin\python.exe          ❌ MSYS2 Python（通常没有pip）
# C:\Users\用户名\AppData\Local\Programs\Python\Python313\python.exe  ✅ 官方Python
# C:\Users\用户名\AppData\Local\Microsoft\WindowsApps\python.exe      ⚠️ Windows商店占位符
```

**如何选择正确的Python：**

1. **检查是否有pip**：
   ```powershell
   python -m pip --version
   ```
   如果显示 "No module named pip"，说明当前Python不可用。

2. **使用完整路径测试**：
   ```powershell
   # 测试官方Python 3.13
   C:\Users\<用户名>\AppData\Local\Programs\Python\Python313\python.exe --version
   C:\Users\<用户名>\AppData\Local\Programs\Python\Python313\python.exe -m pip --version
   ```

3. **如果没有合适的Python，请安装官方版本**：

**下载地址**: https://www.python.org/downloads/

**安装注意事项**：
- ✅ 勾选 "Add Python to PATH"（重要！）
- ✅ 选择 "Install Now" 或自定义安装路径
- ✅ 安装完成后重新打开PowerShell
- ✅ 确保新安装的Python在PATH的最前面

### 步骤二：下载代码

**方法1：下载ZIP（推荐，无需Git）**

1. 访问：https://github.com/carl0820/Schedule-system-V2.0
2. 点击绿色的 "Code" 按钮
3. 选择 "Download ZIP"
4. 解压到任意目录，例如：`D:\chatbot`

**方法2：使用Git克隆（需要先安装Git）**

```powershell
# 克隆代码
git clone https://github.com/carl0820/Schedule-system-V2.0.git

# 进入项目目录
cd Schedule-system-V2.0
```

### 步骤三：安装依赖

打开PowerShell，进入项目目录：

```powershell
# 进入项目目录（根据你的实际路径修改）
cd D:\chatbot
```

**方法1：使用自动安装脚本（推荐）**

```powershell
# 运行Python安装脚本
python install_deps.py
```

脚本会自动：
- ✅ 检测可用的Python版本
- ✅ 使用清华镜像源加速下载
- ✅ 自动处理网络问题
- ✅ 安装所有必需依赖

**方法2：使用PowerShell脚本**

```powershell
# 允许运行脚本（首次需要）
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 运行安装脚本
.\install_deps_simple.ps1
```

**方法3：手动安装（如果脚本失败）**

```powershell
# 使用清华镜像源安装（国内推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用阿里云镜像源
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**如果遇到网络问题**：

```powershell
# 禁用代理
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""

# 再次安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 步骤四：启动服务

**方法1：智能启动脚本（强烈推荐）**

```powershell
# 双击运行 start.bat
# 或在PowerShell中执行
.\start.bat
# 或
.\start.ps1
```

**智能脚本特性**：
- ✅ 自动检测并选择正确的Python（支持多Python环境）
- ✅ 自动排除MSYS2、Cygwin等不适合的Python
- ✅ 自动检查依赖是否安装
- ✅ 友好的错误提示和解决建议
- ✅ 适用于任何Windows电脑，无需修改配置

**方法2：一键部署脚本（首次部署推荐）**

```powershell
# 自动检测Python、安装依赖、启动服务
.\deploy.bat
# 或
.\deploy.ps1
```

这个脚本会自动完成：
1. 检测Python环境
2. 安装所有依赖
3. 启动服务

**方法3：使用原始脚本**

```powershell
.\start_service.ps1
```

**方法4：直接运行Python（需要python命令可用）**

```powershell
python main.py
```

**方法5：使用uvicorn（开发模式，支持热重载）**

```powershell
uvicorn main:app --host 0.0.0.0 --port 8092 --reload
```

**成功启动的标志**：

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8092
```

### 步骤五：访问系统

打开浏览器，访问以下地址：

| 功能 | 地址 | 说明 |
|------|------|------|
| 主页面 | http://localhost:8092 | 可视化界面 |
| 机器人管理 | http://localhost:8092/static/robot_list.html | 注册和管理机器人 |
| 任务管理 | http://localhost:8092/static/task_list.html | 查看任务列表 |
| 地图管理 | http://localhost:8092/static/map_management.html | 地图配置 |
| API文档 | http://localhost:8092/docs | 交互式API文档 |
| 健康检查 | http://localhost:8092/health | 检查服务状态 |

### 步骤六：注册机器人

1. 访问：http://localhost:8092/static/robot_list.html
2. 点击"注册机器人"
3. 输入机器人信息：
   - **机器人ID**：例如 `Apollo`、`P3`
   - **机器人IP地址**：例如 `10.160.129.149`
   - **端口**：默认 `1448`（思岚机器人默认端口）
4. 点击"注册"

**示例**：
```
机器人ID: Apollo
IP地址: 10.160.129.149
端口: 1448
```

系统会自动从机器人获取地图和POI信息。

## ✅ 完成！

现在你可以：
1. ✅ 在主页面查看机器人实时位置
2. ✅ 创建任务（单动作或多动作）
3. ✅ 监控任务执行状态
4. ✅ 配置死锁检测和限行区域

## 🔧 常用操作

### 停止服务

在运行服务的PowerShell窗口中按 `Ctrl + C`

### 重启服务

```powershell
# 停止服务（Ctrl + C）
# 然后重新启动
.\start_service.ps1
```

### 查看日志

```powershell
# 查看实时日志
Get-Content logs\chatbot_service.log -Tail 50 -Wait

# 查看最后100行日志
Get-Content logs\chatbot_service.log -Tail 100
```

### 清空数据（重新开始）

```powershell
# 停止服务后删除数据库
Remove-Item data\tasks.db
Remove-Item data\robots.json

# 重新启动服务
.\start_service.ps1
```

### 更新代码

**使用Git更新**：
```powershell
# 停止服务（Ctrl + C）

# 拉取最新代码
git pull

# 更新依赖（如果requirements.txt有变化）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 重新启动
.\start_service.ps1
```

**手动更新**：
1. 备份 `data` 文件夹（包含数据库）
2. 从GitHub下载最新ZIP
3. 解压并覆盖旧文件（保留data文件夹）
4. 重新安装依赖
5. 启动服务

## 🐛 常见问题

### 1. 端口8092被占用

**错误信息**：
```
ERROR:    [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8092)
```

**解决方法**：

```powershell
# 查找占用端口的进程
netstat -ano | findstr :8092

# 找到PID后，在任务管理器中结束该进程
# 或使用命令（替换<PID>为实际进程ID）
taskkill /PID <PID> /F

# 或修改端口（编辑 main.py 中的 PORT 变量）
```

### 2. Python未找到或pip不可用

**错误信息**：
```
'python' 不是内部或外部命令
```
或
```
No module named pip
```

**解决方法**：

**情况1：系统有多个Python（MSYS2、Anaconda等）**

这是最常见的问题！使用 `where python` 检查所有Python位置：

```powershell
where python

# 可能的输出：
# C:\msys64\ucrt64\bin\python.exe                    ❌ MSYS2（无pip）
# C:\Users\用户名\AppData\Local\Programs\Python\Python313\python.exe  ✅ 官方Python
```

**解决方案**：

1. **方法1：使用完整路径（最可靠）**
   ```powershell
   # 使用官方Python的完整路径
   C:\Users\用户名\AppData\Local\Programs\Python\Python313\python.exe main.py

   # 或使用提供的启动脚本（已配置正确路径）
   .\start.ps1
   ```

2. **方法2：修改PATH环境变量**
   - 系统属性 → 环境变量 → Path
   - 将官方Python路径移到最前面
   - 删除或移除MSYS2/Anaconda的Python路径
   - 重启PowerShell

3. **方法3：创建Python别名**
   ```powershell
   # 在PowerShell配置文件中添加
   Set-Alias python3 "C:\Users\用户名\AppData\Local\Programs\Python\Python313\python.exe"

   # 然后使用
   python3 main.py
   ```

**情况2：Python确实未安装**

1. 下载安装：https://www.python.org/downloads/
2. ✅ 勾选 "Add Python to PATH"
3. 安装后重启PowerShell

### 3. pip安装依赖失败

**常见原因及解决方法**：

**问题1：网络超时**
```powershell
# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**问题2：代理问题**
```powershell
# 禁用代理
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""

# 再次安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**问题3：某些包需要编译（如pydantic-core、numpy）**

错误示例：
```
Rust not found
Compiler c++ cannot compile programs
```

**解决方案**：

1. **升级pip到最新版本**（支持更多预编译wheel）：
   ```powershell
   python -m pip install --upgrade pip
   ```

2. **只安装预编译的二进制包**：
   ```powershell
   pip install -r requirements.txt --only-binary=:all: -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

3. **跳过可选依赖**（numpy是可选的）：
   ```powershell
   # 先安装核心依赖
   pip install fastapi uvicorn httpx pydantic requests -i https://pypi.tuna.tsinghua.edu.cn/simple

   # numpy失败可以忽略（可选依赖）
   pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple || echo "numpy安装失败（可选依赖，可忽略）"
   ```

4. **使用我们提供的修复脚本**：
   ```powershell
   python fix_install_windows.ps1
   ```

**问题4：权限问题**
```powershell
# 以管理员身份运行PowerShell
# 或使用用户安装
pip install --user -r requirements.txt
```

### 4. 无法访问机器人

**检查步骤**：

1. **确认网络连通性**：
```powershell
# 测试机器人IP是否可达
ping 10.160.129.149

# 测试机器人端口是否开放
Test-NetConnection -ComputerName 10.160.129.149 -Port 1448
```

2. **确认机器人服务运行**：
   - 访问机器人Web界面（浏览器打开 `http://机器人IP:1448`）

3. **检查防火墙**：
   - Windows防火墙可能阻止连接
   - 临时关闭防火墙测试

4. **VPN连接**：
   - 如果机器人在VPN网络，确保已连接VPN
   - 确认VPN配置允许访问机器人网段

### 5. 服务启动后立即退出

**查看错误日志**：
```powershell
# 查看日志文件
Get-Content logs\chatbot_service.log -Tail 50
```

**常见原因**：
- 依赖未正确安装
- Python版本不兼容
- 配置文件错误

**解决方法**：
1. 确认所有依赖已安装：`pip list`
2. 检查Python版本：`python --version`（应为3.8-3.13）
3. 查看详细错误信息并根据提示修复

### 6. 任务创建后不执行

**检查步骤**：

1. **确认机器人在线**：
   - 访问 http://localhost:8092/static/robot_list.html
   - 查看机器人状态是否为"在线"

2. **查看任务状态**：
   - 访问 http://localhost:8092/static/task_list.html
   - 查看任务状态和错误信息

3. **检查日志**：
```powershell
# 查看任务执行日志
Get-Content logs\chatbot_service.log -Tail 100 | Select-String "task|error"
```

## 📊 系统监控

### 查看系统状态

访问：http://localhost:8092/api/system/status

```json
{
  "status": "running",
  "robots": 3,
  "active_tasks": 2,
  "pending_tasks": 5,
  "uptime": "2h 30m"
}
```

### 监控任务执行

访问：http://localhost:8092/static/task_list.html

实时查看：
- ✅ 任务状态（等待中、执行中、已完成、失败）
- ✅ 任务进度
- ✅ 执行时间
- ✅ 错误信息

## 🔐 安全建议

### 生产环境部署

如果用于生产环境，建议：

1. **配置防火墙**：
```powershell
# 允许8092端口访问
New-NetFirewallRule -DisplayName "Robot Scheduler" -Direction Inbound -LocalPort 8092 -Protocol TCP -Action Allow
```

2. **启用用户认证**：
   - 系统默认已集成用户登录功能
   - 访问任何页面时会自动跳转到登录页

3. **定期备份数据**：
```powershell
# 备份数据库和配置
$date = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item data\tasks.db "backups\tasks_$date.db"
Copy-Item data\robots.json "backups\robots_$date.json"
```

4. **设置开机自启动**：
   - 使用Windows任务计划程序
   - 创建启动任务执行 `start_service.ps1`

## 📚 进阶配置

### 配置文件说明

系统配置文件位于 `data/runtime_config.json`，包含：

- **死锁检测参数**：检测间隔、超时时间
- **碰撞检测参数**：安全距离、时间窗口
- **避让策略参数**：优先级计算、等待时间
- **限行区域配置**：等待点设置

### API使用示例

**注册机器人**：
```powershell
curl -X POST "http://localhost:8092/api/robots/register?robot_id=Apollo&base_url=http://10.160.129.149:1448"
```

**创建任务**：
```powershell
curl -X POST "http://localhost:8092/api/tasks/" `
  -H "Content-Type: application/json" `
  -d '{"target_poi":"P01","priority":5}'
```

**查询任务状态**：
```powershell
curl "http://localhost:8092/api/tasks/{task_id}"
```

详细API文档：http://localhost:8092/docs

## 🆘 获取帮助

- **GitHub Issues**: https://github.com/carl0820/Schedule-system-V2.0/issues
- **API文档**: http://localhost:8092/docs
- **详细文档**: `docs/` 目录下的其他文档

## 📝 快速参考卡

```
启动服务:     .\start_service.ps1
停止服务:     Ctrl + C
主页面:       http://localhost:8092
机器人管理:   http://localhost:8092/static/robot_list.html
任务管理:     http://localhost:8092/static/task_list.html
API文档:      http://localhost:8092/docs
查看日志:     Get-Content logs\chatbot_service.log -Tail 50 -Wait
更新代码:     git pull
```

---

**部署时间**: 约5-10分钟
**系统要求**: Windows 10/11 + Python 3.8-3.13 + 4GB RAM
**推荐配置**: Windows 11 + Python 3.11 + 8GB RAM

🎉 祝你使用愉快！
