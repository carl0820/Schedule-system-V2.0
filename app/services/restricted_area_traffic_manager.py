"""
限行区域通行管理器
结合等待点实现多机防死锁调度通行
"""
import math
import logging
import asyncio
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
from app.models.robot import Pose
from app.services.map_manager import MapManager
from app.services.robot_manager import RobotManager
from app.services.path_planner import PathPlanner
from app.services.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class RestrictedAreaTrafficManager:
    """限行区域通行管理器"""
    
    # 每0.9米允许1台机器人
    ROBOT_CAPACITY_PER_METER = 0.9
    
    def __init__(
        self,
        map_manager: MapManager,
        robot_manager: RobotManager,
        path_planner: PathPlanner,
        config_manager: ConfigManager,
        task_scheduler=None
    ):
        self.map_manager = map_manager
        self.robot_manager = robot_manager
        self.path_planner = path_planner
        self.config_manager = config_manager
        self.task_scheduler = task_scheduler  # 任务调度器引用，用于获取任务优先级
        
        # 限行区域通行状态
        # {area_id: {'robots': [robot_id], 'waiting_queue': [(robot_id, priority, task_id, enter_time)], 'capacity': int}}
        self.area_traffic: Dict[int, Dict] = {}
        
        # 机器人等待状态
        # {robot_id: {'area_id': int, 'waiting_point': Pose, 'original_task_id': str, 'waiting_since': datetime}}
        self.robot_waiting_status: Dict[str, Dict] = {}
        
        # 机器人进入限行区域的时间记录（用于动态调整优先级）
        # {robot_id: {'area_id': int, 'enter_time': datetime}}
        self.robot_enter_time: Dict[str, Dict] = {}
        
        # POI等待点列表（从配置或机器人获取）
        self.poi_waiting_points: List[Dict] = []
        
        # 动态优先级调整计数器（当优先级一致时使用）
        self.priority_adjustment_counter: Dict[str, int] = {}
    
    def calculate_capacity(self, half_width: float) -> int:
        """
        根据限行区域宽度计算允许的机器人数量
        
        Args:
            half_width: 限行区域的半宽度（米）
            
        Returns:
            允许的机器人数量
        """
        width = half_width * 2  # 总宽度
        capacity = max(1, int(width / self.ROBOT_CAPACITY_PER_METER))
        return capacity
    
    def is_point_in_restricted_area(
        self,
        point: Pose,
        area_start: Dict[str, float],
        area_end: Dict[str, float],
        half_width: float
    ) -> bool:
        """
        判断点是否在限行区域内（机器人中心点）
        
        Args:
            point: 要检查的点（机器人中心）
            area_start: 限行区域起点 {"x": float, "y": float}
            area_end: 限行区域终点 {"x": float, "y": float}
            half_width: 限行区域半宽度（米）
            
        Returns:
            是否在限行区域内
        """
        # 计算线段方向向量
        dx = area_end["x"] - area_start["x"]
        dy = area_end["y"] - area_start["y"]
        length = math.sqrt(dx * dx + dy * dy)
        
        if length == 0:
            return False
        
        # 归一化方向向量
        unit_x = dx / length
        unit_y = dy / length
        
        # 计算点到起点的向量
        px = point.x - area_start["x"]
        py = point.y - area_start["y"]
        
        # 计算点在线段上的投影长度
        projection = px * unit_x + py * unit_y
        
        # 检查投影是否在线段范围内
        if projection < 0 or projection > length:
            return False
        
        # 计算点到线段的垂直距离
        perp_x = px - projection * unit_x
        perp_y = py - projection * unit_y
        distance = math.sqrt(perp_x * perp_x + perp_y * perp_y)
        
        # 检查距离是否小于半宽度
        return distance <= half_width
    
    async def load_poi_waiting_points(self):
        """加载POI等待点（从配置或机器人获取）"""
        try:
            # 1. 从配置中获取POI等待点列表
            config = self.config_manager.get_config()
            poi_waiting_point_names = config.get("deadlock", {}).get("poi_waiting_points", [])
            
            if poi_waiting_point_names:
                # 从机器人获取POI信息
                robot_ids = self.robot_manager.list_robots()
                for robot_id in robot_ids:
                    try:
                        agent = self.robot_manager.get_robot_agent(robot_id)
                        if agent:
                            pois = await asyncio.wait_for(
                                agent.get_all_pois(),
                                timeout=2.0
                            )
                            
                            for poi in pois:
                                display_name = poi.metadata.get("display_name", "") if poi.metadata else ""
                                poi_id = poi.id
                                
                                # 检查POI名称是否在等待点列表中
                                if display_name in poi_waiting_point_names or poi_id in poi_waiting_point_names:
                                    if poi.pose:
                                        self.poi_waiting_points.append({
                                            "name": display_name or poi_id,
                                            "pose": poi.pose,
                                            "poi_id": poi_id
                                        })
                                        logger.info(
                                            f"[RESTRICTED AREA] Loaded POI waiting point: {display_name} "
                                            f"at ({poi.pose.x:.2f}, {poi.pose.y:.2f})"
                                        )
                            
                            # 找到POI后停止查找
                            if self.poi_waiting_points:
                                break
                    except Exception as e:
                        logger.debug(f"Failed to load POIs from robot {robot_id}: {e}")
                        continue
            
            # 2. 如果没有POI等待点，使用预定义等待点
            if not self.poi_waiting_points:
                predefined_points = config.get("deadlock", {}).get("predefined_waiting_points", [])
                for wp in predefined_points:
                    self.poi_waiting_points.append({
                        "name": wp.get("name", "Predefined"),
                        "pose": Pose(
                            x=wp["x"],
                            y=wp["y"],
                            z=wp.get("z", 0.0),
                            yaw=wp.get("yaw", 0.0)
                        )
                    })
                    logger.info(
                        f"[RESTRICTED AREA] Loaded predefined waiting point: {wp.get('name', 'Unknown')} "
                        f"at ({wp['x']:.2f}, {wp['y']:.2f})"
                    )
            
            logger.info(f"[RESTRICTED AREA] Loaded {len(self.poi_waiting_points)} waiting points")
        except Exception as e:
            logger.error(f"Failed to load POI waiting points: {e}", exc_info=True)
    
    def find_waiting_point_near_restricted_area(
        self,
        area_start: Dict[str, float],
        area_end: Dict[str, float],
        half_width: float,
        robot_pose: Pose,
        max_distance: float = 8.0,
        exclude_points: Optional[List[Tuple[float, float]]] = None
    ) -> Optional[Pose]:
        """
        在限行区域周围查找等待点
        
        优先级：
        1. POI等待点（部署的）
        2. 预定义等待点
        3. 系统自动生成的等待点（靠边部署）
        
        Args:
            area_start: 限行区域起点
            area_end: 限行区域终点
            half_width: 限行区域半宽度
            robot_pose: 机器人当前位置
            max_distance: 最大搜索距离（米）
            exclude_points: 要排除的等待点列表（格式：[(x, y), ...]）
            
        Returns:
            等待点位置，如果找不到则返回None
        """
        # 计算限行区域中心
        center_x = (area_start["x"] + area_end["x"]) / 2
        center_y = (area_start["y"] + area_end["y"]) / 2
        
        # 1. 优先使用POI等待点
        # 如果POI等待点列表为空，尝试重新加载
        if not self.poi_waiting_points:
            try:
                # 尝试同步加载POI等待点（如果可能）
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，创建任务异步加载
                    asyncio.create_task(self.load_poi_waiting_points())
                else:
                    # 如果事件循环没有运行，直接运行
                    loop.run_until_complete(self.load_poi_waiting_points())
            except Exception as e:
                logger.debug(f"Failed to reload POI waiting points: {e}")
        
        if self.poi_waiting_points:
            best_poi = None
            min_distance = float('inf')
            
            # 优先选择距离机器人最近的POI等待点（放宽距离限制，优先使用POI等待点）
            for poi_wp in self.poi_waiting_points:
                wp_pose = poi_wp["pose"]
                
                # 检查是否在排除列表中
                if exclude_points:
                    is_excluded = False
                    for excl_x, excl_y in exclude_points:
                        dist_to_excluded = math.sqrt(
                            (wp_pose.x - excl_x) ** 2 + 
                            (wp_pose.y - excl_y) ** 2
                        )
                        if dist_to_excluded < 0.5:  # 如果距离小于0.5米，认为是同一个点
                            is_excluded = True
                            break
                    if is_excluded:
                        continue  # 跳过已排除的点
                
                # 计算到机器人当前位置的距离
                dist_to_robot = math.sqrt(
                    (wp_pose.x - robot_pose.x) ** 2 + 
                    (wp_pose.y - robot_pose.y) ** 2
                )
                
                # 放宽距离限制：如果POI等待点在max_distance * 3范围内，可以使用（优先使用POI等待点）
                if dist_to_robot <= max_distance * 3:
                    if dist_to_robot < min_distance:
                        min_distance = dist_to_robot
                        best_poi = wp_pose
            
            if best_poi:
                # 查找对应的POI名称
                poi_name = "Unknown"
                for poi_wp in self.poi_waiting_points:
                    if poi_wp["pose"].x == best_poi.x and poi_wp["pose"].y == best_poi.y:
                        poi_name = poi_wp.get("name", "Unknown")
                        break
                logger.info(
                    f"[RESTRICTED AREA] Selected POI waiting point '{poi_name}' "
                    f"at ({best_poi.x:.2f}, {best_poi.y:.2f}), "
                    f"distance to robot: {min_distance:.2f}m"
                )
                return best_poi
            else:
                logger.debug(
                    f"[RESTRICTED AREA] POI waiting points available but none within {max_distance * 3:.1f}m "
                    f"of robot at ({robot_pose.x:.2f}, {robot_pose.y:.2f})"
                )
        
        # 2. 如果没有POI等待点，使用系统生成的等待点（靠边部署）
        return self._generate_waiting_point_near_area(
            area_start, area_end, half_width, robot_pose, max_distance
        )
    
    def _generate_waiting_point_near_area(
        self,
        area_start: Dict[str, float],
        area_end: Dict[str, float],
        half_width: float,
        robot_pose: Pose,
        max_distance: float
    ) -> Optional[Pose]:
        """
        系统自动生成等待点（靠边部署，防止堵塞）
        
        参考示意图：在限行区域周围8个方向部署等待点
        """
        # 计算限行区域中心
        center_x = (area_start["x"] + area_end["x"]) / 2
        center_y = (area_start["y"] + area_end["y"]) / 2
        
        # 计算线段方向
        dx = area_end["x"] - area_start["x"]
        dy = area_end["y"] - area_start["y"]
        length = math.sqrt(dx * dx + dy * dy)
        
        if length == 0:
            return None
        
        # 归一化方向向量
        unit_x = dx / length
        unit_y = dy / length
        
        # 垂直方向向量（用于计算宽度方向）
        perp_x = -unit_y
        perp_y = unit_x
        
        # 计算等待点位置（8个方向：4个主要方向 + 4个对角线方向）
        # 主要方向：上下左右
        directions = [
            (0, 1),      # 上
            (0, -1),     # 下
            (1, 0),      # 右
            (-1, 0),     # 左
            (1, 1),      # 右上
            (-1, 1),     # 左上
            (1, -1),     # 右下
            (-1, -1)     # 左下
        ]
        
        # 计算限行区域的扩展边界（加上half_width和距离）
        distance_from_edge = 3.0  # 距离边缘3米
        total_offset = half_width + distance_from_edge
        
        best_point = None
        min_distance = float('inf')
        
        for dir_x, dir_y in directions:
            # 计算等待点位置（从中心点向外偏移）
            offset_x = dir_x * total_offset
            offset_y = dir_y * total_offset
            
            # 转换为世界坐标（考虑限行区域的方向）
            wp_x = center_x + offset_x * perp_x - offset_y * unit_x
            wp_y = center_y + offset_x * perp_y - offset_y * unit_y
            
            # 检查位置是否有效（不在障碍物上）
            if self.path_planner and self.map_manager.metadata:
                map_x, map_y = self.map_manager.world_to_map(wp_x, wp_y)
                if self.path_planner._is_valid_position(map_x, map_y, robot_radius=0.3):
                    # 计算到机器人当前位置的距离
                    dist_to_robot = math.sqrt(
                        (wp_x - robot_pose.x) ** 2 + 
                        (wp_y - robot_pose.y) ** 2
                    )
                    
                    if dist_to_robot < min_distance:
                        min_distance = dist_to_robot
                        best_point = Pose(x=wp_x, y=wp_y, z=0.0, yaw=0.0)
        
        if best_point:
            logger.info(
                f"[RESTRICTED AREA] Generated waiting point at ({best_point.x:.2f}, {best_point.y:.2f})"
            )
        
        return best_point
    
    def _adjust_priority_when_equal(
        self,
        robot_id: str,
        base_priority: float,
        enter_time: Optional[datetime] = None
    ) -> float:
        """
        当优先级一致时，动态调整优先级
        
        调整策略：
        1. 先进入限行区域的机器人优先级更高（FIFO）
        2. 如果同时进入，使用计数器确保公平
        
        Args:
            robot_id: 机器人ID
            base_priority: 基础优先级
            enter_time: 进入限行区域的时间
            
        Returns:
            调整后的优先级
        """
        # 如果提供了进入时间，使用进入时间作为调整因子
        if enter_time:
            # 先进入的优先级更高（时间戳越小，优先级越高）
            # 转换为优先级调整：时间差（秒）作为微调
            time_diff = (datetime.now() - enter_time).total_seconds()
            # 时间差越小，优先级越高（加上一个小的调整值）
            # 增加调整幅度，确保即使时间差很小也能有效区分
            adjustment = -time_diff * 0.05  # 每1秒降低0.05优先级（增加调整幅度）
        else:
            # 使用计数器确保公平
            if robot_id not in self.priority_adjustment_counter:
                self.priority_adjustment_counter[robot_id] = 0
            
            # 计数器越大，优先级越低（确保公平轮换）
            # 增加调整幅度，确保即使计数器相同也能有效区分
            adjustment = -self.priority_adjustment_counter[robot_id] * 0.01
        
        return base_priority + adjustment
    
    async def check_and_manage_traffic(
        self,
        robot_id: str,
        robot_pose: Pose,
        task_priority: float,
        task_id: str
    ) -> Tuple[bool, Optional[Pose], Optional[str]]:
        """
        检查并管理限行区域通行
        
        Args:
            robot_id: 机器人ID
            robot_pose: 机器人当前位置
            task_priority: 任务优先级（值越小优先级越高）
            task_id: 任务ID
            
        Returns:
            (是否允许通行, 等待点位置, 错误信息)
            - 如果允许通行：返回 (True, None, None)
            - 如果需要等待：返回 (False, waiting_point, None)
            - 如果出错：返回 (False, None, error_message)
        """
        # 获取所有限行区域
        restricted_areas = self.map_manager.restricted_areas
        
        if not restricted_areas:
            return True, None, None  # 没有限行区域，允许通行
        
        # 检查机器人是否在某个限行区域内
        for area in restricted_areas:
            area_id = area.get("id")
            area_data = area.get("area", {})
            
            if not area_data:
                continue
            
            start = area_data.get("start", {})
            end = area_data.get("end", {})
            half_width = area_data.get("half_width", 0.5)
            
            if not start or not end:
                continue
            
            # 检查机器人是否在限行区域内
            is_in_area = self.is_point_in_restricted_area(robot_pose, start, end, half_width)
            
            if is_in_area:
                # 机器人在限行区域内
                capacity = self.calculate_capacity(half_width)
                
                # 初始化限行区域通行状态
                if area_id not in self.area_traffic:
                    self.area_traffic[area_id] = {
                        'robots': [],
                        'waiting_queue': [],
                        'capacity': capacity
                    }
                
                traffic = self.area_traffic[area_id]
                
                # 检查当前通行数量
                current_count = len(traffic['robots'])
                
                # 如果机器人已经在通行列表中
                if robot_id in traffic['robots']:
                    # 检查容量是否超限（可能其他机器人也进入了）
                    if current_count > capacity:
                        # 容量超限，需要检查优先级，让低优先级的机器人退出
                        # 计算需要退出的机器人数量
                        overflow_count = current_count - capacity
                        
                        # 获取当前通行列表中所有机器人的优先级
                        robots_in_area = traffic['robots'].copy()
                        robot_priorities = []
                        
                        for rid in robots_in_area:
                            # 获取该机器人的任务优先级
                            # 如果机器人有等待状态，说明之前有任务，但优先级可能已变化
                            # 这里使用默认优先级，因为无法直接获取其他机器人的任务优先级
                            # 更好的方法是在monitor_robots中处理容量超限
                            rid_priority = task_priority if rid == robot_id else 2.0  # 默认中等优先级
                            
                            # 如果机器人有进入时间，用于公平性调整
                            enter_time = self.robot_enter_time.get(rid, {}).get('enter_time', datetime.now())
                            adjusted_priority = self._adjust_priority_when_equal(rid, rid_priority, enter_time)
                            robot_priorities.append((rid, adjusted_priority, enter_time))
                        
                        # 按优先级排序（优先级高的在前，值小的在前）
                        robot_priorities.sort(key=lambda x: (x[1], x[2]))
                        
                        # 让优先级最低的 overflow_count 台机器人退出
                        robots_to_remove = []
                        for i in range(overflow_count):
                            if i < len(robot_priorities):
                                robots_to_remove.append(robot_priorities[-(i+1)][0])  # 从后往前取（优先级最低的）
                        
                        # 如果当前机器人在需要退出的列表中，需要退出到等待点
                        if robot_id in robots_to_remove:
                            # 当前机器人需要退出到等待点
                            traffic['robots'].remove(robot_id)
                            if robot_id in self.robot_enter_time:
                                del self.robot_enter_time[robot_id]
                            
                            logger.warning(
                                f"[RESTRICTED AREA] Robot {robot_id} needs to exit over-capacity area {area_id} "
                                f"(current: {current_count}/{capacity}, overflow: {overflow_count}, "
                                f"robots to remove: {robots_to_remove})"
                            )
                            
                            # 查找等待点并返回，让调用方处理前往等待点的逻辑
                            waiting_point = self.find_waiting_point_near_restricted_area(
                                start, end, half_width, robot_pose, max_distance=8.0
                            )
                            
                            if waiting_point:
                                # 记录等待状态
                                self.robot_waiting_status[robot_id] = {
                                    'area_id': area_id,
                                    'waiting_point': waiting_point,
                                    'original_task_id': task_id,
                                    'waiting_since': datetime.now()
                                }
                                
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {robot_id} needs to exit to waiting point "
                                    f"({waiting_point.x:.2f}, {waiting_point.y:.2f}) for area {area_id}"
                                )
                                
                                return False, waiting_point, None
                            else:
                                # 如果找不到等待点，记录错误但返回False，让调用方知道不能通行
                                logger.error(
                                    f"[RESTRICTED AREA] Robot {robot_id} needs to exit area {area_id} "
                                    f"but no waiting point found"
                                )
                                return False, None, "No suitable waiting point found for capacity overflow"
                        else:
                            # 当前机器人不在需要退出的列表中，允许继续（高优先级的会继续通行）
                            # 但需要移除其他低优先级的机器人，并触发它们前往等待点
                            # 注意：这里只从列表中移除，实际发送等待点指令由_check_and_resolve_capacity_overflow处理
                            # 但为了确保及时处理，我们在这里也触发一次容量检查
                            for rid in robots_to_remove:
                                if rid in traffic['robots']:
                                    traffic['robots'].remove(rid)
                                if rid in self.robot_enter_time:
                                    del self.robot_enter_time[rid]
                                logger.warning(
                                    f"[RESTRICTED AREA] Robot {rid} removed from over-capacity area {area_id} "
                                    f"(priority-based removal). Will be sent to waiting point by monitor_robots."
                                )
                            
                            # 触发容量检查，确保低优先级机器人被发送到等待点
                            # 使用异步任务，不阻塞当前流程
                            asyncio.create_task(self._check_and_resolve_capacity_overflow())
                            
                            # 更新进入时间（如果还没有记录）
                            if robot_id not in self.robot_enter_time:
                                self.robot_enter_time[robot_id] = {
                                    'area_id': area_id,
                                    'enter_time': datetime.now()
                                }
                            return True, None, None
                    else:
                        # 容量未超限，允许继续
                        # 更新进入时间（如果还没有记录）
                        if robot_id not in self.robot_enter_time:
                            self.robot_enter_time[robot_id] = {
                                'area_id': area_id,
                                'enter_time': datetime.now()
                            }
                        return True, None, None
                
                # 检查当前通行数量（更新后的）
                current_count = len(traffic['robots'])
                
                if current_count < capacity:
                    # 还有容量，允许通行
                    traffic['robots'].append(robot_id)
                    self.robot_enter_time[robot_id] = {
                        'area_id': area_id,
                        'enter_time': datetime.now()
                    }
                    logger.info(
                        f"[RESTRICTED AREA] Robot {robot_id} allowed to pass through "
                        f"restricted area {area_id} ({len(traffic['robots'])}/{capacity})"
                    )
                    return True, None, None
                else:
                    # 超过容量，需要等待
                    # 检查是否已经在等待队列中
                    waiting_index = None
                    for idx, (wid, _, _, _) in enumerate(traffic['waiting_queue']):
                        if wid == robot_id:
                            waiting_index = idx
                            break
                    
                    if waiting_index is None:
                        # 动态调整优先级（当优先级一致时）
                        adjusted_priority = self._adjust_priority_when_equal(
                            robot_id, task_priority, datetime.now()
                        )
                        
                        # 添加到等待队列（按优先级排序，优先级高的在前）
                        traffic['waiting_queue'].append((
                            robot_id, 
                            adjusted_priority, 
                            task_id,
                            datetime.now()  # 进入等待队列的时间
                        ))
                        traffic['waiting_queue'].sort(key=lambda x: x[1])  # 按优先级排序
                    
                    # 查找等待点
                    waiting_point = self.find_waiting_point_near_restricted_area(
                        start, end, half_width, robot_pose, max_distance=8.0
                    )
                    
                    if waiting_point:
                        # 记录等待状态
                        self.robot_waiting_status[robot_id] = {
                            'area_id': area_id,
                            'waiting_point': waiting_point,
                            'original_task_id': task_id,
                            'waiting_since': datetime.now()
                        }
                        
                        logger.info(
                            f"[RESTRICTED AREA] Robot {robot_id} needs to wait at waiting point "
                            f"for restricted area {area_id} (capacity: {capacity}, current: {current_count}, "
                            f"queue position: {waiting_index + 1 if waiting_index is not None else len(traffic['waiting_queue'])}/{len(traffic['waiting_queue'])})"
                        )
                        
                        return False, waiting_point, None
                    else:
                        return False, None, "No suitable waiting point found"
        
        # 机器人不在任何限行区域内
        # 检查是否需要释放之前的占用
        await self._check_robot_left_area(robot_id, robot_pose)
        
        # 如果机器人不在限行区域内，但还在等待状态中，应该清除等待状态
        # 避免不在限行区域的机器人不断被要求移动到等待点
        if robot_id in self.robot_waiting_status:
            waiting_area_id = self.robot_waiting_status[robot_id].get('area_id')
            logger.info(
                f"[RESTRICTED AREA] Robot {robot_id} is not in any restricted area, "
                f"but still in waiting status for area {waiting_area_id}, clearing waiting status"
            )
            # 从等待队列中移除
            if waiting_area_id in self.area_traffic:
                traffic = self.area_traffic[waiting_area_id]
                if traffic['waiting_queue']:
                    traffic['waiting_queue'] = [
                        (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                        if wid != robot_id
                    ]
            # 清除等待状态
            del self.robot_waiting_status[robot_id]
        
        return True, None, None
    
    async def _check_robot_left_area(self, robot_id: str, robot_pose: Pose):
        """
        检查机器人是否离开了限行区域（实时监测）
        
        Args:
            robot_id: 机器人ID
            robot_pose: 机器人当前位置
        """
        # 检查机器人是否在某个限行区域内
        restricted_areas = self.map_manager.restricted_areas
        
        if robot_id in self.robot_enter_time:
            area_id = self.robot_enter_time[robot_id]['area_id']
            
            # 查找对应的限行区域
            for area in restricted_areas:
                if area.get("id") == area_id:
                    area_data = area.get("area", {})
                    if area_data:
                        start = area_data.get("start", {})
                        end = area_data.get("end", {})
                        half_width = area_data.get("half_width", 0.5)
                        
                        if start and end:
                            # 检查机器人是否还在限行区域内
                            is_in_area = self.is_point_in_restricted_area(
                                robot_pose, start, end, half_width
                            )
                            
                            if not is_in_area:
                                # 机器人已离开限行区域，释放占用
                                await self.release_robot_from_area(robot_id, area_id)
                            break
    
    async def check_waiting_robots(self):
        """
        检查等待中的机器人是否可以通行
        
        当限行区域有空位时，按优先级顺序让等待的机器人通行
        """
        for area_id, traffic in list(self.area_traffic.items()):
            capacity = traffic.get('capacity', 1)
            current_count = len(traffic['robots'])
            
            # 检查是否有空位
            if current_count < capacity and traffic['waiting_queue']:
                # 有空位，让优先级最高的机器人通行（队列已经按优先级排序）
                robot_id, priority, task_id, enter_time = traffic['waiting_queue'].pop(0)
                
                # 添加到通行列表
                traffic['robots'].append(robot_id)
                
                # 记录进入时间
                self.robot_enter_time[robot_id] = {
                    'area_id': area_id,
                    'enter_time': datetime.now()
                }
                
                # 清除等待状态（这样任务调度器会检测到并恢复任务）
                if robot_id in self.robot_waiting_status:
                    del self.robot_waiting_status[robot_id]
                
                # 增加计数器（用于公平性）
                if robot_id in self.priority_adjustment_counter:
                    self.priority_adjustment_counter[robot_id] += 1
                else:
                    self.priority_adjustment_counter[robot_id] = 1
                
                logger.info(
                    f"[RESTRICTED AREA] Robot {robot_id} can now pass through "
                    f"restricted area {area_id} (priority: {priority:.3f}, "
                    f"queue wait time: {(datetime.now() - enter_time).total_seconds():.1f}s, "
                    f"current: {len(traffic['robots'])}/{capacity})"
                )
                
                # 直接触发任务恢复（如果任务调度器可用）
                if self.task_scheduler:
                    try:
                        # 获取任务并恢复
                        task = self.task_scheduler.tasks.get(task_id)
                        if task and task.status.value in ["executing", "assigned"]:
                            logger.info(
                                f"[RESTRICTED AREA] Triggering immediate task resume for robot {robot_id}, task {task_id}"
                            )
                            # 清除action_id，准备重新执行
                            task.action_id = None
                            # 立即触发任务恢复（不等待调度循环）
                            await self.task_scheduler._check_and_resume_waiting_robots()
                            # 触发调度事件，确保任务立即被处理
                            if self.task_scheduler._scheduler_event:
                                self.task_scheduler._scheduler_event.set()
                    except Exception as e:
                        logger.warning(f"[RESTRICTED AREA] Failed to trigger task resume for robot {robot_id}: {e}")
                
                # 继续检查是否还有空位（可能一次释放多个机器人）
                # 注意：这里使用while循环，确保所有可以通行的机器人都能通行
                while len(traffic['robots']) < capacity and traffic['waiting_queue']:
                    robot_id, priority, task_id, enter_time = traffic['waiting_queue'].pop(0)
                    traffic['robots'].append(robot_id)
                    self.robot_enter_time[robot_id] = {
                        'area_id': area_id,
                        'enter_time': datetime.now()
                    }
                    if robot_id in self.robot_waiting_status:
                        del self.robot_waiting_status[robot_id]
                    logger.info(
                        f"[RESTRICTED AREA] Robot {robot_id} can now pass through "
                        f"restricted area {area_id} (priority: {priority:.3f}, "
                        f"current: {len(traffic['robots'])}/{capacity})"
                    )
                    # 直接触发任务恢复（如果任务调度器可用）
                    if self.task_scheduler:
                        try:
                            task = self.task_scheduler.tasks.get(task_id)
                            if task and task.status.value in ["executing", "assigned"]:
                                logger.info(
                                    f"[RESTRICTED AREA] Triggering immediate task resume for robot {robot_id}, task {task_id}"
                                )
                                task.action_id = None
                                # 立即触发任务恢复（不等待调度循环）
                                await self.task_scheduler._check_and_resume_waiting_robots()
                                # 触发调度事件，确保任务立即被处理
                                if self.task_scheduler._scheduler_event:
                                    self.task_scheduler._scheduler_event.set()
                        except Exception as e:
                            logger.warning(f"[RESTRICTED AREA] Failed to trigger task resume for robot {robot_id}: {e}")
    
    async def release_robot_from_area(self, robot_id: str, area_id: int):
        """
        释放机器人在限行区域的占用
        
        Args:
            robot_id: 机器人ID
            area_id: 限行区域ID
        """
        if area_id in self.area_traffic:
            traffic = self.area_traffic[area_id]
            if robot_id in traffic['robots']:
                traffic['robots'].remove(robot_id)
                logger.info(
                    f"[RESTRICTED AREA] Robot {robot_id} released from restricted area {area_id}"
                )
                
                # 清除进入时间记录
                if robot_id in self.robot_enter_time:
                    del self.robot_enter_time[robot_id]
                
                # 检查等待队列
                await self.check_waiting_robots()
    
    async def monitor_robots(self):
        """
        实时监测机器人位置，判断是否离开限行区域
        同时检查容量超限情况，让低优先级的机器人退出
        检查等待中的机器人是否无法到达等待点，如果是则更新为新的等待点
        检查长时间卡在限行区域的机器人，强制触发恢复
        
        这个方法应该在调度循环中定期调用
        """
        # 首先检查所有限行区域的容量超限情况（处理多台机器人的情况）
        await self._check_and_resolve_capacity_overflow()
        
        # 检查等待中的机器人是否无法到达等待点
        await self._check_waiting_robots_unreachable_points()
        
        # 检查长时间卡在限行区域的机器人（强制恢复机制）
        await self._check_stuck_robots_in_restricted_area()
        
        # 检查限行区域内机器人之间的直接阻塞（一个机器人被另一个机器人卡住）
        await self._check_direct_blocking_in_restricted_area()
        
        # 然后检查机器人是否离开限行区域
        robot_ids = self.robot_manager.list_robots()
        for robot_id in robot_ids:
            try:
                robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=False)
                if robot_state and robot_state.pose:
                    await self._check_robot_left_area(robot_id, robot_state.pose)
            except Exception as e:
                logger.debug(f"Failed to monitor robot {robot_id} position: {e}")
    
    async def _check_and_resolve_capacity_overflow(self, force_unlock: bool = False):
        """
        检查并解决限行区域容量超限问题（支持多台机器人，2台以上）
        
        如果多台机器人都在限行区内但容量超限，让低优先级的机器人退出到等待点
        
        Args:
            force_unlock: 如果为True，强制解锁所有超限的机器人（即使正在回桩也会移除）
        """
        restricted_areas = self.map_manager.restricted_areas
        
        for area in restricted_areas:
            area_id = area.get("id")
            area_data = area.get("area", {})
            
            if not area_data:
                continue
            
            start = area_data.get("start", {})
            end = area_data.get("end", {})
            half_width = area_data.get("half_width", 0.5)
            
            if not start or not end:
                continue
            
            capacity = self.calculate_capacity(half_width)
            
            # 初始化限行区域通行状态（如果还没有）
            if area_id not in self.area_traffic:
                self.area_traffic[area_id] = {
                    'robots': [],
                    'waiting_queue': [],
                    'capacity': capacity
                }
            
            traffic = self.area_traffic[area_id]
            traffic['capacity'] = capacity  # 更新容量（可能限行区域配置已变化）
            
            # 首先检查所有在线机器人，确保在限行区内的机器人都被添加到列表中
            robot_ids = self.robot_manager.list_robots()
            for robot_id in robot_ids:
                try:
                    robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=False)
                    if not robot_state or not robot_state.pose:
                        continue
                    
                    # 检查机器人是否在限行区内
                    is_in_area = self.is_point_in_restricted_area(
                        robot_state.pose, start, end, half_width
                    )
                    
                    if is_in_area:
                        # 机器人在限行区内，确保它在通行列表中
                        if robot_id not in traffic['robots']:
                            # 机器人不在列表中，添加它
                            traffic['robots'].append(robot_id)
                            if robot_id not in self.robot_enter_time:
                                self.robot_enter_time[robot_id] = {
                                    'area_id': area_id,
                                    'enter_time': datetime.now()
                                }
                            logger.info(
                                f"[RESTRICTED AREA] Robot {robot_id} detected in area {area_id} "
                                f"and added to traffic list (current: {len(traffic['robots'])}/{capacity})"
                            )
                except Exception as e:
                    logger.debug(f"Failed to check robot {robot_id} for area {area_id}: {e}")
            
            robots_in_area = traffic['robots'].copy()
            current_count = len(robots_in_area)
            
            # 如果容量超限，需要让低优先级的机器人退出
            if current_count > capacity:
                overflow_count = current_count - capacity
                logger.warning(
                    f"[RESTRICTED AREA] Area {area_id} capacity overflow: {current_count}/{capacity}, "
                    f"need to remove {overflow_count} robots, current robots: {robots_in_area}"
                )
                
                # 获取所有在限行区内的机器人的实际位置和优先级
                robot_info_list = []
                for robot_id in robots_in_area:
                    try:
                        robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=False)
                        if not robot_state or not robot_state.pose:
                            continue
                        
                        # 检查机器人是否真的在限行区内
                        start = area_data.get("start", {})
                        end = area_data.get("end", {})
                        half_width = area_data.get("half_width", 0.5)
                        
                        if not start or not end:
                            continue
                        
                        is_in_area = self.is_point_in_restricted_area(
                            robot_state.pose, start, end, half_width
                        )
                        
                        if not is_in_area:
                            # 机器人不在限行区内，应该从通行列表中移除
                            if robot_id in traffic['robots']:
                                traffic['robots'].remove(robot_id)
                            if robot_id in self.robot_enter_time:
                                del self.robot_enter_time[robot_id]
                            logger.info(
                                f"[RESTRICTED AREA] Robot {robot_id} not actually in area {area_id}, removed from traffic list"
                            )
                            continue
                        
                        # 获取任务优先级（优先从任务调度器获取，否则使用默认值）
                        enter_time = self.robot_enter_time.get(robot_id, {}).get('enter_time', datetime.now())
                        
                        # 尝试从任务调度器获取任务优先级
                        task_priority = 2.0  # 默认中等优先级
                        task_id_found = None
                        if self.task_scheduler:
                            # 查找该机器人的执行中任务
                            for task in self.task_scheduler.tasks.values():
                                if (task.robot_id == robot_id and 
                                    task.status.value in ["executing", "assigned"]):  # 使用小写状态值
                                    task_priority = float(task.priority.value)
                                    task_id_found = task.task_id
                                    logger.info(
                                        f"[RESTRICTED AREA] Found task priority {task_priority} for robot {robot_id} "
                                        f"from task {task.task_id} (status: {task.status.value})"
                                    )
                                    break
                        
                        # 如果没有找到任务，记录日志
                        if not task_id_found:
                            logger.info(
                                f"[RESTRICTED AREA] No active task found for robot {robot_id}, "
                                f"using default priority {task_priority}"
                            )
                        
                        adjusted_priority = self._adjust_priority_when_equal(
                            robot_id, task_priority, enter_time
                        )
                        
                        robot_info_list.append((robot_id, adjusted_priority, enter_time, robot_state.pose))
                    except Exception as e:
                        logger.debug(f"Failed to get robot {robot_id} info for capacity check: {e}")
                        continue
                
                # 按优先级排序（优先级高的在前，值小的在前）
                robot_info_list.sort(key=lambda x: (x[1], x[2]))
                
                # 让优先级最低的 overflow_count 台机器人退出
                # 但是要排除正在执行GO_HOME动作的机器人
                robots_to_remove = []
                i = 0
                skipped_count = 0
                while len(robots_to_remove) < overflow_count and (i + skipped_count) < len(robot_info_list):
                    robot_id, priority, enter_time, robot_pose = robot_info_list[-(i+1+skipped_count)]  # 从后往前取（优先级最低的）
                    
                    # 重要：检查机器人是否正在执行GO_HOME动作（回桩）
                    # 如果正在回桩且不是强制解锁，不应该被强制移出限行区域，应该允许它完成回桩
                    should_skip = False
                    if not force_unlock:  # 只有在非强制解锁时才跳过回桩的机器人
                        try:
                            if self.task_scheduler:
                                for task in self.task_scheduler.tasks.values():
                                    if (task.robot_id == robot_id and 
                                        task.status.value in ["executing", "assigned"] and
                                        task.is_multi_action and task.actions and
                                        task.current_action_index < len(task.actions)):
                                        current_action_item = task.actions[task.current_action_index]
                                        from app.models.task import ActionType
                                        if current_action_item.action_type == ActionType.GO_HOME:
                                            # 机器人正在执行GO_HOME动作，不应该被强制移出限行区域
                                            logger.info(
                                                f"[RESTRICTED AREA] Robot {robot_id} is executing GO_HOME action, "
                                                f"skipping removal from area {area_id} to allow docking"
                                            )
                                            should_skip = True
                                            skipped_count += 1
                                            break
                        except Exception as e:
                            logger.debug(f"Failed to check GO_HOME action for robot {robot_id}: {e}")
                    else:
                        # 强制解锁时，即使正在回桩也要移除
                        logger.warning(
                            f"[RESTRICTED AREA] Force unlock: Robot {robot_id} will be removed from area {area_id} "
                            f"even if executing GO_HOME action"
                        )
                    
                    if should_skip:
                        i += 1
                        continue
                    
                    robots_to_remove.append((robot_id, priority, robot_pose))
                    i += 1
                
                # 移除低优先级的机器人并添加到等待队列
                for robot_id, priority, robot_pose in robots_to_remove:
                    # 从通行列表中移除
                    if robot_id in traffic['robots']:
                        traffic['robots'].remove(robot_id)
                    if robot_id in self.robot_enter_time:
                        del self.robot_enter_time[robot_id]
                    
                    # 查找等待点
                    start = area_data.get("start", {})
                    end = area_data.get("end", {})
                    half_width = area_data.get("half_width", 0.5)
                    waiting_point = self.find_waiting_point_near_restricted_area(
                        start, end, half_width, robot_pose, max_distance=8.0
                    )
                    
                    if waiting_point:
                        # 获取任务ID（优先从任务调度器获取）
                        task_id = None
                        if self.task_scheduler:
                            # 查找该机器人的执行中任务
                            for task in self.task_scheduler.tasks.values():
                                if (task.robot_id == robot_id and 
                                    task.status.value in ["executing", "assigned"]):
                                    task_id = task.task_id
                                    break
                        
                        # 如果从任务调度器没有找到，尝试从等待状态中获取
                        if not task_id and robot_id in self.robot_waiting_status:
                            task_id = self.robot_waiting_status[robot_id].get('original_task_id')
                        
                        # 添加到等待队列
                        traffic['waiting_queue'].append((
                            robot_id,
                            priority,
                            task_id or f"unknown_{robot_id}",
                            datetime.now()
                        ))
                        traffic['waiting_queue'].sort(key=lambda x: x[1])
                        
                        # 记录等待状态
                        self.robot_waiting_status[robot_id] = {
                            'area_id': area_id,
                            'waiting_point': waiting_point,
                            'original_task_id': task_id,
                            'waiting_since': datetime.now()
                        }
                        
                        # 在发送机器人到等待点之前，检查路径是否被其他机器人阻塞
                        # 如果被阻塞，尝试让阻塞的机器人也移动
                        blocking_robots = await self._check_path_blocked_to_waiting_point(
                            robot_id, robot_pose, waiting_point
                        )
                        
                        if blocking_robots:
                            logger.warning(
                                f"[RESTRICTED AREA] Robot {robot_id} path to waiting point is blocked by robots: {blocking_robots}. "
                                f"Attempting to resolve blocking..."
                            )
                            # 尝试让阻塞的机器人也移动到等待点或后退
                            blocking_resolved = await self._resolve_path_blocking(robot_id, blocking_robots, waiting_point)
                            
                            # 如果阻塞无法解决（阻塞机器人无法后退），尝试为当前机器人选择另一个等待点
                            if not blocking_resolved:
                                logger.warning(
                                    f"[RESTRICTED AREA] Cannot resolve blocking for robot {robot_id}, "
                                    f"attempting to find alternative waiting point..."
                                )
                                # 记录已尝试的等待点
                                tried_points = [(waiting_point.x, waiting_point.y)]
                                
                                # 尝试查找另一个等待点（排除当前等待点）
                                # 尝试多个等待点，找到路径畅通的
                                alternative_waiting_point = None
                                max_attempts = 5  # 最多尝试5个不同的等待点
                                
                                for attempt in range(max_attempts):
                                    candidate = self.find_waiting_point_near_restricted_area(
                                        start, end, half_width, robot_pose, 
                                        max_distance=8.0 + attempt * 2.0,  # 逐步扩大搜索范围
                                        exclude_points=tried_points  # 排除已尝试的点
                                    )
                                    
                                    if not candidate:
                                        continue
                                    
                                    # 检查是否与已尝试的点不同
                                    is_different = True
                                    for tried_x, tried_y in tried_points:
                                        dist = math.sqrt(
                                            (candidate.x - tried_x) ** 2 + 
                                            (candidate.y - tried_y) ** 2
                                        )
                                        if dist < 0.5:  # 如果距离小于0.5米，认为是同一个点
                                            is_different = False
                                            break
                                    
                                    if is_different:
                                        # 检查新等待点的路径是否也被阻塞
                                        new_blocking_robots = await self._check_path_blocked_to_waiting_point(
                                            robot_id, robot_pose, candidate
                                        )
                                        
                                        if not new_blocking_robots:
                                            # 新等待点路径畅通，使用新等待点
                                            alternative_waiting_point = candidate
                                            tried_points.append((candidate.x, candidate.y))
                                            break
                                        else:
                                            # 记录已尝试的点（即使被阻塞）
                                            tried_points.append((candidate.x, candidate.y))
                                
                                if alternative_waiting_point:
                                    waiting_point = alternative_waiting_point
                                
                                    logger.info(
                                        f"[RESTRICTED AREA] Robot {robot_id} switched to alternative waiting point "
                                        f"at ({waiting_point.x:.2f}, {waiting_point.y:.2f}) to avoid blocking"
                                    )
                                else:
                                    logger.warning(
                                        f"[RESTRICTED AREA] Cannot find alternative waiting point for robot {robot_id} "
                                        f"after {max_attempts} attempts. All candidate waiting points are blocked or unavailable."
                                    )
                        
                        # 实际发送move_to指令，让机器人移动到等待点
                        try:
                            agent = self.robot_manager.get_robot_agent(robot_id)
                            if agent:
                                # 检查机器人是否已经有正在执行的action
                                current_action = await agent.get_current_action()
                                if current_action and current_action.action_id:
                                    # 如果机器人正在执行其他动作，先取消
                                    try:
                                        await agent.cancel_current_action()
                                        logger.info(
                                            f"[RESTRICTED AREA] Cancelled current action for robot {robot_id} "
                                            f"to move to waiting point"
                                        )
                                        await asyncio.sleep(0.5)  # 等待取消完成
                                    except Exception as e:
                                        logger.warning(f"Failed to cancel current action for robot {robot_id}: {e}")
                                
                                # 发送move_to指令到等待点
                                action_state = await agent.move_to(
                                    target=waiting_point,
                                    mode=0,
                                    acceptable_precision=0.5,  # 等待点精度可以放宽
                                    speed_ratio=1.0
                                )
                                
                                logger.warning(
                                    f"[RESTRICTED AREA] Robot {robot_id} removed from area {area_id} due to capacity overflow "
                                    f"(priority: {priority:.3f}, current: {len(traffic['robots'])}/{capacity}), "
                                    f"moving to waiting point at ({waiting_point.x:.2f}, {waiting_point.y:.2f}), "
                                    f"action_id={action_state.action_id if action_state else 'None'}"
                                )
                            else:
                                logger.error(
                                    f"[RESTRICTED AREA] Failed to get robot agent for robot {robot_id} "
                                    f"to move to waiting point"
                                )
                        except Exception as e:
                            logger.error(
                                f"[RESTRICTED AREA] Failed to send robot {robot_id} to waiting point: {e}",
                                exc_info=True
                            )
                    else:
                        logger.error(
                            f"[RESTRICTED AREA] Failed to find waiting point for robot {robot_id} "
                            f"removed from area {area_id}. Robot will stay at current position."
                        )
                        # 如果找不到等待点，至少记录等待状态，让机器人保持在当前位置
                        # 这样机器人不会因为没有指令而触发其他逻辑（如回桩）
                        self.robot_waiting_status[robot_id] = {
                            'area_id': area_id,
                            'waiting_point': robot_pose,  # 使用当前位置作为等待点
                            'original_task_id': task_id,
                            'waiting_since': datetime.now(),
                            'no_waiting_point_found': True  # 标记为未找到等待点
                        }
                        logger.warning(
                            f"[RESTRICTED AREA] Robot {robot_id} will wait at current position "
                            f"({robot_pose.x:.2f}, {robot_pose.y:.2f}) as no suitable waiting point found"
                        )
    
    async def _check_waiting_robots_unreachable_points(self):
        """
        检查等待中的机器人是否无法到达等待点
        如果检测到无法到达（如CANNOT_REACH_TARGET），重新查找新的等待点
        """
        for robot_id, waiting_status in list(self.robot_waiting_status.items()):
            try:
                area_id = waiting_status.get('area_id')
                current_waiting_point = waiting_status.get('waiting_point')
                task_id = waiting_status.get('original_task_id')
                
                if not area_id or not current_waiting_point:
                    continue
                
                # 获取机器人当前状态
                agent = self.robot_manager.get_robot_agent(robot_id)
                if not agent:
                    continue
                
                # 检查机器人当前action状态
                try:
                    current_action = await agent.get_current_action()
                    if current_action and current_action.action_id:
                        # 获取action状态
                        action_state = await agent.get_action_status(current_action.action_id)
                        
                        if action_state:
                            # 检查action是否失败且原因是无法到达目标
                            status = action_state.state.get("status") if action_state.state else action_state.status
                            result = action_state.state.get("result") if action_state.state else action_state.result
                            reason = action_state.state.get("reason", "") if action_state.state else (action_state.reason or "")
                            
                            # 如果action失败且原因是CANNOT_REACH_TARGET，重新查找等待点
                            if status == 4 and result == -1 and "CANNOT_REACH_TARGET" in reason:
                                logger.warning(
                                    f"[RESTRICTED AREA] Robot {robot_id} cannot reach waiting point "
                                    f"at ({current_waiting_point.x:.2f}, {current_waiting_point.y:.2f}), "
                                    f"reason: {reason}. Finding new reachable waiting point..."
                                )
                                
                                # 获取机器人当前位置
                                robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=True)
                                if not robot_state or not robot_state.pose:
                                    continue
                                
                                # 获取限行区域信息
                                restricted_areas = self.map_manager.restricted_areas
                                area_data = None
                                for area in restricted_areas:
                                    if area.get("id") == area_id:
                                        area_data = area.get("area", {})
                                        break
                                
                                if not area_data:
                                    continue
                                
                                start = area_data.get("start", {})
                                end = area_data.get("end", {})
                                half_width = area_data.get("half_width", 0.5)
                                
                                if not start or not end:
                                    continue
                                
                                # 查找新的等待点（排除当前无法到达的等待点）
                                # 记录已尝试的等待点，避免重复选择
                                tried_points = waiting_status.get('tried_points', [])
                                tried_points.append((current_waiting_point.x, current_waiting_point.y))
                                
                                # 查找新的等待点
                                new_waiting_point = self.find_waiting_point_near_restricted_area(
                                    start, end, half_width, robot_state.pose, max_distance=8.0
                                )
                                
                                # 如果找到新的等待点且与已尝试的点不同
                                if new_waiting_point:
                                    # 检查是否与已尝试的点不同
                                    is_different = True
                                    for tried_x, tried_y in tried_points:
                                        dist = math.sqrt(
                                            (new_waiting_point.x - tried_x) ** 2 + 
                                            (new_waiting_point.y - tried_y) ** 2
                                        )
                                        if dist < 0.5:  # 如果距离小于0.5米，认为是同一个点
                                            is_different = False
                                            break
                                    
                                    if is_different:
                                        # 更新等待状态
                                        waiting_status['waiting_point'] = new_waiting_point
                                        waiting_status['tried_points'] = tried_points
                                        
                                        # 取消当前action
                                        try:
                                            await agent.cancel_current_action()
                                            await asyncio.sleep(0.5)
                                        except Exception as e:
                                            logger.warning(f"Failed to cancel current action for robot {robot_id}: {e}")
                                        
                                        # 发送新的move_to指令到新等待点
                                        try:
                                            action_state = await agent.move_to(
                                                target=new_waiting_point,
                                                mode=0,
                                                acceptable_precision=0.5,
                                                speed_ratio=1.0
                                            )
                                            logger.info(
                                                f"[RESTRICTED AREA] Updated waiting point for robot {robot_id} "
                                                f"from ({current_waiting_point.x:.2f}, {current_waiting_point.y:.2f}) "
                                                f"to ({new_waiting_point.x:.2f}, {new_waiting_point.y:.2f}), "
                                                f"action_id={action_state.action_id if action_state else 'None'}"
                                            )
                                        except Exception as e:
                                            logger.error(
                                                f"[RESTRICTED AREA] Failed to send robot {robot_id} to new waiting point: {e}",
                                                exc_info=True
                                            )
                                    else:
                                        logger.warning(
                                            f"[RESTRICTED AREA] New waiting point for robot {robot_id} "
                                            f"is same as tried points, cannot find alternative waiting point"
                                        )
                                else:
                                    logger.warning(
                                        f"[RESTRICTED AREA] Cannot find new waiting point for robot {robot_id}, "
                                        f"all waiting points may be unreachable"
                                    )
                except Exception as e:
                    logger.debug(f"Failed to check waiting point reachability for robot {robot_id}: {e}")
            except Exception as e:
                logger.debug(f"Error checking waiting robot {robot_id}: {e}")
    
    async def _check_path_blocked_to_waiting_point(
        self, 
        robot_id: str, 
        robot_pose: Pose, 
        waiting_point: Pose
    ) -> List[str]:
        """
        检查机器人到等待点的路径是否被其他机器人阻塞
        
        Args:
            robot_id: 机器人ID
            robot_pose: 机器人当前位置
            waiting_point: 等待点位置
            
        Returns:
            阻塞路径的机器人ID列表，如果没有阻塞则返回空列表
        """
        blocking_robots = []
        
        try:
            # 获取所有其他机器人的位置
            all_robot_ids = self.robot_manager.list_robots()
            
            # 计算路径方向向量
            dx = waiting_point.x - robot_pose.x
            dy = waiting_point.y - robot_pose.y
            path_length = math.sqrt(dx * dx + dy * dy)
            
            if path_length < 0.5:  # 如果距离很近，不需要检查
                return blocking_robots
            
            # 路径方向单位向量
            if path_length > 0:
                unit_dx = dx / path_length
                unit_dy = dy / path_length
            else:
                return blocking_robots
            
            # 检查路径上的其他机器人（在路径前方3米范围内）
            check_distance = min(3.0, path_length)  # 检查前方3米或到等待点的距离
            
            for other_robot_id in all_robot_ids:
                if other_robot_id == robot_id:
                    continue
                
                try:
                    other_state = await self.robot_manager.get_robot_state(other_robot_id, force_update=False)
                    if not other_state or not other_state.pose:
                        continue
                    
                    other_pose = other_state.pose
                    
                    # 计算其他机器人到路径的距离
                    # 使用点到直线的距离公式
                    rel_x = other_pose.x - robot_pose.x
                    rel_y = other_pose.y - robot_pose.y
                    
                    # 投影到路径方向
                    projection = rel_x * unit_dx + rel_y * unit_dy
                    
                    # 如果投影在路径前方（0到check_distance之间）
                    if 0 < projection < check_distance:
                        # 计算到路径的垂直距离
                        perp_x = rel_x - projection * unit_dx
                        perp_y = rel_y - projection * unit_dy
                        perp_distance = math.sqrt(perp_x * perp_x + perp_y * perp_y)
                        
                        # 如果距离路径小于1.5米（机器人半径0.3米 + 安全距离1.2米），认为阻塞
                        if perp_distance < 1.5:
                            blocking_robots.append(other_robot_id)
                            logger.warning(
                                f"[RESTRICTED AREA] Robot {other_robot_id} is blocking path from {robot_id} "
                                f"to waiting point (distance to path: {perp_distance:.2f}m, "
                                f"projection: {projection:.2f}m)"
                            )
                except Exception as e:
                    logger.debug(f"Failed to check robot {other_robot_id} for path blocking: {e}")
                    continue
        except Exception as e:
            logger.error(f"Failed to check path blocking for robot {robot_id}: {e}", exc_info=True)
        
        return blocking_robots
    
    async def _resolve_path_blocking(
        self, 
        robot_id: str, 
        blocking_robots: List[str], 
        waiting_point: Pose
    ) -> bool:
        """
        解决路径阻塞问题：让阻塞的机器人也移动到等待点或后退
        
        Args:
            robot_id: 需要到达等待点的机器人ID
            blocking_robots: 阻塞路径的机器人ID列表
            waiting_point: 目标等待点
            
        Returns:
            True if blocking was resolved, False otherwise
        """
        for blocking_robot_id in blocking_robots:
            try:
                blocking_state = await self.robot_manager.get_robot_state(blocking_robot_id, force_update=False)
                if not blocking_state or not blocking_state.pose:
                    continue
                
                blocking_pose = blocking_state.pose
                
                # 检查阻塞机器人是否在限行区域内
                is_in_restricted_area = False
                restricted_areas = self.map_manager.restricted_areas
                for area in restricted_areas:
                    area_id = area.get("id")
                    area_data = area.get("area", {})
                    if not area_data:
                        continue
                    
                    start = area_data.get("start", {})
                    end = area_data.get("end", {})
                    half_width = area_data.get("half_width", 0.5)
                    
                    if not start or not end:
                        continue
                    
                    if self.is_point_in_restricted_area(blocking_pose, start, end, half_width):
                        is_in_restricted_area = True
                        break
                
                # 如果阻塞机器人不在限行区域内，尝试让它也移动到等待点或后退
                if not is_in_restricted_area:
                    logger.warning(
                        f"[RESTRICTED AREA] Robot {blocking_robot_id} is blocking path but not in restricted area. "
                        f"Attempting to move it to waiting point or back off..."
                    )
                    
                    # 尝试查找另一个等待点给阻塞机器人
                    # 或者让阻塞机器人后退
                    agent = self.robot_manager.get_robot_agent(blocking_robot_id)
                    if agent:
                        # 首先尝试让阻塞机器人移动到等待点（W4或W5等）
                        # 查找限行区域附近的等待点
                        restricted_areas = self.map_manager.restricted_areas
                        blocking_waiting_point = None
                        
                        for area in restricted_areas:
                            area_data = area.get("area", {})
                            if not area_data:
                                continue
                            
                            start = area_data.get("start", {})
                            end = area_data.get("end", {})
                            half_width = area_data.get("half_width", 0.5)
                            
                            if not start or not end:
                                continue
                            
                            # 查找等待点（排除目标等待点，避免移动到同一个点）
                            exclude_points = [(waiting_point.x, waiting_point.y)]
                            blocking_waiting_point = self.find_waiting_point_near_restricted_area(
                                start, end, half_width, blocking_pose, max_distance=10.0,
                                exclude_points=exclude_points
                            )
                            
                            if blocking_waiting_point:
                                break
                        
                        # 如果找到等待点，让阻塞机器人移动到等待点
                        if blocking_waiting_point:
                            try:
                                # 检查阻塞机器人是否有正在执行的任务
                                current_action = await agent.get_current_action()
                                if current_action and current_action.action_id:
                                    # 如果有任务，尝试取消（但可能失败，因为任务可能正在执行）
                                    try:
                                        await agent.cancel_current_action()
                                        await asyncio.sleep(0.5)
                                    except:
                                        pass  # 如果无法取消，继续尝试移动
                                
                                # 发送移动到等待点的指令
                                await agent.move_to(
                                    target=blocking_waiting_point,
                                    mode=0,
                                    acceptable_precision=0.5,
                                    speed_ratio=0.8  # 使用较慢的速度
                                )
                                
                                logger.info(
                                    f"[RESTRICTED AREA] Robot {blocking_robot_id} moved to waiting point "
                                    f"({blocking_waiting_point.x:.2f}, {blocking_waiting_point.y:.2f}) "
                                    f"to clear path for robot {robot_id}"
                                )
                                return True  # 阻塞已解决
                            except Exception as e:
                                logger.warning(
                                    f"[RESTRICTED AREA] Failed to move blocking robot {blocking_robot_id} to waiting point: {e}"
                                )
                        
                        # 如果无法移动到等待点，尝试后退
                        # 计算后退位置（沿着路径反方向后退），并检查是否可行走
                        dx = blocking_pose.x - waiting_point.x
                        dy = blocking_pose.y - waiting_point.y
                        dist = math.sqrt(dx * dx + dy * dy)
                        
                        if dist > 0:
                            # 尝试多个后退距离和方向，找到可行走的位置
                            backoff_pose = None
                            backoff_distances = [1.5, 1.0, 0.5, 2.0]  # 尝试不同的后退距离
                            backoff_angles = [0, 45, -45, 90, -90]  # 尝试不同的角度偏移（度）
                            
                            for backoff_distance in backoff_distances:
                                for angle_offset in backoff_angles:
                                    # 计算后退方向（沿路径反方向）
                                    unit_dx = dx / dist
                                    unit_dy = dy / dist
                                    
                                    # 如果有角度偏移，旋转方向向量
                                    if angle_offset != 0:
                                        angle_rad = math.radians(angle_offset)
                                        cos_a = math.cos(angle_rad)
                                        sin_a = math.sin(angle_rad)
                                        # 旋转方向向量
                                        rotated_dx = unit_dx * cos_a - unit_dy * sin_a
                                        rotated_dy = unit_dx * sin_a + unit_dy * cos_a
                                        unit_dx = rotated_dx
                                        unit_dy = rotated_dy
                                    
                                    # 计算后退位置
                                    candidate_x = blocking_pose.x + unit_dx * backoff_distance
                                    candidate_y = blocking_pose.y + unit_dy * backoff_distance
                                    
                                    # 检查位置是否可行走
                                    if self.path_planner and self.map_manager.metadata:
                                        map_x, map_y = self.map_manager.world_to_map(candidate_x, candidate_y)
                                        if self.path_planner._is_valid_position(map_x, map_y, robot_radius=0.3):
                                            # 也检查是否为自由空间（更严格）
                                            if self.map_manager.is_free(candidate_x, candidate_y):
                                                backoff_pose = Pose(x=candidate_x, y=candidate_y, yaw=blocking_pose.yaw)
                                                logger.info(
                                                    f"[RESTRICTED AREA] Found valid backoff position for robot {blocking_robot_id} "
                                                    f"at ({candidate_x:.2f}, {candidate_y:.2f}) "
                                                    f"(distance: {backoff_distance}m, angle: {angle_offset}°)"
                                                )
                                                break
                                    
                                    # 如果路径规划器不可用，使用地图管理器检查
                                    elif self.map_manager:
                                        if self.map_manager.is_free(candidate_x, candidate_y):
                                            backoff_pose = Pose(x=candidate_x, y=candidate_y, yaw=blocking_pose.yaw)
                                            logger.info(
                                                f"[RESTRICTED AREA] Found valid backoff position for robot {blocking_robot_id} "
                                                f"at ({candidate_x:.2f}, {candidate_y:.2f}) "
                                                f"(distance: {backoff_distance}m, angle: {angle_offset}°)"
                                            )
                                            break
                                
                                if backoff_pose:
                                    break
                            
                            if backoff_pose:
                                try:
                                    # 检查阻塞机器人是否有正在执行的任务
                                    current_action = await agent.get_current_action()
                                    if current_action and current_action.action_id:
                                        # 如果有任务，尝试取消（但可能失败，因为任务可能正在执行）
                                        try:
                                            await agent.cancel_current_action()
                                            await asyncio.sleep(0.5)
                                        except:
                                            pass  # 如果无法取消，继续尝试移动
                                    
                                    # 发送后退指令
                                    await agent.move_to(
                                        target=backoff_pose,
                                        mode=0,
                                        acceptable_precision=0.3,
                                        speed_ratio=0.5  # 使用较慢的速度
                                    )
                                    
                                    logger.info(
                                        f"[RESTRICTED AREA] Robot {blocking_robot_id} moved back to clear path "
                                        f"for robot {robot_id} (backoff to {backoff_pose.x:.2f}, {backoff_pose.y:.2f})"
                                    )
                                    return True  # 阻塞已解决
                                except Exception as e:
                                    logger.warning(
                                        f"[RESTRICTED AREA] Failed to move blocking robot {blocking_robot_id} back: {e}"
                                    )
                            else:
                                logger.warning(
                                    f"[RESTRICTED AREA] Cannot find valid backoff position for robot {blocking_robot_id}. "
                                    f"All candidate positions are in non-walkable areas. "
                                    f"Robot may need to find alternative path or wait."
                                )
                                return False  # 阻塞无法解决
                else:
                    # 如果阻塞机器人在限行区域内，记录日志但不处理（由容量溢出逻辑处理）
                    logger.info(
                        f"[RESTRICTED AREA] Robot {blocking_robot_id} is blocking path but is in restricted area, "
                        f"will be handled by capacity overflow logic"
                    )
                    return False  # 阻塞无法解决（由其他逻辑处理）
            except Exception as e:
                logger.error(
                    f"[RESTRICTED AREA] Failed to resolve blocking for robot {blocking_robot_id}: {e}",
                    exc_info=True
                )
                return False  # 阻塞无法解决
        
        return True  # 所有阻塞都已解决
    
    async def _check_stuck_robots_in_restricted_area(self, force_unlock: bool = False):
        """
        检查长时间卡在限行区域的机器人，强制触发恢复
        
        如果机器人在限行区域内超过30秒且没有移动，强制触发容量检查和恢复
        这可以解决机器人死锁在限行区域的问题
        
        Args:
            force_unlock: 如果为True，立即解锁所有卡住的机器人（不等待阈值时间）
        """
        STUCK_THRESHOLD_SECONDS = 0.0 if force_unlock else 30.0  # 强制解锁时立即处理
        
        restricted_areas = self.map_manager.restricted_areas
        
        for area in restricted_areas:
            area_id = area.get("id")
            area_data = area.get("area", {})
            
            if not area_data:
                continue
            
            start = area_data.get("start", {})
            end = area_data.get("end", {})
            half_width = area_data.get("half_width", 0.5)
            
            if not start or not end:
                continue
            
            # 检查所有在线机器人
            robot_ids = self.robot_manager.list_robots()
            for robot_id in robot_ids:
                try:
                    robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=True)
                    if not robot_state or not robot_state.pose:
                        continue
                    
                    # 检查机器人是否在限行区域内
                    is_in_area = self.is_point_in_restricted_area(
                        robot_state.pose, start, end, half_width
                    )
                    
                    if is_in_area:
                        # 检查机器人是否在通行列表中
                        if area_id in self.area_traffic:
                            traffic = self.area_traffic[area_id]
                            if robot_id in traffic['robots']:
                                # 检查机器人进入时间
                                enter_time = self.robot_enter_time.get(robot_id, {}).get('enter_time')
                                if enter_time:
                                    stuck_duration = (datetime.now() - enter_time).total_seconds()
                                    
                                    # 如果卡住超过阈值（或强制解锁），强制触发恢复
                                    if force_unlock or stuck_duration > STUCK_THRESHOLD_SECONDS:
                                        # 检查机器人是否有正在执行的任务
                                        has_active_task = False
                                        if self.task_scheduler:
                                            for task in self.task_scheduler.tasks.values():
                                                if (task.robot_id == robot_id and 
                                                    task.status.value in ["executing", "assigned"]):
                                                    has_active_task = True
                                                    break
                                        
                                        # 如果机器人没有活跃任务，可能是卡住了
                                        if not has_active_task:
                                            logger.warning(
                                                f"[RESTRICTED AREA] Robot {robot_id} stuck in area {area_id} "
                                                f"for {stuck_duration:.1f}s without active task. "
                                                f"Force triggering capacity check and recovery..."
                                            )
                                            
                                            # 强制触发容量检查和恢复
                                            # 将机器人从通行列表中移除，触发重新分配
                                            if robot_id in traffic['robots']:
                                                traffic['robots'].remove(robot_id)
                                            if robot_id in self.robot_enter_time:
                                                del self.robot_enter_time[robot_id]
                                            
                                            # 清除等待状态（如果有）
                                            if robot_id in self.robot_waiting_status:
                                                del self.robot_waiting_status[robot_id]
                                            
                                            # 触发容量检查，让其他机器人可以通行
                                            await self.check_waiting_robots()
                                            
                                            logger.info(
                                                f"[RESTRICTED AREA] Robot {robot_id} removed from area {area_id} "
                                                f"due to stuck detection. Capacity check triggered."
                                            )
                                        else:
                                            # 有活跃任务但卡住，可能是任务执行问题
                                            # 检查机器人是否真的在移动（通过检查位置变化）
                                            # 这里简化处理：如果卡住超过60秒，即使有任务也强制恢复
                                            if stuck_duration > 60.0:
                                                logger.warning(
                                                    f"[RESTRICTED AREA] Robot {robot_id} stuck in area {area_id} "
                                                    f"for {stuck_duration:.1f}s with active task. "
                                                    f"Force triggering recovery..."
                                                )
                                                
                                                # 强制触发容量检查和恢复
                                                if robot_id in traffic['robots']:
                                                    traffic['robots'].remove(robot_id)
                                                if robot_id in self.robot_enter_time:
                                                    del self.robot_enter_time[robot_id]
                                                
                                                # 触发容量检查
                                                await self.check_waiting_robots()
                                                
                                                logger.info(
                                                    f"[RESTRICTED AREA] Robot {robot_id} removed from area {area_id} "
                                                    f"due to extended stuck detection ({stuck_duration:.1f}s)."
                                                )
                except Exception as e:
                    logger.debug(f"Failed to check stuck robot {robot_id} in area {area_id}: {e}")
                    continue
        
        # 检查等待中的机器人是否长时间无法到达等待点
        for robot_id, waiting_status in list(self.robot_waiting_status.items()):
            try:
                waiting_since = waiting_status.get('waiting_since')
                if waiting_since:
                    wait_duration = (datetime.now() - waiting_since).total_seconds()
                    
                    # 如果等待超过60秒，检查机器人是否真的在等待点
                    if wait_duration > 60.0:
                        robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=True)
                        if robot_state and robot_state.pose:
                            waiting_point = waiting_status.get('waiting_point')
                            if waiting_point:
                                # 计算到等待点的距离
                                distance = math.sqrt(
                                    (robot_state.pose.x - waiting_point.x) ** 2 +
                                    (robot_state.pose.y - waiting_point.y) ** 2
                                )
                                
                                # 如果距离等待点较远（>1米），可能卡在入口处
                                if distance > 1.0:
                                    logger.warning(
                                        f"[RESTRICTED AREA] Robot {robot_id} waiting for {wait_duration:.1f}s "
                                        f"but still {distance:.2f}m away from waiting point. "
                                        f"May be stuck at entrance. Attempting recovery..."
                                    )
                                    
                                    # 尝试查找新的等待点或强制清除等待状态
                                    area_id = waiting_status.get('area_id')
                                    if area_id:
                                        # 查找限行区域信息
                                        for area in restricted_areas:
                                            if area.get("id") == area_id:
                                                area_data = area.get("area", {})
                                                if area_data:
                                                    start = area_data.get("start", {})
                                                    end = area_data.get("end", {})
                                                    half_width = area_data.get("half_width", 0.5)
                                                    
                                                    if start and end:
                                                        # 尝试查找新的等待点
                                                        new_waiting_point = self.find_waiting_point_near_restricted_area(
                                                            start, end, half_width, robot_state.pose, max_distance=10.0
                                                        )
                                                        
                                                        if new_waiting_point:
                                                            # 更新等待点
                                                            waiting_status['waiting_point'] = new_waiting_point
                                                            waiting_status['waiting_since'] = datetime.now()
                                                            
                                                            # 尝试发送新的移动指令
                                                            try:
                                                                agent = self.robot_manager.get_robot_agent(robot_id)
                                                                if agent:
                                                                    current_action = await agent.get_current_action()
                                                                    if current_action and current_action.action_id:
                                                                        try:
                                                                            await agent.cancel_current_action()
                                                                            await asyncio.sleep(0.5)
                                                                        except:
                                                                            pass
                                                                    
                                                                    await agent.move_to(
                                                                        target=new_waiting_point,
                                                                        mode=0,
                                                                        acceptable_precision=0.5,
                                                                        speed_ratio=1.0
                                                                    )
                                                                    logger.info(
                                                                        f"[RESTRICTED AREA] Robot {robot_id} redirected to new waiting point "
                                                                        f"at ({new_waiting_point.x:.2f}, {new_waiting_point.y:.2f})"
                                                                    )
                                                            except Exception as e:
                                                                logger.warning(
                                                                    f"[RESTRICTED AREA] Failed to redirect robot {robot_id} to new waiting point: {e}"
                                                                )
                                                        else:
                                                            # 如果找不到新的等待点，清除等待状态，让机器人继续执行任务
                                                            logger.warning(
                                                                f"[RESTRICTED AREA] Cannot find new waiting point for robot {robot_id}. "
                                                                f"Clearing waiting status to allow task continuation..."
                                                            )
                                                            if robot_id in self.robot_waiting_status:
                                                                del self.robot_waiting_status[robot_id]
                                                            # 从等待队列中移除
                                                            if area_id in self.area_traffic:
                                                                traffic = self.area_traffic[area_id]
                                                                traffic['waiting_queue'] = [
                                                                    (wid, pri, tid, et) for wid, pri, tid, et in traffic['waiting_queue']
                                                                    if wid != robot_id
                                                                ]
                                                break
            except Exception as e:
                logger.debug(f"Failed to check waiting robot {robot_id} stuck status: {e}")
                continue
    
    async def _check_direct_blocking_in_restricted_area(self, force_unlock: bool = False):
        """
        检查限行区域内机器人之间的直接阻塞
        
        如果一个机器人在限行区域内，且被另一个机器人直接阻塞（距离很近），
        强制触发容量检查和恢复，让阻塞的机器人退出
        
        Args:
            force_unlock: 如果为True，立即解锁所有阻塞的机器人（降低距离阈值）
        """
        BLOCKING_DISTANCE_THRESHOLD = 3.0 if force_unlock else 1.5  # 强制解锁时扩大检测范围
        
        restricted_areas = self.map_manager.restricted_areas
        
        for area in restricted_areas:
            area_id = area.get("id")
            area_data = area.get("area", {})
            
            if not area_data:
                continue
            
            start = area_data.get("start", {})
            end = area_data.get("end", {})
            half_width = area_data.get("half_width", 0.5)
            
            if not start or not end:
                continue
            
            # 检查限行区域内的所有机器人
            if area_id not in self.area_traffic:
                continue
            
            traffic = self.area_traffic[area_id]
            robots_in_area = traffic['robots'].copy()
            
            if len(robots_in_area) < 2:
                continue  # 至少需要2台机器人才能有阻塞
            
            # 获取所有机器人的位置
            robot_positions = {}
            for robot_id in robots_in_area:
                try:
                    robot_state = await self.robot_manager.get_robot_state(robot_id, force_update=True)
                    if robot_state and robot_state.pose:
                        # 确认机器人真的在限行区域内
                        is_in_area = self.is_point_in_restricted_area(
                            robot_state.pose, start, end, half_width
                        )
                        if is_in_area:
                            robot_positions[robot_id] = robot_state.pose
                except Exception as e:
                    logger.debug(f"Failed to get position for robot {robot_id}: {e}")
                    continue
            
            # 检查机器人之间的直接阻塞
            # 使用集合记录已处理的阻塞对，避免重复处理
            processed_pairs = set()
            
            for robot_id1, pose1 in robot_positions.items():
                for robot_id2, pose2 in robot_positions.items():
                    if robot_id1 == robot_id2:
                        continue
                    
                    # 创建唯一对标识（避免重复检查同一对机器人）
                    pair_key = tuple(sorted([robot_id1, robot_id2]))
                    if pair_key in processed_pairs:
                        continue
                    
                    # 计算两个机器人之间的距离
                    dx = pose1.x - pose2.x
                    dy = pose1.y - pose2.y
                    distance = math.sqrt(dx * dx + dy * dy)
                    
                    # 如果距离很近，认为直接阻塞
                    if distance < BLOCKING_DISTANCE_THRESHOLD:
                        processed_pairs.add(pair_key)  # 标记为已处理
                        logger.warning(
                            f"[RESTRICTED AREA] Direct blocking detected in area {area_id}: "
                            f"Robot {robot_id1} and {robot_id2} are too close ({distance:.2f}m < {BLOCKING_DISTANCE_THRESHOLD}m). "
                            f"Triggering capacity check and recovery..."
                        )
                        
                        # 检查哪个机器人应该退出（基于优先级）
                        robot1_priority = 2.0
                        robot2_priority = 2.0
                        robot1_task_id = None
                        robot2_task_id = None
                        
                        if self.task_scheduler:
                            # 获取机器人1的任务优先级
                            for task in self.task_scheduler.tasks.values():
                                if (task.robot_id == robot_id1 and 
                                    task.status.value in ["executing", "assigned"]):
                                    robot1_priority = float(task.priority.value)
                                    robot1_task_id = task.task_id
                                    break
                            
                            # 获取机器人2的任务优先级
                            for task in self.task_scheduler.tasks.values():
                                if (task.robot_id == robot_id2 and 
                                    task.status.value in ["executing", "assigned"]):
                                    robot2_priority = float(task.priority.value)
                                    robot2_task_id = task.task_id
                                    break
                        
                        # 调整优先级（考虑进入时间）
                        enter_time1 = self.robot_enter_time.get(robot_id1, {}).get('enter_time', datetime.now())
                        enter_time2 = self.robot_enter_time.get(robot_id2, {}).get('enter_time', datetime.now())
                        
                        adjusted_priority1 = self._adjust_priority_when_equal(robot_id1, robot1_priority, enter_time1)
                        adjusted_priority2 = self._adjust_priority_when_equal(robot_id2, robot2_priority, enter_time2)
                        
                        # 优先级低的机器人应该退出
                        robot_to_remove = None
                        if adjusted_priority1 > adjusted_priority2:
                            # robot_id1 优先级低，应该退出
                            robot_to_remove = robot_id1
                            blocking_robot = robot_id2
                        elif adjusted_priority2 > adjusted_priority1:
                            # robot_id2 优先级低，应该退出
                            robot_to_remove = robot_id2
                            blocking_robot = robot_id1
                        else:
                            # 优先级相同，让后进入的退出
                            if enter_time1 > enter_time2:
                                robot_to_remove = robot_id1
                                blocking_robot = robot_id2
                            else:
                                robot_to_remove = robot_id2
                                blocking_robot = robot_id1
                        
                        if robot_to_remove:
                            logger.info(
                                f"[RESTRICTED AREA] Robot {robot_to_remove} should exit area {area_id} "
                                f"to resolve blocking with {blocking_robot} "
                                f"(priority: {adjusted_priority1 if robot_to_remove == robot_id1 else adjusted_priority2:.3f} vs "
                                f"{adjusted_priority2 if robot_to_remove == robot_id1 else adjusted_priority1:.3f})"
                            )
                            
                            # 从通行列表中移除
                            if robot_to_remove in traffic['robots']:
                                traffic['robots'].remove(robot_to_remove)
                            if robot_to_remove in self.robot_enter_time:
                                del self.robot_enter_time[robot_to_remove]
                            
                            # 查找等待点
                            robot_pose = robot_positions[robot_to_remove]
                            waiting_point = self.find_waiting_point_near_restricted_area(
                                start, end, half_width, robot_pose, max_distance=10.0
                            )
                            
                            if waiting_point:
                                # 获取任务ID
                                task_id = None
                                if self.task_scheduler:
                                    for task in self.task_scheduler.tasks.values():
                                        if (task.robot_id == robot_to_remove and 
                                            task.status.value in ["executing", "assigned"]):
                                            task_id = task.task_id
                                            break
                                
                                # 添加到等待队列
                                priority = adjusted_priority1 if robot_to_remove == robot_id1 else adjusted_priority2
                                traffic['waiting_queue'].append((
                                    robot_to_remove,
                                    priority,
                                    task_id or f"unknown_{robot_to_remove}",
                                    datetime.now()
                                ))
                                traffic['waiting_queue'].sort(key=lambda x: x[1])
                                
                                # 记录等待状态
                                self.robot_waiting_status[robot_to_remove] = {
                                    'area_id': area_id,
                                    'waiting_point': waiting_point,
                                    'original_task_id': task_id,
                                    'waiting_since': datetime.now()
                                }
                                
                                # 发送移动到等待点的指令
                                try:
                                    agent = self.robot_manager.get_robot_agent(robot_to_remove)
                                    if agent:
                                        # 取消当前动作
                                        current_action = await agent.get_current_action()
                                        if current_action and current_action.action_id:
                                            try:
                                                await agent.cancel_current_action()
                                                await asyncio.sleep(0.5)
                                            except:
                                                pass
                                        
                                        # 移动到等待点
                                        action_state = await agent.move_to(
                                            target=waiting_point,
                                            mode=0,
                                            acceptable_precision=0.5,
                                            speed_ratio=1.0
                                        )
                                        
                                        logger.warning(
                                            f"[RESTRICTED AREA] Robot {robot_to_remove} moved to waiting point "
                                            f"({waiting_point.x:.2f}, {waiting_point.y:.2f}) to resolve direct blocking "
                                            f"with {blocking_robot} in area {area_id}, "
                                            f"action_id={action_state.action_id if action_state else 'None'}"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"[RESTRICTED AREA] Failed to move robot {robot_to_remove} to waiting point: {e}",
                                        exc_info=True
                                    )
                            else:
                                logger.warning(
                                    f"[RESTRICTED AREA] Cannot find waiting point for robot {robot_to_remove} "
                                    f"to resolve blocking. Robot will stay at current position."
                                )
                            
                            # 触发容量检查，让其他等待的机器人可以通行
                            await self.check_waiting_robots()
                            
                            # 记录已处理的阻塞对，避免重复处理同一对机器人
                            # 但继续检查其他机器人对
                            logger.info(
                                f"[RESTRICTED AREA] Processed blocking between {robot_id1} and {robot_id2}, "
                                f"continuing to check other robot pairs..."
                            )
                            # 不return，继续检查其他机器人对

