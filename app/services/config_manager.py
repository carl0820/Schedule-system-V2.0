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
                "deadlock_threshold": 10.0,  # 死锁判定阈值（秒，通用）
                "narrow_passage_deadlock_threshold": 3.0,  # 窄道死锁判定阈值（秒）
                "circular_wait_deadlock_threshold": 10.0,  # 循环等待死锁判定阈值（秒）
                "mutual_blocking_deadlock_threshold": 1.5,  # 相互阻塞死锁判定阈值（秒，降低以更快响应）
                "narrow_passage_threshold": 1.0,  # 窄道阈值（米）
                "narrow_passage_backoff_distance": 1.0,  # 窄道死锁后退距离（米）
                "circular_wait_backoff_distance": 1.5,  # 循环等待死锁后退距离（米）
                "mutual_blocking_backoff_distance": 1.0,  # 相互阻塞死锁后退距离（米）
                "default_backoff_distance": 1.0,  # 默认后退距离（米）
                "backoff_speed_ratio": 0.5,  # 后退速度比例
                "backoff_acceptable_precision": 0.2,  # 后退到达精度（米）
                "robot_stuck_threshold": 0.1,  # 机器人卡住判定阈值（米）
                "robot_stuck_time_window": 10.0,  # 机器人卡住时间窗口（秒）
                "mutual_blocking_distance": 1.0,  # 相互阻塞判定距离（米）
                "narrow_passage_detection_distance": 2.0,  # 窄道检测距离（米）
                "history_retention_time": 60.0,  # 死锁历史保留时间（秒）
                "waiting_point_min_distance": 2.0,  # 等待点最小距离（米）
                "waiting_point_max_distance": 5.0,  # 等待点最大距离（米）
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
                    
                    # 范围检查
                    if key.endswith("_threshold") or key.endswith("_distance") or key.endswith("_time_window"):
                        if value <= 0:
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

