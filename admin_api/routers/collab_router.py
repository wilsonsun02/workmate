import re

from fastapi import APIRouter, Body, HTTPException, Header, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import os
import json
from urllib.parse import unquote
from admin_api.models.init_db import get_db_connection
from admin_api.routers.auth_router import verify_token
from admin_api.routers.client_router import manager
from admin_api.services.user_service import UserService
from admin_api.services.collab_notify_service import (
    enrich_chain_summary,
    get_read_state,
    mark_read,
    notify_chain_completed,
    notify_initiator_step_progress,
    notify_step_rejected,
    notify_task_assigned,
)
from workflow.collab_attachment_preprocess import (
    format_task_prompt_for_display as _format_task_prompt_for_display,
)
from loguru import logger

router = APIRouter()

# 配置附件存储目录
COLLAB_UPLOAD_DIR = os.getenv("COLLAB_UPLOAD_DIR", "./collab_uploads")
os.makedirs(COLLAB_UPLOAD_DIR, exist_ok=True)


def _normalize_collab_filename(raw: object) -> str:
    """Decode percent-encoded upload names (e.g. %E5%A1%91...docx)."""
    name = str(raw or "").strip() or "attachment"
    if "%" not in name:
        return name
    try:
        decoded = unquote(name)
        if decoded.strip():
            return decoded.strip()
    except Exception:
        pass
    return name


def _fetch_attachments_grouped_by_step(cursor, chain_id: str) -> Dict[int, list]:
    cursor.execute(
        """
        SELECT a.*, s.step_index
        FROM collab_attachments a
        JOIN collab_steps s ON a.step_id = s.id
        WHERE a.chain_id = %s
        ORDER BY s.step_index ASC, a.created_at ASC
        """,
        (chain_id,),
    )
    grouped: Dict[int, list] = {}
    for row in cursor.fetchall():
        idx = int(row["step_index"])
        normalized = {
            **row,
            "original_filename": _normalize_collab_filename(
                row.get("original_filename")
            ),
        }
        grouped.setdefault(idx, []).append(normalized)
    return grouped


def _format_step_attachment_summary(step_index: int, grouped: Dict[int, list]) -> str:
    items = grouped.get(step_index) or []
    if not items:
        return "(暂无附件)"
    names = [str(a.get("original_filename") or "附件") for a in items]
    return "、".join(names) + f"（共 {len(names)} 个，见协同附件/本地协同目录）"


def _require_step_has_attachments(cursor, chain_id: str, step_id: str) -> None:
    """Block step completion / handoff when the step has no uploaded attachments."""
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM collab_attachments
        WHERE chain_id = %s AND step_id = %s
        """,
        (chain_id, step_id),
    )
    row = cursor.fetchone()
    if isinstance(row, dict):
        count = int(row.get("cnt") or 0)
    else:
        count = int(row[0]) if row else 0
    if count < 1:
        raise HTTPException(
            status_code=400,
            detail="本步骤尚未上传任何附件，请先上传附件后再流转到下一步",
        )


def _validate_step_attachment_ids(
    cursor,
    chain_id: str,
    step_id: str,
    attachment_ids: Optional[List[str]],
) -> None:
    if not attachment_ids:
        return
    ids = [str(i).strip() for i in attachment_ids if str(i).strip()]
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id FROM collab_attachments
        WHERE chain_id = %s AND step_id = %s AND id IN ({placeholders})
        """,
        (chain_id, step_id, *ids),
    )
    found = {str(r["id"]) for r in cursor.fetchall()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"附件不属于当前步骤或不存在: {', '.join(missing[:5])}",
        )


def _is_chain_collaborator(
    cursor,
    chain_id: str,
    user_id: str,
    chain: Optional[dict] = None,
) -> bool:
    """Initiator or any step assignee on the chain."""
    uid = str(user_id or "").strip()
    cid = str(chain_id or "").strip()
    if not uid or not cid:
        return False
    if chain and str(chain.get("initiator_user_id") or "") == uid:
        return True
    if not chain:
        cursor.execute(
            "SELECT initiator_user_id FROM collab_chains WHERE id = %s",
            (cid,),
        )
        row = cursor.fetchone()
        if row and str(row.get("initiator_user_id") or "") == uid:
            return True
    cursor.execute(
        """
        SELECT 1 FROM collab_steps
        WHERE chain_id = %s AND assignee_user_id = %s
        LIMIT 1
        """,
        (cid, uid),
    )
    return cursor.fetchone() is not None


def _assert_can_upload_to_step(cursor, step: dict, chain: dict, user_id: str) -> None:
    cid = str(chain.get("id") or "").strip()
    if not _is_chain_collaborator(cursor, cid, user_id, chain):
        raise HTTPException(status_code=403, detail="仅流程协作者可上传附件")
    if str(step.get("status") or "") != "running":
        raise HTTPException(status_code=400, detail="仅能在进行中的步骤上传附件")
    if str(step.get("assignee_user_id") or "") != user_id:
        raise HTTPException(status_code=403, detail="仅当前步骤执行人可上传附件")


