import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import aclosing
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

import aiosqlite
import sqlite3
from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from loguru import logger

from api.runtime_config import (
    apply_runtime_admin_api_base,
    apply_runtime_desktop_user,
    apply_runtime_general_env,
    apply_runtime_output_base_dir,
    apply_runtime_wechat_env,
)
from workflow.collab_auth import apply_collab_runtime_auth
from api.runtime_state import (
    checkpointer_db_path,
    desktop_chat_state_file,
    get_desktop_chat_state_lock,
    get_mcp_runtime_self_check,
    get_mcp_preload_status,
    set_stream_stop_flag,
)

router = APIRouter(tags=["desktop"])


def _desktop_env_path() -> Path:
    from admin_api.services.env_file_service import EnvFileService

    return EnvFileService.env_file_path()


def sanitize_username(username: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", str(username or "").strip())
    return s.strip("_") or "user"


def desktop_thread_prefix(username: str) -> str:
    return f"desktop_{sanitize_username(username)}_"


_DESKTOP_UPLOAD_MAX_FILES = 10
_DESKTOP_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
_DESKTOP_UPLOAD_ALLOWED_SUFFIXES = frozenset(
    {
        ".xlsx",
        ".xls",
        ".xlsb",
        ".csv",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".pdf",
        ".txt",
        ".md",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".flac",
    }
)


def desktop_uploads_base_dir(username: str) -> Path:
    from workflow.config import OUTPUT_BASE_DIR

    base = Path(OUTPUT_BASE_DIR).expanduser().resolve()
    return base / sanitize_username(username) / "desktop_uploads"


def safe_desktop_upload_filename(name: str) -> str:
    base = os.path.basename(str(name or "").strip())
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    if base in (".", "..") or not base:
        base = "file"
    if len(base) > 200:
        stem, suf = os.path.splitext(base)
        base = stem[:180] + suf
    return base


def is_user_thread(thread_id: str, username: str) -> bool:
    return str(thread_id or "").startswith(desktop_thread_prefix(username))


def read_desktop_chat_states() -> dict:
    path = desktop_chat_state_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def write_desktop_chat_states(data: dict) -> None:
    path = desktop_chat_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception as cleanup_error:
            logger.info("cleanup desktop chat state tmp file failed: {}", cleanup_error)
        raise


def coerce_message_content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
            else:
                try:
                    text = getattr(item, "text", None)
                    parts.append(str(text) if text is not None else str(item))
                except Exception:
                    pass
        return "".join(parts)
    return str(content)


def message_to_role_text(msg) -> tuple[str, str] | None:
    if isinstance(msg, HumanMessage):
        return ("user", coerce_message_content_to_text(msg.content))
    if isinstance(msg, AIMessage):
        from api.routers.quotation import normalize_assistant_message_for_display

        text = normalize_assistant_message_for_display(
            coerce_message_content_to_text(msg.content)
        )
        return ("assistant", text)
    return None


_SHELL_STEP_PREFIXES = (
    "uv run",
    "python ",
    "python3 ",
    "npm ",
    "npx ",
    "node ",
    "bash ",
    "sh ",
    "curl ",
    "pip ",
    "pytest ",
    "cmd ",
    "powershell",
)


def _is_command_only_think_line(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    lower = t.lower()
    return any(lower.startswith(p) for p in _SHELL_STEP_PREFIXES)


def _is_path_like_think_hint(hint: str) -> bool:
    h = str(hint or "").strip()
    if not h:
        return False
    if re.search(r"[/\\]", h):
        return True
    return bool(
        re.search(
            r"\.(png|jpe?g|gif|webp|json|md|docx?|xlsx?|pdf|html?|py|txt)\b", h, re.I
        )
    )


def _extract_tool_arg_hints(args: Any) -> list[str]:
    """思考步骤仅合并路径类参数，不展示 shell 命令全文。"""
    if not isinstance(args, dict):
        return []
    hints: list[str] = []
    for key in ("path", "file_path", "filepath", "directory", "dir", "output", "out"):
        val = args.get(key)
        if val is not None and str(val).strip():
            candidate = str(val).strip()
            if _is_path_like_think_hint(candidate) and candidate not in hints:
                hints.append(candidate)
    return hints


def _append_hints_to_think_line(line: str, hints: list[str]) -> str:
    out = (line or "").strip()
    for hint in hints:
        h = str(hint or "").strip()
        if not h:
            continue
        if out and h in out:
            continue
        out = f"{out} {h}".strip() if out else h
    return out.strip()


def _is_tool_calls_only_content(text: str) -> bool:
    t = str(text or "").strip()
    if not t or t[0] != "[":
        return False
    return (
        "tool_call" in t
        or ('"name"' in t and '"args"' in t)
        or ("'name'" in t and "'args'" in t)
    )


def _think_meta_from_agent_log(ev: dict[str, Any]) -> dict[str, Any]:
    """Parse reasoning JSON written by workflow _agent_step_reasoning_meta."""
    reasoning = ev.get("reasoning") or ""
    if not reasoning:
        return {}
    try:
        meta = json.loads(reasoning)
    except (json.JSONDecodeError, TypeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _format_think_step_from_agent_log(ev: dict[str, Any]) -> Optional[str]:
    """think-steps：仅模型叙述成步，路径合并进同一步；不展示命令行与 JSON。"""
    from api.routers.quotation import strip_generated_files_placeholder_json

    content = str(ev.get("content") or "").strip()
    if content.startswith("[") and "tool_call" in content:
        content = ""
    if _is_tool_calls_only_content(content):
        content = ""
    content = strip_generated_files_placeholder_json(content)
    if _is_command_only_think_line(content):
        content = ""
    line = content

    meta = _think_meta_from_agent_log(ev)
    tools_called: list[dict[str, Any]] = []
    raw_called = meta.get("tools_called") or []
    if isinstance(raw_called, list):
        tools_called = [x for x in raw_called if isinstance(x, dict)]

    arg_hints: list[str] = []
    for tc in tools_called:
        arg_hints.extend(_extract_tool_arg_hints(tc.get("args")))
    raw_gf = meta.get("generated_files") or []
    if isinstance(raw_gf, list):
        for p in raw_gf:
            candidate = str(p or "").strip()
            if _is_path_like_think_hint(candidate) and candidate not in arg_hints:
                arg_hints.append(candidate)
    line = _append_hints_to_think_line(line, arg_hints)

    if line and _is_command_only_think_line(line):
        return None
    return line or None


def build_think_steps_from_agent_logs(
    thread_id: str, session_id: str = ""
) -> list[str]:
    from workflow.report_tools import get_agent_events

    steps: list[str] = []
    for ev in get_agent_events(thread_id, session_id or None):
        if ev.get("event_type") != "agent_step":
            continue
        text = _format_think_step_from_agent_log(ev)
        if text and (not steps or steps[-1] != text):
            steps.append(text)
    return steps


def _attach_think_steps_to_messages(
    messages: list[dict[str, Any]], think_steps: list[str]
) -> None:
    if not think_steps or not messages:
        return
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            messages[i]["thinkSteps"] = think_steps
            return


def _decode_checkpoint_ts(checkpoint_blob: bytes | None) -> int:
    """从 msgpack 序列化的 checkpoint 中提取 ts 字段，转为毫秒时间戳。
    使用轻量级 msgpack 解析器，不依赖外部库。
    若提取失败返回 0。"""
    if not isinstance(checkpoint_blob, bytes) or len(checkpoint_blob) < 10:
        return 0
    try:
        # msgpack fixstr(2) + "ts" = b'\xa2ts'
        idx = checkpoint_blob.find(b"\xa2ts")
        if idx < 0:
            return 0
        pos = idx + 3
        if pos >= len(checkpoint_blob):
            return 0
        tag = checkpoint_blob[pos]
        length = 0
        val_start = pos + 1
        if tag == 0xD9:  # str8
            length = checkpoint_blob[pos + 1]
            val_start = pos + 2
        elif 0xA0 <= tag <= 0xBF:  # fixstr
            length = tag & 0x1F
        elif tag == 0xDA:  # str16
            length = int.from_bytes(checkpoint_blob[pos + 1 : pos + 3], "big")
            val_start = pos + 3
        elif tag == 0xDB:  # str32
            length = int.from_bytes(checkpoint_blob[pos + 1 : pos + 5], "big")
            val_start = pos + 5
        else:
            return 0
        if length <= 0 or val_start + length > len(checkpoint_blob):
            return 0
        ts_str = checkpoint_blob[val_start : val_start + length].decode(
            "utf-8", errors="replace"
        )
        dt = datetime.fromisoformat(ts_str)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


async def last_checkpoint_messages(saver: AsyncSqliteSaver, cfg: dict) -> list:
    """获取最新 checkpoint 中的消息列表（包含完整对话历史）

    alist() 返回从新到旧的 checkpoint 列表，
    最新的 checkpoint 包含完整的消息历史。
    """
    messages: list = []
    async with aclosing(saver.alist(cfg)) as gen:
        async for item in gen:
            channel_values = item.checkpoint.get("channel_values", {})
            mm = channel_values.get("messages", [])
            if isinstance(mm, list):
                messages = mm
            break
    return messages


async def _resolve_checkpoint_conversation_title(
    saver: AsyncSqliteSaver,
    thread_id: str,
    checkpoint_ns: str,
    *,
    fallback: str = "新对话",
) -> str:
    """Derive sidebar title from the latest checkpoint messages."""
    ns = checkpoint_ns or ""
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}
    try:
        messages = await last_checkpoint_messages(saver, cfg)
        if not messages and ns:
            messages = await last_checkpoint_messages(
                saver,
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            )
        if messages:
            return title_from_messages(messages, fallback=fallback)
    except Exception as exc:
        logger.debug(
            "resolve conversation title failed thread={} ns={}: {}",
            thread_id,
            ns,
            exc,
        )
    return fallback


_SOURCE_PREFIX_PATTERNS = (
    "【workmate桌面端】",
    "【定时任务】",
    "【协同任务】",
    "【企业微信】",
)
_SKILLS_INJECTED_PREFIX_RE = re.compile(
    r"^\s*¥¥\[User has selected the following skills for this message\. "
    r"You MUST load and use them by reading their SKILL\.md files:\s*[\s\S]*?\]¥¥"
    r"(?:\r?\n\s*\r?\n|\r?\n)?"
)
# 新格式 XML 标签注入块的正则，用于标题清洗
_XML_INJECTED_BLOCK_RE = re.compile(
    r"^\s*<(skills|mcp-tools|knowledge|attachment|attachment-paths|knowledge-file-ids|knowledge-category-names)>[\s\S]*?</\1>\s*(?:\r?\n)*",
    re.MULTILINE,
)


def _strip_source_prefix(text: str) -> str:
    for prefix in _SOURCE_PREFIX_PATTERNS:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _normalize_conversation_title_text(text: str) -> str:
    cleaned = _strip_source_prefix(str(text or ""))
    while True:
        m = _SKILLS_INJECTED_PREFIX_RE.match(cleaned)
        if not m:
            break
        cleaned = _SKILLS_INJECTED_PREFIX_RE.sub("", cleaned, count=1)
    # 剥离新格式 XML 注入块
    cleaned = _XML_INJECTED_BLOCK_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if re.match(r"^\s*¥¥\[User has selected", cleaned, re.IGNORECASE):
        return ""
    return cleaned


def title_from_messages(messages: list, fallback: str = "新对话") -> str:
    for message in messages:
        if isinstance(message, HumanMessage):
            text = _normalize_conversation_title_text(str(message.content or ""))
            if text:
                return text[:28] + ("…" if len(text) > 28 else "")
    return fallback


def dedupe_desktop_conversation_rows(rows: list[dict]) -> list[dict]:
    # 第一轮：按完整 id（thread_id::checkpoint_ns）去重
    by_id: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        if cid not in by_id:
            by_id[cid] = dict(row)
            continue
        current = by_id[cid]
        current["updatedAt"] = max(
            int(current.get("updatedAt") or 0), int(row.get("updatedAt") or 0)
        )
        for key in ("executionId", "schedulerResultStatus"):
            if not current.get(key) and row.get(key):
                current[key] = row[key]
        current_title = str(current.get("title") or "")
        row_title = str(row.get("title") or "")
        if "定时" in row_title and "定时" not in current_title:
            current["title"] = row["title"]
        elif not current_title.strip() and row_title.strip():
            current["title"] = row["title"]

    # 第二轮：按 threadId 去重，合并同一 thread_id 下多个 checkpoint_ns 的条目
    # 桌面端每轮对话生成新 sessionId，导致同一会话窗口被拆成多个侧栏条目
    by_tid: dict[str, dict] = {}
    for row in by_id.values():
        tid = str(row.get("threadId") or "").strip()
        is_sched = "_sched_" in tid
        # 定时任务条目不按 threadId 合并（可能有独立的 feed 条目需要保留）
        if is_sched or not tid:
            continue
        row_updated = int(row.get("updatedAt") or 0)
        if tid not in by_tid:
            by_tid[tid] = dict(row)
            continue
        existing = by_tid[tid]
        existing_updated = int(existing.get("updatedAt") or 0)
        # 保留更新时间最新的条目作为基础（含 id/sessionId），同时合并标题
        if row_updated > existing_updated:
            # 用更新的条目替换基础，但保留旧条目中更好的标题
            old_title = str(existing.get("title") or "").strip()
            new_row = dict(row)
            new_title = str(new_row.get("title") or "").strip()
            if (
                old_title
                and old_title != "新对话"
                and (not new_title or new_title == "新对话")
            ):
                new_row["title"] = old_title
            by_tid[tid] = new_row
        else:
            # 旧条目的标题可能更好
            existing_title = str(existing.get("title") or "").strip()
            row_title = str(row.get("title") or "").strip()
            if (
                row_title
                and row_title != "新对话"
                and (not existing_title or existing_title == "新对话")
            ):
                existing["title"] = row_title

    # 收集结果：按 threadId 去重后的条目 + 定时任务条目
    result_by_tid: dict[str, dict] = {}
    result_rest: list[dict] = []
    for row in by_id.values():
        tid = str(row.get("threadId") or "").strip()
        is_sched = "_sched_" in tid
        if is_sched or not tid:
            result_rest.append(row)
            continue
        if tid in by_tid and row.get("id") == by_tid[tid].get("id"):
            result_by_tid[tid] = by_tid[tid]
        elif tid in by_tid:
            continue
        else:
            result_rest.append(row)

    return list(result_by_tid.values()) + result_rest


@router.post("/api/desktop/set_collab_token")
async def set_collab_token(body: dict = Body(...)):
    """Sync Admin login token for MCP collab tools (stdio subprocess)."""
    token_path = apply_collab_runtime_auth(body.get("token"))
    if not token_path and str(body.get("token") or "").strip():
        return {"ok": False, "message": "failed to persist collab token"}
    return {"ok": True, "token_file": token_path or ""}


@router.post("/api/desktop/set_active_username")
async def set_active_username(body: dict = Body(...)):
    username = str(body.get("username", "")).strip()
    if not username:
        return {"ok": False, "message": "username is required"}

    mate_name = str(body.get("mate_name", "")).strip() or username
    identity = apply_runtime_desktop_user(username, mate_name)
    try:
        from scheduler.scheduler import get_scheduler

        scheduler = get_scheduler()
        scheduler.apply_active_user_filter(username)
    except Exception as error:
        logger.info("apply_active_user_filter failed: {}", error)
    try:
        from workflow.workflow_core import reset_deep_agent

        await reset_deep_agent()
    except Exception as error:
        logger.info("reset_deep_agent after set_active_username failed: {}", error)
    return {
        "ok": True,
        "username": username,
        "mate_name": identity.get("MATE_NAME", mate_name),
    }


@router.post("/api/desktop/runtime_config")
async def set_desktop_runtime_config(body: dict = Body(default={})):
    output_base_dir = str(body.get("output_base_dir", "")).strip()
    try:
        response_payload: dict[str, object] = {"ok": True}
        if output_base_dir:
            response_payload["output_base_dir"] = apply_runtime_output_base_dir(
                output_base_dir
            )
        response_payload["wechat_env"] = apply_runtime_wechat_env(body)
        response_payload["general_env"] = apply_runtime_general_env(body)
        admin_api_base = str(body.get("admin_api_base", "")).strip()
        if admin_api_base:
            response_payload["admin_api_base"] = apply_runtime_admin_api_base(
                admin_api_base
            )
        return response_payload
    except Exception as error:
        logger.info("set_desktop_runtime_config failed: {}", error)
        return {"ok": False, "message": str(error)}


@router.post("/api/desktop/runtime_paths")
async def set_desktop_runtime_paths(body: dict = Body(default={})):
    return await set_desktop_runtime_config(body)


@router.get("/api/desktop/mcp_runtime_check")
async def get_mcp_runtime_check():
    return {"ok": True, "check": get_mcp_runtime_self_check()}


@router.get("/api/desktop/mcp_preload_status")
async def get_mcp_preload():
    """查询 MCP 连接预热状态（桌面端启动时轮询此接口）"""
    return {"ok": True, "preload": get_mcp_preload_status()}


@router.get("/api/desktop/wxwork_env_config")
async def get_wxwork_env_config():
    """读取 .env 中企微配置（WXWORK_BOT_NAME、WXWORK_BOT_ID、WXWORK_SECRET）"""
    from dotenv import load_dotenv

    load_dotenv(_desktop_env_path(), override=False)
    values = {
        "WXWORK_BOT_NAME": os.environ.get("WXWORK_BOT_NAME", ""),
        "WXWORK_BOT_ID": os.environ.get("WXWORK_BOT_ID", ""),
        "WXWORK_SECRET": os.environ.get("WXWORK_SECRET")
        or os.environ.get("WECHAT_WORK_SECRET", ""),
    }
    return {"ok": True, "values": values}


@router.post("/api/desktop/wxwork_env_config")
async def save_wxwork_env_config(body: dict = Body(default={})):
    """将企微配置写入 .env 文件并立即更新环境变量"""
    env_path = _desktop_env_path()
    bot_id = str(body.get("WXWORK_BOT_ID", "")).strip()
    secret = str(body.get("WXWORK_SECRET", "")).strip()
    if not bot_id and not secret:
        return {"ok": False, "message": "请至少填写一个配置项"}
    try:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        updated_keys = {}
        key_map = {"WXWORK_BOT_ID": bot_id, "WXWORK_SECRET": secret}
        new_lines = []
        written_keys = set()
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in key_map and key_map[key]:
                    new_lines.append(f"{key}={key_map[key]}\n")
                    written_keys.add(key)
                    updated_keys[key] = key_map[key]
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        for key, value in key_map.items():
            if key not in written_keys and value:
                new_lines.append(f"{key}={value}\n")
                updated_keys[key] = value
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        for key, value in updated_keys.items():
            os.environ[key] = value
        logger.info("企微配置已写入 .env: {}", list(updated_keys.keys()))
        return {
            "ok": True,
            "message": "已写入 .env 文件并立即生效",
            "updated_keys": list(updated_keys.keys()),
        }
    except Exception as e:
        logger.error("写入企微配置失败: {}", e)
        return {"ok": False, "message": f"写入失败: {e}"}


# 通用设置 -> .env 环境变量映射
_GENERAL_ENV_MAP: dict[str, str] = {
    "output_base_dir": "OUTPUT_BASE_DIR",
    "image_provider": "IMAGE_PROVIDER",
    "llm_provider": "LLM_PROVIDER",
    "template_dir": "TEMPLATE_DIR",
    "image_template_dir": "IMAGE_TEMPLATE_DIR",
    "memory_compress_enabled": "MEMORY_COMPRESS_ENABLED",
    "memory_compress_threshold": "MEMORY_COMPRESS_THRESHOLD",
    "memory_enable_topic_search": "MEMORY_ENABLE_TOPIC_SEARCH",
    "memory_search_candidate_limit": "MEMORY_SEARCH_CANDIDATE_LIMIT",
    "memory_short_term_tasks": "MEMORY_SHORT_TERM_TASKS",
    "memory_mid_term_tasks": "MEMORY_MID_TERM_TASKS",
    "memory_relevant_tasks_limit": "MEMORY_RELEVANT_TASKS_LIMIT",
    "use_sandbox": "USE_SANDBOX",
    "enable_subagents": "ENABLE_SUBAGENTS",
}

# 通用设置的默认值
_GENERAL_DEFAULTS: dict[str, str] = {
    "output_base_dir": "",
    "image_provider": "gemini",
    "llm_provider": "deepseek",
    "template_dir": "template/report-template",
    "image_template_dir": "template/image-template",
    "memory_compress_enabled": "false",
    "memory_compress_threshold": "3000",
    "memory_enable_topic_search": "false",
    "memory_search_candidate_limit": "50",
    "memory_short_term_tasks": "5",
    "memory_mid_term_tasks": "25",
    "memory_relevant_tasks_limit": "2",
    "use_sandbox": "false",
    "enable_subagents": "false",
}


def _write_env_file(env_path: Path, key_map: dict[str, str]) -> set[str]:
    """将 key_map 中的配置项写入 .env 文件，返回已写入的 key 集合"""
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []
    new_lines: list[str] = []
    written_keys: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in key_map:
                new_lines.append(f"{key}={key_map[key]}\n")
                written_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    for key, value in key_map.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")
            written_keys.add(key)
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    return written_keys


@router.post("/api/desktop/general_env_config")
async def save_general_env_config(body: dict = Body(default={})):
    """将通用设置写入 .env 文件并立即更新环境变量"""
    env_path = _desktop_env_path()

    # 构建 env_key -> value 的映射（跳过空字符串，避免覆盖 .env 现有值）
    key_map: dict[str, str] = {}
    for cfg_key, env_key in _GENERAL_ENV_MAP.items():
        value = body.get(cfg_key, None)
        if value is not None and str(value).strip():
            key_map[env_key] = str(value)
    if not key_map:
        return {"ok": False, "message": "没有可保存的配置项"}

    try:
        written_keys = _write_env_file(env_path, key_map)
        # 立即更新当前进程环境变量
        for key, value in key_map.items():
            os.environ[key] = value
        logger.info("通用设置已写入 .env: {}", list(written_keys))
        return {
            "ok": True,
            "message": "已写入 .env 文件并立即生效",
            "updated_keys": list(written_keys),
        }
    except Exception as e:
        logger.error("写入通用设置到 .env 失败: {}", e)
        return {"ok": False, "message": f"写入失败: {e}"}


@router.post("/api/desktop/general_env_reset")
async def reset_general_env_config():
    """恢复通用设置为默认值并写入 .env 文件"""
    env_path = _desktop_env_path()

    # 构建默认值映射
    key_map: dict[str, str] = {}
    for cfg_key, env_key in _GENERAL_ENV_MAP.items():
        key_map[env_key] = _GENERAL_DEFAULTS.get(cfg_key, "")

    try:
        written_keys = _write_env_file(env_path, key_map)
        # 立即更新当前进程环境变量
        for key, value in key_map.items():
            os.environ[key] = value
        logger.info("通用设置已恢复默认并写入 .env: {}", list(written_keys))
        return {
            "ok": True,
            "message": "已恢复默认配置并写入 .env",
            "updated_keys": list(written_keys),
        }
    except Exception as e:
        logger.error("恢复通用设置默认值失败: {}", e)
        return {"ok": False, "message": f"恢复默认值失败: {e}"}


@router.get("/api/desktop/mcp_read_allowed_dirs")
async def get_mcp_read_allowed_dirs():
    """从 .env 文件读取 MCP_READ_ALLOWED_DIRS 路径列表"""
    env_path = _desktop_env_path()
    dirs: list[str] = []
    try:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("#") or "=" not in stripped:
                        continue
                    key, _, value = stripped.partition("=")
                    if key.strip() == "MCP_READ_ALLOWED_DIRS":
                        raw = value.strip()
                        if raw:
                            dirs = [d.strip() for d in raw.split(",") if d.strip()]
                        break
        # 如果 .env 中没有，回退到 workflow.config 中的默认值
        if not dirs:
            from workflow.config import MCP_OPERABLE_DIRS

            dirs = list(MCP_OPERABLE_DIRS)
    except Exception as e:
        logger.error("读取 MCP_READ_ALLOWED_DIRS 失败: {}", e)
        return {"ok": False, "message": f"读取失败: {e}", "dirs": []}
    return {"ok": True, "dirs": dirs}


@router.post("/api/desktop/mcp_read_allowed_dirs")
async def save_mcp_read_allowed_dirs(body: dict = Body(default={})):
    """将路径列表写入 .env 文件的 MCP_READ_ALLOWED_DIRS"""
    env_path = _desktop_env_path()
    raw_dirs = body.get("dirs", [])
    if not isinstance(raw_dirs, list):
        return {"ok": False, "message": "dirs 必须是字符串数组"}
    dirs_csv = ",".join(str(d).strip() for d in raw_dirs if str(d).strip())
    try:
        _write_env_file(env_path, {"MCP_READ_ALLOWED_DIRS": dirs_csv})
        os.environ["MCP_READ_ALLOWED_DIRS"] = dirs_csv
        logger.info("MCP_READ_ALLOWED_DIRS 已写入 .env: {}", dirs_csv)
        return {"ok": True, "message": "已保存到 .env 文件"}
    except Exception as e:
        logger.error("写入 MCP_READ_ALLOWED_DIRS 失败: {}", e)
        return {"ok": False, "message": f"写入失败: {e}"}


@router.post("/api/desktop/general_env_config_single")
async def save_general_env_config_single(body: dict = Body(default={})):
    """将单个通用设置字段写入 .env 文件并立即生效"""
    env_path = _desktop_env_path()
    cfg_key = str(body.get("cfg_key", "")).strip()
    cfg_value = body.get("cfg_value", None)
    if not cfg_key:
        return {"ok": False, "message": "cfg_key 不能为空"}
    if cfg_key not in _GENERAL_ENV_MAP:
        return {"ok": False, "message": f"未知的配置项: {cfg_key}"}
    env_key = _GENERAL_ENV_MAP[cfg_key]
    env_value = str(cfg_value) if cfg_value is not None else ""
    try:
        _write_env_file(env_path, {env_key: env_value})
        os.environ[env_key] = env_value
        logger.info("单个通用设置已写入 .env: {}={}", env_key, env_value)
        return {"ok": True, "message": "已写入 .env 文件并立即生效"}
    except Exception as e:
        logger.error("写入单个通用设置失败: {}", e)
        return {"ok": False, "message": f"写入失败: {e}"}


_wxwork_agent_process: subprocess.Popen | None = None
_wxwork_agent_lock = asyncio.Lock()


def _resolve_venv_python(project_root: Path) -> str:
    """解析 venv 中的 Python 解释器路径，优先生效于 sys.executable"""
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt" and venv_python.exists():
        return str(venv_python)
    venv_python_unix = project_root / ".venv" / "bin" / "python"
    if venv_python_unix.exists():
        return str(venv_python_unix)
    return sys.executable


def _find_wxwork_agent_pids() -> list[int]:
    """查找系统中所有 wxwork_agent.py 进程的 PID 列表"""
    pids: list[int] = []
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'wxwork_agent' } | "
                    "ForEach-Object { Write-Host $_.ProcessId }",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            for line in result.stdout.strip().splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pids.append(int(pid_str))
        else:
            result = subprocess.run(
                ["pgrep", "-f", "wxwork_agent.py"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pids.append(int(pid_str))
    except Exception:
        pass
    return pids


def _kill_wxwork_agent_processes(exclude_pids: set[int] | None = None) -> None:
    """终止所有 wxwork_agent.py 进程，排除指定的 PID 集"""
    exclude = exclude_pids or set()
    pids = _find_wxwork_agent_pids()
    for pid in pids:
        if pid in exclude:
            continue
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5
                )
            else:
                subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=5)
        except Exception:
            pass


def _get_wxwork_agent_log_path(project_root: Path) -> Path:
    """企微代理日志文件路径"""
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "wxwork_agent.log"


@router.post("/api/desktop/wxwork_connect")
async def start_wxwork_agent():
    """启动企业微信长连接代理进程 (wxwork_agent.py)"""
    global _wxwork_agent_process

    async with _wxwork_agent_lock:
        # 先检查系统上是否已有企微代理进程在运行
        existing_pids = _find_wxwork_agent_pids()
        if existing_pids:
            return {
                "ok": True,
                "running": True,
                "pid": existing_pids[0],
                "message": "企微长连接已在运行中 (PID={})".format(existing_pids[0]),
            }

        # 清理可能残留的僵尸 Popen 引用
        if (
            _wxwork_agent_process is not None
            and _wxwork_agent_process.poll() is not None
        ):
            _wxwork_agent_process = None

        project_root = Path(__file__).resolve().parent.parent.parent
        agent_script = project_root / "wxwork_agent.py"
        if not agent_script.exists():
            return {"ok": False, "message": f"未找到企微代理脚本: {agent_script}"}

        python_exe = _resolve_venv_python(project_root)
        log_path = _get_wxwork_agent_log_path(project_root)
        logger.info(
            "企微代理启动: python={}, script={}, log={}",
            python_exe,
            agent_script,
            log_path,
        )

        try:
            # 将 stdout/stderr 重定向到日志文件，便于诊断崩溃原因
            log_file = open(log_path, "a", encoding="utf-8")
            _wxwork_agent_process = subprocess.Popen(
                [python_exe, str(agent_script)],
                cwd=str(project_root),
                stdout=log_file,
                stderr=log_file,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            logger.info("企微长连接代理已启动: PID={}", _wxwork_agent_process.pid)

            # 等待进程稳定：3 秒后检查进程是否存活
            await asyncio.sleep(3)

            # 用两种方式验证进程是否真正存活
            poll_result = _wxwork_agent_process.poll()
            actual_pids = _find_wxwork_agent_pids()

            if poll_result is not None:
                # Popen 显示进程已退出
                logger.info(
                    "企微长连接代理已退出: code={}, 详见日志 {}", poll_result, log_path
                )
                log_file.close()
                _wxwork_agent_process = None
                hint = "企微长连接启动后立即退出"
                if log_path.exists():
                    try:
                        last_lines = (
                            log_path.read_text(encoding="utf-8")
                            .strip()
                            .splitlines()[-5:]
                        )
                        if last_lines:
                            hint += "。最近日志：\n" + "\n".join(last_lines)
                    except Exception:
                        pass
                return {"ok": False, "message": hint}

            # 检查实际进程数：如果多于 1 个，说明 multiprocessing spawn 产生了子进程
            # 这些子进程（如 loguru enqueue=True 的日志写入进程）是主进程正常运行的一部分
            # 不能杀掉它们，否则会导致主进程崩溃
            if len(actual_pids) > 1:
                logger.info(
                    "企微代理进程树: PIDs={} (含 multiprocessing spawn 子进程)",
                    actual_pids,
                )

            return {
                "ok": True,
                "message": "企微长连接已启动",
                "pid": _wxwork_agent_process.pid,
            }
        except Exception as e:
            logger.error("启动企微长连接代理失败: {}", e)
            try:
                log_file.close()
            except Exception:
                pass
            return {"ok": False, "message": f"启动失败: {e}"}


@router.get("/api/desktop/wxwork_connect")
async def get_wxwork_agent_status():
    """查询企微长连接代理状态（基于实际进程检测）"""
    global _wxwork_agent_process
    actual_pids = _find_wxwork_agent_pids()
    if actual_pids:
        # 同步内存追踪变量（防止 serve.py 重启后丢失追踪）
        if _wxwork_agent_process is None or _wxwork_agent_process.poll() is not None:
            _wxwork_agent_process = None
        return {
            "ok": True,
            "running": True,
            "pid": actual_pids[0],
            "message": "企微长连接运行中 (PID={})".format(actual_pids[0]),
        }
    # 没有企微代理进程
    if _wxwork_agent_process is not None:
        _wxwork_agent_process = None
    return {"ok": True, "running": False, "message": "企微长连接未启动"}


@router.post("/api/desktop/wxwork_disconnect")
async def stop_wxwork_agent():
    """停止企业微信长连接代理进程（包括其 multiprocessing spawn 子进程）"""
    global _wxwork_agent_process

    async with _wxwork_agent_lock:
        # 收集所有企微代理相关进程的 PID（含 spawn 子进程）
        all_pids = _find_wxwork_agent_pids()
        if all_pids:
            # 逐个优雅终止所有相关进程
            for pid in all_pids:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid)], capture_output=True, timeout=5
                    )
                except Exception:
                    pass
            # 等待进程退出
            await asyncio.sleep(2)
            # 强制清理仍在运行的进程
            _kill_wxwork_agent_processes()
            logger.info("企微长连接已停止: PIDs={}", all_pids)
        else:
            logger.info("企微长连接未在运行，无需停止")

        # 同步内存追踪变量
        if _wxwork_agent_process is not None:
            _wxwork_agent_process = None

        return {"ok": True, "message": "企微长连接已断开"}


