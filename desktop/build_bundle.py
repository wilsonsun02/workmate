from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path
import shutil
import json

from loguru import logger


def _run(cmd: list[str], cwd: Path) -> None:
    logger.info("> {}", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _sanitize_desktop_config(path: Path) -> None:
    if not path.is_file():
        return
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("failed to parse desktop config for sanitize: {} ({})", path, exc)
        return

    path_keys = (
        "workspace_root",
        "output_base_dir",
        "webengine_storage_root",
        "wechat_attachment_save_dir",
        "wechat_attachment_cache_file",
        "wechat_audio_cache_file",
    )
    changed = False
    for key in path_keys:
        if str(cfg.get(key, "")).strip():
            cfg[key] = ""
            changed = True
    if not changed:
        return

    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[OK] Sanitized runtime paths in {}", path)


def _collect_npx_packages(mcp_config_path: Path) -> list[str]:
    if not mcp_config_path.is_file():
        return []
    try:
        data = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("failed to parse mcp config: {} ({})", mcp_config_path, exc)
        return []
    if not isinstance(data, list):
        return []

    packages: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        sc = item.get("server_config")
        if not isinstance(sc, dict):
            continue
        if str(sc.get("transport", "")).strip().lower() != "stdio":
            continue
        cmd = str(sc.get("command", "")).strip().lower()
        if Path(cmd).name not in {"npx", "npx.exe"}:
            continue
        args = sc.get("args") or []
        if not isinstance(args, list):
            continue
        # npx 常见形态：["-y", "<pkg>", ...]
        pkg = ""
        for token in args:
            s = str(token).strip()
            if not s:
                continue
            if s.startswith("-"):
                continue
            pkg = s
            break
        if pkg and pkg not in seen:
            seen.add(pkg)
            packages.append(pkg)
    return packages


def _pkg_installed(desktop_dir: Path, package_name: str) -> bool:
    spec = str(package_name).strip()
    if not spec:
        return False
    # npm 包可能带版本号：
    # - unscoped: pkg@1.2.3
    # - scoped: @scope/pkg@1.2.3
    if spec.startswith("@"):
        raw_parts = [p for p in spec.split("/") if p]
        if len(raw_parts) < 2:
            return False
        scope = raw_parts[0]
        name = raw_parts[1].split("@", 1)[0]
        parts = [scope, name]
    else:
        parts = [spec.split("@", 1)[0]]
    if not parts:
        return False
    pkg_json = desktop_dir / "node_modules"
    for part in parts:
        pkg_json = pkg_json / part
    pkg_json = pkg_json / "package.json"
    return pkg_json.is_file()


def _resolve_npm_command() -> str:
    # 优先从 PATH 查找
    for name in ("npm", "npm.cmd", "npm.exe"):
        found = shutil.which(name)
        if found:
            return found
    # 常见 Windows 安装目录兜底
    for root in (
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
    ):
        if not root:
            continue
        candidate = Path(root) / "nodejs" / "npm.cmd"
        if candidate.is_file():
            return str(candidate)
    return ""


def _install_local_npx_packages(desktop_dir: Path) -> None:
    mcp_cfg = desktop_dir / "config" / "mcp_servers.json"
    packages = _collect_npx_packages(mcp_cfg)
    if not packages:
        logger.info("[OK] No npx MCP packages detected")
        return
    npm_cmd = _resolve_npm_command()
    if not npm_cmd:
        logger.error(
            "[MCP] npm not found, skip npx package preinstall. "
            "Please ensure Node.js is installed and npm is available in PATH."
        )
        return
    logger.info("[MCP] Installing {} npx packages locally...", len(packages))
    _run(
        [
            npm_cmd,
            "install",
            "--no-audit",
            "--no-fund",
            "--prefix",
            str(desktop_dir),
            *packages,
        ],
        cwd=desktop_dir,
    )
    logger.info(
        "[OK] Local npx packages installed into {}", desktop_dir / "node_modules"
    )

    installed = [pkg for pkg in packages if _pkg_installed(desktop_dir, pkg)]
    missing = [pkg for pkg in packages if pkg not in installed]
    logger.info(
        "[MCP] npx package preinstall check: installed={}/{}",
        len(installed),
        len(packages),
    )
    for pkg in installed:
        logger.info("[MCP]   ✓ {}", pkg)
    for pkg in missing:
        logger.error("[MCP]   ✗ {} (missing after install)", pkg)


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    dist_dir = project_root / "dist"
    desktop_dir = dist_dir / "workmate-desktop"

    # 一条命令完成：双 EXE 打包（共享 _internal）
    _run(
        [sys.executable, "-m", "PyInstaller", "-y", "workmate-bundle.spec"],
        cwd=project_root,
    )

    if not desktop_dir.is_dir():
        raise RuntimeError(f"desktop 产物不存在: {desktop_dir}")
    if not (desktop_dir / "serve.exe").is_file():
        raise RuntimeError(f"未找到 serve.exe: {desktop_dir / 'serve.exe'}")
    if not (desktop_dir / "workmate-desktop.exe").is_file():
        raise RuntimeError(
            f"未找到 workmate-desktop.exe: {desktop_dir / 'workmate-desktop.exe'}"
        )

    logger.info("[OK] 已生成共享依赖目录: {}", desktop_dir)
    logger.info("[OK] 包含: workmate-desktop.exe + serve.exe（共用一套 _internal）")

    # PyInstaller 的 COLLECT 多入口模式下，config/prompt 等“资源数据”可能被放进 _internal。
    # 你希望它们落在 exe 的平行目录（即 desktop_dir/config 等），这里做一次拷贝补齐。
    internal_dir = desktop_dir / "_internal"
    internal_env = internal_dir / ".env"
    root_env = desktop_dir / ".env"
    if internal_env.is_file():
        if not root_env.exists():
            shutil.copy2(internal_env, root_env)
            logger.info("[OK] Copied .env -> {}", root_env)
        try:
            internal_env.unlink()
            logger.info("[OK] Removed bundled .env from _internal (use install root)")
        except OSError as exc:
            logger.error("failed to remove _internal/.env: {}", exc)

    for name in ("config", "prompt", "skills", "template", "checkpoints"):
        src = internal_dir / name
        dst = desktop_dir / name
        if not src.exists():
            continue
        # 已存在则不覆盖，避免破坏用户手工修改
        if not dst.exists():
            shutil.copytree(src, dst)
            logger.info("[OK] Copied {} -> {}", name, dst)

    # 自动预装 mcp_servers.json 中所有 npx 依赖，减少目标机首次运行时拉包失败。
    _install_local_npx_packages(desktop_dir)

    # 调度运行时数据文件由客户端首次创建任务时自动生成，不随安装包分发。
    for cfg in (
        desktop_dir / "config" / "scheduled_tasks.json",
        desktop_dir / "config" / "task_executions.json",
        desktop_dir / "config" / "desktop_scheduler_feed.json",
        internal_dir / "config" / "scheduled_tasks.json",
        internal_dir / "config" / "task_executions.json",
        internal_dir / "config" / "desktop_scheduler_feed.json",
    ):
        if cfg.exists():
            cfg.unlink()
            logger.info("[OK] Removed runtime file from bundle: {}", cfg)

    # desktop_config.json 可能来自本机运行时，包含机器绝对路径；发布前统一清洗。
    _sanitize_desktop_config(desktop_dir / "config" / "desktop_config.json")
    _sanitize_desktop_config(internal_dir / "config" / "desktop_config.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