def _user_can_delete_attachment(
    cursor,
    attachment: dict,
    step: Optional[dict],
    chain: dict,
    user_id: str,
) -> bool:
    if str(chain.get("status") or "") == "completed":
        return False
    if not step or str(step.get("status") or "") != "running":
        return False
    cid = str(chain.get("id") or attachment.get("chain_id") or "").strip()
    if not _is_chain_collaborator(cursor, cid, user_id, chain):
        return False
    if str(attachment.get("uploader_user_id") or "") == user_id:
        return True
    if str(step.get("assignee_user_id") or "") == user_id:
        return True
    return False


def get_current_user(authorization: str = Header(None)) -> dict:
    """从 Authorization header 中获取当前用户"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    token = authorization.removeprefix("Bearer ").strip()
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或令牌已过期")
    return session


# ========== 请求/响应模型 ==========


class StepCreate(BaseModel):
    assignee_user_id: str
    task_prompt: str


class ChainCreate(BaseModel):
    title: str
    description: Optional[str] = None
    steps: List[StepCreate]


class CompleteStepRequest(BaseModel):
    result_summary: str
    result_detail: Optional[str] = None
    attachment_ids: Optional[List[str]] = None
    relay_note: Optional[str] = None


class RejectStepRequest(BaseModel):
    reject_reason: str


# ========== 同事查询 API ==========


def _text_field(value: object) -> str:
    """Normalize optional DB text fields (NULL -> empty string)."""
    return str(value or "").strip()


_COLLAB_AUTOMATION_USERNAME_PREFIXES = ("rmms", "observer")


def _is_collab_automation_user(user: dict) -> bool:
    """Return True for bot/helper accounts that must not be collab step assignees."""
    username = _text_field(user.get("username")).lower()
    if not username:
        return False
    if username.endswith("helper"):
        return True
    return any(
        username.startswith(prefix) for prefix in _COLLAB_AUTOMATION_USERNAME_PREFIXES
    )


def _assert_collaborator_assignable(user: dict) -> None:
    if _is_collab_automation_user(user):
        username = _text_field(user.get("username")) or "该用户"
        raise HTTPException(
            status_code=400,
            detail=(
                f"用户 {username} 为系统/机器人账号，不能作为协同步骤执行人。"
                "请使用 search_colleagues 选择真实同事。"
            ),
        )


def _resolve_user_display_name(user_id: str, fallback: str = "") -> str:
    """Resolve sys_users.name for UI; fall back to username or stored fallback."""
    user = UserService.get_user_by_id(user_id)
    if user:
        name = _text_field(user.get("name"))
        if name:
            return name
        username = _text_field(user.get("username"))
        if username:
            return username
    return _text_field(fallback)


def _enrich_collab_steps_display_names(steps: list) -> list:
    enriched = []
    for row in steps:
        step = dict(row)
        step["assignee_name"] = _resolve_user_display_name(
            str(step.get("assignee_user_id") or ""),
            str(step.get("assignee_username") or ""),
        )
        enriched.append(step)
    return enriched


def _resolve_assignee_user(user_ref: str) -> dict:
    """
    Resolve assignee from sys_users.id (UUID) or username.

    MCP/Agent 有时会把 username 填入 assignee_user_id 字段，此处做兼容。
    """
    ref = str(user_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="步骤指派人不能为空")

    user = UserService.get_user_by_id(ref)
    if user:
        _assert_collaborator_assignable(user)
        return user

    user = UserService.get_normal_user_by_username(ref)
    if user:
        _assert_collaborator_assignable(user)
        return user

    ref_lower = ref.lower()
    for candidate in UserService.get_users():
        if _text_field(candidate.get("username")).lower() == ref_lower:
            _assert_collaborator_assignable(candidate)
            return candidate

    raise HTTPException(
        status_code=400,
        detail=f"找不到用户 {ref}，请使用 search_colleagues 返回的 user_id（UUID）",
    )


def _activate_collab_chain_first_step(cursor, chain_id: str) -> dict:
    """Set chain status to running and activate step 1 (caller commits)."""
    cursor.execute(
        """
        UPDATE collab_chains
        SET status = 'running', current_step = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (chain_id,),
    )
    cursor.execute(
        "SELECT * FROM collab_steps WHERE chain_id = %s AND step_index = 1",
        (chain_id,),
    )
    first_step = cursor.fetchone()
    if not first_step:
        raise HTTPException(status_code=500, detail="协同链第一步不存在")

    from workflow.collab_attachment_preprocess import finalize_collab_task_prompt

    rendered_first = finalize_collab_task_prompt(
        first_step.get("task_prompt") or "",
        chain_id=chain_id,
        step_index=1,
    )
    cursor.execute(
        """
        UPDATE collab_steps
        SET status = 'running', task_prompt_rendered = %s, started_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (rendered_first, first_step["id"]),
    )
    first_step = dict(first_step)
    first_step["task_prompt_rendered"] = rendered_first
    return first_step


async def _notify_first_step_assigned(
    chain_id: str,
    chain_title: str,
    first_step: dict,
    from_username: str,
) -> None:
    await notify_task_assigned(
        assignee_user_id=first_step["assignee_user_id"],
        chain_id=chain_id,
        chain_title=chain_title,
        step_id=first_step["id"],
        step_index=1,
        from_username=from_username,
        relay_note=None,
        task_prompt_rendered=first_step.get("task_prompt_rendered"),
    )


@router.get("/colleagues")
async def get_colleagues(
    keyword: Optional[str] = None,
    dept_name: Optional[str] = None,
    role_name: Optional[str] = None,
    status: Optional[int] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: str = Header(None),
):
    """查询同事列表"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    users, total = UserService.list_users_paginated(
        keyword=keyword,
        dept_name=dept_name,
        role_name=role_name,
        status=status,
        limit=limit,
        offset=offset,
    )
    colleagues = []

    for user in users:
        if _is_collab_automation_user(user):
            continue

        username = _text_field(user.get("username"))
        raw_name = _text_field(user.get("name_raw"))
        display_name = raw_name or _text_field(user.get("name")) or username
        user_role = _text_field(user.get("role_name"))
        user_dept = _text_field(user.get("dept_name"))

        # 关键词过滤
        if keyword:
            keyword_lower = keyword.lower()
            if (
                keyword_lower not in display_name.lower()
                and keyword_lower not in username.lower()
                and keyword_lower not in user_role.lower()
                and keyword_lower not in user_dept.lower()
            ):
                continue

        # 部门过滤
        if dept_name and dept_name not in user_dept:
            continue

        # 角色过滤
        if role_name and role_name not in user_role:
            continue

        # 从 ConnectionManager 获取在线状态和工作状态
        user_status = manager.get_user_status(user["id"])

        colleagues.append(
            {
                "user_id": user["id"],
                "username": username,
                "name": display_name,
                "is_self": user["id"] == current_user_id,
                "role_name": user_role,
                "dept_name": user_dept,
                "status": user.get("status", 1),
                "is_online": user_status["is_online"],
                "work_status": user_status["work_status"],
                "current_task": user_status["current_task"],
            }
        )

    return {
        "success": True,
        "colleagues": colleagues,
        "total": len(colleagues),
        "limit": limit,
        "offset": offset,
    }


