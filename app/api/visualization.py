"""
可视化API
"""
import logging
import asyncio
import math
import httpx
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from typing import List, Dict, Optional
from app.services.map_manager import MapManager, get_map_manager
from app.services.robot_manager import RobotManager, get_robot_manager
from app.services.task_scheduler import TaskScheduler, get_task_scheduler
from app.services.path_planner import PathPlanner
from app.models.robot import Pose, RobotStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/data", response_model=dict)
async def get_visualization_data(
    map_manager: MapManager = Depends(get_map_manager),
    robot_manager: RobotManager = Depends(get_robot_manager),
    task_scheduler: TaskScheduler = Depends(get_task_scheduler)
):
    """
    获取可视化数据
    
    返回地图数据、机器人位置、任务路径等信息
    """
    try:
        # 优先使用默认地图
        default_map_data = map_manager.get_default_map_data()
        if default_map_data:
            map_info = default_map_data.get("info")
            map_data = default_map_data.get("data")
        else:
            map_info = None
            map_data = None
        
        # 如果本地地图未加载，尝试从已注册的机器人自动加载（只加载一次，因为所有机器人的地图相同）
        # 注意：地图加载可能很慢，如果超时则跳过，不阻塞整个API响应
        if not map_info:
            robot_ids = robot_manager.list_robots()
            if robot_ids:
                logger.info("Map not loaded, attempting to auto-load from first available robot")
                # 只从第一个可用的机器人加载地图（所有机器人的地图相同，不需要加载所有）
                # 增加整体超时控制，最多尝试10秒（给足够时间连接）
                map_load_start = asyncio.get_event_loop().time()
                for robot_id in robot_ids:
                    # 如果已经尝试超过10秒，停止尝试
                    if asyncio.get_event_loop().time() - map_load_start > 10.0:
                        logger.warning("Map loading timeout (10s), skipping auto-load")
                        break
                    
                    try:
                        robot_agent = robot_manager.get_robot_agent(robot_id)
                        if not robot_agent:
                            logger.debug(f"Robot agent not found for robot_id: {robot_id}, trying next robot")
                            continue
                        
                        logger.info(f"Attempting to auto-load map from robot: {robot_id}")
                        # 增加超时控制，每个机器人最多等待8秒（给足够时间连接和传输）
                        try:
                            map_bytes = await asyncio.wait_for(
                                robot_agent.get_map_explore(),
                                timeout=8.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Timeout loading map from robot {robot_id} (8s), trying next robot")
                            continue
                        
                        # 加载地图
                        success = map_manager.load_from_bytes(map_bytes)
                        if success:
                            # 自动加载虚拟墙信息
                            try:
                                walls = await asyncio.wait_for(
                                    robot_agent.get_virtual_walls(),
                                    timeout=3.0
                                )
                                map_manager.virtual_walls = [wall.dict() for wall in walls]
                                logger.info(f"Auto-loaded {len(walls)} virtual walls from robot {robot_id}")
                            except asyncio.TimeoutError:
                                logger.debug(f"Timeout loading virtual walls from robot {robot_id} (3s), continuing without virtual walls")
                            except Exception as e:
                                logger.debug(f"Failed to auto-load virtual walls from robot {robot_id}: {e}")
                            
                            # 自动加载限行区域信息
                            try:
                                areas = await asyncio.wait_for(
                                    robot_agent.get_restricted_areas(),
                                    timeout=3.0
                                )
                                map_manager.restricted_areas = [area.dict() for area in areas]
                                logger.info(f"Auto-loaded {len(areas)} restricted areas from robot {robot_id}")
                            except asyncio.TimeoutError:
                                logger.debug(f"Timeout loading restricted areas from robot {robot_id} (3s), continuing without restricted areas")
                            except Exception as e:
                                logger.debug(f"Failed to auto-load restricted areas from robot {robot_id}: {e}")
                            
                            # 重新获取地图信息
                            map_info = map_manager.get_map_info()
                            if map_info:
                                logger.info(f"Successfully auto-loaded map from robot: {robot_id}")
                                break  # 成功加载后，停止尝试其他机器人
                            else:
                                logger.warning(f"Map loaded from robot {robot_id} but get_map_info() returned None, trying next robot")
                                continue
                        else:
                            logger.warning(f"Failed to load map from bytes for robot: {robot_id}, trying next robot")
                            continue
                    except Exception as e:
                        # 如果这个机器人失败，记录错误并尝试下一个
                        error_msg = f"Failed to auto-load map from robot {robot_id}: {str(e)}"
                        logger.debug(error_msg, exc_info=True)
                        continue
                
                # 检查是否成功加载
                if not map_info:
                    logger.warning("Failed to auto-load map from all robots")
        
        # 如果还没有地图数据，尝试从内存中获取
        if not map_info or not map_data:
            # 重新获取 map_info，确保使用最新的数据
            map_info = map_manager.get_map_info()
            map_data = None
            if map_manager.metadata and map_manager.grid_map is not None:
                # 将地图数据转换为列表格式
                try:
                    if hasattr(map_manager.grid_map, 'tolist'):
                        # numpy array
                        map_data = map_manager.grid_map.tolist()
                    else:
                        # Python list
                        map_data = map_manager.grid_map
                except Exception as e:
                    logger.error(f"Failed to convert map data to list: {e}", exc_info=True)
                    map_data = None
        
        # 记录地图加载状态
        if map_info:
            logger.debug(f"Map loaded: width={map_info.get('width')}, height={map_info.get('height')}, resolution={map_info.get('resolution')}")
        else:
            logger.warning("Map not loaded - map_info is None")
        
        # 获取机器人位置（确保所有注册的机器人都被包含）
        # 使用并发处理以提高性能，并添加超时控制
        robots_data = []
        robot_ids = robot_manager.list_robots()
        logger.debug(f"Found {len(robot_ids)} robots: {robot_ids}")
        
        async def get_robot_data(robot_id: str):
            """获取单个机器人的数据（带超时控制，优化实时性）"""
            try:
                # 优化实时性：对于可视化页面，直接获取位置信息，绕过完整状态更新
                # 这样可以大幅减少延迟，因为只需要位置信息，不需要speed、power、health等
                agent = robot_manager.get_robot_agent(robot_id)
                if not agent:
                    # 如果没有agent，尝试使用缓存状态
                    if robot_id in robot_manager.robot_states:
                        state = robot_manager.robot_states[robot_id]
                        if state and state.pose:
                            return {
                                "robot_id": robot_id,
                                "pose": {
                                    "x": state.pose.x,
                                    "y": state.pose.y,
                                    "yaw": state.pose.yaw
                                },
                                "status": state.status.value if hasattr(state.status, 'value') else str(state.status),
                                "speed": {
                                    "vx": state.speed.vx if state.speed else 0.0,
                                    "vy": state.speed.vy if state.speed else 0.0,
                                    "omega": state.speed.omega if state.speed else 0.0
                                } if state.speed else {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                                "power": {
                                    "batteryPercentage": state.power.batteryPercentage if state.power else 0,
                                    "isCharging": state.power.isCharging if state.power else False,
                                    "isDCConnected": state.power.isDCConnected if state.power else False,
                                    "dockingStatus": state.power.dockingStatus if state.power else "unknown"
                                } if state.power else {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                                "health": {
                                    "hasError": state.health.hasError if state.health else False,
                                    "hasFatal": state.health.hasFatal if state.health else False,
                                    "hasWarning": state.health.hasWarning if state.health else False,
                                    "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                                    "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                                    "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                                    "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                                    "baseError": state.health.baseError if state.health and state.health.baseError else []
                                } if state.health else {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                            }
                    return {
                        "robot_id": robot_id,
                        "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                        "status": "offline",
                        "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                        "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                        "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                    }
                
                # 快速路径：直接获取位置信息（只调用pose API，不调用其他API）
                # 使用非常短的超时时间（0.2秒），快速失败，绕过重试机制
                try:
                    # 直接调用底层API，绕过get_pose()的重试机制，使用最短超时
                    import httpx
                    pose_url = f"{agent.base_url}/api/core/slam/v1/localization/pose"
                    # 使用极短的超时时间，快速失败
                    quick_timeout = httpx.Timeout(timeout=0.2, connect=0.2, read=0.2)
                    async with httpx.AsyncClient(timeout=quick_timeout, verify=False) as quick_client:
                        response = await quick_client.get(pose_url, timeout=quick_timeout)
                        response.raise_for_status()
                        pose_data = response.json()
                        from app.models.robot import Pose
                        pose = Pose(**pose_data)
                except (asyncio.TimeoutError, httpx.TimeoutException):
                    logger.debug(f"Timeout getting pose for robot {robot_id} (0.2s), using cached state")
                    pose = None
                except Exception as e:
                    logger.debug(f"Failed to get pose for robot {robot_id}: {e}, using cached state")
                    pose = None
                
                # 获取缓存状态作为基础（用于其他信息）
                cached_state = robot_manager.robot_states.get(robot_id)
                
                # 如果成功获取到新位置，更新缓存中的位置信息
                if pose and cached_state:
                    cached_state.pose = pose
                    cached_state.last_update_time = datetime.now()
                
                # 使用最新位置或缓存位置
                final_pose = pose if pose else (cached_state.pose if cached_state else None)
                
                if final_pose:
                    return {
                        "robot_id": robot_id,
                        "pose": {
                            "x": final_pose.x,
                            "y": final_pose.y,
                            "yaw": final_pose.yaw
                        },
                        "status": cached_state.status.value if cached_state and hasattr(cached_state.status, 'value') else (str(cached_state.status) if cached_state else "online"),
                        "speed": {
                            "vx": cached_state.speed.vx if cached_state and cached_state.speed else 0.0,
                            "vy": cached_state.speed.vy if cached_state and cached_state.speed else 0.0,
                            "omega": cached_state.speed.omega if cached_state and cached_state.speed else 0.0
                        } if cached_state and cached_state.speed else {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                        "power": {
                            "batteryPercentage": cached_state.power.batteryPercentage if cached_state and cached_state.power else 0,
                            "isCharging": cached_state.power.isCharging if cached_state and cached_state.power else False,
                            "isDCConnected": cached_state.power.isDCConnected if cached_state and cached_state.power else False,
                            "dockingStatus": cached_state.power.dockingStatus if cached_state and cached_state.power else "unknown"
                        } if cached_state and cached_state.power else {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                        "health": {
                            "hasError": cached_state.health.hasError if cached_state and cached_state.health else False,
                            "hasFatal": cached_state.health.hasFatal if cached_state and cached_state.health else False,
                            "hasWarning": cached_state.health.hasWarning if cached_state and cached_state.health else False,
                            "hasSystemEmergencyStop": cached_state.health.hasSystemEmergencyStop if cached_state and cached_state.health else False,
                            "hasLidarDisconnected": cached_state.health.hasLidarDisconnected if cached_state and cached_state.health else False,
                            "hasDepthCameraDisconnected": cached_state.health.hasDepthCameraDisconnected if cached_state and cached_state.health else False,
                            "hasSdpDisconnected": cached_state.health.hasSdpDisconnected if cached_state and cached_state.health else False,
                            "baseError": cached_state.health.baseError if cached_state and cached_state.health and cached_state.health.baseError else []
                        } if cached_state and cached_state.health else {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                    }
                
                # 如果没有位置信息，返回离线状态
                return {
                    "robot_id": robot_id,
                    "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                    "status": "offline",
                    "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                    "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                    "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                }
            except asyncio.TimeoutError:
                logger.debug(f"Timeout getting state for robot {robot_id} (0.3s), using cached state")
                # 尝试使用缓存的状态（即使过期），快速返回
                if robot_id in robot_manager.robot_states:
                    state = robot_manager.robot_states[robot_id]
                    # 返回缓存的状态
                    if state and state.pose:
                        return {
                            "robot_id": robot_id,
                            "pose": {
                                "x": state.pose.x,
                                "y": state.pose.y,
                                "yaw": state.pose.yaw
                            },
                            "status": state.status.value if hasattr(state.status, 'value') else str(state.status),
                            "speed": {
                                "vx": state.speed.vx if state.speed else 0.0,
                                "vy": state.speed.vy if state.speed else 0.0,
                                "omega": state.speed.omega if state.speed else 0.0
                            } if state.speed else {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                            "power": {
                                "batteryPercentage": state.power.batteryPercentage if state.power else 0,
                                "isCharging": state.power.isCharging if state.power else False,
                                "isDCConnected": state.power.isDCConnected if state.power else False,
                                "dockingStatus": state.power.dockingStatus if state.power else "unknown"
                            } if state.power else {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                            "health": {
                                "hasError": state.health.hasError if state.health else False,
                                "hasFatal": state.health.hasFatal if state.health else False,
                                "hasWarning": state.health.hasWarning if state.health else False,
                                "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                                "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                                "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                                "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                                "baseError": state.health.baseError if state.health and state.health.baseError else []
                            } if state.health else {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                        }
                # 如果没有缓存，返回离线状态
                # 超时，返回离线状态
                return {
                    "robot_id": robot_id,
                    "pose": {
                        "x": 0.0,
                        "y": 0.0,
                        "yaw": 0.0
                    },
                    "status": "offline",
                    "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                    "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                    "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                }
            except asyncio.TimeoutError:
                # 超时，使用缓存状态或返回离线状态（快速返回，不阻塞）
                logger.debug(f"Timeout getting state for robot {robot_id} (0.3s), using cached state")
                # 尝试获取缓存状态
                if robot_id in robot_manager.robot_states:
                    cached_state = robot_manager.robot_states[robot_id]
                    if cached_state and cached_state.pose:
                        return {
                            "robot_id": robot_id,
                            "pose": {
                                "x": cached_state.pose.x,
                                "y": cached_state.pose.y,
                                "yaw": cached_state.pose.yaw
                            },
                            "status": cached_state.status.value if hasattr(cached_state.status, 'value') else str(cached_state.status),
                            "speed": {
                                "vx": cached_state.speed.vx if cached_state.speed else 0.0,
                                "vy": cached_state.speed.vy if cached_state.speed else 0.0,
                                "omega": cached_state.speed.omega if cached_state.speed else 0.0
                            } if cached_state.speed else {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                            "power": {
                                "batteryPercentage": cached_state.power.batteryPercentage if cached_state.power else 0,
                                "isCharging": cached_state.power.isCharging if cached_state.power else False,
                                "isDCConnected": cached_state.power.isDCConnected if cached_state.power else False,
                                "dockingStatus": cached_state.power.dockingStatus if cached_state.power else "unknown"
                            } if cached_state.power else {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                            "health": {
                                "hasError": cached_state.health.hasError if cached_state.health else False,
                                "hasFatal": cached_state.health.hasFatal if cached_state.health else False,
                                "hasWarning": cached_state.health.hasWarning if cached_state.health else False,
                                "hasSystemEmergencyStop": cached_state.health.hasSystemEmergencyStop if cached_state.health else False,
                                "hasLidarDisconnected": cached_state.health.hasLidarDisconnected if cached_state.health else False,
                                "hasDepthCameraDisconnected": cached_state.health.hasDepthCameraDisconnected if cached_state.health else False,
                                "hasSdpDisconnected": cached_state.health.hasSdpDisconnected if cached_state.health else False,
                                "baseError": cached_state.health.baseError if cached_state.health and cached_state.health.baseError else []
                            } if cached_state.health else {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                        }
                # 如果没有缓存，返回离线状态
                return {
                    "robot_id": robot_id,
                    "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                    "status": "offline",
                    "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                    "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                    "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                }
            except Exception as e:
                logger.debug(f"Failed to get state for robot {robot_id}: {e}")
                # 即使出错，也包含机器人（离线状态）
                return {
                    "robot_id": robot_id,
                    "pose": {
                        "x": 0.0,
                        "y": 0.0,
                        "yaw": 0.0
                    },
                    "status": "offline",
                    "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                    "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                    "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                }
        
        # 并发获取所有机器人数据（即使某些机器人超时，也继续处理其他机器人）
        if robot_ids:
            robot_tasks = [get_robot_data(robot_id) for robot_id in robot_ids]
            # 使用 return_exceptions=True 确保即使某些任务失败，也能获取其他机器人的数据
            robot_results = await asyncio.gather(*robot_tasks, return_exceptions=True)
            # 过滤掉异常结果，只保留正常的数据
            robots_data = [r for r in robot_results if isinstance(r, dict)]
        else:
            robots_data = []
        
        # 获取所有POI点（用于匹配目标位置，带超时控制）
        async def get_all_pois_for_matching():
            """获取所有POI点用于匹配（带超时控制）"""
            pois_map = {}
            robot_ids = robot_manager.list_robots()
            
            async def get_pois_from_robot(robot_id: str):
                """从单个机器人获取POI（带超时）"""
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        # 添加超时控制，每个机器人最多等待1.5秒（减少超时时间）
                        pois = await asyncio.wait_for(
                            agent.get_all_pois(),
                            timeout=1.5
                        )
                        for poi in pois:
                            if poi.pose:
                                # 使用位置作为键（精确到0.1米）
                                key = f"{poi.pose.x:.1f}_{poi.pose.y:.1f}"
                                if key not in pois_map:
                                    pois_map[key] = poi.metadata.get("display_name", poi.id) if poi.metadata else poi.id
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting POIs from robot {robot_id} (1.5s)")
                except Exception as e:
                    logger.debug(f"Failed to get POIs for robot {robot_id}: {e}")
            
            # 并发获取所有机器人的POI
            if robot_ids:
                poi_tasks = [get_pois_from_robot(robot_id) for robot_id in robot_ids]
                await asyncio.gather(*poi_tasks, return_exceptions=True)
            
            return pois_map
        
        pois_map = await get_all_pois_for_matching()
        
        def find_poi_name(x: float, y: float) -> Optional[str]:
            """根据坐标查找POI名称"""
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
        
        # 获取任务和路径
        tasks_data = []
        all_tasks = await task_scheduler.list_tasks()
        for task in all_tasks:
            # 查找目标位置的POI名称
            target_poi_name = None
            if task.target_pose:
                target_poi_name = find_poi_name(task.target_pose.x, task.target_pose.y)
            
            task_data = {
                "task_id": task.task_id,
                "robot_id": task.robot_id,
                "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                "priority": task.priority.value if hasattr(task.priority, 'value') else int(task.priority),
                "start_pose": {
                    "x": task.start_pose.x,
                    "y": task.start_pose.y,
                    "yaw": task.start_pose.yaw
                } if task.start_pose else None,
                "target_pose": {
                    "x": task.target_pose.x,
                    "y": task.target_pose.y,
                    "yaw": task.target_pose.yaw
                } if task.target_pose else None,
                "target_poi_name": target_poi_name,  # 添加POI名称
                "path": None
            }
            
            # 只计算已分配或执行中任务的路径（减少计算量）
            # 注意：路径规划可能很慢，如果超时则跳过，不阻塞整个API响应
            task_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
            if task.target_pose and task_status in ('assigned', 'executing'):
                try:
                    # 确定起点
                    start_pose = task.start_pose
                    if not start_pose:
                        # 如果任务已分配，从已获取的机器人数据中查找位置（避免重复查询）
                        if task.robot_id:
                            for robot_data in robots_data:
                                if robot_data and robot_data.get('robot_id') == task.robot_id and robot_data.get('pose'):
                                    start_pose = Pose(
                                        x=robot_data['pose']['x'],
                                        y=robot_data['pose']['y'],
                                        yaw=robot_data['pose']['yaw']
                                    )
                                    break
                    
                    if start_pose:
                        # 路径规划在后台线程执行，添加超时控制
                        # 优化：减少路径规划超时时间，避免阻塞API响应
                        try:
                            path = await asyncio.wait_for(
                                asyncio.to_thread(
                                    task_scheduler.path_planner.plan_path,
                                    start_pose,
                                    task.target_pose
                                ),
                                timeout=1.0  # 路径规划最多等待1秒（进一步减少）
                            )
                            if path:
                                task_data["path"] = [
                                    {"x": p.x, "y": p.y, "yaw": p.yaw}
                                    for p in path
                                ]
                        except asyncio.TimeoutError:
                            logger.debug(f"Path planning timeout for task {task.task_id}, skipping path")
                        except Exception as e:
                            logger.debug(f"Failed to plan path for task {task.task_id}: {e}")
                except Exception as e:
                    logger.debug(f"Failed to plan path for task {task.task_id}: {e}")
            
            tasks_data.append(task_data)
        
        # 获取所有POI点（从所有机器人）- 使用并发处理，带超时控制
        async def get_robot_pois(robot_id: str):
            """获取单个机器人的POI点（带超时，增加超时时间确保能获取到数据）"""
            try:
                agent = robot_manager.get_robot_agent(robot_id)
                if agent:
                    # 增加超时时间到2.5秒，确保能获取到POI数据
                    pois = await asyncio.wait_for(
                        agent.get_all_pois(),
                        timeout=2.5
                    )
                    poi_list = [
                        {
                            "id": poi.id,
                            "display_name": poi.metadata.get("display_name", poi.id) if poi.metadata else poi.id,
                            "pose": {
                                "x": poi.pose.x,
                                "y": poi.pose.y,
                                "yaw": poi.pose.yaw
                            },
                            "robot_id": robot_id
                        }
                        for poi in pois if poi.pose  # 只包含有位置的POI
                    ]
                    logger.info(f"Fetched {len(poi_list)} POIs from robot {robot_id}")
                    return poi_list
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting POIs from robot {robot_id} (2.5s)")
                return []
            except Exception as e:
                logger.warning(f"Failed to get POIs for robot {robot_id}: {e}")
                return []
        
        # 并发获取所有POI点（即使某些机器人超时，也继续处理其他机器人）
        pois_data = []
        if robot_ids:
            try:
                # 设置总体超时为5秒，确保能获取到POI数据
                poi_tasks = [get_robot_pois(robot_id) for robot_id in robot_ids]
                poi_results = await asyncio.wait_for(
                    asyncio.gather(*poi_tasks, return_exceptions=True),
                    timeout=5.0
                )
                # 展平结果列表，过滤掉异常
                for poi_list in poi_results:
                    if isinstance(poi_list, list):
                        pois_data.extend(poi_list)
                logger.info(f"Successfully fetched {len(pois_data)} POIs from {len(robot_ids)} robots")
            except asyncio.TimeoutError:
                logger.warning("POI query timeout (5.0s), continuing with partial POI data")
                # 即使超时，也尝试使用已获取的部分数据
                if 'poi_results' in locals():
                    for poi_list in poi_results:
                        if isinstance(poi_list, list):
                            pois_data.extend(poi_list)
        
        # 去重：按POI ID和位置去重（如果多个机器人有相同的POI）
        seen_pois = {}
        unique_pois = []
        for poi in pois_data:
            # 使用POI ID和位置作为唯一键
            poi_key = f"{poi['id']}_{poi['pose']['x']:.2f}_{poi['pose']['y']:.2f}"
            if poi_key not in seen_pois:
                seen_pois[poi_key] = True
                unique_pois.append(poi)
        pois_data = unique_pois
        
        # 确保POI数据不为空时记录日志
        if pois_data:
            logger.info(f"Final POI data: {len(pois_data)} unique POIs after deduplication")
        else:
            logger.warning("No POI data available after fetching from robots")
        
        # 获取虚拟墙信息（优先使用缓存，快速返回，不阻塞首页加载）
        virtual_walls = []
        
        # 检查缓存状态
        has_cache = hasattr(map_manager, 'virtual_walls')
        cache_size = len(map_manager.virtual_walls) if has_cache and map_manager.virtual_walls else 0
        logger.debug(f"Virtual walls cache check: has_cache={has_cache}, cache_size={cache_size}")
        
        # 优先使用缓存的虚拟墙（如果存在且非空），快速返回，不阻塞首页
        if has_cache and map_manager.virtual_walls and len(map_manager.virtual_walls) > 0:
            logger.debug(f"Found {len(map_manager.virtual_walls)} cached virtual walls, using them")
            for wall in map_manager.virtual_walls:
                start = wall.get("start", {})
                end = wall.get("end", {})
                if start and end:
                    virtual_walls.append({
                        "id": wall.get("id"),
                        "start": {
                            "x": start.get("x", 0),
                            "y": start.get("y", 0)
                        },
                        "end": {
                            "x": end.get("x", 0),
                            "y": end.get("y", 0)
                        }
                    })
            logger.debug(f"Loaded {len(virtual_walls)} virtual walls from cache")
        
        # 如果虚拟墙缓存为空，尝试快速从在线机器人获取（但设置短超时，不阻塞首页）
        # 注意：即使获取失败，也立即返回空数组，让首页快速加载
        if not virtual_walls:
            logger.debug(f"Virtual walls cache is empty, attempting quick fetch from online robots (with short timeout to avoid blocking homepage)")
            robot_ids = robot_manager.list_robots()
            if robot_ids:
                # 尝试从所有在线机器人获取虚拟墙，优先使用在线的机器人
                # 设置总体超时时间（最多尝试5秒），避免阻塞首页
                fetch_start_time = asyncio.get_event_loop().time()
                max_total_time = 5.0  # 最多尝试5秒
                
                for robot_id in robot_ids:
                    # 检查是否超过总体超时时间
                    if asyncio.get_event_loop().time() - fetch_start_time > max_total_time:
                        logger.debug(f"Virtual walls fetch timeout ({max_total_time}s), stopping attempts")
                        break
                    
                    # 快速检查机器人是否在线（使用缓存状态，不阻塞）
                    try:
                        robot_state = await asyncio.wait_for(
                            robot_manager.get_robot_state(robot_id, force_update=False),
                            timeout=0.3  # 快速检查，使用缓存状态
                        )
                        # 如果机器人离线，跳过
                        if not robot_state or robot_state.status == RobotStatus.OFFLINE:
                            logger.debug(f"Robot {robot_id} is offline, skipping virtual walls fetch")
                            continue
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.debug(f"Failed to check robot {robot_id} status: {e}, trying anyway")
                    
                    # 尝试从在线机器人获取虚拟墙
                    try:
                        robot_agent = robot_manager.get_robot_agent(robot_id)
                        if robot_agent:
                            robot_ip = getattr(robot_agent, 'base_url', 'unknown')
                            logger.debug(f"Quick fetch virtual walls from robot {robot_id} at {robot_ip} (timeout=2s)")
                            
                            # 直接从机器人获取虚拟墙，使用短超时，快速失败
                            try:
                                walls = await asyncio.wait_for(
                                    robot_agent.get_virtual_walls(),
                                    timeout=2.0  # 减少到2秒，快速失败，不阻塞首页
                                )
                                
                                if walls and len(walls) > 0:
                                    logger.info(f"Received {len(walls)} VirtualWall objects from robot {robot_id} at {robot_ip}")
                                    
                                    # 更新缓存（转换为字典格式）
                                    try:
                                        map_manager.virtual_walls = [wall.dict() if hasattr(wall, 'dict') else wall for wall in walls]
                                    except Exception as e:
                                        logger.debug(f"Failed to convert walls to dict for cache: {e}")
                                    
                                    # 构建虚拟墙列表
                                    parsed_count = 0
                                    for idx, wall in enumerate(walls):
                                        try:
                                            if hasattr(wall, 'start') and hasattr(wall, 'end') and wall.start and wall.end:
                                                start_dict = wall.start if isinstance(wall.start, dict) else {}
                                                end_dict = wall.end if isinstance(wall.end, dict) else {}
                                                
                                                if start_dict and end_dict and "x" in start_dict and "y" in start_dict and "x" in end_dict and "y" in end_dict:
                                                    virtual_walls.append({
                                                        "id": wall.id,
                                                        "start": {
                                                            "x": float(start_dict.get("x", 0)),
                                                            "y": float(start_dict.get("y", 0))
                                                        },
                                                        "end": {
                                                            "x": float(end_dict.get("x", 0)),
                                                            "y": float(end_dict.get("y", 0))
                                                        }
                                                    })
                                                    parsed_count += 1
                                        except Exception as e:
                                            logger.debug(f"Error parsing virtual wall {idx}: {e}")
                                    
                                    if parsed_count > 0:
                                        logger.info(f"Parsed {parsed_count}/{len(walls)} virtual walls successfully from robot {robot_id}")
                                        # 成功获取虚拟墙，停止尝试其他机器人
                                        break
                            except asyncio.TimeoutError:
                                logger.debug(f"Timeout loading virtual walls from robot {robot_id} (2s), trying next robot")
                                continue
                            except Exception as e:
                                logger.debug(f"Failed to load virtual walls from robot {robot_id}: {e}, trying next robot")
                                continue
                    except Exception as e:
                        logger.debug(f"Error accessing robot {robot_id} for virtual walls: {e}, trying next robot")
                        continue
        
        # 确保 virtual_walls 总是存在（即使是空数组）
        if not virtual_walls:
            virtual_walls = []
        
        # 获取限行区域信息（优先使用缓存，快速返回，不阻塞首页加载）
        restricted_areas = []
        
        # 检查缓存状态
        has_areas_cache = hasattr(map_manager, 'restricted_areas')
        areas_cache_size = len(map_manager.restricted_areas) if has_areas_cache and map_manager.restricted_areas else 0
        logger.debug(f"Restricted areas cache check: has_cache={has_areas_cache}, cache_size={areas_cache_size}")
        
        # 总是尝试从所有在线机器人获取最新限行区域数据，合并所有限行区域
        # 如果获取失败或超时，再使用缓存数据
        should_fetch = True
        fetch_success = False
        all_fetched_areas = []  # 存储从所有机器人获取的限行区域
        
        if should_fetch:
            logger.debug(f"Attempting to fetch restricted areas from all online robots")
            robot_ids = robot_manager.list_robots()
            if robot_ids:
                # 并发从所有在线机器人获取限行区域
                async def get_robot_areas_safe(robot_id: str):
                    """安全地从单个机器人获取限行区域"""
                    try:
                        # 快速检查机器人是否在线
                        robot_state = await asyncio.wait_for(
                            robot_manager.get_robot_state(robot_id, force_update=False),
                            timeout=0.3
                        )
                        if not robot_state or robot_state.status == RobotStatus.OFFLINE:
                            logger.debug(f"Robot {robot_id} is offline, skipping")
                            return []
                    except (asyncio.TimeoutError, Exception):
                        # 即使状态检查失败，也尝试获取（可能只是状态更新慢）
                        pass
                    
                    try:
                        robot_agent = robot_manager.get_robot_agent(robot_id)
                        if robot_agent:
                            robot_ip = getattr(robot_agent, 'base_url', 'unknown')
                            logger.debug(f"Fetching restricted areas from robot {robot_id} at {robot_ip}")
                            
                            areas = await asyncio.wait_for(
                                robot_agent.get_restricted_areas(),
                                timeout=2.0
                            )
                            
                            if areas and len(areas) > 0:
                                logger.info(f"Received {len(areas)} restricted areas from robot {robot_id}")
                                # 转换为字典格式
                                result = []
                                for area in areas:
                                    try:
                                        if hasattr(area, 'area') and area.area:
                                            area_dict = area.area if isinstance(area.area, dict) else {}
                                            if area_dict:
                                                result.append({
                                                    "id": area.id,
                                                    "area": area_dict,
                                                    "metadata": area.metadata if hasattr(area, 'metadata') else None,
                                                    "usage": area.usage if hasattr(area, 'usage') else "restricted_area"
                                                })
                                    except Exception as e:
                                        logger.debug(f"Error parsing restricted area from robot {robot_id}: {e}")
                                return result
                    except asyncio.TimeoutError:
                        logger.debug(f"Timeout getting restricted areas from robot {robot_id} (2s)")
                    except Exception as e:
                        logger.debug(f"Failed to get restricted areas from robot {robot_id}: {e}")
                    return []
                
                # 并发获取所有机器人的限行区域
                area_tasks = [get_robot_areas_safe(robot_id) for robot_id in robot_ids]
                area_results = await asyncio.gather(*area_tasks, return_exceptions=True)
                
                # 合并所有限行区域（按ID去重）
                seen_ids = set()
                for area_list in area_results:
                    if isinstance(area_list, list):
                        for area in area_list:
                            area_id = area.get("id")
                            if area_id is not None and area_id not in seen_ids:
                                seen_ids.add(area_id)
                                all_fetched_areas.append(area)
                
                if all_fetched_areas:
                    logger.info(f"Merged {len(all_fetched_areas)} restricted areas from {len(robot_ids)} robots (unique IDs: {sorted(seen_ids)})")
                    restricted_areas = all_fetched_areas
                    # 更新缓存
                    map_manager.restricted_areas = all_fetched_areas
                    fetch_success = True
        
        # 如果获取失败且没有数据，尝试使用缓存数据作为后备
        if not restricted_areas and has_areas_cache and map_manager.restricted_areas and len(map_manager.restricted_areas) > 0:
            logger.debug(f"Failed to fetch restricted areas from robots, using {len(map_manager.restricted_areas)} cached areas")
            for area in map_manager.restricted_areas:
                area_data = area.get("area", {})
                if area_data:
                    restricted_areas.append({
                        "id": area.get("id"),
                        "area": area_data,
                        "metadata": area.get("metadata"),
                        "usage": area.get("usage", "restricted_area")
                    })
        
        # 确保 restricted_areas 总是存在（即使是空数组）
        if not restricted_areas:
            restricted_areas = []
        
        # 记录返回数据状态（使用info级别，确保能看到限行区域数据）
        logger.info(
            f"Returning visualization data: map_info={map_info is not None}, "
            f"{len(robots_data)} robots, {len(tasks_data)} tasks, {len(pois_data)} pois, "
            f"{len(virtual_walls)} virtual walls, {len(restricted_areas)} restricted areas"
        )
        if restricted_areas:
            logger.info(f"Restricted areas details: {[{'id': a.get('id'), 'has_area': 'area' in a} for a in restricted_areas]}")
        
        # 获取等待点配置（用于前端显示）
        waiting_points_config = []
        try:
            from app.services.config_manager import get_config_manager
            config_manager = get_config_manager()
            deadlock_config = config_manager.get_deadlock_config()
            # 检查是否启用POI等待点（支持布尔值和数字1/0）
            use_poi_waiting_points = deadlock_config.get("use_poi_waiting_points")
            logger.info(f"Checking waiting points config: use_poi_waiting_points={use_poi_waiting_points}, type={type(use_poi_waiting_points)}")
            
            # 更宽松的检查：只要值不是False、0、None、"false"、"0"，就认为启用
            if use_poi_waiting_points not in [False, 0, None, "0", "false", ""]:
                poi_waiting_points = deadlock_config.get("poi_waiting_points", [])
                logger.info(f"POI waiting points from config: {poi_waiting_points}, type={type(poi_waiting_points)}")
                if poi_waiting_points and isinstance(poi_waiting_points, list) and len(poi_waiting_points) > 0:
                    waiting_points_config = poi_waiting_points
                    logger.info(f"Including {len(waiting_points_config)} waiting points in visualization data: {waiting_points_config}")
                else:
                    logger.warning(f"POI waiting points is empty or invalid: {poi_waiting_points}")
            else:
                logger.info(f"POI waiting points disabled: use_poi_waiting_points={use_poi_waiting_points}")
        except Exception as e:
            logger.error(f"Failed to get waiting points config: {e}", exc_info=True)
        
        # 确保POI数据总是存在（即使是空数组）
        if not pois_data:
            pois_data = []
            logger.warning("No POI data available, returning empty array")
        
        result = {
            "map": {
                "info": map_info,
                "data": map_data
            },
            "robots": robots_data,
            "tasks": tasks_data,
            "pois": pois_data,  # 确保POI数据被包含
            "virtual_walls": virtual_walls,
            "restricted_areas": restricted_areas,
            "waiting_points": waiting_points_config  # 等待点配置（POI名称列表）
        }
        
        # 记录最终返回的POI数量
        logger.info(f"Returning {len(result['pois'])} POIs in visualization data")
        
        return result
    except Exception as e:
        logger.error(f"Failed to get visualization data: {e}", exc_info=True)
        # 即使出错，也尝试返回部分数据（如果有的话），避免完全失败
        try:
            # 确保POI数据在异常情况下也返回（使用局部变量或空数组）
            error_pois_data = pois_data if 'pois_data' in locals() else []
            # 获取虚拟墙信息（即使出错也尝试返回）
            virtual_walls = []
            if map_manager and hasattr(map_manager, 'virtual_walls') and map_manager.virtual_walls:
                for wall in map_manager.virtual_walls:
                    start = wall.get("start", {})
                    end = wall.get("end", {})
                    if start and end:
                        virtual_walls.append({
                            "id": wall.get("id"),
                            "start": {
                                "x": start.get("x", 0),
                                "y": start.get("y", 0)
                            },
                            "end": {
                                "x": end.get("x", 0),
                                "y": end.get("y", 0)
                            }
                        })
            
            # 确保 virtual_walls 总是存在（即使是空数组）
            if not virtual_walls:
                virtual_walls = []
            
            # 获取限行区域信息（即使出错也尝试返回）
            restricted_areas = []
            if map_manager and hasattr(map_manager, 'restricted_areas') and map_manager.restricted_areas:
                for area in map_manager.restricted_areas:
                    area_data = area.get("area", {})
                    if area_data:
                        restricted_areas.append({
                            "id": area.get("id"),
                            "area": area_data,
                            "metadata": area.get("metadata"),
                            "usage": area.get("usage", "restricted_area")
                        })
            
            # 确保 restricted_areas 总是存在（即使是空数组）
            if not restricted_areas:
                restricted_areas = []
            
            return {
                "map": {
                    "info": map_manager.get_map_info() if map_manager else None,
                    "data": map_manager.grid_map.tolist() if map_manager and map_manager.grid_map is not None and hasattr(map_manager.grid_map, 'tolist') else (map_manager.grid_map if map_manager and map_manager.grid_map is not None else None)
                },
                "robots": robots_data if 'robots_data' in locals() else [],
                "tasks": tasks_data if 'tasks_data' in locals() else [],
                "pois": error_pois_data if 'error_pois_data' in locals() else (pois_data if 'pois_data' in locals() else []),
                "virtual_walls": virtual_walls,
                "restricted_areas": restricted_areas,
                "waiting_points": []  # 异常情况下返回空数组
            }
        except Exception:
            # 如果连部分数据都无法返回，抛出异常
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/map/image")
async def get_map_image(
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取地图图像（PNG格式）
    """
    try:
        if map_manager.metadata is None or map_manager.grid_map is None:
            raise HTTPException(status_code=404, detail="Map not loaded")
        
        # 尝试使用PIL创建图像
        try:
            import io
            from PIL import Image
            
            width = map_manager.metadata.width
            height = map_manager.metadata.height
            
            # 创建图像
            img = Image.new('RGB', (width, height), color='white')
            pixels = img.load()
            
            # 转换地图数据为图像
            for y in range(height):
                for x in range(width):
                    if hasattr(map_manager.grid_map, '__getitem__'):
                        if hasattr(map_manager.grid_map[y], '__getitem__'):
                            value = map_manager.grid_map[y][x]
                        else:
                            value = map_manager.grid_map[y, x] if hasattr(map_manager.grid_map, 'shape') else 0
                    else:
                        value = 0
                    
                    # 内部格式：0=占用(黑色), 100=空闲(白色), -1=未知(灰色)
                    if value == 0:
                        pixels[x, y] = (0, 0, 0)  # 黑色 = 障碍物（占用）
                    elif value == 100:
                        pixels[x, y] = (255, 255, 255)  # 白色 = 可行走（空闲）
                    elif value == -1:
                        pixels[x, y] = (128, 128, 128)  # 灰色 = 未知区域
                    else:
                        pixels[x, y] = (128, 128, 128)  # 其他值也显示为灰色
            
            # 转换为字节流
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            return Response(content=img_bytes.getvalue(), media_type="image/png")
        except ImportError:
            # 如果没有PIL，返回JSON格式的地图数据
            raise HTTPException(status_code=501, detail="PIL/Pillow not installed. Use /api/visualization/data instead.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate map image: {e}")
        raise HTTPException(status_code=500, detail=str(e))

