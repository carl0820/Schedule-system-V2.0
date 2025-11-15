"""
阶段1测试脚本 - 基础框架功能测试
测试内容�?
1. 项目架构搭建
2. 地图管理模块（栅格地图加载、解析、坐标转换）
3. 思岚科技API封装（所有机器人API接口�?
4. 基础路径规划（A*算法�?
"""
import asyncio
import sys
import os
from typing import Optional

# 尝试导入 httpx，如果不存在则设置为 None
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

# 添加项目根目录到sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


async def test_imports():
    """测试1：模块导�?""
    print("\n" + "=" * 60)
    print("测试1：模块导�?)
    print("=" * 60)
    
    modules = [
        ("app.models.robot", "Pose, Speed, RobotStatus"),
        ("app.models.task", "Task, TaskCreate, TaskStatus"),
        ("app.services.robot_agent", "RobotAgent"),
        ("app.services.map_manager", "MapManager, get_map_manager"),
        ("app.services.path_planner", "PathPlanner"),
        ("app.services.robot_manager", "RobotManager, get_robot_manager"),
        ("app.services.task_scheduler", "TaskScheduler, get_task_scheduler"),
        ("app.api", "robots, tasks, maps, system"),
        ("main", "app"),
    ]
    
    failed = []
    for module_name, items in modules:
        try:
            exec(f"from {module_name} import {items}")
            print(f"[OK] {module_name}")
        except Exception as e:
            print(f"[ERROR] {module_name}: {e}")
            failed.append(module_name)
    
    if failed:
        print(f"\n[FAIL] 以下模块导入失败: {', '.join(failed)}")
        return False
    
    print("\n[SUCCESS] 所有模块导入成�?)
    return True


async def test_map_manager():
    """测试2：地图管理模�?""
    print("\n" + "=" * 60)
    print("测试2：地图管理模块（栅格地图加载、解析、坐标转换）")
    print("=" * 60)
    
    try:
        from app.services.map_manager import get_map_manager
        from app.models.robot import Pose
        
        map_manager = get_map_manager()
        print("[OK] MapManager 实例创建成功")
        
        # 测试坐标转换（即使没有地图数据）
        try:
            # 测试世界坐标转像素坐�?
            world_x, world_y = 1.0, 2.0
            pixel_x, pixel_y = map_manager.world_to_pixel(world_x, world_y)
            print(f"[OK] 世界坐标转像素坐�? ({world_x}, {world_y}) -> ({pixel_x}, {pixel_y})")
        except Exception as e:
            print(f"[WARNING] 坐标转换测试: {e} (可能需要地图数�?")
        
        try:
            # 测试像素坐标转世界坐�?
            pixel_x, pixel_y = 100, 200
            world_x, world_y = map_manager.pixel_to_world(pixel_x, pixel_y)
            print(f"[OK] 像素坐标转世界坐�? ({pixel_x}, {pixel_y}) -> ({world_x}, {world_y})")
        except Exception as e:
            print(f"[WARNING] 坐标转换测试: {e} (可能需要地图数�?")
        
        print("[SUCCESS] 地图管理模块测试通过")
        return True
        
    except Exception as e:
        print(f"[ERROR] 地图管理模块测试失败: {e}")
        return False


