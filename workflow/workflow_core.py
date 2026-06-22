import os
import asyncio
import json
import re
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, TypedDict, Callable, Awaitable
import contextvars

from langgraph.types import Command
from langgraph.runtime import Runtime

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents.middleware import wrap_tool_call, AgentMiddleware, hook_config
from langchain.tools.tool_node import ToolCallRequest
from langchain.messages import ToolMessage

from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from deepagents.backends import CompositeBackend

from loguru import logger


# Runloop 沙盒导入
from runloop_api_client import RunloopSDK
from langchain_runloop import RunloopSandbox

from workflow.config import (
    BASE_DIR,
    SKILLS_DIR,
    USE_SANDBOX,
    OUTPUT_BASE_DIR,
    SKILLS_BASE_DIR,
    MCP_READ_ALLOWED_DIRS,
    MCP_WRITE_ALLOWED_DIRS,
    RUNLOOP_API_KEY,
    OWNER_NAME,
    MEMORY_SHORT_TERM_TASKS,
    MEMORY_MID_TERM_TASKS,
    MEMORY_ENABLE_TOPIC_SEARCH,
    MEMORY_RELEVANT_TASKS_LIMIT,
    ENABLE_SUBAGENTS,
)
from workflow.model import mcp_llm
from workflow.mcpClient import get_mcp_tools, get_mcp_tools_skills
from workflow.report_tools import (
    insert_agent_event,
    get_disabled_skills_with_fallback,
    build_skills_policy_notice_for_prompt,
)
from workflow.permission_engine import PermissionEngine

# 导入基础设施模块
from workflow import workflow_infrastructure
from workflow.workflow_infrastructure import (
    _upload_skill_file_on_demand,
    _download_sandbox_files,
    _extract_wechat_contact,
    VirtualEnvLocalShellBackend,
)

# 使用 contextvars 来存储每个请求的上下文，确保并发安全
context_thread_id = contextvars.ContextVar("thread_id", default=None)
context_session_id = contextvars.ContextVar("session_id", default=None)
context_skills_files = contextvars.ContextVar("skills_files", default={})
context_username = contextvars.ContextVar("username", default=None)

# 全局变量
_deep_agent_instance = None
# 与缓存的 Agent 一致：True=含定时任务管理工具，False=定时触发场景（不挂载这些工具）
_deep_agent_scheduler_tools_profile: Optional[bool] = None
# 模块加载时立即创建锁，避免并发时多协程各自创建不同锁实例的竞态条件
_deep_agent_lock = asyncio.Lock()


def trim_by_tasks(messages: list, max_tasks: int = 10) -> list:
    """从消息列表中读取最近 max_tasks 个完整任务，不修改原始数据（Checkpointer 安全）

    任务边界定义：
    - 一个任务从 HumanMessage 开始，到下一个 HumanMessage 之前结束
    - 最后一个任务包含从其 HumanMessage 到列表末尾的所有消息

    注意：不做内容去重，避免不同任务中相同内容的消息被误删导致任务数减少

    Args:
        messages: 消息列表（来自 Checkpointer，只读）
        max_tasks: 保留的最大任务数

    Returns:
        截断后的消息列表（不修改原始 Checkpointer 数据）
    """
    if not messages:
        return []

    # 分离 SystemMessage 和其他消息
    system_messages = [m for m in messages if isinstance(m, SystemMessage)]
    other_messages = [m for m in messages if not isinstance(m, SystemMessage)]

    # 找到所有 HumanMessage 的位置（任务起始点）
    human_msg_indices = [
        i for i, msg in enumerate(other_messages) if isinstance(msg, HumanMessage)
    ]

    if not human_msg_indices:
        latest_system = [system_messages[-1]] if system_messages else []
        return latest_system

    # 构建任务边界列表：每个任务 = [HumanMessage 起始, 下一个 HumanMessage 之前)
    task_boundaries = []
    for i, human_idx in enumerate(human_msg_indices):
        start = human_idx
        end = (
            human_msg_indices[i + 1]
            if i + 1 < len(human_msg_indices)
            else len(other_messages)
        )
        task_boundaries.append((start, end))

    # 保留最近的 max_tasks 个任务
    tasks_to_keep = (
        task_boundaries[-max_tasks:]
        if len(task_boundaries) > max_tasks
        else task_boundaries
    )

    # 收集保留任务的所有消息
    kept_messages = []
    for start, end in tasks_to_keep:
        kept_messages.extend(other_messages[start:end])

    # 只保留最新的 SystemMessage（避免历史冗余系统提示词）
    latest_system = [system_messages[-1]] if system_messages else []
    result = latest_system + kept_messages

    logger.info(
        f"[短期记忆] 读取最近 {len(tasks_to_keep)}/{len(task_boundaries)} 个任务，共 {len(result)} 条消息（Checkpointer 原始 {len(messages)} 条，不修改）"
    )
    return result


def _make_backend(runtime, base_backend):
    """构建 CompositeBackend：默认路由到 base_backend（长期记忆已迁移至 MySQL，不再使用 /memories/ 路由）"""
    return CompositeBackend(
        default=base_backend if not callable(base_backend) else base_backend(runtime),
        routes={},
    )


class DeepAgentState(TypedDict):
    user_input: str
    thread_id: str
    session_id: str
    chat_history: list
    topic: str
    requirement: str
    username: str
    result: str


# 上下文压缩中间件
class ContextCompressionMiddleware(AgentMiddleware):
    """上下文压缩中间件：在模型调用前检查消息数量并压缩上下文"""

    def __init__(self, compression_threshold: int = 100, keep_count: int = 20):
        super().__init__()
        self.compression_threshold = compression_threshold  # 触发压缩的阈值
        self.keep_count = keep_count  # 压缩后保留的消息数
        self.compression_count = 0
        self.last_compressed_msg_count = 0  # 上次压缩后的消息数量

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """在模型调用前检查是否需要压缩上下文"""
        try:
            messages = state.get("messages", [])
            if not messages:
                return None

            msg_count = len(messages)

            # 检查是否需要压缩：
            # 1. 消息数量超过阈值
            # 2. 距离上次压缩后，已新增的消息数量超过阈值（确保不会频繁压缩）
            new_messages_since_last_compress = (
                msg_count - self.last_compressed_msg_count
            )

            # 只有当消息总数超过阈值 且 距离上次压缩后新增的消息也超过阈值时才压缩
            if (
                msg_count > self.compression_threshold
                and new_messages_since_last_compress > self.compression_threshold
            ):
                self.compression_count += 1
                logger.info(
                    f"[上下文压缩] 消息数量 {msg_count} 超过阈值 {self.compression_threshold}，进行压缩 (第 {self.compression_count} 次)"
                )

                # 压缩策略：保留最新的 N 条消息，将之前的消息压缩为摘要
                kept_messages = messages[-self.keep_count :]
                old_messages = messages[: -self.keep_count]

                if old_messages:
                    summary_text = self._compress_messages(old_messages)
                    compressed_msg = AIMessage(content=f"[历史摘要] {summary_text}")
                    new_messages = [compressed_msg] + kept_messages

                    # 更新上次压缩后的消息数量（压缩后应该有 keep_count + 1 条）
                    self.last_compressed_msg_count = len(new_messages)

                    logger.info(f"[上下文压缩] 压缩后消息数量: {len(new_messages)}")
                    return {"messages": new_messages}

        except Exception as e:
            logger.info(f"[上下文压缩] 压缩失败: {e}")

        return None

    def _compress_messages(self, messages: list) -> str:
        """将消息列表压缩为摘要文本"""
        if not messages:
            return ""

        summary_parts = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                summary_parts.append(f"用户: {msg.content[:100]}...")
            elif isinstance(msg, AIMessage):
                content = msg.content[:200] if len(msg.content) > 200 else msg.content
                summary_parts.append(f"AI: {content}...")

        return "\n".join(summary_parts[:5])


def _repair_tool_call_integrity(messages: list) -> list:
    """修复消息列表中的工具调用完整性，确保每个 AIMessage.tool_calls 都有对应的 ToolMessage

    用户中断执行时，AIMessage(tool_calls=[A,B,C]) 可能已写入 Checkpoint，
    但只有部分 ToolMessage(A)、ToolMessage(B) 写入成功，导致 tool_call(C) 缺少回应。
    LangGraph 恢复 State 后会将不完整消息序列送往 LLM API，触发 400 错误：
    "insufficient tool messages following tool_calls message"。

    本函数在消息发送给模型前清除所有孤立 tool_calls 和孤立 ToolMessage。
    使用 model_copy(update=...) 保留消息的所有内部属性（additional_kwargs 等）。
    """
    if not messages:
        return messages

    # 1. 收集所有 ToolMessage 携带的 tool_call_id
    existing_tool_call_ids: set = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                existing_tool_call_ids.add(tc_id)

    # 2. 收集所有 AIMessage.tool_calls 声明要调用的 id
    all_expected_tool_call_ids: set = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    tc_id = (
                        tc.get("id")
                        if isinstance(tc, dict)
                        else getattr(tc, "id", None)
                    )
                    if tc_id:
                        all_expected_tool_call_ids.add(tc_id)

    # 3. 构建修复后的消息列表（使用 model_copy 保留 additional_kwargs 等属性）
    repaired = []
    dirty = False
    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                fixed_tool_calls = [
                    tc
                    for tc in tool_calls
                    if (
                        tc.get("id")
                        if isinstance(tc, dict)
                        else getattr(tc, "id", None)
                    )
                    in existing_tool_call_ids
                ]
                removed = len(tool_calls) - len(fixed_tool_calls)

                if removed > 0:
                    dirty = True
                    logger.info(
                        f"[消息完整性修复] AIMessage 移除 {removed} 个孤立 tool_calls"
                        f"（原始 {len(tool_calls)}，保留 {len(fixed_tool_calls)}）"
                    )

                if fixed_tool_calls:
                    # 使用 model_copy 保留 internal 属性，同时更新 tool_calls 和 additional_kwargs.tool_calls
                    # 注意：必须同时更新 additional_kwargs.tool_calls，因为 LLM API 转换时优先读取它
                    new_msg = msg.model_copy(
                        update={
                            "tool_calls": fixed_tool_calls,
                            "additional_kwargs": {
                                **msg.additional_kwargs,
                                "tool_calls": fixed_tool_calls,
                            },
                        }
                    )
                    repaired.append(new_msg)
                    continue
                else:
                    dirty = True
                    logger.info(
                        "[消息完整性修复] AIMessage 所有 tool_calls 均为孤立，转为纯文本消息"
                    )
                    new_msg = msg.model_copy(
                        update={
                            "tool_calls": [],
                            "additional_kwargs": {
                                **msg.additional_kwargs,
                                "tool_calls": [],
                            },
                        }
                    )
                    repaired.append(new_msg)
                    continue

        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id not in all_expected_tool_call_ids:
                dirty = True
                logger.info(
                    f"[消息完整性修复] 移除孤立 ToolMessage (tool_call_id={tc_id})"
                )
                continue

        repaired.append(msg)

    if dirty:
        logger.info(
            f"[消息完整性修复] 修复完成：原始 {len(messages)} 条 → {len(repaired)} 条"
        )

    return repaired


