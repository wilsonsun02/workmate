"""MCP Filesystem Context and Components.

This module provides the shared context, component initialization, and the FastMCP instance
used across different tool modules.
"""

import os
import sys
from pathlib import Path
from typing import Any, List, Union, Dict

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger


def load_env_file() -> None:
    """Load project .env (stdio MCP subprocess may not inherit serve's cwd)."""
    roots: list[str] = []
    try:
        from mcp_filesystem.paths import app_base_dir

        roots.append(app_base_dir())
    except Exception:
        pass
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.extend([pkg_root, os.getcwd()])
    seen: set[str] = set()
    for root in roots:
        root = (root or "").strip()
        if not root or root in seen:
            continue
        seen.add(root)
        env_path = os.path.join(root, ".env")
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value.strip()
        except OSError:
            pass
        break


# Load .env file
load_env_file()

from .advanced import AdvancedFileOperations
from .operations import FileOperations
from .security import PathValidator
from .grep import GrepTools
from .doc_reader import DocumentReader
from .windows import (
    ProcessManager,
    WindowController,
    UIAutomationController,
    InputSimulator,
    ScriptRecorder,
)

logger = get_logger(__name__)

# Create the FastMCP instance
mcp = FastMCP(
    name="Filesystem MCP Server",
    instructions="Provides secure access to the filesystem through MCP",
)


def get_allowed_dirs() -> List[Union[str, Path]]:
    """Get the list of allowed directories from environment or arguments.

    Returns:
        List of allowed directory paths
    """
    allowed_dirs = os.environ.get("MCP_ALLOWED_DIRS", "").split(os.pathsep)

    # Add any command-line arguments as allowed directories
    if len(sys.argv) > 1:
        allowed_dirs.extend(sys.argv[1:])

    # If no allowed directories specified, use current directory
    if not allowed_dirs or all(not d for d in allowed_dirs):
        allowed_dirs = [os.getcwd()]

    # Cast strings and filter empty strings
    return [d for d in allowed_dirs if d]


# Create component initialization function with caching
_components_cache: Dict[str, Any] = {}
_windows_components_cache: Dict[str, Any] = {}


def get_windows_components() -> Dict[str, Any]:
    """Initialize and return Windows automation components.

    Returns:
        Dictionary with initialized components
    """
    global _windows_components_cache
    if _windows_components_cache:
        return _windows_components_cache

    _windows_components_cache = {
        "process_manager": ProcessManager(),
        "window_controller": WindowController(),
        "ui_automation": UIAutomationController(),
        "input_simulator": InputSimulator(),
        "script_recorder": ScriptRecorder(),
    }
    return _windows_components_cache


def get_components() -> Dict[str, Any]:
    """Initialize and return shared components.

    Returns cached components if already initialized.

    Returns:
        Dictionary with initialized components
    """
    global _components_cache

    # Return cached components if available
    if _components_cache:
        return _components_cache

    # Initialize components
    allowed_dirs_typed: List[Union[str, Path]] = get_allowed_dirs()
    validator = PathValidator(allowed_dirs_typed)
    operations = FileOperations(validator)
    advanced = AdvancedFileOperations(validator, operations)
    grep = GrepTools(validator)
    doc_reader = DocumentReader(validator)

    # Store in cache
    _components_cache = {
        "validator": validator,
        "operations": operations,
        "advanced": advanced,
        "grep": grep,
        "doc_reader": doc_reader,
        "allowed_dirs": validator.get_allowed_dirs(),
    }

    logger.info(
        f"Initialized filesystem components with allowed directories: {validator.get_allowed_dirs()}"
    )

    return _components_cache
