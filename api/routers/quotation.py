import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from api.routers.desktop import desktop_uploads_base_dir
from api.runtime_state import (
    get_runtime_output_base_dir,
    is_stream_stopped,
    set_stream_stop_flag,
)
from workflow.workflow_core import stream_deep_agent

router = APIRouter(tags=["quotation"])


def normalize_attachment_paths_raw(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if p is not None and str(p).strip()]
    return []


def validate_desktop_attachment_paths(paths: list[str], username: str) -> list[str]:
    from pathlib import Path

    from fastapi import HTTPException

    user = str(username or "").strip()
    if not paths:
        return []
    if not user:
        raise HTTPException(
            status_code=400,
            detail="username is required when attachment_paths is provided",
        )
    try:
        root = desktop_uploads_base_dir(user).resolve()
    except OSError as error:
        raise HTTPException(
            status_code=500, detail=f"cannot resolve upload root: {error}"
        ) from error

    out: list[str] = []
    for path in paths:
        try:
            resolved_path = Path(path).expanduser().resolve()
        except OSError:
            raise HTTPException(
                status_code=400, detail=f"invalid path: {path}"
            ) from None
        try:
            if not resolved_path.is_relative_to(root):
                raise HTTPException(
                    status_code=400,
                    detail="attachment path outside allowed upload directory",
                )
        except HTTPException:
            raise
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="attachment path outside allowed upload directory",
            ) from None
        out.append(str(resolved_path))
    return out


def merge_attachment_paths_into_user_input(user_input: str, paths: list[str]) -> str:
    ui = (user_input or "").strip()
    if not paths:
        return ui
    lines = "\n".join(paths)
    return (
        "<attachment-paths>\n"
        + lines
        + "\n</attachment-paths>\n\n"
        + (ui if ui else "(无)")
    )


def merge_knowledge_file_ids_into_user_input(
    user_input: str, file_ids: list[str]
) -> str:
    """将知识库文件ID以XML标签格式注入到用户输入中，供后续预处理阶段读取摘要。"""
    ui = (user_input or "").strip()
    if not file_ids:
        return ui
    ids_text = "\n".join(file_ids)
    return (
        "<knowledge-file-ids>\n"
        + ids_text
        + "\n</knowledge-file-ids>\n\n"
        + (ui if ui else "(无)")
    )


def merge_knowledge_category_names_into_user_input(
    user_input: str, category_names: list[str]
) -> str:
    """将知识库分类名称以XML标签格式注入到用户输入中，供后续预处理阶段按分类读取摘要。"""
    ui = (user_input or "").strip()
    if not category_names:
        return ui
    names_text = "\n".join(category_names)
    return (
        "<knowledge-category-names>\n"
        + names_text
        + "\n</knowledge-category-names>\n\n"
        + (ui if ui else "(无)")
    )


_GENERATED_FILES_BLOCK_RE = re.compile(
    r'\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}',
    re.DOTALL,
)


