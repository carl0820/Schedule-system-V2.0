"""
测试机器人注册功能
"""
import asyncio
import httpx
import sys


async def test_register():
    """测试机器人注册"""
    robot_id = "robot1"
    base_url = "10.160.128.91"  # 或者使用完整URL: "http://10.160.128.91:1448"
    api_url = "http://localhost:8000/api/robots/register"
    
    print(f"正在注册机器人: {robot_id} at {base_url}")
    print(f"API 端点: {api_url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 测试注册（使用JSON请求体）
            response = await client.post(
                api_url,
                json={"robot_id": robot_id, "base_url": base_url}
            )
            
            print(f"\n状态码: {response.status_code}")
            print(f"响应: {response.text}")
            
            if response.status_code == 200:
                print("\n✅ 注册成功！")
                data = response.json()
                print(f"   机器人ID: {data.get('robot_id')}")
                print(f"   Base URL: {data.get('base_url')}")
            elif response.status_code == 409:
                print("\n⚠️  机器人已注册，先注销...")
                # 尝试注销
                unregister_url = f"http://localhost:8000/api/robots/{robot_id}"
                unregister_response = await client.delete(unregister_url)
                print(f"注销响应: {unregister_response.status_code}")
                if unregister_response.status_code == 200:
                    print("注销成功，重新注册...")
                    # 重新注册（使用JSON请求体）
                    response = await client.post(
                        api_url,
                        json={"robot_id": robot_id, "base_url": base_url}
                    )
                    print(f"\n重新注册状态码: {response.status_code}")
                    print(f"重新注册响应: {response.text}")
            else:
                print("\n❌ 注册失败")
                print(f"   错误详情: {response.text}")
                
        except httpx.ConnectError as e:
            print(f"\n❌ 无法连接到 API 服务器: {e}")
            print("   请确保 API 服务器正在运行: python main.py")
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_register())

