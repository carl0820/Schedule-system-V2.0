# Release v1.3.0

**Release Date:** 2025-11-17

## 🎉 Features

### 死锁检测与解锁机制增强
- **新增**: 详细的死锁检测日志系统
  - 添加 `[DETECT]`、`[UNLOCK]`、`[UNLOCK VERIFY]` 标签日志
  - 每5秒记录一次检测状态（机器人数量、执行中任务数、检测到的死锁数）
  - 记录死锁类型、涉及的机器人、持续时间等详细信息
  - 即使未超过阈值也会记录死锁状态，便于调试和验证

- **新增**: 死锁验证指南文档
  - `docs/DEADLOCK_VERIFICATION_GUIDE.md` - 详细的场景验证步骤
  - 包含4种典型死锁场景的验证方法
  - 提供日志查看命令和验证清单

### 地图管理功能增强
- **新增**: 地图切换后首页自动刷新
  - 在地图管理页面切换默认地图后，首页自动更新显示新地图
  - 支持跨标签页通信（localStorage + postMessage）
  - 地图ID跟踪机制，确保每次切换都能正确刷新

### 机器人管理功能增强
- **新增**: 机器人IP地址显示
  - 机器人列表详情页显示机器人的IP地址
  - 方便识别和管理不同机器人

- **新增**: 地图同步功能
  - 机器人列表详情页添加"同步地图"按钮
  - 调用 `/api/multi-floor/map/v1/stcm/:sync` API
  - 方便给对应的机器人做地图持久化保存

### 系统状态统计优化
- **优化**: 在线机器人统计逻辑
  - 在线机器人包含所有在线状态的机器人（idle、busy、error）
  - 故障机器人仍然计入在线数量，但不参与调度
  - 区分"在线正常"和"在线故障"两种状态

## 🐛 Bug Fixes

### 死锁检测日志问题
- **修复**: 死锁检测日志不输出的问题
  - 将关键检测日志从DEBUG级别改为INFO级别
  - 添加异常处理和详细错误日志
  - 确保检测循环正常运行时的日志可见性

### 地图切换问题
- **修复**: 第二次切换默认地图后首页地图不更新的问题
  - 添加地图ID跟踪机制（`lastMapId`）
  - 添加强制刷新标志（`forceMapRefresh`）
  - 直接比较地图ID，比hash更可靠
  - 统一地图变化处理函数

### 机器人健康状态判断
- **修复**: `baseError` 中特定错误码的过滤逻辑
  - 过滤 `errorCode: 17041920` 和 `17042176`（不影响使用的错误）
  - 这些错误仍会在机器人列表显示为"健康提醒"（黄色）
  - 但不影响机器人的调度状态

### 任务调度逻辑
- **修复**: 确保只有空闲（IDLE）机器人参与调度
  - 移除BUSY状态机器人参与调度的逻辑
  - 故障机器人（hasError、hasFatal、significant baseError）不参与调度
  - 确保调度逻辑更加严格和可靠

## 📚 Documentation

### 新增文档
- **死锁验证指南** (`docs/DEADLOCK_VERIFICATION_GUIDE.md`)
  - 死锁检测机制概述
  - 解锁机制流程说明
  - 4种典型场景的验证步骤
  - 日志查看命令和验证清单
  - 故障排查指南

## 🔧 Technical Improvements

### 代码优化
- **死锁检测器** (`app/services/deadlock_detector.py`)
  - 增强日志记录，添加INFO级别日志
  - 添加异常处理，确保检测循环不中断
  - 记录检测开始、检测结果、死锁状态等详细信息

- **任务调度器** (`app/services/task_scheduler.py`)
  - 添加死锁检测状态日志（每5秒记录一次）
  - 添加死锁解锁验证日志（`[UNLOCK VERIFY]`）
  - 优化调度逻辑，确保只有空闲机器人参与调度

- **地图管理器** (`app/services/map_manager.py`)
  - 在地图信息中添加 `map_id` 和 `map_name`
  - 确保前端能够识别当前地图并检测变化

- **前端优化** (`static/index.html`)
  - 添加地图ID跟踪机制
  - 添加强制刷新标志
  - 统一地图变化处理函数
  - 改进地图缓存键（包含地图ID）

- **机器人管理器** (`app/services/robot_manager.py`)
  - 在返回的机器人状态中包含 `base_url`（IP地址）
  - 优化机器人健康状态判断逻辑

- **API优化** (`app/api/robots.py`)
  - 新增 `/api/robots/{robot_id}/sync-map` 端点
  - 支持地图同步功能

## 📊 Statistics

- **修改文件**: 15个
- **新增代码**: 2806行
- **删除代码**: 390行
- **新增文档**: 1个

## 🎯 主要改进点

1. **死锁检测可见性**: 详细的日志系统，便于调试和验证死锁检测机制
2. **地图管理体验**: 地图切换后自动刷新，提升用户体验
3. **机器人管理**: IP地址显示和地图同步功能，方便运维管理
4. **系统状态统计**: 更准确的在线机器人统计和状态区分
5. **调度逻辑**: 更严格的调度条件，确保系统稳定性

## 🔄 升级建议

- **必须重启服务**: 本次更新包含后端代码修改，需要重启服务
- **刷新浏览器**: 前端页面有更新，建议清除缓存或硬刷新（Ctrl+F5）
- **查看日志**: 死锁检测日志现在更加详细，可以通过 `logs/deadlock.log` 查看
- **验证死锁机制**: 参考 `docs/DEADLOCK_VERIFICATION_GUIDE.md` 进行场景验证

## 🚀 使用新功能

### 查看死锁检测日志

```bash
# 实时查看死锁检测日志
tail -f logs/deadlock.log | grep "\[DETECT\]"

# 查看死锁解锁日志
tail -f logs/deadlock.log | grep "\[UNLOCK\]"

# 查看解锁验证日志
tail -f logs/deadlock.log | grep "\[UNLOCK VERIFY\]"
```

### 地图同步功能

1. 打开机器人列表页面
2. 找到需要同步地图的机器人
3. 点击"同步地图"按钮
4. 确认操作后，系统会调用地图同步API

### 地图切换

1. 打开地图管理页面
2. 选择要设为默认的地图
3. 点击"设为默认"按钮
4. 首页会自动刷新显示新地图

## 📦 Files Changed

### Backend
- `app/api/robots.py` - 新增地图同步API
- `app/api/visualization.py` - 优化机器人位置实时更新
- `app/services/deadlock_detector.py` - 增强日志和异常处理
- `app/services/map_manager.py` - 添加地图ID到返回信息
- `app/services/robot_manager.py` - 优化健康状态判断和IP地址返回
- `app/services/task_scheduler.py` - 优化调度逻辑和日志记录

### Frontend
- `static/index.html` - 地图切换自动刷新、实时位置优化
- `static/map_management.html` - 地图变化通知机制
- `static/robot_list.html` - IP地址显示、地图同步按钮、状态统计优化
- `static/deadlock_config.html` - 错误处理改进

### Documentation
- `docs/DEADLOCK_VERIFICATION_GUIDE.md` - 死锁验证指南

### Data
- `data/runtime_config.json` - 死锁配置参数更新
- `data/maps/` - 新增地图文件

## 🔗 Links

- **Repository**: https://github.com/carl0820/schedule-system-based-on-REST
- **API Documentation**: http://localhost:8000/docs
- **Deadlock Verification Guide**: `docs/DEADLOCK_VERIFICATION_GUIDE.md`

## 🙏 Acknowledgments

This release focuses on improving deadlock detection visibility, map management experience, and robot management functionality. All changes are backward compatible.

