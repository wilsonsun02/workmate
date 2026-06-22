#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行 /quotation 接口脚本
支持两种模式：
1. 普通模式：直接运行指定问题
2. 定时任务模式：通过环境变量 SCHEDULED_TASK_PROMPT 传入任务内容
"""

import requests
import json
import sys
import threading
from datetime import datetime
from workflow.config import WECHAT_CONTACTS, OWNER_NAME
from cloud_client import get_cloud_client
import asyncio

from loguru import logger

# 服务地址
BASE_URL = "http://127.0.0.1:8009"


def _run_cloud_client():
    client = get_cloud_client()
    if client.has_credentials():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(client.start())


def start_cloud_sync():
    """启动云端同步（后台线程）"""
    t = threading.Thread(target=_run_cloud_client, daemon=True)
    t.start()
    import time

    time.sleep(2)  # 等待初始配置同步


def generate_session_id(prefix: str = "session") -> str:
    """生成基于当前时间的唯一会话ID"""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    # return "task_2026030102"


def run_quotation(
    user_input: str,
    thread_id: str = "test_session_2026030102",
    session_id: str = "test_session_2026030102",
    wechat_context: str = "",
    username: str = OWNER_NAME,
    contact_name: str = "",
):
    """运行 /quotation 接口 (非流式)"""

    url = f"{BASE_URL}/quotation"

    payload = {
        "user_input": user_input,
        "chat_history": [],
        "thread_id": thread_id,
        "sessionId": session_id,
        "mode": 0,
        "username": username,
        "wechat_context": wechat_context,
        "contact_name": contact_name,
    }

    logger.info(f"=" * 50)
    logger.info(f"运行请求:")
    logger.info(f"URL: {url}")
    logger.info(f"输入: {user_input}")
    logger.info(f"=" * 50)

    try:
        response = requests.post(url, json=payload, timeout=1200)
        response.raise_for_status()

        result = response.json()
        logger.info(f"\n响应结果:")
        logger.info(json.dumps(result, ensure_ascii=False, indent=2))

        return result

    except requests.exceptions.RequestException as e:
        logger.info(f"\n请求错误: {e}")
        return None


def run_stream_quotation(
    user_input: str,
    thread_id: str = "test_thread_2026030102",
    session_id: str = "test_session_2026030102",
    wechat_context: str = "",
    username: str = OWNER_NAME,
    contact_name: str = "",
    scheduled_task_invocation: bool = False,
):
    """运行流式 /quotation 接口 (mode=0)"""

    url = f"{BASE_URL}/quotation"

    payload = {
        "user_input": user_input,
        "chat_history": [],
        "thread_id": thread_id,
        "sessionId": session_id,
        "mode": 0,
        "username": username,
        "wechat_context": wechat_context,
        "contact_name": contact_name,
        "scheduled_task_invocation": scheduled_task_invocation,
    }

    logger.info(f"=" * 50)
    logger.info(f"运行流式请求:")
    logger.info(f"URL: {url}")
    logger.info(f"输入: {user_input}")
    logger.info(f"=" * 50)

    full_content = []

    try:
        with requests.post(url, json=payload, stream=True, timeout=1200) as response:
            response.raise_for_status()

            logger.info(f"\n流式响应:")

            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            event = json.loads(data)
                            logger.info(json.dumps(event, ensure_ascii=False, indent=2))

                            # 收集内容
                            if event.get("event_type") == "done":
                                full_content.append(event.get("content", ""))
                            elif event.get("event_type") == "think":
                                content = event.get("content", "")
                                if content:
                                    full_content.append(content)

                        except json.JSONDecodeError:
                            logger.info(data)

            return "".join(full_content)

    except requests.exceptions.RequestException as e:
        logger.info(f"\n请求错误: {e}")
        return None


_contacts_list = [c.strip() for c in WECHAT_CONTACTS.split(",")]
SCHEDULED_TASK_WECHAT_CONTACT = (
    "文件传输助手"
    if "文件传输助手" in _contacts_list
    else (_contacts_list[0] if _contacts_list else "")
)


def run_scheduled_task(
    task_prompt: str,
    username: str = OWNER_NAME,
    wechat_context: str = "",
    contact: str = "",
):
    """
    运行定时任务
    定时任务模式下，直接调用流式接口并等待结果
    """
    import time

    thread_id = f"scheduled_{int(time.time())}"
    session_id = f"session_{int(time.time())}"

    logger.info(f"=" * 50)
    logger.info(f"定时任务模式:")
    logger.info(f"任务内容: {task_prompt}")
    logger.info(f"用户名: {username}")
    logger.info(f"联系人: {contact}")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"=" * 50)

    result = run_stream_quotation(
        task_prompt,
        thread_id,
        session_id,
        wechat_context,
        username,
        contact_name=contact,
        scheduled_task_invocation=True,
    )

    if result:
        logger.info(f"\n任务执行完成")
        return result
    else:
        logger.info(f"\n任务执行失败")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Agent 任务执行器")
    parser.add_argument("question", nargs="?", help="要执行的问题/任务")
    parser.add_argument("--task-prompt", help="定时任务提示词")
    parser.add_argument("--username", default=OWNER_NAME, help="执行任务的用户名")
    parser.add_argument("--contact", default="", help="接收结果的微信联系人")
    parser.add_argument(
        "--mode", type=int, default=0, help="运行模式: 0=流式(MCP), 1/2=非流式"
    )

    args = parser.parse_args()

    # 检查是否是定时任务模式
    # 优先使用命令行参数，其次检查环境变量（兼容旧方式）
    scheduled_task_prompt = args.task_prompt
    scheduled_username = args.username
    scheduled_contact = args.contact

    # 启动云端同步
    start_cloud_sync()

    if scheduled_task_prompt:
        # 定时任务模式
        run_scheduled_task(
            scheduled_task_prompt, scheduled_username, contact=scheduled_contact
        )
    else:
        # 普通模式 - 动态生成 thread_id 和 session_id
        thread_id = generate_session_id("thread")
        session_id = generate_session_id("session")

        test_questions = [
            # """
            # 获取美国、以色列与伊朗军事冲突的最新消息（调用 report-writer 技能）：
            # 1. 分析当前冲突状态与可能的影响
            # 2. 查询中东石油、天然气的产量、产能、储备等数据、市场报价信息
            # 3. 查询中东铜铝的产量、产能等产业信息
            # 4. 分析冲突对中国石油、天然气价格的影响
            # 5. 分析冲突对全球铜铝等大宗商品价格的影响
            # 6. 分析冲突对全球经济的影响
            # 7. 生成一篇word报告
            # 调用 extract-data 技能，从本地图片中提取结构化数据（示例路径见 skills/extract-data/SKILL.md）
            # 调用 report-operate 技能，生成 "电解铝市场分析" 报告。
            """
            查询市场热点新闻，并编写一份简报
            """
        ]

        # 默认运行问题
        question = args.question or (
            test_questions[0] if len(sys.argv) < 2 else sys.argv[1]
        )

        # 选择模式：0 = 流式(推荐用于MCP工具), 1/2 = 非流式(知识库查询)
        mode = args.mode

        logger.info(f"Thread ID: {thread_id}")
        logger.info(f"Session ID: {session_id}")

        if mode == 1 or mode == 2:
            run_quotation(question, thread_id, session_id)
        else:
            run_stream_quotation(question, thread_id, session_id)
