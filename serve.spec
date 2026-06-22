# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 规格：将 serve.py 打成可在本机运行的 Windows 可执行文件。

用法（在项目根目录）:
  uv run pyinstaller serve.spec

产物:
  dist/serve/serve.exe  （onedir，推荐：启动快、依赖清晰）

部署: 将 dist/serve/ 整个目录复制到目标机，并在同目录放置与开发环境一致的项目资源：
  - .env（密钥与 BASE_DIR 等，可选；未设置 BASE_DIR 时默认同目录）
  - config/、prompt/、skills/、template/、checkpoints/ 等（按你实际使用的功能准备）

若仅复制单个 exe 而无上述目录，服务会因缺少配置或提示词文件而无法正常工作。
"""
from __future__ import annotations

import os
import site
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# PyInstaller 执行 spec 时会注入 SPEC（spec 文件绝对路径）
PROJECT_ROOT = Path(SPEC).resolve().parent

# 与 PyPI 包名冲突：contrib 的 hook-workflow.py 会对「同名」包 copy_metadata，本地 workflow 包会报错，故禁用该 hook
for _sp in site.getsitepackages():
    _bad = os.path.join(_sp, "_pyinstaller_hooks_contrib", "stdhooks", "hook-workflow.py")
    _bak = _bad + ".bak"
    if os.path.isfile(_bad) and not os.path.isfile(_bak):
        os.rename(_bad, _bak)
        break

block_cipher = None

datas: list = []
binaries: list = []
hiddenimports: list = []

# 将 config 下配置随 serve 打包（排除运行时动态文件）
_exclude_runtime_scheduler_files = {
    "scheduled_tasks.json",
    "task_executions.json",
    "desktop_scheduler_feed.json",
}
for _cfg in (PROJECT_ROOT / "config").glob("*"):
    if _cfg.is_file() and _cfg.name not in _exclude_runtime_scheduler_files:
        datas.append((str(_cfg), "config"))
_env_file = PROJECT_ROOT / ".env"
if _env_file.is_file():
    # 按用户要求：把真实 .env 放到产物根目录，便于开箱即用。
    datas.append((str(_env_file), "."))

# 将常用依赖的元数据、子模块一并打入，减少运行期缺模块错误
for pkg in (
    "uvicorn",
    "starlette",
    "fastapi",
    "pydantic",
    "pydantic_settings",
    "anyio",
    "httpx",
    "httpx_sse",
    "langchain_core",
    "langchain",
    "langgraph",
    "langserve",
    "langsmith",
    "deepagents",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_google_genai",
    "langchain_mcp_adapters",
    "langchain_runloop",
    "fastmcp",
    "mcp",
    "apscheduler",
    "mysql",
    "runloop_api_client",
    "sse_starlette",
    "tiktoken",
    "openai",
    "anthropic",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# 项目内包（动态导入较多时显式收集）
for pkg in ("workflow", "scheduler", "mcp_filesystem"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# uvicorn / Windows 常见隐式导入
hiddenimports += [
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "multipart",
    "dns",
    "dns.resolver",
    "mysql.connector",
    "mysql.connector.plugins",
    "mysql.connector.plugins.mysql_native_password",
    "aiosqlite",
    "sqlite3",
    "pydantic.deprecated.decorator",
]

a = Analysis(
    [str(PROJECT_ROOT / "serve.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="serve",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="serve",
)
