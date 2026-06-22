"""Advanced file operation tools.

This module contains advanced file system operations such as directory tree visualization,
size calculation, duplicate finding, and file comparison.
"""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastmcp import Context
from loguru import logger

from ..context import mcp, get_components
from ..paths import get_project_root

# 技能相关常量
SKILLS_DIR = "skills"
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_CONTENT_LENGTH = 100000
VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# 威胁模式用于安全扫描
THREAT_PATTERNS = [
    (
        r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET)",
        "env_exfil_curl",
        "critical",
        "exfiltration",
        "curl command interpolating secret env var",
    ),
    (
        r"ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+instructions",
        "prompt_injection_ignore",
        "critical",
        "injection",
        "prompt injection: ignore previous instructions",
    ),
    (
        r"rm\s+-rf\s+/",
        "destructive_root_rm",
        "critical",
        "destructive",
        "recursive delete from root",
    ),
]

# Control whether Advanced tools are exposed
ENABLE_ADVANCED_TOOLS = (
    os.environ.get("MCP_ENABLE_ADVANCED_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_ADVANCED_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def directory_tree(
    path: str,
    ctx: Context,
    max_depth: int = 3,
    include_files: bool = True,
    pattern: Optional[str] = None,
    exclude_patterns: Optional[List[str]] = None,
    format: str = "text",
) -> str:
    """Get a recursive tree view of files and directories.

    Args:
        path: Root directory
        max_depth: Maximum recursion depth
        include_files: Whether to include files (not just directories)
        pattern: Optional glob pattern to filter entries
        exclude_patterns: Optional patterns to exclude
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Formatted directory tree
    """
    try:
        components = get_components()
        if format.lower() == "json":
            tree = await components["advanced"].directory_tree(
                path, max_depth, include_files, pattern, exclude_patterns
            )
            return json.dumps(tree, indent=2)
        else:
            tree_text = await components["advanced"].directory_tree_formatted(
                path, max_depth, include_files, pattern, exclude_patterns
            )
            return tree_text
    except Exception as e:
        return f"Error creating directory tree: {str(e)}"


@register_tool()
async def calculate_directory_size(
    path: str, ctx: Context, format: str = "human"
) -> str:
    """Calculate the total size of a directory recursively.

    Args:
        path: Directory path
        format: Output format ('human', 'bytes', or 'json')
        ctx: MCP context

    Returns:
        Directory size information
    """
    try:
        components = get_components()
        size_bytes = await components["advanced"].calculate_directory_size(path)

        if format.lower() == "bytes":
            return str(size_bytes)

        if format.lower() == "json":
            return json.dumps(
                {
                    "path": path,
                    "size_bytes": size_bytes,
                    "size_kb": round(size_bytes / 1024, 2),
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "size_gb": round(size_bytes / (1024 * 1024 * 1024), 2),
                },
                indent=2,
            )

        # Human readable format
        if size_bytes < 1024:
            return f"Directory size: {size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"Directory size: {size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"Directory size: {size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"Directory size: {size_bytes / (1024 * 1024 * 1024):.2f} GB"

    except Exception as e:
        return f"Error calculating directory size: {str(e)}"


@register_tool()
async def find_duplicate_files(
    path: str,
    ctx: Context,
    recursive: bool = True,
    min_size: int = 1,
    exclude_patterns: Optional[List[str]] = None,
    max_files: int = 1000,
    format: str = "text",
) -> str:
    """Find duplicate files by comparing file sizes and contents.

    Args:
        path: Starting directory
        recursive: Whether to search subdirectories
        min_size: Minimum file size to consider (bytes)
        exclude_patterns: Optional patterns to exclude
        max_files: Maximum number of files to scan
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Duplicate file information
    """
    try:
        components = get_components()
        duplicates = await components["advanced"].find_duplicate_files(
            path, recursive, min_size, exclude_patterns, max_files
        )

        if format.lower() == "json":
            return json.dumps(duplicates, indent=2)

        # Format as text
        if not duplicates:
            return "No duplicate files found"

        lines = []
        for file_hash, files in duplicates.items():
            lines.append(f"Hash: {file_hash}")
            for file_path in files:
                lines.append(f"  {file_path}")
            lines.append("")

        return f"Found {len(duplicates)} sets of duplicate files:\n\n" + "\n".join(
            lines
        )

    except Exception as e:
        return f"Error finding duplicate files: {str(e)}"


@register_tool()
async def compare_files(
    file1: str,
    file2: str,
    ctx: Context,
    encoding: str = "utf-8",
    format: str = "text",
) -> str:
    """Compare two text files and show differences.

    Args:
        file1: First file path
        file2: Second file path
        encoding: Text encoding (default: utf-8)
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Comparison results
    """
    try:
        components = get_components()
        result = await components["advanced"].compare_files(file1, file2, encoding)

        if format.lower() == "json":
            return json.dumps(result, indent=2)

        # Format as text
        similarity_pct = f"{result['similarity'] * 100:.1f}%"

        if result["are_identical"]:
            return "Files are identical (100% similarity)"

        lines = [
            f"Comparing {file1} with {file2}",
            f"Similarity: {similarity_pct}",
            f"Lines added: {result['added_lines']}",
            f"Lines removed: {result['removed_lines']}",
            "",
            "Diff:",
            result["diff"],
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"Error comparing files: {str(e)}"


@register_tool()
async def find_large_files(
    path: str,
    ctx: Context,
    min_size_mb: float = 100,
    recursive: bool = True,
    max_results: int = 100,
    exclude_patterns: Optional[List[str]] = None,
    format: str = "text",
) -> str:
    """Find files larger than the specified size.

    Args:
        path: Starting directory
        min_size_mb: Minimum file size in megabytes
        recursive: Whether to search subdirectories
        max_results: Maximum number of results to return
        exclude_patterns: Optional patterns to exclude
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Large file information
    """
    try:
        components = get_components()
        results = await components["advanced"].find_large_files(
            path, min_size_mb, recursive, max_results, exclude_patterns
        )

        if format.lower() == "json":
            return json.dumps(results, indent=2)

        # Format as text
        if not results:
            return f"No files larger than {min_size_mb} MB found"

        lines = []
        for file in results:
            size_mb = file["size"] / (1024 * 1024)
            lines.append(f"{file['path']} - {size_mb:.2f} MB")

        return (
            f"Found {len(results)} files larger than {min_size_mb} MB:\n\n"
            + "\n".join(lines)
        )

    except Exception as e:
        return f"Error finding large files: {str(e)}"


@register_tool()
async def find_empty_directories(
    path: str,
    ctx: Context,
    recursive: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    format: str = "text",
) -> str:
    """Find empty directories.

    Args:
        path: Starting directory
        recursive: Whether to search subdirectories
        exclude_patterns: Optional patterns to exclude
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Empty directory information
    """
    try:
        components = get_components()
        results = await components["advanced"].find_empty_directories(
            path, recursive, exclude_patterns
        )

        if format.lower() == "json":
            return json.dumps(results, indent=2)

        # Format as text
        if not results:
            return "No empty directories found"

        return f"Found {len(results)} empty directories:\n\n" + "\n".join(results)

    except Exception as e:
        return f"Error finding empty directories: {str(e)}"


# ==================== 技能管理工具 ====================


def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    原子写入文本内容到文件（使用临时文件 + 原子替换，防止进程崩溃导致部分写入

    Args:
        file_path: 目标文件路径
        content: 要写入的内容
        encoding: 文件编码
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(temp_path, file_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            logger.error("Failed to remove temp file", exc_info=True)
        raise


def _validate_name(name: str) -> Optional[str]:
    """
    验证技能名称

    Args:
        name: 技能名称

    Returns:
        验证失败返回错误信息，验证通过返回 None
    """
    if not name:
        return "Skill name is required."
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return f"Skill name exceeds {MAX_SKILL_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(name):
        return "Invalid skill name. Use lowercase letters, numbers, hyphens, dots, and underscores."
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """
    验证 SKILL.md 的 frontmatter

    Args:
        content: SKILL.md 完整内容

    Returns:
        验证失败返回错误信息，验证通过返回 None
    """
    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---)."

    lines = content.split("---", 3)
    if len(lines) < 3:
        return "SKILL.md must have closing --- for frontmatter."

    frontmatter = lines[1]
    if "name:" not in frontmatter:
        return "SKILL.md frontmatter must contain 'name' field."
    if "description:" not in frontmatter:
        return "SKILL.md frontmatter must contain 'description' field."

    return None


def _get_skills_dir() -> Path:
    """获取 skills 目录路径"""
    project_root = get_project_root()
    return project_root / SKILLS_DIR


def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    """
    查找现有技能

    Args:
        name: 技能名称

    Returns:
        找到返回技能信息字典，未找到返回 None
    """
    skills_dir = _get_skills_dir()
    skill_dir = skills_dir / name
    if skill_dir.exists() and skill_dir.is_dir():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            return {"name": name, "path": skill_dir, "skill_md_path": skill_md}
    return None


def _security_scan_skill(skill_dir: Path) -> Optional[str]:
    """
    安全扫描技能目录

    Args:
        skill_dir: 技能目录路径

    Returns:
        发现问题返回错误信息，通过返回 None
    """
    findings = []
    for file_path in skill_dir.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            rel_path = str(file_path.relative_to(skill_dir))
            for pattern, pid, severity, category, desc in THREAT_PATTERNS:
                for m in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                    findings.append(f"{rel_path}: {desc}")
        except Exception:
            pass

    if findings:
        return "Security scan found issues:\n" + "\n".join(findings)
    return None


def _build_skill_frontmatter(
    skill_name: str, description: str, task_conversations: List[Dict[str, Any]]
) -> str:
    """生成 SKILL.md 的 YAML frontmatter"""
    created_at = datetime.now().isoformat()
    task_ids = [t.get("task_id", "") for t in task_conversations if t.get("task_id")]
    task_ids_json = json.dumps(task_ids, ensure_ascii=False)
    return f"""---
name: {skill_name}
description: {description}
version: 1.0.0
author: Workmate Auto-Created
metadata:
  hermes:
    tags: [auto-created]
    created_at: "{created_at}"
    auto_created: true
    source_tasks: {task_ids_json}
---
"""


def _build_fallback_skill_body(
    skill_name: str, description: str, task_conversations: List[Dict[str, Any]]
) -> str:
    """LLM 调用失败时的兜底模板，仅包含基础结构"""
    skill_title = skill_name.replace("-", " ").title()
    all_tools: set = set()
    for conv in task_conversations:
        for tc in conv.get("tool_calls", []):
            if tc.get("tool"):
                all_tools.add(tc["tool"])
    tools_list = (
        "\n".join(f"- `{t}`" for t in sorted(all_tools)) or "- 根据需要使用相应工具"
    )
    return f"""# {skill_title}

## 概述
{description}

## 何时使用此技能
（待补充）

## 操作步骤
（待补充）

## 可用工具
{tools_list}

## 注意事项
（待补充）

---
*本技能由 Workmate 自动创建，基于历史任务总结。*
"""


async def _generate_skill_content_with_llm(
    skill_name: str, description: str, task_conversations: List[Dict[str, Any]]
) -> str:
    """
    调用 LLM 对任务对话进行总结提炼，生成 SKILL.md 内容

    Args:
        skill_name: 技能名称
        description: 技能描述
        task_conversations: 任务对话历史列表（每项含 conversation_transcript 字段）

    Returns:
        完整的 SKILL.md 文本
    """
    frontmatter = _build_skill_frontmatter(skill_name, description, task_conversations)

    conv_texts = []
    for i, conv in enumerate(task_conversations, 1):
        transcript = conv.get("conversation_transcript", "") or conv.get(
            "full_conversation", ""
        )
        if transcript:
            conv_texts.append(f"[对话 {i}]\n{transcript[:3000]}")

    if not conv_texts:
        return frontmatter + _build_fallback_skill_body(
            skill_name, description, task_conversations
        )

    conversations_joined = "\n\n".join(conv_texts)
    skill_title = skill_name.replace("-", " ").title()

    prompt = f"""请根据以下历史任务对话，为技能 "{skill_name}" 编写一份高质量的 SKILL.md 正文（不含 frontmatter）。

技能描述：{description}

历史任务对话：
{conversations_joined}

请按以下结构输出 Markdown 正文，内容必须基于对话中的真实信息，不要使用占位符：

# {skill_title}

## 概述
（1-2句话说明技能用途）

## 何时使用此技能
（列出具体触发场景，基于对话中的任务类型）

## 操作步骤
（分步骤说明，基于对话中 Agent 的实际执行过程）

## 输出要求
（说明最终交付物的格式和质量标准）

## 注意事项
（列出对话中出现的问题、边缘情况和最佳实践）

---
*本技能由 Workmate 自动创建，基于历史任务总结。*"""

    try:
        from workflow.model import mcp_llm
        from langchain_core.messages import HumanMessage

        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        body = response.content.strip()
        logger.info(f"[write_skill] LLM 生成技能内容成功，长度: {len(body)}")
        return frontmatter + "\n" + body
    except Exception as e:
        logger.error(f"[write_skill] LLM 生成失败，使用兜底模板: {e}")
        return frontmatter + _build_fallback_skill_body(
            skill_name, description, task_conversations
        )


def _generate_skill_content(
    skill_name: str, description: str, task_conversations: List[Dict[str, Any]]
) -> str:
    """同步兜底：仅在无法调用异步 LLM 时使用"""
    return _build_skill_frontmatter(
        skill_name, description, task_conversations
    ) + _build_fallback_skill_body(skill_name, description, task_conversations)


async def write_skill(
    skill_name: str,
    description: str,
    task_conversations: str,
    ctx: Context,
    include_scripts: Optional[str] = None,
    include_references: Optional[str] = None,
    include_assets: Optional[str] = None,
) -> str:
    """
    创建新技能并保存到 skills 目录。
    此工具已从 MCP 工具列表中移除，由后评估系统自动调用。
    保留函数定义仅供 workflow/post_task_evaluator.py 直接引用。
    """
    try:
        # 解析 JSON 参数
        try:
            conversations = json.loads(task_conversations)
        except json.JSONDecodeError:
            return json.dumps(
                {"success": False, "error": "Invalid JSON in task_conversations"}
            )

        scripts_list = []
        if include_scripts:
            try:
                scripts_list = json.loads(include_scripts)
            except json.JSONDecodeError:
                return json.dumps(
                    {"success": False, "error": "Invalid JSON in include_scripts"}
                )

        references_list = []
        if include_references:
            try:
                references_list = json.loads(include_references)
            except json.JSONDecodeError:
                return json.dumps(
                    {"success": False, "error": "Invalid JSON in include_references"}
                )

        assets_list = []
        if include_assets:
            try:
                assets_list = json.loads(include_assets)
            except json.JSONDecodeError:
                return json.dumps(
                    {"success": False, "error": "Invalid JSON in include_assets"}
                )

        # 验证技能名称
        name_error = _validate_name(skill_name)
        if name_error:
            return json.dumps({"success": False, "error": name_error})

        # 检查技能是否已存在
        existing = _find_skill(skill_name)
        if existing:
            return json.dumps(
                {"success": False, "error": f"Skill '{skill_name}' already exists."}
            )

        skill_content = await _generate_skill_content_with_llm(
            skill_name, description, conversations
        )

        # 验证内容大小
        if len(skill_content) > MAX_SKILL_CONTENT_LENGTH:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Skill content too large ({len(skill_content)} chars). "
                    f"Max {MAX_SKILL_CONTENT_LENGTH} chars allowed.",
                }
            )

        # 验证 frontmatter
        frontmatter_error = _validate_frontmatter(skill_content)
        if frontmatter_error:
            return json.dumps({"success": False, "error": frontmatter_error})

        # 创建技能目录
        skills_dir = _get_skills_dir()
        skill_dir = skills_dir / skill_name

        try:
            skill_dir.mkdir(parents=True, exist_ok=False)
            logger.info(f"Created skill directory: {skill_dir}")
        except Exception as e:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Failed to create skill directory: {str(e)}",
                }
            )

        # 写入 SKILL.md
        skill_md_path = skill_dir / "SKILL.md"
        try:
            _atomic_write_text(skill_md_path, skill_content)
            logger.info(f"Created SKILL.md at {skill_md_path}")
        except Exception as e:
            shutil.rmtree(skill_dir, ignore_errors=True)
            return json.dumps(
                {"success": False, "error": f"Failed to write SKILL.md: {str(e)}"}
            )

        # 复制辅助文件
        try:
            # 复制 scripts
            if scripts_list:
                scripts_dir = skill_dir / "scripts"
                scripts_dir.mkdir(exist_ok=True)
                for src_path in scripts_list:
                    src = Path(src_path)
                    if src.exists():
                        shutil.copy2(src, scripts_dir / src.name)

            # 复制 references
            if references_list:
                refs_dir = skill_dir / "references"
                refs_dir.mkdir(exist_ok=True)
                for src_path in references_list:
                    src = Path(src_path)
                    if src.exists():
                        shutil.copy2(src, refs_dir / src.name)

            # 复制 assets
            if assets_list:
                assets_dir = skill_dir / "assets"
                assets_dir.mkdir(exist_ok=True)
                for src_path in assets_list:
                    src = Path(src_path)
                    if src.exists():
                        shutil.copy2(src, assets_dir / src.name)
        except Exception as e:
            logger.warning(f"Failed to copy some resource files: {e}")

        # 安全扫描
        scan_error = _security_scan_skill(skill_dir)
        if scan_error:
            shutil.rmtree(skill_dir, ignore_errors=True)
            return json.dumps({"success": False, "error": scan_error})

        return json.dumps(
            {
                "success": True,
                "skill_name": skill_name,
                "skill_path": str(skill_dir),
                "message": f"Skill '{skill_name}' created successfully",
            },
            ensure_ascii=False,
        )

    except Exception as e:
        logger.error(f"Error in write_skill", exc_info=True)
        return json.dumps({"success": False, "error": str(e)})


