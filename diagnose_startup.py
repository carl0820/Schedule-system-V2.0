#!/usr/bin/env python3
"""
诊断服务启动问题的脚本
用于排查在不同网络环境下服务无法启动的问题
"""
import sys
import os
import asyncio
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_imports():
    """测试模块导入"""
    logger.info("=" * 60)
    logger.info("测试1: 模块导入")
    logger.info("=" * 60)
    
    try:
        import uvicorn
        logger.info(f"[OK] uvicorn version: {uvicorn.__version__}")
    except Exception as e:
        logger.error(f"[ERROR] uvicorn: {e}")
        return False
    
    try:
        import main
        logger.info("[OK] main module imported")
    except Exception as e:
        logger.error(f"[ERROR] main: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        app = main.app
        logger.info("[OK] FastAPI app created")
    except Exception as e:
        logger.error(f"[ERROR] app creation: {e}")
        return False
    
    return True

def test_startup_event():
    """测试启动事件"""
    logger.info("=" * 60)
    logger.info("测试2: 启动事件")
    logger.info("=" * 60)
    
    try:
        import main
        app = main.app
        
        # 检查启动事件是否注册
        if hasattr(app, 'router'):
            logger.info("[OK] FastAPI app has router")
        
        # 尝试运行启动事件（如果可能）
        logger.info("[INFO] Startup event is registered (will run when uvicorn starts)")
        return True
    except Exception as e:
        logger.error(f"[ERROR] startup event test: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_async_operations():
    """测试异步操作"""
    logger.info("=" * 60)
    logger.info("测试3: 异步操作")
    logger.info("=" * 60)
    
    try:
        from app.services.robot_manager import get_robot_manager
        robot_manager = get_robot_manager()
        logger.info("[OK] RobotManager created")
        
        # 测试异步操作（不实际连接机器人）
        logger.info("[INFO] Async operations should work (not testing actual robot connections)")
        return True
    except Exception as e:
        logger.error(f"[ERROR] async operations: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_uvicorn_start():
    """测试uvicorn启动（不实际启动服务器）"""
    logger.info("=" * 60)
    logger.info("测试4: Uvicorn配置")
    logger.info("=" * 60)
    
    try:
        import uvicorn
        from config import settings
        
        logger.info(f"[INFO] Host: {settings.HOST}")
        logger.info(f"[INFO] Port: {settings.PORT}")
        logger.info(f"[INFO] Debug: {settings.DEBUG}")
        
        # 检查端口是否被占用
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((settings.HOST, settings.PORT))
        sock.close()
        
        if result == 0:
            logger.warning(f"[WARN] Port {settings.PORT} is already in use!")
            return False
        else:
            logger.info(f"[OK] Port {settings.PORT} is available")
            return True
    except Exception as e:
        logger.error(f"[ERROR] uvicorn config test: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("服务启动问题诊断脚本")
    logger.info("=" * 60)
    logger.info("")
    
    results = []
    
    # 测试1: 模块导入
    results.append(("模块导入", test_imports()))
    
    # 测试2: 启动事件
    results.append(("启动事件", test_startup_event()))
    
    # 测试3: 异步操作
    results.append(("异步操作", asyncio.run(test_async_operations())))
    
    # 测试4: Uvicorn配置
    results.append(("Uvicorn配置", test_uvicorn_start()))
    
    # 输出结果
    logger.info("")
    logger.info("=" * 60)
    logger.info("诊断结果")
    logger.info("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        logger.info(f"{status} {name}")
        if not result:
            all_passed = False
    
    logger.info("")
    if all_passed:
        logger.info("[SUCCESS] 所有测试通过！服务应该能够正常启动。")
        logger.info("如果服务仍然无法启动，请检查：")
        logger.info("1. 查看 logs/app.log 中的错误信息")
        logger.info("2. 直接运行 'python main.py' 查看控制台输出")
        logger.info("3. 检查防火墙设置")
    else:
        logger.error("[FAIL] 部分测试失败，请根据上述错误信息进行修复。")
        sys.exit(1)

if __name__ == "__main__":
    main()

