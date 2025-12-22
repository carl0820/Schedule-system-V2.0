"""
思岚科技机器人API封装
"""
import httpx
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from app.models.robot import (
    Pose, Speed, PowerStatus, HealthStatus, RobotInfo,
    ActionState, POI, LaserScan, VirtualWall, RestrictedArea
)
from app.services.network_detector import get_network_detector

# 可选导入requests（如果未安装，fallback功能将不可用）
# 尝试从多个位置导入requests
REQUESTS_AVAILABLE = False
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    # 尝试从系统Python的site-packages导入
    try:
        import sys
        import os
        # 常见的系统Python路径
        system_paths = [
            r'C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\Lib\site-packages',
            r'C:\Python313\Lib\site-packages',
            r'C:\Program Files\Python313\Lib\site-packages',
        ]
        for path in system_paths:
            if os.path.exists(path) and path not in sys.path:
                sys.path.insert(0, path)
                try:
                    import requests
                    REQUESTS_AVAILABLE = True
                    logger = logging.getLogger(__name__)
                    logger.info(f"Successfully imported requests from system path: {path}")
                    break
                except ImportError:
                    continue
    except Exception:
        pass
    
    if not REQUESTS_AVAILABLE:
        logger = logging.getLogger(__name__)
        logger.warning("requests library not available. Fallback to requests will be disabled. Install with: pip install requests")

logger = logging.getLogger(__name__)


