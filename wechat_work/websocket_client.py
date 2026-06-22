import asyncio
import json
import time
from typing import Optional, Callable

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from workflow.config import WECHAT_WORK_BOT_ID, WECHAT_WORK_SECRET

from loguru import logger


class WeChatWorkWebSocketClient:
    """企业微信长连接 WebSocket 客户端"""

    # 企业微信 WebSocket 网关地址
    WSS_URL = "wss://openws.work.weixin.qq.com"

    def __init__(
        self,
        bot_id: str,
        secret: str,
        on_message: Optional[Callable] = None,
        on_streaming: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_connected: Optional[Callable] = None,
        on_disconnected: Optional[Callable] = None,
    ):
        self.bot_id = bot_id
        self.secret = secret
        self.on_message = on_message
        self.on_streaming = on_streaming
        self.on_error = on_error
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected

        self.websocket = None
        self.is_running = False
        self.should_reconnect = True
        self.reconnect_delay = 5  # 重连延迟（秒）
        self.max_reconnect_delay = 60  # 最大重连延迟
        self.heartbeat_interval = 25  # 心跳间隔（秒），建议30秒内
        self.last_heartbeat = 0

        self._receive_task = None
        self._heartbeat_task = None
        self._reconnect_task = None
        self._lock = asyncio.Lock()

    async def start(self):
        """启动 WebSocket 客户端"""
        self.should_reconnect = True
        await self._connect()

    async def stop(self):
        """停止 WebSocket 客户端"""
        self.should_reconnect = False
        await self._disconnect()

    async def _connect(self):
        """建立 WebSocket 连接"""
        import uuid

        try:
            # 构建 WebSocket URL
            url = self.WSS_URL

            logger.info(f"[WeChatWork] 正在连接到企业微信 WebSocket 网关: {url}")

            self.websocket = await websockets.connect(
                url,
                ping_interval=None,  # 禁用自动 ping，由我们自己控制
                max_size=None,
                max_queue=32,
            )

            logger.info("[WeChatWork] WebSocket 握手成功，发送订阅请求...")

            # 发送订阅请求 aibot_subscribe
            subscribe_req_id = str(uuid.uuid4())
            subscribe_msg = {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": subscribe_req_id},
                "body": {"bot_id": self.bot_id, "secret": self.secret},
            }

            await self.websocket.send(json.dumps(subscribe_msg))

            # 等待订阅响应
            response = await self.websocket.recv()
            response_data = json.loads(response)

            if response_data.get("errcode") == 0:
                logger.info("[WeChatWork] 订阅成功，连接建立完成")
            else:
                logger.error(f"[WeChatWork] 订阅失败: {response_data.get('errmsg')}")
                await self._schedule_reconnect()
                return

            self.is_running = True
            logger.info("[WeChatWork] 连接建立完成，开始接收消息")

            # 触发连接成功回调
            if self.on_connected:
                await self.on_connected()

            # 启动接收消息任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            # 启动心跳任务
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except WebSocketException as e:
            logger.error(f"[WeChatWork] WebSocket 连接失败: {e}")
            await self._schedule_reconnect()
        except Exception as e:
            logger.error(f"[WeChatWork] 连接异常: {e}")
            await self._schedule_reconnect()

    async def _disconnect(self):
        """断开 WebSocket 连接"""
        self.is_running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        logger.info("[WeChatWork] WebSocket 连接已断开")

        if self.on_disconnected:
            self.on_disconnected()

    async def _receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self.websocket:
                await self._handle_message(message)
        except asyncio.CancelledError:
            pass
        except ConnectionClosed as e:
            logger.info(f"[WeChatWork] WebSocket 连接关闭: {e}")
            await self._handle_disconnect()
        except Exception as e:
            logger.error(f"[WeChatWork] 接收消息异常: {e}")
            if self.on_error:
                self.on_error(str(e))
            await self._handle_disconnect()

    async def _handle_message(self, message: str):
        """处理接收到的消息"""
        try:
            data = json.loads(message)

            # 获取命令类型
            cmd = data.get("cmd", "")

            # 忽略心跳响应
            if cmd == "ping":
                return

            logger.info(f"[WeChatWork] 收到消息: {cmd} - {data}")

            # 处理消息回调 aibot_msg_callback
            if cmd == "aibot_msg_callback":
                body = data.get("body", {})
                msg_type = body.get("msgtype", "text")

                # 将 req_id 注入到 body 中，方便后续处理
                req_id = data.get("headers", {}).get("req_id", "")
                body["req_id"] = req_id

                if self.on_message:
                    await self.on_message(body)
                return

            # 处理事件回调 aibot_event_callback
            if cmd == "aibot_event_callback":
                body = data.get("body", {})
                event_type = body.get("event", {}).get("eventtype", "")
                req_id = data.get("headers", {}).get("req_id", "")
                body["req_id"] = req_id

                logger.info(f"[WeChatWork] 收到事件: {event_type}")

                # 被新连接踢掉时，主动触发断线重连
                if event_type == "disconnected_event":
                    logger.info(
                        "[WeChatWork] 收到 disconnected_event，当前连接被踢掉，触发重连"
                    )
                    asyncio.create_task(self._handle_disconnect())
                    return

                # 其他事件（enter_chat、template_card_event 等）交给上层处理
                if self.on_message:
                    await self.on_message(body)
                return

        except json.JSONDecodeError:
            logger.info(f"[WeChatWork] 收到非 JSON 消息: {message}")
        except Exception as e:
            logger.error(f"[WeChatWork] 处理消息异常: {e}")
            if self.on_error:
                self.on_error(str(e))

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.is_running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.is_running and self.websocket:
                    await self._send_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WeChatWork] 心跳异常: {e}")

    async def _send_ping(self):
        """发送心跳"""
        try:
            if self.websocket and self.is_running:
                ping_data = json.dumps({"type": "ping"})
                await self.websocket.send(ping_data)
                self.last_heartbeat = time.time()
                logger.debug("[WeChatWork] 已发送心跳")
        except Exception as e:
            logger.error(f"[WeChatWork] 发送心跳失败: {e}")
            await self._handle_disconnect()

    async def _handle_disconnect(self):
        """处理连接断开"""
        if not self.should_reconnect:
            return

        await self._disconnect()
        await self._schedule_reconnect()

    async def _schedule_reconnect(self):
        """安排重连"""
        if not self.should_reconnect:
            return

        logger.info(f"[WeChatWork] 将在 {self.reconnect_delay} 秒后尝试重连...")

        # 尝试重连
        await asyncio.sleep(self.reconnect_delay)

        if self.should_reconnect:
            await self._connect()

            # 如果连接成功，重置延迟；如果失败，增加延迟
            if self.is_running:
                self.reconnect_delay = 5
            else:
                self.reconnect_delay = min(
                    self.reconnect_delay * 2, self.max_reconnect_delay
                )

    async def send_welcome_message(self, content: str, req_id: str):
        """回复进入会话欢迎语（aibot_respond_welcome_msg）"""
        if not self.websocket or not self.is_running:
            logger.error("[WeChatWork] WebSocket 未连接，无法发送欢迎语")
            return False
        try:
            message = {
                "cmd": "aibot_respond_welcome_msg",
                "headers": {"req_id": req_id},
                "body": {"msgtype": "text", "text": {"content": content}},
            }
            await self.websocket.send(json.dumps(message, ensure_ascii=False))
            logger.info("[WeChatWork] 欢迎语已发送")
            return True
        except Exception as e:
            logger.error(f"[WeChatWork] 发送欢迎语失败: {e}")
            return False

    async def send_message(
        self, user_id: str, content: str, msg_id: str = None, req_id: str = None
    ):
        """发送消息给用户"""
        if not self.websocket or not self.is_running:
            logger.error("[WeChatWork] WebSocket 未连接，无法发送消息")
            return False

        try:
            # 构建消息体 (适配企业微信长连接格式)
            message = {
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id or "default_req_id"},
                "body": {"msgtype": "text", "text": {"content": content}},
            }

            await self.websocket.send(json.dumps(message, ensure_ascii=False))
            logger.info(f"[WeChatWork] 消息已发送: {content[:50]}...")
            return True

        except Exception as e:
            logger.error(f"[WeChatWork] 发送消息失败: {e}")
            return False

    async def send_streaming_message(
        self,
        user_id: str,
        content: str,
        is_final: bool = False,
        req_id: str = None,
        stream_id: str = None,
    ):
        """发送流式消息（用于 AI 对话）"""
        if not self.websocket or not self.is_running:
            logger.error("[WeChatWork] WebSocket 未连接，无法发送消息")
            return False

        try:
            import uuid

            stream_id = stream_id or str(uuid.uuid4())

            message = {
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id or "default_req_id"},
                "body": {
                    "msgtype": "stream",
                    "stream": {"id": stream_id, "finish": is_final, "content": content},
                },
            }

            await self.websocket.send(json.dumps(message, ensure_ascii=False))

            if is_final:
                logger.info(f"[WeChatWork] 流式消息发送完成")

            return True

        except Exception as e:
            logger.error(f"[WeChatWork] 发送流式消息失败: {e}")
            return False


# 全局 WebSocket 客户端实例
_ws_client: Optional[WeChatWorkWebSocketClient] = None


def get_websocket_client() -> Optional[WeChatWorkWebSocketClient]:
    """获取全局 WebSocket 客户端实例"""
    return _ws_client


async def start_websocket_client(
    on_message: Optional[Callable] = None,
    on_streaming: Optional[Callable] = None,
    on_error: Optional[Callable] = None,
    on_connected: Optional[Callable] = None,
    on_disconnected: Optional[Callable] = None,
) -> WeChatWorkWebSocketClient:
    """启动 WebSocket 客户端"""
    global _ws_client

    _ws_client = WeChatWorkWebSocketClient(
        bot_id=WECHAT_WORK_BOT_ID,
        secret=WECHAT_WORK_SECRET,
        on_message=on_message,
        on_streaming=on_streaming,
        on_error=on_error,
        on_connected=on_connected,
        on_disconnected=on_disconnected,
    )

    await _ws_client.start()
    return _ws_client


async def stop_websocket_client():
    """停止 WebSocket 客户端"""
    global _ws_client

    if _ws_client:
        await _ws_client.stop()
        _ws_client = None
