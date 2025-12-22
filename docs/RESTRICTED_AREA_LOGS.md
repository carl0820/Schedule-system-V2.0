# 限行区域日志记录说明

## 如何判断限行区域生效和机器人前往等待点

### 1. 限行区域生效的日志

#### 1.1 机器人允许通行
```
[RESTRICTED AREA] Robot {robot_id} allowed to pass through restricted area {area_id} ({current_count}/{capacity})
```
- **含义**: 机器人被允许通过限行区域
- **位置**: `restricted_area_traffic_manager.py:527-530`
- **触发条件**: 机器人在限行区域内，且容量未满

#### 1.2 机器人需要等待
```
[RESTRICTED AREA] Robot {robot_id} needs to wait at waiting point for restricted area {area_id} (capacity: {capacity}, current: {current_count}, queue position: {position}/{total})
```
- **含义**: 机器人需要到等待点等待，因为限行区域容量已满
- **位置**: `restricted_area_traffic_manager.py:570-574`
- **触发条件**: 机器人在限行区域内，但容量已满

#### 1.3 容量超限警告
```
[RESTRICTED AREA] Area {area_id} capacity overflow: {current_count}/{capacity}, need to remove {overflow_count} robots, current robots: {robots_list}
```
- **含义**: 限行区域容量超限，需要让低优先级的机器人退出
- **位置**: `restricted_area_traffic_manager.py:748-751`
- **触发条件**: 多台机器人都在限行区内，但容量超限

### 2. 机器人前往等待点的日志

#### 2.1 需要移动到等待点
```
[RESTRICTED AREA] Robot {robot_id} needs to wait at waiting point ({x:.2f}, {y:.2f}) before executing task {task_id}
```
- **含义**: 机器人需要移动到等待点
- **位置**: `task_scheduler.py:1392-1395`
- **触发条件**: 限行区域容量已满，需要等待

#### 2.2 正在移动到等待点
```
[RESTRICTED AREA] Robot {robot_id} moving to waiting point, action_id={action_id}
```
- **含义**: 机器人正在移动到等待点
- **位置**: `task_scheduler.py:1413-1416`
- **触发条件**: 成功发送move_to指令到等待点

#### 2.3 等待点选择
```
[RESTRICTED AREA] Selected POI waiting point at ({x:.2f}, {y:.2f})
```
- **含义**: 选择了POI等待点
- **位置**: `restricted_area_traffic_manager.py:247-250`
- **触发条件**: 找到了合适的POI等待点

### 3. 机器人可以通行的日志

#### 3.1 可以通行
```
[RESTRICTED AREA] Robot {robot_id} can now pass through restricted area {area_id} (priority: {priority:.3f}, queue wait time: {wait_time:.1f}s, current: {current}/{capacity})
```
- **含义**: 等待的机器人现在可以通行了
- **位置**: `restricted_area_traffic_manager.py:673-678`
- **触发条件**: 限行区域有空位，等待队列中的机器人可以通行

#### 3.2 恢复任务
```
[RESTRICTED AREA] Robot {robot_id} can now pass through restricted area {area_id}, resuming task {task_id}
```
- **含义**: 机器人可以通行，恢复任务执行
- **位置**: `task_scheduler.py:1863-1866`
- **触发条件**: 机器人从等待队列中移除，可以继续执行任务

### 4. 机器人离开限行区域的日志

#### 4.1 释放占用
```
[RESTRICTED AREA] Robot {robot_id} released from restricted area {area_id}
```
- **含义**: 机器人已离开限行区域，释放占用
- **位置**: `restricted_area_traffic_manager.py:694-696`
- **触发条件**: 机器人离开限行区域

### 5. 容量超限处理的日志

#### 5.1 机器人被移除
```
[RESTRICTED AREA] Robot {robot_id} removed from area {area_id} due to capacity overflow (priority: {priority:.3f}, current: {current}/{capacity}), moving to waiting point
```
- **含义**: 机器人因容量超限被移除，移动到等待点
- **位置**: `restricted_area_traffic_manager.py:857-861`
- **触发条件**: 多台机器人都在限行区内，容量超限，低优先级机器人被移除

#### 5.2 机器人需要退出
```
[RESTRICTED AREA] Robot {robot_id} needs to exit over-capacity area {area_id} (current: {current_count}/{capacity}, overflow: {overflow_count}, robots to remove: {robots_list})
```
- **含义**: 机器人需要退出超容量的限行区域
- **位置**: `restricted_area_traffic_manager.py:481-485`
- **触发条件**: 容量超限，当前机器人优先级最低

### 6. 等待状态清除的日志

#### 6.1 不在限行区域内
```
[RESTRICTED AREA] Robot {robot_id} is not in any restricted area, but still in waiting status for area {area_id}, clearing waiting status
```
- **含义**: 机器人不在限行区域内，但还在等待状态中，清除等待状态
- **位置**: `restricted_area_traffic_manager.py:588-591`
- **触发条件**: 机器人不在限行区域内，但还有等待状态

## 日志搜索关键词

### 限行区域生效
- `[RESTRICTED AREA] Robot ... allowed to pass through`
- `[RESTRICTED AREA] Robot ... needs to wait at waiting point`
- `[RESTRICTED AREA] Area ... capacity overflow`

### 前往等待点
- `[RESTRICTED AREA] Robot ... needs to wait at waiting point`
- `[RESTRICTED AREA] Robot ... moving to waiting point`
- `[RESTRICTED AREA] Selected POI waiting point`

### 可以通行
- `[RESTRICTED AREA] Robot ... can now pass through`
- `[RESTRICTED AREA] Robot ... resuming task`

### 离开限行区域
- `[RESTRICTED AREA] Robot ... released from restricted area`

## 日志级别

- **INFO**: 正常流程日志（允许通行、需要等待、可以通行等）
- **WARNING**: 异常情况（容量超限、需要退出等）
- **ERROR**: 错误情况（找不到等待点、移动失败等）

## 查看日志的方法

1. **查看服务日志文件**: 通常在 `logs/` 目录下
2. **搜索关键词**: 使用 `[RESTRICTED AREA]` 搜索所有限行区域相关日志
3. **按机器人ID搜索**: 搜索 `Robot {robot_id}` 查看特定机器人的日志
4. **按限行区域ID搜索**: 搜索 `area {area_id}` 查看特定限行区域的日志

