import os
import shutil
import sys
from pathlib import Path

from loguru import logger

from admin_api.services.env_file_service import EnvFileService
from workflow.config import OUTPUT_BASE_DIR, resolve_env_file_path

from api.runtime_state import set_runtime_output_base_dir


def _relocate_packaged_env_from_internal() -> None:
    """One-time migration: PyInstaller puts `.env` under `_internal`; runtime uses exe dir."""
    if not getattr(sys, "frozen", False):
        return
    install_root = Path(sys.executable).resolve().parent
    root_env = resolve_env_file_path()
    internal_env = install_root / "_internal" / ".env"
    if not internal_env.is_file():
        return
    if not root_env.is_file():
        shutil.copy2(internal_env, root_env)
        logger.info("migrated packaged `.env` from _internal to {}", root_env)
    try:
        internal_env.unlink()
    except OSError as error:
        logger.info("could not remove _internal/.env after migrate: {}", error)


def inject_cloud_configs() -> None:
    try:
        _relocate_packaged_env_from_internal()
        if getattr(sys, "frozen", False):
            EnvFileService.apply_to_process()
            logger.info(
                "`.env` loaded into process env (packaged; skipped startup DB hydrate write)"
            )
            return
        result = EnvFileService.hydrate_local_env_from_db(fallback_to_local=True)
        EnvFileService.apply_to_process()
        logger.info("`.env` 配置已成功注入到环境变量，来源={}", result.get("source"))
    except Exception as error:
        logger.error("注入 `.env` 配置失败: {}", error)


def init_runtime_output_base_dir() -> None:
    set_runtime_output_base_dir(str(Path(OUTPUT_BASE_DIR).expanduser().resolve()))


def apply_runtime_output_base_dir(raw_dir: str) -> str:
    import workflow.config as workflow_config
    import workflow.subagents_config as workflow_subagents_config
    import workflow.workflow_core as workflow_core_module
    import workflow.workflow_infrastructure as workflow_infrastructure_module

    resolved = str(Path(raw_dir).expanduser().resolve())
    os.environ["OUTPUT_BASE_DIR"] = resolved

    workflow_config.OUTPUT_BASE_DIR = resolved
    workflow_config.MCP_WRITE_ALLOWED_DIRS = [resolved]
    workflow_core_module.OUTPUT_BASE_DIR = resolved
    workflow_infrastructure_module.OUTPUT_BASE_DIR = resolved
    workflow_subagents_config.OUTPUT_BASE_DIR = resolved
    workflow_subagents_config.MCP_WRITE_ALLOWED_DIRS = [resolved]
    set_runtime_output_base_dir(resolved)
    return resolved


def apply_runtime_desktop_user(username: str, mate_name: str = "") -> dict[str, str]:
    """
    Bind the current desktop login to process env for paths, prompts, and scheduler.

    - WORKMATE_DESKTOP_ACTIVE_USERNAME: workspace paths and MCP placeholders
    - MATE_NAME: injected into MANDATORY.md as the work partner display name
    """
    user = str(username or "").strip()
    if not user:
        return {}
    display = str(mate_name or "").strip() or user
    os.environ["WORKMATE_DESKTOP_ACTIVE_USERNAME"] = user
    os.environ["MATE_NAME"] = display
    logger.info(
        "desktop active user synced: username={} mate_name={}",
        user,
        display,
    )
    return {
        "WORKMATE_DESKTOP_ACTIVE_USERNAME": user,
        "MATE_NAME": display,
        "username": user,
        "mate_name": display,
    }


def apply_runtime_admin_api_base(raw_base: str) -> str:
    """Sync desktop/admin URL into process env for MCP collab stdio children."""
    origin = str(raw_base or "").strip().rstrip("/")
    if not origin:
        return ""
    os.environ["WORKMATE_ADMIN_API_BASE"] = origin
    return origin