@router.get("/api/desktop/skills_config")
async def get_skills_config():
    """读取 config/skills_config.json 返回技能列表"""
    from workflow.config import BASE_DIR

    skills_path = Path(BASE_DIR) / "config" / "skills_config.json"
    if not skills_path.exists():
        return {"ok": False, "message": "skills_config.json not found", "config": {}}
    try:
        with open(skills_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return {"ok": True, "config": config, "path": str(skills_path)}
    except Exception as e:
        logger.error("读取 skills_config.json 失败: {}", e)
        return {"ok": False, "message": str(e), "config": {}}


@router.get("/api/desktop/chat_state")
async def get_desktop_chat_state(username: str = ""):
    user = str(username or "").strip()
    if not user:
        return {
            "ok": False,
            "message": "username is required",
            "has_state": False,
            "state": None,
        }
    async with get_desktop_chat_state_lock():
        all_states = read_desktop_chat_states()
        state = all_states.get(user)
    has_state = state is not None
    if isinstance(state, dict):
        owner = str(state.get("_owner_username", "")).strip()
        if not owner or owner != user:
            has_state = False
            state = None
    return {"ok": True, "username": user, "has_state": has_state, "state": state}


@router.post("/api/desktop/chat_state")
async def save_desktop_chat_state(body: dict = Body(...)):
    user = str((body or {}).get("username", "")).strip()
    state = (body or {}).get("state")
    if not user:
        return {"ok": False, "message": "username is required"}
    if not isinstance(state, dict):
        return {"ok": False, "message": "state must be an object"}
    conversations = state.get("conversations")
    if conversations is None or not isinstance(conversations, list):
        return {"ok": False, "message": "state.conversations must be an array"}

    state["_owner_username"] = user
    async with get_desktop_chat_state_lock():
        all_states = read_desktop_chat_states()
        all_states[user] = state
        write_desktop_chat_states(all_states)
    return {"ok": True, "username": user}


@router.get("/api/desktop/chat_state/debug")
async def debug_desktop_chat_state(username: str = ""):
    user = str(username or "").strip()
    path = desktop_chat_state_file()
    exists = path.exists()
    if not user:
        return {
            "ok": False,
            "message": "username is required",
            "file": str(path),
            "file_exists": exists,
        }

    async with get_desktop_chat_state_lock():
        all_states = read_desktop_chat_states()
        state = all_states.get(user)

    conv_count = 0
    active_id = None
    conversation_ids = []
    if isinstance(state, dict):
        convs = state.get("conversations")
        if isinstance(convs, list):
            conv_count = len(convs)
            conversation_ids = [
                str(c.get("id", ""))
                for c in convs
                if isinstance(c, dict) and c.get("id")
            ][:20]
        active_id = state.get("activeId")
    return {
        "ok": True,
        "username": user,
        "file": str(path),
        "file_exists": exists,
        "has_state": state is not None,
        "conversation_count": conv_count,
        "active_id": active_id,
        "conversation_ids_preview": conversation_ids,
    }


@router.get("/api/desktop/conversations")
async def list_desktop_conversations(username: str = ""):
    user = str(username or "").strip()
    if not user:
        return {"ok": False, "message": "username is required", "conversations": []}

    db_path = checkpointer_db_path()
    if not db_path.exists():
        return {"ok": True, "conversations": []}

    prefix = desktop_thread_prefix(user)
    conn = await aiosqlite.connect(str(db_path))
    try:
        try:
            cur = await conn.execute(
                """
                SELECT thread_id, checkpoint_ns,
                       CAST(substr(checkpoint, 1, 2000) AS BLOB) AS checkpoint_head,
                       MAX(rowid) AS rid
                FROM checkpoints
                WHERE thread_id LIKE ?
                GROUP BY thread_id, checkpoint_ns
                ORDER BY rid DESC
                LIMIT 200
                """,
                (f"{prefix}%",),
            )
            rows = await cur.fetchall()
            await cur.close()
        except sqlite3.OperationalError:
            return {"ok": True, "conversations": []}

        conversations = []
        saver = AsyncSqliteSaver(conn)
        for thread_id, checkpoint_ns, checkpoint_head, rid in rows:
            cp_ts = _decode_checkpoint_ts(checkpoint_head)
            title = await _resolve_checkpoint_conversation_title(
                saver, thread_id, checkpoint_ns or ""
            )
            conversations.append(
                {
                    "id": f"{thread_id}::{checkpoint_ns or ''}",
                    "threadId": thread_id,
                    "sessionId": checkpoint_ns or "",
                    "title": title,
                    "updatedAt": cp_ts if cp_ts > 0 else int(rid or 0),
                }
            )

        try:
            from scheduler.desktop_feed_storage import list_feed_for_user

            feed_items = list_feed_for_user(user)
            rid_floor = 10**12
            for entry in feed_items:
                tid = entry.get("thread_id")
                if not tid:
                    continue
                tid_str = str(tid)
                if "collab" in tid_str:
                    continue
                sns = entry.get("session_id") or ""
                uat = int(entry.get("updated_at_ms") or 0)
                conversations.append(
                    {
                        "id": f"{tid}::{sns}",
                        "threadId": tid,
                        "sessionId": sns,
                        "title": entry.get("title") or "定时任务",
                        "updatedAt": uat if uat > 0 else rid_floor,
                        "executionId": entry.get("execution_id") or "",
                        "schedulerResultStatus": entry.get("result_status") or "",
                    }
                )
                rid_floor -= 1
        except Exception:
            pass

        conversations = dedupe_desktop_conversation_rows(conversations)
        conversations.sort(key=lambda x: -int(x.get("updatedAt") or 0))
        conversations = conversations[:200]
        active_id = conversations[0]["id"] if conversations else None
        return {"ok": True, "activeId": active_id, "conversations": conversations}
    finally:
        await conn.close()


@router.get("/api/desktop/conversations/{thread_id}/messages")
async def get_desktop_conversation_messages(
    thread_id: str,
    username: str = "",
    session_id: str = "",
    offset: int = 0,
    limit: int = 50,
):
    user = str(username or "").strip()
    if not user:
        return {
            "ok": False,
            "message": "username is required",
            "messages": [],
            "total": 0,
            "has_more": False,
        }
    if not is_user_thread(thread_id, user):
        return {
            "ok": False,
            "message": "forbidden thread_id",
            "messages": [],
            "total": 0,
            "has_more": False,
        }

    # 参数校验：offset 不能小于 0，limit 控制在 1~200 之间
    offset = max(offset, 0)
    limit = max(min(limit, 200), 1)

    db_path = checkpointer_db_path()
    if db_path.exists():
        conn = await aiosqlite.connect(str(db_path))
        try:
            # 从 checkpoint 提取 ts 时间戳
            cp_ts_ms = 0
            try:
                cur = await conn.execute(
                    "SELECT CAST(substr(checkpoint, 1, 2000) AS BLOB) FROM checkpoints "
                    "WHERE thread_id = ? AND checkpoint_ns = ? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (thread_id, session_id or ""),
                )
                row = await cur.fetchone()
                await cur.close()
                if row:
                    cp_ts_ms = _decode_checkpoint_ts(row[0])
            except Exception:
                pass

            # 同一个 thread_id 下可能有多个 checkpoint_ns（桌面端每轮对话生成新 sessionId），
            # 需要合并所有 checkpoint_ns 的消息，才能完整展示历史对话
            saver = AsyncSqliteSaver(conn)

            # 查询该 thread_id 下所有 checkpoint_ns，按最新 rowid 排序（从旧到新）
            # 这样合并后消息按时间顺序排列
            ns_list: list[tuple[str, int]] = []
            try:
                ns_cur = await conn.execute(
                    "SELECT checkpoint_ns, MAX(rowid) AS max_rid "
                    "FROM checkpoints WHERE thread_id = ? "
                    "GROUP BY checkpoint_ns ORDER BY max_rid ASC",
                    (thread_id,),
                )
                ns_rows = await ns_cur.fetchall()
                await ns_cur.close()
                ns_list = [(r[0], r[1]) for r in ns_rows if r[0] is not None]
            except Exception:
                ns_list = [(session_id or "", 0)]

            # 依次从每个 checkpoint_ns 收集可显示消息
            # 每个 checkpoint_ns 对应一轮独立对话，内部消息顺序已正确
            # 按 max_rid 从旧到新遍历，保证合并后时间顺序正确
            seen_keys: set[str] = set()
            merged_displayable: list[dict[str, Any]] = []

            for ns, _max_rid in ns_list:
                cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}
                ns_messages = await last_checkpoint_messages(saver, cfg)
                if not ns_messages:
                    continue
                for message in ns_messages:
                    role_text = message_to_role_text(message)
                    if not role_text:
                        continue
                    # 去重键基于完整文本内容，避免不同轮次中相似短消息被误删
                    dedup_key = role_text[0] + "\0" + role_text[1]
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    msg_entry: dict[str, Any] = {
                        "role": role_text[0],
                        "text": role_text[1],
                    }
                    if cp_ts_ms > 0:
                        msg_entry["timestamp"] = str(cp_ts_ms)
                    merged_displayable.append(msg_entry)

            if merged_displayable:
                total = len(merged_displayable)
                start_idx = max(0, total - offset - limit)
                end_idx = max(0, total - offset)

                # 分页边界保护：如果页面以 assistant 消息开头，
                # 说明对应的 user 消息在前一页末尾被截断，
                # 导致前端无法将 assistant 消息与 user 消息配对显示。
                # 此时将 start_idx 前移至最近的 user 消息，确保 Q&A 组完整。
                if start_idx > 0:
                    while (
                        start_idx > 0
                        and merged_displayable[start_idx].get("role") != "user"
                    ):
                        start_idx -= 1

                output = merged_displayable[start_idx:end_idx]
                has_more = start_idx > 0

                return {
                    "ok": True,
                    "messages": output,
                    "total": total,
                    "has_more": has_more,
                }
        finally:
            await conn.close()

    try:
        from scheduler.desktop_feed_storage import get_feed_messages

        feed_messages = get_feed_messages(user, thread_id, session_id or "")
        if feed_messages is not None:
            total = len(feed_messages)
            start_idx = max(0, total - offset - limit)
            end_idx = max(0, total - offset)
            from api.routers.quotation import normalize_assistant_message_for_display

            # 分页边界保护：同上，确保不以孤立 assistant 消息开头
            if start_idx > 0:
                while start_idx > 0 and feed_messages[start_idx].get("role") != "user":
                    start_idx -= 1

            page = []
            for m in feed_messages[start_idx:end_idx]:
                if not isinstance(m, dict):
                    continue
                entry = dict(m)
                if entry.get("role") == "assistant" and entry.get("text"):
                    entry["text"] = normalize_assistant_message_for_display(
                        str(entry["text"])
                    )
                page.append(entry)
            has_more = start_idx > 0
            return {
                "ok": True,
                "messages": page,
                "total": total,
                "has_more": has_more,
            }
    except Exception:
        pass

    return {"ok": True, "messages": [], "total": 0, "has_more": False}


