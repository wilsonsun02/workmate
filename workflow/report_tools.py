from typing import List, Any
from typing import Dict, Optional, Tuple
import json
import asyncio
import mysql.connector
from mysql.connector import Error
import sys
from workflow.config import (
    REPORT_DB_HOST,
    REPORT_DB_DATABASE,
    REPORT_DB_USER,
    REPORT_DB_PASS,
    BASE_DIR,
    SKILLS_BASE_DIR,
    MEMORY_MID_TERM_TASKS,
    MEMORY_SHORT_TERM_TASKS,
)
import re
import os
from pathlib import Path
import contextvars
from workflow.config import MCP_CONFIG_PATH
from loguru import logger

# 技能自动创建/改进配置

# 用于隔离“对话摘要/长期偏好”等按用户分片的数据。
# 默认回退到 .env 里的 AGENT_USERNAME；但当上层（如桌面端）传入 username 时，
# 我们会在 stream_deep_agent 内把该 contextvar 设置为对应用户名，避免并发时写错。
agent_username_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_username_ctx", default=""
)


def _get_agent_username() -> str:
    v = agent_username_ctx.get().strip()
    if v:
        return v
    return os.getenv("USERNAME", "").strip() or os.getenv("AGENT_USERNAME", "").strip()


def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=REPORT_DB_HOST,
            user=REPORT_DB_USER,
            password=REPORT_DB_PASS,
            database=REPORT_DB_DATABASE,
        )
        return connection
    except Error as e:
        logger.info(f"Error connecting to MySQL: {e}")
        return None


