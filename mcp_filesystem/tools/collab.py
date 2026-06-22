"""Collaboration tools for workmate.

This module contains tools for creating and managing collaborative tasks
between team members, including searching colleagues, creating collaboration
chains, completing steps, and rejecting steps.
"""

import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote
from typing import Any, Dict, List, Optional

from fastmcp import Context
import aiohttp
from loguru import logger

from ..context import mcp

# Control whether Collaboration tools are exposed
ENABLE_COLLAB_TOOLS = (
    os.environ.get("MCP_ENABLE_COLLAB_TOOLS", "true").lower() == "true"
)

# Token storage (in a real implementation, this would be more secure)
_user_token = None


def _resolve_admin_api_base() -> str:
    """Admin REST root from WORKMATE_ADMIN_API_BASE (.env) via workflow.config."""
    try:
        from ..context import load_env_file

        load_env_file()
    except Exception:
        pass
    for key in ("ADMIN_API_BASE_URL", "WORKMATE_ADMIN_API_BASE"):
        raw = os.environ.get(key, "").strip().rstrip("/")
        if raw:
            try:
                from workflow.config import normalize_admin_api_base

                return normalize_admin_api_base(raw)
            except Exception:
                if raw.endswith("/api/admin"):
                    return raw
                return f"{raw}/api/admin"
    try:
        from workflow.config import get_admin_api_base

        return get_admin_api_base()
    except Exception:
        host = os.environ.get("WORKMATE_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = os.environ.get("WORKMATE_ADMIN_PORT", "8010").strip() or "8010"
        return f"http://{host}:{port}/api/admin"


def _resolve_collab_token() -> str:
    global _user_token
    if _user_token:
        return _user_token
    for key in ("WORKMATE_ADMIN_BEARER_TOKEN", "COLLAB_ADMIN_TOKEN"):
        token = os.environ.get(key, "").strip()
        if token:
            return token
    try:
        from workflow.collab_auth import read_collab_admin_token

        token = read_collab_admin_token()
        if token:
            return token
    except Exception:
        pass
    for base in _collab_token_base_dirs():
        path = base / "desktop_temp" / "collab_admin_token"
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
    return ""


def _collab_token_base_dirs() -> List[Path]:
    bases: List[Path] = []
    override = os.environ.get("WORKMATE_COLLAB_TOKEN_DIR", "").strip()
    if override:
        bases.append(Path(override))
    env_base = os.environ.get("BASE_DIR", "").strip()
    if env_base:
        bases.append(Path(env_base))
    try:
        from workflow.config import BASE_DIR

        bases.append(Path(BASE_DIR))
    except Exception:
        pass
    try:
        from mcp_filesystem.paths import app_base_dir

        bases.append(Path(app_base_dir()))
    except Exception:
        pass
    bases.append(Path.cwd())
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        bases.append(Path(local) / "Workmate")
    bases.append(Path(tempfile.gettempdir()) / "workmate")
    seen: set[str] = set()
    out: List[Path] = []
    for b in bases:
        key = str(b)
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def _format_collab_ts(value: Any) -> str:
    """Format DB/API timestamps for collab tool text output."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if not s:
        return ""
    normalized = s.replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return s[:16] if len(s) >= 16 else s


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_COLLAB_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


def set_collab_token(token: str):
    """Set the authentication token for collaboration API calls."""
    global _user_token
    _user_token = token


def get_auth_headers() -> Dict[str, str]:
    """Get authentication headers with the current token."""
    headers: Dict[str, str] = {}
    token = _resolve_collab_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


_COLLAB_CHAIN_RULES_HINT = (
    "协同链规则：steps 须 2–5 条；每步必填 assignee_user_id（来自 search_colleagues 的 user_id，"
    "username 也可）与 task_prompt；相邻两步不能是同一人；"
    "禁止指派 *Helper、rmms*、observer* 等系统/机器人账号；"
    "用户点名同事时须 search_colleagues(keyword=姓名) 并使用返回的 user_id。"
)


def _is_collab_automation_username_ref(ref: str) -> bool:
    username = str(ref or "").strip().lower()
    if not username:
        return False
    if username.endswith("helper"):
        return True
    return username.startswith("rmms") or username.startswith("observer")


def _format_fastapi_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail.strip()
    if isinstance(detail, list):
        parts: List[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc = item.get("loc") or []
            field = ".".join(str(x) for x in loc if x not in ("body",))
            msg = str(item.get("msg") or "").strip()
            if field and msg:
                parts.append(f"{field}: {msg}")
            elif msg:
                parts.append(msg)
        if parts:
            return "; ".join(parts)
    if detail is not None:
        return json.dumps(detail, ensure_ascii=False)
    return ""


async def _read_admin_api_error(response: aiohttp.ClientResponse) -> str:
    """Extract actionable error text from Admin API responses."""
    try:
        data = await response.json()
        detail = data.get("detail") if isinstance(data, dict) else None
        if detail is None and isinstance(data, dict):
            detail = data.get("message")
        formatted = _format_fastapi_detail(detail)
        if formatted:
            return formatted
    except Exception:
        pass
    reason = getattr(response, "reason", None) or ""
    if reason:
        return f"HTTP {response.status}: {reason}"
    return f"HTTP {response.status}"


async def _collab_api_error(prefix: str, response: aiohttp.ClientResponse) -> str:
    detail = await _read_admin_api_error(response)
    return f"{prefix}: {detail} (HTTP {response.status})"


def _normalize_chain_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map common Agent field aliases to API schema before validation."""
    normalized: List[Dict[str, Any]] = []
    for raw in steps or []:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        if not str(step.get("assignee_user_id") or "").strip():
            alt = step.get("assignee_username") or step.get("assignee")
            if alt:
                step["assignee_user_id"] = str(alt).strip()
        if not str(step.get("task_prompt") or "").strip():
            alt = step.get("task_description") or step.get("prompt")
            if alt:
                step["task_prompt"] = str(alt).strip()
        normalized.append(step)
    return normalized


def _validate_collab_chain_steps(steps: List[Dict[str, Any]]) -> Optional[str]:
    """Client-side checks mirroring collab_router.create_collab_chain business rules."""
    if not isinstance(steps, list):
        return "steps 必须是数组（list），每项为 {assignee_user_id, task_prompt}。"
    count = len(steps)
    if count < 2 or count > 5:
        return (
            f"协同链需要 2–5 个步骤，当前为 {count} 步。"
            " 请增加步骤（至少 2 人依次协作）或减少步骤（最多 5 步）。"
        )
    assignee_refs: List[str] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return f"steps 第 {index} 项必须是对象。"
        assignee = str(step.get("assignee_user_id") or "").strip()
        if not assignee:
            return (
                f"steps 第 {index} 步缺少 assignee_user_id。"
                " 请先调用 search_colleagues，使用返回的 user_id（UUID）。"
            )
        if _is_collab_automation_username_ref(assignee):
            return (
                f"steps 第 {index} 步不能指派系统/机器人账号 {assignee}。"
                " 请 search_colleagues 选择真实同事。"
            )
        prompt = str(step.get("task_prompt") or "").strip()
        if not prompt:
            return f"steps 第 {index} 步缺少 task_prompt（该步任务说明）。"
        assignee_refs.append(assignee)
    for i in range(1, len(assignee_refs)):
        if assignee_refs[i] == assignee_refs[i - 1]:
            return (
                f"第 {i} 步与第 {i + 1} 步不能指派给同一人（assignee_user_id 相同：{assignee_refs[i]}）。"
                " 请更换其中一步的执行人，或合并为一步。"
            )
    return None


def _colleague_display_name(colleague: dict) -> str:
    """Prefer sys_users.name from API; fall back to login username."""
    return str(colleague.get("name") or colleague.get("username") or "").strip()


def _format_colleagues_markdown_table(colleagues: List[dict]) -> str:
    """Build a markdown table so the agent shows name (not username) in the 姓名 column."""
    total = len(colleagues)
    lines = [
        f"当前同事列表（共{total}人）。姓名列=用户表 sys_users.name（未设置时与登录账号相同）。",
        "【系统】向用户展示时必须原样使用下表「姓名」列，禁止改为 username 登录账号。",
        "指派协同时请使用 user_id（UUID），不要使用登录账号 username。",
        "系统/机器人账号（*Helper、rmms*、observer*）已自动排除，不会出现在列表中。",
        "用户点名某同事时，须用 search_colleagues(keyword=该姓名) 查到对应 user_id 后再 create_collab_chain。",
        "",
        "| 状态 | 姓名 | 部门 | 角色 | user_id |",
        "| --- | --- | --- | --- | --- |",
    ]
    for colleague in colleagues:
        status = "在线" if colleague.get("is_online") else "离线"
        name = _colleague_display_name(colleague)
        if colleague.get("is_self"):
            name = f"{name}（你）"
        dept = str(colleague.get("dept_name") or "").strip() or "—"
        role = str(colleague.get("role_name") or "").strip() or "—"
        uid = str(colleague.get("user_id") or "").strip()
        lines.append(f"| {status} | {name} | {dept} | {role} | `{uid}` |")
    return "\n".join(lines)


@register_tool()
async def search_colleagues(
    ctx: Context,
    keyword: Optional[str] = None,
    dept_name: Optional[str] = None,
    role_name: Optional[str] = None,
) -> str:
    """Search for colleagues with optional filtering.

    Args:
        keyword: Search keyword (matches display name, username, role name, or department name)
        dept_name: Filter by department name
        role_name: Filter by role name
        ctx: MCP context

    Returns:
        Formatted list of colleagues
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/colleagues"
        params = {}
        if keyword:
            params["keyword"] = keyword
        if dept_name:
            params["dept_name"] = dept_name
        if role_name:
            params["role_name"] = role_name

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=get_auth_headers()
            ) as response:
                if response.status != 200:
                    return await _collab_api_error(
                        "Error searching colleagues", response
                    )

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                colleagues = result.get("colleagues", [])

                if not colleagues:
                    return "No colleagues found matching your criteria."

                return _format_colleagues_markdown_table(colleagues)
    except Exception as e:
        return f"Error searching colleagues: {str(e)}"


@register_tool()
async def create_collab_chain(
    ctx: Context,
    title: str,
    description: Optional[str],
    steps: List[Dict[str, Any]],
) -> str:
    """Create a new collaboration chain.

    Args:
        title: Title of the collaboration chain
        description: Optional description
        steps: List of step definitions, each containing:
            - assignee_user_id: sys_users.id (UUID from search_colleagues); username also accepted
            - task_prompt: Prompt/description for the task
        ctx: MCP context

    Returns:
        Result of chain creation. On failure, returns a clear reason (step count 2–5,
        adjacent steps must differ, missing fields, or Admin API detail).

    Rules:
        - 2–5 steps required
        - assignee_user_id and task_prompt required per step
        - consecutive steps cannot share the same assignee_user_id
    """
    try:
        normalized_steps = _normalize_chain_steps(steps)
        validation_error = _validate_collab_chain_steps(normalized_steps)
        if validation_error:
            return f"Error creating chain: {validation_error}\n\n{_COLLAB_CHAIN_RULES_HINT}"

        url = f"{_resolve_admin_api_base()}/collab/chains"
        payload = {
            "title": title,
            "description": description,
            "steps": normalized_steps,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=get_auth_headers()
            ) as response:
                if response.status != 200:
                    api_err = await _collab_api_error("Error creating chain", response)
                    return f"{api_err}\n\n{_COLLAB_CHAIN_RULES_HINT}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                chain_id = result.get("chain_id")
                if str(result.get("status") or "").strip() == "running":
                    step_id = result.get("step_id") or ""
                    return (
                        f"Successfully created and started collaboration chain! "
                        f"Chain ID: {chain_id}, step 1 is now running"
                        + (f" (step_id: {step_id})" if step_id else "")
                        + "."
                    )

                start_msg = await _try_start_collab_chain(session, chain_id)
                if start_msg:
                    return start_msg
                return (
                    f"Successfully created collaboration chain (Chain ID: {chain_id}), "
                    "but auto-start failed. Call start_collab_chain(chain_id) manually."
                )
    except Exception as e:
        return f"Error creating collaboration chain: {str(e)}"


async def _try_start_collab_chain(session: aiohttp.ClientSession, chain_id: str) -> str:
    """Fallback when older Admin API creates chain in defining state only."""
    url = f"{_resolve_admin_api_base()}/collab/chains/{chain_id}/start"
    async with session.post(url, headers=get_auth_headers()) as response:
        if response.status == 200:
            result = await response.json()
            if result.get("success"):
                step_id = result.get("step_id") or ""
                return (
                    f"Successfully created and started collaboration chain! "
                    f"Chain ID: {chain_id}, step 1 is now running"
                    + (f" (step_id: {step_id})" if step_id else "")
                    + "."
                )
        if response.status == 400:
            try:
                data = await response.json()
                detail = str(data.get("detail") or "")
                if "状态不正确" in detail:
                    return (
                        f"Successfully created collaboration chain! "
                        f"Chain ID: {chain_id} (already running)."
                    )
            except Exception:
                pass
        api_err = await _collab_api_error("Error starting chain after create", response)
        return f"Chain created ({chain_id}) but start failed: {api_err}"


@register_tool()
async def start_collab_chain(
    ctx: Context,
    chain_id: str,
) -> str:
    """Start a collaboration chain.

    Args:
        chain_id: ID of the chain to start
        ctx: MCP context

    Returns:
        Result of starting the chain
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/chains/{chain_id}/start"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=get_auth_headers()) as response:
                if response.status != 200:
                    return await _collab_api_error("Error starting chain", response)

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                return f"Successfully started collaboration chain {chain_id}!"
    except Exception as e:
        return f"Error starting collaboration chain: {str(e)}"


@register_tool()
async def list_my_collab_tasks(
    ctx: Context,
) -> str:
    """List all collaboration tasks that involve the current user.

    Args:
        ctx: MCP context

    Returns:
        Formatted list of tasks
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/chains"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=get_auth_headers()) as response:
                if response.status != 200:
                    return f"Error listing tasks: HTTP {response.status}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                chains = result.get("chains", [])

                if not chains:
                    return "No collaboration tasks found."

                output = ["Your collaboration tasks:"]
                for chain in chains:
                    status_icon = {
                        "defining": "📝",
                        "running": "🔄",
                        "completed": "✅",
                        "cancelled": "❌",
                    }.get(chain.get("status"), "❓")

                    output.append(f"{status_icon} {chain['title']} (ID: {chain['id']})")
                    output.append(f"  Status: {chain.get('status', 'unknown')}")
                    output.append(
                        f"  Current step: {chain.get('current_step', 0)} / {chain.get('total_steps', 0)}"
                    )
                    created = _format_collab_ts(chain.get("created_at"))
                    if created:
                        output.append(f"  Created: {created}")
                    updated = _format_collab_ts(chain.get("updated_at"))
                    if updated and updated != created:
                        output.append(f"  Updated: {updated}")
                    if chain.get("status") == "completed":
                        done = _format_collab_ts(chain.get("completed_at"))
                        if done:
                            output.append(f"  Completed: {done}")
                    if chain.get("description"):
                        output.append(f"  Description: {chain['description']}")
                    output.append("")

                return "\n".join(output)
    except Exception as e:
        return f"Error listing collaboration tasks: {str(e)}"


@register_tool()
async def get_collab_chain_detail(
    ctx: Context,
    chain_id: str,
) -> str:
    """Get detailed information about a specific collaboration chain.

    Args:
        chain_id: ID of the chain
        ctx: MCP context

    Returns:
        Detailed information about the chain
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/chains/{chain_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=get_auth_headers()) as response:
                if response.status != 200:
                    return f"Error getting chain detail: HTTP {response.status}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                chain = result.get("chain", {})
                steps = result.get("steps", [])
                attachments = result.get("attachments", [])

                output = [f"Chain: {chain.get('title')}"]
                output.append(f"ID: {chain.get('id')}")
                output.append(f"Status: {chain.get('status')}")
                created = _format_collab_ts(chain.get("created_at"))
                if created:
                    output.append(f"Created: {created}")
                updated = _format_collab_ts(chain.get("updated_at"))
                if updated and updated != created:
                    output.append(f"Updated: {updated}")
                if chain.get("status") == "completed":
                    done = _format_collab_ts(chain.get("completed_at"))
                    if done:
                        output.append(f"Completed: {done}")
                if chain.get("description"):
                    output.append(f"Description: {chain['description']}")
                output.append("")

                output.append("Steps:")
                running_step_id = ""
                for step in steps:
                    status_icon = {
                        "pending": "⏳",
                        "running": "🔄",
                        "completed": "✅",
                        "rejected": "❌",
                    }.get(step.get("status"), "❓")
                    is_running = step.get("status") == "running"
                    step_uuid = str(step.get("id") or "").strip()
                    if is_running and step_uuid:
                        running_step_id = step_uuid

                    prefix = (
                        ">>> CURRENT (complete this step) <<< " if is_running else ""
                    )
                    output.append(
                        f"{prefix}Step {step.get('step_index')}: {status_icon} "
                        f"Assigned to {step.get('assignee_username')}"
                    )
                    if step_uuid:
                        output.append(
                            f"  Step ID (pass to complete_collab_step): {step_uuid}"
                        )
                    started = _format_collab_ts(step.get("started_at"))
                    if started:
                        output.append(f"  Started: {started}")
                    completed = _format_collab_ts(step.get("completed_at"))
                    if completed:
                        output.append(f"  Completed: {completed}")
                    if step.get("task_prompt"):
                        output.append(f"  Task: {step['task_prompt']}")
                    if step.get("status") == "completed" and step.get("result_summary"):
                        output.append(f"  Result: {step['result_summary']}")
                    if step.get("relay_note"):
                        output.append(f"  Note: {step['relay_note']}")
                    output.append("")

                if running_step_id:
                    output.append(
                        f"To complete the current step, call complete_collab_step "
                        f"with step_id={running_step_id!r}"
                    )
                    output.append("")

                if attachments:
                    output.append("Attachments:")
                    for att in attachments:
                        line = (
                            f"  - {att.get('original_filename')} (ID: {att.get('id')})"
                        )
                        uploaded = _format_collab_ts(att.get("created_at"))
                        if uploaded:
                            line += f", uploaded {uploaded}"
                        output.append(line)

                return "\n".join(output)
    except Exception as e:
        return f"Error getting chain detail: {str(e)}"


_GENERATED_FILES_JSON_RE = re.compile(
    r'\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}',
    re.DOTALL,
)


def _extract_generated_files_from_text(text: Optional[str]) -> List[str]:
    """Parse generated_files JSON blocks from agent result text (MANDATORY rule 9)."""
    if not text:
        return []
    out: List[str] = []
    for match in _GENERATED_FILES_JSON_RE.finditer(str(text)):
        try:
            data = json.loads(match.group(0))
            for item in data.get("generated_files") or []:
                path = str(item or "").strip().strip('"').strip("'")
                if path:
                    out.append(path)
        except Exception:
            continue
    return out


def _collab_upload_storage_dir() -> str:
    return os.path.abspath(os.getenv("COLLAB_UPLOAD_DIR", "./collab_uploads"))


def _collab_output_base_dir() -> str:
    raw = os.environ.get("OUTPUT_BASE_DIR", "").strip()
    if raw:
        return os.path.abspath(raw)
    try:
        from workflow.config import OUTPUT_BASE_DIR

        cfg = str(OUTPUT_BASE_DIR or "").strip()
        return os.path.abspath(cfg) if cfg else ""
    except Exception:
        return ""


def _collab_allowed_output_roots() -> List[str]:
    """All roots where agent deliverables may live (desktop_temp vs workspace, etc.)."""
    seen: set[str] = set()
    roots: List[str] = []

    def _add(raw: str) -> None:
        s = str(raw or "").strip()
        if not s:
            return
        try:
            absp = os.path.abspath(s)
        except OSError:
            return
        key = os.path.normcase(absp)
        if key in seen:
            return
        seen.add(key)
        roots.append(absp)

    _add(os.environ.get("OUTPUT_BASE_DIR", ""))
    _add(_collab_output_base_dir())
    try:
        from workflow.config import (
            BASE_DIR,
            MCP_READ_ALLOWED_DIRS,
            MCP_WRITE_ALLOWED_DIRS,
            OUTPUT_BASE_DIR,
        )

        _add(OUTPUT_BASE_DIR)
        for d in MCP_WRITE_ALLOWED_DIRS or []:
            _add(d)
        for d in MCP_READ_ALLOWED_DIRS or []:
            _add(d)
        base = str(BASE_DIR or "").strip()
        if base:
            _add(os.path.join(base, "desktop_temp", "workspace"))
            _add(os.path.join(base, "workspace"))
    except Exception:
        pass
    return roots


def _path_under_output_root(file_path: str, root: str) -> bool:
    try:
        fp = os.path.normcase(os.path.abspath(file_path))
        rt = os.path.normcase(os.path.abspath(root))
    except OSError:
        return False
    if fp == rt:
        return True
    sep = os.sep
    return fp.startswith(rt + sep)


def _filter_collab_deliverable_paths(paths: List[str]) -> List[str]:
    """
    Keep only existing deliverable files for this collab step.
    Does not scan directories — only explicit paths from generated_files / output_file_paths.
    """
    seen: set[str] = set()
    result: List[str] = []
    upload_dir = _collab_upload_storage_dir()
    output_roots = _collab_allowed_output_roots()

    for raw in paths:
        path = str(raw or "").strip().strip('"').strip("'")
        if not path or path in seen:
            continue
        if not os.path.isfile(path):
            logger.info("collab deliverable skipped (not a file): {}", path)
            continue
        absp = os.path.abspath(path)
        if upload_dir and _path_under_output_root(absp, upload_dir):
            logger.info("collab deliverable skipped (collab upload dir): {}", path)
            continue
        if output_roots and not any(
            _path_under_output_root(absp, root) for root in output_roots
        ):
            logger.info(
                "collab deliverable skipped (outside allowed output roots): {}",
                path,
            )
            continue
        seen.add(path)
        result.append(path)
    return result


def _resolve_collab_output_paths(
    output_file_paths: Optional[List[str]],
    result_summary: Optional[str],
    result_detail: Optional[str],
) -> List[str]:
    """Merge explicit paths with generated_files declared in completion text."""
    combined: List[str] = []
    for fp in output_file_paths or []:
        p = str(fp or "").strip()
        if p:
            combined.append(p)
    combined.extend(_extract_generated_files_from_text(result_summary))
    combined.extend(_extract_generated_files_from_text(result_detail))
    return _filter_collab_deliverable_paths(combined)


def _normalize_collab_filename(name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    if "%" in n:
        try:
            decoded = unquote(n.replace("+", " "))
            if decoded.strip():
                return decoded.strip()
        except Exception:
            pass
    return n


async def _fetch_step_attachment_name_to_id(
    chain_id: str, step_id: str
) -> Dict[str, str]:
    """Map original_filename -> attachment_id for one step (for upload dedupe)."""
    cid = str(chain_id or "").strip()
    sid = str(step_id or "").strip()
    if not cid or not sid:
        return {}
    url = f"{_resolve_admin_api_base()}/collab/chains/{cid}"
    out: Dict[str, str] = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=get_auth_headers()) as response:
                if response.status != 200:
                    return out
                result = await response.json()
                for att in result.get("attachments") or []:
                    if str(att.get("step_id") or "") != sid:
                        continue
                    fname = _normalize_collab_filename(
                        str(att.get("original_filename") or "")
                    )
                    att_id = str(att.get("id") or "").strip()
                    if fname and att_id:
                        out[fname] = att_id
    except Exception as exc:
        logger.info("collab fetch step attachments failed: {}", exc)
    return out


def _dedupe_paths(paths: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in paths:
        path = str(raw or "").strip()
        if not path:
            continue
        try:
            key = os.path.normcase(os.path.abspath(path))
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


async def _upload_collab_attachment_impl(
    file_path: str,
    chain_id: str,
    step_id: str,
) -> Optional[str]:
    """Upload a local file; return attachment_id or None on failure."""
    if not os.path.exists(file_path):
        return None
    url = f"{_resolve_admin_api_base()}/collab/attachments/upload"
    params = {"chain_id": chain_id, "step_id": step_id}
    filename = _normalize_collab_filename(os.path.basename(file_path))
    async with aiohttp.ClientSession() as session:
        with open(file_path, "rb") as f:
            form_data = aiohttp.FormData()
            form_data.add_field("file", f, filename=filename)
            async with session.post(
                url, params=params, data=form_data, headers=get_auth_headers()
            ) as response:
                if response.status != 200:
                    return None
                result = await response.json()
                if not result.get("success"):
                    return None
                return str(result.get("attachment_id") or "").strip() or None


@register_tool()
async def complete_collab_step(
    ctx: Context,
    step_id: str,
    result_summary: str,
    result_detail: Optional[str] = None,
    relay_note: Optional[str] = None,
    attachment_ids: Optional[List[str]] = None,
    output_file_paths: Optional[List[str]] = None,
    chain_id: Optional[str] = None,
    step_index: Optional[int] = None,
) -> str:
    """Complete a collaboration step and forward to the next person.

    Args:
        step_id: Step UUID from get_collab_chain_detail (not chain_id-step-N)
        result_summary: Summary of the result; may include {"generated_files": [...]} JSON
        result_detail: Optional detailed result; may also include generated_files JSON
        relay_note: Optional note for the next person
        attachment_ids: Optional list of attachment IDs already uploaded
        output_file_paths: Optional extra deliverable paths (in addition to generated_files)
        chain_id: Required when uploading step outputs; optional fallback for step lookup
        step_index: Optional step index fallback (use with chain_id)
        ctx: MCP context

    Returns:
        Result of completing the step

    Note:
        Only collab deliverables are auto-uploaded: paths from generated_files JSON in
        result_summary/result_detail, plus output_file_paths. Does NOT scan OUTPUT_BASE_DIR.
        The step must have at least one attachment on the server before complete (upload files
        first via upload_collab_attachment or output_file_paths / generated_files).
    """
    try:
        cid = (chain_id or "").strip()
        uploaded_ids: List[str] = [
            str(i).strip() for i in (attachment_ids or []) if str(i).strip()
        ]
        deliverable_paths = _dedupe_paths(
            _resolve_collab_output_paths(
                output_file_paths, result_summary, result_detail
            )
        )
        raw_paths: List[str] = []
        for fp in output_file_paths or []:
            p = str(fp or "").strip()
            if p:
                raw_paths.append(p)
        raw_paths.extend(_extract_generated_files_from_text(result_summary))
        raw_paths.extend(_extract_generated_files_from_text(result_detail))
        if raw_paths and not deliverable_paths:
            existing = [p for p in raw_paths if os.path.isfile(p)]
            logger.info(
                "collab complete blocked: {} generated_files path(s), {} on disk, 0 allowed",
                len(raw_paths),
                len(existing),
            )
            if existing:
                sample = existing[0]
                extra = f" (+{len(existing) - 1} more)" if len(existing) > 1 else ""
                return (
                    "Error: collab deliverables were not uploaded. File(s) exist but are "
                    f"outside allowed output directories: {sample}{extra}. "
                    "Save under OUTPUT_BASE_DIR (desktop workspace) or call "
                    "upload_collab_attachment before complete_collab_step."
                )
            return (
                "Error: generated_files listed in result but no matching files on disk. "
                f"First path: {raw_paths[0]}"
            )
        if deliverable_paths:
            if not cid:
                return (
                    "Error: chain_id is required when uploading collab outputs. "
                    "Pass chain_id from get_collab_chain_detail."
                )
            existing_by_name = await _fetch_step_attachment_name_to_id(cid, step_id)
            for path in deliverable_paths:
                fname = _normalize_collab_filename(os.path.basename(path))
                if fname and fname in existing_by_name:
                    att_id = existing_by_name[fname]
                    if att_id and att_id not in uploaded_ids:
                        uploaded_ids.append(att_id)
                    logger.info("collab deliverable skip duplicate upload: {}", fname)
                    continue
                att_id = await _upload_collab_attachment_impl(path, cid, step_id)
                if not att_id:
                    return f"Error uploading collab output before complete: {path}"
                uploaded_ids.append(att_id)
                if fname:
                    existing_by_name[fname] = att_id

        url = f"{_resolve_admin_api_base()}/collab/steps/{step_id}/complete"
        params: Dict[str, Any] = {}
        if chain_id:
            params["chain_id"] = chain_id
        if step_index is not None:
            params["step_index"] = step_index
        payload = {
            "result_summary": result_summary,
            "result_detail": result_detail,
            "relay_note": relay_note,
            "attachment_ids": uploaded_ids,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, params=params, headers=get_auth_headers()
            ) as response:
                if response.status != 200:
                    err = await _read_admin_api_error(response)
                    hint = (
                        " Call get_collab_chain_detail and use the Step ID shown for the "
                        "running step."
                    )
                    if "步骤不存在" in err or response.status == 404:
                        return f"Error completing step: {err}.{hint}"
                    return f"Error completing step: {err}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                output = ["Successfully completed step!"]
                if deliverable_paths:
                    output.append(
                        f"Uploaded {len(deliverable_paths)} collab output file(s): "
                        + ", ".join(os.path.basename(p) for p in deliverable_paths)
                    )
                if uploaded_ids:
                    output.append(
                        f"Linked {len(uploaded_ids)} attachment id(s) on complete"
                    )
                if result.get("chain_completed"):
                    output.append("The entire collaboration chain is now complete!")
                elif result.get("next_step_id"):
                    output.append(
                        f"Forwarded to next step (ID: {result['next_step_id']})"
                    )

                return "\n".join(output)
    except Exception as e:
        return f"Error completing step: {str(e)}"


@register_tool()
async def delete_collab_chain(
    ctx: Context,
    chain_id: str,
) -> str:
    """Delete a collaboration chain. Only the initiator may delete; completed chains cannot be deleted.

    Args:
        chain_id: Collaboration chain ID
        ctx: MCP context

    Returns:
        Deletion result
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/chains/{chain_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=get_auth_headers()) as response:
                if response.status != 200:
                    err = await _read_admin_api_error(response)
                    return f"Error deleting chain: {err}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                return f"Successfully deleted collaboration chain {chain_id}."
    except Exception as e:
        return f"Error deleting collaboration chain: {str(e)}"


@register_tool()
async def reject_collab_step(
    ctx: Context,
    step_id: str,
    reject_reason: str,
    chain_id: Optional[str] = None,
    step_index: Optional[int] = None,
) -> str:
    """Reject a collaboration step and send it back to the previous person.

    Args:
        step_id: Step UUID from get_collab_chain_detail
        reject_reason: Reason for rejection
        chain_id: Optional chain ID fallback when step_id lookup fails
        step_index: Optional step index fallback (use with chain_id)
        ctx: MCP context

    Returns:
        Result of rejecting the step
    """
    try:
        url = f"{_resolve_admin_api_base()}/collab/steps/{step_id}/reject"
        params: Dict[str, Any] = {}
        if chain_id:
            params["chain_id"] = chain_id
        if step_index is not None:
            params["step_index"] = step_index
        payload = {"reject_reason": reject_reason}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, params=params, headers=get_auth_headers()
            ) as response:
                if response.status != 200:
                    err = await _read_admin_api_error(response)
                    return f"Error rejecting step: {err}"

                result = await response.json()
                if not result.get("success"):
                    return f"Error: {result.get('message', 'Unknown error')}"

                return f"Successfully rejected step! Sent back to previous step (ID: {result.get('prev_step_id')})"
    except Exception as e:
        return f"Error rejecting step: {str(e)}"


@register_tool()
async def upload_collab_attachment(
    ctx: Context,
    file_path: str,
    chain_id: str,
    step_id: str,
) -> str:
    """Upload an attachment for a collaboration step.

    Args:
        file_path: Path to the file to upload
        chain_id: ID of the collaboration chain
        step_id: ID of the step
        ctx: MCP context

    Returns:
        Result of the upload
    """
    try:
        if not os.path.exists(file_path):
            return f"Error: File not found: {file_path}"

        att_id = await _upload_collab_attachment_impl(file_path, chain_id, step_id)
        if not att_id:
            return "Error uploading attachment: upload failed"
        return f"Successfully uploaded attachment! Attachment ID: {att_id}"
    except Exception as e:
        return f"Error uploading attachment: {str(e)}"
