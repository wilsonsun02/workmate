from fastapi import APIRouter
from .routers import (
    config_router,
    mcp_router,
    skills_router,
    prompt_router,
    users_router,
    auth_router,
    sync_router,
    permission_router,
    client_router,
    collab_router,
    monitor_router,
    memory_router,
    knowledge_router,
    template_router,
    security_router,
    scheduler_router,
)

api_router = APIRouter(prefix="/api/admin")

api_router.include_router(auth_router.router, prefix="/auth", tags=["Admin Auth"])
api_router.include_router(client_router.router, prefix="/client", tags=["Admin Client"])
api_router.include_router(config_router.router, prefix="/config", tags=["Admin Config"])
api_router.include_router(mcp_router.router, prefix="/mcp", tags=["Admin MCP"])
api_router.include_router(skills_router.router, prefix="/skills", tags=["Admin Skills"])
api_router.include_router(
    prompt_router.router, prefix="/prompts", tags=["Admin Prompts"]
)
api_router.include_router(users_router.router, prefix="/users", tags=["Admin Users"])
api_router.include_router(sync_router.router, prefix="/sync", tags=["Admin Sync"])
api_router.include_router(
    permission_router.router, prefix="/permissions", tags=["Admin Permissions"]
)
api_router.include_router(
    collab_router.router, prefix="/collab", tags=["Admin Collaboration"]
)
api_router.include_router(
    monitor_router.router, prefix="/monitor", tags=["Admin Monitor"]
)
api_router.include_router(memory_router.router, prefix="/memory", tags=["Admin Memory"])
api_router.include_router(
    knowledge_router.router, prefix="/knowledge", tags=["Admin Knowledge"]
)
api_router.include_router(
    template_router.router, prefix="/templates", tags=["Admin Templates"]
)
api_router.include_router(
    security_router.router, prefix="/security", tags=["Admin Security"]
)
api_router.include_router(
    scheduler_router.router, prefix="/scheduler", tags=["Admin Scheduler"]
)
