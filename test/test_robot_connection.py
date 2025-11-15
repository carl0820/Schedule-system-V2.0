"""
测试机器人连接 - 诊断工具
"""
import asyncio
import httpx
import sys


async def test_robot_connection(base_url: str):
    """测试机器人连接"""
    print(f"\n{'='*60}")
    print(f"测试机器人连接: {base_url}")
    print(f"{'='*60}\n")
    
    # 规范化URL
    normalized_url = base_url.strip()
    if not normalized_url.startswith(('http://', 'https://')):
        normalized_url = f"http://{normalized_url}"
    if ':' not in normalized_url.split('//')[1]:
        normalized_url = f"{normalized_url}:1448"
    
    print(f"规范化后的URL: {normalized_url}\n")
    
    # 测试端点
    test_endpoints = [
        "/api/core/slam/v1/localization/pose",
        "/api/core/system/v1/robot/health",
        "/api/core/system/v1/robot/info",
    ]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for endpoint in test_endpoints:
            url = f"{normalized_url}{endpoint}"
            print(f"测试端点: {url}")
            try:
                response = await client.get(url)
                print(f"  ✅ 状态码: {response.status_code}")
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"  ✅ 响应数据: {data}")
                    except Exception as e:
                        print(f"  ⚠️  响应不是JSON格式: {e}")
                        print(f"  📄 响应内容: {response.text[:200]}")
                else:
                    print(f"  ❌ HTTP错误: {response.status_code}")
                    print(f"  📄 响应内容: {response.text[:200]}")
            except httpx.ConnectError as e:
                print(f"  ❌ 连接错误: {e}")
                print(f"  💡 建议: 检查机器人是否运行，网络是否可达")
            except httpx.TimeoutException as e:
                print(f"  ❌ 连接超时: {e}")
                print(f"  💡 建议: 检查网络连接，防火墙设置")
            except httpx.HTTPStatusError as e:
                print(f"  ❌ HTTP错误: {e.response.status_code}")
                print(f"  📄 响应内容: {e.response.text[:200]}")
            except Exception as e:
                print(f"  ❌ 未知错误: {e}")
            print()


async def test_register_api(robot_id: str, base_url: str):
    """测试注册API"""
    print(f"\n{'='*60}")
    print(f"测试注册API")
    print(f"{'='*60}\n")
    
    api_url = "http://localhost:8000/api/robots/register"
    
    print(f"注册端点: {api_url}")
    print(f"参数: robot_id={robot_id}, base_url={base_url}\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                api_url,
                json={"robot_id": robot_id, "base_url": base_url}
            )
            
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text}\n")
            
            if response.status_code == 200:
                print("✅ 注册成功！")
                data = response.json()
                print(f"   机器人ID: {data.get('robot_id')}")
                print(f"   Base URL: {data.get('base_url')}")
            elif response.status_code == 400:
                print("❌ 注册失败: 请求参数错误")
                try:
                    error_data = response.json()
                    print(f"   错误详情: {error_data.get('detail', 'N/A')}")
                except:
                    print(f"   错误详情: {response.text}")
            elif response.status_code == 409:
                print("⚠️  机器人已注册")
                print("   使用以下命令注销后重试:")
                print(f"   DELETE http://localhost:8000/api/robots/{robot_id}")
            else:
                print(f"❌ 注册失败: HTTP {response.status_code}")
                print(f"   响应: {response.text}")
                
        except httpx.ConnectError as e:
            print(f"❌ 无法连接到API服务器: {e}")
            print("   请确保API服务器正在运行: python main.py")
        except Exception as e:
            print(f"❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python test_robot_connection.py <base_url> [robot_id]")
        print("\n示例:")
        print("  python test_robot_connection.py 10.160.128.91")
        print("  python test_robot_connection.py http://10.160.128.91:1448")
        print("  python test_robot_connection.py 10.160.128.91 robot1")
        sys.exit(1)
    
    base_url = sys.argv[1]
    robot_id = sys.argv[2] if len(sys.argv) > 2 else "robot1"
    
    # 先测试机器人连接
    await test_robot_connection(base_url)
    
    # 再测试注册API
    await test_register_api(robot_id, base_url)


if __name__ == "__main__":
    asyncio.run(main())