@router.get("/api/desktop/conversations/{thread_id}/think-steps")
async def get_desktop_conversation_think_steps(
    thread_id: str, username: str = "", session_id: str = ""
):
    user = str(username or "").strip()
    if not user:
        return {"ok": False, "message": "username is required", "thinkSteps": []}
    if not is_user_thread(thread_id, user):
        return {"ok": False, "message": "forbidden thread_id", "thinkSteps": []}
    think_steps = await asyncio.to_thread(
        build_think_steps_from_agent_logs, thread_id, session_id or ""
    )
    return {"ok": True, "thinkSteps": think_steps}


@router.post("/api/desktop/conversations")
async def create_desktop_conversation(body: dict = Body(default={})):
    user = str((body or {}).get("username", "")).strip()
    if not user:
        return {"ok": False, "message": "username is required"}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = desktop_thread_prefix(user)
    thread_id = f"{prefix}thread_{ts}"
    session_id = ""
    return {
        "ok": True,
        "conversation": {
            "id": f"{thread_id}::{session_id}",
            "threadId": thread_id,
            "sessionId": session_id,
            "title": "新对话",
        },
    }


@router.delete("/api/desktop/conversations/{thread_id}")
async def delete_desktop_conversation(
    thread_id: str, username: str = "", session_id: str = ""
):
    user = str(username or "").strip()
    if not user:
        return {"ok": False, "message": "username is required"}
    if not is_user_thread(thread_id, user):
        return {"ok": False, "message": "forbidden thread_id"}
    try:
        from scheduler.desktop_feed_storage import delete_feed_thread

        delete_feed_thread(user, thread_id)
    except Exception:
        pass

    db_path = checkpointer_db_path()
    if not db_path.exists():
        return {"ok": True}

    conn = await aiosqlite.connect(str(db_path))
    try:
        if session_id:
            await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ?",
                (thread_id, session_id),
            )
            await conn.execute(
                "DELETE FROM writes WHERE thread_id = ? AND checkpoint_ns = ?",
                (thread_id, session_id),
            )
        else:
            await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
            )
            await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        await conn.commit()
        return {"ok": True}
    finally:
        await conn.close()