class TaskTruncationMiddleware(AgentMiddleware):
    """短期记忆截断中间件：在模型调用前，只保留最近的 N 个任务。

    设计原则：
    - 任务截断仅在 awrap_model_call 中执行（修改发送给 LLM 的请求），不修改 Checkpointer 数据
    - before_agent 仅负责修复中断导致的 tool_calls / ToolMessage 完整性问题
    - 这样 Checkpointer 中的完整历史始终保留，前端可以分页加载

    两个环节分工：
    1. before_agent：修复孤立 tool_calls / ToolMessage（直接修改 State，防止下游异常）
    2. awrap_model_call：按任务数截断 + 完整性修复（仅影响发给 LLM 的消息，不落盘）
    """

    def __init__(self, max_tasks: int = 10):
        super().__init__()
        self.max_tasks = max_tasks

    def before_agent(self, state, runtime):
        """Agent 启动前修复 State 中的消息完整性（孤立 tool_calls / ToolMessage）。

        注意：此处不做任务截断，截断仅在下游 awrap_model_call 中执行，
        确保 Checkpointer 中保留完整的历史消息，前端可以分页加载。
        """
        try:
            messages = state.get("messages", [])
            if not messages:
                return None

            # 仅修复 tool_calls 完整性，不截断历史消息
            repaired = _repair_tool_call_integrity(messages)
            if repaired is not messages:
                from langgraph.types import Overwrite

                return {"messages": Overwrite(repaired)}
        except Exception as e:
            logger.info(f"[短期记忆] before_agent 完整性修复失败: {e}")

        return None

    async def awrap_model_call(self, request, handler):
        """模型调用前：按任务数截断历史消息 + 修复完整性（仅影响发给 LLM 的消息）。

        截断只发生在 request 副本上，不会回写到 Checkpointer。
        """
        try:
            messages = request.messages
            if messages:
                # 步骤1：按任务数截断历史消息（只截断发给 LLM 的请求，不修改 Checkpointer）
                trimmed = trim_by_tasks(messages, max_tasks=self.max_tasks)
                if len(trimmed) < len(messages):
                    request = request.override(messages=trimmed)
                    messages = trimmed

                # 步骤2：修复 tool_calls 完整性（防止中断导致的不完整状态）
                repaired = _repair_tool_call_integrity(messages)
                if repaired is not messages:
                    request = request.override(messages=repaired)
        except Exception as e:
            logger.info(f"[短期记忆] awrap_model_call 截断/修复失败: {e}")

        return await handler(request)


class SkillFilterMiddleware(AgentMiddleware):
    """技能加载与过滤中间件

    直接从 skills_config.json 读取技能配置，过滤掉 enabled: false 的技能，
    生成与 SkillsMiddleware 兼容的 skills_metadata 注入到 state 中。
    不依赖 SkillsMiddleware 的磁盘扫描结果，确保在任何环境下都能正确加载。
    """

    def __init__(self):
        super().__init__()
        self._skills_base_dir = SKILLS_BASE_DIR.replace("\\", "/")

    def _build_skills_metadata(self):
        config_path = os.path.join(BASE_DIR, "config", "skills_config.json")
        if not os.path.exists(config_path):
            logger.info("[SkillFilter] skills_config.json 不存在")
            return []

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.info("[SkillFilter] 读取 skills_config.json 失败: {}", e)
            return []

        skills_node = config.get("skills") if isinstance(config, dict) else {}
        if not isinstance(skills_node, dict):
            return []

        enabled_skills = []
        for name, info in skills_node.items():
            if not isinstance(info, dict):
                continue
            if not info.get("enabled", False):
                continue
            description = info.get("description", "")
            if not description:
                continue
            skill_path = f"{self._skills_base_dir}/{name}/SKILL.md"
            enabled_skills.append(
                {
                    "name": name,
                    "description": description,
                    "path": skill_path,
                    "allowed_tools": [],
                }
            )

        logger.info(
            "[SkillFilter] 从 skills_config.json 加载 {} 个启用的技能",
            len(enabled_skills),
        )
        return enabled_skills

    def before_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return {"skills_metadata": self._build_skills_metadata()}

    async def abefore_agent(
        self, state: Any, runtime: Runtime
    ) -> dict[str, Any] | None:
        return {"skills_metadata": self._build_skills_metadata()}


# 创建上下文压缩中间件实例
# 注意：暂时禁用 ContextCompressionMiddleware，因为它可能导致工具调用结果传递问题
# _context_compression_middleware = ContextCompressionMiddleware(compression_threshold=100, keep_count=20)
_context_compression_middleware = None  # 临时禁用


def _fix_llm_path_spaces(path: str) -> str:
    """修复 LLM 在数字与汉字之间错误插入的空格。

    LLM 有排版习惯，会在阿拉伯数字和汉字之间自动加空格（如 "2026 年" -> "2026年"）。
    仅修复"数字↔汉字"边界处的空格，不影响路径中本身合法的空格（如 "Program Files"）。
    修复策略：先尝试修复，若修复后文件/目录存在则采用修复结果，否则返回原路径。
    """
    import re

    pattern = re.compile(r"(\d)\s+([\u4e00-\u9fff])|([\u4e00-\u9fff])\s+(\d)")
    fixed = pattern.sub(
        lambda m: (m.group(1) or "")
        + (m.group(2) or "")
        + (m.group(3) or "")
        + (m.group(4) or ""),
        path,
    )
    if fixed != path and (os.path.exists(fixed) or not os.path.exists(path)):
        return fixed
    return path


