# 任务调度分配逻辑梳理

## 一、整体架构

任务调度系统采用**循环调度**机制，通过 `_scheduler_loop()` 持续运行，每0.5秒执行一次调度检查。

## 二、调度循环流程（`_scheduler_loop`）

### 1. 查找待分配任务
```python
pending_tasks = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
```
- 筛选所有状态为 `PENDING` 的任务
- **按优先级排序**（优先级值越大越优先）：`pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)`

### 2. 查找可用机器人
```python
available_robots = []
for robot_id in robot_ids:
    state = await self.robot_manager.get_robot_state(robot_id)
    if state.status == RobotStatus.IDLE:
        # 检查是否有正在执行或已分配的任务
        has_active_task = any(
            t.robot_id == robot_id and 
            (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
            for t in self.tasks.values()
        )
        if not has_active_task:
            # 检查机器人电量（电量低于20%不分配任务）
            battery_percentage = state.power.batteryPercentage if state.power else 0
            if battery_percentage >= 20:
                available_robots.append((robot_id, state))
```

**可用机器人条件**：
- ✅ 机器人状态为 `IDLE`（空闲）
- ✅ 没有 `ASSIGNED` 或 `EXECUTING` 状态的任务（防止重复分配）
- ✅ **电量 >= 20%**（电量低于20%的机器人不分配任务，确保有足够电量完成任务）
- ✅ **当前位置不在障碍物区域**（如果机器人被人为推到障碍物区域，不分配任务）

### 3. 无可用机器人时的处理
如果没有可用机器人但有待分配任务：
1. 先调用 `_update_executing_tasks()` 更新任务状态（可能释放机器人）
2. 重新检查可用机器人
3. 如果仍然没有，等待0.5秒后继续循环

### 4. 更新执行中的任务状态
在分配新任务之前，先更新执行中任务的状态：
```python
await self._update_executing_tasks()
```
- 检查任务是否完成、失败或取消
- 可能释放机器人，使其重新可用

### 5. 任务分配（核心逻辑）

对每个待分配任务，选择最优机器人：

#### 5.1 机器人选择算法

```python
for task in pending_tasks:
    best_robot_id = None
    best_cost = float('inf')
    
    for robot_id, state in available_robots:
        # 1. 路径规划
        path = self.path_planner.plan_path(robot_pose, target_pose)
        
        # 2. 计算路径长度
        path_length = 计算路径总长度
        
        # 3. 检查路径碰撞惩罚
        collision_penalty = await self._check_path_collision_with_planned_paths(
            robot_id, path, task.task_id
        )
        
        # 4. 计算总成本
        cost = path_length + collision_penalty
        
        # 5. 选择成本最低的机器人
        if cost < best_cost:
            best_cost = cost
            best_robot_id = robot_id
```

**成本计算**：
- **路径长度**：使用A*算法规划路径，计算实际路径总长度（而非直线距离）
- **碰撞惩罚**：检查路径是否与其他机器人已规划的路径碰撞
  - 碰撞惩罚 = `(安全距离 - 最小距离) / 安全距离 * 路径长度 * 10.0`
  - 碰撞越严重，惩罚值越大

**选择原则**：
- ✅ 优先选择**路径最短**的机器人
- ✅ 优先选择**路径碰撞最少**的机器人
- ✅ 如果路径规划失败，使用直线距离作为备选

#### 5.2 分配任务（`_assign_task`）

分配流程：

1. **确定起点**
   - 如果任务有 `start_pose`，使用任务指定的起点
   - 否则使用机器人当前位置

2. **路径规划**
   ```python
   path = self.path_planner.plan_path(start, task.target_pose)
   ```
   - 使用A*算法规划路径
   - 如果规划失败，允许重试（最多3次）

3. **窄道检测**
   ```python
   narrow_passages = self.path_planner.detect_narrow_passages(path, robot_radius=0.2, narrow_threshold=1.0)
   ```
   - 检测路径中的窄道（宽度 < 1.0米）
   - 检查是否有其他机器人也在使用相同的窄道
   - 如果冲突，记录警告（由避让策略运行时处理）

4. **碰撞检测**
   - 检查路径是否与其他机器人当前位置碰撞
   - 检查路径是否与其他任务已规划的路径碰撞
   - 如果碰撞点超过路径的30%，记录警告（继续执行，由避让策略处理）

5. **立即标记任务为已分配**（防止重复分配）
   ```python
   task.robot_id = robot_id
   task.status = TaskStatus.ASSIGNED
   task.assigned_at = datetime.now()
   self._save_tasks_to_file()  # 立即持久化
   ```
   **关键**：在调用机器人API之前就标记为 `ASSIGNED`，防止同一调度循环中重复分配

6. **创建移动动作**
   ```python
   action_state = await agent.move_to(
       target=task.target_pose,
       mode=0,  # Free Navigation - 自由导航模式
       acceptable_precision=0.3,
       speed_ratio=1.0
   )
   ```

