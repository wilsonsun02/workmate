# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import site
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = Path(SPEC).resolve().parent
block_cipher = None

# 与 PyPI 包名冲突：contrib 的 hook-workflow.py 会对「同名」包 copy_metadata，本地 workflow 包会报错，故禁用该 hook
for _sp in site.getsitepackages():
    _bad = os.path.join(_sp, "_pyinstaller_hooks_contrib", "stdhooks", "hook-workflow.py")
    _bak = _bad + ".bak"
    if os.path.isfile(_bad) and not os.path.isfile(_bak):
        os.rename(_bad, _bak)
        break

# -------- desktop 分析 --------
desktop_datas = []
desktop_binaries = []
desktop_hiddenimports = []

tmp_ret = collect_all("PyQt6")
desktop_datas += tmp_ret[0]
desktop_binaries += tmp_ret[1]
desktop_hiddenimports += tmp_ret[2]
tmp_ret = collect_all("PyQt6-WebEngine")
desktop_datas += tmp_ret[0]
desktop_binaries += tmp_ret[1]
desktop_hiddenimports += tmp_ret[2]
desktop_datas += [(str(Path("desktop") / "ui"), "ui")]
_desktop_icon = Path("desktop") / "assets" / "app.ico"

desktop_a = Analysis(
    [str(PROJECT_ROOT / "desktop" / "webview_shell.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=desktop_binaries,
    datas=desktop_datas,
    hiddenimports=desktop_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
desktop_pyz = PYZ(desktop_a.pure, desktop_a.zipped_data, cipher=block_cipher)
desktop_exe_kwargs = dict(
    exclude_binaries=True,
    name="workmate-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if _desktop_icon.is_file():
    desktop_exe_kwargs["icon"] = str(_desktop_icon)

desktop_exe = EXE(
    desktop_pyz,
    desktop_a.scripts,
    [],
    **desktop_exe_kwargs,
)

# -------- serve 分析 --------
serve_datas: list = []
serve_binaries: list = []
serve_hiddenimports: list = []

# 关键：个人独立部署需要的“项目数据目录”必须随 bundle 一并带上，
# 否则 serve 运行时 BASE_DIR/config 下会缺失诸如 subagents.json 的文件。
# 其中 scheduled_tasks.json / task_executions.json / desktop_scheduler_feed.json
# 属于运行时文件，不随安装包分发。
_exclude_runtime_scheduler_files = {
    "scheduled_tasks.json",
    "task_executions.json",
    "desktop_scheduler_feed.json",
}
for _cfg in (PROJECT_ROOT / "config").glob("*"):
    if _cfg.is_file() and _cfg.name not in _exclude_runtime_scheduler_files:
        serve_datas.append((str(_cfg), "config"))
_env_file = PROJECT_ROOT / ".env"
if _env_file.is_file():
    # 按用户要求：把真实 .env 放到安装目录根，供 serve.exe 直接读取。
    serve_datas.append((str(_env_file), "."))

serve_datas += [
    (str(Path("prompt")), "prompt"),
]

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
        serve_datas += d
        serve_binaries += b
        serve_hiddenimports += h
    except Exception:
        pass

for pkg in ("workflow", "scheduler", "mcp_filesystem"):
    try:
        serve_hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

serve_hiddenimports += [
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

serve_a = Analysis(
    [str(PROJECT_ROOT / "serve.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=serve_binaries,
    datas=serve_datas,
    hiddenimports=serve_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
serve_pyz = PYZ(serve_a.pure, serve_a.zipped_data, cipher=block_cipher)
serve_exe = EXE(
    serve_pyz,
    serve_a.scripts,
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

# 单目录收集：两个 exe 共用一套 _internal
coll = COLLECT(
    desktop_exe,
    serve_exe,
    desktop_a.binaries,
    desktop_a.zipfiles,
    desktop_a.datas,
    serve_a.binaries,
    serve_a.zipfiles,
    serve_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="workmate-desktop",
)