def strip_generated_files_placeholder_json(text: str) -> str:
    if not (text or "").strip():
        return text or ""
    cleaned = re.sub(
        r'```(?:json)?\s*\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}\s*```',
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(
        r'\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}',
        "",
        cleaned,
        flags=re.DOTALL,
    )
    return cleaned.strip()


def _collect_generated_files_from_json_fragment(fragment: str, add_path) -> None:
    try:
        data = json.loads(fragment)
        if isinstance(data, dict):
            for item in data.get("generated_files") or []:
                add_path(item)
        return
    except Exception:
        pass
    m = re.search(r'"generated_files"\s*:\s*\[(.*?)\]', fragment, re.DOTALL)
    if not m:
        return
    for qm in re.finditer(r'"([^"]+)"', m.group(1)):
        add_path(qm.group(1))


def extract_generated_files_from_text(text: str) -> list[str]:
    """Extract generated_files paths from assistant text (tolerates invalid JSON escapes)."""
    if not (text or "").strip():
        return []
    paths: list[str] = []
    seen: set[str] = set()

    def add_path(item) -> None:
        s = str(item or "").strip().strip('"').strip("'")
        if s and s not in seen:
            seen.add(s)
            paths.append(s)

    for m in re.finditer(
        r'```(?:json)?\s*(\{[\s\S]*?"generated_files"[\s\S]*?\})\s*```',
        text,
        flags=re.IGNORECASE,
    ):
        _collect_generated_files_from_json_fragment(m.group(1), add_path)

    for m in _GENERATED_FILES_BLOCK_RE.finditer(text):
        _collect_generated_files_from_json_fragment(m.group(0), add_path)

    return paths


def normalize_assistant_message_for_display(text: str) -> str:
    """Strip generated_files JSON and append clickable path bullets (DB reload / feed)."""
    from workflow.user_display_names import apply_display_names_to_text

    raw = text or ""
    paths = extract_generated_files_from_text(raw)
    cleaned = apply_display_names_to_text(strip_generated_files_placeholder_json(raw))
    return merge_generated_files_into_text(cleaned, paths)


def merge_generated_files_into_text(text: str, paths: list[str]) -> str:
    if not paths:
        return text or ""
    base = text or ""
    missing: list[str] = []
    for p in paths:
        s = str(p).strip()
        if not s:
            continue
        candidates = (s, s.replace("\\", "/"), s.replace("/", "\\"))
        if any(c and c in base for c in candidates):
            continue
        missing.append(s)
    if not missing:
        return base
    bullet_block = "\n".join(f"- `{p}`" for p in missing)
    if re.search(r"生成的文件", base):
        return base.rstrip() + "\n" + bullet_block + "\n"
    return base.rstrip() + "\n\n**生成的文件：**\n" + bullet_block + "\n"


async def quotation_handler_streaming(input_data: dict):
    full_content = ""
    merged_file_paths: list[str] = []

    async for event in stream_deep_agent(
        user_input=input_data.get("user_input"),
        thread_id=input_data.get("thread_id"),
        session_id=input_data.get("sessionId"),
        chat_history=input_data.get("chat_history", None),
        username=input_data.get("username"),
        wechat_context=input_data.get("wechat_context", ""),
        contact_name=input_data.get("contact_name", ""),
        scheduled_task_invocation=bool(
            input_data.get("scheduled_task_invocation", False)
        ),
        resume_command=input_data.get("resume_command"),
        skills_names=input_data.get("skills_names", []),
        mcp_tool_names=input_data.get("mcp_tool_names", []),
    ):
        event_type = event.get("event_type", "unknown")
        if event_type == "hitl_wait":
            yield {
                "event_type": "hitl_wait",
                "hitl_type": event.get("hitl_type", "confirm"),
                "message": event.get("message", ""),
                "options": event.get("options", []),
                "placeholder": event.get("placeholder"),
                "allow_attachments": event.get("allow_attachments", False),
                "multi_select": event.get("multi_select", False),
            }
            return
        elif event_type == "agent_step":
            yield {
                "event_type": "think",
                "step": event.get("step"),
                "content": event.get("content", ""),
                "tools_called": event.get("tools_called", []),
                "tool_results": event.get("tool_results", []),
                "node_name": event.get("node_name", ""),
                "generated_files": event.get("generated_files", []),
            }
        elif event_type == "error":
            yield {"event_type": "error", "content": event.get("content", "")}

        generated_files = event.get("generated_files")
        if isinstance(generated_files, list):
            for path in generated_files:
                text_path = str(path).strip() if path else ""
                if text_path and text_path not in merged_file_paths:
                    merged_file_paths.append(text_path)

        if event.get("content"):
            full_content = event.get("content", "")

    from workflow.user_display_names import apply_display_names_to_text

    full_content = apply_display_names_to_text(
        strip_generated_files_placeholder_json(full_content)
    )
    full_content = merge_generated_files_into_text(full_content, merged_file_paths)
    yield {"event_type": "done", "content": full_content}


@router.post("/quotation")
async def quotation_endpoint(request: Request):
    body = await request.json()
    logger.info(
        "[PathDebug] quotation output_base_dir={} username={}",
        get_runtime_output_base_dir(),
        body.get("username"),
    )

    att_list = normalize_attachment_paths_raw(body.get("attachment_paths"))
    validated_paths = (
        validate_desktop_attachment_paths(att_list, body.get("username"))
        if att_list
        else []
    )
    merged_user_input = body.get("user_input")
    if merged_user_input is None:
        merged_user_input = ""
    if not isinstance(merged_user_input, str):
        merged_user_input = str(merged_user_input)
    if validated_paths:
        merged_user_input = merge_attachment_paths_into_user_input(
            merged_user_input, validated_paths
        )

    kb_file_ids = normalize_attachment_paths_raw(body.get("knowledge_file_ids"))
    if kb_file_ids:
        merged_user_input = merge_knowledge_file_ids_into_user_input(
            merged_user_input, kb_file_ids
        )

    kb_category_names = normalize_attachment_paths_raw(
        body.get("knowledge_category_names")
    )
    if kb_category_names:
        merged_user_input = merge_knowledge_category_names_into_user_input(
            merged_user_input, kb_category_names
        )

    input_data = {
        "user_input": merged_user_input,
        "chat_history": body.get("chat_history", None),
        "thread_id": body.get("thread_id"),
        "sessionId": body.get("sessionId"),
        "mode": body.get("mode", 0),
        "username": body.get("username"),
        "wechat_context": body.get("wechat_context", ""),
        "contact_name": body.get("contact_name", ""),
        "scheduled_task_invocation": bool(body.get("scheduled_task_invocation", False)),
        "resume_command": body.get("resume_command"),
        "skills_names": normalize_attachment_paths_raw(body.get("skills_names")),
        "mcp_tool_names": normalize_attachment_paths_raw(body.get("mcp_tool_names")),
    }

    thread_id = str(input_data.get("thread_id") or "")
    session_id = str(input_data.get("sessionId") or "")
    await set_stream_stop_flag(thread_id, session_id, False)

    mode = body.get("mode", 0)
    if mode == 0:

        async def event_generator():
            try:
                agen = quotation_handler_streaming(input_data)
                async for event in agen:
                    if await is_stream_stopped(thread_id, session_id):
                        stop_event = {"event_type": "error", "content": "任务已中断"}
                        yield f"data: {json.dumps(stop_event, ensure_ascii=False)}\n\n"
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except GeneratorExit:
                # 客户端主动断开连接（如 HITL 等待时前端关闭 SSE 流），属于正常行为
                return
            except Exception as error:
                error_event = {
                    "event_type": "error",
                    "content": f"执行错误: {str(error)}",
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            finally:
                await set_stream_stop_flag(thread_id, session_id, False)
            yield f"data: {json.dumps({'event_type': 'stream_end'})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return {"error": "invalid mode"}
