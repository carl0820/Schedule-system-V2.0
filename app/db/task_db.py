"""
任务数据库操作
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from contextlib import contextmanager
from app.models.task import Task, TaskStatus, TaskPriority, ActionItem, ActionType
from app.models.robot import Pose

logger = logging.getLogger(__name__)


class TaskDatabase:
    """任务数据库操作类"""
    
    def __init__(self, db_path: str = "data/tasks.db"):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0
        )
        conn.row_factory = sqlite3.Row  # 使用Row工厂，可以通过列名访问
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 创建任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    robot_id TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    action_id INTEGER,
                    is_multi_action INTEGER NOT NULL DEFAULT 0,
                    current_action_index INTEGER,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    
                    -- Pose字段（JSON存储）
                    start_pose TEXT,
                    target_pose TEXT,
                    
                    -- 时间字段
                    created_at TEXT NOT NULL,
                    assigned_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    
                    -- 多动作任务的actions（JSON存储）
                    actions TEXT,
                    
                    -- 其他字段
                    acceptable_precision REAL DEFAULT 0.3,
                    speed_ratio REAL DEFAULT 1.0,
                    poi_name TEXT
                )
            """)
            
            # 创建索引以提高查询性能
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_robot_id ON tasks(robot_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_robot ON tasks(status, robot_id)
            """)
            
            # 迁移已存在的表：如果target_pose字段有NOT NULL约束，需要移除
            # SQLite不支持直接ALTER COLUMN，需要重建表
            try:
                cursor.execute("PRAGMA table_info(tasks)")
                columns = cursor.fetchall()
                target_pose_col = next((col for col in columns if col[1] == "target_pose"), None)
                if target_pose_col and target_pose_col[3] == 1:  # 3是notnull字段，1表示NOT NULL
                    logger.info("Migrating database: removing NOT NULL constraint from target_pose...")
                    # 创建新表
                    cursor.execute("""
                        CREATE TABLE tasks_new (
                            task_id TEXT PRIMARY KEY,
                            robot_id TEXT,
                            status TEXT NOT NULL,
                            priority INTEGER NOT NULL,
                            action_id INTEGER,
                            is_multi_action INTEGER NOT NULL DEFAULT 0,
                            current_action_index INTEGER,
                            retry_count INTEGER NOT NULL DEFAULT 0,
                            error_message TEXT,
                            start_pose TEXT,
                            target_pose TEXT,
                            created_at TEXT NOT NULL,
                            assigned_at TEXT,
                            started_at TEXT,
                            completed_at TEXT,
                            actions TEXT,
                            acceptable_precision REAL DEFAULT 0.3,
                            speed_ratio REAL DEFAULT 1.0,
                            poi_name TEXT
                        )
                    """)
                    # 复制数据
                    cursor.execute("INSERT INTO tasks_new SELECT * FROM tasks")
                    # 删除旧表
                    cursor.execute("DROP TABLE tasks")
                    # 重命名新表
                    cursor.execute("ALTER TABLE tasks_new RENAME TO tasks")
                    # 重新创建索引
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_robot_id ON tasks(robot_id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_robot ON tasks(status, robot_id)")
                    conn.commit()
                    logger.info("Database migration completed successfully")
            except Exception as e:
                logger.warning(f"Database migration check failed (may not be needed): {e}")
                # 如果迁移失败，不影响正常使用
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def _pose_to_json(self, pose: Optional[Pose]) -> Optional[str]:
        """将Pose对象转换为JSON字符串"""
        if pose is None:
            return None
        return json.dumps({
            "x": pose.x,
            "y": pose.y,
            "z": pose.z,
            "yaw": pose.yaw,
            "pitch": pose.pitch,
            "roll": pose.roll
        })
    
    def _json_to_pose(self, json_str: Optional[str]) -> Optional[Pose]:
        """将JSON字符串转换为Pose对象"""
        if json_str is None:
            return None
        try:
            data = json.loads(json_str)
            return Pose(**data)
        except Exception as e:
            logger.warning(f"Failed to parse pose JSON: {e}")
            return None
    
    def _actions_to_json(self, actions: Optional[List[ActionItem]]) -> Optional[str]:
        """将ActionItem列表转换为JSON字符串"""
        if actions is None:
            return None
        try:
            return json.dumps([action.dict() for action in actions], default=str)
        except Exception as e:
            logger.warning(f"Failed to serialize actions: {e}")
            return None
    
    def _json_to_actions(self, json_str: Optional[str]) -> Optional[List[ActionItem]]:
        """将JSON字符串转换为ActionItem列表"""
        if json_str is None:
            return None
        try:
            data = json.loads(json_str)
            return [ActionItem(**item) for item in data]
        except Exception as e:
            logger.warning(f"Failed to parse actions JSON: {e}")
            return None
    
    def _datetime_to_str(self, dt: Optional[datetime]) -> Optional[str]:
        """将datetime转换为ISO格式字符串"""
        if dt is None:
            return None
        return dt.isoformat()
    
    def _str_to_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """将ISO格式字符串转换为datetime"""
        if dt_str is None:
            return None
        try:
            # 处理不同的datetime格式
            if isinstance(dt_str, str):
                # 处理带空格的时间格式（如 "2025-11-25 18:50:57.429768"）
                if ' ' in dt_str and 'T' not in dt_str:
                    dt_str = dt_str.replace(' ', 'T')
                return datetime.fromisoformat(dt_str)
            return None
        except Exception as e:
            logger.warning(f"Failed to parse datetime '{dt_str}': {e}")
            return None
    
    def save_task(self, task: Task) -> bool:
        """保存任务到数据库"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO tasks (
                        task_id, robot_id, status, priority, action_id,
                        is_multi_action, current_action_index, retry_count, error_message,
                        start_pose, target_pose,
                        created_at, assigned_at, started_at, completed_at,
                        actions, acceptable_precision, speed_ratio, poi_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task.task_id,
                    task.robot_id,
                    task.status.value,
                    task.priority.value,
                    task.action_id,
                    int(task.is_multi_action),
                    task.current_action_index,
                    task.retry_count,
                    task.error_message,
                    self._pose_to_json(task.start_pose),
                    self._pose_to_json(task.target_pose),
                    self._datetime_to_str(task.created_at),
                    self._datetime_to_str(task.assigned_at),
                    self._datetime_to_str(task.started_at),
                    self._datetime_to_str(task.completed_at),
                    self._actions_to_json(task.actions),
                    task.acceptable_precision,
                    task.speed_ratio,
                    task.poi_name
                ))
                
                return True
        except Exception as e:
            logger.error(f"Failed to save task {task.task_id}: {e}", exc_info=True)
            return False
    
    def save_tasks_batch(self, tasks: List[Task]) -> int:
        """批量保存任务到数据库（更高效）"""
        saved_count = 0
        if not tasks:
            logger.debug("No tasks to save in batch")
            return 0
        
        logger.info(f"[DB] Starting to save {len(tasks)} tasks to database...")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                for task in tasks:
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO tasks (
                                task_id, robot_id, status, priority, action_id,
                                is_multi_action, current_action_index, retry_count, error_message,
                                start_pose, target_pose,
                                created_at, assigned_at, started_at, completed_at,
                                actions, acceptable_precision, speed_ratio, poi_name
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            task.task_id,
                            task.robot_id,
                            task.status.value,
                            task.priority.value,
                            task.action_id,
                            int(task.is_multi_action),
                            task.current_action_index,
                            task.retry_count,
                            task.error_message,
                            self._pose_to_json(task.start_pose),
                            self._pose_to_json(task.target_pose),
                            self._datetime_to_str(task.created_at),
                            self._datetime_to_str(task.assigned_at),
                            self._datetime_to_str(task.started_at),
                            self._datetime_to_str(task.completed_at),
                            self._actions_to_json(task.actions),
                            task.acceptable_precision,
                            task.speed_ratio,
                            task.poi_name
                        ))
                        saved_count += 1
                        logger.debug(f"[DB] Task {task.task_id[:8]} saved to database in batch")
                    except Exception as e:
                        logger.error(f"[DB] Failed to save task {task.task_id[:8]} in batch: {e}", exc_info=True)
                        continue
                
                conn.commit()
                logger.info(f"[DB] Successfully saved {saved_count}/{len(tasks)} tasks to database")
        except Exception as e:
            logger.error(f"[DB] Failed to save tasks batch: {e}", exc_info=True)
            # 不重新抛出异常，避免影响任务创建流程
            # 任务已在内存中，下次保存时会重试
        
        return saved_count
    
    def load_task(self, task_id: str) -> Optional[Task]:
        """从数据库加载任务"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
                row = cursor.fetchone()
                
                if row is None:
                    return None
                
                return self._row_to_task(row)
        except Exception as e:
            logger.error(f"Failed to load task {task_id}: {e}", exc_info=True)
            return None
    
    def load_all_tasks(self) -> List[Task]:
        """从数据库加载所有任务"""
        tasks = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC")
                rows = cursor.fetchall()
                
                for row in rows:
                    try:
                        task = self._row_to_task(row)
                        if task:
                            tasks.append(task)
                    except Exception as e:
                        logger.warning(f"Failed to load task from row: {e}")
                        continue
                
                logger.info(f"Loaded {len(tasks)} tasks from database")
        except Exception as e:
            logger.error(f"Failed to load tasks from database: {e}", exc_info=True)
        
        return tasks
    
    def _row_to_task(self, row: sqlite3.Row) -> Optional[Task]:
        """将数据库行转换为Task对象"""
        try:
            task_data = {
                "task_id": row["task_id"],
                "robot_id": row["robot_id"],
                "status": TaskStatus(row["status"]),
                "priority": TaskPriority(row["priority"]),
                "action_id": row["action_id"],
                "is_multi_action": bool(row["is_multi_action"]),
                "current_action_index": row["current_action_index"],
                "retry_count": row["retry_count"] or 0,
                "error_message": row["error_message"],
                "start_pose": self._json_to_pose(row["start_pose"]),
                "target_pose": self._json_to_pose(row["target_pose"]),
                "created_at": self._str_to_datetime(row["created_at"]),
                "assigned_at": self._str_to_datetime(row["assigned_at"]),
                "started_at": self._str_to_datetime(row["started_at"]),
                "completed_at": self._str_to_datetime(row["completed_at"]),
                "actions": self._json_to_actions(row["actions"]),
                "acceptable_precision": row["acceptable_precision"] or 0.3,
                "speed_ratio": row["speed_ratio"] or 1.0,
                "poi_name": row["poi_name"]
            }
            
            return Task(**task_data)
        except Exception as e:
            logger.error(f"Failed to convert row to task: {e}", exc_info=True)
            return None
    
    def delete_task(self, task_id: str) -> bool:
        """从数据库删除任务"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}", exc_info=True)
            return False
    
    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """根据状态查询任务"""
        tasks = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status.value,))
                rows = cursor.fetchall()
                
                for row in rows:
                    task = self._row_to_task(row)
                    if task:
                        tasks.append(task)
        except Exception as e:
            logger.error(f"Failed to get tasks by status {status}: {e}", exc_info=True)
        
        return tasks
    
    def get_tasks_by_robot(self, robot_id: str) -> List[Task]:
        """根据机器人ID查询任务"""
        tasks = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks WHERE robot_id = ? ORDER BY created_at DESC", (robot_id,))
                rows = cursor.fetchall()
                
                for row in rows:
                    task = self._row_to_task(row)
                    if task:
                        tasks.append(task)
        except Exception as e:
            logger.error(f"Failed to get tasks by robot {robot_id}: {e}", exc_info=True)
        
        return tasks
    
    def count_tasks(self) -> int:
        """获取任务总数"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM tasks")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to count tasks: {e}", exc_info=True)
            return 0

