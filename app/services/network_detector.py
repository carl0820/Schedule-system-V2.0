"""
网络环境检测器
自动检测网络环境（VPN/直连）并调整超时设置
"""
import asyncio
import logging
import time
from typing import Optional, Tuple
import httpx
from enum import Enum

logger = logging.getLogger(__name__)


class NetworkType(Enum):
    """网络类型"""
    DIRECT = "direct"  # 直连
    VPN = "vpn"  # VPN
    UNKNOWN = "unknown"  # 未知


class NetworkDetector:
    """网络环境检测器"""
    
    def __init__(self):
        self.network_type: NetworkType = NetworkType.UNKNOWN
        self.avg_latency: float = 0.0
        self.last_detection_time: Optional[float] = None
        self.detection_interval: float = 300.0  # 5分钟检测一次
        
        # 延迟阈值（毫秒）
        self.DIRECT_LATENCY_THRESHOLD = 50.0  # 直连通常 < 50ms
        self.VPN_LATENCY_THRESHOLD = 100.0  # VPN通常 > 100ms
        
        # 默认超时配置（直连环境）
        self.default_timeouts = {
            "connect": 20.0,
            "read": 15.0,
            "total": 15.0,
            "pose": 8.0,
            "power": 8.0,
            "speed": 5.0,
            "health": 5.0,
            "retry_delay": 0.5
        }
        
        # VPN环境超时配置
        self.vpn_timeouts = {
            "connect": 30.0,
            "read": 20.0,
            "total": 20.0,
            "pose": 12.0,
            "power": 12.0,
            "speed": 8.0,
            "health": 8.0,
            "retry_delay": 1.0
        }
    
    async def detect_network_environment(self, test_urls: Optional[list] = None) -> Tuple[NetworkType, float]:
        """
        检测网络环境
        
        Args:
            test_urls: 测试URL列表，如果为None则使用默认的机器人地址
            
        Returns:
            (网络类型, 平均延迟ms)
        """
        # 如果最近检测过，直接返回缓存结果
        current_time = time.time()
        if (self.last_detection_time and 
            current_time - self.last_detection_time < self.detection_interval and
            self.network_type != NetworkType.UNKNOWN):
            logger.debug(f"Using cached network detection: {self.network_type.value}, latency: {self.avg_latency:.2f}ms")
            return self.network_type, self.avg_latency
        
        # 如果没有提供测试URL，尝试从环境变量或配置获取
        if not test_urls:
            # 尝试检测常见的机器人地址（如果系统中有注册的机器人）
            test_urls = []
            # 这里可以添加默认的测试地址，或者从robot_manager获取
        
        # 如果没有测试URL，使用默认的延迟假设
        if not test_urls:
            logger.warning("No test URLs provided, using default network type (DIRECT)")
            self.network_type = NetworkType.DIRECT
            self.avg_latency = 20.0  # 假设直连延迟
            self.last_detection_time = current_time
            return self.network_type, self.avg_latency
        
        # 测试多个URL，取平均延迟
        latencies = []
        for url in test_urls:
            try:
                latency = await self._measure_latency(url)
                if latency:
                    latencies.append(latency)
            except Exception as e:
                logger.debug(f"Failed to measure latency for {url}: {e}")
                continue
        
        if not latencies:
            logger.warning("Failed to measure latency for all URLs, using default network type (DIRECT)")
            self.network_type = NetworkType.DIRECT
            self.avg_latency = 20.0
            self.last_detection_time = current_time
            return self.network_type, self.avg_latency
        
        # 计算平均延迟
        self.avg_latency = sum(latencies) / len(latencies)
        
        # 根据延迟判断网络类型
        if self.avg_latency < self.DIRECT_LATENCY_THRESHOLD:
            self.network_type = NetworkType.DIRECT
        elif self.avg_latency > self.VPN_LATENCY_THRESHOLD:
            self.network_type = NetworkType.VPN
        else:
            # 中间值，根据其他因素判断（可以扩展）
            self.network_type = NetworkType.VPN  # 保守起见，假设是VPN
        
        self.last_detection_time = current_time
        
        logger.info(
            f"Network environment detected: {self.network_type.value}, "
            f"average latency: {self.avg_latency:.2f}ms"
        )
        
        return self.network_type, self.avg_latency
    
    async def _measure_latency(self, url: str, timeout: float = 3.0) -> Optional[float]:
        """
        测量URL的延迟
        
        Args:
            url: 要测试的URL
            timeout: 超时时间
            
        Returns:
            延迟（毫秒），如果失败返回None
        """
        try:
            start_time = time.time()
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                # 尝试HEAD请求（更快）
                try:
                    response = await client.head(url, follow_redirects=True)
                    if response.status_code < 500:
                        latency = (time.time() - start_time) * 1000  # 转换为毫秒
                        return latency
                except:
                    # 如果HEAD失败，尝试GET
                    pass
                
                # 尝试GET请求
                start_time = time.time()
                response = await client.get(url, follow_redirects=True)
                if response.status_code < 500:
                    latency = (time.time() - start_time) * 1000
                    return latency
        except Exception as e:
            logger.debug(f"Latency measurement failed for {url}: {e}")
            return None
        
        return None
    
    def get_timeouts(self) -> dict:
        """
        根据当前网络环境获取超时配置
        
        Returns:
            超时配置字典
        """
        if self.network_type == NetworkType.VPN:
            logger.debug("Using VPN timeout configuration")
            return self.vpn_timeouts.copy()
        elif self.network_type == NetworkType.UNKNOWN:
            # 如果网络类型未知，默认使用VPN配置（更保守，适合VPN环境）
            logger.debug("Network type is unknown, using VPN timeout configuration (conservative)")
            return self.vpn_timeouts.copy()
        else:
            logger.debug("Using direct connection timeout configuration")
            return self.default_timeouts.copy()
    
    def set_network_type(self, network_type: NetworkType):
        """
        手动设置网络类型（用于配置或环境变量）
        
        Args:
            network_type: 网络类型
        """
        self.network_type = network_type
        logger.info(f"Network type manually set to: {network_type.value}")
    
    def get_network_type(self) -> NetworkType:
        """获取当前网络类型"""
        return self.network_type


# 全局单例
_network_detector: Optional[NetworkDetector] = None


def get_network_detector() -> NetworkDetector:
    """获取网络检测器单例"""
    global _network_detector
    if _network_detector is None:
        _network_detector = NetworkDetector()
        
        # 检查环境变量
        import os
        network_env = os.getenv("NETWORK_TYPE", "").lower()
        if network_env == "vpn":
            _network_detector.set_network_type(NetworkType.VPN)
            logger.info("Network type set to VPN via environment variable")
        elif network_env == "direct":
            _network_detector.set_network_type(NetworkType.DIRECT)
            logger.info("Network type set to DIRECT via environment variable")
    
    return _network_detector

