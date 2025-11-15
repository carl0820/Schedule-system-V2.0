# PowerShell API 使用指南

本文档说明如何在 Windows PowerShell 中正确调用 API。

## 问题说明

在 PowerShell 中，`&` 符号是保留字符，用于后台执行命令。因此，在 URL 中包含 `&` 时需要使用引号包裹，或者使用 PowerShell 的 `Invoke-WebRequest` 或 `Invoke-RestMethod` 命令。

## 方法一：使用 Invoke-RestMethod（推荐）

### 注册机器人

```powershell
# 方法1：使用查询参数
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91" -Method POST

# 方法2：使用完整URL（包含协议和端口）
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=http://10.160.128.91:1448" -Method POST

# 方法3：只输入IP地址（API会自动添加协议和端口）
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91" -Method POST
```

### 获取机器人列表

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/" -Method GET
```

### 获取机器人状态

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/robot1/state" -Method GET
```

### 获取机器人位置

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/robot1/pose" -Method GET
```

### 注销机器人

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/robot1" -Method DELETE
```

### 创建任务

```powershell
$body = @{
    target_pose = @{
        x = 5.0
        y = 3.0
        yaw = 0.0
    }
    priority = 2
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/tasks/" -Method POST -Body $body -ContentType "application/json"
```

### 加载地图

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/maps/load?robot_id=robot1" -Method POST
```

## 方法二：使用 curl（需要安装 curl）

如果系统已安装 curl，也可以使用：

```powershell
# 注册机器人
curl -X POST "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91"

# 获取机器人状态
curl "http://localhost:8000/api/robots/robot1/state"
```

## 方法三：使用引号包裹整个URL

```powershell
# 使用单引号包裹整个URL（推荐）
Invoke-RestMethod -Uri 'http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91' -Method POST

# 或使用双引号，但需要转义内部的双引号
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91" -Method POST
```

## API 改进说明

### URL 自动补全

现在 API 支持自动补全 URL 格式：

- **输入**: `10.160.128.91`
- **自动补全为**: `http://10.160.128.91:1448`

- **输入**: `http://10.160.128.91`
- **自动补全为**: `http://10.160.128.91:1448`

- **输入**: `10.160.128.91:1448`
- **自动补全为**: `http://10.160.128.91:1448`

### 错误处理改进

API 现在会返回更清晰的错误信息：

- **400**: 请求格式错误或机器人无法连接
- **404**: 机器人不存在
- **409**: 机器人已注册
- **500**: 服务器内部错误

## 常见问题

### 1. 错误：不允许使用与号(&)

**问题**: PowerShell 报错 "不允许使用与号(&)"

**解决**: 使用 `Invoke-RestMethod` 或 `Invoke-WebRequest` 命令，而不是直接输入 URL

### 2. 错误：机器人注册失败

**错误信息示例**:
- `Cannot connect to robot at http://10.160.128.91:1448. Please check if the robot is running and accessible.`
  - **原因**: 无法连接到机器人（连接被拒绝）
  - **解决**: 
    - 检查机器人 IP 地址是否正确
    - 确认机器人服务正在运行
    - 检查网络连接和防火墙设置
    - 尝试在浏览器中访问 `http://10.160.128.91:1448/api/core/slam/v1/localization/pose`

- `Connection timeout when connecting to http://10.160.128.91:1448. The robot may be unreachable or slow to respond.`
  - **原因**: 连接超时（10秒内无响应）
  - **解决**: 
    - 检查网络连接
    - 确认机器人服务正在运行
    - 检查防火墙是否阻止了连接
    - 尝试 ping 机器人 IP 地址

- `HTTP error 404 when connecting to http://10.160.128.91:1448. The robot API may not be available.`
  - **原因**: HTTP 错误（API 端点不存在）
  - **解决**: 
    - 检查机器人 API 版本是否正确
    - 确认机器人服务已正确启动
    - 检查 API 端点路径是否正确

**通用解决步骤**:
1. 检查机器人 IP 地址是否正确
2. 确认机器人服务正在运行
3. 尝试在浏览器中访问机器人 API 端点
4. 检查网络连接和防火墙设置

### 3. 错误：机器人已注册

**解决**: 先注销机器人，再重新注册：

```powershell
# 注销机器人
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/robot1" -Method DELETE

# 重新注册
Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91" -Method POST
```

## 完整示例

```powershell
# 1. 注册机器人
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=10.160.128.91" -Method POST
Write-Host "注册结果: $($response | ConvertTo-Json)"

# 2. 获取机器人列表
$robots = Invoke-RestMethod -Uri "http://localhost:8000/api/robots/" -Method GET
Write-Host "已注册的机器人: $robots"

# 3. 获取机器人状态
$state = Invoke-RestMethod -Uri "http://localhost:8000/api/robots/robot1/state" -Method GET
Write-Host "机器人状态: $($state | ConvertTo-Json)"

# 4. 加载地图
$map = Invoke-RestMethod -Uri "http://localhost:8000/api/maps/load?robot_id=robot1" -Method POST
Write-Host "地图加载结果: $($map | ConvertTo-Json)"
```