@router.post("/api/desktop/conversations/{thread_id}/stop")
async def stop_desktop_conversation(thread_id: str, request: Request):
    body = await request.json()
    user = str((body or {}).get("username") or "").strip()
    if not user:
        return {"ok": False, "message": "username is required"}
    if not is_user_thread(thread_id, user):
        return {"ok": False, "message": "forbidden thread_id"}

    session_id = str((body or {}).get("session_id") or "").strip()
    await set_stream_stop_flag(thread_id, session_id, True)
    return {
        "ok": True,
        "message": "stop signal sent",
        "thread_id": thread_id,
        "session_id": session_id,
    }


@router.post("/api/desktop/upload")
async def desktop_upload(
    username: str = Form(...),
    files: List[UploadFile] = File(...),
):
    user = str(username or "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="username is required")
    if not files:
        raise HTTPException(status_code=400, detail="no files")
    if len(files) > _DESKTOP_UPLOAD_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too many files (max {_DESKTOP_UPLOAD_MAX_FILES})",
        )

    batch = desktop_uploads_base_dir(user) / str(uuid4())
    batch.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []
    saved_names: list[str] = []
    try:
        for upload_file in files:
            raw_name = safe_desktop_upload_filename(upload_file.filename or "")
            suffix = Path(raw_name).suffix.lower()
            if suffix not in _DESKTOP_UPLOAD_ALLOWED_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"file type not allowed: {raw_name} (suffix {suffix!r})",
                )
            dest = batch / raw_name
            if dest.exists():
                stem = dest.stem
                dest = batch / f"{stem}_{uuid4().hex[:8]}{suffix}"

            size = 0
            with dest.open("wb") as output_file:
                while True:
                    chunk = await upload_file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > _DESKTOP_UPLOAD_MAX_BYTES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"file too large (max {_DESKTOP_UPLOAD_MAX_BYTES} bytes)",
                        )
                    output_file.write(chunk)

            saved_paths.append(str(dest.resolve()))
            saved_names.append(raw_name)
    except HTTPException:
        shutil.rmtree(batch, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(batch, ignore_errors=True)
        raise

    return {"ok": True, "paths": saved_paths, "names": saved_names}


@router.get("/api/desktop/user_preferences")
async def get_user_preferences(username: str = ""):
    user = str(username or "").strip()
    if not user:
        return {"ok": False, "message": "username is required", "preferences": []}
    try:
        from workflow.report_tools import get_db_connection

        conn = get_db_connection()
        if not conn:
            return {"ok": False, "message": "数据库连接失败", "preferences": []}
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, pref_key, pref_value, updated_at FROM user_preferences "
                "WHERE contact_name = %s ORDER BY updated_at DESC",
                (user,),
            )
            rows = cursor.fetchall()
            preferences = []
            for row in rows:
                preferences.append(
                    {
                        "id": row["id"],
                        "pref_key": row["pref_key"],
                        "pref_value": row["pref_value"] or "",
                        "updated_at": str(row["updated_at"])
                        if row["updated_at"]
                        else "",
                    }
                )
            return {"ok": True, "preferences": preferences}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()
    except Exception as e:
        logger.error(f"读取用户偏好失败: {e}")
        return {"ok": False, "message": f"读取失败: {e}", "preferences": []}