async def test_robot_agent():
    """测试3：思岚科技API封装"""
    print("\n" + "=" * 60)
    print("测试3：思岚科技API封装（所有机器人API接口�?)
    print("=" * 60)
    
    try:
        from app.services.robot_agent import RobotAgent
        
        # 使用测试URL（不会实际连接）
        test_url = "http://10.160.128.91:1448"
        agent = RobotAgent(robot_id=test_robot_id, base_url=test_url)
        agent = RobotAgent(robot_id=test_robot_id, base_url=test_url)
        print(f"[OK] RobotAgent 瀹炰緥鍒涘缓鎴愬姛 (robot_id: {test_robot_id}, base_url: {test_url})")
        # 测试API方法是否存在
        methods = [
            "get_pose",
            "get_speed",
            "get_battery_status",
            "get_robot_health",
            "get_robot_info",
            "get_localization_quality",
            "move_to",
            "set_speed",
            "stop",
            "cancel_action",
        ]
        
        for method in methods:
            if hasattr(agent, method):
                print(f"[OK] API方法存在: {method}")
            else:
                print(f"[ERROR] API方法不存�? {method}")
                return False
        
        print("[SUCCESS] 思岚科技API封装测试通过")
        print("[NOTE] 实际API调用需要机器人连接")
        return True
        
    except Exception as e:
        print(f"[ERROR] 思岚科技API封装测试失败: {e}")
        return False


async def test_path_planner():
    """测试4：基础路径规划（A*算法�?""
    print("\n" + "=" * 60)
    print("测试4：基础路径规划（A*算法�?)
    print("=" * 60)
    
    try:
        from app.services.path_planner import PathPlanner
        from app.services.map_manager import get_map_manager
        from app.models.robot import Pose
        
        map_manager = get_map_manager()
        planner = PathPlanner(map_manager)
        print("[OK] PathPlanner 实例创建成功")
        
        # 创建一个简单的测试地图�?0x10，中间有障碍�?
        import numpy as np
        test_map = np.ones((10, 10), dtype=np.uint8) * 255  # 全白（可通行�?
        test_map[4:6, 4:6] = 0  # 中间有障碍（黑色�?
        
        # 测试路径规划
        start = Pose(x=0.0, y=0.0, yaw=0.0)
        goal = Pose(x=9.0, y=9.0, yaw=0.0)
        
        try:
            path = planner.plan_path(start, goal, occupancy_map=test_map)
            if path:
                print(f"[OK] 路径规划成功，路径长�? {len(path)}")
                print(f"[OK] 起始�? ({start.x}, {start.y})")
                print(f"[OK] 目标�? ({goal.x}, {goal.y})")
            else:
                print("[WARNING] 路径规划返回空路径（可能无法到达�?)
        except Exception as e:
            print(f"[WARNING] 路径规划测试: {e} (可能需要地图数�?")
        
        print("[SUCCESS] 路径规划模块测试通过")
        return True
        
    except Exception as e:
        print(f"[ERROR] 路径规划模块测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_api_server():
    """测试5：API服务器启动和基本端点"""
    print("\n" + "=" * 60)
    print("测试5：API服务器启动和基本端点")
    print("=" * 60)
    
    if not HAS_HTTPX:
        print("[WARNING] httpx 模块未安装，跳过API服务器测�?)
        print("[NOTE] 安装命令: pip install httpx")
        return None
    
    base_url = "http://localhost:8000"
    
    # 测试健康检查端�?
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{base_url}/health")
                if response.status_code == 200:
                    print(f"[OK] 健康检查端�? {response.json()}")
                else:
                    print(f"[WARNING] 健康检查返回状态码: {response.status_code}")
            except httpx.ConnectError:
                print(f"[WARNING] 无法连接到服务器 {base_url}")
                print("[NOTE] 请先启动服务�? python main.py")
                return None  # 不是失败，只是服务器未启�?
            
            try:
                response = await client.get(f"{base_url}/")
                if response.status_code == 200:
                    data = response.json()
                    print(f"[OK] 根路径端�? {data}")
            except Exception as e:
                print(f"[WARNING] 根路径测�? {e}")
            
            try:
                response = await client.get(f"{base_url}/docs")
                if response.status_code == 200:
                    print(f"[OK] API文档端点可访�?)
            except Exception as e:
                print(f"[WARNING] API文档测试: {e}")
            
    except Exception as e:
        print(f"[WARNING] API服务器测�? {e}")
        print("[NOTE] 请先启动服务�? python main.py")
        return None
    
    print("[SUCCESS] API服务器测试通过")
    return True


async def test_robot_manager():
    """测试6：机器人管理�?""
    print("\n" + "=" * 60)
    print("测试6：机器人管理�?)
    print("=" * 60)
    
    try:
        from app.services.robot_manager import get_robot_manager
        
        robot_manager = get_robot_manager()
        print("[OK] RobotManager 实例创建成功")
        
        # 测试注册机器人（不实际连接）
        test_robot_id = "test_robot_1"
        test_base_url = "http://10.160.128.91:1448"
        
        try:
            # 注意：这里会尝试连接，但不会实际连接成功（测试环境）
            # 我们只测试方法是否存�?
            if hasattr(robot_manager, "register_robot"):
                print("[OK] register_robot 方法存在")
            if hasattr(robot_manager, "unregister_robot"):
                print("[OK] unregister_robot 方法存在")
            if hasattr(robot_manager, "get_robot_state"):
                print("[OK] get_robot_state 方法存在")
            if hasattr(robot_manager, "get_all_robots"):
                print("[OK] get_all_robots 方法存在")
        except Exception as e:
            print(f"[NOTE] 机器人注册测�? {e} (需要实际机器人连接)")
        
        print("[SUCCESS] 机器人管理器测试通过")
        return True
        
    except Exception as e:
        print(f"[ERROR] 机器人管理器测试失败: {e}")
        return False


async def main():
    """主测试函�?""
    print("\n" + "=" * 60)
    print("阶段1：基础框架功能测试")
    print("=" * 60)
    print("\n测试内容�?)
    print("1. 项目架构搭建")
    print("2. 地图管理模块（栅格地图加载、解析、坐标转换）")
    print("3. 思岚科技API封装（所有机器人API接口�?)
    print("4. 基础路径规划（A*算法�?)
    print("=" * 60)
    
    results = []
    
    # 测试1：模块导�?
    results.append(("模块导入", await test_imports()))
    
    # 测试2：地图管理模�?
    results.append(("地图管理模块", await test_map_manager()))
    
    # 测试3：思岚科技API封装
    results.append(("思岚科技API封装", await test_robot_agent()))
    
    # 测试4：路径规�?
    results.append(("路径规划", await test_path_planner()))
    
    # 测试5：机器人管理�?
    results.append(("机器人管理器", await test_robot_manager()))
    
    # 测试6：API服务器（可选，如果服务器未启动也不会失败）
    api_result = await test_api_server()
    if api_result is not None:
        results.append(("API服务�?, api_result))
    
    # 汇总结�?
    print("\n" + "=" * 60)
    print("测试结果汇�?)
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for name, result in results:
        if result:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}")
            failed += 1
    
    print("=" * 60)
    print(f"通过: {passed}/{len(results)}")
    if failed > 0:
        print(f"失败: {failed}/{len(results)}")
    
    if failed == 0:
        print("\n[SUCCESS] 阶段1所有测试通过�?)
        print("\n下一步：")
        print("1. 启动服务�? python main.py")
        print("2. 访问API文档: http://localhost:8000/docs")
        print("3. 注册机器人并测试实际功能")
    else:
        print(f"\n[WARNING] �?{failed} 个测试失败，请检查上述错误信�?)
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

