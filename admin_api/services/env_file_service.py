from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from dotenv import load_dotenv

from admin_api.models.init_db import get_db_connection
from admin_api.services.config_service import ConfigService
from workflow.config import BASE_DIR, resolve_env_file_path


@dataclass
class EnvLine:
    kind: str
    raw: str
    key: str | None = None
    value: str | None = None
    export: bool = False


class EnvFileService:
    ENV_FILE_PATH: Path | None = None
    HIDDEN_SECTIONS_CONFIG_KEY = "env_file_hidden_sections"
    HIDDEN_KEYS_CONFIG_KEY = "env_file_hidden_keys"
    DB_CONFIG_KEYS = (
        "env_config",
        "global_config",
        "mcp_local_tools_config",
        HIDDEN_SECTIONS_CONFIG_KEY,
        HIDDEN_KEYS_CONFIG_KEY,
    )
    DB_TARGET_PATH = "sys_configs"
    LEGACY_ENV_KEYS = (
        "GOOGLE_API_KEY",
        "MINIMAX_API_KEY",
        "DASHSCOPE_API_KEY",
        "RUNLOOP_API_KEY",
        "OSS_ENDPOINT",
        "OSS_REGION",
        "OSS_BUCKET",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
        "OSS_AUTH_MODE",
        "OSS_STS_TOKEN",
        "SKILL_INSTALL_TRIGGER_MODE",
    )
    LEGACY_GLOBAL_KEYS = (
        "WECHAT_WORK_ALLOWED_USERS",
        "MCP_READ_ALLOWED_DIRS",
        "MCP_WRITE_ALLOWED_DIRS",
    )
    LEGACY_LOCAL_TOOL_KEYS = (
        "MCP_ENABLE_WINDOWS_TOOLS",
        "MCP_ENABLE_ADVANCED_TOOLS",
        "MCP_ENABLE_COMMON_TOOLS",
        "MCP_ENABLE_DOCUMENT_TOOLS",
        "MCP_ENABLE_EXECUTION_TOOLS",
        "MCP_ENABLE_MEDIA_TOOLS",
        "MCP_ENABLE_SEARCH_TOOLS",
        "MCP_ENABLE_WECHAT_TOOLS",
        "MCP_ENABLE_HAPP_TOOLS",
    )
    CLIENT_ENV_KEYS = (
        "SKILL_INSTALL_TRIGGER_MODE",
        "SKILL_AUTO_UPGRADE_MAX_CONCURRENCY",
        "SKILL_AUTO_UPGRADE_RETRY_TIMES",
        "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC",
        "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE",
        "SKILL_ROLLOUT_FAILURE_THRESHOLD",
    )
    CLIENT_GLOBAL_KEYS = (
        "MCP_READ_ALLOWED_DIRS",
        "MCP_WRITE_ALLOWED_DIRS",
        "WECHAT_WORK_ALLOWED_USERS",
    )
    CLIENT_LOCAL_TOOL_KEYS = LEGACY_LOCAL_TOOL_KEYS
    SENSITIVE_KEYS = {
        "GOOGLE_API_KEY",
        "MINIMAX_API_KEY",
        "DASHSCOPE_API_KEY",
        "RUNLOOP_API_KEY",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
        "OSS_STS_TOKEN",
        "WECHAT_WORK_SECRET",
        "WXWORK_SECRET",
        "WXWORK_TOKEN",
        "WXWORK_ENCODIING_AES_KEY",
        "REPORT_DB_PASS",
        "WORKMATE_DB_PASS",
        "REDIS_PASSWORD",
    }
    BOOLEAN_KEYS = {
        "USE_SANDBOX",
        "ENABLE_SUBAGENTS",
        "WORKMATE_LOG_STDOUT",
        "MEMORY_ENABLE_TOPIC_SEARCH",
        *CLIENT_LOCAL_TOOL_KEYS,
    }
    TEXTAREA_KEYS = {
        "MCP_READ_ALLOWED_DIRS",
        "MCP_WRITE_ALLOWED_DIRS",
        "WECHAT_WORK_ALLOWED_USERS",
    }
    SELECT_OPTIONS: dict[str, list[dict[str, str]]] = {
        "SKILL_INSTALL_TRIGGER_MODE": [
            {"label": "主动 (active)", "value": "active"},
            {"label": "被动 (passive)", "value": "passive"},
            {"label": "混合 (hybrid)", "value": "hybrid"},
        ],
        "OSS_AUTH_MODE": [
            {"label": "AK/SK", "value": "aksk"},
            {"label": "STS", "value": "sts"},
        ],
    }
    DEFAULT_VALUES: dict[str, str] = {
        "IMAGE_LLM_MODEL": "gemini-3-pro-image-preview",
        "MINIMAX_DOMAIN": "https://api.minimaxi.com",
        "TEXT_LLM_MODEL": "qwen3-next-80b-a3b-instruct",
        "TEXT_LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "USE_SANDBOX": "false",
        "ENABLE_SUBAGENTS": "false",
        "WORKMATE_LOG_STDOUT": "true",
        "SKILL_INSTALL_TRIGGER_MODE": "hybrid",
        "SKILL_AUTO_UPGRADE_MAX_CONCURRENCY": "1",
        "SKILL_AUTO_UPGRADE_RETRY_TIMES": "2",
        "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC": "5",
        "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE": "100",
        "SKILL_ROLLOUT_FAILURE_THRESHOLD": "0.3",
        "MCP_ENABLE_WINDOWS_TOOLS": "false",
        "MCP_ENABLE_ADVANCED_TOOLS": "true",
        "MCP_ENABLE_COMMON_TOOLS": "true",
        "MCP_ENABLE_DOCUMENT_TOOLS": "true",
        "MCP_ENABLE_EXECUTION_TOOLS": "true",
        "MCP_ENABLE_MEDIA_TOOLS": "true",
        "MCP_ENABLE_SEARCH_TOOLS": "true",
        "MCP_ENABLE_WECHAT_TOOLS": "true",
        "MCP_ENABLE_HAPP_TOOLS": "true",
        "WECHAT_WINDOW_TITLE": "微信",
        "WECHAT_PROCESS_NAME": "Weixin",
        "WORKMATE_ADMIN_HOST": "0.0.0.0",
        "WORKMATE_ADMIN_PORT": "8010",
    }
    SECTION_DEFINITIONS: list[dict[str, Any]] = [
        {
            "id": "models",
            "title": "模型与媒体",
            "description": "模型服务密钥与基础参数。",
            "keys": [
                "GOOGLE_API_KEY",
                "IMAGE_LLM_MODEL",
                "MINIMAX_API_KEY",
                "MINIMAX_DOMAIN",
                "DASHSCOPE_API_KEY",
                "TEXT_LLM_MODEL",
                "TEXT_LLM_BASE_URL",
            ],
        },
        {
            "id": "templates",
            "title": "模板与文档（已迁移至模板管理）",
            "description": "模板路径已迁移至管理端「模板管理」页面动态配置，以下环境变量仅作为离线模式 fallback 保留。",
            "keys": [
                "TEMPLATE_DIR",
                "IMAGE_TEMPLATE_DIR",
            ],
        },
        {
            "id": "sandbox",
            "title": "沙盒与子代理",
            "description": "运行时沙盒与子代理能力控制。",
            "keys": [
                "RUNLOOP_API_KEY",
                "USE_SANDBOX",
                "SUBAGENTS_CONFIG_PATH",
                "ENABLE_SUBAGENTS",
            ],
        },
        {
            "id": "skills",
            "title": "技能分发与 OSS",
            "description": "技能安装触发、分发阈值和 OSS 存储配置。",
            "keys": [
                "SKILL_INSTALL_TRIGGER_MODE",
                "SKILL_AUTO_UPGRADE_MAX_CONCURRENCY",
                "SKILL_AUTO_UPGRADE_RETRY_TIMES",
                "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC",
                "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE",
                "SKILL_ROLLOUT_FAILURE_THRESHOLD",
                "OSS_ENDPOINT",
                "OSS_REGION",
                "OSS_BUCKET",
                "OSS_ACCESS_KEY_ID",
                "OSS_ACCESS_KEY_SECRET",
                "OSS_AUTH_MODE",
                "OSS_STS_TOKEN",
            ],
        },
        {
            "id": "mcp",
            "title": "MCP 与访问控制",
            "description": "MCP 目录白名单与本地工具开关。",
            "keys": [
                "MCP_READ_ALLOWED_DIRS",
                "MCP_WRITE_ALLOWED_DIRS",
                *CLIENT_LOCAL_TOOL_KEYS,
            ],
        },
        {
            "id": "database",
            "title": "数据库与缓存",
            "description": "运行时数据库、缓存等连接信息。",
            "keys": [
                "WORKMATE_DB_HOST",
                "WORKMATE_DB_DATABASE",
                "WORKMATE_DB_USER",
                "WORKMATE_DB_PASS",
                "REDIS_HOST",
                "REDIS_PORT",
                "REDIS_PASSWORD",
            ],
        },
        {
            "id": "wechat",
            "title": "微信与企微",
            "description": "微信附件、企业微信连接与白名单。",
            "keys": [
                "WECHAT_ATTACHMENT_SAVE_DIR",
                "WECHAT_ATTACHMENT_CACHE_FILE",
                "WECHAT_AUDIO_CACHE_FILE",
                "WECHAT_WINDOW_TITLE",
                "WECHAT_PROCESS_NAME",
                "WECHAT_AI_REPLY_PREFIX",
                "WECHAT_WORK_CORP_ID",
                "WECHAT_WORK_AGENT_ID",
                "WECHAT_WORK_SECRET",
                "WECHAT_WORK_ALLOWED_USERS",
                "WXWORK_BOT_ID",
                "WXWORK_SECRET",
                "WXWORK_URL",
                "WXWORK_TOKEN",
                "WXWORK_ENCODIING_AES_KEY",
            ],
        },
        {
            "id": "runtime",
            "title": "运行时与路径",
            "description": "运行目录、日志、URL 与客户端超时。",
            "keys": [
                "BASE_DIR",
                "OUTPUT_BASE_DIR",
                "WORKMATE_CLOUD_URL",
                "WORKMATE_ADMIN_API_BASE",
                "WORKMATE_AGENT_BASE_URL",
                "WORKMATE_ADMIN_HOST",
                "WORKMATE_ADMIN_PORT",
                "WORKMATE_ADMIN_LOG_LEVEL",
                "WORKMATE_LOG_LEVEL",
                "WORKMATE_LOG_STDOUT",
                "AGENT_USERNAME",
                "WORKMATE_CLIENT_HEARTBEAT_TIMEOUT_SECONDS",
                "WORKMATE_CLIENT_AUTH_TIMEOUT_SECONDS",
            ],
        },
        {
            "id": "memory",
            "title": "记忆与执行",
            "description": "记忆系统与执行相关参数。",
            "keys": [
                "MEMORY_SHORT_TERM_TASKS",
                "MEMORY_MID_TERM_TASKS",
                "MEMORY_ENABLE_TOPIC_SEARCH",
                "MEMORY_RELEVANT_TASKS_LIMIT",
                "MEMORY_SEARCH_CANDIDATE_LIMIT",
            ],
        },
    ]
    _SECTION_BY_KEY = {
        key: section["id"] for section in SECTION_DEFINITIONS for key in section["keys"]
    }

    @classmethod
    def env_file_path(cls) -> Path:
        if cls.ENV_FILE_PATH is not None:
            return Path(cls.ENV_FILE_PATH)
        return resolve_env_file_path()

    @classmethod
    def ensure_env_file(cls) -> Path:
        path = cls.env_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        return path

    @staticmethod
    def _normalize_scalar(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _parse_env_value(raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        if value[0] in {"'", '"'} and value[-1:] == value[0]:
            inner = value[1:-1]
            if value[0] == '"':
                inner = (
                    inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
                )
            return inner
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        return value

    @staticmethod
    def _format_env_value(value: Any) -> str:
        text = EnvFileService._normalize_scalar(value)
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        if (
            text == ""
            or text != text.strip()
            or any(ch in text for ch in ("#", '"', "'", " ", "\t", "\n"))
        ):
            return f'"{escaped}"'
        return escaped

    @staticmethod
    def _parse_line(line: str) -> EnvLine:
        if not line.strip():
            return EnvLine(kind="blank", raw="")
        if line.lstrip().startswith("#"):
            return EnvLine(kind="comment", raw=line)
        match = re.match(
            r"^\s*(export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line
        )
        if not match:
            return EnvLine(kind="raw", raw=line)
        return EnvLine(
            kind="kv",
            raw=line,
            key=match.group(2),
            value=EnvFileService._parse_env_value(match.group(3)),
            export=bool(match.group(1)),
        )

    @classmethod
    def _load_lines(cls) -> list[EnvLine]:
        path = cls.ensure_env_file()
        content = path.read_text(encoding="utf-8")
        return [cls._parse_line(line) for line in content.splitlines()]

    @classmethod
    def _effective_values_from_lines(cls, lines: Iterable[EnvLine]) -> dict[str, str]:
        values: dict[str, str] = {}
        for entry in lines:
            if entry.kind == "kv" and entry.key:
                values[entry.key] = entry.value or ""
        return values

    @classmethod
    def load_values(cls) -> dict[str, str]:
        return cls._effective_values_from_lines(cls._load_lines())

    @classmethod
    def get_effective_values(cls) -> dict[str, str]:
        local_values = cls.load_values()
        db_values = cls.load_values_from_db(base_values=local_values)
        if db_values:
            return db_values
        return local_values

    @classmethod
    def apply_to_process(cls) -> dict[str, str]:
        path = str(cls.ensure_env_file())
        load_dotenv(path, override=True)
        return cls.load_values()

    @classmethod
    def get_value(cls, key: str, default: str = "") -> str:
        values = cls.get_effective_values()
        value = values.get(key)
        if value is None or value == "":
            value = os.getenv(key, default)
        return str(value) if value is not None else str(default)

    @classmethod
    def is_sensitive_key(cls, key: str) -> bool:
        return (
            key in cls.SENSITIVE_KEYS
            or key.endswith("_API_KEY")
            or key.endswith("_SECRET")
        )

    @classmethod
    def _default_value(cls, key: str) -> str:
        return cls.DEFAULT_VALUES.get(key, "")

    @classmethod
    def _section_definition(cls, section_id: str) -> dict[str, Any]:
        for section in cls.SECTION_DEFINITIONS:
            if section["id"] == section_id:
                return section
        return {
            "id": "custom",
            "title": "其他配置项",
            "description": "未预设的自定义环境变量。",
            "keys": [],
        }

    @classmethod
    def _section_id_for_key(cls, key: str) -> str:
        if key in cls._SECTION_BY_KEY:
            return cls._SECTION_BY_KEY[key]
        if key.startswith("MCP_ENABLE_"):
            return "mcp"
        if key.startswith("SKILL_") or key.startswith("OSS_"):
            return "skills"
        if (
            key.startswith("WECHAT_")
            or key.startswith("WXWORK_")
            or key.startswith("WECHAT_WORK_")
        ):
            return "wechat"
        if (
            key.startswith("REPORT_DB_")
            or key.startswith("WORKMATE_DB_")
            or key.startswith("REDIS_")
        ):
            return "database"
        if key.startswith("MEMORY_"):
            return "memory"
        return "custom"

    @classmethod
    def _known_keys_in_order(cls) -> list[str]:
        ordered: list[str] = []
        for section in cls.SECTION_DEFINITIONS:
            for key in section["keys"]:
                if key not in ordered:
                    ordered.append(key)
        return ordered

    @classmethod
    def _field_meta(cls, key: str, value: str) -> dict[str, Any]:
        component = "input"
        if key in cls.BOOLEAN_KEYS or key.startswith("MCP_ENABLE_"):
            component = "switch"
        elif key in cls.SELECT_OPTIONS:
            component = "select"
        elif key in cls.TEXTAREA_KEYS:
            component = "textarea"
        elif cls.is_sensitive_key(key):
            component = "password"
        section_id = cls._section_id_for_key(key)
        return {
            "key": key,
            "label": key,
            "description": "",
            "component": component,
            "sensitive": cls.is_sensitive_key(key),
            "section_id": section_id,
            "options": cls.SELECT_OPTIONS.get(key, []),
            "default_value": cls._default_value(key),
            "value": value,
        }

    @classmethod
    def _build_admin_payload(
        cls, values: Mapping[str, Any], *, path: str, updated_at: str = ""
    ) -> dict[str, Any]:
        hidden_sections = set(
            str(section_id).strip()
            for section_id in ConfigService.get_config(
                cls.HIDDEN_SECTIONS_CONFIG_KEY, []
            )
            if str(section_id).strip()
        )
        hidden_keys = set(
            str(key).strip()
            for key in ConfigService.get_config(cls.HIDDEN_KEYS_CONFIG_KEY, [])
            if str(key).strip()
        )
        all_sections = [
            {
                "id": str(section["id"]),
                "title": str(section.get("title") or ""),
                "description": str(section.get("description") or ""),
                "keys": list(section.get("keys") or []),
            }
            for section in cls.SECTION_DEFINITIONS
        ]
        known_keys = cls._known_keys_in_order()
        ordered_keys = list(known_keys)
        for key in values:
            if key not in ordered_keys:
                ordered_keys.append(key)
        section_payload: list[dict[str, Any]] = []
        for section in cls.SECTION_DEFINITIONS + [
            {
                "id": "custom",
                "title": "其他配置项",
                "description": "未在管理端预设的环境变量，可直接增删。",
                "keys": [],
            }
        ]:
            if section["id"] in hidden_sections:
                continue
            fields = []
            for key in ordered_keys:
                if cls._section_id_for_key(key) != section["id"]:
                    continue
                if key in hidden_keys:
                    continue
                fields.append(
                    cls._field_meta(key, values.get(key, cls._default_value(key)))
                )
            if fields:
                section_payload.append(
                    {
                        "id": section["id"],
                        "title": section["title"],
                        "description": section["description"],
                        "fields": fields,
                    }
                )
        return {
            "path": path,
            "updated_at": updated_at,
            "hidden_sections": sorted(hidden_sections),
            "hidden_keys": sorted(hidden_keys),
            "all_sections": all_sections,
            "values": dict(values),
            "raw_items": [
                {"key": key, "value": value} for key, value in values.items()
            ],
            "unknown_items": [
                {"key": key, "value": value}
                for key, value in values.items()
                if key not in known_keys
            ],
            "sections": section_payload,
        }

    @classmethod
    def hide_sections(cls, section_ids: Iterable[str]) -> list[str]:
        normalized = [
            str(section_id).strip()
            for section_id in section_ids
            if str(section_id).strip()
        ]
        if not normalized:
            return []
        current = ConfigService.get_config(cls.HIDDEN_SECTIONS_CONFIG_KEY, [])
        existing = [str(item).strip() for item in (current or []) if str(item).strip()]
        merged = sorted(set(existing + normalized))
        ConfigService.set_config(
            cls.HIDDEN_SECTIONS_CONFIG_KEY,
            "env_section",
            merged,
            "隐藏的环境配置板块",
        )
        return merged

    @classmethod
    def show_sections(cls, section_ids: Iterable[str]) -> list[str]:
        normalized = {
            str(section_id).strip()
            for section_id in section_ids
            if str(section_id).strip()
        }
        if not normalized:
            return cls.hide_sections([])
        current = ConfigService.get_config(cls.HIDDEN_SECTIONS_CONFIG_KEY, [])
        existing = {str(item).strip() for item in (current or []) if str(item).strip()}
        updated = sorted(existing - normalized)
        ConfigService.set_config(
            cls.HIDDEN_SECTIONS_CONFIG_KEY,
            "env_section",
            updated,
            "隐藏的环境配置板块",
        )
        return updated

    @classmethod
    def hide_keys(cls, keys: Iterable[str]) -> list[str]:
        normalized = [str(key).strip() for key in keys if str(key).strip()]
        if not normalized:
            return []
        current = ConfigService.get_config(cls.HIDDEN_KEYS_CONFIG_KEY, [])
        existing = [str(item).strip() for item in (current or []) if str(item).strip()]
        merged = sorted(set(existing + normalized))
        ConfigService.set_config(
            cls.HIDDEN_KEYS_CONFIG_KEY,
            "env_key",
            merged,
            "隐藏的环境配置项",
        )
        return merged

    @classmethod
    def show_keys(cls, keys: Iterable[str]) -> list[str]:
        normalized = {str(key).strip() for key in keys if str(key).strip()}
        if not normalized:
            return cls.hide_keys([])
        current = ConfigService.get_config(cls.HIDDEN_KEYS_CONFIG_KEY, [])
        existing = {str(item).strip() for item in (current or []) if str(item).strip()}
        updated = sorted(existing - normalized)
        ConfigService.set_config(
            cls.HIDDEN_KEYS_CONFIG_KEY,
            "env_key",
            updated,
            "隐藏的环境配置项",
        )
        return updated

    @classmethod
    def get_admin_payload(cls) -> dict[str, Any]:
        values = cls.get_effective_values()
        updated_at = datetime.fromtimestamp(
            cls.ensure_env_file().stat().st_mtime
        ).isoformat()
        return cls._build_admin_payload(
            values,
            path=str(cls.ensure_env_file()),
            updated_at=updated_at,
        )

    @classmethod
    def split_values_for_legacy_configs(
        cls, values: Mapping[str, Any]
    ) -> tuple[dict[str, str], dict[str, str], dict[str, bool]]:
        normalized_values = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(values or {}).items()
            if str(key).strip()
        }
        env_config = {}
        global_config = {
            key: normalized_values[key]
            for key in cls.LEGACY_GLOBAL_KEYS
            if key in normalized_values
        }
        local_tools_config = {
            key: normalized_values[key].strip().lower() in {"1", "true", "yes", "on"}
            for key in cls.LEGACY_LOCAL_TOOL_KEYS
            if key in normalized_values
        }
        for key, value in normalized_values.items():
            if key in cls.LEGACY_GLOBAL_KEYS or key in cls.LEGACY_LOCAL_TOOL_KEYS:
                continue
            env_config[key] = value
        return env_config, global_config, local_tools_config

    @classmethod
    def merge_legacy_configs_to_values(
        cls,
        env_cfg: Mapping[str, Any] | None,
        global_cfg: Mapping[str, Any] | None,
        local_tools_cfg: Mapping[str, Any] | None,
        base_values: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        merged = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(base_values or {}).items()
            if str(key).strip()
        }
        for payload in (env_cfg or {}, global_cfg or {}):
            for key, value in dict(payload).items():
                normalized_key = str(key).strip()
                if normalized_key:
                    merged[normalized_key] = cls._normalize_scalar(value)
        for key, value in dict(local_tools_cfg or {}).items():
            normalized_key = str(key).strip()
            if normalized_key:
                merged[normalized_key] = "true" if bool(value) else "false"
        return merged

    @classmethod
    def load_values_from_db(
        cls, base_values: Mapping[str, Any] | None = None
    ) -> dict[str, str]:
        env_cfg = ConfigService.get_config("env_config", {})
        global_cfg = ConfigService.get_config("global_config", {})
        local_tools_cfg = ConfigService.get_config("mcp_local_tools_config", {})
        merged = cls.merge_legacy_configs_to_values(
            env_cfg, global_cfg, local_tools_cfg, base_values=base_values
        )
        has_db_values = bool(env_cfg) or bool(global_cfg) or bool(local_tools_cfg)
        return merged if has_db_values else {}

    @classmethod
    def get_db_values_only(cls) -> dict[str, str]:
        return cls.load_values_from_db(base_values={})

    @classmethod
    def get_db_updated_at(cls) -> str:
        conn = get_db_connection()
        if not conn:
            return ""
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            placeholders = ", ".join(["%s"] * len(cls.DB_CONFIG_KEYS))
            cursor.execute(
                f"""
                SELECT MAX(updated_at) AS updated_at
                FROM sys_configs
                WHERE config_key IN ({placeholders})
                """,
                cls.DB_CONFIG_KEYS,
            )
            row = cursor.fetchone() or {}
            value = row.get("updated_at")
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value or "")
        except Exception:
            return ""
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def get_db_admin_payload(cls) -> dict[str, Any]:
        values = cls.get_db_values_only()
        return cls._build_admin_payload(
            values,
            path=cls.DB_TARGET_PATH,
            updated_at=cls.get_db_updated_at(),
        )

    @classmethod
    def sync_values_to_db(cls, values: Mapping[str, Any]) -> bool:
        env_config, global_config, local_tools_config = (
            cls.split_values_for_legacy_configs(values)
        )
        success = True
        success = (
            ConfigService.set_config("env_config", "env", env_config, "环境变量配置")
            and success
        )
        success = (
            ConfigService.set_config(
                "global_config", "global", global_config, "全局运行参数"
            )
            and success
        )
        success = (
            ConfigService.set_config(
                "mcp_local_tools_config",
                "mcp_tools",
                local_tools_config,
                "本地MCP工具模块开关",
            )
            and success
        )
        return success

    @classmethod
    def write_all_values(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        normalized_values = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(values or {}).items()
            if str(key).strip()
        }
        current_values = cls.load_values()
        lines = cls._load_lines()
        original_content = cls.ensure_env_file().read_text(encoding="utf-8")
        content = cls._render_content(
            lines, normalized_values, normalized_values, set()
        )
        path = cls.ensure_env_file()
        path.write_text(content, encoding="utf-8")
        if not cls.sync_values_to_db(normalized_values):
            path.write_text(original_content, encoding="utf-8")
            cls.apply_to_process()
            raise RuntimeError("`.env` 与数据库同步失败")
        cls.apply_to_process()
        changed_keys = sorted(
            set(current_values.keys()) | set(normalized_values.keys())
        )
        changed_keys = [
            key
            for key in changed_keys
            if current_values.get(key, cls._default_value(key))
            != normalized_values.get(key, cls._default_value(key))
        ]
        return {
            "changed_keys": changed_keys,
            "before_values": {
                key: current_values.get(key, cls._default_value(key))
                for key in changed_keys
            },
            "after_values": {
                key: normalized_values.get(key, "") for key in changed_keys
            },
            "path": str(path),
        }

    @classmethod
    def write_local_values_only(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        normalized_values = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(values or {}).items()
            if str(key).strip()
        }
        current_values = cls.load_values()
        lines = cls._load_lines()
        path = cls.ensure_env_file()
        content = cls._render_content(
            lines, normalized_values, normalized_values, set()
        )
        original_content = path.read_text(encoding="utf-8")
        if original_content != content:
            path.write_text(content, encoding="utf-8")
        cls.apply_to_process()
        changed_keys = sorted(
            set(current_values.keys()) | set(normalized_values.keys())
        )
        changed_keys = [
            key
            for key in changed_keys
            if current_values.get(key, cls._default_value(key))
            != normalized_values.get(key, cls._default_value(key))
        ]
        return {
            "changed_keys": changed_keys,
            "before_values": {
                key: current_values.get(key, cls._default_value(key))
                for key in changed_keys
            },
            "after_values": {
                key: normalized_values.get(key, "") for key in changed_keys
            },
            "path": str(path),
        }

    @classmethod
    def hydrate_local_env_from_db(
        cls, fallback_to_local: bool = True
    ) -> dict[str, Any]:
        local_values = cls.load_values()
        db_values = cls.load_values_from_db(base_values=local_values)
        if db_values:
            result = cls.write_local_values_only(db_values)
            result["source"] = "database"
            return result
        if fallback_to_local and local_values:
            cls.sync_values_to_db(local_values)
            return {
                "changed_keys": sorted(local_values.keys()),
                "before_values": {},
                "after_values": local_values,
                "path": str(cls.ensure_env_file()),
                "source": "local",
            }
        return {
            "changed_keys": [],
            "before_values": {},
            "after_values": local_values,
            "path": str(cls.ensure_env_file()),
            "source": "empty",
        }

    @classmethod
    def _render_content(
        cls,
        lines: list[EnvLine],
        merged_values: Mapping[str, str],
        updates: Mapping[str, str],
        deleted_keys: set[str],
    ) -> str:
        last_index: dict[str, int] = {}
        for idx, entry in enumerate(lines):
            if entry.kind == "kv" and entry.key:
                last_index[entry.key] = idx

        rendered: list[str] = []
        preserved_keys: set[str] = set()
        for idx, entry in enumerate(lines):
            if entry.kind != "kv" or not entry.key:
                rendered.append(entry.raw)
                continue
            if last_index.get(entry.key) != idx:
                continue
            if entry.key in deleted_keys:
                continue
            preserved_keys.add(entry.key)
            rendered.append(
                f"{'export ' if entry.export else ''}{entry.key}={cls._format_env_value(merged_values.get(entry.key, ''))}"
            )

        pending_new_keys = [
            key
            for key in updates
            if key not in preserved_keys and key not in deleted_keys
        ]
        if pending_new_keys:
            if rendered and rendered[-1].strip():
                rendered.append("")
            grouped: dict[str, list[str]] = {}
            for key in pending_new_keys:
                grouped.setdefault(cls._section_id_for_key(key), []).append(key)
            section_order = [section["id"] for section in cls.SECTION_DEFINITIONS] + [
                "custom"
            ]
            for section_id in section_order:
                keys = grouped.get(section_id, [])
                if not keys:
                    continue
                section = cls._section_definition(section_id)
                rendered.append(f"# {section['title']}")
                for key in keys:
                    rendered.append(
                        f"{key}={cls._format_env_value(merged_values.get(key, ''))}"
                    )
                rendered.append("")

        while rendered and rendered[-1] == "":
            rendered.pop()
        return "\n".join(rendered) + "\n"

    @classmethod
    def update_values(
        cls, updates: Mapping[str, Any], deleted_keys: Iterable[str] | None = None
    ) -> dict[str, Any]:
        normalized_updates = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(updates or {}).items()
            if str(key).strip()
        }
        normalized_deletes = {
            str(key).strip() for key in (deleted_keys or []) if str(key).strip()
        }
        if not normalized_updates and not normalized_deletes:
            return {
                "changed_keys": [],
                "before_values": {},
                "after_values": {},
                "path": str(cls.ensure_env_file()),
            }

        lines = cls._load_lines()
        current_values = cls._effective_values_from_lines(lines)
        merged_values = dict(current_values)
        merged_values.update(normalized_updates)
        for key in normalized_deletes:
            merged_values.pop(key, None)

        changed_keys = sorted(
            set(
                [
                    key
                    for key, new_value in normalized_updates.items()
                    if key not in current_values
                    or current_values.get(key, cls._default_value(key)) != new_value
                ]
                + [key for key in normalized_deletes if key in current_values]
            )
        )
        if not changed_keys:
            return {
                "changed_keys": [],
                "before_values": {},
                "after_values": {},
                "path": str(cls.ensure_env_file()),
            }

        path = cls.ensure_env_file()
        original_content = path.read_text(encoding="utf-8")
        content = cls._render_content(
            lines, merged_values, normalized_updates, normalized_deletes
        )
        path.write_text(content, encoding="utf-8")
        if not cls.sync_values_to_db(merged_values):
            path.write_text(original_content, encoding="utf-8")
            cls.apply_to_process()
            raise RuntimeError("`.env` 与数据库同步失败")
        cls.apply_to_process()
        return {
            "changed_keys": changed_keys,
            "before_values": {
                key: current_values.get(key, cls._default_value(key))
                for key in changed_keys
            },
            "after_values": {key: merged_values.get(key, "") for key in changed_keys},
            "path": str(path),
        }

    @classmethod
    def update_db_values_only(
        cls, updates: Mapping[str, Any], deleted_keys: Iterable[str] | None = None
    ) -> dict[str, Any]:
        normalized_updates = {
            str(key).strip(): cls._normalize_scalar(value)
            for key, value in dict(updates or {}).items()
            if str(key).strip()
        }
        normalized_deletes = {
            str(key).strip() for key in (deleted_keys or []) if str(key).strip()
        }
        if not normalized_updates and not normalized_deletes:
            return {
                "changed_keys": [],
                "before_values": {},
                "after_values": {},
                "path": cls.DB_TARGET_PATH,
            }

        current_values = cls.get_db_values_only()
        merged_values = dict(current_values)
        merged_values.update(normalized_updates)
        for key in normalized_deletes:
            merged_values.pop(key, None)

        changed_keys = sorted(
            set(
                [
                    key
                    for key, new_value in normalized_updates.items()
                    if current_values.get(key, cls._default_value(key)) != new_value
                ]
                + [key for key in normalized_deletes if key in current_values]
            )
        )
        if not changed_keys:
            return {
                "changed_keys": [],
                "before_values": {},
                "after_values": {},
                "path": cls.DB_TARGET_PATH,
            }

        if not cls.sync_values_to_db(merged_values):
            raise RuntimeError("数据库配置同步失败")
        return {
            "changed_keys": changed_keys,
            "before_values": {
                key: current_values.get(key, cls._default_value(key))
                for key in changed_keys
            },
            "after_values": {key: merged_values.get(key, "") for key in changed_keys},
            "path": cls.DB_TARGET_PATH,
        }

    @classmethod
    def subset(
        cls, keys: Iterable[str], *, coerce_bool: bool = False
    ) -> dict[str, Any]:
        values = cls.get_effective_values()
        return cls._subset_from_values(values, keys, coerce_bool=coerce_bool)

    @classmethod
    def _subset_from_values(
        cls,
        values: Mapping[str, Any],
        keys: Iterable[str],
        *,
        coerce_bool: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in keys:
            raw_value = values.get(key, cls._default_value(key))
            if coerce_bool or key in cls.BOOLEAN_KEYS or key.startswith("MCP_ENABLE_"):
                result[key] = str(raw_value).strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
            else:
                result[key] = raw_value
        return result

    @classmethod
    def get_legacy_env_config(cls) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in cls._subset_from_values(
                cls.get_db_values_only(), cls.LEGACY_ENV_KEYS
            ).items()
        }

    @classmethod
    def get_legacy_global_config(cls) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in cls._subset_from_values(
                cls.load_values(), cls.LEGACY_GLOBAL_KEYS
            ).items()
        }

    @classmethod
    def get_legacy_local_tools_config(cls) -> dict[str, bool]:
        return cls._subset_from_values(
            cls.get_db_values_only(), cls.LEGACY_LOCAL_TOOL_KEYS, coerce_bool=True
        )

    @classmethod
    def build_client_payload(cls) -> dict[str, Any]:
        values = cls.get_effective_values()
        env_config = {
            key: str(values.get(key, cls._default_value(key)))
            for key in cls.CLIENT_ENV_KEYS
        }
        global_config = {
            key: str(values.get(key, cls._default_value(key)))
            for key in cls.CLIENT_GLOBAL_KEYS
        }
        local_tools_config = {
            key: str(values.get(key, cls._default_value(key))).strip().lower()
            in {"1", "true", "yes", "on"}
            for key in cls.CLIENT_LOCAL_TOOL_KEYS
        }
        flat_env_config = dict(env_config)
        flat_env_config.update(global_config)
        flat_env_config.update(
            {
                key: "true" if value else "false"
                for key, value in local_tools_config.items()
            }
        )
        return {
            "env_config": env_config,
            "global_config": global_config,
            "mcp_local_tools_config": local_tools_config,
            "flat_env_config": flat_env_config,
            "updated_at": datetime.fromtimestamp(
                cls.ensure_env_file().stat().st_mtime
            ).isoformat(),
            "source": str(cls.ensure_env_file()),
        }