# ========== 协同任务链 API ==========


@router.post("/chains")
async def create_collab_chain(chain: ChainCreate, authorization: str = Header(None)):
    """创建协同任务链"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]
    current_username = current_user["username"]

    # 验证步骤数量
    if len(chain.steps) < 2 or len(chain.steps) > 5:
        raise HTTPException(status_code=400, detail="协同链需要 2-5 个步骤")

    resolved_assignees = [
        _resolve_assignee_user(s.assignee_user_id) for s in chain.steps
    ]

    # 验证相邻步骤不能是同一人
    for i in range(1, len(resolved_assignees)):
        if resolved_assignees[i]["id"] == resolved_assignees[i - 1]["id"]:
            raise HTTPException(
                status_code=400, detail=f"第 {i} 步和第 {i + 1} 步不能是同一人"
            )

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)
        chain_id = str(uuid.uuid4())

        # 创建链
        cursor.execute(
            """
            INSERT INTO collab_chains 
            (id, title, description, initiator_user_id, initiator_username, status, total_steps)
            VALUES (%s, %s, %s, %s, %s, 'defining', %s)
        """,
            (
                chain_id,
                chain.title,
                chain.description,
                current_user_id,
                current_username,
                len(chain.steps),
            ),
        )

        # 创建步骤
        for i, step in enumerate(chain.steps):
            step_id = str(uuid.uuid4())
            assignee = resolved_assignees[i]
            assignee_id = assignee["id"]
            assignee_username = _text_field(assignee.get("username"))

            cursor.execute(
                """
                INSERT INTO collab_steps
                (id, chain_id, step_index, assignee_user_id, assignee_username, task_prompt, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """,
                (
                    step_id,
                    chain_id,
                    i + 1,
                    assignee_id,
                    assignee_username,
                    step.task_prompt,
                ),
            )

        first_step = _activate_collab_chain_first_step(cursor, chain_id)
        conn.commit()

        await _notify_first_step_assigned(
            chain_id=chain_id,
            chain_title=chain.title,
            first_step=first_step,
            from_username=current_username,
        )

        return {
            "success": True,
            "chain_id": chain_id,
            "message": "协同链创建成功，已进入步骤 1",
            "status": "running",
            "current_step": 1,
            "step_id": first_step["id"],
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"创建协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.get("/chains")
async def get_my_chains(
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: str = Header(None),
):
    """获取我参与的协同任务链"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        base_where = """
            FROM collab_chains c
            WHERE c.initiator_user_id = %s
            OR EXISTS (
                SELECT 1 FROM collab_steps s 
                WHERE s.chain_id = c.id AND s.assignee_user_id = %s
            )
        """
        params = [current_user_id, current_user_id]
        if status:
            base_where += " AND c.status = %s"
            params.append(status)

        cursor.execute(
            f"SELECT COUNT(DISTINCT c.id) AS total {base_where}",
            tuple(params),
        )
        total_row = cursor.fetchone() or {}
        total = int(total_row.get("total") or 0)

        cursor.execute(
            f"""
            SELECT DISTINCT c.* {base_where}
            ORDER BY c.updated_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )

        chains = cursor.fetchall()
        steps_by_chain: Dict[str, list] = {}
        read_state_by_chain: Dict[str, bool] = {}
        if chains:
            chain_ids = [c["id"] for c in chains if c.get("id")]
            if chain_ids:
                placeholders = ",".join(["%s"] * len(chain_ids))
                cursor.execute(
                    f"SELECT * FROM collab_steps WHERE chain_id IN ({placeholders}) ORDER BY step_index",
                    tuple(chain_ids),
                )
                for s in cursor.fetchall():
                    steps_by_chain.setdefault(s["chain_id"], []).append(s)
                cursor.execute(
                    f"""
                    SELECT chain_id, unread_at, read_at
                    FROM collab_user_chain_state
                    WHERE user_id = %s AND chain_id IN ({placeholders})
                    """,
                    tuple([current_user_id] + chain_ids),
                )
                for row in cursor.fetchall():
                    unread_at = row.get("unread_at")
                    read_at = row.get("read_at")
                    read_state_by_chain[str(row.get("chain_id") or "")] = bool(
                        unread_at and (read_at is None or unread_at > read_at)
                    )

        enriched = [
            enrich_chain_summary(
                c,
                current_user_id,
                steps_by_chain,
                read_state_by_chain=read_state_by_chain,
            )
            for c in chains
        ]
        return {
            "success": True,
            "chains": enriched,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(f"查询协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.get("/chains/{chain_id}")
async def get_chain_detail(chain_id: str, authorization: str = Header(None)):
    """获取协同任务链详情"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (chain_id,))
        chain = cursor.fetchone()
        if not chain:
            raise HTTPException(status_code=404, detail="协同链不存在")

        if chain["initiator_user_id"] != current_user_id:
            cursor.execute(
                """
                SELECT 1 FROM collab_steps
                WHERE chain_id = %s AND assignee_user_id = %s
                LIMIT 1
                """,
                (chain_id, current_user_id),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=403, detail="无权访问此协同链")

        cursor.execute(
            "SELECT * FROM collab_steps WHERE chain_id = %s ORDER BY step_index",
            (chain_id,),
        )
        steps = cursor.fetchall()
        steps = _enrich_collab_steps_display_names(
            [
                {
                    **row,
                    "task_prompt": _strip_output_dir_instruction(
                        row.get("task_prompt")
                    ),
                    "task_prompt_rendered": _format_task_prompt_for_display(
                        _strip_output_dir_instruction(row.get("task_prompt_rendered"))
                    ),
                }
                for row in steps
            ]
        )

        cursor.execute(
            "SELECT * FROM collab_attachments WHERE chain_id = %s", (chain_id,)
        )
        attachments = [
            {
                **row,
                "original_filename": _normalize_collab_filename(
                    row.get("original_filename")
                ),
            }
            for row in cursor.fetchall()
        ]

        read_state = get_read_state(current_user_id, chain_id)
        chain_out = dict(chain)
        chain_out["initiator_name"] = _resolve_user_display_name(
            str(chain.get("initiator_user_id") or ""),
            str(chain.get("initiator_username") or ""),
        )
        chain_out["is_unread"] = read_state.get("is_unread", False)

        return {
            "success": True,
            "chain": chain_out,
            "steps": steps,
            "attachments": attachments,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询协同链详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn.is_connected():
            conn.close()


@router.post("/chains/{chain_id}/start")
async def start_chain(chain_id: str, authorization: str = Header(None)):
    """启动协同任务链"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        # 查询链信息
        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (chain_id,))
        chain = cursor.fetchone()
        if not chain:
            raise HTTPException(status_code=404, detail="协同链不存在")

        # 验证权限（只有发起者可以启动）
        if chain["initiator_user_id"] != current_user_id:
            raise HTTPException(status_code=403, detail="只有发起者可以启动协同链")

        if chain["status"] != "defining":
            raise HTTPException(status_code=400, detail="协同链状态不正确")

        first_step = _activate_collab_chain_first_step(cursor, chain_id)
        conn.commit()

        await _notify_first_step_assigned(
            chain_id=chain_id,
            chain_title=chain.get("title") or "",
            first_step=first_step,
            from_username=current_user.get("username") or "",
        )

        return {
            "success": True,
            "message": "协同链已启动",
            "chain_id": chain_id,
            "step_id": first_step["id"],
            "status": "running",
            "current_step": 1,
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"启动协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.post("/chains/{chain_id}/read")
async def mark_chain_read(chain_id: str, authorization: str = Header(None)):
    """标记协同链为已读（清除 NEW 状态）"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM collab_chains WHERE id = %s", (chain_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="协同链不存在")

        if not _user_can_access_chain(cursor, chain_id, current_user_id):
            raise HTTPException(status_code=403, detail="无权访问此协同链")

        mark_read(current_user_id, chain_id)
        return {"success": True, "message": "已标记为已读"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记协同链已读失败: {e}")
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def _user_can_access_chain(cursor, chain_id: str, user_id: str) -> bool:
    cursor.execute(
        "SELECT initiator_user_id FROM collab_chains WHERE id = %s", (chain_id,)
    )
    row = cursor.fetchone()
    if not row:
        return False
    if row["initiator_user_id"] == user_id:
        return True
    cursor.execute(
        "SELECT 1 FROM collab_steps WHERE chain_id = %s AND assignee_user_id = %s LIMIT 1",
        (chain_id, user_id),
    )
    return bool(cursor.fetchone())


@router.post("/chains/{chain_id}/cancel")
async def cancel_chain(chain_id: str, authorization: str = Header(None)):
    """取消协同任务链"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        # 查询链信息
        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (chain_id,))
        chain = cursor.fetchone()
        if not chain:
            raise HTTPException(status_code=404, detail="协同链不存在")

        # 验证权限（只有发起者可以取消）
        if chain["initiator_user_id"] != current_user_id:
            raise HTTPException(status_code=403, detail="只有发起者可以取消协同链")

        if chain["status"] in ["completed", "cancelled"]:
            raise HTTPException(status_code=400, detail="协同链已完成或已取消")

        # 更新链状态
        cursor.execute(
            """
            UPDATE collab_chains 
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (chain_id,),
        )

        conn.commit()
        return {"success": True, "message": "协同链已取消"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"取消协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"取消失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def _remove_collab_attachment_files(cursor, chain_id: str) -> None:
    """Delete on-disk files for all attachments on a chain."""
    cursor.execute(
        "SELECT stored_path FROM collab_attachments WHERE chain_id = %s",
        (chain_id,),
    )
    for row in cursor.fetchall():
        stored_path = row.get("stored_path")
        if stored_path and os.path.exists(stored_path):
            try:
                os.remove(stored_path)
            except OSError as e:
                logger.error("删除协同附件文件失败 {}: {}", stored_path, e)


@router.delete("/chains/{chain_id}")
async def delete_chain(chain_id: str, authorization: str = Header(None)):
    """删除协同任务链（仅发起人；已完成不可删除）"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (chain_id,))
        chain = cursor.fetchone()
        if not chain:
            raise HTTPException(status_code=404, detail="协同链不存在")

        if chain["initiator_user_id"] != current_user_id:
            raise HTTPException(status_code=403, detail="只有发起人可以删除协同链")

        if chain["status"] == "completed":
            raise HTTPException(status_code=400, detail="协同链已完成，不可删除")

        _remove_collab_attachment_files(cursor, chain_id)

        cursor.execute(
            "DELETE FROM collab_user_chain_state WHERE chain_id = %s", (chain_id,)
        )
        cursor.execute("DELETE FROM collab_chains WHERE id = %s", (chain_id,))

        conn.commit()
        return {"success": True, "message": "协同链已删除"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"删除协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


# ========== 步骤 API ==========

_STEP_ID_ALIAS_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-step-(\d+)$",
    re.IGNORECASE,
)

_STEP_NOT_FOUND_HINT = (
    "步骤不存在。请调用 get_collab_chain_detail 获取真实的 Step ID（UUID），"
    "勿自行拼接 chain_id-step-N。"
)

_OUTPUT_DIR_INSTRUCTION_RE = re.compile(
    r"^\s*完成后请将(?:结果汇总|分析结果|报告)(?:到|保存到)\s*.+?\s*目录。\s*",
    re.MULTILINE,
)


def _strip_output_dir_instruction(text: Optional[str]) -> str:
    """Remove legacy 'save to OUTPUT_BASE_DIR/...' lines from task prompts."""
    if not text:
        return ""
    return _OUTPUT_DIR_INSTRUCTION_RE.sub("", str(text)).strip()


def _parse_step_id_alias(step_id: str) -> tuple[Optional[str], Optional[int]]:
    """Resolve Agent-guessed ids like {chain_uuid}-step-3."""
    m = _STEP_ID_ALIAS_RE.match((step_id or "").strip())
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def _resolve_collab_step(
    cursor,
    step_id: str,
    chain_id: Optional[str] = None,
    step_index: Optional[int] = None,
) -> Optional[dict]:
    """Look up step by UUID, optional chain_id+step_index, or alias pattern."""
    sid = (step_id or "").strip()
    if sid:
        cursor.execute("SELECT * FROM collab_steps WHERE id = %s", (sid,))
        row = cursor.fetchone()
        if row:
            return row

    alias_chain, alias_index = _parse_step_id_alias(sid)
    cid = (chain_id or alias_chain or "").strip() or None
    idx = step_index if step_index is not None else alias_index
    if cid and idx is not None:
        cursor.execute(
            "SELECT * FROM collab_steps WHERE chain_id = %s AND step_index = %s",
            (cid, idx),
        )
        return cursor.fetchone()
    return None


def render_task_prompt(
    step: dict,
    previous_steps: list,
    attachments_by_step: Optional[Dict[int, list]] = None,
    chain_id: str = "",
    total_steps: int = 0,
) -> str:
    """渲染任务提示，替换占位符；上游附件仅写入摘要（全文在 Agent 执行时加载）。"""
    from workflow.collab_attachment_preprocess import (
        build_collab_last_step_agent_hint,
        build_collab_local_paths_hint,
        build_upstream_summary_block_from_attachments,
        finalize_collab_task_prompt,
        sanitize_collab_handoff_text,
    )
    from workflow.config import OUTPUT_BASE_DIR

    prompt = step["task_prompt"]
    grouped = attachments_by_step or {}
    cid = str(chain_id or step.get("chain_id") or "")

    for prev_step in previous_steps:
        idx = prev_step["step_index"]
        result_placeholder = f"{{step_{idx}.result_summary}}"
        raw_summary = prev_step.get("result_summary") or "(暂无)"
        prompt = prompt.replace(
            result_placeholder, sanitize_collab_handoff_text(str(raw_summary))
        )

        summary = _format_step_attachment_summary(idx, grouped)
        prompt = prompt.replace(f"{{step_{idx}.attachment_urls}}", summary)
        prompt = prompt.replace(f"{{step_{idx}.output_files}}", summary)

    prompt = _strip_output_dir_instruction(prompt)
    upstream_summary = build_upstream_summary_block_from_attachments(
        previous_steps, grouped
    )
    local_paths_hint = build_collab_local_paths_hint(
        output_base_dir=OUTPUT_BASE_DIR,
        assignee_username=str(step.get("assignee_username") or ""),
        chain_id=cid,
        previous_steps=previous_steps,
        attachments_by_step=grouped,
    )
    step_idx = int(step.get("step_index") or 0)
    total = int(total_steps or 0)
    last_step_hint = build_collab_last_step_agent_hint(
        step_index=step_idx, total_steps=total
    )
    return finalize_collab_task_prompt(
        prompt,
        chain_id=cid,
        step_index=step_idx,
        upstream_attachment_block=upstream_summary,
        local_paths_hint=local_paths_hint,
        last_step_hint=last_step_hint,
    )


@router.post("/steps/{step_id}/complete")
async def complete_step(
    step_id: str,
    req: CompleteStepRequest,
    authorization: str = Header(None),
    chain_id: Optional[str] = Query(
        None, description="协同链 ID（与 step_index 联用）"
    ),
    step_index: Optional[int] = Query(None, description="步骤序号（与 chain_id 联用）"),
):
    """完成当前步骤并转发给下一步"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()

        step = _resolve_collab_step(cursor, step_id, chain_id, step_index)
        if not step:
            raise HTTPException(status_code=404, detail=_STEP_NOT_FOUND_HINT)

        resolved_step_id = step["id"]

        # 验证权限（只有当前指派人可以完成）
        if step["assignee_user_id"] != current_user_id:
            raise HTTPException(status_code=403, detail="无权操作此步骤")

        if step["status"] != "running":
            if step["status"] == "completed":
                conn.rollback()
                return {"success": True, "message": "步骤已完成"}
            raise HTTPException(status_code=400, detail="步骤状态不正确")

        # 查询链信息
        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (step["chain_id"],))
        chain = cursor.fetchone()

        _require_step_has_attachments(cursor, step["chain_id"], resolved_step_id)
        _validate_step_attachment_ids(
            cursor, step["chain_id"], resolved_step_id, req.attachment_ids
        )

        # 更新当前步骤
        cursor.execute(
            """
            UPDATE collab_steps 
            SET status = 'completed', result_summary = %s, result_detail = %s, 
                relay_note = %s, completed_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'running'
        """,
            (req.result_summary, req.result_detail, req.relay_note, resolved_step_id),
        )

        if cursor.rowcount == 0:
            conn.rollback()
            return {"success": True, "message": "步骤已处理"}

        # 检查是否是最后一步
        if step["step_index"] >= chain["total_steps"]:
            # 完成整个链
            cursor.execute(
                """
                UPDATE collab_chains 
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (step["chain_id"],),
            )

            conn.commit()

            await notify_chain_completed(
                initiator_user_id=chain["initiator_user_id"],
                chain_id=step["chain_id"],
                chain_title=chain.get("title") or "",
                final_step_summary=req.result_summary,
            )

            return {"success": True, "message": "协同链已完成", "chain_completed": True}
        else:
            # 激活下一步
            next_step_index = step["step_index"] + 1
            cursor.execute(
                """
                SELECT * FROM collab_steps 
                WHERE chain_id = %s AND step_index = %s
            """,
                (step["chain_id"], next_step_index),
            )
            next_step = cursor.fetchone()

            # 获取之前所有步骤的结果用于渲染提示词
            cursor.execute(
                """
                SELECT * FROM collab_steps 
                WHERE chain_id = %s AND step_index < %s
                ORDER BY step_index
            """,
                (step["chain_id"], next_step_index),
            )
            previous_steps = cursor.fetchall()
            attachments_by_step = _fetch_attachments_grouped_by_step(
                cursor, step["chain_id"]
            )

            # 渲染下一步的提示词
            rendered_prompt = render_task_prompt(
                next_step,
                previous_steps,
                attachments_by_step,
                chain_id=str(step["chain_id"]),
                total_steps=int(chain.get("total_steps") or 0),
            )

            # 激活下一步
            cursor.execute(
                """
                UPDATE collab_steps 
                SET status = 'running', task_prompt_rendered = %s, 
                    note_from_previous = %s, started_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (rendered_prompt, req.relay_note, next_step["id"]),
            )

            # 更新链的当前步骤
            cursor.execute(
                """
                UPDATE collab_chains 
                SET current_step = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (next_step_index, step["chain_id"]),
            )

            conn.commit()

            initiator_id = str(chain.get("initiator_user_id") or "").strip()
            if initiator_id and initiator_id != current_user_id:
                await notify_initiator_step_progress(
                    initiator_user_id=initiator_id,
                    chain_id=step["chain_id"],
                    chain_title=chain.get("title") or "",
                    completed_step_index=step["step_index"],
                    from_username=current_user.get("username") or "",
                )

            await notify_task_assigned(
                assignee_user_id=next_step["assignee_user_id"],
                chain_id=step["chain_id"],
                chain_title=chain.get("title") or "",
                step_id=next_step["id"],
                step_index=next_step_index,
                from_username=current_user.get("username") or "",
                relay_note=req.relay_note,
                task_prompt_rendered=rendered_prompt,
            )

            return {
                "success": True,
                "message": "步骤已完成，已转发给下一步",
                "next_step_id": next_step["id"],
                "next_assignee_id": next_step["assignee_user_id"],
            }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"完成步骤失败: {e}")
        raise HTTPException(status_code=500, detail=f"完成失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.post("/steps/{step_id}/reject")
async def reject_step(
    step_id: str,
    req: RejectStepRequest,
    authorization: str = Header(None),
    chain_id: Optional[str] = Query(
        None, description="协同链 ID（与 step_index 联用）"
    ),
    step_index: Optional[int] = Query(None, description="步骤序号（与 chain_id 联用）"),
):
    """退回步骤给上一步"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()

        step = _resolve_collab_step(cursor, step_id, chain_id, step_index)
        if not step:
            raise HTTPException(status_code=404, detail=_STEP_NOT_FOUND_HINT)

        resolved_step_id = step["id"]

        # 验证权限（只有当前指派人可以退回）
        if step["assignee_user_id"] != current_user_id:
            raise HTTPException(status_code=403, detail="无权操作此步骤")

        if step["status"] != "running":
            raise HTTPException(status_code=400, detail="步骤状态不正确")

        if step["step_index"] <= 1:
            raise HTTPException(status_code=400, detail="第一步不能退回")

        # 获取上一步
        prev_step_index = step["step_index"] - 1
        cursor.execute(
            """
            SELECT * FROM collab_steps 
            WHERE chain_id = %s AND step_index = %s
        """,
            (step["chain_id"], prev_step_index),
        )
        prev_step = cursor.fetchone()

        # 更新当前步骤为 rejected
        cursor.execute(
            """
            UPDATE collab_steps 
            SET status = 'rejected', reject_reason = %s
            WHERE id = %s AND status = 'running'
        """,
            (req.reject_reason, resolved_step_id),
        )

        if cursor.rowcount == 0:
            conn.rollback()
            return {"success": True, "message": "步骤已处理"}

        # 重新激活上一步
        cursor.execute(
            """
            UPDATE collab_steps 
            SET status = 'running', started_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (prev_step["id"],),
        )

        # 更新链的当前步骤
        cursor.execute(
            """
            UPDATE collab_chains 
            SET current_step = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (prev_step_index, step["chain_id"]),
        )

        conn.commit()

        cursor.execute(
            "SELECT title FROM collab_chains WHERE id = %s", (step["chain_id"],)
        )
        chain_row = cursor.fetchone()
        chain_title = (chain_row or {}).get("title") or ""

        await notify_step_rejected(
            prev_assignee_user_id=prev_step["assignee_user_id"],
            chain_id=step["chain_id"],
            chain_title=chain_title,
            rejected_step_index=step["step_index"],
            rejected_by_username=current_user.get("username") or "",
            reject_reason=req.reject_reason,
            your_step_index=prev_step["step_index"],
            your_step_id=prev_step["id"],
        )

        return {
            "success": True,
            "message": "步骤已退回",
            "prev_step_id": prev_step["id"],
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"退回步骤失败: {e}")
        raise HTTPException(status_code=500, detail=f"退回失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


# ========== 附件 API ==========


@router.post("/attachments/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    chain_id: Optional[str] = None,
    step_id: Optional[str] = None,
    authorization: str = Header(None),
):
    """上传附件"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    # 验证 chain_id 和 step_id
    if not chain_id or not step_id:
        raise HTTPException(status_code=400, detail="需要提供 chain_id 和 step_id")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM collab_chains WHERE id = %s", (chain_id,))
        chain = cursor.fetchone()
        if not chain:
            raise HTTPException(status_code=404, detail="协同链不存在")

        cursor.execute(
            "SELECT * FROM collab_steps WHERE id = %s AND chain_id = %s",
            (step_id, chain_id),
        )
        step = cursor.fetchone()
        if not step:
            raise HTTPException(status_code=404, detail="步骤不存在")

        _assert_can_upload_to_step(cursor, step, chain, current_user_id)

        original_filename = _normalize_collab_filename(file.filename)

        # 保存文件
        attachment_id = str(uuid.uuid4())
        file_ext = os.path.splitext(original_filename)[1]
        stored_filename = f"{attachment_id}{file_ext}"
        stored_path = os.path.join(COLLAB_UPLOAD_DIR, stored_filename)

        with open(stored_path, "wb") as f:
            content = await file.read()
            f.write(content)
            file_size = len(content)

        # 保存到数据库
        cursor.execute(
            """
            INSERT INTO collab_attachments
            (id, chain_id, step_id, uploader_user_id, original_filename, stored_path, file_size, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                attachment_id,
                chain_id,
                step_id,
                current_user_id,
                original_filename,
                stored_path,
                file_size,
                file.content_type,
            ),
        )

        conn.commit()
        return {
            "success": True,
            "attachment_id": attachment_id,
            "filename": original_filename,
            "message": "上传成功",
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"上传附件失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str, authorization: str = Header(None)):
    """下载附件"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        # 查询附件并验证权限
        cursor.execute(
            """
            SELECT a.* FROM collab_attachments a
            JOIN collab_chains c ON a.chain_id = c.id
            WHERE a.id = %s
            AND (c.initiator_user_id = %s OR
                 EXISTS (SELECT 1 FROM collab_steps s 
                         WHERE s.chain_id = c.id AND s.assignee_user_id = %s))
        """,
            (attachment_id, current_user_id, current_user_id),
        )

        attachment = cursor.fetchone()
        if not attachment:
            raise HTTPException(status_code=404, detail="附件不存在或无权访问")

        if not os.path.exists(attachment["stored_path"]):
            raise HTTPException(status_code=404, detail="附件文件不存在")

        display_name = _normalize_collab_filename(attachment["original_filename"])

        return FileResponse(
            path=attachment["stored_path"],
            filename=display_name,
            media_type=attachment["mime_type"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载附件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, authorization: str = Header(None)):
    """删除协同附件（上传者、该步执行人或发起人；协同链已完成时不可删）"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT a.*, c.initiator_user_id, c.status AS chain_status
            FROM collab_attachments a
            JOIN collab_chains c ON a.chain_id = c.id
            WHERE a.id = %s
            """,
            (attachment_id,),
        )
        attachment = cursor.fetchone()
        if not attachment:
            raise HTTPException(status_code=404, detail="附件不存在")

        cursor.execute(
            "SELECT * FROM collab_steps WHERE id = %s",
            (attachment["step_id"],),
        )
        step = cursor.fetchone()
        chain = {
            "id": attachment.get("chain_id"),
            "initiator_user_id": attachment.get("initiator_user_id"),
            "status": attachment.get("chain_status"),
        }

        if str(chain.get("status") or "") == "completed":
            raise HTTPException(status_code=400, detail="协同链已完成，不可删除附件")

        if not _user_can_delete_attachment(
            cursor, attachment, step, chain, current_user_id
        ):
            raise HTTPException(status_code=403, detail="仅可删除当前进行中步骤的附件")

        stored_path = attachment.get("stored_path")
        if stored_path and os.path.exists(stored_path):
            try:
                os.remove(stored_path)
            except OSError as e:
                logger.error("删除附件文件失败 {}: {}", stored_path, e)

        cursor.execute("DELETE FROM collab_attachments WHERE id = %s", (attachment_id,))
        conn.commit()
        return {"success": True, "message": "附件已删除"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"删除附件失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


@router.delete("/chains/batch")
async def batch_delete_chains(
    body: dict = Body(default={}), authorization: str = Header(None)
):
    """批量删除协同链（仅发起人或参与者可删除）"""
    current_user = get_current_user(authorization)
    current_user_id = current_user["user_id"]

    chain_ids = list(body.get("chain_ids") or [])
    if not chain_ids:
        raise HTTPException(status_code=400, detail="chain_ids is required")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        # 验证用户对每个协同链有权限（发起人或参与者）
        placeholders = ",".join(["%s"] * len(chain_ids))
        cursor.execute(
            f"""
            SELECT DISTINCT c.id FROM collab_chains c
            WHERE c.id IN ({placeholders})
            AND (
                c.initiator_user_id = %s
                OR EXISTS (
                    SELECT 1 FROM collab_steps s
                    WHERE s.chain_id = c.id AND s.assignee_user_id = %s
                )
            )
            """,
            (*chain_ids, current_user_id, current_user_id),
        )
        deletable_ids = [row["id"] for row in cursor.fetchall()]

        if not deletable_ids:
            raise HTTPException(status_code=403, detail="无权删除所选的协同链")

        # 批量删除（collab_steps / collab_attachments 通过外键 CASCADE 自动级联删除）
        d_placeholders = ",".join(["%s"] * len(deletable_ids))
        cursor.execute(
            f"DELETE FROM collab_chains WHERE id IN ({d_placeholders})",
            tuple(deletable_ids),
        )
        conn.commit()
        deleted_count = cursor.rowcount

        logger.info(f"用户 {current_user_id} 批量删除了 {deleted_count} 条协同链")
        return {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_ids": deletable_ids,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除协同链失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
