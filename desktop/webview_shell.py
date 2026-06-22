"""
运行（需安装 desktop 依赖组）:
  uv run --group desktop python -m desktop.webview_shell
或:
  python -m desktop.webview_shell

默认加载同目录下 ui/index.html；若第一个参数为 http(s) URL 则仍打开该远程页。
Agent API 基址：环境变量 WORKMATE_API_BASE，默认 http://127.0.0.1:8009。
Admin API 基址：环境变量 WORKMATE_ADMIN_API_BASE，默认 http://127.0.0.1:8010。
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
import time
import re
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from getpass import getuser
from pathlib import Path

import requests
import yaml

from PyQt6.QtCore import QObject, Qt, QUrl, QUrlQuery, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QContextMenuEvent, QDesktopServices, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import (
    QWebEngineNewWindowRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from loguru import logger

from workflow.config import get_admin_service_origin
from workflow.logging_setup import init_logging

DEFAULT_REMOTE_FALLBACK = "https://testinfo.richsupply.cn/"
DESKTOP_GLOBAL_LOG_LEVEL_KEY = "desktop_global_log_level"
DEFAULT_DESKTOP_CONFIG = {
    "api_base": "http://127.0.0.1:8009",
    "admin_api_base": get_admin_service_origin(),
    "workspace_root": "",
    "output_base_dir": "",
    "output_dir_template": "{output_base_dir}/{username}",
    "auto_create_workspace_root": True,
    "backend_auto_start": True,
    "backend_health_timeout_seconds": 12.0,
    DESKTOP_GLOBAL_LOG_LEVEL_KEY: "",
    "logs_dir": "",
    "webengine_storage_root": "",
    # 通用设置 - 模型与模板
    "image_provider": os.environ.get("IMAGE_PROVIDER", "wan"),
    "llm_provider": os.environ.get("LLM_PROVIDER", "deepseek"),
    "template_dir": os.environ.get("TEMPLATE_DIR", "template/report-template"),
    "image_template_dir": os.environ.get(
        "IMAGE_TEMPLATE_DIR", "template/image-template"
    ),
    # [deprecated] template_dir 和 image_template_dir 将在后续版本移除，
    # 改为从管理端模板管理系统动态获取。当前保留以兼容离线模式。
    # 通用设置 - 记忆与压缩
    "memory_compress_enabled": os.environ.get("MEMORY_COMPRESS_ENABLED", "true").lower()
    in ("true", "1", "yes", "on"),
    "memory_compress_threshold": int(
        os.environ.get("MEMORY_COMPRESS_THRESHOLD", "3000")
    ),
    "memory_short_term_tasks": int(os.environ.get("MEMORY_SHORT_TERM_TASKS", "5")),
    "memory_mid_term_tasks": int(os.environ.get("MEMORY_MID_TERM_TASKS", "25")),
    "memory_relevant_tasks_limit": int(
        os.environ.get("MEMORY_RELEVANT_TASKS_LIMIT", "2")
    ),
    "memory_enable_topic_search": os.environ.get(
        "MEMORY_ENABLE_TOPIC_SEARCH", "true"
    ).lower()
    in ("true", "1", "yes", "on"),
    "memory_search_candidate_limit": int(
        os.environ.get("MEMORY_SEARCH_CANDIDATE_LIMIT", "50")
    ),
    # 通用设置 - 沙箱与子代理
    "use_sandbox": os.environ.get("USE_SANDBOX", "false").lower()
    in ("true", "1", "yes", "on"),
    "enable_subagents": os.environ.get("ENABLE_SUBAGENTS", "false").lower()
    in ("true", "1", "yes", "on"),
    # 微信设置
    "wechat_attachment_save_dir": "",
    "wechat_attachment_cache_file": "",
    "wechat_audio_cache_file": "",
    "wechat_window_title": os.environ.get("WECHAT_WINDOW_TITLE", "微信"),
    "wechat_process_name": os.environ.get("WECHAT_PROCESS_NAME", "WeChat"),
    "wechat_ai_reply_prefix": os.environ.get(
        "WECHAT_AI_REPLY_PREFIX", "现在是Workmate与您对话"
    ),
    "mate_name": os.environ.get("MATE_NAME", ""),
    "company_name": os.environ.get("COMPANY_NAME", ""),
    "department_name": os.environ.get("DEPARTMENT_NAME", ""),
    "mate_title": os.environ.get("MATE_TITLE", ""),
}
OPTIONAL_DESKTOP_STRING_KEYS = (
    DESKTOP_GLOBAL_LOG_LEVEL_KEY,
    "admin_api_base",
    "logs_dir",
    "output_base_dir",
    "webengine_storage_root",
    "image_provider",
    "llm_provider",
    "template_dir",
    "image_template_dir",
    "wechat_attachment_save_dir",
    "wechat_attachment_cache_file",
    "wechat_audio_cache_file",
    "wechat_window_title",
    "wechat_process_name",
    "wechat_ai_reply_prefix",
    "mate_name",
    "company_name",
    "department_name",
    "mate_title",
)
# 布尔型桌面配置键（保存时需要特殊处理为 bool）
OPTIONAL_DESKTOP_BOOL_KEYS = (
    "memory_compress_enabled",
    "memory_enable_topic_search",
    "use_sandbox",
    "enable_subagents",
)
# 数值型桌面配置键（保存时需要转为 int）
OPTIONAL_DESKTOP_INT_KEYS = (
    "memory_compress_threshold",
    "memory_short_term_tasks",
    "memory_mid_term_tasks",
    "memory_relevant_tasks_limit",
    "memory_search_candidate_limit",
)
DEFAULT_API_BASE = os.environ.get(
    "WORKMATE_API_BASE", DEFAULT_DESKTOP_CONFIG["api_base"]
)
DEFAULT_ADMIN_API_BASE = os.environ.get(
    "WORKMATE_ADMIN_API_BASE", DEFAULT_DESKTOP_CONFIG["admin_api_base"]
)
# 供 _logs_dir / 异常提示读取当前桌面配置中的路径项
_paths_cfg: dict[str, object] = {}


def _note_paths_cfg(cfg: dict) -> None:
    _paths_cfg.clear()
    _paths_cfg.update(cfg)


def _apply_admin_api_base(cfg: dict) -> None:
    """Prefer WORKMATE_ADMIN_API_BASE from .env; keep desktop_config as cache."""
    env_val = os.environ.get("WORKMATE_ADMIN_API_BASE", "").strip().rstrip("/")
    if env_val:
        cfg["admin_api_base"] = env_val
        return
    cached = str(cfg.get("admin_api_base", "")).strip().rstrip("/")
    if cached:
        cfg["admin_api_base"] = cached
        return
    cfg["admin_api_base"] = get_admin_service_origin()


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def _frozen_install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _is_dir_writable(dir_path: Path) -> bool:
    """Best-effort check: creating a temp file in the directory must succeed."""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".wm_write_probe_",
            suffix=".tmp",
            dir=str(dir_path),
            delete=True,
        ):
            pass
        return True
    except OSError:
        return False


def _fallback_packaged_runtime_root() -> Path:
    """When the install directory is not writable, store mutable data here."""
    local_appdata = Path(os.environ.get("LOCALAPPDATA", "")).expanduser()
    if str(local_appdata).strip():
        return (local_appdata / "WorkmateDesktop").resolve()
    return (Path.home() / "AppData" / "Local" / "WorkmateDesktop").resolve()


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Per-user installs under %LOCALAPPDATA%\Programs\... are writable: keep all
        # runtime data next to the executable. Fall back only when the install dir is
        # not writable (e.g. machine-wide Program Files installs).
        exe_dir = _frozen_install_dir()
        if _is_dir_writable(exe_dir):
            return exe_dir
        return _fallback_packaged_runtime_root()
    # 开发/调试模式：把运行时生成的 config/logs/workspace 等统一到桌面端临时目录
    # 避免写入项目根目录造成污染。
    return (Path.cwd() / "desktop_temp").resolve()


def _safe_os_username() -> str:
    """用于路径片段的 OS 登录名（去掉 Windows 非法字符）。"""
    name = getuser()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name)
    name = name.strip(" .") or "user"
    return name


def _default_output_base_dir() -> Path:
    """与 exe 同级目录下的 workspace/，作为 Agent 输出根（其下为各业务用户名子目录）。"""
    return (_runtime_base_dir() / "workspace").resolve()


def _ensure_dir_with_fallback(primary: Path, fallback: Path, logger_ctx: str) -> Path:
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except (PermissionError, FileNotFoundError, OSError) as exc:
        logger.error(
            "{} create failed, fallback to {}: {}",
            logger_ctx,
            fallback,
            exc,
        )
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _apply_workspace_category_defaults(cfg: dict) -> None:
    """基于 output_base_dir 统一生成桌面端路径配置。"""
    wr = Path(str(cfg.get("workspace_root", "")).strip())
    # 统一按 output_base_dir 推导（单一来源），避免路径配置分裂。
    cfg["wechat_attachment_save_dir"] = str(
        wr / "{username}" / "wechat" / "attachments"
    )
    cfg["wechat_attachment_cache_file"] = str(
        wr / "{username}" / "wechat" / "config" / "wechat_attachment_cache.json"
    )
    cfg["wechat_audio_cache_file"] = str(
        wr / "{username}" / "wechat" / "config" / "wechat_audio_cache.json"
    )
    cfg["webengine_storage_root"] = str((wr / "webengine").resolve())


def _finalize_desktop_paths(cfg: dict) -> None:
    peer = _runtime_base_dir()
    ob = str(cfg.get("output_base_dir", "")).strip()
    if not ob:
        ob = str((peer / "workspace").resolve())
    cfg["output_base_dir"] = str(Path(ob).resolve())

    # 单一逻辑：workspace_root 始终跟随 output_base_dir。
    cfg["workspace_root"] = cfg["output_base_dir"]

    # 兼容旧版本：过去默认是 workspace/<OS用户名>/，用户希望改为 workspace/<登录用户名>/。
    # 这里识别旧默认形态：workspace/{safe_os_username}，迁移为 workspace（并将微信路径迁移为包含 {username} 模板）。
    peer_ws = Path(peer / "workspace").resolve()
    safe_os_user = _safe_os_username()
    old_default_prefix = str((peer_ws / safe_os_user).resolve())
    if str(cfg["workspace_root"]).startswith(old_default_prefix):
        cfg["workspace_root"] = str(peer_ws)

    def _maybe_replace_prefix(val: str, old_prefix: str, new_prefix: str) -> str:
        if not val:
            return val
        s = str(val)
        if s.startswith(old_prefix):
            return new_prefix + s[len(old_prefix) :]
        return val

    new_user_template_prefix = str(peer_ws / "{username}")
    # webengine 不做分目录（避免登录前创建 workspace/<os用户名>）
    cfg["webengine_storage_root"] = _maybe_replace_prefix(
        str(cfg.get("webengine_storage_root", "") or ""),
        old_default_prefix,
        str(peer_ws),
    )
    cfg["wechat_attachment_save_dir"] = _maybe_replace_prefix(
        str(cfg.get("wechat_attachment_save_dir", "") or ""),
        old_default_prefix,
        new_user_template_prefix,
    )
    cfg["wechat_attachment_cache_file"] = _maybe_replace_prefix(
        str(cfg.get("wechat_attachment_cache_file", "") or ""),
        old_default_prefix,
        new_user_template_prefix,
    )
    cfg["wechat_audio_cache_file"] = _maybe_replace_prefix(
        str(cfg.get("wechat_audio_cache_file", "") or ""),
        old_default_prefix,
        new_user_template_prefix,
    )

    tpl = str(cfg.get("output_dir_template", "") or "").strip()
    if not tpl:
        cfg["output_dir_template"] = "{output_base_dir}/{username}"
    else:
        cfg["output_dir_template"] = tpl
    cfg["auto_create_workspace_root"] = bool(
        cfg.get("auto_create_workspace_root", True)
    )

    _apply_workspace_category_defaults(cfg)

    for k in OPTIONAL_DESKTOP_STRING_KEYS:
        cfg[k] = str(cfg.get(k, "")).strip()
    _apply_admin_api_base(cfg)


def _runtime_config_path() -> Path:
    return _runtime_base_dir() / "config" / "desktop_config.json"


def _package_default_config_path() -> Path:
    return _package_dir() / "config" / "desktop_config.json"


def _read_json_config(path: Path) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _resolve_desktop_config() -> dict:
    cfg = dict(DEFAULT_DESKTOP_CONFIG)
    cfg.update(_read_json_config(_package_default_config_path()))
    runtime_path = _runtime_config_path()
    cfg.update(_read_json_config(runtime_path))
    if os.environ.get("WORKMATE_API_BASE"):
        cfg["api_base"] = os.environ["WORKMATE_API_BASE"]
    _finalize_desktop_paths(cfg)

    if not runtime_path.exists():
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_cfg = dict(cfg)
        runtime_path.write_text(
            json.dumps(runtime_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cfg


def _resolve_desktop_default_config() -> dict:
    """仅按系统默认生成配置，不读取运行时配置文件。"""
    cfg = dict(DEFAULT_DESKTOP_CONFIG)
    cfg.update(_read_json_config(_package_default_config_path()))
    if os.environ.get("WORKMATE_API_BASE"):
        cfg["api_base"] = os.environ["WORKMATE_API_BASE"]
    _finalize_desktop_paths(cfg)
    return cfg


def _normalize_runtime_config(raw: dict) -> dict:
    cfg = dict(DEFAULT_DESKTOP_CONFIG)
    cfg.update(raw or {})
    _finalize_desktop_paths(cfg)
    return cfg


def _persist_runtime_config(data: dict) -> dict:
    cfg = _normalize_runtime_config(data)
    if cfg.get("auto_create_workspace_root", True):
        wr = Path(str(cfg["workspace_root"]).strip()).expanduser()
        fallback = _default_output_base_dir()
        resolved = _ensure_dir_with_fallback(wr, fallback, "workspace_root").resolve()
        cfg["workspace_root"] = str(resolved)
        cfg["output_base_dir"] = str(resolved)
        _apply_workspace_category_defaults(cfg)
    runtime_path = _runtime_config_path()
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg


def _skills_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config" / "skills_config.json"
    return _package_dir().parent / "config" / "skills_config.json"


def _mcp_servers_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config" / "mcp_servers.json"
    return _package_dir().parent / "config" / "mcp_servers.json"


def _normalize_skills_config(raw: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    skills = data.get("skills")
    if isinstance(skills, dict):
        normalized: dict[str, dict[str, object]] = {}
        for name, value in skills.items():
            if isinstance(value, dict):
                normalized[str(name)] = {
                    "description": str(value.get("description", "") or ""),
                    "enabled": bool(value.get("enabled", True)),
                }
            else:
                normalized[str(name)] = {"description": "", "enabled": bool(value)}
        return {"skills": normalized}

    normalized = {}
    for name, value in data.items():
        if isinstance(value, dict):
            normalized[str(name)] = {
                "description": str(value.get("description", "") or ""),
                "enabled": bool(value.get("enabled", True)),
            }
        else:
            normalized[str(name)] = {"description": "", "enabled": bool(value)}
    return {"skills": normalized}


def _read_skills_config() -> dict:
    path = _skills_config_path()
    raw = _read_json_config(path)
    return _normalize_skills_config(raw)


def _persist_skills_config(raw: dict) -> dict:
    normalized = _normalize_skills_config(raw)
    path = _skills_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return normalized


def _skills_install_root() -> Path:
    """Align with packaged layout: skills next to exe / repo root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "skills"
    return _package_dir().parent / "skills"


