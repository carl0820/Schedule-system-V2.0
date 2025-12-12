"""
系统监控API
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional
from app.services.config_manager import get_config_manager
from app.services.network_detector import get_network_detector, NetworkType
from app.services.robot_manager import get_robot_manager
from app.services.deadlock_monitor import get_deadlock_monitor

router = APIRouter()


@router.get("/status", response_model=dict)
async def get_system_status():
    """
    获取系统状态
    """
    return {
        "status": "running",
        "robots": 0,  # TODO: 从机器人管理器获取
        "tasks": 0,  # TODO: 从任务调度器获取
        "maps": 0  # TODO: 从地图管理器获取
    }


@router.get("/metrics", response_model=dict)
async def get_system_metrics():
    """
    获取系统性能指标
    """
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    
    return {
        "cpu_percent": process.cpu_percent(interval=0.1),
        "memory_mb": memory_info.rss / 1024 / 1024,
        "memory_percent": process.memory_percent()
    }


# ========== 配置管理API ==========

class DeadlockConfigUpdate(BaseModel):
    """死锁配置更新模型"""
    deadlock_threshold: Optional[float] = None
    narrow_passage_threshold: Optional[float] = None
    narrow_passage_backoff_distance: Optional[float] = None
    circular_wait_backoff_distance: Optional[float] = None
    mutual_blocking_backoff_distance: Optional[float] = None
    default_backoff_distance: Optional[float] = None
    backoff_speed_ratio: Optional[float] = None
    backoff_acceptable_precision: Optional[float] = None
    robot_stuck_threshold: Optional[float] = None
    robot_stuck_time_window: Optional[float] = None
    mutual_blocking_distance: Optional[float] = None
    narrow_passage_detection_distance: Optional[float] = None
    history_retention_time: Optional[float] = None


@router.get("/config/deadlock")
async def get_deadlock_config():
    """
    获取死锁配置
    """
    try:
        config_manager = get_config_manager()
        config = config_manager.get_deadlock_config()
        return {
            "success": True,
            "config": config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get deadlock config: {str(e)}")


@router.put("/config/deadlock")
async def update_deadlock_config(config_update: DeadlockConfigUpdate):
    """
    更新死锁配置
    """
    try:
        config_manager = get_config_manager()
        
        # 构建更新字典（只包含非None的字段）
        update_dict = {k: v for k, v in config_update.dict().items() if v is not None}
        
        if not update_dict:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        success = config_manager.update_deadlock_config(update_dict)
        
        if success:
            updated_config = config_manager.get_deadlock_config()
            return {
                "success": True,
                "message": "Configuration updated successfully",
                "config": updated_config
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update configuration")
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update deadlock config: {str(e)}")


@router.post("/config/deadlock/reset")
async def reset_deadlock_config():
    """
    重置死锁配置为默认值
    """
    try:
        config_manager = get_config_manager()
        success = config_manager.reset_to_default("deadlock")
        
        if success:
            default_config = config_manager.get_deadlock_config()
            return {
                "success": True,
                "message": "Configuration reset to default values",
                "config": default_config
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to reset configuration")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset deadlock config: {str(e)}")


# ========== 网络环境检测API ==========

@router.get("/network/status")
async def get_network_status():
    """
    获取网络环境状态
    """
    try:
        network_detector = get_network_detector()
        network_type = network_detector.get_network_type()
        timeouts = network_detector.get_timeouts()
        
        return {
            "success": True,
            "network_type": network_type.value,
            "average_latency_ms": network_detector.avg_latency,
            "timeouts": timeouts,
            "last_detection_time": network_detector.last_detection_time
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get network status: {str(e)}")


@router.post("/network/detect")
async def detect_network_environment(
    force: bool = Query(False, description="是否强制重新检测（忽略缓存）")
):
    """
    手动触发网络环境检测
    
    Args:
        force: 是否强制重新检测（忽略缓存）
    """
    try:
        network_detector = get_network_detector()
        robot_manager = get_robot_manager()
        
        # 如果强制检测，清除缓存
        if force:
            network_detector.last_detection_time = None
        
        # 获取已注册的机器人URL作为测试地址
        test_urls = []
        for robot_id, agent in robot_manager.robots.items():
            if agent and agent.base_url:
                test_url = f"{agent.base_url}/api/core/system/v1/robot/health"
                test_urls.append(test_url)
                if len(test_urls) >= 3:
                    break
        
        if not test_urls:
            raise HTTPException(
                status_code=400,
                detail="No robots registered. Please register at least one robot first."
            )
        
        network_type, latency = await network_detector.detect_network_environment(test_urls)
        timeouts = network_detector.get_timeouts()
        
        return {
            "success": True,
            "message": "Network environment detected successfully",
            "network_type": network_type.value,
            "average_latency_ms": latency,
            "timeouts": timeouts
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to detect network environment: {str(e)}")


@router.put("/network/type")
async def set_network_type(
    network_type: str = Query(..., description="网络类型: 'direct' 或 'vpn'")
):
    """
    手动设置网络类型
    
    Args:
        network_type: 网络类型 ('direct' 或 'vpn')
    """
    try:
        network_detector = get_network_detector()
        
        if network_type.lower() == "direct":
            network_detector.set_network_type(NetworkType.DIRECT)
        elif network_type.lower() == "vpn":
            network_detector.set_network_type(NetworkType.VPN)
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid network type. Must be 'direct' or 'vpn'"
            )
        
        timeouts = network_detector.get_timeouts()
        
        return {
            "success": True,
            "message": f"Network type set to {network_type}",
            "network_type": network_detector.get_network_type().value,
            "timeouts": timeouts
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set network type: {str(e)}")


# ========== 死锁监控API ==========

@router.get("/deadlock/stats")
async def get_deadlock_stats():
    """
    获取死锁统计信息

    Returns:
        包含死锁检测、解除成功率、平均解除时间等统计信息
    """
    try:
        deadlock_monitor = get_deadlock_monitor()
        summary = deadlock_monitor.get_summary()

        return {
            "success": True,
            "stats": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get deadlock stats: {str(e)}")


@router.get("/deadlock/alerts")
async def get_deadlock_alerts():
    """
    获取死锁告警信息

    Returns:
        当前的死锁告警列表（高频率、高失败率、机器人频繁参与等）
    """
    try:
        deadlock_monitor = get_deadlock_monitor()
        alerts = deadlock_monitor.get_alerts()

        return {
            "success": True,
            "alert_count": len(alerts),
            "alerts": alerts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get deadlock alerts: {str(e)}")


@router.post("/deadlock/stats/reset")
async def reset_deadlock_stats():
    """
    重置死锁统计信息

    注意：此操作会清除所有历史统计数据
    """
    try:
        deadlock_monitor = get_deadlock_monitor()
        deadlock_monitor.reset_stats()

        return {
            "success": True,
            "message": "Deadlock statistics reset successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset deadlock stats: {str(e)}")