@router.post("/api/desktop/user_preferences")
async def save_user_preference(body: dict = Body(default={})):
    username = str((body or {}).get("username") or "").strip()
    pref_key = str((body or {}).get("pref_key") or "").strip()
    pref_value = str((body or {}).get("pref_value") or "")
    if not username:
        return {"ok": False, "message": "username is required"}
    if not pref_key:
        return {"ok": False, "message": "pref_key is required"}
    try:
        from workflow.report_tools import save_user_preference as _save

        _save(username, pref_key, pref_value)
        return {"ok": True, "message": "偏好已保存"}
    except Exception as e:
        logger.error(f"保存用户偏好失败: {e}")
        return {"ok": False, "message": f"保存失败: {e}"}


@router.delete("/api/desktop/user_preferences/{pref_id}")
async def delete_user_preference(pref_id: int, username: str = ""):
    user = str(username or "").strip()
    if not user:
        return {"ok": False, "message": "username is required"}
    try:
        from workflow.report_tools import get_db_connection

        conn = get_db_connection()
        if not conn:
            return {"ok": False, "message": "数据库连接失败"}
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_preferences WHERE id = %s AND contact_name = %s",
                (pref_id, user),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "message": "偏好记录不存在或无权删除"}
            return {"ok": True, "message": "偏好已删除"}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()
    except Exception as e:
        logger.error(f"删除用户偏好失败: {e}")
        return {"ok": False, "message": f"删除失败: {e}"}


