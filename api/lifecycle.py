import asyncio
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from api.runtime_state import (
    get_mcp_runtime_self_check,
    get_preload_status,
    set_mcp_runtime_self_check,
    set_mcp_preload_status,
)
from scheduler.scheduler import get_scheduler


def _is_true_env(name: str, default: bool = False) -> bool:
    import os

    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _mcp_command_available(command: str) -> bool:
    cmd = str(command or "").strip()
    if not cmd:
        return False
    return shutil.which(cmd) is not None


def run_mcp_runtime_self_check() -> None:
    try:
        from workflow.report_tools import load_final_mcp_config

        final_servers, _, _ = load_final_mcp_config()
        stdio_servers: list[dict] = []
        missing: list[dict] = []
        for server_name, server_cfg in (final_servers or {}).items():
            cfg = server_cfg if isinstance(server_cfg, dict) else {}
            if str(cfg.get("transport", "")).strip().lower() != "stdio":
                continue
            cmd = str(cfg.get("command", "")).strip()
            ok = _mcp_command_available(cmd)
            item = {"server_name": server_name, "command": cmd, "ok": ok}
            stdio_servers.append(item)
            if not ok:
                missing.append(item)

        if missing:
            summary = "MCP stdio dependency check failed: " + ", ".join(
                f"{x['server_name']} (command={x['command']})" for x in missing
            )
            logger.error(summary)
            ok = False
        else:
            summary = (
                f"MCP stdio dependency check passed ({len(stdio_servers)} servers)"
            )
            logger.info(summary)
            ok = True

        set_mcp_runtime_self_check(
            {
                "ok": ok,
                "checked": True,
                "summary": summary,
                "missing_commands": missing,
                "stdio_servers": stdio_servers,
                "missing_count": len(missing),
                "stdio_count": len(stdio_servers),
            }
        )
    except Exception as error:
        summary = f"MCP stdio dependency check error: {error}"
        logger.error(summary)
        set_mcp_runtime_self_check(
            {
                "ok": False,
                "checked": True,
                "summary": summary,
                "missing_commands": [],
                "stdio_servers": [],
                "missing_count": 0,
                "stdio_count": 0,
            }
        )


async def startup_preload_agent() -> None:
    status = get_preload_status()
    enabled = _is_true_env("WORKMATE_PRELOAD_ON_STARTUP", default=False)
    status["enabled"] = enabled
    if not enabled:
        status["done"] = True
        status["ok"] = True
        status["message"] = "preload disabled"
        return

    try:
        from workflow.workflow_core import get_deep_agent

        await get_deep_agent(thread_id="startup_preload", session_id="startup_preload")
        status["done"] = True
        status["ok"] = True
        status["message"] = "preload finished"
        logger.info("[Startup] DeepAgent 预热完成")
    except Exception as error:
        status["done"] = True
        status["ok"] = False
        status["message"] = f"preload failed: {error}"
        logger.error("[Startup] DeepAgent 预热失败: {}", error)


async def startup_preload_mcp() -> None:
    """
    启动时主动预热 MCP 连接，建立所有服务的 session 并缓存工具列表。
    后续任务运行时直接命中缓存，无需再等待握手。
    """
    try:
        from workflow.mcpClient import get_mcp_client, get_mcp_tools

        logger.info("[Startup] 开始预热 MCP 连接...")

        # 建立所有 MCP 服务的 session（并行握手）
        client = await get_mcp_client()
        tools = await get_mcp_tools(add_prefix=False)
        summary = client.get_connect_summary()

        tools_count = len(tools)
        success_servers = summary.get("success", [])
        failed_servers = summary.get("failed", [])

        set_mcp_preload_status(
            {
                "done": True,
                "ok": len(failed_servers) == 0,
                "message": (
                    f"MCP 预热完成: {len(success_servers)} 个服务成功, "
                    f"{len(failed_servers)} 个失败, {tools_count} 个工具"
                ),
                "success_servers": success_servers,
                "failed_servers": failed_servers,
                "tools_count": tools_count,
            }
        )
        logger.info(
            "[Startup] MCP 预热完成: {} 个服务成功, {} 个失败, {} 个工具",
            len(success_servers),
            len(failed_servers),
            tools_count,
        )
    except Exception as error:
        set_mcp_preload_status(
            {
                "done": True,
                "ok": False,
                "message": f"MCP 预热失败: {error}",
                "success_servers": [],
                "failed_servers": [],
                "tools_count": 0,
            }
        )
        logger.error("[Startup] MCP 预热失败: {}", error)


@asynccontextmanager
async def lifespan(app: FastAPI):
    preload_task = asyncio.create_task(startup_preload_agent())
    # MCP 连接预热：启动时即建立所有服务的 session 和工具缓存
    mcp_preload_task = asyncio.create_task(startup_preload_mcp())
    run_mcp_runtime_self_check()
    try:
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("[Startup] 定时任务调度器启动成功")
    except Exception as error:
        logger.error("[Startup] 启动调度器失败: {}", error)
    try:
        from admin_api.models.init_db import init_knowledge_tables

        init_knowledge_tables()
        logger.info("[Startup] 知识库表初始化完成")
    except Exception as error:
        logger.error("[Startup] 知识库表初始化失败: {}", error)
    try:
        from admin_api.models.init_db import init_template_tables

        init_template_tables()
        logger.info("[Startup] 模板表初始化完成")
    except Exception as error:
        logger.error("[Startup] 模板表初始化失败: {}", error)
    try:
        yield
    finally:
        if not preload_task.done():
            preload_task.cancel()
            try:
                await preload_task
            except asyncio.CancelledError:
                pass
        if not mcp_preload_task.done():
            mcp_preload_task.cancel()
            try:
                await mcp_preload_task
            except asyncio.CancelledError:
                pass
        try:
            from workflow.workflow_core import reset_deep_agent

            await reset_deep_agent()
            logger.info("[Shutdown] DeepAgent 已清理")
        except Exception as error:
            logger.error("[Shutdown] 清理 DeepAgent 失败: {}", error)

        try:
            from workflow.mcpClient import reset_mcp_client

            await reset_mcp_client()
            logger.info("[Shutdown] MCP 客户端已重置")
        except Exception as error:
            logger.error("[Shutdown] 重置 MCP 客户端失败: {}", error)

        try:
            scheduler = get_scheduler()
            scheduler.stop(wait=False)
            logger.info("[Shutdown] 调度器已停止")
        except Exception as error:
            logger.error("[Shutdown] 停止调度器失败: {}", error)
