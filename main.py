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
    """根路径 - 返回HTML页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "message": "HTML file not found"
        }


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
    """应用启动事件：加载已注册的机器人，并启动后台任务"""
    import asyncio
    logger.info("Application startup: Loading registered robots...")
    try:
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
        from app.services.task_scheduler import get_task_scheduler
        task_scheduler = get_task_scheduler()
        # 在异步上下文中启动后台任务
        await task_scheduler._start_background_tasks_if_needed_async()
    except Exception as e:
        logger.error(f"Failed to start background tasks on startup: {e}", exc_info=True)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )

