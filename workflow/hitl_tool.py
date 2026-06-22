import json
from typing import Optional, Union
from langchain_core.tools import tool
from langgraph.types import interrupt


def _parse_options(options: Optional[Union[list, str]]) -> list:
    """将 options 参数统一转换为列表，兼容 LLM 将列表序列化为 JSON 字符串的情况。"""
    if options is None:
        return []
    if isinstance(options, list):
        return options
    if isinstance(options, str):
        try:
            parsed = json.loads(options)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


@tool
def request_human_input(
    message: str,
    hitl_type: str = "confirm",
    options: Optional[Union[list, str]] = None,
    placeholder: Optional[str] = None,
    allow_attachments: bool = False,
    multi_select: bool = False,
) -> str:
    """在 Skill 执行过程中暂停，等待用户反馈后再继续。

    当 Skill 明确要求在某个步骤暂停并等待用户确认、补充信息或上传附件时调用此工具。

    Args:
        message: 向用户展示的提示信息，说明需要什么反馈。
        hitl_type: 交互类型，可选值：
            - "confirm"：让用户从预设选项中选择（如同意/拒绝）
            - "input"：让用户输入自由文本
            - "select"：让用户从多个选项中选择（支持多选）
        options: hitl_type 为 "confirm" 或 "select" 时的选项列表，
                 每项格式为 {"value": "...", "label": "...", "description": "..."}。
        placeholder: hitl_type 为 "input" 时输入框的占位提示文字。
        allow_attachments: 是否允许用户上传附件文件。
        multi_select: hitl_type 为 "select" 时是否允许多选。

    Returns:
        用户的响应内容（字符串形式）。
    """
    interrupt_value = {
        "hitl_type": hitl_type,
        "message": message,
        "options": _parse_options(options),
        "placeholder": placeholder,
        "allow_attachments": allow_attachments,
        "multi_select": multi_select,
    }
    result = interrupt(interrupt_value)
    if not isinstance(result, dict):
        return str(result)

    # 构建结构化的返回文本，确保附件完整路径和解析内容清晰可见
    hitl_type_val = result.get("hitl_type", hitl_type)
    parts = []

    if hitl_type_val == "confirm":
        selected = result.get("selected_value", "")
        parts.append(f"用户选择: {selected}")
    elif hitl_type_val == "select":
        selected = result.get("selected_values", [])
        parts.append(f"用户选择: {json.dumps(selected, ensure_ascii=False)}")
    elif hitl_type_val == "input":
        text = result.get("text_input", "")
        if text:
            parts.append(f"用户输入: {text}")

    # 附件信息：明确标注完整路径
    attachments = result.get("attachments", [])
    if attachments:
        path_lines = "\n".join(f"  - {p}" for p in attachments)
        parts.append(f"上传的附件（完整路径）:\n{path_lines}")

    # 解析内容：如果存在 parsed_attachments，直接注入
    parsed = result.get("parsed_attachments", "")
    if parsed:
        parts.append(f"附件解析内容:\n{parsed}")

    return "\n\n".join(parts) if parts else str(result)
