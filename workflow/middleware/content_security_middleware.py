from loguru import logger
import os

try:
    from langchain.agents.middleware import AgentMiddleware
except ImportError:
    from workflow.mcp_middleware import AgentMiddleware

from workflow.content_security import ContentSecurityEngine, ContentSecurityBlockedError


class ContentSecurityMiddleware(AgentMiddleware):
    """面向客户消息的发送安全拦截中间件"""

    OUTBOUND_TOOLS = frozenset(
        {
            "MCPFilesystem_send_wechat_message",
            "MCPFilesystem_send_wechat_file",
        }
    )

    def __init__(self):
        self._engine = ContentSecurityEngine()

    async def awrap_tool_call(self, request, handler):
        """拦截面向客户的发送类工具调用，做安全检查"""
        tool_call = request.tool_call if hasattr(request, "tool_call") else {}
        tool_name = ""
        tool_args = {}

        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name", "") or tool_call.get("function", {}).get(
                "name", ""
            )
            tool_args = tool_call.get("args", {}) or tool_call.get("function", {}).get(
                "args", {}
            )
        elif hasattr(tool_call, "name"):
            tool_name = tool_call.name
            tool_args = getattr(tool_call, "args", {}) or {}

        logger.debug(
            "[安全中间件] 收到工具调用: tool={}, args={}", tool_name, tool_args
        )

        # 非发送类工具直接放行
        if tool_name not in self.OUTBOUND_TOOLS:
            logger.debug("[安全中间件] 非发送类工具，直接放行: {}", tool_name)
            return await handler(request)

        logger.info("[安全中间件] 发送类工具，进入安全检查: tool={}", tool_name)

        # 通过 tool_channel_mapping 配置确定渠道
        config = self._engine.load_rules()
        channel = config.get("tool_channel_mapping", {}).get(tool_name, "unknown")
        logger.debug("[安全中间件] 渠道映射: tool={} → channel={}", tool_name, channel)

        # 渠道不在 channels 列表中 → 直接放行（非面向客户的发送）
        if channel not in config.get("channels", []):
            logger.info("[安全中间件] 渠道 {} 不在检查列表中，直接放行", channel)
            return await handler(request)

        # 提取发送内容和文件路径
        content = ""
        file_paths = []

        if tool_name == "MCPFilesystem_send_wechat_message":
            content = tool_args.get("message", "") or tool_args.get("content", "")
            logger.debug("[安全中间件] 提取文本内容，长度={}", len(content))
        elif tool_name == "MCPFilesystem_send_wechat_file":
            file_path_arg = tool_args.get("file_path", "")
            if file_path_arg:
                file_paths = [file_path_arg]
            logger.debug("[安全中间件] 提取文件路径: {}", file_paths)

        logger.info(
            "[安全中间件] 开始安全检查: channel={}, content_len={}, files={}",
            channel,
            len(content),
            file_paths,
        )

        # 调用安全引擎检查
        result = await self._engine.check(content, file_paths, channel)

        logger.info(
            "[安全中间件] 安全检查结果: passed={}, violations={}",
            result.passed,
            result.violations,
        )

        if result.passed:
            logger.info("[安全中间件] 检查通过，放行工具调用: tool={}", tool_name)
            return await handler(request)

        # 拦截：抛出异常中断执行流
        violation_text = "；".join(result.violations)

        notify_msg = self._engine.build_owner_notify_message(
            result, context=f"WorkMate 工具调用「{tool_name}」"
        )
        notify_hint = (
            f"\n\n请通过微信/企微通知工作伙伴：{notify_msg}" if notify_msg else ""
        )

        block_message = (
            f"【安全拦截】该内容违反保密要求，已拦截，未发送给客户。"
            f"违规项：{violation_text}。"
            f"请修改内容后重新发送，确保不违反公司、部门及职能范围的保密要求。"
            f"{notify_hint}"
        )

        logger.info(
            "[安全中间件] 拦截工具调用: tool={}, channel={}, violations={}",
            tool_name,
            channel,
            result.violations,
        )

        # 异步写入拦截日志到数据库，供管理端安全合规页面查询
        try:
            from admin_api.services.security_log_service import insert_intercept_log

            log_username = os.getenv(
                "WORKMATE_DESKTOP_ACTIVE_USERNAME", ""
            ) or os.getenv("AGENT_USERNAME", "")
            insert_intercept_log(
                username=log_username,
                channel=channel,
                intercept_type=result.intercept_type or "keyword",
                tool_name=tool_name,
                violations=result.violations or [],
                raw_content=result.raw_content or "",
                block_message=block_message,
                mate_name=os.getenv("MATE_NAME", ""),
            )
        except Exception as log_err:
            logger.error("[安全中间件] 写入安全拦截日志失败: {}", log_err)

        raise ContentSecurityBlockedError(block_message, result.violations)
