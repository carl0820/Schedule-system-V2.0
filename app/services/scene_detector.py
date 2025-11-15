"""
场景检测模块 - 识别十字路口和长走廊等特殊场景
"""
import math
import logging
from typing import List, Tuple, Optional, Dict
from enum import Enum
from app.models.robot import Pose
from app.services.map_manager import MapManager
from app.services.path_planner import PathPlanner
from config import settings

logger = logging.getLogger(__name__)


class SceneType(str, Enum):
    """场景类型"""
    NORMAL = "normal"  # 普通场景
    INTERSECTION = "intersection"  # 十字路口
    CORRIDOR = "corridor"  # 长走廊
    NARROW_PASSAGE = "narrow_passage"  # 窄道


class SceneInfo:
    """场景信息"""
    
    def __init__(
        self,
        scene_type: SceneType,
        center: Pose,
        radius: float = 0.0,
        width: float = 0.0,
        length: float = 0.0,
        direction: float = 0.0  # 走廊方向（弧度）
    ):
        self.scene_type = scene_type
        self.center = center
        self.radius = radius
        self.width = width
        self.length = length
        self.direction = direction


class SceneDetector:
    """场景检测器，识别十字路口和长走廊等特殊场景"""
    
    def __init__(
        self,
        map_manager: MapManager,
        path_planner: PathPlanner
    ):
        """
        初始化场景检测器
        
        Args:
            map_manager: 地图管理器
            path_planner: 路径规划器
        """
        self.map_manager = map_manager
        self.path_planner = path_planner
        self.intersection_radius = settings.INTERSECTION_DETECTION_RADIUS
        self.corridor_width_threshold = settings.CORRIDOR_DETECTION_WIDTH
        self.corridor_length_threshold = settings.CORRIDOR_DETECTION_LENGTH
    
    def detect_intersection(self, pose: Pose, radius: float = None) -> Optional[SceneInfo]:
        """
        检测是否为十字路口
        
        十字路口特征：
        1. 周围有4个或更多方向的通道
        2. 每个方向的通道宽度都较大
        3. 中心区域相对开阔
        
        Args:
            pose: 检测位置
            radius: 检测半径（默认使用配置值）
            
        Returns:
            场景信息，如果不是十字路口则返回None
        """
        if radius is None:
            radius = self.intersection_radius
        
        # 检查4个主要方向（上下左右）的通道数量
        directions = [
            (0, 1),   # 上
            (0, -1),  # 下
            (1, 0),   # 右
            (-1, 0)   # 左
        ]
        
        valid_directions = 0
        passage_widths = []
        
        for dx, dy in directions:
            # 检查该方向的通道宽度
            # 计算该方向上的一个点
            check_x = pose.x + dx * radius
            check_y = pose.y + dy * radius
            
            width = self.path_planner.calculate_passage_width(check_x, check_y, settings.ROBOT_ROTATION_RADIUS)
            
            if width > self.corridor_width_threshold:
                valid_directions += 1
                passage_widths.append(width)
        
        # 如果至少有3个方向的通道宽度都较大，认为是十字路口
        if valid_directions >= 3:
            # 计算中心区域的宽度（取最小值）
            center_width = min(passage_widths) if passage_widths else 0.0
            
            return SceneInfo(
                scene_type=SceneType.INTERSECTION,
                center=pose,
                radius=radius,
                width=center_width
            )
        
        return None
    
    def detect_corridor(
        self,
        pose: Pose,
        direction: float,
        check_length: float = None
    ) -> Optional[SceneInfo]:
        """
        检测是否为长走廊
        
        长走廊特征：
        1. 在某个方向上通道很长
        2. 垂直方向的宽度较小
        3. 机器人沿走廊方向移动
        
        Args:
            pose: 检测位置
            direction: 移动方向（弧度）
            check_length: 检查长度（默认使用配置值）
            
        Returns:
            场景信息，如果不是长走廊则返回None
        """
        if check_length is None:
            check_length = self.corridor_length_threshold
        
        # 检查沿移动方向的通道长度
        # 计算前后两个检查点
        forward_x = pose.x + math.cos(direction) * check_length
        forward_y = pose.y + math.sin(direction) * check_length
        backward_x = pose.x - math.cos(direction) * check_length
        backward_y = pose.y - math.sin(direction) * check_length
        
        # 检查前后方向的通道宽度
        forward_width = self.path_planner.calculate_passage_width(
            forward_x, forward_y, settings.ROBOT_ROTATION_RADIUS
        )
        backward_width = self.path_planner.calculate_passage_width(
            backward_x, backward_y, settings.ROBOT_ROTATION_RADIUS
        )
        
        # 检查垂直方向的宽度（应该较小）
        perp_direction = direction + math.pi / 2
        perp_x = pose.x + math.cos(perp_direction) * 1.0
        perp_y = pose.y + math.sin(perp_direction) * 1.0
        perp_width = self.path_planner.calculate_passage_width(
            perp_x, perp_y, settings.ROBOT_ROTATION_RADIUS
        )
        
        # 如果前后方向通道宽度较大，且垂直方向宽度较小，认为是长走廊
        min_forward_backward = min(forward_width, backward_width)
        if (min_forward_backward >= self.corridor_length_threshold and
            perp_width < self.corridor_width_threshold):
            
            # 计算走廊的实际宽度（取垂直方向宽度）
            corridor_width = perp_width if perp_width > 0 else min_forward_backward
            
            return SceneInfo(
                scene_type=SceneType.CORRIDOR,
                center=pose,
                width=corridor_width,
                length=min_forward_backward,
                direction=direction
            )
        
        return None
    
    def detect_scene(
        self,
        pose: Pose,
        direction: Optional[float] = None
    ) -> SceneInfo:
        """
        检测当前位置的场景类型
        
        Args:
            pose: 检测位置
            direction: 移动方向（可选，用于长走廊检测）
            
        Returns:
            场景信息
        """
        # 先检测十字路口
        intersection = self.detect_intersection(pose)
        if intersection:
            return intersection
        
        # 如果有方向信息，检测长走廊
        if direction is not None:
            corridor = self.detect_corridor(pose, direction)
            if corridor:
                return corridor
        
        # 检测窄道
        width = self.path_planner.calculate_passage_width(
            pose.x, pose.y, settings.ROBOT_ROTATION_RADIUS
        )
        if width > 0 and width < 1.0:  # 宽度小于1米认为是窄道
            return SceneInfo(
                scene_type=SceneType.NARROW_PASSAGE,
                center=pose,
                width=width
            )
        
        # 默认普通场景
        return SceneInfo(
            scene_type=SceneType.NORMAL,
            center=pose
        )
    
    def is_robot_in_intersection(self, robot_pose: Pose) -> bool:
        """
        判断机器人是否在十字路口
        
        Args:
            robot_pose: 机器人位置
            
        Returns:
            是否在十字路口
        """
        scene = self.detect_scene(robot_pose)
        return scene.scene_type == SceneType.INTERSECTION
    
    def is_robot_in_corridor(self, robot_pose: Pose, direction: float) -> bool:
        """
        判断机器人是否在长走廊
        
        Args:
            robot_pose: 机器人位置
            direction: 移动方向
            
        Returns:
            是否在长走廊
        """
        scene = self.detect_scene(robot_pose, direction)
        return scene.scene_type == SceneType.CORRIDOR
    
    def calculate_yield_point(
        self,
        robot_pose: Pose,
        corridor_direction: float,
        distance: float = None
    ) -> Optional[Pose]:
        """
        计算长走廊中的让行等待点
        
        Args:
            robot_pose: 机器人当前位置
            corridor_direction: 走廊方向
            distance: 等待点距离（默认使用配置值）
            
        Returns:
            等待点位置，如果无法计算则返回None
        """
        if distance is None:
            distance = settings.CORRIDOR_WAIT_POINT_DISTANCE
        
        # 计算垂直于走廊方向的偏移
        perp_direction = corridor_direction + math.pi / 2
        
        # 尝试在走廊两侧寻找等待点
        for side in [-1, 1]:
            offset_x = math.cos(perp_direction) * distance * side
            offset_y = math.sin(perp_direction) * distance * side
            
            wait_x = robot_pose.x + offset_x
            wait_y = robot_pose.y + offset_y
            
            # 检查等待点是否有效
            if self.map_manager.is_valid_coordinate(wait_x, wait_y):
                if not self.map_manager.is_obstacle(wait_x, wait_y):
                    return Pose(
                        x=wait_x,
                        y=wait_y,
                        z=robot_pose.z,
                        yaw=robot_pose.yaw
                    )
        
        return None

