"""Parse collab upstream attachments and inject markdown into prompts / user input."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from loguru import logger

_CHAIN_ID_RE = re.compile(
    r"协同链\s*ID\s*[：:]\s*"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_STEP_INDEX_RE = re.compile(r"步骤\s*[：:]\s*(\d+)", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)
_COLLAB_DUP_SUFFIX_RE = re.compile(r"^(.+)_(\d+)$")
# Upstream step summaries sometimes embed Step-1 output under .../YYYYMMDD/... — misleads later steps.
_DATE_DIR_ABS_PATH_RE = re.compile(
    r"[A-Za-z]:[^\s\n]*?[/\\]\d{8}[/\\][^\s\n]+",
    re.IGNORECASE,
)
# Other assignee workspace paths (e.g. .../workspace/qiuhao/20260529/file.md)
_OTHER_USER_DATE_PATH_RE = re.compile(
    r"[^\s\n]*?[/\\]workspace[/\\][^\s\n/\\]+[/\\]\d{8}[/\\][^\s\n]+",
    re.IGNORECASE,
)
_SOURCE_PREFIXES = (
    "【workmate桌面端】",
    "【定时任务】",
    "【协同任务】",
    "【企业微信】",
)

MAX_PARSED_CHARS = int(os.getenv("COLLAB_PARSED_ATTACHMENT_MAX_CHARS", "120000"))


def _reader_allowed_dirs() -> List[str]:
    from workflow.config import MCP_READ_ALLOWED_DIRS, OUTPUT_BASE_DIR

    allowed: List[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        s = str(raw or "").strip()
        if not s:
            return
        try:
            key = os.path.normcase(os.path.abspath(s))
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        allowed.append(s)

    for d in MCP_READ_ALLOWED_DIRS or []:
        _add(d)
    _add(os.environ.get("OUTPUT_BASE_DIR", ""))
    _add(OUTPUT_BASE_DIR)
    _add(os.environ.get("COLLAB_UPLOAD_DIR", ""))
    collab_default = os.path.abspath(os.getenv("COLLAB_UPLOAD_DIR", "./collab_uploads"))
    _add(collab_default)
    if not allowed:
        _add(os.getcwd())
    return allowed


async def parse_attachment_paths_to_sections(file_paths: Sequence[str]) -> List[str]:
    """Parse local files to markdown sections (one per file)."""
    from mcp_filesystem.doc_reader import DocumentReader
    from mcp_filesystem.security import PathValidator

    validator = PathValidator(_reader_allowed_dirs())
    reader = DocumentReader(validator)
    sections: List[str] = []
    for file_path in file_paths:
        path = str(file_path or "").strip()
        if not path:
            continue
        name = Path(path).name
        if not os.path.isfile(path):
            logger.info("[collab附件] 文件不存在，跳过: {}", path)
            sections.append(f"## 附件：{name}\n\n[附件文件不存在]")
            continue
        try:
            md_content = await reader.read_to_markdown(path)
            sections.append(f"## 附件：{name}（完整路径：{path}）\n\n{md_content}")
            logger.info("[collab附件] 已解析: {}", path)
        except Exception as exc:
            logger.error("[collab附件] 解析失败 {}: {}", path, exc)
            sections.append(f"## 附件：{name}\n\n[附件解析失败: {exc}]")
    return sections


def _truncate_parsed_block(text: str) -> str:
    if len(text) <= MAX_PARSED_CHARS:
        return text
    logger.info(
        "[collab附件] 解析内容过长 ({} chars)，截断至 {}",
        len(text),
        MAX_PARSED_CHARS,
    )
    return (
        text[: MAX_PARSED_CHARS - 80]
        + "\n\n…（上游附件解析内容已截断，请通过协同附件下载完整文件）"
    )


async def build_parsed_block_for_paths(
    file_paths: Sequence[str],
    *,
    heading: str = "",
) -> str:
    paths = [str(p).strip() for p in file_paths if str(p or "").strip()]
    if not paths:
        return ""
    sections = await parse_attachment_paths_to_sections(paths)
    if not sections:
        return ""
    body = _truncate_parsed_block("\n\n---\n\n".join(sections))
    if heading:
        return f"### {heading}\n\n{body}"
    return body


def _canonical_collab_basename(filename: str) -> str:
    """Group legacy duplicate sync names (e.g. foo_1.md) under foo.md."""
    p = Path(str(filename or "").strip())
    stem, suffix = p.stem, p.suffix
    m = _COLLAB_DUP_SUFFIX_RE.match(stem)
    if m:
        return m.group(1) + suffix
    return p.name


def _pick_canonical_collab_files(paths: Sequence[str]) -> List[str]:
    groups: dict[str, List[str]] = {}
    for raw in paths:
        path = str(raw or "").strip()
        if not path:
            continue
        key = _canonical_collab_basename(Path(path).name)
        groups.setdefault(key, []).append(path)
    out: List[str] = []
    for key, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        preferred = [p for p in group if Path(p).name == key]
        if preferred:
            out.append(preferred[0])
            continue
        out.append(max(group, key=lambda p: os.path.getmtime(p)))
    return sorted(out)


def list_local_collab_upstream_files(
    *,
    output_base_dir: str,
    username: str,
    chain_id: str,
    before_step_index: int,
) -> List[str]:
    """Files synced under {output_base}/{user}/collab/{chain_id}/step_N/."""
    user = str(username or "").strip()
    cid = str(chain_id or "").strip()
    before = int(before_step_index or 0)
    if not user or not cid or before <= 1:
        return []
    base = Path(str(output_base_dir or "").strip()) / user / "collab" / cid
    if not base.is_dir():
        return []
    out: List[str] = []
    for step_n in range(1, before):
        step_dir = base / f"step_{step_n}"
        if not step_dir.is_dir():
            continue
        step_paths = [
            str(entry.resolve())
            for entry in sorted(step_dir.iterdir())
            if entry.is_file() and entry.name != ".inbound_sync.json"
        ]
        out.extend(_pick_canonical_collab_files(step_paths))
    return out


def _strip_source_prefixes(text: str) -> str:
    raw = str(text or "")
    for prefix in _SOURCE_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].lstrip()
    return raw


def _resolve_output_base_dir() -> str:
    try:
        from api.runtime_state import get_runtime_output_base_dir

        resolved = str(get_runtime_output_base_dir() or "").strip()
        if resolved:
            return resolved
    except Exception:
        pass
    from workflow.config import OUTPUT_BASE_DIR

    return str(OUTPUT_BASE_DIR or "").strip()


def infer_step_index_from_local_sync(
    *,
    output_base_dir: str,
    username: str,
    chain_id: str,
) -> Optional[int]:
    """Infer current step when inbound sync has step_1..step_N-1 under collab/."""
    user = str(username or "").strip()
    cid = str(chain_id or "").strip()
    base = Path(str(output_base_dir or "").strip()) / user / "collab" / cid
    if not base.is_dir():
        return None
    indices: List[int] = []
    for entry in base.iterdir():
        if not entry.is_dir() or not entry.name.startswith("step_"):
            continue
        try:
            indices.append(int(entry.name.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    if not indices:
        return None
    return max(indices) + 1


async def resolve_collab_step_index(
    *,
    chain_id: str,
    username: str,
    step_index: Optional[int] = None,
) -> Optional[int]:
    """Resolve assignee step index from text, Admin API, or local inbound sync."""
    idx = int(step_index) if step_index else None
    if idx and idx > 1:
        return idx

    detail = await _fetch_chain_detail(chain_id)
    if detail:
        steps = detail.get("steps") or []
        user = str(username or "").strip()
        for step in steps:
            if str(step.get("status") or "") != "running":
                continue
            if str(step.get("assignee_username") or "").strip() == user:
                try:
                    return int(step.get("step_index") or 0) or None
                except (TypeError, ValueError):
                    return None
        try:
            current = int((detail.get("chain") or {}).get("current_step") or 0)
            if current > 1:
                return current
        except (TypeError, ValueError):
            pass

    return infer_step_index_from_local_sync(
        output_base_dir=_resolve_output_base_dir(),
        username=username,
        chain_id=chain_id,
    )


async def _fetch_chain_detail(chain_id: str) -> Optional[dict]:
    cid = str(chain_id or "").strip()
    if not cid:
        return None
    try:
        import aiohttp
        from workflow.collab_auth import read_collab_admin_token
        from workflow.config import get_admin_api_base

        token = read_collab_admin_token()
        if not token:
            return None
        url = f"{get_admin_api_base().rstrip('/')}/collab/chains/{cid}"
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.info(
                        "[collab附件] 获取协同链详情失败 chain={} status={}",
                        cid,
                        response.status,
                    )
                    return None
                payload = await response.json()
        if not isinstance(payload, dict) or not payload.get("success"):
            return None
        return payload
    except Exception as exc:
        logger.info("[collab附件] 获取协同链详情异常 chain={}: {}", cid, exc)
        return None


def is_collab_task_text(text: str) -> bool:
    raw = _strip_source_prefixes(str(text or ""))
    if not raw.strip():
        return False
    if "【协同任务】" in raw or "协同链ID:" in raw or "协同链 ID:" in raw:
        return True
    if _CHAIN_ID_RE.search(raw):
        return True
    return bool(_UUID_RE.search(raw) and ("协同" in raw or "collab" in raw.lower()))


def build_collab_attachment_read_rule(
    *,
    chain_id: str,
    step_index: int,
    paths: Sequence[str],
) -> str:
    path_lines = "\n".join(f"- `{p}`" for p in paths if str(p or "").strip())
    lines = [
        f"【协同附件读取规则】协同链 {chain_id} 步骤 {step_index}：",
        "- 仅允许用 read_file 读取下列 collab/step_N/ 路径或下方已自动解析正文；",
        "- 禁止使用其他同事 workspace 下的 YYYYMMDD 日期目录路径；",
        "- 禁止通过 HTTP 下载协同附件。",
    ]
    if path_lines:
        lines.append("合法路径：")
        lines.append(path_lines)
    return "\n".join(lines)


def sanitize_collab_handoff_text(text: str) -> str:
    """Remove misleading date-folder absolute paths from text shown to downstream steps."""
    raw = str(text or "")
    if not raw.strip():
        return raw
    placeholder = "[上游步骤摘要中的日期目录路径已省略，请仅使用【本地协同目录】或已自动解析的正文]"
    cleaned = raw
    if _DATE_DIR_ABS_PATH_RE.search(cleaned):
        cleaned = _DATE_DIR_ABS_PATH_RE.sub(placeholder, cleaned)
    if _OTHER_USER_DATE_PATH_RE.search(cleaned):
        cleaned = _OTHER_USER_DATE_PATH_RE.sub(placeholder, cleaned)
    return cleaned.strip()


def extract_collab_context_from_text(text: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract chain_id and step_index from collab task text."""
    raw = str(text or "")
    chain_id = None
    m = _CHAIN_ID_RE.search(raw)
    if m:
        chain_id = m.group(1)
    step_index = None
    sm = _STEP_INDEX_RE.search(raw)
    if sm:
        try:
            step_index = int(sm.group(1))
        except ValueError:
            step_index = None
    return chain_id, step_index


