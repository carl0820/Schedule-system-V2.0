<<<<<<< HEAD
# 多机器人调度系统

基于思岚科技底盘REST API的多机器人调度系统，实现多台机器人在同一场景下的协同调度、实时碰撞检测与避免、高效的任务分配与路径规划。

## 功能特性

### 阶段一：基础框架 ✅
- ✅ 项目架构搭建
- ✅ 地图管理模块（栅格地图加载、解析、坐标转换）
- ✅ 思岚科技API封装（所有机器人API接口）
- ✅ 基础路径规划（A*算法）

### 阶段二：多机协调（待实现）
- 多机器人状态管理
- 任务调度模块
- 碰撞检测算法
- 基础避让策略

### 阶段三：优化完善（待实现）
- 避让算法优化
- 死锁处理
- 性能优化
- 可视化界面

## 技术栈

- **后端框架**：Python 3.8+ + FastAPI
- **通信协议**：HTTP REST API + WebSocket
- **路径规划**：A*算法
- **地图管理**：栅格地图（Occupancy Grid Map）
- **数据存储**：Redis（实时状态）+ PostgreSQL（历史数据）

## 项目结构

```
.
├── app/
│   ├── api/              # API路由
│   │   ├── robots.py     # 机器人管理API
│   │   ├── tasks.py      # 任务管理API
│   │   ├── maps.py       # 地图管理API
│   │   └── system.py     # 系统监控API
│   ├── models/           # 数据模型
│   │   ├── robot.py      # 机器人相关模型
│   │   └── task.py        # 任务相关模型
│   ├── services/         # 业务逻辑服务
│   │   ├── robot_agent.py      # 思岚科技API封装
│   │   ├── robot_manager.py    # 机器人管理器
│   │   ├── task_scheduler.py   # 任务调度器
│   │   ├── map_manager.py      # 地图管理器
│   │   └── path_planner.py     # 路径规划器
│   └── core/             # 核心模块
├── config.py             # 系统配置
├── main.py               # 主应用入口
├── requirements.txt      # Python依赖
└── README.md             # 项目说明
```

## 🚀 快速开始

**新用户请先查看快速部署指南**：
- 📖 [快速开始指南 - Windows（5分钟）](QUICK_START.md)
- 🍎 [快速开始指南 - Mac/Linux（5分钟）](QUICK_START_MAC_LINUX.md)
- 📚 [详细部署指南](docs/QUICK_START_GUIDE.md)

## 安装

### 1. 环境要求

- **操作系统**: Windows 10/11 (64位)
- **Python**: 3.8 - 3.13（推荐 3.11 或 3.12）
- **内存**: 4GB+ RAM（推荐 8GB+）
- **网络**: 与机器人网络连通

### 2. 安装依赖

如果遇到网络或代理问题，请查看 [INSTALL.md](INSTALL.md) 获取详细解决方案。

**方法1：直接安装（推荐）**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**方法2：使用安装脚本（Windows）**
```powershell
.\install_deps_simple.ps1
```

**方法3：使用Python脚本（跨平台）**
```bash
python install_deps.py
```

**方法4：禁用代理后安装**
```powershell
# PowerShell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置

复制 `.env.example` 到 `.env` 并修改配置：

```bash
# 应用配置
APP_NAME=多机器人调度系统
APP_VERSION=1.0.0
DEBUG=False

# 服务器配置
HOST=0.0.0.0
PORT=8000

# 数据库配置（可选）
REDIS_HOST=localhost
REDIS_PORT=6379
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=robot_scheduler

# 地图配置
MAP_RESOLUTION=0.05
```

## 测试

### 1. 语法测试（不需要安装依赖）

```bash
python test/test_syntax_only.py
```

### 2. 快速功能测试（需要安装依赖）

```bash
# 先安装依赖
pip install -r requirements.txt

# 运行快速测试
python test/quick_test.py
```

## 运行

### 启动服务

```bash
python main.py
```

或使用 uvicorn：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后，访问：
- API文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## API使用示例

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

### 5. 取消任务

```bash
curl -X DELETE "http://localhost:8000/api/tasks/{task_id}"
```

## 开发计划

### 阶段一：基础框架 ✅
- [x] 项目架构搭建
- [x] 地图管理模块
- [x] 思岚科技API封装
- [x] 基础路径规划

### 阶段二：多机协调 ✅
- [x] 多机器人状态管理
- [x] 任务调度模块（集成碰撞检测和避让策略）
- [x] 碰撞检测算法（时间窗口预测、轨迹预测）
- [x] 基础避让策略（等待、减速、停止、重新规划）

### 阶段三：优化完善 ✅
- [x] 避让算法优化（考虑速度、优先级、距离等因素）
- [x] 死锁处理（循环等待、相互阻塞、资源竞争检测与自动解决）
- [x] 性能优化（异步处理、错误处理、日志优化）
- [ ] 可视化界面（待实现）

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

