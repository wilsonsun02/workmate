import json
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv

# 加载 .env：打包场景下 BASE_DIR 已由 serve 入口提前写入环境变量，优先从该目录加载。
_base_dir_env = os.environ.get("BASE_DIR", "").strip()
if _base_dir_env:
    _env_file = os.path.join(_base_dir_env, ".env")
    if os.path.isfile(_env_file):
        load_dotenv(_env_file)
load_dotenv()

# 日志配置，用于设置日志的级别和格式
LOGGING_CONFIG = {
    "level": "INFO",  # 日志级别为 INFO，记录信息性日志
    "format": "%(asctime)s - %(levelname)s - %(message)s",  # 日志格式：时间 - 级别 - 消息
}
# LLM 配置列表，定义多个大语言模型的配置，用于不同任务
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dashscope").strip().lower()


def _build_llm_config_dict():
    """根据 LLM_PROVIDER 动态构建模型配置字典"""
    if LLM_PROVIDER == "deepseek":
        return {
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "temperature": 0.6,
            "top_p": 0.95,
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "extra_body": {"thinking": {"type": "disabled"}},
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "16384")),
        }
    else:
        return {
            "model": os.getenv("LLM_MODEL", "qwen3.6-plus"),
            "temperature": 0.6,
            "extra_body": {"enable_thinking": False},
            "top_p": 0.95,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        }


LLM_CONFIGS = [_build_llm_config_dict()]

MCP_LLM_CONFIG = LLM_CONFIGS[0]


