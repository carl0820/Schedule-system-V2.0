"""
路径规划模块 - A*算法
"""
import heapq
import math
import logging
from typing import List, Tuple, Optional
from app.services.map_manager import MapManager
from app.models.robot import Pose

# 检查是否有 numpy
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger(__name__)


class Node:
    """A*算法节点"""
    
    def __init__(self, x: int, y: int, g: float = 0, h: float = 0, parent: Optional['Node'] = None):
        self.x = x
        self.y = y
        self.g = g  # 从起点到当前节点的实际代价
        self.h = h  # 从当前节点到终点的启发式估计代价
        self.f = g + h  # 总代价
        self.parent = parent
    
    def __lt__(self, other):
        return self.f < other.f
    
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    
    def __hash__(self):
        return hash((self.x, self.y))


class PathPlanner:
    """路径规划器，使用A*算法"""
    
    def __init__(self, map_manager: MapManager):
        """
        初始化路径规划器
        
        Args:
            map_manager: 地图管理器
        """
        self.map_manager = map_manager
    
    def _heuristic(self, x1: int, y1: int, x2: int, y2: int) -> float:
        """
        启发式函数（欧几里得距离）
        
        Args:
            x1, y1: 起点坐标
            x2, y2: 终点坐标
            
        Returns:
            启发式估计代价
        """
        dx = x2 - x1
        dy = y2 - y1
        return math.sqrt(dx * dx + dy * dy)
    
    def _get_neighbors(self, node: Node, allow_diagonal: bool = True) -> List[Tuple[int, int]]:
        """
        获取节点的邻居节点
        
        Args:
            node: 当前节点
            allow_diagonal: 是否允许对角线移动
            
        Returns:
            邻居节点列表
        """
        neighbors = []
        
        # 8方向移动（包括对角线）
        if allow_diagonal:
            directions = [
                (-1, -1), (-1, 0), (-1, 1),
                (0, -1),           (0, 1),
                (1, -1),  (1, 0),  (1, 1)
            ]
        else:
            # 4方向移动（上下左右）
            directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        
        for dx, dy in directions:
            nx = node.x + dx
            ny = node.y + dy
            
            # 检查边界
            if (0 <= nx < self.map_manager.metadata.width and
                0 <= ny < self.map_manager.metadata.height):
                neighbors.append((nx, ny))
        
        return neighbors
    
    def _is_valid_position(self, map_x: int, map_y: int, robot_radius: float = None) -> bool:
        """
        检查位置是否有效（考虑机器人半径）
        
        Args:
            map_x: 地图X坐标
            map_y: 地图Y坐标
            robot_radius: 机器人半径（米），默认使用旋转半径
        
        Returns:
            是否有效
        """
        if robot_radius is None:
            from config import settings
            robot_radius = settings.ROBOT_ROTATION_RADIUS
        
        if self.map_manager.metadata is None or self.map_manager.grid_map is None:
            return False
        
        # 检查边界
        if (map_x < 0 or map_x >= self.map_manager.metadata.width or
            map_y < 0 or map_y >= self.map_manager.metadata.height):
            return False
        
        # 检查中心点是否为障碍物
        # 内部格式：0=占用(黑色), 100=空闲(白色), -1=可行走(白色)
        if HAS_NUMPY and isinstance(self.map_manager.grid_map, np.ndarray):
            value = self.map_manager.grid_map[map_y, map_x]
        else:
            value = self.map_manager.grid_map[map_y][map_x]
        if value == 0:  # 0是占用/障碍物，-1和100都是可行走区域
            return False
        
        # 考虑机器人半径，检查周围区域
        radius_pixels = int(robot_radius / self.map_manager.metadata.resolution)
        
        for dy in range(-radius_pixels, radius_pixels + 1):
            for dx in range(-radius_pixels, radius_pixels + 1):
                px = map_x + dx
                py = map_y + dy
                
                if (0 <= px < self.map_manager.metadata.width and
                    0 <= py < self.map_manager.metadata.height):
                    dist = math.sqrt(dx**2 + dy**2) * self.map_manager.metadata.resolution
                    if dist <= robot_radius:
                        if HAS_NUMPY and isinstance(self.map_manager.grid_map, np.ndarray):
                            value = self.map_manager.grid_map[py, px]
                        else:
                            value = self.map_manager.grid_map[py][px]
                        if value == 0:  # 只有0是障碍物，-1和100都是可行走区域
                            return False
        
        return True
    
    def plan_path(
        self,
        start: Pose,
        goal: Pose,
        robot_radius: float = 0.2,
        allow_diagonal: bool = True,
        smooth: bool = True
    ) -> Optional[List[Pose]]:
        """
        使用A*算法规划路径
        
        Args:
            start: 起点位置
            goal: 终点位置
            robot_radius: 机器人半径（米）
            allow_diagonal: 是否允许对角线移动
            smooth: 是否平滑路径
            
        Returns:
            路径点列表（世界坐标），如果无法找到路径则返回None
        """
        if self.map_manager.metadata is None or self.map_manager.grid_map is None:
            logger.error("Map not loaded")
            return None
        
        # 转换为地图坐标
        start_map_x, start_map_y = self.map_manager.world_to_map(start.x, start.y)
        goal_map_x, goal_map_y = self.map_manager.world_to_map(goal.x, goal.y)
        
        # 检查起点和终点是否有效
        if not self._is_valid_position(start_map_x, start_map_y, robot_radius):
            logger.warning(f"Start position ({start.x}, {start.y}) is invalid")
            return None
        
        if not self._is_valid_position(goal_map_x, goal_map_y, robot_radius):
            logger.warning(f"Goal position ({goal.x}, {goal.y}) is invalid")
            return None
        
        # A*算法
        open_set = []
        closed_set = set()
        
        start_node = Node(start_map_x, start_map_y, 0, self._heuristic(start_map_x, start_map_y, goal_map_x, goal_map_y))
        heapq.heappush(open_set, start_node)
        
        came_from = {}
        
        while open_set:
            current = heapq.heappop(open_set)
            
            # 检查是否到达终点
            if current.x == goal_map_x and current.y == goal_map_y:
                # 重构路径
                path = []
                node = current
                while node:
                    world_x, world_y = self.map_manager.map_to_world(node.x, node.y)
                    path.append(Pose(x=world_x, y=world_y, yaw=0.0))
                    node = came_from.get((node.x, node.y))
                
                path.reverse()
                
                # 平滑路径
                if smooth and len(path) > 2:
                    path = self._smooth_path(path, robot_radius)
                
                logger.info(f"Path found with {len(path)} waypoints")
                return path
            
            # 添加到已访问集合
            closed_set.add((current.x, current.y))
            
            # 检查邻居
            for nx, ny in self._get_neighbors(current, allow_diagonal):
                if (nx, ny) in closed_set:
                    continue
                
                if not self._is_valid_position(nx, ny, robot_radius):
                    continue
                
                # 计算移动代价（对角线移动代价更高）
                is_diagonal = (abs(nx - current.x) + abs(ny - current.y)) == 2
                move_cost = math.sqrt(2) if is_diagonal else 1.0
                
                tentative_g = current.g + move_cost
                
                # 检查是否已经在开放集合中
                existing_node = None
                for node in open_set:
                    if node.x == nx and node.y == ny:
                        existing_node = node
                        break
                
                if existing_node:
                    if tentative_g < existing_node.g:
                        # 更新节点
                        existing_node.g = tentative_g
                        existing_node.f = tentative_g + existing_node.h
                        existing_node.parent = current
                        came_from[(nx, ny)] = current
                else:
                    # 创建新节点
                    h = self._heuristic(nx, ny, goal_map_x, goal_map_y)
                    new_node = Node(nx, ny, tentative_g, h, current)
                    heapq.heappush(open_set, new_node)
                    came_from[(nx, ny)] = current
        
        logger.warning("No path found")
        return None
    
    def _smooth_path(self, path: List[Pose], robot_radius: float) -> List[Pose]:
        """
        平滑路径（简化路径，移除不必要的中间点）
        
        Args:
            path: 原始路径
            robot_radius: 机器人半径
            
        Returns:
            平滑后的路径
        """
        if len(path) <= 2:
            return path
        
        smoothed = [path[0]]
        i = 0
        
        while i < len(path) - 1:
            # 尝试从当前点直接连接到更远的点
            j = len(path) - 1
            found = False
            
            while j > i + 1:
                # 检查直接连接是否可行
                if self._is_path_clear(path[i], path[j], robot_radius):
                    smoothed.append(path[j])
                    i = j
                    found = True
                    break
                j -= 1
            
            if not found:
                smoothed.append(path[i + 1])
                i += 1
        
        return smoothed
    
    def _is_path_clear(self, start: Pose, end: Pose, robot_radius: float, num_checks: int = 10) -> bool:
        """
        检查两点之间的路径是否畅通
        
        Args:
            start: 起点
            end: 终点
            robot_radius: 机器人半径
            num_checks: 检查点数量
            
        Returns:
            路径是否畅通
        """
        for i in range(num_checks + 1):
            t = i / num_checks
            x = start.x + t * (end.x - start.x)
            y = start.y + t * (end.y - start.y)
            
            map_x, map_y = self.map_manager.world_to_map(x, y)
            
            if not self._is_valid_position(map_x, map_y, robot_radius):
                return False
        
        return True
    
    def _point_to_line_distance(self, px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """
        计算点到线段的距离
        
        Args:
            px, py: 点坐标
            x1, y1, x2, y2: 线段两端点坐标
            
        Returns:
            点到线段的距离
        """
        # 计算线段长度的平方
        line_length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        
        if line_length_sq == 0:
            # 线段退化为点
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
        
        # 计算投影参数t
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_length_sq))
        
        # 计算投影点
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        # 返回点到投影点的距离
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    
    def calculate_passage_width(self, world_x: float, world_y: float, robot_radius: float = 0.2) -> float:
        """
        计算指定位置的通道宽度（考虑虚拟墙）
        
        Args:
            world_x: 世界X坐标
            world_y: 世界Y坐标
            robot_radius: 机器人半径（米）
            
        Returns:
            通道宽度（米），如果无法计算则返回-1
        """
        if self.map_manager.metadata is None or self.map_manager.grid_map is None:
            return -1
        
        map_x, map_y = self.map_manager.world_to_map(world_x, world_y)
        
        # 检查边界
        if (map_x < 0 or map_x >= self.map_manager.metadata.width or
            map_y < 0 or map_y >= self.map_manager.metadata.height):
            return -1
        
        # 首先检查是否靠近虚拟墙（虚拟墙附近可能是窄道）
        virtual_wall_threshold = 0.5  # 虚拟墙影响范围（米），扩大范围以更准确检测窄道
        near_virtual_wall = False
        closest_wall_distance = float('inf')
        
        if hasattr(self.map_manager, 'virtual_walls') and self.map_manager.virtual_walls:
            for wall in self.map_manager.virtual_walls:
                start = wall.get("start", {})
                end = wall.get("end", {})
                if start and end:
                    dist = self._point_to_line_distance(
                        world_x, world_y,
                        start.get("x", 0), start.get("y", 0),
                        end.get("x", 0), end.get("y", 0)
                    )
                    if dist < closest_wall_distance:
                        closest_wall_distance = dist
                    if dist < virtual_wall_threshold:
                        near_virtual_wall = True
        
        # 计算8个方向的可用空间
        max_width = 0.0
        resolution = self.map_manager.metadata.resolution
        
        # 检查4个主要方向（上下左右）
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            width = 0.0
            # 向一个方向扩展
            for i in range(1, 100):  # 最多检查100个像素
                px = map_x + dx * i
                py = map_y + dy * i
                
                if (px < 0 or px >= self.map_manager.metadata.width or
                    py < 0 or py >= self.map_manager.metadata.height):
                    break
                
                # 检查是否与虚拟墙相交（虚拟墙视为障碍物）
                world_px, world_py = self.map_manager.map_to_world(px, py)
                hit_virtual_wall = False
                if hasattr(self.map_manager, 'virtual_walls') and self.map_manager.virtual_walls:
                    for wall in self.map_manager.virtual_walls:
                        start = wall.get("start", {})
                        end = wall.get("end", {})
                        if start and end:
                            # 检查点是否在线段附近（考虑虚拟墙的宽度，约0.15米）
                            dist = self._point_to_line_distance(
                                world_px, world_py,
                                start.get("x", 0), start.get("y", 0),
                                end.get("x", 0), end.get("y", 0)
                            )
                            if dist < 0.15:  # 虚拟墙宽度约0.15米（考虑机器人半径）
                                hit_virtual_wall = True
                                break
                
                if hit_virtual_wall:
                    break
                
                if HAS_NUMPY and isinstance(self.map_manager.grid_map, np.ndarray):
                    value = self.map_manager.grid_map[py, px]
                else:
                    value = self.map_manager.grid_map[py][px]
                
                if value == 0:  # 遇到障碍物
                    break
                
                width += resolution
            
            # 向相反方向扩展
            for i in range(1, 100):
                px = map_x - dx * i
                py = map_y - dy * i
                
                if (px < 0 or px >= self.map_manager.metadata.width or
                    py < 0 or py >= self.map_manager.metadata.height):
                    break
                
                # 检查是否与虚拟墙相交（虚拟墙视为障碍物）
                world_px, world_py = self.map_manager.map_to_world(px, py)
                hit_virtual_wall = False
                if hasattr(self.map_manager, 'virtual_walls') and self.map_manager.virtual_walls:
                    for wall in self.map_manager.virtual_walls:
                        start = wall.get("start", {})
                        end = wall.get("end", {})
                        if start and end:
                            # 检查点是否在线段附近（考虑虚拟墙的宽度，约0.15米）
                            dist = self._point_to_line_distance(
                                world_px, world_py,
                                start.get("x", 0), start.get("y", 0),
                                end.get("x", 0), end.get("y", 0)
                            )
                            if dist < 0.15:  # 虚拟墙宽度约0.15米（考虑机器人半径）
                                hit_virtual_wall = True
                                break
                
                if hit_virtual_wall:
                    break
                
                if HAS_NUMPY and isinstance(self.map_manager.grid_map, np.ndarray):
                    value = self.map_manager.grid_map[py, px]
                else:
                    value = self.map_manager.grid_map[py][px]
                
                if value == 0:  # 遇到障碍物
                    break
                
                width += resolution
            
            max_width = max(max_width, width)
        
        # 如果靠近虚拟墙，适当减小计算的宽度（虚拟墙围成的区域通常是窄道）
        if near_virtual_wall and max_width > 0:
            max_width = max_width * 0.8  # 减小20%以反映虚拟墙的影响
        
        return max_width
    
    def detect_narrow_passages(self, path: List[Pose], robot_radius: float = 0.2, narrow_threshold: float = 1.0) -> List[Tuple[int, Pose, float]]:
        """
        检测路径中的窄道
        
        Args:
            path: 路径点列表
            robot_radius: 机器人半径（米）
            narrow_threshold: 窄道阈值（米），宽度小于此值认为是窄道
            
        Returns:
            窄道列表，每个元素为(索引, 位置, 宽度)
        """
        narrow_passages = []
        
        if not path:
            return narrow_passages
        
        # 检查路径中的每个点
        for i, pose in enumerate(path):
            width = self.calculate_passage_width(pose.x, pose.y, robot_radius)
            
            if width > 0 and width < narrow_threshold:
                narrow_passages.append((i, pose, width))
                logger.debug(f"Narrow passage detected at path index {i}: width={width:.2f}m")
        
        return narrow_passages
    
    def can_pass_concurrently(self, passage_width: float, robot_radius: float, num_robots: int = 2) -> bool:
        """
        判断窄道是否可以同时通过多个机器人
        
        Args:
            passage_width: 通道宽度（米）
            robot_radius: 机器人半径（米）
            num_robots: 机器人数量
            
        Returns:
            是否可以同时通过
        """
        # 需要至少2个机器人直径的宽度，加上安全距离
        required_width = num_robots * robot_radius * 2 + 0.2  # 0.2米安全距离
        return passage_width >= required_width
    
    def find_waiting_point(
        self,
        current_pose: Pose,
        narrow_passage_pose: Optional[Pose] = None,
        min_distance: float = 2.0,
        max_distance: float = 5.0,
        robot_radius: float = 0.3
    ) -> Optional[Pose]:
        """
        查找等待点（系统自动计算，无需手动标注）
        
        等待点应该满足：
        1. 距离窄道足够远，不会阻塞其他机器人
        2. 位置安全，不在障碍物上
        3. 有足够的空间供机器人停留
        
        Args:
            current_pose: 机器人当前位置
            narrow_passage_pose: 窄道位置（如果提供，等待点会在窄道后方）
            min_distance: 最小距离（米）
            max_distance: 最大距离（米）
            robot_radius: 机器人半径（米）
            
        Returns:
            等待点位置，如果找不到则返回None
        """
        if self.map_manager.metadata is None or self.map_manager.grid_map is None:
            logger.warning("Map not loaded, cannot find waiting point")
            return None
        
        # 确定搜索方向
        if narrow_passage_pose:
            # 如果提供了窄道位置，向窄道后方搜索
            dx = current_pose.x - narrow_passage_pose.x
            dy = current_pose.y - narrow_passage_pose.y
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > 0:
                direction = math.atan2(dy, dx)  # 从窄道指向当前位置的方向
            else:
                # 如果位置相同，使用机器人当前朝向的反方向
                direction = current_pose.yaw + math.pi
        else:
            # 如果没有窄道位置，使用机器人当前朝向的反方向
            direction = current_pose.yaw + math.pi
        
        # 在多个距离上尝试查找等待点
        search_distances = []
        step = (max_distance - min_distance) / 5
        for i in range(6):
            dist = min_distance + i * step
            search_distances.append(dist)
        
        # 也在侧向搜索（左右各30度）
        side_angles = [-math.pi / 6, math.pi / 6]
        
        best_point = None
        best_score = -1
        
        for distance in search_distances:
            # 正后方
            test_angles = [direction] + [direction + angle for angle in side_angles]
            
            for angle in test_angles:
                test_x = current_pose.x - math.cos(angle) * distance
                test_y = current_pose.y - math.sin(angle) * distance
                test_pose = Pose(x=test_x, y=test_y, z=current_pose.z, yaw=current_pose.yaw)
                
                # 转换为地图坐标
                map_x, map_y = self.map_manager.world_to_map(test_x, test_y)
                
                # 检查位置是否有效
                if not self._is_valid_position(map_x, map_y, robot_radius):
                    continue
                
                # 检查周围是否有足够空间（至少1.5倍机器人直径）
                clearance_radius = robot_radius * 1.5
                clearance_pixels = int(clearance_radius / self.map_manager.metadata.resolution)
                
                has_clearance = True
                for dy in range(-clearance_pixels, clearance_pixels + 1):
                    for dx in range(-clearance_pixels, clearance_pixels + 1):
                        px = map_x + dx
                        py = map_y + dy
                        
                        if (0 <= px < self.map_manager.metadata.width and
                            0 <= py < self.map_manager.metadata.height):
                            dist = math.sqrt(dx**2 + dy**2) * self.map_manager.metadata.resolution
                            if dist <= clearance_radius:
                                if HAS_NUMPY and isinstance(self.map_manager.grid_map, np.ndarray):
                                    value = self.map_manager.grid_map[py, px]
                                else:
                                    value = self.map_manager.grid_map[py][px]
                                if value == 0:  # 障碍物
                                    has_clearance = False
                                    break
                    if not has_clearance:
                        break
                
                if not has_clearance:
                    continue
                
                # 检查是否靠近虚拟墙（避免在虚拟墙附近设置等待点）
                near_virtual_wall = False
                if hasattr(self.map_manager, 'virtual_walls') and self.map_manager.virtual_walls:
                    for wall in self.map_manager.virtual_walls:
                        start = wall.get("start", {})
                        end = wall.get("end", {})
                        if start and end:
                            dist = self._point_to_line_distance(
                                test_x, test_y,
                                start.get("x", 0), start.get("y", 0),
                                end.get("x", 0), end.get("y", 0)
                            )
                            if dist < 0.5:  # 距离虚拟墙小于0.5米，不适合作为等待点
                                near_virtual_wall = True
                                break
                
                if near_virtual_wall:
                    continue  # 跳过虚拟墙附近的点
                
                # 计算得分：距离适中、远离窄道、空间充足、远离虚拟墙
                score = 1.0
                # 距离越接近(min_distance + max_distance)/2越好
                ideal_distance = (min_distance + max_distance) / 2
                distance_score = 1.0 - abs(distance - ideal_distance) / (max_distance - min_distance)
                score *= distance_score
                
                # 如果提供了窄道位置，优先选择远离窄道的点
                if narrow_passage_pose:
                    dist_to_passage = math.sqrt(
                        (test_x - narrow_passage_pose.x)**2 + (test_y - narrow_passage_pose.y)**2
                    )
                    if dist_to_passage > min_distance:
                        score *= 1.2  # 奖励远离窄道的点
                
                if score > best_score:
                    best_score = score
                    best_point = test_pose
        
        if best_point:
            logger.info(
                f"Found waiting point at ({best_point.x:.2f}, {best_point.y:.2f}), "
                f"distance={math.sqrt((best_point.x - current_pose.x)**2 + (best_point.y - current_pose.y)**2):.2f}m"
            )
        else:
            logger.warning(f"Could not find waiting point for robot at ({current_pose.x:.2f}, {current_pose.y:.2f})")
        
        return best_point

