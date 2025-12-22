"""
将JSON文件中的任务迁移到数据库
"""
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.task_db import TaskDatabase
from app.models.task import Task, TaskStatus, TaskPriority, Pose
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """迁移任务数据"""
    json_file = Path("data/tasks.json")
    db = TaskDatabase("data/tasks.db")
    
    if not json_file.exists():
        print("No tasks.json file found, skipping migration")
        return
    
    print("Loading tasks from JSON file...")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load JSON file: {e}")
        return
    
    tasks_data = data.get('tasks', [])
    print(f"Found {len(tasks_data)} tasks to migrate")
    
    if len(tasks_data) == 0:
        print("No tasks to migrate")
        return
    
    migrated = 0
    failed = 0
    
    for task_data in tasks_data:
        try:
            # 解析datetime字段
            if 'created_at' in task_data and task_data['created_at']:
                if isinstance(task_data['created_at'], str):
                    # 处理带空格的时间格式（如 "2025-11-25 18:50:57.429768"）
                    if ' ' in task_data['created_at'] and 'T' not in task_data['created_at']:
                        task_data['created_at'] = task_data['created_at'].replace(' ', 'T')
                    task_data['created_at'] = datetime.fromisoformat(task_data['created_at'])
            
            if 'assigned_at' in task_data and task_data['assigned_at']:
                if isinstance(task_data['assigned_at'], str):
                    if ' ' in task_data['assigned_at'] and 'T' not in task_data['assigned_at']:
                        task_data['assigned_at'] = task_data['assigned_at'].replace(' ', 'T')
                    task_data['assigned_at'] = datetime.fromisoformat(task_data['assigned_at'])
            
            if 'started_at' in task_data and task_data['started_at']:
                if isinstance(task_data['started_at'], str):
                    if ' ' in task_data['started_at'] and 'T' not in task_data['started_at']:
                        task_data['started_at'] = task_data['started_at'].replace(' ', 'T')
                    task_data['started_at'] = datetime.fromisoformat(task_data['started_at'])
            
            if 'completed_at' in task_data and task_data['completed_at']:
                if isinstance(task_data['completed_at'], str):
                    if ' ' in task_data['completed_at'] and 'T' not in task_data['completed_at']:
                        task_data['completed_at'] = task_data['completed_at'].replace(' ', 'T')
                    task_data['completed_at'] = datetime.fromisoformat(task_data['completed_at'])
            
            # 解析Pose对象
            if 'start_pose' in task_data and task_data['start_pose']:
                task_data['start_pose'] = Pose(**task_data['start_pose'])
            if 'target_pose' in task_data and task_data['target_pose']:
                task_data['target_pose'] = Pose(**task_data['target_pose'])
            
            # 解析枚举
            if 'status' in task_data:
                task_data['status'] = TaskStatus(task_data['status'])
            if 'priority' in task_data:
                task_data['priority'] = TaskPriority(task_data['priority'])
            
            task = Task(**task_data)
            
            if db.save_task(task):
                migrated += 1
                if migrated % 100 == 0:
                    print(f"  Migrated {migrated} tasks...")
            else:
                failed += 1
                print(f"Failed to migrate task {task.task_id}")
        except Exception as e:
            failed += 1
            print(f"Error migrating task: {e}")
            logger.exception(f"Error details for task: {task_data.get('task_id', 'unknown')}")
    
    print(f"\nMigration completed:")
    print(f"  Migrated: {migrated}")
    print(f"  Failed: {failed}")
    print(f"\nDatabase file: data/tasks.db")
    print("You can now backup and remove data/tasks.json if migration was successful")
    
    # 验证迁移结果
    db_count = db.count_tasks()
    print(f"\nVerification: Database contains {db_count} tasks")


if __name__ == "__main__":
    migrate()

