"""
碰撞检测模块
"""
import math
import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from app.models.robot import Pose, Speed
from app.services.robot_manager import RobotManager
from config import settings

logger = logging.getLogger(__name__)


class CollisionPrediction:
    """碰撞预测结果"""
    
    def __init__(
        self,
        robot_id1: str,
        robot_id2: str,
        collision_time: float,
        collision_point: Pose,
        severity: str = "warning"  # "warning", "critical"
    ):
        self.robot_id1 = robot_id1
        self.robot_id2 = robot_id2
        self.collision_time = collision_time  # 预测碰撞时间（秒）
        self.collision_point = collision_point  # 碰撞点位置
        self.severity = severity  # 严重程度


class CollisionDetector:
    """碰撞检测器，用于检测多机器人之间的潜在碰撞"""
    
    def __init__(self, robot_manager: RobotManager):
        """
        初始化碰撞检测器
        
        Args:
            robot_manager: 机器人管理器
        """
        self.robot_manager = robot_manager
        self.prediction_window = settings.COLLISION_PREDICTION_WINDOW
        self.safety_distance = settings.COLLISION_SAFETY_DISTANCE
        self.detection_frequency = settings.COLLISION_DETECTION_FREQUENCY
        self.robot_radius = settings.ROBOT_RADIUS  # 机器人半径（米）
        self.robot_rotation_radius = settings.ROBOT_ROTATION_RADIUS  # 机器人旋转半径（米）
    
    def predict_robot_position(
        self,
        current_pose: Pose,
        current_speed: Speed,
        time_delta: float
    ) -> Pose:
        """
        预测机器人在未来某个时刻的位置
        
        Args:
            current_pose: 当前位置
            current_speed: 当前速度
            time_delta: 时间差（秒）
            
        Returns:
            预测的位置
        """
        # 简化的运动模型：假设机器人以当前速度直线运动
        # 实际应用中可以使用更复杂的运动模型
        
        # 计算位移
        dx = current_speed.vx * time_delta * math.cos(current_pose.yaw)
        dy = current_speed.vx * time_delta * math.sin(current_pose.yaw)
        
        # 计算新的朝向（考虑角速度）
        new_yaw = current_pose.yaw + current_speed.omega * time_delta
        
        return Pose(
            x=current_pose.x + dx,
            y=current_pose.y + dy,
            z=current_pose.z,
            yaw=new_yaw,
            pitch=current_pose.pitch,
            roll=current_pose.roll
        )
    
    def predict_robot_trajectory(
        self,
        current_pose: Pose,
        current_speed: Speed,
        time_window: float,
        num_points: int = 20
    ) -> List[Pose]:
        """
        预测机器人轨迹
        
        Args:
            current_pose: 当前位置
            current_speed: 当前速度
            time_window: 时间窗口（秒）
            num_points: 预测点数量
            
        Returns:
            预测轨迹点列表
        """
        trajectory = []
        dt = time_window / num_points
        
        current = current_pose
        for i in range(num_points):
            t = (i + 1) * dt
            predicted = self.predict_robot_position(current_pose, current_speed, t)
            trajectory.append(predicted)
            current = predicted
        
        return trajectory
    
    def calculate_distance(self, pose1: Pose, pose2: Pose) -> float:
        """计算两点之间的距离"""
        dx = pose1.x - pose2.x
        dy = pose1.y - pose2.y
        return math.sqrt(dx * dx + dy * dy)
    
    def check_collision(
        self,
        pose1: Pose,
        pose2: Pose,
        radius1: float = None,
        radius2: float = None,
        use_rotation_radius: bool = True
    ) -> bool:
        """
        检查两个位置是否会发生碰撞
        
        Args:
            pose1: 机器人1的位置
            pose2: 机器人2的位置
            radius1: 机器人1的半径（默认使用旋转半径）
            radius2: 机器人2的半径（默认使用旋转半径）
            use_rotation_radius: 是否使用旋转半径（考虑机器人旋转空间）
            
        Returns:
            是否会发生碰撞
        """
        if radius1 is None:
            radius1 = self.robot_rotation_radius if use_rotation_radius else self.robot_radius
        if radius2 is None:
            radius2 = self.robot_rotation_radius if use_rotation_radius else self.robot_radius
        
        distance = self.calculate_distance(pose1, pose2)
        min_distance = radius1 + radius2 + self.safety_distance
        
        return distance < min_distance
    
    async def detect_collisions(
        self,
        robot_ids: Optional[List[str]] = None
    ) -> List[CollisionPrediction]:
        """
        检测所有机器人之间的潜在碰撞
        
        Args:
            robot_ids: 要检测的机器人ID列表（None表示检测所有机器人）
            
        Returns:
            碰撞预测列表
        """
        collisions = []
        
        # 获取所有机器人ID
        if robot_ids is None:
            robot_ids = self.robot_manager.list_robots()
        
        if len(robot_ids) < 2:
            return collisions
        
        # 获取所有机器人的状态
        robot_states = {}
        for robot_id in robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state and state.status.value in ["idle", "online", "busy"]:
                robot_states[robot_id] = state
        
        # 预测所有机器人的轨迹
        trajectories = {}
        for robot_id, state in robot_states.items():
            trajectory = self.predict_robot_trajectory(
                state.pose,
                state.speed,
                self.prediction_window
            )
            trajectories[robot_id] = trajectory
        
        # 检查每对机器人之间的碰撞
        robot_list = list(robot_states.keys())
        for i in range(len(robot_list)):
            for j in range(i + 1, len(robot_list)):
                robot_id1 = robot_list[i]
                robot_id2 = robot_list[j]
                
                traj1 = trajectories[robot_id1]
                traj2 = trajectories[robot_id2]
                
                # 检查轨迹中的每个时间点
                for t_idx, (pred1, pred2) in enumerate(zip(traj1, traj2)):
                    if self.check_collision(pred1, pred2):
                        # 计算碰撞时间
                        collision_time = (t_idx + 1) * (self.prediction_window / len(traj1))
                        
                        # 计算碰撞点（两个位置的中间点）
                        collision_point = Pose(
                            x=(pred1.x + pred2.x) / 2,
                            y=(pred1.y + pred2.y) / 2,
                            z=(pred1.z + pred2.z) / 2,
                            yaw=0.0
                        )
                        
                        # 判断严重程度
                        distance = self.calculate_distance(pred1, pred2)
                        min_distance = self.robot_radius * 2 + self.safety_distance
                        severity = "critical" if distance < min_distance * 0.5 else "warning"
                        
                        collision = CollisionPrediction(
                            robot_id1=robot_id1,
                            robot_id2=robot_id2,
                            collision_time=collision_time,
                            collision_point=collision_point,
                            severity=severity
                        )
                        collisions.append(collision)
                        
                        # 如果发现严重碰撞，立即返回
                        if severity == "critical":
                            logger.warning(
                                f"Critical collision detected between {robot_id1} and {robot_id2} "
                                f"at ({collision_point.x:.2f}, {collision_point.y:.2f}) "
                                f"in {collision_time:.2f} seconds"
                            )
        
        return collisions
    
    async def check_path_collision(
        self,
        robot_id: str,
        path: List[Pose],
        other_robots: Optional[List[str]] = None
    ) -> List[Tuple[int, str]]:
        """
        检查路径是否与其他机器人的轨迹碰撞
        
        Args:
            robot_id: 机器人ID
            path: 路径点列表
            other_robots: 其他机器人ID列表（None表示检查所有其他机器人）
            
        Returns:
            碰撞点索引和碰撞机器人ID的列表
        """
        collisions = []
        
        # 验证路径格式
        if not path or not isinstance(path, list):
            return collisions
        
        # 获取机器人状态
        robot_state = await self.robot_manager.get_robot_state(robot_id)
        if not robot_state:
            return collisions
        
        # 获取其他机器人ID
        if other_robots is None:
            all_robots = self.robot_manager.list_robots()
            other_robots = [r for r in all_robots if r != robot_id]
        
        # 预测其他机器人的轨迹
        other_trajectories = {}
        for other_id in other_robots:
            other_state = await self.robot_manager.get_robot_state(other_id)
            if other_state and other_state.status.value in ["idle", "online", "busy"]:
                try:
                    trajectory = self.predict_robot_trajectory(
                        other_state.pose,
                        other_state.speed,
                        self.prediction_window
                    )
                    other_trajectories[other_id] = trajectory
                except Exception as e:
                    logger.warning(f"Failed to predict trajectory for robot {other_id}: {e}")
                    continue
        
        # 检查路径中的每个点
        for path_idx, path_point in enumerate(path):
            # 验证路径点格式
            if not isinstance(path_point, Pose):
                logger.warning(f"Invalid path point at index {path_idx}: expected Pose, got {type(path_point)}")
                continue
            # 估算到达该点的时间（简化：假设以恒定速度移动）
            estimated_time = path_idx * 0.5  # 假设每0.5秒到达一个点
            
            # 检查与其他机器人轨迹的碰撞
            for other_id, trajectory in other_trajectories.items():
                # 跳过空轨迹或非列表类型
                if not trajectory or not isinstance(trajectory, list) or len(trajectory) == 0:
                    continue
                
                try:
                    # 找到对应时间点的预测位置
                    if len(trajectory) > 0:
                        traj_idx = min(int(estimated_time / (self.prediction_window / len(trajectory))), len(trajectory) - 1)
                        traj_idx = max(0, traj_idx)  # 确保索引非负
                        if traj_idx < len(trajectory):
                            other_pred = trajectory[traj_idx]
                            
                            # 验证预测位置格式
                            if isinstance(other_pred, Pose):
                                if self.check_collision(path_point, other_pred):
                                    collisions.append((path_idx, other_id))
                                    logger.warning(
                                        f"Path collision detected for {robot_id} at waypoint {path_idx} "
                                        f"with robot {other_id}"
                                    )
                except (IndexError, TypeError, ZeroDivisionError) as e:
                    logger.warning(f"Error checking collision for robot {other_id} at waypoint {path_idx}: {e}")
                    continue
        
        return collisions