def init_database_tables():
    """
    初始化数据库表，创建必要的表（如果不存在）。
    """
    connection = get_db_connection()
    if not connection:
        logger.info("数据库连接失败，无法初始化表")
        return False

    try:
        cursor = connection.cursor()

        # 创建 agent_execution_logs 表（如果不存在）
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS agent_execution_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            thread_id VARCHAR(255) NOT NULL,
            session_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(50) NOT NULL DEFAULT 'agent_step',
            step INT DEFAULT 0,
            content TEXT,
            tool_name VARCHAR(255),
            reasoning TEXT,
            created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_thread_id (thread_id(191)),
            INDEX idx_session_id (session_id(191)),
            INDEX idx_thread_session (thread_id(100), session_id(100)),
            INDEX idx_created_time (created_time)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """

        cursor.execute(create_table_sql)
        connection.commit()
        logger.info("数据库表初始化完成")
        return True

    except Exception as e:
        logger.info(f"初始化数据库表失败: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# 应用启动时自动初始化
init_database_tables()


def insert_agent_event(
    thread_id: str,
    session_id: str,
    event_type: str,
    step: int = 0,
    content: str = "",
    tool_name: str = None,
    reasoning: str = None,
) -> int:
    """
    插入 DeepAgent 执行事件到数据库。
    """
    connection = get_db_connection()
    if not connection:
        logger.info("数据库连接失败")
        return 0

    try:
        cursor = connection.cursor()

        query = """
            INSERT INTO agent_execution_logs
            (thread_id, session_id, event_type, step, content, tool_name, reasoning)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            thread_id,
            session_id,
            event_type,
            step,
            content,
            tool_name,
            reasoning,
        )

        cursor.execute(query, params)
        connection.commit()

        return cursor.lastrowid

    except Exception as e:
        logger.info(f"插入 Agent 执行事件失败: {e}")
        if connection.is_connected():
            connection.rollback()
        return 0
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def get_agent_events(
    thread_id: str, session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    获取 DeepAgent 执行事件历史
    """
    connection = get_db_connection()
    if not connection:
        return []

    try:
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT id, event_type, step, content, tool_name, reasoning, created_time
            FROM agent_execution_logs
            WHERE thread_id = %s
        """
        params = [thread_id]

        if session_id:
            query += " AND session_id = %s"
            params.append(session_id)

        query += " ORDER BY step ASC, created_time ASC"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        # 格式化时间
        for row in rows:
            if row.get("created_time"):
                row["created_time"] = row["created_time"].strftime("%Y-%m-%d %H:%M:%S")

        return rows

    except Exception as e:
        logger.info(f"获取 Agent 事件失败: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def clean_response_and_markdown(response: str) -> str:
    """清理语言模型输出，去除 <think>...</think> 标签及其内容"""
    cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL)
    cleaned = cleaned.strip()
    return cleaned


# langchain_mcp_adapters.create_session 会把 server_config 里除 transport 外的键原样 ** 传给各 transport 的构造函数。
# 若 HTTP 类配置里误带 stdio 字段（如 env、command），会报错：
# _create_streamable_http_session() got an unexpected keyword argument 'env'
_MCP_STDIO_KEYS = frozenset(
    {
        "command",
        "args",
        "env",
        "cwd",
        "encoding",
        "encoding_error_handler",
        "session_kwargs",
    }
)
_MCP_SSE_KEYS = frozenset(
    {
        "url",
        "headers",
        "timeout",
        "sse_read_timeout",
        "session_kwargs",
        "httpx_client_factory",
        "auth",
    }
)
_MCP_STREAMABLE_HTTP_KEYS = frozenset(
    {
        "url",
        "headers",
        "timeout",
        "sse_read_timeout",
        "terminate_on_close",
        "session_kwargs",
        "httpx_client_factory",
        "auth",
    }
)
_MCP_WEBSOCKET_KEYS = frozenset({"url", "session_kwargs"})


def sanitize_mcp_server_config(server_config: dict) -> dict:
    """
    按 transport 仅保留 langchain_mcp_adapters 支持的字段，避免脏配置导致连接失败。
    """
    if not server_config or not isinstance(server_config, dict):
        return server_config
    transport = server_config.get("transport")
    if not transport:
        return dict(server_config)

    key_sets = {
        "stdio": _MCP_STDIO_KEYS,
        "sse": _MCP_SSE_KEYS,
        "streamable_http": _MCP_STREAMABLE_HTTP_KEYS,
        "streamable-http": _MCP_STREAMABLE_HTTP_KEYS,
        "http": _MCP_STREAMABLE_HTTP_KEYS,
        "websocket": _MCP_WEBSOCKET_KEYS,
    }
    allowed = key_sets.get(str(transport))
    if allowed is None:
        return dict(server_config)

    return {k: v for k, v in server_config.items() if k == "transport" or k in allowed}


def rewrite_mcp_filesystem_stdio_dirs(server_config: dict) -> dict:
    """
    统一规范 MCPFilesystem 的 stdio args：
    - 始终使用当前环境的 BASE_DIR（不存在则回退本仓库根）作为 --directory
    - run_server.py 后的可操作目录由统一配置（workflow.config.MCP_OPERABLE_DIRS）生成
    - 同时兼容保留原配置中仍存在的额外目录，避免升级丢失已有可用路径
    """
    if not server_config or server_config.get("transport") != "stdio":
        return server_config
    args = list(server_config.get("args") or [])
    if "run_server.py" not in args:
        return server_config
    cmd = str(server_config.get("command") or "").strip()
    cmd_name = Path(cmd).name.lower() if cmd else ""
    if cmd_name not in ("uv", "uv.exe"):
        return server_config

    proj_dir: Path | None = None
    try:
        di = args.index("--directory")
        if di + 1 < len(args):
            proj_dir = Path(args[di + 1])
    except ValueError:
        proj_dir = None

    from workflow.config import BASE_DIR, MCP_OPERABLE_DIRS, OUTPUT_BASE_DIR

    repo_root = Path(__file__).resolve().parent.parent
    base_path = Path(BASE_DIR).expanduser()
    if not base_path.is_dir():
        base_path = repo_root
    base_path = base_path.resolve()

    # 正确格式: uv run run_server.py <dir1> <dir2>...
    new_args = ["run", "run_server.py"]
    seen: set[str] = set()

    def _add_dir(p: Path) -> None:
        try:
            if p.is_dir():
                r = str(p.resolve())
                if r not in seen:
                    seen.add(r)
                    new_args.append(r)
        except OSError:
            pass

    _add_dir(base_path)  # 必须把 BASE_DIR 作为第一个允许的目录
    _add_dir(base_path / "skills")
    _add_dir(base_path / "workspace")
    legacy_output = base_path / "output"
    if legacy_output.is_dir():
        _add_dir(legacy_output)
    try:
        _add_dir(Path(OUTPUT_BASE_DIR).expanduser().resolve())
    except OSError:
        pass
    _add_dir(base_path / "tools" / "wechat_attachments")
    for d in MCP_OPERABLE_DIRS:
        if d:
            _add_dir(Path(d))

    try:
        ri = args.index("run_server.py")
        for old in args[ri + 1 :]:
            if old and str(old).strip():
                _add_dir(Path(str(old)))
    except ValueError:
        pass

    out = dict(server_config)
    try:
        from workflow.config import get_admin_service_origin

        admin_origin = get_admin_service_origin().strip().rstrip("/")
        if admin_origin:
            child_env = dict(out.get("env") or {})
            child_env.setdefault("WORKMATE_ADMIN_API_BASE", admin_origin)
            out["env"] = child_env
    except Exception:
        pass
    # 打包模式：改为调用 serve.exe 自身的内置 MCPFilesystem 启动入口，
    # 避免依赖外部 uv / run_server.py / 源码目录。
    if getattr(sys, "frozen", False):
        embedded_args = [str(base_path), *new_args[4:]]
        out["command"] = str(Path(sys.executable).resolve())
        out["args"] = ["--run-mcp-filesystem-stdio", *embedded_args]
    else:
        out["args"] = new_args
    if proj_dir is not None and not proj_dir.is_dir():
        logger.info(
            f"[MCP] MCPFilesystem：原 --directory 无效 ({proj_dir!s})，"
            f"已改用本机项目根: {base_path}"
        )
    return out


def normalize_mcp_server_config(server_config: dict) -> dict:
    """清洗非法字段 + 修正失效的本机 MCP Filesystem stdio 路径。"""
    return rewrite_mcp_filesystem_stdio_dirs(sanitize_mcp_server_config(server_config))


def _load_mcp_servers_with_fallback() -> List[Dict[str, Any]]:
    """优先从数据库读取 MCP 配置，失败或为空时回退到本地配置文件。"""
    from admin_api.services.config_service import ConfigService

    servers_list = ConfigService.get_config("mcp_servers", [])
    if isinstance(servers_list, list) and servers_list:
        return servers_list

    if os.path.exists(MCP_CONFIG_PATH):
        try:
            with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                file_servers = json.load(f)
                if isinstance(file_servers, list):
                    logger.info(f"[MCP] 使用本地配置文件兜底: {MCP_CONFIG_PATH}")
                    return file_servers
        except Exception as e:
            logger.info(f"[MCP] 读取本地配置文件失败: {e}")

    return []


def load_skills_config_with_fallback() -> Dict[str, Any]:
    """优先从数据库读取 skills_config，失败或为空时回退到本地配置文件。"""
    from admin_api.services.config_service import ConfigService

    skills_config = ConfigService.get_config("skills_config", {})
    if isinstance(skills_config, dict) and skills_config:
        return skills_config

    default_skills_path = os.path.join(
        Path(MCP_CONFIG_PATH).parent, "skills_config.json"
    )
    for candidate in (default_skills_path,):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    if isinstance(file_config, dict):
                        logger.info(f"[Skills] 使用本地配置文件兜底: {candidate}")
                        return file_config
            except Exception as e:
                logger.info(f"[Skills] 读取本地配置文件失败: {e}")
    return {}


def _normalize_skills_config_map(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Flatten to { skill_name: { description, enabled } }."""
    if not isinstance(raw, dict):
        return {}
    node = raw.get("skills")
    if isinstance(node, dict):
        src = node
    else:
        src = {k: v for k, v in raw.items() if k != "skills" and isinstance(v, dict)}
    out: Dict[str, Dict[str, Any]] = {}
    for name, value in src.items():
        key = str(name)
        if isinstance(value, dict):
            out[key] = {
                "description": str(value.get("description", "") or ""),
                "enabled": bool(value.get("enabled", True)),
            }
        else:
            out[key] = {"description": "", "enabled": bool(value)}
    return out


def merge_skills_config_db_and_file() -> Dict[str, Any]:
    """
    Merge DB skills_config with local skills_config.json (AND per-skill enabled).

    Ensures desktop-written \"disabled\" (e.g. not in skill_market) is honored
    even when the DB still has global enabled=true.
    """
    from admin_api.services.config_service import ConfigService

    db_raw = ConfigService.get_config("skills_config", {}) or {}
    file_raw: Dict[str, Any] = {}
    default_skills_path = os.path.join(
        Path(MCP_CONFIG_PATH).parent, "skills_config.json"
    )
    if os.path.isfile(default_skills_path):
        try:
            with open(default_skills_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    file_raw = loaded
        except Exception as e:
            logger.info("[Skills] merge: read local file failed: {}", e)

    db_map = _normalize_skills_config_map(db_raw)
    file_map = _normalize_skills_config_map(file_raw)
    merged_skills: Dict[str, Dict[str, Any]] = {}
    for key in set(db_map) | set(file_map):
        d = db_map.get(key, {})
        f = file_map.get(key, {})
        merged_skills[key] = {
            "description": str(f.get("description") or d.get("description") or ""),
            "enabled": bool(d.get("enabled", True)) and bool(f.get("enabled", True)),
        }
    return {"skills": merged_skills}


def get_disabled_skills_with_fallback() -> set:
    """从 skills 配置中解析 disabled 集合，兼容两种结构；启用状态为 DB 与本地文件合并结果。"""
    raw = merge_skills_config_db_and_file()
    skills_node = raw.get("skills") if isinstance(raw, dict) else None
    source = skills_node if isinstance(skills_node, dict) else raw
    if not isinstance(source, dict):
        return set()

    disabled = set()
    for name, value in source.items():
        enabled = value
        if isinstance(value, dict):
            enabled = value.get("enabled", True)
        if not bool(enabled):
            disabled.add(name)
    return disabled


_SKILL_PATH_SEGMENT_RE = re.compile(r"(?i)skills[/\\]([A-Za-z0-9_.\-]+)")


def _skill_names_from_text(*fragments: Optional[str]) -> set[str]:
    """Match repo-relative `skills/<name>/...` segments inside arbitrary command strings."""
    names: set[str] = set()
    for frag in fragments:
        if not frag or not isinstance(frag, str):
            continue
        norm = frag.replace("\\", "/")
        for m in _SKILL_PATH_SEGMENT_RE.finditer(norm):
            names.add(m.group(1))
    return names


def build_skills_policy_notice_for_prompt(
    discovered_skills: List[Tuple[str, str]],
    final_available_skills: List[Tuple[str, str]],
) -> str:
    """
    Injected into SYSTEM.md / SUBSYSTEM.md as {{SKILLS_POLICY_NOTICE}}.

    ``discovered_skills`` must be the full list parsed from disk (before disabled
    and allow filters). ``final_available_skills`` is the list after both filters.
    """
    disabled = get_disabled_skills_with_fallback()
    discovered_names = {n for n, _ in discovered_skills}
    permitted = {n for n, _ in final_available_skills}
    names_disabled = sorted(n for n in discovered_names if n in disabled)
    enabled_by_cfg = {n for n in discovered_names if n not in disabled}
    perm_denied = sorted(enabled_by_cfg - permitted)

    parts: List[str] = []
    if names_disabled:
        joined = "、".join(f"`{n}`" for n in names_disabled)
        parts.append(
            "### 已在配置中停用的技能（本机 `skills_config.json` 与管理端合并后生效）\n"
            f"{joined}\n\n"
            "**必须遵守**：不得使用任何工具读取、列举或执行上述技能在 `skills/<技能名>/` 下的文件或命令；"
            "不得在回复中声称已成功使用这些技能完成任务。若用户点名其中一项，须明确告知该技能在本环境已停用，"
            "并给出不访问该技能目录的替代方案（可在允许的输出目录内交付其他形式的产出）。"
        )
    if perm_denied:
        joined = "、".join(f"`{n}`" for n in perm_denied)
        parts.append(
            "### 未对当前账号授权的技能（需在管理端 `sys_skill_permissions` 中配置为 allow）\n"
            f"{joined}\n\n"
            "**必须遵守**：不得访问其目录或执行其中脚本。若用户点名，须说明需管理员为该账号开通对应技能权限。"
        )
    return "\n\n".join(parts) if parts else ""


def _block_reason_for_skill_name(
    username: Optional[str], skill_name: str
) -> Optional[str]:
    """Shared policy: merged disabled list + explicit allow when DB user resolves."""
    if not skill_name or skill_name.startswith("_"):
        return None
    if skill_name in get_disabled_skills_with_fallback():
        return (
            f"技能目录「{skill_name}」已在配置中禁用或未对当前账号开放，"
            f"禁止通过工具访问。请在管理端开通权限并同步桌面配置。"
        )
    u = (username or "").strip()
    if not u:
        return None

    from workflow.permission_engine import PermissionEngine

    user_row = PermissionEngine._get_user_info(u)
    if not user_row:
        return None
    allowed = PermissionEngine.filter_skills_by_explicit_allow(u, [skill_name])
    if not allowed:
        return (
            f"技能「{skill_name}」未对当前账号授权（需在 sys_skill_permissions 中 allow），"
            f"禁止访问其目录下的文件或执行其中脚本。"
        )
    return None


def block_reason_for_skill_filesystem_path(
    username: Optional[str], tool_args: Any
) -> Optional[str]:
    """
    Enforce the same policy as the desktop UI for anything that touches a skill:

    - Path parameters pointing under SKILLS_DIR/<skillName>/
    - Command-line tools (e.g. execute_script) that embed ``skills/<name>/`` in
      ``command`` or ``cwd`` — the common bypass when path-only checks miss.

    Uses merged skills_config \"disabled\" plus explicit allow when the user
    exists in DB.
    """
    if not isinstance(tool_args, dict):
        return None

    from workflow.config import BASE_DIR, SKILLS_DIR

    skill_names: set[str] = set()
    for k in ("command", "cwd", "shell_command", "cmd", "arguments"):
        v = tool_args.get(k)
        if isinstance(v, str) and v.strip():
            skill_names |= _skill_names_from_text(v)

    target: Optional[str] = None
    for path_key in (
        "file_path",
        "path",
        "directory",
        "dir_path",
        "folder_path",
        "root_path",
        "target_file",
        "source_path",
        "src_path",
        "dest_path",
        "destination",
    ):
        v = tool_args.get(path_key)
        if v is not None and str(v).strip():
            target = str(v).strip().strip('"')
            break

    if target:
        path_raw = target.replace("/", os.sep)
        if not os.path.isabs(path_raw):
            candidate = os.path.join(BASE_DIR, path_raw)
        else:
            candidate = path_raw
        try:
            abs_target = os.path.normcase(
                os.path.realpath(os.path.abspath(os.path.expanduser(candidate)))
            )
            skills_abs = os.path.normcase(
                os.path.realpath(os.path.abspath(str(SKILLS_DIR)))
            )
        except OSError:
            abs_target = ""
            skills_abs = ""

        if skills_abs:
            sep = os.sep
            prefix = skills_abs.rstrip(sep) + sep
            if abs_target.rstrip(sep) == skills_abs.rstrip(sep):
                u_root = (username or "").strip()
                if u_root:
                    from workflow.permission_engine import PermissionEngine

                    if PermissionEngine._get_user_info(u_root):
                        return "禁止访问技能根目录；请仅访问已在管理端授权的具体技能子目录下的文件。"
            elif abs_target.startswith(prefix):
                try:
                    rel = os.path.relpath(abs_target, skills_abs)
                except ValueError:
                    rel = ""
                parts = rel.split(sep) if rel else []
                if parts and parts[0] not in (".", ""):
                    skill_names.add(parts[0])

    for sn in sorted(skill_names):
        br = _block_reason_for_skill_name(username, sn)
        if br:
            return br
    return None


def load_mcp_config():
    """加载 active 的服务器和 skills（数据库优先，本地文件兜底）。"""
    servers_list = _load_mcp_servers_with_fallback()

    active_servers = {}
    skills_list = []

    for item in servers_list:
        if item.get("is_load"):
            name = item["server_name"]
            # 组装为 RobustMultiServerMCPClient 需要的格式
            active_servers[name] = normalize_mcp_server_config(item["server_config"])
            # 收集技能说明
            if item.get("skills"):
                skills_list.append(f"### {name} 工具技能说明:\n{item['skills']}")

    return active_servers, "\n".join(skills_list)


def load_final_mcp_config() -> Tuple[Dict[str, Any], str, Dict[str, List[str]]]:
    """
    根据执行计划和配置文件，加载最终的 MCP 服务器配置及技能说明
    数据库优先加载配置；数据库为空时回退本地 mcp_servers.json；
    仅根据 mcp_servers 中的 is_load 标识决定是否加载

    返回:
        final_servers: 可加载的服务配置 {server_name: server_config}
        final_skills_list: 技能说明字符串
        available_tools: 可加载的工具 {server_name: [tool_name1, tool_name2, ...]}
    """
    # 1. 数据库优先，本地文件兜底
    servers_list = _load_mcp_servers_with_fallback()

    # 建立所有活跃配置的快速索引: {server_name: full_item}
    active_configs_map = {
        item["server_name"]: item for item in servers_list if item.get("is_load")
    }

    # 2. 直接返回所有 is_load 为 true 的服务器配置
    final_servers = {}
    final_skills_list = []
    available_tools = {}

    for s_name, item in active_configs_map.items():
        # 组装 RobustMultiServerMCPClient 需要的格式
        final_servers[s_name] = normalize_mcp_server_config(item["server_config"])

        # 收集技能说明
        if item.get("skills"):
            final_skills_list.append(f"## {s_name} 工具技能说明:\n{item['skills']}")

        # 收集可加载的工具（根据每个工具的 is_load 字段过滤）
        tools = item.get("tools", [])
        loadable_tool_names = [
            t.get("tool_name")
            for t in tools
            if t.get("is_load", True) and t.get("tool_name")
        ]
        available_tools[s_name] = loadable_tool_names

    logger.info("final_servers: ", final_servers)
    logger.info("available_tools: ", available_tools)
    return final_servers, "\n".join(final_skills_list), available_tools


def create_conversation_summaries_table():
    """创建对话摘要表，并兼容旧表自动补充 username 字段"""
    connection = get_db_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL DEFAULT '',
                thread_id VARCHAR(255) NOT NULL,
                summary TEXT,
                last_sequence_number INT DEFAULT 0,
                last_chat_index INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_username_thread (username, thread_id(100)),
                INDEX idx_thread_id (thread_id(191))
            )
        """)
        # 兼容旧表：若 username 列不存在则自动添加
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversation_summaries' AND COLUMN_NAME = 'username'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE conversation_summaries ADD COLUMN username VARCHAR(100) NOT NULL DEFAULT '' AFTER id"
            )
            cursor.execute(
                "ALTER TABLE conversation_summaries ADD INDEX idx_username_thread (username, thread_id)"
            )
        # 兼容旧表：若 compressed_conversation 列不存在则自动添加
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversation_summaries' AND COLUMN_NAME = 'compressed_conversation'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE conversation_summaries ADD COLUMN compressed_conversation MEDIUMTEXT DEFAULT NULL "
                "COMMENT 'LLM压缩后的对话，保留关键决策和结论，去除冗余细节'"
            )
        connection.commit()
    except Error as e:
        logger.info(f"创建 conversation_summaries 表失败: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def save_conversation_summary(
    thread_id: str,
    summary: str,
    last_seq: int,
    last_chat_idx: int,
    checkpoint_session_id: str = None,
    full_conversation: str = None,
    compressed_conversation: str = None,
):
    """保存新的会话摘要，agent_username 从 .env AGENT_USERNAME 读取，用于隔离多 Agent 实例的上下文
    - checkpoint_session_id: Checkpoint DB中对应的session标识（通常就是thread_id）
    - full_conversation: 完整对话内容，将直接存储到 MySQL 表中
    - compressed_conversation: LLM压缩后的对话，保留关键决策和结论
    """
    agent_username = _get_agent_username()
    connection = get_db_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        sql = """
            INSERT INTO conversation_summaries (username, thread_id, summary, last_sequence_number, last_chat_index, checkpoint_session_id, full_conversation, compressed_conversation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        session_id = (
            checkpoint_session_id
            if (
                checkpoint_session_id is not None
                and checkpoint_session_id.strip() != ""
            )
            else thread_id
        )
        cursor.execute(
            sql,
            (
                agent_username,
                thread_id,
                summary,
                last_seq,
                last_chat_idx,
                session_id,
                full_conversation,
                compressed_conversation,
            ),
        )
        connection.commit()
        logger.info(
            f"[记忆] 已保存对话摘要 - thread_id: {thread_id}, 完整对话长度: {len(full_conversation) if full_conversation else 0}, 压缩对话长度: {len(compressed_conversation) if compressed_conversation else 0}"
        )
    except Error as e:
        logger.info(f"[记忆] 保存会话摘要失败: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


async def load_full_conversation_from_checkpoint(
    thread_id: str, checkpoint_session_id: str = None
) -> str:
    """
    从 Checkpoint DB 加载最近一个任务的完整对话，包括所有中间步骤。

    Args:
        thread_id: 线程 ID
        checkpoint_session_id: 检查点会话 ID（即 checkpoint_ns）

    Returns:
        格式化后的完整对话字符串
    """
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from workflow.config import BASE_DIR

    checkpoint_db = os.path.join(BASE_DIR, "checkpoints", "checkpoints.db")
    if not os.path.exists(checkpoint_db):
        logger.info(f"[记忆] Checkpoint DB 不存在: {checkpoint_db}")
        return ""

    try:
        conn = await aiosqlite.connect(checkpoint_db)
        checkpointer = AsyncSqliteSaver(conn)

        config = {"configurable": {"thread_id": thread_id}}

        messages = []
        try:
            async for item in checkpointer.alist(config):
                channel_values = item.checkpoint.get("channel_values", {})
                msgs = channel_values.get("messages", [])
                if msgs:
                    messages = msgs
                    break
        finally:
            await conn.close()

        if not messages:
            logger.info(f"[记忆] Checkpoint DB 中未找到消息 - thread_id: {thread_id}")
            return ""

        # 参考 trim_by_tasks 的逻辑，只提取最近一个任务的对话
        # 任务边界定义：从 HumanMessage 开始，到下一个 HumanMessage 之前结束
        human_msg_indices = [
            i for i, msg in enumerate(messages) if type(msg).__name__ == "HumanMessage"
        ]

        if not human_msg_indices:
            logger.info(f"[记忆] 未找到任务起始点 (HumanMessage)")
            return ""

        # 获取最后一个任务的边界
        last_task_start = human_msg_indices[-1]

        # 最后一个任务：从最后一个 HumanMessage 到列表末尾
        last_task_end = len(messages)

        # 提取最后一个任务的消息
        task_messages = messages[last_task_start:last_task_end]

        formatted_conv = []
        for msg in task_messages:
            msg_type = type(msg).__name__
            content = str(msg.content) if hasattr(msg, "content") else ""

            role = "用户" if msg_type == "HumanMessage" else "AI"

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls_str = []
                for tc in msg.tool_calls:
                    tc_name = tc.get("name", "")
                    tc_args = tc.get("args", {})
                    tool_calls_str.append(
                        f"[{role}] 曾调用工具: {tc_name}\n    参数: {tc_args}"
                    )
                formatted_conv.append("\n".join(tool_calls_str))
            elif hasattr(msg, "tool_call_id") and msg.tool_call_id:
                tool_output = f"[{role}] 工具返回结果: {content}"
                formatted_conv.append(tool_output)
            else:
                formatted_conv.append(f"[{role}] {content}")

        conv_text = "\n".join(formatted_conv)
        logger.info(
            f"[记忆] 从 Checkpoint DB 加载最近任务对话成功 - 原始 {len(messages)} 条，提取 {len(task_messages)} 条，长度: {len(conv_text)}"
        )
        return conv_text

    except Exception as e:
        logger.info(f"[记忆] 从 Checkpoint DB 加载失败: {e}")
        import traceback

        logger.info(f"[记忆] 错误堆栈: {traceback.format_exc()}")
        return ""


def get_recent_full_conversations(limit: int = 5) -> str:
    """
    获取用户最近的完整对话记录，作为短期记忆注入 system_prompt。
    从 MySQL conversation_summaries 表的 full_conversation 字段读取，
    仅按 username 过滤，按 created_at DESC 取最近 limit 条。

    Args:
        limit: 返回的最大记录数（默认 5）

    Returns:
        格式化后的短期记忆字符串（用分隔标记包裹）
    """
    agent_username = _get_agent_username()

    connection = get_db_connection()
    if not connection:
        return ""

    try:
        cursor = connection.cursor()
        sql = """
            SELECT thread_id, full_conversation, compressed_conversation, summary, created_at
            FROM conversation_summaries
            WHERE username = %s
              AND (full_conversation IS NOT NULL AND full_conversation != '')
            ORDER BY created_at DESC
            LIMIT %s
        """
        cursor.execute(sql, (agent_username, limit))
        rows = cursor.fetchall()

        if not rows:
            logger.info("[短期记忆] 未找到完整对话记录")
            return ""

        # 反转列表，让展示顺序为时间从远到近
        rows.reverse()

        header = "=" * 60
        parts = [
            f"{header}",
            f"** [短期记忆 Short-Term Memory] 最近{len(rows)}个任务的完整对话 **",
            f"{header}",
        ]
        for idx, row in enumerate(rows, 1):
            thread_id_val = row[0]
            full_conv = row[1] or ""
            compressed_conv = row[2] or ""
            summary = row[3] or ""
            created_at = row[4]
            # 优先使用压缩版对话，回退到完整对话
            conversation = compressed_conv if compressed_conv else full_conv
            is_compressed = bool(compressed_conv)
            time_str = (
                created_at.strftime("%Y-%m-%d %H:%M:%S")
                if hasattr(created_at, "strftime")
                else str(created_at)
            )
            parts.append(f"  [短期任务 {idx}] [{time_str}]: ")
            if summary:
                parts.append(f"  [摘要] {summary}")
            parts.append(f"  [压缩对话]" if is_compressed else f"  [完整对话]")
            parts.append(f"  {conversation}")
        parts.append(f"{header}")
        parts.append(f"** [END 短期记忆 Short-Term Memory] **")
        parts.append(f"{header}")

        result_str = "\n".join(parts)
        logger.info(
            f"[短期记忆] 已加载 {len(rows)} 条对话（其中压缩版: {sum(1 for r in rows if r[2])} 条）"
        )
        return result_str

    except Exception as e:
        logger.info(f"[短期记忆] 获取完整对话失败: {e}")
        return ""
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def get_recent_summaries_by_username(
    contact_name: str = "", limit: int = None, offset: int = None
) -> str:
    """
    查询指定用户的对话摘要，作为中期记忆注入 system_prompt。
    - agent_username 从 .env AGENT_USERNAME 读取，用于隔离不同 Agent 实例的数据
    - 仅按 username 过滤，不再限制 thread_id（参考相关记忆搜索逻辑）
    - 读取最近 limit 条摘要，默认读取 MEMORY_MID_TERM_TASKS 条
    返回空字符串表示无摘要或查询失败。
    """
    if limit is None:
        limit = MEMORY_MID_TERM_TASKS
    if offset is None:
        offset = 0

    agent_username = _get_agent_username()

    connection = get_db_connection()
    if not connection:
        return ""

    try:
        cursor = connection.cursor()
        sql = """
            SELECT summary, created_at, thread_id FROM conversation_summaries
            WHERE username = %s AND summary IS NOT NULL AND summary != ''
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(sql, (agent_username, limit, offset))
        rows = cursor.fetchall()

        if not rows:
            return ""

        # 反转列表，让展示顺序为时间从远到近
        rows.reverse()

        header = "=" * 60
        parts = [
            f"{header}",
            f"\n** [中期记忆 Mid-Term Memory] 最近{limit}个任务的概要，共 {len(rows)} 条 **",
            f"{header}",
        ]
        for row in rows:
            summary = row[0]
            created_at = row[1]
            thread_id_val = row[2]
            if summary:
                time_str = (
                    created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if hasattr(created_at, "strftime")
                    else str(created_at)
                )
                parts.append(f"- [{time_str}] [会话: {thread_id_val}] {summary}")
        parts.append(f"{header}")
        parts.append(f"\n** [END 中期记忆 Mid-Term Memory] **\n")
        parts.append(f"{header}")
        return "\n".join(parts)

    except Exception as e:
        logger.info(f"[记忆] 获取近期摘要失败: {e}")
        return ""
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# ── 完整对话压缩 ──────────────────────────────────────────────

