from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
import asyncio
import os

from loguru import logger


def _format_mcp_connection_error(exc: BaseException, depth: int = 0) -> str:
    """展开 TaskGroup / ExceptionGroup 的内层异常，便于排查 stdio 子进程失败等原因。"""
    ind = "  " * depth
    lines = [f"{ind}{type(exc).__name__}: {exc}"]
    subs = getattr(exc, "exceptions", None)
    if subs:
        for sub in subs:
            lines.append(_format_mcp_connection_error(sub, depth + 1))
    if depth == 0 and exc.__cause__ is not None:
        lines.append("cause:")
        lines.append(_format_mcp_connection_error(exc.__cause__, 1))
    return "\n".join(lines)


class RobustMultiServerMCPClient:
    """
    健壮的多服务 MCP 客户端。

    核心设计：用一个后台常驻 asyncio Task 持有所有 session 的生命周期。
    所有 session 的 anyio cancel scope 都在同一个 Task 中创建和销毁，
    彻底避免 'Attempted to exit cancel scope in a different task' 错误。

    工具调用通过 asyncio.Future 与后台任务通信：
    - 调用方将 (session, args, kwargs, future) 放入队列
    - 后台任务在自己的上下文中执行调用，将结果写回 future
    """

    def __init__(self, servers_config: dict):
        self.servers_config = servers_config
        self._tools_cache = None
        self._lock = asyncio.Lock()
        self._connect_timeout_s = max(
            1.0, float(os.getenv("MCP_SERVER_CONNECT_TIMEOUT_SECONDS", "12"))
        )
        self._tools_timeout_s = max(
            1.0, float(os.getenv("MCP_SERVER_TOOLS_TIMEOUT_SECONDS", "10"))
        )
        # 并发连接数上限，避免同时连接过多服务导致资源竞争超时
        self._max_concurrent = max(
            1, int(os.getenv("MCP_SERVER_CONNECT_CONCURRENCY", "4"))
        )
        # 后台任务句柄，用于取消
        self._bg_task: asyncio.Task | None = None
        # 后台任务就绪信号
        self._ready_event = asyncio.Event()
        # 后台任务内部持有的 sessions（仅后台任务读写）
        self._sessions: dict = {}
        # 停止信号
        self._stop_event = asyncio.Event()
        # 连接结果摘要（成功/失败的服务列表）
        self._connect_summary: dict = {"success": [], "failed": []}

    async def _background_session_holder(self):
        """
        后台常驻任务：在同一个 Task 中建立并持有所有 MCP session。
        session 的 anyio cancel scope 始终在本任务内创建和销毁。
        使用有界并发（Semaphore）避免同时连接过多服务导致资源竞争超时。
        """
        client = MultiServerMCPClient(self.servers_config)

        # 有界并发：限制同时连接的服务数量，避免网络/进程资源竞争
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def _connect_one(server_name: str):
            """连接单个 MCP 服务，通过信号量控制并发数"""
            async with semaphore:
                try:
                    ctx = client.session(server_name)
                    session = await asyncio.wait_for(
                        ctx.__aenter__(), timeout=self._connect_timeout_s
                    )
                    logger.info("[MCP] 服务 {} 握手成功，已标记归属。", server_name)
                    return (server_name, session, ctx, None)
                except asyncio.TimeoutError:
                    logger.error(
                        "[MCP] 连接服务 {} 超时（{}s），已跳过该服务。",
                        server_name,
                        self._connect_timeout_s,
                    )
                    return (server_name, None, None, "timeout")
                except Exception as e:
                    logger.error(
                        "[MCP] 连接服务 {} 失败:\n{}",
                        server_name,
                        _format_mcp_connection_error(e),
                    )
                    return (server_name, None, None, str(e))

        logger.info(
            "[MCP] 开始并行握手 {} 个服务（并发数: {}）",
            len(self.servers_config),
            self._max_concurrent,
        )
        # 并行发起所有服务的握手，通过信号量控制并发数
        results = await asyncio.gather(
            *[_connect_one(name) for name in self.servers_config.keys()]
        )

        # 汇总成功和失败的服务
        sessions_with_ctx = {}
        self._connect_summary = {"success": [], "failed": []}
        for server_name, session, ctx, error in results:
            if error is None:
                sessions_with_ctx[server_name] = (session, ctx)
                self._connect_summary["success"].append(server_name)
            else:
                self._connect_summary["failed"].append(
                    {"server_name": server_name, "error": error}
                )

        self._sessions = {k: v[0] for k, v in sessions_with_ctx.items()}

        # 通知等待方：session 已就绪
        self._ready_event.set()

        # 持续等待停止信号，保持 session 存活
        await self._stop_event.wait()

        # 收到停止信号后，在本任务中关闭所有 session
        for server_name, (session, ctx) in sessions_with_ctx.items():
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._sessions.clear()
        logger.info("[MCP] 后台 session 持有任务已退出")

    async def _ensure_bg_task(self):
        """确保后台任务正在运行且已就绪"""
        if self._bg_task is None or self._bg_task.done():
            self._ready_event.clear()
            self._stop_event.clear()
            self._bg_task = asyncio.get_event_loop().create_task(
                self._background_session_holder()
            )
        await self._ready_event.wait()

    async def get_tools(self):
        # 第一次无锁快速检查
        if self._tools_cache is not None:
            return self._tools_cache

        async with self._lock:
            # 加锁后二次检查
            if self._tools_cache is not None:
                return self._tools_cache

            # 启动后台任务并等待所有 session 就绪
            await self._ensure_bg_task()

            # 并行获取所有服务的工具列表，使用信号量控制并发
            tools_semaphore = asyncio.Semaphore(self._max_concurrent)

            async def _load_one(server_name: str, session):
                """获取单个服务的工具列表"""
                async with tools_semaphore:
                    try:
                        srv_tools = await asyncio.wait_for(
                            load_mcp_tools(session), timeout=self._tools_timeout_s
                        )
                        for tool in srv_tools:
                            if tool.metadata is None:
                                tool.metadata = {}
                            tool.metadata["server_name"] = server_name
                        return (server_name, srv_tools, None)
                    except asyncio.TimeoutError:
                        logger.error(
                            "[MCP] 获取服务 {} 工具超时（{}s），已跳过该服务工具。",
                            server_name,
                            self._tools_timeout_s,
                        )
                        return (server_name, [], "timeout")
                    except Exception as e:
                        logger.error("[MCP] 获取服务 {} 工具失败: {}", server_name, e)
                        return (server_name, [], str(e))

            results = await asyncio.gather(
                *[_load_one(name, session) for name, session in self._sessions.items()]
            )

            all_tools = []
            for server_name, tools, error in results:
                if error is None:
                    all_tools.extend(tools)
                else:
                    logger.error("[MCP] 服务 {} 工具获取失败: {}", server_name, error)

            self._tools_cache = all_tools
            return all_tools

    def is_connected(self) -> bool:
        """检查后台任务是否存活且 session 已就绪"""
        return (
            self._bg_task is not None
            and not self._bg_task.done()
            and self._ready_event.is_set()
            and len(self._sessions) > 0
        )

    def get_connect_summary(self) -> dict:
        """获取连接结果摘要，包含成功和失败的服务列表"""
        return dict(self._connect_summary)

    async def shutdown(self):
        """
        停止后台任务，释放所有 session。
        使用强制取消策略避免因 MCP session 异步生成器损坏导致的 __aexit__ 卡死。
        """
        self._tools_cache = None

        if self._bg_task is not None and not self._bg_task.done():
            self._stop_event.set()
            # 等待后台任务唤醒（极短时间），然后直接取消，不等待 session 优雅清理
            # 因为 MCP session 的 async generators 在反复重连后可能已损坏，
            # __aexit__ 会抛出 RuntimeError: generator didn't stop after athrow()
            try:
                await asyncio.wait_for(asyncio.shield(self._bg_task), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._bg_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._bg_task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._bg_task = None

        self._sessions.clear()
        self._ready_event.clear()
        self._stop_event.clear()
        logger.info("[MCP] 连接池已完全释放")