def build_collab_last_step_agent_hint(*, step_index: int, total_steps: int) -> str:
    """Instructions for the final collab step assignee's agent."""
    idx = int(step_index or 0)
    total = int(total_steps or 0)
    if total <= 0 or idx < total:
        return ""
    return (
        "【最后一步】本步为协同链终点，无「流转到下一步」。"
        "完成后必须调用 complete_collab_step，并在 result_summary 或 result_detail 中写出 "
        '{"generated_files":["<OUTPUT_DIR> 下交付物完整路径>"]}；'
        "系统将自动上传所列文件为附件并完成整条协同链。"
    )


def build_collab_local_paths_hint(
    *,
    output_base_dir: str,
    assignee_username: str,
    chain_id: str,
    previous_steps: Iterable[dict],
    attachments_by_step: dict,
) -> str:
    """Tell the assignee where desktop inbound sync stores upstream files."""
    user = str(assignee_username or "").strip()
    cid = str(chain_id or "").strip()
    base_root = str(output_base_dir or "").strip()
    if not user or not cid or not base_root:
        return ""
    base = Path(base_root) / user / "collab" / cid
    lines: List[str] = [
        "【本地协同目录】",
        "上游附件由桌面端同步到以下路径；请用 read_file 读取，"
        "勿猜测日期目录（如 YYYYMMDD/文件名），勿通过 HTTP 重复下载：",
    ]
    has_any = False
    for prev in sorted(previous_steps, key=lambda s: int(s.get("step_index") or 0)):
        idx = int(prev.get("step_index") or 0)
        items = attachments_by_step.get(idx) or []
        if not items:
            continue
        has_any = True
        step_dir = base / f"step_{idx}"
        lines.append(f"步骤 {idx} 目录: {step_dir}")
        for att in items:
            name = str(att.get("original_filename") or "").strip()
            if not name:
                sp = str(att.get("stored_path") or "").strip()
                name = Path(sp).name if sp else ""
            if name:
                lines.append(f"  - {step_dir / name}")
    if not has_any:
        return ""
    lines.append("若用户消息已含「【上游协同附件（已自动解析）】」，优先使用其中正文。")
    return "\n".join(lines)