@router.get("/api/desktop/prompt_content")
async def get_prompt_content(file: str = ""):
    """读取 prompt 目录下的 markdown 文件内容"""
    allowed = {"rich", "department", "identity"}
    filename = str(file or "").strip()
    if filename not in allowed:
        return {"ok": False, "message": f"不支持的文件，允许: {', '.join(allowed)}"}
    from workflow.config import BASE_DIR

    file_path = Path(BASE_DIR) / "prompt" / f"{filename}.md"
    if not file_path.exists():
        return {"ok": False, "message": f"文件不存在: {filename}.md"}
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"ok": True, "file": filename, "content": content}
    except Exception as e:
        logger.error(f"读取 {filename}.md 失败: {e}")
        return {"ok": False, "message": f"读取失败: {e}"}


@router.get("/api/desktop/mcp_servers_config")
async def get_mcp_servers_config():
    """读取 config/mcp_servers.json 文件内容并返回"""
    from workflow.config import BASE_DIR

    file_path = Path(BASE_DIR) / "config" / "mcp_servers.json"
    if not file_path.exists():
        return {"ok": False, "message": "mcp_servers.json not found"}
    try:
        config = json.loads(file_path.read_text(encoding="utf-8"))
        return {"ok": True, "config": config}
    except Exception as e:
        logger.error(f"读取 mcp_servers.json 失败: {e}")
        return {"ok": False, "message": f"读取失败: {e}"}


