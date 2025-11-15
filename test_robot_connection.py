"""
测试机器人连接诊断脚本
用于诊断为什么PowerShell可以访问但httpx失败
"""
import asyncio
import httpx
import time
from typing import Optional

async def test_connection(url: str, timeout: float = 30.0):
    """
    测试连接到指定URL
    
    Args:
        url: 要测试的URL
        timeout: 超时时间（秒）
    """
    print(f"\n{'='*60}")
    print(f"测试连接: {url}")
    print(f"超时设置: {timeout}秒")
    print(f"{'='*60}")
    
    # 测试1: 使用临时客户端（当前代码使用的方式）
    print("\n[测试1] 使用临时AsyncClient（当前代码使用的方式）")
    try:
        request_timeout = httpx.Timeout(
            timeout=timeout,
            connect=timeout,
            read=timeout
        )
        async with httpx.AsyncClient(
            timeout=request_timeout,
            follow_redirects=True,
            http2=False,
            verify=False
        ) as client:
            start_time = time.time()
            response = await client.get(url, timeout=request_timeout)
            elapsed = time.time() - start_time
            print(f"[OK] 成功！状态码: {response.status_code}")
            print(f"   响应时间: {elapsed:.2f}秒")
            print(f"   响应头: {dict(response.headers)}")
            if response.content:
                print(f"   响应内容长度: {len(response.content)}字节")
                try:
                    content = response.json()
                    print(f"   响应内容: {content}")
                except:
                    print(f"   响应内容（文本）: {response.text[:200]}")
            return True
    except httpx.ConnectError as e:
        print(f"[ERROR] 连接错误: {type(e).__name__}: {str(e)}")
        if hasattr(e, 'request') and hasattr(e.request, 'url'):
            print(f"   请求URL: {e.request.url}")
        return False
    except httpx.TimeoutException as e:
        print(f"[ERROR] 超时错误: {type(e).__name__}: {str(e)}")
        return False
    except Exception as e:
        print(f"[ERROR] 其他错误: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # 测试2: 使用更长的超时时间
    print("\n[测试2] 使用更长的超时时间（60秒）")
    try:
        request_timeout = httpx.Timeout(
            timeout=60.0,
            connect=60.0,
            read=60.0
        )
        async with httpx.AsyncClient(
            timeout=request_timeout,
            follow_redirects=True,
            http2=False,
            verify=False
        ) as client:
            start_time = time.time()
            response = await client.get(url, timeout=request_timeout)
            elapsed = time.time() - start_time
            print(f"[OK] 成功！状态码: {response.status_code}")
            print(f"   响应时间: {elapsed:.2f}秒")
            return True
    except Exception as e:
        print(f"[ERROR] 失败: {type(e).__name__}: {str(e)}")
        return False
    
    # 测试3: 使用同步客户端（对比）
    print("\n[测试3] 使用同步Client（对比测试）")
    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            http2=False,
            verify=False
        ) as client:
            start_time = time.time()
            response = client.get(url)
            elapsed = time.time() - start_time
            print(f"[OK] 成功！状态码: {response.status_code}")
            print(f"   响应时间: {elapsed:.2f}秒")
            return True
    except Exception as e:
        print(f"[ERROR] 失败: {type(e).__name__}: {str(e)}")
        return False

async def test_multiple_urls():
    """测试多个URL"""
    urls = [
        "http://10.160.129.23:1448/api/core/system/v1/robot/health",
        "http://10.160.129.226:1448/api/core/system/v1/robot/health",
        "http://10.160.128.150:1448/api/core/system/v1/robot/health",
        "http://10.160.129.145:1448/api/core/system/v1/robot/health",
    ]
    
    results = {}
    for url in urls:
        result = await test_connection(url, timeout=30.0)
        results[url] = result
        await asyncio.sleep(1)  # 短暂延迟
    
    # 汇总结果
    print(f"\n{'='*60}")
    print("测试结果汇总:")
    print(f"{'='*60}")
    for url, success in results.items():
        status = "[OK] 成功" if success else "[ERROR] 失败"
        print(f"{status}: {url}")
    
    return results

async def test_dns_resolution():
    """测试DNS解析"""
    print(f"\n{'='*60}")
    print("DNS解析测试")
    print(f"{'='*60}")
    
    import socket
    
    hosts = [
        "10.160.129.23",
        "10.160.129.226",
        "10.160.128.150",
        "10.160.129.145",
    ]
    
    for host in hosts:
        try:
            # 尝试反向DNS解析
            name = socket.gethostbyaddr(host)[0]
            print(f"[OK] {host} -> {name}")
        except:
            print(f"[WARN] {host} -> 无法解析（这是正常的，IP地址可能没有反向DNS）")
        
        # 测试端口连接
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, 1448))
            sock.close()
            if result == 0:
                print(f"   [OK] 端口1448可访问")
            else:
                print(f"   [ERROR] 端口1448不可访问 (错误码: {result})")
        except Exception as e:
            print(f"   [ERROR] 端口测试失败: {e}")

async def main():
    """主函数"""
    print("="*60)
    print("机器人连接诊断工具")
    print("="*60)
    
    # 测试DNS解析和端口连接
    await test_dns_resolution()
    
    # 测试HTTP连接
    await test_multiple_urls()
    
    print(f"\n{'='*60}")
    print("诊断完成！")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())