_COMPRESS_PROMPT = """你是一个对话压缩专家。请将以下历史对话压缩为精简版，保留任务的完整执行链路。

1. 必须保留的内容（任务执行链路）：
   - 触发：用户的原始需求、意图和关键约束
   - 思考：AI 的关键分析判断和方案选择理由
   - 执行：调用了哪些工具、工具的关键参数（仅影响结果的关键参数）、工具返回的核心结论
   - 调用链：工具之间的调用顺序和依赖关系（如：先读取文件→再分析→最后写入）
   - 结论：AI 的最终输出结果和决策

2. 应当去除的内容（冗余噪声）：
   - 工具返回值中的冗长原始数据（如完整文件内容、长列表），仅保留结论性描述
   - 重复的确认和寒暄
   - 调试过程中的无效试错（如参数格式错误→修正→再调用，仅保留最终成功的调用）
   - AI 的冗长推理过程，压缩为一句关键判断

3. 格式要求：
   - 按任务阶段组织，每个阶段包含：触发→思考→执行→结论
   - 工具调用格式：[调用 工具名(关键参数)] → 核心结论
   - 压缩后总长度不超过原长的 40%

原始对话：
{conversation}

压缩后的对话："""


async def _compress_conversation(conversation: str, user_input: str) -> str:
    """使用 LLM 压缩完整对话，保留任务执行链路，去除冗余细节

    Args:
        conversation: 原始完整对话文本
        user_input: 用户原始输入（用于日志追踪）

    Returns:
        压缩后的对话文本；压缩失败或未缩短时返回原文
    """
    try:
        from workflow.model import mcp_llm
        from langchain_core.messages import HumanMessage

        prompt = _COMPRESS_PROMPT.format(conversation=conversation)
        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        compressed = response.content.strip()

        if compressed and len(compressed) < len(conversation):
            ratio = len(compressed) / len(conversation) * 100
            logger.info(
                f"[记忆压缩] 压缩完成 | 用户输入: {user_input[:50]} | "
                f"原始: {len(conversation)} 字符 | 压缩后: {len(compressed)} 字符 | 压缩率: {ratio:.1f}%"
            )
            return compressed
        else:
            logger.info(
                f"[记忆压缩] 压缩后未缩短，使用原文 | 原始: {len(conversation)} 字符"
            )
            return conversation
    except Exception as e:
        logger.info(f"[记忆压缩] 压缩失败，使用原文: {e}")
        return conversation


