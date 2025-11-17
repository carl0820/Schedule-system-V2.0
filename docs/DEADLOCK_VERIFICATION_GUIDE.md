# 死锁检测与解锁机制验证指南

## 一、死锁检测机制概述

### 1. 检测循环
- **频率**: 每0.5秒检测一次（2Hz）
- **启动条件**: 当有执行中或已分配的任务时自动启动
- **日志文件**: `logs/deadlock.log`

### 2. 检测的死锁类型

| 死锁类型 | 阈值 | 说明 |
|---------|------|------|
| **窄道死锁** | 2.0秒 | 多个机器人在窄道中相互阻塞 |
| **循环等待** | 10.0秒 | 机器人形成循环等待链 |
| **相互阻塞** | 3.0秒 | 两个或多个机器人面对面阻塞 |
| **资源竞争** | 5.0秒 | 单个机器人卡住 |
| **活锁** | 15.0秒 | 机器人持续移动但无进展 |
| **饥饿死锁** | 120.0秒 | 任务长时间等待分配 |

## 二、解锁机制流程

### 1. 死锁检测流程

```
检测循环启动
  ↓
更新机器人状态历史
  ↓
检测各种死锁类型
  ├─ 循环等待 (detect_circular_wait)
  ├─ 窄道死锁 (detect_narrow_passage_deadlock)
  ├─ 相互阻塞 (detect_mutual_blocking)
  └─ 其他类型...
  ↓
记录死锁状态（DeadlockState）
  ↓
检查持续时间是否超过阈值
  ↓
超过阈值 → 触发解锁
```

### 2. 解锁流程（以窄道死锁为例）

```
检测到死锁超过阈值
  ↓
[UNLOCK] Starting narrow passage deadlock resolution
  ↓
获取机器人任务优先级
  ↓
按优先级排序，选择低优先级机器人
  ↓
计算需要让行的机器人数量
  ├─ 1-3台: 让1台后退
  ├─ 4-5台: 让一半后退
  └─ 6+台: 让1/3后退
  ↓
查找等待点（find_waiting_point）
  ├─ 成功 → 移动到等待点
  └─ 失败 → 后退固定距离
  ↓
[UNLOCK] Robot moving to waiting point, action_id=xxx
  ↓
记录到 robots_in_deadlock_resolution
  ↓
等待机器人到达等待点
  ↓
[UNLOCK VERIFY] Robot reached waiting point
  ↓
恢复原任务执行
  ↓
[UNLOCK VERIFY] Task resumed successfully
```

## 三、日志标记说明

### 1. 检测阶段标记

- `[DETECT]`: 死锁检测过程
  - `[DETECT] Checking circular wait for N robots: [...]`
  - `[DETECT] Circular wait detected: robots [...]`
  - `[DETECT] Narrow passage deadlock detected: robots [...]`
  - `[DETECT] Mutual blocking detected: robots [...]`

### 2. 解锁阶段标记

- `[UNLOCK]`: 解锁执行过程
  - `[UNLOCK] Starting narrow passage deadlock resolution for robots: [...]`
  - `[UNLOCK] Robot moving to waiting point, action_id=xxx`
  - `[UNLOCK] Narrow passage deadlock resolved: N/M robots moved`

### 3. 验证阶段标记

- `[UNLOCK VERIFY]`: 解锁验证过程
  - `[UNLOCK VERIFY] Robot reached waiting point (distance=Xm < 0.5m)`
  - `[UNLOCK VERIFY] Resuming task XXX for robot YYY`
  - `[UNLOCK VERIFY] Task XXX resumed successfully, new action_id=ZZZ`

## 四、场景验证步骤

### 场景1: 窄道死锁（2台机器人）

**验证步骤**:
1. 创建2个任务，让2台机器人进入窄道（宽度<1.4米）
2. 观察日志，查找:
   ```
   [DETECT] Narrow passage deadlock detected: robots [robot1, robot2]
   ```
3. 等待2秒（超过阈值），查找:
   ```
   [UNLOCK] Starting narrow passage deadlock resolution for robots: [robot1, robot2]
   [UNLOCK] Narrow passage deadlock: robot X (priority=Y) moving to waiting point
   ```
4. 等待机器人到达等待点，查找:
   ```
   [UNLOCK VERIFY] Robot X reached waiting point (distance=0.XXm < 0.5m)
   [UNLOCK VERIFY] Task XXX resumed successfully
   ```

**验证要点**:
- ✅ 低优先级机器人被选中避让
- ✅ 机器人成功移动到等待点
- ✅ 原任务成功恢复执行

### 场景2: 相互阻塞死锁（2台机器人面对面）

**验证步骤**:
1. 创建2个任务，让2台机器人面对面接近（距离<0.5米）
2. 观察日志，查找:
   ```
   [DETECT] Mutual blocking detected: robots [robot1, robot2]
   ```
3. 等待3秒（超过阈值），查找:
   ```
   [UNLOCK] Starting mutual blocking deadlock resolution for robots: [robot1, robot2]
   [UNLOCK] Mutual blocking deadlock: robot X backing up 3.0m, action_id=xxx
   ```
4. 验证机器人成功后退

