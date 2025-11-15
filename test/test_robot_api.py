"""
机器人API测试脚本
用于测试阶段一功能并注册机器人
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000"
ROBOT_IP = "10.160.128.91"
ROBOT_ID = "robot_1"

def test_api(method, endpoint, params=None, json_data=None, expected_status=200):
    """测试API端点"""
    url = f"{BASE_URL}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=10)
        elif method == "POST":
            response = requests.post(url, params=params, json=json_data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, params=params, timeout=10)
        else:
            print(f"❌ 不支持的方法: {method}")
            return False
        
        status_icon = "✅" if response.status_code == expected_status else "❌"
        print(f"{status_icon} {method} {endpoint}")
        print(f"   状态码: {response.status_code}")
        
        if response.status_code == expected_status:
            try:
                data = response.json()
                print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
            except:
                print(f"   响应: {response.text[:200]}")
            return True
        else:
            print(f"   错误: {response.text[:200]}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ {method} {endpoint} - 无法连接到服务器")
        return False
    except Exception as e:
        print(f"❌ {method} {endpoint} - 异常: {str(e)}")
        return False

def main():
    print("=" * 80)
    print("阶段一功能测试 - API验证")
    print("=" * 80)
    print()
    
    results = []
    
    # 1. 系统级API测试
    print("【系统级API】")
    results.append(("健康检查", test_api("GET", "/health")))
    results.append(("系统信息", test_api("GET", "/")))
    print()
    
    # 2. 机器人管理API测试
    print("【机器人管理API】")
    # 2.1 获取机器人列表（应该为空）
    results.append(("获取机器人列表", test_api("GET", "/api/robots/")))
    
    # 2.2 注册机器人
    print(f"\n正在注册机器人: {ROBOT_ID} ({ROBOT_IP}:1448)")
    robot_base_url = f"http://{ROBOT_IP}:1448"
    results.append(("注册机器人", test_api("POST", "/api/robots/register", 
                                            json_data={"robot_id": ROBOT_ID, "base_url": robot_base_url})))
    
    # 2.3 再次获取机器人列表（应该包含注册的机器人）
    results.append(("获取机器人列表（注册后）", test_api("GET", "/api/robots/")))
    
    # 2.4 获取机器人状态
    results.append(("获取机器人状态", test_api("GET", f"/api/robots/{ROBOT_ID}/state")))
    
    # 2.5 获取机器人位置
    results.append(("获取机器人位置", test_api("GET", f"/api/robots/{ROBOT_ID}/pose")))
    print()
    
    # 3. 任务管理API测试
    print("【任务管理API】")
    # 3.1 获取任务列表
    results.append(("获取任务列表", test_api("GET", "/api/tasks/")))
    
    # 3.2 创建任务
    task_data = {
        "target_pose": {
            "x": 5.0,
            "y": 3.0,
            "yaw": 0.0
        },
        "priority": 2
    }
    results.append(("创建任务", test_api("POST", "/api/tasks/", json_data=task_data)))
    
    # 3.3 获取任务列表（创建后）
    results.append(("获取任务列表（创建后）", test_api("GET", "/api/tasks/")))
    
    # 获取任务ID（从列表响应中提取）
    try:
        response = requests.get(f"{BASE_URL}/api/tasks/", timeout=10)
        if response.status_code == 200:
            tasks = response.json()
            if tasks and len(tasks) > 0:
                task_id = tasks[0]["task_id"]
                # 3.4 获取任务详情
                results.append(("获取任务详情", test_api("GET", f"/api/tasks/{task_id}")))
                
                # 3.5 取消任务
                results.append(("取消任务", test_api("DELETE", f"/api/tasks/{task_id}")))
    except Exception as e:
        print(f"⚠️  无法获取任务ID: {e}")
    print()
    
    # 4. 地图管理API测试
    print("【地图管理API】")
    # 4.1 获取地图信息
    results.append(("获取地图信息", test_api("GET", "/api/maps/info", expected_status=[200, 404])))
    
    # 4.2 检查位置
    results.append(("检查位置", test_api("GET", "/api/maps/check", 
                                         params={"x": 1.0, "y": 1.0}, 
                                         expected_status=[200, 500])))
    
    # 4.3 加载地图（从已注册的机器人）
    results.append(("加载地图", test_api("POST", "/api/maps/load", 
                                        params={"robot_id": ROBOT_ID},
                                        expected_status=[200, 404, 500])))
    print()
    
    # 5. 系统监控API测试
    print("【系统监控API】")
    results.append(("获取系统状态", test_api("GET", "/api/system/status")))
    results.append(("获取系统指标", test_api("GET", "/api/system/metrics")))
    print()
    
    # 6. 测试总结
    print("=" * 80)
    print("测试总结")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print()
    print(f"总测试数: {len(results)}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    print(f"通过率: {passed/len(results)*100:.1f}%")
    print("=" * 80)
    
    # 返回退出码
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()

