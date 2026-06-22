import os
import sys


def maybe_run_embedded_mcp_filesystem_stdio() -> None:
    """
    打包模式下的 MCPFilesystem 启动兜底：
    通过 serve.exe 自身直接拉起 mcp_filesystem，避免依赖 uv/run_server.py 外部文件。
    """
    flag = "--run-mcp-filesystem-stdio"
    if flag not in sys.argv:
        return

    idx = sys.argv.index(flag)
    allowed_dirs = [str(x).strip() for x in sys.argv[idx + 1 :] if str(x).strip()]
    if allowed_dirs:
        os.environ["MCP_ALLOWED_DIRS"] = os.pathsep.join(allowed_dirs)

    from mcp_filesystem.server import mcp

    mcp.run(transport="stdio")
    raise SystemExit(0)
