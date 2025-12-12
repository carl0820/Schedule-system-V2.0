"""
机器人管理API
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import List, Optional
import re
import logging
from urllib.parse import urlparse
from app.models.robot import RobotState, RobotStatus, RegisterRequest
from app.services.robot_manager import RobotManager, get_robot_manager
# 认证已移除，所有API端点无需授权即可调用

router = APIRouter()
logger = logging.getLogger(__name__)


def normalize_base_url(base_url: str) -> str:
    """
    规范化base_url格式
    
    Args:
        base_url: 原始URL（可能缺少协议或端口）
        
    Returns:
        规范化后的URL（包含协议和端口）
    """
    # 去除首尾空格
    base_url = base_url.strip()
    
    # 如果没有协议，添加http://
    if not re.match(r'^https?://', base_url, re.IGNORECASE):
        base_url = f"http://{base_url}"
    
    # 如果只有IP地址或域名，添加默认端口1448
    if not re.search(r':\d+', base_url):
        base_url = f"{base_url}:1448"
    
    return base_url


def extract_host_from_url(url: str) -> str:
    """
    从URL中提取主机地址（IP或域名）
    
    Args:
        url: URL字符串（如：http://10.160.128.91:1448）
        
    Returns:
        主机地址（如：10.160.128.91）
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        # 如果解析失败，尝试用正则表达式提取
        match = re.search(r'://([^:/]+)', url)
        return match.group(1) if match else ""