@wrap_tool_call
async def tool_logging_middleware(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """工具调用监控中间件：记录工具调用到数据库（异步版本），并按需上传 skills 文件"""
    tool_name = request.tool_call.get("name", "unknown")
    tool_args = request.tool_call.get("args", {})

    # 修复所有工具调用中路径参数里 LLM 错误插入的数字↔汉字空格
    for param_key in ("file_path", "path", "directory", "dir_path", "folder_path"):
        if param_key in tool_args and isinstance(tool_args[param_key], str):
            fixed = _fix_llm_path_spaces(tool_args[param_key])
            if fixed != tool_args[param_key]:
                logger.info(
                    f"[中间件] 自动修复路径空格 [{param_key}]: '{tool_args[param_key]}' -> '{fixed}'"
                )
                request.tool_call["args"][param_key] = fixed
                tool_args = request.tool_call.get("args", {})

    # 按需上传: 如果是 read_file 调用且文件路径在 skills 目录，则先上传
    if tool_name == "read_file" and "skills" in str(tool_args):
        file_path = tool_args.get("file_path", "")

        # 修复路径中的引号问题
        if file_path and ('"' in file_path or "'" in file_path):
            clean_path = file_path.replace('"', "").replace("'", "")
            # 修改请求参数，确保后续工具调用使用正确的路径
            request.tool_call["args"]["file_path"] = clean_path
            file_path = clean_path
            logger.info(f"[DeepAgent] 自动修复文件路径: {file_path}")

        if file_path and "/home/user/skills/" in file_path:
            # 只有在沙盒模式下才需要按需上传
            if not USE_SANDBOX:
                return await handler(request)

            # 优先从 contextvars 获取，其次从 agent 获取
            skills_files = context_skills_files.get()
            if not skills_files:
                # 从 agent 实例获取
                global _deep_agent_instance
                if _deep_agent_instance and hasattr(
                    _deep_agent_instance, "skills_files"
                ):
                    skills_files = _deep_agent_instance.skills_files

            # 尝试上传文件
            # 注意：skills_files 中的键是标准路径（无引号），所以这里必须使用 clean_path
            if skills_files:
                await _upload_skill_file_on_demand(file_path, skills_files)

    thread_id = context_thread_id.get()
    session_id = context_session_id.get()
    if thread_id and session_id:
        try:
            logger.info(f"[工具监控] 工具调用开始: {tool_name}")
        except Exception as e:
            logger.info(f"[工具监控] 保存数据库失败: {e}")

    try:
        # 执行工具调用
        result = await handler(request)

        # 记录成功的调用
        thread_id = context_thread_id.get()
        session_id = context_session_id.get()

        if thread_id and session_id:
            try:
                # 提取结果预览
                result_content = ""
                if isinstance(result, ToolMessage):
                    result_content = str(result.content)
                elif isinstance(result, str):
                    result_content = result
                else:
                    result_content = str(result)

                logger.info(f"[工具监控] 工具调用成功: {tool_name}")
            except Exception as e:
                logger.info(f"[工具监控] 保存数据库失败: {e}")

        return result
    except Exception as e:
        # 记录失败的调用
        thread_id = context_thread_id.get()
        session_id = context_session_id.get()

        if thread_id and session_id:
            try:
                logger.info(f"[工具监控] 工具调用失败: {tool_name}, 错误: {str(e)}")
            except:
                pass
        raise


def _load_prompt_from_file(prompt_file: str) -> str:
    from workflow.config import BASE_DIR

    prompt_path = os.path.join(BASE_DIR, "prompt", prompt_file)
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _resolve_runtime_username(explicit: str = "") -> str:
    """Resolve the business username for output paths (desktop login > env > wechat owner)."""
    u = str(explicit or "").strip()
    if u:
        return u
    for key in ("WORKMATE_DESKTOP_ACTIVE_USERNAME", "AGENT_USERNAME"):
        env_u = os.environ.get(key, "").strip()
        if env_u:
            return env_u
    owner = str(OWNER_NAME or "").strip()
    return owner or "default"


def _compute_output_dir(username: str = "") -> str:
    uname = _resolve_runtime_username(username)
    date_str = datetime.now().strftime("%Y%m%d")
    if USE_SANDBOX:
        return f"/charts/{uname}/{date_str}/"
    return f"{OUTPUT_BASE_DIR}/{uname}/{date_str}/"


def _load_first_system_prompt() -> str:
    """加载 MANDATORY.md 并完成模板替换和子文件注入"""
    from workflow.config import BASE_DIR

    # 1. 读取 MANDATORY.md 模板
    first_system_path = os.path.join(BASE_DIR, "prompt", "MANDATORY.md")
    if not os.path.exists(first_system_path):
        logger.info("[MANDATORY] MANDATORY.md 不存在，返回空字符串")
        return ""

    with open(first_system_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 2. 从环境变量读取身份信息并替换模板变量
    mate_name = os.getenv("MATE_NAME", "工作伙伴")
    company_name = os.getenv("COMPANY_NAME", "公司")
    department_name = os.getenv("DEPARTMENT_NAME", "部门")
    mate_title = os.getenv("MATE_TITLE", "员工")

    content = content.replace("{{MATE_NAME}}", mate_name)
    content = content.replace("{{COMPANY_NAME}}", company_name)
    content = content.replace("{{DEPARTMENT_NAME}}", department_name)
    content = content.replace("{{MATE_TITLE}}", mate_title)

    logger.info(
        f"[MANDATORY] 身份信息已注入: "
        f"MATE_NAME={mate_name}, COMPANY_NAME={company_name}, "
        f"DEPARTMENT_NAME={department_name}, MATE_TITLE={mate_title}"
    )

    # 3. 注入子文件内容（rich.md, department.md, identity.md）
    content = _inject_prompt_file(content, "{{RICH_CONTENT}}", BASE_DIR, "rich.md")
    content = _inject_prompt_file(
        content, "{{DEPARTMENT_CONTENT}}", BASE_DIR, "department.md"
    )
    content = _inject_prompt_file(
        content, "{{IDENTITY_CONTENT}}", BASE_DIR, "identity.md"
    )

    # 4. 注入输出目录变量（与 _build_system_prompt 中的计算逻辑保持一致）
    output_dir = _compute_output_dir()
    content = content.replace("{{OUTPUT_DIR}}", output_dir)

    return content


def _inject_prompt_file(
    content: str, placeholder: str, base_dir: str, filename: str
) -> str:
    """读取指定 prompt 文件内容并替换 content 中的占位符，返回替换后的内容"""
    file_path = os.path.join(base_dir, "prompt", filename)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read().strip()
        if file_content:
            logger.info(f"[MANDATORY] {filename} 内容已注入")
            return content.replace(placeholder, file_content)
    # 文件不存在或为空，移除占位符
    return content.replace(placeholder, "")


_SOURCE_PREFIX_PATTERNS = [
    "【workmate桌面端】",
    "【定时任务】",
    "【协同任务】",
    "【企业微信】",
]


def _strip_source_prefix(text: str) -> str:
    """剥离任务来源前缀，用于记忆搜索等不需要区分来源的场景"""
    for prefix in _SOURCE_PREFIX_PATTERNS:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


_GENERIC_QUERY_PATTERNS = [
    "你是谁",
    "你好",
    "hi",
    "hello",
    "在吗",
    "在不在",
    "测试",
    "test",
    "help",
    "帮助",
]


def _should_skip_relevant_memory_search(topic: str) -> bool:
    """判断是否应跳过相关历史记忆搜索"""
    stripped = topic.strip()
    if len(stripped) < 10:
        return True
    stripped_lower = stripped.lower()
    for pattern in _GENERIC_QUERY_PATTERNS:
        if stripped_lower == pattern:
            return True
    return False


async def _read_long_term_memory(contact_name: str) -> str:
    """从 MySQL user_preferences 表读取用户长期偏好（持久化，重启后保留）"""
    if not contact_name:
        logger.info("[长期记忆] contact_name 为空，跳过加载")
        return ""
    try:
        from workflow.report_tools import get_user_preferences
        import contextvars

        # asyncio.to_thread 默认不继承 contextvars，需显式传递 Context
        ctx = contextvars.copy_context()
        return await asyncio.to_thread(ctx.run, get_user_preferences, contact_name)
    except Exception as e:
        logger.info(f"[长期记忆] 读取失败: {e}")
        return ""


async def _preprocess_desktop_attachments(user_input: str) -> str:
    """预处理桌面端上传的附件：自动解析每个附件为 Markdown 并注入到用户输入中。

    在将 user_input 传给 LLM 之前，检测 <attachment-paths> 标签并提取文件路径，
    对每个附件文件调用 DocumentReader 解析为 Markdown 内容，
    如果解析后的内容超过 3000 字，则调用 LLM 压缩为摘要后注入，
    否则直接注入全文。

    兼容旧格式【桌面端上传的附件】标记。
    """
    if not user_input:
        return user_input

    import re

    # 优先匹配新格式 <attachment-paths>，兼容旧格式【桌面端上传的附件】
    attachment_section_match = re.search(
        r"<attachment-paths>\n(.*?)\n</attachment-paths>",
        user_input,
        re.DOTALL,
    )
    if not attachment_section_match:
        attachment_section_match = re.search(
            r"【桌面端上传的附件】\n(.*?)\n\n【用户说明】",
            user_input,
            re.DOTALL,
        )
    if not attachment_section_match:
        return user_input

    attachment_paths_text = attachment_section_match.group(1)
    file_paths = [p.strip() for p in attachment_paths_text.split("\n") if p.strip()]

    if not file_paths:
        return user_input

    from pathlib import Path
    from mcp_filesystem.doc_reader import DocumentReader
    from mcp_filesystem.security import PathValidator

    # 构建允许的目录列表：包含配置中的可读目录和 OUTPUT_BASE_DIR
    allowed_dirs = list(MCP_READ_ALLOWED_DIRS) if MCP_READ_ALLOWED_DIRS else []
    if OUTPUT_BASE_DIR and OUTPUT_BASE_DIR not in allowed_dirs:
        allowed_dirs.append(OUTPUT_BASE_DIR)
    # 兜底：至少包含当前工作目录
    if not allowed_dirs:
        allowed_dirs = [os.getcwd()]

    validator = PathValidator(allowed_dirs)
    reader = DocumentReader(validator)

    ATTACHMENT_SUMMARY_THRESHOLD = 3000

    parsed_contents = []
    for file_path in file_paths:
        if not os.path.exists(file_path):
            logger.info(f"[附件预处理] 文件不存在，跳过: {file_path}")
            parsed_contents.append(f"[附件文件不存在：{Path(file_path).name}]")
            continue

        try:
            md_content = await reader.read_to_markdown(file_path)
            filename = Path(file_path).name

            if len(md_content) > ATTACHMENT_SUMMARY_THRESHOLD:
                summary = await _compress_attachment_content(
                    md_content, ATTACHMENT_SUMMARY_THRESHOLD
                )
                parsed_contents.append(
                    f"## 附件：{filename}（完整路径：{file_path}）\n\n"
                    f"【以下为附件内容摘要，原文过长已压缩。如需完整内容请根据文件路径重新解析】\n\n"
                    f"{summary}"
                )
                logger.info(
                    f"[附件预处理] 附件过长({len(md_content)}字)，已压缩为摘要: {file_path}"
                )
            else:
                parsed_contents.append(
                    f"## 附件：{filename}（完整路径：{file_path}）\n\n{md_content}"
                )
                logger.info(f"[附件预处理] 成功解析: {file_path}")
        except Exception as e:
            logger.error(f"[附件预处理] 解析失败: {file_path}, 错误: {e}")
            parsed_contents.append(f"[附件解析失败：{Path(file_path).name} - {e}]")

    if not parsed_contents:
        return user_input

    # 保留标签之前和之后的内容
    before_section = user_input[: attachment_section_match.start()]
    user_note_section = user_input[attachment_section_match.end() :]

    parsed_text = "\n\n---\n\n".join(parsed_contents)
    new_input = (
        f"{before_section}"
        f"<attachment>\n"
        f"{parsed_text}\n"
        f"</attachment>\n\n"
        f"{user_note_section.lstrip()}"
    )

    success_count = sum(1 for c in parsed_contents if not c.startswith("[附件"))
    logger.info(
        f"[附件预处理] 共处理 {len(file_paths)} 个附件，成功解析 {success_count} 个"
    )

    return new_input


async def _compress_attachment_content(content: str, max_length: int = 3000) -> str:
    """使用 LLM 将附件内容压缩到指定长度以内的摘要。

    当附件文件解析后的 Markdown 内容过长时，调用 LLM 生成结构化摘要，
    避免占用过多上下文空间。

    Args:
        content: 附件的 Markdown 内容
        max_length: 摘要最大字符数，默认 3000
    """
    try:
        from workflow.model import mcp_llm
        from langchain_core.messages import HumanMessage

        truncated = content[:8000] if len(content) > 8000 else content
        prompt = (
            f"请将以下文档内容压缩为结构化摘要，要求：\n"
            f"1. 摘要总长度不超过{max_length}字\n"
            f"2. 保留文档的核心信息、关键数据和重要结论\n"
            f"3. 按文档结构组织摘要，使用标题和列表形式\n"
            f"4. 不要遗漏重要的数据、数字、日期等事实信息\n\n"
            f"文档内容：\n{truncated}\n\n"
            f"请直接输出摘要内容："
        )
        response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
        result = response.content.strip()
        if len(result) > max_length * 1.2:
            result = result[:max_length] + "..."
        return result
    except Exception as e:
        logger.error(f"[附件压缩] LLM压缩失败，降级为截断: {e}")
        if len(content) > max_length:
            return content[:max_length] + "...\n（内容过长，LLM压缩失败，已截断显示）"
        return content


async def _preprocess_collab_upstream_attachments(
    user_input: str, username: str
) -> str:
    """Parse locally synced collab upstream attachments into collab task input."""
    try:
        from workflow.collab_attachment_preprocess import enrich_collab_user_input

        return await enrich_collab_user_input(user_input, username or "")
    except Exception as exc:
        logger.info("[collab附件] 协同上游附件预处理跳过: {}", exc)
        return user_input


async def _preprocess_knowledge_files(user_input: str, username: str) -> str:
    """预处理知识库文件和分类：从数据库读取摘要并注入到用户输入中。

    支持两种标记（新格式 XML 标签，兼容旧格式【】标记）：
    - <knowledge-file-ids> 或 【知识库文件ID】：按文件ID逐个读取摘要
    - <knowledge-category-names> 或 【知识库分类】：按分类名称读取该分类下所有文件的摘要
    """
    if not user_input:
        return user_input

    has_file_ids = (
        "<knowledge-file-ids>" in user_input or "【知识库文件ID】" in user_input
    )
    has_category_names = (
        "<knowledge-category-names>" in user_input or "【知识库分类】" in user_input
    )
    if not has_file_ids and not has_category_names:
        return user_input

    import re

    resolved_user = _resolve_runtime_username(username)

    try:
        from admin_api.models.init_db import db_cursor
    except ImportError:
        logger.error("[知识库预处理] 无法导入数据库模块")
        return user_input

    summaries = []
    processed_file_ids = set()

    if has_category_names:
        # 优先匹配新格式，兼容旧格式
        cat_section_match = re.search(
            r"<knowledge-category-names>\n(.*?)\n</knowledge-category-names>",
            user_input,
            re.DOTALL,
        )
        if not cat_section_match:
            cat_section_match = re.search(
                r"【知识库分类】\n(.*?)(?:\n\n|\Z)",
                user_input,
                re.DOTALL,
            )
        if cat_section_match:
            cat_names_text = cat_section_match.group(1)
            category_names = [
                n.strip() for n in cat_names_text.split("\n") if n.strip()
            ]
            for cat_name in category_names:
                try:
                    with db_cursor(dictionary=True) as (conn, cursor):
                        if not conn:
                            summaries.append(f"- [分类: {cat_name}] 数据库连接失败")
                            continue
                        # 同时查询个人知识库和公司知识库
                        cursor.execute(
                            "SELECT id, category_name, original_filename, md_filename, summary, kb_type "
                            "FROM kb_files WHERE category_name = %s AND (username = %s OR username = '__company__')",
                            (cat_name, resolved_user),
                        )
                        rows = cursor.fetchall()
                        if not rows:
                            summaries.append(
                                f"- [分类: {cat_name}] 该分类下无知识库文件"
                            )
                            continue
                        for row in rows:
                            fid = row["id"]
                            if fid in processed_file_ids:
                                continue
                            processed_file_ids.add(fid)
                            display_name = (
                                row["md_filename"].replace(".md", "")
                                if row["md_filename"]
                                else row["original_filename"]
                            )
                            summary_text = row["summary"] or "（无摘要）"
                            kb_type_label = (
                                "公司知识库"
                                if row.get("kb_type") == "company"
                                else "个人知识库"
                            )
                            summaries.append(
                                f"### {display_name}\n"
                                f"- 分类: {row['category_name']}\n"
                                f"- 来源: {kb_type_label}\n"
                                f"- 原始文件名: {row['original_filename']}\n"
                                f"- file_name: {display_name}\n"
                                f"- 摘要:\n{summary_text}"
                            )
                        logger.info(
                            f"[知识库预处理] 按分类 '{cat_name}' 读取 {len(rows)} 个文件摘要"
                        )
                except Exception as e:
                    logger.error(f"[知识库预处理] 读取分类 {cat_name} 失败: {e}")
                    summaries.append(f"- [分类: {cat_name}] 读取失败: {e}")
            user_input = (
                user_input[: cat_section_match.start()]
                + user_input[cat_section_match.end() :]
            )

    if has_file_ids:
        # 优先匹配新格式，兼容旧格式
        kb_section_match = re.search(
            r"<knowledge-file-ids>\n(.*?)\n</knowledge-file-ids>",
            user_input,
            re.DOTALL,
        )
        if not kb_section_match:
            kb_section_match = re.search(
                r"【知识库文件ID】\n(.*?)(?:\n\n|\Z)",
                user_input,
                re.DOTALL,
            )
        if kb_section_match:
            file_ids_text = kb_section_match.group(1)
            file_ids = [fid.strip() for fid in file_ids_text.split("\n") if fid.strip()]
            for file_id in file_ids:
                if file_id in processed_file_ids:
                    continue
                try:
                    with db_cursor(dictionary=True) as (conn, cursor):
                        if not conn:
                            summaries.append(f"- [文件ID: {file_id}] 数据库连接失败")
                            continue
                        # 同时查询个人知识库和公司知识库
                        cursor.execute(
                            "SELECT id, category_name, original_filename, md_filename, summary, kb_type "
                            "FROM kb_files WHERE id = %s AND (username = %s OR username = '__company__')",
                            (file_id, resolved_user),
                        )
                        row = cursor.fetchone()
                        if not row:
                            summaries.append(
                                f"- [文件ID: {file_id}] 未找到对应知识库文件"
                            )
                            continue
                        processed_file_ids.add(row["id"])
                        display_name = (
                            row["md_filename"].replace(".md", "")
                            if row["md_filename"]
                            else row["original_filename"]
                        )
                        summary_text = row["summary"] or "（无摘要）"
                        kb_type_label = (
                            "公司知识库"
                            if row.get("kb_type") == "company"
                            else "个人知识库"
                        )
                        summaries.append(
                            f"### {display_name}\n"
                            f"- 分类: {row['category_name']}\n"
                            f"- 来源: {kb_type_label}\n"
                            f"- 原始文件名: {row['original_filename']}\n"
                            f"- file_name: {display_name}\n"
                            f"- 摘要:\n{summary_text}"
                        )
                        logger.info(f"[知识库预处理] 成功读取摘要: {display_name}")
                except Exception as e:
                    logger.error(f"[知识库预处理] 读取文件 {file_id} 失败: {e}")
                    summaries.append(f"- [文件ID: {file_id}] 读取失败: {e}")
            user_input = (
                user_input[: kb_section_match.start()]
                + user_input[kb_section_match.end() :]
            )

    if not summaries:
        return user_input

    summaries_text = "\n\n".join(summaries)
    new_input = f"<knowledge>\n{summaries_text}\n</knowledge>\n\n{user_input.strip()}"

    logger.info(
        f"[知识库预处理] 共处理 {len(processed_file_ids)} 个知识库文件，"
        f"成功读取 {sum(1 for s in summaries if not s.startswith('- ['))} 个"
    )

    return new_input


def _reassemble_user_input(
    user_input: str, skills_names: list, mcp_tool_names: list
) -> str:
    """预处理完成后，将所有注入块按正确顺序重组为最终输入。

    目标格式：
    【workmate桌面端】
    <attachment>...</attachment>
    <knowledge>...</knowledge>
    <skills>...</skills>
    <mcp-tools>...</mcp-tools>
    用户输入的任务...
    """
    import re

    if not user_input:
        return user_input

    # 提取各XML块
    attachment_match = re.search(r"<attachment>[\s\S]*?</attachment>", user_input)
    knowledge_match = re.search(r"<knowledge>[\s\S]*?</knowledge>", user_input)
    desktop_match = re.search(r"【workmate桌面端】", user_input)

    # 从原文中移除已提取的块，得到剩余文本
    remaining = user_input
    if attachment_match:
        remaining = (
            remaining[: attachment_match.start()] + remaining[attachment_match.end() :]
        )
    if knowledge_match:
        remaining = (
            remaining[: knowledge_match.start()] + remaining[knowledge_match.end() :]
        )
    if desktop_match:
        remaining = remaining.replace("【workmate桌面端】", "", 1)
    # 清理残留的skills/mcp-tools标签（前端已改为payload传递，但兼容旧流程）
    remaining = re.sub(r"<skills>[\s\S]*?</skills>\s*", "", remaining)
    remaining = re.sub(r"<mcp-tools>[\s\S]*?</mcp-tools>\s*", "", remaining)
    remaining = remaining.strip()

    # 按目标顺序组装
    parts = ["【workmate桌面端】"]

    if attachment_match:
        parts.append("\n" + attachment_match.group(0))

    if knowledge_match:
        parts.append("\n" + knowledge_match.group(0))

    if skills_names:
        parts.append("\n<skills>" + ", ".join(skills_names) + "</skills>")

    if mcp_tool_names:
        parts.append("\n<mcp-tools>" + ", ".join(mcp_tool_names) + "</mcp-tools>")

    if remaining:
        parts.append("\n" + remaining)

    return "\n".join(parts)


async def _preprocess_hitl_attachments(resume_command: dict) -> dict:
    """预处理 HITL 恢复时上传的附件：解析每个文件为 Markdown 并注入到 resume_command 中。

    HITL 恢复时，用户上传的附件路径通过 resume_command.attachments 传递。
    在将 resume_command 传给 LangGraph 之前，解析所有附件文件，
    将解析后的 Markdown 内容注入到 resume_command 中（新增 parsed_attachments 字段），
    这样 LLM 不需要手动调用 MCPFilesystem_parse_file_2_md 来解析附件。

    同时保留原始 attachments 字段，以便 LLM 仍然知道原始文件路径。
    """
    attachments = (
        resume_command.get("attachments") if isinstance(resume_command, dict) else None
    )
    if not attachments or not isinstance(attachments, list) or len(attachments) == 0:
        return resume_command

    from pathlib import Path
    from mcp_filesystem.doc_reader import DocumentReader
    from mcp_filesystem.security import PathValidator

    allowed_dirs = list(MCP_READ_ALLOWED_DIRS) if MCP_READ_ALLOWED_DIRS else []
    if OUTPUT_BASE_DIR and OUTPUT_BASE_DIR not in allowed_dirs:
        allowed_dirs.append(OUTPUT_BASE_DIR)
    if not allowed_dirs:
        allowed_dirs = [os.getcwd()]

    validator = PathValidator(allowed_dirs)
    reader = DocumentReader(validator)

    parsed_contents = []
    for file_path in attachments:
        file_path = str(file_path).strip()
        if not file_path:
            continue
        if not os.path.exists(file_path):
            logger.info(f"[HITL附件预处理] 文件不存在，跳过: {file_path}")
            parsed_contents.append(f"[附件文件不存在：{Path(file_path).name}]")
            continue

        try:
            md_content = await reader.read_to_markdown(file_path)
            filename = Path(file_path).name
            parsed_contents.append(
                f"## 附件：{filename}（完整路径：{file_path}）\n\n{md_content}"
            )
            logger.info(f"[HITL附件预处理] 成功解析: {file_path}")
        except Exception as e:
            logger.error(f"[HITL附件预处理] 解析失败: {file_path}, 错误: {e}")
            parsed_contents.append(f"[附件解析失败：{Path(file_path).name} - {e}]")

    if not parsed_contents:
        return resume_command

    parsed_text = "\n\n---\n\n".join(parsed_contents)
    result = dict(resume_command)
    result["parsed_attachments"] = parsed_text

    success_count = sum(1 for c in parsed_contents if not c.startswith("[附件"))
    logger.info(
        f"[HITL附件预处理] 共处理 {len(attachments)} 个附件，"
        f"成功解析 {success_count} 个"
    )

    return result


def _build_system_prompt(
    username: str,
    chat_history_str: str,
    mcp_history_str: str = "",
    wechat_context: str = "",
    memory_summary: str = "",
    long_term_memory: str = "",
    relevant_memory: str = "",
    short_term_memory: str = "",
    scheduled_task_invocation: bool = False,
) -> str:
    system_prompt = _load_prompt_from_file("SYSTEM.md")

    # 根据 ENABLE_SUBAGENTS 配置选择 task 工具的提示词
    if ENABLE_SUBAGENTS:
        # 启用 subagent 时，使用完整的 task 工具指南
        task_tool_guide = """
        - **需符合以下规则，才可以使用 `task` 工具创建 subagent**，若不符合规则，禁止使用 `task` 工具：
            - `task` 工具可以创建新的 subagent 子代理用于处理特定且复杂的任务，简单任务禁止使用 `task` 工具。
            - 调用 `task` 工具时，根据任务类型从可用 subagent 列表中选择最匹配的 subagent，**禁止使用 `general-purpose` subagent**。
            - 调用 `task` 工具时，完成的任务一定要与所选 subagent 的功能相匹配，若不匹配，禁止使用 `task` 工具。
        """
    else:
        # 禁用 subagent 时，明确告知 Agent 不要使用 task 工具
        task_tool_guide = "- **禁用 `task` 工具，不支持创建 subagent子代理**"
    system_prompt = system_prompt.replace("{{TASK_TOOL_GUIDE}}", task_tool_guide)

    # 移除不再需要的 SUBAGENTS_GUIDE 占位符替换（如果存在）
    system_prompt = system_prompt.replace("{{SUBAGENTS_GUIDE}}", "")

    username = _resolve_runtime_username(username)
    output_dir = _compute_output_dir(username)

    if USE_SANDBOX:
        skills_base_path = "/home/user/skills"
        env_desc = "沙盒"
    else:
        skills_base_path = SKILLS_BASE_DIR
        env_desc = "本地（非沙盒）"

    # 替换变量
    system_prompt = system_prompt.replace("{{OUTPUT_DIR}}", output_dir)
    system_prompt = system_prompt.replace("{username}", username)
    system_prompt = system_prompt.replace(
        "{datetime}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    system_prompt = system_prompt.replace("{environment}", env_desc)
    system_prompt = system_prompt.replace("{chat_history}", chat_history_str or "无")

    if wechat_context:
        system_prompt = system_prompt.replace(
            "{{WECHAT_CONTEXT}}", f"\n{wechat_context}"
        )
    else:
        system_prompt = system_prompt.replace("{{WECHAT_CONTEXT}}", "")

    # 替换 MCP 文件系统目录权限变量
    if MCP_READ_ALLOWED_DIRS:
        read_dirs_str = "\n".join([f"- {d}" for d in MCP_READ_ALLOWED_DIRS])
    else:
        read_dirs_str = "无"
    system_prompt = system_prompt.replace("{{MCP_READ_ALLOWED_DIRS}}", read_dirs_str)

    if MCP_WRITE_ALLOWED_DIRS:
        write_dirs_str = "\n".join([f"- {d}" for d in MCP_WRITE_ALLOWED_DIRS])
    else:
        write_dirs_str = "无"
    system_prompt = system_prompt.replace("{{MCP_WRITE_ALLOWED_DIRS}}", write_dirs_str)

    # 替换记忆配置变量（从 .env 同步数值，避免 SYSTEM.md 硬编码）
    system_prompt = system_prompt.replace(
        "{{MEMORY_SHORT_TERM_TASKS}}", str(MEMORY_SHORT_TERM_TASKS)
    )
    system_prompt = system_prompt.replace(
        "{{MEMORY_MID_TERM_TASKS}}", str(MEMORY_MID_TERM_TASKS)
    )

    # 添加 MCP 工具调用历史
    if mcp_history_str:
        system_prompt = system_prompt.replace(
            "{{MCP_HISTORY}}", f"\n\n## 历史工具调用记录\n\n{mcp_history_str}"
        )
    else:
        system_prompt = system_prompt.replace("{{MCP_HISTORY}}", "")

    disabled_skills = get_disabled_skills_with_fallback()

    from workflow.config import BASE_DIR

    skills_dir = os.path.join(BASE_DIR, "skills")
    discovered_skills = []

    if os.path.exists(skills_dir):
        for item in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, item)
            if os.path.isdir(skill_path):
                skill_md_path = os.path.join(skill_path, "SKILL.md")
                description = ""
                if os.path.exists(skill_md_path):
                    try:
                        with open(skill_md_path, "r", encoding="utf-8-sig") as mf:
                            content = mf.read()
                            if content.startswith("---"):
                                end_idx = content.find("---", 3)
                                if end_idx > 0:
                                    import re

                                    yaml_section = content[3:end_idx].strip()
                                    name_match = re.search(
                                        r"name:\s*(.+)", yaml_section
                                    )
                                    desc_match = re.search(
                                        r"description:\s*(.+)", yaml_section
                                    )
                                    if name_match:
                                        name = name_match.group(1).strip()
                                        if desc_match:
                                            desc_raw = desc_match.group(1).strip()
                                            # 处理 YAML 块标量语法 (description: > 或 description: |)
                                            if desc_raw in (
                                                ">",
                                                "|",
                                                ">-",
                                                "|-",
                                                ">+",
                                                "|+",
                                            ):
                                                lines = yaml_section.split("\n")
                                                desc_found = False
                                                block_lines = []
                                                is_folded = desc_raw.startswith(">")
                                                for line in lines:
                                                    stripped = line.strip()
                                                    if stripped.startswith(
                                                        "description:"
                                                    ):
                                                        desc_found = True
                                                        continue
                                                    if desc_found:
                                                        if line and line[0] in (
                                                            " ",
                                                            "\t",
                                                        ):
                                                            block_lines.append(stripped)
                                                        elif stripped == "":
                                                            continue
                                                        else:
                                                            break
                                                if is_folded:
                                                    description = " ".join(block_lines)
                                                else:
                                                    description = "\n".join(block_lines)
                                            else:
                                                description = desc_raw
                                        discovered_skills.append((name, description))
                    except Exception:
                        pass

    working_skills = [s for s in discovered_skills if s[0] not in disabled_skills]

    allowed_names = PermissionEngine.filter_skills_by_explicit_allow(
        username, [s[0] for s in working_skills]
    )
    allowed_set = set(allowed_names)
    available_skills = [s for s in working_skills if s[0] in allowed_set]

    skills_policy_notice = build_skills_policy_notice_for_prompt(
        discovered_skills, available_skills
    )
    system_prompt = system_prompt.replace(
        "{{SKILLS_POLICY_NOTICE}}", skills_policy_notice
    )

    # 根据是否使用沙盒动态设置 skills 路径
    skills_text = "\n".join(
        [
            f"- {name} (`{skills_base_path}/{name}/`) - {desc}"
            for name, desc in available_skills
        ]
    )

    # 动态注入细粒度权限限制提示词
    mcp_perms = PermissionEngine.get_user_mcp_permissions(username)
    perm_hints = []
    for tool_key, config in mcp_perms.items():
        if config.get("action") == "allow" and config.get("rules"):
            rules_str = json.dumps(config.get("rules"), ensure_ascii=False)
            perm_hints.append(
                f"- 对于工具 {tool_key}，你必须遵守以下限制规则: {rules_str}"
            )

    if perm_hints:
        permission_guide = (
            "\n## 细粒度权限限制\n由于安全策略，你在执行以下工具时必须严格遵守特定参数限制：\n"
            + "\n".join(perm_hints)
        )
        system_prompt = system_prompt.replace(
            "{{AVAILABLE_SKILLS}}", skills_text + "\n" + permission_guide
        )
    else:
        system_prompt = system_prompt.replace("{{AVAILABLE_SKILLS}}", skills_text)

    # 替换 MCP 工具技能说明
    mcp_tools_skills = get_mcp_tools_skills()
    if mcp_tools_skills:
        # 本地文件路径
        mcp_tools_file = os.path.join(BASE_DIR, "prompt", "MCP_TOOLS_DESCRIPTION.md")

        try:
            with open(mcp_tools_file, "w", encoding="utf-8") as f:
                f.write(mcp_tools_skills)
            logger.info(f"[MCP 工具] 已将技能说明保存到 {mcp_tools_file}")

            # 沙盒模式：上传文件到沙盒
            if USE_SANDBOX:
                from workflow.workflow_infrastructure import _runloop_backend

                if _runloop_backend:
                    try:
                        # 创建沙盒中的目录
                        _runloop_backend.execute("mkdir -p /prompt")

                        # 读取本地文件内容并上传
                        with open(mcp_tools_file, "r", encoding="utf-8") as f:
                            content = f.read()

                        import base64

                        encoded = base64.b64encode(content.encode("utf-8")).decode(
                            "utf-8"
                        )
                        write_cmd = f"echo '{encoded}' | base64 -d > /prompt/MCP_TOOLS_DESCRIPTION.md"
                        result = _runloop_backend.execute(write_cmd)

                        if result.exit_code == 0:
                            logger.info(
                                f"[MCP 工具] 已上传到沙盒 /prompt/MCP_TOOLS_DESCRIPTION.md"
                            )
                        else:
                            logger.info(f"[MCP 工具] 上传沙盒失败: {result.output}")
                    except Exception as upload_error:
                        logger.info(f"[MCP 工具] 上传沙盒异常: {upload_error}")
        except Exception as e:
            logger.info(f"[MCP 工具] 保存技能说明失败: {e}")

        # 替换为详细提示信息（根据环境使用不同路径）
        if USE_SANDBOX:
            mcp_tools_file_path = "/prompt/MCP_TOOLS_DESCRIPTION.md"
        else:
            mcp_tools_file_path = mcp_tools_file

        mcp_tools_section = f"""
使用 MCP 工具前，请调用 `MCPFilesystem_read_file` 工具，读取 `{mcp_tools_file_path}` 文件，了解工具的使用场景和调用约束。

**使用步骤**：
1. 分析用户需求，判断是否需要使用 MCP 工具
2. 读取 `{mcp_tools_file_path}` 文件，获取工具列表和详细说明
3. 根据工具说明选择合适的工具进行调用
4. 遵循工具的参数要求和调用约束

请根据工具说明正确调用这些外部 MCP 工具。"""

        system_prompt = system_prompt.replace("{{MCP_TOOLS_SKILLS}}", mcp_tools_section)
    else:
        system_prompt = system_prompt.replace("{{MCP_TOOLS_SKILLS}}", "无外部 MCP 工具")

    # 记忆注入区域 —— 使用统一分隔标记区分3层记忆
    has_short_term = bool(short_term_memory)
    has_mid_term = bool(memory_summary)
    has_relevant = bool(relevant_memory)
    has_long_term = bool(long_term_memory)

    if has_short_term or has_mid_term or has_relevant or has_long_term:
        header = "=" * 60
        system_prompt += f"\n\n{header}"
        system_prompt += f"\n记忆上下文 Memory Context"
        system_prompt += f"\n{header}"

        if long_term_memory:
            system_prompt += f"\n\n{long_term_memory}"

        if memory_summary:
            system_prompt += f"\n\n{memory_summary}"

        if relevant_memory:
            system_prompt += f"\n\n{relevant_memory}"

        if short_term_memory:
            system_prompt += f"\n\n{short_term_memory}"
        # 短期记忆加载已禁用，后续将从 checkpoint 中加载
        # else:
        #     system_prompt += (
        #         f"\n\n{header}"
        #         f"\n** [短期记忆 Short-Term Memory] 最近5个任务的完整对话 **"
        #         f"\n  状态: 无完整对话记录（conversation_summaries 表中 full_conversation 为空）"
        #         f"\n{header}"
        #     )

    if scheduled_task_invocation:
        system_prompt += (
            "\n\n## 定时任务执行上下文（必读）\n"
            "本次请求由**调度器中已存在的定时任务**触发，Cron/下次执行时间已在系统内配置完毕。"
            "你的职责是**仅根据下方用户消息完成本次要交付的业务结果**（报告、摘要、检索、生成文件等）。\n"
            "**禁止**再创建、修改或删除定时任务，也禁止触发「立即再跑一遍定时任务」类操作；"
            "本会话未提供任何定时任务管理工具。即使用户文案含有「每天/定时/cron」等字样，也只视为对本批次任务内容的**文字描述**，"
            "完成这一次输出即可，不要尝试新建或重复登记定时任务。\n"
        )

    return system_prompt


async def reset_deep_agent():
    """重置 DeepAgent 实例，用于 MCP 连接重置时"""
    global _deep_agent_instance, _deep_agent_scheduler_tools_profile
    async with _deep_agent_lock:
        _deep_agent_instance = None
        _deep_agent_scheduler_tools_profile = None
        logger.info("[DeepAgent] Agent 实例已重置")


async def get_deep_agent(
    thread_id: str,
    session_id: str,
    include_scheduler_management_tools: bool = True,
):
    global _deep_agent_instance, _deep_agent_scheduler_tools_profile

    async with _deep_agent_lock:
        if (
            _deep_agent_instance is not None
            and _deep_agent_scheduler_tools_profile is not None
            and _deep_agent_scheduler_tools_profile
            != include_scheduler_management_tools
        ):
            logger.info("[DeepAgent] 定时任务工具集与当前请求不一致，重置 Agent 实例")
            _deep_agent_instance = None
        # --- 沙盒健康检查 ---
        if (
            _deep_agent_instance is not None
            and workflow_infrastructure._runloop_backend is not None
        ):
            try:
                # 尝试执行一个简单命令来检查沙盒是否存活
                # 如果沙盒已关闭 (DEVBOX_SHUTDOWN)，这里会抛出异常
                logger.info("[DeepAgent] 正在检查沙盒健康状态...")
                health_check = await asyncio.to_thread(
                    workflow_infrastructure._runloop_backend.execute,
                    "echo 'alive'",
                )
                if health_check.exit_code != 0:
                    logger.info(
                        f"[DeepAgent] 沙盒健康检查失败: exit code {health_check.exit_code}"
                    )
                    _deep_agent_instance = None
                    workflow_infrastructure._runloop_sandbox = None
                    workflow_infrastructure._runloop_backend = None
                else:
                    logger.info("[DeepAgent] 沙盒状态正常")
            except Exception as e:
                logger.info(f"[DeepAgent] 沙盒健康检查异常 (沙盒可能已关闭): {e}")
                _deep_agent_instance = None
                workflow_infrastructure._runloop_sandbox = None
                workflow_infrastructure._runloop_backend = None

        # MCP 连接健康检查：无论 _deep_agent_instance 是否已被其他检查重置，
        # 都要确保 MCP 客户端处于可用状态，避免定时任务执行后导致的 session 失效
        # 注意：不能使用 from-import，因为 _mcp_client_instance 是模块级变量，
        # from-import 会绑定导入时的值，后续重新赋值不会更新局部变量
        import workflow.mcpClient as mcpClient

        if (
            mcpClient._mcp_client_instance is None
            or not mcpClient._mcp_client_instance.is_connected()
        ):
            logger.info("[DeepAgent] 检测到 MCP 连接已断开，重置 Agent 实例触发重建")
            _deep_agent_instance = None
            await mcpClient.reset_mcp_client()

        if _deep_agent_instance is None:
            mcp_tools = await mcpClient.get_mcp_tools()

            # 如果 MCP 工具为空且客户端声称已连接（_tools_cache 被错误地缓存为空列表），
            # 强制重置客户端并重试一次，以恢复因 session 损坏而丢失的工具
            if not mcp_tools and mcpClient._mcp_client_instance is not None:
                logger.info(
                    "[DeepAgent] MCP 工具为空但客户端声称已连接，强制重置并重试"
                )
                await mcpClient.reset_mcp_client()
                mcp_tools = await mcpClient.get_mcp_tools()

            from scheduler.tools import get_scheduler_tools

            if include_scheduler_management_tools:
                scheduler_native_tools = get_scheduler_tools()
            else:
                scheduler_native_tools = []
            from workflow.hitl_tool import request_human_input

            agent_tools = (
                list(mcp_tools) + list(scheduler_native_tools) + [request_human_input]
            )
            _deep_agent_scheduler_tools_profile = include_scheduler_management_tools
            logger.info(
                f"[DeepAgent] 工具: MCP {len(mcp_tools)} + 定时任务 {len(scheduler_native_tools)} + HITL 1 = {len(agent_tools)}"
                f" (定时管理工具: {'开' if include_scheduler_management_tools else '关'})"
            )

            disabled_skills = get_disabled_skills_with_fallback()

            # 列出 skills 目录下所有技能文件夹
            skills_dir = SKILLS_DIR.replace("\\", "/")
            active_skills = []
            if os.path.exists(skills_dir):
                for item in os.listdir(skills_dir):
                    skill_path = os.path.join(skills_dir, item)
                    if os.path.isdir(skill_path):
                        active_skills.append(item)
            # 过滤掉被禁用的技能
            active_skills = [s for s in active_skills if s not in disabled_skills]

            uname = context_username.get()
            if uname:
                active_skills = PermissionEngine.filter_skills_by_explicit_allow(
                    str(uname), active_skills
                )

            # 根据是否使用沙盒设置虚拟路径前缀
            if USE_SANDBOX:
                virtual_skills_prefix = "/home/user/skills"
            else:
                virtual_skills_prefix = skills_dir  # 本地模式使用实际路径

            skills_files = {}

            # 沙盒文件大小限制（约 100KB）
            MAX_FILE_SIZE = 100 * 1024

            for skill_name in active_skills:
                skill_md_file = f"{skills_dir}/{skill_name}/SKILL.md"
                if os.path.exists(skill_md_file):
                    try:
                        file_size = os.path.getsize(skill_md_file)
                        if file_size > MAX_FILE_SIZE:
                            logger.info(
                                f"[DeepAgent] 跳过太大文件: {skill_md_file} ({file_size} bytes)"
                            )
                        else:
                            with open(skill_md_file, "r", encoding="utf-8") as f:
                                content = f.read()
                                virtual_path = (
                                    f"{virtual_skills_prefix}/{skill_name}/SKILL.md"
                                )
                                skills_files[virtual_path] = create_file_data(content)
                    except UnicodeDecodeError:
                        logger.info(f"[DeepAgent] 跳过二进制文件: {skill_md_file}")

                scripts_dir = f"{skills_dir}/{skill_name}/scripts"
                if os.path.exists(scripts_dir):
                    # 递归加载所有文件
                    for root, dirs, files in os.walk(scripts_dir):
                        for script_file in files:
                            # 加载所有文件，不限制扩展名
                            script_path = os.path.join(root, script_file)
                            rel_path = os.path.relpath(script_path, scripts_dir)
                            try:
                                file_size = os.path.getsize(script_path)
                                if file_size > MAX_FILE_SIZE:
                                    logger.info(
                                        f"[DeepAgent] 跳过太大文件: {script_path} ({file_size} bytes)"
                                    )
                                    continue

                                with open(script_path, "r", encoding="utf-8") as f:
                                    content = f.read()
                                    virtual_path = f"{virtual_skills_prefix}/{skill_name}/scripts/{rel_path}"
                                    # 转换反斜杠为正斜杠
                                    virtual_path = virtual_path.replace("\\", "/")
                                    skills_files[virtual_path] = create_file_data(
                                        content
                                    )
                            except UnicodeDecodeError:
                                # 跳过二进制文件
                                pass

            logger.info(
                f"[DeepAgent] 初始化 | 工具数: {len(agent_tools)}, Skills文件数: {len(skills_files)}"
            )
            logger.info(f"[DeepAgent] Skills目录: {skills_dir}")
            logger.info(f"[DeepAgent] 已加载Skills文件: {list(skills_files.keys())}")

            if agent_tools:
                logger.info(
                    f"[DeepAgent] 工具列表预览: {[t.name for t in agent_tools[:5]]}..."
                )
            else:
                logger.info(f"[DeepAgent] 警告: 没有获取到任何工具!")

            # 使用 SQLite 作为持久化存储（Checkpointer + 长期记忆 Store 共用同一个 db）
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from workflow.config import BASE_DIR

            checkpoint_dir = os.path.join(BASE_DIR, "checkpoints")
            os.makedirs(checkpoint_dir, exist_ok=True)
            checkpoint_db = os.path.join(checkpoint_dir, "checkpoints.db")

            conn = await aiosqlite.connect(checkpoint_db)
            checkpointer = AsyncSqliteSaver(conn)

            logger.info(f"[DeepAgent] 使用 SQLite 持久化存储: {checkpoint_db}")

            # 使用 Runloop 沙盒作为 backend 或本地后端
            backend = None

            if USE_SANDBOX:
                try:
                    # 每次都创建新沙盒，不复用（网络/同步 SDK，勿阻塞 asyncio 事件循环）
                    logger.info(f"[DeepAgent] 正在创建 Runloop 沙盒...")

                    def _sync_create_devbox():
                        os.environ["RUNLOOP_API_KEY"] = RUNLOOP_API_KEY
                        client = RunloopSDK(bearer_token=RUNLOOP_API_KEY)
                        return client.devbox.create()

                    workflow_infrastructure._runloop_sandbox = await asyncio.to_thread(
                        _sync_create_devbox
                    )
                    workflow_infrastructure._runloop_backend = RunloopSandbox(
                        devbox=workflow_infrastructure._runloop_sandbox
                    )
                    logger.info(
                        f"[DeepAgent] Runloop 沙盒创建成功: {workflow_infrastructure._runloop_sandbox.id}"
                    )

                    # 按需上传模式: 不在初始化时上传所有 skills
                    # 只在 agent 需要时通过 middleware 上传
                    skills_dir = "/home/user/skills"

                    # 创建一个空的 skills 目录结构
                    _rb = workflow_infrastructure._runloop_backend
                    if skills_files:
                        await asyncio.to_thread(_rb.execute, f"mkdir -p {skills_dir}")
                        logger.info(f"[DeepAgent] Skills 目录创建完成 (按需上传模式)")

                    # 确保 /charts 目录存在且可写
                    try:
                        logger.info(f"[DeepAgent] 初始化 /charts 目录...")
                        await asyncio.to_thread(_rb.execute, "sudo mkdir -p /charts")
                        await asyncio.to_thread(
                            _rb.execute, "sudo chmod -R 777 /charts"
                        )
                        await asyncio.to_thread(
                            _rb.execute, "mkdir -p /home/user/charts"
                        )
                    except Exception as e:
                        logger.info(f"[DeepAgent] 初始化 /charts 目录失败: {e}")

                    backend = workflow_infrastructure._runloop_backend
                except Exception as e:
                    logger.info(
                        f"[DeepAgent] Runloop 沙盒创建失败: {e}，回退到本地后端"
                    )
                    if workflow_infrastructure._runloop_sandbox is not None:
                        try:
                            workflow_infrastructure._runloop_sandbox.shutdown()
                        except:
                            pass
                        workflow_infrastructure._runloop_sandbox = None
                        workflow_infrastructure._runloop_backend = None

            if backend is None:
                logger.info(f"[DeepAgent] 使用本地后端 (VirtualEnvLocalShellBackend)")
                current_dir = os.getcwd().replace("\\", "/")
                backend = VirtualEnvLocalShellBackend(
                    root_dir=current_dir, virtual_mode=True
                )

            # 将 base_backend 包装为支持 /memories/ 路由的 CompositeBackend
            base_backend_ref = backend

            def _composite_backend_factory(runtime, _base=base_backend_ref):
                return _make_backend(runtime, _base)

            backend = _composite_backend_factory

            # 根据是否使用沙盒动态设置 skills 路径
            # 注意：USE_SANDBOX 已经在文件开头导入，但这里为了确保作用域正确，再次从 config 导入
            # 实际上，USE_SANDBOX 已经在文件顶部导入，可以直接使用
            # 但为了避免 UnboundLocalError，我们在这里不重新导入，而是直接使用
            # 如果之前有局部导入覆盖了全局变量，可能会导致问题
            # 检查之前的代码块，发现在 if USE_SANDBOX: 块中没有重新导入

            # 为了安全起见，我们使用全局导入的 USE_SANDBOX
            # 并确保 SKILLS_BASE_DIR 也被导入
            from workflow.config import SKILLS_BASE_DIR

            skills_path = "/home/user/skills/" if USE_SANDBOX else SKILLS_BASE_DIR + "/"

            # 将 SUBSYSTEM.md 注入框架内置的 general-purpose 子代理系统提示词
            # 框架始终将 general-purpose 放在第一位，无法通过配置覆盖，因此使用 monkey-patch
            # 使用 _GP_ORIGINAL_PROMPT 标记保存原始提示词，避免重复 patch 时内容累积
            try:
                from deepagents.middleware import subagents as _da_subagents_mod
                from workflow.subagents_config import (
                    _load_subsystem_template,
                    _substitute_system_prompt,
                )

                _subsystem_prompt = _load_subsystem_template()
                _gp_username = context_username.get() or _resolve_runtime_username()
                _subsystem_prompt = _substitute_system_prompt(
                    _subsystem_prompt, _gp_username
                )
                _gp_dict = _da_subagents_mod.GENERAL_PURPOSE_SUBAGENT
                if "_original_system_prompt" not in _gp_dict:
                    _gp_dict["_original_system_prompt"] = _gp_dict.get(
                        "system_prompt", ""
                    )
                _gp_dict["system_prompt"] = (
                    _subsystem_prompt + "\n\n" + _gp_dict["_original_system_prompt"]
                )
                logger.info(
                    "[Subagent] 已将 SUBSYSTEM.md 注入 general-purpose 子代理系统提示词"
                )
            except Exception as _e:
                logger.info(f"[Subagent] 注入 SUBSYSTEM.md 失败: {_e}")

            # 根据 ENABLE_SUBAGENTS 配置决定是否构建子代理
            if ENABLE_SUBAGENTS:
                from workflow.subagents_config import build_subagents

                uname_sa = context_username.get() or ""
                subagents = build_subagents(mcp_tools, uname_sa)
                logger.info(
                    f"[Subagent] 已启用 subagent 功能，共构建 {len(subagents)} 个子代理"
                )
            else:
                # 禁用子代理：设置为 None，这样 create_deep_agent 不会添加额外的子代理
                # 但请注意，create_deep_agent 会自动创建一个 general-purpose 子代理
                # 我们需要在创建 agent 后删除 task 工具
                subagents = None
                logger.info("[Subagent] 已禁用 subagent 功能，将移除 task 工具")

            from workflow.mcp_middleware import MCPMiddleware
            from workflow.middleware.content_security_middleware import (
                ContentSecurityMiddleware,
            )

            # 加载技能检查强制规则提示词，放在 BASE_AGENT_PROMPT 前以确保首因效应
            first_system_prompt = _load_first_system_prompt()

            _deep_agent_instance = create_deep_agent(
                model=mcp_llm,
                tools=agent_tools,
                skills=[skills_path],
                backend=backend,
                checkpointer=checkpointer,
                interrupt_on={
                    "write_file": False,
                    "read_file": False,
                    "edit_file": False,
                    "execute": False,
                },
                system_prompt=first_system_prompt,
                subagents=subagents,
                middleware=[
                    SkillFilterMiddleware(),
                    MCPMiddleware(),
                    ContentSecurityMiddleware(),
                    TaskTruncationMiddleware(max_tasks=MEMORY_SHORT_TERM_TASKS),
                    tool_logging_middleware,
                ],
            )

            # 如果禁用了 subagent，在系统提示词中明确告知不要使用 task 工具
            if not ENABLE_SUBAGENTS and _deep_agent_instance:
                try:
                    # 在 agent 的配置中添加一个标志，告知中间件禁用 task 工具
                    _deep_agent_instance.config.setdefault("metadata", {})[
                        "disable_task_tool"
                    ] = True
                    logger.info("[Subagent] task 工具已禁用")
                except Exception as e:
                    logger.info(f"[Subagent] 禁用 task 工具时出错: {e}")

            # 保存 skills_files 到实例中，供 middleware 使用
            if _deep_agent_instance:
                try:
                    # 尝试将 skills_files 附加到 agent 实例
                    # 注意：create_deep_agent 返回的是 CompiledGraph，可能无法直接添加属性
                    # 但我们可以尝试，或者使用全局变量
                    _deep_agent_instance.skills_files = skills_files
                except:
                    pass

            logger.info(f"[DeepAgent] 初始化完成")

    return _deep_agent_instance


async def execute_deep_agent(
    user_input: str,
    thread_id: str,
    session_id: str,
    chat_history: list,
    topic: str = None,
    requirement: str = "",
    username: str = "",
    wechat_context: str = "",
    contact_name: str = "",
    scheduled_task_invocation: bool = False,
    skills_names: Optional[list] = None,
    mcp_tool_names: Optional[list] = None,
) -> Dict[str, Any]:
    logger.info(f"\n========== DeepAgent 开始执行 ==========")
    logger.info(f"用户输入: {user_input[:200]}...")

    # 自动预处理桌面端上传的附件（解析每个文件为 Markdown 并注入 prompt）
    user_input = await _preprocess_desktop_attachments(user_input)
    resolved_user = _resolve_runtime_username(username)
    user_input = await _preprocess_collab_upstream_attachments(
        user_input, resolved_user
    )
    user_input = await _preprocess_knowledge_files(user_input, resolved_user)
    # 预处理完成后，按正确顺序重组最终输入
    user_input = _reassemble_user_input(
        user_input, skills_names or [], mcp_tool_names or []
    )

    # 设置工具监控上下文 (使用 contextvars)
    context_thread_id.set(thread_id)
    context_session_id.set(session_id)
    context_username.set(resolved_user)

    # 隔离"会话摘要/长期偏好"等按登录用户分片的数据
    from workflow import report_tools as _report_tools

    _report_tools.agent_username_ctx.set(resolved_user)

    # 从 agent 实例获取 skills_files
    if _deep_agent_instance and hasattr(_deep_agent_instance, "skills_files"):
        context_skills_files.set(_deep_agent_instance.skills_files)
    else:
        context_skills_files.set({})

    agent = await get_deep_agent(
        thread_id,
        session_id,
        include_scheduler_management_tools=not scheduled_task_invocation,
    )

    await asyncio.to_thread(
        insert_agent_event,
        thread_id=thread_id,
        session_id=session_id,
        event_type="agent_start",
        step=0,
        content=f"开始执行 DeepAgent，用户输入: {user_input[:100]}...",
        reasoning="DeepAgent 开始处理请求",
    )

    chat_history_str = ""
    mcp_history_str = ""

    from workflow.report_tools import (
        get_recent_summaries_by_username,
        search_relevant_summaries_by_topic,
        # get_recent_full_conversations,  # 暂时禁用，后续将从 checkpoint 加载短期记忆
    )

    # 短期记忆加载已禁用，后续将从 checkpoint 中加载
    short_term_memory = ""
    # if username:
    #     short_term_memory = await asyncio.to_thread(get_recent_full_conversations, 5)
    #     if short_term_memory:
    #         logger.info(f"[短期记忆] 已注入完整对话到 system_prompt，长度: {len(short_term_memory)}")
    #     else:
    #         logger.info(f"[短期记忆] 未找到完整对话记录")

    memory_summary = (
        await asyncio.to_thread(get_recent_summaries_by_username, username)
        if username
        else ""
    )
    if memory_summary:
        logger.info(f"[中期记忆] 已注入对话摘要到 system_prompt")

    # 基于主题的相关记忆搜索
    relevant_memory = ""
    if MEMORY_ENABLE_TOPIC_SEARCH and user_input and user_input.strip():
        search_topic = _strip_source_prefix(user_input)
        if _should_skip_relevant_memory_search(search_topic):
            logger.info(
                f"[记忆搜索] 查询过短或为泛化语，跳过历史记忆匹配: {search_topic}"
            )
        else:
            relevant_memory = await search_relevant_summaries_by_topic(
                topic=search_topic,
                limit=MEMORY_RELEVANT_TASKS_LIMIT,
                exclude_latest=MEMORY_SHORT_TERM_TASKS,
            )

        if relevant_memory:
            logger.info(f"[记忆搜索] 已加载相关记忆，长度: {len(relevant_memory)}")
        else:
            logger.info(f"[记忆搜索] 未找到相关记忆")

    long_term_memory = await _read_long_term_memory(contact_name or username)
    if long_term_memory:
        logger.info(f"[长期记忆] 已注入用户偏好到 system_prompt")

    system_prompt = _build_system_prompt(
        username,
        chat_history_str,
        mcp_history_str,
        wechat_context,
        memory_summary,
        long_term_memory,
        relevant_memory,
        short_term_memory=short_term_memory,
        scheduled_task_invocation=scheduled_task_invocation,
    )

    # 添加用户输入和特定要求
    full_input = user_input
    if requirement:
        full_input = f"{user_input}\n\n【特定要求】\n{requirement}"

    # 构造初始消息
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=full_input)]

    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": session_id,
            "username": username,
        },
        "recursion_limit": 50,
    }

    logger.info(
        f"[DeepAgent] config 检查 - thread_id: {thread_id}, session_id: {session_id}, checkpoint_ns: {session_id}"
    )
    logger.info(f"[DeepAgent] 开始调用 invoke...")

    final_state = None
    full_final_content = ""
    step_counter = 0

    try:
        async for event in agent.astream({"messages": messages}, config=config):
            # 处理流式事件
            for key, value in event.items():
                step_counter += 1
                if key == "agent":
                    # Agent 思考和回复
                    if "messages" in value and value["messages"]:
                        last_msg = value["messages"][-1]
                        if isinstance(last_msg, AIMessage):
                            content = last_msg.content
                            if content:
                                logger.info(
                                    f"[DeepAgent] Agent 回复: {content[:100]}..."
                                )
                                full_final_content = content

                                # 记录到数据库
                                await asyncio.to_thread(
                                    insert_agent_event,
                                    thread_id=thread_id,
                                    session_id=session_id,
                                    event_type="agent_response",
                                    step=step_counter,
                                    content=content,
                                    reasoning="",
                                )

                elif key == "tools":
                    # 工具调用结果
                    if "messages" in value and value["messages"]:
                        last_msg = value["messages"][-1]
                        if isinstance(last_msg, ToolMessage):
                            logger.info(
                                f"[DeepAgent] 工具返回: {last_msg.name} -> {str(last_msg.content)[:100]}..."
                            )

                            # 记录到数据库
                            await asyncio.to_thread(
                                insert_agent_event,
                                thread_id=thread_id,
                                session_id=session_id,
                                event_type="tool_result",
                                step=step_counter,
                                content=str(last_msg.content)[:1000],
                                reasoning=f"工具 {last_msg.name} 执行完成",
                            )

            final_state = event

        logger.info(f"[DeepAgent] 执行完成")

        # 记录结束事件
        await asyncio.to_thread(
            insert_agent_event,
            thread_id=thread_id,
            session_id=session_id,
            event_type="agent_end",
            step=step_counter + 1,
            content="DeepAgent 执行结束",
            reasoning="任务完成",
        )

        # 尝试下载生成的文件
        wechat_contact = _extract_wechat_contact(wechat_context)
        await _download_sandbox_files(username, full_final_content, wechat_contact)

        # 后评估：偏好提取、技能创建、技能改进
        if username and full_final_content:
            from workflow.post_task_evaluator import run_post_task_evaluation
            from workflow.config import POST_TASK_EVALUATION_ENABLED

            if POST_TASK_EVALUATION_ENABLED:
                asyncio.create_task(
                    run_post_task_evaluation(
                        user_input=user_input,
                        full_final_content=full_final_content,
                        username=username,
                        contact_name=contact_name or username or "",
                        thread_id=thread_id,
                        session_id=session_id,
                        full_conversation=f"用户: {user_input}\n\nAI: {full_final_content}",
                    )
                )

        return {
            "result": full_final_content,
            "thread_id": thread_id,
            "session_id": session_id,
        }

    except Exception as e:
        logger.info(f"[DeepAgent] 执行异常: {e}")
        traceback.print_exc()

        await asyncio.to_thread(
            insert_agent_event,
            thread_id=thread_id,
            session_id=session_id,
            event_type="error",
            step=step_counter + 1,
            content=f"执行出错: {str(e)}",
            reasoning="系统异常",
        )

        return {
            "result": f"执行出错: {str(e)}",
            "thread_id": thread_id,
            "session_id": session_id,
        }


