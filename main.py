"""
多机器人调度系统 - 主应用
"""
import logging
import os
from logging.handlers import RotatingFileHandler
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import robots, tasks, maps, system, visualization, auth
from app.services.robot_manager import get_robot_manager
from config import settings

# 配置日志 - 同时输出到文件和控制台
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, "app.log")

# 创建日志格式
log_format = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 清除现有的处理器
root_logger.handlers.clear()

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)
root_logger.addHandler(console_handler)

# 文件处理器 - 使用轮转，每个文件最大10MB，保留5个备份
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_format)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info(f"日志文件已配置: {log_file}")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="多机器人调度系统 - 基于思岚科技底盘REST API"
)

# 定制OpenAPI schema，移除start_pose字段，添加安全定义
def custom_openapi():
    # 清除缓存，强制重新生成schema
    if hasattr(app, 'openapi_schema'):
        del app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # 认证已移除，所有API端点无需授权即可调用
    # 不再添加安全定义和安全要求
    
    # 从TaskCreate和MultiActionTaskCreate模型中移除start_pose字段
    if "components" in openapi_schema and "schemas" in openapi_schema["components"]:
        schemas = openapi_schema["components"]["schemas"]
        # 移除TaskCreate中的start_pose
        if "TaskCreate" in schemas and "properties" in schemas["TaskCreate"]:
            schemas["TaskCreate"]["properties"].pop("start_pose", None)
            if "required" in schemas["TaskCreate"]:
                schemas["TaskCreate"]["required"] = [
                    r for r in schemas["TaskCreate"]["required"] 
                    if r != "start_pose"
                ]
        # 移除MultiActionTaskCreate中的start_pose
        if "MultiActionTaskCreate" in schemas and "properties" in schemas["MultiActionTaskCreate"]:
            schemas["MultiActionTaskCreate"]["properties"].pop("start_pose", None)
            if "required" in schemas["MultiActionTaskCreate"]:
                schemas["MultiActionTaskCreate"]["required"] = [
                    r for r in schemas["MultiActionTaskCreate"]["required"] 
                    if r != "start_pose"
                ]
    # 不缓存schema，确保每次请求都重新生成
    app.openapi_schema = openapi_schema
    return openapi_schema

app.openapi = custom_openapi

# 添加中间件，防止OpenAPI JSON被浏览器缓存
@app.middleware("http")
async def no_cache_openapi(request, call_next):
    response = await call_next(request)
    # 如果是OpenAPI相关请求，添加无缓存头
    if request.url.path in ["/openapi.json", "/docs", "/redoc"]:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(robots.router, prefix="/api/robots", tags=["机器人管理"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(maps.router, prefix="/api/maps", tags=["地图管理"])
app.include_router(system.router, prefix="/api/system", tags=["系统监控"])
app.include_router(visualization.router, prefix="/api/visualization", tags=["可视化"])

# HTML页面路由（必须在静态文件挂载之前注册，以确保优先级）
@app.get("/")
async def root():
    """根路径 - 重定向到首页"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.get("/task_list.html")
async def task_list_page():
    """任务列表页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "task_list.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Task list page not found")


@app.get("/task_detail.html")
async def task_detail_page():
    """任务详情页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "task_detail.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Task detail page not found")


@app.get("/robot_list.html")
async def robot_list_page():
    """机器人列表页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "robot_list.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Robot list page not found")


@app.get("/multi_action_task.html")
async def multi_action_task_page():
    """多动作任务创建页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "multi_action_task.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Multi-action task page not found")


@app.get("/map_management.html")
async def map_management_page():
    """地图管理页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "map_management.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Map management page not found")


