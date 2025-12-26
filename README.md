# 多机器人调度系统 V2.0

基于思岚科技底盘REST API的多机器人调度系统，实现多台机器人在同一场景下的协同调度、实时碰撞检测与避免、高效的任务分配与路径规划。

**✅ 项目状态：已完成三个阶段开发，支持3台机器人协同调度，已通过实际测试验证**

## 🎯 核心功能

### ✅ 阶段一：基础框架
- ✅ **项目架构搭建**：模块化设计，清晰的代码结构
- ✅ **地图管理模块**：栅格地图加载、解析、坐标转换
- ✅ **思岚科技API封装**：完整的机器人API接口封装
- ✅ **基础路径规划**：A*算法实现

### ✅ 阶段二：多机协调
- ✅ **多机器人状态管理**：实时监控多台机器人状态（位置、电量、速度等）
- ✅ **任务调度模块**：智能任务分配，支持优先级调度
- ✅ **碰撞检测算法**：时间窗口预测、轨迹预测，实时检测潜在碰撞
- ✅ **基础避让策略**：等待、减速、停止、重新规划等多种避让策略

### ✅ 阶段三：优化完善
- ✅ **避让算法优化**：考虑速度、优先级、距离等因素的智能避让
- ✅ **死锁处理**：循环等待、相互阻塞、资源竞争检测与自动解决
- ✅ **限行区域管理**：支持限行区域通行控制，结合等待点实现多机防死锁调度
- ✅ **性能优化**：异步处理、错误处理、日志优化、任务分配优化
- ✅ **多动作任务支持**：支持创建包含多个动作的复杂任务（MOVE_TO、WAIT、GO_HOME）
- ✅ **任务数据库**：SQLite数据库持久化，支持任务历史查询
- ✅ **任务可靠性增强**（新增）：
  - 🔧 卡住任务自动检测与恢复（10分钟超时检测）
  - 🔧 完善的错误处理与日志记录（所有失败路径都有明确日志）
  - 🔧 关键状态同步数据库（防止状态丢失）
  - 🔧 任务执行超时保护（单任务5分钟，多动作10分钟）
- ✅ **指定机器人任务API**：支持直接给指定机器人下发任务，包含8个完整示例
- ⏳ **可视化界面**：基础Web界面（待进一步优化）

## 🚀 快速开始

**新用户请先查看快速部署指南**：
- 🎯 [新手快速开始（3分钟）](docs/QUICKSTART_BEGINNER.md) - **完全零基础用户推荐**
- 💻 [Windows快速部署（无需Docker）](docs/WINDOWS_QUICK_DEPLOY.md) - **Windows用户推荐**
- 📖 [快速开始指南 - Windows（5分钟）](docs/QUICK_START.md)
- 🍎 [快速开始指南 - Mac/Linux（5分钟）](docs/QUICK_START_MAC_LINUX.md)
- 🐳 [Docker快速部署指南](docs/DOCKER_QUICK_START.md) - 适合有Docker环境的用户
- 📚 [详细部署指南](docs/QUICK_START_GUIDE.md)
- 📖 [API文档](docs/API.md)

## 技术栈

- **后端框架**：Python 3.8+ + FastAPI
- **通信协议**：HTTP REST API + WebSocket
- **路径规划**：A*算法（系统级）+ 机器人自主导航
- **地图管理**：栅格地图（Occupancy Grid Map）
- **数据存储**：SQLite（任务数据库）+ JSON（配置文件）
- **异步处理**：asyncio + httpx（异步HTTP客户端）

## 项目结构

```
.
├── app/
│   ├── api/                          # API路由
│   │   ├── robots.py                 # 机器人管理API
│   │   ├── tasks.py                  # 任务管理API（单动作/多动作）
│   │   ├── maps.py                   # 地图管理API
│   │   ├── system.py                 # 系统监控API
│   │   └── visualization.py          # 可视化数据API
│   ├── models/                       # 数据模型
│   │   ├── robot.py                  # 机器人相关模型
│   │   └── task.py                   # 任务相关模型
│   ├── services/                     # 业务逻辑服务
│   │   ├── robot_agent.py            # 思岚科技API封装
│   │   ├── robot_manager.py          # 机器人管理器
│   │   ├── task_scheduler.py         # 任务调度器（核心）
│   │   ├── map_manager.py            # 地图管理器
│   │   ├── path_planner.py           # 路径规划器
│   │   ├── collision_detector.py     # 碰撞检测器
│   │   ├── avoidance_strategy.py     # 避让策略
│   │   ├── deadlock_detector.py      # 死锁检测器
│   │   ├── restricted_area_traffic_manager.py  # 限行区域通行管理器
│   │   ├── priority_calculator.py    # 优先级计算器
│   │   └── config_manager.py         # 配置管理器
│   ├── db/                           # 数据库模块
│   │   └── task_db.py                # 任务数据库（SQLite）
│   └── core/                         # 核心模块
├── docs/                             # 文档目录
│   ├── API.md                        # API详细文档
│   ├── QUICK_START.md                # 快速开始指南
│   ├── TASK_SCHEDULING_LOGIC.md      # 任务调度逻辑说明
│   └── ...
├── static/                           # 静态文件（Web界面）
├── data/                             # 数据目录
│   ├── tasks.db                      # 任务数据库
│   └── ...
├── main.py                           # 主应用入口
├── requirements.txt                  # Python依赖
└── README.md                         # 项目说明
```