def finalize_collab_task_prompt(
    prompt: str,
    *,
    chain_id: str,
    step_index: int,
    upstream_attachment_block: str = "",
    upstream_parsed_block: str = "",
    local_paths_hint: str = "",
    last_step_hint: str = "",
) -> str:
    """Prepend chain metadata and optional upstream attachment summary."""
    cid = str(chain_id or "").strip()
    header = f"协同链ID: {cid}\n当前步骤: {int(step_index or 0)}\n\n"
    body = str(prompt or "").strip()
    block = str(upstream_attachment_block or upstream_parsed_block or "").strip()
    if block:
        body = f"{body}\n\n【上游协同附件】\n\n{block}".strip()
    hint = str(local_paths_hint or "").strip()
    if hint:
        body = f"{body}\n\n{hint}".strip()
    last = str(last_step_hint or "").strip()
    if last:
        body = f"{body}\n\n{last}".strip()
    return (header + body).strip()


def build_upstream_summary_block_from_attachments(
    previous_steps: Iterable[dict],
    attachments_by_step: dict,
) -> str:
    """Filename-only summary for task_prompt_rendered (full parse happens at agent runtime)."""
    lines: List[str] = []
    for prev in sorted(previous_steps, key=lambda s: int(s.get("step_index") or 0)):
        idx = int(prev.get("step_index") or 0)
        items = attachments_by_step.get(idx) or []
        names: List[str] = []
        for att in items:
            name = str(att.get("original_filename") or "").strip()
            if not name:
                sp = str(att.get("stored_path") or "").strip()
                name = Path(sp).name if sp else ""
            if name:
                names.append(name)
        if names:
            lines.append(f"步骤 {idx}: " + "、".join(names))
    if not lines:
        return ""
    return (
        "\n".join(lines)
        + "\n（Agent 执行时从本地 collab/step_N/ 目录自动加载正文，勿猜日期路径）"
    )