def _parse_skill_dir_meta(skill_dir: Path) -> tuple[str, str]:
    skill_name = skill_dir.name
    version = "0.0.1"
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return skill_name, version
    try:
        content = skill_md.read_text(encoding="utf-8")
        if content.startswith("---"):
            end_idx = content.find("---", 3)
            if end_idx != -1:
                metadata = yaml.safe_load(content[3:end_idx]) or {}
                skill_name = str(metadata.get("name") or skill_name)
                version = str(metadata.get("version") or version)
    except Exception:
        pass
    return skill_name, version


def _safe_extract_skill_zip(zip_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    abs_target = str(extract_dir.resolve())
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_name = member.filename.replace("\\", "/")
            if member_name.startswith("/") or ".." in member_name.split("/"):
                raise ValueError("Invalid ZIP path")
            member_target = str((extract_dir / member_name).resolve())
            if not member_target.startswith(abs_target):
                raise ValueError("Invalid ZIP path")
        zf.extractall(extract_dir)


def _decode_collab_display_filename(raw: str) -> str:
    name = (raw or "").strip() or "attachment"
    if "%" not in name:
        return name
    try:
        decoded = urllib.parse.unquote(name)
        return decoded.strip() or name
    except Exception:
        return name


def _download_skill_bytes(url: str, dest: Path, bearer_token: str = "") -> None:
    headers: dict[str, str] = {}
    token = (bearer_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(
        url, headers=headers, timeout=120, stream=True, allow_redirects=True
    ) as resp:
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(8192):
                if chunk:
                    out.write(chunk)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _install_skill_package_impl(payload: dict, log) -> dict:
    """
    Download and extract a skill zip next to the desktop install / repo root.
    payload: skill_name, version, download_url (optional), sha256 (optional),
             admin_api_base + bearer_token when download_url is empty (uses download-latest).
    """
    skill_name = str(payload.get("skill_name") or "").strip()
    target_version = str(payload.get("version") or "").strip()
    download_url = str(payload.get("download_url") or "").strip()
    expected_sha = str(payload.get("sha256") or "").strip()
    admin_base = str(payload.get("admin_api_base") or "").rstrip("/")
    bearer = str(payload.get("bearer_token") or "").strip()
    if not skill_name or not target_version:
        return {"ok": False, "message": "missing skill_name or version"}
    skills_root = _skills_install_root()
    skills_root.mkdir(parents=True, exist_ok=True)
    if not download_url:
        if not admin_base or not bearer:
            return {"ok": False, "message": "missing download_url or admin auth"}
        q = urllib.parse.quote(skill_name, safe="")
        download_url = f"{admin_base}/api/admin/skills/{q}/download-latest"
    with tempfile.TemporaryDirectory(dir=str(skills_root)) as td:
        td_path = Path(td)
        zip_path = td_path / "skill.zip"
        try:
            _download_skill_bytes(download_url, zip_path, bearer)
        except Exception as e:
            log.exception("skill download failed")
            return {"ok": False, "message": f"download failed: {e}"}
        if expected_sha:
            actual = _sha256_file(zip_path)
            if actual.lower() != expected_sha.lower():
                return {"ok": False, "message": "sha256 mismatch"}
        extract_dir = td_path / "extracted"
        try:
            _safe_extract_skill_zip(zip_path, extract_dir)
        except Exception as e:
            return {"ok": False, "message": f"invalid zip: {e}"}
        items = [p for p in extract_dir.iterdir()]
        skill_root = extract_dir
        if len(items) == 1 and items[0].is_dir():
            skill_root = items[0]
        parsed_name, parsed_ver = _parse_skill_dir_meta(skill_root)
        if parsed_name != skill_name:
            return {
                "ok": False,
                "message": f"skill name mismatch: expected {skill_name}, got {parsed_name}",
            }
        if str(parsed_ver) != str(target_version):
            return {
                "ok": False,
                "message": f"version mismatch: expected {target_version}, got {parsed_ver}",
            }
        target_dir = skills_root / skill_name
        backup_dir = td_path / "backup_prev"
        prev_backup: Path | None = None
        if target_dir.exists():
            prev_backup = (
                skills_root
                / f"{skill_name}_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            shutil.move(str(target_dir), str(prev_backup))
        try:
            shutil.move(str(skill_root), str(target_dir))
        except Exception as e:
            if prev_backup and prev_backup.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                shutil.move(str(prev_backup), str(target_dir))
            log.exception("skill install move failed")
            return {"ok": False, "message": str(e)}
        if prev_backup and prev_backup.exists():
            shutil.rmtree(prev_backup, ignore_errors=True)
    log.info("Installed skill {} @ {}", skill_name, target_version)
    return {
        "ok": True,
        "skill_name": skill_name,
        "version": target_version,
        "path": str(target_dir),
    }


def _collect_local_skill_inventory(log) -> list[dict]:
    root = _skills_install_root()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith("_"):
            continue
        name, ver = _parse_skill_dir_meta(item)
        out.append(
            {
                "name": name,
                "version": ver,
                "installed_at": datetime.now().isoformat(),
            }
        )
    return out


def _normalize_mcp_servers_config(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["server_name"] = str(item.get("server_name", "") or "").strip()
        row["server_description"] = str(item.get("server_description", "") or "")
        row["is_load"] = bool(item.get("is_load", False))
        normalized.append(row)
    return normalized


def _read_mcp_servers_config() -> list[dict]:
    path = _mcp_servers_config_path()
    raw: object = []
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = []
    return _normalize_mcp_servers_config(raw)


def _persist_mcp_servers_config(raw: object) -> list[dict]:
    normalized = _normalize_mcp_servers_config(raw)
    path = _mcp_servers_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return normalized


def _logs_dir() -> Path:
    raw = str(_paths_cfg.get("logs_dir", "")).strip()
    if raw:
        path = Path(raw).expanduser().resolve()
    else:
        path = _runtime_base_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_desktop_log_level() -> str:
    default_level = "ERROR" if getattr(sys, "frozen", False) else "INFO"
    raw_level = str(_paths_cfg.get(DESKTOP_GLOBAL_LOG_LEVEL_KEY, "")).strip().upper()
    if raw_level in {"DEBUG", "INFO", "ERROR"}:
        return raw_level
    return default_level


def _setup_logging():
    desktop_log_level = _resolve_desktop_log_level()
    os.environ["WORKMATE_LOG_LEVEL"] = desktop_log_level
    log_file = init_logging(
        "desktop",
        base_dir=_runtime_base_dir(),
        level=desktop_log_level,
    )
    logger.info(
        "desktop shell started (mode={}, log_level={})",
        "frozen" if getattr(sys, "frozen", False) else "dev",
        desktop_log_level,
    )
    logger.info("desktop log file: {}", log_file)
    return logger


def _install_exception_hooks(logger) -> None:
    default_excepthook = sys.excepthook

    def _show_log_hint_dialog() -> None:
        app = QApplication.instance()
        if app is None:
            return
        log_path = (_logs_dir() / "desktop.log").resolve()
        QMessageBox.critical(
            None,
            "Workmate 发生错误",
            f"程序发生未处理异常，请查看日志：\n{log_path}",
        )

    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        logger.error(
            "uncaught exception:\n{}",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip(),
        )
        try:
            _show_log_hint_dialog()
        except Exception:
            logger.exception("failed to show crash dialog")
        default_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _handle_exception

    if hasattr(threading, "excepthook"):
        default_thread_hook = threading.excepthook

        def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
            logger.error(
                "uncaught thread exception ({}):\n{}",
                args.thread.name if args.thread else "unknown",
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ).rstrip(),
            )
            default_thread_hook(args)

        threading.excepthook = _handle_thread_exception


def _resolve_ui_index() -> Path:
    """开发：desktop/ui/index.html；打包：_MEIPASS/ui 或 exe 同目录/ui。"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "ui" / "index.html")
        candidates.append(Path(sys.executable).resolve().parent / "ui" / "index.html")
    candidates.append(_package_dir() / "ui" / "index.html")
    for p in candidates:
        if p.is_file():
            return p
    return _package_dir() / "ui" / "index.html"


def _resolve_window_icon_candidates() -> list[Path]:
    """桌面窗口图标搜索顺序：安装目录 assets、包内 assets、UI assets。"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "assets" / "app.ico",
                exe_dir / "ui" / "assets" / "app.ico",
                exe_dir / "ui" / "assets" / "logo.ico",
                exe_dir / "ui" / "assets" / "logo.svg",
            ]
        )
    candidates.extend(
        [
            _package_dir() / "assets" / "app.ico",
            _package_dir() / "ui" / "assets" / "app.ico",
            _package_dir() / "ui" / "assets" / "logo.ico",
            _package_dir() / "ui" / "assets" / "logo.svg",
        ]
    )
    return candidates


def _local_app_url(
    api_base: str | None = None, desktop_config: dict | None = None
) -> QUrl:
    config = desktop_config or {}
    base = (api_base or str(config.get("api_base") or DEFAULT_API_BASE)).rstrip("/")
    admin_base = str(config.get("admin_api_base") or DEFAULT_ADMIN_API_BASE).rstrip("/")
    path = _resolve_ui_index()
    url = QUrl.fromLocalFile(str(path.resolve()))
    q = QUrlQuery()
    q.addQueryItem("api_base", base)
    q.addQueryItem("admin_api_base", admin_base)
    q.addQueryItem(
        "desktop_config",
        json.dumps(config, ensure_ascii=False),
    )
    q.addQueryItem("os_username", getuser())
    url.setQuery(q)
    return url


def _is_local_api_base(api_base: str) -> bool:
    parsed = urllib.parse.urlparse(api_base)
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _resolve_backend_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe_name = "serve.exe" if os.name == "nt" else "serve"
    candidates: list[Path] = []
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "serve" / exe_name)
    candidates.append(exe_dir / exe_name)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "serve" / exe_name)
    for p in candidates:
        if p.is_file():
            return p
    return None


