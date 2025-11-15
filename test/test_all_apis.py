"""
全面API测试脚本
验证所有API端点是否正常工作
"""
import asyncio
import httpx
import json
from typing import Dict, List, Optional
from datetime import datetime


class APITester:
    """API测试类"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.results: List[Dict] = []
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    def _log_result(self, method: str, endpoint: str, status: str, 
                   status_code: Optional[int] = None, 
                   error: Optional[str] = None,
                   response: Optional[Dict] = None):
        """记录测试结果"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "endpoint": endpoint,
            "status": status,
            "status_code": status_code,
            "error": error,
            "response": response
        }
        self.results.append(result)
        
        # 打印结果
        status_icon = "✅" if status == "PASS" else "❌"
        print(f"{status_icon} {method} {endpoint} - {status}")
        if status_code:
            print(f"   状态码: {status_code}")
        if error:
            print(f"   错误: {error}")
        if response and status == "PASS":
            print(f"   响应: {json.dumps(response, indent=2, ensure_ascii=False)[:200]}")
    
    async def test_endpoint(self, method: str, endpoint: str, 
                          expected_status = 200,
                          json_data: Optional[Dict] = None,
                          params: Optional[Dict] = None) -> bool:
        """测试单个API端点"""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = await self.client.get(url, params=params)
            elif method == "POST":
                response = await self.client.post(url, json=json_data, params=params)
            elif method == "DELETE":
                response = await self.client.delete(url, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            # 检查状态码
            expected_codes = expected_status if isinstance(expected_status, list) else [expected_status]
            if response.status_code in expected_codes:
                try:
                    response_data = response.json()
                    self._log_result(method, endpoint, "PASS", 
                                   status_code=response.status_code,
                                   response=response_data)
                    return True
                except:
                    # 如果不是JSON响应，检查文本
                    if response.text:
                        self._log_result(method, endpoint, "PASS", 
                                       status_code=response.status_code,
                                       response={"text": response.text[:200]})
                        return True
                    else:
                        self._log_result(method, endpoint, "PASS", 
                                       status_code=response.status_code)
                        return True
            else:
                error_msg = f"Expected status {expected_status}, got {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f": {error_data}"
                except:
                    error_msg += f": {response.text[:200]}"
                self._log_result(method, endpoint, "FAIL", 
                               status_code=response.status_code,
                               error=error_msg)
                return False
        except httpx.ConnectError as e:
            self._log_result(method, endpoint, "FAIL", 
                           error=f"连接错误: {str(e)}")
            return False
        except Exception as e:
            self._log_result(method, endpoint, "FAIL", 
                           error=f"异常: {str(e)}")
            return False
    
    async def test_all_apis(self, robot_url: Optional[str] = None):
        """测试所有API端点"""
        print("=" * 80)
        print("开始API全面测试")
        print("=" * 80)
        print()
        
        # 1. 系统级API
        print("【系统级API】")
        await self.test_endpoint("GET", "/")
        await self.test_endpoint("GET", "/health")
        print()
        
        # 2. 机器人管理API
        print("【机器人管理API】")
        # 2.1 获取机器人列表（应该为空）
        await self.test_endpoint("GET", "/api/robots/")
        
        # 2.2 注册机器人（如果提供了robot_url）
        robot_id = "test_robot_1"
        if robot_url:
            await self.test_endpoint("POST", "/api/robots/register", 
                                   json_data={"robot_id": robot_id, "base_url": robot_url})
            # 2.3 获取机器人列表（应该包含注册的机器人）
            await self.test_endpoint("GET", "/api/robots/")
            # 2.4 获取机器人状态
            await self.test_endpoint("GET", f"/api/robots/{robot_id}/state")
            # 2.5 获取机器人位置
            await self.test_endpoint("GET", f"/api/robots/{robot_id}/pose")
        else:
            print("⚠️  跳过机器人相关测试（未提供robot_url）")
        print()
        
        # 3. 任务管理API
        print("【任务管理API】")
        # 3.1 获取任务列表（应该为空）
        await self.test_endpoint("GET", "/api/tasks/")
        
        # 3.2 创建任务
        task_data = {
            "target_pose": {
                "x": 5.0,
                "y": 3.0,
                "yaw": 0.0
            },
            "priority": 2
        }
        task_created = await self.test_endpoint("POST", "/api/tasks/", 
                                               json_data=task_data)
        
        if task_created:
            # 3.3 获取任务列表（应该包含创建的任务）
            await self.test_endpoint("GET", "/api/tasks/")
            
            # 获取创建的任务ID（需要从响应中提取）
            try:
                response = await self.client.get(f"{self.base_url}/api/tasks/")
                if response.status_code == 200:
                    tasks = response.json()
                    if tasks and len(tasks) > 0:
                        task_id = tasks[0]["task_id"]
                        # 3.4 获取任务信息
                        await self.test_endpoint("GET", f"/api/tasks/{task_id}")
                        # 3.5 取消任务
                        await self.test_endpoint("DELETE", f"/api/tasks/{task_id}")
            except:
                print("⚠️  无法获取任务ID，跳过任务详情和取消测试")
        print()
        
        # 4. 地图管理API
        print("【地图管理API】")
        # 4.1 获取地图信息（可能未加载）
        await self.test_endpoint("GET", "/api/maps/info", expected_status=[200, 404])
        
        # 4.2 检查位置（可能失败，因为地图未加载）
        await self.test_endpoint("GET", "/api/maps/check", 
                               params={"x": 1.0, "y": 1.0}, 
                               expected_status=[200, 500])
        
        # 4.3 加载地图（需要机器人已注册）
        if robot_url:
            await self.test_endpoint("POST", "/api/maps/load", 
                                   params={"robot_id": robot_id},
                                   expected_status=[200, 404, 500])
        else:
            print("⚠️  跳过地图加载测试（未提供robot_url）")
        print()
        
        # 5. 系统监控API
        print("【系统监控API】")
        await self.test_endpoint("GET", "/api/system/status")
        await self.test_endpoint("GET", "/api/system/metrics")
        print()
        
        # 6. 清理：注销机器人
        if robot_url:
            print("【清理】")
            await self.test_endpoint("DELETE", f"/api/robots/{robot_id}", 
                                   expected_status=[200, 404])
            print()
    
    def print_summary(self):
        """打印测试总结"""
        print("=" * 80)
        print("测试总结")
        print("=" * 80)
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        
        print(f"总测试数: {total}")
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"通过率: {passed/total*100:.1f}%")
        print()
        
        if failed > 0:
            print("失败的测试:")
            for result in self.results:
                if result["status"] == "FAIL":
                    print(f"  ❌ {result['method']} {result['endpoint']}")
                    if result.get("error"):
                        print(f"     错误: {result['error']}")
            print()
        
        return passed, failed


async def main():
    """主函数"""
    import sys
    
    # 解析命令行参数
    robot_url = None
    if len(sys.argv) > 1:
        robot_url = sys.argv[1]
        print(f"使用机器人URL: {robot_url}")
    else:
        print("未提供机器人URL，将跳过需要机器人的测试")
        print("用法: python test_all_apis.py [robot_url]")
        print("示例: python test_all_apis.py 10.160.128.91")
    print()
    
    async with APITester() as tester:
        await tester.test_all_apis(robot_url=robot_url)
        passed, failed = tester.print_summary()
        
        # 返回退出码
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())

