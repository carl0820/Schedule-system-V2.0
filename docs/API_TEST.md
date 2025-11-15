# API测试指南

## 概述

本目录包含全面的API测试脚本，用于验证所有API端点是否正常工作。

## 测试脚本

### `test/test_all_apis.py`

全面的API测试脚本，测试所有API端点：

#### 测试范围

1. **系统级API**
   - `GET /` - 根路径
   - `GET /health` - 健康检查

2. **机器人管理API**
   - `GET /api/robots/` - 获取所有机器人列表
   - `POST /api/robots/register` - 注册机器人
   - `GET /api/robots/{robot_id}/state` - 获取机器人状态
   - `GET /api/robots/{robot_id}/pose` - 获取机器人位置
   - `DELETE /api/robots/{robot_id}` - 注销机器人

3. **任务管理API**
   - `GET /api/tasks/` - 获取任务列表
   - `POST /api/tasks/` - 创建任务
   - `GET /api/tasks/{task_id}` - 获取任务信息
   - `DELETE /api/tasks/{task_id}` - 取消任务

4. **地图管理API**
   - `GET /api/maps/info` - 获取地图信息
   - `GET /api/maps/check` - 检查位置是否为障碍物
   - `POST /api/maps/load` - 从机器人加载地图

5. **系统监控API**
   - `GET /api/system/status` - 获取系统状态
   - `GET /api/system/metrics` - 获取系统性能指标

## 使用方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

或单独安装测试所需依赖：

```bash
pip install httpx fastapi uvicorn psutil
```

### 2. 启动服务

在终端1中启动服务：

```bash
python main.py
```

或使用uvicorn：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 运行测试

在终端2中运行测试：

#### 基本测试（不需要机器人）

```bash
python test/test_all_apis.py
```

#### 完整测试（需要机器人）

```bash
python test/test_all_apis.py 10.160.128.91
```

其中 `10.160.128.91` 是机器人的IP地址。

### 4. 查看测试结果

测试脚本会输出详细的测试结果，包括：
- ✅ 每个API端点的测试状态
- 响应状态码
- 响应数据（前200字符）
- 错误信息（如果有）

最后会显示测试总结：
- 总测试数
- 通过数
- 失败数
- 通过率

## 测试输出示例

```
================================================================================
开始API全面测试
================================================================================

【系统级API】
✅ GET / - PASS
   状态码: 200
   响应: {
  "name": "多机器人调度系统",
  "version": "1.0.0",
  "status": "running"
}
✅ GET /health - PASS
   状态码: 200
   响应: {
  "status": "healthy"
}

【机器人管理API】
✅ GET /api/robots/ - PASS
   状态码: 200
   响应: []
...

================================================================================
测试总结
================================================================================
总测试数: 15
✅ 通过: 15
❌ 失败: 0
通过率: 100.0%
```

## 注意事项

1. **服务必须先启动**：测试前确保服务正在运行（默认端口8000）
2. **机器人连接**：如果需要测试机器人相关API，需要提供可访问的机器人IP地址
3. **测试顺序**：测试脚本会按顺序执行，某些测试可能依赖于前面的测试结果
4. **清理**：测试完成后会自动清理（注销测试机器人）

## 故障排查

### 连接错误

如果出现连接错误，请检查：
1. 服务是否正在运行
2. 端口是否正确（默认8000）
3. 防火墙设置

### 机器人连接失败

如果机器人相关测试失败，请检查：
1. 机器人IP地址是否正确
2. 机器人是否可访问
3. 机器人服务是否正在运行

### 依赖缺失

如果提示缺少依赖，请安装：
```bash
pip install -r requirements.txt
```

## 持续集成

可以在CI/CD流程中使用此测试脚本：

```bash
# 启动服务
python main.py &
sleep 5

# 运行测试
python test/test_all_apis.py

# 检查退出码
if [ $? -eq 0 ]; then
    echo "所有测试通过"
else
    echo "测试失败"
    exit 1
fi
```

