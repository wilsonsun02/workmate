"""Runtime Admin token bridge for MCP collab tools (stdio subprocess)."""

from __future__ import annotations

import os
from pathlib import Path


def collab_token_store_path() -> Path:
    """
    Stable token file path shared by serve.py and MCPFilesystem subprocess.

    Override parent dir with WORKMATE_COLLAB_TOKEN_DIR (directory only).
    """
    override_dir = os.environ.get("WORKMATE_COLLAB_TOKEN_DIR", "").strip()
    if override_dir:
        return Path(override_dir).expanduser() / "collab_admin_token"
    try:
        from workflow.config import BASE_DIR

        base = Path(BASE_DIR).expanduser()
    except Exception:
        base = Path.cwd()
    return base / "desktop_temp" / "collab_admin_token"


def read_collab_admin_token() -> str:
    path = collab_token_store_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def apply_collab_runtime_auth(admin_token: str | None) -> str:
    """
    Persist desktop Admin login token for MCP collab HTTP calls.

    Returns absolute path to the token file (empty string if cleared).
    """
    token = str(admin_token or "").strip()
    path = collab_token_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["WORKMATE_COLLAB_TOKEN_DIR"] = str(path.parent)

    if token:
        path.write_text(token, encoding="utf-8")
        os.environ["WORKMATE_ADMIN_BEARER_TOKEN"] = token
        return str(path.resolve())

    os.environ.pop("WORKMATE_ADMIN_BEARER_TOKEN", None)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    return ""