async def generate_and_save_summary(
    thread_id: str,
    user_input: str,
    ai_reply: str,
    checkpoint_session_id: str = None,
    full_conversation: str = None,
):
    """
    异步调用 LLM 生成对话摘要并写入 conversation_summaries 表。
    在 stream_deep_agent 结束后通过 asyncio.create_task 调用，不阻塞主流程。
    agent_username 从 .env AGENT_USERNAME 读取，用于隔离多 Agent 实例的数据。
    checkpoint_session_id: Checkpoint DB 对应的 session ID（通常就是 thread_id）
    full_conversation: 完整对话内容，将直接存储到 MySQL 表中
    """
    try:
        from workflow.model import mcp_llm
        from langchain_core.messages import HumanMessage
        from workflow.config import MEMORY_COMPRESS_ENABLED, MEMORY_COMPRESS_THRESHOLD

        prompt = (
            f"请用一段文字（不超过300字）概括以下对话的核心内容，重点保留用户的需求、决策和关键结论：\n\n"
            f"用户：{user_input}\n"
            f"AI：{ai_reply}\n\n"
            f"摘要："
        )
        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        summary_text = response.content.strip()

        # 压缩完整对话：超过阈值时调用 LLM 压缩，保留任务执行链路
        compressed_conv = None
        if (
            full_conversation
            and MEMORY_COMPRESS_ENABLED
            and len(full_conversation) > MEMORY_COMPRESS_THRESHOLD
        ):
            compressed_conv = await _compress_conversation(
                full_conversation, user_input
            )
            logger.info(
                f"[记忆压缩] 完整对话已压缩 | 原始: {len(full_conversation)} 字符 | "
                f"压缩后: {len(compressed_conv)} 字符"
            )
        elif full_conversation:
            # 短对话无需压缩，直接使用原文
            compressed_conv = full_conversation

        if summary_text:
            await asyncio.to_thread(
                save_conversation_summary,
                thread_id,
                summary_text,
                0,
                0,
                checkpoint_session_id,
                full_conversation,
                compressed_conversation=compressed_conv,
            )
            logger.info(
                f"[记忆] 已生成并保存对话摘要和完整对话, 摘要长度: {len(summary_text)}, 完整对话长度: {len(full_conversation) if full_conversation else 0}, 压缩对话长度: {len(compressed_conv) if compressed_conv else 0}"
            )

    except Exception as e:
        logger.info(f"[记忆] 生成摘要失败，跳过: {e}")