7. **更新任务状态**
   ```python
   task.action_id = action_state.action_id
   task.status = TaskStatus.EXECUTING
   task.started_at = datetime.now()
   self._save_tasks_to_file()
   ```

8. **错误处理**
   - 如果API调用失败，重置任务为 `PENDING`，允许重新分配
   - 重试次数达到3次后，标记为 `FAILED`

## 三、任务状态更新（`_update_executing_tasks`）

定期检查执行中任务的状态：

### 1. 检查范围
- `EXECUTING` 状态的任务
- `ASSIGNED` 状态的任务（可能还没有action_id）

### 2. 获取action_id
如果任务已分配但还没有 `action_id`：
- 查询机器人当前action
- 如果获取到，更新任务状态为 `EXECUTING`

### 3. 查询action状态
```python
action_state = await agent.get_action_status(task.action_id)
```

### 4. 状态判断
- **status=4, result=0**：任务完成 → `COMPLETED`
- **status=4, result=-1**：任务失败 → `FAILED`
- **status=4, result=-2**：任务中止 → `CANCELLED`
- **status=1**：正在执行 → 保持 `EXECUTING`
- **status=None**：action可能已完成，通过位置判断是否到达目标

## 四、防重复分配机制

### 1. 状态检查
在查找可用机器人时，检查是否有 `ASSIGNED` 或 `EXECUTING` 状态的任务：
```python
has_active_task = any(
    t.robot_id == robot_id and 
    (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
    for t in self.tasks.values()
)
```

### 2. 立即标记
在 `_assign_task` 中，**在调用机器人API之前**就标记任务为 `ASSIGNED` 并持久化：
```python
task.status = TaskStatus.ASSIGNED
self._save_tasks_to_file()  # 立即保存
```

### 3. 从可用列表移除
分配成功后，立即从 `available_robots` 列表中移除该机器人：
```python
available_robots = [(r, s) for r, s in available_robots if r != best_robot_id]
```

## 五、碰撞检测与避让

### 1. 路径碰撞检测（分配时）
- 检查路径与其他机器人当前位置的碰撞
- 检查路径与其他任务已规划路径的碰撞
- 计算碰撞惩罚值，影响机器人选择

### 2. 运行时碰撞检测（`_collision_check_loop`）
- 每0.1秒检测一次（10Hz）
- 对每个执行中的任务调用避让策略
- 如果检测到碰撞，触发避让动作

### 3. 死锁检测（`_deadlock_check_loop`）
- 每0.5秒检测一次（提高响应速度）
- 检测多种死锁类型：
  - **相互阻塞**：阈值3.0秒（快速响应）
  - **循环等待**：阈值10.0秒
  - **窄道死锁**：阈值3.0秒（快速响应）
  - **资源竞争**：阈值10.0秒
- 如果死锁持续时间超过阈值，尝试解决
- **死锁解除策略**：
  - 优先使用任务优先级选择需要避让的机器人
  - 优先移动到系统计算的等待点（而非简单后退）
  - 支持多机器人死锁（3台或更多机器人时，让多个低优先级机器人避让）
  
### 4. 死锁解除后任务恢复机制
- **问题**：机器人因死锁解除移动到等待点后，原任务可能被中断，导致任务一直显示在执行状态
- **解决方案**：
  1. **跟踪避让状态**：系统记录因死锁解除而移动到等待点的机器人及其原任务信息
     - 记录原任务ID、原action_id、等待点位置、开始时间
  2. **自动检测到达**：在每次任务状态更新时检查机器人是否已到达等待点
     - 距离判断：机器人当前位置与等待点距离 < 0.5米
  3. **自动恢复任务**：
     - **普通任务**：重新移动到目标点
     - **多动作任务**：继续执行当前动作
     - 更新任务状态和action_id，确保任务继续执行
  4. **超时保护**：如果30秒内未到达等待点，强制恢复任务执行
- **工作流程**：
  ```
  死锁检测 → 机器人移动到等待点 → 记录原任务信息
  → 任务状态更新循环 → 检查是否到达等待点
  → 到达等待点 → 自动恢复原任务执行 → 任务继续执行 → 正常完成
  ```

## 六、任务优先级

- 任务按优先级排序：`priority.value` 越大越优先
- 高优先级任务优先分配

## 七、调度频率

- **调度循环**：每0.5秒执行一次
- **状态更新**：在调度循环中调用
- **碰撞检测**：每0.1秒执行一次（独立循环）
- **死锁检测**：每0.5秒执行一次（独立循环，提高响应速度）
- **任务恢复检查**：在每次任务状态更新时执行（检查死锁解除后的任务恢复）

## 八、关键设计点

### 1. 防止重复分配
- ✅ 检查 `ASSIGNED` 和 `EXECUTING` 状态
- ✅ 立即标记并持久化状态
- ✅ 从可用列表移除

