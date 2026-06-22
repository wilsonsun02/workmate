"""Collaboration notifications: unread persistence and Admin WebSocket push."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from admin_api.models.init_db import get_db_connection


def list_prior_attachments(chain_id: str, step_index: int) -> List[Dict[str, Any]]:
    """Attachments from completed steps before the given step_index (for inbound sync)."""
    cid = str(chain_id or "").strip()
    idx = int(step_index or 0)
    if not cid or idx <= 1:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT a.id, a.original_filename, a.file_size, a.mime_type, a.step_id,
                   s.step_index, a.uploader_user_id
            FROM collab_attachments a
            JOIN collab_steps s ON a.step_id = s.id
            WHERE a.chain_id = %s AND s.step_index < %s
            ORDER BY s.step_index ASC, a.created_at ASC
            """,
            (cid, idx),
        )
        rows = cursor.fetchall() or []
        out: List[Dict[str, Any]] = []
        for row in rows:
            name = str(row.get("original_filename") or "").strip()
            if "%" in name:
                try:
                    from urllib.parse import unquote

                    name = unquote(name).strip() or name
                except Exception:
                    pass
            out.append(
                {
                    "id": row.get("id"),
                    "original_filename": name,
                    "file_size": row.get("file_size"),
                    "mime_type": row.get("mime_type"),
                    "step_id": row.get("step_id"),
                    "step_index": row.get("step_index"),
                    "uploader_user_id": row.get("uploader_user_id"),
                }
            )
        return out
    except Exception as e:
        logger.error("list_prior_attachments failed chain={} step={}: {}", cid, idx, e)
        return []
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def _is_unread_row(row: Optional[dict]) -> bool:
    if not row:
        return False
    unread_at = row.get("unread_at")
    if unread_at is None:
        return False
    read_at = row.get("read_at")
    if read_at is None:
        return True
    return unread_at > read_at


def compute_is_unread(unread_at, read_at) -> bool:
    if unread_at is None:
        return False
    if read_at is None:
        return True
    return unread_at > read_at


def mark_unread(user_id: str, chain_id: str) -> None:
    """Mark chain as unread for user (upsert unread_at)."""
    uid = str(user_id or "").strip()
    cid = str(chain_id or "").strip()
    if not uid or not cid:
        return
    conn = get_db_connection()
    if not conn:
        logger.error("mark_unread: database connection failed")
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO collab_user_chain_state (user_id, chain_id, unread_at, read_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP, NULL)
            ON DUPLICATE KEY UPDATE
                unread_at = CURRENT_TIMESTAMP,
                read_at = NULL
            """,
            (uid, cid),
        )
        conn.commit()
    except Exception as e:
        logger.error("mark_unread failed user={} chain={}: {}", uid, cid, e)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def mark_read(user_id: str, chain_id: str) -> None:
    """Mark chain as read for user."""
    uid = str(user_id or "").strip()
    cid = str(chain_id or "").strip()
    if not uid or not cid:
        return
    conn = get_db_connection()
    if not conn:
        logger.error("mark_read: database connection failed")
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO collab_user_chain_state (user_id, chain_id, unread_at, read_at)
            VALUES (%s, %s, NULL, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE read_at = CURRENT_TIMESTAMP
            """,
            (uid, cid),
        )
        conn.commit()
    except Exception as e:
        logger.error("mark_read failed user={} chain={}: {}", uid, cid, e)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def get_read_state(user_id: str, chain_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    if not conn:
        return {"is_unread": False}
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT unread_at, read_at FROM collab_user_chain_state
            WHERE user_id = %s AND chain_id = %s
            """,
            (str(user_id), str(chain_id)),
        )
        row = cursor.fetchone()
        return {
            "is_unread": _is_unread_row(row),
            "unread_at": row.get("unread_at") if row else None,
        }
    except Exception as e:
        logger.error("get_read_state failed: {}", e)
        return {"is_unread": False}
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


async def push_collab_message(user_id: str, payload: dict) -> bool:
    from admin_api.routers.client_router import manager

    uid = str(user_id or "").strip()
    if not uid:
        return False
    try:
        sent = await manager.send_to_user(uid, payload)
        if not sent:
            logger.info(
                "collab WS not delivered (offline) user={} action={}",
                uid,
                payload.get("action"),
            )
        return sent
    except Exception as e:
        logger.error("push_collab_message failed user={}: {}", uid, e)
        return False


def chain_progress_text(chain: dict) -> str:
    status = str(chain.get("status") or "")
    total = int(chain.get("total_steps") or 0)
    current = int(chain.get("current_step") or 0)
    if status == "defining":
        return "定义中"
    if status == "cancelled":
        return "已取消"
    if status == "completed":
        return f"{total}/{total} · 已完成" if total else "已完成"
    if status == "running" and total:
        return f"{current}/{total} · 进行中"
    return status or "—"


def enrich_chain_summary(
    chain: dict,
    user_id: str,
    steps_by_chain: Optional[dict] = None,
    read_state_by_chain: Optional[dict] = None,
) -> dict:
    """Add is_unread, progress_text, my_step_status to a chain dict."""
    out = dict(chain)
    is_unread = False
    cid = str(chain.get("id") or "")
    if read_state_by_chain is not None:
        is_unread = bool(read_state_by_chain.get(cid, False))
    else:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    SELECT unread_at, read_at FROM collab_user_chain_state
                    WHERE user_id = %s AND chain_id = %s
                    """,
                    (str(user_id), cid),
                )
                is_unread = _is_unread_row(cursor.fetchone())
            except Exception as e:
                logger.error("enrich_chain_summary read state: {}", e)
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

    out["is_unread"] = is_unread
    out["progress_text"] = chain_progress_text(chain)

    my_status = ""
    if steps_by_chain and cid in steps_by_chain:
        try:
            for step in steps_by_chain[cid]:
                if str(step.get("assignee_user_id") or "") == str(user_id):
                    my_status = str(step.get("status") or "")
                    break
        except Exception:
            my_status = ""
    out["my_step_status"] = my_status
    return out