@router.get("/api/desktop/wechat_mode_references")
async def get_wechat_mode_references():
    """读取 skills/wechat-mode/references 目录下所有 .md 文件内容"""
    from workflow.config import BASE_DIR

    ref_dir = Path(BASE_DIR) / "skills" / "wechat-mode" / "references"
    if not ref_dir.exists():
        return {"ok": True, "files": []}
    files = []
    for md_path in sorted(ref_dir.glob("*.md")):
        try:
            content = md_path.read_text(encoding="utf-8")
            files.append(
                {"name": md_path.stem, "filename": md_path.name, "content": content}
            )
        except Exception as e:
            logger.error(f"读取 wechat-mode reference {md_path.name} 失败: {e}")
    return {"ok": True, "files": files}


@router.post("/api/desktop/wechat_mode_reference_save")
async def save_wechat_mode_reference(body: dict = Body(default={})):
    """保存 skills/wechat-mode/references 目录下的 .md 文件"""
    filename = str(body.get("filename") or "").strip()
    content = str(body.get("content") or "")
    if not filename:
        return {"ok": False, "message": "filename is required"}
    if (
        not filename.endswith(".md")
        or ".." in filename
        or "/" in filename
        or "\\" in filename
    ):
        return {"ok": False, "message": "invalid filename"}
    from workflow.config import BASE_DIR

    file_path = Path(BASE_DIR) / "skills" / "wechat-mode" / "references" / filename
    if not file_path.exists():
        return {"ok": False, "message": f"文件不存在: {filename}"}
    try:
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"已保存 wechat-mode reference: {filename}")
        return {"ok": True, "message": "保存成功"}
    except Exception as e:
        logger.error(f"保存 wechat-mode reference {filename} 失败: {e}")
        return {"ok": False, "message": f"保存失败: {e}"}


