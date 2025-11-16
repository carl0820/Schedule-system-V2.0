# 两个任务到达同一个点的处理机制

## 概述

当两个或多个任务的目标点相同或非常接近时，系统采用**多层防护机制**来确保所有任务都能安全完成，避免冲突和死锁。

## 处理机制

### 1. 任务分配阶段（预防性处理）

#### 1.1 路径碰撞检测
在分配任务时，系统会检查新任务的路径是否与其他**已规划路径**碰撞：

```python
# 检查与其他任务已规划路径的碰撞
planned_path_collisions = await self._check_path_collision_with_planned_paths(
    robot_id, path, task.task_id
)
```

**检测逻辑**：
- 比较新路径与所有执行中任务的路径点
- 计算路径点之间的最小距离
- 如果距离 < 安全距离（机器人半径×2 + 安全距离），认为有碰撞
- 安全距离 = 0.3m × 2 + 0.8m = **1.4米**

#### 1.2 碰撞惩罚机制
如果检测到路径碰撞，系统会计算**碰撞惩罚值**：

```python
# 惩罚值 = (安全距离 - 最小距离) / 安全距离 * 路径长度 * 10.0
penalty = (safety_distance - min_distance) / safety_distance * len(path) * 10.0
```

**影响**：
- 碰撞惩罚值会加到路径成本中
- 碰撞越严重，惩罚值越大
- 系统会优先选择**碰撞最少**的机器人

#### 1.3 机器人选择策略
系统会为每个待分配任务选择**成本最低**的机器人：

```python
cost = path_length + collision_penalty
```

**选择原则**：
- ✅ 优先选择路径最短的机器人
- ✅ 优先选择路径碰撞最少的机器人
- ✅ 如果多个任务目标点相同，会分配给不同的机器人（如果可能）

### 2. 运行时处理（动态避让）

#### 2.1 碰撞检测循环
系统每 **0.1秒**（10Hz）检测一次碰撞：

```python
async def _collision_check_loop(self):
    while True:
        # 检测所有执行中任务的碰撞
        # 触发避让策略
```

**检测内容**：
- 机器人当前位置之间的碰撞
- 预测轨迹的碰撞
- 目标点附近的碰撞

#### 2.2 目标点阻塞检测
系统会检查是否有机器人**阻塞了目标点**：

```python
# 检查是否阻塞了目标点
if target_pose:
    dx = robot_pose.x - target_pose.x
    dy = robot_pose.y - target_pose.y
    target_distance = math.sqrt(dx*dx + dy*dy)
    if target_distance < threshold_distance:  # 1.4米
        blocking_reason = "blocking target point"
```

**处理方式**：
- 如果机器人阻塞了目标点，系统会**立即**让该机器人移动到避让点
- 避让点计算：向后退或移动到路径一侧
- 使用更高优先级，确保快速执行

#### 2.3 避让策略
根据碰撞情况，系统会采取不同的避让动作：

**避让动作类型**：
1. **WAIT（等待）**：优先级低的机器人等待
2. **SLOW_DOWN（减速）**：降低速度，让其他机器人先通过
3. **STOP（停止）**：紧急情况下停止
4. **REROUTE（重新规划）**：重新规划路径绕过冲突点
5. **YIELD（让行）**：主动让行给优先级高的机器人

**优先级计算**：
```python
priority = task_priority * 10 + distance_factor
```
- 任务优先级越高，越优先通行
- 距离目标越近，优先级越高

### 3. 死锁检测与解除

#### 3.1 资源竞争死锁检测
如果多个机器人竞争同一个目标点，系统会检测**资源竞争死锁**：

**检测条件**：
- 多个机器人长时间（5秒）无法到达目标点
- 目标点被其他机器人占用
- 机器人相互阻塞

#### 3.2 死锁解除策略
检测到死锁后，系统会：