class RobotAgent:
    """机器人代理，封装思岚科技底盘API"""
    
    def __init__(self, robot_id: str, base_url: str, timeout: float = 5.0):
        """
        初始化机器人代理
        
        Args:
            robot_id: 机器人ID
            base_url: 机器人底盘API基础URL（如：http://10.160.128.91:1448）
            timeout: 请求超时时间（秒），默认5秒（增加超时时间，确保有足够时间连接）
        """
        self.robot_id = robot_id
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        # 配置更详细的超时设置：连接超时和读取超时
        # 增加连接超时时间，确保有足够时间建立连接
        timeout_config = httpx.Timeout(timeout, connect=timeout * 2, read=timeout)
        # 配置连接限制：减少连接池大小，避免连接问题
        limits = httpx.Limits(max_keepalive_connections=2, max_connections=5)
        # 创建httpx客户端，使用更宽松的配置
        # 显式禁用代理，避免使用环境变量中的代理设置（代理可能不可用）
        # 使用 trust_env=False 来禁用环境变量中的代理设置
        self.client = httpx.AsyncClient(
            timeout=timeout_config,
            limits=limits,
            follow_redirects=True,
            http2=False,  # 禁用HTTP/2，使用HTTP/1.1
            verify=False,  # 禁用SSL验证（如果机器人使用自签名证书）
            trust_env=False  # 禁用环境变量中的代理设置，直接连接机器人
        )
        # 线程池执行器，用于执行同步的requests请求（fallback）
        self._executor = ThreadPoolExecutor(max_workers=2)
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()
        self._executor.shutdown(wait=True)
    
    async def _get_with_requests_fallback(self, url: str, timeout: float) -> Dict[str, Any]:
        """
        使用requests库作为fallback（同步，VPN环境下更稳定）
        
        Args:
            url: 请求URL
            timeout: 超时时间（秒）
            
        Returns:
            JSON响应数据
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests library is not available. Install with: pip install requests")
        
        loop = asyncio.get_event_loop()
        try:
            logger.debug(f"Robot {self.robot_id} using requests fallback for {url}")
            # 显式禁用代理，避免使用环境变量中的代理设置（代理可能不可用）
            response = await loop.run_in_executor(
                self._executor,
                lambda: requests.get(
                    url,
                    timeout=timeout,
                    verify=False,
                    allow_redirects=True,
                    proxies={'http': None, 'https': None}  # 禁用代理
                )
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Robot {self.robot_id} requests fallback failed for {url}: {e}")
            raise
        except Exception as e:
            logger.warning(f"Robot {self.robot_id} requests fallback error for {url}: {e}")
            raise
    
    async def _post_with_requests_fallback(self, url: str, data: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        """
        使用requests库作为POST请求的fallback
        
        Args:
            url: 请求URL
            data: POST数据
            timeout: 超时时间（秒）
            
        Returns:
            JSON响应数据
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests library is not available. Install with: pip install requests")
        
        loop = asyncio.get_event_loop()
        try:
            logger.debug(f"Robot {self.robot_id} using requests fallback for POST {url}")
            # 显式禁用代理，避免使用环境变量中的代理设置（代理可能不可用）
            response = await loop.run_in_executor(
                self._executor,
                lambda: requests.post(
                    url,
                    json=data,
                    timeout=timeout,
                    verify=False,
                    allow_redirects=True,
                    proxies={'http': None, 'https': None}  # 禁用代理
                )
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.RequestException as e:
            logger.warning(f"Robot {self.robot_id} requests POST fallback failed for {url}: {e}")
            raise
        except Exception as e:
            logger.warning(f"Robot {self.robot_id} requests POST fallback error for {url}: {e}")
            raise
    
    async def _get(self, path: str, silent_errors: Optional[list] = None, retries: int = 2) -> Dict[str, Any]:
        """
        GET请求（带重试机制）
        
        Args:
            path: API路径
            silent_errors: 不记录日志的错误状态码列表（如 [400, 404]）
            retries: 重试次数（默认2次）
        """
        url = f"{self.base_url}{path}"
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    logger.debug(f"Robot {self.robot_id} GET {url} (retry {attempt}/{retries})")
                else:
                    logger.debug(f"Robot {self.robot_id} GET {url}")
                
                # 每次请求都使用新的超时配置，确保连接成功
                # 根据网络环境自动调整超时时间
                network_detector = get_network_detector()
                timeouts = network_detector.get_timeouts()
                request_timeout = httpx.Timeout(
                    timeout=timeouts["total"],
                    connect=timeouts["connect"],
                    read=timeouts["read"]
                )
                
                # 优先使用临时客户端（避免连接池问题，特别是在VPN环境下）
                # 临时客户端每次都是新的连接，更可靠
                # 显式禁用代理，避免使用环境变量中的代理设置（代理可能不可用）
                # 使用 trust_env=False 来禁用环境变量中的代理设置
                async with httpx.AsyncClient(
                    timeout=request_timeout,
                    follow_redirects=True,
                    http2=False,
                    verify=False,
                    trust_env=False  # 禁用环境变量中的代理设置，直接连接机器人
                ) as temp_client:
                    response = await temp_client.get(url, timeout=request_timeout)
                
                response.raise_for_status()
                return response.json()
                
            except httpx.ConnectError as e:
                last_exception = e
                # 连接错误，记录详细信息（包括异常类型和详细信息）
                error_details = f"{type(e).__name__}: {str(e)}"
                if hasattr(e, 'request') and hasattr(e.request, 'url'):
                    error_details += f" (URL: {e.request.url})"
                
                # httpx失败，尝试使用requests作为fallback（VPN环境下更稳定）
                logger.warning(
                    f"Robot {self.robot_id} httpx connection failed to {url} (attempt {attempt + 1}/{retries + 1}): {error_details}. "
                    f"Trying requests fallback..."
                )
                try:
                    # 使用requests库作为fallback（同步，VPN环境下更稳定）
                    network_detector = get_network_detector()
                    timeouts = network_detector.get_timeouts()
                    return await self._get_with_requests_fallback(url, timeouts["total"])
                except Exception as fallback_error:
                    # requests fallback也失败，继续重试逻辑
                    if attempt < retries:
                        logger.warning(
                            f"Robot {self.robot_id} requests fallback also failed, will retry httpx (attempt {attempt + 1}/{retries + 1})"
                        )
                        await asyncio.sleep(timeouts["retry_delay"] * (attempt + 1))
                    else:
                        error_msg = f"Robot {self.robot_id} connection failed to {url} after {retries + 1} attempts (httpx and requests both failed): {error_details}"
                        logger.error(error_msg, exc_info=True)
                        logger.error(f"Requests fallback error: {fallback_error}")
                        logger.error(f"Diagnosis: Check if robot is accessible at {self.base_url}/index.html")
                        raise fallback_error
            except httpx.TimeoutException as e:
                last_exception = e
                # 超时错误，记录详细信息
                error_details = f"{type(e).__name__}: {str(e)}"
                if hasattr(e, 'request') and hasattr(e.request, 'url'):
                    error_details += f" (URL: {e.request.url})"
                
                # httpx超时，尝试使用requests作为fallback
                logger.warning(
                    f"Robot {self.robot_id} httpx timeout to {url} (attempt {attempt + 1}/{retries + 1}): {error_details}. "
                    f"Trying requests fallback..."
                )
                try:
                    # 使用requests库作为fallback
                    network_detector = get_network_detector()
                    timeouts = network_detector.get_timeouts()
                    return await self._get_with_requests_fallback(url, timeouts["total"])
                except Exception as fallback_error:
                    # requests fallback也失败，继续重试逻辑
                    if attempt < retries:
                        logger.warning(
                            f"Robot {self.robot_id} requests fallback also timed out, will retry httpx (attempt {attempt + 1}/{retries + 1})"
                        )
                        await asyncio.sleep(1.0 * (attempt + 1))
                    else:
                        error_msg = f"Robot {self.robot_id} request timeout to {url} after {retries + 1} attempts (httpx and requests both failed): {error_details}"
                        logger.error(error_msg, exc_info=True)
                        logger.error(f"Requests fallback error: {fallback_error}")
                        raise fallback_error
            except httpx.HTTPStatusError as e:
                # HTTP状态错误，不重试（除非是5xx错误）
                if silent_errors and e.response.status_code in silent_errors:
                    raise
                # 对于502 Bad Gateway等5xx错误，增加重试次数
                if e.response.status_code >= 500 and attempt < retries:
                    logger.warning(
                        f"Robot {self.robot_id} GET {path} server error {e.response.status_code} "
                        f"(attempt {attempt + 1}/{retries + 1}). Will retry..."
                    )
                    await asyncio.sleep(1.0 * (attempt + 1))  # VPN环境：从0.5秒增加到1秒
                    last_exception = e
                    continue
                logger.error(f"Robot {self.robot_id} GET {path} failed: {e}")
                raise
            except Exception as e:
                last_exception = e
                # 记录详细的异常信息
                error_details = f"{type(e).__name__}: {str(e)}"
                if attempt < retries:
                    logger.warning(
                        f"Robot {self.robot_id} GET {path} failed (attempt {attempt + 1}/{retries + 1}): {error_details}. "
                        f"Will retry..."
                    )
                    await asyncio.sleep(1.0 * (attempt + 1))  # VPN环境：从0.5秒增加到1秒
                else:
                    logger.error(f"Robot {self.robot_id} GET {path} failed after {retries + 1} attempts: {error_details}", exc_info=True)
                    raise
        
        # 如果所有重试都失败，抛出最后一个异常
        if last_exception:
            raise last_exception
    
    async def _post(self, path: str, data: Optional[Dict[str, Any]] = None, retries: int = 2) -> Dict[str, Any]:
        """POST请求（带重试机制）"""
        url = f"{self.base_url}{path}"
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                # 根据网络环境自动调整超时时间
                network_detector = get_network_detector()
                timeouts = network_detector.get_timeouts()
                request_timeout = httpx.Timeout(
                    timeout=timeouts["total"],
                    connect=timeouts["connect"],
                    read=timeouts["read"]
                )
                
                # 优先使用临时客户端（避免连接池问题，特别是在VPN环境下）
                # 临时客户端每次都是新的连接，更可靠
                # 显式禁用代理，避免使用环境变量中的代理设置（代理可能不可用）
                # 使用 trust_env=False 来禁用环境变量中的代理设置
                async with httpx.AsyncClient(
                    timeout=request_timeout,
                    follow_redirects=True,
                    http2=False,
                    verify=False,
                    trust_env=False  # 禁用环境变量中的代理设置，直接连接机器人
                ) as temp_client:
                    response = await temp_client.post(url, json=data, timeout=request_timeout)
                
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.ConnectError as e:
                last_exception = e
                # httpx失败，尝试使用requests作为fallback
                logger.warning(
                    f"Robot {self.robot_id} httpx POST connection failed to {url} (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Trying requests fallback..."
                )
                try:
                    # 使用requests库作为fallback
                    network_detector = get_network_detector()
                    timeouts = network_detector.get_timeouts()
                    return await self._post_with_requests_fallback(url, data, timeouts["total"])
                except Exception as fallback_error:
                    # requests fallback也失败，继续重试逻辑
                    if attempt < retries:
                        logger.warning(
                            f"Robot {self.robot_id} requests POST fallback also failed, will retry httpx (attempt {attempt + 1}/{retries + 1})"
                        )
                        await asyncio.sleep(timeouts["retry_delay"] * (attempt + 1))
                    else:
                        error_msg = f"Robot {self.robot_id} POST {path} connection failed after {retries + 1} attempts (httpx and requests both failed): {e}"
                        logger.error(error_msg)
                        logger.error(f"Requests fallback error: {fallback_error}")
                        raise fallback_error
            except httpx.TimeoutException as e:
                last_exception = e
                # httpx超时，尝试使用requests作为fallback
                logger.warning(
                    f"Robot {self.robot_id} httpx POST timeout to {url} (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Trying requests fallback..."
                )
                try:
                    # 使用requests库作为fallback
                    network_detector = get_network_detector()
                    timeouts = network_detector.get_timeouts()
                    return await self._post_with_requests_fallback(url, data, timeouts["total"])
                except Exception as fallback_error:
                    # requests fallback也失败，继续重试逻辑
                    if attempt < retries:
                        logger.warning(
                            f"Robot {self.robot_id} requests POST fallback also timed out, will retry httpx (attempt {attempt + 1}/{retries + 1})"
                        )
                        await asyncio.sleep(1.0 * (attempt + 1))
                    else:
                        error_msg = f"Robot {self.robot_id} POST {path} timeout after {retries + 1} attempts (httpx and requests both failed): {e}"
                        logger.error(error_msg)
                        logger.error(f"Requests fallback error: {fallback_error}")
                        raise fallback_error
            except httpx.HTTPStatusError as e:
                # HTTP状态错误，5xx错误可以重试
                if e.response.status_code >= 500 and attempt < retries:
                    logger.warning(f"Robot {self.robot_id} POST {path} server error {e.response.status_code} (attempt {attempt + 1}/{retries + 1}). Will retry...")
                    await asyncio.sleep(1.0 * (attempt + 1))  # VPN环境：从0.5秒增加到1秒
                    last_exception = e
                    continue
                
                # 尝试提取详细的错误信息
                error_detail = str(e)
                try:
                    if e.response is not None and e.response.content:
                        error_data = e.response.json()
                        if 'detail' in error_data:
                            error_detail = error_data['detail']
                        elif 'message' in error_data:
                            error_detail = error_data['message']
                except:
                    pass
                logger.error(f"Robot {self.robot_id} POST {path} failed: {error_detail}")
                # 创建一个包含详细错误信息的新异常
                new_exception = httpx.HTTPStatusError(
                    error_detail,
                    request=e.request,
                    response=e.response
                )
                # 添加detail属性以便后续访问
                if not hasattr(new_exception, 'detail'):
                    new_exception.detail = error_detail
                raise new_exception
            except Exception as e:
                last_exception = e
                if attempt < retries:
                    logger.warning(f"Robot {self.robot_id} POST {path} failed (attempt {attempt + 1}/{retries + 1}): {e}. Will retry...")
                    await asyncio.sleep(1.0 * (attempt + 1))  # VPN环境：从0.5秒增加到1秒
                else:
                    logger.error(f"Robot {self.robot_id} POST {path} failed after {retries + 1} attempts: {e}")
                    raise
        
        # 如果所有重试都失败，抛出最后一个异常
        if last_exception:
            raise last_exception
    
    async def _delete(self, path: str) -> bool:
        """DELETE请求"""
        url = f"{self.base_url}{path}"
        try:
            response = await self.client.delete(url)
            response.raise_for_status()
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Robot {self.robot_id} DELETE {path} failed: {e}")
            raise
    
    # ========== 状态获取 ==========
    
    async def get_pose(self) -> Pose:
        """获取机器人位置坐标"""
        try:
            data = await self._get("/api/core/slam/v1/localization/pose")
            logger.debug(f"Robot {self.robot_id} pose data: {data}")
            return Pose(**data)
        except KeyError as e:
            error_msg = f"Missing required field in pose data: {e}. Received data: {data}"
            logger.error(f"Failed to parse pose data for robot {self.robot_id}: {error_msg}")
            raise ValueError(error_msg) from e
        except TypeError as e:
            error_msg = f"Invalid data type in pose data: {e}. Received data: {data}"
            logger.error(f"Failed to parse pose data for robot {self.robot_id}: {error_msg}")
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to parse pose data: {e}. Received data: {data if 'data' in locals() else 'N/A'}"
            logger.error(f"Failed to parse pose data for robot {self.robot_id}: {error_msg}")
            raise
    
    async def get_speed(self) -> Speed:
        """获取机器人速度"""
        data = await self._get("/api/core/motion/v1/speed")
        return Speed(**data)
    
    async def get_power_status(self) -> PowerStatus:
        """获取电量状态"""
        data = await self._get("/api/core/system/v1/power/status")
        return PowerStatus(**data)
    
    async def get_health_status(self) -> HealthStatus:
        """获取设备健康状态"""
        data = await self._get("/api/core/system/v1/robot/health")
        return HealthStatus(**data)
    
    async def get_robot_info(self) -> RobotInfo:
        """获取设备信息"""
        data = await self._get("/api/core/system/v1/robot/info")
        return RobotInfo(**data)
    
    async def get_localization_quality(self) -> int:
        """获取定位质量"""
        data = await self._get("/api/core/slam/v1/localization/quality")
        return int(data) if isinstance(data, (int, float)) else data
    
    async def get_home_dock_pose(self) -> Optional[Pose]:
        """
        获取绑定的充电桩坐标
        
        Returns:
            充电桩位置，如果获取失败返回None
        """
        try:
            data = await self._get("/api/multi-floor/map/v1/homedocks/:current")
            if data and isinstance(data, dict):
                # 检查响应格式
                if "data" in data and isinstance(data["data"], dict):
                    pose_data = data["data"].get("pose")
                    if pose_data:
                        return Pose(**pose_data)
                # 如果data直接是pose数据
                elif "pose" in data:
                    return Pose(**data["pose"])
            return None
        except Exception as e:
            logger.debug(f"Failed to get home dock pose for robot {self.robot_id}: {e}")
            return None
    
    async def get_imu(self) -> Dict[str, Any]:
        """获取IMU信息"""
        return await self._get("/api/core/slam/v1/imu")
    
    async def get_odom_pose(self) -> Pose:
        """获取里程计位姿"""
        data = await self._get("/api/core/slam/v1/localization/odopose")
        return Pose(**data)
    
    async def get_laser_scan(self) -> LaserScan:
        """获取激光雷达数据"""
        data = await self._get("/api/core/system/v1/laserscan")
        return LaserScan(**data)
    
    # ========== 运动控制 ==========
    
    async def move_to(
        self,
        target: Pose,
        mode: int = 0,
        flags: Optional[list] = None,
        yaw: Optional[float] = None,
        acceptable_precision: float = 0.3,
        fail_retry_count: int = 0,
        speed_ratio: float = 1.0
    ) -> ActionState:
        """
        创建移动到目标点的运动行为
        
        Args:
            target: 目标位置
            mode: 导航模式（0:Free navigation, 1:Strict Track, 2:Track priority）
            flags: 标志列表（如：["precise", "with_yaw"]）
            yaw: 目标朝向
            acceptable_precision: 到达精度（米）
            fail_retry_count: 失败重试次数
            speed_ratio: 速度比例
        """
        payload = {
            "action_name": "slamtec.agent.actions.MoveToAction",
            "options": {
                "target": {
                    "x": target.x,
                    "y": target.y,
                    "z": target.z
                },
                "move_options": {
                    "mode": mode,
                    "flags": flags or [],
                    "yaw": target.yaw if yaw is None else yaw,
                    "acceptable_precision": acceptable_precision,
                    "fail_retry_count": fail_retry_count,
                    "speed_ratio": speed_ratio
                }
            }
        }
        data = await self._post("/api/core/motion/v1/actions", payload)
        return ActionState(**data)
    
    async def move_to_poi(
        self,
        poi_name: str,
        mode: int = 0,
        flags: Optional[list] = None,
        acceptable_precision: float = 0.5,
        fail_retry_count: int = 0
    ) -> ActionState:
        """
        通过POI的方式移动到点
        
        Args:
            poi_name: POI名称
            mode: 导航模式
            flags: 标志列表
            acceptable_precision: 到达精度
            fail_retry_count: 失败重试次数
        """
        payload = {
            "action_name": "slamtec.agent.actions.MultiFloorMoveAction",
            "options": {
                "target": {
                    "poi_name": poi_name
                },
                "move_options": {
                    "mode": mode,
                    "flags": flags or [],
                    "acceptable_precision": acceptable_precision,
                    "fail_retry_count": fail_retry_count
                }
            }
        }
        data = await self._post("/api/core/motion/v1/actions", payload)
        return ActionState(**data)
    
    async def go_home(self) -> ActionState:
        """回桩"""
        try:
            data = await self._post("/api/multi-floor/motion/v1/gohomeaction", {})
            # 记录详细的响应信息，特别是Hermes
            logger.info(f"Robot {self.robot_id} go-home API response: {data}")
            
            # 检查响应中是否包含action_id
            if not data.get("action_id"):
                logger.warning(f"Robot {self.robot_id} go-home response missing action_id: {data}")
                # 尝试从state中获取action_id
                if isinstance(data.get("state"), dict) and "action_id" in data.get("state", {}):
                    data["action_id"] = data["state"]["action_id"]
                    logger.info(f"Robot {self.robot_id} extracted action_id from state: {data['action_id']}")
            
            # 检查action状态，看是否立即失败
            if isinstance(data.get("state"), dict):
                state = data["state"]
                result_code = state.get("result")
                status_code = state.get("status")
                reason = state.get("reason", "")
                
                logger.info(
                    f"Robot {self.robot_id} go-home action state: "
                    f"result={result_code}, status={status_code}, reason={reason}"
                )
                
                # 如果action立即失败，记录详细信息
                if result_code == -1:
                    error_msg = f"回桩失败: {reason}" if reason else "回桩失败: 未知错误"
                    logger.error(f"Robot {self.robot_id} go-home failed immediately: {error_msg}")
                    raise Exception(error_msg)
            
            return ActionState(**data)
        except httpx.TimeoutException as e:
            logger.error(f"Robot {self.robot_id} go-home timeout: {e}")
            raise Exception(f"回桩请求超时: 机器人 {self.robot_id} 未在 {self.timeout} 秒内响应")
        except httpx.HTTPStatusError as e:
            logger.error(f"Robot {self.robot_id} go-home HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"回桩请求失败: HTTP {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"Robot {self.robot_id} go-home error: {e}", exc_info=True)
            raise
    
    async def cancel_current_action(self) -> bool:
        """取消当前任务"""
        return await self._delete("/api/core/motion/v1/actions/current")
    
    async def get_action_status(self, action_id: int) -> Optional[ActionState]:
        """
        查询action的状态
        
        使用API: GET /api/core/motion/v1/actions/{action_id}
        响应格式:
        {
            "action_id": 4526,
            "state": {
                "reason": "",
                "result": 0,  # 0:Success, -1:Failed, -2:Aborted
                "status": 4   # 0:NewBorn, 1:Working, 3:Paused, 4:Done
            }
        }
        
        Args:
            action_id: action的ID
            
        Returns:
            ActionState对象，如果action不存在或已清除则返回None
        """
        try:
            # 400和404错误表示action不存在或已清除，这是正常情况（action完成后会被清除）
            data = await self._get(f"/api/core/motion/v1/actions/{action_id}", silent_errors=[400, 404])
            # 确保响应数据格式正确（API返回的state字段包含status、result、reason）
            if data and "state" in data and isinstance(data["state"], dict):
                # state字段已存在，直接使用
                logger.debug(f"Robot {self.robot_id} action_id={action_id} status retrieved: state={data.get('state')}")
            return ActionState(**data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # action不存在（可能已完成并被清除）
                logger.debug(f"Robot {self.robot_id} action_id={action_id} not found (404), action may have been completed")
                return None
            elif e.response.status_code == 400:
                # action无效（可能已完成并被清除）
                logger.debug(f"Robot {self.robot_id} action_id={action_id} invalid (400), action may have been completed")
                return None
            # 其他HTTP错误，抛出异常
            raise
    
    async def get_current_action(self) -> Optional[ActionState]:
        """查询当前任务状态"""
        try:
            # 400和404错误表示没有当前任务，这是正常情况，不需要记录错误日志
            data = await self._get("/api/core/motion/v1/actions/current", silent_errors=[400, 404])
            return ActionState(**data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 如果没有当前任务，返回None
                logger.debug(f"Robot {self.robot_id} has no current action (404)")
                return None
            elif e.response.status_code == 400:
                # API返回400表示没有当前任务（Invalid Action Id）
                logger.debug(f"Robot {self.robot_id} has no current action (400)")
                return None
            raise
        except Exception as e:
            logger.warning(f"Failed to get current action for robot {self.robot_id}: {e}")
            return None
    
    # ========== 地图管理 ==========
    
    async def sync_map(self) -> bool:
        """同步地图"""
        try:
            await self._post("/api/multi-floor/map/v1/stcm/:sync", {})
            return True
        except Exception as e:
            logger.error(f"Sync map failed: {e}")
            return False
    
    async def get_map_explore(
        self,
        min_x: Optional[float] = None,
        min_y: Optional[float] = None,
        max_x: Optional[float] = None,
        max_y: Optional[float] = None
    ) -> bytes:
        """
        获取栅格地图（二进制字节流）
        
        Args:
            min_x, min_y, max_x, max_y: 地图范围（可选）
        """
        url = f"{self.base_url}/api/core/slam/v1/maps/explore"
        params = {}
        if min_x is not None:
            params["min_x"] = min_x
        if min_y is not None:
            params["min_y"] = min_y
        if max_x is not None:
            params["max_x"] = max_x
        if max_y is not None:
            params["max_y"] = max_y
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Get map failed: {e}")
            raise
    
    # ========== POI管理 ==========
    
    async def create_poi(self, poi_id: str, display_name: str) -> bool:
        """创建当前点POI"""
        payload = {
            "id": poi_id,
            "metadata": {
                "display_name": display_name
            }
        }
        result = await self._post("/api/core/artifact/v1/pois", payload)
        return result is True
    
    async def get_all_pois(self) -> list[POI]:
        """获取所有POI"""
        data = await self._get("/api/core/artifact/v1/pois")
        return [POI(**item) for item in data]
    
    async def get_virtual_walls(self) -> list[VirtualWall]:
        """获取所有虚拟墙"""
        try:
            logger.info(f"Fetching virtual walls from robot {self.robot_id} at {self.base_url}/api/core/artifact/v1/lines/walls")
            data = await self._get("/api/core/artifact/v1/lines/walls")
            logger.info(f"Robot {self.robot_id} at {self.base_url} virtual walls API returned {len(data) if isinstance(data, list) else 'non-list'} items")
            if not isinstance(data, list):
                logger.warning(f"Robot {self.robot_id} at {self.base_url} virtual walls API returned non-list data: {type(data)}")
                return []
            walls = [VirtualWall(**item) for item in data]
            logger.info(f"Robot {self.robot_id} at {self.base_url} successfully parsed {len(walls)} virtual walls")
            return walls
        except Exception as e:
            logger.error(f"Get virtual walls failed for robot {self.robot_id} at {self.base_url}: {e}", exc_info=True)
            raise
    
    async def get_restricted_areas(self) -> list[RestrictedArea]:
        """获取所有限行区域"""
        try:
            logger.info(f"Fetching restricted areas from robot {self.robot_id} at {self.base_url}/api/core/artifact/v1/rectangle-areas/restricted_area")
            data = await self._get("/api/core/artifact/v1/rectangle-areas/restricted_area")
            logger.info(f"Robot {self.robot_id} at {self.base_url} restricted areas API returned {len(data) if isinstance(data, list) else 'non-list'} items")
            if not isinstance(data, list):
                logger.warning(f"Robot {self.robot_id} at {self.base_url} restricted areas API returned non-list data: {type(data)}")
                return []
            areas = [RestrictedArea(**item) for item in data]
            logger.info(f"Robot {self.robot_id} at {self.base_url} successfully parsed {len(areas)} restricted areas")
            return areas
        except Exception as e:
            logger.error(f"Get restricted areas failed for robot {self.robot_id} at {self.base_url}: {e}", exc_info=True)
            raise
    
    async def update_poi(self, poi_id: str, display_name: str) -> bool:
        """
        更新POI的显示名称
        
        注意：如果底层API不支持直接更新，此方法会先删除旧POI再创建新POI
        这需要机器人当前位置与POI位置一致，因此可能不适用于所有场景
        
        Args:
            poi_id: POI ID
            display_name: 新的显示名称
            
        Returns:
            是否更新成功
        """
        # 尝试使用 PUT 方法更新（如果底层 API 支持）
        try:
            payload = {
                "id": poi_id,
                "metadata": {
                    "display_name": display_name
                }
            }
            # 尝试 PUT 方法
            url = f"{self.base_url}/api/core/artifact/v1/pois/{poi_id}"
            response = await self.client.put(url, json=payload)
            response.raise_for_status()
            return True
        except Exception as e:
            # 如果 PUT 不支持，尝试使用 POST 方法（某些 API 可能使用 POST 来更新）
            try:
                url = f"{self.base_url}/api/core/artifact/v1/pois/{poi_id}"
                payload = {
                    "id": poi_id,
                    "metadata": {
                        "display_name": display_name
                    }
                }
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                return True
            except Exception:
                # 如果都不支持，记录警告并返回 False
                logger.warning(f"Update POI not supported by API, may need to delete and recreate: {e}")
                return False