def create_user_preferences_table():
    """创建用户长期偏好表，仿照 conversation_summaries 设计，便于查询与监控"""
    connection = get_db_connection()
    if not connection:
        return
    try:
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INT AUTO_INCREMENT PRIMARY KEY,
                agent_username VARCHAR(100) NOT NULL DEFAULT '',
                contact_name VARCHAR(255) NOT NULL DEFAULT '',
                pref_key VARCHAR(255) NOT NULL,
                pref_value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_agent_contact_key (agent_username(70), contact_name(70), pref_key(50)),
                INDEX idx_agent_contact (agent_username, contact_name(100))
            )
        """)
        connection.commit()
    except Error as e:
        logger.info(f"创建 user_preferences 表失败: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def save_user_preference(contact_name: str, pref_key: str, pref_value: str):
    """写入或更新一条用户偏好记录（upsert），agent_username 来自 .env AGENT_USERNAME"""
    create_user_preferences_table()
    agent_username = _get_agent_username()
    connection = get_db_connection()
    if not connection:
        return
    try:
        cursor = connection.cursor()
        sql = """
            INSERT INTO user_preferences (agent_username, contact_name, pref_key, pref_value)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE pref_value = VALUES(pref_value), updated_at = NOW()
        """
        cursor.execute(sql, (agent_username, contact_name, pref_key, pref_value))
        connection.commit()
    except Error as e:
        logger.info(f"[长期记忆] 保存偏好失败: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def get_user_preferences(contact_name: str) -> str:
    """读取指定联系人的所有长期偏好，返回格式化字符串注入 system_prompt"""
    create_user_preferences_table()
    agent_username = _get_agent_username()
    connection = get_db_connection()
    if not connection:
        return ""
    try:
        cursor = connection.cursor()
        sql = """
            SELECT pref_key, pref_value FROM user_preferences
            WHERE agent_username = %s AND contact_name = %s
            ORDER BY updated_at DESC
        """
        cursor.execute(sql, (agent_username, contact_name))
        rows = cursor.fetchall()
        if not rows:
            return ""
        header = "=" * 60
        parts = [
            "",
            f"{header}",
            f"[长期记忆 Long-Term Memory] 用户偏好与习惯",
            f"{header}",
        ]
        for key, value in rows:
            if value:
                parts.append(f"- **{key}**: {value} ")
        parts.append(f"\n {header}")
        parts.append(f"\n [END 长期记忆 Long-Term Memory] \n")
        parts.append(f"{header}")
        parts.append("")
        return "\n".join(parts)
    except Exception as e:
        logger.info(f"[长期记忆] 读取偏好失败: {e}")
        return ""
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# 尝试创建表
create_conversation_summaries_table()
create_user_preferences_table()

if __name__ == "__main__":
    # results_list = get_event_result_by_thread_id("20260213_200202")
    # logger.info(results_list)
    load_final_mcp_config()


async def extract_search_keywords(user_input: str) -> list[str]:
    """
    使用 LLM 从用户输入中提取搜索关键词，包括任务关键词和任务类型。

    Args:
        user_input: 用户的原始输入文本

    Returns:
        提取到的关键词列表（用于搜索）
    """
    from workflow.model import mcp_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    logger.info(f"[关键词提取] 开始从用户输入中提取关键词")
    logger.info(f"[关键词提取] 用户输入: {user_input[:200]}...")

    system_prompt = """你是一个专业的关键词提取助手。请从用户的任务描述中提取2-5个搜索关键词，用于搜索历史对话。

