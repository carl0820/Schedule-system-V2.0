"""
任务相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from app.models.robot import Pose


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"  # 待分配
    ASSIGNED = "assigned"  # 已分配
    EXECUTING = "executing"  # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskPriority(int, Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TaskCreate(BaseModel):
    """创建任务请求
    
    注意：start_pose字段已废弃，系统会根据机器人当前位置自动分配任务，无需配置起始点。
    """
    # start_pose字段保留在模型中以保持向后兼容，但在Swagger UI中隐藏
    start_pose: Optional[Pose] = None
    target_pose: Pose  # 终点
    priority: Optional[TaskPriority] = None  # 优先级（可选，如果不指定则自动计算）
    poi_name: Optional[str] = None  # 如果使用POI导航
    acceptable_precision: float = 0.3  # 到达精度（米）
    speed_ratio: float = 1.0  # 速度比例
    
    class Config:
        # 从OpenAPI schema中排除start_pose字段
        fields = {
            'start_pose': {'exclude': True}
        }
        json_schema_extra = {
            "example": {
                "target_pose": {
                    "x": -16.58,
                    "y": 11.46,
                    "z": 0.0,
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "roll": 0.0
                },
                "priority": 2,
                "acceptable_precision": 0.3,
                "speed_ratio": 1.0
            }
        }


class ActionType(str, Enum):
    """动作类型"""
    MOVE_TO = "move_to"  # 移动到目标点
    WAIT = "wait"  # 等待
    GO_HOME = "go_home"  # 回桩


class ActionItem(BaseModel):
    """动作项"""
    action_type: ActionType  # 动作类型
    target_pose: Optional[Pose] = None  # 目标位置（move_to时使用）
    poi_name: Optional[str] = None  # POI名称（move_to时可选使用）
    poi_display_name: Optional[str] = None  # POI显示名称（move_to时可选使用，用于离线时显示）
    wait_duration: Optional[float] = None  # 等待时长（秒，wait时使用）
    acceptable_precision: float = 0.3  # 到达精度（米，move_to时使用）
    speed_ratio: float = 1.0  # 速度比例（move_to时使用）


class MultiActionTaskCreate(BaseModel):
    """创建多动作任务请求
    
    注意：start_pose字段已废弃，系统会根据机器人当前位置自动分配任务，无需配置起始点。
    """
    actions: List[ActionItem]  # 动作序列
    priority: Optional[TaskPriority] = None  # 优先级（可选，如果不指定则自动计算）
    # start_pose字段保留在模型中以保持向后兼容，但在Swagger UI中隐藏
    start_pose: Optional[Pose] = None
    
    class Config:
        # 从OpenAPI schema中排除start_pose字段
        fields = {
            'start_pose': {'exclude': True}
        }
        json_schema_extra = {
            "examples": [
                {
                    "summary": "移动到坐标并等待10秒（推荐）",
                    "description": "使用坐标导航，移动到指定位置后等待10秒。这是最简单可靠的方式。注意：不需要配置start_pose。",
                    "value": {
                        "actions": [
                            {
                                "action_type": "move_to",
                                "target_pose": {
                                    "x": 3.8,
                                    "y": -2.9,
                                    "z": 0.0,
                                    "yaw": 0.0,
                                    "pitch": 0.0,
                                    "roll": 0.0
                                },
                                "acceptable_precision": 0.3,
                                "speed_ratio": 1.0
                            },
                            {
                                "action_type": "wait",
                                "wait_duration": 10.0
                            }
                        ],
                        "priority": 1
                    }
                },
                {
                    "summary": "移动到POI并等待",
                    "description": "使用POI名称导航（需要先查询POI列表：GET /api/maps/pois）。如果POI不存在会失败。注意：不需要配置start_pose。",
                    "value": {
                        "actions": [
                            {
                                "action_type": "move_to",
                                "poi_name": "PO3",
                                "acceptable_precision": 0.3,
                                "speed_ratio": 1.0
                            },
                            {
                                "action_type": "wait",
                                "wait_duration": 10.0
                            }
                        ],
                        "priority": 1
                    }
                },
                {
                    "summary": "完整多动作任务：移动到POI -> 等待 -> 移动到另一个POI -> 回桩",
                    "description": "包含多个动作的完整任务示例：移动到POI、等待、移动到另一个POI、最后回桩。注意：不需要配置start_pose。",
                    "value": {
                        "actions": [
                            {
                                "action_type": "move_to",
                                "poi_name": "PO7",
                                "acceptable_precision": 0.3,
                                "speed_ratio": 1.0
                            },
                            {
                                "action_type": "wait",
                                "wait_duration": 60.0
                            },
                            {
                                "action_type": "move_to",
                                "poi_name": "P02",
                                "acceptable_precision": 0.3,
                                "speed_ratio": 1.0
                            },
                            {
                                "action_type": "go_home"
                            }
                        ],
                        "priority": 4
                    }
                }
            ]
        }


class TaskCreateResponse(BaseModel):
    """创建任务响应（简化版，明确返回task_id）"""
    task_id: str
    status: TaskStatus
    created_at: datetime
    message: str = "Task created successfully"
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Task(BaseModel):
    """任务信息"""
    task_id: str  # 任务ID（必需字段，会在响应中返回）
    robot_id: Optional[str] = None
    status: TaskStatus
    start_pose: Optional[Pose] = None
    target_pose: Pose
    priority: TaskPriority
    action_id: Optional[int] = None
    created_at: datetime
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    # 多动作任务相关字段
    is_multi_action: bool = False  # 是否为多动作任务
    actions: Optional[List[ActionItem]] = None  # 动作序列（多动作任务时使用）
    current_action_index: int = 0  # 当前执行的动作索引（多动作任务时使用）
    # 任务参数（从TaskCreate传递）
    acceptable_precision: float = 0.3  # 到达精度（米）
    speed_ratio: float = 1.0  # 速度比例
    poi_name: Optional[str] = None  # POI名称（如果使用POI导航）

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

