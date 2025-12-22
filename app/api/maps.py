"""
地图管理API
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel
from app.services.map_manager import MapManager, get_map_manager
from app.services.robot_manager import RobotManager, get_robot_manager
# 认证已移除，所有API端点无需授权即可调用

logger = logging.getLogger(__name__)
router = APIRouter()


class LoadMapFromRobotRequest(BaseModel):
    """从机器人加载地图请求"""
    robot_id: str
    name: str
    description: Optional[str] = None


@router.get("/info", response_model=dict)
async def get_map_info(
    map_manager: MapManager = Depends(get_map_manager),
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取地图信息
    
    如果本地地图未加载，但存在已注册的机器人，会自动尝试从第一个可用机器人加载地图。
    """
    # 先检查本地是否已加载地图
    info = map_manager.get_map_info()
    if info:
        return info
    
    # 如果本地地图未加载，尝试从已注册的机器人自动加载
    robot_ids = robot_manager.list_robots()
    if not robot_ids:
        raise HTTPException(
            status_code=404, 
            detail="Map not loaded. Please register a robot first, then load the map using POST /api/maps/load"
        )
    
    # 尝试从第一个可用的机器人加载地图
    errors = []
    for robot_id in robot_ids:
        try:
            robot_agent = robot_manager.get_robot_agent(robot_id)
            if not robot_agent:
                logger.debug(f"Robot agent not found for robot_id: {robot_id}")
                continue
            
            logger.info(f"Attempting to auto-load map from robot: {robot_id}")
            # 尝试从机器人获取地图数据
            map_bytes = await robot_agent.get_map_explore()
            
            # 加载地图
            success = map_manager.load_from_bytes(map_bytes)
            if success:
                # 自动加载虚拟墙信息
                try:
                    import asyncio
                    walls = await asyncio.wait_for(
                        robot_agent.get_virtual_walls(),
                        timeout=3.0
                    )
                    map_manager.virtual_walls = [wall.dict() for wall in walls]
                    logger.info(f"Auto-loaded {len(walls)} virtual walls from robot {robot_id}")
                except Exception as e:
                    logger.debug(f"Failed to auto-load virtual walls from robot {robot_id}: {e}")
                
                # 自动加载限行区域信息
                try:
                    import asyncio
                    areas = await asyncio.wait_for(
                        robot_agent.get_restricted_areas(),
                        timeout=3.0
                    )
                    map_manager.restricted_areas = [area.dict() for area in areas]
                    logger.info(f"Auto-loaded {len(areas)} restricted areas from robot {robot_id}")
                except Exception as e:
                    logger.debug(f"Failed to auto-load restricted areas from robot {robot_id}: {e}")
                
                # 重新获取地图信息
                info = map_manager.get_map_info()
                if info:
                    logger.info(f"Successfully auto-loaded map from robot: {robot_id}")
                    return info
                else:
                    logger.warning(f"Map loaded from robot {robot_id} but get_map_info() returned None")
                    continue
            else:
                logger.warning(f"Failed to load map from bytes for robot: {robot_id}")
                continue
        except Exception as e:
            # 如果这个机器人失败，记录错误并尝试下一个
            error_msg = f"Failed to auto-load map from robot {robot_id}: {str(e)}"
            logger.debug(error_msg, exc_info=True)
            errors.append(error_msg)
            continue
    
    # 所有尝试都失败了
    raise HTTPException(
        status_code=404,
        detail=f"Map not loaded. Failed to auto-load map from registered robots. Please try POST /api/maps/load with a robot_id"
    )


