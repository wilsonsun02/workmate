"""
桌面端侧栏会话：定时任务执行结束后追加一条「虚拟会话」，不写入 LangGraph checkpoint，避免依赖图结构。
数据文件：config/desktop_scheduler_feed.json
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

_lock = threading.RLock()
_MAX_ENTRIES_PER_USER = 120


def _sanitize_username(username: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", str(username or "").strip())
    return s.strip("_") or "user"


def desktop_thread_prefix(username: str) -> str:
    return f"desktop_{_sanitize_username(username)}_"


def _config_dir() -> Path:
    import os

    base = os.environ.get("BASE_DIR", "").strip()
    if base:
        return Path(os.path.expandvars(base)) / "config"
    return Path(__file__).resolve().parent.parent / "config"


def _feed_path() -> Path:
    return _config_dir() / "desktop_scheduler_feed.json"


def _read_raw() -> Dict[str, Any]:
    path = _feed_path()
    if not path.exists():
        return {"users": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("users"), dict):
            return d
    except Exception as e:
        logger.info("读取 desktop_scheduler_feed 失败: {}", e)
    return {"users": {}}


def _write_raw(data: Dict[str, Any]) -> None:
    path = _feed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_feed_for_user(username: str) -> List[Dict[str, Any]]:
    """返回该用户的 feed 条目列表（每项含 thread_id, session_id, title, updated_at_ms, messages）。"""
    user = str(username or "").strip()
    if not user:
        return []
    with _lock:
        raw = _read_raw()
        users = raw.get("users") or {}
        arr = users.get(user)
        if not isinstance(arr, list):
            return []
        return [x for x in arr if isinstance(x, dict)]


def get_feed_messages(
    username: str, thread_id: str, session_id: str = ""
) -> Optional[List[Dict[str, str]]]:
    """若该 thread 属于本用户的 feed，返回 static messages；否则 None。"""
    user = str(username or "").strip()
    tid = str(thread_id or "").strip()
    if not user or not tid:
        return None
    ns = session_id or ""
    for entry in list_feed_for_user(user):
        if entry.get("thread_id") != tid:
            continue
        if str(entry.get("session_id") or "") != ns:
            continue
        msgs = entry.get("messages")
        if isinstance(msgs, list):
            out: List[Dict[str, str]] = []
            base_ts = str(entry.get("updated_at_ms") or "")
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "")
                text = str(m.get("text") or "")
                if role in ("user", "assistant") and text:
                    out.append({"role": role, "text": text, "timestamp": base_ts})
            return out
    return None


def append_scheduler_desktop_result(
    *,
    username: str,
    task_id: str,
    execution_id: str,
    task_name: Optional[str],
    task_description: str,
    status: str,
    result_text: str,
    execution_time: Optional[str] = None,
) -> None:
    """
    追加一条桌面侧栏会话：用户向为任务摘要，助手向为执行结果。
    同一 execution_id 的 running → completed 状态变更会更新已有条目，而非新建。
    status: running / success / failed / error
    """
    user = str(username or "").strip()
    if not user:
        return

    prefix = desktop_thread_prefix(user)
    title_base = (
        (task_name or "").strip() or (task_description or "").strip() or "定时任务"
    )
    title = (title_base[:26] + "…") if len(title_base) > 28 else title_base
    if not title.startswith("定时"):
        title = f"定时·{title}"

    desc = (task_description or "").strip()
    st_zh = {
        "success": "成功",
        "failed": "失败",
        "error": "异常",
        "running": "运行中",
    }.get(status, status)

    time_str = execution_time or "未知"
    user_text = (
        f"【定时任务】{task_name or '未命名'}\n"
        f"task_id: {task_id}\n"
        f"execution_id: {execution_id}\n"
        f"状态: {st_zh}\n"
        f"执行时间: {time_str}\n" + (f"\n{desc}\n" if desc else "")
    ).strip()

    body = (result_text or "").strip() or "（无输出）"
    if status == "running":
        assistant_text = f"**定时任务已完成（running）**\n\n{body}"
    else:
        assistant_text = f"**定时任务已完成（{st_zh}）**\n\n{body}"

    with _lock:
        raw = _read_raw()
        users = raw.setdefault("users", {})
        arr: List[Dict[str, Any]] = users.setdefault(user, [])
        if not isinstance(arr, list):
            arr = []
            users[user] = arr

        # 查找是否已有同一 execution_id 的条目，有则更新而非新建
        existing_idx = None
        for i, item in enumerate(arr):
            if isinstance(item, dict) and item.get("execution_id") == execution_id:
                existing_idx = i
                break

        if existing_idx is not None:
            # 更新已有条目：复用 thread_id，更新内容和状态
            entry = arr[existing_idx]
            entry["title"] = title
            entry["updated_at_ms"] = int(time.time() * 1000)
            entry["result_status"] = status
            entry["messages"] = [
                {"role": "user", "text": user_text},
                {"role": "assistant", "text": assistant_text},
            ]
            logger.info(
                "已更新桌面定时任务会话 thread_id={} execution_id={} user={} status={}",
                entry["thread_id"],
                execution_id,
                user,
                status,
            )
        else:
            # 新建条目
            thread_id = f"{prefix}sched_{uuid.uuid4().hex[:12]}"
            session_id = ""
            entry = {
                "thread_id": thread_id,
                "session_id": session_id,
                "title": title,
                "updated_at_ms": int(time.time() * 1000),
                "task_id": task_id,
                "execution_id": execution_id,
                "result_status": status,
                "messages": [
                    {"role": "user", "text": user_text},
                    {"role": "assistant", "text": assistant_text},
                ],
            }
            arr.insert(0, entry)
            logger.info(
                "已写入桌面定时任务会话 thread_id={} execution_id={} user={} status={}",
                thread_id,
                execution_id,
                user,
                status,
            )

        while len(arr) > _MAX_ENTRIES_PER_USER:
            arr.pop()
        _write_raw(raw)


def delete_feed_thread(username: str, thread_id: str) -> bool:
    """用户删除侧栏会话时，同步删除 feed 中的条目。"""
    user = str(username or "").strip()
    tid = str(thread_id or "").strip()
    if not user or not tid:
        return False
    with _lock:
        raw = _read_raw()
        users = raw.get("users") or {}
        arr = users.get(user)
        if not isinstance(arr, list):
            return False
        new_arr = [
            x for x in arr if not (isinstance(x, dict) and x.get("thread_id") == tid)
        ]
        if len(new_arr) == len(arr):
            return False
        users[user] = new_arr
        _write_raw(raw)
    return True


def append_collab_task_feed(
    *,
    username: str,
    chain_id: str,
    chain_title: str,
    step_id: str,
    step_index: int,
    from_username: str,
    relay_note: Optional[str] = None,
    task_prompt: Optional[str] = None,
) -> None:
    """
    追加一条协同任务会话到桌面侧栏。
    """
    user = str(username or "").strip()
    if not user:
        return

    prefix = desktop_thread_prefix(user)
    thread_id = f"{prefix}collab_{uuid.uuid4().hex[:12]}"
    session_id = ""
    title_base = chain_title.strip() or "协同任务"
    title = (title_base[:26] + "…") if len(title_base) > 28 else title_base
    if not title.startswith("协同"):
        title = f"协同·{title}"

    # 构建用户消息
    user_text = (
        f"【协同任务】{chain_title}\n"
        f"协同链ID: {chain_id}\n"
        f"步骤: {step_index}\n"
        f"来自: {from_username}\n"
    )
    if relay_note:
        user_text += f"\n传递说明:\n{relay_note}\n"
    if task_prompt:
        user_text += f"\n任务要求:\n{task_prompt}\n"

    # 构建助手消息
    assistant_text = (
        f"**收到协同任务**\n\n"
        f"请您协助完成「{chain_title}」的第 {step_index} 步。\n"
        f"您可以使用 `search_colleagues`、`create_collab_chain`、`complete_collab_step` 等工具进行操作。"
    )

    entry = {
        "thread_id": thread_id,
        "session_id": session_id,
        "title": title,
        "updated_at_ms": int(time.time() * 1000),
        "chain_id": chain_id,
        "step_id": step_id,
        "step_index": step_index,
        "from_username": from_username,
        "messages": [
            {"role": "user", "text": user_text.strip()},
            {"role": "assistant", "text": assistant_text},
        ],
    }

    with _lock:
        raw = _read_raw()
        users = raw.setdefault("users", {})
        arr: List[Dict[str, Any]] = users.setdefault(user, [])
        if not isinstance(arr, list):
            arr = []
            users[user] = arr
        arr.insert(0, entry)
        while len(arr) > _MAX_ENTRIES_PER_USER:
            arr.pop()
        _write_raw(raw)

    logger.info("已写入桌面协同任务会话 thread_id={} user={}", thread_id, user)


def append_collab_completed_feed(
    *, username: str, chain_id: str, chain_title: str, summary: Optional[str] = None
) -> None:
    """
    追加一条协同链完成通知到桌面侧栏。
    """
    user = str(username or "").strip()
    if not user:
        return

    prefix = desktop_thread_prefix(user)
    thread_id = f"{prefix}collab_done_{uuid.uuid4().hex[:12]}"
    session_id = ""
    title_base = chain_title.strip() or "协同任务"
    title = (title_base[:26] + "…") if len(title_base) > 28 else title_base
    if not title.startswith("协同完成"):
        title = f"协同完成·{title}"

    user_text = f"【协同链完成】{chain_title}\nchain_id: {chain_id}"

    assistant_text = f"**协同链「{chain_title}」已全部完成！**\n\n"
    if summary:
        assistant_text += f"最终总结:\n{summary}"
    else:
        assistant_text += "所有参与者的工作都已顺利完成。"

    entry = {
        "thread_id": thread_id,
        "session_id": session_id,
        "title": title,
        "updated_at_ms": int(time.time() * 1000),
        "chain_id": chain_id,
        "messages": [
            {"role": "user", "text": user_text.strip()},
            {"role": "assistant", "text": assistant_text},
        ],
    }

    with _lock:
        raw = _read_raw()
        users = raw.setdefault("users", {})
        arr: List[Dict[str, Any]] = users.setdefault(user, [])
        if not isinstance(arr, list):
            arr = []
            users[user] = arr
        arr.insert(0, entry)
        while len(arr) > _MAX_ENTRIES_PER_USER:
            arr.pop()
        _write_raw(raw)

    logger.info("已写入桌面协同完成通知 thread_id={} user={}", thread_id, user)


def append_collab_rejected_feed(
    *,
    username: str,
    chain_id: str,
    chain_title: str,
    rejected_step_index: int,
    rejected_by_username: str,
    reject_reason: Optional[str] = None,
    your_step_index: int,
    your_step_id: str,
) -> None:
    """
    追加一条协同步骤被退回的通知到桌面侧栏。
    """
    user = str(username or "").strip()
    if not user:
        return

    prefix = desktop_thread_prefix(user)
    thread_id = f"{prefix}collab_reject_{uuid.uuid4().hex[:12]}"
    session_id = ""
    title_base = chain_title.strip() or "协同任务"
    title = (title_base[:24] + "…") if len(title_base) > 26 else title_base
    title = f"协同退回·{title}"

    user_text = (
        f"【协同步骤被退回】{chain_title}\n"
        f"被退回的步骤: {rejected_step_index}\n"
        f"退回者: {rejected_by_username}\n"
        f"需要重新处理的您的步骤: {your_step_index}\n"
    )

    assistant_text = f"**您的协同任务的后续步骤被退回了！**\n\n"
    assistant_text += f"同事 {rejected_by_username} 在处理第 {rejected_step_index} 步时，发现您的第 {your_step_index} 步需要重新处理。\n"
    if reject_reason:
        assistant_text += f"\n退回原因:\n{reject_reason}\n"
    assistant_text += f"\n请您重新提交第 {your_step_index} 步的输出。"

    entry = {
        "thread_id": thread_id,
        "session_id": session_id,
        "title": title,
        "updated_at_ms": int(time.time() * 1000),
        "chain_id": chain_id,
        "your_step_id": your_step_id,
        "your_step_index": your_step_index,
        "messages": [
            {"role": "user", "text": user_text.strip()},
            {"role": "assistant", "text": assistant_text},
        ],
    }

    with _lock:
        raw = _read_raw()
        users = raw.setdefault("users", {})
        arr: List[Dict[str, Any]] = users.setdefault(user, [])
        if not isinstance(arr, list):
            arr = []
            users[user] = arr
        arr.insert(0, entry)
        while len(arr) > _MAX_ENTRIES_PER_USER:
            arr.pop()
        _write_raw(raw)

    logger.info("已写入桌面协同退回通知 thread_id={} user={}", thread_id, user)
