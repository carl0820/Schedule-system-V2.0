"""
配置管理模块 - 管理运行时配置参数
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_FILE = Path("data/runtime_config.json")


class ConfigManager:
    """配置管理器，管理运行时配置参数"""
    
    def __init__(self, config_file: Path = CONFIG_FILE):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """从文件加载配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                logger.info(f"Loaded config from {self.config_file}")
            else:
                # 使用默认配置
                self._config = self._get_default_config()
                self._save_config()
                logger.info(f"Created default config file: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._config = self._get_default_config()
    
    def _save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved config to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "deadlock": {
                # ========== 死锁检测阈值（针对思岚底盘优化） ==========
                "deadlock_threshold": 10.0,  # 死锁判定阈值（秒，通用）
                "narrow_passage_deadlock_threshold": 2.5,  # 窄道死锁判定阈值（秒）- 优化：从3.0降低到2.5，更快响应
                "circular_wait_deadlock_threshold": 6.0,  # 循环等待死锁判定阈值（秒）- 优化：从10.0降低到6.0，提高响应速度
                "mutual_blocking_deadlock_threshold": 1.5,  # 相互阻塞死锁判定阈值（秒）- 保持1.5秒，快速响应

                # ========== 距离和避让参数（针对思岚底盘调优） ==========
                "narrow_passage_threshold": 1.0,  # 窄道阈值（米）
                "narrow_passage_backoff_distance": 1.5,  # 窄道死锁后退距离（米）- 优化：从1.0增加到1.5，确保足够距离
                "circular_wait_backoff_distance": 2.0,  # 循环等待死锁后退距离（米）- 优化：从1.5增加到2.0，确保解锁
                "mutual_blocking_backoff_distance": 1.5,  # 相互阻塞死锁后退距离（米）- 优化：从1.0增加到1.5
                "default_backoff_distance": 1.5,  # 默认后退距离（米）- 优化：从1.0增加到1.5
                "backoff_speed_ratio": 0.5,  # 后退速度比例
                "backoff_acceptable_precision": 0.3,  # 后退到达精度（米）- 优化：从0.2放宽到0.3，避免过于严格

                # ========== 卡住检测参数 ==========
                "robot_stuck_threshold": 0.15,  # 机器人卡住判定阈值（米）- 优化：从0.1放宽到0.15，减少误判
                "robot_stuck_time_window": 8.0,  # 机器人卡住时间窗口（秒）- 优化：从10.0降低到8.0，更快检测

                # ========== 距离检测参数 ==========
                "mutual_blocking_distance": 1.5,  # 相互阻塞判定距离（米）- 优化：从1.0增加到1.5，提前检测
                "narrow_passage_detection_distance": 2.5,  # 窄道检测距离（米）- 优化：从2.0增加到2.5，提前预警

                # ========== 历史和等待点 ==========
                "history_retention_time": 60.0,  # 死锁历史保留时间（秒）
                "waiting_point_min_distance": 2.0,  # 等待点最小距离（米）
                "waiting_point_max_distance": 6.0,  # 等待点最大距离（米）- 优化：从5.0增加到6.0，扩大搜索范围
                "waiting_point_search_step": 0.5,  # 等待点搜索步长（米）- 新增：用于等待点计算
                "waiting_point_safety_margin": 0.8,  # 等待点安全裕度（米）- 新增：确保等待点足够安全

                # ========== 预定义等待点 ==========
                "predefined_waiting_points": [],  # 预定义等待点列表 [{"x": float, "y": float, "z": float, "yaw": float, "name": str}]
                "use_predefined_waiting_points": True,  # 是否优先使用预定义等待点
                
                # ========== POI等待点配置 ==========
                "poi_waiting_points": [],  # POI等待点名称列表（从机器人POI中选择，例如：["等待点1", "等待点2"]）
                "use_poi_waiting_points": True,  # 是否优先使用POI等待点

                # ========== 区域锁（针对思岚底盘的通道管理） ==========
                "area_lock_enabled": True,  # 是否启用区域锁
                "area_lock_timeout": 25.0,  # 区域锁超时时间（秒）- 优化：从30.0降低到25.0，避免长时间占用
                "area_lock_detection_radius": 3.5,  # 区域锁检测半径（米）- 优化：从3.0增加到3.5，提前预留

                # ========== 新增：思岚底盘特定参数 ==========
                "slamware_action_timeout": 120.0,  # 思岚底盘动作超时（秒）- 新增：超过此时间认为动作失败
                "slamware_recovery_enabled": True,  # 是否启用思岚底盘自动恢复（新增）
                "slamware_recovery_max_attempts": 2,  # 思岚底盘恢复最大尝试次数（新增）

                "updated_at": datetime.now().isoformat()
            },
            "task_completion": {
                # ========== 任务完成后的行为配置 ==========
                "auto_go_home_on_blocking": False,  # 完成任务后如果阻塞其他机器人是否自动回桩（默认禁用）
                "auto_go_home_on_cancel": True,  # 取消任务时是否自动回桩（默认启用，保持原有行为）
                "auto_go_home_on_avoidance_fail": True,  # 避让失败时是否自动回桩（默认启用，保持原有行为）
                "updated_at": datetime.now().isoformat()
            },
            "task_execution": {
                # ========== 任务执行超时配置 ==========
                "task_timeout_enabled": True,  # 是否启用任务超时检测
                "task_timeout_seconds": 300,  # 任务执行超时时间（秒，默认5分钟）
                "multi_action_timeout_seconds": 600,  # 多动作任务超时时间（秒，默认10分钟）
                "updated_at": datetime.now().isoformat()
            },
            "updated_at": datetime.now().isoformat()
        }
    
    def get_deadlock_config(self) -> Dict[str, Any]:
        """
        获取死锁配置

        Returns:
            死锁配置字典
        """
        if "deadlock" not in self._config:
            self._config["deadlock"] = self._get_default_config()["deadlock"]
        return self._config["deadlock"].copy()

    def get_task_completion_config(self) -> Dict[str, Any]:
        """
        获取任务完成配置

        Returns:
            任务完成配置字典
        """
        if "task_completion" not in self._config:
            self._config["task_completion"] = self._get_default_config()["task_completion"]
        return self._config["task_completion"].copy()

    def get_task_execution_config(self) -> Dict[str, Any]:
        """
        获取任务执行配置

        Returns:
            任务执行配置字典
        """
        if "task_execution" not in self._config:
            self._config["task_execution"] = self._get_default_config()["task_execution"]
        return self._config["task_execution"].copy()
    
    def update_deadlock_config(self, config: Dict[str, Any]) -> bool:
        """
        更新死锁配置
        
        Args:
            config: 要更新的配置字典（只包含要更新的字段）
        
        Returns:
            是否更新成功
        """
        try:
            if "deadlock" not in self._config:
                self._config["deadlock"] = self._get_default_config()["deadlock"]
            
            # 验证配置值
            default_config = self._get_default_config()["deadlock"]
            for key, value in config.items():
                if key in default_config:
                    # 类型检查
                    if isinstance(default_config[key], float):
                        value = float(value)
                    elif isinstance(default_config[key], int):
                        value = int(value)
                    elif isinstance(default_config[key], bool):
                        value = bool(value)
                    elif isinstance(default_config[key], list):
                        # 列表类型（如 poi_waiting_points），直接使用
                        if not isinstance(value, list):
                            raise ValueError(f"{key} must be a list")
                        value = value
                    
                    # 范围检查
                    if key.endswith("_threshold") or key.endswith("_distance") or key.endswith("_time_window"):
                        if isinstance(value, (int, float)) and value <= 0:
                            raise ValueError(f"{key} must be positive")
                    
                    if key == "backoff_speed_ratio":
                        if not 0 < value <= 1.0:
                            raise ValueError("backoff_speed_ratio must be between 0 and 1")
                    
                    self._config["deadlock"][key] = value
                else:
                    logger.warning(f"Unknown config key: {key}")
            
            # 更新更新时间
            self._config["deadlock"]["updated_at"] = datetime.now().isoformat()
            self._config["updated_at"] = datetime.now().isoformat()
            
            # 保存配置
            self._save_config()
            
            logger.info(f"Updated deadlock config: {config}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update deadlock config: {e}")
            return False
    
    def get_config(self, section: Optional[str] = None) -> Dict[str, Any]:
        """
        获取配置
        
        Args:
            section: 配置节名称（如 "deadlock"），None表示获取全部配置
        
        Returns:
            配置字典
        """
        if section:
            return self._config.get(section, {}).copy()
        return self._config.copy()
    
    def reset_to_default(self, section: Optional[str] = None) -> bool:
        """
        重置配置为默认值
        
        Args:
            section: 配置节名称（如 "deadlock"），None表示重置全部配置
        
        Returns:
            是否重置成功
        """
        try:
            if section:
                if section in self._get_default_config():
                    self._config[section] = self._get_default_config()[section].copy()
                    self._config[section]["updated_at"] = datetime.now().isoformat()
                else:
                    logger.warning(f"Unknown section: {section}")
                    return False
            else:
                self._config = self._get_default_config()
            
            self._save_config()
            logger.info(f"Reset config section: {section or 'all'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset config: {e}")
            return False


# 全局配置管理器实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

