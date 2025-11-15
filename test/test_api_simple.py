"""
简单的API测试脚本 - 使用Python标准库
"""
import urllib.request
import urllib.parse
import json

BASE_URL = "http://localhost:8000"
ROBOT_IP = "10.160.128.91"
ROBOT_ID = "robot_1"

def test_api(method, endpoint, params=None, json_data=None, expected_status=200):
    """测试API端点"""
    url = f"{BASE_URL}{endpoint}"
    
    if params:
        query_string = urllib.parse.urlencode(params)
        url += f"?{query_string}"
    
    try:
        if method == "GET":
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                data = response.read().decode('utf-8')
        elif method == "POST":
            if json_data:
                body = json.dumps(json_data).encode('utf-8')
                req = urllib.request.Request(url, data=body, method='POST')
                req.add_header('Content-Type', 'application/json')
            else:
                req = urllib.request.Request(url, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                data = response.read().decode('utf-8')
        elif method == "DELETE":
            req = urllib.request.Request(url, method='DELETE')
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                data = response.read().decode('utf-8')
        else:
            print(f"[FAIL] {method} {endpoint} - 不支持的方法")
            return False
        
        expected_codes = expected_status if isinstance(expected_status, list) else [expected_status]
        if status_code in expected_codes:
            print(f"[OK] {method} {endpoint} - 状态码: {status_code}")
            try:
                json_data = json.loads(data)
                print(f"    响应: {json.dumps(json_data, indent=2, ensure_ascii=False)[:200]}")
            except:
                print(f"    响应: {data[:200]}")
            return True
        else:
            print(f"[FAIL] {method} {endpoint} - 状态码: {status_code}, 期望: {expected_status}")
            print(f"    响应: {data[:200]}")
            return False
    except urllib.error.HTTPError as e:
        status_code = e.code
        expected_codes = expected_status if isinstance(expected_status, list) else [expected_status]
        if status_code in expected_codes:
            print(f"[OK] {method} {endpoint} - 状态码: {status_code} (预期状态)")
            return True
        else:
            print(f"[FAIL] {method} {endpoint} - 状态码: {status_code}, 期望: {expected_status}")
            print(f"    错误: {e.read().decode('utf-8')[:200]}")
            return False
    except Exception as e:
        print(f"[FAIL] {method} {endpoint} - 异常: {str(e)}")
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
    results.append(("获取机器人列表", test_api("GET", "/api/robots/")))
    
    print(f"\n正在注册机器人: {ROBOT_ID} ({ROBOT_IP}:1448)")
    robot_base_url = f"http://{ROBOT_IP}:1448"
    results.append(("注册机器人", test_api("POST", "/api/robots/register", 
                                            json_data={"robot_id": ROBOT_ID, "base_url": robot_base_url})))
    
    results.append(("获取机器人列表（注册后）", test_api("GET", "/api/robots/")))
    results.append(("获取机器人状态", test_api("GET", f"/api/robots/{ROBOT_ID}/state")))
    results.append(("获取机器人位置", test_api("GET", f"/api/robots/{ROBOT_ID}/pose")))
    print()
    
    # 3. 任务管理API测试
    print("【任务管理API】")
    results.append(("获取任务列表", test_api("GET", "/api/tasks/")))
    
    task_data = {
        "target_pose": {
            "x": 5.0,
            "y": 3.0,
            "yaw": 0.0
        },
        "priority": 2
    }
    results.append(("创建任务", test_api("POST", "/api/tasks/", json_data=task_data)))
    results.append(("获取任务列表（创建后）", test_api("GET", "/api/tasks/")))
    
    # 获取任务ID
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/tasks/")
        with urllib.request.urlopen(req, timeout=10) as response:
            tasks = json.loads(response.read().decode('utf-8'))
            if tasks and len(tasks) > 0:
                task_id = tasks[0]["task_id"]
                results.append(("获取任务详情", test_api("GET", f"/api/tasks/{task_id}")))
                results.append(("取消任务", test_api("DELETE", f"/api/tasks/{task_id}")))
    except Exception as e:
        print(f"⚠️  无法获取任务ID: {e}")
    print()
    
    # 4. 地图管理API测试
    print("【地图管理API】")
    results.append(("获取地图信息", test_api("GET", "/api/maps/info", expected_status=[200, 404])))
    results.append(("检查位置", test_api("GET", "/api/maps/check", 
                                         params={"x": "1.0", "y": "1.0"}, 
                                         expected_status=[200, 500])))
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
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
    
    print()
    print(f"总测试数: {len(results)}")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    print(f"通过率: {passed/len(results)*100:.1f}%")
    print("=" * 80)
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    exit(main())