def _fuzzy_find_and_replace(
    content: str, old_string: str, new_string: str, replace_all: bool = False
) -> tuple[str, int, str, Optional[str]]:
    """
    模糊查找并替换（处理空白符差异等）

    Args:
        content: 原始内容
        old_string: 要查找的字符串
        new_string: 替换后的字符串
        replace_all: 是否替换所有匹配

    Returns:
        (新内容, 匹配次数, 策略, 错误信息)
    """
    # 简单实现：先精确匹配，失败则归一化空白符匹配
    match_count = 0
    error = None

    # 精确匹配
    if old_string in content:
        if replace_all:
            new_content = content.replace(old_string, new_string)
            match_count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            match_count = 1
        return new_content, match_count, "exact", None

    # 归一化空白符匹配
    def normalize_whitespace(s):
        return re.sub(r"\s+", " ", s.strip())

    normalized_content = normalize_whitespace(content)
    normalized_old = normalize_whitespace(old_string)

    if normalized_old in normalized_content:
        # 这里是简化实现，实际需要更复杂的匹配
        error = "Could not find exact match, but fuzzy match found. Use edit with full content for better results."
        return content, 0, "fuzzy_failed", error

    error = (
        f"Could not find string to replace. Preview of content start:\n" + content[:500]
    )
    return content, 0, "not_found", error


