import asyncio
import json
import requests

from .websocket_client import get_websocket_client
from .session import SessionManager
from workflow.config import WECHAT_WORK_ALLOWED_USERS, WECHAT_AGENT_BASE_URL
from workflow.content_security import ContentSecurityEngine

from loguru import logger

_session_manager = SessionManager()

# 内容安全检查引擎实例
_security_engine = ContentSecurityEngine()

AGENT_BASE_URL = WECHAT_AGENT_BASE_URL


async def handle_message(data: dict):
    """处理接收到的文本消息"""
    ws_client = get_websocket_client()
    if not ws_client:
        logger.error("[WeChatWork] WebSocket 客户端未初始化")
        return

    msg_type = data.get("msgtype")
    user_id = data.get("from", {}).get("userid", "")
    msg_id = data.get("msgid", "")
    req_id = data.get("req_id", "")

    content = ""
    if msg_type == "text" and "text" in data:
        content = data["text"].get("content", "")

    # 处理进入会话事件，5 秒内必须回复欢迎语
    if msg_type == "event":
        event_type = data.get("event", {}).get("eventtype", "")
        if event_type == "enter_chat":
            logger.info(f"[WeChatWork] 用户 {user_id} 进入会话，发送欢迎语")
            await ws_client.send_welcome_message(
                "你好！我是智能助手，有什么可以帮您的吗？", req_id
            )
        return

    if msg_type != "text" or not content:
        return

    logger.info(f"[WeChatWork] 收到用户消息: {user_id} - {content}")

    if WECHAT_WORK_ALLOWED_USERS and user_id not in WECHAT_WORK_ALLOWED_USERS:
        # 这里为了兼容，也可以选择检查 sys_admin_users 是否绑定了该 wechat_work_id
        # 为了不破坏现有逻辑，先保留环境变量白名单机制
        logger.info("[WeChatWork] 拦截非白名单用户: {}", user_id)
        await ws_client.send_message(
            user_id, "抱歉，您没有权限使用此服务。", msg_id, req_id
        )
        return

    asyncio.create_task(
        process_user_message(ws_client, user_id, content, msg_id, req_id)
    )


async def handle_streaming(data: dict):
    """处理流式响应"""
    ws_client = get_websocket_client()
    if not ws_client:
        return

    user_id = data.get("user_id", "")
    content = data.get("content", "")
    is_final = data.get("type") == "finish"
    req_id = data.get("req_id", "")
    stream_id = data.get("stream_id", "")

    await ws_client.send_streaming_message(
        user_id, content, is_final, req_id, stream_id
    )


async def handle_error(error: str):
    """处理错误"""
    logger.error(f"[WeChatWork] 错误: {error}")


async def handle_connected():
    """处理连接成功"""
    logger.info("[WeChatWork] 已连接到企业微信长连接服务")


async def handle_disconnected():
    """处理连接断开"""
    logger.info("[WeChatWork] 与企业微信长连接服务断开")


def _call_agent_api(
    user_id: str, content: str, thread_id: str, session_id: str, wechat_context: str
) -> str:
    """同步调用 serve.py /quotation 接口，返回最终回复内容"""
    payload = {
        "user_input": "【企业微信】" + content,
        "chat_history": [],
        "thread_id": thread_id,
        "sessionId": session_id,
        "mode": 0,
        "username": user_id,
        "wechat_context": wechat_context,
    }

    full_content = ""
    try:
        with requests.post(
            f"{AGENT_BASE_URL}/quotation", json=payload, stream=True, timeout=1200
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                try:
                    event = json.loads(decoded[6:])
                    if event.get("event_type") == "done":
                        full_content = event.get("content", "")
                    elif event.get("event_type") == "error":
                        full_content = event.get("content", "执行出错")
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.error(f"[WeChatWork] 调用 Agent 接口失败: {e}")
        raise

    return full_content


async def process_user_message(
    ws_client, user_id: str, content: str, msg_id: str, req_id: str
):
    """处理用户消息：调用 serve.py Agent 接口，将结果回传企业微信"""
    import uuid

    try:
        thread_id = _session_manager.get_thread_id(user_id)
        session_id = _session_manager.get_session_id(user_id)
        wechat_context = f"【企业微信】用户 {user_id} 发起任务"
        stream_id = str(uuid.uuid4())

        # 立即回复"正在处理"，避免用户等待无响应
        await ws_client.send_streaming_message(
            user_id, "正在思考中...", False, req_id, stream_id
        )

        # 在线程池中执行同步 HTTP 请求，避免阻塞事件循环
        full_content = await asyncio.to_thread(
            _call_agent_api, user_id, content, thread_id, session_id, wechat_context
        )

        if full_content:
            # 安全检查：对发送给客户的文本内容进行安全审查
            text_check = await _security_engine.check_text(full_content, "wechat_work")
            if not text_check.passed:
                logger.info(
                    "[安全拦截-企微] 文本回复被拦截: violations={}",
                    text_check.violations,
                )
                notify_msg = _security_engine.build_owner_notify_message(
                    text_check, context=f"企微用户「{user_id}」的文本回复"
                )
                if notify_msg:
                    await ws_client.send_message(user_id, notify_msg, msg_id, req_id)
                # 替换为安全提示语
                safe_msg = (
                    text_check.safe_content or "该回复经安全审查未通过，暂无法发送。"
                )
                await ws_client.send_streaming_message(
                    user_id, safe_msg, True, req_id, stream_id
                )
                return

            # 企微 stream 消息的 content 是累积全量文本（非增量），每次发送都包含之前所有内容
            # 先用增量方式逐步发送，最后一帧发送完整内容并设置 finish=True
            chunks = _split_content(full_content)
            accumulated = ""
            for i, chunk in enumerate(chunks):
                accumulated += chunk
                is_last = i == len(chunks) - 1
                await ws_client.send_streaming_message(
                    user_id, accumulated, is_last, req_id, stream_id
                )
                if not is_last:
                    await asyncio.sleep(0.5)
        else:
            await ws_client.send_streaming_message(
                user_id, "任务执行完毕，但未返回任何结果。", True, req_id, stream_id
            )

    except Exception as e:
        logger.error(f"[WeChatWork] 处理消息异常: {e}")
        import traceback

        traceback.print_exc()
        await ws_client.send_message(
            user_id, f"抱歉，任务执行失败: {str(e)}", msg_id, req_id
        )


def _split_content(content: str, chunk_size: int = 500) -> list:
    """将长文本按行分片，用于流式发送"""
    if len(content) <= chunk_size:
        return [content]

    chunks = []
    current_chunk = ""
    for line in content.split("\n"):
        if len(current_chunk) + len(line) + 1 <= chunk_size:
            current_chunk += line + "\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + "\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [content]
