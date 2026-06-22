"""Basic file operation tools.

This module contains basic file system operations such as reading, writing,
listing, and moving files and directories.
"""

import json
import os
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..context import mcp, get_components

try:
    from PIL import Image, ImageGrab

    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False

# Control whether Common tools are exposed
ENABLE_COMMON_TOOLS = (
    os.environ.get("MCP_ENABLE_COMMON_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_COMMON_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def read_file(path: str, ctx: Context, encoding: str = "utf-8") -> str:
    """Read the complete contents of a file.

    Args:
        path: Path to the file
        encoding: File encoding (default: utf-8)
        ctx: MCP context

    Returns:
        File contents as a string
    """
    try:
        components = get_components()
        return await components["operations"].read_file(path, encoding)
    except Exception as e:
        return f"Error reading file: {str(e)}"


@register_tool()
async def read_multiple_files(
    paths: List[str], ctx: Context, encoding: str = "utf-8"
) -> Dict[str, str]:
    """Read multiple files at once.

    Args:
        paths: List of file paths to read
        encoding: File encoding (default: utf-8)
        ctx: MCP context

    Returns:
        Dictionary mapping file paths to contents or error messages
    """
    try:
        components = get_components()
        results = await components["operations"].read_multiple_files(paths, encoding)

        # Convert exceptions to strings for JSON serialization
        formatted_results = {}
        for path, result in results.items():
            if isinstance(result, Exception):
                formatted_results[path] = f"Error: {str(result)}"
            else:
                formatted_results[path] = result

        return formatted_results
    except Exception as e:
        return {"error": str(e)}


@register_tool()
async def write_file(
    path: str,
    content: str,
    ctx: Context,
    encoding: str = "utf-8",
    create_dirs: bool = False,
) -> str:
    """Create a new file or overwrite an existing file with new content.

    Args:
        path: Path to write to
        content: Content to write
        encoding: File encoding (default: utf-8)
        create_dirs: Whether to create parent directories if they don't exist
        ctx: MCP context

    Returns:
        Success or error message
    """
    try:
        components = get_components()
        await components["operations"].write_file(path, content, encoding, create_dirs)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@register_tool()
async def create_directory(
    path: str,
    ctx: Context,
    parents: bool = True,
    exist_ok: bool = True,
) -> str:
    """Create a new directory or ensure a directory exists.

    Args:
        path: Path to the directory
        parents: Create parent directories if they don't exist
        exist_ok: Don't raise an error if directory already exists
        ctx: MCP context

    Returns:
        Success or error message
    """
    try:
        components = get_components()
        await components["operations"].create_directory(path, parents, exist_ok)
        return f"Successfully created directory {path}"
    except Exception as e:
        return f"Error creating directory: {str(e)}"


@register_tool()
async def list_directory(
    path: str,
    ctx: Context,
    include_hidden: bool = False,
    pattern: Optional[str] = None,
    format: str = "text",
) -> str:
    """Get a detailed listing of files and directories in a path.

    Args:
        path: Path to the directory
        include_hidden: Whether to include hidden files (starting with .)
        pattern: Optional glob pattern to filter entries
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Formatted directory listing
    """
    try:
        components = get_components()
        if format.lower() == "json":
            entries = await components["operations"].list_directory(
                path, include_hidden, pattern
            )
            return json.dumps(entries, indent=2)
        else:
            return await components["operations"].list_directory_formatted(
                path, include_hidden, pattern
            )
    except Exception as e:
        return f"Error listing directory: {str(e)}"


@register_tool()
async def move_file(
    source: str,
    destination: str,
    ctx: Context,
    overwrite: bool = False,
) -> str:
    """Move or rename files and directories.

    Args:
        source: Source path
        destination: Destination path
        overwrite: Whether to overwrite existing destination
        ctx: MCP context

    Returns:
        Success or error message
    """
    try:
        components = get_components()
        await components["operations"].move_file(source, destination, overwrite)
        return f"Successfully moved {source} to {destination}"
    except Exception as e:
        return f"Error moving file: {str(e)}"


@register_tool()
async def get_file_info(path: str, ctx: Context, format: str = "text") -> str:
    """Retrieve detailed metadata about a file or directory.

    Args:
        path: Path to the file or directory
        format: Output format ('text' or 'json')
        ctx: MCP context

    Returns:
        Formatted file information
    """
    try:
        components = get_components()
        info = await components["operations"].get_file_info(path)

        if format.lower() == "json":
            return json.dumps(info.to_dict(), indent=2)
        else:
            return str(info)
    except Exception as e:
        return f"Error getting file info: {str(e)}"


@register_tool()
async def download_file(url: str, path: str, ctx: Context) -> str:
    """Download a file from a URL to a local path.

    Supports downloading various file types including .txt, .md, .doc, .docx,
    .pdf, .ppt, .pptx, .xls, .xlsx, .csv, images, videos, and audio files.

    Args:
        url: URL of the file to download
        path: Local path to save the file
        ctx: MCP context

    Returns:
        Success or error message
    """
    try:
        components = get_components()
        saved_path = await components["operations"].download_file(url, path)
        return f"Successfully downloaded {url} to {saved_path}"
    except Exception as e:
        return f"Error downloading file: {str(e)}"


@register_tool()
async def list_allowed_directories(ctx: Context) -> str:
    """Returns the list of directories that this server is allowed to access.

    Args:
        ctx: MCP context

    Returns:
        List of allowed directories
    """
    components = get_components()
    allowed_dirs = components["allowed_dirs"]
    return f"Allowed directories:\n{os.linesep.join(allowed_dirs)}"


@register_tool()
async def edit_file(
    path: str,
    edits: List[Dict[str, str]],
    ctx: Context,
    encoding: str = "utf-8",
    dry_run: bool = False,
) -> str:
    """Make line-based edits to a text file.

    Args:
        path: Path to the file
        edits: List of {oldText, newText} dictionaries
        encoding: Text encoding (default: utf-8)
        dry_run: If True, return diff but don't modify file
        ctx: MCP context

    Returns:
        Git-style diff showing changes
    """
    try:
        components = get_components()
        return await components["operations"].edit_file(path, edits, encoding, dry_run)
    except Exception as e:
        return f"Error editing file: {str(e)}"


@register_tool()
async def take_screenshot(
    path: str,
    ctx: Context,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    """Take a screenshot of the entire screen or a specific region.

    Args:
        path: Path to save the screenshot file (e.g., "${BASE_DIR}/output/screenshots/kline.png")
        ctx: MCP context
        x: X coordinate of the capture region (None for full screen)
        y: Y coordinate of the capture region (None for full screen)
        width: Width of the capture region (None for full screen width)
        height: Height of the capture region (None for full screen height)

    Returns:
        Success or error message
    """
    if not SCREENSHOT_AVAILABLE:
        return "Error: PIL/Pillow is not installed. Screenshot functionality is unavailable."

    try:
        if x is not None and y is not None and width is not None and height is not None:
            bbox = (x, y, x + width, y + height)
            img = ImageGrab.grab(bbox=bbox)
        else:
            img = ImageGrab.grab()

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        img.save(path)
        return f"Success: Screenshot saved to {path}"
    except Exception as e:
        return f"Error taking screenshot: {str(e)}"


@register_tool()
async def head_file(
    path: str,
    ctx: Context,
    lines: int = 10,
    encoding: str = "utf-8",
) -> str:
    """Read the first N lines of a text file.

    Args:
        path: Path to the file
        lines: Number of lines to read (default: 10)
        encoding: Text encoding (default: utf-8)
        ctx: MCP context

    Returns:
        First N lines of the file
    """
    try:
        components = get_components()
        content = await components["operations"].head_file(path, lines, encoding)
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


@register_tool()
async def tail_file(
    path: str,
    ctx: Context,
    lines: int = 10,
    encoding: str = "utf-8",
) -> str:
    """Read the last N lines of a text file.

    Args:
        path: Path to the file
        lines: Number of lines to read (default: 10)
        encoding: Text encoding (default: utf-8)
        ctx: MCP context

    Returns:
        Last N lines of the file
    """
    try:
        components = get_components()
        content = await components["operations"].tail_file(path, lines, encoding)
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


@register_tool()
async def read_file_lines(
    path: str,
    ctx: Context,
    offset: int = 0,
    limit: Optional[int] = None,
    encoding: str = "utf-8",
) -> str:
    """Read specific lines from a text file.

    Args:
        path: Path to the file
        offset: Line offset (0-based, starts at first line)
        limit: Maximum number of lines to read (None for all remaining)
        encoding: Text encoding (default: utf-8)
        ctx: MCP context

    Returns:
        File content and metadata
    """
    try:
        components = get_components()
        content, metadata = await components["operations"].read_file_lines(
            path, offset, limit, encoding
        )

        if not content:
            last_line_desc = "end" if limit is None else f"offset+{limit}"
            return f"No content found between offset {offset} and {last_line_desc}"

        # Calculate display lines (1-based for human readability)
        display_start = offset + 1
        display_end = offset + metadata["lines_read"]

        header = (
            f"File: {path}\n"
            f"Lines: {display_start} to {display_end} "
            f"(of {metadata['total_lines']} total)\n"
            f"----------------------------------------\n"
        )

        return header + content

    except Exception as e:
        return f"Error reading file lines: {str(e)}"


@register_tool()
async def edit_file_at_line(
    path: str,
    line_edits: List[Dict[str, Any]],
    ctx: Context,
    offset: int = 0,
    limit: Optional[int] = None,
    relative_line_numbers: bool = False,
    abort_on_verification_failure: bool = False,
    encoding: str = "utf-8",
    dry_run: bool = False,
) -> str:
    """Edit specific lines in a text file.

    Args:
        path: Path to the file
        line_edits: List of edits to apply. Each edit is a dict with:
            - line_number: Line number to edit (0-based if relative_line_numbers=True, otherwise 1-based)
            - action: "replace", "insert_before", "insert_after", "delete"
            - content: New content for replace/insert operations (optional for delete)
            - expected_content: (Optional) Expected content of the line being edited for verification
        offset: Line offset (0-based) to start considering lines
        limit: Maximum number of lines to consider
        relative_line_numbers: Whether line numbers in edits are relative to offset
        abort_on_verification_failure: Whether to abort all edits if any verification fails
        encoding: Text encoding (default: utf-8)
        dry_run: If True, returns what would be changed without modifying the file
        ctx: MCP context

    Returns:
        Edit results summary
    """
    try:
        components = get_components()
        results = await components["operations"].edit_file_at_line(
            path,
            line_edits,
            offset,
            limit,
            relative_line_numbers,
            abort_on_verification_failure,
            encoding,
            dry_run,
        )

        # Format as text summary
        mode = "Would apply" if dry_run else "Applied"

        # Check if we had verification failures that prevented editing
        if "success" in results and not results["success"]:
            summary = [
                f"Failed to edit {results['path']} due to content verification failures:",
                "",
            ]

            if "verification_failures" in results:
                for failure in results["verification_failures"]:
                    line_num = failure.get("line", "?")
                    action = failure.get("action", "?")
                    summary.append(f"Line {line_num}: {action} - Verification failed")
                    summary.append(f"  Expected: {failure.get('expected', '').strip()}")
                    summary.append(f"  Actual:   {failure.get('actual', '').strip()}")
                    summary.append("")

            if "message" in results:
                summary.append(f"Error: {results['message']}")

            return "\n".join(summary)

        # Normal success case
        summary = [
            f"{mode} {results['edits_applied']} edits to {results['path']}:",
            "",
        ]

        # Add verification warnings if any
        if "verification_failures" in results and results["verification_failures"]:
            summary.append(
                "Warning: Some content verification checks failed but edits were applied:"
            )
            for failure in results["verification_failures"]:
                line_num = failure.get("line", "?")
                summary.append(f"  Line {line_num}: Content did not match expected")
            summary.append("")

        for change in results["changes"]:
            line_num = change.get("line", "?")
            action = change.get("action", "?")
            orig_line_num = change.get("original_line_number", "")
            line_info = f"Line {line_num}"
            if relative_line_numbers and orig_line_num != "":
                line_info = f"Line {line_num} (relative: {orig_line_num})"

            if action == "replace":
                summary.append(f"{line_info}: Replaced")
                summary.append(f"  - {change.get('before', '').strip()}")
                summary.append(f"  + {change.get('after', '').strip()}")
            elif action == "insert_before":
                summary.append(f"{line_info}: Inserted before")
                summary.append(f"  + {change.get('content', '').strip()}")
            elif action == "insert_after":
                summary.append(f"{line_info}: Inserted after")
                summary.append(f"  + {change.get('content', '').strip()}")
            elif action == "delete":
                summary.append(f"{line_info}: Deleted")
                summary.append(f"  - {change.get('content', '').strip()}")

            if "error" in change:
                summary.append(f"  ! Error: {change['error']}")

            summary.append("")

        return "\n".join(summary)

    except Exception as e:
        return f"Error editing file: {str(e)}"


async def save_user_preference(
    contact_name: str, pref_key: str, pref_value: str, ctx: Context
) -> str:
    """将用户的长期偏好或习惯写入 MySQL 数据库（持久化，重启后保留）。

    此工具已从 MCP 工具列表中移除，由后评估系统自动调用。
    保留函数定义仅供 workflow/post_task_evaluator.py 直接引用。
    """
    try:
        from workflow.report_tools import save_user_preference as _save

        _save(contact_name, pref_key, pref_value)
        return f"已保存长期偏好：[{pref_key}] = {pref_value}"
    except Exception as e:
        return f"保存长期偏好失败: {e}"


@register_tool()
async def get_user_preferences_summary(contact_name: str, ctx: Context) -> str:
    """从 MySQL 数据库读取指定联系人的所有长期偏好记录。

    Args:
        contact_name: 联系人名称（当前对话的用户名）
        ctx: MCP context

    Returns:
        格式化的偏好列表，若无记录则返回提示信息
    """
    try:
        from workflow.report_tools import get_user_preferences

        result = get_user_preferences(contact_name)
        return result if result else f"暂无 {contact_name} 的长期偏好记录"
    except Exception as e:
        return f"读取长期偏好失败: {e}"