**验证要点**:
- ✅ 低优先级机器人被选中后退
- ✅ 机器人成功后退3米
- ✅ 死锁解除，其他机器人可以继续

### 场景3: 循环等待死锁（3台或更多机器人）

**验证步骤**:
1. 创建3个任务，形成循环等待链
2. 观察日志，查找:
   ```
   [DETECT] Circular wait detected: robots [robot1, robot2, robot3]
   ```
3. 等待10秒（超过阈值），查找:
   ```
   [UNLOCK] Circular wait deadlock: robot X backing up, action_id=xxx
   ```
4. 验证循环被打破

**验证要点**:
- ✅ 循环等待被正确检测
- ✅ 低优先级机器人被选中打破循环
- ✅ 循环被成功打破

### 场景4: 多机器人窄道死锁（4-8台机器人）

**验证步骤**:
1. 创建4-8个任务，让多台机器人进入窄道
2. 观察日志，查找:
   ```
   [DETECT] Narrow passage deadlock detected: robots [robot1, robot2, ...]
   ```
3. 验证让行策略:
   - 4-5台: 让一半后退
   - 6+台: 让1/3后退
4. 查找:
   ```
   [UNLOCK] Narrow passage deadlock resolved: N/M robots moved to waiting points
   ```

**验证要点**:
- ✅ 正确计算需要让行的机器人数量
- ✅ 多个机器人成功移动到等待点
- ✅ 死锁成功解除

## 五、日志查看命令

### 实时查看死锁日志
```bash
tail -f logs/deadlock.log
```

### 查看特定场景的日志
```bash
# 查看检测日志
grep "\[DETECT\]" logs/deadlock.log

# 查看解锁日志
grep "\[UNLOCK\]" logs/deadlock.log

# 查看验证日志
grep "\[UNLOCK VERIFY\]" logs/deadlock.log

# 查看特定机器人的日志
grep "robot1" logs/deadlock.log
```

### 查看完整的解锁流程
```bash
# 查看从检测到验证的完整流程
grep -E "\[DETECT\]|\[UNLOCK\]|\[UNLOCK VERIFY\]" logs/deadlock.log | tail -50
```

## 六、验证检查清单

### 检测阶段
- [ ] 死锁检测循环已启动（查看日志中的"Deadlock check loop started"）
- [ ] 配置已加载（查看"Deadlock config loaded"）
- [ ] 检测到死锁时记录 `[DETECT]` 日志
- [ ] 死锁持续时间正确计算

### 解锁阶段
- [ ] 超过阈值后触发解锁（查看 `[UNLOCK] Starting ...`）
- [ ] 正确选择低优先级机器人
- [ ] 机器人成功发送移动指令（有action_id）
- [ ] 记录到 `robots_in_deadlock_resolution`

### 验证阶段
- [ ] 机器人到达等待点后记录 `[UNLOCK VERIFY] Robot reached waiting point`
- [ ] 任务成功恢复（查看 `[UNLOCK VERIFY] Task resumed successfully`）
- [ ] 新的action_id已更新
- [ ] 任务状态为EXECUTING

## 七、常见问题排查

### 问题1: 死锁检测循环未启动
**检查**:
- 是否有执行中的任务
- 查看主日志是否有错误
- 检查 `_deadlock_check_task` 是否已创建

### 问题2: 检测到死锁但未触发解锁
**检查**:
- 死锁持续时间是否超过阈值
- 查看日志中的 `duration` 和 `threshold` 值
- 检查配置是否正确加载

### 问题3: 解锁后任务未恢复
**检查**:
- 机器人是否到达等待点（距离<0.5米）
- 查看 `[UNLOCK VERIFY]` 日志
- 检查任务状态是否正确更新
- 查看是否有超时强制恢复的日志

### 问题4: 多个机器人未同时解锁
**检查**:
- 查看解锁日志中的 `N/M robots moved`
- 检查是否有机器人解锁失败的错误日志
- 验证让行策略是否正确执行

## 八、性能指标

### 检测性能
- **检测频率**: 2Hz（每0.5秒）
- **检测延迟**: <0.5秒
- **阈值响应**: 窄道死锁2秒，相互阻塞3秒

### 解锁性能
- **解锁触发**: 超过阈值后立即触发
- **移动时间**: 取决于等待点距离和机器人速度
- **任务恢复**: 到达等待点后立即恢复（<0.5秒检测）

## 九、配置参数

关键配置参数（可在 `deadlock_config.html` 页面修改）:

- `narrow_passage_deadlock_threshold`: 2.0秒（窄道死锁触发阈值）
- `narrow_passage_detection_distance`: 3.0米（检测距离）
- `narrow_passage_backoff_distance`: 3.0米（后退距离）
- `mutual_blocking_deadlock_threshold`: 3.0秒（相互阻塞触发阈值）
- `circular_wait_deadlock_threshold`: 10.0秒（循环等待触发阈值）

## 十、测试建议

1. **单场景测试**: 逐个测试每种死锁类型
2. **多场景测试**: 同时触发多种死锁类型
3. **压力测试**: 8台机器人同时进入窄道
4. **边界测试**: 测试阈值边界情况
5. **恢复测试**: 验证任务恢复机制