@app.get("/deadlock_config.html")
async def deadlock_config_page():
    """死锁配置页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "deadlock_config.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        raise HTTPException(status_code=404, detail="Deadlock config page not found")


# 静态文件服务（必须在具体路由之后挂载）
try:
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
except Exception as e:
    logger.warning(f"Failed to mount static files: {e}")


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """应用启动事件：加载已注册的机器人，并启动后台任务
    
    注意：此事件必须快速完成，不能阻塞uvicorn启动。
    所有可能阻塞的操作（如网络连接、文件IO等）都放在后台任务中执行。
    """
    import asyncio
    logger.info("Application startup: Starting initialization (non-blocking)...")
    
    # 立即启动后台初始化任务，不等待完成
    # 这样即使初始化失败，服务也能正常启动并监听端口
    async def initialize_background():
        try:
            logger.info("Application startup: Loading registered robots...")
            robot_manager = get_robot_manager()
            
            # 将机器人加载改为后台任务，不阻塞服务启动
            # 这样即使机器人连接超时，服务也能快速启动并监听端口
            async def load_robots_background():
                try:
                    await robot_manager.load_pending_robots()
                    logger.info("Application startup: Finished loading registered robots")
                except Exception as e:
                    logger.error(f"Failed to load robots in background: {e}", exc_info=True)
            
            # 在后台异步加载机器人，不等待完成
            asyncio.create_task(load_robots_background())
            logger.info("Application startup: Robot loading started in background (non-blocking)")
            
            # 启动任务调度器的后台任务（如果有执行中的任务）
            # 也改为后台任务，不阻塞服务启动
            async def start_task_scheduler_background():
                try:
                    from app.services.task_scheduler import get_task_scheduler
                    task_scheduler = get_task_scheduler()
                    # 在异步上下文中启动后台任务
                    await task_scheduler._start_background_tasks_if_needed_async()
                except Exception as e:
                    logger.error(f"Failed to start task scheduler background tasks: {e}", exc_info=True)
            
            # 在后台异步启动任务调度器，不等待完成
            asyncio.create_task(start_task_scheduler_background())
            logger.info("Application startup: Task scheduler background tasks started in background (non-blocking)")
        except Exception as e:
            logger.error(f"Failed to start background tasks on startup: {e}", exc_info=True)
    
    # 在后台执行初始化，不阻塞启动事件
    # 使用create_task立即返回，不等待完成
    asyncio.create_task(initialize_background())
    logger.info("Application startup: Initialization started in background (non-blocking)")
    # 启动事件立即返回，确保uvicorn能够正常启动


if __name__ == "__main__":
    import sys
    import socket
    
    logger.info(f"Starting uvicorn server on {settings.HOST}:{settings.PORT}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    print(f"[INFO] Starting uvicorn server on {settings.HOST}:{settings.PORT}", flush=True)
    
    # 检查端口是否可用
    def check_port_available(host, port):
        """检查端口是否可用"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result != 0  # 如果连接失败，说明端口可用
        except Exception as e:
            logger.warning(f"Port check failed: {e}")
            return True  # 如果检查失败，假设端口可用
    
    # 检查端口是否被占用
    if not check_port_available(settings.HOST, settings.PORT):
        logger.error(f"Port {settings.PORT} is already in use or not accessible!")
        print(f"[ERROR] Port {settings.PORT} is already in use or not accessible!", flush=True)
        print(f"[INFO] Please stop the process using port {settings.PORT} or use a different port", flush=True)
        print(f"[INFO] To check port usage: Get-NetTCPConnection -LocalPort {settings.PORT}", flush=True)
        sys.exit(1)
    
    try:
        # 确保uvicorn能够正常启动，即使启动事件中有问题
        uvicorn.run(
            "main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=settings.DEBUG,
            log_level="info",
            access_log=True
        )
    except OSError as e:
        if e.winerror == 10013:  # Windows权限错误
            logger.error(f"Permission denied binding to port {settings.PORT}. This may be due to:")
            logger.error("1. Port is reserved by Windows (check with: netsh interface ipv4 show excludedportrange protocol=tcp)")
            logger.error("2. Port is already in use by another process")
            logger.error("3. Firewall or antivirus blocking the port")
            logger.error("4. Need administrator privileges")
            print(f"[ERROR] Permission denied binding to port {settings.PORT}", flush=True)
            print("[INFO] Solutions:", flush=True)
            print("  1. Check if port is reserved: netsh interface ipv4 show excludedportrange protocol=tcp", flush=True)
            print("  2. Check if port is in use: Get-NetTCPConnection -LocalPort 8000", flush=True)
            print("  3. Try using a different port (e.g., 8001) by setting PORT=8001 in .env file", flush=True)
            print("  4. Run PowerShell as Administrator and try again", flush=True)
        else:
            logger.error(f"OS error binding to port {settings.PORT}: {e}", exc_info=True)
            print(f"[ERROR] OS error: {e}", flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        print("[INFO] Server stopped by user", flush=True)
        raise
    except Exception as e:
        logger.error(f"Failed to start uvicorn server: {e}", exc_info=True)
        import traceback
        print(f"[ERROR] Failed to start uvicorn server: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

