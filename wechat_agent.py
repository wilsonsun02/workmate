import os
import sys
import json
import requests
import asyncio
from datetime import datetime, timedelta
import mysql.connector

# Database config from config.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from workflow.config import (
    REPORT_DB_HOST,
    REPORT_DB_DATABASE,
    REPORT_DB_USER,
    REPORT_DB_PASS,
    WECHAT_CONTACTS,
    OWNER_NAME,
    CHECK_INTERVAL,
    WECHAT_AGENT_BASE_URL,
    WECHAT_AI_REPLY_PREFIX,
)
from workflow.robust_mcp_client import RobustMultiServerMCPClient
from workflow.report_tools import normalize_mcp_server_config
from workflow.content_security import ContentSecurityEngine

from loguru import logger

# 内容安全检查引擎实例
_security_engine = ContentSecurityEngine()

BASE_URL = WECHAT_AGENT_BASE_URL

_LOCAL_MCP_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config", "mcp_servers.json"
)


def _load_local_mcp_config():
    """从本地 config/mcp_servers.json 读取 MCP 配置"""
    if not os.path.exists(_LOCAL_MCP_CONFIG_PATH):
        return {}
    with open(_LOCAL_MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
        servers_list = json.load(f)
    return {
        item["server_name"]: normalize_mcp_server_config(item["server_config"])
        for item in servers_list
        if item.get("is_load")
    }


_wechat_mcp_client = None


async def get_wechat_mcp_client():
    global _wechat_mcp_client
    if _wechat_mcp_client is None:
        active_servers = _load_local_mcp_config()
        if "MCPFilesystem" not in active_servers:
            logger.error("Error: MCPFilesystem server not found in config")
            return None
        _wechat_mcp_client = RobustMultiServerMCPClient(
            {"MCPFilesystem": active_servers["MCPFilesystem"]}
        )
    return _wechat_mcp_client


def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=REPORT_DB_HOST,
            user=REPORT_DB_USER,
            password=REPORT_DB_PASS,
            database=REPORT_DB_DATABASE,
        )
        return connection
    except Exception as e:
        logger.error("Error connecting to MySQL: {}", e)
        return None


