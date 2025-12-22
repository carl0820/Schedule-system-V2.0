"""
任务管理API
"""
import logging
import math
import time
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Body
from typing import List, Optional, Dict, Any, Annotated
import json
from app.models.task import Task, TaskCreate, TaskStatus, MultiActionTaskCreate, TaskCreateResponse
from app.services.task_scheduler import TaskScheduler, get_task_scheduler
from app.services.map_manager import MapManager, get_map_manager
from app.services.robot_manager import RobotManager, get_robot_manager
from app.services.restricted_area_traffic_manager import RestrictedAreaTrafficManager
# 认证已移除，所有API端点无需授权即可调用

router = APIRouter()
logger = logging.getLogger(__name__)




@router.post("/", response_model=Task, summary="创建单点任务")
async def create_task(
    task: TaskCreate,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
   创建单点任务
    
    返回完整的任务信息，包括 task_id、status、created_at 等。
    使用返回的 task_id 可以查询任务状态：GET /api/tasks/{task_id}
    
    **重要说明：**
    - 不需要配置 `start_pose`（已废弃），系统会根据机器人当前位置自动分配任务
    - 只需指定 `target_pose`（目标位置）即可
    - 系统会自动选择距离目标最近的机器人执行任务
    
    Args:
        task: 任务创建请求（只需指定target_pose，无需start_pose）
    
    Returns:
        Task: 创建的任务对象，包含 task_id、status、created_at 等字段
    """
    logger.info(f"API: Received single-point task creation request: target_pose={task.target_pose}, poi_name={task.poi_name}, priority={task.priority}")
    try:
        
        # 验证地图是否已加载
        map_info = map_manager.get_map_info()
        if not map_info:
            raise HTTPException(
                status_code=400,
                detail="Map not loaded. Please load the map first using POST /api/maps/load"
            )
        
        # 验证目标位置是否在地图范围内
        if task.target_pose:
            if not map_manager.is_valid_coordinate(task.target_pose.x, task.target_pose.y):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target position ({task.target_pose.x}, {task.target_pose.y}) is outside the map bounds"
                )
            
            # 检查目标位置是否为障碍物
            if map_manager.is_obstacle(task.target_pose.x, task.target_pose.y):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target position ({task.target_pose.x}, {task.target_pose.y}) is an obstacle"
                )
        
        # 创建任务
        logger.info("API: Starting task creation in scheduler...")
        api_start_time = time.time()
        try:
            created_task = await task_scheduler.create_task(task)
            api_elapsed = time.time() - api_start_time
            logger.info(f"API: Single-point task created successfully: task_id={created_task.task_id}, status={created_task.status.value}, API elapsed={api_elapsed:.3f}s")
        except Exception as e:
            logger.error(f"API: Task creation failed in scheduler: {e}", exc_info=True)
            raise
        
        # 确保返回的任务包含 task_id
        if not created_task.task_id:
            raise HTTPException(status_code=500, detail="Task created but task_id is missing")
        
        # 确保 task_id 在响应中（显式验证）
        logger.debug(f"Returning task with task_id: {created_task.task_id}, status: {created_task.status}")
        
        # 返回 Task 对象，FastAPI 会自动序列化为 JSON，包含所有字段包括 task_id
        return created_task
    except HTTPException as e:
        logger.warning(f"API: Task creation rejected: {e.status_code} - {e.detail}")
        raise
    except Exception as e:
        logger.error(f"API: Failed to create task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: str,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler)
):
    """
    获取任务信息
    
    Args:
        task_id: 任务ID
    """
    try:
        task = await task_scheduler.get_task(task_id)
        if task:
            return task
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=Dict[str, Any])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    robot_id: Optional[str] = None,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    sort_order: str = Query("desc", description="排序方式: asc(升序) 或 desc(降序)"),
    task_scheduler: TaskScheduler = Depends(get_task_scheduler),
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取任务列表（包含POI名称映射，支持分页）
    
    Args:
        status: 任务状态过滤
        robot_id: 机器人ID过滤
        page: 页码（从1开始）
        page_size: 每页数量（1-100）
        start_date: 开始日期过滤 (YYYY-MM-DD)
        end_date: 结束日期过滤 (YYYY-MM-DD)
        sort_order: 排序方式 (asc/desc)
    """
    try:
        # 优化：不在API请求时同步更新任务状态，避免阻塞响应
        # 任务状态更新在后台循环中自动进行，这里直接获取当前状态即可
        # await task_scheduler._update_executing_tasks()  # 注释掉，避免阻塞
        
        # 优化：使用数据库层面的分页，避免加载所有任务
        # 先获取总数（用于分页信息），然后只加载当前页的任务
        import asyncio
        import math
        
        # 计算分页参数
        limit = page_size
        offset = (page - 1) * page_size
        
        # 添加超时保护，确保即使数据库查询很慢也能快速返回
        try:
            # 并发获取总数和当前页任务（提高响应速度）
            # 增加超时时间到8秒，给数据库查询和转换留出足够时间
            total_count, tasks = await asyncio.wait_for(
                asyncio.gather(
                    task_scheduler.count_tasks(status, robot_id),
                    task_scheduler.list_tasks(status, robot_id, limit=limit, offset=offset)
                ),
                timeout=8.0  # 8秒超时，给数据库查询和任务转换留出足够时间
            )
        except asyncio.TimeoutError:
            logger.error("Task list query timeout, returning empty list")
            tasks = []
            total_count = 0
        
        # 优化：POI查询改为可选，如果超时则跳过（不影响任务列表显示）
        async def get_all_pois_data():
            """获取所有POI点数据（合并查询，带超时控制，快速失败）"""
            import asyncio
            import math
            
            pois_map = {}  # 位置 -> 显示名称
            pois_dict = {}  # POI ID -> 显示名称
            robot_ids = robot_manager.list_robots()
            
            async def get_robot_pois(robot_id: str):
                """从单个机器人获取POI（带超时，快速失败）"""
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        # 缩短超时时间到0.5秒，快速失败
                        pois = await asyncio.wait_for(
                            agent.get_all_pois(),
                            timeout=0.5
                        )
                        for poi in pois:
                            # 构建ID映射
                            if poi.id not in pois_dict:
                                pois_dict[poi.id] = poi.metadata.get("display_name", poi.id) if poi.metadata else poi.id
                            
                            # 构建位置映射
                            if poi.pose:
                                # 使用位置作为键（精确到0.1米）
                                key = f"{poi.pose.x:.1f}_{poi.pose.y:.1f}"
                                if key not in pois_map:
                                    pois_map[key] = poi.metadata.get("display_name", poi.id) if poi.metadata else poi.id
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting POIs from robot {robot_id} (0.5s)")
                except Exception as e:
                    logger.debug(f"Failed to get POIs for robot {robot_id}: {e}")
            
            # 并发获取所有机器人的POI，但设置总体超时为2秒
            if robot_ids:
                try:
                    poi_tasks = [get_robot_pois(robot_id) for robot_id in robot_ids]
                    await asyncio.wait_for(
                        asyncio.gather(*poi_tasks, return_exceptions=True),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("POI query timeout (2.0s), continuing without POI data")
            
            return pois_map, pois_dict
        
        # POI查询改为可选，如果失败不影响任务列表返回
        # 优化：暂时跳过POI查询以提高响应速度（POI信息可以在任务详情中单独获取）
        # POI查询可能很慢，导致API超时，先确保任务列表能快速返回
        pois_map, pois_dict = {}, {}
        logger.debug("Skipping POI query for faster response")
        
        def find_poi_name(x: float, y: float) -> Optional[str]:
            """根据坐标查找POI名称"""
            import math
            # 允许0.1米的误差范围
            for key, name in pois_map.items():
                parts = key.split('_')
                if len(parts) == 2:
                    poi_x = float(parts[0])
                    poi_y = float(parts[1])
                    distance = math.sqrt((x - poi_x) ** 2 + (y - poi_y) ** 2)
                    if distance < 0.1:  # 0.1米范围内认为是同一个POI
                        return name
            return None
        
        # 时间筛选（在转换为字典之前进行，直接使用datetime对象比较，更可靠）
        from datetime import datetime, date
        if start_date or end_date:
            try:
                start_dt = None
                end_dt = None
                
                if start_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                
                if end_date:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                
                # 在Task对象级别进行筛选
                filtered_tasks = []
                for task in tasks:
                    if not task.created_at:
                        # 如果没有创建时间，跳过该任务（不包含在结果中）
                        continue
                    
                    task_date = task.created_at
                    task_dt = None
                    
                    # 处理datetime对象（最常见的情况）
                    if isinstance(task_date, datetime):
                        # 如果是带时区的datetime，转换为本地时间（naive datetime）
                        if task_date.tzinfo is not None:
                            # 移除时区信息，使用本地时间进行比较
                            task_dt = task_date.replace(tzinfo=None)
                        else:
                            task_dt = task_date
                    elif isinstance(task_date, str):
                        # 如果是字符串，尝试解析
                        try:
                            # 尝试解析ISO格式字符串
                            if "T" in task_date:
                                # 处理ISO格式，移除时区信息
                                date_str = task_date.replace("Z", "")
                                if "+" in date_str:
                                    date_str = date_str.split("+")[0]
                                elif date_str.count("-") >= 5:  # 有时区偏移，如 2024-01-01T12:00:00-05:00
                                    date_str = date_str.rsplit("-", 2)[0]
                                
                                if "." in date_str:
                                    # 有微秒，如 2024-01-01T12:00:00.123456
                                    parts = date_str.split(".")
                                    task_dt = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%S")
                                else:
                                    # 无微秒，如 2024-01-01T12:00:00
                                    task_dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                            else:
                                # 简单日期格式，如 2024-01-01
                                task_dt = datetime.strptime(task_date.split()[0], "%Y-%m-%d")
                        except Exception as e:
                            logger.debug(f"Failed to parse created_at for task {task.task_id}: {task_date}, error: {e}")
                            continue
                    else:
                        # 其他类型，跳过
                        logger.debug(f"Unexpected created_at type for task {task.task_id}: {type(task_date)}")
                        continue
                    
                    # 进行日期比较
                    if task_dt:
                        if start_dt and task_dt < start_dt:
                            continue
                        if end_dt and task_dt > end_dt:
                            continue
                        filtered_tasks.append(task)
                
                original_count = len(tasks)
                tasks = filtered_tasks
                logger.debug(f"Time filter applied: start_date={start_date}, end_date={end_date}, filtered {len(filtered_tasks)} tasks from {original_count} total")
            except Exception as e:
                logger.warning(f"Invalid date format: start_date={start_date}, end_date={end_date}, error: {e}")
        
        # 将Task对象转换为字典，并添加target_poi_name字段
        # 注意：由于使用了数据库层面的分页，tasks已经是当前页的数据（最多20条）
        # 不需要再限制处理数量，直接处理即可
        
        import time
        dict_start = time.time()
        
        # 预先收集所有需要获取充电桩坐标的GO_HOME任务，并发获取
        go_home_tasks = {}
        for task in tasks:
            if task.is_multi_action and task.actions:
                last_action = task.actions[-1] if task.actions else None
                if last_action:
                    last_action_type = last_action.action_type if hasattr(last_action, 'action_type') else last_action.get('action_type')
                    if last_action_type == "go_home" and task.robot_id:
                        go_home_tasks[task.task_id] = task.robot_id
        
        # 并发获取所有充电桩坐标（带超时控制）
        dock_poses = {}
        if go_home_tasks:
            async def get_dock_pose(robot_id, task_id):
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        return task_id, await asyncio.wait_for(
                            agent.get_home_dock_pose(),
                            timeout=1.5  # 1.5秒超时，避免累积超时
                        )
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting home dock pose for robot {robot_id} (task {task_id})")
                except Exception as e:
                    logger.debug(f"Failed to get home dock pose for robot {robot_id} (task {task_id}): {e}")
                return task_id, None
            
            # 并发获取所有充电桩坐标
            dock_results = await asyncio.gather(*[
                get_dock_pose(robot_id, task_id) 
                for task_id, robot_id in go_home_tasks.items()
            ], return_exceptions=True)
            
            for result in dock_results:
                if isinstance(result, tuple) and len(result) == 2:
                    task_id, dock_pose = result
                    if dock_pose:
                        dock_poses[task_id] = dock_pose
        
        result = []
        for task in tasks:
            # 对于多动作任务，检查动作序列中是否有使用POI的动作
            target_poi_name = None
            # 初始化 last_move_action，确保在所有代码路径中都有定义
            last_move_action = None
            
            if task.is_multi_action and task.actions:
                # 检查最后一个动作是否是GO_HOME
                last_action = task.actions[-1] if task.actions else None
                last_action_type = None
                if last_action:
                    last_action_type = last_action.action_type if hasattr(last_action, 'action_type') else last_action.get('action_type')
                
                # 如果最后一个动作是GO_HOME，使用预先获取的充电桩坐标
                if last_action_type == "go_home":
                    # GO_HOME动作的目标是充电桩，使用预先获取的充电桩坐标
                    dock_pose = dock_poses.get(task.task_id)
                    
                    # 如果获取到充电桩坐标，使用实际坐标；否则使用默认值(0,0,0)
                    if dock_pose:
                        if task.target_pose:
                            task.target_pose.x = dock_pose.x
                            task.target_pose.y = dock_pose.y
                            task.target_pose.yaw = dock_pose.yaw
                        else:
                            from app.models.robot import Pose
                            task.target_pose = Pose(x=dock_pose.x, y=dock_pose.y, yaw=dock_pose.yaw)
                        logger.debug(
                            f"Task {task.task_id} GO_HOME: using actual dock pose "
                            f"({dock_pose.x:.2f}, {dock_pose.y:.2f}, {dock_pose.yaw:.2f}) for robot {task.robot_id}"
                        )
                    else:
                        # 如果无法获取充电桩坐标，使用默认值(0,0,0)
                        if task.target_pose:
                            task.target_pose.x = 0.0
                            task.target_pose.y = 0.0
                            task.target_pose.yaw = 0.0
                        else:
                            from app.models.robot import Pose
                            task.target_pose = Pose(x=0.0, y=0.0, yaw=0.0)
                        logger.debug(
                            f"Task {task.task_id} GO_HOME: using default dock pose (0,0,0) "
                            f"(robot {task.robot_id} dock pose not available)"
                        )
                    target_poi_name = "充电桩"  # 标记为充电桩
                    # 对于GO_HOME动作，last_move_action保持为None
                    last_move_action = None
                else:
                    # 查找最后一个MOVE_TO动作（排除GO_HOME，用于显示目标位置）
                    # 确保在循环前last_move_action已初始化为None
                    last_move_action = None
                    for action in reversed(task.actions):
                        # action可能是ActionItem对象或字典
                        action_type = action.action_type if hasattr(action, 'action_type') else action.get('action_type')
                        # 只查找MOVE_TO动作，排除GO_HOME（因为GO_HOME不是目标点）
                        if action_type == "move_to":
                            last_move_action = action
                            break
                
                # 处理 last_move_action（无论是否找到）
                if last_move_action:
                    # 检查是否有poi_name
                    poi_name = None
                    if hasattr(last_move_action, 'poi_name'):
                        poi_name = last_move_action.poi_name
                    elif isinstance(last_move_action, dict):
                        poi_name = last_move_action.get('poi_name')
                    
                    if poi_name:
                        # 优先使用保存的显示名称（如果存在），否则从POI字典中获取
                        poi_display_name = None
                        if hasattr(last_move_action, 'poi_display_name'):
                            poi_display_name = last_move_action.poi_display_name
                        elif isinstance(last_move_action, dict):
                            poi_display_name = last_move_action.get('poi_display_name')
                        
                        if poi_display_name and poi_display_name.strip():
                            # 使用保存的显示名称
                            target_poi_name = poi_display_name
                        elif pois_dict:
                            # 如果机器人在线，从POI字典中获取显示名称
                            target_poi_name = pois_dict.get(poi_name, poi_name)
                        else:
                            # 如果机器人离线且没有保存的显示名称，至少显示POI ID
                            target_poi_name = poi_name
                    else:
                        # 如果动作没有poi_name，但有target_pose，使用它
                        if hasattr(last_move_action, 'target_pose') and last_move_action.target_pose:
                            task.target_pose = last_move_action.target_pose
                        elif isinstance(last_move_action, dict) and last_move_action.get('target_pose'):
                            from app.models.robot import Pose
                            pose_data = last_move_action.get('target_pose')
                            if isinstance(pose_data, dict):
                                task.target_pose = Pose(**pose_data)
                
                # 如果没有找到POI，尝试通过坐标查找（只有当target_pose不是默认值时）
                if not target_poi_name and task.target_pose:
                    # 只有当坐标不是(0,0)时才尝试通过坐标查找
                    if task.target_pose.x != 0.0 or task.target_pose.y != 0.0:
                        target_poi_name = find_poi_name(task.target_pose.x, task.target_pose.y)
            else:
                # 普通任务：通过坐标查找POI名称
                if task.target_pose:
                    target_poi_name = find_poi_name(task.target_pose.x, task.target_pose.y)
            
            # 将Task对象转换为字典
            task_dict = task.dict()
            # 添加target_poi_name字段
            task_dict["target_poi_name"] = target_poi_name
            result.append(task_dict)
        
        # 排序
        if sort_order == "asc":
            result.sort(key=lambda t: t.get("created_at", "") or "")
        else:  # desc
            result.sort(key=lambda t: t.get("created_at", "") or "", reverse=True)
        
        # 注意：由于使用了数据库层面的分页，result已经是当前页的数据
        # 但如果有时间筛选，需要重新计算总数和分页
        # 为了性能，统计信息只基于当前页（如果需要完整统计，需要额外查询）
        
        # 如果有时间筛选，需要重新计算总数（简化处理：使用当前页数据估算）
        # 实际总数应该基于数据库查询，但为了性能暂时使用当前页数据
        if start_date or end_date:
            # 有时间筛选时，总数需要重新计算（这里简化处理）
            # 实际应该从数据库查询，但为了性能暂时使用当前页数据
            total = len(result)
        else:
            # 没有时间筛选时，使用数据库查询的总数
            total = total_count
        
        # 计算统计信息（基于当前页数据，如果需要完整统计需要额外查询）
        stats = {
            "total": total,
            "pending": sum(1 for t in result if t.get("status") == "pending"),
            "assigned": sum(1 for t in result if t.get("status") == "assigned"),
            "executing": sum(1 for t in result if t.get("status") == "executing"),
            "completed": sum(1 for t in result if t.get("status") == "completed"),
            "failed": sum(1 for t in result if t.get("status") == "failed"),
            "cancelled": sum(1 for t in result if t.get("status") == "cancelled")
        }
        
        # 分页处理（result已经是当前页的数据，但如果有时间筛选需要重新分页）
        if start_date or end_date:
            # 有时间筛选时，需要重新分页
            total_pages = math.ceil(total / page_size) if total > 0 else 1
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_tasks = result[start_idx:end_idx]
        else:
            # 没有时间筛选时，result已经是分页后的数据
            total_pages = math.ceil(total / page_size) if total > 0 else 1
            paginated_tasks = result
        
        return {
            "tasks": paginated_tasks,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            },
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{task_id}", response_model=dict)
async def cancel_task(
    task_id: str,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler)
):
    """
    取消任务
    
    Args:
        task_id: 任务ID
    """
    try:
        success = await task_scheduler.cancel_task(task_id)
        if success:
            return {"message": "Task cancelled successfully"}
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/multi-action", response_model=Task)
async def create_multi_action_task(
    request_body: Dict[str, Any] = Body(
        ...,
        description="多动作任务创建请求。支持两种格式：1) 直接发送actions和priority；2) 发送包含value字段的Swagger示例格式（自动提取value内容）",
        example={
            "actions": [
                {
                    "action_type": "move_to",
                    "target_pose": {
                        "x": 3.8,
                        "y": -2.9,
                        "z": 0.0,
                        "yaw": 0.0,
                        "pitch": 0.0,
                        "roll": 0.0
                    },
                    "acceptable_precision": 0.3,
                    "speed_ratio": 1.0,
                    "mode": 0,
                    "flags": ["precise", "with_yaw"],
                    "fail_retry_count": 0
                },
                {
                    "action_type": "wait",
                    "wait_duration": 10.0
                }
            ],
            "priority": 1
        }
    ),
    task_scheduler: TaskScheduler = Depends(get_task_scheduler),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    创建多动作任务
    
    返回完整的任务信息，包括 task_id、status、created_at 等。
    使用返回的 task_id 可以查询任务状态：GET /api/tasks/{task_id}
    
    **重要说明：**
    - 不需要配置 `start_pose`（已废弃），系统会根据机器人当前位置自动分配任务
    - 只需指定 `actions`（动作序列）即可
    - 系统会自动选择距离目标最近的机器人执行任务
    
    **支持的动作类型：**
    - **move_to**: 移动到目标点
      - 方式1（推荐）：使用 `target_pose` 指定坐标，简单可靠
      - 方式2：使用 `poi_name` 指定POI名称（需要先查询POI：GET /api/maps/pois）
      - **move_options 配置参数**（可选）：
        - `mode`: 导航模式（0:Free navigation, 1:Strict Track, 2:Track priority），默认 0
        - `flags`: 标志列表（如：`["precise", "with_yaw"]`），默认 `[]`
        - `fail_retry_count`: 失败重试次数，默认 0
        - `acceptable_precision`: 到达精度（米），默认 0.3
        - `speed_ratio`: 速度比例，默认 1.0
    - **wait**: 等待指定时间（需要 `wait_duration` > 0，单位：秒）
    - **go_home**: 回桩（不需要额外参数）
    
    **注意事项：**
    - 如果使用 `poi_name`，请确保POI名称正确（可通过 GET /api/maps/pois 查询）
    - 如果同时提供 `target_pose` 和 `poi_name`，系统优先使用 `poi_name` 进行POI导航
    - 建议使用 `target_pose` 进行坐标导航，更简单可靠，不会出现 POI_NOT_FOUND 错误
    - `priority` 可选，如果不指定则系统自动计算（1-4，1最低，4最高）
    
    **请求格式：**
    - 方式1（推荐）：直接发送 `actions` 和 `priority`
    - 方式2：发送包含 `value` 字段的Swagger示例格式（自动提取 `value` 内容）
    
    **示例：**
    查看下方 "Examples" 下拉菜单，选择不同的示例进行测试。
    
    Args:
        task: 多动作任务创建请求（支持直接格式或包含value字段的格式）
    
    Returns:
        Task: 创建的任务对象，包含 task_id、status、created_at 等字段
    """
    api_start = time.time()
    
    try:
        # 支持从Swagger示例格式中提取value字段
        if "value" in request_body and isinstance(request_body["value"], dict):
            # 如果请求体包含value字段（Swagger示例格式），提取其内容
            task_data = request_body["value"]
            logger.debug("Extracting task data from 'value' field (Swagger example format)")
        else:
            # 直接使用请求体（标准格式）
            task_data = request_body
        
        # 将dict转换为MultiActionTaskCreate对象
        try:
            task = MultiActionTaskCreate(**task_data)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid request format: {str(e)}. Please check that 'actions' is a list and all required fields are present."
            )
        
        logger.info(f"API: Received multi-action task creation request with {len(task.actions)} actions, priority={task.priority}")
        
        # 最小化验证：只检查地图是否已加载（快速检查）
        map_info = map_manager.get_map_info()
        if not map_info:
            raise HTTPException(
                status_code=400,
                detail="Map not loaded. Please load the map first using POST /api/maps/load"
            )
        
        # 快速验证：只检查动作类型和必需参数，不验证坐标（坐标验证在任务分配时进行）
        for i, action in enumerate(task.actions):
            if action.action_type == "move_to":
                # move_to动作必须提供target_pose或poi_name（快速检查）
                has_target_pose = action.target_pose is not None
                has_poi_name = action.poi_name is not None and action.poi_name.strip() != ""
                
                if not has_target_pose and not has_poi_name:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Action {i}: move_to requires either target_pose or poi_name"
                    )
                
                # 坐标验证移到任务分配时进行（不在这里阻塞）
                # POI验证也移到任务分配时进行
                # 【修复】不要将poi_name（可能是UUID）直接赋值给poi_display_name
                # 让调度器在执行时自动解析POI的display_name
            elif action.action_type == "wait":
                if action.wait_duration is None or action.wait_duration <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Action {i}: wait requires wait_duration > 0"
                    )
            elif action.action_type == "go_home":
                pass  # 回桩不需要额外参数
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Action {i}: unknown action type {action.action_type}"
                )
        
        # 立即创建任务（不等待任何耗时操作）
        logger.info(f"API: Calling task_scheduler.create_multi_action_task (elapsed: {time.time() - api_start:.3f}s)")
        logger.info("API: Starting multi-action task creation in scheduler...")
        try:
            created_task = await task_scheduler.create_multi_action_task(task)
            api_elapsed = time.time() - api_start
            logger.info(f"API: Multi-action task created successfully: task_id={created_task.task_id}, status={created_task.status.value}, {len(task.actions)} actions, elapsed={api_elapsed:.3f}s")
        except Exception as e:
            logger.error(f"API: Multi-action task creation failed in scheduler: {e}", exc_info=True)
            raise
        
        # 确保返回的任务包含 task_id
        if not created_task.task_id:
            raise HTTPException(status_code=500, detail="Task created but task_id is missing")
        
        # 确保 task_id 在响应中（显式验证）
        logger.debug(f"Returning multi-action task with task_id: {created_task.task_id}, status: {created_task.status}")
        
        # 返回 Task 对象，FastAPI 会自动序列化为 JSON，包含所有字段包括 task_id
        return created_task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_elapsed = time.time() - api_start
        logger.error(f"API: Failed to create multi-action task after {api_elapsed:.3f}s: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create multi-action task: {str(e)}")


@router.post("/{task_id}/reset", response_model=Task)
async def reset_task(
    task_id: str,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler)
):
    """
    重置失败的任务状态为PENDING，允许重新调度
    
    Args:
        task_id: 任务ID
    """
    try:
        task = await task_scheduler.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # 重置任务状态
        if task.status == TaskStatus.FAILED:
            task.status = TaskStatus.PENDING
            task.error_message = None
            task.completed_at = None
            task.retry_count = 0  # 重置重试计数
            if task.is_multi_action:
                task.current_action_index = 0  # 重置动作索引
            # 持久化到文件（通过task_scheduler的内部方法）
            task_scheduler._save_tasks_to_file()
            logger.info(f"Task {task_id} reset to PENDING status")
            return task
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Task {task_id} is not in FAILED status, cannot reset"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/force-unlock-restricted-area", response_model=dict, summary="强制解锁限行区域中的机器人")
async def force_unlock_restricted_area(
    task_scheduler: TaskScheduler = Depends(get_task_scheduler)
):
    """
    强制解锁限行区域中卡住的机器人
    
    这个API会：
    1. 强制检查并解锁所有限行区域的阻塞
    2. 清除所有等待状态，让机器人继续执行任务
    3. 触发容量检查，让等待的机器人可以通行
    
    用于解决机器人死锁在限行区域的问题。
    
    Returns:
        dict: 解锁结果，包含解锁的机器人数量和状态
    """
    try:
        logger.info("[API] Force unlock restricted area requested")
        
        restricted_area_manager = task_scheduler.restricted_area_traffic_manager
        
        # 强制检查并解锁所有限行区域的阻塞（使用force_unlock=True立即解锁）
        await restricted_area_manager._check_and_resolve_capacity_overflow(force_unlock=True)
        await restricted_area_manager._check_direct_blocking_in_restricted_area(force_unlock=True)
        await restricted_area_manager._check_stuck_robots_in_restricted_area(force_unlock=True)
        
        # 强制清除所有等待状态，让机器人继续执行任务
        waiting_robots = list(restricted_area_manager.robot_waiting_status.keys())
        cleared_waiting = len(waiting_robots)
        if waiting_robots:
            logger.warning(
                f"[API] Found {cleared_waiting} robots in waiting status: {waiting_robots}. "
                f"Clearing waiting status to allow task continuation..."
            )
            for robot_id in waiting_robots:
                if robot_id in restricted_area_manager.robot_waiting_status:
                    del restricted_area_manager.robot_waiting_status[robot_id]
        
        # 强制触发容量检查，让等待的机器人可以通行
        await restricted_area_manager.check_waiting_robots()
        
        # 验证并清理不在限行区域内的机器人
        # 重要：先检查所有机器人的实际位置，然后统一释放
        robots_to_release = []
        restricted_areas = restricted_area_manager.map_manager.restricted_areas
        
        logger.info(f"[API] Starting validation: {len(restricted_area_manager.area_traffic)} areas in traffic")
        # 遍历所有限行区域的通行列表
        for area_id, traffic in list(restricted_area_manager.area_traffic.items()):
            logger.info(f"[API] Area {area_id}: {len(traffic['robots'])} robots in traffic list: {traffic['robots']}")
            if not traffic.get('robots'):
                logger.info(f"[API] Area {area_id} has no robots in traffic list, skipping")
                continue
            for robot_id in list(traffic['robots']):
                try:
                    robot_state = await task_scheduler.robot_manager.get_robot_state(robot_id, force_update=True)
                    if robot_state and robot_state.pose:
                        # 检查机器人是否真的在限行区域内
                        is_in_area = False
                        area_found = False
                        for area in restricted_areas:
                            if area.get("id") == area_id:
                                area_found = True
                                area_data = area.get("area", {})
                                if area_data:
                                    start = area_data.get("start", {})
                                    end = area_data.get("end", {})
                                    half_width = area_data.get("half_width", 0.5)
                                    if start and end:
                                        is_in_area = restricted_area_manager.is_point_in_restricted_area(
                                            robot_state.pose, start, end, half_width
                                        )
                                        if is_in_area:
                                            logger.info(
                                                f"[API] Robot {robot_id} is confirmed in area {area_id} "
                                                f"(pose: {robot_state.pose.x:.2f}, {robot_state.pose.y:.2f})"
                                            )
                                        else:
                                            logger.warning(
                                                f"[API] Robot {robot_id} is NOT in area {area_id} "
                                                f"(pose: {robot_state.pose.x:.2f}, {robot_state.pose.y:.2f}, "
                                                f"area_start=({start.get('x', 0):.2f}, {start.get('y', 0):.2f}), "
                                                f"area_end=({end.get('x', 0):.2f}, {end.get('y', 0):.2f}), "
                                                f"half_width={half_width})"
                                            )
                                        break
                                else:
                                    logger.warning(f"[API] Area {area_id} has no area_data")
                        if not area_found:
                            logger.warning(f"[API] Area {area_id} not found in restricted_areas, will release robot {robot_id}")
                            robots_to_release.append((robot_id, area_id))
                        elif not is_in_area:
                            # 机器人不在限行区域内，应该释放
                            robots_to_release.append((robot_id, area_id))
                            logger.warning(
                                f"[API] Robot {robot_id} is in traffic list for area {area_id} "
                                f"but NOT actually in the area (pose: {robot_state.pose.x:.2f}, {robot_state.pose.y:.2f}). "
                                f"Will release from area."
                            )
                    else:
                        # 无法获取机器人状态，也释放（可能是机器人离线或状态异常）
                        logger.warning(
                            f"[API] Cannot get robot state for {robot_id}, will release from area {area_id}"
                        )
                        robots_to_release.append((robot_id, area_id))
                except Exception as e:
                    logger.error(f"[API] Failed to check robot {robot_id} position: {e}, will release from area {area_id}", exc_info=True)
                    robots_to_release.append((robot_id, area_id))
        
        # 释放不在限行区域内的机器人
        logger.info(f"[API] Found {len(robots_to_release)} robots to release: {robots_to_release}")
        for robot_id, area_id in robots_to_release:
            try:
                logger.info(f"[API] Releasing robot {robot_id} from area {area_id}...")
                await restricted_area_manager.release_robot_from_area(robot_id, area_id)
                logger.info(f"[API] Successfully released robot {robot_id} from area {area_id}")
            except Exception as e:
                logger.error(f"[API] Failed to release robot {robot_id} from area {area_id}: {e}", exc_info=True)
        
        # 检查P3的状态（用于调试）
        p3_in_traffic = any('P3' in traffic['robots'] for traffic in restricted_area_manager.area_traffic.values())
        p3_in_waiting = 'P3' in restricted_area_manager.robot_waiting_status
        logger.info(
            f"[API] P3 status: in_traffic_list={p3_in_traffic}, "
            f"in_waiting_status={p3_in_waiting}, "
            f"waiting_status={restricted_area_manager.robot_waiting_status.get('P3') if p3_in_waiting else None}"
        )
        
        # 如果P3在等待状态中但不在通行列表中，尝试将其移到通行列表
        if p3_in_waiting and not p3_in_traffic:
            waiting_info = restricted_area_manager.robot_waiting_status.get('P3')
            if waiting_info:
                area_id = waiting_info.get('area_id')
                task_id = waiting_info.get('original_task_id')
                logger.warning(
                    f"[API] P3 is in waiting status for area {area_id} but not in traffic list. "
                    f"Task: {task_id}. Will try to add to traffic list."
                )
                # 检查限行区域是否有空位
                if area_id in restricted_area_manager.area_traffic:
                    traffic = restricted_area_manager.area_traffic[area_id]
                    capacity = traffic.get('capacity', 1)
                    if len(traffic['robots']) < capacity:
                        # 有空位，将P3移到通行列表
                        traffic['robots'].append('P3')
                        restricted_area_manager.robot_enter_time['P3'] = {
                            'area_id': area_id,
                            'enter_time': datetime.now()
                        }
                        logger.info(
                            f"[API] Added P3 to traffic list for area {area_id} "
                            f"(capacity: {capacity}, current: {len(traffic['robots'])})"
                        )
        
        # 强制触发任务恢复，确保在通行列表中的机器人恢复任务
        await task_scheduler._check_and_resume_waiting_robots()
        
        # 强制检查POI等待点（确保POI已加载）
        if not restricted_area_manager.poi_waiting_points:
            await restricted_area_manager.load_poi_waiting_points()
        
        # 检查P3的任务状态（用于调试）
        p3_tasks = [task for task in task_scheduler.tasks.values() if task.robot_id == "P3"]
        p3_task_info = []
        for task in p3_tasks:
            p3_task_info.append({
                "task_id": task.task_id,
                "status": task.status.value,
                "action_id": task.action_id,
                "current_action_index": task.current_action_index if hasattr(task, 'current_action_index') else None,
                "is_multi_action": task.is_multi_action if hasattr(task, 'is_multi_action') else False
            })
            logger.info(
                f"[API] P3 task {task.task_id}: status={task.status.value}, "
                f"action_id={task.action_id}, in_traffic_list={any('P3' in traffic['robots'] for traffic in restricted_area_manager.area_traffic.values())}"
            )
        
        # 统计限行区域中的机器人数量（在清理后）
        robots_in_areas = {}
        for area_id, traffic in restricted_area_manager.area_traffic.items():
            robots_in_areas[area_id] = {
                "robots": traffic['robots'].copy(),
                "count": len(traffic['robots']),
                "capacity": traffic.get('capacity', 0)
            }
        
        logger.info(f"[API] Force unlock completed: cleared {cleared_waiting} waiting robots, released {len(robots_to_release)} robots not in areas")
        
        return {
            "status": "success",
            "cleared_waiting_robots": cleared_waiting,
            "waiting_robots": waiting_robots,
            "robots_in_restricted_areas": robots_in_areas,
            "released_robots": [{"robot_id": r[0], "area_id": r[1]} for r in robots_to_release],
            "p3_tasks": p3_task_info,
            "message": f"Force unlock completed. Cleared {cleared_waiting} waiting robots, released {len(robots_to_release)} robots not in areas."
        }
    except Exception as e:
        logger.error(f"[API] Failed to force unlock restricted area: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to force unlock: {str(e)}")

