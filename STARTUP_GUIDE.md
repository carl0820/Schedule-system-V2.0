# 🚀 服务启动指南

本文档提供了Windows环境下启动机器人调度系统服务的所有方法和故障排除指南。

---

## 📋 快速选择

| 场景 | 推荐脚本 | 说明 |
|------|---------|------|
| **首次启动** | `start_safe.ps1` | 最安全，自动处理端口冲突 |
| **日常使用** | `restart_service.ps1` | 自动停止旧服务并启动新服务 |
| **遇到问题** | `diagnose.ps1` → `start_safe.ps1` | 先诊断，再启动 |
| **快速启动** | `start_service.ps1` | 适合确定端口空闲时 |
| **智能启动** | `start.ps1` | 自动检测Python和端口 |

---

## 🛠️ 启动脚本详解

### 1. start_safe.ps1 ⭐ 推荐首选

**适用场景**：首次启动、端口被占用、启动失败

**特点**：
- ✅ 自动检测并终止占用端口的进程（最多3次重试）
- ✅ 确保端口完全释放（2秒等待）
- ✅ 验证Python 3.13安装
- ✅ 无需手动干预

**使用方法**：
```powershell
.\start_safe.ps1
```

**输出示例**：
```
============================================================
Robot Scheduler - Safe Startup
============================================================

[STEP 1/3] Checking for conflicting processes...
[WARN] Port 8092 is in use (attempt 1/3)
  Stopping process: python (PID: 12345)
[OK] Port 8092 is available

[STEP 2/3] Verifying Python installation...
[OK] Found Python: Python 3.13.7

[STEP 3/3] Starting service...
```

---

### 2. restart_service.ps1 ⭐ 日常使用

**适用场景**：更新代码后重启、日常维护

**特点**：
- ✅ 自动停止现有服务
- ✅ 3秒等待确保端口释放
- ✅ 最终端口验证
- ✅ 前台运行，实时查看日志

**使用方法**：
```powershell
.\restart_service.ps1
```

**工作流程**：
```
[1/2] Stopping existing service...
Found running service processes: 12345
[OK] Stopped process 12345
[OK] Stopped 1 processes

Ensuring port is fully released...
(等待3秒)

[2/2] Starting new service...
Service will start on: http://localhost:8092
```

---

### 3. diagnose.ps1 🔍 诊断工具

**适用场景**：启动失败、端口问题、故障排查

**功能**：
- 🔍 检查端口8092使用情况
- 🔍 查找Python进程
- 🔍 测试端口绑定能力
- 🔍 检查防火墙规则
- 🔍 验证Python安装

**使用方法**：
```powershell
.\diagnose.ps1
```

**输出示例**：
```
============================================================
Port 8092 Diagnostic Tool
============================================================

[TEST 1] Checking if port 8092 is currently in use...
[ISSUE FOUND] Port 8092 is currently in use!

Processes using port 8092:
  - PID: 12345
    Name: python
    Path: C:\...\python.exe
    State: Established

SOLUTION: Run the following command to stop these processes:
  Stop-Process -Id 12345 -Force

[TEST 2] Checking for running Python processes...
[INFO] Found 1 Python process(es):
  - PID: 12345, Name: python, Start: 2025-12-29 19:00:00

[TEST 3] Testing if we can bind to port 8092...
[ISSUE FOUND] Cannot bind to port 8092!
Error: Address already in use

[TEST 4] Checking Windows Firewall rules for port 8092...
[INFO] No specific firewall rules found for port 8092

[TEST 5] Verifying Python installation...
[OK] Python found at: C:\Users\...\Python313\python.exe
     Version: Python 3.13.7
```

---

### 4. start.ps1 - 智能启动

**适用场景**：不确定Python路径、需要自动检测

**特点**：
- 🔍 自动检测Python环境
- ✅ 检查端口可用性
- ❓ 询问是否停止冲突进程
- 📊 显示详细启动信息

**使用方法**：
```powershell
.\start.ps1
```

---

### 5. start_service.ps1 - 快速启动

**适用场景**：确定端口空闲、快速测试

**特点**：
- ⚡ 最快速启动
- 🎯 使用固定Python 3.13路径
- 🚫 无端口检查（需手动确认）

**使用方法**：
```powershell
.\start_service.ps1
```

---

## 🐛 常见问题和解决方案

### 问题1: 端口8092被占用

