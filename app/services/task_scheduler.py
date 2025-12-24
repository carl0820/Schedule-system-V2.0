"""
任务调度器（增强版本：集成碰撞检测、避让策略和死锁处理）
"""
import uuid
import asyncio
import logging
import math
import json
import time
from pathlib import Path
from typing import List, Optional, Dict, Set
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
from app.db.task_db import TaskDatabase

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
        self._scheduler_event: Optional[asyncio.Event] = None  # 用于立即触发调度检查
        self._task_creation_timestamps: Dict[str, float] = {}  # task_id -> creation_timestamp (用于计算分配耗时)
        # 分配锁：防止多个任务同时分配给同一个机器人
        # robot_id -> task_id (正在分配给该机器人的任务ID)
        self._assignment_locks: Dict[str, str] = {}  # robot_id -> task_id
        self._assignment_lock = asyncio.Lock()  # 保护分配锁字典的锁
        
        # 确保数据目录存在
        self.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化任务数据库
        self.task_db = TaskDatabase("data/tasks.db")
        
        # 从数据库加载已保存的任务（如果数据库为空，尝试从JSON文件迁移）
        self._load_tasks_from_database()
        
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
            # 传入任务调度器引用和限行区域通行管理器，让死锁检测器可以访问任务优先级和限行区域管理
            # 注意：限行区域通行管理器在下面初始化，所以这里需要延迟初始化死锁检测器
            deadlock_detector = None  # 先设置为None，在限行区域通行管理器初始化后再创建
        else:
            # 如果已经提供了死锁检测器，也设置任务调度器引用和限行区域通行管理器
            deadlock_detector.task_scheduler = self
        self._deadlock_detector_temp = deadlock_detector  # 临时保存
        
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
        
        # 记录每个action_id的开始时间（用于计算动作执行时间）
        # 格式: {task_id: {action_id: datetime}}
        self.action_start_times: Dict[str, Dict[int, datetime]] = {}
        
        # 初始化优先级计算器
        self.priority_calculator = PriorityCalculator(robot_manager, path_planner)
        
        # 初始化限行区域通行管理器
        from app.services.restricted_area_traffic_manager import RestrictedAreaTrafficManager
        from app.services.config_manager import get_config_manager
        from app.services.map_manager import get_map_manager
        map_manager = get_map_manager()
        config_manager = get_config_manager()
        self.restricted_area_traffic_manager = RestrictedAreaTrafficManager(
            map_manager, robot_manager, path_planner, config_manager, task_scheduler=self
        )
        # 注意：POI等待点将在异步上下文中加载（在_start_background_tasks_if_needed_async中）
        
        # 现在初始化死锁检测器（传入限行区域通行管理器）
        if self._deadlock_detector_temp is None:
            from app.services.deadlock_detector import DeadlockDetector
            self.deadlock_detector = DeadlockDetector(
                robot_manager, collision_detector, path_planner, task_scheduler=self,
                restricted_area_traffic_manager=self.restricted_area_traffic_manager
            )
        else:
            self.deadlock_detector = self._deadlock_detector_temp
            # 设置限行区域通行管理器引用
            self.deadlock_detector.restricted_area_traffic_manager = self.restricted_area_traffic_manager
        
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
            
            # 加载POI等待点（在启动后台任务时加载）
            try:
                await self.restricted_area_traffic_manager.load_poi_waiting_points()
                logger.info("POI waiting points loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load POI waiting points: {e}")
            
            # 启动调度器
            if self._scheduler_task is None or (self._scheduler_task and self._scheduler_task.done()):
                logger.info("Starting scheduler loop...")
                self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            
            # 启动碰撞检测任务
            if self._collision_check_task is None or (self._collision_check_task and self._collision_check_task.done()):
                logger.info("Starting collision check loop...")
                self._collision_check_task = asyncio.create_task(self._collision_check_loop())
            
            # 启动死锁检测任务（限行区域死锁需要检测）
            if self._deadlock_check_task is None or (self._deadlock_check_task and self._deadlock_check_task.done()):
                logger.info("Starting deadlock check loop...")
                try:
                    self._deadlock_check_task = asyncio.create_task(self._deadlock_check_loop())
                    logger.info("Deadlock check loop started successfully")
                except Exception as e:
                    logger.error(f"Failed to start deadlock check loop: {e}", exc_info=True)
            else:
                logger.info(f"Deadlock check loop already running (task state: done={self._deadlock_check_task.done()})")
            
            # 服务启动时强制解锁当前卡在限行区域的机器人
            async def force_unlock_stuck_robots():
                try:
                    await asyncio.sleep(2.0)  # 等待2秒，确保机器人状态已加载
                    logger.info("[STARTUP] Checking for stuck robots in restricted areas and forcing unlock...")
                    
                    # 强制检查并解锁所有限行区域的阻塞（使用force_unlock=True立即解锁）
                    await self.restricted_area_traffic_manager._check_and_resolve_capacity_overflow(force_unlock=True)
                    await self.restricted_area_traffic_manager._check_direct_blocking_in_restricted_area(force_unlock=True)
                    await self.restricted_area_traffic_manager._check_stuck_robots_in_restricted_area(force_unlock=True)
                    
                    # 强制清除所有等待状态，让机器人继续执行任务
                    waiting_robots = list(self.restricted_area_traffic_manager.robot_waiting_status.keys())
                    if waiting_robots:
                        logger.warning(
                            f"[STARTUP] Found {len(waiting_robots)} robots in waiting status: {waiting_robots}. "
                            f"Clearing waiting status to allow task continuation..."
                        )
                        for robot_id in waiting_robots:
                            if robot_id in self.restricted_area_traffic_manager.robot_waiting_status:
                                del self.restricted_area_traffic_manager.robot_waiting_status[robot_id]
                    
                    # 强制触发容量检查，让等待的机器人可以通行
                    await self.restricted_area_traffic_manager.check_waiting_robots()
                    
                    logger.info("[STARTUP] Force unlock completed")
                except Exception as e:
                    logger.error(f"[STARTUP] Failed to force unlock stuck robots: {e}", exc_info=True)
            
            # 在后台执行强制解锁
            asyncio.create_task(force_unlock_stuck_robots())
            
            logger.info(f"Background tasks started for {executing_count} existing executing tasks")
            self._need_start_background_tasks = False
        else:
            logger.debug(f"No executing tasks found ({executing_count} executing/assigned tasks), background tasks not started")
    
    def _load_tasks_from_database(self):
        """从数据库加载已保存的任务（如果数据库为空，尝试从JSON文件迁移）"""
        load_start = time.time()
        try:
            # 首先尝试从数据库加载
            tasks = self.task_db.load_all_tasks()
            load_elapsed = time.time() - load_start
            
            if tasks:
                # 数据库中有任务，直接加载
                loaded_count = 0
                for task in tasks:
                    try:
                        self.tasks[task.task_id] = task
                        loaded_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to load task {task.task_id} from database: {e}")
                        continue
                
                logger.info(f"Loaded {loaded_count} tasks from database in {load_elapsed:.3f}s")
            else:
                # 数据库为空，尝试从JSON文件迁移
                logger.info("Database is empty, attempting to migrate from JSON file...")
                self._migrate_from_json_file()
                
        except Exception as e:
            logger.error(f"Failed to load tasks from database: {e}", exc_info=True)
            # 如果数据库加载失败，尝试从JSON文件迁移
            logger.info("Database load failed, attempting to migrate from JSON file...")
            self._migrate_from_json_file()
    
    def _migrate_from_json_file(self):
        """从JSON文件迁移任务到数据库"""
        try:
            if not self.STORAGE_FILE.exists():
                logger.info(f"Storage file {self.STORAGE_FILE} does not exist. Starting with empty task list.")
                return
            
            with open(self.STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict) or 'tasks' not in data:
                logger.warning(f"Invalid storage file format: {self.STORAGE_FILE}")
                return
            
            tasks_data = data.get('tasks', [])
            if not isinstance(tasks_data, list):
                logger.warning(f"Invalid tasks data format in {self.STORAGE_FILE}")
                return
            
            loaded_count = 0
            migrated_count = 0
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
                    
                    # 保存到数据库
                    if self.task_db.save_task(task):
                        migrated_count += 1
                except Exception as e:
                    logger.warning(f"Failed to load/migrate task from storage: {e}")
                    continue
            
            logger.info(f"Migrated {migrated_count}/{loaded_count} tasks from JSON file to database")
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in storage file {self.STORAGE_FILE}: {e}")
        except Exception as e:
            logger.error(f"Failed to migrate tasks from storage file {self.STORAGE_FILE}: {e}", exc_info=True)
    
    def _save_tasks_to_file(self):
        """保存所有任务到数据库（同步版本，用于后台任务）"""
        try:
            tasks_list = list(self.tasks.values())
            if not tasks_list:
                logger.debug("No tasks to save to database")
                return
            
            # 使用批量保存以提高性能
            saved_count = self.task_db.save_tasks_batch(tasks_list)
            logger.debug(f"Saved {saved_count}/{len(tasks_list)} tasks to database")
            
        except Exception as e:
            logger.error(f"Failed to save tasks to database: {e}", exc_info=True)
    
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
        start_time = time.time()
        task_creation_time = time.time()  # 记录任务创建时间，用于计算分配耗时
        # 自动计算优先级（如果用户没有指定）
        # 优化：简化优先级计算，不再依赖起始点（系统不再需要起始点）
        if task_create.priority is None:
            # 使用默认优先级（NORMAL），任务分配时会根据机器人位置计算最优分配
            priority = TaskPriority.NORMAL
            
            # 如果有POI信息，适当提高优先级
            if task_create.poi_name:
                priority = TaskPriority.HIGH
            
            logger.info(f"Auto-calculated priority for new task: {priority.value} ({priority.name})")
        else:
            # 用户指定了优先级，使用用户指定的
            priority = task_create.priority
            logger.info(f"Using user-specified priority: {priority.value} ({priority.name})")
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 创建任务对象（不再使用start_pose，系统会根据机器人当前位置分配任务）
        task = Task(
            task_id=task_id,
            robot_id=None,
            status=TaskStatus.PENDING,
            start_pose=None,  # 不再使用起始点，系统会根据机器人当前位置分配
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
        
        # 记录任务创建时间戳（用于计算分配耗时）
        # 使用外部字典存储，因为Task是Pydantic模型，不能直接添加未定义字段
        self._task_creation_timestamps[task_id] = task_creation_time
        
        # 立即触发调度检查（事件驱动，无需等待下一个循环）
        # 如果事件对象还未初始化，在调度器循环中会初始化
        if self._scheduler_event is not None:
            self._scheduler_event.set()
            logger.debug(f"Triggered scheduler event for new task {task_id}")
        else:
            # 如果调度器还没启动，事件对象会在调度器循环中初始化
            # 这里先创建事件对象，确保可以立即触发
            self._scheduler_event = asyncio.Event()
            self._scheduler_event.set()
            logger.debug(f"Created and triggered scheduler event for new task {task_id}")
        
        # 优化：对于连续创建的任务，立即尝试一次快速分配（不等待调度器循环）
        # 这样可以更快响应，特别是当有可用机器人时
        try:
            # 快速检查是否有可用机器人（使用缓存状态，不查询）
            quick_available = []
            for robot_id in self.robot_manager.list_available_robots():
                cached_state = self.robot_manager.robot_states.get(robot_id)
                if cached_state and cached_state.status == RobotStatus.IDLE:
                    # 检查是否有活跃任务
                    has_active = any(
                        t.robot_id == robot_id and 
                        (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                        for t in self.tasks.values()
                    )
                    if not has_active:
                        quick_available.append((robot_id, cached_state))
            
            # 如果有可用机器人，立即尝试快速分配（不等待调度器循环）
            # 这对于连续创建的任务特别有效
            if quick_available:
                # 快速计算成本（使用直线距离，不进行路径规划）
                best_robot_id = None
                best_cost = float('inf')
                for robot_id, state in quick_available:
                    if state.pose:
                        dx = task.target_pose.x - state.pose.x
                        dy = task.target_pose.y - state.pose.y
                        cost = math.sqrt(dx*dx + dy*dy)
                        if cost < best_cost:
                            best_cost = cost
                            best_robot_id = robot_id
                
                if best_robot_id:
                    # 使用分配锁机制，防止多个任务同时分配给同一个机器人
                    async def try_quick_assign():
                        async with self._assignment_lock:
                            # 检查机器人是否仍然可用（防止并发分配）
                            has_active = any(
                                t.robot_id == best_robot_id and 
                                (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                                for t in self.tasks.values()
                            )
                            
                            # 检查是否有其他任务正在分配给这个机器人
                            if best_robot_id in self._assignment_locks:
                                other_task_id = self._assignment_locks[best_robot_id]
                                logger.debug(
                                    f"Robot {best_robot_id} is being assigned to task {other_task_id}, "
                                    f"skipping quick assignment for task {task_id}"
                                )
                                return
                            
                            if not has_active:
                                # 标记这个机器人正在被分配给当前任务
                                self._assignment_locks[best_robot_id] = task_id
                                logger.info(f"Quick assignment: task {task_id} to robot {best_robot_id} (cost: {best_cost:.2f}m)")
                                # 在后台异步分配，不阻塞任务创建
                                asyncio.create_task(self._assign_task_with_lock(task, best_robot_id))
                                
                                # 立即触发调度检查，确保任务快速分配
                                if self._scheduler_event is not None:
                                    self._scheduler_event.set()
                            else:
                                logger.debug(f"Robot {best_robot_id} has active task, skipping quick assignment for task {task_id}")
                    
                    # 异步尝试快速分配
                    asyncio.create_task(try_quick_assign())
                    
                    # 立即触发调度检查（即使快速分配失败，也要触发调度）
                    if self._scheduler_event is not None:
                        self._scheduler_event.set()
                    else:
                        self._scheduler_event = asyncio.Event()
                        self._scheduler_event.set()
        except Exception as e:
            logger.debug(f"Quick assignment failed for task {task_id}: {e}, will use normal scheduler")
        
        # 启动碰撞检测任务（如果还没有启动或已停止）
        if self._collision_check_task is None or self._collision_check_task.done():
            logger.info("Starting collision check loop...")
            self._collision_check_task = asyncio.create_task(self._collision_check_loop())
        else:
            logger.debug("Collision check loop already running")
        
        # 启动死锁检测任务（如果还没有启动或已停止）
        # 禁用死锁检测循环（临时禁用，专注于修复多动作任务）
        # if self._deadlock_check_task is None or self._deadlock_check_task.done():
        #     logger.info("Starting deadlock check loop...")
        #     self._deadlock_check_task = asyncio.create_task(self._deadlock_check_loop())
        # else:
        #     logger.debug("Deadlock check loop already running")
        # 启用死锁检测循环（限行区域死锁需要检测）
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
        
        # 确定目标位置（使用最后一个移动动作的目标位置，用于显示）
        target_pose = None
        last_action = task_create.actions[-1] if task_create.actions else None
        
        # 如果最后一个动作是GO_HOME，使用充电桩坐标（通常是原点(0,0,0)）
        if last_action and last_action.action_type == ActionType.GO_HOME:
            # GO_HOME动作的目标是充电桩，通常位于原点(0,0,0)
            # 注意：实际充电桩坐标可能因机器人而异，但通常都是原点
            target_pose = Pose(x=0.0, y=0.0, yaw=0.0)
        else:
            # 从后往前查找最后一个移动动作（排除GO_HOME，因为GO_HOME不是目标点）
            for action in reversed(task_create.actions):
                if action.action_type == ActionType.MOVE_TO:
                    if action.target_pose:
                        target_pose = action.target_pose
                        break
                    elif action.poi_name:
                        # POI瀵艰埅锛氫娇鐢ㄩ粯璁や綅缃紝浠诲姟鍒嗛厤鏃跺啀鑾峰彇瀹為檯浣嶇疆
                        # 娉ㄦ剰锛氳繖閲岃缃负(0,0,0)锛屼絾浼氬湪浠诲姟鍒楄〃API涓€氳繃POI瑙ｆ瀽鑾峰彇瀹為檯鍧愭爣
                        target_pose = Pose(x=0.0, y=0.0, yaw=0.0)
                        break
        # 如果没有移动动作且最后一个动作不是GO_HOME，使用默认目标位置（用于兼容）
        if target_pose is None:
            target_pose = Pose(x=0.0, y=0.0, yaw=0.0)
        
        # 创建任务对象（快速创建，不再使用start_pose）
        task = Task(
            task_id=task_id,
            robot_id=None,
            status=TaskStatus.PENDING,
            start_pose=None,  # 不再使用起始点，系统会根据机器人当前位置分配
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
        
        # 记录任务创建时间戳（用于计算分配耗时）
        # 使用外部字典存储，因为Task是Pydantic模型，不能直接添加未定义字段
        task_creation_time = time.time()
        self._task_creation_timestamps[task_id] = task_creation_time
        
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
                
                # 立即触发调度检查（事件驱动，无需等待下一个循环）
                # 如果事件对象还未初始化，在调度器循环中会初始化
                if self._scheduler_event is not None:
                    self._scheduler_event.set()
                    logger.debug(f"Triggered scheduler event for new multi-action task {task_id}")
                else:
                    # 如果调度器还没启动，事件对象会在调度器循环中初始化
                    # 这里先创建事件对象，确保可以立即触发
                    self._scheduler_event = asyncio.Event()
                    self._scheduler_event.set()
                    logger.debug(f"Created and triggered scheduler event for new multi-action task {task_id}")
                
                # 启动碰撞检测任务（如果还没有启动或已停止）
                if self._collision_check_task is None or self._collision_check_task.done():
                    logger.info("Starting collision check loop...")
                    self._collision_check_task = asyncio.create_task(self._collision_check_loop())
                else:
                    logger.debug("Collision check loop already running")
                
                # 启动死锁检测任务（如果还没有启动或已停止）
                # 启用死锁检测循环（限行区域死锁需要检测）
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
        获取任务信息（从数据库读取，确保数据一致性）
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务信息
        """
        # 优先从数据库读取，确保数据一致性
        task = self.task_db.load_task(task_id)
        if task:
            # 同步更新内存中的任务（用于调度器内部使用）
            self.tasks[task_id] = task
            return task
        
        # 如果数据库中没有，检查内存中是否有（可能是新创建但还未保存的任务）
        return self.tasks.get(task_id)
    
    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        robot_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Task]:
        """
        获取任务列表（从数据库读取，确保数据一致性，支持分页）
        
        Args:
            status: 任务状态过滤
            robot_id: 机器人ID过滤
            limit: 限制返回数量（用于分页）
            offset: 偏移量（用于分页）
            
        Returns:
            任务列表
        """
        # 使用数据库层面的分页和过滤，避免加载所有任务
        tasks = self.task_db.load_tasks_with_filters(
            status=status,
            robot_id=robot_id,
            limit=limit,
            offset=offset
        )
        
        return tasks
    
    async def count_tasks(
        self,
        status: Optional[TaskStatus] = None,
        robot_id: Optional[str] = None
    ) -> int:
        """
        统计任务数量（用于分页）
        
        Args:
            status: 任务状态过滤
            robot_id: 机器人ID过滤
            
        Returns:
            任务总数
        """
        return self.task_db.count_tasks_with_filters(status=status, robot_id=robot_id)
    
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
        
        # 初始化事件对象（在异步上下文中）
        if self._scheduler_event is None:
            self._scheduler_event = asyncio.Event()
        
        # 确保死锁检测循环已启动（如果还没有启动）
        await self._start_background_tasks_if_needed_async()
        loop_count = 0
        while True:
            try:
                loop_count += 1
                
                # 等待事件触发或超时（0.01秒），实现立即响应和定期检查
                # 进一步减少超时时间，更快响应新任务
                try:
                    await asyncio.wait_for(self._scheduler_event.wait(), timeout=0.01)
                    self._scheduler_event.clear()  # 清除事件标志
                    logger.debug("Scheduler triggered by event (new task created)")
                except asyncio.TimeoutError:
                    # 超时是正常的，继续执行调度检查
                    # 检查是否有执行中的任务需要更新状态
                    executing_tasks_check = [
                        t for t in self.tasks.values()
                        if (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED) and t.robot_id
                    ]
                    # 如果没有待分配任务，但有待执行的任务，需要定期更新状态
                    pending_tasks_check = [
                        t for t in self.tasks.values()
                        if t.status == TaskStatus.PENDING
                    ]
                    if not pending_tasks_check:
                        # 没有待分配任务，但如果有执行中的任务，需要更新状态
                        if executing_tasks_check:
                            # 定期更新执行中的任务状态（每次循环都更新，确保及时检测动作完成）
                            await self._update_executing_tasks()
                        # 继续等待事件
                        continue
                
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
                
                # 按优先级排序，相同优先级时按创建时间排序（先创建的任务先执行）
                if pending_tasks:
                    pending_tasks.sort(
                        key=lambda t: (t.priority.value, t.created_at.timestamp() if t.created_at else 0),
                        reverse=True
                    )
                
                # 查找空闲的机器人（优化：优先使用缓存状态，只查询在线机器人）
                available_robots = []
                # 只获取可用的机器人（排除停用的机器人）
                robot_ids = self.robot_manager.list_available_robots()
                if pending_tasks:
                    logger.info(f"Scheduler loop: checking {len(robot_ids)} available robots, {len(pending_tasks)} pending tasks")
                else:
                    # 没有待分配任务，减少日志输出
                    if loop_count % 20 == 0:
                        logger.debug(f"Scheduler loop iteration {loop_count}: no pending tasks")
                
                # 优化：先使用缓存状态，只对在线机器人进行查询（避免离线机器人阻塞）
                # 1. 先获取所有机器人的缓存状态
                cached_states = {}
                online_robot_ids = []
                for robot_id in robot_ids:
                    # 尝试获取缓存状态（不强制更新）
                    cached_state = self.robot_manager.robot_states.get(robot_id)
                    if cached_state:
                        # 检查缓存是否足够新（5秒内）且机器人是在线的
                        if cached_state.last_update_time:
                            time_since_update = (datetime.now() - cached_state.last_update_time).total_seconds()
                            if time_since_update < 5.0 and cached_state.status != RobotStatus.OFFLINE:
                                cached_states[robot_id] = cached_state
                                continue  # 使用缓存，不需要查询
                        # 如果机器人是在线的，需要更新状态
                        if cached_state.status != RobotStatus.OFFLINE:
                            online_robot_ids.append(robot_id)
                    else:
                        # 没有缓存，需要查询
                        online_robot_ids.append(robot_id)
                
                # 2. 只查询在线机器人（使用短超时，避免阻塞）
                if online_robot_ids:
                    robot_states = await asyncio.gather(
                        *[asyncio.wait_for(
                            self.robot_manager.get_robot_state(robot_id, force_update=True),
                            timeout=1.5  # 减少超时时间到1.5秒，更快响应
                        ) for robot_id in online_robot_ids],
                        return_exceptions=True
                    )
                    # 合并查询结果到缓存状态
                    for robot_id, state in zip(online_robot_ids, robot_states):
                        if not isinstance(state, Exception) and state:
                            cached_states[robot_id] = state
                
                # 3. 使用合并后的状态（缓存 + 查询结果）
                robot_states_list = []
                for robot_id in robot_ids:
                    if robot_id in cached_states:
                        robot_states_list.append((robot_id, cached_states[robot_id]))
                    else:
                        robot_states_list.append((robot_id, None))
                
                for robot_id, state in robot_states_list:
                    if not state:
                        # 跳过没有状态的机器人（可能是离线或查询失败）
                        continue
                    if state:
                        # 减少日志输出，只在有待分配任务时输出详细信息
                        if pending_tasks:
                            logger.debug(f"Robot {robot_id} status: {state.status.value}")
                        # 检查机器人状态是否为 IDLE（空闲）
                        # 注意：只有空闲状态的机器人才能参与调度
                        # 忙碌的机器人需要完成任务恢复到空闲状态才能参与调度
                        if state.status == RobotStatus.IDLE:
                            # 检查机器人是否被停用
                            if self.robot_manager.is_robot_disabled(robot_id):
                                logger.info(f"Robot {robot_id} is disabled, skipping task assignment")
                                continue
                            
                            # 检查机器人是否有故障（hasError、hasFatal或baseError不为空）- 有故障的机器人不参与调度
                            # 注意：errorCode为17041920或17042176的错误不影响使用，需要过滤掉
                            has_error = False
                            if state.health:
                                ignored_error_codes = [17041920, 17042176]
                                has_base_error = False
                                if state.health.baseError and len(state.health.baseError) > 0:
                                    # 过滤掉不影响使用的错误码
                                    significant_errors = [
                                        err for err in state.health.baseError 
                                        if isinstance(err, dict) and err.get('errorCode') not in ignored_error_codes
                                    ]
                                    has_base_error = len(significant_errors) > 0
                                has_error = state.health.hasError or state.health.hasFatal or has_base_error
                            
                            if has_error:
                                logger.warning(
                                    f"Robot {robot_id} has error/fatal issue, skipping task assignment "
                                    f"(hasError: {state.health.hasError if state.health else False}, "
                                    f"hasFatal: {state.health.hasFatal if state.health else False})"
                                )
                                continue  # 跳过有故障的机器人
                            
                            # 检查是否有正在执行或已分配的任务（包括ASSIGNED和EXECUTING状态）
                            # 即使机器人状态是IDLE，如果有活跃任务，也不参与调度
                            has_active_task = any(
                                t.robot_id == robot_id and 
                                (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                                for t in self.tasks.values()
                            )
                            if has_active_task:
                                logger.info(f"Robot {robot_id} has active task (ASSIGNED or EXECUTING), skipping")
                                continue
                            
                            # 检查机器人电量（电量低于20%不分配任务）
                            battery_percentage = state.power.batteryPercentage if state.power else 0
                            if battery_percentage < 20:
                                logger.info(
                                    f"Robot {robot_id} battery is too low ({battery_percentage}% < 20%), "
                                    f"skipping task assignment"
                                )
                                continue
                            
                            # 检查机器人当前位置是否为障碍物（被人为推到障碍物区域）
                            if not state.pose:
                                logger.warning(
                                    f"Robot {robot_id} has no pose information, skipping task assignment"
                                )
                                continue
                            
                            # 检查机器人当前位置是否为障碍物（被人为推到障碍物区域）
                            if self.path_planner:
                                is_obstacle = self.path_planner.map_manager.is_obstacle(
                                    state.pose.x, state.pose.y
                                )
                                if is_obstacle:
                                    logger.warning(
                                        f"Robot {robot_id} is in obstacle area "
                                        f"({state.pose.x:.2f}, {state.pose.y:.2f}), "
                                        f"skipping task assignment"
                                    )
                                    continue
                            
                            # 所有条件都满足，机器人可以参与调度
                            available_robots.append((robot_id, state))
                            # 减少日志输出，只在有多个待分配任务时输出详细信息
                            if len(pending_tasks) > 1:
                                logger.debug(
                                    f"Robot {robot_id} is available for task assignment "
                                    f"(battery: {battery_percentage}%, "
                                    f"position: ({state.pose.x:.2f}, {state.pose.y:.2f}))"
                                )
                    else:
                        logger.warning(f"Robot {robot_id} state is None, skipping")
                
                # 记录调度信息（减少日志输出，避免阻塞）
                if pending_tasks:
                    # 只在有多个待分配任务或首次分配时输出详细信息
                    if len(pending_tasks) > 1 or loop_count % 5 == 0:
                        logger.info(
                            f"Scheduler loop: {len(pending_tasks)} pending tasks, "
                            f"{len(available_robots)} available robots"
                        )
                    else:
                        logger.debug(
                            f"Scheduler loop: {len(pending_tasks)} pending tasks, "
                            f"{len(available_robots)} available robots"
                        )
                
                # 如果没有空闲机器人但有待分配任务，先更新任务状态（可能释放机器人）
                if not available_robots and pending_tasks:
                    logger.debug(
                        f"No available robots, {len(pending_tasks)} pending tasks waiting. "
                        f"Updating task status to check for newly available robots..."
                    )
                    # 更新任务状态，可能释放机器人
                    await self._update_executing_tasks()
                    
                    # 重新检查可用机器人（使用缓存状态，只查询在线机器人）
                    # 使用相同的优化策略：优先使用缓存
                    cached_states = {}
                    online_robot_ids = []
                    for robot_id in robot_ids:
                        cached_state = self.robot_manager.robot_states.get(robot_id)
                        if cached_state and cached_state.last_update_time:
                            time_since_update = (datetime.now() - cached_state.last_update_time).total_seconds()
                            if time_since_update < 5.0 and cached_state.status != RobotStatus.OFFLINE:
                                cached_states[robot_id] = cached_state
                                continue
                        if not cached_state or cached_state.status != RobotStatus.OFFLINE:
                            online_robot_ids.append(robot_id)
                    
                    if online_robot_ids:
                        robot_states = await asyncio.gather(
                            *[asyncio.wait_for(
                                self.robot_manager.get_robot_state(robot_id, force_update=True),
                                timeout=1.5
                            ) for robot_id in online_robot_ids],
                            return_exceptions=True
                        )
                        for robot_id, state in zip(online_robot_ids, robot_states):
                            if not isinstance(state, Exception) and state:
                                cached_states[robot_id] = state
                    
                    available_robots = []
                    for robot_id in robot_ids:
                        state = cached_states.get(robot_id)
                        if not state:
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
                    
                    # 如果仍然没有可用机器人，等待（但如果有新任务事件，立即响应）
                    if not available_robots:
                        # 检查是否有新任务事件（快速检查，不等待）
                        if self._scheduler_event.is_set():
                            self._scheduler_event.clear()
                            continue  # 立即继续循环，处理新任务
                        await asyncio.sleep(0.05)  # 减少等待时间到0.05秒，更快响应
                        continue
                
                # 更新执行中的任务状态（在分配新任务之前）
                await self._update_executing_tasks()
                
                # 重新检查待分配任务（因为状态更新可能导致任务完成，释放机器人）
                pending_tasks = [
                    t for t in self.tasks.values()
                    if t.status == TaskStatus.PENDING
                ]
                if pending_tasks:
                    # 按优先级排序，相同优先级时按创建时间排序（先创建的任务先执行）
                    pending_tasks.sort(
                        key=lambda t: (t.priority.value, t.created_at.timestamp() if t.created_at else 0),
                        reverse=True
                    )
                
                # 优化：复用之前查询的机器人状态，避免重复查询
                # 只更新需要更新的机器人状态（缓存超过3秒的）
                online_robot_ids_to_update = []
                for robot_id in robot_ids:
                    cached_state = cached_states.get(robot_id)
                    if not cached_state or cached_state.status == RobotStatus.OFFLINE:
                        online_robot_ids_to_update.append(robot_id)
                    elif cached_state.last_update_time:
                        time_since_update = (datetime.now() - cached_state.last_update_time).total_seconds()
                        if time_since_update >= 3.0:  # 缓存超过3秒才更新
                            online_robot_ids_to_update.append(robot_id)
                
                # 只更新需要更新的机器人状态（并发查询，使用短超时）
                if online_robot_ids_to_update:
                    robot_states = await asyncio.gather(
                        *[asyncio.wait_for(
                            self.robot_manager.get_robot_state(robot_id, force_update=True),
                            timeout=1.0  # 减少超时时间到1秒，更快响应
                        ) for robot_id in online_robot_ids_to_update],
                        return_exceptions=True
                    )
                    for robot_id, state in zip(online_robot_ids_to_update, robot_states):
                        if not isinstance(state, Exception) and state:
                            cached_states[robot_id] = state
                
                # 重新计算可用机器人（基于更新后的状态）
                available_robots = []
                for robot_id in robot_ids:
                    state = cached_states.get(robot_id)
                    if not state:
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
                # 重要：每次循环都重新检查可用机器人，确保第二个任务能找到其他可用机器人
                for task in pending_tasks:
                    # 重新检查可用机器人（因为前面的任务可能已经分配了机器人）
                    # 只检查空闲且没有活跃任务的机器人
                    current_available_robots = []
                    for robot_id in robot_ids:
                        state = cached_states.get(robot_id)
                        if not state or state.status != RobotStatus.IDLE:
                            continue
                        
                        # 检查是否有活跃任务
                        has_active_task = any(
                            t.robot_id == robot_id and 
                            (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED)
                            for t in self.tasks.values()
                        )
                        if has_active_task:
                            continue
                        
                        # 检查是否正在被分配给其他任务（分配锁）
                        # 注意：这里需要快速检查，不能长时间持有锁
                        # 使用临时变量避免在锁内执行其他操作
                        is_locked = False
                        async with self._assignment_lock:
                            is_locked = robot_id in self._assignment_locks
                        if is_locked:
                            continue
                        
                        # 检查电量
                        battery_percentage = state.power.batteryPercentage if state.power else 0
                        if battery_percentage < 20:
                            continue
                        
                        # 检查位置
                        if not state.pose:
                            continue
                        if self.path_planner:
                            is_obstacle = self.path_planner.map_manager.is_obstacle(
                                state.pose.x, state.pose.y
                            )
                            if is_obstacle:
                                continue
                        
                        current_available_robots.append((robot_id, state))
                    
                    if not current_available_robots:
                        logger.warning(
                            f"No available robots for task {task.task_id} "
                            f"(total robots: {len(robot_ids)}, "
                            f"pending tasks: {len(pending_tasks)})"
                        )
                        # 不break，继续检查下一个任务（可能其他任务可以分配）
                        continue
                    
                    # 在计算成本之前，先过滤掉已经有活跃任务的机器人（双重检查，确保不会重复分配）
                    filtered_available_robots = []
                    for robot_id, state in current_available_robots:
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
                        # 不break，继续检查下一个任务
                        continue
                    
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
                            
                            # 优化：移除系统路径规划，只使用直线距离计算成本
                            # 机器人会使用自己的导航系统进行路径规划，系统只需要选择最近的机器人
                            dx = target_pose.x - robot_pose.x
                            dy = target_pose.y - robot_pose.y
                            cost = math.sqrt(dx*dx + dy*dy)
                            
                            logger.debug(
                                f"Robot {robot_id} cost for task {task.task_id}: "
                                f"straight-line distance = {cost:.2f}m (robot will use its own path planner)"
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
                    
                    # 记录所有机器人的成本，便于调试（减少日志输出）
                    if robot_costs and len(pending_tasks) <= 2:
                        logger.debug(
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
                            # 继续下一个任务（不修改available_robots，因为每次循环都重新检查）
                            continue
                        
                        # 使用分配锁机制，防止多个任务同时分配给同一个机器人
                        async with self._assignment_lock:
                            # 再次检查是否有其他任务正在分配给这个机器人
                            if best_robot_id in self._assignment_locks:
                                other_task_id = self._assignment_locks[best_robot_id]
                                logger.debug(
                                    f"Robot {best_robot_id} is being assigned to task {other_task_id}, "
                                    f"skipping assignment for task {task.task_id}"
                                )
                                # 继续下一个任务（不修改available_robots，因为每次循环都重新检查）
                                continue
                            
                            # 标记这个机器人正在被分配给当前任务
                            self._assignment_locks[best_robot_id] = task.task_id
                        
                        # 分配任务
                        # 计算从创建到分配的时间
                        assignment_time = time.time()
                        assignment_delay = 0.0
                        if task.task_id in self._task_creation_timestamps:
                            assignment_delay = assignment_time - self._task_creation_timestamps[task.task_id]
                            logger.info(
                                f"Assigning task {task.task_id} to robot {best_robot_id} "
                                f"(best cost: {best_cost:.2f}m, target: ({task.target_pose.x}, {task.target_pose.y}), "
                                f"assignment delay: {assignment_delay:.2f}s)"
                            )
                            if assignment_delay > 10.0:
                                logger.warning(
                                    f"Task {task.task_id} assignment delay ({assignment_delay:.2f}s) exceeds 10s threshold!"
                                )
                            # 分配完成后，清理时间戳（节省内存）
                            del self._task_creation_timestamps[task.task_id]
                        else:
                            logger.info(
                                f"Assigning task {task.task_id} to robot {best_robot_id} "
                                f"(best cost: {best_cost:.2f}m, target: ({task.target_pose.x}, {task.target_pose.y}))"
                            )
                        await self._assign_task_with_lock(task, best_robot_id)
                        # 任务已分配，继续下一个任务（不需要修改available_robots，因为每次循环都重新检查）
                    else:
                        logger.warning(
                            f"No available robot found for task {task.task_id} "
                            f"(target: {task.target_pose.x}, {task.target_pose.y})"
                        )
                
                # 更新执行中的任务状态
                await self._update_executing_tasks()
                
                # 不再需要sleep，因为事件机制已经处理了等待
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(1.0)
            
            # 【重要修复】即使没有待分配任务，也要定期更新执行中的任务状态
            # 这确保多动作任务能够及时检测动作完成并切换到下一个动作
            executing_tasks_count = len([
                t for t in self.tasks.values()
                if (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED) and t.robot_id
            ])
            if executing_tasks_count > 0:
                # 有执行中的任务，定期更新状态（每2次循环更新一次，约1秒）
                if loop_count % 2 == 0:
                    await self._update_executing_tasks()
    
    async def _assign_task_with_lock(self, task: Task, robot_id: str):
        """
        带锁的任务分配方法（内部方法，确保分配完成后释放锁）
        """
        try:
            await self._assign_task(task, robot_id)
        finally:
            # 释放分配锁
            async with self._assignment_lock:
                if robot_id in self._assignment_locks and self._assignment_locks[robot_id] == task.task_id:
                    del self._assignment_locks[robot_id]
                    logger.debug(f"Released assignment lock for robot {robot_id} (task {task.task_id})")
    
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
            
            logger.info(f"Robot agent found for {robot_id}, assigning task directly (robot will use its own path planner)")
            
            # 优化：移除系统路径规划，让机器人使用自己的导航系统
            # 系统只需要分配任务，机器人会自主导航到目标点
            # 死锁解锁策略会在运行时处理冲突情况
            
            # 在分配前，再次检查机器人是否已经有活跃任务（防止并发分配）
            has_active_task = any(
                t.robot_id == robot_id and 
                (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED) and
                t.task_id != task.task_id  # 排除当前任务本身
                for t in self.tasks.values()
            )
            
            if has_active_task:
                error_msg = f"Robot {robot_id} already has an active task (ASSIGNED or EXECUTING), cannot assign new task {task.task_id}"
                logger.warning(error_msg)
                # 重置任务状态，允许重新分配
                task.status = TaskStatus.PENDING
                task.robot_id = None
                task.assigned_at = None
                self._save_tasks_to_file()
                return
            
            # 检查机器人当前是否有正在执行的action（通过API查询）
            try:
                current_action = await agent.get_current_action()
                if current_action and current_action.status == 1:  # status=1表示正在执行
                    error_msg = f"Robot {robot_id} already has an executing action (action_id={current_action.action_id}), cannot assign new task {task.task_id}"
                    logger.warning(error_msg)
                    # 重置任务状态，允许重新分配
                    task.status = TaskStatus.PENDING
                    task.robot_id = None
                    task.assigned_at = None
                    self._save_tasks_to_file()
                    return
            except Exception as e:
                # 如果查询失败，记录警告但继续（可能是网络问题）
                logger.warning(f"Failed to check current action for robot {robot_id}: {e}, continuing with assignment")
            
            # 获取机器人当前位置，设置为任务的起始位置
            robot_state = None
            try:
                robot_state = await self.robot_manager.get_robot_state(robot_id)
                if robot_state and robot_state.pose:
                    task.start_pose = robot_state.pose
                    logger.debug(
                        f"Task {task.task_id} start_pose set to robot {robot_id} current position: "
                        f"({robot_state.pose.x}, {robot_state.pose.y})"
                    )
            except Exception as e:
                logger.warning(f"Failed to get robot {robot_id} position for start_pose: {e}")
            
            # 检查限行区域通行（如果机器人在限行区域内或接近限行区域）
            if robot_state and robot_state.pose:
                try:
                    # 获取任务优先级（值越小优先级越高）
                    task_priority_value = task.priority.value  # TaskPriority枚举值：1-4
                    # 转换为数值（值越小优先级越高，用于限行区域管理器）
                    priority_for_traffic = float(task_priority_value)
                    
                    # 检查限行区域通行
                    can_pass, waiting_point, error = await self.restricted_area_traffic_manager.check_and_manage_traffic(
                        robot_id, robot_state.pose, priority_for_traffic, task.task_id
                    )
                    
                    if not can_pass:
                        if waiting_point:
                            # 需要移动到等待点
                            logger.info(
                                f"[RESTRICTED AREA] Robot {robot_id} needs to wait at waiting point "
                                f"({waiting_point.x:.2f}, {waiting_point.y:.2f}) before executing task {task.task_id}"
                            )
                            
                            # 标记任务为已分配，但状态保持ASSIGNED（等待通行）
                            task.robot_id = robot_id
                            task.status = TaskStatus.ASSIGNED
                            task.assigned_at = datetime.now()
                            task.retry_count = 0
                            self._save_tasks_to_file()
                            
                            # 移动到等待点
                            try:
                                action_state = await agent.move_to(
                                    target=waiting_point,
                                    mode=0,
                                    acceptable_precision=0.5,  # 等待点精度可以放宽
                                    speed_ratio=1.0
                                )
                                task.action_id = action_state.action_id
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} moving to waiting point, "
                                    f"action_id={action_state.action_id}"
                                )
                                self._save_tasks_to_file()
                                return  # 等待到达等待点后再继续执行任务
                            except Exception as e:
                                logger.error(
                                    f"[RESTRICTED AREA] Failed to move robot {robot_id} to waiting point: {e}",
                                    exc_info=True
                                )
                                # 如果移动到等待点失败，继续尝试执行任务（可能限行区域已释放）
                        else:
                            logger.error(
                                f"[RESTRICTED AREA] Robot {robot_id} cannot pass restricted area: {error}"
                            )
                            # 如果无法找到等待点，继续尝试执行任务（可能限行区域已释放）
                except Exception as e:
                    logger.warning(
                        f"[RESTRICTED AREA] Failed to check restricted area traffic for robot {robot_id}: {e}",
                        exc_info=True
                    )
                    # 如果检查失败，继续执行任务（不阻塞）
            
            # 先标记任务为已分配，避免在同一个调度循环中重复分配
            task.robot_id = robot_id
            task.status = TaskStatus.ASSIGNED
            task.assigned_at = datetime.now()
            task.retry_count = 0  # 重置重试计数
            
            # 如果是多动作任务且最后一个动作是GO_HOME，尝试获取充电桩的实际坐标
            if task.is_multi_action and task.actions:
                last_action = task.actions[-1]
                if last_action.action_type == ActionType.GO_HOME:
                    try:
                        dock_pose = await agent.get_home_dock_pose()
                        if dock_pose:
                            # 更新target_pose为充电桩的实际坐标
                            task.target_pose = dock_pose
                            logger.info(
                                f"Task {task.task_id} GO_HOME: updated target_pose to actual dock pose "
                                f"({dock_pose.x:.2f}, {dock_pose.y:.2f}, {dock_pose.yaw:.2f}) for robot {robot_id}"
                            )
                        else:
                            logger.debug(
                                f"Task {task.task_id} GO_HOME: could not get dock pose for robot {robot_id}, "
                                f"using default (0,0,0)"
                            )
                    except Exception as e:
                        logger.debug(f"Failed to get home dock pose for robot {robot_id}: {e}")
            
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
                
                # 在调用move_to之前，最后一次检查（防止在标记ASSIGNED到调用move_to之间的时间窗口内被其他任务分配）
                has_active_task_final = any(
                    t.robot_id == robot_id and 
                    (t.status == TaskStatus.EXECUTING or t.status == TaskStatus.ASSIGNED) and
                    t.task_id != task.task_id
                    for t in self.tasks.values()
                )
                
                if has_active_task_final:
                    error_msg = f"Robot {robot_id} was assigned another task while preparing to assign task {task.task_id}, cancelling assignment"
                    logger.warning(error_msg)
                    # 重置任务状态，允许重新分配
                    task.status = TaskStatus.PENDING
                    task.robot_id = None
                    task.assigned_at = None
                    self._save_tasks_to_file()
                    return
                
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
        from app.services.deadlock_detector import deadlock_logger
        deadlock_logger.info("=" * 80)
        deadlock_logger.info("Deadlock check loop started")
        deadlock_logger.info("=" * 80)
        loop_count = 0
        while True:
            try:
                loop_count += 1
                
                # 首先检查是否有执行中的任务，如果没有就直接跳过检测，避免在没有任务时仍然运行
                executing_count = len([
                    t for t in self.tasks.values()
                    if t.status.value in ["EXECUTING", "ASSIGNED"]
                ])
                
                if executing_count == 0:
                    # 没有执行中的任务，跳过死锁检测和阻塞检查
                    await asyncio.sleep(0.5)
                    continue
                
                # 每20次循环（10秒）记录一次运行状态
                if loop_count % 20 == 0:
                    deadlock_logger.debug(f"Deadlock check loop running (iteration {loop_count})")
                
                # 检测死锁
                deadlocks = await self.deadlock_detector.detect_deadlocks()
                
                # 记录检测结果（用于验证）
                robot_ids = self.robot_manager.list_robots()
                
                # 每10次循环（5秒）记录一次检测状态（INFO级别，确保能看到）
                if loop_count % 10 == 0:
                    deadlock_logger.info(
                        f"[DETECT] Cycle {loop_count}: {len(robot_ids)} robots, "
                        f"{executing_count} executing tasks, {len(deadlocks)} deadlock(s) detected"
                    )
                
                if deadlocks:
                    deadlock_logger.info(
                        f"[DETECT] Found {len(deadlocks)} potential deadlock(s) in this cycle: "
                        f"{[f'{d.deadlock_type}({d.robot_ids}, duration={d.duration:.1f}s)' for d in deadlocks]}"
                    )
                elif executing_count >= 2 and len(robot_ids) >= 2:
                    # 有多个执行中的任务但没有检测到死锁，说明机器人正常通行
                    if loop_count % 20 == 0:  # 每10秒记录一次
                        deadlock_logger.info(
                            f"[DETECT] No deadlock detected - robots are moving normally "
                            f"({executing_count} executing tasks, {len(robot_ids)} robots)"
                        )
                
                # 处理死锁
                for deadlock in deadlocks:
                    # 重新加载配置以获取最新的阈值
                    self.deadlock_detector._load_config()
                    
                    # 根据死锁类型使用不同的阈值
                    threshold = self.deadlock_detector.deadlock_threshold  # 默认阈值
                    if deadlock.deadlock_type == "restricted_area":
                        # 限行区域死锁：立即触发解决（阈值为0），因为容量溢出需要立即处理
                        threshold = 0.0
                    elif deadlock.deadlock_type == "narrow_passage":
                        threshold = self.deadlock_detector.narrow_passage_deadlock_threshold
                    elif deadlock.deadlock_type == "circular_wait":
                        threshold = self.deadlock_detector.circular_wait_deadlock_threshold
                    elif deadlock.deadlock_type == "mutual_blocking":
                        # mutual_blocking死锁：立即触发解决（阈值为0），因为相互阻塞需要立即处理
                        threshold = 0.0
                    elif deadlock.deadlock_type == "resource_contention":
                        # 资源竞争（单个机器人卡住）使用较短的阈值
                        threshold = 5.0  # 5秒后认为卡住
                    elif deadlock.deadlock_type == "livelock":
                        # 活锁使用较长的阈值（因为需要观察一段时间才能确定）
                        threshold = self.deadlock_detector.livelock_threshold
                    elif deadlock.deadlock_type == "starvation":
                        # 饥饿死锁使用较长的阈值
                        threshold = self.deadlock_detector.starvation_deadlock_threshold
                    
                    # 记录死锁检测信息（即使未超过阈值也记录，便于调试）
                    from app.services.deadlock_detector import deadlock_logger
                    if deadlock.duration > threshold:
                        deadlock_logger.warning(
                            f"Deadlock detected: {deadlock.deadlock_type} "
                            f"involving robots {deadlock.robot_ids} "
                            f"(duration: {deadlock.duration:.1f}s, threshold: {threshold:.1f}s) - Attempting to resolve..."
                        )
                        logger.warning(
                            f"Deadlock detected: {deadlock.deadlock_type} "
                            f"involving robots {deadlock.robot_ids} "
                            f"(duration: {deadlock.duration:.1f}s, threshold: {threshold:.1f}s) - Attempting to resolve..."
                        )
                        
                        # 尝试解决死锁
                        success = await self.deadlock_detector.resolve_deadlock(deadlock)
                        if success:
                            deadlock_logger.info(f"✓ Deadlock resolved successfully for robots {deadlock.robot_ids}")
                            logger.info(f"✓ Deadlock resolved successfully for robots {deadlock.robot_ids}")
                        else:
                            deadlock_logger.error(f"✗ Failed to resolve deadlock for robots {deadlock.robot_ids} - tasks may be cancelled")
                            logger.error(f"✗ Failed to resolve deadlock for robots {deadlock.robot_ids} - tasks may be cancelled")
                    else:
                        # 记录死锁但未超过阈值的情况（INFO级别，确保能看到）
                        deadlock_logger.info(
                            f"[DETECT] Deadlock detected but below threshold: {deadlock.deadlock_type} "
                            f"involving robots {deadlock.robot_ids} "
                            f"(duration: {deadlock.duration:.1f}s, threshold: {threshold:.1f}s) - Will resolve when threshold exceeded"
                        )
                
                # 检测单个机器人卡住的情况（即使不是死锁，也需要处理）
                await self._check_stuck_robots()
                
                # 检测已完成任务的机器人是否阻塞了执行中任务的路径（提高检测频率）
                await self._check_completed_task_blocking()
                
                # 减少等待时间，提高响应速度（更快检测阻塞）
                await asyncio.sleep(0.2)
                
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
                if not task:
                    # 任务不存在，移除记录
                    robots_to_remove.append(robot_id)
                    continue
                
                # 如果任务已完成或已取消，移除记录
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    robots_to_remove.append(robot_id)
                    continue
                
                # 如果任务状态是 PENDING，但机器人正在死锁解除中，也应该恢复任务
                # 这可能是因为任务在死锁解除过程中被重置为 PENDING
                if task.status == TaskStatus.PENDING:
                    logger.warning(
                        f"Task {task_id} is PENDING but robot {robot_id} is in deadlock resolution, "
                        f"will attempt to resume task"
                    )
                    # 继续执行恢复逻辑，不要跳过
                
                # 获取机器人当前位置
                state = await self.robot_manager.get_robot_state(robot_id)
                if not state or not state.pose:
                    # 如果超时（60秒），强制恢复任务执行（增加超时时间，给死锁解除更多时间）
                    if start_time and (now - start_time).total_seconds() > 60.0:
                        logger.warning(
                            f"Robot {robot_id} timeout reaching waiting point (60s), "
                            f"forcing task {task_id} resume"
                        )
                        await self._resume_task_after_deadlock_resolution(task, robot_id)
                        robots_to_remove.append(robot_id)
                    continue
                
                # 检查是否需要立即恢复（对于相互阻塞等场景，后退后立即恢复）
                immediate_resume = resolution_info.get('immediate_resume', False)
                if immediate_resume:
                    from app.services.deadlock_detector import deadlock_logger
                    deadlock_logger.info(
                        f"[UNLOCK VERIFY] Robot {robot_id} immediate resume requested, "
                        f"resuming task {task_id} immediately"
                    )
                    logger.info(
                        f"Robot {robot_id} immediate resume requested, resuming task {task_id}"
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
                    from app.services.deadlock_detector import deadlock_logger
                    deadlock_logger.info(
                        f"[UNLOCK VERIFY] Robot {robot_id} reached waiting point "
                        f"(distance={distance:.2f}m < 0.5m), resuming task {task_id}"
                    )
                    logger.info(
                        f"Robot {robot_id} reached waiting point (distance={distance:.2f}m), "
                        f"resuming task {task_id}"
                    )
                    await self._resume_task_after_deadlock_resolution(task, robot_id)
                    robots_to_remove.append(robot_id)
                elif start_time and (now - start_time).total_seconds() > 60.0:
                    # 超时，强制恢复（增加超时时间到60秒）
                    logger.warning(
                        f"Robot {robot_id} timeout reaching waiting point (60s, distance={distance:.2f}m), "
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
    
    async def _release_robot_from_restricted_area_on_completion(self, task: Task):
        """
        任务完成时释放机器人在限行区域的占用
        
        Args:
            task: 已完成的任务
        """
        if not task.robot_id:
            return
        
        try:
            robot_state = await self.robot_manager.get_robot_state(task.robot_id, force_update=False)
            if robot_state and robot_state.pose:
                # 检查机器人是否在限行区域内
                restricted_areas = self.map_manager.restricted_areas
                for area in restricted_areas:
                    area_id = area.get("id")
                    area_data = area.get("area", {})
                    if area_data:
                        start = area_data.get("start", {})
                        end = area_data.get("end", {})
                        half_width = area_data.get("half_width", 0.5)
                        if start and end:
                            if self.restricted_area_traffic_manager.is_point_in_restricted_area(
                                robot_state.pose, start, end, half_width
                            ):
                                await self.restricted_area_traffic_manager.release_robot_from_area(
                                    task.robot_id, area_id
                                )
                                logger.info(
                                    f"[RESTRICTED AREA] Released robot {task.robot_id} from restricted area {area_id} "
                                    f"after task {task.task_id} completion"
                                )
                                break
        except Exception as e:
            logger.debug(f"Failed to release robot {task.robot_id} from restricted area: {e}")
    
    async def _check_and_resume_waiting_robots(self):
        """
        检查等待限行区域通行的机器人是否可以恢复任务
        
        当限行区域有空位时，等待的机器人可以继续执行任务
        
        注意：不仅要检查waiting_status中的机器人，还要检查所有执行中的任务，
        看看是否有机器人在等待点，并且已经在通行列表中（可能等待状态已被check_waiting_robots清除）
        """
        waiting_status = self.restricted_area_traffic_manager.robot_waiting_status
        
        robots_to_resume = []
        robots_to_resume_set = set()  # 用于避免重复添加
        
        # 首先检查所有执行中的任务，看看是否有机器人在通行列表中，但没有action_id
        # 这可以处理check_waiting_robots已经将机器人移到通行列表，但等待状态已被清除的情况
        logger.info(f"[RESTRICTED AREA] Checking {len(self.tasks)} tasks for robots in traffic list")
        for task_id, task in list(self.tasks.items()):
            if task.status not in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED]:
                logger.debug(f"[RESTRICTED AREA] Task {task_id} status={task.status.value}, skipping")
                continue
            if not task.robot_id:
                continue
            
            robot_id = task.robot_id
            # 检查机器人是否在某个限行区域的通行列表中
            for area_id, traffic in self.restricted_area_traffic_manager.area_traffic.items():
                if robot_id in traffic['robots']:
                    logger.info(
                        f"[RESTRICTED AREA] Robot {robot_id} is in traffic list for area {area_id}, "
                        f"task {task_id} status={task.status.value}, action_id={task.action_id}, "
                        f"in_waiting_status={robot_id in waiting_status}, "
                        f"is_multi_action={task.is_multi_action if hasattr(task, 'is_multi_action') else False}, "
                        f"current_action_index={task.current_action_index if hasattr(task, 'current_action_index') else None}"
                    )
                    # 机器人已经在通行列表中
                    # 如果任务没有action_id，或者action_id对应的action已经完成/aborted，应该恢复任务
                    should_resume = False
                    if not task.action_id:
                        # 任务没有action_id，说明可能正在等待限行区域释放
                        should_resume = True
                        reason = "task has no action_id"
                    else:
                        # 检查action_id对应的action是否已经完成/aborted
                        try:
                            agent = self.robot_manager.get_robot_agent(robot_id)
                            if agent:
                                action_state = await agent.get_action_status(task.action_id)
                                if action_state:
                                    status = action_state.state.get("status") if action_state.state else action_state.status
                                    result = action_state.state.get("result") if action_state.state else action_state.result
                                    # 如果action已经完成（status=4）或aborted（result=-2），应该恢复任务
                                    if status == 4 or result == -2:
                                        should_resume = True
                                        reason = f"action {task.action_id} is done (status={status}, result={result})"
                        except Exception as e:
                            logger.debug(f"Failed to check action status for task {task_id}: {e}")
                            # 如果无法检查action状态，但机器人不在等待状态中，也尝试恢复任务
                            if robot_id not in waiting_status:
                                should_resume = True
                                reason = "cannot check action status and robot not in waiting status"
                    
                    if should_resume:
                        # 机器人已经在通行列表中，但不在等待状态中，或者action已经完成/aborted
                        # 说明check_waiting_robots已经将机器人移到通行列表，但任务还没有恢复
                        # 重要：即使机器人还在waiting_status中，只要在通行列表中且任务没有action_id，也应该恢复任务
                        # 因为check_waiting_robots已经将机器人移到了通行列表，说明限行区域已经释放
                        if robot_id not in waiting_status:
                            if (robot_id, task_id) not in robots_to_resume_set:
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} is in traffic list for area {area_id} "
                                    f"and {reason}. Resuming task {task_id}."
                                )
                                robots_to_resume.append((robot_id, task_id, task))
                                robots_to_resume_set.add((robot_id, task_id))
                        else:
                            # 机器人还在waiting_status中，但已经在通行列表中
                            # 说明check_waiting_robots已经将机器人移到了通行列表，但waiting_status可能还没有清除
                            # 这种情况下，也应该恢复任务，并清除waiting_status
                            if (robot_id, task_id) not in robots_to_resume_set:
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} is in traffic list for area {area_id} "
                                    f"and {reason}, but still in waiting_status. Resuming task {task_id} and clearing waiting_status."
                                )
                                robots_to_resume.append((robot_id, task_id, task))
                                robots_to_resume_set.add((robot_id, task_id))
                                # 清除waiting_status，因为机器人已经在通行列表中了
                                if robot_id in waiting_status:
                                    del waiting_status[robot_id]
                        break
                    else:
                        logger.info(
                            f"[RESTRICTED AREA] Robot {robot_id} is in traffic list for area {area_id} "
                            f"but should_resume=False (task has action_id={task.action_id})"
                        )
        
        # 然后检查waiting_status中的机器人
        if not waiting_status:
            # 如果没有等待状态，但上面找到了需要恢复的任务，直接处理
            if robots_to_resume:
                pass  # 继续处理robots_to_resume
            else:
                return
        
        for robot_id, status in list(waiting_status.items()):
            try:
                area_id = status.get('area_id')
                waiting_point = status.get('waiting_point')
                task_id = status.get('original_task_id')
                waiting_since = status.get('waiting_since')
                
                if not task_id or not area_id:
                    continue
                
                # 获取任务
                task = self.tasks.get(task_id)
                if not task:
                    # 任务不存在，清除等待状态
                    if robot_id in waiting_status:
                        del waiting_status[robot_id]
                    continue
                
                # 如果任务已完成或已取消，清除等待状态
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    if robot_id in waiting_status:
                        del waiting_status[robot_id]
                    continue
                
                # 检查机器人是否在限行区域的通行列表中（说明可以通行了）
                traffic = self.restricted_area_traffic_manager.area_traffic.get(area_id)
                if traffic and robot_id in traffic['robots']:
                    # 机器人可以通行了，恢复任务
                    if (robot_id, task_id) not in robots_to_resume_set:
                        robots_to_resume.append((robot_id, task_id, task))
                        robots_to_resume_set.add((robot_id, task_id))
                    
                    # 清除等待状态
                    if robot_id in waiting_status:
                        del waiting_status[robot_id]
                    
                    logger.info(
                        f"[RESTRICTED AREA] Robot {robot_id} can now pass through restricted area {area_id}, "
                        f"resuming task {task_id}"
                    )
                    continue  # 已处理，继续下一个机器人
                
                # 如果机器人不在通行列表中，但限行区域有空位，尝试重新申请通行
                # 这可以处理机器人尚未到达等待点，但限行区已释放的情况
                if traffic and len(traffic['robots']) < traffic.get('capacity', 1):
                    # 限行区域有空位，尝试重新申请通行
                    try:
                        robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=False)
                        if robot_state and robot_state.pose:
                            priority_value = task.priority.value
                            can_pass, _, _ = await self.restricted_area_traffic_manager.check_and_manage_traffic(
                                robot_id, robot_state.pose, float(priority_value), task_id
                            )
                            if can_pass:
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} can now pass through restricted area {area_id} "
                                    f"(capacity available), resuming task {task_id}"
                                )
                                if (robot_id, task_id) not in robots_to_resume_set:
                                    robots_to_resume.append((robot_id, task_id, task))
                                    robots_to_resume_set.add((robot_id, task_id))
                                if robot_id in waiting_status:
                                    del waiting_status[robot_id]
                                continue  # 已处理，继续下一个机器人
                    except Exception as e:
                        logger.debug(f"Failed to check traffic for robot {robot_id}: {e}")
                
                # 检查机器人是否到达等待点
                if waiting_point:
                    # 检查机器人是否到达等待点
                    robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=False)
                    if robot_state and robot_state.pose:
                        # 首先检查机器人是否还在限行区域内
                        # 如果不在限行区域内，应该清除等待状态，而不是恢复任务
                        is_still_in_area = False
                        restricted_areas = self.restricted_area_traffic_manager.map_manager.restricted_areas
                        for area in restricted_areas:
                            area_data = area.get("area", {})
                            if not area_data or area.get("id") != area_id:
                                continue
                            start = area_data.get("start", {})
                            end = area_data.get("end", {})
                            half_width = area_data.get("half_width", 0.5)
                            if start and end:
                                is_still_in_area = self.restricted_area_traffic_manager.is_point_in_restricted_area(
                                    robot_state.pose, start, end, half_width
                                )
                                if is_still_in_area:
                                    break
                        
                        # 如果机器人不在限行区域内了，且未到达等待点，清除等待状态并恢复任务
                        if not is_still_in_area:
                            distance = math.sqrt(
                                (robot_state.pose.x - waiting_point.x) ** 2 + 
                                (robot_state.pose.y - waiting_point.y) ** 2
                            )
                            if distance >= 0.5:  # 未到达等待点
                                # 重要：检查机器人是否在充电桩附近，如果是，不应该恢复任务（可能是回桩了）
                                distance_to_origin = math.sqrt(robot_state.pose.x ** 2 + robot_state.pose.y ** 2)
                                if distance_to_origin < 1.5 and robot_state.status.value == "idle":
                                    # 机器人在充电桩附近，可能是回桩了，不应该恢复任务
                                    logger.warning(
                                        f"[RESTRICTED AREA] Robot {robot_id} is no longer in restricted area {area_id} "
                                        f"and is at charging dock (distance={distance_to_origin:.2f}m, status=idle). "
                                        f"Task {task_id} may have been interrupted. Clearing waiting status but NOT resuming task."
                                    )
                                    if robot_id in waiting_status:
                                        del waiting_status[robot_id]
                                    if traffic and traffic['waiting_queue']:
                                        traffic['waiting_queue'] = [
                                            (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                            if wid != robot_id
                                        ]
                                    continue
                                
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} is no longer in restricted area {area_id} "
                                    f"and has not reached waiting point, clearing waiting status and resuming task"
                                )
                                # 恢复任务，因为机器人已经不在限行区域内了，应该继续执行任务
                                if (robot_id, task_id) not in robots_to_resume_set:
                                    robots_to_resume.append((robot_id, task_id, task))
                                    robots_to_resume_set.add((robot_id, task_id))
                                if robot_id in waiting_status:
                                    del waiting_status[robot_id]
                                # 从等待队列中移除
                                if traffic and traffic['waiting_queue']:
                                    traffic['waiting_queue'] = [
                                        (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                        if wid != robot_id
                                    ]
                                continue
                            # 如果到达等待点但不在限行区域内，应该检查限行区域是否有空位
                            # 只有当限行区域有空位时，才恢复任务；否则继续等待
                            else:
                                # 重要：检查机器人是否在充电桩附近，如果是，不应该恢复任务（可能是回桩了）
                                distance_to_origin = math.sqrt(robot_state.pose.x ** 2 + robot_state.pose.y ** 2)
                                if distance_to_origin < 1.5 and robot_state.status.value == "idle":
                                    # 机器人在充电桩附近，可能是回桩了，不应该恢复任务
                                    logger.warning(
                                        f"[RESTRICTED AREA] Robot {robot_id} reached waiting point but is at charging dock "
                                        f"(distance={distance_to_origin:.2f}m, status=idle). "
                                        f"Task {task_id} may have been interrupted. Clearing waiting status but NOT resuming task."
                                    )
                                    if robot_id in waiting_status:
                                        del waiting_status[robot_id]
                                    if traffic and traffic['waiting_queue']:
                                        traffic['waiting_queue'] = [
                                            (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                            if wid != robot_id
                                        ]
                                    continue
                                
                                # 检查限行区域是否有空位（通过检查机器人是否在通行列表中）
                                if traffic and robot_id in traffic['robots']:
                                    # 机器人在通行列表中，说明限行区域已释放，可以恢复任务
                                    logger.info(
                                        f"[RESTRICTED AREA] Robot {robot_id} reached waiting point and restricted area {area_id} "
                                        f"has capacity available, resuming task {task_id}"
                                    )
                                    if (robot_id, task_id) not in robots_to_resume_set:
                                        robots_to_resume.append((robot_id, task_id, task))
                                        robots_to_resume_set.add((robot_id, task_id))
                                    if robot_id in waiting_status:
                                        del waiting_status[robot_id]
                                    if traffic and traffic['waiting_queue']:
                                        traffic['waiting_queue'] = [
                                            (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                            if wid != robot_id
                                        ]
                                # 检查限行区域是否有空位（即使机器人不在通行列表中，也可能有空位）
                                elif traffic and len(traffic['robots']) < traffic.get('capacity', 1):
                                    # 限行区域有空位，尝试重新申请通行
                                    priority_value = task.priority.value
                                can_pass, _, _ = await self.restricted_area_traffic_manager.check_and_manage_traffic(
                                    robot_id, robot_state.pose, float(priority_value), task_id
                                )
                                if can_pass:
                                    logger.info(
                                        f"[RESTRICTED AREA] Robot {robot_id} reached waiting point and restricted area {area_id} "
                                        f"has capacity available, resuming task {task_id}"
                                    )
                                    if (robot_id, task_id) not in robots_to_resume_set:
                                        robots_to_resume.append((robot_id, task_id, task))
                                        robots_to_resume_set.add((robot_id, task_id))
                                    if robot_id in waiting_status:
                                        del waiting_status[robot_id]
                                    if traffic and traffic['waiting_queue']:
                                        traffic['waiting_queue'] = [
                                            (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                            if wid != robot_id
                                        ]
                                    else:
                                        # 限行区域还没有空位，继续等待
                                        logger.debug(
                                            f"[RESTRICTED AREA] Robot {robot_id} reached waiting point but restricted area {area_id} "
                                            f"is still occupied, waiting for capacity to be available"
                                        )
                                else:
                                    # 限行区域还没有空位，继续等待
                                    logger.debug(
                                        f"[RESTRICTED AREA] Robot {robot_id} reached waiting point but restricted area {area_id} "
                                        f"is still occupied (capacity: {traffic.get('capacity', 1) if traffic else 1}, "
                                        f"current: {len(traffic['robots']) if traffic else 0}), waiting for capacity to be available"
                                    )
                                continue
                        
                        # 机器人还在限行区域内，检查是否到达等待点
                        distance = math.sqrt(
                            (robot_state.pose.x - waiting_point.x) ** 2 + 
                            (robot_state.pose.y - waiting_point.y) ** 2
                        )
                        
                        if distance < 0.5:  # 到达等待点
                            # 检查限行区域是否有空位（通过检查机器人是否在通行列表中）
                            # 如果机器人在通行列表中，说明限行区域已释放，可以恢复任务
                            if traffic and robot_id in traffic['robots']:
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} reached waiting point and restricted area {area_id} "
                                    f"has capacity available, resuming task {task_id}"
                                )
                                if (robot_id, task_id) not in robots_to_resume_set:
                                    robots_to_resume.append((robot_id, task_id, task))
                                    robots_to_resume_set.add((robot_id, task_id))
                                if robot_id in waiting_status:
                                    del waiting_status[robot_id]
                            # 检查限行区域是否有空位（即使机器人不在通行列表中，也可能有空位）
                            elif traffic and len(traffic['robots']) < traffic.get('capacity', 1):
                                # 限行区域有空位，尝试重新申请通行
                                priority_value = task.priority.value
                                can_pass, _, _ = await self.restricted_area_traffic_manager.check_and_manage_traffic(
                                    robot_id, robot_state.pose, float(priority_value), task_id
                                )
                                if can_pass:
                                    logger.info(
                                        f"[RESTRICTED AREA] Robot {robot_id} reached waiting point and restricted area {area_id} "
                                        f"has capacity available, resuming task {task_id}"
                                    )
                                    if (robot_id, task_id) not in robots_to_resume_set:
                                        robots_to_resume.append((robot_id, task_id, task))
                                        robots_to_resume_set.add((robot_id, task_id))
                                    if robot_id in waiting_status:
                                        del waiting_status[robot_id]
                            elif waiting_since:
                                # 如果等待超过30秒，重新检查限行区域通行状态
                                wait_time = (datetime.now() - waiting_since).total_seconds()
                                if wait_time > 30.0:
                                    # 重新检查限行区域通行
                                    priority_value = task.priority.value
                                    can_pass, _, _ = await self.restricted_area_traffic_manager.check_and_manage_traffic(
                                        robot_id, robot_state.pose, float(priority_value), task_id
                                    )
                                    # 如果可以通过且还在限行区域内，恢复任务
                                    if can_pass and is_still_in_area:
                                        logger.info(
                                            f"[RESTRICTED AREA] Robot {robot_id} can now pass through restricted area {area_id} "
                                            f"after waiting {wait_time:.1f}s, resuming task {task_id}"
                                        )
                                        if (robot_id, task_id) not in robots_to_resume_set:
                                            robots_to_resume.append((robot_id, task_id, task))
                                            robots_to_resume_set.add((robot_id, task_id))
                                        if robot_id in waiting_status:
                                            del waiting_status[robot_id]
                                    # 如果不在限行区域内了，清除等待状态并恢复任务
                                    elif not is_still_in_area:
                                        # 重要：检查机器人是否在充电桩附近，如果是，不应该恢复任务（可能是回桩了）
                                        distance_to_origin = math.sqrt(robot_state.pose.x ** 2 + robot_state.pose.y ** 2)
                                        if distance_to_origin < 1.5 and robot_state.status.value == "idle":
                                            # 机器人在充电桩附近，可能是回桩了，不应该恢复任务
                                            logger.warning(
                                                f"[RESTRICTED AREA] Robot {robot_id} is no longer in restricted area {area_id} "
                                                f"after waiting {wait_time:.1f}s and is at charging dock "
                                                f"(distance={distance_to_origin:.2f}m, status=idle). "
                                                f"Task {task_id} may have been interrupted. Clearing waiting status but NOT resuming task."
                                            )
                                            if robot_id in waiting_status:
                                                del waiting_status[robot_id]
                                            if traffic and traffic['waiting_queue']:
                                                traffic['waiting_queue'] = [
                                                    (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                                    if wid != robot_id
                                                ]
                                        else:
                                            logger.info(
                                                f"[RESTRICTED AREA] Robot {robot_id} is no longer in restricted area {area_id} "
                                                f"after waiting {wait_time:.1f}s, clearing waiting status and resuming task"
                                            )
                                            # 恢复任务，因为机器人已经不在限行区域内了，应该继续执行任务
                                            if (robot_id, task_id) not in robots_to_resume_set:
                                                robots_to_resume.append((robot_id, task_id, task))
                                                robots_to_resume_set.add((robot_id, task_id))
                                            if robot_id in waiting_status:
                                                del waiting_status[robot_id]
                                            if traffic and traffic['waiting_queue']:
                                                traffic['waiting_queue'] = [
                                                    (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                                    if wid != robot_id
                                                ]
                            # 如果限行区域还没有释放，机器人继续等待
                            else:
                                logger.debug(
                                    f"[RESTRICTED AREA] Robot {robot_id} reached waiting point but restricted area {area_id} "
                                    f"is still occupied, waiting for capacity to be available"
                                )
            except Exception as e:
                logger.debug(f"Failed to check waiting robot {robot_id}: {e}")
        
        # 恢复任务执行
        for robot_id, task_id, task in robots_to_resume:
            try:
                # 确保任务状态是 EXECUTING（如果任务被暂停或处于其他状态，恢复为 EXECUTING）
                if task.status not in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED]:
                    logger.info(
                        f"[RESTRICTED AREA] Resuming task {task_id} for robot {robot_id} "
                        f"from status {task.status.value} to EXECUTING"
                    )
                    task.status = TaskStatus.EXECUTING
                
                agent = self.robot_manager.get_robot_agent(robot_id)
                if not agent:
                    logger.warning(f"Failed to get robot agent for robot {robot_id} to resume task {task_id}")
                    continue
                
                # 清除 action_id，准备重新执行
                task.action_id = None
                
                # 恢复任务执行
                if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
                    # 多动作任务：继续执行当前动作（从当前索引开始）
                    current_action_item = task.actions[task.current_action_index]
                    logger.info(
                        f"[RESTRICTED AREA] Resuming multi-action task {task_id} for robot {robot_id}, "
                        f"continuing from action {task.current_action_index + 1}/{len(task.actions)} "
                        f"(type={current_action_item.action_type})"
                    )
                    
                    # 重要：检查当前动作是否应该是GO_HOME
                    # 如果当前动作不是GO_HOME，但机器人已经在充电桩附近，说明任务可能被错误地跳过了
                    if current_action_item.action_type != ActionType.GO_HOME:
                        try:
                            robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=True)
                            if robot_state and robot_state.pose:
                                distance_to_origin = math.sqrt(robot_state.pose.x ** 2 + robot_state.pose.y ** 2)
                                if distance_to_origin < 1.5 and robot_state.status.value == "idle":
                                    logger.warning(
                                        f"[RESTRICTED AREA] Robot {robot_id} is at charging dock but current action "
                                        f"({task.current_action_index + 1}/{len(task.actions)}) is not GO_HOME. "
                                        f"Task {task_id} may have been incorrectly advanced. "
                                        f"Current action type: {current_action_item.action_type}. "
                                        f"Will still resume task to continue from current action."
                                    )
                        except Exception as e:
                            logger.debug(f"Failed to check robot state when resuming task {task_id}: {e}")
                    
                    await self._execute_next_action(task, agent, robot_id)
                else:
                    # 普通任务：重新发送move_to指令到目标点
                    if task.target_pose:
                        acceptable_precision = getattr(task, 'acceptable_precision', 0.3)
                        speed_ratio = getattr(task, 'speed_ratio', 1.0)
                        
                        move_result = await agent.move_to(
                            target=task.target_pose,
                            mode=0,
                            acceptable_precision=acceptable_precision,
                            speed_ratio=speed_ratio
                        )
                        task.action_id = move_result.action_id if move_result else None
                        if task.started_at is None:
                            task.started_at = datetime.now()
                        self._save_tasks_to_file()
                        logger.info(
                            f"[RESTRICTED AREA] Resumed task {task_id} for robot {robot_id}, "
                            f"action_id={task.action_id}, target=({task.target_pose.x:.2f}, {task.target_pose.y:.2f})"
                        )
                    else:
                        logger.warning(
                            f"[RESTRICTED AREA] Cannot resume task {task_id} for robot {robot_id}: "
                            f"no target_pose"
                        )
            except Exception as e:
                logger.error(
                    f"[RESTRICTED AREA] Failed to resume task {task_id} for robot {robot_id}: {e}",
                    exc_info=True
                )
    
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
                    from app.services.deadlock_detector import deadlock_logger
                    deadlock_logger.info(
                        f"[UNLOCK VERIFY] Resuming task {task.task_id} for robot {robot_id}, "
                        f"target=({task.target_pose.x:.2f}, {task.target_pose.y:.2f})"
                    )
                    logger.info(f"Resuming task {task.task_id} for robot {robot_id}, resending move_to command")
                    move_result = await agent.move_to(
                        task.target_pose,
                        mode=0,
                        acceptable_precision=0.3,
                        speed_ratio=1.0
                    )
                    task.action_id = move_result.action_id
                    task.status = TaskStatus.EXECUTING
                    task.robot_id = robot_id  # 确保机器人ID已设置
                    if task.started_at is None:
                        task.started_at = datetime.now()
                    if task.assigned_at is None:
                        task.assigned_at = datetime.now()
                    # 持久化任务状态
                    self._save_tasks_to_file()
                    deadlock_logger.info(
                        f"[UNLOCK VERIFY] Task {task.task_id} resumed successfully, "
                        f"new action_id={task.action_id}, status=EXECUTING, robot_id={robot_id}"
                    )
                    logger.info(f"Task {task.task_id} resumed, new action_id={task.action_id}, robot_id={robot_id}")
                else:
                    logger.warning(f"Task {task.task_id} has no target_pose, cannot resume")
        except Exception as e:
            logger.error(f"Failed to resume task {task.task_id} for robot {robot_id}: {e}", exc_info=True)
    
    async def _update_executing_tasks(self):
        """更新执行中的任务状态"""
        # 首先检查是否有机器人已完成死锁解除避让，需要恢复任务
        await self._check_and_resume_deadlock_resolution_tasks()
        
        # 限行区域监测：实时监测机器人位置，判断是否离开限行区域
        try:
            await self.restricted_area_traffic_manager.monitor_robots()
            # 检查等待队列，让可以通行的机器人继续执行任务
            # 注意：check_waiting_robots 内部会调用 _check_and_resume_waiting_robots
            # 但为了确保及时恢复，这里也调用一次
            await self.restricted_area_traffic_manager.check_waiting_robots()
        except Exception as e:
            logger.debug(f"Failed to monitor restricted areas: {e}")
        
        # 检查等待中的机器人是否可以恢复任务
        # 优化：即使 check_waiting_robots 已调用，这里也再次检查，确保没有遗漏
        await self._check_and_resume_waiting_robots()
        
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
            # 【修复】为每个任务的更新添加5秒超时保护，防止单个任务阻塞整个更新循环
            try:
                await asyncio.wait_for(
                    self._process_single_task_update(task),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Task {task.task_id[:8]} update timed out after 5s, will retry in next cycle")
            except Exception as e:
                logger.error(f"Failed to update task {task.task_id[:8]}: {e}", exc_info=True)

    async def _handle_multi_action_completion(self, task: Task, agent, robot_id: str, completed_action_idx: int):
        """
        处理多动作任务的单个动作完成，切换到下一个动作
        
        Args:
            task: 任务对象
            agent: 机器人代理
            robot_id: 机器人ID
            completed_action_idx: 刚完成的动作索引（在递增之前）
        """
        logger.info(
            f"[MULTI-ACTION] Task {task.task_id} action {completed_action_idx + 1}/{len(task.actions)} completed. "
            f"Current index: {task.current_action_index}, Total actions: {len(task.actions)}"
        )
        
        # 清除当前action_id并保存状态
        task.action_id = None
        self._save_tasks_to_file()
        
        # 递增索引
        task.current_action_index += 1
        
        if task.current_action_index < len(task.actions):
            # 还有下一个动作，执行它
            logger.info(
                f"[MULTI-ACTION] Task {task.task_id} moving to next action: "
                f"{task.current_action_index + 1}/{len(task.actions)}"
            )
            await self._execute_next_action(task, agent, robot_id)
        else:
            # 所有动作完成
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            # 释放限行区域占用
            await self._release_robot_from_restricted_area_on_completion(task)
            if task.task_id in self.task_paths:
                del self.task_paths[task.task_id]
            self._save_tasks_to_file()
            logger.info(
                f"[MULTI-ACTION] Task {task.task_id} completed all {len(task.actions)} actions successfully"
            )
    
    async def _check_action_completion_by_position(self, task: Task, agent, robot_id: str) -> bool:
        """
        通过检查机器人位置来判断动作是否完成（用于status=1但可能已到达目标的情况）
        
        Returns:
            True if action is completed, False otherwise
        """
        if not task.is_multi_action or not task.actions:
            return False
        
        if task.current_action_index >= len(task.actions):
            return False
        
        current_action_item = task.actions[task.current_action_index]
        
        # 对MOVE_TO和GO_HOME动作检查位置
        if current_action_item.action_type == ActionType.GO_HOME:
            # 对于GO_HOME动作，检查机器人是否在充电桩
            try:
                robot_state = await self.robot_manager.get_robot_state(robot_id)
                if not robot_state or not robot_state.pose:
                    return False
                
                # 获取充电桩位置
                try:
                    dock_pose = await agent.get_home_dock_pose()
                    if dock_pose:
                        target = dock_pose
                    else:
                        # 如果没有获取到充电桩位置，使用原点作为默认值
                        target = Pose(x=0.0, y=0.0, yaw=0.0)
                except Exception as e:
                    logger.debug(f"Failed to get dock pose for robot {robot_id}: {e}")
                    # 使用原点作为默认值
                    target = Pose(x=0.0, y=0.0, yaw=0.0)
                
                current = robot_state.pose
                distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
                acceptable_precision = 1.5  # GO_HOME动作的精度阈值
                
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} GO_HOME action position check: "
                    f"current=({current.x:.2f}, {current.y:.2f}), dock=({target.x:.2f}, {target.y:.2f}), "
                    f"distance={distance:.2f}m, acceptable_precision={acceptable_precision}m, "
                    f"status={robot_state.status.value}, current_action_id={robot_state.current_action_id}"
                )
                
                # GO_HOME动作必须真正到达充电桩才能完成
                # 要求：1) 机器人状态为idle且没有current_action_id 2) 距离充电桩在可接受范围内（1.5米）
                if robot_state.status.value == "idle" and not robot_state.current_action_id:
                    # 只有距离在可接受范围内（1.5米），才认为完成
                    if distance <= acceptable_precision:
                        logger.info(
                            f"[MULTI-ACTION] Task {task.task_id} GO_HOME action completed: "
                            f"robot at charging dock (distance={distance:.2f}m <= {acceptable_precision}m, status=idle, no action_id)"
                        )
                        return True
                    else:
                        # 机器人状态是idle但没有到达充电桩，可能是回桩失败或中断
                        logger.warning(
                            f"[MULTI-ACTION] Task {task.task_id} GO_HOME action: robot is idle with no action_id, "
                            f"but distance={distance:.2f}m > {acceptable_precision}m from dock. "
                            f"Robot may not have reached charging dock. Action still in progress."
                        )
                        return False
                else:
                    logger.debug(
                        f"[MULTI-ACTION] Task {task.task_id} GO_HOME action still in progress: "
                        f"distance={distance:.2f}m, status={robot_state.status.value}, "
                        f"current_action_id={robot_state.current_action_id}"
                    )
                    return False
            except Exception as e:
                logger.warning(f"[MULTI-ACTION] Failed to check GO_HOME position for task {task.task_id}: {e}")
                return False
        
        # 只对MOVE_TO动作检查位置
        if current_action_item.action_type != ActionType.MOVE_TO:
            return False
        
        try:
            robot_state = await self.robot_manager.get_robot_state(robot_id)
            if not robot_state or not robot_state.pose:
                logger.warning(
                    f"[MULTI-ACTION] Task {task.task_id} cannot check position: robot_state or pose is None"
                )
                return False
            
            # 获取当前动作的目标位置
            target = None
            if current_action_item.target_pose:
                target = current_action_item.target_pose
                logger.debug(
                    f"[MULTI-ACTION] Task {task.task_id} using target_pose: ({target.x}, {target.y})"
                )
            elif current_action_item.poi_name:
                logger.debug(
                    f"[MULTI-ACTION] Task {task.task_id} resolving POI: {current_action_item.poi_name}"
                )
                try:
                    pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                    for poi in pois:
                        if poi.id == current_action_item.poi_name or (poi.metadata and poi.metadata.get("display_name") == current_action_item.poi_name):
                            if poi.pose:
                                target = poi.pose
                                logger.debug(
                                    f"[MULTI-ACTION] Task {task.task_id} resolved POI to pose: ({target.x}, {target.y})"
                                )
                                break
                except Exception as e:
                    logger.warning(
                        f"[MULTI-ACTION] Task {task.task_id} failed to resolve POI {current_action_item.poi_name}: {e}"
                    )
            
            if not target:
                logger.warning(
                    f"[MULTI-ACTION] Task {task.task_id} cannot determine target position for action {task.current_action_index + 1}"
                )
                return False
            
            # 计算距离
            current = robot_state.pose
            distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
            acceptable_precision = current_action_item.acceptable_precision or 0.3
            
            logger.info(
                f"[MULTI-ACTION] Task {task.task_id} action {task.current_action_index + 1}/{len(task.actions)} "
                f"position check: current=({current.x:.2f}, {current.y:.2f}), target=({target.x:.2f}, {target.y:.2f}), "
                f"distance={distance:.2f}m, acceptable_precision={acceptable_precision}m"
            )
            
            # 如果已到达目标，认为动作完成
            if distance <= acceptable_precision:
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} action {task.current_action_index + 1}/{len(task.actions)} "
                    f"(action_id={task.action_id}) reached target (distance={distance:.2f}m <= {acceptable_precision}m). "
                    f"Status=1 but position indicates completion."
                )
                return True
            else:
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} action {task.current_action_index + 1}/{len(task.actions)} "
                    f"still moving (distance={distance:.2f}m > {acceptable_precision}m)"
                )
                return False
        except Exception as e:
            logger.error(
                f"[MULTI-ACTION] Failed to check robot position for task {task.task_id}: {e}",
                exc_info=True
            )
            return False

    async def _handle_action_status_none(self, task, agent, action_state):
        """
        处理action状态为None的情况（action可能已完成或被清除）
        重点关注多动作任务的完成判断和死锁检测
        """
        logger.warning(
            f"Task {task.task_id} action_id={task.action_id} status is None. "
            f"Action may have been completed or cleared. Checking robot current action..."
        )
        try:
            current_action = await agent.get_current_action()
            if current_action is None or current_action.action_id != task.action_id:
                # 机器人当前没有执行这个action，可能已经完成
                robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                if robot_state:
                    # 对于多动作任务，检查当前动作类型
                    if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
                        current_action_item = task.actions[task.current_action_index]
                        
                        # 如果是WAIT动作，不应该检查机器人状态（WAIT动作由后台任务处理）
                        if current_action_item.action_type == ActionType.WAIT:
                            logger.debug(
                                f"Task {task.task_id} is in WAIT action (action_index={task.current_action_index}), "
                                f"robot idle status is normal, waiting for WAIT to complete"
                            )
                            return False  # 继续等待WAIT完成
                        
                        # 如果是GO_HOME动作，检查机器人是否在充电桩
                        if current_action_item.action_type == ActionType.GO_HOME:
                            if robot_state.status == "idle" and not robot_state.current_action_id:
                                logger.info(
                                    f"Task {task.task_id} GO_HOME action: robot {task.robot_id} appears to be at charging dock "
                                    f"(status=idle, no current_action_id)"
                                )
                                await self._handle_multi_action_completion(task, agent, task.robot_id, task.current_action_index)
                                return True
                            else:
                                logger.debug(
                                    f"Task {task.task_id} GO_HOME action: robot {task.robot_id} status={robot_state.status}, "
                                    f"current_action_id={robot_state.current_action_id}, still in progress"
                                )
                                return False  # 继续等待
                        
                        # 对于MOVE_TO动作，通过检查机器人位置来判断是否到达目标
                        elif current_action_item.action_type == ActionType.MOVE_TO:
                            if current_action_item.target_pose:
                                target = current_action_item.target_pose
                            elif current_action_item.poi_name:
                                # POI导航：尝试获取POI位置
                                try:
                                    pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                                    for poi in pois:
                                        if poi.id == current_action_item.poi_name or (poi.metadata and poi.metadata.get("display_name") == current_action_item.poi_name):
                                            if poi.pose:
                                                target = poi.pose
                                                break
                                    else:
                                        target = task.target_pose
                                except:
                                    target = task.target_pose
                            else:
                                target = task.target_pose
                        else:
                            target = task.target_pose
                        
                        current = robot_state.pose
                        distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
                        logger.info(
                            f"Task {task.task_id}: action status is None, "
                            f"distance to target: {distance:.2f}m"
                        )
                        
                        execution_time = 0.0
                        if task.started_at:
                            execution_time = (datetime.now() - task.started_at).total_seconds()
                        
                        acceptable_precision = 0.3
                        if distance <= acceptable_precision:
                            # 多动作任务：使用统一的方法处理动作完成
                            completed_action_idx = task.current_action_index
                            logger.info(
                                f"[MULTI-ACTION] Task {task.task_id} action {completed_action_idx + 1}/{len(task.actions)} "
                                f"completed (status=None, distance={distance:.2f}m <= {acceptable_precision}m)"
                            )
                            await self._handle_multi_action_completion(task, agent, task.robot_id, completed_action_idx)
                            return True
                        elif execution_time > 15.0:
                            # 如果执行时间超过15秒且未到达目标，可能是死锁，触发死锁检测
                            logger.warning(
                                f"Task {task.task_id} action status is None, robot not at target "
                                f"(distance={distance:.2f}m, execution_time={execution_time:.1f}s). "
                                f"Robot may be blocked. Triggering deadlock detection..."
                            )
                            await self._recover_task_with_invalid_action_id(task, agent, task.robot_id)
                            return False
                    else:
                        # 普通任务：检查是否到达目标
                        if robot_state.pose and task.target_pose:
                            current = robot_state.pose
                            target = task.target_pose
                            distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
                            acceptable_precision = 0.3
                            if distance <= acceptable_precision:
                                task.status = TaskStatus.COMPLETED
                                task.completed_at = datetime.now()
                                await self._release_robot_from_restricted_area_on_completion(task)
                                if task.task_id in self.task_paths:
                                    del self.task_paths[task.task_id]
                                self._save_tasks_to_file()
                                logger.info(
                                    f"Task {task.task_id} completed (distance to target: {distance:.2f}m <= {acceptable_precision}m)"
                                )
                                return True
        except Exception as e:
            logger.debug(f"Failed to check current action for task {task.task_id}: {e}")
        return False

    async def _handle_action_status_done_success(self, task, agent, action_state):
        """
        处理action状态为Done且result=0（成功）的情况
        重点关注多动作任务的完成处理
        """
        if task.is_multi_action and task.actions:
            completed_action_idx = task.current_action_index
            logger.info(
                f"[MULTI-ACTION] Task {task.task_id} action {completed_action_idx + 1}/{len(task.actions)} "
                f"(action_id={task.action_id}) completed successfully (status=4, result=0)"
            )
            await self._handle_multi_action_completion(task, agent, task.robot_id, completed_action_idx)
            return True
        else:
            # 普通任务完成
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            logger.info(f"Task {task.task_id} completed successfully")
            await self._release_robot_from_restricted_area_on_completion(task)
            if task.task_id in self.task_paths:
                del self.task_paths[task.task_id]
            self._save_tasks_to_file()
            return True

    async def _handle_action_status_done_failed(self, task, agent, action_state, reason):
        """
        处理action状态为Done且result=-1（失败）的情况
        重点关注多动作任务的失败处理和死锁检测
        """
        # 对于多动作任务，如果当前动作失败，尝试继续下一个动作（如果还有）
        if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
            current_action_item = task.actions[task.current_action_index]
            
            # 特殊处理：如果是GO_HOME动作失败且原因是DOCK_ID_NOT_FOUND，检查机器人是否已经在充电桩
            if current_action_item.action_type == ActionType.GO_HOME and "DOCK_ID_NOT_FOUND" in reason:
                try:
                    robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                    if robot_state and robot_state.pose:
                        distance_to_origin = math.sqrt(robot_state.pose.x * robot_state.pose.x + robot_state.pose.y * robot_state.pose.y)
                        if distance_to_origin < 1.0 and robot_state.status.value == "idle":
                            try:
                                current_action = await agent.get_current_action()
                                if not current_action or not current_action.action_id:
                                    # 机器人已经在充电桩，标记当前动作完成，继续下一个动作
                                    logger.info(
                                        f"Task {task.task_id} GO_HOME action failed with DOCK_ID_NOT_FOUND "
                                        f"but robot is already at charging dock (distance={distance_to_origin:.2f}m, status=idle). "
                                        f"Marking action as completed and continuing to next action."
                                    )
                                    task.current_action_index += 1
                                    if task.current_action_index < len(task.actions):
                                        task.action_id = None
                                        self._save_tasks_to_file()
                                        await self._execute_next_action(task, agent, task.robot_id)
                                        return True
                                    else:
                                        # 这是最后一个动作，标记任务为完成
                                        task.status = TaskStatus.COMPLETED
                                        task.completed_at = datetime.now()
                                        await self._release_robot_from_restricted_area_on_completion(task)
                                        if task.task_id in self.task_paths:
                                            del self.task_paths[task.task_id]
                                        self._save_tasks_to_file()
                                        logger.info(
                                            f"Task {task.task_id} (multi-action) completed: "
                                            f"GO_HOME action failed with DOCK_ID_NOT_FOUND but robot already at charging dock"
                                        )
                                        return True
                            except Exception as e:
                                logger.debug(f"Failed to get current action for robot {task.robot_id}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to check robot state for GO_HOME DOCK_ID_NOT_FOUND error: {e}")
            
            # 检查是否是因为无法到达目标而失败（可能是死锁导致）
            # 如果机器人距离目标较近，可能是被阻塞，尝试触发死锁检测和恢复
            try:
                # 首先检查机器人是否正在死锁解除中，如果是，不要标记为失败
                if task.robot_id in self.robots_in_deadlock_resolution:
                    logger.info(
                        f"Task {task.task_id} action {task.current_action_index} failed but robot {task.robot_id} is in deadlock resolution, "
                        f"will not mark as failed, waiting for resolution to complete"
                    )
                    return False  # 继续监控，不标记为失败
                
                robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                if robot_state and robot_state.pose:
                    # 获取当前动作的目标位置
                    if current_action_item.action_type == ActionType.MOVE_TO:
                        if current_action_item.target_pose:
                            target = current_action_item.target_pose
                        elif current_action_item.poi_name:
                            try:
                                pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                                for poi in pois:
                                    if poi.id == current_action_item.poi_name or (poi.metadata and poi.metadata.get("display_name") == current_action_item.poi_name):
                                        if poi.pose:
                                            target = poi.pose
                                            break
                                else:
                                    target = task.target_pose
                            except:
                                target = task.target_pose
                        else:
                            target = task.target_pose
                    else:
                        target = task.target_pose
                    
                    current = robot_state.pose
                    distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                    
                    # 如果距离目标较近（< 8米），可能是被阻塞，尝试恢复
                    if distance < 8.0:
                        execution_time = 0.0
                        if task.started_at:
                            execution_time = (datetime.now() - task.started_at).total_seconds()
                        
                        # 如果执行时间较长，可能是死锁，触发死锁检测（降低阈值到10秒）
                        if execution_time > 10.0:
                            logger.warning(
                                f"Task {task.task_id} failed but robot is close to target "
                                f"(distance={distance:.2f}m, execution_time={execution_time:.1f}s). "
                                f"May be blocked by other robots. Triggering deadlock detection and retry..."
                            )
                            # 触发死锁检测（异步，不阻塞）
                            asyncio.create_task(self._trigger_deadlock_detection_for_robot(task.robot_id))
                            
                            # 尝试重新发送move_to指令（增加重试次数到5次）
                            if task.retry_count < 5:
                                task.retry_count += 1
                                logger.info(
                                    f"Retrying task {task.task_id} (retry {task.retry_count}/5) "
                                    f"after failure, distance to target: {distance:.2f}m"
                                )
                                try:
                                    move_result = await agent.move_to(
                                        target=task.target_pose,
                                        mode=0,
                                        acceptable_precision=0.3,
                                        speed_ratio=1.0
                                    )
                                    task.action_id = move_result.action_id
                                    task.status = TaskStatus.EXECUTING
                                    self._save_tasks_to_file()
                                    logger.info(
                                        f"Task {task.task_id} retried after failure, "
                                        f"new action_id={task.action_id}, status=EXECUTING"
                                    )
                                    return False  # 继续监控，不标记为失败
                                except Exception as e:
                                    logger.error(f"Failed to retry task {task.task_id} after failure: {e}")
                    
                    # 如果距离很近（< 0.5米），认为已到达目标
                    if distance <= 0.5:
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        task.error_message = None
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                        self._save_tasks_to_file()
                        logger.info(
                            f"Task {task.task_id} action failed but robot reached target "
                            f"(distance={distance:.2f}m <= 0.5m). Marking as completed."
                        )
                        return True
            except Exception as e:
                logger.warning(f"Failed to check robot position for failed task {task.task_id}: {e}")
            
            # 如果无法恢复，对于多动作任务，尝试继续下一个动作
            logger.warning(
                f"Task {task.task_id} action {task.current_action_index} failed: {reason or 'Unknown error'}. "
                f"Attempting to continue with next action..."
            )
            task.current_action_index += 1
            if task.current_action_index < len(task.actions):
                task.action_id = None
                self._save_tasks_to_file()
                logger.info(
                    f"Task {task.task_id} continuing to next action ({task.current_action_index}/{len(task.actions)})"
                )
                await self._execute_next_action(task, agent, task.robot_id)
                return False  # 继续执行下一个动作
            else:
                # 所有动作都失败了，标记为失败
                task.status = TaskStatus.FAILED
                task.error_message = f"All actions failed. Last error: {reason or 'Unknown error'}"
                task.completed_at = datetime.now()
                if task.task_id in self.task_paths:
                    del self.task_paths[task.task_id]
                self._save_tasks_to_file()
                logger.warning(f"Task {task.task_id} (multi-action) failed: all actions failed")
                return True
        
        # 普通任务或无法继续的多动作任务：检查是否是因为无法到达目标而失败
        try:
            # 首先检查机器人是否正在死锁解除中，如果是，不要标记为失败
            if task.robot_id in self.robots_in_deadlock_resolution:
                logger.info(
                    f"Task {task.task_id} failed but robot {task.robot_id} is in deadlock resolution, "
                    f"will not mark as failed, waiting for resolution to complete"
                )
                return False  # 继续监控，不标记为失败
            
            robot_state = await self.robot_manager.get_robot_state(task.robot_id)
            if robot_state and robot_state.pose and task.target_pose:
                current = robot_state.pose
                target = task.target_pose
                distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                
                # 如果距离目标较近（< 8米），可能是被阻塞，尝试恢复
                if distance < 8.0:
                    execution_time = 0.0
                    if task.started_at:
                        execution_time = (datetime.now() - task.started_at).total_seconds()
                    
                    # 如果执行时间较长，可能是死锁，触发死锁检测（降低阈值到10秒）
                    if execution_time > 10.0:
                        logger.warning(
                            f"Task {task.task_id} failed but robot is close to target "
                            f"(distance={distance:.2f}m, execution_time={execution_time:.1f}s). "
                            f"May be blocked by other robots. Triggering deadlock detection and retry..."
                        )
                        # 触发死锁检测（异步，不阻塞）
                        asyncio.create_task(self._trigger_deadlock_detection_for_robot(task.robot_id))
                        
                        # 尝试重新发送move_to指令（增加重试次数到5次）
                        if task.retry_count < 5:
                            task.retry_count += 1
                            logger.info(
                                f"Retrying task {task.task_id} (retry {task.retry_count}/5) "
                                f"after failure, distance to target: {distance:.2f}m"
                            )
                            try:
                                move_result = await agent.move_to(
                                    target=task.target_pose,
                                    mode=0,
                                    acceptable_precision=0.3,
                                    speed_ratio=1.0
                                )
                                task.action_id = move_result.action_id
                                task.status = TaskStatus.EXECUTING
                                self._save_tasks_to_file()
                                logger.info(
                                    f"Task {task.task_id} retried after failure, "
                                    f"new action_id={task.action_id}, status=EXECUTING"
                                )
                                return False  # 继续监控，不标记为失败
                            except Exception as e:
                                logger.error(f"Failed to retry task {task.task_id} after failure: {e}")
                    
                    # 如果距离很近（< 0.5米），认为已到达目标
                    if distance <= 0.5:
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        task.error_message = None
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                        self._save_tasks_to_file()
                        logger.info(
                            f"Task {task.task_id} action failed but robot reached target "
                            f"(distance={distance:.2f}m <= 0.5m). Marking as completed."
                        )
                        return True
        except Exception as e:
            logger.warning(f"Failed to check robot position for failed task {task.task_id}: {e}")
        
        # 如果无法恢复，标记为失败
        task.status = TaskStatus.FAILED
        task.error_message = reason or "Unknown error"
        task.completed_at = datetime.now()
        if task.task_id in self.task_paths:
            del self.task_paths[task.task_id]
        self._save_tasks_to_file()
        logger.warning(f"Task {task.task_id} failed: {task.error_message}")
        return True

    async def _handle_action_status_done_aborted(self, task, agent, action_state):
        """
        处理action状态为Done且result=-2（中止）的情况
        重点关注多动作任务的中止处理和限行区域等待逻辑
        """
        robot_id = task.robot_id
        if robot_id and self.restricted_area_traffic_manager:
            waiting_status = self.restricted_area_traffic_manager.robot_waiting_status.get(robot_id)
            if waiting_status:
                # 机器人正在限行区域等待，这是正常的等待行为，不要取消任务
                if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
                    current_action_item = task.actions[task.current_action_index]
                    if current_action_item.action_type == ActionType.GO_HOME:
                        # 检查机器人是否已经在充电桩
                        try:
                            robot_state = await self.robot_manager.get_robot_state(robot_id)
                            if robot_state and robot_state.pose:
                                distance_to_origin = math.sqrt(robot_state.pose.x * robot_state.pose.x + robot_state.pose.y * robot_state.pose.y)
                                if distance_to_origin < 1.0 and robot_state.status.value == "idle":
                                    try:
                                        current_action = await agent.get_current_action()
                                        if not current_action or not current_action.action_id:
                                            # 机器人已经回桩，标记任务为完成
                                            task.status = TaskStatus.COMPLETED
                                            task.completed_at = datetime.now()
                                            await self._release_robot_from_restricted_area_on_completion(task)
                                            if task.task_id in self.task_paths:
                                                del self.task_paths[task.task_id]
                                            if robot_id in self.restricted_area_traffic_manager.robot_waiting_status:
                                                del self.restricted_area_traffic_manager.robot_waiting_status[robot_id]
                                            self._save_tasks_to_file()
                                            logger.info(
                                                f"Task {task.task_id} (multi-action) completed: "
                                                f"GO_HOME action aborted but robot already at charging dock "
                                                f"(distance={distance_to_origin:.2f}m, status=idle)"
                                            )
                                            return True
                                    except Exception as e:
                                        logger.debug(f"Failed to get current action for robot {robot_id}: {e}")
                        except Exception as e:
                            logger.debug(f"Failed to check robot state for GO_HOME in restricted area: {e}")
                    
                    # 机器人正在限行区域等待，这是正常的等待行为，不要取消任务
                    logger.info(
                        f"Task {task.task_id} action aborted but robot {robot_id} is waiting at restricted area "
                        f"(area_id={waiting_status.get('area_id')}). Task will resume when area is released."
                    )
                    task.action_id = None
                    self._save_tasks_to_file()
                    return False  # 继续等待，不标记为完成
        
        # 对于多动作任务，如果当前动作中止，尝试继续下一个动作
        if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
            current_action_item = task.actions[task.current_action_index]
            try:
                robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                if robot_state and robot_state.pose:
                    # 获取当前动作的目标位置
                    if current_action_item.action_type == ActionType.MOVE_TO:
                        if current_action_item.target_pose:
                            target = current_action_item.target_pose
                        elif current_action_item.poi_name:
                            try:
                                pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                                for poi in pois:
                                    if poi.id == current_action_item.poi_name or (poi.metadata and poi.metadata.get("display_name") == current_action_item.poi_name):
                                        if poi.pose:
                                            target = poi.pose
                                            break
                                else:
                                    target = task.target_pose
                            except:
                                target = task.target_pose
                        else:
                            target = task.target_pose
                    else:
                        target = task.target_pose
                    
                    current = robot_state.pose
                    distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                    acceptable_precision = 0.3
                    
                    if distance <= acceptable_precision:
                        # 机器人已经到达目标，继续下一个动作
                        logger.info(
                            f"Task {task.task_id} action {task.current_action_index + 1} aborted but robot reached target "
                            f"(distance={distance:.2f}m <= {acceptable_precision}m). Continuing to next action."
                        )
                        task.current_action_index += 1
                        if task.current_action_index < len(task.actions):
                            task.action_id = None
                            self._save_tasks_to_file()
                            await self._execute_next_action(task, agent, task.robot_id)
                            return False
                        else:
                            # 所有动作完成
                            task.status = TaskStatus.COMPLETED
                            task.completed_at = datetime.now()
                            await self._release_robot_from_restricted_area_on_completion(task)
                            if task.task_id in self.task_paths:
                                del self.task_paths[task.task_id]
                            self._save_tasks_to_file()
                            logger.info(f"Task {task.task_id} (multi-action) completed all actions")
                            return True
                    else:
                        # 机器人没有到达目标，应该重试当前动作，而不是跳到下一个动作
                        logger.warning(
                            f"Task {task.task_id} action {task.current_action_index + 1} aborted and robot did not reach target "
                            f"(distance={distance:.2f}m > {acceptable_precision}m). Retrying current action."
                        )
                        task.action_id = None
                        self._save_tasks_to_file()
                        # 重试当前动作，而不是跳到下一个动作
                        await self._execute_next_action(task, agent, task.robot_id)
                        return False
            except Exception as e:
                logger.warning(f"Failed to check robot position for aborted task {task.task_id}: {e}")
            
            # 如果无法判断是否到达目标，检查机器人是否在等待点
            # 如果在等待点，应该等待完成后重试当前动作，而不是跳到下一个动作
            if robot_id and self.restricted_area_traffic_manager:
                waiting_status = self.restricted_area_traffic_manager.robot_waiting_status.get(robot_id)
                if waiting_status:
                    # 机器人在等待点，等待完成后应该重试当前动作
                    logger.info(
                        f"Task {task.task_id} action {task.current_action_index + 1} aborted but robot {robot_id} "
                        f"is at waiting point. Will retry current action after waiting."
                    )
                    task.action_id = None
                    self._save_tasks_to_file()
                    return False  # 继续等待，等待完成后会重试当前动作
            
            # 如果机器人不在等待点且无法判断是否到达目标，应该重试当前动作
            # 而不是跳到下一个动作（因为动作没有完成）
            logger.warning(
                f"Task {task.task_id} action {task.current_action_index + 1} aborted and robot did not reach target. "
                f"Retrying current action instead of skipping to next."
            )
            task.action_id = None
            self._save_tasks_to_file()
            # 重试当前动作，而不是跳到下一个动作
            await self._execute_next_action(task, agent, task.robot_id)
            return False
        
        # 如果不是多动作任务，处理单动作任务的中止
        else:
                # 这是最后一个动作，检查是否是GO_HOME动作且机器人已经回桩
                if task.actions and task.current_action_index < len(task.actions):
                    last_action = task.actions[task.current_action_index]
                    if last_action and last_action.action_type == ActionType.GO_HOME:
                        try:
                            robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                            if robot_state and robot_state.status.value == "idle":
                                try:
                                    current_action = await agent.get_current_action()
                                    if not current_action or not current_action.action_id:
                                        task.status = TaskStatus.COMPLETED
                                        task.completed_at = datetime.now()
                                        await self._release_robot_from_restricted_area_on_completion(task)
                                        if task.task_id in self.task_paths:
                                            del self.task_paths[task.task_id]
                                        self._save_tasks_to_file()
                                        logger.info(
                                            f"Task {task.task_id} (multi-action) completed: "
                                            f"last action (GO_HOME) aborted but robot already at charging dock"
                                        )
                                        return True
                                except Exception as e:
                                    logger.debug(f"Failed to get current action for robot {task.robot_id}: {e}")
                        except Exception as e:
                            logger.warning(f"Failed to check robot state for aborted GO_HOME action: {e}")
                
                # 检查是否是因为限行区域等待（再次检查，以防之前没有检测到）
                if robot_id and self.restricted_area_traffic_manager:
                    waiting_status = self.restricted_area_traffic_manager.robot_waiting_status.get(robot_id)
                    if waiting_status:
                        logger.info(
                            f"Task {task.task_id} all actions aborted but robot {robot_id} is waiting at restricted area. "
                            f"Task will resume when area is released. NOT cancelling task."
                        )
                        task.action_id = None
                        self._save_tasks_to_file()
                        return False
                
                # 所有动作都中止了，且不是限行区域等待
                task.status = TaskStatus.FAILED
                task.error_message = "All actions aborted (not waiting at restricted area)"
                task.completed_at = datetime.now()
                if task.task_id in self.task_paths:
                    del self.task_paths[task.task_id]
                self._save_tasks_to_file()
                logger.warning(
                    f"Task {task.task_id} (multi-action) failed: all actions aborted (not waiting at restricted area). "
                    f"Task marked as FAILED, NOT cancelled. Robot will NOT automatically return to dock."
                )
                return True
        
        # 普通任务或无法继续的多动作任务：检查是否已经到达目标
        try:
            robot_state = await self.robot_manager.get_robot_state(task.robot_id)
            if robot_state and robot_state.pose and task.target_pose:
                current = robot_state.pose
                target = task.target_pose
                distance = math.sqrt((current.x - target.x) ** 2 + (current.y - target.y) ** 2)
                acceptable_precision = 0.3
                
                if distance <= acceptable_precision:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    await self._release_robot_from_restricted_area_on_completion(task)
                    if task.task_id in self.task_paths:
                        del self.task_paths[task.task_id]
                    self._save_tasks_to_file()
                    logger.info(
                        f"Task {task.task_id} action aborted but robot reached target "
                        f"(distance={distance:.2f}m <= {acceptable_precision}m). Marking as completed."
                    )
                    return True
                else:
                    # 机器人未到达目标，检查是否被阻塞（死锁）
                    if task.robot_id in self.robots_in_deadlock_resolution:
                        logger.info(
                            f"Task {task.task_id} aborted but robot {task.robot_id} is in deadlock resolution, "
                            f"will not cancel task, waiting for resolution to complete"
                        )
                        return False
                    
                    execution_time = 0.0
                    if task.started_at:
                        execution_time = (datetime.now() - task.started_at).total_seconds()
                    
                    if distance < 8.0 and execution_time > 10.0:
                        logger.warning(
                            f"Task {task.task_id} aborted but robot is close to target "
                            f"(distance={distance:.2f}m, execution_time={execution_time:.1f}s). "
                            f"May be blocked by other robots. Triggering deadlock detection and retry..."
                        )
                        asyncio.create_task(self._trigger_deadlock_detection_for_robot(task.robot_id))
                        
                        if task.retry_count < 5:
                            task.retry_count += 1
                            logger.info(
                                f"Retrying task {task.task_id} (retry {task.retry_count}/5) "
                                f"after abort, distance to target: {distance:.2f}m"
                            )
                            try:
                                move_result = await agent.move_to(
                                    target=task.target_pose,
                                    mode=0,
                                    acceptable_precision=0.3,
                                    speed_ratio=1.0
                                )
                                task.action_id = move_result.action_id
                                task.status = TaskStatus.EXECUTING
                                self._save_tasks_to_file()
                                logger.info(
                                    f"Task {task.task_id} retried after abort, "
                                    f"new action_id={task.action_id}, status=EXECUTING"
                                )
                                return False
                            except Exception as e:
                                logger.error(f"Failed to retry task {task.task_id} after abort: {e}")
                    
                    # 如果无法恢复，标记为取消
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = datetime.now()
                        if task.task_id in self.task_paths:
                            del self.task_paths[task.task_id]
                    self._save_tasks_to_file()
                    logger.info(
                        f"Task {task.task_id} aborted and robot not at target "
                        f"(distance={distance:.2f}m > {acceptable_precision}m)"
                    )
                    return True
            else:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                if task.task_id in self.task_paths:
                    del self.task_paths[task.task_id]
                self._save_tasks_to_file()
                logger.info(f"Task {task.task_id} aborted (robot state unavailable)")
                return True
        except Exception as e:
            logger.warning(f"Failed to check robot position for aborted task {task.task_id}: {e}")
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            if task.task_id in self.task_paths:
                del self.task_paths[task.task_id]
            self._save_tasks_to_file()
            logger.info(f"Task {task.task_id} aborted (check failed)")
            return True

    async def _handle_action_status_working(self, task, agent, action_state):
        """
        处理action状态为Working（status=1）的情况
        重点关注多动作任务的位置检查
        """
        if task.is_multi_action and task.actions:
            logger.info(
                f"[MULTI-ACTION] Task {task.task_id} status=1 (Working), checking position for action "
                f"{task.current_action_index + 1}/{len(task.actions)} (action_id={task.action_id})"
            )
            is_completed = await self._check_action_completion_by_position(task, agent, task.robot_id)
            if is_completed:
                completed_action_idx = task.current_action_index
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} position check indicates action {completed_action_idx + 1} completed, "
                    f"switching to next action"
                )
                await self._handle_multi_action_completion(task, agent, task.robot_id, completed_action_idx)
                return True
            else:
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} action {task.current_action_index + 1}/{len(task.actions)} "
                    f"still in progress (status=1, position check indicates not at target)"
                )
        logger.debug(f"Task {task.task_id} is still working (status=1)")
        return False

    async def _process_single_task_update(self, task):
        """处理单个任务的状态更新（内部辅助方法）"""
        try:
            agent = self.robot_manager.get_robot_agent(task.robot_id)
            if not agent:
                logger.warning(f"Robot agent not found for task {task.task_id}, robot_id={task.robot_id}")
                return
                
            # 如果是多动作任务且当前是等待动作，不需要查询action状态（等待动作没有action_id）
            if task.is_multi_action and task.actions:
                if task.current_action_index < len(task.actions):
                    current_action = task.actions[task.current_action_index]
                    if current_action and current_action.action_type == ActionType.WAIT:
                        # 等待动作由后台任务处理，这里不需要更新状态
                        # 但需要确保任务状态正确，防止被其他逻辑误判
                        if task.status != TaskStatus.EXECUTING:
                            task.status = TaskStatus.EXECUTING
                            self._save_tasks_to_file()
                        
                        # 重要：WAIT动作期间，不允许其他逻辑修改current_action_index
                        # 检查是否有其他逻辑错误地修改了索引
                        if task.current_action_index >= len(task.actions):
                            logger.warning(
                                f"[MULTI-ACTION] Task {task.task_id} WAIT action: current_action_index "
                                f"({task.current_action_index}) >= actions length ({len(task.actions)}). "
                                f"This should not happen during WAIT."
                            )
                        
                        logger.debug(
                            f"[MULTI-ACTION] Task {task.task_id} is in WAIT action "
                            f"(action_index={task.current_action_index}), skipping status update"
                        )
                        return
                    # 对于GO_HOME动作，如果没有action_id，尝试从机器人获取当前action
                    elif current_action and current_action.action_type == ActionType.GO_HOME:
                        if not task.action_id:
                            try:
                                current_action_state = await agent.get_current_action()
                                if current_action_state and current_action_state.action_id:
                                    task.action_id = current_action_state.action_id
                                    logger.info(f"Task {task.task_id} GO_HOME action assigned action_id: {current_action_state.action_id}")
                                    self._save_tasks_to_file()
                            except Exception as e:
                                logger.debug(f"Failed to get current action for GO_HOME task {task.task_id}: {e}")
                                # 如果无法获取action_id，检查机器人是否已经在充电桩附近
                                try:
                                    robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                                    if robot_state and robot_state.pose:
                                        # 检查机器人是否在充电桩附近（通常充电桩在原点附近，或者可以通过机器人状态判断）
                                        # 如果机器人状态显示idle且没有current_action_id，可能已经回桩完成
                                        if robot_state.status == "idle" and not robot_state.current_action_id:
                                            logger.info(f"Task {task.task_id} GO_HOME action: robot {task.robot_id} appears to be at charging dock (idle, no action_id)")
                                            # 标记GO_HOME动作完成
                                            await self._handle_multi_action_completion(task, agent, task.robot_id, task.current_action_index)
                                            return
                                except Exception as e2:
                                    logger.debug(f"Failed to check robot state for GO_HOME task {task.task_id}: {e2}")
                
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
                    return
            
            # 如果有action_id，查询action状态
            if not task.action_id:
                return
            
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
                    return
                elif e.response.status_code == 400:
                    # action_id无效（400），可能是action已被清除或无效
                    logger.warning(
                        f"Task {task.task_id} action_id={task.action_id} returned 400 (Invalid Action Id). "
                        f"Action may have been cleared. Attempting to recover..."
                    )
                    # 尝试恢复任务：检查机器人位置或重新发送指令
                    await self._recover_task_with_invalid_action_id(task, agent, task.robot_id)
                    return
                else:
                    # 其他HTTP错误，记录并返回
                    logger.error(f"Failed to get action status for task {task.task_id}: {e}")
                    return
            except Exception as e:
                logger.error(f"Failed to get action status for task {task.task_id}: {e}", exc_info=True)
                return
            
            # 检查状态 - 优先使用state字典中的值，如果不存在则使用直接属性
            # 注意：API返回的state字典中，status和result可能是整数或字符串
            status = None
            if action_state.state:
                status = action_state.state.get("status")
                # 如果status是字符串，尝试转换为整数
                if isinstance(status, str):
                    try:
                        status = int(status)
                    except (ValueError, TypeError):
                        pass
            
            if status is None:
                status = action_state.status
            # 如果status是字符串，尝试转换为整数
            if isinstance(status, str):
                try:
                    status = int(status)
                except (ValueError, TypeError):
                    pass
            
            result = None
            if action_state.state:
                result = action_state.state.get("result")
                # 如果result是字符串，尝试转换为整数
                if isinstance(result, str):
                    try:
                        result = int(result)
                    except (ValueError, TypeError):
                        pass
            
            if result is None:
                result = action_state.result
            # 如果result是字符串，尝试转换为整数
            if isinstance(result, str):
                try:
                    result = int(result)
                except (ValueError, TypeError):
                    pass
            
            # 对于多动作任务，使用INFO级别记录状态，便于调试
            log_level = logger.info if task.is_multi_action else logger.debug
            log_level(
                f"Task {task.task_id} (action_id={task.action_id}, "
                f"multi_action={task.is_multi_action}, current_idx={task.current_action_index if task.is_multi_action else 'N/A'}): "
                f"status={status} (type={type(status).__name__}), result={result} (type={type(result).__name__}), "
                f"state_dict={action_state.state}, action_state.status={action_state.status}, action_state.result={action_state.result}"
            )
            
            # 确保status和result是整数类型（用于比较）
            if status is not None and not isinstance(status, int):
                try:
                    status = int(status)
                except (ValueError, TypeError):
                    logger.warning(f"Task {task.task_id} action_id={task.action_id} status is not an integer: {status}")
            
            if result is not None and not isinstance(result, int):
                try:
                    result = int(result)
                except (ValueError, TypeError):
                    logger.warning(f"Task {task.task_id} action_id={task.action_id} result is not an integer: {result}")
            
            # 对于GO_HOME动作，即使status=1（Working），也要检查机器人是否已经在充电桩
            # 因为GO_HOME动作可能已经完成，但action状态还没有更新
            if task.is_multi_action and task.actions and task.current_action_index < len(task.actions):
                current_action_item = task.actions[task.current_action_index]
                if current_action_item.action_type == ActionType.GO_HOME:
                    # 检查机器人是否已经在充电桩
                    try:
                        robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                        if robot_state and robot_state.pose:
                            # 获取实际的充电桩坐标
                            dock_pose = None
                            try:
                                dock_pose = await agent.get_home_dock_pose()
                            except Exception as e:
                                logger.debug(f"Failed to get home dock pose for robot {task.robot_id}: {e}")
                            
                            # 如果获取到充电桩坐标，使用实际坐标；否则使用原点作为后备
                            if dock_pose:
                                distance_to_dock = math.sqrt(
                                    (robot_state.pose.x - dock_pose.x) ** 2 + 
                                    (robot_state.pose.y - dock_pose.y) ** 2
                                )
                                dock_distance = distance_to_dock
                                dock_location = f"({dock_pose.x:.2f}, {dock_pose.y:.2f})"
                            else:
                                # 后备方案：使用原点距离
                                distance_to_origin = math.sqrt(robot_state.pose.x ** 2 + robot_state.pose.y ** 2)
                                dock_distance = distance_to_origin
                                dock_location = "origin (0,0)"
                            
                            # GO_HOME动作必须真正到达充电桩才能完成
                            # 要求：1) 机器人在充电桩附近（距离<1.5m） 2) 状态为idle 3) 没有正在执行的action
                            if dock_distance < 1.5 and robot_state.status.value == "idle":
                                # 检查机器人当前是否有正在执行的action
                                current_action = await agent.get_current_action()
                                if current_action is None or (hasattr(current_action, 'action_id') and current_action.action_id != task.action_id):
                                    logger.info(
                                        f"Task {task.task_id} GO_HOME action: robot {task.robot_id} is at charging dock "
                                        f"(distance={dock_distance:.2f}m < 1.5m from {dock_location}, status=idle, no current_action or different action_id). "
                                        f"Action status={status}, robot is at dock. Marking GO_HOME as completed."
                                    )
                                    # 标记GO_HOME动作完成
                                    await self._handle_multi_action_completion(task, agent, task.robot_id, task.current_action_index)
                                    return
                                else:
                                    logger.debug(
                                        f"Task {task.task_id} GO_HOME action: robot {task.robot_id} is near dock "
                                        f"(distance={dock_distance:.2f}m) but still has active action. Waiting for completion."
                                    )
                            else:
                                # 机器人不在充电桩附近，即使状态是idle也不应该认为完成
                                if robot_state.status.value == "idle" and not robot_state.current_action_id:
                                    logger.warning(
                                        f"Task {task.task_id} GO_HOME action: robot {task.robot_id} is idle with no action_id, "
                                        f"but distance={dock_distance:.2f}m > 1.5m from {dock_location}. "
                                        f"Robot may not have reached charging dock. Action still in progress."
                                    )
                    except Exception as e:
                        logger.debug(f"Failed to check robot state for GO_HOME task {task.task_id}: {e}")
            
                # 如果status为None，说明action可能已经完成或被清除
                if status is None:
                    handled = await self._handle_action_status_none(task, agent, action_state)
                    if handled:
                        return
            
            if status == 4:  # Done
                if result == 0:  # Success
                    handled = await self._handle_action_status_done_success(task, agent, action_state)
                    if handled:
                        return
                elif result == -1:  # Failed
                    reason = action_state.state.get("reason", "") if action_state.state else action_state.reason
                    handled = await self._handle_action_status_done_failed(task, agent, action_state, reason)
                    if handled:
                        return
                elif result == -2:  # Aborted
                    handled = await self._handle_action_status_done_aborted(task, agent, action_state)
                    if handled:
                        return
            elif status == 1:  # Working
                handled = await self._handle_action_status_working(task, agent, action_state)
                if handled:
                    return
            elif status == 0:  # NewBorn
                logger.debug(f"Task {task.task_id} is in NewBorn state (status=0)")
            elif status == 3:  # Paused
                logger.debug(f"Task {task.task_id} is paused (status=3)")
        except Exception as e:
            logger.error(f"Failed to process task update for task {task.task_id}: {e}", exc_info=True)
    
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
                        mode=action.mode,
                        flags=action.flags,
                        acceptable_precision=action.acceptable_precision,
                        fail_retry_count=action.fail_retry_count
                    )
                    # 更新task.target_pose为POI的实际坐标（用于显示）
                    try:
                        pois = await asyncio.wait_for(agent.get_all_pois(), timeout=2.0)
                        for poi in pois:
                            if poi.id == action.poi_name or (poi.metadata and poi.metadata.get("display_name") == action.poi_name):
                                if poi.pose:
                                    task.target_pose = poi.pose
                                    logger.info(
                                        f"Updated task {task.task_id} target_pose to POI '{poi_name_to_use}' "
                                        f"position: ({poi.pose.x:.2f}, {poi.pose.y:.2f})"
                                    )
                                    break
                    except Exception as e:
                        logger.debug(f"Failed to get POI position for task {task.task_id}: {e}")
                elif action.target_pose:
                    # 使用坐标导航
                    action_state = await agent.move_to(
                        target=action.target_pose,
                        mode=action.mode,
                        flags=action.flags,
                        acceptable_precision=action.acceptable_precision,
                        fail_retry_count=action.fail_retry_count,
                        speed_ratio=action.speed_ratio
                    )
                    # 更新task.target_pose为当前动作的目标坐标
                    task.target_pose = action.target_pose
                    logger.info(
                        f"Updated task {task.task_id} target_pose to action target: "
                        f"({action.target_pose.x:.2f}, {action.target_pose.y:.2f})"
                    )
                else:
                    raise ValueError("move_to action requires either target_pose or poi_name")
                
                task.action_id = action_state.action_id
                task.status = TaskStatus.EXECUTING
                if task.started_at is None:
                    task.started_at = datetime.now()
                logger.info(
                    f"MoveToAction created for task {task.task_id}: "
                    f"action_id={action_state.action_id}, "
                    f"current_action_index={task.current_action_index}/{len(task.actions) if task.is_multi_action else 1}, "
                    f"status=executing"
                )
                # 立即保存状态，确保action_id被持久化
                self._save_tasks_to_file()
                
            elif action.action_type == ActionType.WAIT:
                # 等待动作：创建一个异步任务来等待
                task.action_id = None  # 等待动作没有action_id
                task.status = TaskStatus.EXECUTING
                if task.started_at is None:
                    task.started_at = datetime.now()
                
                # 记录等待开始时间（用于防止其他逻辑干扰）
                wait_start_time = datetime.now()
                self._save_tasks_to_file()  # 立即保存状态，确保WAIT动作被记录
                
                # 创建一个后台任务来等待
                async def wait_and_continue():
                    try:
                        logger.info(
                            f"[MULTI-ACTION] Task {task.task_id} WAIT action started: "
                            f"duration={action.wait_duration}s, action_index={task.current_action_index}"
                        )
                        
                        # 等待指定时长
                        await asyncio.sleep(action.wait_duration)
                        
                        # 等待完成后，检查任务状态是否仍然有效
                        if task.task_id not in self.tasks:
                            logger.warning(f"Task {task.task_id} was deleted during WAIT, aborting")
                            return
                        
                        if task.status not in [TaskStatus.EXECUTING, TaskStatus.ASSIGNED]:
                            logger.warning(
                                f"Task {task.task_id} status changed to {task.status.value} during WAIT, "
                                f"aborting continuation"
                            )
                            return
                        
                        # 验证当前动作索引仍然正确
                        if task.current_action_index >= len(task.actions):
                            logger.warning(
                                f"Task {task.task_id} current_action_index ({task.current_action_index}) "
                                f">= actions length ({len(task.actions)}), aborting"
                            )
                            return
                        
                        # 重要：检查当前动作是否仍然是WAIT动作
                        # 如果动作索引已经改变（被其他逻辑修改），说明WAIT动作已被跳过，不应该继续
                        current_action_item = task.actions[task.current_action_index]
                        if current_action_item.action_type != ActionType.WAIT:
                            logger.warning(
                                f"Task {task.task_id} WAIT action was skipped: current_action_index={task.current_action_index}, "
                                f"current_action_type={current_action_item.action_type}. Aborting WAIT continuation."
                            )
                            return
                        
                        # 等待完成后，继续下一个动作
                        task.current_action_index += 1
                        self._save_tasks_to_file()  # 保存索引更新
                        
                        if task.current_action_index < len(task.actions):
                            logger.info(
                                f"[MULTI-ACTION] Task {task.task_id} WAIT completed ({action.wait_duration}s), "
                                f"executing next action {task.current_action_index + 1}/{len(task.actions)}"
                            )
                            await self._execute_next_action(task, agent, robot_id)
                        else:
                            # 所有动作完成
                            task.status = TaskStatus.COMPLETED
                            task.completed_at = datetime.now()
                            # 释放限行区域占用
                            await self._release_robot_from_restricted_area_on_completion(task)
                            logger.info(f"Task {task.task_id} (multi-action) completed all actions")
                            self._save_tasks_to_file()
                    except Exception as e:
                        logger.error(
                            f"[MULTI-ACTION] Error in WAIT action continuation for task {task.task_id}: {e}",
                            exc_info=True
                        )
                
                # 启动等待任务
                asyncio.create_task(wait_and_continue())
                logger.info(
                    f"[MULTI-ACTION] Task {task.task_id} WAIT action started: "
                    f"duration={action.wait_duration}s, action_index={task.current_action_index}"
                )
                
            elif action.action_type == ActionType.GO_HOME:
                # 回桩
                try:
                    action_state = await asyncio.wait_for(agent.go_home(), timeout=10.0)
                    if action_state and action_state.action_id:
                        task.action_id = action_state.action_id
                        task.status = TaskStatus.EXECUTING
                        if task.started_at is None:
                            task.started_at = datetime.now()
                        logger.info(f"GoHomeAction created: action_id={action_state.action_id}")
                    else:
                        logger.warning(f"GoHomeAction for task {task.task_id} returned no action_id, will check robot state")
                        # 即使没有action_id，也标记为执行中，后续通过检查机器人状态来判断完成
                        task.status = TaskStatus.EXECUTING
                        if task.started_at is None:
                            task.started_at = datetime.now()
                except asyncio.TimeoutError:
                    logger.warning(f"GoHomeAction for task {task.task_id} timed out after 10s, will check robot state")
                    # 超时后也标记为执行中，后续通过检查机器人状态来判断完成
                    task.status = TaskStatus.EXECUTING
                    if task.started_at is None:
                        task.started_at = datetime.now()
                except Exception as e:
                    logger.error(f"Failed to execute GO_HOME action for task {task.task_id}: {e}", exc_info=True)
                    raise  # 重新抛出异常，让外层错误处理逻辑处理
            
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
        # 重要：只检查正在执行的任务，不取消它们，而是通过增加惩罚来让新任务等待
        executing_tasks = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.EXECUTING 
            and t.task_id != current_task_id
        ]
        
        for other_task in executing_tasks:
            other_path = self.task_paths.get(other_task.task_id)
            other_target = other_task.target_pose
            
            # 优化：检查两个路径是否碰撞（使用采样点，减少计算量）
            # 对于长路径，只检查关键点（起点、终点、中间采样点）
            min_distance = float('inf')
            collision_points = []
            target_collision = False  # 是否经过正在执行任务的目标点
            
            # 安全距离 = 机器人半径 * 2 + 安全距离
            safety_distance = 0.3 * 2 + self.collision_detector.safety_distance
            
            # 重要：首先检查新任务的路径是否经过正在执行任务的目标点
            # 如果经过，应该让新任务等待，而不是取消正在执行的任务
            if other_target:
                for path_point in path:
                    dx = path_point.x - other_target.x
                    dy = path_point.y - other_target.y
                    distance_sq = dx*dx + dy*dy
                    distance = math.sqrt(distance_sq) if distance_sq < safety_distance * safety_distance else float('inf')
                    
                    if distance < safety_distance:
                        target_collision = True
                        min_distance = min(min_distance, distance)
                        if return_collisions:
                            collision_points.append(('target', 'target', distance))
                        logger.info(
                            f"New task path passes through executing task {other_task.task_id}'s target point "
                            f"({other_target.x:.2f}, {other_target.y:.2f}), "
                            f"distance={distance:.2f}m. New task will wait (penalty increased)."
                        )
                        break  # 找到目标点碰撞即可
            
            # 如果路径存在，检查路径之间的碰撞
            if other_path and len(other_path) > 0:
                # 优化：对路径进行采样，减少计算量
                # 对于短路径（<10个点），检查所有点；对于长路径，采样检查
                path_sample = path
                other_path_sample = other_path
                if len(path) > 10:
                    # 采样：起点、终点、中间均匀采样
                    step = max(1, len(path) // 5)
                    path_sample = [path[i] for i in range(0, len(path), step)] + [path[-1]]
                if len(other_path) > 10:
                    step = max(1, len(other_path) // 5)
                    other_path_sample = [other_path[i] for i in range(0, len(other_path), step)] + [other_path[-1]]
                
                for i, path_point in enumerate(path_sample):
                    for j, other_point in enumerate(other_path_sample):
                        dx = path_point.x - other_point.x
                        dy = path_point.y - other_point.y
                        distance_sq = dx*dx + dy*dy  # 使用平方距离，避免开方
                        distance = math.sqrt(distance_sq) if distance_sq < safety_distance * safety_distance else float('inf')
                        
                        if distance < safety_distance:
                            min_distance = min(min_distance, distance)
                            if return_collisions:
                                collision_points.append((i, j, distance))
            
            # 如果有碰撞，计算惩罚值
            # 重要：如果新任务路径经过正在执行任务的目标点，增加更大的惩罚值
            # 这样新任务会等待正在执行的任务完成，而不是取消它
            if min_distance < float('inf'):
                # 基础惩罚值 = (安全距离 - 最小距离) / 安全距离 * 路径长度 * 10.0
                base_penalty = (safety_distance - min_distance) / safety_distance * len(path) * 10.0
                
                # 如果经过正在执行任务的目标点，惩罚值增加3倍，确保新任务等待
                if target_collision:
                    penalty = base_penalty * 3.0
                    logger.info(
                        f"Path collision with executing task {other_task.task_id}'s target point: "
                        f"penalty increased to {penalty:.2f} (base: {base_penalty:.2f})"
                    )
                else:
                    penalty = base_penalty
                
                collision_penalty += penalty
                
                if return_collisions:
                    collisions.append({
                        'task_id': other_task.task_id,
                        'robot_id': other_task.robot_id,
                        'collision_points': collision_points,
                        'min_distance': min_distance,
                        'target_collision': target_collision
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
                    # 释放限行区域占用
                    await self._release_robot_from_restricted_area_on_completion(task)
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
                        # 释放限行区域占用
                        await self._release_robot_from_restricted_area_on_completion(task)
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
                    # 释放限行区域占用
                    await self._release_robot_from_restricted_area_on_completion(task)
                    if task.task_id in self.task_paths:
                        del self.task_paths[task.task_id]
                    self._save_tasks_to_file()
                else:
                    # 未到达目标，检查是否被其他机器人阻塞（死锁检测）
                    # 如果机器人长时间卡住，可能是死锁，需要触发死锁检测
                    execution_time = 0.0
                    if task.started_at:
                        execution_time = (datetime.now() - task.started_at).total_seconds()
                    
                    # 如果执行时间超过30秒且机器人没有移动，可能是死锁
                    if execution_time > 30.0:
                        logger.warning(
                            f"Task {task.task_id} action_id invalid, robot not at target "
                            f"(distance={distance:.2f}m, execution_time={execution_time:.1f}s). "
                            f"Robot may be blocked by other robots. Triggering deadlock detection..."
                        )
                        # 触发死锁检测（异步，不阻塞）
                        asyncio.create_task(self._trigger_deadlock_detection_for_robot(robot_id))
                    
                    # 重新发送move_to指令
                    logger.info(
                        f"Task {task.task_id} action_id invalid, robot not at target "
                        f"(distance={distance:.2f}m). Resending move_to command."
                    )
                    try:
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
                    except Exception as e:
                        logger.error(
                            f"Failed to resend move_to for task {task.task_id}: {e}. "
                            f"Robot may be blocked. Will retry later."
                        )
                        # 如果重新发送失败，可能是被阻塞，触发死锁检测
                        asyncio.create_task(self._trigger_deadlock_detection_for_robot(robot_id))
            else:
                logger.warning(f"Task {task.task_id} has no target_pose, cannot recover")
        except Exception as e:
            logger.error(f"Failed to recover task {task.task_id} after invalid action_id: {e}", exc_info=True)
    
    async def _trigger_deadlock_detection_for_robot(self, robot_id: str):
        """
        为特定机器人触发死锁检测
        
        Args:
            robot_id: 机器人ID
        """
        try:
            from app.services.deadlock_detector import deadlock_logger
            logger.info(f"Triggering deadlock detection for robot {robot_id}")
            deadlock_logger.info(f"[TRIGGER] Manual deadlock detection triggered for robot {robot_id}")
            
            # 获取所有机器人ID（包括当前机器人）
            all_robot_ids = self.robot_manager.list_robots()
            
            # 触发死锁检测
            deadlocks = await self.deadlock_detector.detect_deadlocks(all_robot_ids)
            
            if deadlocks:
                # 查找包含当前机器人的死锁
                for deadlock in deadlocks:
                    if robot_id in deadlock.robot_ids:
                        deadlock_logger.warning(
                            f"[TRIGGER] Deadlock detected for robot {robot_id}: "
                            f"type={deadlock.deadlock_type}, robots={deadlock.robot_ids}, "
                            f"duration={deadlock.duration:.1f}s"
                        )
                        # 尝试解决死锁
                        success = await self.deadlock_detector.resolve_deadlock(deadlock)
                        if success:
                            deadlock_logger.info(f"[TRIGGER] Deadlock resolved for robot {robot_id}")
                        else:
                            deadlock_logger.error(f"[TRIGGER] Failed to resolve deadlock for robot {robot_id}")
                        break
            else:
                deadlock_logger.info(f"[TRIGGER] No deadlock detected for robot {robot_id}")
        except Exception as e:
            logger.error(f"Failed to trigger deadlock detection for robot {robot_id}: {e}", exc_info=True)
            from app.services.deadlock_detector import deadlock_logger
            deadlock_logger.error(f"[TRIGGER] Failed to trigger deadlock detection for robot {robot_id}: {e}")
    
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
            # 首先检查是否有执行中的任务，如果没有就直接返回，避免在没有任务时仍然检查阻塞
            executing_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.EXECUTING and t.robot_id and t.target_pose
            ]
            
            if not executing_tasks:
                # 没有执行中的任务，不需要检查阻塞
                logger.debug("No executing tasks found, skipping blocking check")
                return
            
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
            
            # 获取所有正在执行任务的机器人ID（这些机器人不应该被移动到避让点）
            executing_robot_ids = set()
            for task in self.tasks.values():
                if task.status == TaskStatus.EXECUTING and task.robot_id:
                    executing_robot_ids.add(task.robot_id)
                elif task.status == TaskStatus.ASSIGNED and task.robot_id:
                    executing_robot_ids.add(task.robot_id)
            
            # 合并已完成任务、失败任务和IDLE状态的机器人
            # 重要：排除正在执行任务的机器人
            blocking_robots = []
            for completed_task in completed_tasks:
                completed_robot_id = completed_task.robot_id
                # 如果这个机器人正在执行其他任务，不应该让它避让
                if completed_robot_id in executing_robot_ids:
                    logger.debug(
                        f"Robot {completed_robot_id} has completed task {completed_task.task_id} "
                        f"but is executing another task, skipping blocking check"
                    )
                    continue
                if completed_robot_id in self.completed_robots_avoiding:
                    continue
                # 检查机器人是否正在回桩（有go_home action），如果有就不应该让它避让
                try:
                    agent = self.robot_manager.get_robot_agent(completed_robot_id)
                    if agent:
                        current_action = await agent.get_current_action()
                        if current_action and current_action.action_id:
                            # 检查是否是回桩action（通过action_name判断）
                            if current_action.action_name and "BackHome" in current_action.action_name:
                                logger.debug(
                                    f"Robot {completed_robot_id} is returning to charging dock (action_id={current_action.action_id}), "
                                    f"skipping blocking check to avoid interrupting go_home action"
                                )
                                continue
                except Exception as e:
                    logger.debug(f"Failed to get current action for robot {completed_robot_id}: {e}")
                
                # 检查机器人是否已经在充电桩附近（距离原点<1米），如果是就不应该让它避让
                state = await self.robot_manager.get_robot_state(completed_robot_id)
                if state and state.pose:
                    distance_to_origin = math.sqrt(state.pose.x * state.pose.x + state.pose.y * state.pose.y)
                    if distance_to_origin < 1.0:  # 距离原点小于1米，认为在充电桩
                        logger.debug(
                            f"Robot {completed_robot_id} is at charging dock (distance to origin: {distance_to_origin:.2f}m), "
                            f"skipping blocking check to avoid moving robot away from dock"
                        )
                        continue
                    
                    # 检查机器人最近完成的任务是否是GO_HOME（刚回桩完成）
                    # 如果最近完成的任务是GO_HOME且完成时间在5分钟内，认为机器人刚回桩，不应该让它避让
                    recent_go_home_completed = False
                    for task in self.tasks.values():
                        if (task.robot_id == completed_robot_id and 
                            task.status == TaskStatus.COMPLETED and 
                            task.completed_at):
                            # 检查是否是最近5分钟内完成的GO_HOME任务
                            time_since_completion = (datetime.now() - task.completed_at).total_seconds()
                            if time_since_completion < 300:  # 5分钟内
                                if task.is_multi_action and task.actions:
                                    # 检查最后一个动作是否是GO_HOME
                                    last_action = task.actions[-1] if task.actions else None
                                    if last_action and last_action.action_type == ActionType.GO_HOME:
                                        recent_go_home_completed = True
                                        logger.debug(
                                            f"Robot {completed_robot_id} recently completed GO_HOME task {task.task_id} "
                                            f"({time_since_completion:.1f}s ago), skipping blocking check"
                                        )
                                        break
                                elif not task.is_multi_action:
                                    # 对于非多动作任务，检查任务的目标是否是充电桩（距离原点很近）
                                    if task.target_pose:
                                        target_distance_to_origin = math.sqrt(task.target_pose.x * task.target_pose.x + task.target_pose.y * task.target_pose.y)
                                        if target_distance_to_origin < 1.0:
                                            recent_go_home_completed = True
                                            logger.debug(
                                                f"Robot {completed_robot_id} recently completed task {task.task_id} to charging dock "
                                                f"({time_since_completion:.1f}s ago), skipping blocking check"
                                            )
                                            break
                    
                    if recent_go_home_completed:
                        continue
                    
                    blocking_robots.append((completed_robot_id, state.pose, completed_task.task_id, "completed"))
            
            # 添加失败任务的机器人（同样排除正在执行任务的机器人）
            for failed_task in failed_tasks:
                failed_robot_id = failed_task.robot_id
                # 如果这个机器人正在执行其他任务，不应该让它避让
                if failed_robot_id in executing_robot_ids:
                    logger.debug(
                        f"Robot {failed_robot_id} has failed task {failed_task.task_id} "
                        f"but is executing another task, skipping blocking check"
                    )
                    continue
                if failed_robot_id in self.completed_robots_avoiding:
                    continue
                # 检查机器人是否正在回桩（有go_home action），如果有就不应该让它避让
                try:
                    agent = self.robot_manager.get_robot_agent(failed_robot_id)
                    if agent:
                        current_action = await agent.get_current_action()
                        if current_action and current_action.action_id:
                            # 检查是否是回桩action（通过action_name判断）
                            if current_action.action_name and "BackHome" in current_action.action_name:
                                logger.debug(
                                    f"Robot {failed_robot_id} is returning to charging dock (action_id={current_action.action_id}), "
                                    f"skipping blocking check to avoid interrupting go_home action"
                                )
                                continue
                except Exception as e:
                    logger.debug(f"Failed to get current action for robot {failed_robot_id}: {e}")
                
                # 检查机器人是否已经在充电桩附近（距离原点<1米），如果是就不应该让它避让
                state = await self.robot_manager.get_robot_state(failed_robot_id)
                if state and state.pose:
                    distance_to_origin = math.sqrt(state.pose.x * state.pose.x + state.pose.y * state.pose.y)
                    if distance_to_origin < 1.0:  # 距离原点小于1米，认为在充电桩
                        logger.debug(
                            f"Robot {failed_robot_id} is at charging dock (distance to origin: {distance_to_origin:.2f}m), "
                            f"skipping blocking check to avoid moving robot away from dock"
                        )
                        continue
                    
                    # 检查机器人最近完成的任务是否是GO_HOME（刚回桩完成）
                    # 如果最近完成的任务是GO_HOME且完成时间在5分钟内，认为机器人刚回桩，不应该让它避让
                    recent_go_home_completed = False
                    for task in self.tasks.values():
                        if (task.robot_id == failed_robot_id and 
                            task.status == TaskStatus.COMPLETED and 
                            task.completed_at):
                            # 检查是否是最近5分钟内完成的GO_HOME任务
                            time_since_completion = (datetime.now() - task.completed_at).total_seconds()
                            if time_since_completion < 300:  # 5分钟内
                                if task.is_multi_action and task.actions:
                                    # 检查最后一个动作是否是GO_HOME
                                    last_action = task.actions[-1] if task.actions else None
                                    if last_action and last_action.action_type == ActionType.GO_HOME:
                                        recent_go_home_completed = True
                                        logger.debug(
                                            f"Robot {failed_robot_id} recently completed GO_HOME task {task.task_id} "
                                            f"({time_since_completion:.1f}s ago), skipping blocking check"
                                        )
                                        break
                                elif not task.is_multi_action:
                                    # 对于非多动作任务，检查任务的目标是否是充电桩（距离原点很近）
                                    if task.target_pose:
                                        target_distance_to_origin = math.sqrt(task.target_pose.x * task.target_pose.x + task.target_pose.y * task.target_pose.y)
                                        if target_distance_to_origin < 1.0:
                                            recent_go_home_completed = True
                                            logger.debug(
                                                f"Robot {failed_robot_id} recently completed task {task.task_id} to charging dock "
                                                f"({time_since_completion:.1f}s ago), skipping blocking check"
                                            )
                                            break
                    
                    if recent_go_home_completed:
                        continue
                    
                    blocking_robots.append((failed_robot_id, state.pose, failed_task.task_id, "failed"))
            
            # 添加IDLE状态的机器人（同样排除正在执行任务的机器人）
            for robot_id, pose in idle_robots:
                # 如果这个机器人正在执行任务，不应该让它避让
                if robot_id in executing_robot_ids:
                    logger.debug(
                        f"Robot {robot_id} is idle but has an executing task, skipping blocking check"
                    )
                    continue
                # 检查机器人是否正在回桩（有go_home action），如果有就不应该让它避让
                try:
                    agent = self.robot_manager.get_robot_agent(robot_id)
                    if agent:
                        current_action = await agent.get_current_action()
                        if current_action and current_action.action_id:
                            # 检查是否是回桩action（通过action_name判断）
                            if current_action.action_name and "BackHome" in current_action.action_name:
                                logger.debug(
                                    f"Robot {robot_id} is returning to charging dock (action_id={current_action.action_id}), "
                                    f"skipping blocking check to avoid interrupting go_home action"
                                )
                                continue
                except Exception as e:
                    logger.debug(f"Failed to get current action for robot {robot_id}: {e}")
                
                # 检查机器人是否已经在充电桩附近（距离原点<1米），如果是就不应该让它避让
                # 充电桩通常在原点(0,0)附近
                distance_to_origin = math.sqrt(pose.x * pose.x + pose.y * pose.y)
                if distance_to_origin < 1.0:  # 距离原点小于1米，认为在充电桩
                    logger.debug(
                        f"Robot {robot_id} is at charging dock (distance to origin: {distance_to_origin:.2f}m), "
                        f"skipping blocking check to avoid moving robot away from dock"
                    )
                    continue
                
                # 检查机器人最近完成的任务是否是GO_HOME（刚回桩完成）
                # 如果最近完成的任务是GO_HOME且完成时间在5分钟内，认为机器人刚回桩，不应该让它避让
                recent_go_home_completed = False
                for task in self.tasks.values():
                    if (task.robot_id == robot_id and 
                        task.status == TaskStatus.COMPLETED and 
                        task.completed_at):
                        # 检查是否是最近5分钟内完成的GO_HOME任务
                        time_since_completion = (datetime.now() - task.completed_at).total_seconds()
                        if time_since_completion < 300:  # 5分钟内
                            if task.is_multi_action and task.actions:
                                # 检查最后一个动作是否是GO_HOME
                                last_action = task.actions[-1] if task.actions else None
                                if last_action and last_action.action_type == ActionType.GO_HOME:
                                    recent_go_home_completed = True
                                    logger.debug(
                                        f"Robot {robot_id} recently completed GO_HOME task {task.task_id} "
                                        f"({time_since_completion:.1f}s ago), skipping blocking check"
                                    )
                                    break
                            elif not task.is_multi_action and task.action_type == ActionType.GO_HOME:
                                recent_go_home_completed = True
                                logger.debug(
                                    f"Robot {robot_id} recently completed GO_HOME task {task.task_id} "
                                    f"({time_since_completion:.1f}s ago), skipping blocking check"
                                )
                                break
                
                if recent_go_home_completed:
                    continue
                
                if robot_id not in self.completed_robots_avoiding:
                    blocking_robots.append((robot_id, pose, None, "idle"))
            
            if not blocking_robots:
                return
            
            # 执行中的任务已经在方法开始处检查过了，这里直接使用
            logger.debug(
                f"Checking blocking: {len(blocking_robots)} potential blocking robots, "
                f"{len(executing_tasks)} executing tasks"
            )
            
            # 对每个可能阻塞的机器人，检查是否阻塞了执行中任务的路径
            for robot_id, robot_pose, task_id, task_status in blocking_robots:
                # 首先检查机器人是否已经有正在执行的action，如果有就不应该认为它阻塞
                try:
                    agent = self.robot_manager.get_robot_agent(robot_id)
                    if agent:
                        current_action = await agent.get_current_action()
                        if current_action and current_action.action_id:
                            logger.debug(
                                f"Robot {robot_id} has active action (action_id={current_action.action_id}), "
                                f"skipping blocking check to avoid false positives"
                            )
                            continue
                except Exception as e:
                    logger.debug(f"Failed to get current action for robot {robot_id}: {e}")
                
                # 检查是否阻塞了任何执行中任务的路径或目标点
                blocking_executing_tasks = []
                robot_radius = 0.3  # 机器人半径
                safety_distance = 0.8  # 安全距离
                threshold_distance = robot_radius * 2 + safety_distance  # 1.4米
                
                for executing_task in executing_tasks:
                    # 重要：排除机器人阻塞自己任务的情况
                    if robot_id == executing_task.robot_id:
                        logger.debug(
                            f"Robot {robot_id} is executing task {executing_task.task_id}, "
                            f"skipping self-blocking check"
                        )
                        continue
                    
                    # 获取执行中任务的机器人当前位置（用于计算到阻塞机器人的距离）
                    executing_robot_state = await self.robot_manager.get_robot_state(executing_task.robot_id)
                    if not executing_robot_state or not executing_robot_state.pose:
                        continue
                    
                    executing_path = self.task_paths.get(executing_task.task_id)
                    target_pose = executing_task.target_pose
                    
                    min_distance = float('inf')
                    blocking_reason = None
                    
                    # 1. 检查是否阻塞了执行中机器人的当前位置（如果执行中机器人被卡住）
                    # 只检查如果执行中机器人距离目标点较远（>2米），说明可能被阻塞
                    if target_pose:
                        dx_to_target = executing_robot_state.pose.x - target_pose.x
                        dy_to_target = executing_robot_state.pose.y - target_pose.y
                        distance_to_target = math.sqrt(dx_to_target*dx_to_target + dy_to_target*dy_to_target)
                        if distance_to_target > 2.0:  # 执行中机器人距离目标点较远，可能被阻塞
                            dx = robot_pose.x - executing_robot_state.pose.x
                            dy = robot_pose.y - executing_robot_state.pose.y
                            current_distance = math.sqrt(dx*dx + dy*dy)
                            if current_distance < threshold_distance:
                                min_distance = current_distance
                                blocking_reason = "blocking executing robot's current position"
                    
                    # 2. 检查是否阻塞了路径（如果有路径）- 这是最重要的检查
                    if executing_path and len(executing_path) > 0:
                        for path_point in executing_path:
                            dx = robot_pose.x - path_point.x
                            dy = robot_pose.y - path_point.y
                            distance = math.sqrt(dx*dx + dy*dy)
                            if distance < min_distance:
                                min_distance = distance
                                blocking_reason = "blocking path"
                    
                    # 3. 检查是否阻塞了目标点（只检查如果执行中机器人距离目标点很近，<1米）
                    # 这样可以避免对距离目标点很远的任务误判
                    if target_pose:
                        dx_to_target = robot_pose.x - target_pose.x
                        dy_to_target = robot_pose.y - target_pose.y
                        target_distance = math.sqrt(dx_to_target*dx_to_target + dy_to_target*dy_to_target)
                        
                        # 获取执行中机器人到目标点的距离
                        dx_executing_to_target = executing_robot_state.pose.x - target_pose.x
                        dy_executing_to_target = executing_robot_state.pose.y - target_pose.y
                        executing_to_target_distance = math.sqrt(dx_executing_to_target*dx_executing_to_target + dy_executing_to_target*dy_executing_to_target)
                        
                        # 只有当执行中机器人距离目标点很近（<1米）时，才检查阻塞机器人是否阻塞目标点
                        # 这样可以避免对距离目标点很远的任务误判
                        if executing_to_target_distance < 1.0 and target_distance < min_distance:
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
        将已完成任务的机器人移动到避让点（优化：确保避让点远离被阻塞的路径和目标点）
        
        Args:
            robot_id: 机器人ID
            current_pose: 当前位置
            blocking_tasks: 被阻塞的任务列表
        """
        try:
            # 首先检查机器人是否已经在充电桩附近（距离原点<1米），如果是就不应该发送避让指令
            distance_to_origin = math.sqrt(current_pose.x * current_pose.x + current_pose.y * current_pose.y)
            if distance_to_origin < 1.0:  # 距离原点小于1米，认为在充电桩
                logger.info(
                    f"Robot {robot_id} is at charging dock (distance to origin: {distance_to_origin:.2f}m), "
                    f"skipping avoidance to avoid moving robot away from dock"
                )
                # 从避让列表中移除
                self.completed_robots_avoiding.discard(robot_id)
                return
            
            # 检查机器人状态是否为idle且没有current_action（已经在充电桩）
            try:
                robot_state = await self.robot_manager.get_robot_state(robot_id)
                if robot_state and robot_state.status.value == "idle":
                    agent = self.robot_manager.get_robot_agent(robot_id)
                    if agent:
                        current_action = await agent.get_current_action()
                        if not current_action or not current_action.action_id:
                            logger.info(
                                f"Robot {robot_id} is idle at charging dock (no current action), "
                                f"skipping avoidance to avoid moving robot away from dock"
                            )
                            # 从避让列表中移除
                            self.completed_robots_avoiding.discard(robot_id)
                            return
            except Exception as e:
                logger.debug(f"Failed to check robot state for robot {robot_id}: {e}")
            
            # 检查机器人最近完成的任务是否是GO_HOME（刚回桩完成）
            # 如果最近完成的任务是GO_HOME且完成时间在5分钟内，认为机器人刚回桩，不应该让它避让
            recent_go_home_completed = False
            for task in self.tasks.values():
                if (task.robot_id == robot_id and 
                    task.status == TaskStatus.COMPLETED and 
                    task.completed_at):
                    # 检查是否是最近5分钟内完成的GO_HOME任务
                    time_since_completion = (datetime.now() - task.completed_at).total_seconds()
                    if time_since_completion < 300:  # 5分钟内
                        if task.is_multi_action and task.actions:
                            # 检查最后一个动作是否是GO_HOME
                            last_action = task.actions[-1] if task.actions else None
                            if last_action and last_action.action_type == ActionType.GO_HOME:
                                recent_go_home_completed = True
                                logger.info(
                                    f"Robot {robot_id} recently completed GO_HOME task {task.task_id} "
                                    f"({time_since_completion:.1f}s ago), skipping avoidance"
                                )
                                break
                        elif not task.is_multi_action:
                            # 对于非多动作任务，检查任务的目标是否是充电桩（距离原点很近）
                            if task.target_pose:
                                target_distance_to_origin = math.sqrt(task.target_pose.x * task.target_pose.x + task.target_pose.y * task.target_pose.y)
                                if target_distance_to_origin < 1.0:
                                    recent_go_home_completed = True
                                    logger.info(
                                        f"Robot {robot_id} recently completed task {task.task_id} to charging dock "
                                        f"({time_since_completion:.1f}s ago), skipping avoidance"
                                    )
                                    break
            
            if recent_go_home_completed:
                # 从避让列表中移除
                self.completed_robots_avoiding.discard(robot_id)
                return
            
            agent = self.robot_manager.get_robot_agent(robot_id)
            if not agent:
                return
            
            # 避让点必须远离所有被阻塞的路径和目标点（至少3米）
            min_safe_distance = 3.0  # 避让点必须距离路径和目标点至少3米
            
            # 计算避让点：尝试多个距离，从远到近，找到第一个有效的避让点
            backoff_distances = [5.0, 4.0, 3.0, 2.5]  # 优先选择更远的避让点
            
            backoff_pose = None
            for backoff_distance in backoff_distances:
                # 计算后退目标点（沿着当前朝向的反方向）
                back_x = current_pose.x - math.cos(current_pose.yaw) * backoff_distance
                back_y = current_pose.y - math.sin(current_pose.yaw) * backoff_distance
                
                # 检查后退点是否在地图范围内且不是障碍物
                if not (self.path_planner.map_manager.is_valid_coordinate(back_x, back_y) and
                        not self.path_planner.map_manager.is_obstacle(back_x, back_y)):
                    continue
                
                # 验证避让点是否远离所有被阻塞的路径和目标点
                is_far_enough = True
                for task in blocking_tasks:
                    # 检查避让点是否远离执行中机器人的当前位置
                    executing_robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                    if executing_robot_state and executing_robot_state.pose:
                        dx = back_x - executing_robot_state.pose.x
                        dy = back_y - executing_robot_state.pose.y
                        distance = math.sqrt(dx*dx + dy*dy)
                        if distance < min_safe_distance:
                            is_far_enough = False
                            break
                    
                    # 检查避让点是否远离路径
                    path = self.task_paths.get(task.task_id)
                    if path:
                        for path_point in path:
                            dx = back_x - path_point.x
                            dy = back_y - path_point.y
                            distance = math.sqrt(dx*dx + dy*dy)
                            if distance < min_safe_distance:
                                is_far_enough = False
                                break
                        if not is_far_enough:
                            break
                    
                    # 检查避让点是否远离目标点
                    if task.target_pose:
                        dx = back_x - task.target_pose.x
                        dy = back_y - task.target_pose.y
                        distance = math.sqrt(dx*dx + dy*dy)
                        if distance < min_safe_distance:
                            is_far_enough = False
                            break
                
                if is_far_enough:
                    backoff_pose = Pose(
                        x=back_x,
                        y=back_y,
                        z=current_pose.z,
                        yaw=current_pose.yaw
                    )
                    logger.info(
                        f"Found valid avoidance point for robot {robot_id} at "
                        f"({back_x:.2f}, {back_y:.2f}), distance={backoff_distance:.2f}m"
                    )
                    break
            
            if backoff_pose:
                # 再次检查机器人是否已经在充电桩附近（距离原点<1米），如果是就不应该发送避让指令
                # 这个检查在计算避让点之后，发送move_to之前，确保即使避让点计算成功，也不会移动回桩的机器人
                try:
                    robot_state = await self.robot_manager.get_robot_state(robot_id)
                    if robot_state and robot_state.pose:
                        distance_to_origin = math.sqrt(robot_state.pose.x * robot_state.pose.x + robot_state.pose.y * robot_state.pose.y)
                        if distance_to_origin < 1.0:  # 距离原点小于1米，认为在充电桩
                            logger.info(
                                f"Robot {robot_id} is at charging dock (distance to origin: {distance_to_origin:.2f}m), "
                                f"skipping avoidance move_to to avoid moving robot away from dock"
                            )
                            # 从避让列表中移除
                            self.completed_robots_avoiding.discard(robot_id)
                            return
                        
                        # 检查机器人状态是否为idle且没有current_action（已经在充电桩）
                        if robot_state.status.value == "idle":
                            try:
                                current_action = await agent.get_current_action()
                                if not current_action or not current_action.action_id:
                                    logger.info(
                                        f"Robot {robot_id} is idle at charging dock (no current action), "
                                        f"skipping avoidance move_to to avoid moving robot away from dock"
                                    )
                                    # 从避让列表中移除
                                    self.completed_robots_avoiding.discard(robot_id)
                                    return
                            except Exception as e:
                                logger.debug(f"Failed to get current action for robot {robot_id}: {e}")
                except Exception as e:
                    logger.debug(f"Failed to check robot state for robot {robot_id}: {e}")
                
                # 检查机器人是否已经有正在执行的action，如果有就不发送新的move_to指令
                try:
                    current_action = await agent.get_current_action()
                    if current_action and current_action.action_id:
                        # 检查是否是回桩action（通过action_name判断）
                        if current_action.action_name and "BackHome" in current_action.action_name:
                            logger.info(
                                f"Robot {robot_id} is returning to charging dock (action_id={current_action.action_id}), "
                                f"skipping avoidance move_to to avoid interrupting go_home action"
                            )
                            # 从避让列表中移除，避免重复处理
                            self.completed_robots_avoiding.discard(robot_id)
                            return
                        else:
                            logger.info(
                                f"Robot {robot_id} already has an active action (action_id={current_action.action_id}), "
                                f"skipping avoidance move_to to avoid duplicate commands"
                            )
                            # 从避让列表中移除，避免重复处理
                            self.completed_robots_avoiding.discard(robot_id)
                            return
                except Exception as e:
                    logger.debug(f"Failed to get current action for robot {robot_id}: {e}")
                
                logger.info(
                    f"Moving completed task robot {robot_id} to avoidance point "
                    f"({backoff_pose.x:.2f}, {backoff_pose.y:.2f})"
                )
                
                # 移动到避让点（使用较高速度，快速让出路径）
                await agent.move_to(
                    backoff_pose,
                    mode=0,  # Free Navigation
                    acceptable_precision=0.3,
                    speed_ratio=0.8  # 提高速度，快速让出路径
                )
                
                logger.info(f"Robot {robot_id} moved to avoidance point")
                
                # 等待一小段时间让机器人到达避让点
                await asyncio.sleep(1.0)
                
                # 验证避让是否成功：检查是否仍然阻塞
                new_state = await self.robot_manager.get_robot_state(robot_id)
                if new_state and new_state.pose:
                    still_blocking = False
                    for task in blocking_tasks:
                        executing_robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                        if executing_robot_state and executing_robot_state.pose:
                            dx = new_state.pose.x - executing_robot_state.pose.x
                            dy = new_state.pose.y - executing_robot_state.pose.y
                            distance = math.sqrt(dx*dx + dy*dy)
                            if distance < 1.4:  # 仍然阻塞
                                still_blocking = True
                                logger.warning(
                                    f"Robot {robot_id} still blocking after avoidance "
                                    f"(distance={distance:.2f}m < 1.4m). Sending robot back to charging dock."
                                )
                                break
                    
                    if still_blocking:
                        # 避让失败，直接回桩（最可靠的避让方式）
                        try:
                            go_home_result = await agent.go_home()
                            logger.info(
                                f"Robot {robot_id} sent back to charging dock as avoidance failed. "
                                f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                            )
                        except Exception as e:
                            logger.error(f"Failed to send robot {robot_id} back to charging dock: {e}")
                    else:
                        logger.info(f"Robot {robot_id} successfully avoided blocking position")
                
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
                        # 垂直于路径方向移动（尝试多个距离，从远到近）
                        side_distances = [4.0, 3.0, 2.0, 1.5]  # 优先选择更远的侧移点
                        side_pose = None
                        
                        for side_distance in side_distances:
                            # 尝试两个方向（左右两侧）
                            for direction_offset in [math.pi/2, -math.pi/2]:
                                side_x = current_pose.x + math.cos(avg_direction + direction_offset) * side_distance
                                side_y = current_pose.y + math.sin(avg_direction + direction_offset) * side_distance
                                
                                if not (self.path_planner.map_manager.is_valid_coordinate(side_x, side_y) and
                                        not self.path_planner.map_manager.is_obstacle(side_x, side_y)):
                                    continue
                                
                                # 验证侧移点是否远离所有被阻塞的路径和目标点
                                is_far_enough = True
                                for task in blocking_tasks:
                                    executing_robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                                    if executing_robot_state and executing_robot_state.pose:
                                        dx = side_x - executing_robot_state.pose.x
                                        dy = side_y - executing_robot_state.pose.y
                                        distance = math.sqrt(dx*dx + dy*dy)
                                        if distance < min_safe_distance:
                                            is_far_enough = False
                                            break
                                    
                                    path = self.task_paths.get(task.task_id)
                                    if path:
                                        for path_point in path:
                                            dx = side_x - path_point.x
                                            dy = side_y - path_point.y
                                            distance = math.sqrt(dx*dx + dy*dy)
                                            if distance < min_safe_distance:
                                                is_far_enough = False
                                                break
                                        if not is_far_enough:
                                            break
                                    
                                    if task.target_pose:
                                        dx = side_x - task.target_pose.x
                                        dy = side_y - task.target_pose.y
                                        distance = math.sqrt(dx*dx + dy*dy)
                                        if distance < min_safe_distance:
                                            is_far_enough = False
                                            break
                                
                                if is_far_enough:
                                    side_pose = Pose(
                                        x=side_x,
                                        y=side_y,
                                        z=current_pose.z,
                                        yaw=current_pose.yaw
                                    )
                                    logger.info(
                                        f"Found valid side avoidance point for robot {robot_id} at "
                                        f"({side_x:.2f}, {side_y:.2f}), distance={side_distance:.2f}m"
                                    )
                                    break
                            
                            if side_pose:
                                break
                        
                        if side_pose:
                            logger.info(
                                f"Moving completed task robot {robot_id} to side avoidance point "
                                f"({side_pose.x:.2f}, {side_pose.y:.2f})"
                            )
                            
                            await agent.move_to(
                                side_pose,
                                mode=0,
                                acceptable_precision=0.3,
                                speed_ratio=0.8  # 提高速度，快速让出路径
                            )
                            
                            logger.info(f"Robot {robot_id} moved to side avoidance point")
                            
                            # 等待一小段时间让机器人到达避让点
                            await asyncio.sleep(1.0)
                            
                            # 验证避让是否成功
                            new_state = await self.robot_manager.get_robot_state(robot_id)
                            if new_state and new_state.pose:
                                still_blocking = False
                                for task in blocking_tasks:
                                    executing_robot_state = await self.robot_manager.get_robot_state(task.robot_id)
                                    if executing_robot_state and executing_robot_state.pose:
                                        dx = new_state.pose.x - executing_robot_state.pose.x
                                        dy = new_state.pose.y - executing_robot_state.pose.y
                                        distance = math.sqrt(dx*dx + dy*dy)
                                        if distance < 1.4:  # 仍然阻塞
                                            still_blocking = True
                                            logger.warning(
                                                f"Robot {robot_id} still blocking after side avoidance "
                                                f"(distance={distance:.2f}m < 1.4m). Sending robot back to charging dock."
                                            )
                                            break
                                
                                if still_blocking:
                                    # 避让失败，直接回桩
                                    try:
                                        go_home_result = await agent.go_home()
                                        logger.info(
                                            f"Robot {robot_id} sent back to charging dock as side avoidance failed. "
                                            f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to send robot {robot_id} back to charging dock: {e}")
                                else:
                                    logger.info(f"Robot {robot_id} successfully avoided blocking position (side)")
                            
                            # 从避让列表中移除（避让动作已完成）
                            self.completed_robots_avoiding.discard(robot_id)
                        else:
                            # 无法找到有效的侧移避让点，直接回桩
                            logger.warning(
                                f"Cannot find valid side avoidance point for robot {robot_id}. "
                                f"Sending robot back to charging dock instead."
                            )
                            try:
                                go_home_result = await agent.go_home()
                                logger.info(
                                    f"Robot {robot_id} sent back to charging dock as no valid side avoidance point found. "
                                    f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                                )
                                self.completed_robots_avoiding.discard(robot_id)
                            except Exception as e:
                                logger.error(f"Failed to send robot {robot_id} back to charging dock: {e}")
                    else:
                        # 无法计算避让方向，直接回桩
                        logger.warning(
                            f"Cannot calculate avoidance direction for robot {robot_id}. "
                            f"No valid paths found. Sending robot back to charging dock."
                        )
                        try:
                            go_home_result = await agent.go_home()
                            logger.info(
                                f"Robot {robot_id} sent back to charging dock as no valid avoidance direction found. "
                                f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                            )
                            self.completed_robots_avoiding.discard(robot_id)
                        except Exception as e:
                            logger.error(f"Failed to send robot {robot_id} back to charging dock: {e}")
                else:
                    # 没有阻塞任务，但被调用到这里，直接回桩（安全起见）
                    logger.warning(f"No blocking tasks found for robot {robot_id}, but avoidance was triggered. Sending robot back to charging dock.")
                    try:
                        go_home_result = await agent.go_home()
                        logger.info(
                            f"Robot {robot_id} sent back to charging dock (no blocking tasks but avoidance triggered). "
                            f"Action ID: {go_home_result.action_id if go_home_result else 'None'}"
                        )
                        self.completed_robots_avoiding.discard(robot_id)
                    except Exception as e:
                        logger.error(f"Failed to send robot {robot_id} back to charging dock: {e}")
                    
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

