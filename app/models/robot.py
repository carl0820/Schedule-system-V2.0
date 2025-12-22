"""
机器人相关数据模型
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class RobotStatus(str, Enum):
    """机器人状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"


class Pose(BaseModel):
    """位置和姿态"""
    x: float
    y: float
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


class Speed(BaseModel):
    """速度信息"""
    vx: float = 0.0
    vy: float = 0.0
    omega: float = 0.0


class PowerStatus(BaseModel):
    """电量状态"""
    batteryPercentage: int
    dockingStatus: str
    isCharging: bool
    isDCConnected: bool
    powerStage: str
    sleepMode: str


class HealthStatus(BaseModel):
    """健康状态"""
    hasError: bool
    hasFatal: bool
    hasWarning: bool
    hasLidarDisconnected: bool
    hasDepthCameraDisconnected: bool
    hasSdpDisconnected: bool
    hasSystemEmergencyStop: bool
    baseError: List[Dict[str, Any]] = []


class RobotInfo(BaseModel):
    """机器人信息"""
    deviceID: str
    device_id: str
    hardwareVersion: str
    softwareVersion: str
    modelName: str
    manufacturerName: str


class RobotState(BaseModel):
    """机器人完整状态"""
    robot_id: str
    status: RobotStatus
    pose: Pose
    speed: Speed
    power: PowerStatus
    health: HealthStatus
    info: Optional[RobotInfo] = None
    localization_quality: Optional[int] = None
    current_action_id: Optional[int] = None
    last_update_time: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ActionState(BaseModel):
    """Action状态"""
    action_id: int
    action_name: Optional[str] = None
    stage: Optional[str] = None
    state: Dict[str, Any]
    reason: Optional[str] = None
    result: Optional[int] = None  # 0:Success, -1:Failed, -2:Aborted
    status: Optional[int] = None  # 0:NewBorn, 1:Working, 3:Paused, 4:Done


class POI(BaseModel):
    """兴趣点"""
    id: str
    metadata: Dict[str, Any]
    pose: Optional[Pose] = None


class VirtualWall(BaseModel):
    """虚拟墙"""
    id: int
    start: Dict[str, float]  # {"x": float, "y": float}
    end: Dict[str, float]   # {"x": float, "y": float}
    metadata: Optional[Dict[str, Any]] = None


class RestrictedArea(BaseModel):
    """限行区域"""
    id: int
    area: Dict[str, Any]  # 包含 start, end, half_width
    metadata: Optional[Dict[str, Any]] = None
    usage: str  # 通常为 "restricted_area"


class LaserScan(BaseModel):
    """激光雷达扫描数据"""
    pose: Pose
    laser_points: List[Dict[str, Any]]


class RegisterRequest(BaseModel):
    """注册机器人请求"""
    robot_id: str
    base_url: str

