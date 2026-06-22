import asyncio
import functools
from typing import List

from langchain_core.tools import BaseTool
from loguru import logger

from workflow.report_tools import load_mcp_config
from workflow.robust_mcp_client import RobustMultiServerMCPClient

try:
    from langchain_mcp_adapters.tools import (
        _convert_call_tool_result as original_convert,
    )
    from langchain_mcp_adapters.tools import ToolException

    def patched_convert_call_tool_result(call_tool_result):
        """修改版：将错误转换为返回消息而不是抛出异常"""
        if hasattr(call_tool_result, "isError") and call_tool_result.isError:
            error_parts = []
            for content in call_tool_result.content:
                if hasattr(content, "text"):
                    error_parts.append(content.text)
                elif hasattr(content, "texts"):
                    error_parts.extend(content.texts)
            error_msg = "\n".join(error_parts) if error_parts else "未知错误"
            error_text = f"工具执行出错: {error_msg}"
            return ([{"type": "text", "text": error_text}], None)
        return original_convert(call_tool_result)

    import langchain_mcp_adapters.tools

    langchain_mcp_adapters.tools._convert_call_tool_result = (
        patched_convert_call_tool_result
    )
    logger.info("已 patch langchain_mcp_adapters 错误处理")
except ImportError as e:
    logger.info("无法 patch langchain_mcp_adapters: {}", e)


def _add_tool_prefix(tool: BaseTool) -> BaseTool:
    """
    为工具添加服务器名称前缀，避免与内置工具重名。
    例如：read_file -> ai_report_word_pdf_read_file
    """
    # 获取服务器名称作为前缀
    server_name = getattr(tool, "server_name", None) or getattr(tool, "McpServer", None)

    if not server_name:
        # 尝试从工具的 metadata 获取
        metadata = getattr(tool, "metadata", None) or {}
        # 优先查找 server_name (RobustMultiServerMCPClient 注入的字段)
        # 其次查找 server (部分旧代码可能使用的字段)
        # 最后默认为 mcp
        server_name = metadata.get("server_name") or metadata.get("server") or "mcp"

    # 保留完整的服务器名称，只将连字符和空格替换为下划线
    safe_name = str(server_name).replace("-", "_").replace(" ", "_")

    # 添加前缀（如果工具名还没有这个前缀）
    if safe_name and not tool.name.startswith(f"{safe_name}_"):
        tool.name = f"{safe_name}_{tool.name}"
        # 更新 description 中的引用
        if hasattr(tool, "description") and tool.description:
            tool.description = f"[{server_name}] " + tool.description

    return tool


def _wrap_tool_with_error_handling(tool: BaseTool) -> BaseTool:
    """
    包装工具的调用方法，使其在出错时返回错误信息而不是抛出异常。
    这样错误会被返回给 Agent，让 Agent 决定如何处理。
    """
    tool_name = tool.name

    original_func = tool.func if hasattr(tool, "func") else None
    original_coroutine = (
        tool.coroutine if hasattr(tool, "coroutine") and tool.coroutine else None
    )

    if original_coroutine:

        @functools.wraps(original_coroutine)
        async def wrapped_coroutine(*args, **kwargs):
            logger.debug(
                "[工具包装] 开始执行工具: {}, args={}, kwargs={}",
                tool_name,
                args,
                kwargs,
            )
            try:
                result = await original_coroutine(*args, **kwargs)
                logger.debug(
                    "[工具包装] 工具执行成功: {}, result_type={}, result={}",
                    tool_name,
                    type(result).__name__,
                    str(result)[:200],
                )
                return result
            except Exception as e:
                logger.error(
                    "[工具包装] 工具执行异常: {}, error_type={}, error={}",
                    tool_name,
                    type(e).__name__,
                    e,
                )
                try:
                    from langgraph.errors import GraphBubbleUp

                    if isinstance(e, GraphBubbleUp):
                        raise
                except ImportError:
                    pass
                # 检查是否是连接关闭错误 (ClosedResourceError 或 ConnectionError)
                error_type = type(e).__name__
                if (
                    "ClosedResourceError" in error_type
                    or "ConnectionClosed" in error_type
                    or "BrokenPipeError" in error_type
                ):
                    logger.info(
                        "[MCP] 检测到连接断开 ({})，尝试重置客户端并重试...", error_type
                    )
                    try:
                        # 1. 重置客户端（创建全新实例，彻底丢弃旧连接）
                        await reset_mcp_client()

                        # 2. 获取新客户端并重新建立所有连接
                        client = await get_mcp_client()

                        # 3. 获取已添加前缀的完整工具列表（与 tool.name 格式一致）
                        new_wrapped_tools = await get_mcp_tools(add_prefix=True)

                        # 4. 按带前缀的名称匹配目标工具
                        target_tool = next(
                            (t for t in new_wrapped_tools if t.name == tool.name), None
                        )

                        if target_tool:
                            logger.info(
                                "[MCP] 已获取新工具实例 {}，开始重试...", tool.name
                            )
                            # 5. 直接调用新工具（已包装错误处理，coroutine 已是 wrapped_coroutine）
                            # 为避免无限递归，直接调用底层原始 coroutine
                            inner = (
                                getattr(target_tool, "_original_coroutine", None)
                                or target_tool.coroutine
                            )
                            if inner:
                                return await inner(*args, **kwargs)
                        else:
                            logger.error(
                                "[MCP] 重试失败: 无法在新连接中找到工具 {}", tool.name
                            )
                    except Exception as retry_e:
                        logger.error("[MCP] 重连/重试过程失败: {}", retry_e)
                        # 重试失败，继续抛出原始错误或返回错误信息

                error_msg = f"工具 {tool_name} 调用失败: {type(e).__name__}: {str(e)}"
                logger.info("[工具错误处理] {}", error_msg)
                error_text = f"错误: {error_msg}\n请检查参数是否正确，或尝试其他方法。"
                return (error_text, None)

        tool.coroutine = wrapped_coroutine

    return tool


