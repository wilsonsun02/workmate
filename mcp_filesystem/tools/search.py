"""Search tools.

This module contains tools for searching files and content within files,
including knowledge base semantic search powered by LLM.
"""

import json
import os
from typing import List, Optional

from fastmcp import Context
from loguru import logger

from ..context import mcp, get_components

# Control whether Search tools are exposed
ENABLE_SEARCH_TOOLS = (
    os.environ.get("MCP_ENABLE_SEARCH_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_SEARCH_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def search_files(
    path: str,
    pattern: str,
    ctx: Context,
    recursive: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    content_match: Optional[str] = None,
    max_results: int = 100,
    format: str = "text",
) -> str:
    """Recursively search for files and directories matching a pattern.

    Args:
        path: Starting directory
        pattern: Glob pattern to match against filenames
        recursive: Whether to search subdirectories
        exclude_patterns: Optional patterns to exclude
        content_match: Optional text to search within files
        max_results: Maximum number of results to return
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Search results
    """
    try:
        components = get_components()
        results = await components["operations"].search_files(
            path, pattern, recursive, exclude_patterns, content_match, max_results
        )

        if format.lower() == "json":
            return json.dumps(results, indent=2)

        # Format as text
        if not results:
            return "No matching files found"

        lines = []
        for item in results:
            is_dir = item.get("is_directory", False)
            type_label = "[DIR]" if is_dir else "[FILE]"
            size = f" ({item['size']:,} bytes)" if not is_dir else ""
            lines.append(f"{type_label} {item['path']}{size}")

        return f"Found {len(results)} matching files:\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Error searching files: {str(e)}"


def _is_url(source: str) -> bool:
    """判断 source 是否为 URL 地址。"""
    s = source.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


@register_tool()
async def add_knowledge(
    knowledge_name: str,
    sources: List[str],
    ctx: Context,
) -> str:
    """向个人知识库添加文件。支持本地文件路径和 URL 地址。

    如果指定名称的知识库不存在，会自动创建后再添加文件；
    如果知识库已存在，则直接将文件解析为 Markdown 并存储到该知识库。

    支持的文件类型：.txt, .md, .pdf, .docx, .doc, .ppt, .pptx,
                      .csv, .xls, .xlsx, .jpg, .jpeg, .png, .gif, .bmp, .webp
    支持的 URL：http:// 或 https:// 开头的网页地址，系统会自动抓取并转换为 Markdown。

    Args:
        knowledge_name: 【必填】知识库名称（即分类名称），如果不存在会自动创建
        sources: 【必填】知识库文件路径或 URL 地址列表，至少提供一个
        ctx: MCP context

    Returns:
        str: 添加结果汇总，包含成功/失败计数及每个文件的处理详情
    """
    try:
        if not knowledge_name or not knowledge_name.strip():
            return "knowledge_name 参数不能为空，请提供知识库名称。"
        if not sources:
            return "sources 参数不能为空，请提供至少一个文件路径或 URL 地址。"

        from services.knowledge_service import (
            create_category,
            upload_file,
            add_url,
            _safe_filename,
        )

        # 确保知识库分类存在，不存在则自动创建
        safe_name = _safe_filename(knowledge_name)
        cat_result = create_category(safe_name)
        if cat_result.get("success") or "已存在" in cat_result.get("error", ""):
            logger.info(f"[add_knowledge] 知识库 '{safe_name}' 已就绪")
        else:
            return f"创建知识库分类失败: {cat_result.get('error', '未知错误')}"

        # 逐个处理文件路径或 URL
        results = []
        success_count = 0
        fail_count = 0

        for source in sources:
            source = source.strip()
            if not source:
                continue

            if _is_url(source):
                # URL 类型：调用 add_url
                try:
                    result = await add_url(source, safe_name)
                    if result.get("success"):
                        file_info = result.get("file", {})
                        results.append(
                            f"✅ URL: {source}\n"
                            f"   文件名: {file_info.get('md_filename', '')}\n"
                            f"   摘要: {file_info.get('summary', '')[:100]}..."
                        )
                        success_count += 1
                    else:
                        results.append(
                            f"❌ URL: {source} - {result.get('error', '未知错误')}"
                        )
                        fail_count += 1
                except Exception as e:
                    results.append(f"❌ URL: {source} - 处理异常: {str(e)}")
                    fail_count += 1
            else:
                # 本地文件路径：读取文件内容后调用 upload_file
                if not os.path.exists(source):
                    results.append(f"❌ 文件不存在: {source}")
                    fail_count += 1
                    continue

                try:
                    filename = os.path.basename(source)
                    with open(source, "rb") as f:
                        file_content = f.read()

                    result = await upload_file(file_content, filename, safe_name)
                    if result.get("success"):
                        file_info = result.get("file", {})
                        results.append(
                            f"✅ 文件: {filename}\n"
                            f"   存储名: {file_info.get('md_filename', '')}\n"
                            f"   摘要: {file_info.get('summary', '')[:100]}..."
                        )
                        success_count += 1
                    else:
                        results.append(
                            f"❌ 文件: {filename} - {result.get('error', '未知错误')}"
                        )
                        fail_count += 1
                except Exception as e:
                    results.append(
                        f"❌ 文件: {os.path.basename(source)} - 处理异常: {str(e)}"
                    )
                    fail_count += 1

        # 汇总结果
        summary = (
            f"知识库「{safe_name}」添加完成：\n"
            f"- 成功: {success_count} 个\n"
            f"- 失败: {fail_count} 个\n\n" + "\n".join(results)
        )
        return summary

    except Exception as e:
        logger.error(f"add_knowledge 工具执行失败: {e}")
        return f"Error adding knowledge: {str(e)}"


def _resolve_username(username: str = "") -> str:
    """解析当前操作用户名，优先级：参数 > 环境变量 > default。"""
    u = str(username or "").strip()
    if u:
        return u
    for key in ("WORKMATE_DESKTOP_ACTIVE_USERNAME", "AGENT_USERNAME", "USERNAME"):
        env_u = os.environ.get(key, "").strip()
        if env_u:
            return env_u
    return "default"


def _fetch_files_by_names(
    file_names: list[str], username: str, *, with_content: bool = False
) -> list[dict]:
    """根据 file_name 列表从数据库批量获取知识库文件信息。

    file_name 对应 md_filename 去掉 .md 后缀。
    with_content=True 时返回 md_content 字段，否则仅返回摘要等元信息。
    同时检索分享给当前用户的文件（kb_shares 关联）。
    """
    from services.knowledge_service import _ensure_tables

    _ensure_tables()
    uname = _resolve_username(username)

    md_filenames = []
    for fn in file_names:
        md_filenames.append(fn if fn.endswith(".md") else f"{fn}.md")

    from admin_api.models.init_db import db_cursor

    results = []
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            placeholders = ", ".join(["%s"] * len(md_filenames))
            select_fields = (
                "id, category_name, original_filename, md_filename, "
                "file_type, file_size, summary, source_url, "
                "created_at, updated_at"
            )
            if with_content:
                select_fields += ", md_content"

            # 查询个人知识库文件
            cursor.execute(
                f"SELECT {select_fields} FROM kb_files "
                f"WHERE md_filename IN ({placeholders}) AND username = %s",
                (*md_filenames, uname),
            )
            rows = cursor.fetchall()
            for row in rows:
                item = {
                    "id": row["id"],
                    "category": row["category_name"],
                    "original_filename": row["original_filename"],
                    "md_filename": row["md_filename"] or "",
                    "file_type": row["file_type"],
                    "file_size": row["file_size"],
                    "summary": row["summary"] or "",
                    "source_url": row["source_url"] or "",
                    "created_at": row["created_at"].isoformat()
                    if row["created_at"]
                    else "",
                    "updated_at": row["updated_at"].isoformat()
                    if row["updated_at"]
                    else "",
                    "source": "personal",
                }
                if with_content:
                    item["md_content"] = row["md_content"] or ""
                results.append(item)

            # 查询分享给当前用户的文件（排除已从个人知识库查到的）
            found_ids = {r["id"] for r in results}
            cursor.execute(
                f"SELECT f.id, f.category_name, f.original_filename, f.md_filename, "
                f"f.file_type, f.file_size, f.summary, f.source_url, "
                f"f.created_at, f.updated_at"
                + (", f.md_content" if with_content else "")
                + f", s.owner_username AS share_owner "
                f"FROM kb_files f "
                f"INNER JOIN kb_shares s ON s.file_id = f.id "
                f"WHERE f.md_filename IN ({placeholders}) AND s.target_username = %s",
                (*md_filenames, uname),
            )
            shared_rows = cursor.fetchall()
            for row in shared_rows:
                if row["id"] in found_ids:
                    continue
                item = {
                    "id": row["id"],
                    "category": row["category_name"],
                    "original_filename": row["original_filename"],
                    "md_filename": row["md_filename"] or "",
                    "file_type": row["file_type"],
                    "file_size": row["file_size"],
                    "summary": row["summary"] or "",
                    "source_url": row["source_url"] or "",
                    "created_at": row["created_at"].isoformat()
                    if row["created_at"]
                    else "",
                    "updated_at": row["updated_at"].isoformat()
                    if row["updated_at"]
                    else "",
                    "source": "shared",
                    "share_owner": row.get("share_owner", ""),
                }
                if with_content:
                    item["md_content"] = row["md_content"] or ""
                results.append(item)
        except Exception as e:
            logger.error(f"批量获取知识库文件信息失败: {e}")
            return []

    found_names = {r["md_filename"] for r in results}
    for i, mfn in enumerate(md_filenames):
        if mfn not in found_names:
            results.append(
                {
                    "id": None,
                    "category": "",
                    "original_filename": "",
                    "md_filename": mfn,
                    "file_type": "",
                    "file_size": 0,
                    "summary": "",
                    "source_url": "",
                    "created_at": "",
                    "updated_at": "",
                    "_not_found": True,
                    "requested_name": file_names[i],
                }
            )

    return results


async def _llm_filter_relevant_files(
    query: str, file_summaries: list[dict]
) -> list[dict]:
    """通过 LLM 判断指定文件列表中哪些与检索条件相关。

    将文件的 summary 和检索条件一起发送给 LLM，
    让 LLM 返回相关文件的 md_filename 列表及判断理由。
    """
    if not file_summaries:
        return []

    from workflow.model import mcp_llm
    from langchain_core.messages import HumanMessage

    summaries_text = ""
    for i, f in enumerate(file_summaries, 1):
        display_name = (
            f["md_filename"][:-3]
            if f.get("md_filename", "").endswith(".md")
            else f.get("md_filename", "")
        )
        summaries_text += (
            f"\n--- 文件{i} ---\n"
            f"文件名: {display_name}\n"
            f"分类: {f['category']}\n"
            f"原始文件名: {f['original_filename']}\n"
            f"摘要: {f['summary']}\n"
        )

    prompt = (
        "你是一个知识库检索助手。用户提出了一个检索条件，请根据以下知识库文件的摘要信息，"
        "判断哪些文件与检索条件相关。\n\n"
        f"检索条件：{query}\n\n"
        f"知识库文件列表：{summaries_text}\n\n"
        "请按以下 JSON 格式返回结果（仅返回 JSON，不要其他内容）：\n"
        "[\n"
        '  {"file_name": "文件名（md_filename去掉.md后缀）", "reason": "判断为相关的理由"}\n'
        "]\n\n"
        "注意：\n"
        "1. 只返回与检索条件确实相关的文件，不要返回不相关的文件\n"
        "2. 如果没有相关文件，返回空数组 []\n"
        "3. 判断时应考虑语义相关性，而非简单的关键词匹配\n"
    )

    try:
        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        json_str = content
        if "```" in content:
            lines = content.split("\n")
            in_code_block = False
            json_lines = []
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    json_lines.append(line)
            json_str = "\n".join(json_lines)

        result = json.loads(json_str)
        if not isinstance(result, list):
            return []

        name_reason_map = {}
        for item in result:
            fn = item.get("file_name", "")
            if fn:
                name_reason_map[fn] = item.get("reason", "")

        matched = []
        for f in file_summaries:
            display_name = (
                f["md_filename"][:-3]
                if f.get("md_filename", "").endswith(".md")
                else f.get("md_filename", "")
            )
            if display_name in name_reason_map:
                matched.append({**f, "relevance_reason": name_reason_map[display_name]})
        return matched
    except json.JSONDecodeError:
        logger.error(f"LLM 返回的 JSON 解析失败: {content[:200]}")
        return []
    except Exception as e:
        logger.error(f"LLM 判断知识库文件相关性失败: {e}")
        return []


async def _llm_extract_relevant_paragraphs(
    query: str, file_name: str, filename: str, content: str
) -> str:
    """通过 LLM 从文件内容中提取与检索条件相关的段落。"""
    from workflow.model import mcp_llm
    from langchain_core.messages import HumanMessage

    truncated = content[:15000] if len(content) > 15000 else content
    if len(content) > 15000:
        truncated += "\n\n...（内容过长已截断，仅展示前15000字符）"

    prompt = (
        "你是一个知识库检索助手。用户提出了一个检索条件，请从以下文件内容中，"
        "找出与检索条件相关的段落或部分，并原样引用这些内容。\n\n"
        f"检索条件：{query}\n"
        f"文件名：{filename}\n\n"
        f"文件内容：\n{truncated}\n\n"
        "请按以下格式输出：\n"
        "1. 先简要说明该文件与检索条件的关联\n"
        "2. 然后逐段引用与检索条件相关的内容片段，每段前标注其在原文中的位置（如章节标题或段落序号）\n"
        "3. 如果文件中没有与检索条件相关的内容，请说明\n"
    )

    try:
        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        logger.error(f"LLM 提取知识库相关段落失败: {e}")
        return f"提取相关段落时出错: {str(e)}"


@register_tool()
async def search_knowledge(
    file_names: List[str],
    ctx: Context,
    query: str = "",
) -> str:
    """根据知识库文件名列表检索相关内容；也可直接返回指定文件的全文。

    两种使用模式：
    - 读取模式（query 为空）：直接返回 file_names 列表中所有文件的全文 md_content
    - 检索模式（query 不为空）：根据 query 语义在 file_names 列表中检索，返回相关文件的相关段落

    file_name 对应 md_filename 去掉 .md 后缀，例如 md_filename 为 "百色高新区_d9a0.md"，
    则 file_name 为 "百色高新区_d9a0"。

    检索模式流程：
    1. 获取 file_names 列表中文件的摘要（summary）
    2. 通过大模型判断列表中哪些文件与检索条件语义相关
    3. 读取相关文件的完整内容（md_content）
    4. 通过大模型定位每个文件中与检索条件相关的段落
    5. 返回相关文件的相关片段

    Args:
        file_names: 【必填】知识库文件名列表（md_filename去掉.md后缀），不能为空
        query: 【选填】检索条件，描述需要查找的信息；为空时返回所有指定文件的全文
        ctx: MCP context

    Returns:
        str: 检索模式下返回相关文件及其相关段落；读取模式下返回指定文件的全文
    """
    try:
        if not file_names:
            return "file_names 参数不能为空，请提供至少一个知识库文件名。"

        username = _resolve_username()

        if not query:
            files = _fetch_files_by_names(file_names, username, with_content=True)
            if not files:
                return "未找到指定的知识库文件，请检查文件名是否正确。"

            not_found = [f for f in files if f.get("_not_found")]
            found = [f for f in files if not f.get("_not_found")]

            parts = []
            for f in found:
                source_info = ""
                if f.get("source_url"):
                    source_info = f"- 来源URL：{f['source_url']}\n"
                parts.append(
                    f"## 文件：{f['original_filename']}\n"
                    f"- 分类：{f['category']}\n"
                    f"- 文件类型：{f['file_type']}\n"
                    f"- 文件大小：{f['file_size']:,} bytes\n"
                    f"- 摘要：{f['summary']}\n"
                    f"{source_info}"
                    f"- 创建时间：{f['created_at']}\n"
                    f"- 更新时间：{f['updated_at']}\n\n"
                    f"---\n\n{f['md_content']}"
                )

            if not_found:
                nf_names = [
                    f.get("requested_name", f["md_filename"]) for f in not_found
                ]
                parts.append(f"以下文件未找到：{', '.join(nf_names)}")

            if not found:
                return f"未找到指定的知识库文件：{', '.join(file_names)}"

            return "\n\n---\n\n".join(parts)

        file_summaries = _fetch_files_by_names(file_names, username, with_content=False)
        if not file_summaries:
            return "未找到指定的知识库文件，请检查文件名是否正确。"

        valid_summaries = [f for f in file_summaries if not f.get("_not_found")]
        not_found = [f for f in file_summaries if f.get("_not_found")]

        if not valid_summaries:
            nf_names = [f.get("requested_name", f["md_filename"]) for f in not_found]
            return f"未找到指定的知识库文件：{', '.join(nf_names)}"

        relevant_files = await _llm_filter_relevant_files(query, valid_summaries)
        if not relevant_files:
            return "在指定文件中未找到与检索条件相关的内容。"

        relevant_ids = {f["id"] for f in relevant_files}
        relevant_with_content = _fetch_files_by_names(
            [
                f["md_filename"][:-3]
                if f["md_filename"].endswith(".md")
                else f["md_filename"]
                for f in relevant_files
            ],
            username,
            with_content=True,
        )
        content_map = {
            f["id"]: f for f in relevant_with_content if not f.get("_not_found")
        }

        results = []
        for f in relevant_files:
            file_data = content_map.get(f["id"])
            if not file_data or not file_data.get("md_content"):
                continue

            paragraphs = await _llm_extract_relevant_paragraphs(
                query,
                f["md_filename"][:-3]
                if f["md_filename"].endswith(".md")
                else f["md_filename"],
                f["original_filename"],
                file_data["md_content"],
            )

            display_name = (
                f["md_filename"][:-3]
                if f["md_filename"].endswith(".md")
                else f["md_filename"]
            )
            results.append(
                f"## 文件：{f['original_filename']}\n"
                f"- 分类：{f['category']}\n"
                f"- 文件名：{display_name}\n"
                f"- 相关性判断：{f.get('relevance_reason', '')}\n\n"
                f"{paragraphs}"
            )

        if not results:
            return "相关文件内容读取失败，请稍后重试。"

        header = f"共找到 {len(relevant_files)} 个相关文件，以下是与检索条件「{query}」相关的内容：\n\n"
        return header + "\n\n---\n\n".join(results)

    except Exception as e:
        logger.error(f"知识库检索失败: {e}")
        return f"Error searching knowledge: {str(e)}"


@register_tool()
async def grep_files(
    path: str,
    pattern: str,
    ctx: Context,
    is_regex: bool = False,
    case_sensitive: bool = True,
    whole_word: bool = False,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    context_lines: int = 0,
    context_before: int = 0,
    context_after: int = 0,
    results_offset: int = 0,
    results_limit: Optional[int] = None,
    max_results: int = 1000,
    max_file_size_mb: float = 10,
    recursive: bool = True,
    max_depth: Optional[int] = None,
    count_only: bool = False,
    format: str = "text",
) -> str:
    """Search for pattern in files, similar to grep.

    Args:
        path: Starting directory or file path
        pattern: Text or regex pattern to search for
        is_regex: Whether to treat pattern as regex
        case_sensitive: Whether search is case sensitive
        whole_word: Match whole words only
        include_patterns: Only include files matching these patterns
        exclude_patterns: Exclude files matching these patterns
        context_lines: Number of lines to show before AND after matches (like grep -C)
        context_before: Number of lines to show BEFORE matches (like grep -B)
        context_after: Number of lines to show AFTER matches (like grep -A)
        results_offset: Start at Nth match (0-based, for pagination)
        results_limit: Return at most this many matches (for pagination)
        max_results: Maximum total matches to find during search
        max_file_size_mb: Skip files larger than this size
        recursive: Whether to search subdirectories
        max_depth: Maximum directory depth to recurse
        count_only: Only show match counts per file
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Search results
    """
    try:
        components = get_components()

        # Fix regex escaping - if is_regex is True, handle backslash escaping
        pattern_fixed = pattern
        if is_regex and "\\" in pattern:
            # For patterns coming from JSON where backslashes are escaped,
            # we need to convert double backslashes to single backslashes
            pattern_fixed = pattern.replace("\\\\", "\\")

        results = await components["grep"].grep_files(
            path,
            pattern_fixed,
            is_regex,
            case_sensitive,
            whole_word,
            include_patterns,
            exclude_patterns,
            context_lines,
            context_before,
            context_after,
            max_results,
            max_file_size_mb,
            recursive,
            max_depth,
            count_only,
            results_offset=results_offset,
            results_limit=results_limit,
        )

        if format.lower() == "json":
            return json.dumps(results.to_dict(), indent=2)
        else:
            # Format as text with appropriate options
            show_line_numbers = True
            show_file_names = True
            show_context = context_lines > 0
            highlight = True

            return results.format_text(
                show_line_numbers=show_line_numbers,
                show_file_names=show_file_names,
                count_only=count_only,
                show_context=show_context,
                highlight=highlight,
            )

    except Exception as e:
        return f"Error searching files: {str(e)}"
