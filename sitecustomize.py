from __future__ import annotations

import os
import sys
from pathlib import Path

from workflow.logging_setup import init_logging


def _guess_app_name() -> str:
    stem = Path(sys.argv[0]).stem.lower() if sys.argv else ""
    if "serve" in stem:
        return "serve"
    if "desktop" in stem or "webview_shell" in stem:
        return "desktop"
    return "workmate"


def _guess_base_dir() -> str:
    env_base = os.environ.get("BASE_DIR", "").strip()
    if env_base:
        return env_base
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return str(Path.cwd().resolve())


try:
    app_name = _guess_app_name()
    _env_log_level = os.environ.get("WORKMATE_LOG_LEVEL", "").strip().upper()
    if _env_log_level in {"DEBUG", "INFO", "ERROR"}:
        _log_level = _env_log_level
    else:
        _log_level = (
            "ERROR"
            if getattr(sys, "frozen", False) and app_name in {"serve", "workmate"}
            else "INFO"
        )
    init_logging(
        app_name,
        base_dir=_guess_base_dir(),
        level=_log_level,
    )
except Exception:
    # 保底：即便日志初始化失败，也不影响主进程继续启动。
    pass