def _agent_step_reasoning_meta(event_data: dict) -> str:
    """Serialize tool call/result metadata for agent_execution_logs.reasoning."""
    meta: dict = {}
    if event_data.get("tools_called"):
        meta["tools_called"] = event_data["tools_called"]
    if event_data.get("tool_results"):
        meta["tool_results"] = event_data["tool_results"]
    if event_data.get("generated_files"):
        meta["generated_files"] = event_data["generated_files"]
    if not meta:
        return str(event_data.get("reasoning") or "")
    try:
        return json.dumps(meta, ensure_ascii=False)[:8000]
    except Exception:
        return ""


def _agent_step_tool_name_field(event_data: dict) -> str | None:
    names: list[str] = []
    for tc in event_data.get("tools_called") or []:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or tc.get("tool_name") or "").strip()
        if name:
            names.append(name)
    if not names:
        return None
    return ",".join(names)[:255]


def _sanitize_agent_step_event_content(event_data: dict) -> None:
    """剥离 generated_files JSON、整理 content，供 DB 与 SSE 共用。"""
    content = str(event_data.get("content") or "")
    if not content:
        return

    gf_extracted: list = []
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if code_block_match:
        try:
            gf_data = json.loads(code_block_match.group(1))
            gf_extracted = [p for p in gf_data.get("generated_files", []) if p]
        except Exception:
            pass
    if not gf_extracted:
        bare_match = re.search(
            r'\{[^{}]*?"generated_files"\s*:\s*\[([^\]]*)\][^{}]*?\}',
            content,
            re.DOTALL,
        )
        if bare_match:
            try:
                gf_data = json.loads(bare_match.group(0))
                gf_extracted = [p for p in gf_data.get("generated_files", []) if p]
            except Exception:
                pass
    if gf_extracted:
        event_data["generated_files"] = gf_extracted

    content = re.sub(r"```json\s*\{.*?\}\s*```", "", content, flags=re.DOTALL)
    content = re.sub(r"```\s*\{.*?\}\s*```", "", content, flags=re.DOTALL)
    content = re.sub(
        r'```(?:json)?\s*\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}\s*```',
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r'\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}',
        "",
        content,
        flags=re.DOTALL,
    )
    event_data["content"] = content.strip()


