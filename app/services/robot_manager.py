"""
机器人管理器
"""
import asyncio
import json
import logging
import os
import httpx
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime
from app.services.robot_agent import RobotAgent
from app.services.network_detector import get_network_detector
from app.models.robot import RobotState, RobotStatus, Pose, Speed, PowerStatus, HealthStatus, RobotInfo

logger = logging.getLogger(__name__)


class RobotManager:
    """机器人管理器，管理多台机器人的状态和生命周期"""
    
    # 存储文件路径
    STORAGE_FILE = Path("data/robots.json")
    
    def __init__(self):
        """初始化机器人管理器"""
        self.robots: Dict[str, RobotAgent] = {}  # robot_id -> RobotAgent
        self.robot_states: Dict[str, RobotState] = {}  # robot_id -> RobotState
        self._update_task: Optional[asyncio.Task] = None
        
        # 确保数据目录存在
        self.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 从文件读取已注册的机器人信息（待异步加载）
        self._pending_robots = []
        self._load_robots_from_file()
        
        # 初始化网络检测器（延迟检测，在首次注册机器人后触发）
        self._network_detection_task: Optional[asyncio.Task] = None
    
    async def register_robot(self, robot_id: str, base_url: str) -> Tuple[bool, Optional[str]]:
        """
        注册机器人（容错模式：允许注册离线机器人）
        
        Args:
            robot_id: 机器人ID
            base_url: 机器人底盘API基础URL
            
        Returns:
            (是否注册成功, 错误信息)
        """
        result = await self._register_robot_internal(robot_id, base_url, save_to_file=True)
        
        # 如果注册成功且还没有检测过网络环境，触发网络环境检测
        if result[0] and self._network_detection_task is None:
            self._network_detection_task = asyncio.create_task(self._detect_network_environment())
        
        return result
    
    async def _detect_network_environment(self):
        """检测网络环境（使用已注册的机器人地址）"""
        try:
            network_detector = get_network_detector()
            
            # 如果已经通过环境变量设置了网络类型，跳过自动检测
            import os
            if os.getenv("NETWORK_TYPE"):
                logger.info("Network type set via environment variable, skipping auto-detection")
                return
            
            # 获取已注册的机器人URL作为测试地址
            test_urls = []
            for robot_id, agent in self.robots.items():
                if agent and agent.base_url:
                    # 尝试使用机器人的健康检查端点
                    test_url = f"{agent.base_url}/api/core/system/v1/robot/health"
                    test_urls.append(test_url)
                    if len(test_urls) >= 3:  # 最多测试3个机器人
                        break
            
            if test_urls:
                logger.info(f"Auto-detecting network environment using {len(test_urls)} robot(s)...")
                network_type, latency = await network_detector.detect_network_environment(test_urls)
                logger.info(
                    f"Network environment auto-detected: {network_type.value}, "
                    f"average latency: {latency:.2f}ms"
                )
            else:
                logger.info("No robots registered yet, using default network type (DIRECT)")
        except Exception as e:
            logger.warning(f"Failed to detect network environment: {e}, using default (DIRECT)")
    
    async def _create_offline_state(self, robot_id: str):
        """创建离线状态"""
        from app.models.robot import RobotState, RobotStatus, Pose, Speed, PowerStatus, HealthStatus
        from datetime import datetime
        
        state = RobotState(
            robot_id=robot_id,
            status=RobotStatus.OFFLINE,
            pose=Pose(x=0, y=0, z=0, yaw=0, pitch=0, roll=0),
            speed=Speed(vx=0, vy=0, omega=0),
            power=PowerStatus(
                batteryPercentage=0,
                isCharging=False,
                isDCConnected=False,
                dockingStatus="unknown",
                powerStage="unknown",
                sleepMode="unknown"
            ),
            health=HealthStatus(
                hasError=False,
                hasFatal=False,
                hasWarning=False,
                hasSystemEmergencyStop=False,
                hasLidarDisconnected=False,
                hasDepthCameraDisconnected=False,
                hasSdpDisconnected=False,
                baseError=[]
            ),
            info=None,
            localization_quality=None,
            current_action_id=None,
            last_update_time=datetime.now()
        )
        self.robot_states[robot_id] = state
    
    async def unregister_robot(self, robot_id: str) -> bool:
        """
        注销机器人
        
        Args:
            robot_id: 机器人ID
            
        Returns:
            是否注销成功
        """
        try:
            if robot_id not in self.robots:
                return False
            
            # 关闭机器人代理
            agent = self.robots.pop(robot_id)
            await agent.close()
            
            # 移除状态
            self.robot_states.pop(robot_id, None)
            
            # 保存到文件
            self._save_robots_to_file()
            
            logger.info(f"Robot {robot_id} unregistered successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister robot {robot_id}: {e}")
            return False
    
    def list_robots(self) -> list[str]:
        """获取所有机器人ID列表"""
        return list(self.robots.keys())
    
    def get_robot_agent(self, robot_id: str) -> Optional[RobotAgent]:
        """获取机器人代理"""
        return self.robots.get(robot_id)
    
    def find_robot_by_host(self, host: str) -> Optional[str]:
        """
        根据主机地址（IP或域名）查找已注册的机器人ID
        
        Args:
            host: 主机地址（IP或域名）
            
        Returns:
            机器人ID，如果未找到则返回None
        """
        from urllib.parse import urlparse
        
        for robot_id, agent in self.robots.items():
            try:
                parsed = urlparse(agent.base_url)
                agent_host = parsed.hostname or ""
                if agent_host == host:
                    return robot_id
            except Exception:
                continue
        
        return None
    
    async def get_robot_state(self, robot_id: str, force_update: bool = False) -> Optional[RobotState]:
        """
        获取机器人状态
        
        Args:
            robot_id: 机器人ID
            force_update: 是否强制更新（默认False，使用缓存的状态）
            
        Returns:
            机器人状态，如果机器人不存在则返回None
        """
        if robot_id not in self.robots:
            return None
        
        # 检查缓存的状态是否足够新（10秒内，增加缓存时间以减少API调用）
        # 但如果缓存状态是离线，即使缓存足够新，也强制更新一次（确保能检测到机器人上线）
        if not force_update and robot_id in self.robot_states:
            state = self.robot_states[robot_id]
            if state.last_update_time:
                time_since_update = (datetime.now() - state.last_update_time).total_seconds()
                # 如果状态在10秒内更新过，且状态不是离线，直接返回缓存
                if time_since_update < 10.0 and state.status != RobotStatus.OFFLINE:
                    return state
                # 如果状态是离线，即使缓存足够新，也强制更新一次
                elif state.status == RobotStatus.OFFLINE:
                    force_update = True
                    logger.info(f"Robot {robot_id} is offline in cache, forcing update to check if it's back online")
        
        # 需要更新状态
        await self._update_robot_state(robot_id)
        
        # 如果状态存在，返回状态
        if robot_id in self.robot_states:
            return self.robot_states[robot_id]
        
        # 如果状态不存在，创建一个离线状态
        # 这通常不应该发生，但为了安全起见
        agent = self.robots.get(robot_id)
        if agent:
            state = RobotState(
                robot_id=robot_id,
                status=RobotStatus.OFFLINE,
                pose=Pose(x=0, y=0, z=0, yaw=0, pitch=0, roll=0),
                speed=Speed(vx=0, vy=0, omega=0),
                power=PowerStatus(
                    batteryPercentage=0,
                    isCharging=False,
                    isDCConnected=False,
                    dockingStatus="unknown",
                    powerStage="unknown",
                    sleepMode="unknown"
                ),
                health=HealthStatus(
                    hasError=False,
                    hasFatal=False,
                    hasWarning=False,
                    hasSystemEmergencyStop=False,
                    hasLidarDisconnected=False,
                    hasDepthCameraDisconnected=False,
                    hasSdpDisconnected=False,
                    baseError=[]
                ),
                info=None,
                localization_quality=None,
                current_action_id=None,
                last_update_time=datetime.now()
            )
            self.robot_states[robot_id] = state
            return state
        
        return None
    
    async def get_robot_pose(self, robot_id: str) -> Optional[Pose]:
        """
        获取机器人位置
        
        Args:
            robot_id: 机器人ID
            
        Returns:
            机器人位置
        """
        agent = self.robots.get(robot_id)
        if not agent:
            return None
        
        try:
            return await agent.get_pose()
        except Exception as e:
            logger.error(f"Failed to get pose for robot {robot_id}: {e}")
            return None
    
    async def _update_robot_state(self, robot_id: str):
        """
        更新机器人状态（优化：使用并发获取，减少总时间）
        
        Args:
            robot_id: 机器人ID
        """
        agent = self.robots.get(robot_id)
        if not agent:
            return
        
        try:
            # 优化：为每个API单独设置超时，避免一个慢的API导致整体超时
            # 根据网络环境自动调整超时时间
            network_detector = get_network_detector()
            timeouts = network_detector.get_timeouts()
            
            async def get_pose_with_timeout():
                """获取pose（根据网络环境自动调整超时）"""
                try:
                    return await asyncio.wait_for(agent.get_pose(), timeout=timeouts["pose"])
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting pose for robot {robot_id} ({timeouts['pose']}s)")
                    return None
                except Exception as e:
                    logger.warning(f"Failed to get pose for robot {robot_id}: {e}")
                    return None
            
            async def get_speed_with_timeout():
                """获取speed（根据网络环境自动调整超时）"""
                try:
                    return await asyncio.wait_for(agent.get_speed(), timeout=timeouts["speed"])
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting speed for robot {robot_id} ({timeouts['speed']}s)")
                    return None
                except Exception as e:
                    logger.debug(f"Failed to get speed for robot {robot_id}: {e}")
                    return None
            
            async def get_power_with_timeout():
                """获取power（根据网络环境自动调整超时）"""
                try:
                    return await asyncio.wait_for(agent.get_power_status(), timeout=timeouts["power"])
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting power for robot {robot_id} ({timeouts['power']}s)")
                    return None
                except Exception as e:
                    logger.warning(f"Failed to get power for robot {robot_id}: {e}")
                    return None
            
            async def get_health_with_timeout():
                """获取health（根据网络环境自动调整超时，health是最轻量级的API，优先使用）"""
                try:
                    # health API是最轻量级的，使用较长的超时时间，确保能成功获取
                    return await asyncio.wait_for(agent.get_health_status(), timeout=timeouts["health"])
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout getting health for robot {robot_id} ({timeouts['health']}s)")
                    return None
                except Exception as e:
                    logger.debug(f"Failed to get health for robot {robot_id}: {e}")
                    return None
            
            # 并发获取核心状态（每个API独立超时，不会互相影响）
            pose, speed, power, health = await asyncio.gather(
                get_pose_with_timeout(),
                get_speed_with_timeout(),
                get_power_with_timeout(),
                get_health_with_timeout(),
                return_exceptions=True
            )
            
            # 处理异常结果
            if isinstance(pose, Exception):
                logger.warning(f"Exception getting pose for robot {robot_id}: {pose}")
                pose = None
            if isinstance(speed, Exception):
                logger.debug(f"Exception getting speed for robot {robot_id}: {speed}")
                speed = None
            if isinstance(power, Exception):
                logger.warning(f"Exception getting power for robot {robot_id}: {power}")
                power = None
            if isinstance(health, Exception):
                logger.debug(f"Exception getting health for robot {robot_id}: {health}")
                health = None
            
            # 优化：如果power或pose任何一个获取成功，说明机器人是在线的
            # 优先使用power判断（因为用户提供的证据显示power API是可访问的）
            logger.info(f"Robot {robot_id} state check: pose={pose is not None}, power={power is not None}, speed={speed is not None}, health={health is not None}")
            
            # 详细记录每个API的获取结果
            if pose:
                logger.debug(f"Robot {robot_id} pose: ({pose.x:.2f}, {pose.y:.2f}, {pose.yaw:.2f})")
            if power:
                logger.debug(f"Robot {robot_id} power: {power.batteryPercentage}%, charging={power.isCharging}")
            if health:
                logger.debug(f"Robot {robot_id} health: error={health.hasError}, fatal={health.hasFatal}")
            
            # 优化：只要任何一个API成功，就认为机器人在线
            # 优先检查health（最轻量级），然后是speed，最后是pose和power
            if not pose and not power and not health and not speed:
                # 所有API都失败，标记为离线
                error_msg = f"Failed to get essential states for robot {robot_id}: pose={pose is not None}, power={power is not None}, health={health is not None}, speed={speed is not None}, base_url={agent.base_url}"
                logger.warning(error_msg)
                raise Exception(error_msg)
            
            # 如果至少有一个API成功，标记为在线（使用默认值填充缺失的数据）
            if not pose:
                logger.debug(f"Robot {robot_id}: Pose unavailable, using default pose (0,0,0)")
                pose = Pose(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0)
            
            if not power:
                logger.debug(f"Robot {robot_id}: Power unavailable, using default power status")
                power = PowerStatus(
                    batteryPercentage=0,
                    isCharging=False,
                    isDCConnected=False,
                    dockingStatus="unknown",
                    powerStage="unknown",
                    sleepMode="unknown"
                )
            
            # 如果至少有一个API成功，说明机器人是在线的
            if health or speed or pose or power:
                logger.debug(f"Robot {robot_id}: At least one API succeeded (pose={pose is not None}, power={power is not None}, health={health is not None}, speed={speed is not None}). Marking as online.")
            
            # health可以缺失，如果获取失败，使用默认的健康状态（假设健康）
            if not health:
                logger.debug(f"Health status unavailable for robot {robot_id}, using default healthy status")
                health = HealthStatus(
                    hasError=False,
                    hasFatal=False,
                    hasWarning=False,
                    hasSystemEmergencyStop=False,
                    hasLidarDisconnected=False,
                    hasDepthCameraDisconnected=False,
                    hasSdpDisconnected=False,
                    baseError=[]
                )
            
            # 获取可选状态（并发获取，快速失败）
            info = None
            quality = None
            current_action = None
            
            async def get_optional_states():
                """并发获取可选状态"""
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(
                            agent.get_robot_info(),
                            agent.get_localization_quality(),
                            agent.get_current_action(),
                            return_exceptions=True
                        ),
                        timeout=1.5  # 可选状态总超时1.5秒
                    )
                    return results
                except asyncio.TimeoutError:
                    return [None, None, None]
            
            optional_results = await get_optional_states()
            if len(optional_results) >= 1 and not isinstance(optional_results[0], Exception):
                info = optional_results[0]
            if len(optional_results) >= 2 and not isinstance(optional_results[1], Exception):
                quality = optional_results[1]
            if len(optional_results) >= 3 and not isinstance(optional_results[2], Exception):
                current_action = optional_results[2]
            
            # 确定机器人状态
            # 注意：current_action为None或400错误都表示没有正在执行的动作，应该标记为IDLE
            logger.debug(f"Robot {robot_id} status determination: health_error={health.hasError if health else 'N/A'}, "
                        f"health_fatal={health.hasFatal if health else 'N/A'}, "
                        f"current_action={'None' if not current_action else f'status={current_action.status}'}")
            
            # 判断机器人状态：有错误、致命错误、系统急停或baseError不为空都视为故障
            # 注意：errorCode为17041920或17042176的错误不影响使用，需要过滤掉
            ignored_error_codes = [17041920, 17042176]
            has_base_error = False
            if health.baseError and len(health.baseError) > 0:
                # 过滤掉不影响使用的错误码
                significant_errors = [
                    err for err in health.baseError 
                    if isinstance(err, dict) and err.get('errorCode') not in ignored_error_codes
                ]
                has_base_error = len(significant_errors) > 0
            
            if health.hasError or health.hasFatal or health.hasSystemEmergencyStop or has_base_error:
                status = RobotStatus.ERROR
            elif current_action and current_action.status == 1:  # Working (status=1表示正在工作)
                status = RobotStatus.BUSY
            else:
                # current_action为None或status!=1都表示空闲
                status = RobotStatus.IDLE
            
            # 创建默认的speed和power（如果获取失败）
            if not speed:
                speed = Speed(vx=0, vy=0, omega=0)
            if not power:
                power = PowerStatus(
                    batteryPercentage=0,
                    isCharging=False,
                    isDCConnected=False,
                    dockingStatus="unknown",
                    powerStage="unknown",
                    sleepMode="unknown"
                )
            
            # 创建机器人状态对象
            state = RobotState(
                robot_id=robot_id,
                status=status,
                pose=pose,
                speed=speed,
                power=power,
                health=health,
                info=info,
                localization_quality=quality,
                current_action_id=current_action.action_id if current_action and current_action.action_id else None,
                last_update_time=datetime.now()
            )
            
            self.robot_states[robot_id] = state
            
            # 记录状态更新日志（关键信息）
            logger.info(
                f"Robot {robot_id} state updated: status={status.value}, "
                f"pose=({pose.x:.2f}, {pose.y:.2f}), "
                f"power={power.batteryPercentage}%, "
                f"current_action={'None' if not current_action else f'status={current_action.status}'}, "
                f"health_error={health.hasError if health else 'N/A'}"
            )
            
        except httpx.ConnectError as e:
            logger.warning(f"Failed to connect to robot {robot_id} at {agent.base_url}: {e}. Will retry in next update cycle.")
            # 连接失败，标记为离线（但会在下次循环重试）
            # 注意：即使连接失败，也不立即标记为离线，因为可能是临时网络问题
            # 只有在多次失败后才标记为离线
            if robot_id in self.robot_states:
                # 如果之前是在线状态，保持在线状态一段时间（避免频繁切换）
                if self.robot_states[robot_id].status != RobotStatus.OFFLINE:
                    logger.debug(f"Robot {robot_id} connection failed but was online, keeping online status temporarily")
                else:
                    self.robot_states[robot_id].status = RobotStatus.OFFLINE
                    self.robot_states[robot_id].last_update_time = datetime.now()
            else:
                await self._create_offline_state(robot_id)
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout when updating state for robot {robot_id} at {agent.base_url}: {e}. Will retry in next update cycle.")
            # 超时，标记为离线（但会在下次循环重试）
            # 注意：即使超时，也不立即标记为离线，因为可能是临时网络问题
            if robot_id in self.robot_states:
                # 如果之前是在线状态，保持在线状态一段时间（避免频繁切换）
                if self.robot_states[robot_id].status != RobotStatus.OFFLINE:
                    logger.debug(f"Robot {robot_id} timeout but was online, keeping online status temporarily")
                else:
                    self.robot_states[robot_id].status = RobotStatus.OFFLINE
                    self.robot_states[robot_id].last_update_time = datetime.now()
            else:
                await self._create_offline_state(robot_id)
        except Exception as e:
            error_msg = str(e)
            # 检查是否是"Failed to get essential states"错误（所有API都失败）
            if "Failed to get essential states" in error_msg:
                logger.warning(f"All APIs failed for robot {robot_id} at {agent.base_url}: {e}. Will retry in next update cycle.")
            else:
                logger.warning(f"Failed to update state for robot {robot_id} at {agent.base_url}: {e}. Will retry in next update cycle.")
            # 其他错误，标记为离线（但会在下次循环重试）
            if robot_id in self.robot_states:
                # 如果之前是在线状态，保持在线状态一段时间（避免频繁切换）
                if self.robot_states[robot_id].status != RobotStatus.OFFLINE and "Failed to get essential states" not in error_msg:
                    logger.debug(f"Robot {robot_id} error but was online, keeping online status temporarily")
                else:
                    self.robot_states[robot_id].status = RobotStatus.OFFLINE
                    self.robot_states[robot_id].last_update_time = datetime.now()
            else:
                await self._create_offline_state(robot_id)
    
    async def _update_states_loop(self):
        """状态更新循环（优化：确保2分钟内能更新所有机器人状态）"""
        import asyncio
        import time
        logger.info("Robot state update loop started")
        cycle_count = 0
        while True:
            try:
                cycle_start_time = time.time()
                robot_ids = list(self.robots.keys())
                if robot_ids:
                    cycle_count += 1
                    # 每10个周期（20秒）记录一次详细信息
                    if cycle_count % 10 == 0:
                        logger.info(f"Updating states for {len(robot_ids)} robots: {robot_ids} (cycle {cycle_count})")
                    else:
                        logger.debug(f"Updating states for {len(robot_ids)} robots: {robot_ids}")
                    
                    # 并发更新所有机器人状态（提高效率，确保在2分钟内完成）
                    # 为每个机器人设置最大超时时间（30秒），确保不会无限等待
                    async def update_with_timeout(robot_id: str):
                        """带超时的状态更新"""
                        try:
                            await asyncio.wait_for(
                                self._update_robot_state(robot_id),
                                timeout=30.0  # 每个机器人最多30秒
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Timeout updating state for robot {robot_id} (30s)")
                            # 超时后标记为离线
                            if robot_id in self.robot_states:
                                self.robot_states[robot_id].status = RobotStatus.OFFLINE
                                self.robot_states[robot_id].last_update_time = datetime.now()
                            else:
                                await self._create_offline_state(robot_id)
                    
                    tasks = [update_with_timeout(robot_id) for robot_id in robot_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    cycle_elapsed = time.time() - cycle_start_time
                    
                    # 检查更新结果，记录成功和失败的机器人
                    success_count = 0
                    offline_count = 0
                    for robot_id, result in zip(robot_ids, results):
                        if isinstance(result, Exception):
                            offline_count += 1
                        else:
                            state = self.robot_states.get(robot_id)
                            if state and state.status != RobotStatus.OFFLINE:
                                success_count += 1
                            else:
                                offline_count += 1
                    
                    # 每10个周期记录一次统计信息（包括耗时）
                    if cycle_count % 10 == 0:
                        logger.info(f"State update cycle {cycle_count}: {success_count} online, {offline_count} offline, elapsed={cycle_elapsed:.2f}s")
                    elif cycle_elapsed > 5.0:  # 如果单次循环超过5秒，记录警告
                        logger.warning(f"State update cycle {cycle_count} took {cycle_elapsed:.2f}s (slow)")
                
                # 等待2秒后再次更新（减少更新频率，避免过于频繁的API调用）
                await asyncio.sleep(2.0)
                
            except Exception as e:
                logger.error(f"Error in update states loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)
    
    async def close(self):
        """关闭机器人管理器"""
        # 停止更新任务
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有机器人代理
        for robot_id in list(self.robots.keys()):
            await self.unregister_robot(robot_id)
    
    def _load_robots_from_file(self):
        """从文件读取已注册的机器人信息（同步方法，只读取不加载）"""
        try:
            if not self.STORAGE_FILE.exists():
                logger.info(f"Storage file {self.STORAGE_FILE} does not exist. Starting with empty robot list.")
                self._pending_robots = []
                return
            
            with open(self.STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict) or 'robots' not in data:
                logger.warning(f"Invalid storage file format: {self.STORAGE_FILE}")
                self._pending_robots = []
                return
            
            robots_data = data.get('robots', [])
            if not isinstance(robots_data, list):
                logger.warning(f"Invalid robots data format in {self.STORAGE_FILE}")
                self._pending_robots = []
                return
            
            # 保存待加载的机器人信息
            self._pending_robots = robots_data
            logger.info(f"Found {len(robots_data)} robots in storage file, will load them on startup")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse storage file {self.STORAGE_FILE}: {e}")
            self._pending_robots = []
        except Exception as e:
            logger.error(f"Failed to read storage file {self.STORAGE_FILE}: {e}", exc_info=True)
            self._pending_robots = []
    
    async def load_pending_robots(self):
        """异步加载待注册的机器人（在应用启动时调用）"""
        if not hasattr(self, '_pending_robots') or not self._pending_robots:
            return
        
        logger.info(f"Loading {len(self._pending_robots)} robots from storage file")
        
        # 并发加载所有机器人，而不是串行加载，加快启动速度
        async def load_single_robot(robot_info):
            robot_id = robot_info.get('robot_id')
            base_url = robot_info.get('base_url')
            
            if not robot_id or not base_url:
                logger.warning(f"Invalid robot info: {robot_info}")
                return
            
            try:
                # 重新注册机器人（但不保存到文件，避免重复保存）
                success, error_msg = await self._register_robot_internal(robot_id, base_url, save_to_file=False)
                if success:
                    logger.info(f"Loaded robot {robot_id} from storage file")
                else:
                    logger.warning(f"Failed to load robot {robot_id} from storage file: {error_msg}")
            except Exception as e:
                logger.error(f"Error loading robot {robot_id} from storage file: {e}", exc_info=True)
        
        # 并发加载所有机器人
        await asyncio.gather(*[load_single_robot(robot_info) for robot_info in self._pending_robots], return_exceptions=True)
        
        # 清空待加载列表
        self._pending_robots = []
        
        # 加载完所有机器人后，触发网络环境检测（如果还没有检测过）
        if self._network_detection_task is None and len(self.robots) > 0:
            self._network_detection_task = asyncio.create_task(self._detect_network_environment())
    
    def _save_robots_to_file(self):
        """保存已注册的机器人到文件"""
        try:
            robots_data = []
            for robot_id, agent in self.robots.items():
                robots_data.append({
                    'robot_id': robot_id,
                    'base_url': agent.base_url
                })
            
            data = {
                'robots': robots_data,
                'last_updated': datetime.now().isoformat()
            }
            
            # 使用临时文件写入，然后重命名，确保原子性
            temp_file = self.STORAGE_FILE.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # 原子性替换
            temp_file.replace(self.STORAGE_FILE)
            
            logger.debug(f"Saved {len(robots_data)} robots to storage file")
            
        except Exception as e:
            logger.error(f"Failed to save robots to storage file {self.STORAGE_FILE}: {e}", exc_info=True)
    
    async def _register_robot_internal(self, robot_id: str, base_url: str, save_to_file: bool = True) -> Tuple[bool, Optional[str]]:
        """
        内部注册机器人方法（用于从文件加载时避免重复保存）
        
        Args:
            robot_id: 机器人ID
            base_url: 机器人底盘API基础URL
            save_to_file: 是否保存到文件
            
        Returns:
            (是否注册成功, 错误信息)
        """
        try:
            if robot_id in self.robots:
                logger.warning(f"Robot {robot_id} already registered")
                return False, f"Robot {robot_id} is already registered"
            
            # 创建机器人代理
            agent = RobotAgent(robot_id, base_url)
            
            # 快速测试连接（使用轻量级API和网络检测器的超时配置）
            connection_success = False
            connection_error = None
            # 获取网络检测器的超时配置（在try块外定义，确保except块可以访问）
            network_detector = get_network_detector()
            timeouts = network_detector.get_timeouts()
            # 启动时连接测试使用更短的超时（1秒），避免阻塞服务启动
            # 即使连接失败也会注册机器人，后台任务会继续尝试连接
            test_timeout = min(timeouts["health"], 1.0)
            
            try:
                # 使用health API（最轻量级）来测试连接，而不是pose API
                # health API比pose API更快，更适合快速连接测试
                health = await asyncio.wait_for(agent.get_health_status(), timeout=test_timeout)
                logger.info(f"Successfully connected to robot {robot_id} at {base_url}. Health: {health}")
                connection_success = True
            except asyncio.TimeoutError:
                # 超时是正常的，不记录为错误，让后台任务去检测
                connection_error = f"Connection test timeout (quick check, {test_timeout}s). The system will automatically retry connection every 2 seconds."
                logger.debug(f"Robot {robot_id} quick connection test timeout at {base_url} (using health API, timeout={test_timeout}s). Will retry in background.")
            except httpx.ConnectError as e:
                connection_error = f"Cannot connect to robot at {base_url}. The robot may be offline or starting up. Error: {str(e)}"
                logger.debug(
                    f"Robot {robot_id} connection failed during startup at {base_url}: {e}. "
                    f"This is normal if the robot is starting up or temporarily unreachable. "
                    f"The system will automatically retry connection every 2 seconds."
                )
            except httpx.TimeoutException as e:
                connection_error = f"Connection timeout when connecting to {base_url}. The robot may be unreachable. Error: {str(e)}"
                logger.debug(
                    f"Robot {robot_id} connection timeout during startup at {base_url}: {e}. "
                    f"This is normal if the robot is starting up or temporarily unreachable. "
                    f"The system will automatically retry connection every 2 seconds."
                )
            except httpx.HTTPStatusError as e:
                connection_error = f"HTTP error {e.response.status_code} when connecting to {base_url}. Response: {e.response.text[:200]}"
                logger.debug(
                    f"Robot {robot_id} HTTP error during startup at {base_url}: {e}. "
                    f"The system will automatically retry connection every 2 seconds."
                )
            except Exception as e:
                connection_error = f"Error when connecting to {base_url}: {str(e)}"
                logger.debug(
                    f"Robot {robot_id} connection error during startup at {base_url}: {e}. "
                    f"This is normal if the robot is starting up or temporarily unreachable. "
                    f"The system will automatically retry connection every 2 seconds."
                )
            
            # 注册机器人（即使连接失败也允许注册）
            self.robots[robot_id] = agent
            
            # 如果连接成功，初始化状态；否则延迟判定离线（让状态更新循环尝试重连）
            if connection_success:
                try:
                    await self._update_robot_state(robot_id)
                except Exception as e:
                    logger.warning(f"Failed to update robot state for {robot_id}: {e}. Will retry during status updates.")
                    # 不立即创建离线状态，让状态更新循环去尝试
                    # 只在状态更新循环中多次失败后才判定为离线
            else:
                # 启动时连接失败，不立即判定为离线
                # 让状态更新循环去尝试连接，如果多次失败才判定为离线
                logger.info(f"Robot {robot_id} connection failed during startup. Will retry connection during status updates (every 2 seconds).")
                # 创建一个临时状态，标记为离线但允许重试
                # 状态更新循环会尝试连接，如果成功会更新状态
                await self._create_offline_state(robot_id)
            
            # 保存到文件（如果需要）
            if save_to_file:
                self._save_robots_to_file()
            
            # 启动状态更新任务（如果还没有启动）
            if self._update_task is None or self._update_task.done():
                self._update_task = asyncio.create_task(self._update_states_loop())
            
            logger.info(f"Robot {robot_id} registered successfully at {base_url}")
            if connection_error:
                logger.info(
                    f"Note: Robot {robot_id} connection failed during startup. "
                    f"This is normal if the robot is starting up or temporarily unreachable. "
                    f"The system will automatically retry connection every 2 seconds. "
                    f"Once the robot is online, its status will be updated automatically."
                )
            
            return True, None
            
        except Exception as e:
            error_msg = f"Failed to register robot {robot_id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg


# 全局机器人管理器实例
_robot_manager: Optional[RobotManager] = None


def get_robot_manager() -> RobotManager:
    """获取机器人管理器实例（依赖注入）"""
    global _robot_manager
    if _robot_manager is None:
        _robot_manager = RobotManager()
    return _robot_manager

