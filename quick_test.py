"""
快速测试多动作任务执行
"""
import urllib.request
import urllib.error
import json
import time
import os

# 禁用代理，直接连接本地服务
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
if 'http_proxy' in os.environ:
    del os.environ['http_proxy']
if 'https_proxy' in os.environ:
    del os.environ['https_proxy']

BASE_URL = "http://localhost:8092"

def http_post(url, data):
    """发送POST请求"""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

def http_get(url):
    """发送GET请求"""
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

def test_multi_action_task():
    """测试多动作任务"""
    print("=" * 80)
    print("创建多动作测试任务...")
    print("=" * 80)

    # 创建任务（使用坐标导航，避免POI兼容性问题）
    payload = {
        "actions": [
            {
                "action_type": "move_to",
                "target_pose": {
                    "x": 13.43,
                    "y": -2.43,
                    "yaw": 0.0
                },
                "acceptable_precision": 0.3,
                "speed_ratio": 1.0
            },
            {
                "action_type": "wait",
                "wait_duration": 2.0
            },
            {
                "action_type": "move_to",
                "target_pose": {
                    "x": 13.41,
                    "y": -4.12,
                    "yaw": 0.0
                },
                "acceptable_precision": 0.3,
                "speed_ratio": 1.0
            }
        ],
        "priority": 2
    }

    status, response = http_post(f"{BASE_URL}/api/tasks/multi-action", payload)

    if status == 200:
        task = response
        task_id = task['task_id']
        print(f"[OK] 任务创建成功: {task_id}")
        print(f"  状态: {task['status']}")
        print(f"  动作数: {len(task.get('actions', []))}")
        print()

        # 监控30秒
        print("监控任务执行（30秒）...")
        start_time = time.time()
        last_index = -1

        while time.time() - start_time < 30:
            task_status, task_data = http_get(f"{BASE_URL}/api/tasks/{task_id}")
            if task_status == 200:
                current_index = task_data.get('current_action_index', 0)
                status = task_data.get('status')

                if current_index != last_index:
                    print(f"[{int(time.time() - start_time)}s] 动作索引: {current_index}, 状态: {status}")
                    last_index = current_index

                if status in ['COMPLETED', 'FAILED', 'CANCELLED']:
                    print()
                    print(f"任务结束: 状态={status}, 最终动作索引={current_index}")
                    break

            time.sleep(1)

        print()
        print("检查完整日志:")
        print("  tail -f logs/app.log | grep -E \"multi-action|PERIODIC\"")
    else:
        print(f"[ERROR] 任务创建失败: {status}")
        print(f"  {response}")

if __name__ == "__main__":
    test_multi_action_task()