def _agent_step_has_display_payload(event_data: dict) -> bool:
    """桌面端思考区仅展示有实质内容的步骤，跳过 middleware 等空更新。"""
    content = str(event_data.get("content") or "").strip()
    if content:
        return True
    if event_data.get("generated_files"):
        return True
    if event_data.get("tools_called"):
        return True
    for tr in event_data.get("tool_results") or []:
        if isinstance(tr, dict) and str(tr.get("result") or "").strip():
            return True
    return False


async def stream_deep_agent(
    user_input: str,
    thread_id: str,
    session_id: str,
    chat_history: list,
    topic: str = None,
    requirement: str = "",
    username: str = "",
    wechat_context: str = "",
    contact_name: str = "",
    scheduled_task_invocation: bool = False,
    resume_command: Optional[dict] = None,
    skills_names: Optional[list] = None,
    mcp_tool_names: Optional[list] = None,
):
    # 自动预处理桌面端上传的附件（解析每个文件为 Markdown 并注入 prompt）
    if resume_command is None:
        user_input = await _preprocess_desktop_attachments(user_input)

    # 设置工具监控上下文 (使用 contextvars)
    context_thread_id.set(thread_id)
    context_session_id.set(session_id)
    resolved_username = _resolve_runtime_username(username)
    if resume_command is None:
        user_input = await _preprocess_collab_upstream_attachments(
            user_input, resolved_username
        )
        user_input = await _preprocess_knowledge_files(user_input, resolved_username)
        # 预处理完成后，按正确顺序重组最终输入
        user_input = _reassemble_user_input(
            user_input, skills_names or [], mcp_tool_names or []
        )
    context_username.set(resolved_username)

    # 从 agent 实例获取 skills_files
    if _deep_agent_instance and hasattr(_deep_agent_instance, "skills_files"):
        context_skills_files.set(_deep_agent_instance.skills_files)
    else:
        context_skills_files.set({})

    # 隔离“会话摘要/长期偏好”等按登录用户分片的数据。
    # report_tools 通过 agent_username_ctx 读取，而不是直接依赖全局 .env AGENT_USERNAME。
    from workflow import report_tools as _report_tools

    _token_agent_username = _report_tools.agent_username_ctx.set(resolved_username)

    agent = await get_deep_agent(
        thread_id,
        session_id,
        include_scheduler_management_tools=not scheduled_task_invocation,
    )

    chat_history_str = ""
    mcp_history_str = ""

    from workflow.report_tools import (
        get_recent_summaries_by_username,
        search_relevant_summaries_by_topic,
        # get_recent_full_conversations,  # 暂时禁用，后续将从 checkpoint 加载短期记忆
    )

    # 短期记忆加载已禁用，后续将从 checkpoint 中加载
    short_term_memory = ""
    # if username:
    #     short_term_memory = await asyncio.to_thread(get_recent_full_conversations, 5)
    #     if short_term_memory:
    #         logger.info(f"[短期记忆] 已注入完整对话到 system_prompt，长度: {len(short_term_memory)}")
    #     else:
    #         logger.info(f"[短期记忆] 未找到完整对话记录")

    memory_summary = (
        await asyncio.to_thread(get_recent_summaries_by_username, resolved_username)
        if resolved_username
        else ""
    )
    if memory_summary:
        logger.info(f"[中期记忆] 已注入对话摘要到 system_prompt")

    # 基于主题的相关记忆搜索
    relevant_memory = ""
    logger.info(f"[记忆搜索调试] 开始检查是否开启主题搜索")
    logger.info(
        f"[记忆搜索调试] MEMORY_ENABLE_TOPIC_SEARCH = {MEMORY_ENABLE_TOPIC_SEARCH}"
    )
    logger.info(
        f"[记忆搜索调试] user_input 是否非空: {bool(user_input and user_input.strip())}"
    )
    logger.info(f"[记忆搜索调试] resolved_username = {resolved_username}")
    logger.info(
        f"[记忆搜索调试] MEMORY_RELEVANT_TASKS_LIMIT = {MEMORY_RELEVANT_TASKS_LIMIT}"
    )
    logger.info(f"[记忆搜索调试] MEMORY_SHORT_TERM_TASKS = {MEMORY_SHORT_TERM_TASKS}")

    if MEMORY_ENABLE_TOPIC_SEARCH and user_input and user_input.strip():
        search_topic = _strip_source_prefix(user_input)
        logger.info(f"[记忆搜索] 搜索主题: {search_topic[:200]}")
        if _should_skip_relevant_memory_search(search_topic):
            logger.info(
                f"[记忆搜索] 查询过短或为泛化语，跳过历史记忆匹配: {search_topic}"
            )
        else:
            relevant_memory = await search_relevant_summaries_by_topic(
                topic=search_topic,
                limit=MEMORY_RELEVANT_TASKS_LIMIT,
                exclude_latest=MEMORY_SHORT_TERM_TASKS,
            )

        if relevant_memory:
            logger.info(f"[记忆搜索] 已加载相关记忆，长度: {len(relevant_memory)}")
        else:
            logger.info(f"[记忆搜索] 未找到相关记忆")

    long_term_memory = await _read_long_term_memory(contact_name or resolved_username)
    if long_term_memory:
        logger.info(f"[长期记忆] 已注入用户偏好到 system_prompt")

    system_prompt = _build_system_prompt(
        resolved_username,
        chat_history_str,
        mcp_history_str,
        wechat_context,
        memory_summary,
        long_term_memory,
        relevant_memory,
        short_term_memory=short_term_memory,
        scheduled_task_invocation=scheduled_task_invocation,
    )

    stream_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": session_id,
            "username": resolved_username,
        },
        "stream_mode": "updates",
    }

    logger.info(
        f"[DeepAgent] stream_config 检查 - thread_id: {thread_id}, session_id: {session_id}, checkpoint_ns: {session_id}"
    )

    step_counter = 0
    full_final_content = ""

    if resume_command is not None:
        # 自动预处理 HITL 恢复时上传的附件（解析每个文件为 Markdown 并注入 ctx）
        resume_command = await _preprocess_hitl_attachments(resume_command)
        input_payload = Command(resume=resume_command)
        logger.info(
            f"[DeepAgent] HITL 恢复模式 | thread_id: {thread_id} | resume_command: {resume_command}"
        )
    else:
        input_payload = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
            ]
        }

    try:
        async for event in agent.astream(input_payload, config=stream_config):
            if isinstance(event, dict) and "__interrupt__" in event:
                interrupts = event["__interrupt__"]
                if interrupts:
                    iv = (
                        interrupts[0].value
                        if hasattr(interrupts[0], "value")
                        else interrupts[0]
                    )
                    logger.info(
                        f"[DeepAgent] 检测到 HITL interrupt | thread_id: {thread_id} | value: {iv}"
                    )
                    yield {
                        "event_type": "hitl_wait",
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "hitl_type": iv.get("hitl_type", "confirm")
                        if isinstance(iv, dict)
                        else "confirm",
                        "message": iv.get("message", "")
                        if isinstance(iv, dict)
                        else str(iv),
                        "options": iv.get("options", [])
                        if isinstance(iv, dict)
                        else [],
                        "placeholder": iv.get("placeholder")
                        if isinstance(iv, dict)
                        else None,
                        "allow_attachments": iv.get("allow_attachments", False)
                        if isinstance(iv, dict)
                        else False,
                        "multi_select": iv.get("multi_select", False)
                        if isinstance(iv, dict)
                        else False,
                    }
                return

            step_counter += 1

            event_data = {
                "event_type": "agent_step",
                "step": step_counter,
                "thread_id": thread_id,
                "session_id": session_id,
                "tools_called": [],
                "tool_results": [],
            }

            if isinstance(event, dict):
                for node_name, node_output in event.items():
                    event_data["node_name"] = node_name
                    if isinstance(node_output, dict):
                        if "messages" in node_output:
                            messages = node_output["messages"]
                            if hasattr(messages, "__iter__") and not isinstance(
                                messages, str
                            ):
                                try:
                                    for msg in messages:
                                        if isinstance(msg, AIMessage):
                                            event_data["content"] = msg.content
                                            # 累积 AI 回复内容
                                            if msg.content:
                                                full_final_content = msg.content

                                            if (
                                                hasattr(msg, "tool_calls")
                                                and msg.tool_calls
                                            ):
                                                for tc in msg.tool_calls:
                                                    if isinstance(tc, dict):
                                                        tool_name = (
                                                            tc.get("name", "")
                                                            or tc.get("tool_name", "")
                                                            or ""
                                                        )
                                                        tool_args = (
                                                            tc.get("args", {}) or {}
                                                        )
                                                    else:
                                                        tool_name = (
                                                            getattr(tc, "name", "")
                                                            or getattr(
                                                                tc, "tool_name", ""
                                                            )
                                                            or ""
                                                        )
                                                        tool_args = (
                                                            getattr(tc, "args", None)
                                                            or {}
                                                        )
                                                    event_data["tools_called"].append(
                                                        {
                                                            "name": tool_name,
                                                            "args": tool_args,
                                                        }
                                                    )
                                        elif (
                                            hasattr(msg, "tool_call_id")
                                            and msg.tool_call_id
                                        ):
                                            tool_result = getattr(msg, "content", "")
                                            event_data["tool_results"].append(
                                                {
                                                    "name": getattr(msg, "name", "")
                                                    or "",
                                                    "result": str(tool_result)[:2000]
                                                    if tool_result
                                                    else "",
                                                }
                                            )
                                except Exception:
                                    pass

            _sanitize_agent_step_event_content(event_data)

            await asyncio.to_thread(
                insert_agent_event,
                thread_id=thread_id,
                session_id=session_id,
                event_type=event_data.get("event_type", "agent_step"),
                step=step_counter,
                content=event_data.get("content", ""),
                tool_name=_agent_step_tool_name_field(event_data),
                reasoning=_agent_step_reasoning_meta(event_data),
            )

            if _agent_step_has_display_payload(event_data):
                yield event_data

        from workflow.user_display_names import apply_display_names_to_text

        full_final_content = apply_display_names_to_text(full_final_content)

        # 打印最终结果以便调试
        logger.info(f"\n========== DeepAgent 最终完整回复 ==========")
        logger.info(full_final_content)
        logger.info("==========================================\n")

        # 写入结束事件，供 is_agent_busy() 判断任务已完成
        await asyncio.to_thread(
            insert_agent_event,
            thread_id=thread_id,
            session_id=session_id,
            event_type="agent_end",
            step=step_counter + 1,
            content="stream_deep_agent 执行结束",
            reasoning="任务完成",
        )

        wechat_contact = _extract_wechat_contact(wechat_context)
        await _download_sandbox_files(username, full_final_content, wechat_contact)

        if username and full_final_content:
            from workflow.report_tools import (
                generate_and_save_summary,
                load_full_conversation_from_checkpoint,
            )

            full_conversation = await load_full_conversation_from_checkpoint(
                thread_id, session_id
            )

            if not full_conversation or not full_conversation.strip():
                full_conversation = f"用户: {user_input}\n\nAI: {full_final_content}"
                logger.info(f"[记忆] 使用简单格式保存对话")

            asyncio.create_task(
                generate_and_save_summary(
                    thread_id,
                    user_input,
                    full_final_content,
                    session_id,
                    full_conversation,
                )
            )

            # 后评估：偏好提取、技能创建、技能改进
            from workflow.post_task_evaluator import run_post_task_evaluation
            from workflow.config import POST_TASK_EVALUATION_ENABLED

            if POST_TASK_EVALUATION_ENABLED:
                asyncio.create_task(
                    run_post_task_evaluation(
                        user_input=user_input,
                        full_final_content=full_final_content,
                        username=username,
                        contact_name=contact_name or username or "",
                        thread_id=thread_id,
                        session_id=session_id,
                        full_conversation=full_conversation or "",
                    )
                )

    except GeneratorExit:
        # 调用方（SSE 生成器）被客户端关闭时抛出，属于正常的流关闭行为，直接返回
        logger.info("[DeepAgent] SSE 流已被客户端关闭（GeneratorExit），正常退出")
        return
    except Exception as e:
        from workflow.content_security import ContentSecurityBlockedError

        if isinstance(e, ContentSecurityBlockedError):
            # 内容安全拦截：以拦截消息作为最终回复推送给桌面端，阻止 LLM 生成误导性"成功"回复
            logger.info("[DeepAgent] 内容安全拦截，终止执行: {}", e.violations)
            # 异步写入拦截日志到数据库，供管理端安全合规页面查询
            try:
                from admin_api.services.security_log_service import insert_intercept_log

                insert_intercept_log(
                    username=resolved_username or "",
                    channel="unknown",
                    intercept_type="keyword",
                    tool_name="",
                    violations=e.violations or [],
                    raw_content="",
                    block_message=e.block_message or "",
                    mate_name=os.getenv("MATE_NAME", ""),
                )
            except Exception as log_err:
                logger.error("[DeepAgent] 写入安全拦截日志失败: {}", log_err)
            yield {
                "event_type": "done",
                "step": step_counter,
                "thread_id": thread_id,
                "session_id": session_id,
                "content": e.block_message,
            }
            return
        yield {
            "event_type": "error",
            "step": step_counter,
            "thread_id": thread_id,
            "session_id": session_id,
            "content": f"执行错误: {str(e)}",
            "reasoning": "",
        }
    finally:
        try:
            _report_tools.agent_username_ctx.reset(_token_agent_username)
        except Exception as e:
            logger.info("[DeepAgent] reset agent_username_ctx skipped: {}", e)
