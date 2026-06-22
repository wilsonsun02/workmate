import os
from fastapi import APIRouter, HTTPException, Body, Request, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from admin_api.services.config_service import ConfigService
from admin_api.services.env_change_log_service import EnvChangeLogService
from admin_api.services.env_file_service import EnvFileService
from admin_api.services.agent_runtime_service import notify_agent_reload
from admin_api.services.mcp_service import McpService

router = APIRouter()


class LocalToolsConfig(BaseModel):
    MCP_ENABLE_WINDOWS_TOOLS: bool = False
    MCP_ENABLE_ADVANCED_TOOLS: bool = True
    MCP_ENABLE_COMMON_TOOLS: bool = True
    MCP_ENABLE_DOCUMENT_TOOLS: bool = True
    MCP_ENABLE_EXECUTION_TOOLS: bool = True
    MCP_ENABLE_MEDIA_TOOLS: bool = True
    MCP_ENABLE_SEARCH_TOOLS: bool = True
    MCP_ENABLE_WECHAT_TOOLS: bool = True
    MCP_ENABLE_HAPP_TOOLS: bool = True


class McpToolPayload(BaseModel):
    tool_name: str
    tool_description: str = ""
    is_load: bool = True


class McpServerConfigPayload(BaseModel):
    transport: str = "stdio"
    command: str = ""
    args: List[str] = []
    env: Dict[str, str] = {}
    url: str = ""
    headers: Dict[str, str] = {}


class McpServerPayload(BaseModel):
    server_name: str
    server_description: str = ""
    is_load: bool = True
    skills: str = ""
    server_config: McpServerConfigPayload
    tools: List[McpToolPayload] = []


class McpProbePayload(BaseModel):
    server_name: str
    server_config: McpServerConfigPayload


@router.get("/local-tools")
async def get_local_tools_config():
    return EnvFileService.get_legacy_local_tools_config()


@router.put("/local-tools")
async def update_local_tools_config(config: LocalToolsConfig, request: Request):
    try:
        result = EnvFileService.update_db_values_only(config.model_dump())
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))
    if result["changed_keys"]:
        EnvChangeLogService.log_change(
            operator=getattr(request.state, "admin_session", {}) or {},
            source_ip=request.client.host if request.client else "",
            target_file=result["path"],
            changed_keys=result["changed_keys"],
            before_values=result["before_values"],
            after_values=result["after_values"],
        )
    return {
        "success": True,
        "message": "本地工具开关已保存到数据库，可按需手动同步到本地环境"
        if result["changed_keys"]
        else "没有检测到配置变更",
        "changed_keys": result["changed_keys"],
    }


@router.get("/")
async def get_mcp_servers():
    return McpService.list_servers()


@router.get("/paginated")
async def get_mcp_servers_paginated(
    keyword: Optional[str] = None,
    enabled_only: bool = False,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    servers, total = McpService.list_servers_paginated(
        keyword=keyword,
        enabled_only=enabled_only,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "data": servers,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{server_name}")
async def get_mcp_server(server_name: str):
    server = McpService.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    return server


@router.post("/probe")
async def probe_mcp_server(payload: McpProbePayload):
    tools = await McpService.probe_server_tools(
        payload.server_name, payload.server_config.dict()
    )
    return {"success": True, "data": tools}


@router.post("/")
async def create_mcp_server(payload: McpServerPayload):
    try:
        data = McpService.create_server(payload.dict())
        await notify_agent_reload("mcp_servers_created")
        return {"success": True, "message": "MCP 服务创建成功", "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/")
async def save_mcp_servers(config: List[Dict[str, Any]] = Body(...)):
    try:
        data = McpService.replace_all_servers(config)
        await notify_agent_reload("mcp_servers_updated")
        return {"success": True, "message": "MCP配置保存成功", "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{server_name}")
async def update_mcp_server(server_name: str, payload: McpServerPayload):
    try:
        data = McpService.update_server(server_name, payload.dict())
        await notify_agent_reload("mcp_servers_updated")
        return {"success": True, "message": "MCP 服务更新成功", "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{server_id}")
async def delete_mcp_server(server_id: str):
    try:
        deleted = McpService.delete_server_by_id(server_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="MCP 服务不存在")
        await notify_agent_reload("mcp_servers_deleted")
        return {"success": True, "message": "MCP 服务删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{server_name}/allocations")
async def get_mcp_allocations(server_name: str):
    try:
        server = McpService.get_server(server_name)
        if not server:
            raise HTTPException(status_code=404, detail="MCP 服务不存在")
        return {
            "success": True,
            "data": McpService.list_service_allocations(server_name),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