_UPSTREAM_ATTACHMENT_MARKER_RE = re.compile(r"【上游协同附件(?:（已自动解析）)?】")


def format_task_prompt_for_display(text: str) -> str:
    """Strip legacy full parsed attachment bodies from prompts shown in UI."""
    t = str(text or "").strip()
    if not t:
        return ""
    m = _UPSTREAM_ATTACHMENT_MARKER_RE.search(t)
    if not m:
        return t
    before = t[: m.start()].rstrip()
    after = t[m.start() :]
    if re.search(r"### 步骤|## 附件：", after):
        names = re.findall(r"## 附件：([^\n]+)", after)
        summary = "【上游协同附件】"
        if names:
            shown = "、".join(names[:8])
            if len(names) > 8:
                shown += f" 等共 {len(names)} 个"
            summary += " " + shown
        summary += "（正文已解析，执行时由 Agent 自动加载，界面省略显示）"
        return f"{before}\n\n{summary}".strip() if before else summary
    return t


async def build_upstream_block_from_attachments(
    previous_steps: Iterable[dict],
    attachments_by_step: dict,
) -> str:
    """Build parsed markdown from prior-step collab attachment stored paths."""
    blocks: List[str] = []
    for prev in sorted(previous_steps, key=lambda s: int(s.get("step_index") or 0)):
        idx = int(prev.get("step_index") or 0)
        items = attachments_by_step.get(idx) or []
        paths: List[str] = []
        for att in items:
            sp = str(att.get("stored_path") or "").strip()
            if sp and os.path.isfile(sp):
                paths.append(sp)
        if not paths:
            continue
        block = await build_parsed_block_for_paths(
            paths, heading=f"步骤 {idx} 上游附件"
        )
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


async def enrich_collab_user_input(user_input: str, username: str) -> str:
    """
    When user message is a collab task, parse locally synced upstream attachments
    and inject markdown (complements task_prompt_rendered on Admin API).
    """
    text = str(user_input or "")
    if not is_collab_task_text(text):
        return user_input
    if "【上游协同附件（已自动解析）】" in text:
        return user_input
    if "【协同附件读取规则】" in text:
        return user_input

    chain_id, step_index = extract_collab_context_from_text(text)
    if not chain_id:
        um = _UUID_RE.search(text)
        if um:
            chain_id = um.group(1)
    if not chain_id:
        return user_input

    user = str(username or "").strip()
    step_index = await resolve_collab_step_index(
        chain_id=chain_id,
        username=user,
        step_index=step_index,
    )
    if not step_index or step_index <= 1:
        logger.info(
            "[collab附件] 无法解析协同步骤 chain={} user={}",
            chain_id,
            user,
        )
        return user_input

    output_base = _resolve_output_base_dir()
    paths = list_local_collab_upstream_files(
        output_base_dir=output_base,
        username=user,
        chain_id=chain_id,
        before_step_index=step_index,
    )
    if not paths:
        logger.info(
            "[collab附件] 本地无上游附件 chain={} step={} user={} base={}",
            chain_id,
            step_index,
            user,
            output_base,
        )
        return user_input

    block = await build_parsed_block_for_paths(
        paths, heading="本地协同目录中的上游附件"
    )
    if not block:
        return user_input

    rule = build_collab_attachment_read_rule(
        chain_id=chain_id,
        step_index=step_index,
        paths=paths,
    )
    logger.info(
        "[collab附件] 已注入 {} 个本地 upstream 文件到协同任务输入",
        len(paths),
    )
    return f"{rule}\n\n{text.rstrip()}\n\n【上游协同附件（已自动解析）】\n\n{block}\n"