def _resolve_dev_serve_py() -> Path | None:
    """开发态：仓库根目录下的 serve.py。"""
    p = _package_dir().parent / "serve.py"
    return p if p.is_file() else None


def _backend_child_environment(desktop_config: dict | None) -> dict[str, str]:
    """与打包场景一致：注入 OUTPUT_BASE_DIR 与 WECHAT_*，供子进程 serve 使用。"""
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env.setdefault("WORKMATE_PRELOAD_ON_STARTUP", "1")
    if getattr(sys, "frozen", False):
        child_env.setdefault("BASE_DIR", str(Path(sys.executable).resolve().parent))
    dc = desktop_config or {}
    ob = str(dc.get("output_base_dir", "")).strip()
    if not ob:
        ob = str(_default_output_base_dir())
    child_env["OUTPUT_BASE_DIR"] = str(Path(ob).resolve())
    _wechat_env_map = (
        ("wechat_attachment_save_dir", "WECHAT_ATTACHMENT_SAVE_DIR"),
        ("wechat_attachment_cache_file", "WECHAT_ATTACHMENT_CACHE_FILE"),
        ("wechat_audio_cache_file", "WECHAT_AUDIO_CACHE_FILE"),
        ("wechat_window_title", "WECHAT_WINDOW_TITLE"),
        ("wechat_process_name", "WECHAT_PROCESS_NAME"),
        ("wechat_ai_reply_prefix", "WECHAT_AI_REPLY_PREFIX"),
    )
    for cfg_key, env_key in _wechat_env_map:
        val = str(dc.get(cfg_key, "")).strip()
        if val:
            child_env[env_key] = val
    # 通用设置 - 模型与模板环境变量映射
    _general_env_map = (
        ("image_provider", "IMAGE_PROVIDER"),
        ("llm_provider", "LLM_PROVIDER"),
        ("template_dir", "TEMPLATE_DIR"),
        ("image_template_dir", "IMAGE_TEMPLATE_DIR"),
    )
    for cfg_key, env_key in _general_env_map:
        val = str(dc.get(cfg_key, "")).strip()
        if val:
            child_env[env_key] = val
    # 通用设置 - 布尔型环境变量映射
    _general_bool_env_map = (
        ("memory_compress_enabled", "MEMORY_COMPRESS_ENABLED"),
        ("memory_enable_topic_search", "MEMORY_ENABLE_TOPIC_SEARCH"),
        ("use_sandbox", "USE_SANDBOX"),
        ("enable_subagents", "ENABLE_SUBAGENTS"),
    )
    for cfg_key, env_key in _general_bool_env_map:
        child_env[env_key] = "true" if dc.get(cfg_key, False) else "false"
    # 通用设置 - 数值型环境变量映射
    _general_int_env_map = (
        ("memory_compress_threshold", "MEMORY_COMPRESS_THRESHOLD"),
        ("memory_short_term_tasks", "MEMORY_SHORT_TERM_TASKS"),
        ("memory_mid_term_tasks", "MEMORY_MID_TERM_TASKS"),
        ("memory_relevant_tasks_limit", "MEMORY_RELEVANT_TASKS_LIMIT"),
        ("memory_search_candidate_limit", "MEMORY_SEARCH_CANDIDATE_LIMIT"),
    )
    for cfg_key, env_key in _general_int_env_map:
        try:
            child_env[env_key] = str(int(dc.get(cfg_key, 0)))
        except (ValueError, TypeError):
            child_env[env_key] = str(DEFAULT_DESKTOP_CONFIG.get(cfg_key, 0))
    child_env["WORKMATE_LOG_LEVEL"] = _resolve_desktop_log_level()
    admin_base = (
        str(dc.get("admin_api_base") or DEFAULT_ADMIN_API_BASE).strip().rstrip("/")
    )
    if admin_base:
        child_env["WORKMATE_ADMIN_API_BASE"] = admin_base
    return child_env