### 2. 最优机器人选择
- ✅ 使用实际路径长度（而非直线距离）
- ✅ 考虑路径碰撞惩罚
- ✅ 优先选择成本最低的机器人

### 3. 容错机制
- ✅ 路径规划失败允许重试（最多3次）
- ✅ API调用失败重置为 `PENDING`，允许重新分配
- ✅ 状态更新失败不影响其他任务

### 4. 实时性
- ✅ 快速响应（0.5秒调度周期）
- ✅ 及时更新任务状态
- ✅ 实时碰撞检测和避让

## 九、任务状态流转

```
PENDING → ASSIGNED → EXECUTING → COMPLETED/FAILED/CANCELLED
   ↑         ↓
   └─────────┘ (API失败时重置)
```

- **PENDING**：待分配
- **ASSIGNED**：已分配给机器人，但还未开始执行
- **EXECUTING**：正在执行
- **COMPLETED**：完成
- **FAILED**：失败
- **CANCELLED**：取消

## 十、总结

任务调度系统采用**基于成本的贪心算法**：
1. 按优先级排序待分配任务
2. 筛选可用机器人（IDLE状态、无活跃任务、电量 >= 20%、不在障碍物区域）
3. 对每个任务，选择**成本最低**的可用机器人
4. 成本 = 路径长度 + 碰撞惩罚
5. 立即标记任务状态，防止重复分配
6. 持续监控任务状态，及时释放机器人
7. 运行时进行碰撞检测和避让，确保安全

## 十一、电量管理

系统在分配任务时会检查机器人电量：
- **电量阈值**：20%
- **规则**：电量低于20%的机器人不会被分配新任务
- **目的**：确保机器人有足够电量完成任务，避免任务执行中途因电量不足而失败
- **检查位置**：在所有查找可用机器人的地方都进行电量检查

## 十二、障碍物区域检查

系统在分配任务时会检查机器人当前位置：
- **检查方法**：使用 `MapManager.is_obstacle()` 检查机器人当前位置是否为障碍物
- **规则**：位于障碍物区域的机器人不会被分配新任务
- **目的**：
  - 防止给被人为推到障碍物区域的机器人分配任务
  - 避免机器人从障碍物区域开始执行任务，可能导致路径规划失败或异常行为
- **检查位置**：在所有查找可用机器人的地方都进行障碍物检查
- **日志记录**：如果机器人位于障碍物区域，会记录警告日志，包含机器人位置信息

## 十三、死锁解除后任务恢复机制

### 问题背景
当机器人因死锁解除而移动到等待点后，原任务可能被中断，导致任务一直显示在执行状态而无法继续。

### 解决方案

#### 1. 跟踪避让状态
系统使用 `robots_in_deadlock_resolution` 字典跟踪正在执行死锁解除避让的机器人：
```python
{
    robot_id: {
        'task_id': str,              # 原任务ID
        'original_action_id': str,   # 原action_id
        'waiting_point': Pose,       # 等待点位置
        'start_time': datetime       # 开始时间
    }
}
```

#### 2. 自动检测到达
在每次 `_update_executing_tasks()` 调用时，首先执行 `_check_and_resume_deadlock_resolution_tasks()`：
- 检查机器人当前位置与等待点的距离
- 如果距离 < 0.5米，认为已到达等待点
- 检查机器人当前动作状态，确认避让动作已完成

#### 3. 自动恢复任务
当检测到机器人已到达等待点：
- **普通任务**：
  - 重新调用 `agent.move_to(task.target_pose)` 移动到目标点
  - 更新 `task.action_id` 和 `task.status = EXECUTING`
- **多动作任务**：
  - 调用 `_execute_next_action()` 继续执行当前动作
  - 保持任务状态为 `EXECUTING`

#### 4. 超时保护
- 如果30秒内机器人仍未到达等待点，强制恢复任务执行
- 防止因异常情况导致任务永久卡住

#### 5. 日志记录
- 记录机器人到达等待点的信息
- 记录任务恢复的详细信息（新action_id、目标位置等）
- 记录超时强制恢复的警告信息

### 工作流程示例

```
1. 死锁检测 → 检测到相互阻塞死锁（phoebus, p3_1）
2. 死锁解除 → p3_1（低优先级）移动到等待点
3. 记录信息 → robots_in_deadlock_resolution['p3_1'] = {...}
4. 任务状态更新 → _check_and_resume_deadlock_resolution_tasks()
5. 检测到达 → 距离等待点 < 0.5米
6. 恢复任务 → 重新移动到目标点，更新action_id
7. 任务继续 → 正常执行并完成
```

### 关键设计点

- ✅ **非阻塞**：任务恢复检查在任务状态更新时异步执行，不阻塞主流程
- ✅ **自动恢复**：无需人工干预，系统自动检测并恢复
- ✅ **支持多任务类型**：普通任务和多动作任务都支持
- ✅ **超时保护**：防止异常情况导致任务永久卡住
- ✅ **详细日志**：便于调试和问题排查