async def edit_skill(
    skill_name: str,
    relevant_conversations: str,
    improvement_reason: str,
    ctx: Context,
    update_type: str = "patch",
    old_string: Optional[str] = None,
    new_string: Optional[str] = None,
    full_content: Optional[str] = None,
) -> str:
    """
    改进现有技能。
    此工具已从 MCP 工具列表中移除，由后评估系统自动调用。
    保留函数定义仅供 workflow/post_task_evaluator.py 直接引用。

    Args:
        skill_name: 要改进的技能名称
        relevant_conversations: JSON 格式的相关对话历史列表字符串
        improvement_reason: 改进原因描述
        update_type: 更新类型（patch 或 full，默认 patch）
        old_string: 要替换的旧字符串（patch 模式需要）
        new_string: 替换后的新字符串（patch 模式需要）
        full_content: 完整的新内容（full 模式需要）
        ctx: MCP 上下文

    Returns:
        JSON 格式的操作结果
    """
    try:
        # 解析对话历史
        try:
            conversations = json.loads(relevant_conversations)
        except json.JSONDecodeError:
            return json.dumps(
                {"success": False, "error": "Invalid JSON in relevant_conversations"}
            )

        # 查找现有技能
        existing = _find_skill(skill_name)
        if not existing:
            return json.dumps(
                {"success": False, "error": f"Skill '{skill_name}' not found."}
            )

        skill_dir = existing["path"]
        skill_md_path = existing["skill_md_path"]

        # 读取原始内容
        original_content = skill_md_path.read_text(encoding="utf-8")

        # 更新版本号
        import re

        version_match = re.search(r"version:\s*([\d.]+)", original_content)
        old_version = version_match.group(1) if version_match else "1.0.0"

        # 版本号递增
        version_parts = old_version.split(".")
        if len(version_parts) >= 3:
            version_parts[2] = str(int(version_parts[2]) + 1)
        else:
            version_parts = ["1", "0", "1"]
        new_version = ".".join(version_parts)

        # 根据更新类型处理
        new_content = original_content
        changes = []

        if update_type == "patch":
            if not old_string or not new_string:
                return json.dumps(
                    {
                        "success": False,
                        "error": "old_string and new_string required for patch update_type",
                    }
                )

            new_content, match_count, strategy, match_error = _fuzzy_find_and_replace(
                original_content, old_string, new_string, replace_all=False
            )

            if match_error:
                return json.dumps({"success": False, "error": match_error})

            changes.append(f"Patch applied ({match_count} replacement(s))")

        elif update_type == "full":
            if not full_content:
                return json.dumps(
                    {
                        "success": False,
                        "error": "full_content required for full update_type",
                    }
                )

            # 验证新内容
            frontmatter_error = _validate_frontmatter(full_content)
            if frontmatter_error:
                return json.dumps({"success": False, "error": frontmatter_error})

            new_content = full_content
            changes.append("Full skill content rewritten")

        else:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Invalid update_type: {update_type}. Use 'patch' or 'full'.",
                }
            )

        # 更新版本号
        new_content = re.sub(
            r"version:\s*[\d.]+", f"version: {new_version}", new_content
        )
        changes.append(f"Version updated from {old_version} to {new_version}")

        # 添加改进记录
        now = datetime.now().isoformat()
        improvement_note = (
            f"\n\n---\n## Improvement Note ({now}):\n{improvement_reason}\n"
        )
        if "## Improvement Note" not in new_content:
            new_content = new_content.rstrip() + improvement_note

        # 备份原文件
        backup_path = skill_md_path.with_suffix(
            f".md.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(skill_md_path, backup_path)

        # 原子写入新内容
        _atomic_write_text(skill_md_path, new_content)

        # 安全扫描
        scan_error = _security_scan_skill(skill_dir)
        if scan_error:
            shutil.copy2(backup_path, skill_md_path)
            backup_path.unlink(missing_ok=True)
            return json.dumps({"success": False, "error": scan_error})

        backup_path.unlink(missing_ok=True)

        return json.dumps(
            {
                "success": True,
                "skill_name": skill_name,
                "old_version": old_version,
                "new_version": new_version,
                "message": f"Skill '{skill_name}' updated successfully",
                "changes": changes,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        logger.error(f"Error in edit_skill", exc_info=True)
        return json.dumps({"success": False, "error": str(e)})
