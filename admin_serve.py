import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

# PyInstaller：必须在导入 workflow / admin_api 前设置 BASE_DIR，保持与 serve.py 一致。
if getattr(sys, "frozen", False):
    _admin_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    os.environ.setdefault("BASE_DIR", _admin_exe_dir)

from admin_api import api_router as admin_api_router
from admin_api.services.auth_interceptor import (
    is_admin_auth_exempt_path,
    require_admin_auth_request,
)
from workflow.config import BASE_DIR
from workflow.logging_setup import init_logging

_env_log_level = os.environ.get("WORKMATE_ADMIN_LOG_LEVEL", "").strip().upper()
_fallback_log_level = os.environ.get("WORKMATE_LOG_LEVEL", "").strip().upper()
_admin_log_level = (
    _env_log_level
    if _env_log_level in {"DEBUG", "INFO", "ERROR"}
    else (
        _fallback_log_level
        if _fallback_log_level in {"DEBUG", "INFO", "ERROR"}
        else ("ERROR" if getattr(sys, "frozen", False) else "INFO")
    )
)

init_logging("admin_serve", base_dir=BASE_DIR, level=_admin_log_level)

os.chdir(BASE_DIR)
os.environ["DISABLE_WSL_INTEROP"] = "1"


app = FastAPI(
    title="Workmate Admin API",
    version="1.0",
    description="Standalone admin API for Workmate configuration, users, permissions, clients, and skills.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/admin/health")
async def admin_health():
    return {"success": True, "status": "ok", "service": "workmate-admin"}


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    if request.method != "OPTIONS" and not is_admin_auth_exempt_path(request.url.path):
        try:
            await require_admin_auth_request(request)
        except HTTPException as error:
            headers = dict(error.headers or {})
            origin = request.headers.get("origin")
            if origin:
                headers.setdefault("Access-Control-Allow-Origin", origin)
                headers.setdefault("Access-Control-Allow-Credentials", "true")
                headers.setdefault("Vary", "Origin")
            return JSONResponse(
                status_code=error.status_code,
                content={"detail": error.detail},
                headers=headers,
            )
    return await call_next(request)


app.include_router(admin_api_router)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WORKMATE_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("WORKMATE_ADMIN_PORT", "8010"))
    uvicorn.run(app, host=host, port=port)
