"""
任务管理API
"""
import logging
import math
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional, Dict, Any
from app.models.task import Task, TaskCreate, TaskStatus, MultiActionTaskCreate
from app.services.task_scheduler import TaskScheduler, get_task_scheduler
from app.services.map_manager import MapManager, get_map_manager
from app.services.robot_manager import RobotManager, get_robot_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=Task)
async def create_task(
    task: TaskCreate,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    创建任务
    
    Args:
        task: 任务创建请求
    """
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
        import time
        api_start_time = time.time()
        created_task = await task_scheduler.create_task(task)
        api_elapsed = time.time() - api_start_time
        logger.info(f"Single-point task created via API: {created_task.task_id}, API elapsed={api_elapsed:.3f}s")
        return created_task
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to create task: {e}", exc_info=True)
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
    except Exception as e:
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
        # 在返回任务列表前，先更新执行中的任务状态
        await task_scheduler._update_executing_tasks()
        tasks = await task_scheduler.list_tasks(status, robot_id)
        
        # 优化：合并POI查询，只获取一次，同时构建位置映射和ID映射
        async def get_all_pois_data():
            """获取所有POI点数据（合并查询，带超时控制）"""
            import asyncio
            import math
            
            pois_map = {}  # 位置 -> 显示名称
            pois_dict = {}  # POI ID -> 显示名称
            robot_ids = robot_manager.list_robots()
            
            async def get_robot_pois(robot_id: str):
                """从单个机器人获取POI（带超时）"""
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        # 添加超时控制，每个机器人最多等待1.0秒（快速失败）
                        pois = await asyncio.wait_for(
                            agent.get_all_pois(),
                            timeout=1.0
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
                    logger.debug(f"Timeout getting POIs from robot {robot_id} (1.0s)")
                except Exception as e:
                    logger.debug(f"Failed to get POIs for robot {robot_id}: {e}")
            
            # 并发获取所有机器人的POI
            if robot_ids:
                poi_tasks = [get_robot_pois(robot_id) for robot_id in robot_ids]
                await asyncio.gather(*poi_tasks, return_exceptions=True)
            
            return pois_map, pois_dict
        
        pois_map, pois_dict = await get_all_pois_data()
        
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
        result = []
        for task in tasks:
            # 对于多动作任务，检查动作序列中是否有使用POI的动作
            target_poi_name = None
            if task.is_multi_action and task.actions:
                # 查找第一个使用POI的移动动作
                for action in task.actions:
                    # action可能是ActionItem对象或字典
                    action_type = action.action_type if hasattr(action, 'action_type') else action.get('action_type')
                    if action_type == "move_to":
                        # 检查是否有poi_name
                        poi_name = None
                        if hasattr(action, 'poi_name'):
                            poi_name = action.poi_name
                        elif isinstance(action, dict):
                            poi_name = action.get('poi_name')
                        
                        if poi_name:
                            # 优先使用保存的显示名称（如果存在），否则从POI字典中获取
                            poi_display_name = None
                            if hasattr(action, 'poi_display_name'):
                                poi_display_name = action.poi_display_name
                            elif isinstance(action, dict):
                                poi_display_name = action.get('poi_display_name')
                            
                            if poi_display_name and poi_display_name.strip():
                                # 使用保存的显示名称
                                target_poi_name = poi_display_name
                            elif pois_dict:
                                # 如果机器人在线，从POI字典中获取显示名称
                                target_poi_name = pois_dict.get(poi_name, poi_name)
                            else:
                                # 如果机器人离线且没有保存的显示名称，至少显示POI ID
                                target_poi_name = poi_name
                            break
                
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
        
        # 计算统计信息（在筛选和排序之后）
        total = len(result)
        stats = {
            "total": total,
            "pending": sum(1 for t in result if t.get("status") == "pending"),
            "assigned": sum(1 for t in result if t.get("status") == "assigned"),
            "executing": sum(1 for t in result if t.get("status") == "executing"),
            "completed": sum(1 for t in result if t.get("status") == "completed"),
            "failed": sum(1 for t in result if t.get("status") == "failed"),
            "cancelled": sum(1 for t in result if t.get("status") == "cancelled")
        }
        
        # 分页处理
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_tasks = result[start_idx:end_idx]
        
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
    task: MultiActionTaskCreate,
    task_scheduler: TaskScheduler = Depends(get_task_scheduler),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    创建多动作任务（优化：立即返回任务ID，最小化验证）
    
    支持的动作类型：
    - move_to: 移动到目标点（需要target_pose或poi_name）
    - wait: 等待指定时间（需要wait_duration）
    - go_home: 回桩
    
    Args:
        task: 多动作任务创建请求
    """
    import time
    api_start = time.time()
    logger.info(f"API: Received multi-action task creation request with {len(task.actions)} actions")
    
    try:
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
                if has_poi_name:
                    # 保存POI显示名称（如果前端提供了）
                    if not hasattr(action, 'poi_display_name') or not action.poi_display_name:
                        action.poi_display_name = action.poi_name
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
        created_task = await task_scheduler.create_multi_action_task(task)
        api_elapsed = time.time() - api_start
        logger.info(f"API: Multi-action task created successfully: {created_task.task_id}, {len(task.actions)} actions, elapsed={api_elapsed:.3f}s")
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

