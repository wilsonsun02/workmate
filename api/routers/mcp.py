from contextlib import AsyncExitStack
from typing import List

from fastapi import APIRouter, Body, HTTPException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from loguru import logger

from admin_api.services.config_service import ConfigService

router = APIRouter(tags=["mcp"])


@router.get("/mcp/config")
async def get_mcp_server_config():
    return ConfigService.get_config("mcp_servers", [])


@router.post("/mcp/config")
async def save_mcp_server_config(config: List[dict] = Body(...)):
    try:
        success = ConfigService.set_config(
            "mcp_servers", "mcp", config, "MCP服务器配置"
        )
        if not success:
            raise HTTPException(status_code=500, detail="保存失败")

        from workflow.mcpClient import reset_mcp_client

        await reset_mcp_client()
        return {"success": True, "message": "保存成功"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/mcp/add_server")
async def add_mcp_server(new_server_item: dict):
    try:
        server_name = new_server_item.get("server_name")
        server_config = new_server_item.get("server_config")
        if not server_name or not server_config:
            raise HTTPException(status_code=400, detail="缺少服务名称或配置信息")

        probe_config = {server_name: server_config}
        new_tools_data = []
        try:
            async with AsyncExitStack() as stack:
                probe_client = MultiServerMCPClient(probe_config)
                session = await stack.enter_async_context(
                    probe_client.session(server_name)
                )
                probe_tools = await load_mcp_tools(session, server_name=server_name)
                for tool in probe_tools:
                    new_tools_data.append(
                        {"name": tool.name, "description": tool.description}
                    )
                logger.info("成功探测到新 MCP 服务: {}", server_name)
        except Exception as probe_err:
            logger.error("探测新服务失败: {}", probe_err)
            raise HTTPException(
                status_code=422, detail=f"无法连接到该服务: {str(probe_err)}"
            )

        full_config = ConfigService.get_config("mcp_servers", [])
        existing_index = next(
            (i for i, s in enumerate(full_config) if s["server_name"] == server_name),
            None,
        )
        if existing_index is not None:
            full_config[existing_index] = new_server_item
        else:
            full_config.append(new_server_item)
        ConfigService.set_config("mcp_servers", "mcp", full_config, "MCP服务器配置")

        from workflow.mcpClient import reset_mcp_client

        await reset_mcp_client()
        return {
            "success": True,
            "server_name": server_name,
            "added_tools": new_tools_data,
        }
    except Exception as error:
        logger.error("Add Server Logic Error: {}", error)
        raise HTTPException(status_code=500, detail=str(error))
