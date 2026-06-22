from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel
from typing import List, Dict, Any
from admin_api.models.init_db import connect_mysql
from admin_api.services.config_service import ConfigService
from admin_api.services.env_change_log_service import EnvChangeLogService
from admin_api.services.env_file_service import EnvFileService

from loguru import logger

router = APIRouter()


class EnvConfig(BaseModel):
    GOOGLE_API_KEY: str = ""
    MINIMAX_API_KEY: str = ""
    DASHSCOPE_API_KEY: str = ""
    RUNLOOP_API_KEY: str = ""
    OSS_ENDPOINT: str = ""
    OSS_REGION: str = ""
    OSS_BUCKET: str = ""
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_AUTH_MODE: str = "aksk"
    OSS_STS_TOKEN: str = ""
    SKILL_INSTALL_TRIGGER_MODE: str = "hybrid"


class GlobalConfig(BaseModel):
    WECHAT_WORK_ALLOWED_USERS: str = ""
    MCP_READ_ALLOWED_DIRS: str = ""
    MCP_WRITE_ALLOWED_DIRS: str = ""


class EnvFileUpdatePayload(BaseModel):
    values: Dict[str, Any] = {}
    deleted_keys: List[str] = []
    hidden_sections: List[str] = []
    shown_sections: List[str] = []
    hidden_keys: List[str] = []
    shown_keys: List[str] = []


async def _persist_env_updates(
    updates: Dict[str, Any], request: Request
) -> Dict[str, Any]:
    payload = dict(updates or {})
    deleted_keys = payload.pop("__deleted_keys__", [])
    try:
        result = EnvFileService.update_db_values_only(
            payload, deleted_keys=deleted_keys
        )
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
    return result


@router.get("/env-file")
async def get_env_file_config():
    return EnvFileService.get_db_admin_payload()


@router.put("/env-file")
async def update_env_file_config(payload: EnvFileUpdatePayload, request: Request):
    result = await _persist_env_updates(
        {
            **dict(payload.values or {}),
            "__deleted_keys__": list(payload.deleted_keys or []),
        },
        request,
    )
    hidden_sections = [
        str(item).strip()
        for item in (payload.hidden_sections or [])
        if str(item).strip()
    ]
    if hidden_sections:
        EnvFileService.hide_sections(hidden_sections)
    shown_sections = [
        str(item).strip()
        for item in (payload.shown_sections or [])
        if str(item).strip()
    ]
    if shown_sections:
        EnvFileService.show_sections(shown_sections)
    hidden_keys = [
        str(item).strip() for item in (payload.hidden_keys or []) if str(item).strip()
    ]
    if hidden_keys:
        EnvFileService.hide_keys(hidden_keys)
    shown_keys = [
        str(item).strip() for item in (payload.shown_keys or []) if str(item).strip()
    ]
    if shown_keys:
        EnvFileService.show_keys(shown_keys)
    return {
        "success": True,
        "message": "数据库配置保存成功"
        if result["changed_keys"]
        else "没有检测到配置变更",
        "changed_keys": result["changed_keys"],
    }


@router.get("/env-file/logs")
async def get_env_file_logs(limit: int = 50):
    logs = EnvChangeLogService.list_logs(limit=limit)
    return {"success": True, "items": logs, "total": len(logs)}


@router.get("/env")
async def get_env_config():
    return EnvFileService.get_legacy_env_config()


@router.put("/env")
async def update_env_config(config: EnvConfig, request: Request):
    result = await _persist_env_updates(config.model_dump(), request)
    return {
        "success": True,
        "message": "环境变量保存成功"
        if result["changed_keys"]
        else "没有检测到配置变更",
        "changed_keys": result["changed_keys"],
    }


@router.get("/global")
async def get_global_config():
    return EnvFileService.get_legacy_global_config()


@router.put("/global")
async def update_global_config(config: GlobalConfig, request: Request):
    result = await _persist_env_updates(config.model_dump(), request)
    return {
        "success": True,
        "message": "全局配置保存成功"
        if result["changed_keys"]
        else "没有检测到配置变更",
        "changed_keys": result["changed_keys"],
    }


@router.get("/third-party-dbs")
async def get_third_party_dbs():
    config = ConfigService.get_config("third_party_dbs_config", [])
    return config


@router.put("/third-party-dbs")
async def update_third_party_dbs(config: List[Dict[str, Any]] = Body(...)):
    # 保存前，确保所有的 tenant_id 都在 sys_tenants 表中有对应记录
    from admin_api.models.init_db import get_db_connection

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            for tenant in config:
                tenant_id = tenant.get("tenant_id")
                tenant_name = tenant.get("tenant_name", "未命名租户")
                if tenant_id:
                    cursor.execute(
                        """
                        INSERT IGNORE INTO sys_tenants (id, name, description) 
                        VALUES (%s, %s, %s)
                    """,
                        (tenant_id, tenant_name, "Third party sync source"),
                    )
            conn.commit()
        except Exception as e:
            logger.error("Error upserting tenants: {}", e)
        finally:
            conn.close()

    success = ConfigService.set_config(
        "third_party_dbs_config", "third_party_dbs", config, "多租户第三方数据源配置"
    )
    if success:
        return {"success": True, "message": "第三方数据源配置保存成功"}
    raise HTTPException(status_code=500, detail="保存失败")


@router.post("/third-party-dbs/test-connection")
async def test_db_connection(conn_config: Dict[str, Any] = Body(...)):
    try:
        connection = connect_mysql(
            host=conn_config.get("host"),
            port=int(conn_config.get("port", 3306)),
            user=conn_config.get("user"),
            password=conn_config.get("password"),
            database=conn_config.get("database"),
            connect_timeout=5,
        )
        if connection.is_connected():
            connection.close()
            return {"success": True, "message": "连接成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")