def _wait_backend_ready(api_base: str, timeout_s: float = 12.0) -> bool:
    import time

    health_url = f"{api_base.rstrip('/')}/agent/health"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.35)
    return False


def _sync_runtime_config(api_base: str, desktop_config: dict, logger) -> None:
    """
    后端已在运行时，同步桌面配置到后端运行时。
    这样手动启动的 serve 也能与桌面配置立即对齐。
    """
    if not _is_local_api_base(api_base):
        return
    dc = desktop_config or {}
    payload = json.dumps(
        {
            "output_base_dir": str(
                Path(str(dc.get("output_base_dir", "")).strip()).resolve()
            )
            if str(dc.get("output_base_dir", "")).strip()
            else "",
            "wechat_attachment_save_dir": str(
                dc.get("wechat_attachment_save_dir", "")
            ).strip(),
            "wechat_attachment_cache_file": str(
                dc.get("wechat_attachment_cache_file", "")
            ).strip(),
            "wechat_audio_cache_file": str(
                dc.get("wechat_audio_cache_file", "")
            ).strip(),
            "wechat_window_title": str(dc.get("wechat_window_title", "")).strip(),
            "wechat_process_name": str(dc.get("wechat_process_name", "")).strip(),
            "wechat_ai_reply_prefix": str(dc.get("wechat_ai_reply_prefix", "")).strip(),
            "admin_api_base": str(dc.get("admin_api_base") or DEFAULT_ADMIN_API_BASE)
            .strip()
            .rstrip("/"),
            # 通用设置 - 模型与模板
            "image_provider": str(dc.get("image_provider", "")).strip(),
            "llm_provider": str(dc.get("llm_provider", "")).strip(),
            "template_dir": str(dc.get("template_dir", "")).strip(),
            "image_template_dir": str(dc.get("image_template_dir", "")).strip(),
            # 通用设置 - 布尔型
            "memory_compress_enabled": bool(dc.get("memory_compress_enabled", False)),
            "memory_enable_topic_search": bool(
                dc.get("memory_enable_topic_search", False)
            ),
            "use_sandbox": bool(dc.get("use_sandbox", False)),
            "enable_subagents": bool(dc.get("enable_subagents", False)),
            # 通用设置 - 数值型
            "memory_compress_threshold": int(dc.get("memory_compress_threshold", 3000)),
            "memory_short_term_tasks": int(dc.get("memory_short_term_tasks", 5)),
            "memory_mid_term_tasks": int(dc.get("memory_mid_term_tasks", 25)),
            "memory_relevant_tasks_limit": int(
                dc.get("memory_relevant_tasks_limit", 2)
            ),
            "memory_search_candidate_limit": int(
                dc.get("memory_search_candidate_limit", 50)
            ),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/desktop/runtime_config",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5):
            logger.info("synced runtime desktop_config to backend")
    except Exception as exc:
        logger.info("sync runtime desktop_config failed: {}", exc)


def _check_mcp_runtime_and_notify(api_base: str, logger) -> None:
    """
    读取后端 MCP 运行时依赖自检结果：
    - 记录到 desktop.log
    - 缺失依赖时给出桌面端弹窗提示
    """
    if not _is_local_api_base(api_base):
        return
    try:
        url = f"{api_base.rstrip('/')}/api/desktop/mcp_runtime_check"
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        check = payload.get("check") if isinstance(payload, dict) else None
        if not isinstance(check, dict):
            return
        summary = str(check.get("summary", "")).strip()
        if summary:
            logger.info("mcp runtime self-check: {}", summary)
        if bool(check.get("ok", True)):
            return
        missing = check.get("missing_commands", [])
        lines: list[str] = []
        if isinstance(missing, list):
            for item in missing:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {item.get('server_name', '')}: command={item.get('command', '')}"
                )
        detail = "\n".join(lines) if lines else "请查看 serve.log 获取详情。"
        raw_missing_count = check.get("missing_count")
        if isinstance(raw_missing_count, int) and raw_missing_count >= 0:
            n_missing = raw_missing_count
        else:
            n_missing = len(lines)
        count_line = f"共 {n_missing} 项 command 不可用。\n\n" if n_missing else ""
        QMessageBox.warning(
            None,
            "MCP 依赖检查告警",
            "检测到部分 MCP 依赖缺失，相关工具可能不可用：\n"
            f"{detail}\n"
            f"{count_line}"
            "请安装对应命令后重启（例如 Node.js/npx、uv/uvx）。",
        )
    except Exception as exc:
        logger.info("read mcp runtime self-check failed: {}", exc)


def _wait_mcp_preload(api_base: str, logger, timeout_s: float = 30.0) -> None:
    """
    等待后端 MCP 连接预热完成。
    后端启动时会并行建立所有 MCP 服务的 session 并缓存工具列表，
    此函数轮询预热状态接口，直到完成或超时。
    预热完成后，后续任务运行时无需再等待 MCP 握手。
    """
    if not _is_local_api_base(api_base):
        return
    import time

    url = f"{api_base.rstrip('/')}/api/desktop/mcp_preload_status"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            preload = payload.get("preload") if isinstance(payload, dict) else None
            if isinstance(preload, dict) and preload.get("done"):
                ok = preload.get("ok", False)
                message = preload.get("message", "")
                tools_count = preload.get("tools_count", 0)
                failed_servers = preload.get("failed_servers", [])
                if ok:
                    logger.info("MCP 预热完成: {} (工具数: {})", message, tools_count)
                else:
                    logger.info("MCP 预热部分失败: {}", message)
                    if failed_servers:
                        failed_names = [
                            s.get("server_name", "") if isinstance(s, dict) else str(s)
                            for s in failed_servers
                        ]
                        logger.info("失败的服务: {}", ", ".join(failed_names))
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    logger.info("等待 MCP 预热超时（{}s），后续任务将按需连接", timeout_s)


class ManagedBackend:
    def __init__(self, api_base: str, logger) -> None:
        self.api_base = api_base
        self.logger = logger
        self.process: subprocess.Popen | None = None
        self._started_by_shell = False

    def ensure_started(self, desktop_config: dict | None = None) -> None:
        if not _is_local_api_base(self.api_base):
            return
        if _wait_backend_ready(self.api_base, timeout_s=0.2):
            return

        child_env = _backend_child_environment(desktop_config)
        frozen = getattr(sys, "frozen", False)
        if frozen:
            backend_exe = _resolve_backend_executable()
            if not backend_exe:
                return
            cmd: list[str] = [str(backend_exe)]
            cwd = str(backend_exe.parent)
        else:
            serve_py = _resolve_dev_serve_py()
            if not serve_py:
                self.logger.info(
                    "dev backend: serve.py not found, skip auto-start ({})",
                    _package_dir().parent / "serve.py",
                )
                return
            cmd = [str(sys.executable), str(serve_py)]
            cwd = str(serve_py.parent)

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
                env=child_env,
            )
            self._started_by_shell = True
            self.logger.info("backend started: {}", " ".join(cmd))
            self.logger.info("backend cwd: {}", cwd)
        except Exception:
            self.logger.exception("failed to start backend")
            self.process = None
            self._started_by_shell = False

    def stop(self) -> None:
        if not self._started_by_shell:
            return
        if not self.process or self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            self.logger.exception("backend terminate failed, trying kill")
            try:
                self.process.kill()
            except Exception:
                self.logger.exception("backend kill failed")