# 全局单例与锁
_mcp_client_instance = None
_client_lock = asyncio.Lock()


async def get_mcp_client():
    """
    获取全局唯一的稳定 MCP 客户端单例。
    使用 RobustMultiServerMCPClient 为每个服务器维护固定的 session，确保上下文连贯。
    """
    global _mcp_client_instance

    if _mcp_client_instance is None:
        async with _client_lock:
            if _mcp_client_instance is None:
                active_servers, _ = load_mcp_config()

                _mcp_client_instance = RobustMultiServerMCPClient(active_servers)

    return _mcp_client_instance


async def get_mcp_tools(add_prefix: bool = True) -> List[BaseTool]:
    """
    获取所有可用的 MCP 工具列表。
    根据 load_final_mcp_config 返回的 available_tools 过滤工具，
    只返回 is_load=true 的工具。

    Args:
        add_prefix: 是否为工具名称添加服务器前缀（避免与内置工具重名）

    Returns:
        MCP 工具列表（已包装错误处理）
    """
    try:
        from workflow.report_tools import load_final_mcp_config

        _, _, available_tools_map = load_final_mcp_config()

        client = await get_mcp_client()
        tools = await client.get_tools()
        logger.info("获取 MCP 工具成功，数量: {}", len(tools))

        # 构建可用的工具名称集合（带前缀）
        available_tool_names = set()
        for server_name, tool_names in available_tools_map.items():
            safe_server_name = server_name.replace("-", "_").replace(" ", "_")
            for tool_name in tool_names:
                available_tool_names.add(f"{safe_server_name}_{tool_name}")

        wrapped_tools = []
        filtered_count = 0
        for tool in tools:
            # 构建带前缀的工具名称
            server_name = None
            if tool.metadata:
                server_name = tool.metadata.get("server_name")
            if not server_name:
                server_name = "mcp"

            safe_server_name = server_name.replace("-", "_").replace(" ", "_")
            prefixed_tool_name = f"{safe_server_name}_{tool.name}"

            # 检查工具是否在可加载列表中
            if prefixed_tool_name not in available_tool_names:
                logger.info(
                    "[工具过滤] 跳过工具 (is_load=false): {}", prefixed_tool_name
                )
                filtered_count += 1
                continue

            # 如果启用前缀，添加服务器名称前缀避免重名
            if add_prefix:
                tool = _add_tool_prefix(tool)
            wrapped_tool = _wrap_tool_with_error_handling(tool)
            wrapped_tools.append(wrapped_tool)

        logger.info("已过滤 {} 个工具 (is_load=false)", filtered_count)
        logger.info("已包装 {} 个工具的错误处理", len(wrapped_tools))
        return wrapped_tools
    except Exception as e:
        logger.error("获取 MCP 工具失败: {}", e)
        return []


def get_mcp_tools_skills() -> str:
    """
    从 MCP 配置文件中读取已加载工具的 skills 字段。

    Returns:
        合并后的 skills 字符串，用于添加到系统提示词中
    """
    try:
        from workflow.report_tools import load_mcp_config

        _, mcp_skills = load_mcp_config()
        if mcp_skills:
            logger.info("获取 MCP 工具 skills 成功，长度: {}", len(mcp_skills))
            return mcp_skills
        return ""
    except Exception as e:
        logger.error("获取 MCP 工具 skills 失败: {}", e)
        return ""


async def reset_mcp_client():
    """
    重置 MCP 客户端单例，用于配置变更时重新加载。
    """
    global _mcp_client_instance

    async with _client_lock:
        if _mcp_client_instance is not None:
            # shutdown() 内部直接替换 stack 实例，不跨任务关闭，安全调用
            await _mcp_client_instance.shutdown()
            _mcp_client_instance = None
            logger.info("MCP 客户端已重置")
