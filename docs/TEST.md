# 测试说明

## 测试结果

### 语法测试 ✅
所有Python文件语法检查通过：
- ✅ config.py
- ✅ main.py
- ✅ app/models/robot.py
- ✅ app/models/task.py
- ✅ app/services/robot_agent.py
- ✅ app/services/map_manager.py
- ✅ app/services/path_planner.py
- ✅ app/services/robot_manager.py
- ✅ app/services/task_scheduler.py
- ✅ app/api/robots.py
- ✅ app/api/tasks.py
- ✅ app/api/maps.py
- ✅ app/api/system.py

## 测试步骤

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

如果遇到网络问题，可以尝试：
```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 运行语法测试

```bash
python test/test_syntax_only.py
```

这个测试只检查语法，不检查导入依赖。

### 3. 运行完整测试

```bash
python test/test_basic.py
```

这个测试会检查导入，如果缺少依赖会显示警告。

### 4. 启动应用测试

```bash
python main.py
```

或者使用 uvicorn：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 访问API文档

启动后访问：
- API文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 根路径：http://localhost:8000/

## API测试示例

### 1. 注册机器人

```bash
curl -X POST "http://localhost:8000/api/robots/register?robot_id=robot1&base_url=http://10.160.128.91:1448"
```

### 2. 获取机器人状态

```bash
curl "http://localhost:8000/api/robots/robot1/state"
```

### 3. 创建任务

```bash
curl -X POST "http://localhost:8000/api/tasks/" \
  -H "Content-Type: application/json" \
  -d '{
    "target_pose": {
      "x": 5.0,
      "y": 3.0,
      "yaw": 0.0
    },
    "priority": 2
  }'
```

### 4. 查询任务列表

```bash
curl "http://localhost:8000/api/tasks/"
```

### 5. 获取地图信息

```bash
curl "http://localhost:8000/api/maps/info"
```

## 注意事项

1. **依赖安装**：如果遇到网络问题，可能需要配置代理或使用国内镜像源
2. **机器人连接**：确保机器人底盘API可访问（http://10.160.128.91:1448）
3. **数据库**：Redis和PostgreSQL是可选的，如果不需要可以暂时不配置
4. **地图数据**：需要先从机器人获取地图数据才能进行路径规划

## 常见问题

### Q: 导入错误 "No module named 'xxx'"
A: 需要安装依赖：`pip install -r requirements.txt`

### Q: 无法连接到机器人
A: 检查机器人IP地址和端口是否正确，确保网络连通

### Q: 地图相关功能报错
A: 需要先同步地图或获取地图数据

