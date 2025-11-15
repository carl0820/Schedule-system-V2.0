"""
地图数据模型
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MapInfo(BaseModel):
    """地图信息模型"""
    map_id: str  # 唯一ID（UUID）
    name: str  # 地图名称（用户自定义）
    description: Optional[str] = None  # 地图描述
    robot_id: Optional[str] = None  # 来源机器人ID
    is_default: bool = False  # 是否为默认地图
    created_at: str  # 创建时间（ISO格式字符串）
    updated_at: str  # 更新时间（ISO格式字符串）
    file_path: str  # 地图文件存储路径
    thumbnail_path: Optional[str] = None  # 缩略图路径
    metadata: dict  # 地图元数据（width, height, resolution等）
    file_size: int  # 文件大小（字节）

