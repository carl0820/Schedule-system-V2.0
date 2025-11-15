# API缺失分析报告

## 一、已有API覆盖情况

### ✅ 已覆盖的功能

#### 1. 机器人状态获取
- ✅ **位置**：`GET /api/core/slam/v1/localization/pose` - 获取机器人位置坐标
- ✅ **姿态**：同上（包含pitch, roll, yaw）
- ✅ **速度（查询）**：`GET /api/core/motion/v1/speed` - 获取机器人速度
- ✅ **电量**：`GET /api/core/system/v1/power/status` - 获取电量状态
- ✅ **健康状态**：`GET /api/core/system/v1/robot/health` - 获取设备健康状态
- ✅ **设备信息**：`GET /api/core/system/v1/robot/info` - 获取设备信息SN和固件版本
- ✅ **定位质量**：`GET /api/core/slam/v1/localization/quality` - 获取定位质量

#### 2. 运动控制
- ✅ **目标点导航**：`POST /api/core/motion/v1/actions` (MoveToAction) - 创建运动行为
- ✅ **POI导航**：`POST /api/core/motion/v1/actions` (MultiFloorMoveAction) - 通过POI精确移动到点
- ✅ **回桩**：`POST /api/multi-floor/motion/v1/gohomeaction` - 回桩
- ✅ **任务状态查询**：`GET /api/core/motion/v1/actions/{action_id}` - 查询action状态
- ✅ **当前任务查询**：`GET /api/core/motion/v1/actions/:current` - 查询当前任务状态

#### 3. 传感器数据
- ✅ **IMU信息**：`GET /api/core/slam/v1/imu` - 获取IMU信息
- ✅ **里程计位姿**：`GET /api/core/slam/v1/localization/odopose` - 获取里程计位姿

#### 4. 地图管理
- ✅ **获取栅格地图**：`GET /api/core/slam/v1/maps/explore` - 获取栅格地图（二进制字节流）
- ✅ **同步地图**：`POST /api/multi-floor/map/v1/stcm/:sync` - 同步地图

#### 5. 其他功能
- ✅ **创建POI**：`POST /api/core/artifact/v1/pois` - 创建当前点POI

---

## 二、缺失的API

根据PRD.md的5.1节需求，以下API可能缺失：

### ❌ 1. 速度指令（发送速度）
**需求**：PRD.md 5.1节明确提到"速度指令"（运动控制部分）

**现状**：
- ✅ 已有：`GET /api/core/motion/v1/speed` - 查询速度
- ❌ 缺失：`POST /api/core/motion/v1/speed` - 设置速度指令

**建议补充**：
```http
POST /api/core/motion/v1/speed
Request Body:
{
  "vx": 0.5,      // 线速度 x 方向
  "vy": 0.0,      // 线速度 y 方向
  "omega": 0.1    // 角速度
}
```

**重要性**：⭐⭐⭐⭐⭐
- 碰撞避免模块可能需要直接控制机器人速度（减速、等待）
- PRD中提到"避让策略（等待、绕行、减速）"需要速度控制能力

---

### ❌ 2. 取消/停止任务
**需求**：PRD.md 2.1.3节提到"任务取消与重试机制"

**现状**：
- ✅ 已有：`GET /api/core/motion/v1/actions/{action_id}` - 查询action状态
- ❌ 缺失：`DELETE /api/core/motion/v1/actions/{action_id}` 或 `POST /api/core/motion/v1/actions/{action_id}/cancel` - 取消/停止任务

**建议补充**：
```http
DELETE /api/core/motion/v1/actions/{action_id}
或
POST /api/core/motion/v1/actions/{action_id}/cancel
Request Body: {}
```

**重要性**：⭐⭐⭐⭐⭐
- 任务调度模块需要取消任务的能力
- 碰撞避免时可能需要紧急停止某个任务
- PRD明确提到"任务取消与重试机制"

---

### ❌ 3. 激光雷达数据
**需求**：PRD.md 5.1节提到"传感器数据：激光雷达、里程计等（如有）"

**现状**：
- ✅ 已有：里程计位姿、IMU信息
- ✅ 已有：健康状态中有`hasLidarDisconnected`字段，可检测激光雷达是否断开
- ❌ 缺失：获取激光雷达点云/扫描数据的API

**建议补充**：
```http
GET /api/core/slam/v1/lidar/scan
或
GET /api/core/slam/v1/lidar/pointcloud
```

**重要性**：⭐⭐⭐
- 如果碰撞避免算法需要实时激光雷达数据，可能需要此API
- 但地图已经提供了障碍物信息，可能不需要实时激光雷达数据
- 建议：根据实际碰撞避免算法需求决定是否需要

---

### ❌ 4. 紧急停止
**需求**：PRD.md 7.2节提到"紧急停止所有机器人"

**现状**：
- ✅ 已有：健康状态中有`hasSystemEmergencyStop`字段，可检测是否处于紧急停止状态
- ❌ 缺失：设置紧急停止的API

**建议补充**：
```http
POST /api/core/system/v1/emergency/stop
Request Body: {}
或
POST /api/core/motion/v1/emergency/stop
Request Body: {}
```

**重要性**：⭐⭐⭐⭐
- 安全功能，PRD明确提到"紧急停止所有机器人"
- 用于紧急情况下的安全保护

---

### ❓ 5. 查询/列出所有POI
**需求**：POI管理功能

**现状**：
- ✅ 已有：`POST /api/core/artifact/v1/pois` - 创建POI
- ❌ 缺失：查询所有POI列表的API

**建议补充**：
```http
GET /api/core/artifact/v1/pois
响应：[
  {
    "id": "xxx",
    "metadata": {
      "display_name": "P01"
    },
    "position": {
      "x": 0.0,
      "y": 0.0,
      "yaw": 0.0
    }
  }
]
```

**重要性**：⭐⭐⭐
- 虽然不是PRD明确要求的，但对任务调度和路径规划可能有用
- 可以用于查询可用的导航点

---

## 三、总结

### 必须补充的API（优先级高）
1. **设置速度指令** - 碰撞避免需要
2. **取消/停止任务** - PRD明确要求

### 建议补充的API（优先级中）
3. **紧急停止** - 安全功能
4. **查询POI列表** - 功能完整性

### 可选补充的API（根据需求）
5. **激光雷达数据** - 如果碰撞避免算法需要实时激光雷达数据

---

## 四、建议

1. **优先确认**：速度指令和取消任务的API是否真的缺失，还是使用了其他方式（如通过action的speed_ratio参数控制速度）
2. **联系思岚科技技术支持**：确认是否有这些API，或者需要如何实现这些功能
3. **功能验证**：如果确实缺失，评估是否影响系统核心功能，决定是否需要寻找替代方案

