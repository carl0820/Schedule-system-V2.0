"""
死锁检测模块
"""
import math
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Set, Tuple, Optional, Any
from datetime import datetime, timedelta
from app.models.robot import Pose, Speed
from app.services.robot_manager import RobotManager
from app.services.collision_detector import CollisionDetector
from app.services.path_planner import PathPlanner

logger = logging.getLogger(__name__)

# 创建专门的死锁日志记录器
deadlock_logger = logging.getLogger("deadlock")
deadlock_logger.setLevel(logging.INFO)
# 避免重复添加handler
if not deadlock_logger.handlers:
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    deadlock_log_file = os.path.join(log_dir, "deadlock.log")
    
    # 死锁日志文件处理器 - 使用轮转，每个文件最大10MB，保留5个备份
    deadlock_file_handler = RotatingFileHandler(
        deadlock_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    deadlock_file_handler.setLevel(logging.INFO)
    deadlock_file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    deadlock_logger.addHandler(deadlock_file_handler)
    deadlock_logger.info("=" * 80)
    deadlock_logger.info("Deadlock detection logger initialized")
    deadlock_logger.info(f"Deadlock log file: {deadlock_log_file}")
    deadlock_logger.info("=" * 80)


class DeadlockState:
    """死锁状态"""
    
    def __init__(
        self,
        robot_ids: List[str],
        deadlock_type: str,  # "circular_wait", "mutual_blocking", "resource_contention", "narrow_passage", "livelock", "starvation"
        start_time: datetime,
        duration: float = 0.0,
        additional_info: Optional[Dict[str, Any]] = None
    ):
        self.robot_ids = robot_ids
        self.deadlock_type = deadlock_type
        self.start_time = start_time
        self.duration = duration  # 死锁持续时间（秒）
        self.additional_info = additional_info or {}  # 额外信息（如任务ID、等待时间等）


class DeadlockDetector:
    """死锁检测器，检测多机器人系统中的死锁情况"""
    
    def __init__(
        self,
        robot_manager: RobotManager,
        collision_detector: CollisionDetector,
        path_planner: Optional[PathPlanner] = None,
        task_scheduler: Optional[Any] = None  # 任务调度器引用，用于获取任务优先级
    ):
        """
        初始化死锁检测器
        
        Args:
            robot_manager: 机器人管理器
            collision_detector: 碰撞检测器
            path_planner: 路径规划器（可选，用于窄道检测）
            task_scheduler: 任务调度器（可选，用于获取任务优先级）
        """
        self.robot_manager = robot_manager
        self.collision_detector = collision_detector
        self.path_planner = path_planner
        self.task_scheduler = task_scheduler  # 任务调度器引用
        self.robot_states_history: Dict[str, List[Tuple[datetime, Pose]]] = {}  # 机器人状态历史
        self.deadlock_history: List[DeadlockState] = []  # 死锁历史
        
        # 从配置管理器加载配置（默认值）
        self._load_config()
    
    def _load_config(self):
        """从配置管理器加载配置"""
        try:
            from app.services.config_manager import get_config_manager
            config_manager = get_config_manager()
            config = config_manager.get_deadlock_config()
            
            self.deadlock_threshold = config.get("deadlock_threshold", 10.0)
            # 不同死锁类型的阈值（如果未配置，使用通用阈值）
            self.narrow_passage_deadlock_threshold = config.get("narrow_passage_deadlock_threshold", 3.0)  # 窄道死锁3秒触发
            self.circular_wait_deadlock_threshold = config.get("circular_wait_deadlock_threshold", 10.0)  # 循环等待10秒
            self.mutual_blocking_deadlock_threshold = config.get("mutual_blocking_deadlock_threshold", 1.5)  # 相互阻塞1.5秒（更快响应）
            self.narrow_passage_threshold = config.get("narrow_passage_threshold", 1.0)
            self.narrow_passage_backoff_distance = config.get("narrow_passage_backoff_distance", 1.0)
            self.circular_wait_backoff_distance = config.get("circular_wait_backoff_distance", 1.5)
            self.mutual_blocking_backoff_distance = config.get("mutual_blocking_backoff_distance", 1.0)
            self.default_backoff_distance = config.get("default_backoff_distance", 1.0)
            self.backoff_speed_ratio = config.get("backoff_speed_ratio", 0.5)
            self.backoff_acceptable_precision = config.get("backoff_acceptable_precision", 0.2)
            self.robot_stuck_threshold = config.get("robot_stuck_threshold", 0.1)
            self.robot_stuck_time_window = config.get("robot_stuck_time_window", 10.0)
            self.mutual_blocking_distance = config.get("mutual_blocking_distance", 1.0)
            self.narrow_passage_detection_distance = config.get("narrow_passage_detection_distance", 2.0)
            self.history_retention_time = config.get("history_retention_time", 60.0)
            self.waiting_point_min_distance = config.get("waiting_point_min_distance", 2.0)  # 等待点最小距离
            self.waiting_point_max_distance = config.get("waiting_point_max_distance", 5.0)  # 等待点最大距离
            # 活锁检测配置
            self.livelock_threshold = config.get("livelock_threshold", 15.0)  # 活锁检测阈值（秒）
            self.livelock_progress_threshold = config.get("livelock_progress_threshold", 0.5)  # 活锁进度阈值（米）
            self.livelock_oscillation_threshold = config.get("livelock_oscillation_threshold", 1.0)  # 活锁振荡阈值（米）
            # 饥饿死锁检测配置
            self.starvation_threshold = config.get("starvation_threshold", 60.0)  # 饥饿死锁阈值（秒）- 任务等待时间
            self.starvation_deadlock_threshold = config.get("starvation_deadlock_threshold", 120.0)  # 饥饿死锁触发阈值（秒）
            
            # 记录配置加载（仅在初始化时记录，避免日志过多）
            if not hasattr(self, '_config_loaded'):
                deadlock_logger.info(
                    f"Deadlock config loaded: narrow_passage_threshold={self.narrow_passage_threshold}m, "
                    f"narrow_passage_detection_distance={self.narrow_passage_detection_distance}m, "
                    f"narrow_passage_deadlock_threshold={self.narrow_passage_deadlock_threshold}s, "
                    f"narrow_passage_backoff_distance={self.narrow_passage_backoff_distance}m"
                )
                self._config_loaded = True
        except Exception as e:
            logger.warning(f"Failed to load config, using defaults: {e}")
            deadlock_logger.warning(f"Failed to load config, using defaults: {e}")
            # 使用默认值
            self.deadlock_threshold = 10.0
            self.narrow_passage_deadlock_threshold = 3.0
            self.circular_wait_deadlock_threshold = 10.0
            self.mutual_blocking_deadlock_threshold = 1.5
            self.narrow_passage_threshold = 1.0
            self.narrow_passage_backoff_distance = 1.0
            self.circular_wait_backoff_distance = 1.5
            self.mutual_blocking_backoff_distance = 1.0
            self.default_backoff_distance = 1.0
            self.backoff_speed_ratio = 0.5
            self.backoff_acceptable_precision = 0.2
            self.robot_stuck_threshold = 0.1
            self.robot_stuck_time_window = 10.0
            self.mutual_blocking_distance = 1.0
            self.narrow_passage_detection_distance = 2.0
            self.history_retention_time = 60.0
            self.waiting_point_min_distance = 2.0
            self.waiting_point_max_distance = 5.0
            # 活锁检测配置（默认值）
            self.livelock_threshold = 15.0
            self.livelock_progress_threshold = 0.5
            self.livelock_oscillation_threshold = 1.0
            # 饥饿死锁检测配置（默认值）
            self.starvation_threshold = 60.0
            self.starvation_deadlock_threshold = 120.0
    
    def calculate_distance(self, pose1: Pose, pose2: Pose) -> float:
        """计算两点之间的距离"""
        dx = pose1.x - pose2.x
        dy = pose1.y - pose2.y
        return math.sqrt(dx * dx + dy * dy)
    
    def update_robot_history(self, robot_id: str, pose: Pose):
        """更新机器人状态历史"""
        if robot_id not in self.robot_states_history:
            self.robot_states_history[robot_id] = []
        
        now = datetime.now()
        self.robot_states_history[robot_id].append((now, pose))
        
        # 只保留最近30秒的历史
        cutoff_time = now - timedelta(seconds=30)
        self.robot_states_history[robot_id] = [
            (t, p) for t, p in self.robot_states_history[robot_id]
            if t > cutoff_time
        ]
    
    def check_robot_stuck(self, robot_id: str) -> bool:
        """
        检查机器人是否卡住（位置长时间不变）
        
        Args:
            robot_id: 机器人ID
            
        Returns:
            是否卡住
        """
        if robot_id not in self.robot_states_history:
            return False
        
        history = self.robot_states_history[robot_id]
        if len(history) < 5:
            return False
        
        # 检查最近时间窗口内的位置变化
        self._load_config()  # 重新加载配置（支持运行时更新）
        now = datetime.now()
        cutoff_time = now - timedelta(seconds=self.robot_stuck_time_window)
        recent_history = [(t, p) for t, p in history if t > cutoff_time]
        
        if len(recent_history) < 3:
            return False
        
        # 计算位置变化
        positions = [p for _, p in recent_history]
        max_distance = 0.0
        
        for i in range(len(positions) - 1):
            for j in range(i + 1, len(positions)):
                distance = self.calculate_distance(positions[i], positions[j])
                max_distance = max(max_distance, distance)
        
        # 如果最大移动距离小于阈值，认为卡住
        return max_distance < self.robot_stuck_threshold
    
    async def detect_livelock(self, robot_ids: List[str]) -> Optional[List[str]]:
        """
        检测活锁（机器人不断移动但无法前进）
        
        Args:
            robot_ids: 机器人ID列表
            
        Returns:
            活锁的机器人ID列表，如果没有则返回None
        """
        if len(robot_ids) < 1 or not self.task_scheduler:
            return None
        
        self._load_config()
        livelock_robots = []
        
        for robot_id in robot_ids:
            if robot_id not in self.robot_states_history:
                continue
            
            history = self.robot_states_history[robot_id]
            if len(history) < 10:  # 需要足够的历史数据
                continue
            
            # 检查最近时间窗口内的位置变化
            now = datetime.now()
            cutoff_time = now - timedelta(seconds=self.livelock_threshold)
            recent_history = [(t, p) for t, p in history if t > cutoff_time]
            
            if len(recent_history) < 5:
                continue
            
            positions = [p for _, p in recent_history]
            
            # 1. 检查是否在振荡（来回移动）
            oscillation_detected = False
            if len(positions) >= 6:
                # 检查位置是否在小范围内振荡
                center_x = sum(p.x for p in positions) / len(positions)
                center_y = sum(p.y for p in positions) / len(positions)
                max_distance_from_center = 0.0
                
                for p in positions:
                    distance = math.sqrt((p.x - center_x)**2 + (p.y - center_y)**2)
                    max_distance_from_center = max(max_distance_from_center, distance)
                
                # 如果最大距离小于振荡阈值，且总移动距离较大，可能是振荡
                total_distance = 0.0
                for i in range(len(positions) - 1):
                    total_distance += self.calculate_distance(positions[i], positions[i+1])
                
                if max_distance_from_center < self.livelock_oscillation_threshold and total_distance > 2.0:
                    oscillation_detected = True
            
            # 2. 检查是否在目标方向上有进展
            progress_made = False
            task = None
            target_pose = None
            
            # 获取机器人的当前任务
            for t in self.task_scheduler.tasks.values():
                if t.robot_id == robot_id and t.status.value in ["EXECUTING", "ASSIGNED"]:
                    task = t
                    if t.target_pose:
                        target_pose = t.target_pose
                    elif t.is_multi_action and t.actions and t.current_action_index is not None:
                        # 对于多动作任务，检查当前动作的目标
                        current_action = t.actions[t.current_action_index]
                        if current_action.get("target_pose"):
                            from app.models.robot import Pose as PoseModel
                            tp = current_action["target_pose"]
                            target_pose = PoseModel(x=tp.get("x", 0), y=tp.get("y", 0), yaw=tp.get("yaw", 0))
                    break
            
            if target_pose and len(positions) >= 2:
                # 计算到目标的距离变化
                initial_distance = self.calculate_distance(positions[0], target_pose)
                final_distance = self.calculate_distance(positions[-1], target_pose)
                distance_improvement = initial_distance - final_distance
                
                # 如果距离改善小于阈值，认为没有进展
                if distance_improvement < self.livelock_progress_threshold:
                    progress_made = False
                else:
                    progress_made = True
            
            # 3. 检查总移动距离
            total_distance = 0.0
            for i in range(len(positions) - 1):
                total_distance += self.calculate_distance(positions[i], positions[i+1])
            
            # 如果机器人移动了很长距离，但在目标方向上没有进展，或者在小范围内振荡，认为是活锁
            if (oscillation_detected or (total_distance > 3.0 and not progress_made)) and task:
                livelock_robots.append(robot_id)
                deadlock_logger.warning(
                    f"Livelock detected for robot {robot_id}: "
                    f"oscillation={oscillation_detected}, progress={progress_made}, "
                    f"total_distance={total_distance:.2f}m, task_id={task.task_id}"
                )
        
        return livelock_robots if len(livelock_robots) > 0 else None
    
    async def detect_starvation(self, robot_ids: Optional[List[str]] = None) -> Optional[List[str]]:
        """
        检测饥饿死锁（任务等待时间过长）
        
        Args:
            robot_ids: 机器人ID列表（可选，None表示检测所有机器人）
            
        Returns:
            饥饿的机器人ID列表，如果没有则返回None
        """
        if not self.task_scheduler:
            return None
        
        self._load_config()
        starved_robots = []
        now = datetime.now()
        
        # 检查所有待分配的任务
        for task in self.task_scheduler.tasks.values():
            if task.status.value != "PENDING":
                continue
            
            # 计算任务等待时间
            if task.created_at:
                wait_time = (now - task.created_at).total_seconds()
                
                if wait_time > self.starvation_threshold:
                    # 检查是否有可用的机器人
                    available_robots = []
                    for robot_id in (robot_ids or self.robot_manager.list_robots()):
                        state = await self.robot_manager.get_robot_state(robot_id)
                        if state and state.status.value in ["idle", "online"]:
                            # 检查是否有正在执行的任务
                            has_executing_task = any(
                                t.robot_id == robot_id and t.status.value in ["EXECUTING", "ASSIGNED"]
                                for t in self.task_scheduler.tasks.values()
                            )
                            if not has_executing_task:
                                available_robots.append(robot_id)
                    
                    # 如果有可用机器人但任务仍未分配，可能是饥饿死锁
                    if len(available_robots) > 0 and wait_time > self.starvation_deadlock_threshold:
                        # 找到应该分配但未分配的机器人（可能是调度器问题）
                        starved_robots.extend(available_robots[:1])  # 只添加一个机器人作为代表
                        deadlock_logger.warning(
                            f"Starvation detected: Task {task.task_id} waiting for {wait_time:.1f}s, "
                            f"available robots: {available_robots}, priority={task.priority}"
                        )
        
        return starved_robots if len(starved_robots) > 0 else None
    
    async def detect_circular_wait(self, robot_ids: List[str]) -> Optional[List[str]]:
        """
        检测循环等待死锁
        
        Args:
            robot_ids: 机器人ID列表
            
        Returns:
            死锁的机器人ID列表，如果没有则返回None
        """
        if len(robot_ids) < 2:
            return None
        
        # 获取所有机器人的状态
        robot_states = {}
        for robot_id in robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state and state.status.value in ["idle", "online", "busy"]:
                robot_states[robot_id] = state
        
        if len(robot_states) < 2:
            return None
        
        # 检查是否存在循环等待
        # 简化：如果多个机器人都在等待对方，可能形成循环等待
        waiting_robots = []
        for robot_id, state in robot_states.items():
            # 检查机器人是否在等待（速度很小）
            if abs(state.speed.vx) < 0.05 and abs(state.speed.omega) < 0.05:
                waiting_robots.append(robot_id)
        
        if len(waiting_robots) >= 2:
            # 检查这些机器人是否相互阻塞
            blocked_pairs = []
            robot_list = list(waiting_robots)
            for i in range(len(robot_list)):
                for j in range(i + 1, len(robot_list)):
                    robot_id1 = robot_list[i]
                    robot_id2 = robot_list[j]
                    
                    pose1 = robot_states[robot_id1].pose
                    pose2 = robot_states[robot_id2].pose
                    distance = self.calculate_distance(pose1, pose2)
                    
                    # 如果距离很近，可能相互阻塞
                    self._load_config()  # 重新加载配置
                    if distance < self.mutual_blocking_distance:
                        blocked_pairs.append((robot_id1, robot_id2))
            
            # 如果有多对机器人相互阻塞，可能形成循环等待
            if len(blocked_pairs) >= 2:
                # 构建依赖图
                dependencies = {}
                for robot_id1, robot_id2 in blocked_pairs:
                    if robot_id1 not in dependencies:
                        dependencies[robot_id1] = []
                    dependencies[robot_id1].append(robot_id2)
                    if robot_id2 not in dependencies:
                        dependencies[robot_id2] = []
                    dependencies[robot_id2].append(robot_id1)
                
                # 检查是否存在循环
                # 简化：如果所有机器人都在等待，且相互阻塞，可能形成循环
                if len(dependencies) >= 2:
                    # 检查是否形成环
                    visited = set()
                    
                    def has_cycle(node: str, parent: Optional[str] = None) -> bool:
                        """检查是否存在环"""
                        visited.add(node)
                        for neighbor in dependencies.get(node, []):
                            if neighbor == parent:
                                continue
                            if neighbor in visited:
                                return True
                            if has_cycle(neighbor, node):
                                return True
                        return False
                    
                    for robot_id in dependencies:
                        if robot_id not in visited:
                            if has_cycle(robot_id):
                                return list(dependencies.keys())
        
        return None
    
    async def detect_mutual_blocking(self, robot_ids: List[str]) -> Optional[List[str]]:
        """
        检测相互阻塞死锁（支持多台机器人）
        
        Args:
            robot_ids: 机器人ID列表
            
        Returns:
            死锁的机器人ID列表，如果没有则返回None
        """
        if len(robot_ids) < 2:
            return None
        
        # 获取所有机器人的状态
        robot_states = {}
        for robot_id in robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state and state.status.value in ["idle", "online", "busy"]:
                robot_states[robot_id] = state
        
        if len(robot_states) < 2:
            return None
        
        # 重新加载配置
        self._load_config()
        
        # 使用聚类方法，将距离较近的机器人分组
        blocking_groups = []  # 每个组是相互阻塞的机器人列表
        processed = set()
        robot_list = list(robot_states.keys())
        
        for robot_id1 in robot_list:
            if robot_id1 in processed:
                continue
            
            # 创建一个新的组
            group = [robot_id1]
            processed.add(robot_id1)
            pose1 = robot_states[robot_id1].pose
            speed1 = robot_states[robot_id1].speed
            
            # 查找所有与robot_id1相互阻塞的机器人
            for robot_id2 in robot_list:
                if robot_id2 in processed:
                    continue
                
                pose2 = robot_states[robot_id2].pose
                speed2 = robot_states[robot_id2].speed
                distance = self.calculate_distance(pose1, pose2)
                
                # 如果距离很近，检查是否相互阻塞
                if distance < self.mutual_blocking_distance:
                    # 检查机器人是否有执行中的任务（如果有任务但速度为零，可能是卡住了）
                    # 注意：即使机器人状态是idle，如果有执行中的任务，也应该检测
                    has_task1 = False
                    has_task2 = False
                    if self.task_scheduler:
                        for task in self.task_scheduler.tasks.values():
                            if task.robot_id == robot_id1 and task.status.value in ["EXECUTING", "ASSIGNED"]:
                                has_task1 = True
                            if task.robot_id == robot_id2 and task.status.value in ["EXECUTING", "ASSIGNED"]:
                                has_task2 = True
                    
                    # 检测相互阻塞的情况：
                    # 1. 如果至少一个机器人有执行中的任务，且距离很近，检查是否相互阻塞
                    # 2. 即使两个机器人都没有任务，如果它们距离很近且都静止，也可能形成死锁（相互阻塞）
                    # 3. 即使另一个机器人没有任务，如果它阻塞了有任务机器人的路径，也应该检测
                    both_stuck = (speed1.vx == 0 and speed1.vy == 0 and speed2.vx == 0 and speed2.vy == 0)
                    if has_task1 or has_task2 or (both_stuck and distance < 1.5):
                        # 如果两个机器人都有任务，检查相互阻塞
                        if has_task1 and has_task2:
                            # 计算速度方向（如果速度为零，使用朝向方向）
                            if speed1.vx == 0 and speed1.vy == 0:
                                # 速度为零，使用朝向方向作为"想要移动的方向"
                                vx1 = math.cos(pose1.yaw)
                                vy1 = math.sin(pose1.yaw)
                            else:
                                vx1 = speed1.vx * math.cos(pose1.yaw)
                                vy1 = speed1.vx * math.sin(pose1.yaw)
                            
                            if speed2.vx == 0 and speed2.vy == 0:
                                vx2 = math.cos(pose2.yaw)
                                vy2 = math.sin(pose2.yaw)
                            else:
                                vx2 = speed2.vx * math.cos(pose2.yaw)
                                vy2 = speed2.vx * math.sin(pose2.yaw)
                            
                            # 计算相对速度
                            rel_vx = vx2 - vx1
                            rel_vy = vy2 - vy1
                            
                            # 计算相对位置
                            rel_x = pose2.x - pose1.x
                            rel_y = pose2.y - pose1.y
                            
                            # 如果相对速度方向与相对位置方向相反，或者两个机器人都静止且距离很近，可能相互阻塞
                            dot_product = rel_vx * rel_x + rel_vy * rel_y
                            if dot_product < 0 or (speed1.vx == 0 and speed1.vy == 0 and speed2.vx == 0 and speed2.vy == 0):
                                group.append(robot_id2)
                                processed.add(robot_id2)
                        elif not has_task1 and not has_task2:
                            # 两个机器人都没有任务，但如果它们距离很近且都静止，可能形成死锁
                            if both_stuck and distance < 1.5:
                                group.append(robot_id2)
                                processed.add(robot_id2)
                                deadlock_logger.info(
                                    f"[DETECT] Robots {robot_id1} and {robot_id2} (both no task) "
                                    f"are stuck close together at distance {distance:.2f}m"
                                )
                        elif has_task1 and not has_task2:
                            # robot1有任务，robot2没有任务，但robot2可能阻塞了robot1的路径
                            # 检查robot2是否在robot1到目标的路径上
                            if self.task_scheduler:
                                for task in self.task_scheduler.tasks.values():
                                    if task.robot_id == robot_id1 and task.status.value in ["EXECUTING", "ASSIGNED"]:
                                        if task.target_pose:
                                            # 计算robot2是否在robot1到目标的路径上
                                            target = task.target_pose
                                            # 计算robot1到目标的方向
                                            dx1 = target.x - pose1.x
                                            dy1 = target.y - pose1.y
                                            # 计算robot2相对于robot1的位置
                                            dx2 = pose2.x - pose1.x
                                            dy2 = pose2.y - pose1.y
                                            # 如果robot2在robot1到目标的方向上，且距离很近，可能阻塞
                                            dot = dx1 * dx2 + dy1 * dy2
                                            if dot > 0 and distance < 1.5:  # 在前进方向上，距离小于1.5米
                                                group.append(robot_id2)
                                                processed.add(robot_id2)
                                                deadlock_logger.info(
                                                    f"[DETECT] Robot {robot_id2} (no task) blocking robot {robot_id1} "
                                                    f"(has task {task.task_id}) at distance {distance:.2f}m"
                                                )
                                                break
                        elif has_task2 and not has_task1:
                            # robot2有任务，robot1没有任务，但robot1可能阻塞了robot2的路径
                            # 检查robot1是否在robot2到目标的路径上
                            if self.task_scheduler:
                                for task in self.task_scheduler.tasks.values():
                                    if task.robot_id == robot_id2 and task.status.value in ["EXECUTING", "ASSIGNED"]:
                                        if task.target_pose:
                                            # 计算robot1是否在robot2到目标的路径上
                                            target = task.target_pose
                                            # 计算robot2到目标的方向
                                            dx2 = target.x - pose2.x
                                            dy2 = target.y - pose2.y
                                            # 计算robot1相对于robot2的位置
                                            dx1 = pose1.x - pose2.x
                                            dy1 = pose1.y - pose2.y
                                            # 如果robot1在robot2到目标的方向上，且距离很近，可能阻塞
                                            dot = dx2 * dx1 + dy2 * dy1
                                            if dot > 0 and distance < 1.5:  # 在前进方向上，距离小于1.5米
                                                group.append(robot_id2)
                                                processed.add(robot_id2)
                                                deadlock_logger.info(
                                                    f"[DETECT] Robot {robot_id1} (no task) blocking robot {robot_id2} "
                                                    f"(has task {task.task_id}) at distance {distance:.2f}m"
                                                )
                                                break
            
            # 如果组中有2个或更多机器人，可能形成死锁
            if len(group) >= 2:
                blocking_groups.append(group)
        
        # 合并所有阻塞的机器人
        blocked_robots = []
        for group in blocking_groups:
            for robot_id in group:
                if robot_id not in blocked_robots:
                    blocked_robots.append(robot_id)
            
            if len(group) >= 2:
                logger.warning(
                    f"Mutual blocking deadlock detected: {len(group)} robots "
                    f"({', '.join(group)})"
                )
        
        return blocked_robots if len(blocked_robots) >= 2 else None
    
    async def detect_narrow_passage_deadlock(self, robot_ids: List[str]) -> Optional[List[str]]:
        """
        检测窄道死锁（支持多台机器人）
        
        Args:
            robot_ids: 机器人ID列表
            
        Returns:
            死锁的机器人ID列表，如果没有则返回None
        """
        if len(robot_ids) < 2 or not self.path_planner:
            return None
        
        # 获取所有机器人的状态
        robot_states = {}
        for robot_id in robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state and state.status.value in ["idle", "online", "busy"]:
                robot_states[robot_id] = state
        
        if len(robot_states) < 2:
            return None
        
        # 重新加载配置
        self._load_config()
        
        # 第一步：识别所有在窄道中的机器人
        robots_in_passage = {}  # robot_id -> (pose, width)
        robot_list = list(robot_states.keys())
        
        for robot_id in robot_list:
            pose = robot_states[robot_id].pose
            width = self.path_planner.calculate_passage_width(pose.x, pose.y, 0.2)
            
            # 如果位置是窄道
            if width > 0 and width < self.narrow_passage_threshold:
                robots_in_passage[robot_id] = (pose, width)
        
        if len(robots_in_passage) < 2:
            return None
        
        # 第二步：检查这些机器人是否在同一个窄道区域（距离很近）
        # 使用聚类方法，将距离较近的机器人分组
        passage_groups = []  # 每个组是一个窄道中的机器人列表
        processed = set()
        
        # 记录检测信息（用于调试）
        deadlock_logger.debug(
            f"Narrow passage detection: found {len(robots_in_passage)} robots in narrow passages, "
            f"detection_distance={self.narrow_passage_detection_distance}m, "
            f"threshold={self.narrow_passage_threshold}m"
        )
        
        for robot_id1 in robots_in_passage:
            if robot_id1 in processed:
                continue
            
            # 创建一个新的组
            group = [robot_id1]
            processed.add(robot_id1)
            pose1, width1 = robots_in_passage[robot_id1]
            
            # 查找所有与robot_id1在同一个窄道区域的机器人
            for robot_id2 in robots_in_passage:
                if robot_id2 in processed:
                    continue
                
                pose2, width2 = robots_in_passage[robot_id2]
                distance = self.calculate_distance(pose1, pose2)
                
                # 如果距离很近，且都在窄道中，可能在同一区域
                if distance < self.narrow_passage_detection_distance:
                    # 检查是否可以同时通过所有机器人
                    min_width = min(width1, width2)
                    num_robots = len(group) + 1
                    can_pass = self.path_planner.can_pass_concurrently(
                        min_width, 0.2, num_robots
                    )
                    
                    if not can_pass:
                        group.append(robot_id2)
                        processed.add(robot_id2)
            
            # 如果组中有2个或更多机器人，可能形成死锁
            if len(group) >= 2:
                passage_groups.append(group)
        
        # 第三步：检查每个组中的机器人是否真的相互阻塞（速度方向）
        blocked_robots = []
        
        for group in passage_groups:
            group_blocked = []
            
            # 检查组内机器人是否相互阻塞
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    robot_id1 = group[i]
                    robot_id2 = group[j]
                    
                    pose1 = robot_states[robot_id1].pose
                    pose2 = robot_states[robot_id2].pose
                    speed1 = robot_states[robot_id1].speed
                    speed2 = robot_states[robot_id2].speed
                    
                    # 计算速度方向
                    vx1 = speed1.vx * math.cos(pose1.yaw)
                    vy1 = speed1.vx * math.sin(pose1.yaw)
                    vx2 = speed2.vx * math.cos(pose2.yaw)
                    vy2 = speed2.vx * math.sin(pose2.yaw)
                    
                    # 计算相对速度
                    rel_vx = vx2 - vx1
                    rel_vy = vy2 - vy1
                    
                    # 计算相对位置
                    rel_x = pose2.x - pose1.x
                    rel_y = pose2.y - pose1.y
                    
                    # 如果相对速度方向与相对位置方向相反，可能相互阻塞
                    dot_product = rel_vx * rel_x + rel_vy * rel_y
                    if dot_product < 0:  # 方向相反
                        if robot_id1 not in group_blocked:
                            group_blocked.append(robot_id1)
                        if robot_id2 not in group_blocked:
                            group_blocked.append(robot_id2)
            
            # 如果组中有多个机器人相互阻塞，添加到总列表
            if len(group_blocked) >= 2:
                for robot_id in group_blocked:
                    if robot_id not in blocked_robots:
                        blocked_robots.append(robot_id)
                
                # 检查是否在虚拟墙围成的窄道中
                near_virtual_wall = False
                if self.path_planner and hasattr(self.path_planner.map_manager, 'virtual_walls'):
                    virtual_walls = self.path_planner.map_manager.virtual_walls
                    if virtual_walls:
                        for robot_id in group_blocked:
                            pose = robot_states[robot_id].pose
                            for wall in virtual_walls:
                                start = wall.get("start", {})
                                end = wall.get("end", {})
                                if start and end:
                                    dist = self.path_planner._point_to_line_distance(
                                        pose.x, pose.y,
                                        start.get("x", 0), start.get("y", 0),
                                        end.get("x", 0), end.get("y", 0)
                                    )
                                    if dist < 0.5:
                                        near_virtual_wall = True
                                        break
                            if near_virtual_wall:
                                break
                
                wall_info = " (virtual wall detected)" if near_virtual_wall else ""
                min_width = min([robots_in_passage[rid][1] for rid in group_blocked])
                deadlock_logger.warning(
                    f"Narrow passage deadlock detected: {len(group_blocked)} robots "
                    f"({', '.join(group_blocked)}) in passage (width={min_width:.2f}m){wall_info}"
                )
                logger.warning(
                    f"Narrow passage deadlock detected: {len(group_blocked)} robots "
                    f"({', '.join(group_blocked)}) in passage (width={min_width:.2f}m){wall_info}"
                )
        
        return blocked_robots if len(blocked_robots) >= 2 else None
    
    async def detect_deadlocks(self, robot_ids: Optional[List[str]] = None) -> List[DeadlockState]:
        """
        检测死锁
        
        Args:
            robot_ids: 要检测的机器人ID列表（None表示检测所有机器人）
            
        Returns:
            死锁状态列表
        """
        try:
            deadlocks = []
            
            # 获取所有机器人ID
            if robot_ids is None:
                robot_ids = self.robot_manager.list_robots()
            
            # 如果没有机器人，直接返回
            if not robot_ids:
                return deadlocks
            
            # 注意：即使只有1个机器人，也需要检测卡住情况（虽然不是死锁，但需要处理）
            # 但死锁检测（循环等待、相互阻塞等）需要至少2个机器人
            
            # 更新机器人状态历史（所有机器人，包括单个机器人）
            # 同时保存当前状态，用于后续检测
            robot_states = {}
            for robot_id in robot_ids:
                try:
                    state = await self.robot_manager.get_robot_state(robot_id)
                    if state and state.status.value in ["idle", "online", "busy"]:
                        self.update_robot_history(robot_id, state.pose)
                        robot_states[robot_id] = state
                except Exception as e:
                    deadlock_logger.warning(f"[DETECT] Failed to get state for robot {robot_id}: {e}")
                    continue
            
            # 如果只有1个机器人，只检测卡住情况，不检测死锁
            if len(robot_ids) < 2:
                # 检测单个机器人卡住的情况
                stuck_robots = []
                for robot_id in robot_ids:
                    if self.check_robot_stuck(robot_id):
                        stuck_robots.append(robot_id)
                
                # 确保 robot_states 被定义（即使只有一个机器人）
                if not robot_states:
                    robot_states = {}
                    for robot_id in robot_ids:
                        try:
                            state = await self.robot_manager.get_robot_state(robot_id)
                            if state and state.status.value in ["idle", "online", "busy"]:
                                robot_states[robot_id] = state
                        except Exception:
                            pass
                
                if stuck_robots:
                    # 检查是否已经记录了死锁
                    existing_deadlock = None
                    for deadlock in self.deadlock_history:
                        if (deadlock.deadlock_type == "resource_contention" and
                            set(deadlock.robot_ids) == set(stuck_robots)):
                            existing_deadlock = deadlock
                            break
                    
                    if existing_deadlock:
                        # 更新持续时间
                        existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                    else:
                        # 创建新的死锁记录
                        deadlock = DeadlockState(
                            robot_ids=stuck_robots,
                            deadlock_type="resource_contention",
                            start_time=datetime.now()
                        )
                        self.deadlock_history.append(deadlock)
                        deadlocks.append(deadlock)
                        deadlock_logger.warning(f"[DETECT] Single robot stuck detected: {stuck_robots}")
                        logger.warning(f"Single robot stuck detected: {stuck_robots}")
                
                # 清理过期的死锁记录
                self._load_config()
                now = datetime.now()
                self.deadlock_history = [
                    d for d in self.deadlock_history
                    if (now - d.start_time).total_seconds() < self.history_retention_time
                ]
                
                return deadlocks
            
            # 多个机器人：检测各种死锁类型
            # 记录检测开始（用于验证）- 使用INFO级别
            if len(robot_ids) >= 2:
                deadlock_logger.info(
                    f"[DETECT] Starting deadlock detection for {len(robot_ids)} robots: {robot_ids}"
                )
            
            # 检测循环等待
            circular_wait = await self.detect_circular_wait(robot_ids)
            if circular_wait:
                deadlock_logger.info(f"[DETECT] Circular wait detected: robots {circular_wait}")
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == "circular_wait" and
                        set(deadlock.robot_ids) == set(circular_wait)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=circular_wait,
                        deadlock_type="circular_wait",
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"Circular wait deadlock detected: {circular_wait}")
                    deadlock_logger.warning(
                        f"[CIRCULAR_WAIT] Detected for robots: {', '.join(circular_wait)}"
                    )
            
            # 检测窄道死锁（包括十字路口和长走廊场景）
            narrow_passage_deadlock = await self.detect_narrow_passage_deadlock(robot_ids)
            if narrow_passage_deadlock:
                deadlock_logger.info(f"[DETECT] Narrow passage deadlock detected: robots {narrow_passage_deadlock}")
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == "narrow_passage" and
                        set(deadlock.robot_ids) == set(narrow_passage_deadlock)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=narrow_passage_deadlock,
                        deadlock_type="narrow_passage",
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"Narrow passage deadlock detected: {narrow_passage_deadlock}")
                    deadlock_logger.warning(
                        f"[NARROW_PASSAGE] Detected for robots: {', '.join(narrow_passage_deadlock)}"
                    )
            
            # 检测相互阻塞
            mutual_blocking = await self.detect_mutual_blocking(robot_ids)
            if mutual_blocking:
                deadlock_logger.info(f"[DETECT] Mutual blocking detected: robots {mutual_blocking}")
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == "mutual_blocking" and
                        set(deadlock.robot_ids) == set(mutual_blocking)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=mutual_blocking,
                        deadlock_type="mutual_blocking",
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"Mutual blocking deadlock detected: {mutual_blocking}")
                    deadlock_logger.warning(
                        f"[MUTUAL_BLOCKING] Detected for robots: {', '.join(mutual_blocking)}"
                    )
            
            # 检测活锁（机器人不断移动但无法前进）
            livelock_robots = await self.detect_livelock(robot_ids)
            if livelock_robots:
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == "livelock" and
                        set(deadlock.robot_ids) == set(livelock_robots)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=livelock_robots,
                        deadlock_type="livelock",
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"Livelock detected: {livelock_robots}")
                    deadlock_logger.warning(
                        f"[LIVELOCK] Detected for robots: {', '.join(livelock_robots)}"
                    )
            
            # 检测饥饿死锁（任务等待时间过长）
            starved_robots = await self.detect_starvation(robot_ids)
            if starved_robots:
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == "starvation" and
                        set(deadlock.robot_ids) == set(starved_robots)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=starved_robots,
                        deadlock_type="starvation",
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"Starvation deadlock detected: {starved_robots}")
                    deadlock_logger.warning(
                        f"[STARVATION] Detected for robots: {', '.join(starved_robots)}"
                    )
            
            # 检测卡住的机器人（即使没有任务，如果机器人长时间静止且距离很近，也应该检测）
            stuck_robots = []
            for robot_id in robot_ids:
                if self.check_robot_stuck(robot_id):
                    stuck_robots.append(robot_id)
            
            # 额外检测：如果多个机器人距离很近且都静止，即使没有任务，也可能形成死锁
            if len(stuck_robots) < 2 and len(robot_states) >= 2:
                # 检查是否有多个机器人距离很近且都静止
                robot_list = list(robot_states.keys())
                deadlock_logger.debug(
                    f"[DETECT] Checking {len(robot_list)} robots for close stuck pairs "
                    f"(current stuck: {len(stuck_robots)})"
                )
                for i, robot_id1 in enumerate(robot_list):
                    if robot_id1 in stuck_robots:
                        continue
                    state1 = robot_states[robot_id1]
                    speed1 = state1.speed
                    # 如果机器人静止
                    if speed1.vx == 0 and speed1.vy == 0:
                        for robot_id2 in robot_list[i+1:]:
                            if robot_id2 in stuck_robots:
                                continue
                            state2 = robot_states[robot_id2]
                            speed2 = state2.speed
                            # 如果另一个机器人也静止
                            if speed2.vx == 0 and speed2.vy == 0:
                                distance = self.calculate_distance(state1.pose, state2.pose)
                                # 如果距离很近（小于1.5米），可能相互阻塞
                                if distance < 1.5:
                                    if robot_id1 not in stuck_robots:
                                        stuck_robots.append(robot_id1)
                                    if robot_id2 not in stuck_robots:
                                        stuck_robots.append(robot_id2)
                                    deadlock_logger.warning(
                                        f"[DETECT] Found close stuck robots without tasks: "
                                        f"{robot_id1} (pose=({state1.pose.x:.2f}, {state1.pose.y:.2f})) and "
                                        f"{robot_id2} (pose=({state2.pose.x:.2f}, {state2.pose.y:.2f})) "
                                        f"at distance {distance:.2f}m"
                                    )
            
            if stuck_robots:
                # 如果有多个机器人卡住，使用 mutual_blocking 类型（更合适）
                # 如果只有一个机器人卡住，使用 resource_contention 类型
                deadlock_type = "mutual_blocking" if len(stuck_robots) >= 2 else "resource_contention"
                
                # 检查是否已经记录了死锁
                existing_deadlock = None
                for deadlock in self.deadlock_history:
                    if (deadlock.deadlock_type == deadlock_type and
                        set(deadlock.robot_ids) == set(stuck_robots)):
                        existing_deadlock = deadlock
                        break
                
                if existing_deadlock:
                    # 更新持续时间
                    existing_deadlock.duration = (datetime.now() - existing_deadlock.start_time).total_seconds()
                    deadlocks.append(existing_deadlock)  # 确保已存在的死锁也被返回
                    deadlock_logger.info(
                        f"[DETECT] Existing {deadlock_type} deadlock updated: "
                        f"robots={stuck_robots}, duration={existing_deadlock.duration:.1f}s"
                    )
                else:
                    # 创建新的死锁记录
                    deadlock = DeadlockState(
                        robot_ids=stuck_robots,
                        deadlock_type=deadlock_type,
                        start_time=datetime.now()
                    )
                    self.deadlock_history.append(deadlock)
                    deadlocks.append(deadlock)
                    logger.warning(f"{deadlock_type} deadlock detected: {stuck_robots}")
                    deadlock_logger.warning(
                        f"[{deadlock_type.upper()}] Detected for robots: {', '.join(stuck_robots)}"
                    )
            
            # 清理过期的死锁记录
            self._load_config()  # 重新加载配置
            now = datetime.now()
            self.deadlock_history = [
                d for d in self.deadlock_history
                if (now - d.start_time).total_seconds() < self.history_retention_time
            ]
            
            # 如果有检测到的死锁，记录详细信息（即使未超过阈值也记录）
            if deadlocks:
                for deadlock in deadlocks:
                    deadlock_logger.warning(
                        f"[DETECT] Deadlock detected: type={deadlock.deadlock_type}, "
                        f"robots={deadlock.robot_ids}, duration={deadlock.duration:.1f}s"
                    )
            else:
                # 如果没有检测到死锁，记录调试信息（每10次循环记录一次，避免日志过多）
                # 但只在有多个机器人时记录
                if len(robot_ids) >= 2 and len(robot_states) >= 2:
                    # 记录机器人状态摘要（仅记录静止的机器人）
                    static_robots = []
                    for robot_id, state in robot_states.items():
                        if state.speed.vx == 0 and state.speed.vy == 0:
                            static_robots.append(
                                f"{robot_id}({state.pose.x:.2f},{state.pose.y:.2f})"
                            )
                    if len(static_robots) >= 2:
                        deadlock_logger.debug(
                            f"[DETECT] No deadlock detected. Static robots: {', '.join(static_robots)}"
                        )
            
            return deadlocks
        except Exception as e:
            deadlock_logger.error(f"[ERROR] Exception in detect_deadlocks: {e}", exc_info=True)
            logger.error(f"Exception in detect_deadlocks: {e}", exc_info=True)
            return []
    
    async def resolve_deadlock(self, deadlock: DeadlockState) -> bool:
        """
        解决死锁（优化版本：使用后退、让行等策略，避免取消任务）
        
        Args:
            deadlock: 死锁状态
            
        Returns:
            是否成功解决
        """
        if len(deadlock.robot_ids) == 0:
            return False
        
        deadlock_logger.info(
            f"[RESOLVE] Starting resolution for {deadlock.deadlock_type} deadlock "
            f"involving robots: {', '.join(deadlock.robot_ids)}, duration: {deadlock.duration:.1f}s"
        )
        
        # 根据死锁类型采用不同策略
        if deadlock.deadlock_type == "narrow_passage":
            # 窄道死锁：让优先级低的机器人后退
            result = await self._resolve_narrow_passage_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Narrow passage deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve narrow passage deadlock")
            return result
        elif deadlock.deadlock_type == "circular_wait":
            # 循环等待：打破循环，让一个机器人后退
            result = await self._resolve_circular_wait_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Circular wait deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve circular wait deadlock")
            return result
        elif deadlock.deadlock_type == "mutual_blocking":
            # 相互阻塞：让一个机器人后退
            result = await self._resolve_mutual_blocking_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Mutual blocking deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve mutual blocking deadlock")
            return result
        elif deadlock.deadlock_type == "resource_contention":
            # 资源竞争（单个机器人卡住）：尝试重新发送任务指令或移动到避让点
            result = await self._resolve_resource_contention_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Resource contention deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve resource contention deadlock")
            return result
        elif deadlock.deadlock_type == "livelock":
            # 活锁：让机器人后退或重新规划路径
            result = await self._resolve_livelock_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Livelock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve livelock")
            return result
        elif deadlock.deadlock_type == "starvation":
            # 饥饿死锁：强制分配任务或提高优先级
            result = await self._resolve_starvation_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Starvation deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve starvation deadlock")
            return result
        else:
            # 其他类型：使用默认策略
            result = await self._resolve_default_deadlock(deadlock)
            if result:
                deadlock_logger.info(f"[RESOLVE] Default deadlock resolved successfully")
            else:
                deadlock_logger.error(f"[RESOLVE] Failed to resolve default deadlock")
            return result
    
    def _get_robot_task_priority(self, robot_id: str) -> float:
        """
        获取机器人当前任务的综合优先级（考虑多个因素）
        
        考虑因素：
        1. 任务基础优先级（用户指定或自动计算）
        2. 任务执行时间（执行时间越长，优先级越高，因为已经投入了时间）
        3. 任务完成进度（接近完成的任务优先级更高）
        4. 任务等待时间（如果任务被阻塞，等待时间越长优先级越高）
        5. 任务重试次数（重试次数多说明任务重要或困难）
        
        Args:
            robot_id: 机器人ID
            
        Returns:
            综合优先级值（数值越大优先级越高），如果没有任务则返回0
        """
        if not self.task_scheduler:
            return 0.0
        
        # 查找该机器人的执行中或已分配任务
        task = None
        for t in self.task_scheduler.tasks.values():
            if (t.robot_id == robot_id and 
                (t.status.value in ["EXECUTING", "ASSIGNED", "PENDING"])):
                task = t
                break
        
        if not task:
            return 0.0  # 没有任务时优先级最低
        
        # 基础优先级
        base_priority = task.priority.value
        
        # 因素1：任务执行时间（执行时间越长，优先级越高）
        execution_time_bonus = 0.0
        if task.started_at:
            execution_time = (datetime.now() - task.started_at).total_seconds()
            # 执行时间超过30秒，增加优先级
            if execution_time > 60.0:
                execution_time_bonus = 1.0  # 执行超过1分钟，显著提升优先级
            elif execution_time > 30.0:
                execution_time_bonus = 0.5  # 执行超过30秒，适度提升优先级
        
        # 因素2：任务完成进度（接近完成的任务优先级更高）
        progress_bonus = 0.0
        if task.target_pose:
            try:
                # 获取机器人当前位置
                state = None
                if self.robot_manager:
                    # 注意：这里不能使用await，因为这是同步方法
                    # 在实际使用时，应该在异步方法中获取状态
                    pass
                
                # 如果是多动作任务，考虑剩余动作数
                if task.is_multi_action and task.actions:
                    total_actions = len(task.actions)
                    completed_actions = task.current_action_index or 0
                    if total_actions > 0:
                        progress = completed_actions / total_actions
                        # 完成度超过50%，提升优先级
                        if progress > 0.7:
                            progress_bonus = 0.8  # 接近完成，显著提升优先级
                        elif progress > 0.5:
                            progress_bonus = 0.4  # 完成一半，适度提升优先级
            except Exception:
                pass  # 如果获取状态失败，忽略进度因素
        
        # 因素3：任务等待时间（如果任务被阻塞，等待时间越长优先级越高）
        wait_time_bonus = 0.0
        if task.status.value == "PENDING":
            wait_time = (datetime.now() - task.created_at).total_seconds()
            if wait_time > 60.0:
                wait_time_bonus = 1.0  # 等待超过1分钟，显著提升优先级
            elif wait_time > 30.0:
                wait_time_bonus = 0.5  # 等待超过30秒，适度提升优先级
        
        # 因素4：任务重试次数（重试次数多说明任务重要或困难）
        retry_bonus = 0.0
        if task.retry_count > 0:
            retry_bonus = min(0.5, task.retry_count * 0.1)  # 每次重试增加0.1，最多0.5
        
        # 计算综合优先级
        comprehensive_priority = base_priority + execution_time_bonus + progress_bonus + wait_time_bonus + retry_bonus
        
        # 限制优先级范围（0-5）
        comprehensive_priority = max(0.0, min(5.0, comprehensive_priority))
        
        return comprehensive_priority
    
    async def _get_robot_task_priority_with_state(self, robot_id: str) -> float:
        """
        获取机器人当前任务的综合优先级（异步版本，可以获取机器人状态）
        
        Args:
            robot_id: 机器人ID
            
        Returns:
            综合优先级值（数值越大优先级越高），如果没有任务则返回0
        """
        if not self.task_scheduler:
            return 0.0
        
        # 查找该机器人的执行中或已分配任务
        task = None
        for t in self.task_scheduler.tasks.values():
            if (t.robot_id == robot_id and 
                (t.status.value in ["EXECUTING", "ASSIGNED", "PENDING"])):
                task = t
                break
        
        if not task:
            return 0.0  # 没有任务时优先级最低
        
        # 基础优先级
        base_priority = task.priority.value
        
        # 因素1：任务执行时间
        execution_time_bonus = 0.0
        if task.started_at:
            execution_time = (datetime.now() - task.started_at).total_seconds()
            if execution_time > 60.0:
                execution_time_bonus = 1.0
            elif execution_time > 30.0:
                execution_time_bonus = 0.5
        
        # 因素2：任务完成进度（可以获取机器人状态计算剩余距离）
        progress_bonus = 0.0
        if task.target_pose:
            try:
                state = await self.robot_manager.get_robot_state(robot_id)
                if state and state.pose:
                    # 计算到目标的剩余距离
                    dx = task.target_pose.x - state.pose.x
                    dy = task.target_pose.y - state.pose.y
                    remaining_distance = math.sqrt(dx*dx + dy*dy)
                    
                    # 如果任务有起点，计算总距离
                    if task.start_pose:
                        total_dx = task.target_pose.x - task.start_pose.x
                        total_dy = task.target_pose.y - task.start_pose.y
                        total_distance = math.sqrt(total_dx*total_dx + total_dy*total_dy)
                        
                        if total_distance > 0:
                            progress = 1.0 - (remaining_distance / total_distance)
                            # 完成度超过70%，显著提升优先级
                            if progress > 0.7:
                                progress_bonus = 0.8
                            elif progress > 0.5:
                                progress_bonus = 0.4
                    else:
                        # 如果没有起点，使用剩余距离判断
                        if remaining_distance < 2.0:  # 距离目标小于2米
                            progress_bonus = 0.6
                        elif remaining_distance < 5.0:  # 距离目标小于5米
                            progress_bonus = 0.3
                
                # 如果是多动作任务，考虑剩余动作数
                if task.is_multi_action and task.actions:
                    total_actions = len(task.actions)
                    completed_actions = task.current_action_index or 0
                    if total_actions > 0:
                        progress = completed_actions / total_actions
                        if progress > 0.7:
                            progress_bonus = max(progress_bonus, 0.8)
                        elif progress > 0.5:
                            progress_bonus = max(progress_bonus, 0.4)
            except Exception:
                pass  # 如果获取状态失败，忽略进度因素
        
        # 因素3：任务等待时间
        wait_time_bonus = 0.0
        if task.status.value == "PENDING":
            wait_time = (datetime.now() - task.created_at).total_seconds()
            if wait_time > 60.0:
                wait_time_bonus = 1.0
            elif wait_time > 30.0:
                wait_time_bonus = 0.5
        
        # 因素4：任务重试次数
        retry_bonus = 0.0
        if task.retry_count > 0:
            retry_bonus = min(0.5, task.retry_count * 0.1)
        
        # 计算综合优先级
        comprehensive_priority = base_priority + execution_time_bonus + progress_bonus + wait_time_bonus + retry_bonus
        
        # 限制优先级范围（0-5）
        comprehensive_priority = max(0.0, min(5.0, comprehensive_priority))
        
        return comprehensive_priority
    
    async def _resolve_narrow_passage_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决窄道死锁：使用实际任务优先级，优先使用等待点（支持多台机器人）"""
        deadlock_logger.info(
            f"[UNLOCK] Starting narrow passage deadlock resolution for robots: {deadlock.robot_ids}"
        )
        # 获取每个机器人对应的任务综合优先级（考虑多个因素）
        robot_priorities = []
        robot_states = {}
        
        for robot_id in deadlock.robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state:
                robot_states[robot_id] = state
                # 使用综合优先级（考虑执行时间、完成进度等）
                priority_value = await self._get_robot_task_priority_with_state(robot_id)
                robot_priorities.append((robot_id, priority_value))
        
        if not robot_priorities:
            return False
        
        # 按综合优先级排序（优先级值越小，优先级越低）
        robot_priorities.sort(key=lambda x: x[1])
        
        # 记录优先级信息（用于调试和验证）
        deadlock_logger.info(
            f"[PRIORITY] Narrow passage deadlock resolution priority ranking for {len(robot_priorities)} robots: "
            + ", ".join([f"{rid}({prio:.2f})" for rid, prio in robot_priorities])
        )
        
        # 重新加载配置
        self._load_config()
        
        # 计算需要让行的机器人数量
        # 策略：根据机器人数量动态调整让行数量，支持4-8台机器人场景
        num_robots = len(robot_priorities)
        num_to_resolve = 1  # 默认只让1台机器人后退
        
        if num_robots >= 6:
            # 6台或更多机器人：让1/3的低优先级机器人后退（向上取整）
            num_to_resolve = max(2, (num_robots + 2) // 3)
            logger.info(
                f"Large group deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots (1/3 of total)"
            )
        elif num_robots >= 4:
            # 4-5台机器人：让一半的低优先级机器人后退
            num_to_resolve = max(2, num_robots // 2)
            logger.info(
                f"Medium group deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots (1/2 of total)"
            )
        elif num_robots >= 3:
            # 3台机器人：让1台低优先级机器人后退
            num_to_resolve = 1
            logger.info(
                f"Small group deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robot"
            )
        
        # 计算所有机器人的中心位置（用于确定窄道位置）
        if len(robot_states) > 0:
            center_x = sum(pose.x for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
            center_y = sum(pose.y for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
            narrow_passage_pose = Pose(x=center_x, y=center_y, z=0.0, yaw=0.0)
        else:
            narrow_passage_pose = None
        
        # 让多个低优先级机器人后退
        success_count = 0
        for i in range(min(num_to_resolve, len(robot_priorities))):
            robot_id_to_resolve, priority_value = robot_priorities[i]
            
            agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
            if not agent:
                continue
            
            try:
                # 获取机器人状态
                state = robot_states[robot_id_to_resolve]
                
                # 尝试查找等待点（系统自动计算）
                waiting_point = None
                if self.path_planner:
                    waiting_point = self.path_planner.find_waiting_point(
                        current_pose=state.pose,
                        narrow_passage_pose=narrow_passage_pose,
                        min_distance=self.waiting_point_min_distance,
                        max_distance=self.waiting_point_max_distance,
                        robot_radius=0.3
                    )
                
                if waiting_point:
                    # 使用等待点
                    # 记录原任务信息，以便后续恢复
                    original_task = None
                    original_action_id = None
                    if self.task_scheduler:
                        for task in self.task_scheduler.tasks.values():
                            # 检查任务是否属于这个机器人，且状态是执行中、已分配或待处理
                            # 注意：PENDING 状态的任务也可能需要恢复（如果机器人正在死锁解除中）
                            if (task.robot_id == robot_id_to_resolve and 
                                task.status.value in ["EXECUTING", "ASSIGNED", "PENDING"]):
                                original_task = task
                                original_action_id = task.action_id
                                break
                    
                    # 记录机器人正在执行死锁解除避让
                    if self.task_scheduler and original_task:
                        from datetime import datetime
                        self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                            'task_id': original_task.task_id,
                            'original_action_id': original_action_id,
                            'waiting_point': waiting_point,
                            'start_time': datetime.now()
                        }
                        logger.info(
                            f"Robot {robot_id_to_resolve} task {original_task.task_id} will be resumed "
                            f"after reaching waiting point"
                        )
                    
                    move_result = await agent.move_to(
                        waiting_point, 
                        mode=0, 
                        acceptable_precision=self.backoff_acceptable_precision, 
                        speed_ratio=self.backoff_speed_ratio
                    )
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Narrow passage deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f}), action_id={action_id}"
                    )
                    logger.info(
                        f"Resolved narrow passage deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f}), action_id={action_id}"
                    )
                    if original_task:
                        deadlock_logger.info(
                            f"[UNLOCK] Task {original_task.task_id} will be resumed after robot {robot_id_to_resolve} "
                            f"reaches waiting point (current action_id={action_id})"
                        )
                    success_count += 1
                else:
                    # 如果找不到等待点，使用后退策略
                    back_distance = self.narrow_passage_backoff_distance
                    back_x = state.pose.x - math.cos(state.pose.yaw) * back_distance
                    back_y = state.pose.y - math.sin(state.pose.yaw) * back_distance
                    back_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=state.pose.z,
                        yaw=state.pose.yaw
                    )
                    
                    await agent.move_to(
                        back_pose, 
                        mode=0, 
                        acceptable_precision=self.backoff_acceptable_precision, 
                        speed_ratio=self.backoff_speed_ratio
                    )
                    logger.info(
                        f"Resolved narrow passage deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up (waiting point not found)"
                    )
                    success_count += 1
            
            except Exception as e:
                logger.error(f"Failed to resolve narrow passage deadlock for robot {robot_id_to_resolve}: {e}")
                continue
        
        # 如果至少有一个机器人成功后退，认为死锁已解决
        if success_count > 0:
            # 从死锁历史中移除
            self.deadlock_history = [
                d for d in self.deadlock_history
                if d != deadlock
            ]
            deadlock_logger.info(
                f"[UNLOCK] Narrow passage deadlock resolved: {success_count}/{num_to_resolve} robots moved to waiting points"
            )
            logger.info(
                f"Resolved narrow passage deadlock: {success_count}/{num_to_resolve} robots moved"
            )
            return True
        
        deadlock_logger.warning(
            f"[UNLOCK] Narrow passage deadlock resolution failed: 0/{num_to_resolve} robots moved"
        )
        return False
    
    async def _resolve_circular_wait_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决循环等待死锁：使用实际任务优先级，支持多台机器人场景"""
        # 获取每个机器人对应的任务综合优先级（考虑多个因素）
        robot_priorities = []
        robot_states = {}
        for robot_id in deadlock.robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state:
                robot_states[robot_id] = state
                # 使用综合优先级（考虑执行时间、完成进度等）
                priority_value = await self._get_robot_task_priority_with_state(robot_id)
                robot_priorities.append((robot_id, priority_value))
        
        if not robot_priorities:
            return False
        
        # 按优先级排序（优先级值越小，优先级越低）
        robot_priorities.sort(key=lambda x: x[1])
        
        # 计算需要让行的机器人数量（支持4-8台机器人场景）
        num_robots = len(robot_priorities)
        num_to_resolve = 1  # 默认只让1台机器人后退
        
        if num_robots >= 6:
            # 6台或更多机器人：让1/3的低优先级机器人后退
            num_to_resolve = max(2, (num_robots + 2) // 3)
            logger.info(
                f"Large circular wait deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots"
            )
        elif num_robots >= 4:
            # 4-5台机器人：让一半的低优先级机器人后退
            num_to_resolve = max(2, num_robots // 2)
            logger.info(
                f"Medium circular wait deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots"
            )
        else:
            # 2-3台机器人：让1台低优先级机器人后退
            num_to_resolve = 1
        
        # 重新加载配置
        self._load_config()
        
        # 让多个低优先级机器人后退
        success_count = 0
        for i in range(min(num_to_resolve, len(robot_priorities))):
            robot_id_to_resolve, priority_value = robot_priorities[i]
            
            agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
            if not agent:
                continue
            
            try:
                state = robot_states[robot_id_to_resolve]
                if not state:
                    continue
                
                # 优先尝试查找等待点（系统自动计算）
                waiting_point = None
                if self.path_planner:
                    # 计算所有机器人的中心位置（用于确定等待点位置）
                    center_x = sum(pose.x for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
                    center_y = sum(pose.y for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
                    center_pose = Pose(x=center_x, y=center_y, z=0.0, yaw=0.0)
                    
                    waiting_point = self.path_planner.find_waiting_point(
                        current_pose=state.pose,
                        narrow_passage_pose=center_pose,
                        min_distance=self.waiting_point_min_distance,
                        max_distance=self.waiting_point_max_distance,
                        robot_radius=0.3
                    )
                
                if waiting_point:
                    # 使用等待点（更高效）
                    # 记录原任务信息，以便后续恢复
                    original_task = None
                    original_action_id = None
                    if self.task_scheduler:
                        for task in self.task_scheduler.tasks.values():
                            if (task.robot_id == robot_id_to_resolve and 
                                task.status.value in ["EXECUTING", "ASSIGNED", "PENDING"]):
                                original_task = task
                                original_action_id = task.action_id
                                break
                    
                    # 记录机器人正在执行死锁解除避让
                    if self.task_scheduler and original_task:
                        from datetime import datetime
                        self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                            'task_id': original_task.task_id,
                            'original_action_id': original_action_id,
                            'waiting_point': waiting_point,
                            'start_time': datetime.now()
                        }
                        logger.info(
                            f"Robot {robot_id_to_resolve} task {original_task.task_id} will be resumed "
                            f"after reaching waiting point"
                        )
                    
                    move_result = await agent.move_to(
                        waiting_point, 
                        mode=0, 
                        acceptable_precision=self.backoff_acceptable_precision, 
                        speed_ratio=self.backoff_speed_ratio
                    )
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Circular wait deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f}), action_id={action_id}"
                    )
                    logger.info(
                        f"Resolved circular wait deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f})"
                    )
                    if original_task:
                        deadlock_logger.info(
                            f"[UNLOCK] Task {original_task.task_id} will be resumed after robot {robot_id_to_resolve} "
                            f"reaches waiting point (current action_id={action_id})"
                        )
                    success_count += 1
                else:
                    # 如果找不到等待点，使用后退策略
                    back_distance = self.circular_wait_backoff_distance
                    back_x = state.pose.x - math.cos(state.pose.yaw) * back_distance
                    back_y = state.pose.y - math.sin(state.pose.yaw) * back_distance
                    back_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=state.pose.z,
                        yaw=state.pose.yaw
                    )
                    
                    move_result = await agent.move_to(back_pose, mode=0, acceptable_precision=self.backoff_acceptable_precision, speed_ratio=self.backoff_speed_ratio)
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Circular wait deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up {back_distance}m (waiting point not found), action_id={action_id}"
                    )
                    logger.info(
                        f"Resolved circular wait deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up {back_distance}m (waiting point not found)"
                    )
                    success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to resolve circular wait deadlock for robot {robot_id_to_resolve}: {e}")
                continue
        
        # 如果至少有一个机器人成功后退，认为死锁已解决
        if success_count > 0:
            self.deadlock_history = [
                d for d in self.deadlock_history
                if d != deadlock
            ]
            deadlock_logger.info(
                f"[UNLOCK] Circular wait deadlock resolved: {success_count}/{num_to_resolve} robots moved"
            )
            logger.info(
                f"✓ Circular wait deadlock resolved: {success_count}/{num_to_resolve} robots moved"
            )
            return True
        
        return False
    
    async def _resolve_mutual_blocking_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决相互阻塞死锁：优先使用任务优先级，其次考虑距离"""
        deadlock_logger.info(
            f"[UNLOCK] Starting mutual blocking deadlock resolution for robots: {deadlock.robot_ids}"
        )
        logger.info(f"Resolving mutual blocking deadlock for robots: {deadlock.robot_ids}")
        
        if len(deadlock.robot_ids) < 2:
            logger.warning(f"Mutual blocking deadlock requires at least 2 robots, got {len(deadlock.robot_ids)}")
            return False
        
        # 获取每个机器人的状态和优先级
        robot_info = []
        for robot_id in deadlock.robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if not state:
                logger.warning(f"Could not get state for robot {robot_id} in mutual blocking deadlock")
                continue
            
            # 计算到其他机器人的平均距离
            total_distance = 0.0
            count = 0
            for other_id in deadlock.robot_ids:
                if other_id == robot_id:
                    continue
                other_state = await self.robot_manager.get_robot_state(other_id)
                if other_state:
                    distance = self.calculate_distance(state.pose, other_state.pose)
                    total_distance += distance
                    count += 1
            
            avg_distance = total_distance / count if count > 0 else float('inf')
            # 使用综合优先级（考虑执行时间、完成进度等）
            priority_value = await self._get_robot_task_priority_with_state(robot_id)
            
            # 获取任务信息（用于更细粒度的判断）
            task_execution_time = 0.0
            task_remaining_actions = 0
            if self.task_scheduler:
                for task in self.task_scheduler.tasks.values():
                    if task.robot_id == robot_id and task.status.value in ["EXECUTING", "ASSIGNED"]:
                        # 计算任务执行时间
                        if task.started_at:
                            task_execution_time = (datetime.now() - task.started_at).total_seconds()
                        # 计算剩余动作数（多动作任务）
                        if task.is_multi_action and task.actions:
                            task_remaining_actions = len(task.actions) - (task.current_action_index or 0)
                        break
            
            robot_info.append((
                robot_id, 
                priority_value, 
                avg_distance,
                task_execution_time,  # 执行时间长的优先避让
                -task_remaining_actions,  # 剩余动作多的优先避让（取负值，因为sort是升序）
                robot_id  # 最后按ID排序，确保确定性
            ))
            logger.debug(
                f"Robot {robot_id}: priority={priority_value}, avg_distance={avg_distance:.2f}m, "
                f"execution_time={task_execution_time:.1f}s, remaining_actions={task_remaining_actions}"
            )
        
        if not robot_info:
            logger.error("No valid robot info found for mutual blocking deadlock resolution")
            return False
        
        # 检查是否有机器人没有任务（没有任务的机器人应该优先避让）
        robots_without_task = []
        robots_with_task = []
        for robot_id, priority, avg_dist, exec_time, rem_actions, _ in robot_info:
            has_task = False
            if self.task_scheduler:
                for task in self.task_scheduler.tasks.values():
                    if task.robot_id == robot_id and task.status.value in ["EXECUTING", "ASSIGNED"]:
                        has_task = True
                        break
            if has_task:
                robots_with_task.append((robot_id, priority, avg_dist, exec_time, rem_actions, robot_id))
            else:
                robots_without_task.append((robot_id, priority, avg_dist, exec_time, rem_actions, robot_id))
        
        # 如果有没有任务的机器人，优先让它们避让
        if robots_without_task:
            # 没有任务的机器人优先避让，按距离排序（距离近的优先避让）
            robots_without_task.sort(key=lambda x: (x[2], x[5]))  # 按距离和ID排序
            # 有任务的机器人按综合优先级排序（优先级值越小，优先级越低）
            robots_with_task.sort(key=lambda x: (x[1], x[2], x[3], x[4], x[5]))
            # 合并：没有任务的在前，有任务的在后
            robot_info = robots_without_task + robots_with_task
            deadlock_logger.info(
                f"[RESOLVE] Mutual blocking: {len(robots_without_task)} robots without tasks, "
                f"{len(robots_with_task)} robots with tasks. Robots without tasks will resolve first."
            )
            # 记录有任务机器人的优先级信息
            if robots_with_task:
                deadlock_logger.info(
                    f"[PRIORITY] Robots with tasks priority ranking: "
                    + ", ".join([f"{rid}(priority={prio:.2f}, dist={dist:.2f}m, time={time:.1f}s)" 
                                for rid, prio, dist, time, rem, _ in robots_with_task])
                )
        else:
            # 所有机器人都有任务，按原策略排序
            # 排序策略（优先级从高到低）：
            # 1. 优先级最低的（数值最小）
            # 2. 距离最近的（如果优先级相同）
            # 3. 执行时间最长的（如果优先级和距离都相同）
            # 4. 剩余动作最多的（如果前面都相同）
            # 5. 机器人ID（确保确定性）
            robot_info.sort(key=lambda x: (x[1], x[2], x[3], x[4], x[5]))
        
        # 计算需要让行的机器人数量（支持4-8台机器人场景，使用更激进的策略）
        num_robots = len(robot_info)
        num_to_resolve = 1  # 默认只让1台机器人后退
        
        if num_robots >= 7:
            # 7-8台机器人：让一半的低优先级机器人后退（更激进）
            num_to_resolve = max(3, num_robots // 2)
            logger.info(
                f"Large mutual blocking deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots (aggressive strategy)"
            )
        elif num_robots >= 5:
            # 5-6台机器人：让一半的低优先级机器人后退
            num_to_resolve = max(2, num_robots // 2)
            logger.info(
                f"Medium-large mutual blocking deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots"
            )
        elif num_robots >= 4:
            # 4台机器人：让一半的低优先级机器人后退（2台）
            num_to_resolve = 2
            logger.info(
                f"Medium mutual blocking deadlock ({num_robots} robots), resolving {num_to_resolve} "
                f"lowest priority robots"
            )
        else:
            # 2-3台机器人：让1台低优先级机器人后退
            num_to_resolve = 1
        
        # 重新加载配置
        self._load_config()
        
        # 让多个低优先级机器人后退
        success_count = 0
        for i in range(min(num_to_resolve, len(robot_info))):
            robot_id_to_resolve = robot_info[i][0]
            priority_value = robot_info[i][1]
            avg_distance = robot_info[i][2]
            execution_time = robot_info[i][3]
            remaining_actions = -robot_info[i][4]  # 恢复正值
            
            logger.info(
                f"Selected robot {robot_id_to_resolve} to resolve mutual blocking deadlock "
                f"(priority={priority_value}, avg_distance={avg_distance:.2f}m, "
                f"execution_time={execution_time:.1f}s, remaining_actions={remaining_actions})"
            )
            
            agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
            if not agent:
                logger.error(f"Robot agent not found for {robot_id_to_resolve}")
                continue
            
            try:
                state = await self.robot_manager.get_robot_state(robot_id_to_resolve)
                if not state:
                    logger.error(f"Could not get state for robot {robot_id_to_resolve} before resolving")
                    continue
                
                # 优先尝试查找等待点（系统自动计算）
                waiting_point = None
                if self.path_planner:
                    # 获取所有机器人的状态（用于计算中心位置）
                    all_robot_states = {}
                    for rid in deadlock.robot_ids:
                        rs = await self.robot_manager.get_robot_state(rid)
                        if rs:
                            all_robot_states[rid] = rs
                    
                    if len(all_robot_states) > 0:
                        # 计算所有机器人的中心位置（用于确定等待点位置）
                        center_x = sum(pose.x for pose in [all_robot_states[rid].pose for rid in all_robot_states.keys()]) / len(all_robot_states)
                        center_y = sum(pose.y for pose in [all_robot_states[rid].pose for rid in all_robot_states.keys()]) / len(all_robot_states)
                        center_pose = Pose(x=center_x, y=center_y, z=0.0, yaw=0.0)
                    else:
                        center_pose = None
                    
                    if center_pose:
                        waiting_point = self.path_planner.find_waiting_point(
                            current_pose=state.pose,
                            narrow_passage_pose=center_pose,
                            min_distance=self.waiting_point_min_distance,
                            max_distance=self.waiting_point_max_distance,
                            robot_radius=0.3
                        )
                
                # 检查是否有需要恢复的任务
                original_task = None
                original_action_id = None
                if self.task_scheduler:
                    for task in self.task_scheduler.tasks.values():
                        if (task.robot_id == robot_id_to_resolve and 
                            task.status.value in ["EXECUTING", "ASSIGNED", "PENDING"]):
                            original_task = task
                            original_action_id = task.action_id
                            break
                
                if waiting_point:
                    # 使用等待点（更高效）
                    # 记录机器人正在执行死锁解除避让
                    if self.task_scheduler and original_task:
                        from datetime import datetime
                        self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                            'task_id': original_task.task_id,
                            'original_action_id': original_action_id,
                            'waiting_point': waiting_point,
                            'start_time': datetime.now()
                        }
                        logger.info(
                            f"Robot {robot_id_to_resolve} task {original_task.task_id} will be resumed "
                            f"after reaching waiting point"
                        )
                    
                    move_result = await agent.move_to(
                        waiting_point, 
                        mode=0, 
                        acceptable_precision=self.backoff_acceptable_precision, 
                        speed_ratio=self.backoff_speed_ratio
                    )
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Mutual blocking deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f}), action_id={action_id}"
                    )
                    logger.info(
                        f"✓ Successfully moved robot {robot_id_to_resolve} (priority={priority_value}) "
                        f"to waiting point at ({waiting_point.x:.2f}, {waiting_point.y:.2f}) "
                        f"to resolve mutual blocking deadlock"
                    )
                    if original_task:
                        deadlock_logger.info(
                            f"[UNLOCK] Task {original_task.task_id} will be resumed after robot {robot_id_to_resolve} "
                            f"reaches waiting point (current action_id={action_id})"
                        )
                    success_count += 1
                else:
                    # 如果找不到等待点，使用后退策略
                    back_distance = self.mutual_blocking_backoff_distance
                    logger.info(f"Moving robot {robot_id_to_resolve} back {back_distance}m to resolve deadlock (waiting point not found)")
                    back_x = state.pose.x - math.cos(state.pose.yaw) * back_distance
                    back_y = state.pose.y - math.sin(state.pose.yaw) * back_distance
                    back_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=state.pose.z,
                        yaw=state.pose.yaw
                    )
                    
                    move_result = await agent.move_to(back_pose, mode=0, acceptable_precision=self.backoff_acceptable_precision, speed_ratio=self.backoff_speed_ratio)
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Mutual blocking deadlock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up {back_distance}m (waiting point not found), action_id={action_id}"
                    )
                    logger.info(
                        f"✓ Successfully moved robot {robot_id_to_resolve} (priority={priority_value}) "
                        f"back {back_distance}m to resolve mutual blocking deadlock (waiting point not found)"
                    )
                    
                    # 如果有任务，记录需要恢复（对于后退策略，后退后立即恢复任务）
                    if original_task and self.task_scheduler:
                        from datetime import datetime
                        self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                            'task_id': original_task.task_id,
                            'original_action_id': original_action_id,
                            'waiting_point': back_pose,  # 使用后退点作为"等待点"
                            'start_time': datetime.now(),
                            'immediate_resume': True  # 标记为立即恢复
                        }
                        deadlock_logger.info(
                            f"[UNLOCK] Task {original_task.task_id} will be resumed after robot {robot_id_to_resolve} "
                            f"backs up (action_id={action_id})"
                        )
                    
                    success_count += 1
                
            except Exception as e:
                logger.error(
                    f"✗ Failed to resolve mutual blocking deadlock for robot {robot_id_to_resolve}: {e}",
                    exc_info=True
                )
                continue
        
        # 如果至少有一个机器人成功后退，认为死锁已解决
        if success_count > 0:
            # 从死锁历史中移除
            self.deadlock_history = [
                d for d in self.deadlock_history
                if d != deadlock
            ]
            
            deadlock_logger.info(
                f"[UNLOCK] Mutual blocking deadlock resolved: {success_count}/{num_to_resolve} robots moved "
                f"for robots {deadlock.robot_ids}"
            )
            logger.info(
                f"✓ Mutual blocking deadlock resolved: {success_count}/{num_to_resolve} robots moved "
                f"for robots {deadlock.robot_ids}"
            )
            return True
        
        deadlock_logger.warning(
            f"[UNLOCK] Mutual blocking deadlock resolution failed: 0/{num_to_resolve} robots moved"
        )
        return False
    
    async def _resolve_resource_contention_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决资源竞争死锁（单个机器人卡住）：尝试重新发送任务指令"""
        if len(deadlock.robot_ids) == 0:
            return False
        
        robot_id_to_resolve = deadlock.robot_ids[0]
        agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
        if not agent:
            logger.error(f"Robot agent not found for {robot_id_to_resolve}")
            return False
        
        try:
            # 获取该机器人的当前任务
            if not self.task_scheduler:
                logger.error("Task scheduler not available for resolving resource contention deadlock")
                return False
            
            # 查找该机器人的执行中任务
            task = None
            for t in self.task_scheduler.tasks.values():
                if t.robot_id == robot_id_to_resolve and t.status.value in ["EXECUTING", "ASSIGNED"]:
                    task = t
                    break
            
            if not task:
                logger.warning(f"No executing task found for robot {robot_id_to_resolve} in resource contention deadlock")
                # 即使没有任务，也尝试让机器人后退一点，避免卡在当前位置
                state = await self.robot_manager.get_robot_state(robot_id_to_resolve)
                if state and state.pose:
                    back_distance = 1.0
                    back_x = state.pose.x - math.cos(state.pose.yaw) * back_distance
                    back_y = state.pose.y - math.sin(state.pose.yaw) * back_distance
                    back_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=state.pose.z,
                        yaw=state.pose.yaw
                    )
                    await agent.move_to(back_pose, mode=0, acceptable_precision=0.3, speed_ratio=0.5)
                    logger.info(f"Resolved resource contention deadlock: robot {robot_id_to_resolve} backed up (no active task)")
                    self.deadlock_history = [d for d in self.deadlock_history if d != deadlock]
                    return True
                return False
            
            # 如果是多动作任务，继续执行下一个动作
            if task.is_multi_action and task.actions:
                logger.info(f"Resolving resource contention deadlock for multi-action task {task.task_id}, continuing next action")
                await self.task_scheduler._execute_next_action(task, agent, robot_id_to_resolve)
                logger.info(f"Resolved resource contention deadlock: robot {robot_id_to_resolve} continuing multi-action task")
                self.deadlock_history = [d for d in self.deadlock_history if d != deadlock]
                return True
            else:
                # 普通任务：尝试使用等待点或重新发送move_to指令
                if task.target_pose:
                    # 首先尝试找到等待点（更高效）
                    state = await self.robot_manager.get_robot_state(robot_id_to_resolve)
                    if state and state.pose:
                        # 尝试找到等待点
                        waiting_point = None
                        if self.path_planner:
                            try:
                                # 获取所有其他机器人的位置
                                other_robot_states = {}
                                for other_id in deadlock.robot_ids:
                                    if other_id != robot_id_to_resolve:
                                        other_state = await self.robot_manager.get_robot_state(other_id)
                                        if other_state and other_state.pose:
                                            other_robot_states[other_id] = other_state.pose
                                
                                # 计算中心位置（用于寻找等待点）
                                if other_robot_states:
                                    center_x = sum(p.x for p in other_robot_states.values()) / len(other_robot_states)
                                    center_y = sum(p.y for p in other_robot_states.values()) / len(other_robot_states)
                                    center_pose = Pose(x=center_x, y=center_y, yaw=0.0)
                                    
                                    # 寻找等待点
                                    waiting_point = self.path_planner.find_waiting_point(
                                        robot_pose=state.pose,
                                        target_pose=task.target_pose,
                                        other_robots=other_robot_states,
                                        center_pose=center_pose
                                    )
                            except Exception as e:
                                logger.debug(f"Failed to find waiting point for resource contention deadlock: {e}")
                        
                        if waiting_point:
                            # 使用等待点（更高效）
                            logger.info(
                                f"Resolving resource contention deadlock for task {task.task_id}, "
                                f"moving to waiting point at ({waiting_point.x:.2f}, {waiting_point.y:.2f})"
                            )
                            move_result = await agent.move_to(
                                waiting_point,
                                mode=0,
                                acceptable_precision=self.backoff_acceptable_precision,
                                speed_ratio=self.backoff_speed_ratio
                            )
                            action_id = move_result.action_id if move_result else None
                            deadlock_logger.info(
                                f"[UNLOCK] Resource contention deadlock: robot {robot_id_to_resolve} "
                                f"moving to waiting point at ({waiting_point.x:.2f}, {waiting_point.y:.2f}), "
                                f"action_id={action_id}"
                            )
                            
                            # 记录任务恢复信息
                            if self.task_scheduler:
                                from datetime import datetime
                                self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                                    'task_id': task.task_id,
                                    'original_action_id': task.action_id,
                                    'waiting_point': waiting_point,
                                    'start_time': datetime.now()
                                }
                                logger.info(
                                    f"Robot {robot_id_to_resolve} task {task.task_id} will be resumed "
                                    f"after reaching waiting point"
                                )
                            
                            self.deadlock_history = [d for d in self.deadlock_history if d != deadlock]
                            return True
                        else:
                            # 如果找不到等待点，重新发送move_to指令
                            logger.info(f"Resolving resource contention deadlock for task {task.task_id}, resending move_to command (waiting point not found)")
                            move_result = await agent.move_to(
                                task.target_pose,
                                mode=0,
                                acceptable_precision=0.3,
                                speed_ratio=1.0
                            )
                            task.action_id = move_result.action_id
                            deadlock_logger.info(
                                f"[UNLOCK] Resource contention deadlock: robot {robot_id_to_resolve} "
                                f"resent move_to command, new action_id={task.action_id}"
                            )
                            logger.info(f"Resolved resource contention deadlock: robot {robot_id_to_resolve} resent move_to command, new action_id={task.action_id}")
                            self.deadlock_history = [d for d in self.deadlock_history if d != deadlock]
                            return True
                    else:
                        # 无法获取机器人状态，直接重新发送move_to指令
                        logger.info(f"Resolving resource contention deadlock for task {task.task_id}, resending move_to command (robot state unavailable)")
                        move_result = await agent.move_to(
                            task.target_pose,
                            mode=0,
                            acceptable_precision=0.3,
                            speed_ratio=1.0
                        )
                        task.action_id = move_result.action_id
                        deadlock_logger.info(
                            f"[UNLOCK] Resource contention deadlock: robot {robot_id_to_resolve} "
                            f"resent move_to command, new action_id={task.action_id}"
                        )
                        logger.info(f"Resolved resource contention deadlock: robot {robot_id_to_resolve} resent move_to command, new action_id={task.action_id}")
                        self.deadlock_history = [d for d in self.deadlock_history if d != deadlock]
                        return True
                else:
                    logger.warning(f"Task {task.task_id} has no target_pose, cannot resolve resource contention deadlock")
                    return False
        except Exception as e:
            logger.error(f"Failed to resolve resource contention deadlock for robot {robot_id_to_resolve}: {e}", exc_info=True)
            return False
    
    async def _resolve_default_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决默认死锁（最后手段：短暂停止后继续）"""
        robot_id_to_resolve = deadlock.robot_ids[0]
        
        agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
        if not agent:
            return False
        
        try:
            # 短暂停止（不取消任务）
            await agent.cancel_current_action()
            import asyncio
            await asyncio.sleep(2.0)  # 等待2秒
            
            logger.info(f"Resolved default deadlock: robot {robot_id_to_resolve} paused and will continue")
            
            # 从死锁历史中移除
            self.deadlock_history = [
                d for d in self.deadlock_history
                if d != deadlock
            ]
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to resolve default deadlock for robot {robot_id_to_resolve}: {e}")
            return False
    
    async def _resolve_livelock_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决活锁：让机器人后退或重新规划路径，支持多台机器人场景"""
        deadlock_logger.info(f"Resolving livelock for robots: {deadlock.robot_ids}")
        
        if len(deadlock.robot_ids) < 1:
            return False
        
        # 获取每个机器人对应的任务优先级
        robot_priorities = []
        robot_states = {}
        
        for robot_id in deadlock.robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state:
                robot_states[robot_id] = state
                priority_value = self._get_robot_task_priority(robot_id)
                robot_priorities.append((robot_id, priority_value))
        
        if not robot_priorities:
            return False
        
        # 按优先级排序（优先级值越小，优先级越低）
        robot_priorities.sort(key=lambda x: x[1])
        
        # 计算需要让行的机器人数量（支持4-8台机器人场景）
        num_robots = len(robot_priorities)
        num_to_resolve = 1  # 默认只让1台机器人后退
        
        if num_robots >= 6:
            # 6台或更多机器人：让1/3的低优先级机器人后退
            num_to_resolve = max(2, (num_robots + 2) // 3)
            deadlock_logger.info(
                f"Large livelock ({num_robots} robots), resolving {num_to_resolve} lowest priority robots"
            )
        elif num_robots >= 4:
            # 4-5台机器人：让一半的低优先级机器人后退
            num_to_resolve = max(2, num_robots // 2)
            deadlock_logger.info(
                f"Medium livelock ({num_robots} robots), resolving {num_to_resolve} lowest priority robots"
            )
        else:
            # 1-3台机器人：让1台低优先级机器人后退
            num_to_resolve = 1
        
        # 重新加载配置
        self._load_config()
        
        # 让多个低优先级机器人后退
        success_count = 0
        for i in range(min(num_to_resolve, len(robot_priorities))):
            robot_id_to_resolve, priority_value = robot_priorities[i]
            
            agent = self.robot_manager.get_robot_agent(robot_id_to_resolve)
            if not agent:
                continue
            
            try:
                state = robot_states[robot_id_to_resolve]
                if not state:
                    continue
                
                # 优先尝试查找等待点（系统自动计算）
                waiting_point = None
                if self.path_planner:
                    if len(robot_states) > 0:
                        # 计算所有机器人的中心位置（用于确定等待点位置）
                        center_x = sum(pose.x for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
                        center_y = sum(pose.y for pose in [robot_states[rid].pose for rid in robot_states.keys()]) / len(robot_states)
                        center_pose = Pose(x=center_x, y=center_y, z=0.0, yaw=0.0)
                    else:
                        center_pose = None
                    
                    if center_pose:
                        waiting_point = self.path_planner.find_waiting_point(
                            current_pose=state.pose,
                            narrow_passage_pose=center_pose,
                            min_distance=self.waiting_point_min_distance,
                            max_distance=self.waiting_point_max_distance,
                            robot_radius=0.3
                        )
                
                if waiting_point:
                    # 使用等待点（更高效）
                    # 记录原任务信息，以便后续恢复
                    original_task = None
                    original_action_id = None
                    if self.task_scheduler:
                        for task in self.task_scheduler.tasks.values():
                            if (task.robot_id == robot_id_to_resolve and 
                                task.status.value in ["EXECUTING", "ASSIGNED", "PENDING"]):
                                original_task = task
                                original_action_id = task.action_id
                                break
                    
                    # 记录机器人正在执行死锁解除避让
                    if self.task_scheduler and original_task:
                        from datetime import datetime
                        self.task_scheduler.robots_in_deadlock_resolution[robot_id_to_resolve] = {
                            'task_id': original_task.task_id,
                            'original_action_id': original_action_id,
                            'waiting_point': waiting_point,
                            'start_time': datetime.now()
                        }
                        logger.info(
                            f"Robot {robot_id_to_resolve} task {original_task.task_id} will be resumed "
                            f"after reaching waiting point"
                        )
                    
                    move_result = await agent.move_to(
                        waiting_point, 
                        mode=0, 
                        acceptable_precision=self.backoff_acceptable_precision, 
                        speed_ratio=self.backoff_speed_ratio
                    )
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Livelock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f}), action_id={action_id}"
                    )
                    logger.info(
                        f"Resolved livelock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) moving to waiting point at "
                        f"({waiting_point.x:.2f}, {waiting_point.y:.2f})"
                    )
                    if original_task:
                        deadlock_logger.info(
                            f"[UNLOCK] Task {original_task.task_id} will be resumed after robot {robot_id_to_resolve} "
                            f"reaches waiting point (current action_id={action_id})"
                        )
                    success_count += 1
                else:
                    # 如果找不到等待点，使用后退策略（活锁需要更大的后退距离）
                    back_distance = 2.0  # 活锁需要后退更远
                    back_x = state.pose.x - math.cos(state.pose.yaw) * back_distance
                    back_y = state.pose.y - math.sin(state.pose.yaw) * back_distance
                    back_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=state.pose.z,
                        yaw=state.pose.yaw
                    )
                    
                    move_result = await agent.move_to(back_pose, mode=0, acceptable_precision=self.backoff_acceptable_precision, speed_ratio=self.backoff_speed_ratio)
                    action_id = move_result.action_id if move_result else None
                    deadlock_logger.info(
                        f"[UNLOCK] Livelock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up {back_distance}m (waiting point not found), action_id={action_id}"
                    )
                    logger.info(
                        f"Resolved livelock: robot {robot_id_to_resolve} "
                        f"(priority={priority_value}) backing up {back_distance}m (waiting point not found)"
                    )
                    success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to resolve livelock for robot {robot_id_to_resolve}: {e}")
                deadlock_logger.error(f"[LIVELOCK] Failed to resolve for robot {robot_id_to_resolve}: {e}")
                continue
        
        # 如果至少有一个机器人成功后退，认为死锁已解决
        if success_count > 0:
            self.deadlock_history = [
                d for d in self.deadlock_history
                if d != deadlock
            ]
            logger.info(
                f"✓ Livelock resolved: {success_count}/{num_to_resolve} robots moved"
            )
            deadlock_logger.info(
                f"[LIVELOCK] Resolved: {success_count}/{num_to_resolve} robots moved"
            )
            return True
        
        return False
    
    async def _resolve_starvation_deadlock(self, deadlock: DeadlockState) -> bool:
        """解决饥饿死锁：强制分配任务或提高优先级"""
        deadlock_logger.info(f"Resolving starvation deadlock for robots: {deadlock.robot_ids}")
        
        if not self.task_scheduler:
            deadlock_logger.error("[STARVATION] Task scheduler not available")
            return False
        
        # 找到等待时间最长的待分配任务
        now = datetime.now()
        longest_waiting_task = None
        longest_wait_time = 0.0
        
        for task in self.task_scheduler.tasks.values():
            if task.status.value != "PENDING":
                continue
            
            if task.created_at:
                wait_time = (now - task.created_at).total_seconds()
                if wait_time > longest_wait_time:
                    longest_wait_time = wait_time
                    longest_waiting_task = task
        
        if not longest_waiting_task:
            deadlock_logger.warning("[STARVATION] No pending tasks found")
            return False
        
        # 检查是否有可用机器人
        available_robots = []
        for robot_id in deadlock.robot_ids:
            state = await self.robot_manager.get_robot_state(robot_id)
            if state and state.status.value in ["idle", "online"]:
                # 检查是否有正在执行的任务
                has_executing_task = any(
                    t.robot_id == robot_id and t.status.value in ["EXECUTING", "ASSIGNED"]
                    for t in self.task_scheduler.tasks.values()
                )
                if not has_executing_task:
                    available_robots.append(robot_id)
        
        if len(available_robots) == 0:
            deadlock_logger.warning(
                f"[STARVATION] No available robots for task {longest_waiting_task.task_id}"
            )
            return False
        
        # 提高任务优先级（如果当前优先级较低）
        from app.models.task import TaskPriority
        if longest_waiting_task.priority.value < TaskPriority.HIGH.value:
            old_priority = longest_waiting_task.priority
            longest_waiting_task.priority = TaskPriority.HIGH
            logger.info(
                f"Starvation resolution: Task {longest_waiting_task.task_id} priority "
                f"increased from {old_priority.name} to HIGH"
            )
            deadlock_logger.info(
                f"[STARVATION] Task {longest_waiting_task.task_id} priority increased "
                f"from {old_priority.name} to HIGH"
            )
        
        # 尝试立即分配任务（触发调度器事件）
        if hasattr(self.task_scheduler, '_scheduler_event') and self.task_scheduler._scheduler_event:
            self.task_scheduler._scheduler_event.set()
            deadlock_logger.info(
                f"[STARVATION] Triggered scheduler event for task {longest_waiting_task.task_id}"
            )
        
        # 从死锁历史中移除
        self.deadlock_history = [
            d for d in self.deadlock_history
            if d != deadlock
        ]
        
        logger.info(
            f"✓ Starvation deadlock resolved: Task {longest_waiting_task.task_id} "
            f"priority increased, scheduler triggered"
        )
        deadlock_logger.info(
            f"[STARVATION] Resolved: Task {longest_waiting_task.task_id} priority increased, "
            f"wait_time={longest_wait_time:.1f}s"
        )
        
        return True

