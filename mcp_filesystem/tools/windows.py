"""Windows automation tools.

This module contains tools for Windows UI automation, process management,
and input simulation.
"""

import json
import os
from typing import List, Optional

from fastmcp import Context

from ..context import mcp, get_windows_components

# Control whether Windows tools are exposed
# Default to True, can be disabled by setting MCP_ENABLE_WINDOWS_TOOLS=false
ENABLE_WINDOWS_TOOLS = (
    os.environ.get("MCP_ENABLE_WINDOWS_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator based on ENABLE_WINDOWS_TOOLS."""
    if ENABLE_WINDOWS_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def start_app(
    target: str,
    ctx: Context,
    mode: str = "process_name",
    wait_ready: bool = True,
    timeout: int = 30,
) -> str:
    """Start an application.

    Args:
        target: Target identifier (process name, path, or .lnk file)
        mode: Identification mode ("process_name", "path", "lnk")
        wait_ready: Whether to wait for the application to be ready
        timeout: Start timeout in seconds
        ctx: MCP context

    Returns:
        Execution result string
    """
    try:
        components = get_windows_components()
        result = components["process_manager"].start(target, mode, wait_ready, timeout)
        if result["success"]:
            return f'Success: Started "{result["name"]}" (PID: {result["pid"]})'
        return f"Error: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def stop_app(
    target: str,
    ctx: Context,
    force: bool = False,
    timeout: int = 10,
) -> str:
    """Stop an application.

    Args:
        target: Process name or PID
        force: Whether to force terminate
        timeout: Stop timeout in seconds
        ctx: MCP context

    Returns:
        Execution result string
    """
    try:
        components = get_windows_components()
        result = components["process_manager"].stop(target, force, timeout)
        if result["success"]:
            return f'Success: Stopped application "{target}"'
        return f"Error: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def list_processes(
    ctx: Context,
    filter: Optional[str] = None,
    include_system: bool = False,
) -> str:
    """List running processes.

    Args:
        filter: Process name filter
        include_system: Whether to include system processes
        ctx: MCP context

    Returns:
        Process list string
    """
    try:
        components = get_windows_components()
        processes = components["process_manager"].list(filter, include_system)

        if not processes:
            return "No processes found matching criteria."

        lines = [f"{'Name':<30} {'PID':<10} {'CPU%':<10} {'Mem(MB)':<10}"]
        lines.append("-" * 60)

        for p in processes:
            lines.append(
                f"{p['name']:<30} {p['pid']:<10} {p['cpu_percent']:<10} {p['memory_mb']:<10}"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def get_process_info(
    target: str,
    ctx: Context,
) -> str:
    """Get detailed process information.

    Args:
        target: Process name or PID
        ctx: MCP context

    Returns:
        Process info string
    """
    try:
        components = get_windows_components()
        info = components["process_manager"].get_info(target)

        if "error" in info:
            return f"Error: {info['error']}"

        return json.dumps(info, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def find_window(
    ctx: Context,
    title: Optional[str] = None,
    class_name: Optional[str] = None,
    process_name: Optional[str] = None,
) -> str:
    """Find a window handle based on criteria.

    Args:
        title: Window title (partial match)
        class_name: Window class name
        process_name: Process name owning the window
        ctx: MCP context

    Returns:
        Window handle info
    """
    try:
        components = get_windows_components()
        hwnd = components["window_controller"].find(title, class_name, process_name)

        if hwnd:
            return f"Found window handle: {hwnd}"
        return "Window not found"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def get_window_state(
    window: str,
    ctx: Context,
) -> str:
    """Get window state.

    Args:
        window: Window handle (as string)
        ctx: MCP context

    Returns:
        Window state info
    """
    try:
        components = get_windows_components()
        if not window.isdigit():
            # Try to find window first if name provided
            hwnd = components["window_controller"].find(title=window)
            if not hwnd:
                return f"Error: Window '{window}' not found"
        else:
            hwnd = int(window)

        state = components["window_controller"].get_state(hwnd)

        if "error" in state:
            return f"Error: {state['error']}"

        return json.dumps(state, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def set_window_state(
    window: str,
    state: str,
    ctx: Context,
) -> str:
    """Set window state.

    Args:
        window: Window handle or title
        state: Target state (activate, minimize, maximize, restore, hide, show, close)
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if not window.isdigit():
            hwnd = components["window_controller"].find(title=window)
            if not hwnd:
                return f"Error: Window '{window}' not found"
        else:
            hwnd = int(window)

        success = components["window_controller"].set_state(hwnd, state)

        if success:
            return f"Success: Set window {hwnd} state to {state}"
        return f"Error: Failed to set window state"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def close_window(
    window: str,
    ctx: Context,
    force: bool = False,
) -> str:
    """Close window.

    Args:
        window: Window handle or title
        force: Whether to force close
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if not window.isdigit():
            hwnd = components["window_controller"].find(title=window)
            if not hwnd:
                return f"Error: Window '{window}' not found"
        else:
            hwnd = int(window)

        success = components["window_controller"].close(hwnd, force)

        if success:
            return f"Success: Closed window {hwnd}"
        return f"Error: Failed to close window"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def click_element(
    window: str,
    ctx: Context,
    element_name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    button: str = "left",
    double_click: bool = False,
) -> str:
    """Click a UI element.

    Args:
        window: Window title or handle
        element_name: Element name (title)
        automation_id: Automation ID
        control_type: Control type
        button: Mouse button (left, right, middle)
        double_click: Whether to double click
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        ui = components["ui_automation"]

        if not ui.connect(window):
            return f"Error: Could not connect to window '{window}'"

        criteria = {}
        if element_name:
            criteria["element_name"] = element_name
        if automation_id:
            criteria["automation_id"] = automation_id
        if control_type:
            criteria["control_type"] = control_type

        element = ui.find_element(criteria)
        if not element:
            return f"Error: Element not found with criteria: {criteria}"

        if ui.click(element, button, double_click):
            return "Success: Clicked element"
        return "Error: Failed to click element"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def input_text(
    window: str,
    text: str,
    ctx: Context,
    element_name: Optional[str] = None,
    automation_id: Optional[str] = None,
    clear_first: bool = False,
) -> str:
    """Input text into a UI element.

    Args:
        window: Window title or handle
        text: Text to input
        element_name: Element name (title)
        automation_id: Automation ID (more reliable than element_name for system dialogs)
        clear_first: Whether to clear existing text
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        ui = components["ui_automation"]

        if not ui.connect(window):
            return f"Error: Could not connect to window '{window}'"

        criteria = {}
        if element_name:
            criteria["element_name"] = element_name
        if automation_id:
            criteria["automation_id"] = automation_id

        element = ui.find_element(criteria)
        if not element:
            return f"Error: Element not found"

        if ui.input(element, text, clear_first):
            return "Success: Input text"
        return "Error: Failed to input text"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def list_elements(
    window: str,
    ctx: Context,
) -> str:
    """列出窗口所有子元素的 automation_id、title、control_type，用于诊断元素查找问题。

    Args:
        window: 窗口标题或句柄
        ctx: MCP context

    Returns:
        元素列表 JSON 字符串
    """
    try:
        components = get_windows_components()
        ui = components["ui_automation"]
        elements = ui.list_elements(window)
        if not elements:
            return f"Error: No elements found or could not connect to window '{window}'"
        return json.dumps(elements, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def mouse_click(
    x: int,
    y: int,
    ctx: Context,
    button: str = "left",
    double_click: bool = False,
) -> str:
    """Click mouse at coordinates.

    Args:
        x: X coordinate
        y: Y coordinate
        button: Mouse button
        double_click: Whether to double click
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["input_simulator"].mouse_click(x, y, button, double_click):
            return f"Success: Clicked at ({x}, {y})"
        return "Error: Failed to click mouse"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def keyboard_type(
    text: str,
    ctx: Context,
) -> str:
    """Type text using keyboard simulation.

    Args:
        text: Text to type
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["input_simulator"].keyboard_type(text):
            return f"Success: Typed text"
        return "Error: Failed to type text"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def keyboard_hotkey(
    keys: List[str],
    ctx: Context,
) -> str:
    """Press a combination of keys (hotkey).

    Args:
        keys: List of keys to press together (e.g., ["ctrl", "s"], ["alt", "f4"])
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["input_simulator"].keyboard_hotkey(*keys):
            return f"Success: Pressed hotkey {'+'.join(keys)}"
        return "Error: Failed to press hotkey"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def clipboard_paste(
    text: str,
    ctx: Context,
) -> str:
    """Set text to clipboard and paste it using Ctrl+V.

    This is the most reliable way to input text, especially for paths or when dealing with different input methods (IME).

    Args:
        text: Text to paste
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["input_simulator"].clipboard_set_and_paste(text):
            return f"Success: Pasted text from clipboard"
        return "Error: Failed to paste text"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def clipboard_read(
    ctx: Context,
) -> str:
    """Read text from clipboard.

    Args:
        ctx: MCP context

    Returns:
        Clipboard text or error message
    """
    try:
        components = get_windows_components()
        text = components["input_simulator"].clipboard_read()
        if text is not None:
            return text
        return "Error: Clipboard is empty or contains non-text data"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def clipboard_copy_file(
    file_paths: List[str],
    ctx: Context,
) -> str:
    """Copy files to clipboard so they can be pasted into applications (like WeChat, Explorer).

    This is the most reliable way to send files in chat applications.

    Args:
        file_paths: List of absolute file paths to copy
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["input_simulator"].clipboard_copy_file(file_paths):
            return f"Success: Copied {len(file_paths)} files to clipboard"
        return "Error: Failed to copy files to clipboard (check if files exist)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def wait_for_element(
    window: str,
    ctx: Context,
    element_name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """Wait for a UI element to appear.

    Args:
        window: Window title or handle
        element_name: Element name
        automation_id: Automation ID
        control_type: Control type
        timeout: Timeout in seconds
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        ui = components["ui_automation"]

        if not ui.connect(window):
            return f"Error: Could not connect to window '{window}'"

        criteria = {}
        if element_name:
            criteria["element_name"] = element_name
        if automation_id:
            criteria["automation_id"] = automation_id
        if control_type:
            criteria["control_type"] = control_type

        element = ui.wait(criteria, timeout)
        if element:
            return "Success: Element found"
        return f"Error: Timeout waiting for element"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def start_recording(ctx: Context) -> str:
    """Start recording user actions.

    Args:
        ctx: MCP context

    Returns:
        Result string
    """
    try:
        components = get_windows_components()
        if components["script_recorder"].start():
            return "Success: Recording started"
        return "Error: Failed to start recording (already recording?)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def stop_recording(
    ctx: Context,
    save_path: Optional[str] = None,
) -> str:
    """Stop recording user actions.

    Args:
        save_path: Path to save the script
        ctx: MCP context

    Returns:
        Recording result
    """
    try:
        components = get_windows_components()
        result = components["script_recorder"].stop(save_path)

        if "error" in result:
            return f"Error: {result['error']}"

        msg = f"Success: Recording stopped. {result['actions_count']} actions recorded."
        if "saved_to" in result:
            msg += f" Saved to {result['saved_to']}"
        return msg
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def playback_script(
    script_path: str,
    ctx: Context,
    speed: float = 1.0,
    repeat: int = 1,
) -> str:
    """Playback a recorded script.

    Args:
        script_path: Path to script file
        speed: Playback speed multiplier
        repeat: Number of times to repeat
        ctx: MCP context

    Returns:
        Playback result
    """
    try:
        components = get_windows_components()
        result = components["script_recorder"].playback(script_path, speed, repeat)

        if result["success"]:
            return f"Success: Playback completed. {result['actions_played']} actions played."
        return f"Error: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"