1. **选择避让机器人**：
   - 优先级最低的机器人
   - 距离最近的机器人（如果优先级相同）
   - 执行时间最长的机器人（如果优先级和距离都相同）

2. **移动到等待点**：
   - 计算安全的等待点（距离目标点1.5-2米）
   - 移动到等待点
   - 等待其他机器人完成任务

3. **任务恢复**：
   - 检测其他机器人是否已离开目标点
   - 如果距离 < 0.5米，认为已离开
   - 自动恢复原任务

### 4. 具体场景处理

#### 场景1：两个任务同时分配到相同目标点

**处理流程**：
1. 任务A分配给机器人1，任务B分配给机器人2
2. 系统检测到路径碰撞，计算碰撞惩罚
3. 两个任务都开始执行
4. 碰撞检测循环持续监控
5. 当机器人接近目标点时，触发避让策略
6. 优先级高的机器人先到达，优先级低的等待或避让

#### 场景2：一个机器人已到达目标点，另一个机器人也要到达

**处理流程**：
1. 系统检测到目标点被阻塞（"blocking target point"）
2. **立即**让已到达的机器人移动到避让点
3. 等待的机器人继续执行任务
4. 等待的机器人到达后，已避让的机器人可以返回（如果需要）

#### 场景3：多个机器人同时到达目标点（死锁）

**处理流程**：
1. 死锁检测器检测到资源竞争死锁（5秒阈值）
2. 根据优先级选择避让机器人
3. 避让机器人移动到等待点（1.5-2米外）
4. 其他机器人完成任务
5. 避让机器人检测到目标点空闲（距离 < 0.5米）
6. 自动恢复原任务

### 5. 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 安全距离 | 1.4米 | 机器人半径×2 + 安全距离 |
| 目标点阻塞阈值 | 1.4米 | 如果机器人距离目标点 < 1.4米，认为阻塞 |
| 避让点距离 | 1.5-2米 | 避让机器人移动到目标点外1.5-2米 |
| 目标点空闲判断 | 0.5米 | 如果所有机器人距离目标点 > 0.5米，认为空闲 |
| 资源竞争死锁阈值 | 5秒 | 如果5秒无法到达目标点，触发死锁检测 |
| 碰撞检测频率 | 10Hz | 每0.1秒检测一次 |
| 死锁检测频率 | 2Hz | 每0.5秒检测一次 |

### 6. 日志示例

#### 正常避让
```
[INFO] Path collision detected for task xxx. Collisions at waypoints: [...]
[WARN] Robot robot1 is blocking task task2 (robot: robot2): min_distance=0.8m < threshold=1.4m, reason=blocking target point
[WARN] Robot robot1 (completed task task1) is blocking paths of 1 executing tasks. Moving to avoidance point immediately...
```

#### 死锁检测与解除
```
[WARN] Resource contention deadlock detected: robots=['robot1', 'robot2'] competing for target point (10.0, 5.0)
[INFO] Resolving resource contention deadlock: robot robot2 (priority=1) moving to waiting point
[INFO] Robot robot2 moved to waiting point (11.2, 5.0), distance=1.2m from target
[INFO] Target point (10.0, 5.0) is now free, robot robot2 can resume task
[INFO] Resolved resource contention deadlock: robot robot2 resumed task task2
```

## 总结

系统采用**多层防护机制**处理相同目标点的情况：

1. **预防**：任务分配时检测路径碰撞，选择碰撞最少的机器人
2. **监控**：运行时持续检测碰撞和目标点阻塞
3. **避让**：根据优先级动态避让，确保高优先级任务优先完成
4. **恢复**：死锁检测与自动解除，确保所有任务最终完成

**关键特点**：
- ✅ 不会阻止多个任务分配到相同目标点
- ✅ 通过碰撞检测和避让策略动态协调
- ✅ 根据任务优先级决定通行顺序
- ✅ 自动检测和解除死锁
- ✅ 确保所有任务最终完成