## 安装

### 1. 环境要求

- **操作系统**: Windows 10/11, macOS 10.14+, Linux (Ubuntu 18.04+, CentOS 7+)
- **Python**: 3.8 - 3.13（推荐 3.11 或 3.12）
- **内存**: 4GB+ RAM（推荐 8GB+）
- **网络**: 与机器人网络连通

### 2. 安装依赖

**方法1：使用Python脚本（推荐，自动处理网络问题）**
```bash
python install_deps.py
```

**方法2：使用PowerShell脚本（Windows）**
```powershell
.\install_deps_simple.ps1
```

**方法3：直接安装**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**方法4：禁用代理后安装**
```powershell
# PowerShell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置

系统会自动从机器人获取地图和配置信息，无需手动配置。如需自定义配置，可修改 `data/runtime_config.json`。

## 部署

### Docker 部署（推荐，适合快速部署）

**快速开始（3步）：**

```bash
# 1. 克隆代码
git clone https://github.com/carl0820/Schedule-system-V2.0.git
cd Schedule-system-V2.0

# 2. 构建并启动
docker-compose up -d --build

# 3. 访问服务
# http://localhost:8092/docs
```

**详细文档：**
- 📖 [Docker 快速部署指南](docs/DOCKER_QUICK_START.md) - 适合快速上手
- 📚 [Docker 详细部署文档](docs/DOCKER_DEPLOYMENT.md) - 完整配置说明

**优势：**
- ✅ 无需安装 Python 环境
- ✅ 自动处理所有依赖
- ✅ 一键启动，开箱即用
- ✅ 环境隔离，不影响系统

### 本地部署

**Windows（推荐使用一键部署）:**

```powershell
# 方法1：一键部署（推荐，首次部署）
.\deploy.bat          # 双击运行，或在PowerShell中执行
# 或
.\deploy.ps1          # 自动检测Python、安装依赖、启动服务

# 方法2：快速启动（已安装依赖）
.\start.bat           # 双击运行，或在PowerShell中执行
# 或
.\start.ps1           # 自动检测Python并启动

# 方法3：使用原始脚本
.\start_service.ps1

# 方法4：直接运行（需要python命令可用）
python main.py
```

**智能启动脚本特性：**
- ✅ 自动检测并选择正确的Python（支持多Python环境）
- ✅ 自动排除MSYS2、Cygwin等不适合的Python
- ✅ 自动检查依赖安装状态
- ✅ 友好的错误提示和解决建议
- ✅ 适用于任何Windows电脑，无需修改配置

**重要提示（Windows用户）：**
- 如果系统中安装了多个Python（如MSYS2、Anaconda等），我们的脚本会自动选择正确的Python
- 如果自动检测失败，脚本会提供明确的安装指引
- 检查Python版本：`python --version` 或 `where python`
- 手动指定Python路径（如需要）：
  ```powershell
  C:\Users\<用户名>\AppData\Local\Programs\Python\Python313\python.exe main.py
  ```

**Mac/Linux:**
```bash
python main.py
```

**或使用 uvicorn:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8092 --reload
```

服务启动后，访问：
- **首页**: http://localhost:8092
- **机器人管理**: http://localhost:8092/static/robot_list.html
- **任务管理**: http://localhost:8092/static/task_list.html
- **地图管理**: http://localhost:8092/static/map_management.html
- **API文档**: http://localhost:8092/docs
- **健康检查**: http://localhost:8092/health

## API使用示例

### 1. 注册机器人

```bash
curl -X POST "http://localhost:8000/api/robots/register?robot_id=P3&base_url=http://10.160.129.149:1448"
```

### 2. 获取机器人状态

```bash
curl "http://localhost:8000/api/robots/P3/state"
```

### 3. 创建单动作任务

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

### 4. 创建多动作任务（自动分配机器人）