要求：
1. 提取任务关键词（核心主题）
2. 提取任务类型（如：编写报告、分析数据、生成图表等）
3. 返回格式：仅返回关键词，用逗号分隔，不要其他内容

示例：
输入："编写一篇关于美伊战争的报告"
输出：美伊战争,编写报告

输入："帮我分析一下上个月的销售数据"
输出：销售数据,数据分析"""

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"用户输入：{user_input}\n请提取关键词："),
        ]

        response = await mcp_llm.ainvoke(messages)
        keyword_text = response.content.strip()

        # 解析关键词
        keywords = []
        if keyword_text:
            # 按逗号或空格分割
            import re

            parts = re.split(r"[,\s]+", keyword_text)
            keywords = [k.strip() for k in parts if k.strip()]

        # 最多保留5个关键词
        keywords = keywords[:5]

        logger.info(f"[关键词提取] 提取到的关键词: {keywords}")
        return keywords

    except Exception as e:
        logger.info(f"[关键词提取] 提取失败: {e}")
        import traceback

        logger.info(f"[关键词提取] 错误堆栈: {traceback.format_exc()}")
        # 失败时直接使用原输入作为关键词
        return [user_input[:100]]


async def match_relevant_summaries_with_llm(
    user_task: str,
    summaries_list: list[dict],
    limit: int = 3,
    checkpoint_thread_ids: set = None,
) -> list[dict]:
    """
    使用 LLM 评分制从摘要列表中找出与当前任务相关的摘要。
    每条候选由 LLM 打分（0-10），仅返回达到最低相关性阈值的摘要。

    Args:
        user_task: 当前用户的任务描述
        summaries_list: 摘要列表，每个元素包含 id, summary, thread_id, created_at
        limit: 返回的最大相关摘要数
        checkpoint_thread_ids: Checkpoint DB 中存在的 thread_id 集合，用于标注

    Returns:
        达到评分阈值的摘要列表（按相关性评分降序）
    """
    from workflow.model import mcp_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    _RELEVANCE_THRESHOLD = 5

    logger.info(f"[LLM 匹配] 开始评分制匹配，用户任务: {user_task[:200]}...")
    logger.info(f"[LLM 匹配] 待匹配的摘要数量: {len(summaries_list)}")

    if not summaries_list:
        return []

    checkpoint_thread_ids = checkpoint_thread_ids or set()

    summaries_text = []
    for idx, s in enumerate(summaries_list):
        summary_text = s.get("summary", "")[:500]
        thread_id = s.get("thread_id", "")
        in_checkpoint = "✓完整对话" if thread_id in checkpoint_thread_ids else "✗仅摘要"
        summaries_text.append(
            f"[摘要 {idx + 1}][{in_checkpoint}]\n内容: {summary_text}"
        )

    summaries_joined = "\n\n".join(summaries_text)

    system_prompt = """你是一个严格的历史对话匹配助手。请对每条候选摘要与当前任务的相关性进行评分。