def is_agent_busy():
    """检查 Agent 当前是否有任务正在执行（微信触发或非微信触发均计入）。

    判断逻辑：在过去30分钟内，找出最近一次 agent_start 之后
    还没有对应 agent_end / error 的 thread，即认为该 thread 仍在运行。
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor(dictionary=True)
        # 取每个 thread 最近一条 agent_start 的时间，以及该时间之后是否有结束事件
        query = """
            SELECT t.thread_id
            FROM (
                SELECT thread_id, MAX(created_time) AS last_start
                FROM agent_execution_logs
                WHERE event_type = 'agent_start'
                  AND created_time > %s
                GROUP BY thread_id
            ) t
            LEFT JOIN agent_execution_logs e
                ON e.thread_id = t.thread_id
               AND e.event_type IN ('agent_end', 'error')
               AND e.created_time >= t.last_start
            WHERE e.id IS NULL
        """
        thirty_mins_ago = datetime.now() - timedelta(minutes=30)
        cursor.execute(query, (thirty_mins_ago,))
        active_threads = cursor.fetchall()

        if active_threads:
            logger.info(
                f"[{datetime.now().strftime('%H:%M:%S')}] Agent is busy with threads: {[t['thread_id'] for t in active_threads]}"
            )
            return True
        return False
    except Exception as e:
        logger.error("Error checking agent status: {}", e)
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def _extract_tool_text(raw) -> str:
    """从 MCP 工具返回值中提取纯文本内容。

    MCP 工具返回的结果可能是以下几种格式：
    1. 纯字符串
    2. ToolMessage 对象（有 content 属性）
    3. Python 列表字符串，如 "[{'type': 'text', 'text': '...', 'id': '...'}]"
    """
    import ast

    if raw is None:
        return ""

    # 如果是 ToolMessage 对象
    if hasattr(raw, "content"):
        raw = raw.content

    raw_str = str(raw)

    # 尝试用 ast.literal_eval 解析外层 Python 列表
    try:
        parsed = ast.literal_eval(raw_str)
        if isinstance(parsed, list) and parsed:
            first = parsed[0]
            if isinstance(first, dict) and "text" in first:
                return first["text"]
    except (ValueError, SyntaxError):
        pass

    return raw_str


async def call_mcp_tool(tool_name, arguments):
    """调用微信 MCP 工具，返回纯文本结果"""
    client = await get_wechat_mcp_client()
    if not client:
        return "Error: MCP client not initialized"

    tools = await client.get_tools()

    target_tool = None
    for tool in tools:
        if tool.name.endswith(tool_name):
            target_tool = tool
            break

    if not target_tool:
        return f"Error: Tool {tool_name} not found"

    try:
        result = await target_tool.ainvoke(arguments)
        return _extract_tool_text(result)
    except Exception as e:
        return f"Error calling tool: {e}"


def _parse_msg_list(json_str: str) -> list:
    """将 JSON 字符串解析为消息列表，兼容空值和异常"""
    if not json_str or json_str.strip() in ("[]", ""):
        return []
    try:
        return json.loads(json_str)
    except Exception:
        return []


def _msg_to_content(msg) -> str:
    """从消息对象（字典或字符串）中提取文本内容"""
    if isinstance(msg, dict):
        return msg.get("content", "")
    return str(msg)


def _extract_generated_files(reply: str) -> list:
    """从 Agent 回复中提取 generated_files 列表"""
    import re

    match = re.search(
        r'\{[^{}]*"generated_files"\s*:\s*\[([^\]]*)\][^{}]*\}', reply, re.DOTALL
    )
    if not match:
        return []
    try:
        json_str = match.group(0)
        data = json.loads(json_str)
        return [p for p in data.get("generated_files", []) if p]
    except Exception:
        return []


def _strip_generated_files_json(reply: str) -> str:
    """从 Agent 回复中移除 generated_files JSON 块（含前后的 markdown 代码块标记）"""
    import re

    cleaned = re.sub(
        r'```json\s*\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}\s*```',
        "",
        reply,
        flags=re.DOTALL,
    )
    cleaned = re.sub(
        r'\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}',
        "",
        cleaned,
        flags=re.DOTALL,
    )
    return cleaned.strip()


async def process_wechat_queue(queue):
    """处理未回复消息队列"""
    for item in queue:
        chat_name = item["chat_name"]
        messages = item["messages"]

        if not messages:
            continue

        logger.info(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] Processing messages from {chat_name}"
        )

        # 1. 直接使用 monitor_wechat_messages 返回的历史记录，避免再次激活微信
        chat_history = []
        for msg in item.get("history", []):
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type", "")
            if msg_type == "system":
                continue
            role = "用户" if msg_type == "received" else "AI"
            chat_history.append(
                {
                    "role": role,
                    "content": f"{msg.get('sender', '')}: {msg.get('content', '')}",
                }
            )

        # 2. 组装微信上下文，将附件路径注入供 Agent 使用（不会出现在微信回复中）
        wechat_context = f"你现在正在通过微信与联系人【{chat_name}】对话。\n"
        wechat_context += f"机主（你代表的人）的名字是：{OWNER_NAME}。\n"
        wechat_context += f"请注意，你的回复将直接发送给该联系人。\n"
        wechat_context += (
            f"你的回复的第一句话必须严格是：'{WECHAT_AI_REPLY_PREFIX}。'\n"
        )

        attachment_lines = [
            f"- {m.get('content', '')[:30]}... → {m['attachment_path']}"
            for m in messages
            if isinstance(m, dict) and m.get("attachment_path")
        ]
        if attachment_lines:
            wechat_context += "\n以下是本次对话中涉及的本地附件文件路径（供你直接调用工具使用，无需询问用户）：\n"
            wechat_context += "\n".join(attachment_lines) + "\n"

        # 3. 将未回复消息列表拼接为用户输入，附件消息同时附上本地路径标注
        def _msg_with_path(m) -> str:
            if not isinstance(m, dict):
                return str(m)
            content = m.get("content", "")
            path = m.get("attachment_path")
            if path:
                return f"{content}\n[本地文件路径: {path}]"
            return content

        user_input = "\n".join(_msg_with_path(m) for m in messages)

        # 4. Call /quotation endpoint
        # 同一联系人固定使用相同的 thread_id 和 session_id，
        # 确保 LangGraph Checkpointer 能持久化并复用历史对话记录
        safe_name = chat_name.replace(" ", "_")
        thread_id = f"wechat_{safe_name}"
        session_id = f"wechat_session_{safe_name}"

        payload = {
            "user_input": user_input,
            "chat_history": chat_history,
            "thread_id": thread_id,
            "sessionId": session_id,
            "mode": 0,  # Stream mode
            "username": OWNER_NAME,
            "wechat_context": wechat_context,
            "contact_name": safe_name,
        }

        logger.info(f"Calling Agent for {safe_name}...")
        try:
            full_content = []
            raw_step_files = []
            with requests.post(
                f"{BASE_URL}/quotation", json=payload, stream=True, timeout=1200
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            try:
                                event = json.loads(data)
                                event_type = event.get("event_type")
                                if event_type == "done":
                                    full_content.append(event.get("content", ""))
                                elif event_type in ("agent_step", "think"):
                                    # agent_step 事件携带 generated_files 字段（在 JSON 块被删除前提取）
                                    step_files = event.get("generated_files", [])
                                    if step_files:
                                        raw_step_files.extend(step_files)
                            except json.JSONDecodeError:
                                pass

            agent_reply = "".join(full_content)
            logger.info(f"Agent reply: {agent_reply[:100]}...")

            # 5. Ensure the reply starts with the required prefix
            prefix = f"{WECHAT_AI_REPLY_PREFIX}。"
            if not agent_reply.startswith(prefix):
                if agent_reply.startswith(WECHAT_AI_REPLY_PREFIX):
                    agent_reply = prefix + agent_reply[
                        len(WECHAT_AI_REPLY_PREFIX) :
                    ].lstrip("。")
                else:
                    agent_reply = prefix + "\n" + agent_reply

            # 6. 提取 generated_files：优先从 agent_step 原始内容中获取（JSON 未被删除），
            #    再从 done 事件的最终回复中补充，合并去重
            done_files = _extract_generated_files(agent_reply)
            seen = set()
            generated_files = []
            for f in raw_step_files + done_files:
                if f not in seen:
                    seen.add(f)
                    generated_files.append(f)
            clean_reply = _strip_generated_files_json(agent_reply)

            # 7. 先逐个发送生成的文件（必须在文字回复之前，避免触发下一轮监控）
            for file_path in generated_files:
                if os.path.exists(file_path):
                    # 安全检查：对发送给客户的文件进行内容安全审查
                    file_check = await _security_engine.check_file(file_path, "wechat")
                    if not file_check.passed:
                        logger.info(
                            "[安全拦截-微信] 文件发送被拦截: file={}, violations={}",
                            file_path,
                            file_check.violations,
                        )
                        notify_msg = _security_engine.build_owner_notify_message(
                            file_check, context=f"微信联系人「{chat_name}」的文件发送"
                        )
                        if notify_msg:
                            await call_mcp_tool(
                                "send_wechat_message",
                                {"chat_name": OWNER_NAME, "message": notify_msg},
                            )
                        continue  # 跳过违规文件，不发送
                    logger.info(f"Sending generated file to {chat_name}: {file_path}")
                    file_result = await call_mcp_tool(
                        "send_wechat_file",
                        {"chat_name": chat_name, "file_path": file_path},
                    )
                    logger.info(f"File send result: {file_result}")
                else:
                    logger.info(f"Generated file not found, skipping: {file_path}")

            # 8. 最后发送文字回复
            # 安全检查：对发送给客户的文本内容进行安全审查
            text_check = await _security_engine.check_text(clean_reply, "wechat")
            if not text_check.passed:
                logger.info(
                    "[安全拦截-微信] 文本回复被拦截: violations={}",
                    text_check.violations,
                )
                notify_msg = _security_engine.build_owner_notify_message(
                    text_check, context=f"微信联系人「{chat_name}」的文本回复"
                )
                if notify_msg:
                    await call_mcp_tool(
                        "send_wechat_message",
                        {"chat_name": OWNER_NAME, "message": notify_msg},
                    )
                # 替换为安全提示语
                safe_msg = (
                    text_check.safe_content or "该回复经安全审查未通过，暂无法发送。"
                )
                send_result = await call_mcp_tool(
                    "send_wechat_message", {"chat_name": chat_name, "message": safe_msg}
                )
            else:
                logger.info(f"Sending reply to {chat_name}...")
                send_result = await call_mcp_tool(
                    "send_wechat_message",
                    {"chat_name": chat_name, "message": clean_reply},
                )
            logger.info(f"Send result: {send_result}")

        except Exception as e:
            logger.error("Error calling Agent or sending reply: {}", e)

        # Sleep a bit between processing different contacts
        await asyncio.sleep(2)


async def main_loop():
    logger.info(f"Starting WeChat Agent Monitor...")
    logger.info(f"Monitoring contacts: {WECHAT_CONTACTS}")
    logger.info(f"Check interval: {CHECK_INTERVAL} seconds")

    while True:
        try:
            # 1. Check if Agent is busy with other tasks
            if is_agent_busy():
                logger.info(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Agent is busy. Pausing monitoring..."
                )
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            # 2. Monitor WeChat messages
            logger.info(
                f"[{datetime.now().strftime('%H:%M:%S')}] Checking WeChat messages..."
            )
            result_str = await call_mcp_tool(
                "monitor_wechat_messages", {"contacts": WECHAT_CONTACTS}
            )

            if result_str:
                try:
                    # Try to parse as JSON
                    if isinstance(result_str, str):
                        # The result might be a string representation of a list of dicts
                        # e.g. "[{'type': 'text', 'text': '[{"chat_name": "文件传输助手", "messages": [...]}]'}]"
                        # Let's try to extract the actual JSON array
                        import ast

                        try:
                            # First try to evaluate it as a Python literal (list of dicts)
                            parsed_result = ast.literal_eval(result_str)
                            if (
                                isinstance(parsed_result, list)
                                and len(parsed_result) > 0
                            ):
                                first_item = parsed_result[0]
                                if (
                                    isinstance(first_item, dict)
                                    and "text" in first_item
                                ):
                                    # Extract the inner JSON string
                                    inner_json_str = first_item["text"]
                                    queue = json.loads(inner_json_str)
                                else:
                                    # Maybe it's already the queue
                                    queue = parsed_result
                            else:
                                queue = parsed_result
                        except (ValueError, SyntaxError):
                            # Fallback to standard JSON parsing
                            if result_str.strip().startswith("["):
                                queue = json.loads(result_str)
                            else:
                                queue = None
                                logger.info(f"Monitor result: {result_str}")

                        if queue is not None:
                            if queue:
                                logger.info(
                                    f"Found unreplied messages from {len(queue)} contacts."
                                )
                                # 3. Process the queue
                                await process_wechat_queue(queue)
                            else:
                                logger.info("No unreplied messages.")
                    else:
                        logger.info(f"Monitor result: {result_str}")
                except json.JSONDecodeError as e:
                    logger.error(
                        "Error parsing monitor result: {}. Raw result: {}",
                        e,
                        result_str,
                    )
            else:
                logger.info("No result from monitor tool.")

        except Exception as e:
            logger.error("Error in monitor loop: {}", e)

        # Wait for the next check
        await asyncio.sleep(CHECK_INTERVAL)


def main():
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
