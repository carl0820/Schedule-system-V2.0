"""
系统配置文件
"""
try:
    # Pydantic v1 (当前版本)
    from pydantic import BaseSettings
except ImportError:
    try:
        # Pydantic v2
        from pydantic_settings import BaseSettings
    except ImportError:
        # Fallback
        from pydantic import BaseModel as BaseSettings

from typing import Optional


class Settings(BaseSettings):
    """系统配置"""
    
    # 应用配置
    APP_NAME: str = "多机器人调度系统"
    APP_VERSION: str = "1.4.0"
    DEBUG: bool = False
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8092  # 改为8092，因为Windows保留了7992-8091端口范围
    
    # 数据库配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "robot_scheduler"
    
    # 地图配置
    MAP_RESOLUTION: float = 0.05  # 地图分辨率，单位：米/像素
    MAP_ORIGIN_X: float = 0.0
    MAP_ORIGIN_Y: float = 0.0
    
    # 路径规划配置
    PATH_PLANNER_ALGORITHM: str = "astar"  # astar, dijkstra
    PATH_SMOOTHING: bool = True
    
    # 碰撞避免配置
    COLLISION_PREDICTION_WINDOW: float = 3.0  # 预测时间窗口（秒）
    COLLISION_SAFETY_DISTANCE: float = 0.5  # 安全距离（米）
    COLLISION_DETECTION_FREQUENCY: float = 10.0  # 碰撞检测频率（Hz）
    
    # 机器人配置
    ROBOT_MAX_SPEED: float = 1.0  # 最大线速度（米/秒）
    ROBOT_MAX_ANGULAR_SPEED: float = 1.0  # 最大角速度（弧度/秒）
    ROBOT_MAX_ACCELERATION: float = 0.5  # 最大加速度（米/秒²）
    ROBOT_RADIUS: float = 0.3  # 机器人半径（米）
    ROBOT_ROTATION_RADIUS: float = 0.45  # 机器人旋转半径（米），单台需要900mm旋转空间
    ROBOT_DIAMETER: float = 0.6  # 机器人直径（米）
    ROBOT_ROTATION_DIAMETER: float = 0.9  # 机器人旋转直径（米）
    
    # 十字路口配置
    INTERSECTION_DETECTION_RADIUS: float = 2.0  # 十字路口检测半径（米）
    INTERSECTION_COORDINATION_DISTANCE: float = 3.0  # 十字路口协调距离（米）
    INTERSECTION_PRIORITY_TIMEOUT: float = 5.0  # 十字路口优先级超时（秒）
    
    # 长走廊配置
    CORRIDOR_DETECTION_WIDTH: float = 2.0  # 长走廊检测宽度阈值（米）
    CORRIDOR_DETECTION_LENGTH: float = 5.0  # 长走廊检测长度阈值（米）
    CORRIDOR_YIELD_DISTANCE: float = 2.0  # 长走廊让行距离（米）
    CORRIDOR_WAIT_POINT_DISTANCE: float = 1.5  # 长走廊等待点距离（米）
    
    # 任务调度配置
    TASK_MAX_RETRY_COUNT: int = 3
    TASK_TIMEOUT: float = 300.0  # 任务超时时间（秒）
    
    # 自动优先级计算配置
    PRIORITY_WAIT_TIME_THRESHOLD_1: float = 30.0  # 等待30秒后提升优先级
    PRIORITY_WAIT_TIME_THRESHOLD_2: float = 60.0  # 等待60秒后进一步提升
    PRIORITY_WAIT_TIME_THRESHOLD_3: float = 120.0  # 等待120秒后提升到最高
    PRIORITY_RETRY_THRESHOLD: int = 2  # 重试2次后提升优先级
    
    # WebSocket配置
    WS_MAX_CONNECTIONS: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