@router.post("/register", response_model=dict)
async def register_robot(
    request: RegisterRequest,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    注册机器人
    
    使用请求体（JSON格式）：
    POST /api/robots/register
    Body: {"robot_id": "robot1", "base_url": "10.160.128.91"}
    
    Args:
        request: 注册请求体，包含robot_id和base_url
    """
    
    try:
        robot_id = request.robot_id
        base_url = request.base_url
        
        logger.info(f"Registering robot: robot_id={robot_id}, base_url={base_url}")
        
        # 规范化URL格式
        try:
            normalized_url = normalize_base_url(base_url)
            logger.debug(f"Normalized URL: {normalized_url}")
        except Exception as e:
            logger.error(f"Failed to normalize URL {base_url}: {e}", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to normalize URL: {str(e)}"
            )
        
        # 验证URL格式
        if not re.match(r'^https?://[\w\.-]+:\d+$', normalized_url, re.IGNORECASE):
            logger.warning(f"Invalid URL format: {normalized_url}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base_url format. Expected format: http://host:port or host. Got: {base_url}"
            )
        
        # 检查机器人是否已注册
        try:
            existing_robots = robot_manager.list_robots()
            logger.debug(f"Existing robots: {existing_robots}")
            if robot_id in existing_robots:
                logger.warning(f"Robot {robot_id} is already registered")
                raise HTTPException(
                    status_code=409,
                    detail=f"Robot {robot_id} is already registered"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking existing robots: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Error checking existing robots: {str(e)}"
            )
        
        # 检查同一IP是否已注册
        try:
            host = extract_host_from_url(normalized_url)
            logger.debug(f"Extracted host: {host}")
            if host:
                existing_robot_id = robot_manager.find_robot_by_host(host)
                if existing_robot_id and existing_robot_id != robot_id:
                    logger.warning(f"IP {host} is already registered by robot {existing_robot_id}")
                    raise HTTPException(
                        status_code=409,
                        detail=f"IP address {host} is already registered by robot {existing_robot_id}. Each IP can only register one robot."
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking IP conflict: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Error checking IP conflict: {str(e)}"
            )
        
        # 尝试注册机器人
        try:
            logger.info(f"Attempting to register robot {robot_id} at {normalized_url}")
            success, error_msg = await robot_manager.register_robot(robot_id, normalized_url)
            
            if not success:
                logger.error(f"Failed to register robot {robot_id}: {error_msg}")
                # 确保错误信息不为空
                if not error_msg:
                    error_msg = f"Failed to register robot {robot_id}. Please check if the robot is accessible at {normalized_url}"
                raise HTTPException(
                    status_code=400,
                    detail=error_msg
                )
            
            logger.info(f"Robot {robot_id} registered successfully at {normalized_url}")
            return {
                "message": "Robot registered successfully",
                "robot_id": robot_id,
                "base_url": normalized_url
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during robot registration: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Error during robot registration: {str(e)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in register_robot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{robot_id}", response_model=dict)
async def unregister_robot(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    注销机器人
    
    Args:
        robot_id: 机器人ID
    """
    
    try:
        success = await robot_manager.unregister_robot(robot_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        return {"message": "Robot unregistered successfully", "robot_id": robot_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/", response_model=List[dict])
async def list_robots(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取所有机器人列表（包含ID、base_url和停用状态）
    """
    robots = []
    for robot_id in robot_manager.list_robots():
        agent = robot_manager.get_robot_agent(robot_id)
        if agent:
            robots.append({
                "robot_id": robot_id,
                "base_url": agent.base_url,
                "disabled": robot_manager.is_robot_disabled(robot_id)
            })
    return robots


@router.get("/force-update/{robot_id}", response_model=dict)
async def force_update_robot_state(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    强制更新机器人状态（调试用）
    
    访问路径: /api/robots/force-update/{robot_id}
    """
    if robot_id not in robot_manager.robots:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
    
    try:
        # 强制更新状态
        await robot_manager.get_robot_state(robot_id, force_update=True)
        state = robot_manager.robot_states.get(robot_id)
        if state:
            return {
                "robot_id": robot_id,
                "status": state.status.value if isinstance(state.status, RobotStatus) else str(state.status),
                "last_update_time": state.last_update_time.isoformat() if state.last_update_time else None,
                "pose": {
                    "x": state.pose.x if state.pose else 0.0,
                    "y": state.pose.y if state.pose else 0.0,
                    "yaw": state.pose.yaw if state.pose else 0.0
                } if state.pose else None,
                "power": {
                    "batteryPercentage": state.power.batteryPercentage if state.power else 0
                } if state.power else None
            }
        else:
            return {"robot_id": robot_id, "error": "State not available"}
    except Exception as e:
        logger.error(f"Failed to force update state for {robot_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update state: {str(e)}")


@router.get("/debug/{robot_id}", response_model=dict)
async def debug_robot_connection(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    调试机器人连接（测试用）
    
    直接测试机器人的连接，返回详细的连接信息
    访问路径: /api/robots/debug/{robot_id}
    """
    import asyncio
    from datetime import datetime
    
    result = {
        "robot_id": robot_id,
        "exists": False,
        "base_url": None,
        "test_results": {}
    }
    
    if robot_id not in robot_manager.robots:
        result["error"] = f"Robot {robot_id} not found"
        return result
    
    result["exists"] = True
    agent = robot_manager.get_robot_agent(robot_id)
    if agent:
        result["base_url"] = agent.base_url
        
        # 测试各个API端点
        test_endpoints = {
            "pose": "/api/core/slam/v1/localization/pose",
            "health": "/api/core/system/v1/robot/health",
            "speed": "/api/core/motion/v1/speed",
            "power": "/api/core/system/v1/power/status"
        }
        
        for name, path in test_endpoints.items():
            try:
                start_time = datetime.now()
                # 增加超时时间到10秒，确保有足够时间连接
                data = await asyncio.wait_for(agent._get(path), timeout=10.0)
                elapsed = (datetime.now() - start_time).total_seconds()
                result["test_results"][name] = {
                    "success": True,
                    "elapsed": elapsed,
                    "data": data
                }
            except asyncio.TimeoutError:
                result["test_results"][name] = {
                    "success": False,
                    "error": "Timeout (10s)"
                }
            except Exception as e:
                result["test_results"][name] = {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
    
    return result


@router.post("/{robot_id}/go-home", response_model=dict)
async def go_home(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    让机器人回桩
    
    Args:
        robot_id: 机器人ID
        
    Returns:
        回桩操作结果，包含 action_id 等信息
    """
    # 检查权限：所有角色都可以让机器人回桩（这是基本操作）
    # 不需要权限检查，所有登录用户都可以操作
    
    logger.info(f"Received go-home request for robot: {robot_id}")
    try:
        agent = robot_manager.get_robot_agent(robot_id)
        if not agent:
            logger.warning(f"Robot {robot_id} not found in robot_manager")
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        
        logger.info(f"Sending robot {robot_id} home, base_url: {agent.base_url}")
        # 调用机器人回桩
        result = await agent.go_home()
        
        # 检查回桩结果
        if result:
            action_id = result.action_id
            # 检查action状态，看是否立即失败
            if result.state:
                result_code = result.state.get("result")
                reason = result.state.get("reason", "")
                status = result.state.get("status")
                
                logger.info(
                    f"Robot {robot_id} go-home action check: "
                    f"action_id={action_id}, result={result_code}, status={status}, reason={reason}"
                )
                
                # 如果action立即失败，返回错误信息
                if result_code == -1:
                    error_msg = f"回桩失败: {reason}" if reason else "回桩失败: 未知错误"
                    if "DOCK_ID_NOT_FOUND" in reason or "dock" in reason.lower():
                        error_msg = "回桩失败: 未找到充电桩ID。请检查机器人配置，确保充电桩已正确设置。"
                    logger.error(f"Robot {robot_id} go-home failed immediately: {error_msg}")
                    raise HTTPException(
                        status_code=400, 
                        detail=error_msg
                    )
                
                # 如果status为4（Done）且result为-1，说明已经失败
                if status == 4 and result_code == -1:
                    error_msg = f"回桩失败: {reason}" if reason else "回桩失败: 未知错误"
                    logger.error(f"Robot {robot_id} go-home action already done with failure: {error_msg}")
                    raise HTTPException(
                        status_code=400,
                        detail=error_msg
                    )
            
            logger.info(f"Robot {robot_id} go-home command sent successfully, action_id: {action_id}")
            return {
                "success": True,
                "robot_id": robot_id,
                "action_id": action_id,
                "message": f"Robot {robot_id} is returning to charging dock"
            }
        else:
            logger.error(f"Robot {robot_id} go-home command returned no result")
            raise HTTPException(
                status_code=500, 
                detail="回桩命令执行失败：未收到有效响应"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send robot {robot_id} home: {e}", exc_info=True)
        error_detail = str(e)
        # 如果是DOCK_ID_NOT_FOUND错误，提供更友好的提示
        if "DOCK_ID_NOT_FOUND" in error_detail or "dock" in error_detail.lower():
            error_detail = "未找到充电桩ID。请检查机器人配置，确保充电桩已正确设置。"
        raise HTTPException(status_code=500, detail=f"回桩失败: {error_detail}")


@router.post("/{robot_id}/disable", response_model=dict)
async def disable_robot(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    停用机器人（停用的机器人将无法执行任何调度任务）
    
    Args:
        robot_id: 机器人ID
    """
    if robot_id not in robot_manager.robots:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
    
    success = robot_manager.disable_robot(robot_id)
    if success:
        return {
            "robot_id": robot_id,
            "disabled": True,
            "message": f"Robot {robot_id} has been disabled"
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to disable robot {robot_id}")


@router.post("/{robot_id}/enable", response_model=dict)
async def enable_robot(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    启用机器人
    
    Args:
        robot_id: 机器人ID
    """
    if robot_id not in robot_manager.robots:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
    
    success = robot_manager.enable_robot(robot_id)
    if success:
        return {
            "robot_id": robot_id,
            "disabled": False,
            "message": f"Robot {robot_id} has been enabled"
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to enable robot {robot_id}")


@router.post("/{robot_id}/sync-map", response_model=dict)
async def sync_map(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    同步机器人地图（地图持久化保存）
    
    Args:
        robot_id: 机器人ID
        
    Returns:
        同步地图操作结果
    """
    # 检查权限：所有角色都可以同步地图（这是基本操作）
    # 不需要权限检查，所有登录用户都可以操作
    
    logger.info(f"Received sync-map request for robot: {robot_id}")
    try:
        agent = robot_manager.get_robot_agent(robot_id)
        if not agent:
            logger.warning(f"Robot {robot_id} not found in robot_manager")
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        
        logger.info(f"Syncing map for robot {robot_id}, base_url: {agent.base_url}")
        # 调用机器人同步地图
        success = await agent.sync_map()
        if success:
            logger.info(f"Robot {robot_id} map sync completed successfully")
            return {
                "success": True,
                "robot_id": robot_id,
                "message": f"Robot {robot_id} map synchronized successfully"
            }
        else:
            logger.error(f"Robot {robot_id} map sync failed")
            raise HTTPException(status_code=500, detail="Map sync failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync map for robot {robot_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to sync map: {str(e)}")


@router.get("/{robot_id}/state")
async def get_robot_state(
    robot_id: str,
    test: bool = Query(False, description="如果为True，返回详细的连接测试信息（调试用）"),
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取机器人状态
    
    Args:
        robot_id: 机器人ID
        test: 如果为True，返回详细的连接测试信息（调试用）
    """
    # 如果test参数为True，返回详细的测试信息
    if test:
        import asyncio
        from datetime import datetime
        from typing import Dict, Any
        
        result: Dict[str, Any] = {
            "robot_id": robot_id,
            "exists": False,
            "base_url": None,
            "test_results": {}
        }
        
        if robot_id not in robot_manager.robots:
            result["error"] = f"Robot {robot_id} not found"
            return JSONResponse(content=result)
        
        result["exists"] = True
        agent = robot_manager.get_robot_agent(robot_id)
        if agent:
            result["base_url"] = agent.base_url
            
            # 测试各个API端点
            test_endpoints = {
                "pose": "/api/core/slam/v1/localization/pose",
                "health": "/api/core/system/v1/robot/health",
                "speed": "/api/core/motion/v1/speed",
                "power": "/api/core/system/v1/power/status"
            }
            
            for name, path in test_endpoints.items():
                try:
                    start_time = datetime.now()
                    data = await asyncio.wait_for(agent._get(path), timeout=3.0)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    result["test_results"][name] = {
                        "success": True,
                        "elapsed": elapsed,
                        "data": data
                    }
                except asyncio.TimeoutError:
                    result["test_results"][name] = {
                        "success": False,
                        "error": "Timeout (3s)"
                    }
                except Exception as e:
                    result["test_results"][name] = {
                        "success": False,
                        "error": str(e)
                    }
        
        return JSONResponse(content=result)
    
    # 正常返回状态
    try:
        state = await robot_manager.get_robot_state(robot_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        return state
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{robot_id}/pose", response_model=dict)
async def get_robot_pose(
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取机器人位置
    
    Args:
        robot_id: 机器人ID
    """
    try:
        pose = await robot_manager.get_robot_pose(robot_id)
        if not pose:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        return pose.dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/states", response_model=List[dict])
async def get_all_robots_states(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取所有机器人的状态（轻量级版本，用于机器人列表页面）
    
    返回所有已注册机器人的基本状态信息，包括：
    - robot_id: 机器人ID
    - pose: 位置信息
    - status: 机器人状态
    - speed: 速度信息
    - power: 电量信息
    - health: 健康状态
    """
    import asyncio
    from typing import Dict, Any
    
    robots_states = []
    robot_ids = robot_manager.list_robots()
    
    if not robot_ids:
        return []
    
    # 并发获取所有机器人的状态（使用缓存，快速响应）
    async def get_single_robot_state(robot_id: str) -> Dict[str, Any]:
        """获取单个机器人的状态（优先使用缓存，但如果需要更新则允许更长时间）"""
        try:
            from datetime import datetime
            
            # 检查缓存是否足够新
            cached_state = None
            use_cache = False
            if robot_id in robot_manager.robot_states:
                cached_state = robot_manager.robot_states[robot_id]
                if cached_state and cached_state.last_update_time:
                    time_since_update = (datetime.now() - cached_state.last_update_time).total_seconds()
                    # 如果状态在10秒内更新过，直接使用缓存（避免API调用）
                    # 但如果缓存状态是离线，即使缓存足够新，也强制更新一次（确保能检测到机器人上线）
                    if time_since_update < 10.0 and cached_state.status != RobotStatus.OFFLINE:
                        use_cache = True
                        state = cached_state
                    else:
                        # 缓存过期或状态是离线，需要更新，允许更长时间（5秒，确保有足够时间）
                        # 如果状态是离线，强制更新
                        force_update = (cached_state.status == RobotStatus.OFFLINE)
                        state = await asyncio.wait_for(
                            robot_manager.get_robot_state(robot_id, force_update=force_update),
                            timeout=5.0  # 增加超时时间，确保有足够时间更新状态
                        )
                else:
                    # 缓存存在但没有更新时间，需要更新
                    state = await asyncio.wait_for(
                        robot_manager.get_robot_state(robot_id, force_update=True),
                        timeout=5.0
                    )
            else:
                # 没有缓存，需要获取状态，强制更新
                state = await asyncio.wait_for(
                    robot_manager.get_robot_state(robot_id, force_update=True),
                    timeout=5.0
                )
            
            # 获取机器人的base_url（IP地址）
            agent = robot_manager.get_robot_agent(robot_id)
            base_url = agent.base_url if agent else None
            
            # 如果使用缓存，直接返回（不需要后续处理）
            if use_cache and state:
                status = state.status.value if isinstance(state.status, RobotStatus) else str(state.status)
                return {
                    "robot_id": robot_id,
                    "base_url": base_url,  # 添加IP地址
                    "disabled": robot_manager.is_robot_disabled(robot_id),  # 添加停用状态
                    "pose": {
                        "x": state.pose.x if state.pose else 0.0,
                        "y": state.pose.y if state.pose else 0.0,
                        "yaw": state.pose.yaw if state.pose else 0.0
                    },
                    "status": status,
                    "speed": {
                        "vx": state.speed.vx if state.speed else 0.0,
                        "vy": state.speed.vy if state.speed else 0.0,
                        "omega": state.speed.omega if state.speed else 0.0
                    },
                    "power": {
                        "batteryPercentage": state.power.batteryPercentage if state.power else 0,
                        "isCharging": state.power.isCharging if state.power else False,
                        "isDCConnected": state.power.isDCConnected if state.power else False,
                        "dockingStatus": state.power.dockingStatus if state.power else "unknown"
                    },
                    "health": {
                        "hasError": state.health.hasError if state.health else False,
                        "hasFatal": state.health.hasFatal if state.health else False,
                        "hasWarning": state.health.hasWarning if state.health else False,
                        "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                        "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                        "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                        "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                        "baseError": state.health.baseError if state.health and state.health.baseError else []
                    }
                }
            if not state:
                return {
                    "robot_id": robot_id,
                    "base_url": base_url,  # 添加IP地址
                    "disabled": robot_manager.is_robot_disabled(robot_id),  # 添加停用状态
                    "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                    "status": "offline",
                    "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                    "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                    "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
                }
            
            # 提取状态信息
            status = state.status.value if isinstance(state.status, RobotStatus) else str(state.status)
            
            return {
                "robot_id": robot_id,
                "base_url": base_url,  # 添加IP地址
                "disabled": robot_manager.is_robot_disabled(robot_id),  # 添加停用状态
                "pose": {
                    "x": state.pose.x if state.pose else 0.0,
                    "y": state.pose.y if state.pose else 0.0,
                    "yaw": state.pose.yaw if state.pose else 0.0
                },
                "status": status,
                "speed": {
                    "vx": state.speed.vx if state.speed else 0.0,
                    "vy": state.speed.vy if state.speed else 0.0,
                    "omega": state.speed.omega if state.speed else 0.0
                },
                "power": {
                    "batteryPercentage": state.power.batteryPercentage if state.power else 0,
                    "isCharging": state.power.isCharging if state.power else False,
                    "isDCConnected": state.power.isDCConnected if state.power else False,
                    "dockingStatus": state.power.dockingStatus if state.power else "unknown"
                },
                "health": {
                    "hasError": state.health.hasError if state.health else False,
                    "hasFatal": state.health.hasFatal if state.health else False,
                    "hasWarning": state.health.hasWarning if state.health else False,
                    "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                    "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                    "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                    "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                    "baseError": state.health.baseError if state.health and state.health.baseError else []
                }
            }
        except asyncio.TimeoutError:
            # 获取机器人的base_url（IP地址）
            agent = robot_manager.get_robot_agent(robot_id)
            base_url = agent.base_url if agent else None
            
            # 超时，尝试使用缓存的状态
            if robot_id in robot_manager.robot_states:
                state = robot_manager.robot_states[robot_id]
                if state:
                    status = state.status.value if isinstance(state.status, RobotStatus) else str(state.status)
                    return {
                        "robot_id": robot_id,
                        "base_url": base_url,  # 添加IP地址
                        "pose": {
                            "x": state.pose.x if state.pose else 0.0,
                            "y": state.pose.y if state.pose else 0.0,
                            "yaw": state.pose.yaw if state.pose else 0.0
                        },
                        "status": status,
                        "speed": {
                            "vx": state.speed.vx if state.speed else 0.0,
                            "vy": state.speed.vy if state.speed else 0.0,
                            "omega": state.speed.omega if state.speed else 0.0
                        },
                        "power": {
                            "batteryPercentage": state.power.batteryPercentage if state.power else 0,
                            "isCharging": state.power.isCharging if state.power else False,
                            "isDCConnected": state.power.isDCConnected if state.power else False,
                            "dockingStatus": state.power.dockingStatus if state.power else "unknown"
                        },
                        "health": {
                            "hasError": state.health.hasError if state.health else False,
                            "hasFatal": state.health.hasFatal if state.health else False,
                            "hasWarning": state.health.hasWarning if state.health else False,
                            "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                            "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                            "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                            "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                            "baseError": state.health.baseError if state.health and state.health.baseError else []
                        }
                    }
            # 如果没有缓存，返回离线状态
            return {
                "robot_id": robot_id,
                "base_url": base_url,  # 添加IP地址
                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                "status": "offline",
                "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
            }
        except Exception as e:
            logger.debug(f"Failed to get state for robot {robot_id}: {e}")
            # 获取机器人的base_url（IP地址）
            agent = robot_manager.get_robot_agent(robot_id)
            base_url = agent.base_url if agent else None
            
            return {
                "robot_id": robot_id,
                "base_url": base_url,  # 添加IP地址
                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                "status": "offline",
                "speed": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
                "power": {"batteryPercentage": 0, "isCharging": False, "isDCConnected": False, "dockingStatus": "unknown"},
                "health": {"hasError": False, "hasFatal": False, "hasWarning": False, "hasSystemEmergencyStop": False, "hasLidarDisconnected": False, "hasDepthCameraDisconnected": False, "hasSdpDisconnected": False, "baseError": []}
            }
    
    # 并发获取所有机器人的状态
    tasks = [get_single_robot_state(robot_id) for robot_id in robot_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    for result in results:
        if isinstance(result, Exception):
            logger.debug(f"Exception in get_all_robots_states: {result}")
            continue
        robots_states.append(result)
    
    return robots_states


@router.get("/health", response_model=List[dict])
async def get_all_robots_health(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取所有机器人的健康状态
    
    返回所有已注册机器人的健康状态信息，包括：
    - robot_id: 机器人ID
    - status: 机器人状态（IDLE, BUSY, ERROR, OFFLINE）
    - health: 健康状态详情
    - online: 是否在线
    - error: 错误信息（如果有）
    """
    import asyncio
    from typing import Dict, Any
    
    robots_health = []
    robot_ids = robot_manager.list_robots()
    
    if not robot_ids:
        return []
    
    # 并发获取所有机器人的健康状态
    async def get_single_robot_health(robot_id: str) -> Dict[str, Any]:
        """获取单个机器人的健康状态"""
        try:
            state = await robot_manager.get_robot_state(robot_id)
            if not state:
                return {
                    "robot_id": robot_id,
                    "status": "OFFLINE",
                    "online": False,
                    "health": None,
                    "error": "Robot state not available"
                }
            
            # 提取健康信息
            health_info = {
                "hasError": state.health.hasError if state.health else False,
                "hasFatal": state.health.hasFatal if state.health else False,
                "hasWarning": state.health.hasWarning if state.health else False,
                "hasSystemEmergencyStop": state.health.hasSystemEmergencyStop if state.health else False,
                "hasLidarDisconnected": state.health.hasLidarDisconnected if state.health else False,
                "hasDepthCameraDisconnected": state.health.hasDepthCameraDisconnected if state.health else False,
                "hasSdpDisconnected": state.health.hasSdpDisconnected if state.health else False,
                "baseError": state.health.baseError if state.health and state.health.baseError else []
            }
            
            # 判断状态
            status = state.status.value if isinstance(state.status, RobotStatus) else str(state.status)
            
            return {
                "robot_id": robot_id,
                "status": status,
                "online": True,
                "health": health_info,
                "last_update_time": state.last_update_time.isoformat() if state.last_update_time else None,
                "error": None
            }
        except Exception as e:
            logger.error(f"Failed to get health status for robot {robot_id}: {e}", exc_info=True)
            return {
                "robot_id": robot_id,
                "status": "ERROR",
                "online": False,
                "health": None,
                "error": str(e)
            }
    
    # 并发获取所有机器人的健康状态
    tasks = [get_single_robot_health(robot_id) for robot_id in robot_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Exception in get_all_robots_health: {result}", exc_info=True)
            continue
        robots_health.append(result)
    
    return robots_health

