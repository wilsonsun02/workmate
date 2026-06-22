"""MCP Filesystem Server.

This module provides a Model Context Protocol server for filesystem operations,
allowing Claude and other MCP clients to safely access and manipulate files.
"""

from .context import mcp

# Import tools to register them with the MCP server
from . import tools  # noqa: F401

# Entry point for direct execution
if __name__ == "__main__":
    mcp.run()
