"""
地图管理模块
"""
import struct
import logging
import math
import json
import uuid
import gzip
from pathlib import Path
from typing import Tuple, Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime
from config import settings
from app.models.map import MapInfo

# 尝试导入 numpy，如果没有则使用 Python 列表
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger(__name__)
if not HAS_NUMPY:
    logger.warning("numpy not available, using Python lists (slower performance)")


@dataclass
class MapMetadata:
    """地图元数据"""
    origin_x: float  # 起始X坐标（世界坐标）
    origin_y: float  # 起始Y坐标（世界坐标）
    width: int  # 地图宽度（栅格数）
    height: int  # 地图高度（栅格数）
    resolution: float  # 地图分辨率（米/像素）
    min_x: float  # 最小X坐标（世界坐标）
    min_y: float  # 最小Y坐标（世界坐标）
    max_x: float  # 最大X坐标（世界坐标）
    max_y: float  # 最大Y坐标（世界坐标）


class MapManager:
    """地图管理器，处理栅格地图的加载、解析和坐标转换，支持多地图管理"""
    
    def __init__(self, resolution: float = None):
        """
        初始化地图管理器
        
        Args:
            resolution: 地图分辨率（米/像素），默认0.05m/pixel
        """
        self.resolution = resolution or settings.MAP_RESOLUTION
        self.metadata: Optional[MapMetadata] = None
        # 栅格地图（内部格式），0=占用（黑色），100=空闲（白色），-1=未知（灰色）
        # 注意：直接使用ROS格式（ROS: 0=占用，100=空闲，255=未知）
        # 如果有 numpy，使用 np.ndarray，否则使用 List[List[int]]
        self.grid_map: Optional[any] = None
        
        # 多地图管理
        self.maps_storage = Path("data/maps")
        self.maps_storage.mkdir(parents=True, exist_ok=True)
        self.maps_metadata_file = self.maps_storage / "maps.json"
        self.maps: Dict[str, MapInfo] = {}  # map_id -> MapInfo
        self.current_map_id: Optional[str] = None  # 当前加载到内存的地图ID
        # 虚拟墙信息（从机器人获取）
        self.virtual_walls: List[Dict[str, Any]] = []  # 存储虚拟墙列表
        # 限行区域信息（从机器人获取）
        self.restricted_areas: List[Dict[str, Any]] = []  # 存储限行区域列表
        self._load_maps_metadata()
        self._load_default_map()
    
    def load_from_bytes(self, map_bytes: bytes) -> bool:
        """
        从二进制字节流加载地图
        
        地图格式：
        - 前32字节为元数据（低位字节在前）
        - 后续为地图数据（每个字节代表一个格子）
        
        Args:
            map_bytes: 地图二进制数据
            
        Returns:
            是否加载成功
        """
        try:
            if len(map_bytes) < 32:
                logger.error("Map data too short, need at least 32 bytes for metadata")
                return False
            
            # 解析元数据（前32字节，低位字节在前）
            # 假设格式：origin_x(float), origin_y(float), width(int), height(int), resolution(float)
            metadata_bytes = map_bytes[:32]
            
            # 解析元数据（根据思岚科技API文档，可能需要调整）
            # 这里使用通用格式：4个float32 + 2个int32
            origin_x = struct.unpack('<f', metadata_bytes[0:4])[0]
            origin_y = struct.unpack('<f', metadata_bytes[4:8])[0]
            width = struct.unpack('<i', metadata_bytes[8:12])[0]
            height = struct.unpack('<i', metadata_bytes[12:16])[0]
            resolution = struct.unpack('<f', metadata_bytes[16:20])[0]
            
            # 如果解析的分辨率不合理，使用配置的分辨率
            if resolution <= 0 or resolution > 1.0:
                resolution = self.resolution
                logger.warning(f"Invalid resolution from metadata, using configured resolution: {resolution}")
            
            # 解析地图数据
            map_data = map_bytes[32:]
            expected_size = width * height
            
            if len(map_data) < expected_size:
                logger.error(f"Map data size mismatch: expected {expected_size}, got {len(map_data)}")
                return False
            
            # 转换为数组（ROS标准：0=占用，100=空闲，255=未知）
            # 内部存储：0=占用（黑色），100=空闲（白色），-1=未知（灰色）
            if HAS_NUMPY:
                grid_map = np.frombuffer(map_data[:expected_size], dtype=np.uint8)
                grid_map = grid_map.reshape((height, width))
                # 转换值：ROS格式 -> 内部格式
                # ROS: 0=占用 -> 内部: 0=占用（保持不变）
                # ROS: 100=空闲 -> 内部: 100=空闲（保持不变）
                # ROS: 255=未知 -> 内部: -1=未知
                grid_map = grid_map.astype(np.int32)
                # 只处理未知区域：255 -> -1
                unknown_mask = (grid_map == 255)
                grid_map[unknown_mask] = -1
                # 0 和 100 保持不变
            else:
                # 使用 Python 列表
                grid_map = []
                for y in range(height):
                    row = []
                    for x in range(width):
                        idx = y * width + x
                        value = map_data[idx]
                        # 转换值：ROS格式 -> 内部格式
                        # ROS: 0=占用 -> 内部: 0=占用（保持不变）
                        # ROS: 100=空闲 -> 内部: 100=空闲（保持不变）
                        # ROS: 255=未知 -> 内部: -1=未知
                        if value == 255:
                            row.append(-1)  # 未知
                        else:
                            # 0 和 100 以及其他值保持原样
                            row.append(int(value))
                    grid_map.append(row)
            
            # 创建元数据
            min_x = origin_x
            min_y = origin_y
            max_x = origin_x + width * resolution
            max_y = origin_y + height * resolution
            
            self.metadata = MapMetadata(
                origin_x=origin_x,
                origin_y=origin_y,
                width=width,
                height=height,
                resolution=resolution,
                min_x=min_x,
                min_y=min_y,
                max_x=max_x,
                max_y=max_y
            )
            
            self.grid_map = grid_map
            
            logger.info(f"Map loaded: {width}x{height}, resolution={resolution}m/pixel, "
                       f"world bounds: ({min_x}, {min_y}) to ({max_x}, {max_y})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load map: {e}")
            return False
    
    def world_to_map(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """
        世界坐标转换为地图坐标
        
        Args:
            world_x: 世界X坐标
            world_y: 世界Y坐标
            
        Returns:
            (map_x, map_y) 地图坐标（栅格索引）
        """
        if self.metadata is None:
            raise ValueError("Map not loaded")
        
        map_x = int((world_x - self.metadata.origin_x) / self.metadata.resolution)
        map_y = int((world_y - self.metadata.origin_y) / self.metadata.resolution)
        
        return map_x, map_y
    
    def map_to_world(self, map_x: int, map_y: int) -> Tuple[float, float]:
        """
        地图坐标转换为世界坐标
        
        Args:
            map_x: 地图X坐标（栅格索引）
            map_y: 地图Y坐标（栅格索引）
            
        Returns:
            (world_x, world_y) 世界坐标
        """
        if self.metadata is None:
            raise ValueError("Map not loaded")
        
        world_x = self.metadata.origin_x + map_x * self.metadata.resolution
        world_y = self.metadata.origin_y + map_y * self.metadata.resolution
        
        return world_x, world_y
    
    def is_valid_coordinate(self, world_x: float, world_y: float) -> bool:
        """
        检查世界坐标是否在地图范围内
        
        Args:
            world_x: 世界X坐标
            world_y: 世界Y坐标
            
        Returns:
            是否有效
        """
        if self.metadata is None:
            return False
        
        return (self.metadata.min_x <= world_x <= self.metadata.max_x and
                self.metadata.min_y <= world_y <= self.metadata.max_y)
    
    def is_obstacle(self, world_x: float, world_y: float) -> bool:
        """
        检查世界坐标是否为障碍物
        
        Args:
            world_x: 世界X坐标
            world_y: 世界Y坐标
            
        Returns:
            是否为障碍物
        """
        if not self.is_valid_coordinate(world_x, world_y):
            return True  # 超出地图范围视为障碍物
        
        map_x, map_y = self.world_to_map(world_x, world_y)
        
        # 检查边界
        if map_x < 0 or map_x >= self.metadata.width or map_y < 0 or map_y >= self.metadata.height:
            return True
        
        # 检查是否为障碍物
        # 内部格式：0=占用(黑色), 100=空闲(白色), -1=未知(灰色)
        if HAS_NUMPY:
            value = self.grid_map[map_y, map_x]
        else:
            value = self.grid_map[map_y][map_x]
        # 0是占用/障碍物，100是空闲，-1是未知（视为障碍物）
        return value == 0 or value == -1
    
    def is_free(self, world_x: float, world_y: float) -> bool:
        """
        检查世界坐标是否为自由空间
        
        Args:
            world_x: 世界X坐标
            world_y: 世界Y坐标
            
        Returns:
            是否为自由空间
        """
        if not self.is_valid_coordinate(world_x, world_y):
            return False
        
        map_x, map_y = self.world_to_map(world_x, world_y)
        
        # 检查边界
        if map_x < 0 or map_x >= self.metadata.width or map_y < 0 or map_y >= self.metadata.height:
            return False
        
        # 检查是否为自由空间
        # 内部格式：0=占用(黑色), 100=空闲(白色), -1=未知(灰色)
        if HAS_NUMPY:
            value = self.grid_map[map_y, map_x]
        else:
            value = self.grid_map[map_y][map_x]
        # 100是空闲/自由空间，0是占用，-1是未知（视为障碍物）
        return value == 100
    
    def add_obstacle(self, world_x: float, world_y: float, radius: float = 0.2):
        """
        在地图上添加障碍物（动态障碍物）
        
        Args:
            world_x: 障碍物中心X坐标
            world_y: 障碍物中心Y坐标
            radius: 障碍物半径（米）
        """
        if self.metadata is None or self.grid_map is None:
            return
        
        # 计算障碍物覆盖的栅格范围
        map_x, map_y = self.world_to_map(world_x, world_y)
        radius_pixels = int(radius / self.metadata.resolution)
        
        # 标记障碍物
        for dy in range(-radius_pixels, radius_pixels + 1):
            for dx in range(-radius_pixels, radius_pixels + 1):
                px = map_x + dx
                py = map_y + dy
                
                if 0 <= px < self.metadata.width and 0 <= py < self.metadata.height:
                    # 检查距离
                    if HAS_NUMPY:
                        dist = np.sqrt(dx**2 + dy**2) * self.metadata.resolution
                    else:
                        dist = math.sqrt(dx**2 + dy**2) * self.metadata.resolution
                    if dist <= radius:
                        # 障碍物设置为0（占用/黑色）
                        if HAS_NUMPY:
                            self.grid_map[py, px] = 0
                        else:
                            self.grid_map[py][px] = 0
    
    def remove_obstacle(self, world_x: float, world_y: float, radius: float = 0.2):
        """
        从地图上移除障碍物（需要原始地图数据，这里简化处理）
        
        Args:
            world_x: 障碍物中心X坐标
            world_y: 障碍物中心Y坐标
            radius: 障碍物半径（米）
        """
        # 注意：这个功能需要保存原始地图数据，这里简化处理
        # 实际实现中应该保存原始地图，然后重新应用动态障碍物
        logger.warning("remove_obstacle not fully implemented, need original map data")
    
    def get_map_info(self) -> Optional[dict]:
        """
        获取地图信息
        
        Returns:
            地图信息字典
        """
        if self.metadata is None:
            return None
        
        return {
            "width": self.metadata.width,
            "height": self.metadata.height,
            "resolution": self.metadata.resolution,
            "origin_x": self.metadata.origin_x,
            "origin_y": self.metadata.origin_y,
            "min_x": self.metadata.min_x,
            "min_y": self.metadata.min_y,
            "max_x": self.metadata.max_x,
            "max_y": self.metadata.max_y
        }
    
    def _load_maps_metadata(self):
        """从文件加载地图元数据"""
        try:
            if self.maps_metadata_file.exists():
                with open(self.maps_metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for map_id, map_data in data.items():
                        self.maps[map_id] = MapInfo(**map_data)
                logger.info(f"Loaded {len(self.maps)} maps from metadata file")
        except Exception as e:
            logger.error(f"Failed to load maps metadata: {e}", exc_info=True)
            self.maps = {}
    
    def _save_maps_metadata(self):
        """保存地图元数据到文件"""
        try:
            data = {}
            for map_id, map_info in self.maps.items():
                data[map_id] = map_info.dict()
            with open(self.maps_metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self.maps)} maps metadata")
        except Exception as e:
            logger.error(f"Failed to save maps metadata: {e}", exc_info=True)
    
    def _load_default_map(self):
        """加载默认地图到内存"""
        default_map = None
        for map_id, map_info in self.maps.items():
            if map_info.is_default:
                default_map = map_info
                break
        
        if default_map:
            self.load_map_to_memory(default_map.map_id)
        else:
            logger.info("No default map found")
    
    def load_map_to_memory(self, map_id: str) -> bool:
        """
        加载指定地图到内存
        
        Args:
            map_id: 地图ID
            
        Returns:
            是否加载成功
        """
        if map_id not in self.maps:
            logger.error(f"Map {map_id} not found")
            return False
        
        map_info = self.maps[map_id]
        file_path = self.maps_storage / map_info.file_path
        
        if not file_path.exists():
            logger.error(f"Map file not found: {file_path}")
            return False
        
        try:
            # 读取地图文件（支持gzip压缩）
            if file_path.suffix == '.gz':
                with gzip.open(file_path, 'rb') as f:
                    map_bytes = f.read()
            else:
                with open(file_path, 'rb') as f:
                    map_bytes = f.read()
            
            # 加载地图
            success = self.load_from_bytes(map_bytes)
            if success:
                self.current_map_id = map_id
                logger.info(f"Loaded map {map_id} ({map_info.name}) to memory")
            return success
        except Exception as e:
            logger.error(f"Failed to load map {map_id}: {e}", exc_info=True)
            return False
    
    async def save_map_from_robot(self, robot_id: str, name: str, description: Optional[str] = None, 
                                   map_bytes: bytes = None, robot_agent=None) -> Optional[str]:
        """
        从机器人加载地图并保存
        
        Args:
            robot_id: 机器人ID
            name: 地图名称
            description: 地图描述
            map_bytes: 地图数据（如果提供则直接使用，否则从robot_agent获取）
            robot_agent: 机器人代理（如果map_bytes为None则需要）
            
        Returns:
            地图ID，如果失败返回None
        """
        try:
            # 如果没有提供地图数据，从机器人获取
            if map_bytes is None:
                if robot_agent is None:
                    logger.error("Either map_bytes or robot_agent must be provided")
                    return None
                map_bytes = await robot_agent.get_map_explore()
            
            # 先加载到内存以获取元数据
            temp_metadata = self.metadata
            temp_grid_map = self.grid_map
            success = self.load_from_bytes(map_bytes)
            if not success:
                logger.error("Failed to parse map bytes")
                return None
            
            # 获取地图元数据
            map_info_dict = self.get_map_info()
            if not map_info_dict:
                logger.error("Failed to get map info")
                return None
            
            # 生成地图ID
            map_id = str(uuid.uuid4())
            
            # 保存地图文件（使用gzip压缩）
            file_path = f"{map_id}.bin.gz"
            full_path = self.maps_storage / file_path
            with gzip.open(full_path, 'wb') as f:
                f.write(map_bytes)
            
            # 创建地图信息
            now = datetime.now().isoformat()
            map_info = MapInfo(
                map_id=map_id,
                name=name,
                description=description,
                robot_id=robot_id,
                is_default=len(self.maps) == 0,  # 第一张地图自动设为默认
                created_at=now,
                updated_at=now,
                file_path=file_path,
                thumbnail_path=None,  # 稍后生成
                metadata=map_info_dict,
                file_size=len(map_bytes)
            )
            
            # 保存到字典
            self.maps[map_id] = map_info
            
            # 如果这是第一张地图，设为默认并加载到内存
            if map_info.is_default:
                self.current_map_id = map_id
            else:
                # 恢复之前的地图
                self.metadata = temp_metadata
                self.grid_map = temp_grid_map
            
            # 保存元数据
            self._save_maps_metadata()
            
            # 生成缩略图（异步，不阻塞）
            try:
                self._generate_thumbnail(map_id)
            except Exception as e:
                logger.warning(f"Failed to generate thumbnail for map {map_id}: {e}")
            
            logger.info(f"Saved map {map_id} ({name}) from robot {robot_id}")
            return map_id
            
        except Exception as e:
            logger.error(f"Failed to save map from robot: {e}", exc_info=True)
            return None
    
    def _generate_thumbnail(self, map_id: str) -> Optional[str]:
        """
        生成地图缩略图
        
        Args:
            map_id: 地图ID
            
        Returns:
            缩略图路径，如果失败返回None
        """
        try:
            # 尝试导入PIL
            try:
                from PIL import Image
            except ImportError:
                logger.warning("PIL not available, skipping thumbnail generation")
                return None
            
            if map_id not in self.maps:
                return None
            
            map_info = self.maps[map_id]
            
            # 加载地图数据
            file_path = self.maps_storage / map_info.file_path
            if not file_path.exists():
                return None
            
            # 读取地图文件
            if file_path.suffix == '.gz':
                with gzip.open(file_path, 'rb') as f:
                    map_bytes = f.read()
            else:
                with open(file_path, 'rb') as f:
                    map_bytes = f.read()
            
            # 解析元数据
            metadata_bytes = map_bytes[:32]
            width = struct.unpack('<i', metadata_bytes[8:12])[0]
            height = struct.unpack('<i', metadata_bytes[12:16])[0]
            map_data = map_bytes[32:]
            expected_size = width * height
            
            if len(map_data) < expected_size:
                return None
            
            # 创建图像
            img = Image.new('RGB', (width, height), color='white')
            pixels = img.load()
            
            # 转换地图数据为图像
            for y in range(height):
                for x in range(width):
                    idx = y * width + x
                    if idx < len(map_data):
                        value = map_data[idx]
                        # ROS格式：0=占用(黑色), 100=空闲(白色), 255=未知(灰色)
                        if value == 0:
                            pixels[x, y] = (0, 0, 0)  # 黑色
                        elif value == 100:
                            pixels[x, y] = (255, 255, 255)  # 白色
                        else:
                            pixels[x, y] = (128, 128, 128)  # 灰色
            
            # 生成缩略图（200x200）
            thumbnail_size = 200
            # 兼容不同PIL版本
            try:
                img.thumbnail((thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
            except AttributeError:
                # 旧版本PIL使用LANCZOS常量
                img.thumbnail((thumbnail_size, thumbnail_size), Image.LANCZOS)
            
            # 保存缩略图
            thumbnail_path = f"{map_id}_thumbnail.png"
            thumbnail_full_path = self.maps_storage / thumbnail_path
            img.save(thumbnail_full_path, 'PNG')
            
            # 更新地图信息
            map_info.thumbnail_path = thumbnail_path
            map_info.updated_at = datetime.now().isoformat()
            self._save_maps_metadata()
            
            return thumbnail_path
            
        except Exception as e:
            logger.error(f"Failed to generate thumbnail: {e}", exc_info=True)
            return None
    
    def set_default_map(self, map_id: str) -> bool:
        """
        设置默认地图
        
        Args:
            map_id: 地图ID
            
        Returns:
            是否设置成功
        """
        if map_id not in self.maps:
            logger.error(f"Map {map_id} not found")
            return False
        
        # 取消其他地图的默认状态
        for mid, map_info in self.maps.items():
            map_info.is_default = (mid == map_id)
        
        # 加载新默认地图到内存
        self.load_map_to_memory(map_id)
        
        # 保存元数据
        self._save_maps_metadata()
        
        logger.info(f"Set default map to {map_id}")
        return True
    
    def delete_map(self, map_id: str) -> bool:
        """
        删除地图
        
        Args:
            map_id: 地图ID
            
        Returns:
            是否删除成功
        """
        if map_id not in self.maps:
            logger.error(f"Map {map_id} not found")
            return False
        
        map_info = self.maps[map_id]
        
        # 不能删除默认地图（除非是最后一张）
        if map_info.is_default and len(self.maps) > 1:
            logger.error("Cannot delete default map when other maps exist")
            return False
        
        # 删除文件
        try:
            file_path = self.maps_storage / map_info.file_path
            if file_path.exists():
                file_path.unlink()
            
            if map_info.thumbnail_path:
                thumbnail_path = self.maps_storage / map_info.thumbnail_path
                if thumbnail_path.exists():
                    thumbnail_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete map files: {e}")
        
        # 从字典中删除
        del self.maps[map_id]
        
        # 如果删除的是当前加载的地图，清空内存
        if self.current_map_id == map_id:
            self.metadata = None
            self.grid_map = None
            self.current_map_id = None
            
            # 如果有其他地图，加载第一张
            if self.maps:
                first_map_id = next(iter(self.maps.keys()))
                self.set_default_map(first_map_id)
        
        # 保存元数据
        self._save_maps_metadata()
        
        logger.info(f"Deleted map {map_id}")
        return True
    
    def list_maps(self) -> List[MapInfo]:
        """
        获取所有地图列表
        
        Returns:
            地图信息列表
        """
        return list(self.maps.values())
    
    def get_default_map_data(self) -> Optional[dict]:
        """
        获取默认地图的完整数据（用于可视化）
        
        Returns:
            包含info和data的字典，如果没有默认地图返回None
        """
        default_map = None
        for map_id, map_info in self.maps.items():
            if map_info.is_default:
                default_map = map_info
                break
        
        if not default_map:
            return None
        
        # 确保地图已加载到内存
        if self.current_map_id != default_map.map_id:
            if not self.load_map_to_memory(default_map.map_id):
                return None
        
        # 获取地图信息
        map_info = self.get_map_info()
        if not map_info:
            return None
        
        # 在地图信息中添加地图ID，用于前端检测地图变化
        map_info["map_id"] = default_map.map_id
        map_info["map_name"] = default_map.name
        
        # 转换地图数据
        map_data = None
        if self.grid_map is not None:
            try:
                if hasattr(self.grid_map, 'tolist'):
                    map_data = self.grid_map.tolist()
                else:
                    map_data = self.grid_map
            except Exception as e:
                logger.error(f"Failed to convert map data: {e}", exc_info=True)
                return None
        
        return {
            "info": map_info,
            "data": map_data
        }


# 全局地图管理器实例
_map_manager: Optional[MapManager] = None


def get_map_manager() -> MapManager:
    """获取地图管理器实例（依赖注入）"""
    global _map_manager
    if _map_manager is None:
        _map_manager = MapManager()
    return _map_manager

