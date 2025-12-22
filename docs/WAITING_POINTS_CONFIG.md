# 等待点配置指南

## 配置文件位置

等待点配置在 `data/runtime_config.json` 文件中。

## 配置方式

### 方式1：POI等待点（推荐）

使用机器人已有的POI点作为等待点。这是推荐的方式，因为：
- POI点已经在机器人系统中配置好
- 位置准确，已经验证可达
- 便于管理和维护

**配置示例：**

```json
{
  "deadlock": {
    "poi_waiting_points": ["等待点1", "等待点2", "等待点3"],
    "use_poi_waiting_points": true
  }
}
```

**配置说明：**
- `poi_waiting_points`: POI名称列表，使用POI的 `display_name` 或 `id`
- `use_poi_waiting_points`: 是否优先使用POI等待点（默认 `true`）

**如何获取POI名称：**
1. 通过机器人API获取所有POI：`GET /api/core/artifact/v1/pois`
2. 查看POI的 `display_name` 或 `id` 字段
3. 将需要用作等待点的POI名称添加到配置中

### 方式2：预定义等待点

直接指定等待点的坐标。适用于：
- 没有配置POI点的情况
- 需要精确控制等待点位置的情况

**配置示例：**

```json
{
  "deadlock": {
    "predefined_waiting_points": [
      {
        "x": 10.0,
        "y": -5.0,
        "z": 0.0,
        "yaw": 0.0,
        "name": "等待点1-走廊东侧"
      },
      {
        "x": 15.0,
        "y": -3.0,
        "z": 0.0,
        "yaw": 1.57,
        "name": "等待点2-走廊西侧"
      }
    ],
    "use_predefined_waiting_points": true
  }
}
```

**字段说明：**
- `x`, `y` (必需): 等待点的X、Y坐标（米）
- `z` (可选，默认0.0): Z坐标（米）
- `yaw` (可选，默认0.0): 朝向（弧度）
- `name` (可选): 等待点名称（用于日志记录）

## 等待点选择优先级

系统按以下顺序选择等待点：

1. **POI等待点**（如果配置了 `poi_waiting_points` 且 `use_poi_waiting_points` 为 `true`）
2. **预定义等待点**（如果配置了 `predefined_waiting_points` 且 `use_predefined_waiting_points` 为 `true`）
3. **动态生成等待点**（如果前两者都不可用，系统会自动生成）

## 等待点选择条件

系统在选择等待点时会检查以下条件：

1. **不在限行区域内**：等待点不能在限行区域内或太靠近限行区域
2. **不在障碍物上**：等待点必须在可通行区域
3. **有足够空间**：等待点周围必须有足够的空间供机器人停留
4. **距离合适**：等待点距离机器人当前位置应在合理范围内

## 完整配置示例

```json
{
  "deadlock": {
    "deadlock_threshold": 10.0,
    "waiting_point_min_distance": 2.0,
    "waiting_point_max_distance": 6.0,
    
    "poi_waiting_points": ["等待点1", "等待点2"],
    "use_poi_waiting_points": true,
    
    "predefined_waiting_points": [
      {
        "x": 10.0,
        "y": -5.0,
        "z": 0.0,
        "yaw": 0.0,
        "name": "备用等待点1"
      }
    ],
    "use_predefined_waiting_points": true
  }
}
```

## 注意事项

1. **坐标系统**：确保等待点坐标使用与地图相同的坐标系统
2. **可达性**：确保等待点位置是机器人可以到达的（不在障碍物上）
3. **空间充足**：确保等待点周围有足够的空间供机器人停留
4. **定期检查**：如果地图发生变化，需要相应更新等待点配置
5. **限行区域**：等待点应该部署在限行区域旁边，但不在限行区域内

## 如何查看当前配置

查看 `data/runtime_config.json` 文件，检查 `deadlock` 节中的等待点配置。

## 日志记录

当系统使用等待点时，会在日志中记录：

```
[RESTRICTED AREA] Selected predefined waiting point (10.00, -5.00) for robot robot1
[RESTRICTED AREA] Loaded POI waiting point: 等待点1 at (10.00, -5.00)
```