@router.post("/load", response_model=dict)
async def load_map(
    robot_id: str,
    map_manager: MapManager = Depends(get_map_manager),
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    从机器人加载地图
    
    Args:
        robot_id: 机器人ID（用于获取地图数据）
    """
    import asyncio
    try:
        # 获取机器人代理
        robot_agent = robot_manager.get_robot_agent(robot_id)
        if not robot_agent:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        
        # 从机器人获取地图数据
        map_bytes = await robot_agent.get_map_explore()
        
        # 加载地图
        success = map_manager.load_from_bytes(map_bytes)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to load map from bytes")
        
        # 自动加载虚拟墙信息
        try:
            walls = await asyncio.wait_for(
                robot_agent.get_virtual_walls(),
                timeout=3.0
            )
            map_manager.virtual_walls = [wall.dict() for wall in walls]
            logger.info(f"Loaded {len(walls)} virtual walls from robot {robot_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout loading virtual walls from robot {robot_id} (3s), continuing without virtual walls")
        except Exception as e:
            logger.warning(f"Failed to load virtual walls from robot {robot_id}: {e}, continuing without virtual walls")
        
        # 自动加载限行区域信息
        try:
            areas = await asyncio.wait_for(
                robot_agent.get_restricted_areas(),
                timeout=3.0
            )
            map_manager.restricted_areas = [area.dict() for area in areas]
            logger.info(f"Loaded {len(areas)} restricted areas from robot {robot_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout loading restricted areas from robot {robot_id} (3s), continuing without restricted areas")
        except Exception as e:
            logger.warning(f"Failed to load restricted areas from robot {robot_id}: {e}, continuing without restricted areas")
        
        # 返回地图信息
        info = map_manager.get_map_info()
        return {
            "message": "Map loaded successfully",
            "robot_id": robot_id,
            "map_info": info,
            "virtual_walls_count": len(map_manager.virtual_walls),
            "restricted_areas_count": len(map_manager.restricted_areas)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load map: {str(e)}")


@router.post("/load-from-file", response_model=dict)
async def load_map_from_file(
    file: UploadFile = File(...),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    从文件加载地图
    
    Args:
        file: 地图文件（二进制格式）
    """
    try:
        # 读取文件内容
        map_bytes = await file.read()
        
        if len(map_bytes) < 32:
            raise HTTPException(
                status_code=400,
                detail="Map file too short, need at least 32 bytes for metadata"
            )
        
        # 加载地图
        success = map_manager.load_from_bytes(map_bytes)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to load map from file")
        
        # 返回地图信息
        info = map_manager.get_map_info()
        return {
            "message": "Map loaded successfully from file",
            "filename": file.filename,
            "file_size": len(map_bytes),
            "map_info": info
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load map from file: {str(e)}")


@router.get("/check", response_model=dict)
async def check_position(
    x: float,
    y: float,
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    检查位置是否为障碍物
    
    Args:
        x: 世界X坐标
        y: 世界Y坐标
    """
    try:
        is_obstacle = map_manager.is_obstacle(x, y)
        is_free = map_manager.is_free(x, y)
        is_valid = map_manager.is_valid_coordinate(x, y)
        
        return {
            "x": x,
            "y": y,
            "is_obstacle": is_obstacle,
            "is_free": is_free,
            "is_valid": is_valid
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pois", response_model=list)
async def get_all_pois(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    获取所有POI点（轻量级版本，用于多动作任务页面）
    
    返回所有已注册机器人的POI点列表
    """
    import asyncio
    
    robot_ids = robot_manager.list_robots()
    if not robot_ids:
        return []
    
    async def get_robot_pois(robot_id: str):
        """获取单个机器人的POI点（带超时）"""
        try:
            agent = robot_manager.get_robot_agent(robot_id)
            if agent:
                # 添加超时控制，每个机器人最多等待1.5秒
                pois = await asyncio.wait_for(
                    agent.get_all_pois(),
                    timeout=1.5
                )
                return [
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
        except asyncio.TimeoutError:
            logger.debug(f"Timeout getting POIs from robot {robot_id} (1.5s)")
            return []
        except Exception as e:
            logger.debug(f"Failed to get POIs for robot {robot_id}: {e}")
            return []
    
    # 并发获取所有POI点
    poi_tasks = [get_robot_pois(robot_id) for robot_id in robot_ids]
    poi_results = await asyncio.gather(*poi_tasks, return_exceptions=True)
    
    # 展平结果列表，过滤掉异常
    pois_data = []
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
    
    return unique_pois


@router.put("/pois/{poi_id}", response_model=dict)
async def update_poi_name(
    poi_id: str,
    display_name: str,
    robot_id: str,
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    更新POI的显示名称
    
    Args:
        poi_id: POI ID（例如：66dbe769-eec7-4184-a994-8e551b954d48，可以只提供前6位如66dbe7）
        display_name: 新的显示名称
        robot_id: 机器人ID（POI所属的机器人）
    """
    try:
        # 获取机器人代理
        robot_agent = robot_manager.get_robot_agent(robot_id)
        if not robot_agent:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
        
        # 如果只提供了POI ID的前6位，需要先查找完整的POI ID
        pois = await robot_agent.get_all_pois()
        full_poi_id = None
        
        for poi in pois:
            if poi.id == poi_id or poi.id.startswith(poi_id):
                full_poi_id = poi.id
                break
        
        if not full_poi_id:
            raise HTTPException(status_code=404, detail=f"POI {poi_id} not found")
        
        # 尝试更新POI名称
        success = await robot_agent.update_poi(full_poi_id, display_name)
        
        if success:
            return {
                "message": "POI name updated successfully",
                "poi_id": full_poi_id,
                "display_name": display_name
            }
        else:
            # 如果更新失败，返回提示信息
            raise HTTPException(
                status_code=501,
                detail="POI update not supported by robot API. You may need to delete and recreate the POI."
            )
    except HTTPException:
        raise
    except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update POI: {str(e)}")


@router.get("/list", response_model=dict)
async def list_maps(
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取所有地图列表（带缩略图信息）
    """
    try:
        maps = map_manager.list_maps()
        maps_data = []
        for map_info in maps:
            map_dict = map_info.dict()
            # 添加缩略图URL
            if map_info.thumbnail_path:
                map_dict["thumbnail_url"] = f"/api/maps/{map_info.map_id}/thumbnail"
            else:
                map_dict["thumbnail_url"] = None
            maps_data.append(map_dict)
        
        return {
            "maps": maps_data,
            "count": len(maps_data)
        }
    except Exception as e:
        logger.error(f"Failed to list maps: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list maps: {str(e)}")


@router.post("/load-from-robot", response_model=dict)
async def load_map_from_robot(
    request: LoadMapFromRobotRequest,
    map_manager: MapManager = Depends(get_map_manager),
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """
    从机器人加载地图并保存
    
    Args:
        request: 加载地图请求（包含robot_id, name, description）
    """
    try:
        # 获取机器人代理
        robot_agent = robot_manager.get_robot_agent(request.robot_id)
        if not robot_agent:
            raise HTTPException(status_code=404, detail=f"Robot {request.robot_id} not found")
        
        # 从机器人加载并保存地图
        map_id = await map_manager.save_map_from_robot(
            robot_id=request.robot_id,
            name=request.name,
            description=request.description,
            robot_agent=robot_agent
        )
        
        if not map_id:
            raise HTTPException(status_code=500, detail="Failed to save map from robot")
        
        return {
            "message": "Map loaded and saved successfully",
            "map_id": map_id,
            "robot_id": request.robot_id,
            "name": request.name
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load map from robot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load map from robot: {str(e)}")


@router.put("/{map_id}/set-default", response_model=dict)
async def set_default_map(
    map_id: str,
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    设置默认地图
    
    Args:
        map_id: 地图ID
    """
    try:
        success = map_manager.set_default_map(map_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Map {map_id} not found")
        
        return {
            "message": "Default map set successfully",
            "map_id": map_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set default map: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set default map: {str(e)}")


@router.delete("/{map_id}", response_model=dict)
async def delete_map(
    map_id: str,
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    删除地图
    
    Args:
        map_id: 地图ID
    """
    try:
        success = map_manager.delete_map(map_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Map {map_id} not found or cannot be deleted")
        
        return {
            "message": "Map deleted successfully",
            "map_id": map_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete map: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete map: {str(e)}")


@router.get("/{map_id}/thumbnail")
async def get_map_thumbnail(
    map_id: str,
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取地图缩略图
    
    Args:
        map_id: 地图ID
    """
    try:
        if map_id not in map_manager.maps:
            raise HTTPException(status_code=404, detail=f"Map {map_id} not found")
        
        map_info = map_manager.maps[map_id]
        if not map_info.thumbnail_path:
            raise HTTPException(status_code=404, detail="Thumbnail not available")
        
        thumbnail_path = map_manager.maps_storage / map_info.thumbnail_path
        if not thumbnail_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file not found")
        
        return FileResponse(
            thumbnail_path,
            media_type="image/png",
            filename=f"{map_id}_thumbnail.png"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get thumbnail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get thumbnail: {str(e)}")


@router.get("/default", response_model=dict)
async def get_default_map(
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取默认地图的完整数据（用于可视化）
    """
    try:
        map_data = map_manager.get_default_map_data()
        if not map_data:
            raise HTTPException(status_code=404, detail="No default map found")
        
        return {
            "map": map_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get default map: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get default map: {str(e)}")


@router.get("/virtual-walls", response_model=list)
async def get_virtual_walls(
    robot_id: Optional[str] = None,
    robot_manager: RobotManager = Depends(get_robot_manager),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取虚拟墙信息
    
    Args:
        robot_id: 机器人ID（可选，如果不提供则从所有机器人获取）
    """
    import asyncio
    
    try:
        # 如果指定了robot_id，只从该机器人获取
        if robot_id:
            robot_agent = robot_manager.get_robot_agent(robot_id)
            if not robot_agent:
                raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
            
            try:
                walls = await asyncio.wait_for(
                    robot_agent.get_virtual_walls(),
                    timeout=3.0
                )
                # 更新map_manager中的虚拟墙信息
                map_manager.virtual_walls = [wall.dict() for wall in walls]
                return [wall.dict() for wall in walls]
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting virtual walls from robot {robot_id} (3s)")
                # 返回缓存的虚拟墙信息
                return map_manager.virtual_walls
            except Exception as e:
                logger.warning(f"Failed to get virtual walls from robot {robot_id}: {e}")
                # 返回缓存的虚拟墙信息
                return map_manager.virtual_walls
        else:
            # 从所有机器人获取虚拟墙（合并去重）
            robot_ids = robot_manager.list_robots()
            if not robot_ids:
                return map_manager.virtual_walls
            
            async def get_robot_walls(robot_id: str):
                """获取单个机器人的虚拟墙（带超时）"""
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        walls = await asyncio.wait_for(
                            agent.get_virtual_walls(),
                            timeout=2.0
                        )
                        return [wall.dict() for wall in walls]
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting virtual walls from robot {robot_id} (2s)")
                except Exception as e:
                    logger.debug(f"Failed to get virtual walls for robot {robot_id}: {e}")
                return []
            
            # 并发获取所有虚拟墙
            wall_tasks = [get_robot_walls(robot_id) for robot_id in robot_ids]
            wall_results = await asyncio.gather(*wall_tasks, return_exceptions=True)
            
            # 合并所有虚拟墙（按ID去重）
            all_walls = []
            seen_ids = set()
            for wall_list in wall_results:
                if isinstance(wall_list, list):
                    for wall in wall_list:
                        wall_id = wall.get("id")
                        if wall_id is not None and wall_id not in seen_ids:
                            seen_ids.add(wall_id)
                            all_walls.append(wall)
            
            # 更新map_manager中的虚拟墙信息
            map_manager.virtual_walls = all_walls
            return all_walls
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get virtual walls: {e}", exc_info=True)
        # 返回缓存的虚拟墙信息
        return map_manager.virtual_walls


@router.get("/restricted-areas", response_model=list)
async def get_restricted_areas(
    robot_id: Optional[str] = None,
    robot_manager: RobotManager = Depends(get_robot_manager),
    map_manager: MapManager = Depends(get_map_manager)
):
    """
    获取限行区域信息
    
    限行区域用于多机防死锁调度通行，结合等待点实现机器人通行控制。
    
    Args:
        robot_id: 机器人ID（可选，如果不提供则从所有机器人获取）
    """
    import asyncio
    
    try:
        # 如果指定了robot_id，只从该机器人获取
        if robot_id:
            robot_agent = robot_manager.get_robot_agent(robot_id)
            if not robot_agent:
                raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found")
            
            try:
                areas = await asyncio.wait_for(
                    robot_agent.get_restricted_areas(),
                    timeout=3.0
                )
                # 更新map_manager中的限行区域信息
                map_manager.restricted_areas = [area.dict() for area in areas]
                return [area.dict() for area in areas]
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting restricted areas from robot {robot_id} (3s)")
                # 返回缓存的限行区域信息
                return map_manager.restricted_areas
            except Exception as e:
                logger.warning(f"Failed to get restricted areas from robot {robot_id}: {e}")
                # 返回缓存的限行区域信息
                return map_manager.restricted_areas
        else:
            # 从所有机器人获取限行区域（合并去重）
            robot_ids = robot_manager.list_robots()
            if not robot_ids:
                return map_manager.restricted_areas
            
            async def get_robot_areas(robot_id: str):
                """获取单个机器人的限行区域（带超时）"""
                try:
                    agent = robot_manager.get_robot_agent(robot_id)
                    if agent:
                        areas = await asyncio.wait_for(
                            agent.get_restricted_areas(),
                            timeout=2.0
                        )
                        return [area.dict() for area in areas]
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting restricted areas from robot {robot_id} (2s)")
                except Exception as e:
                    logger.debug(f"Failed to get restricted areas for robot {robot_id}: {e}")
                return []
            
            # 并发获取所有限行区域
            area_tasks = [get_robot_areas(robot_id) for robot_id in robot_ids]
            area_results = await asyncio.gather(*area_tasks, return_exceptions=True)
            
            # 合并所有限行区域（按ID去重）
            all_areas = []
            seen_ids = set()
            for area_list in area_results:
                if isinstance(area_list, list):
                    for area in area_list:
                        area_id = area.get("id")
                        if area_id is not None and area_id not in seen_ids:
                            seen_ids.add(area_id)
                            all_areas.append(area)
            
            # 更新map_manager中的限行区域信息
            map_manager.restricted_areas = all_areas
            return all_areas
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get restricted areas: {e}", exc_info=True)
        # 返回缓存的限行区域信息
        return map_manager.restricted_areas

