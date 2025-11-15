"""
任务相关数据模型
"""
from pydantic import BaseModel
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
    """创建任务请求"""
    start_pose: Optional[Pose] = None  # 起点（可选，默认使用机器人当前位置）
    target_pose: Pose  # 终点
    priority: Optional[TaskPriority] = None  # 优先级（可选，如果不指定则自动计算）
    poi_name: Optional[str] = None  # 如果使用POI导航
    acceptable_precision: float = 0.3  # 到达精度（米）
    speed_ratio: float = 1.0  # 速度比例


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
    """创建多动作任务请求"""
    actions: List[ActionItem]  # 动作序列
    priority: Optional[TaskPriority] = None  # 优先级（可选，如果不指定则自动计算）
    start_pose: Optional[Pose] = None  # 起点（可选，默认使用机器人当前位置）


class Task(BaseModel):
    """任务信息"""
    task_id: str
    robot_id: Optional[str] = None
    status: TaskStatus
    start_pose: Optional[Pose]
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

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

