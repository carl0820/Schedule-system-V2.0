# 服务重启指南

## 在 Windows PowerShell 中重启服务

### 方法一：使用重启脚本（推荐）

#### 完整版本（推荐）
```powershell
.\restart_service.ps1
```

或者指定端口：
```powershell
.\restart_service.ps1 -Port 8000
```

#### 简化版本（快速）
```powershell
.\restart_service_simple.ps1
```

### 方法二：手动重启

#### 1. 停止当前服务

**查找运行在端口 8000 的进程：**
```powershell
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
```

**停止进程（替换 PID 为实际进程ID）：**
```powershell
Stop-Process -Id <PID> -Force
```

**或者一行命令停止所有相关进程：**
```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
```

#### 2. 启动服务

**激活虚拟环境（如果使用）：**
```powershell
.\venv\Scripts\Activate.ps1
```

**启动服务：**
```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**或者后台运行：**
```powershell
Start-Process python -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"
```

### 方法三：使用 Python 脚本

创建并运行 `restart_service.py`：
```python
import subprocess
import time
import psutil

# 停止运行在端口 8000 的进程
for proc in psutil.process_iter(['pid', 'name']):
    try:
        for conn in proc.connections():
            if conn.laddr.port == 8000:
                proc.kill()
                print(f"已停止进程 PID: {proc.info['pid']}")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

time.sleep(2)

# 启动服务
subprocess.Popen(['python', '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'])
print("服务已启动")
```

## 验证服务是否正常运行

### 检查服务健康状态
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/health"
```

### 检查所有机器人健康状态（新功能）
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/robots/health" | Select-Object -ExpandProperty Content
```

### 查看 API 文档
在浏览器中打开：
```
http://localhost:8000/docs
```

## 新增功能：批量获取所有机器人健康状态

### API 端点
```
GET /api/robots/health
```

### 返回格式
```json
[
  {
    "robot_id": "robot1",
    "status": "idle",
    "online": true,
    "health": {
      "hasError": false,
      "hasFatal": false,
      "hasWarning": false,
      "hasSystemEmergencyStop": false,
      "hasLidarDisconnected": false,
      "hasDepthCameraDisconnected": false,
      "hasSdpDisconnected": false,
      "baseError": []
    },
    "last_update_time": "2024-01-01T12:00:00",
    "error": null
  },
  {
    "robot_id": "robot2",
    "status": "offline",
    "online": false,
    "health": null,
    "error": "Robot state not available"
  }
]
```

### 使用示例

**PowerShell:**
```powershell
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/robots/health"
$response | Format-Table robot_id, status, online
```

**curl:**
```bash
curl http://localhost:8000/api/robots/health
```

**Python:**
```python
import requests
response = requests.get("http://localhost:8000/api/robots/health")
robots_health = response.json()
for robot in robots_health:
    print(f"{robot['robot_id']}: {robot['status']} ({'在线' if robot['online'] else '离线'})")
```

## 常见问题

### 端口被占用
如果端口 8000 被占用，可以：
1. 使用其他端口：`python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload`
2. 修改 `config.py` 中的 `PORT` 设置
3. 停止占用端口的进程

### 权限问题
如果遇到权限问题，以管理员身份运行 PowerShell：
```powershell
# 右键 PowerShell，选择"以管理员身份运行"
```

### 服务无法启动
检查：
1. Python 环境是否正确
2. 依赖是否安装：`pip install -r requirements.txt`
3. 配置文件是否正确
4. 查看日志输出

