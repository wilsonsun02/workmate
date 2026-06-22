"""部署根目录解析：与 workflow.config 的 BASE_DIR 一致（打包后以 serve 入口处 environ 为准）。"""

from __future__ import annotations

import os


def app_base_dir() -> str:
    env = os.environ.get("BASE_DIR", "").strip()
    if env:
        return env
    pkg = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(pkg)


def get_project_root() -> str:
    """获取项目根目录，与 app_base_dir 相同"""
    return app_base_dir()
