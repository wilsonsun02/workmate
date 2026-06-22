import os
import sys

# PyInstaller：必须在导入 workflow / scheduler 任一模块之前设置 BASE_DIR，否则 workflow.config 会在错误的目录上求值。
if getattr(sys, "frozen", False):
    _serve_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    os.environ.setdefault("BASE_DIR", _serve_exe_dir)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.cors import CORSMiddleware

from api.bootstrap import maybe_run_embedded_mcp_filesystem_stdio
from api.lifecycle import lifespan
from api.routers.desktop import router as desktop_router
from api.routers.mcp import router as mcp_router
from api.routers.quotation import router as quotation_router
from api.routers.knowledge import router as knowledge_router
from api.routers.skills import router as skills_router
from api.runtime_config import inject_cloud_configs, init_runtime_output_base_dir
from api.runtime_state import get_preload_status
from scheduler.routes import router as scheduler_router
from workflow.config import BASE_DIR
from workflow.logging_setup import init_logging

maybe_run_embedded_mcp_filesystem_stdio()
_env_log_level = os.environ.get("WORKMATE_LOG_LEVEL", "").strip().upper()
_serve_log_level = (
    _env_log_level
    if _env_log_level in {"DEBUG", "INFO", "ERROR"}
    else ("ERROR" if getattr(sys, "frozen", False) else "INFO")
)
init_logging(
    "serve",
    base_dir=BASE_DIR,
    level=_serve_log_level,
)

os.chdir(BASE_DIR)
os.environ["DISABLE_WSL_INTEROP"] = "1"

inject_cloud_configs()
init_runtime_output_base_dir()

app = FastAPI(
    title="Workmate API",
    version="1.0",
    description="API for chat, quotation, planning, processing, template management, and login.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8009", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/agent/health")
async def agent_health():
    return {"success": True, "status": "ok", "service": "workmate-agent"}


@app.get("/agent/preload_status")
async def preload_status():
    return {"success": True, "preload": get_preload_status()}


@app.post("/agent/reload")
async def agent_reload():
    from workflow.mcpClient import reset_mcp_client
    from workflow.workflow_core import reset_deep_agent

    inject_cloud_configs()
    await reset_mcp_client()
    await reset_deep_agent()
    return {"success": True, "message": "agent runtime reloaded"}


app.include_router(desktop_router)
app.include_router(quotation_router)
app.include_router(mcp_router)
app.include_router(knowledge_router)
app.include_router(skills_router)

# 挂载模板文件静态目录，供桌面端预览封面图
_template_oss_dir = os.path.join(BASE_DIR, "template_oss")
if os.path.isdir(_template_oss_dir):
    app.mount(
        "/template_oss", StaticFiles(directory=_template_oss_dir), name="template_oss"
    )

try:
    app.include_router(scheduler_router)
    logger.info("定时任务路由注册成功")
except ImportError as error:
    logger.error("定时任务路由注册失败: {}", error)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8009)
