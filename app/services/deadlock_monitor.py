"""
死锁监控模块 - 统计和监控死锁情况
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class DeadlockStats:
    """死锁统计信息"""
    # 总体统计
    total_detections: int = 0  # 总检测次数
    total_resolutions: int = 0  # 总解除次数
    total_failures: int = 0  # 总失败次数

    # 按类型统计
    by_type: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {
        "detections": 0,
        "resolutions": 0,
        "failures": 0,
        "total_duration": 0.0,
        "max_duration": 0.0
    }))

    # 按机器人统计
    by_robot: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {
        "involvement_count": 0,  # 参与死锁次数
        "avoidance_count": 0,  # 被选中避让次数
        "last_involvement": None  # 最后一次参与时间
    }))

    # 时间统计
    avg_resolution_time: float = 0.0  # 平均解除时间（秒）
    max_resolution_time: float = 0.0  # 最大解除时间（秒）
    min_resolution_time: float = float('inf')  # 最小解除时间（秒）

    # 最近统计（最近1小时）
    recent_detections_1h: int = 0
    recent_resolutions_1h: int = 0
    recent_failures_1h: int = 0

    # 统计开始时间
    start_time: datetime = field(default_factory=datetime.now)
    last_update: datetime = field(default_factory=datetime.now)


class DeadlockMonitor:
    """死锁监控器"""

    def __init__(self):
        """初始化死锁监控器"""
        self.stats = DeadlockStats()
        self.recent_events: List[Dict] = []  # 最近的死锁事件
        self.max_recent_events = 100  # 保留最近100个事件

    def record_detection(self, deadlock_type: str, robot_ids: List[str], duration: float = 0.0):
        """
        记录死锁检测

        Args:
            deadlock_type: 死锁类型
            robot_ids: 涉及的机器人ID列表
            duration: 死锁持续时间（秒）
        """
        now = datetime.now()
        self.stats.total_detections += 1
        self.stats.last_update = now

        # 按类型统计
        if deadlock_type not in self.stats.by_type:
            self.stats.by_type[deadlock_type] = {
                "detections": 0,
                "resolutions": 0,
                "failures": 0,
                "total_duration": 0.0,
                "max_duration": 0.0
            }

        self.stats.by_type[deadlock_type]["detections"] += 1
        self.stats.by_type[deadlock_type]["total_duration"] += duration
        self.stats.by_type[deadlock_type]["max_duration"] = max(
            self.stats.by_type[deadlock_type]["max_duration"],
            duration
        )

        # 按机器人统计
        for robot_id in robot_ids:
            if robot_id not in self.stats.by_robot:
                self.stats.by_robot[robot_id] = {
                    "involvement_count": 0,
                    "avoidance_count": 0,
                    "last_involvement": None
                }
            self.stats.by_robot[robot_id]["involvement_count"] += 1
            self.stats.by_robot[robot_id]["last_involvement"] = now.isoformat()

        # 记录事件
        event = {
            "type": "detection",
            "deadlock_type": deadlock_type,
            "robot_ids": robot_ids,
            "duration": duration,
            "timestamp": now.isoformat()
        }
        self.recent_events.append(event)

        # 清理旧事件
        if len(self.recent_events) > self.max_recent_events:
            self.recent_events = self.recent_events[-self.max_recent_events:]

        # 更新最近1小时统计
        self._update_recent_stats()

    def record_resolution(
        self,
        deadlock_type: str,
        robot_ids: List[str],
        duration: float,
        success: bool,
        avoidance_robots: Optional[List[str]] = None
    ):
        """
        记录死锁解除尝试

        Args:
            deadlock_type: 死锁类型
            robot_ids: 涉及的机器人ID列表
            duration: 死锁持续时间（秒）
            success: 是否成功解除
            avoidance_robots: 被选中避让的机器人ID列表
        """
        now = datetime.now()
        self.stats.last_update = now

        if success:
            self.stats.total_resolutions += 1
            if deadlock_type in self.stats.by_type:
                self.stats.by_type[deadlock_type]["resolutions"] += 1

            # 更新解除时间统计
            self.stats.avg_resolution_time = (
                (self.stats.avg_resolution_time * (self.stats.total_resolutions - 1) + duration)
                / self.stats.total_resolutions
            )
            self.stats.max_resolution_time = max(self.stats.max_resolution_time, duration)
            self.stats.min_resolution_time = min(self.stats.min_resolution_time, duration)
        else:
            self.stats.total_failures += 1
            if deadlock_type in self.stats.by_type:
                self.stats.by_type[deadlock_type]["failures"] += 1

        # 记录避让机器人
        if avoidance_robots:
            for robot_id in avoidance_robots:
                if robot_id in self.stats.by_robot:
                    self.stats.by_robot[robot_id]["avoidance_count"] += 1

        # 记录事件
        event = {
            "type": "resolution",
            "deadlock_type": deadlock_type,
            "robot_ids": robot_ids,
            "duration": duration,
            "success": success,
            "avoidance_robots": avoidance_robots or [],
            "timestamp": now.isoformat()
        }
        self.recent_events.append(event)

        # 清理旧事件
        if len(self.recent_events) > self.max_recent_events:
            self.recent_events = self.recent_events[-self.max_recent_events:]

        # 更新最近1小时统计
        self._update_recent_stats()

    def _update_recent_stats(self):
        """更新最近1小时统计"""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        recent_detections = 0
        recent_resolutions = 0
        recent_failures = 0

        for event in self.recent_events:
            try:
                event_time = datetime.fromisoformat(event["timestamp"])
                if event_time > one_hour_ago:
                    if event["type"] == "detection":
                        recent_detections += 1
                    elif event["type"] == "resolution":
                        if event.get("success"):
                            recent_resolutions += 1
                        else:
                            recent_failures += 1
            except Exception:
                continue

        self.stats.recent_detections_1h = recent_detections
        self.stats.recent_resolutions_1h = recent_resolutions
        self.stats.recent_failures_1h = recent_failures

    def get_summary(self) -> Dict:
        """
        获取统计摘要

        Returns:
            统计摘要字典
        """
        # 更新最近统计
        self._update_recent_stats()

        # 计算成功率
        success_rate = 0.0
        if self.stats.total_detections > 0:
            success_rate = (self.stats.total_resolutions / self.stats.total_detections) * 100

        # 找出最频繁参与死锁的机器人（前5名）
        top_robots = sorted(
            self.stats.by_robot.items(),
            key=lambda x: x[1]["involvement_count"],
            reverse=True
        )[:5]

        summary = {
            "overall": {
                "total_detections": self.stats.total_detections,
                "total_resolutions": self.stats.total_resolutions,
                "total_failures": self.stats.total_failures,
                "success_rate": f"{success_rate:.1f}%",
                "avg_resolution_time": f"{self.stats.avg_resolution_time:.2f}s",
                "max_resolution_time": f"{self.stats.max_resolution_time:.2f}s",
                "min_resolution_time": f"{self.stats.min_resolution_time:.2f}s" if self.stats.min_resolution_time != float('inf') else "N/A"
            },
            "recent_1h": {
                "detections": self.stats.recent_detections_1h,
                "resolutions": self.stats.recent_resolutions_1h,
                "failures": self.stats.recent_failures_1h
            },
            "by_type": {
                deadlock_type: {
                    "detections": type_stats["detections"],
                    "resolutions": type_stats["resolutions"],
                    "failures": type_stats["failures"],
                    "success_rate": f"{(type_stats['resolutions'] / type_stats['detections'] * 100) if type_stats['detections'] > 0 else 0:.1f}%",
                    "avg_duration": f"{(type_stats['total_duration'] / type_stats['detections']) if type_stats['detections'] > 0 else 0:.2f}s",
                    "max_duration": f"{type_stats['max_duration']:.2f}s"
                }
                for deadlock_type, type_stats in self.stats.by_type.items()
            },
            "top_robots": [
                {
                    "robot_id": robot_id,
                    "involvement_count": robot_stats["involvement_count"],
                    "avoidance_count": robot_stats["avoidance_count"],
                    "last_involvement": robot_stats["last_involvement"]
                }
                for robot_id, robot_stats in top_robots
            ],
            "monitoring_period": {
                "start_time": self.stats.start_time.isoformat(),
                "last_update": self.stats.last_update.isoformat(),
                "duration_hours": (self.stats.last_update - self.stats.start_time).total_seconds() / 3600
            }
        }

        return summary

    def get_alerts(self) -> List[Dict]:
        """
        获取告警信息

        Returns:
            告警列表
        """
        alerts = []

        # 检查死锁频率（最近1小时检测超过10次）
        if self.stats.recent_detections_1h > 10:
            alerts.append({
                "level": "WARNING",
                "type": "high_frequency",
                "message": f"High deadlock detection frequency: {self.stats.recent_detections_1h} detections in the last hour",
                "timestamp": datetime.now().isoformat()
            })

        # 检查失败率（最近1小时失败率超过30%）
        if self.stats.recent_detections_1h > 0:
            recent_failure_rate = (self.stats.recent_failures_1h / self.stats.recent_detections_1h) * 100
            if recent_failure_rate > 30:
                alerts.append({
                    "level": "CRITICAL",
                    "type": "high_failure_rate",
                    "message": f"High deadlock resolution failure rate: {recent_failure_rate:.1f}% in the last hour",
                    "timestamp": datetime.now().isoformat()
                })

        # 检查单个机器人频繁参与死锁（最近1小时参与超过5次）
        one_hour_ago = datetime.now() - timedelta(hours=1)
        for robot_id, robot_stats in self.stats.by_robot.items():
            if robot_stats["last_involvement"]:
                try:
                    last_time = datetime.fromisoformat(robot_stats["last_involvement"])
                    if last_time > one_hour_ago:
                        # 统计最近1小时该机器人参与的死锁次数
                        recent_count = sum(
                            1 for event in self.recent_events
                            if event.get("type") == "detection" and
                            robot_id in event.get("robot_ids", []) and
                            datetime.fromisoformat(event["timestamp"]) > one_hour_ago
                        )
                        if recent_count >= 5:
                            alerts.append({
                                "level": "WARNING",
                                "type": "robot_frequent_deadlock",
                                "robot_id": robot_id,
                                "message": f"Robot {robot_id} involved in {recent_count} deadlocks in the last hour. Check robot health.",
                                "timestamp": datetime.now().isoformat()
                            })
                except Exception:
                    continue

        return alerts

    def reset_stats(self):
        """重置统计信息"""
        self.stats = DeadlockStats()
        self.recent_events = []
        logger.info("Deadlock statistics reset")


# 全局监控器实例
_monitor_instance: Optional[DeadlockMonitor] = None


def get_deadlock_monitor() -> DeadlockMonitor:
    """
    获取死锁监控器单例

    Returns:
        DeadlockMonitor实例
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = DeadlockMonitor()
    return _monitor_instance
