"""
快速测试脚本 - 测试基本功能
"""
import asyncio
import sys
import os

# 添加项目根目录到sys.path，以便导入模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

async def test_imports():
    """测试导入"""
    print("=" * 60)
    print("测试导入...")
    print("=" * 60)
    
    try:
        from app.models.robot import Pose, Speed, RobotStatus
        print("[OK] app.models.robot")
    except Exception as e:
        print(f"[ERROR] app.models.robot: {e}")
        return False
    
    try:
        from app.models.task import Task, TaskCreate, TaskStatus
        print("[OK] app.models.task")
    except Exception as e:
        print(f"[ERROR] app.models.task: {e}")
        return False
    
    try:
        from app.services.robot_agent import RobotAgent
        print("[OK] app.services.robot_agent")
    except Exception as e:
        print(f"[ERROR] app.services.robot_agent: {e}")
        return False
    
    try:
        from app.services.map_manager import MapManager, get_map_manager
        print("[OK] app.services.map_manager")
    except Exception as e:
        print(f"[ERROR] app.services.map_manager: {e}")
        return False
    
    try:
        from app.services.path_planner import PathPlanner
        print("[OK] app.services.path_planner")
    except Exception as e:
        print(f"[ERROR] app.services.path_planner: {e}")
        return False
    
    try:
        from app.services.robot_manager import RobotManager, get_robot_manager
        print("[OK] app.services.robot_manager")
    except Exception as e:
        print(f"[ERROR] app.services.robot_manager: {e}")
        return False
    
    try:
        from app.services.task_scheduler import TaskScheduler, get_task_scheduler
        print("[OK] app.services.task_scheduler")
    except Exception as e:
        print(f"[ERROR] app.services.task_scheduler: {e}")
        return False
    
    try:
        from app.api import robots, tasks, maps, system
        print("[OK] app.api modules")
    except Exception as e:
        print(f"[ERROR] app.api: {e}")
        return False
    
    try:
        import main
        print("[OK] main")
    except Exception as e:
        print(f"[ERROR] main: {e}")
        return False
    
    return True

async def test_basic_functionality():
    """测试基本功能"""
    print("\n" + "=" * 60)
    print("测试基本功能...")
    print("=" * 60)
    
    try:
        from app.models.robot import Pose
        pose = Pose(x=1.0, y=2.0, yaw=0.5)
        print(f"[OK] Pose model: {pose}")
    except Exception as e:
        print(f"[ERROR] Pose model: {e}")
        return False
    
    try:
        from app.services.map_manager import get_map_manager
        map_manager = get_map_manager()
        print(f"[OK] MapManager instance created")
    except Exception as e:
        print(f"[ERROR] MapManager: {e}")
        return False
    
    try:
        from app.services.robot_manager import get_robot_manager
        robot_manager = get_robot_manager()
        print(f"[OK] RobotManager instance created")
    except Exception as e:
        print(f"[ERROR] RobotManager: {e}")
        return False
    
    try:
        from app.services.task_scheduler import get_task_scheduler
        task_scheduler = get_task_scheduler()
        print(f"[OK] TaskScheduler instance created")
    except Exception as e:
        print(f"[ERROR] TaskScheduler: {e}")
        return False
    
    return True

async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("快速功能测试")
    print("=" * 60)
    
    # 测试导入
    if not await test_imports():
        print("\n[FAIL] 导入测试失败，请检查依赖是否安装")
        print("安装依赖: pip install -r requirements.txt")
        sys.exit(1)
    
    # 测试基本功能
    if not await test_basic_functionality():
        print("\n[FAIL] 基本功能测试失败")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("[SUCCESS] 所有测试通过！")
    print("=" * 60)
    print("\n可以启动应用：python main.py")
    print("或使用 uvicorn: uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())

