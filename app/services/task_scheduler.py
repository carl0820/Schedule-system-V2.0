"""
任务调度器（增强版本：集成碰撞检测、避让策略和死锁处理）
"""
import uuid
import asyncio
import logging
import math
import json
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import httpx
from app.models.task import Task, TaskCreate, TaskStatus, TaskPriority, MultiActionTaskCreate, ActionItem, ActionType
from app.services.robot_manager import RobotManager, get_robot_manager
from app.services.path_planner import PathPlanner
from app.services.collision_detector import CollisionDetector
from app.services.avoidance_strategy import AvoidanceStrategy
from app.services.deadlock_detector import DeadlockDetector
from app.services.priority_calculator import PriorityCalculator
from app.models.robot import Pose, RobotStatus

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度器，管理任务的创建、分配和执行（集成碰撞检测和避让策略）"""
    
    # 存储文件路径
    STORAGE_FILE = Path("data/tasks.json")
    
    def __init__(
        self,
        robot_manager: RobotManager,
        path_planner: PathPlanner,
        collision_detector: Optional[CollisionDetector] = None,
        avoidance_strategy: Optional[AvoidanceStrategy] = None,
        deadlock_detector: Optional[DeadlockDetector] = None
    ):
        """
        初始化任务调度器
        
        Args:
            robot_manager: 机器人管理器
            path_planner: 路径规划器
            collision_detector: 碰撞检测器（可选）
            avoidance_strategy: 避让策略（可选）
            deadlock_detector: 死锁检测器（可选）
        """
        self.robot_manager = robot_manager
        self.path_planner = path_planner
        self.tasks: Dict[str, Task] = {}  # task_id -> Task
        self._scheduler_task: Optional[asyncio.Task] = None
        
        # 确保数据目录存在
        self.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 从文件加载已保存的任务
        self._load_tasks_from_file()
        
        # 初始化碰撞检测和避让策略
        if collision_detector is None:
            from app.services.collision_detector import CollisionDetector
            collision_detector = CollisionDetector(robot_manager)
        self.collision_detector = collision_detector
        
        if avoidance_strategy is None:
            from app.services.avoidance_strategy import AvoidanceStrategy
            from app.services.scene_detector import SceneDetector
            from app.services.map_manager import get_map_manager
            map_manager = get_map_manager()
            scene_detector = SceneDetector(map_manager, path_planner)
            avoidance_strategy = AvoidanceStrategy(
                robot_manager,
                collision_detector,
                path_planner,
                scene_detector
            )
        self.avoidance_strategy = avoidance_strategy
        
        if deadlock_detector is None:
            from app.services.deadlock_detector import DeadlockDetector
            # 传入任务调度器引用，让死锁检测器可以访问任务优先级
            deadlock_detector = DeadlockDetector(robot_manager, collision_detector, path_planner, task_scheduler=self)
        else:
            # 如果已经提供了死锁检测器，也设置任务调度器引用
            deadlock_detector.task_scheduler = self
        self.deadlock_detector = deadlock_detector
        
        # 启动碰撞检测和死锁检测任务
        self._collision_check_task: Optional[asyncio.Task] = None
        self._deadlock_check_task: Optional[asyncio.Task] = None
        
        # 存储每个任务的规划路径，用于碰撞检测
        self.task_paths: Dict[str, List[Pose]] = {}  # task_id -> path
        
        # 记录已完成任务的机器人是否正在执行避让动作（防止重复触发）
        self.completed_robots_avoiding: Set[str] = set()  # robot_id set
        
        # 记录因死锁解除而移动到等待点的机器人及其原任务（用于恢复任务执行）
        # 格式: {robot_id: {'task_id': str, 'original_action_id': str, 'waiting_point': Pose, 'start_time': datetime}}
        self.robots_in_deadlock_resolution: Dict[str, Dict] = {}
        
        # 初始化优先级计算器
        self.priority_calculator = PriorityCalculator(robot_manager, path_planner)
        
        # 如果加载的任务中有执行中的任务，启动后台任务（死锁检测、碰撞检测等）
        self._start_background_tasks_if_needed()
    
    def _start_background_tasks_if_needed(self):
        """如果有执行中的任务，启动后台任务（死锁检测、碰撞检测等）
        注意：这个方法在同步上下文中调用，不能直接创建异步任务
        """
        # 检查是否有执行中或已分配的任务
        has_executing_tasks = any(
            t.status in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED] and t.robot_id
            for t in self.tasks.values()
        )
        
        if has_executing_tasks:
            logger.info("Found executing/assigned tasks from file, will start background tasks in async context")
            # 标记需要启动后台任务，在异步上下文中调用_start_background_tasks_if_needed_async
            self._need_start_background_tasks = True
    
    async def _start_background_tasks_if_needed_async(self):
        """在异步上下文中启动后台任务（死锁检测、碰撞检测等）"""
        # 检查是否有执行中或已分配的任务
        has_executing_tasks = any(
            t.status in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED] and t.robot_id
            for t in self.tasks.values()
        )
        
        executing_count = sum(1 for t in self.tasks.values() 
                             if t.status in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED] and t.robot_id)
        
        if has_executing_tasks or getattr(self, '_need_start_background_tasks', False):
            logger.info(f"Found {executing_count} executing/assigned tasks, starting background tasks...")
            # 启动调度器
            if self._scheduler_task is None or (self._scheduler_task and self._scheduler_task.done()):
                logger.info("Starting scheduler loop...")
                self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            
            # 启动碰撞检测任务
            if self._collision_check_task is None or (self._collision_check_task and self._collision_check_task.done()):
                logger.info("Starting collision check loop...")
                self._collision_check_task = asyncio.create_task(self._collision_check_loop())
            
            # 启动死锁检测任务
            if self._deadlock_check_task is None or (self._deadlock_check_task and self._deadlock_check_task.done()):
                logger.info("Starting deadlock check loop...")
                try:
                    self._deadlock_check_task = asyncio.create_task(self._deadlock_check_loop())
                    logger.info("Deadlock check loop started successfully")
                except Exception as e:
                    logger.error(f"Failed to start deadlock check loop: {e}", exc_info=True)
            else:
                logger.info(f"Deadlock check loop already running (task state: done={self._deadlock_check_task.done()})")
            
            logger.info(f"Background tasks started for {executing_count} existing executing tasks")
            self._need_start_background_tasks = False
        else:
            logger.debug(f"No executing tasks found ({executing_count} executing/assigned tasks), background tasks not started")
    
    def _load_tasks_from_file(self):
        """从文件加载已保存的任务"""
        import time
        load_start = time.time()
        try:
            if not self.STORAGE_FILE.exists():
                logger.info(f"Storage file {self.STORAGE_FILE} does not exist. Starting with empty task list.")
                return
            
            with open(self.STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            load_elapsed = time.time() - load_start
            logger.debug(f"Loaded tasks file in {load_elapsed:.3f}s")
            
            if not isinstance(data, dict) or 'tasks' not in data:
                logger.warning(f"Invalid storage file format: {self.STORAGE_FILE}")
                return
            
            tasks_data = data.get('tasks', [])
            if not isinstance(tasks_data, list):
                logger.warning(f"Invalid tasks data format in {self.STORAGE_FILE}")
                return
            
            loaded_count = 0
            for task_data in tasks_data:
                try:
                    # 解析datetime字段
                    if 'created_at' in task_data:
                        task_data['created_at'] = datetime.fromisoformat(task_data['created_at'])
                    if 'assigned_at' in task_data and task_data['assigned_at']:
                        task_data['assigned_at'] = datetime.fromisoformat(task_data['assigned_at'])
                    if 'started_at' in task_data and task_data['started_at']:
                        task_data['started_at'] = datetime.fromisoformat(task_data['started_at'])
                    if 'completed_at' in task_data and task_data['completed_at']:
                        task_data['completed_at'] = datetime.fromisoformat(task_data['completed_at'])
                    
                    # 解析Pose对象
                    if 'start_pose' in task_data and task_data['start_pose']:
                        task_data['start_pose'] = Pose(**task_data['start_pose'])
                    if 'target_pose' in task_data:
                        task_data['target_pose'] = Pose(**task_data['target_pose'])
                    
                    # 解析枚举
                    if 'status' in task_data:
                        task_data['status'] = TaskStatus(task_data['status'])
                    if 'priority' in task_data:
                        task_data['priority'] = TaskPriority(task_data['priority'])
                    
                    task = Task(**task_data)
                    self.tasks[task.task_id] = task
                    loaded_count += 1
                except Exception as e:
                    logger.warning(f"Failed to load task from storage: {e}")
                    continue
            
            logger.info(f"Loaded {loaded_count} tasks from storage file")
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in storage file {self.STORAGE_FILE}: {e}")
        except Exception as e:
            logger.error(f"Failed to load tasks from storage file {self.STORAGE_FILE}: {e}", exc_info=True)
    
    def _save_tasks_to_file(self):
        """保存所有任务到文件（同步版本，用于后台任务）"""
        try:
            tasks_data = []
            for task in self.tasks.values():
                # 将Task对象转换为字典
                task_dict = task.dict()
                tasks_data.append(task_dict)
            
            data = {
                'tasks': tasks_data,
                'last_updated': datetime.now().isoformat()
            }
            
            # 使用临时文件写入，然后重命名，确保原子性
            temp_file = self.STORAGE_FILE.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            
            # 原子性替换
            temp_file.replace(self.STORAGE_FILE)
            
            logger.debug(f"Saved {len(tasks_data)} tasks to storage file")
            
        except Exception as e:
            logger.error(f"Failed to save tasks to storage file {self.STORAGE_FILE}: {e}", exc_info=True)
    
    async def _save_tasks_to_file_async(self):
        """异步保存所有任务到文件（用于API调用，避免阻塞）"""
        await asyncio.to_thread(self._save_tasks_to_file)
    
    async def create_task(self, task_create: TaskCreate) -> Task:
        """
        创建任务（自动计算优先级）
        
        Args:
            task_create: 任务创建请求
            
        Returns:
            创建的任务
        """
        # 自动计算优先级（如果用户没有指定）
        if task_create.priority is None:
            # 如果没有起点，尝试使用最近的空闲机器人位置来估算
            start_pose_for_calc = task_create.start_pose
            if start_pose_for_calc is None:
                # 查找最近的空闲机器人
                robot_ids = self.robot_manager.list_robots()
                min_distance = float('inf')
                nearest_robot_pose = None
                
                for robot_id in robot_ids:
                    try:
                        state = await self.robot_manager.get_robot_state(robot_id)
                        if state and state.status == RobotStatus.IDLE:
                            # 检查是否有正在执行的任务
                            has_executing_task = any(
                                t.robot_id == robot_id and t.status == TaskStatus.EXECUTING
                                for t in self.tasks.values()
                            )
                            if not has_executing_task:
                                # 计算到目标点的距离
                                dx = state.pose.x - task_create.target_pose.x
                                dy = state.pose.y - task_create.target_pose.y
                                distance = math.sqrt(dx*dx + dy*dy)
                                if distance < min_distance:
                                    min_distance = distance
                                    nearest_robot_pose = state.pose
                    except Exception as e:
                        logger.debug(f"Failed to get state for robot {robot_id}: {e}")
                        continue
                
                if nearest_robot_pose:
                    start_pose_for_calc = nearest_robot_pose
                    logger.debug(f"Using nearest robot pose for priority calculation: ({nearest_robot_pose.x}, {nearest_robot_pose.y})")
            
            # 使用路径规划计算更准确的优先级
            calculated_priority = self.priority_calculator.calculate_priority_with_path(
                task_create.target_pose,
                start_pose_for_calc
            )
            # 如果有POI信息，也会影响优先级计算
            if task_create.poi_name:
                # POI任务通常比较重要，适当提高
                if calculated_priority.value < TaskPriority.HIGH.value:
                    calculated_priority = TaskPriority.HIGH
            priority = calculated_priority
            logger.info(f"Auto-calculated priority for new task: {priority.value} ({priority.name})")
        else:
            # 用户指定了优先级，使用用户指定的
            priority = task_create.priority
            logger.info(f"Using user-specified priority: {priority.value} ({priority.name})")
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 创建任务对象
        task = Task(
            task_id=task_id,
            robot_id=None,
            status=TaskStatus.PENDING,
            start_pose=task_create.start_pose,
            target_pose=task_create.target_pose,
            priority=priority,
            action_id=None,
            created_at=datetime.now(),
            retry_count=0
        )
        
        # 保存任务
        self.tasks[task_id] = task
        logger.info(f"Task {task_id} saved to tasks dict. Total tasks: {len(self.tasks)}")
        
        # 持久化到文件
        self._save_tasks_to_file()
        
        # 启动调度器（如果还没有启动）
        if self._scheduler_task is None or self._scheduler_task.done():
            logger.info("Starting scheduler loop...")
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        else:
            logger.info("Scheduler loop already running")
        
        # 启动碰撞检测任务（如果还没有启动或已停止）
        if self._collision_check_task is None or self._collision_check_task.done():
            logger.info("Starting collision check loop...")
            self._collision_check_task = asyncio.create_task(self._collision_check_loop())
        else:
            logger.debug("Collision check loop already running")
        
        # 启动死锁检测任务（如果还没有启动或已停止）
        if self._deadlock_check_task is None or self._deadlock_check_task.done():
            logger.info("Starting deadlock check loop...")
            self._deadlock_check_task = asyncio.create_task(self._deadlock_check_loop())
        else:
            logger.debug("Deadlock check loop already running")
        
        elapsed_time = time.time() - start_time
        logger.info(f"Task {task_id} created: target=({task_create.target_pose.x}, {task_create.target_pose.y}), status={task.status.value}, elapsed={elapsed_time:.3f}s")
        return task
    
    async def create_multi_action_task(self, task_create: MultiActionTaskCreate) -> Task:
        """
        创建多动作任务（优化：立即返回任务ID，所有耗时操作异步处理）
        
        Args:
            task_create: 多动作任务创建请求
            
        Returns:
            创建的任务（立即返回，不等待文件保存和后台任务启动）
        """
        # 验证动作序列（快速验证，不阻塞）
        if not task_create.actions or len(task_create.actions) == 0:
            raise ValueError("Actions list cannot be empty")
        
        logger.info(f"Creating multi-action task with {len(task_create.actions)} actions")
        
        # 验证每个动作（基本验证，快速完成）
        for i, action in enumerate(task_create.actions):
            if action.action_type == ActionType.MOVE_TO:
                if not action.target_pose and not action.poi_name:
                    raise ValueError(f"Action {i}: move_to requires either target_pose or poi_name")
            elif action.action_type == ActionType.WAIT:
                if action.wait_duration is None or action.wait_duration <= 0:
                    raise ValueError(f"Action {i}: wait requires wait_duration > 0")
            elif action.action_type == ActionType.GO_HOME:
                pass  # 回桩不需要额外参数
            else:
                raise ValueError(f"Action {i}: unknown action type {action.action_type}")
        
        # 使用默认优先级（不计算，立即返回）
        priority = task_create.priority if task_create.priority is not None else TaskPriority.NORMAL
        
        # 生成任务ID（立即生成）
        task_id = str(uuid.uuid4())
        
        # 确定目标位置（快速确定，使用第一个移动动作的目标位置）
        target_pose = None
        for action in task_create.actions:
            if action.action_type == ActionType.MOVE_TO:
                if action.target_pose:
                    target_pose = action.target_pose
                    break
                elif action.poi_name:
                    # POI导航：使用默认位置，任务分配时再获取实际位置
                    target_pose = Pose(x=0.0, y=0.0, yaw=0.0)
                    break
        
        # 如果没有移动动作，使用起点作为目标位置（用于兼容）
        if target_pose is None:
            target_pose = task_create.start_pose or Pose(x=0.0, y=0.0, yaw=0.0)
        
        # 创建任务对象（快速创建）
        task = Task(
            task_id=task_id,
            robot_id=None,
            status=TaskStatus.PENDING,
            start_pose=task_create.start_pose,
            target_pose=target_pose,
            priority=priority,
            action_id=None,
            created_at=datetime.now(),
            retry_count=0,
            is_multi_action=True,
            actions=task_create.actions,
            current_action_index=0
        )
        
        # 保存任务到内存（立即完成，确保任务可以被查询到）
        self.tasks[task_id] = task
        logger.info(f"Multi-action task {task_id} created and saved to memory: {len(task_create.actions)} actions, priority={priority.value}, status={task.status.value}")
        
        # 异步处理所有耗时操作（不阻塞返回）
        async def _async_post_creation_tasks():
            """异步处理任务创建后的耗时操作"""
            try:
                # 持久化到文件（异步，不阻塞）
                await self._save_tasks_to_file_async()
                logger.debug(f"Task {task_id} saved to file (async)")
                
                # 启动调度器（如果还没有启动）
                if self._scheduler_task is None or self._scheduler_task.done():
                    logger.info("Starting scheduler loop...")
                    self._scheduler_task = asyncio.create_task(self._scheduler_loop())
                else:
                    logger.debug("Scheduler loop already running")
                
                # 启动碰撞检测任务（如果还没有启动或已停止）
                if self._collision_check_task is None or self._collision_check_task.done():
                    logger.info("Starting collision check loop...")
                    self._collision_check_task = asyncio.create_task(self._collision_check_loop())
                else:
                    logger.debug("Collision check loop already running")
                
                # 启动死锁检测任务（如果还没有启动或已停止）
                if self._deadlock_check_task is None or self._deadlock_check_task.done():
                    logger.info("Starting deadlock check loop...")
                    self._deadlock_check_task = asyncio.create_task(self._deadlock_check_loop())
                else:
                    logger.debug("Deadlock check loop already running")
            except Exception as e:
                logger.error(f"Error in async post-creation tasks for task {task_id}: {e}", exc_info=True)
        
        # 启动异步后台任务（不等待完成，立即返回）
        asyncio.create_task(_async_post_creation_tasks())
        
        # 立即返回任务（不等待文件保存和后台任务启动）
        logger.info(f"Multi-action task {task_id} returning immediately (task is in memory and can be queried)")
        return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务信息
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务信息
        """
        return self.tasks.get(task_id)
    
    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        robot_id: Optional[str] = None
    ) -> List[Task]:
        """
        获取任务列表
        
        Args:
            status: 任务状态过滤
            robot_id: 机器人ID过滤
            
        Returns:
            任务列表
        """
        tasks = list(self.tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        if robot_id:
            tasks = [t for t in tasks if t.robot_id == robot_id]
        
        return tasks
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务，取消后机器人自动返回充电桩
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否取消成功
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        # 如果任务正在执行或已分配，取消机器人的action并让机器人回桩
        if task.robot_id and (task.status == TaskStatus.EXECUTING or task.status == TaskStatus.ASSIGNED):
            agent = self.robot_manager.get_robot_agent(task.robot_id)
            if agent:
                try:
                    # 先取消当前action
                    if task.action_id:
                        try:
                            await agent.cancel_current_action()
                            logger.info(f"Cancelled action {task.action_id} for task {task_id}")
                        except Exception as e:
                            logger.warning(f"Failed to cancel action for task {task_id}: {e}")
                    
                    # 等待一小段时间确保action已取消
                    await asyncio.sleep(0.5)
                    
                    # 让机器人回桩
                    try:
                        go_home_result = await agent.go_home()
                        logger.info(
                            f"Robot {task.robot_id} returning to charging dock after task {task_id} cancellation. "
                            f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send robot {task.robot_id} back to charging dock: {e}")
                        # 即使回桩失败，任务仍然标记为已取消
                except Exception as e:
                    logger.error(f"Error during task cancellation for task {task_id}: {e}")
        
        # 更新任务状态
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now()
        
        # 清理任务的规划路径
        if task.task_id in self.task_paths:
            del self.task_paths[task.task_id]
        
        # 持久化到文件
        self._save_tasks_to_file()
        
        logger.info(f"Task {task_id} cancelled")
        return True
    
    async def start_background_tasks_if_needed(self):
        """公共方法：确保后台任务（死锁检测、碰撞检测等）已启动"""
        await self._start_background_tasks_if_needed_async()
    
    async def _scheduler_loop(self):
        """任务调度循环"""
        logger.info("Task scheduler loop started")
        # 确保死锁检测循环已启动（如果还没有启动）
        await self._start_background_tasks_if_needed_async()
        loop_count = 0
        while True:
            try:
                loop_count += 1
                # 查找待分配的任务
                pending_tasks = [
                    t for t in self.tasks.values()
                    if t.status == TaskStatus.PENDING
                ]
                
                # 动态更新优先级（考虑等待时间）
                for task in pending_tasks:
                    old_priority = task.priority
                    new_priority = self.priority_calculator.calculate_dynamic_priority(
                        task,
                        len(pending_tasks)
                    )
                    if new_priority != old_priority:
                        task.priority = new_priority
                        logger.info(
                            f"Task {task.task_id} priority updated: "
                            f"{old_priority.name}({old_priority.value}) -> "
                            f"{new_priority.name}({new_priority.value})"
                        )
                
                # 按优先级排序
                if pending_tasks:
                    pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)
                
                # 查找空闲的机器人（并发查询，提高效率）
                available_robots = []
                robot_ids = self.robot_manager.list_robots()
                logger.info(f"Scheduler loop: checking {len(robot_ids)} robots, {len(pending_tasks)} pending tasks")
                
                # 并发查询所有机器人状态
                robot_states = await asyncio.gather(
                    *[self.robot_manager.get_robot_state(robot_id) for robot_id in robot_ids],
                    return_exceptions=True
                )
                
                for robot_id, state in zip(robot_ids, robot_states):
                    if isinstance(state, Exception):
                        logger.warning(f"Error getting state for robot {robot_id}: {state}")
                        continue
                    if state:
                        logger.info(f"Robot {robot_id} status: {state.status.value}")
                        # 检查机器人状态是否为 IDLE（空闲）或 BUSY（忙碌但可能刚完成死锁解除）
                        # 注意：死锁解除后机器人可能处于BUSY状态（正在移动到避让点），
                        # 但如果没有活跃任务，仍然应该考虑分配（因为避让是临时状态）
                        if state.status == RobotStatus.IDLE or state.status == RobotStatus.BUSY:
                            # 检查是否有正在执行或已分配的任务（包括ASSIGNED和EXECUTING状态）
                            has_active_task = any(
                                t.robot_id == robot_id and 
                                (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                                for t in self.tasks.values()
                            )
                            if not has_active_task:
                                # 检查机器人电量（电量低于20%不分配任务）
                                battery_percentage = state.power.batteryPercentage if state.power else 0
                                if battery_percentage < 20:
                                    logger.info(
                                        f"Robot {robot_id} battery is too low ({battery_percentage}% < 20%), "
                                        f"skipping task assignment"
                                    )
                                else:
                                    # 检查机器人当前位置是否为障碍物（被人为推到障碍物区域）
                                    if state.pose:
                                        is_obstacle = self.path_planner.map_manager.is_obstacle(
                                            state.pose.x, state.pose.y
                                        )
                                        if is_obstacle:
                                            logger.warning(
                                                f"Robot {robot_id} is in obstacle area "
                                                f"({state.pose.x:.2f}, {state.pose.y:.2f}), "
                                                f"skipping task assignment"
                                            )
                                        else:
                                            available_robots.append((robot_id, state))
                                            logger.info(
                                                f"Robot {robot_id} is available for task assignment "
                                                f"(battery: {battery_percentage}%, "
                                                f"position: ({state.pose.x:.2f}, {state.pose.y:.2f}))"
                                            )
                                    else:
                                        # 如果没有位置信息，也跳过（可能是离线状态）
                                        logger.warning(
                                            f"Robot {robot_id} has no pose information, skipping task assignment"
                                        )
                            else:
                                logger.info(f"Robot {robot_id} has active task (ASSIGNED or EXECUTING), skipping")
                        else:
                            logger.info(f"Robot {robot_id} is not idle (status: {state.status.value}), skipping")
                    else:
                        logger.warning(f"Robot {robot_id} state is None, skipping")
                
                # 记录调度信息
                if pending_tasks:
                    logger.info(
                        f"Scheduler loop: {len(pending_tasks)} pending tasks, "
                        f"{len(available_robots)} available robots"
                    )
                    for task in pending_tasks:
                        logger.info(
                            f"Pending task {task.task_id}: target=({task.target_pose.x}, {task.target_pose.y}), "
                            f"priority={task.priority.value}, status={task.status.value}"
                        )
                elif len(self.tasks) > 0:
                    logger.info(f"Scheduler loop: no pending tasks, but {len(self.tasks)} total tasks exist")
                    for task_id, task in self.tasks.items():
                        logger.info(f"Task {task_id}: status={task.status.value}, robot_id={task.robot_id}")
                else:
                    if loop_count % 10 == 0:  # 每10次循环输出一次日志，避免日志过多
                        logger.info(f"Scheduler loop iteration {loop_count}: no tasks, no robots")
                
                # 如果没有空闲机器人但有待分配任务，先更新任务状态（可能释放机器人）
                if not available_robots and pending_tasks:
                    logger.info(
                        f"No available robots, {len(pending_tasks)} pending tasks waiting. "
                        f"Updating task status to check for newly available robots..."
                    )
                    # 更新任务状态，可能释放机器人
                    await self._update_executing_tasks()
                    
                    # 重新检查可用机器人（并发查询）
                    robot_states = await asyncio.gather(
                        *[self.robot_manager.get_robot_state(robot_id) for robot_id in robot_ids],
                        return_exceptions=True
                    )
                    available_robots = []
                    for robot_id, state in zip(robot_ids, robot_states):
                        if isinstance(state, Exception) or not state:
                            continue
                        if state.status == RobotStatus.IDLE:
                            # 检查是否有正在执行或已分配的任务
                            has_active_task = any(
                                t.robot_id == robot_id and 
                                (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                                for t in self.tasks.values()
                            )
                            if not has_active_task:
                                # 检查机器人电量（电量低于20%不分配任务）
                                battery_percentage = state.power.batteryPercentage if state.power else 0
                                if battery_percentage >= 20:
                                    # 检查机器人当前位置是否为障碍物
                                    if state.pose:
                                        is_obstacle = self.path_planner.map_manager.is_obstacle(
                                            state.pose.x, state.pose.y
                                        )
                                        if not is_obstacle:
                                            available_robots.append((robot_id, state))
                    
                    # 如果仍然没有可用机器人，等待
                    if not available_robots:
                        await asyncio.sleep(0.2)  # 减少等待时间到0.2秒，更快响应
                        continue
                
                # 更新执行中的任务状态（在分配新任务之前）
                await self._update_executing_tasks()
                
                # 重新检查待分配任务（因为状态更新可能导致任务完成，释放机器人）
                pending_tasks = [
                    t for t in self.tasks.values()
                    if t.status == TaskStatus.PENDING
                ]
                if pending_tasks:
                    pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)
                
                # 重新检查可用机器人（因为任务完成可能释放了机器人，并发查询）
                robot_states = await asyncio.gather(
                    *[self.robot_manager.get_robot_state(robot_id) for robot_id in robot_ids],
                    return_exceptions=True
                )
                available_robots = []
                for robot_id, state in zip(robot_ids, robot_states):
                    if isinstance(state, Exception) or not state:
                        continue
                    if state.status == RobotStatus.IDLE:
                        # 检查是否有正在执行或已分配的任务
                        has_active_task = any(
                            t.robot_id == robot_id and 
                            (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                            for t in self.tasks.values()
                        )
                        if not has_active_task:
                            # 检查机器人电量（电量低于20%不分配任务）
                            battery_percentage = state.power.batteryPercentage if state.power else 0
                            if battery_percentage >= 20:
                                # 检查机器人当前位置是否为障碍物
                                if state.pose:
                                    is_obstacle = self.path_planner.map_manager.is_obstacle(
                                        state.pose.x, state.pose.y
                                    )
                                    if not is_obstacle:
                                        available_robots.append((robot_id, state))
                
                # 分配任务（考虑路径碰撞）
                for task in pending_tasks:
                    if not available_robots:
                        break
                    
                    # 在计算成本之前，先过滤掉已经有活跃任务的机器人（双重检查，确保不会重复分配）
                    filtered_available_robots = []
                    for robot_id, state in available_robots:
                        # 检查该机器人是否已经有活跃任务（ASSIGNED或EXECUTING状态）
                        has_active_task = any(
                            t.robot_id == robot_id and 
                            (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                            for t in self.tasks.values()
                        )
                        if not has_active_task:
                            filtered_available_robots.append((robot_id, state))
                    
                    if not filtered_available_robots:
                        logger.warning(f"No available robots for task {task.task_id} after filtering active tasks")
                        break
                    
                    # 选择最优的机器人（考虑路径碰撞）- 并发计算所有机器人的成本
                    async def calculate_robot_cost(robot_id: str, state) -> tuple:
                        """并发计算单个机器人的成本"""
                        try:
                            robot_pose = state.pose
                            target_pose = task.target_pose
                            
                            # 对于多动作任务，如果target_pose是默认值(0,0)，尝试从第一个动作获取实际目标位置
                            if task.is_multi_action and task.actions:
                                first_action = task.actions[0] if len(task.actions) > 0 else None
                                if first_action and first_action.action_type == ActionType.MOVE_TO:
                                    if first_action.target_pose:
                                        target_pose = first_action.target_pose
                                    elif first_action.poi_name:
                                        try:
                                            agent = self.robot_manager.get_robot_agent(robot_id)
                                            if agent:
                                                pois = await agent.get_all_pois()
                                                for poi in pois:
                                                    if poi.id == first_action.poi_name or (poi.metadata and poi.metadata.get("display_name") == first_action.poi_name):
                                                        if poi.pose:
                                                            target_pose = poi.pose
                                                            logger.debug(f"Using POI '{first_action.poi_name}' position ({poi.pose.x}, {poi.pose.y}) for robot {robot_id} cost calculation")
                                                            break
                                        except Exception as e:
                                            logger.debug(f"Failed to get POI position for robot {robot_id}: {e}")
                                            pass
                            
                            # 如果target_pose仍然是(0,0)，跳过路径规划，使用较大的成本值
                            if target_pose.x == 0.0 and target_pose.y == 0.0:
                                logger.warning(f"Task {task.task_id} has invalid target_pose (0,0), using high cost for robot {robot_id}")
                                return (robot_id, float('inf'))
                            
                            # 使用asyncio.to_thread在后台线程中执行路径规划（避免阻塞）
                            path = await asyncio.to_thread(self.path_planner.plan_path, robot_pose, target_pose)
                            
                            if path and len(path) > 1:
                                # 计算路径总长度
                                path_length = 0.0
                                for i in range(len(path) - 1):
                                    dx = path[i+1].x - path[i].x
                                    dy = path[i+1].y - path[i].y
                                    path_length += math.sqrt(dx*dx + dy*dy)
                                
                                # 检查路径是否与其他机器人已规划的路径碰撞
                                collision_penalty = await self._check_path_collision_with_planned_paths(
                                    robot_id, path, task.task_id
                                )
                                
                                # 成本 = 路径长度 + 碰撞惩罚（碰撞惩罚越大，成本越高）
                                cost = path_length + collision_penalty
                            else:
                                # 如果路径规划失败，使用直线距离作为备选
                                dx = target_pose.x - robot_pose.x
                                dy = target_pose.y - robot_pose.y
                                cost = math.sqrt(dx*dx + dy*dy)
                                logger.warning(
                                    f"Path planning failed for robot {robot_id} to task {task.task_id}, "
                                    f"using straight-line distance: {cost:.2f}m"
                                )
                            
                            return (robot_id, cost)
                        except Exception as e:
                            logger.error(f"Error calculating cost for robot {robot_id}: {e}")
                            return (robot_id, float('inf'))
                    
                    # 并发计算所有机器人的成本（只对过滤后的机器人计算）
                    robot_costs = await asyncio.gather(
                        *[calculate_robot_cost(robot_id, state) for robot_id, state in filtered_available_robots]
                    )
                    
                    # 找到成本最低的机器人
                    best_robot_id = None
                    best_cost = float('inf')
                    for robot_id, cost in robot_costs:
                        if cost < best_cost:
                            best_cost = cost
                            best_robot_id = robot_id
                    
                    # 记录所有机器人的成本，便于调试
                    if robot_costs:
                        logger.info(
                            f"Task {task.task_id} robot selection: "
                            f"{', '.join([f'{r_id}({cost:.2f}m)' for r_id, cost in robot_costs])}"
                        )
                    
                    if best_robot_id:
                        # 在分配之前，再次检查该机器人是否仍然可用（防止并发分配）
                        has_active_task = any(
                            t.robot_id == best_robot_id and 
                            (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                            for t in self.tasks.values()
                        )
                        
                        if has_active_task:
                            logger.warning(
                                f"Robot {best_robot_id} already has active task, skipping assignment for task {task.task_id}"
                            )
                            # 从可用列表中移除该机器人，继续下一个任务
                            available_robots = [(r, s) for r, s in available_robots if r != best_robot_id]
                            continue
                        
                        # 分配任务
                        logger.info(
                            f"Assigning task {task.task_id} to robot {best_robot_id} "
                            f"(best cost: {best_cost:.2f}m, target: ({task.target_pose.x}, {task.target_pose.y}))"
                        )
                        await self._assign_task(task, best_robot_id)
                        # 从可用列表中移除（立即移除，防止下一个任务重复分配）
                        available_robots = [(r, s) for r, s in available_robots if r != best_robot_id]
                    else:
                        logger.warning(
                            f"No available robot found for task {task.task_id} "
                            f"(target: {task.target_pose.x}, {task.target_pose.y})"
                        )
                
                # 更新执行中的任务状态
                await self._update_executing_tasks()
                
                # 等待0.2秒后再次调度（提高响应速度，更快分配任务）
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _assign_task(self, task: Task, robot_id: str):
        """
        分配任务给机器人（集成碰撞检测和路径规划）
        
        使用API.md中的7.创建运动行为来下发任务：
        POST /api/core/motion/v1/actions
        action_name: "slamtec.agent.actions.MoveToAction"
        
        Args:
            task: 任务
            robot_id: 机器人ID
        """
        try:
            logger.info(f"Starting task assignment: task_id={task.task_id}, robot_id={robot_id}")
            
            agent = self.robot_manager.get_robot_agent(robot_id)
            if not agent:
                error_msg = f"Robot {robot_id} not found in robot manager"
                logger.error(error_msg)
                task.status = TaskStatus.FAILED
                task.error_message = error_msg
                task.completed_at = datetime.now()
                return
            
            logger.info(f"Robot agent found for {robot_id}, getting current pose...")
            
            # 确定起点
            if task.start_pose:
                start = task.start_pose
                logger.info(f"Using task start_pose: ({start.x}, {start.y}, yaw={start.yaw})")
            else:
                # 使用机器人当前位置
                try:
                    pose = await agent.get_pose()
                    start = Pose(x=pose.x, y=pose.y, yaw=pose.yaw)
                    logger.info(f"Using robot current pose: ({start.x}, {start.y}, yaw={start.yaw})")
                except Exception as e:
                    error_msg = f"Failed to get robot pose: {e}"
                    logger.error(error_msg)
                    task.status = TaskStatus.FAILED
                    task.error_message = error_msg
                    task.completed_at = datetime.now()
                    return
            
            # 检查路径是否与其他机器人碰撞
            logger.info(f"Planning path from ({start.x}, {start.y}) to ({task.target_pose.x}, {task.target_pose.y})")
            path = self.path_planner.plan_path(start, task.target_pose)
            if not path:
                error_msg = (
                    f"Path planning failed for task {task.task_id}: "
                    f"cannot find path from ({start.x}, {start.y}) to "
                    f"({task.target_pose.x}, {task.target_pose.y})"
                )
                logger.error(error_msg)
                # 对于路径规划失败，允许重试（不立即标记为FAILED）
                # 如果重试次数过多，再标记为FAILED
                task.retry_count += 1
                if task.retry_count >= 3:
                    task.status = TaskStatus.FAILED
                    task.error_message = error_msg
                    task.completed_at = datetime.now()
                else:
                    logger.warning(f"Path planning failed, will retry later. Retry count: {task.retry_count}")
                    task.status = TaskStatus.PENDING  # 保持PENDING状态，等待重试
                return
            
            logger.info(
                f"Path planned for task {task.task_id}: {len(path)} waypoints from "
                f"({start.x}, {start.y}) to ({task.target_pose.x}, {task.target_pose.y})"
            )
            
            # 存储任务的规划路径，用于后续碰撞检测
            self.task_paths[task.task_id] = path
            
            # 检测路径中的窄道
            narrow_passages = self.path_planner.detect_narrow_passages(path, robot_radius=0.2, narrow_threshold=1.0)
            if narrow_passages:
                logger.info(
                    f"Task {task.task_id} path contains {len(narrow_passages)} narrow passage(s): "
                    f"{[(i, f'{w:.2f}m') for i, _, w in narrow_passages]}"
                )
                
                # 检查窄道通行限制：如果路径中有窄道，检查是否有其他机器人也在使用相同的窄道
                for passage_idx, passage_pose, passage_width in narrow_passages:
                    # 检查是否可以同时通过多个机器人
                    can_pass_concurrently = self.path_planner.can_pass_concurrently(
                        passage_width, robot_radius=0.2, num_robots=2
                    )
                    
                    if not can_pass_concurrently:
                        # 检查是否有其他机器人正在使用这个窄道
                        conflicting_robots = await self._check_narrow_passage_conflict(
                            robot_id, passage_pose, passage_width, task.task_id
                        )
                        
                        if conflicting_robots:
                            logger.warning(
                                f"Narrow passage conflict detected for task {task.task_id} at "
                                f"({passage_pose.x:.2f}, {passage_pose.y:.2f}): "
                                f"width={passage_width:.2f}m, conflicting robots={conflicting_robots}"
                            )
                            # 如果冲突严重，可以考虑延迟任务或重新规划路径
                            # 这里先记录警告，让避让策略在运行时处理
            
            # 检查路径碰撞（考虑其他机器人已规划的路径）
            other_robots = [r for r in self.robot_manager.list_robots() if r != robot_id]
            collisions = await self.collision_detector.check_path_collision(
                robot_id,
                path,
                other_robots
            )
            
            # 检查与其他任务已规划路径的碰撞
            planned_path_collisions = await self._check_path_collision_with_planned_paths(
                robot_id, path, task.task_id, return_collisions=True
            )
            
            if collisions or planned_path_collisions:
                collision_count = len(collisions) + len(planned_path_collisions)
                logger.warning(
                    f"Path collision detected for task {task.task_id}. "
                    f"Collisions at waypoints: {[c[0] for c in collisions]}, "
                    f"planned path collisions: {len(planned_path_collisions)}"
                )
                # 如果碰撞严重，尝试重新规划路径
                if collision_count > len(path) * 0.3:  # 如果碰撞点超过路径的30%
                    logger.warning(
                        f"Too many collisions ({collision_count}) for task {task.task_id}, "
                        f"but continuing execution. Avoidance strategy will handle collisions."
                    )
                # 继续执行，让避让策略在运行时处理
            
            # 先标记任务为已分配，避免在同一个调度循环中重复分配
            task.robot_id = robot_id
            task.status = TaskStatus.ASSIGNED
            task.assigned_at = datetime.now()
            task.retry_count = 0  # 重置重试计数
            # 立即保存，确保状态更新
            self._save_tasks_to_file()
            logger.info(
                f"Task {task.task_id} marked as ASSIGNED to robot {robot_id} "
                f"(preventing duplicate assignment in same scheduler loop)"
            )
            
            # 如果是多动作任务，执行第一个动作
            if task.is_multi_action and task.actions:
                await self._execute_next_action(task, agent, robot_id)
            else:
                # 创建移动action（使用API.md中的7.创建运动行为）
                logger.info(
                    f"Creating MoveToAction for task {task.task_id} to robot {robot_id}: "
                    f"target=({task.target_pose.x}, {task.target_pose.y}, yaw={task.target_pose.yaw})"
                )
                logger.info(
                    f"Calling POST /api/core/motion/v1/actions with action_name=slamtec.agent.actions.MoveToAction"
                )
                
                try:
                    # 使用自由导航模式（mode=0: Free Navigation）
                    action_state = await agent.move_to(
                        target=task.target_pose,
                        mode=0,  # 0: Free Navigation - 自由导航模式
                        acceptable_precision=0.3,
                        speed_ratio=1.0
                    )
                    logger.info(
                        f"MoveToAction created successfully: action_id={action_state.action_id}, "
                        f"status={action_state.state.get('status')}, result={action_state.state.get('result')}"
                    )
                except Exception as e:
                    error_msg = f"Failed to create MoveToAction via API: {e}"
                    logger.error(error_msg, exc_info=True)
                    task.retry_count += 1
                    if task.retry_count >= 3:
                        task.status = TaskStatus.FAILED
                        task.error_message = error_msg
                        task.completed_at = datetime.now()
                    else:
                        logger.warning(f"API call failed, will retry later. Retry count: {task.retry_count}")
                        # 重置为PENDING状态，允许重新分配
                        task.status = TaskStatus.PENDING
                        task.robot_id = None
                        task.assigned_at = None
                    # 持久化状态
                    self._save_tasks_to_file()
                    return
                
                # 更新任务为执行中
                task.action_id = action_state.action_id
                task.status = TaskStatus.EXECUTING
                task.started_at = datetime.now()
                
                # 持久化到文件
                self._save_tasks_to_file()
                
                logger.info(
                    f"Task {task.task_id} successfully assigned to robot {robot_id}, "
                    f"action_id={action_state.action_id}, status=EXECUTING"
                )
            
        except Exception as e:
            error_msg = f"Failed to assign task {task.task_id} to robot {robot_id}: {e}"
            logger.error(error_msg, exc_info=True)
            task.retry_count += 1
            if task.retry_count >= 3:
                task.status = TaskStatus.FAILED
                task.error_message = error_msg
                task.completed_at = datetime.now()
            else:
                logger.warning(f"Task assignment failed, will retry later. Retry count: {task.retry_count}")
                task.status = TaskStatus.PENDING  # 保持PENDING状态，等待重试
    
    async def _collision_check_loop(self):
        """碰撞检测循环"""
        while True:
            try:
                # 获取所有执行中的任务
                executing_tasks = [
                    t for t in self.tasks.values()
                    if t.status == TaskStatus.EXECUTING and t.robot_id
                ]
                
                # 对每个执行中的任务进行碰撞检测和避让
                for task in executing_tasks:
                    try:
                        collisions = await self.avoidance_strategy.check_and_avoid_collisions(
                            task.robot_id,
                            task.priority.value
                        )
                        
                        if collisions:
                            logger.warning(
                                f"Collisions detected for robot {task.robot_id} "
                                f"executing task {task.task_id}: {len(collisions)} collisions"
                            )
                    except Exception as e:
                        logger.error(f"Error in collision check for task {task.task_id}: {e}")
                
                # 等待0.1秒后再次检测（10Hz）
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in collision check loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _deadlock_check_loop(self):
        """死锁检测循环"""
        logger.info("Deadlock check loop started")
        while True:
            try:
                # 检测死锁
                deadlocks = await self.deadlock_detector.detect_deadlocks()
                
                # 处理死锁
                for deadlock in deadlocks:
                    # 重新加载配置以获取最新的阈值
                    self.deadlock_detector._load_config()
                    
                    # 根据死锁类型使用不同的阈值
                    threshold = self.deadlock_detector.deadlock_threshold  # 默认阈值
                    if deadlock.deadlock_type == "narrow_passage":
                        threshold = self.deadlock_detector.narrow_passage_deadlock_threshold
                    elif deadlock.deadlock_type == "circular_wait":
                        threshold = self.deadlock_detector.circular_wait_deadlock_threshold
                    elif deadlock.deadlock_type == "mutual_blocking":
                        threshold = self.deadlock_detector.mutual_blocking_deadlock_threshold
                    elif deadlock.deadlock_type == "resource_contention":
                        # 资源竞争（单个机器人卡住）使用较短的阈值
                        threshold = 5.0  # 5秒后认为卡住
                    
                    # 记录死锁检测信息（即使未超过阈值也记录，便于调试）
                    if deadlock.duration > threshold:
                        logger.warning(
                            f"Deadlock detected: {deadlock.deadlock_type} "
                            f"involving robots {deadlock.robot_ids} "
                            f"(duration: {deadlock.duration:.1f}s, threshold: {threshold:.1f}s) - Attempting to resolve..."
                        )
                        
                        # 尝试解决死锁
                        success = await self.deadlock_detector.resolve_deadlock(deadlock)
                        if success:
                            logger.info(f"✓ Deadlock resolved successfully for robots {deadlock.robot_ids}")
                        else:
                            logger.error(f"✗ Failed to resolve deadlock for robots {deadlock.robot_ids} - tasks may be cancelled")
                    else:
                        # 记录死锁但未超过阈值的情况（改为INFO级别，便于调试）
                        logger.info(
                            f"Deadlock detected but below threshold: {deadlock.deadlock_type} "
                            f"involving robots {deadlock.robot_ids} "
                            f"(duration: {deadlock.duration:.1f}s, threshold: {threshold:.1f}s) - Will resolve when threshold exceeded"
                        )
                
                # 检测单个机器人卡住的情况（即使不是死锁，也需要处理）
                await self._check_stuck_robots()
                
                # 检测已完成任务的机器人是否阻塞了执行中任务的路径（提高检测频率）
                await self._check_completed_task_blocking()
                
                # 等待0.5秒后再次检测（提高响应速度，更快检测阻塞）
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in deadlock check loop: {e}", exc_info=True)
                # 发生错误时，等待1秒后继续，确保循环不会停止
                await asyncio.sleep(1.0)
                # 如果任务已停止，尝试重启（但这里不能直接重启，需要外部调用）
                if self._deadlock_check_task and self._deadlock_check_task.done():
                    logger.warning("Deadlock check loop stopped unexpectedly, will be restarted on next task creation")
    
    async def _check_and_resume_deadlock_resolution_tasks(self):
        """
        检查是否有机器人已完成死锁解除避让，需要恢复任务
        """
        if not self.robots_in_deadlock_resolution:
            return
        
        now = datetime.now()
        robots_to_remove = []
        
        for robot_id, resolution_info in self.robots_in_deadlock_resolution.items():
            try:
                task_id = resolution_info.get('task_id')
                waiting_point = resolution_info.get('waiting_point')
                start_time = resolution_info.get('start_time')
                
                if not task_id or not waiting_point:
                    robots_to_remove.append(robot_id)
                    continue
                
                # 获取任务
                task = self.tasks.get(task_id)
                if not task or task.status not in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED]:
                    # 任务已完成或已取消，移除记录
                    robots_to_remove.append(robot_id)
                    continue
                
                # 获取机器人当前位置
                state = await self.robot_manager.get_robot_state(robot_id)
                if not state or not state.pose:
                    # 如果超时（30秒），强制恢复任务执行
                    if start_time and (now - start_time).total_seconds() > 30.0:
                        logger.warning(
                            f"Robot {robot_id} timeout reaching waiting point (30s), "
                            f"forcing task {task_id} resume"
                        )
                        await self._resume_task_after_deadlock_resolution(task, robot_id)
                        robots_to_remove.append(robot_id)
                    continue
                
                # 计算到等待点的距离
                dx = state.pose.x - waiting_point.x
                dy = state.pose.y - waiting_point.y
                distance = math.sqrt(dx*dx + dy*dy)
                
                # 如果距离小于0.5米，认为已到达等待点
                if distance < 0.5:
                    logger.info(
                        f"Robot {robot_id} reached waiting point (distance={distance:.2f}m), "
                        f"resuming task {task_id}"
                    )
                    await self._resume_task_after_deadlock_resolution(task, robot_id)
                    robots_to_remove.append(robot_id)
                elif start_time and (now - start_time).total_seconds() > 30.0:
                    # 超时，强制恢复
                    logger.warning(
                        f"Robot {robot_id} timeout reaching waiting point (30s, distance={distance:.2f}m), "
                        f"forcing task {task_id} resume"
                    )
                    await self._resume_task_after_deadlock_resolution(task, robot_id)
                    robots_to_remove.append(robot_id)
            except Exception as e:
                logger.error(f"Error checking deadlock resolution for robot {robot_id}: {e}", exc_info=True)
                robots_to_remove.append(robot_id)
        
        # 移除已处理的机器人
        for robot_id in robots_to_remove:
            self.robots_in_deadlock_resolution.pop(robot_id, None)
    
    async def _resume_task_after_deadlock_resolution(self, task: Task, robot_id: str):
        """
        恢复死锁解除后的任务执行
        
        Args:
            task: 要恢复的任务
            robot_id: 机器人ID
        """
        try:
            agent = self.robot_manager.get_robot_agent(robot_id)
            if not agent:
                logger.error(f"Robot agent not found for {robot_id}")
                return
            
            if task.is_multi_action and task.actions:
                # 多动作任务：继续执行当前动作
                logger.info(f"Resuming multi-action task {task.task_id} for robot {robot_id}")
                await self._execute_next_action(task, agent, robot_id)
            else:
                # 普通任务：重新发送move_to指令
                if task.target_pose:
                    logger.info(f"Resuming task {task.task_id} for robot {robot_id}, resending move_to command")
                    move_result = await agent.move_to(
                        task.target_pose,
                        mode=0,
                        acceptable_precision=0.3,
                        speed_ratio=1.0
                    )
                    task.action_id = move_result.action_id
                    task.status = TaskStatus.EXECUTING
                    if task.started_at is None:
                        task.started_at = datetime.now()
                    logger.info(f"Task {task.task_id} resumed, new action_id={task.action_id}")
                else:
                    logger.warning(f"Task {task.task_id} has no target_pose, cannot resume")
        except Exception as e:
            logger.error(f"Failed to resume task {task.task_id} for robot {robot_id}: {e}", exc_info=True)
    
    async def _update_executing_tasks(self):
        """更新执行中的任务状态"""
        # 首先检查是否有机器人已完成死锁解除避让，需要恢复任务
        await self._check_and_resume_deadlock_resolution_tasks()
        
        # 检查所有执行中或已分配的任务
        executing_tasks = [
            t for t in self.tasks.values()
            if (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED) 
            and t.robot_id
        ]
        
        if not executing_tasks:
            return
        
        logger.info(f"Checking {len(executing_tasks)} executing/assigned tasks for status updates")
        
        for task in executing_tasks:
            try:
                agent = self.robot_manager.get_robot_agent(task.robot_id)
                if not agent:
                    logger.warning(f"Robot agent not found for task {task.task_id}, robot_id={task.robot_id}")
                    continue
                
                # 如果是多动作任务且当前是等待动作，不需要查询action状态（等待动作没有action_id）
                if task.is_multi_action and task.actions:
                    current_action = task.actions[task.current_action_index] if task.current_action_index < len(task.actions) else None
                    if current_action and current_action.action_type == ActionType.WAIT:
                        # 等待动作由后台任务处理，这里不需要更新状态
                        continue
                
                # 如果任务已分配但还没有action_id，检查机器人当前action
                if not task.action_id:
                    try:
                        current_action = await agent.get_current_action()
                        if current_action and current_action.action_id:
                            task.action_id = current_action.action_id
                            logger.info(f"Task {task.task_id} assigned action_id: {current_action.action_id}")
                            # 如果获取到action_id，更新任务状态为执行中
                            if task.status == TaskStatus.ASSIGNED:
                                task.status = TaskStatus.EXECUTING
                                # 持久化到文件
                                self._save_tasks_to_file()
                                logger.info(f"Task {task.task_id} status updated to EXECUTING")
                    except Exception as e:
                        logger.debug(f"Failed to get current action for task {task.task_id}: {e}")
                        continue
                
                # 如果有action_id，查询action状态
                if not task.action_id:
                    continue
                
                try:
                    action_state = await agent.get_action_status(task.action_id)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        # action_id已失效（404），说明action可能已经完成或被清除
                        logger.warning(
                            f"Task {task.task_id} action_id={task.action_id} returned 404. "
                            f"Action may have been completed or cleared. Attempting to recover..."
                        )
                        # 尝试恢复任务：检查机器人位置或重新发送指令
                        await self._recover_task_with_invalid_action_id(task, agent, task.robot_id)
                        continue
                    else:
                        # 其他HTTP错误，记录并继续
                        logger.error(f"Failed to get action status for task {task.task_id}: {e}")
                        continue
                except Exception as e:
                    logger.error(f"Failed to get action status for task {task.task_id}: {e}", exc_info=True)
                    continue
                
                # 检查状态 - 优先使用state字典中的值，如果不存在则使用直接属性
                status = action_state.state.get("status") if action_state.state else None
                if status is None:
                    status = action_state.status
                
                result = action_state.state.get("result") if action_state.state else None
                if result is None:
                    result = action_state.result
                
                logger.debug(
                    f"Task {task.task_id} (action_id={task.action_id}): "
                    f"status={status}, result={result}, "
                    f"state_dict={action_state.state}"
                )
                
                # 如果status为None，说明action可能已经完成或被清除
                if status is None:
                    logger.warning(
                        f"Task {task.task_id} action_id={task.action_id} status is None. "
                        f"Action may have been completed or cleared. Checking robot current action..."
                    )
                    # 检查机器人当前是否有正在执行的任务
                    try:
                        current_action = await agent.get_current_action()
                        if current_action is None or current_action.action_id != task.action_id:
                            # 机器人当前没有执行这个action，可能已经完成
                            # 通过检查机器人位置来判断是否到达目标
                            robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                            if robot_state:
                                target = task.target_pose
                                current = robot_state.pose
                                distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
                                logger.info(
                                    f"Task {task.task_id}: action status is None, "
                                    f"distance to target: {distance:.2f}m"
                                )
                                # 如果距离目标很近（在acceptable_precision范围内），认为任务完成
                                # 使用默认精度0.3米（与创建任务时使用的默认值一致）
                                acceptable_precision = 0.3
                                if distance <= acceptable_precision:
                                    task.status = TaskStatus.COMPLETED
                                    task.completed_at = datetime.now()
                                    # 清理任务的规划路径
                                    if task.task_id in self.task_paths:
                                        del self.task_paths[task.task_id]
                                    # 持久化到文件
                                    self._save_tasks_to_file()
                                    logger.info(
                                        f"Task {task.task_id} completed (distance to target: {distance:.2f}m <= {acceptable_precision}m)"
                                    )
                    except Exception as e:
                        logger.debug(f"Failed to check current action for task {task.task_id}: {e}")
                    continue
                
                if status == 4:  # Done
                    if result == 0:  # Success
                        # 如果是多动作任务，检查是否还有下一个动作
                        if task.is_multi_action and task.actions:
                            # 当前动作完成，执行下一个动作
                            task.current_action_index += 1
                            if task.current_action_index < len(task.actions):
                                # 还有下一个动作，执行它
                                logger.info(
                                    f"Task {task.task_id} action {task.current_action_index - 1} completed, "
                                    f"executing next action ({task.current_action_index}/{len(task.actions)})"
                                )
                                await self._execute_next_action(task, agent, task.robot_id)
                                # 继续执行，不标记为完成
                                continue
                            else:
                                # 所有动作完成
                                task.status = TaskStatus.COMPLETED
                                task.completed_at = datetime.now()
                                logger.info(f"Task {task.task_id} (multi-action) completed all actions successfully")
                        else:
                            # 普通任务完成
                            task.status = TaskStatus.COMPLETED
                            task.completed_at = datetime.now()
                            logger.info(f"Task {task.task_id} completed successfully")
                        
                        # 清理任务的规划路径
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                        # 持久化到文件
                        self._save_tasks_to_file()
                    elif result == -1:  # Failed
                        reason = action_state.state.get("reason", "") if action_state.state else action_state.reason
                        task.status = TaskStatus.FAILED
                        task.error_message = reason or "Unknown error"
                        task.completed_at = datetime.now()
                        # 清理任务的规划路径
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                        # 持久化到文件
                        self._save_tasks_to_file()
                        logger.warning(f"Task {task.task_id} failed: {task.error_message}")
                    elif result == -2:  # Aborted
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = datetime.now()
                        # 清理任务的规划路径
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                        # 持久化到文件
                        self._save_tasks_to_file()
                        logger.info(f"Task {task.task_id} aborted")
                elif status == 1:  # Working
                    logger.debug(f"Task {task.task_id} is still working (status=1)")
                elif status == 0:  # NewBorn
                    logger.debug(f"Task {task.task_id} is in NewBorn state (status=0)")
                elif status == 3:  # Paused
                    logger.debug(f"Task {task.task_id} is paused (status=3)")
                
            except Exception as e:
                logger.error(f"Failed to update task {task.task_id}: {e}", exc_info=True)
    
    async def _execute_next_action(self, task: Task, agent, robot_id: str):
        """
        执行多动作任务的下一个动作
        
        Args:
            task: 任务
            agent: 机器人代理
            robot_id: 机器人ID
        """
        if not task.is_multi_action or not task.actions:
            return
        
        if task.current_action_index >= len(task.actions):
            logger.warning(f"Task {task.task_id} current_action_index ({task.current_action_index}) >= actions length ({len(task.actions)})")
            return
        
        action = task.actions[task.current_action_index]
        logger.info(
            f"Executing action {task.current_action_index + 1}/{len(task.actions)} for task {task.task_id}: "
            f"type={action.action_type}"
        )
        
        try:
            if action.action_type == ActionType.MOVE_TO:
                # 移动到目标点
                if action.poi_name:
                    # 使用POI导航
                    # 优先使用前端发送的poi_display_name（避免查询POI列表导致超时）
                    if action.poi_display_name:
                        # 如果前端已经提供了poi_display_name，直接使用（快速路径）
                        poi_name_to_use = action.poi_display_name
                        logger.info(f"Using POI display_name '{poi_name_to_use}' for task {task.task_id} (from frontend)")
                    else:
                        # 如果没有poi_display_name，尝试从机器人获取POI（向后兼容，但可能较慢）
                        poi_name_to_use = action.poi_name
                        try:
                            # 设置较短的超时，避免阻塞
                            pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                            for poi in pois:
                                # 如果输入的poi_name匹配id或display_name，使用display_name（根据API文档）
                                if poi.id == action.poi_name:
                                    # 如果匹配的是id，使用display_name（如果存在）
                                    if poi.metadata and poi.metadata.get("display_name"):
                                        poi_name_to_use = poi.metadata.get("display_name")
                                    else:
                                        poi_name_to_use = poi.id
                                    break
                                elif poi.metadata and poi.metadata.get("display_name") == action.poi_name:
                                    # 如果匹配的是display_name，直接使用
                                    poi_name_to_use = poi.metadata.get("display_name")
                                    break
                        except asyncio.TimeoutError:
                            logger.warning(f"Timeout getting POIs for robot {robot_id}, using original name '{poi_name_to_use}'")
                        except Exception as e:
                            logger.warning(f"Failed to get POIs to resolve name for robot {robot_id}: {e}, using original name '{poi_name_to_use}'")
                        logger.info(f"Using POI name '{poi_name_to_use}' for task {task.task_id} (resolved from '{action.poi_name}')")
                    action_state = await agent.move_to_poi(
                        poi_name=poi_name_to_use,
                        mode=0,
                        acceptable_precision=action.acceptable_precision,
                        fail_retry_count=0
                    )
                elif action.target_pose:
                    # 使用坐标导航
                    action_state = await agent.move_to(
                        target=action.target_pose,
                        mode=0,
                        acceptable_precision=action.acceptable_precision,
                        speed_ratio=action.speed_ratio
                    )
                else:
                    raise ValueError("move_to action requires either target_pose or poi_name")
                
                task.action_id = action_state.action_id
                task.status = TaskStatus.EXECUTING
                if task.started_at is None:
                    task.started_at = datetime.now()
                logger.info(f"MoveToAction created: action_id={action_state.action_id}")
                
            elif action.action_type == ActionType.WAIT:
                # 等待动作：创建一个异步任务来等待
                task.action_id = None  # 等待动作没有action_id
                task.status = TaskStatus.EXECUTING
                if task.started_at is None:
                    task.started_at = datetime.now()
                
                # 创建一个后台任务来等待
                async def wait_and_continue():
                    await asyncio.sleep(action.wait_duration)
                    # 等待完成后，继续下一个动作
                    task.current_action_index += 1
                    if task.current_action_index < len(task.actions):
                        logger.info(f"Wait completed, executing next action for task {task.task_id}")
                        await self._execute_next_action(task, agent, robot_id)
                    else:
                        # 所有动作完成
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        logger.info(f"Task {task.task_id} (multi-action) completed all actions")
                        self._save_tasks_to_file()
                
                # 启动等待任务
                asyncio.create_task(wait_and_continue())
                logger.info(f"Wait action started: duration={action.wait_duration}s")
                
            elif action.action_type == ActionType.GO_HOME:
                # 回桩
                action_state = await agent.go_home()
                task.action_id = action_state.action_id
                task.status = TaskStatus.EXECUTING
                if task.started_at is None:
                    task.started_at = datetime.now()
                logger.info(f"GoHomeAction created: action_id={action_state.action_id}")
            
            # 持久化到文件
            self._save_tasks_to_file()
            
        except Exception as e:
            # 提取更详细的错误信息
            error_msg = str(e)
            # 如果是HTTP错误，尝试提取详细错误信息
            if hasattr(e, 'response') and hasattr(e.response, 'json'):
                try:
                    error_data = e.response.json()
                    if 'detail' in error_data:
                        error_msg = error_data['detail']
                    elif 'message' in error_data:
                        error_msg = error_data['message']
                except:
                    pass
            
            # 检查是否是POI_NOT_FOUND错误
            if 'POI_NOT_FOUND' in error_msg or 'poi' in error_msg.lower() and 'not found' in error_msg.lower():
                error_msg = f"POI_NOT_FOUND: POI '{action.poi_name if action.action_type == ActionType.MOVE_TO and hasattr(action, 'poi_name') and action.poi_name else 'unknown'}' not found"
            
            full_error_msg = f"Failed to execute action {task.current_action_index + 1} ({action.action_type}) for task {task.task_id}: {error_msg}"
            logger.error(full_error_msg, exc_info=True)
            
            task.retry_count += 1
            if task.retry_count >= 3:
                task.status = TaskStatus.FAILED
                task.error_message = error_msg  # 只保存简化的错误消息
                task.completed_at = datetime.now()
                self._save_tasks_to_file()
            else:
                logger.warning(f"Action execution failed, will retry later. Retry count: {task.retry_count}")
                task.status = TaskStatus.PENDING
                task.robot_id = None
                task.assigned_at = None
                task.current_action_index = 0  # 重置动作索引
                self._save_tasks_to_file()
    
    async def _check_narrow_passage_conflict(
        self,
        robot_id: str,
        passage_pose: Pose,
        passage_width: float,
        current_task_id: str
    ) -> List[str]:
        """
        检查窄道冲突：是否有其他机器人正在使用相同的窄道
        
        Args:
            robot_id: 当前机器人ID
            passage_pose: 窄道位置
            passage_width: 窄道宽度
            current_task_id: 当前任务ID
            
        Returns:
            冲突的机器人ID列表
        """
        conflicting_robots = []
        passage_threshold = 0.5  # 0.5米范围内认为是同一个窄道
        
        # 检查其他机器人的规划路径
        for task_id, path in self.task_paths.items():
            if task_id == current_task_id:
                continue
            
            # 检查路径中是否有接近窄道位置的点
            for pose in path:
                distance = math.sqrt(
                    (pose.x - passage_pose.x) ** 2 + (pose.y - passage_pose.y) ** 2
                )
                
                if distance < passage_threshold:
                    # 找到使用这个窄道的任务
                    task = self.tasks.get(task_id)
                    if task and task.robot_id and task.robot_id != robot_id:
                        if task.robot_id not in conflicting_robots:
                            conflicting_robots.append(task.robot_id)
                    break
        
        # 检查其他机器人的当前位置（如果它们在窄道附近）
        other_robots = [r for r in self.robot_manager.list_robots() if r != robot_id]
        for other_robot_id in other_robots:
            try:
                state = await self.robot_manager.get_robot_state(other_robot_id)
                if state and state.status.value in ["idle", "online", "busy"]:
                    distance = math.sqrt(
                        (state.pose.x - passage_pose.x) ** 2 + (state.pose.y - passage_pose.y) ** 2
                    )
                    
                    if distance < passage_threshold:
                        # 检查这个位置是否也是窄道
                        width = self.path_planner.calculate_passage_width(
                            state.pose.x, state.pose.y, 0.2
                        )
                        
                        if width > 0 and width < 1.0:  # 也是窄道
                            if other_robot_id not in conflicting_robots:
                                conflicting_robots.append(other_robot_id)
            except Exception as e:
                logger.debug(f"Failed to check robot {other_robot_id} state: {e}")
        
        return conflicting_robots
    
    async def _check_path_collision_with_planned_paths(
        self,
        robot_id: str,
        path: List[Pose],
        current_task_id: str,
        return_collisions: bool = False
    ):
        """
        检查路径是否与其他任务已规划的路径碰撞
        
        Args:
            robot_id: 机器人ID
            path: 要检查的路径
            current_task_id: 当前任务ID
            return_collisions: 是否返回碰撞列表（True）或碰撞惩罚值（False）
            
        Returns:
            如果return_collisions=False，返回碰撞惩罚值（0表示无碰撞，值越大表示碰撞越严重）
            如果return_collisions=True，返回碰撞列表
        """
        if not path or len(path) == 0:
            return [] if return_collisions else 0.0
        
        collisions = []
        collision_penalty = 0.0
        
        # 获取所有正在执行的任务的规划路径
        executing_tasks = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.EXECUTING 
            and t.task_id != current_task_id
            and t.task_id in self.task_paths
        ]
        
        for other_task in executing_tasks:
            other_path = self.task_paths.get(other_task.task_id)
            if not other_path or len(other_path) == 0:
                continue
            
            # 检查两个路径是否碰撞
            # 简化：检查路径点之间的距离
            min_distance = float('inf')
            collision_points = []
            
            for i, path_point in enumerate(path):
                for j, other_point in enumerate(other_path):
                    dx = path_point.x - other_point.x
                    dy = path_point.y - other_point.y
                    distance = math.sqrt(dx*dx + dy*dy)
                    
                    # 安全距离 = 机器人半径 * 2 + 安全距离
                    safety_distance = 0.3 * 2 + self.collision_detector.safety_distance
                    
                    if distance < safety_distance:
                        min_distance = min(min_distance, distance)
                        collision_points.append((i, j, distance))
            
            # 如果有碰撞，计算惩罚值
            if min_distance < float('inf'):
                # 惩罚值 = (安全距离 - 最小距离) / 安全距离 * 路径长度
                # 碰撞越严重，惩罚值越大
                penalty = (safety_distance - min_distance) / safety_distance * len(path) * 10.0
                collision_penalty += penalty
                
                if return_collisions:
                    collisions.append({
                        'task_id': other_task.task_id,
                        'robot_id': other_task.robot_id,
                        'collision_points': collision_points,
                        'min_distance': min_distance
                    })
        
        if return_collisions:
            return collisions
        else:
            return collision_penalty
    
    async def _recover_task_with_invalid_action_id(self, task: Task, agent, robot_id: str):
        """
        当action_id失效（404）时，尝试恢复任务
        
        Args:
            task: 任务
            agent: 机器人代理
            robot_id: 机器人ID
        """
        try:
            # 检查机器人当前位置
            robot_state = await self.robot_manager.get_robot_state(robot_id)
            if not robot_state or not robot_state.pose:
                logger.warning(f"Cannot recover task {task.task_id}: robot {robot_id} state unavailable")
                return
            
            # 如果是多动作任务，先检查当前动作是否已完成
            if task.is_multi_action and task.actions:
                if task.current_action_index >= len(task.actions):
                    # 所有动作已完成，标记任务为完成
                    logger.info(f"Task {task.task_id} all actions completed, marking as completed")
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    task.action_id = None
                    self._save_tasks_to_file()
                    return
                
                current_action = task.actions[task.current_action_index]
                logger.info(
                    f"Recovering multi-action task {task.task_id} after invalid action_id, "
                    f"current_action_index={task.current_action_index}, action_type={current_action.action_type}"
                )
                
                # 检查当前动作是否已完成
                action_completed = False
                if current_action.action_type == ActionType.MOVE_TO:
                    # 对于移动动作，检查是否已到达目标
                    if current_action.target_pose:
                        current = robot_state.pose
                        target = current_action.target_pose
                        distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                        acceptable_precision = current_action.acceptable_precision or 0.3
                        if distance <= acceptable_precision:
                            logger.info(
                                f"Task {task.task_id} action {task.current_action_index + 1} completed "
                                f"(distance={distance:.2f}m <= {acceptable_precision}m)"
                            )
                            action_completed = True
                    elif current_action.poi_name:
                        # 对于POI动作，尝试查询POI位置并检查是否已到达
                        try:
                            pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                            poi_found = False
                            poi_pose = None
                            for poi in pois:
                                if poi.id == current_action.poi_name or (poi.metadata and poi.metadata.get("display_name") == current_action.poi_name):
                                    if poi.pose:
                                        poi_pose = poi.pose
                                        poi_found = True
                                        break
                            
                            if poi_found and poi_pose:
                                current = robot_state.pose
                                distance = math.sqrt((current.x - poi_pose.x) ** 2 + (current.y - poi_pose.y) ** 2)
                                acceptable_precision = current_action.acceptable_precision or 0.3
                                if distance <= acceptable_precision:
                                    logger.info(
                                        f"Task {task.task_id} action {task.current_action_index + 1} (POI) completed "
                                        f"(distance={distance:.2f}m <= {acceptable_precision}m)"
                                    )
                                    action_completed = True
                                else:
                                    logger.info(
                                        f"Task {task.task_id} action {task.current_action_index + 1} (POI) not completed "
                                        f"(distance={distance:.2f}m > {acceptable_precision}m)"
                                    )
                            else:
                                # POI未找到，假设已完成（可能是POI名称变化）
                                logger.warning(
                                    f"Task {task.task_id} action {task.current_action_index + 1} (POI) POI not found, "
                                    f"assuming completed"
                                )
                                action_completed = True
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"Task {task.task_id} action {task.current_action_index + 1} (POI) timeout querying POIs, "
                                f"assuming completed and continuing"
                            )
                            action_completed = True
                        except Exception as e:
                            logger.warning(
                                f"Task {task.task_id} action {task.current_action_index + 1} (POI) error querying POIs: {e}, "
                                f"assuming completed and continuing"
                            )
                            action_completed = True
                elif current_action.action_type == ActionType.WAIT:
                    # 等待动作：如果action_id失效，说明等待可能已完成
                    logger.info(
                        f"Task {task.task_id} action {task.current_action_index + 1} (WAIT) action_id invalid, "
                        f"assuming completed and continuing next action"
                    )
                    action_completed = True
                elif current_action.action_type == ActionType.GO_HOME:
                    # 回桩动作：如果action_id失效，检查是否在充电桩附近
                    # 简化处理：假设已完成
                    logger.info(
                        f"Task {task.task_id} action {task.current_action_index + 1} (GO_HOME) action_id invalid, "
                        f"assuming completed and continuing next action"
                    )
                    action_completed = True
                
                if action_completed:
                    # 当前动作已完成，继续下一个动作
                    task.current_action_index += 1
                    if task.current_action_index >= len(task.actions):
                        # 所有动作已完成
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        task.action_id = None
                        logger.info(f"Task {task.task_id} all actions completed")
                    else:
                        # 执行下一个动作
                        logger.info(f"Task {task.task_id} continuing to next action {task.current_action_index + 1}")
                        await self._execute_next_action(task, agent, robot_id)
                else:
                    # 当前动作未完成，重新执行当前动作
                    logger.info(
                        f"Task {task.task_id} action {task.current_action_index + 1} not completed, "
                        f"re-executing current action"
                    )
                    await self._execute_next_action(task, agent, robot_id)
                return
            
            # 普通任务：检查是否已到达目标
            if task.target_pose:
                current = robot_state.pose
                target = task.target_pose
                distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                acceptable_precision = 0.3
                
                if distance <= acceptable_precision:
                    # 已到达目标，标记为完成
                    logger.info(
                        f"Task {task.task_id} action_id invalid but robot reached target "
                        f"(distance={distance:.2f}m <= {acceptable_precision}m). Marking as completed."
                    )
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    if task.task_id in self.task_paths:
                        del self.task_paths[task.task_id]
                    self._save_tasks_to_file()
                else:
                    # 未到达目标，重新发送move_to指令
                    logger.info(
                        f"Task {task.task_id} action_id invalid, robot not at target "
                        f"(distance={distance:.2f}m). Resending move_to command."
                    )
                    move_result = await agent.move_to(
                        target=task.target_pose,
                        mode=0,
                        acceptable_precision=0.3,
                        speed_ratio=1.0
                    )
                    task.action_id = move_result.action_id
                    task.status = TaskStatus.EXECUTING
                    if task.started_at is None:
                        task.started_at = datetime.now()
                    logger.info(f"Task {task.task_id} recovered, new action_id={task.action_id}")
                    self._save_tasks_to_file()
            else:
                logger.warning(f"Task {task.task_id} has no target_pose, cannot recover")
        except Exception as e:
            logger.error(f"Failed to recover task {task.task_id} after invalid action_id: {e}", exc_info=True)
    
    async def _check_stuck_robots(self):
        """
        检测单个机器人卡住的情况（即使不是死锁，也需要处理）
        如果机器人长时间卡住，尝试重新发送任务指令或移动到避让点
        """
        try:
            # 获取所有执行中的任务
            executing_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.EXECUTING and t.robot_id
            ]
            
            if not executing_tasks:
                return
            
            for task in executing_tasks:
                robot_id = task.robot_id
                if not robot_id:
                    continue
                
                # 检查机器人是否卡住（使用死锁检测器的卡住检测）
                if self.deadlock_detector.check_robot_stuck(robot_id):
                    # 检查任务执行时间
                    if task.started_at:
                        execution_time = (datetime.now() - task.started_at).total_seconds()
                        # 如果执行时间超过30秒且机器人卡住，尝试处理
                        if execution_time > 30.0:
                            logger.warning(
                                f"Robot {robot_id} appears stuck on task {task.task_id} "
                                f"(execution time: {execution_time:.1f}s). Attempting to resolve..."
                            )
                            
                            # 尝试重新发送任务指令（如果是多动作任务，继续执行下一个动作）
                            try:
                                agent = self.robot_manager.get_robot_agent(robot_id)
                                if agent:
                                    # 检查当前action状态
                                    if task.action_id:
                                        action_state = await agent.get_action_status(task.action_id)
                                        status = action_state.state.get("status") if action_state.state else action_state.status
                                        
                                        # 如果action状态异常或卡住，尝试重新发送
                                        if status is None or status == 1:  # Working状态但卡住
                                            logger.info(f"Resending task command for stuck robot {robot_id}, task {task.task_id}")
                                            
                                            # 如果是多动作任务，继续执行下一个动作
                                            if task.is_multi_action and task.actions:
                                                await self._execute_next_action(task, agent, robot_id)
                                            else:
                                                # 普通任务，重新发送move_to指令
                                                if task.target_pose:
                                                    move_result = await agent.move_to(
                                                        target=task.target_pose,
                                                        mode=0,
                                                        acceptable_precision=0.3,
                                                        speed_ratio=1.0
                                                    )
                                                    task.action_id = move_result.action_id
                                                    logger.info(f"Resent move_to command for stuck robot {robot_id}, new action_id={task.action_id}")
                            except Exception as e:
                                logger.error(f"Failed to resolve stuck robot {robot_id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in _check_stuck_robots: {e}", exc_info=True)
    
    async def _check_completed_task_blocking(self):
        """
        检测已完成/失败任务的机器人或IDLE状态的机器人是否阻塞了执行中任务的路径
        如果检测到阻塞，让这些机器人移动到避让点
        """
        try:
            # 获取所有已完成任务的机器人
            completed_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.COMPLETED and t.robot_id
            ]
            
            # 获取所有失败任务的机器人（也需要避让）
            failed_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.FAILED and t.robot_id
            ]
            
            # 获取所有IDLE状态的机器人（没有活跃任务的机器人）
            idle_robots = []
            robot_ids = self.robot_manager.list_robots()
            for robot_id in robot_ids:
                # 检查是否有活跃任务
                has_active_task = any(
                    t.robot_id == robot_id and 
                    (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                    for t in self.tasks.values()
                )
                if not has_active_task:
                    state = await self.robot_manager.get_robot_state(robot_id)
                    if state and state.status.value == "idle" and state.pose:
                        idle_robots.append((robot_id, state.pose))
            
            # 合并已完成任务、失败任务和IDLE状态的机器人
            blocking_robots = []
            for completed_task in completed_tasks:
                completed_robot_id = completed_task.robot_id
                if completed_robot_id in self.completed_robots_avoiding:
                    continue
                state = await self.robot_manager.get_robot_state(completed_robot_id)
                if state and state.pose:
                    blocking_robots.append((completed_robot_id, state.pose, completed_task.task_id, "completed"))
            
            # 添加失败任务的机器人
            for failed_task in failed_tasks:
                failed_robot_id = failed_task.robot_id
                if failed_robot_id in self.completed_robots_avoiding:
                    continue
                state = await self.robot_manager.get_robot_state(failed_robot_id)
                if state and state.pose:
                    blocking_robots.append((failed_robot_id, state.pose, failed_task.task_id, "failed"))
            
            # 添加IDLE状态的机器人
            for robot_id, pose in idle_robots:
                if robot_id not in self.completed_robots_avoiding:
                    blocking_robots.append((robot_id, pose, None, "idle"))
            
            if not blocking_robots:
                return
            
            # 获取所有执行中的任务（不要求路径必须存在，因为可能路径规划失败或路径未保存）
            executing_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.EXECUTING and t.robot_id and t.target_pose
            ]
            
            if not executing_tasks:
                logger.debug("No executing tasks found for blocking check")
                return
            
            logger.debug(
                f"Checking blocking: {len(blocking_robots)} potential blocking robots, "
                f"{len(executing_tasks)} executing tasks"
            )
            
            # 对每个可能阻塞的机器人，检查是否阻塞了执行中任务的路径
            for robot_id, robot_pose, task_id, task_status in blocking_robots:
                # 检查是否阻塞了任何执行中任务的路径或目标点
                blocking_executing_tasks = []
                robot_radius = 0.3  # 机器人半径
                safety_distance = 0.8  # 安全距离
                threshold_distance = robot_radius * 2 + safety_distance  # 1.4米
                
                for executing_task in executing_tasks:
                    # 获取执行中任务的机器人当前位置（用于计算到阻塞机器人的距离）
                    executing_robot_state = await self.robot_manager.get_robot_state(executing_task.robot_id)
                    if not executing_robot_state or not executing_robot_state.pose:
                        continue
                    
                    executing_path = self.task_paths.get(executing_task.task_id)
                    target_pose = executing_task.target_pose
                    
                    min_distance = float('inf')
                    blocking_reason = None
                    
                    # 1. 检查是否阻塞了执行中机器人的当前位置（如果执行中机器人被卡住）
                    dx = robot_pose.x - executing_robot_state.pose.x
                    dy = robot_pose.y - executing_robot_state.pose.y
                    current_distance = math.sqrt(dx*dx + dy*dy)
                    if current_distance < threshold_distance:
                        min_distance = current_distance
                        blocking_reason = "blocking executing robot's current position"
                    
                    # 2. 检查是否阻塞了路径（如果有路径）
                    if executing_path and len(executing_path) > 0:
                        for path_point in executing_path:
                            dx = robot_pose.x - path_point.x
                            dy = robot_pose.y - path_point.y
                            distance = math.sqrt(dx*dx + dy*dy)
                            if distance < min_distance:
                                min_distance = distance
                                blocking_reason = "blocking path"
                    
                    # 3. 检查是否阻塞了目标点（必须检查）
                    if target_pose:
                        dx = robot_pose.x - target_pose.x
                        dy = robot_pose.y - target_pose.y
                        target_distance = math.sqrt(dx*dx + dy*dy)
                        if target_distance < min_distance:
                            min_distance = target_distance
                            blocking_reason = "blocking target point"
                    
                    # 如果距离小于安全距离，认为阻塞了路径
                    if min_distance < threshold_distance:
                        logger.warning(
                            f"Robot {robot_id} is blocking task {executing_task.task_id} "
                            f"(robot: {executing_task.robot_id}): "
                            f"min_distance={min_distance:.2f}m < threshold={threshold_distance:.2f}m, "
                            f"reason={blocking_reason}"
                        )
                        blocking_executing_tasks.append(executing_task)
                
                # 如果阻塞了执行中的任务，让机器人移动到避让点
                if blocking_executing_tasks:
                    task_info = f"{task_status} task {task_id}" if task_id else f"{task_status} (no active task)"
                    logger.warning(
                        f"Robot {robot_id} ({task_info}) "
                        f"is blocking paths of {len(blocking_executing_tasks)} executing tasks. "
                        f"Moving to avoidance point immediately..."
                    )
                    
                    # 标记该机器人正在执行避让动作
                    self.completed_robots_avoiding.add(robot_id)
                    
                    # 计算避让点：向后退或移动到路径一侧（使用更高优先级，更快执行）
                    await self._move_completed_robot_to_avoidance_point(
                        robot_id,
                        robot_pose,
                        blocking_executing_tasks
                    )
                    
        except Exception as e:
            logger.error(f"Error in _check_completed_task_blocking: {e}")
    
    async def _move_completed_robot_to_avoidance_point(
        self,
        robot_id: str,
        current_pose: Pose,
        blocking_tasks: List[Task]
    ):
        """
        将已完成任务的机器人移动到避让点
        
        Args:
            robot_id: 机器人ID
            current_pose: 当前位置
            blocking_tasks: 被阻塞的任务列表
        """
        try:
            agent = self.robot_manager.get_robot_agent(robot_id)
            if not agent:
                return
            
            # 计算避让点：向后退2.5米（增加距离，确保完全让出路径），或移动到路径一侧
            # 优先选择后退，因为更简单
            backoff_distance = 2.5  # 增加后退距离，确保完全让出路径
            
            # 计算后退目标点（沿着当前朝向的反方向）
            back_x = current_pose.x - math.cos(current_pose.yaw) * backoff_distance
            back_y = current_pose.y - math.sin(current_pose.yaw) * backoff_distance
            
            # 检查后退点是否在地图范围内且不是障碍物
            if (self.path_planner.map_manager.is_valid_coordinate(back_x, back_y) and
                not self.path_planner.map_manager.is_obstacle(back_x, back_y)):
                
                backoff_pose = Pose(
                    x=back_x,
                    y=back_y,
                    z=current_pose.z,
                    yaw=current_pose.yaw
                )
                
                logger.info(
                    f"Moving completed task robot {robot_id} to avoidance point "
                    f"({back_x:.2f}, {back_y:.2f})"
                )
                
                # 移动到避让点（使用较高速度，快速让出路径）
                await agent.move_to(
                    backoff_pose,
                    mode=0,  # Free Navigation
                    acceptable_precision=0.3,
                    speed_ratio=0.8  # 提高速度，快速让出路径（从0.5提高到0.8）
                )
                
                logger.info(f"Robot {robot_id} moved to avoidance point")
                # 从避让列表中移除（避让动作已完成）
                self.completed_robots_avoiding.discard(robot_id)
            else:
                # 如果后退点不可用，尝试移动到路径一侧
                # 计算所有被阻塞路径的平均方向
                if blocking_tasks:
                    avg_direction = 0.0
                    count = 0
                    for task in blocking_tasks:
                        path = self.task_paths.get(task.task_id)
                        if path and len(path) > 1:
                            # 计算路径方向
                            dx = path[-1].x - path[0].x
                            dy = path[-1].y - path[0].y
                            if dx != 0 or dy != 0:
                                avg_direction += math.atan2(dy, dx)
                                count += 1
                    
                    if count > 0:
                        avg_direction /= count
                        # 垂直于路径方向移动（增加距离）
                        side_distance = 1.5  # 增加侧移距离，确保完全让出路径
                        side_x = current_pose.x + math.cos(avg_direction + math.pi/2) * side_distance
                        side_y = current_pose.y + math.sin(avg_direction + math.pi/2) * side_distance
                        
                        if (self.path_planner.map_manager.is_valid_coordinate(side_x, side_y) and
                            not self.path_planner.map_manager.is_obstacle(side_x, side_y)):
                            
                            side_pose = Pose(
                                x=side_x,
                                y=side_y,
                                z=current_pose.z,
                                yaw=current_pose.yaw
                            )
                            
                            logger.info(
                                f"Moving completed task robot {robot_id} to side avoidance point "
                                f"({side_x:.2f}, {side_y:.2f})"
                            )
                            
                            await agent.move_to(
                                side_pose,
                                mode=0,
                                acceptable_precision=0.3,
                                speed_ratio=0.8  # 提高速度，快速让出路径
                            )
                            
                            logger.info(f"Robot {robot_id} moved to side avoidance point")
                            # 从避让列表中移除（避让动作已完成）
                            self.completed_robots_avoiding.discard(robot_id)
                        else:
                            logger.warning(
                                f"Cannot find valid avoidance point for robot {robot_id}. "
                                f"Backoff point and side point are both invalid."
                            )
                    else:
                        logger.warning(
                            f"Cannot calculate avoidance direction for robot {robot_id}. "
                            f"No valid paths found."
                        )
                else:
                    logger.warning(f"No blocking tasks found for robot {robot_id}")
                    
        except Exception as e:
            logger.error(f"Failed to move completed task robot {robot_id} to avoidance point: {e}")
            # 发生错误时，也从避让列表中移除，允许重试
            self.completed_robots_avoiding.discard(robot_id)


# 全局任务调度器实例
_task_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler() -> TaskScheduler:
    """获取任务调度器实例（依赖注入）"""
    global _task_scheduler
    if _task_scheduler is None:
        robot_manager = get_robot_manager()
        from app.services.map_manager import get_map_manager
        map_manager = get_map_manager()
        path_planner = PathPlanner(map_manager)
        
        # 创建碰撞检测和避让策略
        from app.services.collision_detector import CollisionDetector
        from app.services.avoidance_strategy import AvoidanceStrategy
        from app.services.deadlock_detector import DeadlockDetector
        
        collision_detector = CollisionDetector(robot_manager)
        avoidance_strategy = AvoidanceStrategy(robot_manager, collision_detector, path_planner)
        deadlock_detector = DeadlockDetector(robot_manager, collision_detector, path_planner)
        
        _task_scheduler = TaskScheduler(
            robot_manager,
            path_planner,
            collision_detector,
            avoidance_strategy,
            deadlock_detector
        )
    return _task_scheduler