async def notify_task_assigned(
    *,
    assignee_user_id: str,
    chain_id: str,
    chain_title: str,
    step_id: str,
    step_index: int,
    from_username: str,
    relay_note: Optional[str] = None,
    task_prompt_rendered: Optional[str] = None,
    prior_attachments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    mark_unread(assignee_user_id, chain_id)
    prior = prior_attachments
    if prior is None:
        prior = list_prior_attachments(chain_id, step_index)
    await push_collab_message(
        assignee_user_id,
        {
            "action": "collab_task_assigned",
            "chain_id": chain_id,
            "chain_title": chain_title,
            "step_id": step_id,
            "step_index": step_index,
            "from_username": from_username,
            "relay_note": relay_note,
            "task_prompt_rendered": task_prompt_rendered,
            "prior_attachments": prior,
        },
    )


async def notify_chain_completed(
    *,
    initiator_user_id: str,
    chain_id: str,
    chain_title: str,
    final_step_summary: Optional[str] = None,
) -> None:
    mark_unread(initiator_user_id, chain_id)
    await push_collab_message(
        initiator_user_id,
        {
            "action": "collab_chain_completed",
            "chain_id": chain_id,
            "chain_title": chain_title,
            "final_step_summary": final_step_summary,
        },
    )


async def notify_initiator_step_progress(
    *,
    initiator_user_id: str,
    chain_id: str,
    chain_title: str,
    completed_step_index: int,
    from_username: str,
) -> None:
    """Notify chain initiator when a step completes (watch progress, show NEW)."""
    uid = str(initiator_user_id or "").strip()
    if not uid:
        return
    mark_unread(uid, chain_id)
    await push_collab_message(
        uid,
        {
            "action": "collab_chain_progress",
            "chain_id": chain_id,
            "chain_title": chain_title,
            "completed_step_index": completed_step_index,
            "from_username": from_username,
        },
    )


async def notify_step_rejected(
    *,
    prev_assignee_user_id: str,
    chain_id: str,
    chain_title: str,
    rejected_step_index: int,
    rejected_by_username: str,
    reject_reason: Optional[str],
    your_step_index: int,
    your_step_id: str,
) -> None:
    mark_unread(prev_assignee_user_id, chain_id)
    prior = list_prior_attachments(chain_id, your_step_index)
    await push_collab_message(
        prev_assignee_user_id,
        {
            "action": "collab_step_rejected",
            "chain_id": chain_id,
            "chain_title": chain_title,
            "rejected_step_index": rejected_step_index,
            "rejected_by_username": rejected_by_username,
            "reject_reason": reject_reason,
            "your_step_index": your_step_index,
            "your_step_id": your_step_id,
            "prior_attachments": prior,
        },
    )
