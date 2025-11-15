"""
避让策略模块（优化版本）
"""
import math
import logging
from typing import List, Optional, Dict, Tuple
from enum import Enum
from app.models.robot import Pose, Speed
from app.services.collision_detector import CollisionDetector, CollisionPrediction
from app.services.robot_manager import RobotManager
from app.services.path_planner import PathPlanner
from app.services.scene_detector import SceneDetector, SceneType
from config import settings

logger = logging.getLogger(__name__)


class AvoidanceAction(str, Enum):
    """避让动作类型"""
    WAIT = "wait"  # 等待
    SLOW_DOWN = "slow_down"  # 减速
    STOP = "stop"  # 停止
    REROUTE = "reroute"  # 重新规划路径
    YIELD = "yield"  # 让行


class AvoidanceStrategy:
    """避让策略，决定机器人如何避免碰撞"""
    
    def __init__(
        self,
        robot_manager: RobotManager,
        collision_detector: CollisionDetector,
        path_planner: PathPlanner,
        scene_detector: SceneDetector = None
    ):
        """
        初始化避让策略
        
        Args:
            robot_manager: 机器人管理器
            collision_detector: 碰撞检测器
            path_planner: 路径规划器
            scene_detector: 场景检测器（可选）
        """
        self.robot_manager = robot_manager
        self.collision_detector = collision_detector
        self.path_planner = path_planner
        self.safety_distance = settings.COLLISION_SAFETY_DISTANCE
        self.robot_radius = settings.ROBOT_RADIUS
        self.robot_rotation_radius = settings.ROBOT_ROTATION_RADIUS
        
        # 初始化场景检测器
        if scene_detector is None:
            from app.services.map_manager import get_map_manager
            map_manager = get_map_manager()
            from app.services.scene_detector import SceneDetector
            scene_detector = SceneDetector(map_manager, path_planner)
        self.scene_detector = scene_detector
        
        # 十字路口协调状态（robot_id -> 进入时间）
        self.intersection_occupancy: Dict[str, float] = {}
    
    async def calculate_priority(
        self,
        robot_id: str,
        task_priority: int = 2
    ) -> float:
        """
        计算机器人优先级
        
        Args:
            robot_id: 机器人ID
            task_priority: 任务优先级
            
        Returns:
            优先级分数（越高越优先）
        """
        try:
            # 优先级 = 任务优先级 * 10 + 距离因子
            # 距离因子：距离目标越近，优先级越高
            
            state = await self.robot_manager.get_robot_state(robot_id)
            if not state:
                return task_priority * 10
            
            # 这里可以添加更多因素，比如机器人电量、任务进度等
            return task_priority * 10
        except Exception as e:
            logger.error(f"Error calculating priority for robot {robot_id}: {e}")
            return task_priority * 10
    
    async def decide_avoidance_action(
        self,
        robot_id: str,
        collision: CollisionPrediction,
        current_task_priority: int = 2
    ) -> Tuple[AvoidanceAction, Dict]:
        """
        决定避让动作（优化版本：针对十字路口和长走廊场景）
        
        Args:
            robot_id: 机器人ID
            collision: 碰撞预测
            current_task_priority: 当前任务优先级
            
        Returns:
            (避让动作, 动作参数)
        """
        try:
            import time
            
            # 确定两个机器人中哪个是当前机器人
            other_robot_id = collision.robot_id2 if collision.robot_id1 == robot_id else collision.robot_id1
            
            # 获取机器人状态
            robot_state = await self.robot_manager.get_robot_state(robot_id)
            other_state = await self.robot_manager.get_robot_state(other_robot_id)
            
            if not robot_state or not other_state:
                return AvoidanceAction.WAIT, {}
            
            # 检测碰撞点场景
            collision_scene = self.scene_detector.detect_scene(
                collision.collision_point,
                robot_state.pose.yaw
            )
            
            # 十字路口场景：使用协调机制
            if collision_scene.scene_type == SceneType.INTERSECTION:
                return await self._handle_intersection_collision(
                    robot_id, other_robot_id, robot_state, other_state,
                    collision, current_task_priority
                )
            
            # 长走廊场景：使用让行策略
            elif collision_scene.scene_type == SceneType.CORRIDOR:
                return await self._handle_corridor_collision(
                    robot_id, other_robot_id, robot_state, other_state,
                    collision, current_task_priority, collision_scene
                )
            
            # 普通场景：使用原有策略
            else:
                return await self._handle_normal_collision(
                    robot_id, other_robot_id, robot_state, other_state,
                    collision, current_task_priority
                )
                
        except Exception as e:
            logger.error(f"Error deciding avoidance action for robot {robot_id}: {e}")
            # 默认：等待
            return AvoidanceAction.WAIT, {"duration": 1.0}
    
    async def _handle_intersection_collision(
        self,
        robot_id: str,
        other_robot_id: str,
        robot_state,
        other_state,
        collision: CollisionPrediction,
        current_task_priority: int
    ) -> Tuple[AvoidanceAction, Dict]:
        """处理十字路口碰撞"""
        import time
        
        # 计算优先级
        robot_priority = await self.calculate_priority(robot_id, current_task_priority)
        other_priority = await self.calculate_priority(other_robot_id, 2)
        
        # 检查哪个机器人先到达十字路口
        robot_distance = self.collision_detector.calculate_distance(
            robot_state.pose, collision.collision_point
        )
        other_distance = self.collision_detector.calculate_distance(
            other_state.pose, collision.collision_point
        )
        
        # 检查是否已经在十字路口
        robot_in_intersection = self.scene_detector.is_robot_in_intersection(robot_state.pose)
        other_in_intersection = self.scene_detector.is_robot_in_intersection(other_state.pose)
        
        # 如果当前机器人已经在十字路口，优先通行
        if robot_in_intersection and not other_in_intersection:
            return AvoidanceAction.WAIT, {"duration": 0.5}  # 短暂等待，让其他机器人等待
        
        # 如果其他机器人已经在十字路口，当前机器人等待
        if other_in_intersection and not robot_in_intersection:
            return AvoidanceAction.WAIT, {"duration": collision.collision_time + 1.0}
        
        # 如果都在十字路口，使用优先级和距离决定
        if robot_in_intersection and other_in_intersection:
            if robot_priority > other_priority:
                return AvoidanceAction.WAIT, {"duration": 0.5}
            elif robot_priority < other_priority:
                return AvoidanceAction.YIELD, {"back_distance": 0.5}
            else:
                # 优先级相同，距离近的优先
                if robot_distance < other_distance:
                    return AvoidanceAction.WAIT, {"duration": 0.5}
                else:
                    return AvoidanceAction.YIELD, {"back_distance": 0.5}
        
        # 都不在十字路口，根据距离和优先级决定
        if robot_distance < other_distance:
            # 当前机器人更近，优先通行
            if robot_priority >= other_priority:
                return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.7}
            else:
                return AvoidanceAction.WAIT, {"duration": collision.collision_time + 0.5}
        else:
            # 其他机器人更近，当前机器人等待或让行
            if robot_priority > other_priority:
                return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.7}
            else:
                return AvoidanceAction.WAIT, {"duration": collision.collision_time + 1.0}
    
    async def _handle_corridor_collision(
        self,
        robot_id: str,
        other_robot_id: str,
        robot_state,
        other_state,
        collision: CollisionPrediction,
        current_task_priority: int,
        scene_info
    ) -> Tuple[AvoidanceAction, Dict]:
        """处理长走廊碰撞"""
        # 计算机器人速度
        robot_speed = math.sqrt(robot_state.speed.vx ** 2 + robot_state.speed.vy ** 2)
        other_speed = math.sqrt(other_state.speed.vx ** 2 + other_state.speed.vy ** 2)
        
        # 计算相对位置和方向
        dx = other_state.pose.x - robot_state.pose.x
        dy = other_state.pose.y - robot_state.pose.y
        distance = math.sqrt(dx**2 + dy**2)
        
        # 计算相对速度方向
        robot_vx = robot_speed * math.cos(robot_state.pose.yaw)
        robot_vy = robot_speed * math.sin(robot_state.pose.yaw)
        other_vx = other_speed * math.cos(other_state.pose.yaw)
        other_vy = other_speed * math.sin(other_state.pose.yaw)
        
        rel_vx = other_vx - robot_vx
        rel_vy = other_vy - robot_vy
        
        # 判断是否相向而行
        dot_product = rel_vx * dx + rel_vy * dy
        is_opposite = dot_product < 0
        
        # 如果相向而行，需要让行
        if is_opposite:
            # 检查走廊宽度是否足够让行
            if scene_info.width >= settings.ROBOT_ROTATION_DIAMETER * 2 + settings.CORRIDOR_YIELD_DISTANCE:
                # 宽度足够，可以侧向让行
                return AvoidanceAction.YIELD, {
                    "yield_distance": settings.CORRIDOR_YIELD_DISTANCE,
                    "yield_direction": scene_info.direction + math.pi / 2
                }
            else:
                # 宽度不足，需要后退到等待点
                yield_point = self.scene_detector.calculate_yield_point(
                    robot_state.pose, scene_info.direction
                )
                if yield_point:
                    return AvoidanceAction.YIELD, {
                        "yield_point": yield_point,
                        "back_distance": settings.CORRIDOR_WAIT_POINT_DISTANCE
                    }
                else:
                    # 无法找到等待点，减速等待
                    return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.3}
        
        # 同向而行，根据优先级和速度决定
        robot_priority = await self.calculate_priority(robot_id, current_task_priority)
        other_priority = await self.calculate_priority(other_robot_id, 2)
        
        if robot_priority > other_priority:
            return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.8}
        elif robot_priority < other_priority:
            return AvoidanceAction.WAIT, {"duration": collision.collision_time + 0.5}
        else:
            # 优先级相同，速度快的优先
            if robot_speed > other_speed:
                return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.8}
            else:
                return AvoidanceAction.WAIT, {"duration": collision.collision_time + 0.5}
    
    async def _handle_normal_collision(
        self,
        robot_id: str,
        other_robot_id: str,
        robot_state,
        other_state,
        collision: CollisionPrediction,
        current_task_priority: int
    ) -> Tuple[AvoidanceAction, Dict]:
        """处理普通场景碰撞（原有逻辑）"""
        # 计算优先级
        robot_priority = await self.calculate_priority(robot_id, current_task_priority)
        other_priority = await self.calculate_priority(other_robot_id, 2)
        
        # 考虑机器人速度
        robot_speed = math.sqrt(robot_state.speed.vx ** 2 + robot_state.speed.vy ** 2)
        other_speed = math.sqrt(other_state.speed.vx ** 2 + other_state.speed.vy ** 2)
        
        # 如果碰撞严重，优先处理
        if collision.severity == "critical":
            if robot_speed > other_speed * 1.2:
                return AvoidanceAction.STOP, {"duration": collision.collision_time + 0.5}
            elif robot_priority >= other_priority:
                return AvoidanceAction.STOP, {"duration": collision.collision_time + 0.5}
            else:
                return AvoidanceAction.WAIT, {"duration": collision.collision_time + 1.0}
        
        # 根据碰撞时间决定动作
        if collision.collision_time < 1.0:
            return AvoidanceAction.STOP, {"duration": collision.collision_time + 1.0}
        elif collision.collision_time < 2.0:
            if robot_priority >= other_priority:
                return AvoidanceAction.STOP, {"duration": collision.collision_time + 0.5}
            else:
                return AvoidanceAction.SLOW_DOWN, {"speed_ratio": 0.3}
        elif collision.collision_time < 5.0:
            speed_ratio = max(0.3, 1.0 - (collision.collision_time / 5.0))
            return AvoidanceAction.SLOW_DOWN, {"speed_ratio": speed_ratio}
        else:
            if robot_priority >= other_priority:
                return AvoidanceAction.WAIT, {"duration": 1.0}
            else:
                return AvoidanceAction.REROUTE, {}
    
    async def apply_avoidance_action(
        self,
        robot_id: str,
        action: AvoidanceAction,
        params: Dict
    ) -> bool:
        """
        应用避让动作
        
        Args:
            robot_id: 机器人ID
            action: 避让动作
            params: 动作参数
            
        Returns:
            是否成功应用
        """
        agent = self.robot_manager.get_robot_agent(robot_id)
        if not agent:
            return False
        
        try:
            if action == AvoidanceAction.STOP:
                # 停止：取消当前action
                await agent.cancel_current_action()
                logger.info(f"Robot {robot_id} stopped for collision avoidance")
                return True
            
            elif action == AvoidanceAction.SLOW_DOWN:
                # 减速：这里需要机器人支持速度调整
                # 由于思岚科技API可能不支持直接调整速度，这里记录日志
                logger.info(f"Robot {robot_id} should slow down (speed_ratio={params.get('speed_ratio', 0.5)})")
                # 实际应用中可能需要重新规划路径并降低速度
                return True
            
            elif action == AvoidanceAction.WAIT:
                # 等待：暂停当前action
                await agent.cancel_current_action()
                logger.info(f"Robot {robot_id} waiting for {params.get('duration', 1.0)} seconds")
                # 等待指定时间后继续
                import asyncio
                await asyncio.sleep(params.get('duration', 1.0))
                return True
            
            elif action == AvoidanceAction.REROUTE:
                # 重新规划路径：需要获取当前任务并重新规划
                logger.info(f"Robot {robot_id} should reroute to avoid collision")
                # 这里需要与任务调度器配合，重新规划路径
                return True
            
            elif action == AvoidanceAction.YIELD:
                # 让行：移动到一侧或后退
                logger.info(f"Robot {robot_id} yielding to other robot")
                
                # 获取机器人状态
                robot_state = await self.robot_manager.get_robot_state(robot_id)
                if not robot_state:
                    return False
                
                # 如果有后退距离，执行后退
                if "back_distance" in params:
                    back_distance = params.get("back_distance", 0.5)
                    # 计算后退目标点
                    back_x = robot_state.pose.x - math.cos(robot_state.pose.yaw) * back_distance
                    back_y = robot_state.pose.y - math.sin(robot_state.pose.yaw) * back_distance
                    back_pose = Pose(x=back_x, y=back_y, z=robot_state.pose.z, yaw=robot_state.pose.yaw)
                    
                    # 移动到后退点
                    try:
                        await agent.move_to(back_pose, mode=0, acceptable_precision=0.2, speed_ratio=0.5)
                        logger.info(f"Robot {robot_id} backing up {back_distance}m to yield")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to move robot {robot_id} back: {e}")
                        return False
                
                # 如果有让行点，移动到让行点
                elif "yield_point" in params:
                    yield_point = params["yield_point"]
                    try:
                        await agent.move_to(yield_point, mode=0, acceptable_precision=0.2, speed_ratio=0.5)
                        logger.info(f"Robot {robot_id} moving to yield point")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to move robot {robot_id} to yield point: {e}")
                        return False
                
                # 如果有让行方向和距离，侧向移动
                elif "yield_direction" in params and "yield_distance" in params:
                    yield_direction = params["yield_direction"]
                    yield_distance = params["yield_distance"]
                    
                    # 计算侧向移动目标点
                    side_x = robot_state.pose.x + math.cos(yield_direction) * yield_distance
                    side_y = robot_state.pose.y + math.sin(yield_direction) * yield_distance
                    side_pose = Pose(x=side_x, y=side_y, z=robot_state.pose.z, yaw=robot_state.pose.yaw)
                    
                    try:
                        await agent.move_to(side_pose, mode=0, acceptable_precision=0.2, speed_ratio=0.5)
                        logger.info(f"Robot {robot_id} moving sideways to yield")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to move robot {robot_id} sideways: {e}")
                        return False
                
                # 默认：短暂停止
                await agent.cancel_current_action()
                import asyncio
                await asyncio.sleep(1.0)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to apply avoidance action {action} for robot {robot_id}: {e}")
            return False
    
    async def handle_collision(
        self,
        robot_id: str,
        collision: CollisionPrediction,
        task_priority: int = 2
    ) -> bool:
        """
        处理碰撞
        
        Args:
            robot_id: 机器人ID
            collision: 碰撞预测
            task_priority: 任务优先级
            
        Returns:
            是否成功处理
        """
        # 决定避让动作
        action, params = await self.decide_avoidance_action(
            robot_id,
            collision,
            task_priority
        )
        
        # 应用避让动作
        success = await self.apply_avoidance_action(robot_id, action, params)
        
        if success:
            logger.info(
                f"Collision avoided for robot {robot_id} using action {action.value}"
            )
        
        return success
    
    async def check_and_avoid_collisions(
        self,
        robot_id: str,
        task_priority: int = 2
    ) -> List[CollisionPrediction]:
        """
        检查并避免碰撞
        
        Args:
            robot_id: 机器人ID
            task_priority: 任务优先级
            
        Returns:
            发现的碰撞列表
        """
        try:
            # 检测碰撞
            collisions = await self.collision_detector.detect_collisions([robot_id])
            
            # 过滤出与当前机器人相关的碰撞
            robot_collisions = [
                c for c in collisions
                if c.robot_id1 == robot_id or c.robot_id2 == robot_id
            ]
            
            # 处理每个碰撞
            for collision in robot_collisions:
                await self.handle_collision(robot_id, collision, task_priority)
            
            return robot_collisions
        except Exception as e:
            logger.error(f"Error in check_and_avoid_collisions for robot {robot_id}: {e}")
            return []