def _build_text_llm_config_dict():
    """根据 LLM_PROVIDER 动态构建文本模型配置字典（PPT生成、摘要等轻量任务）"""
    if LLM_PROVIDER == "deepseek":
        return {
            "model": os.getenv("DEEPSEEK_TEXT_MODEL", "deepseek-chat"),
            "temperature": 0.8,
            "top_p": 0.95,
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    else:
        return {
            "model": os.getenv("TEXT_LLM_MODEL", "qwen3-next-80b-a3b-instruct"),
            "temperature": 0.8,
            "extra_body": {"enable_thinking": False},
            "top_p": 0.95,
            "base_url": os.getenv(
                "TEXT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        }


MCP_TEXT_LLM_CONFIG = _build_text_llm_config_dict()

REPORT_DB_HOST = os.getenv("WORKMATE_DB_HOST", "localhost")
REPORT_DB_DATABASE = os.getenv("WORKMATE_DB_DATABASE", "workmate_pd")
REPORT_DB_USER = os.getenv("WORKMATE_DB_USER", "")
REPORT_DB_PASS = os.getenv("WORKMATE_DB_PASS", "")

_env_base_dir = os.getenv("BASE_DIR", "").strip()
_project_root_candidate = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)
_project_root_marker = os.path.join(_project_root_candidate, "serve.py")

# 默认使用当前项目根目录；仅在无法识别项目根目录时回退到 .env 的 BASE_DIR
if os.path.isfile(_project_root_marker):
    BASE_DIR = _project_root_candidate
elif _env_base_dir:
    BASE_DIR = os.path.normpath(_env_base_dir)
else:
    BASE_DIR = os.path.normpath(os.getcwd())


def resolve_env_file_path() -> Path:
    """Canonical `.env` path: install root (exe dir) when packaged, else project BASE_DIR."""
    override = os.environ.get("WORKMATE_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(BASE_DIR) / ".env"


# 路径配置，定义文件和目录的存储位置
MCP_CONFIG_PATH = f"{BASE_DIR}/config/mcp_servers.json"
MCP_OPERABLE_DIRS_CONFIG_PATH = f"{BASE_DIR}/config/mcp_operable_dirs.json"
SKILLS_DIR = f"{BASE_DIR}/skills"  # 技能目录
SKILLS_BASE_DIR = f"{BASE_DIR}/skills"  # 技能基础目录
USE_SANDBOX = os.getenv("USE_SANDBOX", "false").lower() == "true"  # 是否使用沙盒环境
# 可由环境变量覆盖（桌面壳可向子进程注入），默认 {BASE_DIR}/workspace
OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", "").strip() or os.path.join(
    BASE_DIR, "workspace"
)

# Admin 管理服务（admin_serve.py）：单一配置源，供 Desktop / MCP 协同 / cloud_client 使用。
# 覆盖方式（优先级从高到低）：
#   WORKMATE_ADMIN_API_BASE — 完整 origin 或已含 /api/admin 的 URL
#   WORKMATE_ADMIN_HOST + WORKMATE_ADMIN_PORT — 拼装 http://{host}:{port}
ADMIN_API_PATH = "/api/admin"
ADMIN_CLIENT_WS_PATH = f"{ADMIN_API_PATH}/client/ws"
WORKMATE_ADMIN_HOST = (
    os.getenv("WORKMATE_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
)
WORKMATE_ADMIN_PORT = int(os.getenv("WORKMATE_ADMIN_PORT", "8010") or "8010")


def get_admin_service_origin(url: Optional[str] = None) -> str:
    """Admin HTTP origin（无路径后缀），如 http://127.0.0.1:8010。"""
    raw = (url or os.getenv("WORKMATE_ADMIN_API_BASE", "")).strip().rstrip("/")
    if raw:
        if raw.endswith(ADMIN_API_PATH):
            return raw[: -len(ADMIN_API_PATH)].rstrip("/") or raw
        return raw
    return f"http://{WORKMATE_ADMIN_HOST}:{WORKMATE_ADMIN_PORT}"


def get_admin_api_base(url: Optional[str] = None) -> str:
    """Admin REST API 根路径，如 http://127.0.0.1:8010/api/admin。"""
    origin = get_admin_service_origin(url).rstrip("/")
    if origin.endswith(ADMIN_API_PATH):
        return origin
    return f"{origin}{ADMIN_API_PATH}"


def normalize_admin_api_base(url: Optional[str] = None) -> str:
    """将 Desktop/MCP 传入的 Admin 地址规范为 .../api/admin。"""
    return get_admin_api_base(url)


def normalize_admin_ws_url(raw_url: Optional[str] = None) -> str:
    """将 Admin HTTP/WS 地址规范为客户端 WebSocket URL。"""
    if not raw_url or not str(raw_url).strip():
        origin = get_admin_service_origin()
        return urlunparse(
            ("ws", urlparse(origin).netloc, ADMIN_CLIENT_WS_PATH, "", "", "")
        )

    raw_url = str(raw_url).strip()
    parsed = urlparse(raw_url if "://" in raw_url else f"http://{raw_url}")
    scheme_map = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}
    scheme = scheme_map.get((parsed.scheme or "http").lower(), parsed.scheme or "ws")
    path = (parsed.path or "").rstrip("/")
    if not path:
        path = ADMIN_CLIENT_WS_PATH
    elif not path.endswith(ADMIN_CLIENT_WS_PATH):
        if path.endswith(f"{ADMIN_API_PATH}/client"):
            path = ADMIN_CLIENT_WS_PATH
        elif path.endswith(ADMIN_API_PATH):
            path = ADMIN_CLIENT_WS_PATH
        else:
            path = f"{path}{ADMIN_CLIENT_WS_PATH}"
    netloc = parsed.netloc or f"{WORKMATE_ADMIN_HOST}:{WORKMATE_ADMIN_PORT}"
    return urlunparse((scheme, netloc, path, "", "", ""))


DEFAULT_ADMIN_WS_URL = normalize_admin_ws_url(None)


def _parse_dirs_csv(value: str) -> list[str]:
    return [d.strip() for d in value.split(",") if d and d.strip()]


def _load_mcp_operable_dirs() -> list[str]:
    """
    统一读取 MCP 可操作目录白名单：
    1) 优先读取 config/mcp_operable_dirs.json（便于打包后手动维护）
    2) 回退到 .env 的 MCP_READ_ALLOWED_DIRS（兼容旧配置）
    """
    try:
        if os.path.exists(MCP_OPERABLE_DIRS_CONFIG_PATH):
            with open(MCP_OPERABLE_DIRS_CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                dirs = loaded.get("operable_dirs", [])
                if isinstance(dirs, list):
                    normalized_dirs: list[str] = []
                    for item in dirs:
                        raw = str(item).strip()
                        if not raw:
                            continue
                        raw = raw.replace("${BASE_DIR}", BASE_DIR)
                        path = (
                            raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
                        )
                        normalized_dirs.append(os.path.normpath(path))
                    if normalized_dirs:
                        return normalized_dirs
    except Exception:
        pass

    _mcp_read_dirs = os.getenv("MCP_READ_ALLOWED_DIRS", "")
    if _mcp_read_dirs:
        return _parse_dirs_csv(_mcp_read_dirs)

    # 最终兜底：默认允许项目内 skills / workspace，便于开箱即用
    return [
        os.path.normpath(os.path.join(BASE_DIR, "skills")),
        os.path.normpath(os.path.join(BASE_DIR, "workspace")),
    ]


MCP_OPERABLE_DIRS = _load_mcp_operable_dirs()
# 保持旧变量名兼容，统一由 MCP_OPERABLE_DIRS 提供值
MCP_READ_ALLOWED_DIRS = MCP_OPERABLE_DIRS

MCP_WRITE_ALLOWED_DIRS = [OUTPUT_BASE_DIR]  # MCP 允许写入的目录


def _env_int(key: str, default: int) -> int:
    """Parse integer env vars safely; invalid values fall back to default."""
    raw = os.getenv(key)
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


# 记忆系统配置
MEMORY_SHORT_TERM_TASKS = _env_int(
    "MEMORY_SHORT_TERM_TASKS", 5
)  # 短期记忆保留的最近任务数
MEMORY_MID_TERM_TASKS = _env_int(
    "MEMORY_MID_TERM_TASKS", 45
)  # 中期记忆读取的最大摘要条数
MEMORY_ENABLE_TOPIC_SEARCH = (
    os.getenv("MEMORY_ENABLE_TOPIC_SEARCH", "true").lower() == "true"
)  # 是否开启基于主题的相关记忆搜索
MEMORY_RELEVANT_TASKS_LIMIT = _env_int(
    "MEMORY_RELEVANT_TASKS_LIMIT", 3
)  # 最大加载的相关历史记忆条数
MEMORY_SEARCH_CANDIDATE_LIMIT = _env_int(
    "MEMORY_SEARCH_CANDIDATE_LIMIT", 200
)  # 搜索候选摘要数量
MEMORY_COMPRESS_ENABLED = (
    os.getenv("MEMORY_COMPRESS_ENABLED", "true").lower() == "true"
)  # 是否开启对话压缩（超长对话自动压缩保留关键链路）
MEMORY_COMPRESS_THRESHOLD = _env_int(
    "MEMORY_COMPRESS_THRESHOLD", 10000
)  # 对话压缩的最小字符数阈值
AGENT_USERNAME = os.getenv(
    "USERNAME", ""
)  # 当前 Agent 实例的用户名，用于隔离多 Agent 的对话摘要
RUNLOOP_API_KEY = os.getenv("RUNLOOP_API_KEY", "")  # Runloop API Key
VENV_PYTHON = (
    os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
    if os.name == "nt"
    else os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")
)
VENV_PIP = (
    os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "pip.exe")
    if os.name == "nt"
    else os.path.join(os.path.dirname(__file__), ".venv", "bin", "pip")
)
IS_WINDOWS = os.name == "nt"
CACHE_SAVE_CONFIG = f"{BASE_DIR}/config/_cache.json"
WECHAT_CONFIG_PATH = f"{BASE_DIR}/config/wechat.json"
SUBAGENTS_CONFIG_PATH = os.path.join(
    BASE_DIR, os.getenv("SUBAGENTS_CONFIG_PATH", "config/subagents.json")
)
ENABLE_SUBAGENTS = os.getenv("ENABLE_SUBAGENTS", "true").lower() == "true"

# Post-task evaluation (preference extraction, skill create/improve)
POST_TASK_EVALUATION_ENABLED = (
    os.getenv("POST_TASK_EVALUATION_ENABLED", "true").lower() == "true"
)
POST_TASK_EVALUATION_PREFERENCE = (
    os.getenv("POST_TASK_EVALUATION_PREFERENCE", "true").lower() == "true"
)
POST_TASK_EVALUATION_SKILL_CREATE = (
    os.getenv("POST_TASK_EVALUATION_SKILL_CREATE", "true").lower() == "true"
)
POST_TASK_EVALUATION_SKILL_IMPROVE = (
    os.getenv("POST_TASK_EVALUATION_SKILL_IMPROVE", "true").lower() == "true"
)
POST_TASK_EVALUATION_LLM_TIMEOUT = _env_int("POST_TASK_EVALUATION_LLM_TIMEOUT", 30)


def _resolve_video_person_path() -> str:
    """优先从 TemplateCache 获取默认视频模板，fallback 到本地文件。"""
    try:
        from workflow.template_cache import get_template_cache

        cache = get_template_cache()
        if cache:
            template = cache.get_template_by_type_sync("0", category="video")
            if template and template.get("local_file_path"):
                return template["local_file_path"]
    except Exception:
        pass
    fallback = os.path.join(BASE_DIR, "template/video-template/金融主播.png")
    return fallback if os.path.exists(fallback) else ""


VIDEO_PERSON_FILE_PATH = _resolve_video_person_path()


def _load_wechat_config() -> dict:
    """从配置文件加载微信配置"""
    import json

    defaults = {
        "wechat_contacts": "File Transfer Assistant",
        "owner_name": "YourName",
        "check_interval": 60,
        "wechat_agent_base_url": "http://127.0.0.1:8009",
    }
    if not os.path.exists(WECHAT_CONFIG_PATH):
        return defaults
    try:
        with open(WECHAT_CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            defaults.update(loaded)
    except Exception:
        pass
    return defaults


_wechat_cfg = _load_wechat_config()

# WeChat Agent Configuration
WECHAT_CONTACTS = _wechat_cfg.get("wechat_contacts", "File Transfer Assistant")
OWNER_NAME = _wechat_cfg.get("owner_name", "YourName")
CHECK_INTERVAL = _wechat_cfg.get("check_interval", 180)
ALIAS_NAME = _wechat_cfg.get("alias_name", "Workmate")
WECHAT_AI_REPLY_PREFIX = os.getenv(
    "WECHAT_AI_REPLY_PREFIX",
    f"现在是{ALIAS_NAME}与您对话",
)

# 企业微信机器人配置
WECHAT_WORK_CORP_ID = os.getenv("WECHAT_WORK_CORP_ID", "")
WECHAT_WORK_AGENT_ID = os.getenv("WECHAT_WORK_AGENT_ID", "")
WECHAT_WORK_SECRET = os.getenv("WXWORK_SECRET") or os.getenv("WECHAT_WORK_SECRET", "")
WECHAT_WORK_BOT_ID = os.getenv("WXWORK_BOT_ID", "")
WECHAT_WORK_URL = os.getenv("WXWORK_URL", "")
WECHAT_WORK_TOKEN = os.getenv("WXWORK_TOKEN", "")
WECHAT_WORK_ENCODING_AES_KEY = os.getenv("WXWORK_ENCODIING_AES_KEY", "")
_wechat_work_allowed_users = os.getenv("WECHAT_WORK_ALLOWED_USERS", "")
WECHAT_WORK_ALLOWED_USERS = (
    [u.strip() for u in _wechat_work_allowed_users.split(",")]
    if _wechat_work_allowed_users
    else []
)