```bash
curl -X POST "http://localhost:8092/api/tasks/multi-action" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {
        "action_type": "move_to",
        "target_pose": {"x": 5.0, "y": 3.0, "yaw": 0.0}
      },
      {
        "action_type": "wait",
        "wait_duration": 10
      },
      {
        "action_type": "move_to",
        "poi_name": "P08"
      }
    ],
    "priority": 2
  }'
```

### 4.1 给指定机器人创建任务（推荐）

**使用POI导航：**
```bash
curl -X POST "http://localhost:8092/api/tasks/multi-action/P3" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {
        "action_type": "move_to",
        "poi_name": "P04"
      }
    ]
  }'
```

**使用坐标导航：**
```bash
curl -X POST "http://localhost:8092/api/tasks/multi-action/Apollo" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {
        "action_type": "move_to",
        "target_pose": {"x": 3.8, "y": -2.9, "yaw": 0.0}
      }
    ]
  }'
```

**多点巡检任务：**
```bash
curl -X POST "http://localhost:8092/api/tasks/multi-action/P3" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {"action_type": "move_to", "poi_name": "P01"},
      {"action_type": "wait", "wait_duration": 5.0},
      {"action_type": "move_to", "poi_name": "P04"},
      {"action_type": "wait", "wait_duration": 5.0},
      {"action_type": "move_to", "poi_name": "P08"},
      {"action_type": "go_home"}
    ],
    "priority": 2
  }'
```

**更多示例请访问API文档：** http://localhost:8092/docs#/任务管理/create_multi_action_task_for_robot

### 5. 查询任务列表

```bash
curl "http://localhost:8000/api/tasks/?status=executing&limit=10"
```

### 6. 取消任务

```bash
curl -X DELETE "http://localhost:8000/api/tasks/{task_id}"
```

### 7. 强制解锁限行区域

```bash
curl -X POST "http://localhost:8000/api/tasks/force-unlock-restricted-area"
```

## 核心特性详解

### 1. 智能任务分配
- **优先级调度**：支持任务优先级，高优先级任务优先分配
- **动态优先级**：根据等待时间自动提升优先级
- **最优机器人选择**：基于距离、负载、电量等因素选择最优机器人
- **并发分配优化**：支持多个任务同时分配给不同机器人

### 2. 碰撞检测与避让
- **时间窗口预测**：预测未来时间窗口内的潜在碰撞
- **轨迹预测**：基于机器人速度和路径预测轨迹
- **多种避让策略**：等待、减速、停止、重新规划
- **智能避让决策**：考虑速度、优先级、距离等因素

### 3. 死锁检测与解决
- **循环等待检测**：检测机器人之间的循环等待死锁
- **相互阻塞检测**：检测机器人相互阻塞的情况
- **资源竞争检测**：检测限行区域等资源的竞争
- **自动解锁机制**：自动检测并解决死锁问题

### 4. 限行区域管理
- **通行容量控制**：根据限行区域宽度动态计算通行容量
- **等待点机制**：机器人无法通行时自动前往等待点
- **优先级通行**：根据任务优先级决定通行顺序
- **自动恢复任务**：限行区域释放后自动恢复任务执行

### 5. 多动作任务支持
- **动作序列**：支持创建包含多个动作的复杂任务
- **动作类型**：支持 MOVE_TO（移动到目标点）、WAIT（等待）、GO_HOME（回桩）
- **POI支持**：支持使用POI名称作为目标点
- **自动执行**：系统自动按顺序执行所有动作

## 测试验证

✅ **已通过实际测试验证**：
- 支持3台机器人同时协同调度
- 任务正确分配和执行
- 碰撞检测和避让正常工作
- 死锁检测和自动解锁功能正常
- 限行区域管理功能正常

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
- [x] 限行区域管理（通行容量控制、等待点机制、优先级通行）
- [x] 多动作任务支持（动作序列、POI支持、自动执行）
- [x] 任务数据库（SQLite持久化、历史查询）
- [x] 性能优化（异步处理、错误处理、日志优化、任务分配优化）
- [ ] 可视化界面优化（待进一步优化）

## 文档

- 📖 [API详细文档](docs/API.md)
- 📖 [任务调度逻辑说明](docs/TASK_SCHEDULING_LOGIC.md)
- 📖 [快速开始指南](docs/QUICK_START.md)
- 📖 [限行区域配置](docs/WAITING_POINTS_CONFIG.md)

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 更新日志

### V2.0 (当前版本)
- ✅ 完成三个阶段开发
- ✅ 支持3台机器人协同调度
- ✅ 实现限行区域管理
- ✅ 优化任务分配逻辑
- ✅ 增强死锁检测和自动解锁
- ✅ 支持多动作任务

### V1.0
- ✅ 基础框架搭建
- ✅ 单机器人任务调度
