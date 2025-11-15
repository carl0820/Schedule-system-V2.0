# 地图加载指南

## 概述

系统支持从机器人加载地图数据。地图数据是二进制字节流格式，包含地图元数据和栅格数据。

## 地图加载方式

### 方式1：从机器人加载地图（推荐）

如果已经注册了机器人，可以从机器人加载地图：

#### 使用 API 加载

**PowerShell 示例：**
```powershell
# 1. 先注册机器人（如果还没有注册）
$body = @{
    robot_id = "robot_001"
    base_url = "http://10.160.128.91:1448"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/api/robots/" -Method POST -ContentType "application/json" -Body $body

# 2. 从机器人加载地图
Invoke-WebRequest -Uri "http://localhost:8000/api/maps/load?robot_id=robot_001" -Method POST
```

**curl 示例：**
```bash
# 1. 先注册机器人
curl -X POST "http://localhost:8000/api/robots/" \
  -H "Content-Type: application/json" \
  -d '{"robot_id": "robot_001", "base_url": "http://10.160.128.91:1448"}'

# 2. 从机器人加载地图
curl -X POST "http://localhost:8000/api/maps/load?robot_id=robot_001"
```

#### 自动加载

当访问 `/api/maps/info` 时，如果本地没有地图，系统会自动尝试从已注册的机器人加载地图：

```powershell
# 自动从第一个可用的机器人加载地图
Invoke-WebRequest -Uri "http://localhost:8000/api/maps/info"
```

### 方式2：从文件加载地图

如果已经有保存的地图文件（二进制格式），可以直接从文件加载：

**PowerShell 示例：**
```powershell
# 使用 multipart/form-data 上传文件
$filePath = "path/to/map.bin"
$fileBytes = [System.IO.File]::ReadAllBytes($filePath)
$boundary = [System.Guid]::NewGuid().ToString()
$fileName = [System.IO.Path]::GetFileName($filePath)

# 构建 multipart/form-data 请求体
$bodyLines = @(
    "--$boundary",
    "Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"",
    "Content-Type: application/octet-stream",
    "",
    [System.Text.Encoding]::Default.GetString($fileBytes),
    "--$boundary--"
)
$body = $bodyLines -join "`r`n"

# 发送请求
$headers = @{
    "Content-Type" = "multipart/form-data; boundary=$boundary"
}
Invoke-WebRequest -Uri "http://localhost:8000/api/maps/load-from-file" -Method POST -Headers $headers -Body ([System.Text.Encoding]::Default.GetBytes($body))
```

**使用 curl 示例：**
```bash
curl -X POST "http://localhost:8000/api/maps/load-from-file" \
  -F "file=@path/to/map.bin"
```

**使用 Python 示例：**
```python
import requests

with open("path/to/map.bin", "rb") as f:
    files = {"file": f}
    response = requests.post("http://localhost:8000/api/maps/load-from-file", files=files)
    print(response.json())
```

## 地图格式说明

地图数据是二进制字节流，格式如下：

- **前32字节**：元数据（低位字节在前）
  - 0-3字节：origin_x (float32)
  - 4-7字节：origin_y (float32)
  - 8-11字节：width (int32)
  - 12-15字节：height (int32)
  - 16-19字节：resolution (float32)
  - 20-31字节：保留字段

- **后续字节**：栅格地图数据
  - 每个字节代表一个栅格
  - 0 = 空闲区域
  - 100 = 占用区域（障碍物）
  - 255 = 未知区域

## 验证地图加载

加载地图后，可以通过以下方式验证：

### 1. 获取地图信息

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/maps/info" | Select-Object -ExpandProperty Content
```

返回示例：
```json
{
  "width": 1000,
  "height": 800,
  "resolution": 0.05,
  "origin_x": -10.0,
  "origin_y": -8.0,
  "min_x": -10.0,
  "min_y": -8.0,
  "max_x": 40.0,
  "max_y": 32.0
}
```

### 2. 检查位置是否为障碍物

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/maps/check?x=5.0&y=3.0" | Select-Object -ExpandProperty Content
```

返回示例：
```json
{
  "x": 5.0,
  "y": 3.0,
  "is_obstacle": false,
  "is_free": true,
  "is_valid": true
}
```

### 3. 在可视化界面查看

访问可视化界面查看地图：
```
http://localhost:8000/static/index.html
```

## 常见问题

### Q: 如何知道机器人是否支持地图加载？

A: 机器人需要支持 `/api/core/slam/v1/maps/explore` API 端点。这是思岚科技底盘的标准API。

### Q: 地图加载失败怎么办？

A: 检查以下几点：
1. 机器人是否已正确注册
2. 机器人是否在线且可访问
3. 机器人是否支持地图API
4. 查看服务器日志获取详细错误信息

### Q: 可以加载多个地图吗？

A: 当前系统只支持加载一个地图。加载新地图会替换旧地图。

### Q: 地图数据会持久化吗？

A: 当前地图数据只保存在内存中，服务重启后需要重新加载。

## 相关 API

- `GET /api/maps/info` - 获取地图信息（如果未加载会自动尝试加载）
- `POST /api/maps/load?robot_id={robot_id}` - 从机器人加载地图
- `POST /api/maps/load-from-file` - 从文件加载地图
- `GET /api/maps/check?x={x}&y={y}` - 检查位置是否为障碍物

