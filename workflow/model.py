import os
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, ToolMessage
from workflow.config import MCP_LLM_CONFIG, LLM_PROVIDER, MCP_TEXT_LLM_CONFIG
from loguru import logger


PROMPT_DIR = Path(__file__).parent.parent / "prompt"


class FilePromptTemplate(PromptTemplate):
    """自定义 PromptTemplate，支持从文件动态加载/重载提示词。"""

    file_path: str

    def format(self, **kwargs) -> str:
        self.reload()
        return super().format(**kwargs)

    def reload(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.template = f.read()

    @classmethod
    def from_file(
        cls, filename: str, input_variables: list, partial_variables: dict = None
    ):
        file_path = PROMPT_DIR / filename
        with open(file_path, "r", encoding="utf-8") as f:
            template = f.read()
        return cls(
            input_variables=input_variables,
            template=template,
            file_path=str(file_path),
            partial_variables=partial_variables or {},
        )


def load_prompt(filename: str) -> str:
    """从 prompt 目录加载提示词文件内容"""
    file_path = PROMPT_DIR / filename
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def get_ppt_outline_prompt() -> str:
    """获取 PPT 大纲生成提示词"""
    return load_prompt("PPT_OUTLINE_PROMPT.md")


def get_ppt_page_expand_prompt() -> str:
    """获取 PPT 页面内容扩展提示词"""
    return load_prompt("PPT_PAGE_EXPAND_PROMPT.md")


def get_image_analysis_prompt() -> str:
    """获取图片内容分析提示词"""
    return load_prompt("IMAGE_ANALYSIS_PROMPT.md")


def create_llm_instance(**overrides):
    """
    根据 LLM_PROVIDER 创建主模型实例，支持参数覆盖。
    - dashscope → ChatOpenAI
    - deepseek  → ChatDeepSeek
    """
    config = dict(MCP_LLM_CONFIG)
    config.update(overrides)
    if LLM_PROVIDER == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(**config)
    else:
        return ChatOpenAI(**config)


def create_text_llm_instance(**overrides):
    """
    根据 LLM_PROVIDER 创建文本模型实例（PPT生成、摘要等轻量任务），支持参数覆盖。
    """
    config = dict(MCP_TEXT_LLM_CONFIG)
    config.update(overrides)
    if LLM_PROVIDER == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(**config)
    else:
        return ChatOpenAI(**config)


def _repair_tool_call_integrity(messages: list) -> list:
    """修复消息列表中的工具调用完整性

    两种场景会导致不完整：
    1. 用户点击"停止"：AIMessage(tool_calls=[A,B,C]) 写入 checkpoint，但工具执行被中断，
       只有部分 ToolMessage 写入成功
    2. LLM 输出 invalid_tool_call（args 为 string 而非 dict，格式不合法），
       LangGraph 工具节点无法处理，未生成对应 ToolMessage，
       但 LangChain 的 OpenAI block translator 仍会将其转换为 API 格式发送

    关键：invalid_tool_calls 存储在 msg.invalid_tool_calls 字段（不是 msg.tool_calls），
    但 OpenAI block translator 回退查找时会从中读取并发送给 API，
    API 仍会校验其 tool_call_id 是否有对应的 tool 消息。
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

    # 2. 收集所有 AIMessage 声明要调用的 id（同时检查 tool_calls 和 invalid_tool_calls）
    all_expected_tool_call_ids: set = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            # 正常 tool_calls
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = (
                    tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                )
                if tc_id:
                    all_expected_tool_call_ids.add(tc_id)
            # invalid_tool_calls（LLM 输出格式不合法的工具调用）
            for tc in getattr(msg, "invalid_tool_calls", None) or []:
                tc_id = (
                    tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                )
                if tc_id:
                    all_expected_tool_call_ids.add(tc_id)
            # additional_kwargs.tool_calls（API 转换时直接使用此字段）
            for tc in msg.additional_kwargs.get("tool_calls") or []:
                if isinstance(tc, dict) and "id" in tc:
                    all_expected_tool_call_ids.add(tc["id"])

    # 3. 构建修复后的消息列表
    repaired = []
    dirty = False
    for msg in messages:
        if isinstance(msg, AIMessage):
            valid_tool_calls = getattr(msg, "tool_calls", None) or []
            invalid_tool_calls = getattr(msg, "invalid_tool_calls", None) or []
            all_tool_calls = list(valid_tool_calls) + list(invalid_tool_calls)

            if not all_tool_calls:
                repaired.append(msg)
                continue

            # 过滤：只保留有对应 ToolMessage 的 tool_calls
            fixed_valid_tool_calls = [
                tc
                for tc in valid_tool_calls
                if (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None))
                in existing_tool_call_ids
            ]
            fixed_invalid_tool_calls = [
                tc
                for tc in invalid_tool_calls
                if (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None))
                in existing_tool_call_ids
            ]
            removed_valid = len(valid_tool_calls) - len(fixed_valid_tool_calls)
            removed_invalid = len(invalid_tool_calls) - len(fixed_invalid_tool_calls)

            if removed_valid + removed_invalid > 0:
                dirty = True
                logger.info(
                    f"[LLM消息修复] AIMessage 移除 {removed_valid} 个孤立 tool_calls"
                    f" + {removed_invalid} 个孤立 invalid_tool_calls"
                    f"（原始 tool_calls={len(valid_tool_calls)}, invalid={len(invalid_tool_calls)}）"
                )

            # 同时过滤 additional_kwargs.tool_calls（API 转换时直接读取此字段）
            fixed_additional_tool_calls = [
                tc
                for tc in (msg.additional_kwargs.get("tool_calls") or [])
                if isinstance(tc, dict) and tc.get("id") in existing_tool_call_ids
            ]

            fixed_all = fixed_valid_tool_calls + fixed_invalid_tool_calls
            if fixed_all:
                new_msg = msg.model_copy(
                    update={
                        "tool_calls": fixed_valid_tool_calls,
                        "invalid_tool_calls": fixed_invalid_tool_calls,
                        "additional_kwargs": {
                            **msg.additional_kwargs,
                            "tool_calls": fixed_additional_tool_calls,
                        },
                    }
                )
                repaired.append(new_msg)
                continue
            else:
                dirty = True
                logger.info(
                    "[LLM消息修复] AIMessage 所有 tool_calls/invalid_tool_calls 均为孤立，清空"
                )
                new_msg = msg.model_copy(
                    update={
                        "tool_calls": [],
                        "invalid_tool_calls": [],
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
                    f"[LLM消息修复] 移除孤立 ToolMessage (tool_call_id={tc_id})"
                )
                continue

        repaired.append(msg)

    if dirty:
        logger.info(
            f"[LLM消息修复] 修复完成：原始 {len(messages)} 条 → {len(repaired)} 条"
        )

    return repaired


def _salvage_invalid_tool_calls(messages: list) -> list:
    """尝试拯救 invalid_tool_calls：将 args 字符串尝试 json.loads 解析，成功则转为正常 tool_call

    LLM 有时会将 tool_call 的 arguments 输出为被额外序列化的 JSON 字符串
    （例如 content 参数过长时），导致 LangChain 的 default_tool_parser 中 json.loads 失败。
    本函数在完整性修复之前，先尝试对 invalid_tool_calls 的参数做二次解析。
    """
    import json as json_mod

    dirty = False
    repaired = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            repaired.append(msg)
            continue

        invalid_tool_calls = getattr(msg, "invalid_tool_calls", None) or []
        if not invalid_tool_calls:
            repaired.append(msg)
            continue

        valid_tool_calls = list(getattr(msg, "tool_calls", None) or [])
        remaining_invalid = []

        for itc in invalid_tool_calls:
            raw_args = (
                itc.get("args") if isinstance(itc, dict) else getattr(itc, "args", None)
            )
            if not isinstance(raw_args, str):
                remaining_invalid.append(itc)
                continue
            try:
                parsed = json_mod.loads(raw_args)
                if isinstance(parsed, dict):
                    from langchain_core.messages.tool import (
                        tool_call as create_tool_call,
                    )

                    new_tc = create_tool_call(
                        name=itc.get("name", "unknown"),
                        args=parsed,
                        id=itc.get("id"),
                    )
                    valid_tool_calls.append(new_tc)
                    dirty = True
                    logger.info(
                        f"[LLM消息拯救] 成功拯救 invalid_tool_call '{itc.get('name')}' → 转为正常 tool_call"
                    )
                    continue
            except (json_mod.JSONDecodeError, TypeError, ValueError):
                pass

            remaining_invalid.append(itc)

        if dirty:
            new_msg = msg.model_copy(
                update={
                    "tool_calls": valid_tool_calls,
                    "invalid_tool_calls": remaining_invalid,
                    "additional_kwargs": {
                        **msg.additional_kwargs,
                        "tool_calls": valid_tool_calls + remaining_invalid,
                    },
                }
            )
            repaired.append(new_msg)
        else:
            repaired.append(msg)

    return repaired


class RepairToolCallLLM:
    """LLM 代理包装器：在每次 API 调用前自动修复消息中的孤立 tool_calls

    这是防止 "insufficient tool messages following tool_calls message" 错误
    的最后一道防线。所有经过该 LLM 的 ainvoke/invoke 调用都会自动修复消息。

    修复流程：
    1. _salvage_invalid_tool_calls：拯救可解析的 invalid_tool_calls → tool_calls
    2. _repair_tool_call_integrity：清除孤立 tool_calls 和孤立 ToolMessage
    """

    def __init__(self, llm):
        self._llm = llm

    async def ainvoke(self, input_, config=None, *, stop=None, **kwargs):
        """异步调用：修复消息后转发"""
        return await self._llm.ainvoke(
            self._repair_input(input_), config=config, stop=stop, **kwargs
        )

    def invoke(self, input_, config=None, *, stop=None, **kwargs):
        """同步调用：修复消息后转发"""
        return self._llm.invoke(
            self._repair_input(input_), config=config, stop=stop, **kwargs
        )

    def bind_tools(self, tools, **kwargs):
        """绑定工具并返回新的包装实例（LangGraph agent 内部会调用此方法）"""
        bound = self._llm.bind_tools(tools, **kwargs)
        return RepairToolCallLLM(bound)

    def bind(self, **kwargs):
        """绑定参数并返回新的包装实例"""
        bound = self._llm.bind(**kwargs)
        return RepairToolCallLLM(bound)

    @property
    def profile(self):
        return getattr(self._llm, "profile", None)

    @profile.setter
    def profile(self, value):
        self._llm.profile = value

    def _repair_input(self, input_):
        """两步修复消息：先拯救 invalid_tool_calls，再修复完整性"""
        if isinstance(input_, list):
            saved = _salvage_invalid_tool_calls(input_)
            return _repair_tool_call_integrity(saved)
        return input_

    @property
    def _identifying_params(self):
        return getattr(self._llm, "_identifying_params", {})

    @property
    def _llm_type(self):
        return getattr(self._llm, "_llm_type", "repair_tool_call_llm")

    def __getattr__(self, name):
        """将其他所有属性和方法委托给底层 LLM"""
        return getattr(self._llm, name)


mcp_llm = RepairToolCallLLM(create_llm_instance())

# 注入超大 max_input_tokens，使 deepagents 内置的 SummarizationMiddleware 触发阈值极大
# trigger=("fraction", 0.85) → 0.85 * 10_000_000_000 ≈ 85 亿 tokens，实际永远不会触发
# 历史消息截断完全由 TaskTruncationMiddleware 按任务数控制，Checkpointer 数据不会被删除
mcp_llm.profile = {"max_input_tokens": 10_000_000_000}