@router.get("/api/desktop/contacts/departments")
async def get_contacts_departments(request: Request):
    """获取公司组织架构部门树，供桌面端联系人面板使用"""
    try:
        from admin_api.services.user_service import UserService

        tenant_id = _extract_tenant_id_from_request(request)
        depts = UserService.get_departments(tenant_id=tenant_id)
        return {"ok": True, "departments": depts}
    except Exception as e:
        logger.error("获取部门列表失败: {}", e)
        return {"ok": False, "departments": []}


@router.get("/api/desktop/contacts/users")
async def get_contacts_users(request: Request):
    """获取公司全部员工列表（含部门信息和在线状态），供桌面端联系人面板使用"""
    try:
        from admin_api.services.user_service import UserService
        from admin_api.routers.client_router import manager

        tenant_id = _extract_tenant_id_from_request(request)
        users, _ = UserService.list_users_paginated(
            tenant_id=tenant_id,
            keyword=None,
            dept_id=None,
            role_id=None,
            status=1,
            limit=2000,
            offset=0,
        )
        simplified = []
        for u in users:
            user_status = manager.get_user_status(u.get("id", ""))
            simplified.append(
                {
                    "id": u.get("id", ""),
                    "username": u.get("username", ""),
                    "name": u.get("name", ""),
                    "dept_id": u.get("dept_id", ""),
                    "dept_name": u.get("dept_name", ""),
                    "title": u.get("title", u.get("position", "")),
                    "wechat_work_id": u.get("wechat_work_id", ""),
                    "is_online": user_status.get("is_online", False),
                }
            )
        return {"ok": True, "users": simplified}
    except Exception as e:
        logger.error("获取联系人列表失败: {}", e)
        return {"ok": False, "users": []}


def _extract_tenant_id_from_request(request: Request) -> Optional[str]:
    """从请求头中提取租户ID，无则返回None"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return None
    try:
        token = auth_header.replace("Bearer ", "").strip()
        if not token:
            return None
        from admin_api.routers.auth_router import verify_token

        session = verify_token(token)
        if session and isinstance(session, dict):
            return session.get("tenant_id")
        return None
    except Exception:
        return None


@router.get("/api/desktop/templates/categories")
async def desktop_template_categories():
    """获取模板分类列表，供桌面端模板管理页面使用"""
    try:
        from admin_api.services import template_service

        categories = template_service.get_categories()
        return {"ok": True, "categories": categories}
    except Exception as e:
        logger.error("桌面端获取模板分类失败: {}", e)
        return {"ok": False, "message": str(e), "categories": []}


@router.get("/api/desktop/templates/list")
async def desktop_template_list(category_key: str = ""):
    """获取启用的模板列表，供桌面端模板管理页面使用（仅为封面图生成访问 URL）"""
    try:
        import os
        from admin_api.services import template_service
        from workflow.config import BASE_DIR

        templates = template_service.get_runtime_templates(
            category_key=category_key, include_download_urls=False
        )

        # 判断本地 template_oss 目录是否有文件
        _template_oss_dir = os.path.join(BASE_DIR, "template_oss")
        _has_local_files = os.path.isdir(_template_oss_dir) and any(
            os.scandir(_template_oss_dir)
        )

        for t in templates:
            cover = t.get("cover_url", "")
            if not cover:
                continue
            if cover.startswith("http"):
                continue
            if _has_local_files:
                # 本地存储模式：通过静态文件路由访问
                t["cover_url"] = "/template_oss/" + cover.replace("\\", "/")
            else:
                # OSS 存储模式：生成 presigned URL
                try:
                    from admin_api.services.oss_service import OssService

                    t["cover_url"] = OssService.generate_presigned_get_url(
                        cover, expires=3600
                    )
                except Exception:
                    t["cover_url"] = ""

        return {"ok": True, "data": templates}
    except Exception as e:
        logger.error("桌面端获取模板列表失败: {}", e)
        return {"ok": False, "message": str(e), "data": []}


# ---- 安全规则配置（桌面端从管理端同步后写入本地文件） ----


@router.get("/api/desktop/content_security_rules")
async def get_content_security_rules():
    """读取桌面端本地 config/content_security_rules.json"""
    from workflow.config import BASE_DIR

    file_path = Path(BASE_DIR) / "config" / "content_security_rules.json"
    if not file_path.exists():
        return {"ok": True, "rules": {}}
    try:
        rules = json.loads(file_path.read_text(encoding="utf-8"))
        return {"ok": True, "rules": rules}
    except Exception as e:
        logger.error("读取 content_security_rules.json 失败: {}", e)
        return {"ok": False, "message": f"读取失败: {e}"}


@router.post("/api/desktop/content_security_rules")
async def save_content_security_rules(request: Request):
    """将管理端同步的安全规则写入桌面端本地 JSON 文件，供 ContentSecurityEngine 热加载"""
    from workflow.config import BASE_DIR

    try:
        body = await request.json()
        rules = body.get("rules")
        if rules is None:
            return {"ok": False, "message": "缺少 rules 字段"}

        file_path = Path(BASE_DIR) / "config" / "content_security_rules.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("桌面端安全规则已写入: {}", file_path)
        return {"ok": True, "message": "安全规则已保存"}
    except Exception as e:
        logger.error("写入 content_security_rules.json 失败: {}", e)
        return {"ok": False, "message": f"写入失败: {e}"}