def apply_runtime_wechat_env(runtime_cfg: dict) -> dict:
    env_updates = {
        "WECHAT_ATTACHMENT_SAVE_DIR": str(
            runtime_cfg.get("wechat_attachment_save_dir", "")
        ).strip(),
        "WECHAT_ATTACHMENT_CACHE_FILE": str(
            runtime_cfg.get("wechat_attachment_cache_file", "")
        ).strip(),
        "WECHAT_AUDIO_CACHE_FILE": str(
            runtime_cfg.get("wechat_audio_cache_file", "")
        ).strip(),
        "WECHAT_WINDOW_TITLE": str(runtime_cfg.get("wechat_window_title", "")).strip(),
        "WECHAT_PROCESS_NAME": str(runtime_cfg.get("wechat_process_name", "")).strip(),
        "WECHAT_AI_REPLY_PREFIX": str(
            runtime_cfg.get("wechat_ai_reply_prefix", "")
        ).strip(),
    }
    applied: dict[str, str] = {}
    for env_key, env_value in env_updates.items():
        if env_value:
            os.environ[env_key] = env_value
            applied[env_key] = env_value

    try:
        import mcp_filesystem.tools.wechat as wechat_tools_module

        if applied.get("WECHAT_AUDIO_CACHE_FILE"):
            wechat_tools_module._audio_cache_env = applied["WECHAT_AUDIO_CACHE_FILE"]
        if applied.get("WECHAT_ATTACHMENT_SAVE_DIR"):
            wechat_tools_module._attachment_dir_env = applied[
                "WECHAT_ATTACHMENT_SAVE_DIR"
            ]
        if applied.get("WECHAT_ATTACHMENT_CACHE_FILE"):
            wechat_tools_module._attachment_cache_env = applied[
                "WECHAT_ATTACHMENT_CACHE_FILE"
            ]
        if applied.get("WECHAT_WINDOW_TITLE"):
            wechat_tools_module.WECHAT_WINDOW_TITLE = applied["WECHAT_WINDOW_TITLE"]
        if applied.get("WECHAT_PROCESS_NAME"):
            wechat_tools_module.WECHAT_PROCESS_NAME = applied["WECHAT_PROCESS_NAME"]
        if applied.get("WECHAT_AI_REPLY_PREFIX"):
            wechat_tools_module.WECHAT_AI_REPLY_PREFIX = applied[
                "WECHAT_AI_REPLY_PREFIX"
            ]
    except Exception as error:
        logger.info("apply runtime wechat module vars failed: {}", error)

    return applied


def apply_runtime_general_env(runtime_cfg: dict) -> dict:
    """同步通用设置（模型/模板/记忆/沙箱/子代理）到进程环境变量。"""
    # 字符串型配置映射
    _string_env_map = {
        "image_provider": "IMAGE_PROVIDER",
        "llm_provider": "LLM_PROVIDER",
        "template_dir": "TEMPLATE_DIR",
        "image_template_dir": "IMAGE_TEMPLATE_DIR",
    }
    # 布尔型配置映射
    _bool_env_map = {
        "memory_compress_enabled": "MEMORY_COMPRESS_ENABLED",
        "memory_enable_topic_search": "MEMORY_ENABLE_TOPIC_SEARCH",
        "use_sandbox": "USE_SANDBOX",
        "enable_subagents": "ENABLE_SUBAGENTS",
    }
    # 数值型配置映射
    _int_env_map = {
        "memory_compress_threshold": "MEMORY_COMPRESS_THRESHOLD",
        "memory_short_term_tasks": "MEMORY_SHORT_TERM_TASKS",
        "memory_mid_term_tasks": "MEMORY_MID_TERM_TASKS",
        "memory_relevant_tasks_limit": "MEMORY_RELEVANT_TASKS_LIMIT",
        "memory_search_candidate_limit": "MEMORY_SEARCH_CANDIDATE_LIMIT",
    }

    applied: dict[str, str] = {}

    # 同步字符串型配置
    for cfg_key, env_key in _string_env_map.items():
        val = str(runtime_cfg.get(cfg_key, "")).strip()
        if val:
            os.environ[env_key] = val
            applied[env_key] = val

    # 同步布尔型配置
    for cfg_key, env_key in _bool_env_map.items():
        val = "true" if runtime_cfg.get(cfg_key, False) else "false"
        os.environ[env_key] = val
        applied[env_key] = val

    # 同步数值型配置
    for cfg_key, env_key in _int_env_map.items():
        try:
            val = str(int(runtime_cfg.get(cfg_key, 0)))
        except (ValueError, TypeError):
            val = "0"
        os.environ[env_key] = val
        applied[env_key] = val

    if applied:
        logger.info("apply runtime general env: {}", applied)

    return applied
