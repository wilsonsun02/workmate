from datetime import datetime

from loguru import logger

try:
    from langgraph.errors import GraphBubbleUp as _GraphBubbleUp
except ImportError:
    _GraphBubbleUp = None

# 尝试导入 LangChain 中间件模块
try:
    from langchain.agents.middleware import AgentMiddleware, ModelRequest

    # ToolCallRequest might be in types submodule depending on version
    try:
        from langchain.agents.middleware import ToolCallRequest
    except ImportError:
        from langchain.agents.middleware.types import ToolCallRequest
except ImportError:
    # 如果环境没有该模块，我们定义一个兼容的基类（Polyfill）
    class AgentMiddleware:
        def wrap_model_call(self, request, handler):
            return handler(request)

        def wrap_tool_call(self, request, handler):
            return handler(request)

        async def awrap_tool_call(self, request, handler):
            return await handler(request)

    class ModelRequest:
        def __init__(self, model, messages, tools, config):
            self.model = model
            self.messages = messages
            self.tools = tools
            self.config = config
            self.state = None  # 假设有 state

        def override(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ToolCallRequest:
        def __init__(self, tool_call, config):
            self.tool_call = tool_call
            self.config = config


from workflow.report_tools import load_final_mcp_config
from workflow.permission_engine import PermissionEngine


class MCPMiddleware(AgentMiddleware):
    """
    MCP 核心中间件，整合了动态工具加载和工具执行日志记录功能。
    """

    # 框架内置的、在 Windows 上不兼容的工具名称黑名单
    # 这些工具由 FilesystemMiddleware 和 TodoListMiddleware 注入，需要在此处拦截
    BLOCKED_BUILTIN_TOOLS = frozenset(
        {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"}
    )

    def _filter_tools(self, request: ModelRequest):
        """
        核心过滤逻辑：
        1. 过滤掉黑名单中的内置工具（Windows 不兼容）
        2. 对 MCP 工具按照当前配置进行白名单过滤
        3. 其他非 MCP 内置工具（如 task）直接保留
        返回过滤后的新 request 对象（request.override 返回新对象，不修改原对象）
        """
        needed_servers_map, _, available_tools_map = load_final_mcp_config()
        needed_server_names = set(needed_servers_map.keys())

        # 构建 MCP 工具白名单：{safe_server_name}_{tool_name}
        available_tool_names = set()
        for server_name, tool_names in available_tools_map.items():
            safe = server_name.replace("-", "_").replace(" ", "_")
            for t in tool_names:
                available_tool_names.add(f"{safe}_{t}")

        original_tools = request.tools or []
        logger.info("[MCP中间件] 原始工具数量: {}", len(original_tools))

        filtered_tools = []
        for tool in original_tools:
            name = tool.name if hasattr(tool, "name") else tool.get("name")

            # 第一优先级：黑名单内置工具直接丢弃
            if name in self.BLOCKED_BUILTIN_TOOLS:
                continue

            # 尝试识别该工具属于哪个 MCP server
            tool_server_name = None
            if hasattr(tool, "metadata") and tool.metadata:
                tool_server_name = tool.metadata.get("server_name")
            if not tool_server_name:
                for server_name in needed_server_names:
                    safe = server_name.replace("-", "_").replace(" ", "_")
                    if name.startswith(f"{safe}_"):
                        tool_server_name = server_name
                        break

            if tool_server_name:
                # MCP 工具：按白名单过滤
                if tool_server_name not in needed_server_names:
                    continue
                if name in available_tool_names:
                    filtered_tools.append(tool)
                else:
                    server_tools = available_tools_map.get(tool_server_name, [])
                    safe = tool_server_name.replace("-", "_").replace(" ", "_")
                    original_name = (
                        name[len(f"{safe}_") :] if name.startswith(f"{safe}_") else name
                    )
                    if original_name in server_tools:
                        filtered_tools.append(tool)
            else:
                # 非 MCP、非黑名单的内置工具（如 task）：直接保留
                filtered_tools.append(tool)

        filtered_out = [t for t in original_tools if t not in filtered_tools]
        logger.info(
            "[MCP中间件] 过滤后工具数量: {} (过滤掉 {})",
            len(filtered_tools),
            len(filtered_out),
        )

        wechat_tools = [
            t.name if hasattr(t, "name") else t.get("name")
            for t in filtered_tools
            if "wechat" in (t.name if hasattr(t, "name") else t.get("name", "")).lower()
        ]
        if wechat_tools:
            logger.info("[MCP中间件] 微信相关工具已保留: {}", wechat_tools)
        else:
            logger.info("[MCP中间件] 警告：微信相关工具全部被过滤！")

        return request.override(tools=filtered_tools)

    async def awrap_model_call(self, request: ModelRequest, handler):
        """在 LLM 调用前拦截，过滤掉黑名单内置工具和不在配置中的 MCP 工具。"""
        logger.info("\n{}", "=" * 60)
        logger.info("[MCP中间件] awrap_model_call 开始执行")
        request = self._filter_tools(request)
        logger.info("[MCP中间件] awrap_model_call 执行完成")
        logger.info("{}\n", "=" * 60)
        return await handler(request)

    def wrap_model_call(self, request: ModelRequest, handler):
        """同步版本：在 LLM 调用前拦截，过滤掉黑名单内置工具和不在配置中的 MCP 工具。"""
        request = self._filter_tools(request)
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        """
        拦截工具调用，记录日志，并阻止创建 general-purpose 子代理。
        """
        config = getattr(request, "config", {}) or {}
        if (
            not config
            and hasattr(request, "runtime")
            and hasattr(request.runtime, "config")
        ):
            config = request.runtime.config

        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        session_id = configurable.get("session_id", "unknown")
        username = configurable.get("username", "unknown")

        if thread_id == "unknown" and hasattr(request, "state"):
            state = request.state
            if isinstance(state, dict):
                thread_id = state.get("thread_id", thread_id)
                session_id = state.get("session_id", session_id)

        tool_call = request.tool_call
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "unknown")

        from workflow.report_tools import block_reason_for_skill_filesystem_path

        u_for_skill = (
            str(username).strip()
            if username and str(username).strip() != "unknown"
            else None
        )
        skill_fs_block = block_reason_for_skill_filesystem_path(u_for_skill, tool_args)
        if skill_fs_block:
            from langchain_core.messages import ToolMessage

            logger.info(
                "[MCP中间件] 技能路径拦截: user={}, tool={}, detail={}",
                username,
                tool_name,
                skill_fs_block,
            )
            return ToolMessage(
                content=f"【系统拦截】{skill_fs_block}",
                tool_call_id=tool_call_id,
            )

        # 1. 细粒度权限硬拦截 (防越权)
        if username != "unknown":
            mcp_perms = PermissionEngine.get_user_mcp_permissions(username)
            # 为了匹配权限配置，我们需要推断 server_name
            # 这里简单处理，如果 tool_name 不在权限配置的 allow 列表中，或者是全局禁用的，我们根据实际情况决定
            # 因为我们在 awrap_model_call 中已经做了一层过滤，这里主要是校验 rules（如 allowed_dirs）

            # 寻找匹配的权限规则
            matched_rules = None
            action = "allow"  # 默认假设前面已经过滤过

            for perm_key, perm_config in mcp_perms.items():
                if perm_key.endswith(f":{tool_name}") or perm_key.endswith(":*"):
                    action = perm_config.get("action", "allow")
                    matched_rules = perm_config.get("rules", {})
                    if perm_key.endswith(f":{tool_name}"):
                        break  # 精确匹配优先

            if action == "deny":
                from langchain_core.messages import ToolMessage

                logger.info(
                    "[MCP中间件] 权限拦截：用户 {} 被明确拒绝使用工具 {}",
                    username,
                    tool_name,
                )
                return ToolMessage(
                    content=f"【系统拦截】你没有权限使用工具 [{tool_name}]，请向管理员申请权限。",
                    tool_call_id=tool_call_id,
                )

            # 校验目录限制 (例如 rules: {"allowed_dirs": ["/work"]})
            if matched_rules and "allowed_dirs" in matched_rules:
                allowed_dirs = matched_rules["allowed_dirs"]
                # 提取工具调用中的路径参数
                target_path = None
                for path_key in [
                    "file_path",
                    "path",
                    "directory",
                    "dir_path",
                    "folder_path",
                ]:
                    if path_key in tool_args:
                        target_path = str(tool_args[path_key])
                        break

                if target_path:
                    # 检查目标路径是否在允许的目录前缀内
                    is_allowed = False
                    for allowed_dir in allowed_dirs:
                        if target_path.startswith(allowed_dir):
                            is_allowed = True
                            break

                    if not is_allowed:
                        from langchain_core.messages import ToolMessage

                        error_msg = f"【系统安全拦截】由于安全策略，你只能访问以下目录: {', '.join(allowed_dirs)}。你尝试访问的路径 ({target_path}) 越权。"
                        logger.info(
                            "[MCP中间件] 目录越权拦截: 用户={}, 工具={}, 路径={}",
                            username,
                            tool_name,
                            target_path,
                        )
                        return ToolMessage(content=error_msg, tool_call_id=tool_call_id)

        # 拦截 task 工具：禁止创建 general-purpose 子代理
        # 框架 task 工具的参数名为 subagent_type（不是 name）
        # if tool_name == 'task':
        #     task_args = tool_call.get('args', {})
        #     subagent_name = task_args.get('subagent_type', '')
        #     if subagent_name == 'general-purpose':
        #         tool_call_id = tool_call.get('id', 'unknown')
        #         error_msg = (
        #             "【系统拦截】禁止创建 general-purpose 子代理。"
        #             "请根据任务类型选择正确的专用子代理：\n"
        #             "- wechat-agent：微信消息/文件发送\n"
        #             "- document-agent：文档读取/解析\n"
        #             "- data-search-agent：搜索/查询/报告生成\n"
        #             "- browser-automation-agent：网页抓取/浏览器自动化\n"
        #             "- ppt-agent：PPT制作\n"
        #             "- media-agent：图片/视频/音频生成\n"
        #             "- enterprise-info-agent：企业信息查询\n"
        #             "请重新调用 task 工具并指定正确的子代理名称。"
        #         )
        #         optional: log blocked general-purpose subagent request
        #         from langchain_core.messages import ToolMessage
        #         return ToolMessage(content=error_msg, tool_call_id=tool_call_id)

        # 记录工具开始
        logger.info("[MCP中间件] 工具调用开始: {}", tool_name)

        start_time = datetime.now()

        try:
            result = await handler(request)

            # 2. 记录工具结束
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(
                "[MCP中间件] 工具调用结束: {} 耗时 {:.2f}s", tool_name, duration
            )

            return result
        except Exception as e:
            # GraphBubbleUp 是 LangGraph interrupt() 触发的特殊异常，必须向上传播
            # 不能捕获，否则 HITL 中断机制会失效
            if _GraphBubbleUp is not None and isinstance(e, _GraphBubbleUp):
                raise

            # ContentSecurityBlockedError 是内容安全拦截异常，必须向上传播
            # 不能捕获，否则拦截信号会被吞掉，LLM 会误判为工具执行失败并生成误导性回复
            from workflow.content_security import ContentSecurityBlockedError

            if isinstance(e, ContentSecurityBlockedError):
                raise

            # 3. 记录异常
            logger.error("[MCP中间件] 工具调用异常: {}, 错误: {}", tool_name, str(e))

            error_message = f"工具 [{tool_name}] 执行失败: {str(e)}"
            from langchain_core.messages import ToolMessage

            tool_call_id = tool_call.get("id") if tool_call else "unknown"
            return ToolMessage(content=error_message, tool_call_id=tool_call_id)