评分标准（0-10 分）：
- 8-10：高度相关（任务主题、领域、目标高度一致）
- 5-7：部分相关（有共同关键词或类似场景，但核心任务不同）
- 1-4：弱相关（仅有零星词汇重叠，实质内容无关）
- 0：完全不相关

重要规则：
1. 为每条摘要独立评分，不要因为必须返回结果而虚高打分
2. 仅凭单个共享关键词（如"AI"、"报告"、"文件"）不足以判定相关，必须语义层面实质相关
3. 优先选择标记为[✓完整对话]的摘要，如有完整对话且相关，可适当提高 1 分

返回格式：每行一个 "序号: 分数"，仅输出这些行，不要其他内容。示例：
1: 8
3: 6
5: 0

如果没有达到 5 分的摘要，输出一行 "NONE" 即可。"""

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=f"当前任务：{user_task}\n\n历史摘要列表：\n{summaries_joined}\n\n请为每条摘要独立评分："
            ),
        ]

        response = await mcp_llm.ainvoke(messages)
        result_text = response.content.strip()

        logger.info(f"[LLM 匹配] LLM 返回评分: {result_text}")

        if result_text.upper() == "NONE" or result_text == "":
            logger.info("[LLM 匹配] LLM 判定无相关摘要")
            return []

        import re

        scored = []
        for line in result_text.split("\n"):
            line = line.strip()
            match = re.match(r"(\d+)\s*[:：]\s*(\d+)", line)
            if match:
                idx = int(match.group(1))
                score = int(match.group(2))
                if 1 <= idx <= len(summaries_list) and score >= _RELEVANCE_THRESHOLD:
                    scored.append((idx - 1, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        matched_summaries = []
        for idx, score in scored:
            matched_summaries.append(summaries_list[idx])
            logger.info(f"[LLM 匹配] 入选摘要 {idx + 1}，评分: {score}")
            if len(matched_summaries) >= limit:
                break

        if not matched_summaries:
            logger.info(f"[LLM 匹配] 所有摘要评分均低于阈值 {_RELEVANCE_THRESHOLD}")
        else:
            logger.info(f"[LLM 匹配] 找到 {len(matched_summaries)} 条达阈值摘要")

        return matched_summaries

    except Exception as e:
        logger.info(f"[LLM 匹配] 匹配失败: {e}")
        import traceback

        logger.info(f"[LLM 匹配] 错误堆栈: {traceback.format_exc()}")
        return summaries_list[:limit]


async def search_relevant_summaries_by_topic(
    topic: str, limit: int = 3, exclude_latest: int = 5
) -> str:
    """
    基于主题搜索相关的完整对话历史（异步版本）：
    1. 从 MySQL conversation_summaries 表中查询最近 200 条摘要
    2. 用 LLM 匹配出与当前任务最相关的 limit 条摘要
    3. 从 SQLite Checkpoint DB 中加载对应的完整对话
    4. 返回格式化的完整记忆内容

    Args:
        topic: 搜索主题（通常是当前用户输入）
        limit: 返回的最大相关记忆条数
        exclude_latest: 跳过的最近任务数（避免与短期记忆重复）

    Returns:
        格式化后的相关记忆字符串（用 XML 标签包裹）
    """
    if not topic or not topic.strip():
        return ""

    agent_username = _get_agent_username()
    from workflow.config import MEMORY_SEARCH_CANDIDATE_LIMIT

    # 第一步：从 MySQL 查询最近 N 条摘要
    recent_summaries = []
    connection = get_db_connection()
    if not connection:
        logger.info("[记忆搜索] 数据库连接失败")
        return ""

    # 不再硬编码上限，直接使用用户配置的 MEMORY_SEARCH_CANDIDATE_LIMIT
    candidate_limit = MEMORY_SEARCH_CANDIDATE_LIMIT

    try:
        cursor = connection.cursor(dictionary=True)

        sql = f"""
            SELECT id, summary, thread_id, checkpoint_session_id, full_conversation, compressed_conversation, created_at
            FROM conversation_summaries
            WHERE username = %s
            AND summary IS NOT NULL
            AND summary != ''
            ORDER BY created_at DESC
            LIMIT {candidate_limit} OFFSET %s
        """

        cursor.execute(sql, (agent_username, exclude_latest))
        rows = cursor.fetchall()

        if not rows:
            logger.info(
                f"[记忆搜索] 未找到历史摘要 (username={agent_username}, limit={candidate_limit}, offset={exclude_latest})"
            )
            return ""

        recent_summaries = rows
        logger.info(f"[记忆搜索] 查询到 {len(rows)} 条摘要 (username={agent_username})")
    except Exception as e:
        logger.info(f"[记忆搜索] 查询摘要失败: {e}")
        return ""
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    # 独立步骤：从 Checkpoint DB 中提取已存在对话的 thread_id 集合
    # 用于在 LLM 匹配时标注哪些摘要有完整对话可加载
    checkpoint_thread_ids = set()
    try:
        import aiosqlite
        from workflow.config import BASE_DIR

        _checkpoint_db = os.path.join(BASE_DIR, "checkpoints", "checkpoints.db")
        if os.path.exists(_checkpoint_db):
            conn_cp = await aiosqlite.connect(_checkpoint_db)
            cursor_cp = await conn_cp.execute(
                "SELECT DISTINCT thread_id FROM checkpoints GROUP BY thread_id"
            )
            rows_cp = await cursor_cp.fetchall()
            await conn_cp.close()

            checkpoint_thread_ids = set(row[0] for row in rows_cp if row[0])
            logger.info(
                f"[记忆搜索] Checkpoint DB 中有 {len(checkpoint_thread_ids)} 个 thread_id"
            )
        else:
            logger.info(f"[记忆搜索] Checkpoint DB 不存在: {_checkpoint_db}")
    except Exception as e:
        logger.info(f"[记忆搜索] 读取 Checkpoint DB thread_id 失败: {e}")

    # 第二步：用 LLM 匹配出最相关的摘要
    matched_summaries = await match_relevant_summaries_with_llm(
        user_task=topic,
        summaries_list=recent_summaries,
        limit=limit,
        checkpoint_thread_ids=checkpoint_thread_ids,
    )

    if not matched_summaries:
        logger.info(f"[记忆搜索] 未匹配到相关摘要")
        return ""

    # 第三步：从 MySQL 直接读取对话（优先使用压缩版）
    final_results = []

    for thread_info in matched_summaries:
        thread_id = thread_info.get("thread_id", "")
        summary = thread_info.get("summary", "")
        created_at = thread_info.get("created_at", "")
        full_conversation = thread_info.get("full_conversation", None)
        compressed_conversation = thread_info.get("compressed_conversation", None)

        # 优先使用压缩版对话，回退到完整对话
        conversation = (
            compressed_conversation if compressed_conversation else full_conversation
        )
        is_compressed = bool(compressed_conversation)
        date_str = (
            created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "未知时间"
        )

        if conversation and conversation.strip():
            final_results.append(
                {
                    "thread_id": thread_id,
                    "date": date_str,
                    "summary": summary,
                    "conversation": conversation,
                    "is_compressed": is_compressed,
                }
            )
        else:
            final_results.append(
                {
                    "thread_id": thread_id,
                    "date": date_str,
                    "summary": summary,
                    "conversation": None,
                    "is_compressed": False,
                }
            )

    if not final_results:
        logger.info(f"[记忆搜索] 未找到相关记忆")
        return ""

    # 按时间从远到近排序（最早的在前面）
    if final_results:
        final_results.sort(key=lambda x: x["date"])

    header = "=" * 60
    sep = "-" * 60
    parts = [
        f"{header}",
        f"** [相关历史记忆 Relevant-Historical-Memory] 与当前任务相关的历史任务，共 {len(final_results)} 条 **",
        f"{header}",
        f"<relevant_historical_memory>",
    ]
    for idx, result in enumerate(final_results, 1):
        parts.append(f"\n")
        parts.append(f"{sep}\n")
        parts.append(
            f"[相关历史 {idx}] [{result['date']}] [会话: {result['thread_id']}]"
        )
        parts.append(f"\n{sep}\n")
        # parts.append(f"[摘要] {result['summary']}")
        if result.get("conversation"):
            conv_label = "[压缩对话]" if result.get("is_compressed") else "[完整对话]"
            parts.append(f"[{conv_label}]")
            parts.append(f"{result['conversation']}")
        else:
            parts.append(f"[注] 仅摘要，无完整对话")

    parts.append(f"")
    parts.append("</relevant_historical_memory>")
    parts.append(f"{header}")
    parts.append(f"** [END 相关历史记忆 Relevant-Historical-Memory] **")
    parts.append(f"{header}")

    result_str = "\n".join(parts)
    logger.info(f"[记忆搜索] 已加载 {len(final_results)} 条相关记忆")

    return result_str