def _is_remote_url(arg: str) -> bool:
    lowered = arg.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _singleton_server_name() -> str:
    """
    QLocalServer 名称：按安装目录区分，避免不同拷贝互相抢占；
    开发态按仓库根路径区分。
    """
    if getattr(sys, "frozen", False):
        key = str(Path(sys.executable).resolve()).lower()
    else:
        key = str(_package_dir().parent.resolve()).lower()
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"workmate_desktop_{digest}"


def _multi_instance_allowed() -> bool:
    return os.environ.get("WORKMATE_DESKTOP_MULTI_INSTANCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bring_main_window_forward(window: QMainWindow) -> None:
    state = window.windowState()
    if state & Qt.WindowState.WindowMinimized:
        window.setWindowState(state & ~Qt.WindowState.WindowMinimized)
    window.raise_()
    window.activateWindow()


def _try_notify_running_instance(logger) -> bool:
    """
    若已有实例在监听，则唤醒其主窗口并返回 True（当前进程应退出）。
    须在 QApplication 已创建后调用（避免单独 QCoreApplication 阻塞后续初始化）。
    """
    if _multi_instance_allowed():
        return False
    name = _singleton_server_name()
    sock = QLocalSocket()
    connected = False
    for _ in range(6):
        sock.connectToServer(name)
        if sock.waitForConnected(350):
            connected = True
            break
        sock.abort()
        time.sleep(0.06)
    if not connected:
        return False
    try:
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(800)
    finally:
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(300)
    logger.info("another desktop instance is running; activated it and exiting")
    return True


def _attach_singleton_server(window: QMainWindow, logger) -> QLocalServer | None:
    """主实例：监听同名管道，收到连接时把主窗口提到前台。"""
    if _multi_instance_allowed():
        return None
    name = _singleton_server_name()
    server = QLocalServer(window)

    def _on_activate_request() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def _finish() -> None:
            try:
                sock.disconnectFromServer()
            except Exception:
                pass
            sock.deleteLater()

        try:
            _bring_main_window_forward(window)
        except Exception:
            logger.exception("singleton activate handler failed")
        finally:
            _finish()

    server.newConnection.connect(_on_activate_request)

    if not server.listen(name):
        QLocalServer.removeServer(name)
        if not server.listen(name):
            logger.error(
                "single-instance listen failed: {} ({})",
                server.errorString(),
                name,
            )
            return None

    def _cleanup() -> None:
        server.close()
        QLocalServer.removeServer(name)

    QApplication.instance().aboutToQuit.connect(_cleanup)
    logger.info("single-instance server listening ({})", name)
    return server


def _configure_webengine(
    view: QWebEngineView, desktop_config: dict | None = None
) -> None:
    dc = desktop_config or {}
    raw = str(dc.get("webengine_storage_root", "")).strip()
    if raw:
        storage_root = Path(raw).expanduser().resolve()
    else:
        storage_root = Path.home() / ".cache" / "workmate-desktop" / "webengine"
    fallback_root = _default_output_base_dir() / "webengine"
    storage_root = _ensure_dir_with_fallback(
        storage_root, fallback_root, "webengine_storage_root"
    ).resolve()
    if isinstance(desktop_config, dict):
        desktop_config["webengine_storage_root"] = str(storage_root)
    profile = QWebEngineProfile.defaultProfile()
    profile.setPersistentStoragePath(str(storage_root))
    profile.setCachePath(str(storage_root / "cache"))

    settings = view.settings()
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
    )
    # 允许本地页面跳转到本地 file:// 资源（用于点击聊天消息中的保存位置路径）
    try:
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
    except Exception:
        pass
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)