**错误信息**：
```
ERROR: [Errno 13] error while attempting to bind on address ('0.0.0.0', 8092)
```

**解决方案**：
```powershell
# 方案1：使用诊断工具（推荐）
.\diagnose.ps1

# 方案2：使用安全启动
.\start_safe.ps1

# 方案3：手动停止进程
Get-NetTCPConnection -LocalPort 8092 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }

# 等待30秒后重试
Start-Sleep -Seconds 30
.\start_service.ps1
```

---

### 问题2: 显示乱码/繁体字

**错误显示**：
```
浣跨敤 Python 3.13 鍚姩鏈嶅姟...
```

**解决方案**：
所有脚本已更新为纯英文版本，直接使用新脚本即可：
```powershell
.\start_safe.ps1  # 纯英文界面
```

---

### 问题3: Python未找到

**错误信息**：
```
[ERROR] Python 3.13 not found
```

**解决方案**：
```powershell
# 检查Python安装
where python
python --version

# 如果Python已安装但路径不对，使用智能启动
.\start.ps1  # 自动检测Python路径

# 或手动修改脚本中的Python路径
# 编辑 start_service.ps1 第4行
$pythonPath = "你的Python路径\python.exe"
```

---

### 问题4: 服务启动后立即崩溃

**解决方案**：
```powershell
# 1. 检查日志
Get-Content logs\app.log -Tail 50

# 2. 检查依赖
python -m pip list

# 3. 重新安装依赖
python install_deps.py
```

---

### 问题5: 防火墙阻止

**症状**：服务启动成功但无法访问

**解决方案**：
```powershell
# 允许端口8092通过防火墙
New-NetFirewallRule -DisplayName "Robot Scheduler" -Direction Inbound -Protocol TCP -LocalPort 8092 -Action Allow

# 或者关闭防火墙（不推荐）
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
```

---

## 📊 推荐工作流

### 首次部署
```powershell
# 1. 诊断环境
.\diagnose.ps1

# 2. 安全启动
.\start_safe.ps1

# 3. 验证服务
# 打开浏览器访问: http://localhost:8092
```

### 日常开发
```powershell
# 更新代码后重启
git pull
.\restart_service.ps1
```

### 遇到问题
```powershell
# 1. 诊断
.\diagnose.ps1

# 2. 根据诊断结果修复

# 3. 安全启动
.\start_safe.ps1
```

---

## 🔧 高级用法

### 后台运行（不推荐）
```powershell
# 使用PowerShell后台任务
Start-Process powershell -ArgumentList "-File start_service.ps1" -WindowStyle Hidden
```

### 以管理员身份运行
```powershell
# 右键 PowerShell → 以管理员身份运行
# 然后执行启动脚本
.\start_safe.ps1
```

### 查看实时日志
```powershell
# 启动服务
.\restart_service.ps1

# 另开终端监控日志
Get-Content logs\app.log -Wait -Tail 20
```

---

## 📞 获取帮助

如果以上方法都无法解决问题：

1. **查看完整日志**：
   ```powershell
   Get-Content logs\app.log
   ```

2. **收集诊断信息**：
   ```powershell
   .\diagnose.ps1 > diagnostic_report.txt
   ```

3. **提交Issue**：将 `diagnostic_report.txt` 和错误截图发送给开发团队

---

## 📝 脚本对比表

| 脚本 | 端口检查 | 自动停止 | 等待时间 | Python检测 | 适用场景 |
|------|---------|---------|---------|-----------|---------|
| **start_safe.ps1** | ✅ (3次重试) | ✅ | 2秒 | ✅ | 首次启动/有问题 |
| **restart_service.ps1** | ✅ | ✅ | 3秒 | ✅ | 日常重启 |
| **diagnose.ps1** | ✅ | ❌ | - | ✅ | 诊断问题 |
| **start.ps1** | ✅ | ❓ (询问) | 2秒 | ✅ | 自动检测 |
| **start_service.ps1** | ❌ | ❌ | 0秒 | ❌ | 快速启动 |

---

## 🎯 总结

- **90%场景**: 使用 `restart_service.ps1`
- **遇到问题**: 使用 `diagnose.ps1` + `start_safe.ps1`
- **首次部署**: 使用 `start_safe.ps1`
- **快速测试**: 使用 `start_service.ps1`

祝你使用愉快！ 🎉
