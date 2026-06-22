import asyncio
from pathlib import Path

from workflow.config import BASE_DIR, OUTPUT_BASE_DIR

_RUNTIME_OUTPUT_BASE_DIR = str(Path(OUTPUT_BASE_DIR).expanduser().resolve())

_PRELOAD_STATUS = {
    "enabled": False,
    "done": False,
    "ok": False,
    "message": "",
}

_MCP_RUNTIME_SELF_CHECK: dict = {
    "ok": True,
    "checked": False,
    "summary": "",
    "missing_commands": [],
    "stdio_servers": [],
    "missing_count": 0,
    "stdio_count": 0,
}

_DESKTOP_CHAT_STATE_LOCK = asyncio.Lock()
_STREAM_STOP_FLAGS: dict[str, bool] = {}
_STREAM_STOP_LOCK = asyncio.Lock()

_MCP_PRELOAD_STATUS: dict = {
    "done": False,
    "ok": False,
    "message": "",
    "success_servers": [],
    "failed_servers": [],
    "tools_count": 0,
}


def desktop_chat_state_file() -> Path:
    return Path(BASE_DIR) / "config" / "desktop_chat_states.json"


def checkpointer_db_path() -> Path:
    return Path(BASE_DIR) / "checkpoints" / "checkpoints.db"


def get_runtime_output_base_dir() -> str:
    return _RUNTIME_OUTPUT_BASE_DIR


def set_runtime_output_base_dir(value: str) -> None:
    global _RUNTIME_OUTPUT_BASE_DIR
    _RUNTIME_OUTPUT_BASE_DIR = str(value)


def get_preload_status() -> dict:
    return _PRELOAD_STATUS


def get_mcp_runtime_self_check() -> dict:
    return _MCP_RUNTIME_SELF_CHECK


def set_mcp_runtime_self_check(value: dict) -> None:
    global _MCP_RUNTIME_SELF_CHECK
    _MCP_RUNTIME_SELF_CHECK = value


def get_mcp_preload_status() -> dict:
    return _MCP_PRELOAD_STATUS


def set_mcp_preload_status(value: dict) -> None:
    global _MCP_PRELOAD_STATUS
    _MCP_PRELOAD_STATUS = value


def get_desktop_chat_state_lock() -> asyncio.Lock:
    return _DESKTOP_CHAT_STATE_LOCK


def _stream_stop_key(thread_id: str, session_id: str) -> str:
    return f"{thread_id or ''}::{session_id or ''}"


async def set_stream_stop_flag(thread_id: str, session_id: str, value: bool) -> None:
    key = _stream_stop_key(thread_id, session_id)
    async with _STREAM_STOP_LOCK:
        if value:
            _STREAM_STOP_FLAGS[key] = True
        else:
            _STREAM_STOP_FLAGS.pop(key, None)


async def is_stream_stopped(thread_id: str, session_id: str) -> bool:
    key = _stream_stop_key(thread_id, session_id)
    async with _STREAM_STOP_LOCK:
        return bool(_STREAM_STOP_FLAGS.get(key, False))
