import json
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from admin_api.models.init_db import get_db_connection
from admin_api.services.skill_distribution_service import SkillDistributionService

router = APIRouter()


class McpToolPermission(BaseModel):
    server_name: str
    tool_name: str
    action: str  # 'allow' or 'deny'
    rules: Optional[Dict[str, Any]] = None


class SkillPermission(BaseModel):
    skill_name: str
    action: str  # 'allow' or 'deny'


class SavePermissionsRequest(BaseModel):
    mcp_tools: List[McpToolPermission] = []
    skills: List[SkillPermission] = []


@router.get("/preview/user/{user_id}")
async def preview_user_skill_permissions(user_id: str):
    """预览用户最终可用技能（默认拒绝 + 显式allow生效）"""
    try:
        skills = SkillDistributionService.get_enabled_allowed_skills_for_user(user_id)
        return {"success": True, "data": {"user_id": user_id, "skills": skills}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{owner_type}/{owner_id}")
async def get_permissions(owner_type: str, owner_id: str):
    """获取指定对象（部门/角色/人员）的当前权限配置"""
    if owner_type not in ["user", "role", "dept"]:
        raise HTTPException(status_code=400, detail="Invalid owner_type")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        cursor = conn.cursor(dictionary=True)

        # 获取 MCP 权限
        cursor.execute(
            """
            SELECT server_name, tool_name, action, rules
            FROM sys_mcp_tool_permissions
            WHERE owner_type = %s AND owner_id = %s
        """,
            (owner_type, owner_id),
        )
        mcp_perms = cursor.fetchall()
        for p in mcp_perms:
            p["rules"] = json.loads(p["rules"]) if p["rules"] else None

        # 获取 Skills 权限
        cursor.execute(
            """
            SELECT skill_name, action
            FROM sys_skill_permissions
            WHERE owner_type = %s AND owner_id = %s
        """,
            (owner_type, owner_id),
        )
        skill_perms = cursor.fetchall()

        return {
            "success": True,
            "data": {"mcp_tools": mcp_perms, "skills": skill_perms},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.post("/{owner_type}/{owner_id}")
async def save_permissions(owner_type: str, owner_id: str, req: SavePermissionsRequest):
    """保存指定对象（部门/角色/人员）的权限配置"""
    if owner_type not in ["user", "role", "dept"]:
        raise HTTPException(status_code=400, detail="Invalid owner_type")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        cursor = conn.cursor()

        # 1. 删除旧的 MCP 权限
        cursor.execute(
            "DELETE FROM sys_mcp_tool_permissions WHERE owner_type = %s AND owner_id = %s",
            (owner_type, owner_id),
        )

        # 2. 插入新的 MCP 权限
        if req.mcp_tools:
            mcp_values = []
            for p in req.mcp_tools:
                mcp_values.append(
                    (
                        str(uuid.uuid4()),
                        owner_type,
                        owner_id,
                        p.server_name,
                        p.tool_name,
                        p.action,
                        json.dumps(p.rules) if p.rules else None,
                    )
                )
            cursor.executemany(
                """
                INSERT INTO sys_mcp_tool_permissions
                (id, owner_type, owner_id, server_name, tool_name, action, rules)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
                mcp_values,
            )

        # 3. 删除旧的 Skills 权限
        cursor.execute(
            "DELETE FROM sys_skill_permissions WHERE owner_type = %s AND owner_id = %s",
            (owner_type, owner_id),
        )

        # 4. 插入新的 Skills 权限
        if req.skills:
            skill_values = []
            for p in req.skills:
                skill_values.append(
                    (str(uuid.uuid4()), owner_type, owner_id, p.skill_name, p.action)
                )
            cursor.executemany(
                """
                INSERT INTO sys_skill_permissions
                (id, owner_type, owner_id, skill_name, action)
                VALUES (%s, %s, %s, %s, %s)
            """,
                skill_values,
            )

        conn.commit()
        return {"success": True, "message": "Permissions saved successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
