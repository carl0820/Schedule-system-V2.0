"""
综合测试脚本 - 测试所有功能
"""
import asyncio
import httpx
import sys
import json


async def test_health():
    """测试健康检查"""
    print("\n=== 测试1: 健康检查 ===")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get("http://localhost:8000/health")
            print(f"状态码: {response.status_code}")
            if response.status_code == 200:
                print(f"响应: {response.json()}")
                return True
            else:
                print(f"响应文本: {response.text}")
                return False
        except Exception as e:
            print(f"错误: {e}")
            return False


async def test_register_robot():
    """测试注册机器人"""
    print("\n=== 测试2: 注册机器人 ===")
    robot_id = "robot1"
    base_url = "10.160.128.91"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 先尝试注销（如果已存在）
            try:
                await client.delete(f"http://localhost:8000/api/robots/{robot_id}")
                print("已清理旧注册")
            except:
                pass
            
            # 注册机器人
            response = await client.post(
                "http://localhost:8000/api/robots/register",
                json={"robot_id": robot_id, "base_url": base_url}
            )
            
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[OK] 注册成功: {data.get('robot_id')}")
                return True
            else:
                print(f"[FAIL] 注册失败: {response.text}")
                return False
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_list_robots():
    """测试列出所有机器人"""
    print("\n=== 测试3: 列出所有机器人 ===")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get("http://localhost:8000/api/robots", follow_redirects=True)
            print(f"状态码: {response.status_code}")
            if response.status_code == 200:
                robots = response.json()
                print(f"[OK] 找到 {len(robots)} 个机器人:")
                for robot in robots:
                    print(f"  - {robot.get('robot_id')}: {robot.get('status')}")
                return True
            else:
                print(f"[FAIL] 失败: {response.text}")
                return False
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            return False


async def test_get_robot_state():
    """测试获取机器人状态"""
    print("\n=== 测试4: 获取机器人状态 ===")
    robot_id = "robot1"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"http://localhost:8000/api/robots/{robot_id}/state")
            print(f"状态码: {response.status_code}")
            if response.status_code == 200:
                state = response.json()
                print(f"[OK] 机器人状态:")
                print(f"  - 位置: ({state.get('pose', {}).get('x', 0):.2f}, {state.get('pose', {}).get('y', 0):.2f})")
                print(f"  - 速度: vx={state.get('speed', {}).get('vx', 0):.2f}, vy={state.get('speed', {}).get('vy', 0):.2f}")
                return True
            else:
                print(f"[WARN] 状态码: {response.status_code}, 响应: {response.text}")
                return False
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            return False


async def test_create_task():
    """测试创建任务"""
    print("\n=== 测试5: 创建任务 ===")
    robot_id = "robot1"
    task_data = {
        "robot_id": robot_id,
        "target_pose": {
            "x": 5.0,
            "y": 5.0,
            "theta": 0.0
        },
        "priority": 2
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                "http://localhost:8000/api/tasks",
                json=task_data,
                follow_redirects=True
            )
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text}")
            
            if response.status_code == 200:
                task = response.json()
                print(f"[OK] 任务创建成功: {task.get('task_id')}")
                return task.get('task_id')
            else:
                print(f"[WARN] 任务创建: {response.status_code}, {response.text}")
                return None
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            import traceback
            traceback.print_exc()
            return None


async def test_list_tasks():
    """测试列出所有任务"""
    print("\n=== 测试6: 列出所有任务 ===")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get("http://localhost:8000/api/tasks", follow_redirects=True)
            print(f"状态码: {response.status_code}")
            if response.status_code == 200:
                tasks = response.json()
                print(f"[OK] 找到 {len(tasks)} 个任务:")
                for task in tasks:
                    print(f"  - {task.get('task_id')}: {task.get('status')} (机器人: {task.get('robot_id')})")
                return True
            else:
                print(f"[FAIL] 失败: {response.text}")
                return False
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            return False


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("多机器人调度系统 - 综合测试")
    print("=" * 60)
    
    results = []
    
    # 测试1: 健康检查
    results.append(("健康检查", await test_health()))
    
    # 测试2: 注册机器人
    results.append(("注册机器人", await test_register_robot()))
    
    # 测试3: 列出机器人
    results.append(("列出机器人", await test_list_robots()))
    
    # 测试4: 获取机器人状态
    results.append(("获取机器人状态", await test_get_robot_state()))
    
    # 测试5: 创建任务
    task_id = await test_create_task()
    results.append(("创建任务", task_id is not None))
    
    # 测试6: 列出任务
    results.append(("列出任务", await test_list_tasks()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    for name, result in results:
        status = "[PASS] 通过" if result else "[FAIL] 失败"
        print(f"{name}: {status}")
    print(f"\n总计: {passed}/{total} 通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

