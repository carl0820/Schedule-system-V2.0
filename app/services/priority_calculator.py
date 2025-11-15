"""
自动优先级计算模块
根据多个因素自动计算任务优先级，无需人工干预
"""
import math
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
from app.models.task import Task, TaskPriority, TaskStatus
from app.services.robot_manager import RobotManager
from app.services.path_planner import PathPlanner
from config import settings

logger = logging.getLogger(__name__)


class PriorityCalculator:
    """自动优先级计算器"""
    
    def __init__(
        self,
        robot_manager: RobotManager,
        path_planner: PathPlanner
    ):
        """
        初始化优先级计算器
        
        Args:
            robot_manager: 机器人管理器
            path_planner: 路径规划器
        """
        self.robot_manager = robot_manager
        self.path_planner = path_planner
        
        # 优先级计算参数
        self.base_priority = TaskPriority.NORMAL.value  # 基础优先级（2）
        self.max_priority = TaskPriority.URGENT.value  # 最大优先级（4）
        self.min_priority = TaskPriority.LOW.value  # 最小优先级（1）
        
        # 等待时间阈值（秒）- 从配置读取
        self.wait_time_threshold_1 = settings.PRIORITY_WAIT_TIME_THRESHOLD_1
        self.wait_time_threshold_2 = settings.PRIORITY_WAIT_TIME_THRESHOLD_2
        self.wait_time_threshold_3 = settings.PRIORITY_WAIT_TIME_THRESHOLD_3
        
        # 重试次数阈值
        self.retry_threshold = settings.PRIORITY_RETRY_THRESHOLD
    
    def calculate_initial_priority(
        self,
        target_pose,
        start_pose: Optional = None,
        poi_name: Optional[str] = None
    ) -> TaskPriority:
        """
        计算任务的初始优先级
        
        考虑因素：
        1. 任务距离（距离越远，可能需要更高优先级以确保及时完成）
        2. POI重要性（如果有POI信息）
        3. 系统当前负载
        
        Args:
            target_pose: 目标位置
            start_pose: 起点位置（可选）
            poi_name: POI名称（可选）
            
        Returns:
            计算出的优先级
        """
        try:
            priority_score = self.base_priority  # 从基础优先级开始
            
            # 因素1：任务距离
            if start_pose:
                distance = self._calculate_distance(
                    start_pose.x, start_pose.y,
                    target_pose.x, target_pose.y
                )
                # 距离越远，优先级适当提高（但不超过HIGH）
                if distance > 10.0:  # 超过10米
                    priority_score += 0.5
                elif distance > 5.0:  # 超过5米
                    priority_score += 0.3
            else:
                # 如果没有起点，使用路径规划估算距离
                # 这里简化处理，使用默认值
                pass
            
            # 因素2：POI重要性（如果有POI，可能表示重要位置）
            if poi_name:
                # POI任务通常比较重要，适当提高优先级
                priority_score += 0.2
            
            # 因素3：系统负载（待分配任务数量）
            # 这个在动态调整时考虑，初始优先级不包含
            
            # 限制优先级范围
            priority_score = max(self.min_priority, min(self.max_priority, priority_score))
            
            # 转换为TaskPriority枚举
            if priority_score >= 3.5:
                return TaskPriority.URGENT
            elif priority_score >= 2.5:
                return TaskPriority.HIGH
            elif priority_score >= 1.5:
                return TaskPriority.NORMAL
            else:
                return TaskPriority.LOW
                
        except Exception as e:
            logger.error(f"Error calculating initial priority: {e}")
            return TaskPriority.NORMAL
    
    def calculate_dynamic_priority(
        self,
        task: Task,
        pending_tasks_count: int = 0
    ) -> TaskPriority:
        """
        计算任务的动态优先级（考虑等待时间和系统状态）
        
        考虑因素：
        1. 等待时间（等待越久优先级越高）
        2. 重试次数（重试越多优先级越高）
        3. 系统负载（待分配任务越多，等待任务优先级提升越快）
        
        Args:
            task: 任务对象
            pending_tasks_count: 当前待分配任务数量
            
        Returns:
            计算出的优先级
        """
        try:
            # 从初始优先级开始
            priority_score = task.priority.value
            
            # 因素1：等待时间
            if task.status == TaskStatus.PENDING:
                wait_time = (datetime.now() - task.created_at).total_seconds()
                
                # 根据等待时间提升优先级
                if wait_time >= self.wait_time_threshold_3:
                    # 等待超过120秒，提升到最高优先级
                    priority_score = self.max_priority
                elif wait_time >= self.wait_time_threshold_2:
                    # 等待超过60秒，提升到HIGH或URGENT
                    priority_score = min(self.max_priority, priority_score + 1.5)
                elif wait_time >= self.wait_time_threshold_1:
                    # 等待超过30秒，适当提升
                    priority_score = min(self.max_priority, priority_score + 0.8)
                
                # 系统负载影响：待分配任务越多，等待时间的影响越大
                if pending_tasks_count > 5:
                    # 系统负载高，等待时间影响加倍
                    if wait_time >= self.wait_time_threshold_1:
                        priority_score = min(self.max_priority, priority_score + 0.5)
            
            # 因素2：重试次数
            if task.retry_count >= self.retry_threshold:
                # 重试次数多，说明任务可能比较重要或困难，提升优先级
                priority_score = min(self.max_priority, priority_score + 0.5)
            
            # 因素3：任务失败后重置的情况
            if task.status == TaskStatus.PENDING and task.retry_count > 0:
                # 失败后重新调度的任务，适当提高优先级
                priority_score = min(self.max_priority, priority_score + 0.3)
            
            # 限制优先级范围
            priority_score = max(self.min_priority, min(self.max_priority, priority_score))
            
            # 转换为TaskPriority枚举
            if priority_score >= 3.5:
                return TaskPriority.URGENT
            elif priority_score >= 2.5:
                return TaskPriority.HIGH
            elif priority_score >= 1.5:
                return TaskPriority.NORMAL
            else:
                return TaskPriority.LOW
                
        except Exception as e:
            logger.error(f"Error calculating dynamic priority for task {task.task_id}: {e}")
            return task.priority  # 出错时返回原优先级
    
    def _calculate_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """计算两点之间的距离"""
        dx = x2 - x1
        dy = y2 - y1
        return math.sqrt(dx * dx + dy * dy)
    
    def calculate_priority_with_path(
        self,
        target_pose,
        start_pose: Optional = None
    ) -> TaskPriority:
        """
        使用路径规划计算更准确的优先级（考虑实际路径长度）
        
        Args:
            target_pose: 目标位置
            start_pose: 起点位置（可选）
            
        Returns:
            计算出的优先级
        """
        try:
            priority_score = self.base_priority
            
            if start_pose:
                # 尝试使用路径规划计算实际路径长度
                path = self.path_planner.plan_path(start_pose, target_pose)
                if path and len(path) > 1:
                    # 计算路径总长度
                    path_length = 0.0
                    for i in range(len(path) - 1):
                        dx = path[i+1].x - path[i].x
                        dy = path[i+1].y - path[i].y
                        path_length += math.sqrt(dx*dx + dy*dy)
                    
                    # 根据路径长度调整优先级
                    if path_length > 15.0:  # 路径超过15米
                        priority_score += 0.5
                    elif path_length > 8.0:  # 路径超过8米
                        priority_score += 0.3
                else:
                    # 路径规划失败，使用直线距离
                    distance = self._calculate_distance(
                        start_pose.x, start_pose.y,
                        target_pose.x, target_pose.y
                    )
                    if distance > 10.0:
                        priority_score += 0.3
            
            # 限制优先级范围
            priority_score = max(self.min_priority, min(self.max_priority, priority_score))
            
            # 转换为TaskPriority枚举
            if priority_score >= 3.5:
                return TaskPriority.URGENT
            elif priority_score >= 2.5:
                return TaskPriority.HIGH
            elif priority_score >= 1.5:
                return TaskPriority.NORMAL
            else:
                return TaskPriority.LOW
                
        except Exception as e:
            logger.error(f"Error calculating priority with path: {e}")
            return TaskPriority.NORMAL

