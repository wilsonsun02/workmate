"""安全合规管理端 API：提供安全拦截日志查询、统计和安全规则配置接口"""

import json
import os

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional

from admin_api.services.security_log_service import (
    query_intercept_logs,
    get_intercept_stats,
)
from admin_api.services.config_service import ConfigService
from admin_api.routers.auth_router import verify_token
from loguru import logger

router = APIRouter()

# 安全规则在 sys_configs 中的 key
_SECURITY_RULES_CONFIG_KEY = "content_security_rules"
_SECURITY_RULES_CONFIG_TYPE = "security"


def _require_auth(authorization: str = Header(None)) -> dict:
    """验证管理员身份"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    token = authorization.removeprefix("Bearer ").strip()
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或令牌已过期")
    return session


def _load_local_security_rules() -> dict:
    """从管理端本地 JSON 文件加载安全规则（fallback）"""
    try:
        from workflow.config import BASE_DIR

        config_path = os.path.join(BASE_DIR, "config", "content_security_rules.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("[安全合规API] 读取本地安全规则文件失败: {}", e)
    return {}


def _save_local_security_rules(rules: dict) -> None:
    """将安全规则写回管理端本地 JSON 文件，保持热加载兼容"""
    try:
        from workflow.config import BASE_DIR

        config_path = os.path.join(BASE_DIR, "config", "content_security_rules.json")
        config_dir = os.path.dirname(config_path)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        logger.info("[安全合规API] 安全规则已写回本地文件: {}", config_path)
    except Exception as e:
        logger.error("[安全合规API] 写回本地安全规则文件失败: {}", e)


@router.get("/rules")
async def get_security_rules(authorization: str = Header(None)):
    """获取安全规则配置（优先从数据库读取，fallback 到本地文件）"""
    _require_auth(authorization)

    try:
        # 优先从数据库读取
        rules = ConfigService.get_config(_SECURITY_RULES_CONFIG_KEY, None)
        if rules is not None:
            return {"success": True, "rules": rules, "source": "database"}

        # fallback 到本地文件
        rules = _load_local_security_rules()
        if rules:
            return {"success": True, "rules": rules, "source": "local_file"}

        return {"success": True, "rules": {}, "source": "none"}
    except Exception as e:
        logger.error("[安全合规API] 获取安全规则失败: {}", e)
        raise HTTPException(status_code=500, detail=f"获取安全规则失败: {str(e)}")


@router.put("/rules")
async def save_security_rules(
    payload: dict,
    authorization: str = Header(None),
):
    """保存安全规则配置到数据库，同时写回管理端本地文件"""
    _require_auth(authorization)

    rules = payload.get("rules")
    if rules is None:
        raise HTTPException(status_code=400, detail="缺少 rules 字段")

    try:
        # 写入数据库
        success = ConfigService.set_config(
            config_key=_SECURITY_RULES_CONFIG_KEY,
            config_type=_SECURITY_RULES_CONFIG_TYPE,
            config_value=rules,
            description="内容安全检查规则配置",
        )
        if not success:
            raise HTTPException(status_code=500, detail="写入数据库失败")

        # 同时写回管理端本地文件，保持热加载兼容
        _save_local_security_rules(rules)

        return {"success": True, "message": "安全规则已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[安全合规API] 保存安全规则失败: {}", e)
        raise HTTPException(status_code=500, detail=f"保存安全规则失败: {str(e)}")


@router.get("/intercept-logs")
async def list_intercept_logs(
    keyword: Optional[str] = None,
    channel: Optional[str] = None,
    intercept_type: Optional[str] = None,
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: str = Header(None),
):
    """分页查询安全拦截日志，支持按关键词/渠道/类型/用户/时间范围筛选"""
    _require_auth(authorization)

    try:
        logs, total = query_intercept_logs(
            keyword=keyword,
            channel=channel,
            intercept_type=intercept_type,
            username=username,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error("[安全合规API] 查询拦截日志失败: {}", e)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/intercept-logs/stats")
async def intercept_stats(authorization: str = Header(None)):
    """获取安全拦截统计概览：总数、今日数、按渠道分布、按类型分布"""
    _require_auth(authorization)

    try:
        stats = get_intercept_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        logger.error("[安全合规API] 获取拦截统计失败: {}", e)
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")