class WorkmateWebEnginePage(QWebEnginePage):
    """
    本地 file:// 嵌入 UI 时：拦截主框架与新窗口中对 http(s) 的导航，改为系统默认浏览器打开，
    避免聊天链接或脚本把整窗带到外部网页。
    """

    def __init__(
        self,
        profile: QWebEngineProfile,
        parent,
        logger,
        open_http_in_system_browser: bool,
    ) -> None:
        super().__init__(profile, parent)
        self._logger = logger
        self._open_http_in_system_browser = open_http_in_system_browser
        if open_http_in_system_browser:
            self.newWindowRequested.connect(self._on_new_window_requested)

    def _on_new_window_requested(self, request: QWebEngineNewWindowRequest) -> None:
        try:
            url = request.requestedUrl()
            if url.scheme().lower() in {"http", "https"}:
                QDesktopServices.openUrl(url)
        except Exception:
            self._logger.exception("newWindowRequested handler failed")

    def acceptNavigationRequest(
        self,
        url: QUrl,
        nav_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        if self._open_http_in_system_browser and is_main_frame:
            scheme = url.scheme().lower()
            if scheme in {"http", "https"}:
                try:
                    QDesktopServices.openUrl(url)
                except Exception:
                    self._logger.exception(
                        "acceptNavigationRequest openUrl failed url={}", url
                    )
                return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class WorkmateWebEngineView(QWebEngineView):
    """嵌套 HTML 页面时关闭 Chromium 默认右键菜单，避免与桌面应用不一致。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        event.accept()


class WebShellWindow(QMainWindow):
    def __init__(self, start_url: QUrl, desktop_config: dict, logger) -> None:
        super().__init__()
        self.setWindowTitle("Workmate")
        self._apply_window_icon()
        self.resize(1280, 800)
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self._desktop_config = dict(desktop_config)
        self._logger = logger

        self._view = WorkmateWebEngineView(self)
        embed_local_file_ui = (
            start_url.isLocalFile() or start_url.scheme().lower() == "file"
        )
        page = WorkmateWebEnginePage(
            QWebEngineProfile.defaultProfile(),
            self._view,
            logger,
            open_http_in_system_browser=embed_local_file_ui,
        )
        self._view.setPage(page)
        _configure_webengine(self._view, self._desktop_config)
        self._bridge = DesktopConfigBridge(self)
        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("desktopBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self.setCentralWidget(self._view)
        self._view.setUrl(start_url)

    def _apply_window_icon(self) -> None:
        for icon_path in _resolve_window_icon_candidates():
            try:
                if not icon_path.exists():
                    continue
                icon = QIcon(str(icon_path))
                if icon.isNull():
                    continue
                self.setWindowIcon(icon)
                break
            except Exception:
                continue

    def closeEvent(self, event: QCloseEvent) -> None:
        reply = QMessageBox.question(
            self,
            "退出确认",
            "确定要关闭 Workmate 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._disconnect_wxwork_agent()
            event.accept()
        else:
            event.ignore()

    def _disconnect_wxwork_agent(self) -> None:
        """通知后端断开企微长连接代理进程；后端不可达时本地兜底杀进程"""
        disconnected = False
        try:
            api_base = str(
                self._desktop_config.get("api_base", "http://127.0.0.1:8009")
            ).rstrip("/")
            url = f"{api_base}/api/desktop/wxwork_disconnect"
            req = urllib.request.Request(url, method="POST")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=5)
            disconnected = True
            self._logger.info("已通知后端断开企微长连接")
        except Exception as api_err:
            self._logger.info("后端不可达，尝试本地终止企微进程: {}", api_err)

        # 后端不可达时的兜底：本地 PowerShell/pkill 清理
        if not disconnected:
            try:
                if os.name == "nt":
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                            "Where-Object { $_.CommandLine -match 'wxwork_agent' } | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
                        ],
                        capture_output=True,
                        timeout=15,
                    )
                else:
                    subprocess.run(
                        ["pkill", "-f", "wxwork_agent.py"],
                        capture_output=True,
                        timeout=10,
                    )
                self._logger.info("已本地终止企微长连接进程")
            except Exception as local_err:
                self._logger.info("本地终止企微进程失败: {}", local_err)


def _reveal_local_path_in_file_manager(path: Path, logger) -> bool:
    """
    Open the OS file manager for *path*.
    Existing files are highlighted when the platform supports it (Windows/macOS).
    """
    p = path.expanduser()
    try:
        p = p.resolve(strict=False)
    except (OSError, ValueError):
        p = path.expanduser()

    if p.exists() and p.is_file():
        if sys.platform == "win32":
            try:
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(str(p))],
                    close_fds=True,
                )
                return True
            except Exception:
                logger.exception("explorer /select failed path={}", p)
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", "-R", str(p)], close_fds=True)
                return True
            except Exception:
                logger.exception("open -R failed path={}", p)
        parent = p.parent
        if parent.exists():
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
        return False

    if p.exists() and p.is_dir():
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    folder = p.parent if p.suffix else p
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    if folder.exists() and folder.is_dir():
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    return False


class DesktopConfigBridge(QObject):
    def __init__(self, window: WebShellWindow) -> None:
        super().__init__()
        self._window = window

    @pyqtSlot(result=str)
    def get_desktop_config(self) -> str:
        return json.dumps(self._window._desktop_config, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def save_desktop_config(self, payload: str) -> str:
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("配置必须是对象")
            merged = dict(self._window._desktop_config)
            merged["workspace_root"] = str(data.get("workspace_root", "")).strip()
            merged["output_dir_template"] = str(
                data.get("output_dir_template", "{output_base_dir}/{username}")
            ).strip()
            merged["auto_create_workspace_root"] = bool(
                data.get("auto_create_workspace_root", True)
            )
            for k in OPTIONAL_DESKTOP_STRING_KEYS:
                if k in data:
                    merged[k] = str(data.get(k, "")).strip()
            for k in OPTIONAL_DESKTOP_BOOL_KEYS:
                if k in data:
                    merged[k] = bool(data.get(k, False))
            for k in OPTIONAL_DESKTOP_INT_KEYS:
                if k in data:
                    try:
                        merged[k] = int(data.get(k, 0))
                    except (ValueError, TypeError):
                        merged[k] = DEFAULT_DESKTOP_CONFIG.get(k, 0)
            persisted = _persist_runtime_config(merged)
            self._window._desktop_config = persisted
            _note_paths_cfg(persisted)
            _sync_runtime_config(
                str(persisted.get("api_base") or DEFAULT_API_BASE),
                persisted,
                self._window._logger,
            )
            return json.dumps({"ok": True, "config": persisted}, ensure_ascii=False)
        except Exception as exc:
            self._window._logger.exception("save_desktop_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def reset_desktop_config(self) -> str:
        try:
            cfg = _resolve_desktop_default_config()
            persisted = _persist_runtime_config(cfg)
            self._window._desktop_config = persisted
            _note_paths_cfg(persisted)
            _sync_runtime_config(
                str(persisted.get("api_base") or DEFAULT_API_BASE),
                persisted,
                self._window._logger,
            )
            return json.dumps({"ok": True, "config": persisted}, ensure_ascii=False)
        except Exception as exc:
            self._window._logger.exception("reset_desktop_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def download_collab_attachment(self, payload: str) -> str:
        """
        Download a collab attachment via Admin API and save with a native dialog.
        Payload JSON: admin_api_base, bearer_token, attachment_id, filename (optional).
        """
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("payload must be object")
            admin_base = str(data.get("admin_api_base") or "").strip().rstrip("/")
            token = str(data.get("bearer_token") or "").strip()
            attachment_id = str(data.get("attachment_id") or "").strip()
            hint_name = _decode_collab_display_filename(str(data.get("filename") or ""))
            if not admin_base or not token or not attachment_id:
                return json.dumps(
                    {
                        "ok": False,
                        "message": "missing admin_api_base, token, or attachment_id",
                    },
                    ensure_ascii=False,
                )

            url = (
                f"{admin_base}/api/admin/collab/attachments/"
                f"{urllib.parse.quote(attachment_id, safe='')}/download"
            )
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
            if resp.status_code != 200:
                detail = resp.text[:500] if resp.text else resp.reason
                return json.dumps(
                    {"ok": False, "message": f"HTTP {resp.status_code}: {detail}"},
                    ensure_ascii=False,
                )

            save_name = hint_name
            cd = resp.headers.get("Content-Disposition") or ""
            m = re.search(r"filename\*=UTF-8''([^;\s]+)", cd, re.I)
            if m:
                try:
                    save_name = urllib.parse.unquote(m.group(1)) or save_name
                except Exception:
                    save_name = m.group(1) or save_name
            else:
                m = re.search(r'filename="([^"]+)"', cd, re.I)
                if m:
                    save_name = m.group(1) or save_name

            downloads = Path.home() / "Downloads"
            default_path = (
                downloads / save_name if downloads.is_dir() else Path(save_name)
            )
            chosen, _ = QFileDialog.getSaveFileName(
                self._window,
                "保存协同附件",
                str(default_path),
            )
            if not chosen:
                return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)

            out_path = Path(chosen)
            out_path.write_bytes(resp.content)
            self._window._logger.info("collab attachment saved: {}", out_path)
            return json.dumps(
                {"ok": True, "path": str(out_path), "filename": save_name},
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("download_collab_attachment failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @staticmethod
    def _load_collab_inbound_manifest(base_dir: Path) -> dict[str, dict]:
        manifest_path = base_dir / ".inbound_sync.json"
        if not manifest_path.is_file():
            return {}
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict] = {}
        for key, val in raw.items():
            if isinstance(key, str) and isinstance(val, dict):
                out[key] = val
        return out

    @staticmethod
    def _save_collab_inbound_manifest(
        base_dir: Path, manifest: dict[str, dict]
    ) -> None:
        manifest_path = base_dir / ".inbound_sync.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @pyqtSlot(str, result=str)
    def sync_collab_inbound_attachments(self, payload: str) -> str:
        """
        Download prior-step collab attachments into workspace collab folder.
        Payload JSON: admin_api_base, bearer_token, chain_id, username,
        workspace_root, prior_attachments[].
        """
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("payload must be object")
            admin_base = str(data.get("admin_api_base") or "").strip().rstrip("/")
            token = str(data.get("bearer_token") or "").strip()
            chain_id = str(data.get("chain_id") or "").strip()
            username = str(data.get("username") or "").strip() or "user"
            workspace_root = str(data.get("workspace_root") or "").strip()
            prior = data.get("prior_attachments") or []
            if not isinstance(prior, list):
                prior = []
            if not admin_base or not token or not chain_id or not prior:
                return json.dumps(
                    {
                        "ok": True,
                        "saved": [],
                        "skipped": [],
                        "message": "nothing to sync",
                    },
                    ensure_ascii=False,
                )
            if not workspace_root:
                return json.dumps(
                    {"ok": False, "message": "workspace_root is empty"},
                    ensure_ascii=False,
                )

            base_dir = Path(workspace_root) / username / "collab" / chain_id
            base_dir.mkdir(parents=True, exist_ok=True)
            manifest = self._load_collab_inbound_manifest(base_dir)
            saved: list[dict[str, str]] = []
            skipped: list[dict[str, str]] = []
            for item in prior:
                if not isinstance(item, dict):
                    continue
                att_id = str(item.get("id") or "").strip()
                if not att_id:
                    continue
                step_index = int(item.get("step_index") or 0)
                fname = _decode_collab_display_filename(
                    str(item.get("original_filename") or "attachment")
                )
                dest_dir = base_dir / f"step_{step_index}"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / fname

                rec = manifest.get(att_id)
                if isinstance(rec, dict):
                    cached = Path(str(rec.get("path") or ""))
                    if cached.is_file():
                        skipped.append(
                            {
                                "id": att_id,
                                "path": str(cached),
                                "step_index": str(step_index),
                                "filename": fname,
                            }
                        )
                        continue

                if dest_path.is_file():
                    manifest[att_id] = {
                        "path": str(dest_path),
                        "step_index": step_index,
                        "filename": fname,
                    }
                    skipped.append(
                        {
                            "id": att_id,
                            "path": str(dest_path),
                            "step_index": str(step_index),
                            "filename": fname,
                        }
                    )
                    continue

                url = (
                    f"{admin_base}/api/admin/collab/attachments/"
                    f"{urllib.parse.quote(att_id, safe='')}/download"
                )
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=120,
                )
                if resp.status_code != 200:
                    self._window._logger.error(
                        "collab inbound download failed id={} status={}",
                        att_id,
                        resp.status_code,
                    )
                    continue
                dest_path.write_bytes(resp.content)
                manifest[att_id] = {
                    "path": str(dest_path),
                    "step_index": step_index,
                    "filename": fname,
                }
                saved.append(
                    {
                        "id": att_id,
                        "path": str(dest_path),
                        "step_index": str(step_index),
                        "filename": fname,
                    }
                )

            if saved or skipped:
                self._save_collab_inbound_manifest(base_dir, manifest)

            self._window._logger.info(
                "collab inbound sync chain={} saved={} skipped={}",
                chain_id,
                len(saved),
                len(skipped),
            )
            return json.dumps(
                {
                    "ok": True,
                    "saved": saved,
                    "skipped": skipped,
                    "base_dir": str(base_dir),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("sync_collab_inbound_attachments failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def upload_collab_attachment_paths(self, payload: str) -> str:
        """
        Upload local files as collab step attachments via Admin API.
        Payload JSON: admin_api_base, bearer_token, chain_id, step_id, paths[].
        """
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("payload must be object")
            admin_base = str(data.get("admin_api_base") or "").strip().rstrip("/")
            token = str(data.get("bearer_token") or "").strip()
            chain_id = str(data.get("chain_id") or "").strip()
            step_id = str(data.get("step_id") or "").strip()
            paths_in = data.get("paths") or []
            if not isinstance(paths_in, list):
                paths_in = []
            if not admin_base or not token or not chain_id or not step_id:
                return json.dumps(
                    {
                        "ok": False,
                        "message": "missing admin_api_base, token, chain_id, or step_id",
                    },
                    ensure_ascii=False,
                )
            if not paths_in:
                return json.dumps(
                    {"ok": True, "attachment_ids": [], "uploaded": []},
                    ensure_ascii=False,
                )

            uploaded: list[dict[str, str]] = []
            attachment_ids: list[str] = []
            for raw in paths_in:
                path = str(raw or "").strip().strip('"').strip("'")
                if not path:
                    continue
                src = Path(path)
                if not src.is_file():
                    self._window._logger.info(
                        "collab deliverable upload skipped (not a file): {}", path
                    )
                    continue
                fname = _decode_collab_display_filename(src.name)
                url = (
                    f"{admin_base}/api/admin/collab/attachments/upload"
                    f"?chain_id={urllib.parse.quote(chain_id, safe='')}"
                    f"&step_id={urllib.parse.quote(step_id, safe='')}"
                )
                with open(src, "rb") as fh:
                    resp = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": (fname, fh)},
                        timeout=120,
                    )
                if resp.status_code != 200:
                    detail = resp.text[:500] if resp.text else resp.reason
                    self._window._logger.error(
                        "collab deliverable upload failed path={} status={}",
                        path,
                        resp.status_code,
                    )
                    return json.dumps(
                        {
                            "ok": False,
                            "message": f"HTTP {resp.status_code}: {detail}",
                            "path": path,
                        },
                        ensure_ascii=False,
                    )
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                if not body.get("success"):
                    return json.dumps(
                        {
                            "ok": False,
                            "message": str(body.get("message") or "upload failed"),
                            "path": path,
                        },
                        ensure_ascii=False,
                    )
                att_id = str(body.get("attachment_id") or "").strip()
                if att_id:
                    attachment_ids.append(att_id)
                uploaded.append(
                    {"path": str(src), "attachment_id": att_id, "filename": fname}
                )

            self._window._logger.info(
                "collab deliverable upload chain={} step={} count={}",
                chain_id,
                step_id,
                len(uploaded),
            )
            return json.dumps(
                {
                    "ok": True,
                    "attachment_ids": attachment_ids,
                    "uploaded": uploaded,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("upload_collab_attachment_paths failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=bool)
    def open_external_url(self, url: str) -> bool:
        """
        从桌面端调用系统默认程序打开 URL。
        JS 用于点击聊天里的保存位置路径（file:///...）。
        对于本地 file:// 路径：在资源管理器中打开；若目标为已存在文件则选中并定位到该文件。
        """
        try:
            u = (url or "").strip()
            if not u:
                return False
            allowed = (
                u.startswith("file://")
                or u.startswith("http://")
                or u.startswith("https://")
            )
            if not allowed:
                return False

            if u.startswith("file://"):
                local_file = QUrl(u).toLocalFile()
                if local_file:
                    revealed = _reveal_local_path_in_file_manager(
                        Path(local_file), self._window._logger
                    )
                    if revealed:
                        return True
                    self._window._logger.info(
                        "open_external_url: no existing directory to open for {}", u
                    )
                    return False

            # fallback：直接尝试打开该 URL
            return QDesktopServices.openUrl(QUrl(u))
        except Exception:
            self._window._logger.exception("open_external_url failed")
            return False

    @pyqtSlot(result=str)
    def get_skills_config(self) -> str:
        try:
            cfg = _read_skills_config()
            return json.dumps(
                {"ok": True, "config": cfg, "path": str(_skills_config_path())},
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("get_skills_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def save_skills_config(self, payload: str) -> str:
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("skills 配置必须是对象")
            persisted = _persist_skills_config(data)
            return json.dumps(
                {"ok": True, "config": persisted, "path": str(_skills_config_path())},
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("save_skills_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def install_skill_package(self, payload: str) -> str:
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("payload must be object")
            result = _install_skill_package_impl(data, self._window._logger)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            self._window._logger.exception("install_skill_package failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_skill_inventory(self) -> str:
        try:
            skills = _collect_local_skill_inventory(self._window._logger)
            return json.dumps({"ok": True, "skills": skills}, ensure_ascii=False)
        except Exception as exc:
            self._window._logger.exception("get_skill_inventory failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_mcp_config(self) -> str:
        try:
            cfg = _read_mcp_servers_config()
            return json.dumps(
                {"ok": True, "config": cfg, "path": str(_mcp_servers_config_path())},
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("get_mcp_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def save_mcp_config(self, payload: str) -> str:
        try:
            data = json.loads(payload or "[]")
            if not isinstance(data, list):
                raise ValueError("mcp 配置必须是数组")
            persisted = _persist_mcp_servers_config(data)
            return json.dumps(
                {
                    "ok": True,
                    "config": persisted,
                    "path": str(_mcp_servers_config_path()),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            self._window._logger.exception("save_mcp_config failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def select_directory(self) -> str:
        """弹出系统文件夹选择对话框，返回所选路径"""
        try:
            chosen = QFileDialog.getExistingDirectory(
                self._window,
                "选择允许访问的目录",
                "",
            )
            if not chosen:
                return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
            return json.dumps(
                {"ok": True, "path": str(Path(chosen))}, ensure_ascii=False
            )
        except Exception as exc:
            self._window._logger.exception("select_directory failed")
            return json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)


def main() -> int:
    desktop_config = _resolve_desktop_config()
    _note_paths_cfg(desktop_config)
    logger = _setup_logging()
    _install_exception_hooks(logger)
    app = QApplication(sys.argv)
    app.setApplicationName("WorkmateDesktop")

    if _try_notify_running_instance(logger):
        return 0

    api_base = str(desktop_config.get("api_base") or DEFAULT_API_BASE)
    backend = ManagedBackend(api_base, logger)

    if len(sys.argv) > 1 and _is_remote_url(sys.argv[1]):
        start = QUrl(sys.argv[1])
    else:
        if desktop_config.get("backend_auto_start", True):
            backend.ensure_started(desktop_config)
        if _wait_backend_ready(api_base, timeout_s=2.5):
            _sync_runtime_config(api_base, desktop_config, logger)
            _check_mcp_runtime_and_notify(api_base, logger)
            # 等待 MCP 连接预热完成，确保后续任务运行时无需再握手
            _wait_mcp_preload(api_base, logger)
        atexit.register(backend.stop)
        start = _local_app_url(api_base=api_base, desktop_config=desktop_config)

    win = WebShellWindow(start_url=start, desktop_config=desktop_config, logger=logger)
    _attach_singleton_server(win, logger)
    win.showMaximized()
    exit_code = app.exec()
    backend.stop()
    logger.info("desktop shell exited with code={}", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
