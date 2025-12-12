"""
区域锁管理器 - 管理关键区域的互斥访问
"""
import asyncio
import math
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from app.models.robot import Pose
from app.services.scene_detector import SceneDetector, SceneType

logger = logging.getLogger(__name__)


class AreaType(str, Enum):
    """区域类型"""
    NARROW_PASSAGE = "narrow_passage"  # 窄道
    INTERSECTION = "intersection"  # 交叉口
    BOTTLENECK = "bottleneck"  # 瓶颈区域
    CUSTOM = "custom"  # 自定义区域


@dataclass
class AreaLock:
    """区域锁"""
    area_id: str  # 区域ID（基于坐标网格）
    area_type: AreaType  # 区域类型
    center: Pose  # 区域中心位置
    radius: float  # 区域半径（米）
    robot_id: Optional[str] = None  # 持有锁的机器人ID
    lock_time: Optional[datetime] = None  # 锁定时间
    timeout: float = 30.0  # 超时时间（秒）
    waiting_queue: List[str] = field(default_factory=list)  # 等待队列（机器人ID列表）


class AreaLockManager:
    """区域锁管理器"""
    
    def __init__(
        self,
        scene_detector: Optional[SceneDetector] = None,
        lock_timeout: float = 30.0,
        detection_radius: float = 3.0
    ):
        """
        初始化区域锁管理器
        
        Args:
            scene_detector: 场景检测器（用于识别关键区域）
            lock_timeout: 锁超时时间（秒）
            detection_radius: 检测半径（米），机器人距离区域多远时开始检测
        """
        self.scene_detector = scene_detector
        self.lock_timeout = lock_timeout
        self.detection_radius = detection_radius
        
        # 区域锁字典：area_id -> AreaLock
        self.area_locks: Dict[str, AreaLock] = {}
        
        # 机器人当前持有的锁：robot_id -> List[area_id]
        self.robot_locks: Dict[str, List[str]] = {}
        
        # 锁操作锁（防止并发问题）
        self._lock = asyncio.Lock()
        
        # 网格大小（用于生成区域ID）
        self.grid_size = 0.5  # 0.5米网格
        
        logger.info(f"AreaLockManager initialized: lock_timeout={lock_timeout}s, detection_radius={detection_radius}m")
    
    def _generate_area_id(self, pose: Pose, area_type: AreaType) -> str:
        """
        生成区域ID（基于坐标网格）
        
        Args:
            pose: 位置
            area_type: 区域类型
            
        Returns:
            区域ID
        """
        # 将坐标映射到网格
        grid_x = int(pose.x / self.grid_size)
        grid_y = int(pose.y / self.grid_size)
        
        return f"{area_type.value}_{grid_x}_{grid_y}"
    
    def _calculate_distance(self, pose1: Pose, pose2: Pose) -> float:
        """计算两点距离"""
        dx = pose1.x - pose2.x
        dy = pose1.y - pose2.y
        return math.sqrt(dx * dx + dy * dy)
    
    async def detect_critical_area(
        self,
        pose: Pose,
        direction: Optional[float] = None
    ) -> Optional[AreaLock]:
        """
        检测当前位置是否为关键区域
        
        Args:
            pose: 机器人当前位置
            direction: 移动方向（可选）
            
        Returns:
            如果是关键区域，返回AreaLock对象，否则返回None
        """
        if not self.scene_detector:
            return None
        
        # 检测场景类型
        scene_info = self.scene_detector.detect_scene(pose, direction)
        
        if scene_info.scene_type == SceneType.NARROW_PASSAGE:
            # 窄道区域
            area_id = self._generate_area_id(pose, AreaType.NARROW_PASSAGE)
            radius = 1.0  # 窄道区域半径1米
            
            if area_id not in self.area_locks:
                self.area_locks[area_id] = AreaLock(
                    area_id=area_id,
                    area_type=AreaType.NARROW_PASSAGE,
                    center=pose,
                    radius=radius,
                    timeout=self.lock_timeout
                )
            
            return self.area_locks[area_id]
        
        elif scene_info.scene_type == SceneType.INTERSECTION:
            # 交叉口区域
            area_id = self._generate_area_id(pose, AreaType.INTERSECTION)
            radius = scene_info.radius if scene_info.radius > 0 else 2.0
            
            if area_id not in self.area_locks:
                self.area_locks[area_id] = AreaLock(
                    area_id=area_id,
                    area_type=AreaType.INTERSECTION,
                    center=scene_info.center,
                    radius=radius,
                    timeout=self.lock_timeout
                )
            
            return self.area_locks[area_id]
        
        return None
    
    async def try_acquire_lock(
        self,
        robot_id: str,
        pose: Pose,
        direction: Optional[float] = None
    ) -> Tuple[bool, Optional[AreaLock], Optional[str]]:
        """
        尝试获取区域锁
        
        Args:
            robot_id: 机器人ID
            pose: 机器人当前位置
            direction: 移动方向（可选）
            
        Returns:
            (是否成功, AreaLock对象, 错误信息)
        """
        async with self._lock:
            # 检测是否为关键区域
            area_lock = await self.detect_critical_area(pose, direction)
            
            if not area_lock:
                # 不是关键区域，不需要锁
                return True, None, None
            
            # 检查是否已经持有锁
            if area_lock.robot_id == robot_id:
                return True, area_lock, None
            
            # 检查锁是否被其他机器人持有
            if area_lock.robot_id is not None:
                # 检查锁是否超时
                if area_lock.lock_time:
                    elapsed = (datetime.now() - area_lock.lock_time).total_seconds()
                    if elapsed > area_lock.timeout:
                        logger.warning(
                            f"Area lock {area_lock.area_id} timeout ({elapsed:.1f}s > {area_lock.timeout}s), "
                            f"releasing from robot {area_lock.robot_id}"
                        )
                        await self._release_lock_internal(area_lock.robot_id, area_lock.area_id)
                    else:
                        # 锁被占用且未超时，加入等待队列
                        if robot_id not in area_lock.waiting_queue:
                            area_lock.waiting_queue.append(robot_id)
                            logger.info(
                                f"Robot {robot_id} waiting for area lock {area_lock.area_id} "
                                f"(held by {area_lock.robot_id}, {len(area_lock.waiting_queue)} robots waiting)"
                            )
                        return False, area_lock, f"Area locked by robot {area_lock.robot_id}"
            
            # 锁可用，获取锁
            area_lock.robot_id = robot_id
            area_lock.lock_time = datetime.now()
            
            # 记录机器人持有的锁
            if robot_id not in self.robot_locks:
                self.robot_locks[robot_id] = []
            if area_lock.area_id not in self.robot_locks[robot_id]:
                self.robot_locks[robot_id].append(area_lock.area_id)
            
            logger.info(
                f"Robot {robot_id} acquired area lock {area_lock.area_id} "
                f"({area_lock.area_type.value})"
            )
            
            return True, area_lock, None
    
    async def check_and_acquire_lock(
        self,
        robot_id: str,
        pose: Pose,
        direction: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        检查并获取区域锁（如果接近关键区域）
        
        当机器人接近关键区域时（距离 < detection_radius），尝试获取锁
        
        Args:
            robot_id: 机器人ID
            pose: 机器人当前位置
            direction: 移动方向（可选）
            
        Returns:
            (是否成功, 错误信息)
        """
        # 检查是否接近已存在的关键区域
        async with self._lock:
            for area_id, area_lock in self.area_locks.items():
                distance = self._calculate_distance(pose, area_lock.center)
                
                # 如果距离关键区域小于检测半径，尝试获取锁
                if distance < (area_lock.radius + self.detection_radius):
                    logger.info(
                        f"Robot {robot_id} approaching existing area lock {area_id} "
                        f"({area_lock.area_type.value}) at distance {distance:.2f}m"
                    )
                    success, lock_obj, error = await self.try_acquire_lock(robot_id, pose, direction)
                    if not success:
                        logger.warning(
                            f"Robot {robot_id} cannot acquire area lock {area_id}: {error}"
                        )
                        return False, error
                    return True, None
        
        # 检测新的关键区域
        success, lock_obj, error = await self.try_acquire_lock(robot_id, pose, direction)
        if lock_obj:
            logger.info(
                f"Robot {robot_id} detected new critical area {lock_obj.area_id} "
                f"({lock_obj.area_type.value}) at ({pose.x:.2f}, {pose.y:.2f})"
            )
        return success, error
    
    async def release_lock(self, robot_id: str, area_id: Optional[str] = None):
        """
        释放区域锁
        
        Args:
            robot_id: 机器人ID
            area_id: 区域ID（如果为None，释放该机器人的所有锁）
        """
        async with self._lock:
            if area_id:
                await self._release_lock_internal(robot_id, area_id)
            else:
                # 释放该机器人的所有锁
                if robot_id in self.robot_locks:
                    area_ids = self.robot_locks[robot_id].copy()
                    for aid in area_ids:
                        await self._release_lock_internal(robot_id, aid)
    
    async def _release_lock_internal(self, robot_id: str, area_id: str):
        """内部方法：释放锁（需要在锁内调用）"""
        if area_id not in self.area_locks:
            return
        
        area_lock = self.area_locks[area_id]
        
        if area_lock.robot_id != robot_id:
            logger.warning(
                f"Robot {robot_id} tried to release lock {area_id} "
                f"but it's held by {area_lock.robot_id}"
            )
            return
        
        # 释放锁
        area_lock.robot_id = None
        area_lock.lock_time = None
        
        # 从机器人锁列表中移除
        if robot_id in self.robot_locks:
            if area_id in self.robot_locks[robot_id]:
                self.robot_locks[robot_id].remove(area_id)
        
        # 如果有等待队列，让下一个机器人获取锁
        if area_lock.waiting_queue:
            next_robot_id = area_lock.waiting_queue.pop(0)
            area_lock.robot_id = next_robot_id
            area_lock.lock_time = datetime.now()
            
            if next_robot_id not in self.robot_locks:
                self.robot_locks[next_robot_id] = []
            self.robot_locks[next_robot_id].append(area_id)
            
            logger.info(
                f"Area lock {area_id} released by {robot_id}, "
                f"acquired by waiting robot {next_robot_id}"
            )
        else:
            logger.info(f"Area lock {area_id} released by {robot_id}")
    
    async def check_lock_timeout(self):
        """检查并释放超时的锁（定期调用）"""
        async with self._lock:
            now = datetime.now()
            timeout_locks = []
            
            for area_id, area_lock in self.area_locks.items():
                if area_lock.robot_id and area_lock.lock_time:
                    elapsed = (now - area_lock.lock_time).total_seconds()
                    if elapsed > area_lock.timeout:
                        timeout_locks.append((area_lock.robot_id, area_id))
            
            for robot_id, area_id in timeout_locks:
                logger.warning(
                    f"Area lock {area_id} timeout, releasing from robot {robot_id}"
                )
                await self._release_lock_internal(robot_id, area_id)
    
    def get_lock_status(self, area_id: str) -> Optional[Dict]:
        """获取锁状态（用于调试）"""
        if area_id not in self.area_locks:
            return None
        
        area_lock = self.area_locks[area_id]
        return {
            "area_id": area_id,
            "area_type": area_lock.area_type.value,
            "robot_id": area_lock.robot_id,
            "lock_time": area_lock.lock_time.isoformat() if area_lock.lock_time else None,
            "waiting_queue": area_lock.waiting_queue.copy(),
            "center": {
                "x": area_lock.center.x,
                "y": area_lock.center.y
            },
            "radius": area_lock.radius
        }

