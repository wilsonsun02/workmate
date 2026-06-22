"""
企业微信智能机器人独立脚本

使用方法:
    python wxwork_agent.py

启动后会建立与企业微信的 WebSocket 长连接，
接收用户消息并调用 DeepAgent 处理后返回结果。

参考 wechat_agent.py 的设计模式，作为独立进程运行。
"""

import asyncio
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger

from workflow.config import (
    WECHAT_WORK_BOT_ID,
    WECHAT_WORK_SECRET,
    WECHAT_WORK_ALLOWED_USERS,
)

from wechat_work.websocket_client import start_websocket_client, stop_websocket_client
import wechat_work.message_handler as mh
from cloud_client import get_cloud_client


async def main():
    """主函数"""
    logger.info("{}", "=" * 50)
    logger.info("企业微信智能机器人启动中...")
    logger.info("{}", "=" * 50)

    # 启动云端客户端（后台任务）
    cloud_client = get_cloud_client()
    if cloud_client.has_credentials():
        asyncio.create_task(cloud_client.start())
        # 给一点时间让云端配置同步完成
        await asyncio.sleep(2)

    # 检查配置
    if not WECHAT_WORK_BOT_ID:
        logger.error("错误: 未配置 WXWORK_BOT_ID")
        logger.error("请在 .env 文件中配置:")
        logger.error("  WXWORK_BOT_ID=您的BotID")
        return

    if not WECHAT_WORK_SECRET:
        logger.error("错误: 未配置 WXWORK_SECRET")
        logger.error("请在 .env 文件中配置:")
        logger.error("  WXWORK_SECRET=您的Secret")
        return

    logger.info("BotID: {}", WECHAT_WORK_BOT_ID)
    logger.info(
        "白名单用户: {}",
        WECHAT_WORK_ALLOWED_USERS if WECHAT_WORK_ALLOWED_USERS else "无 (允许所有用户)",
    )
    logger.info("{}", "-" * 50)

    # 启动 WebSocket 客户端
    try:
        await start_websocket_client(
            on_message=mh.handle_message,
            on_streaming=mh.handle_streaming,
            on_error=mh.handle_error,
            on_connected=mh.handle_connected,
            on_disconnected=mh.handle_disconnected,
        )
        logger.info("企业微信 WebSocket 长连接已启动")

        # 保持运行
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭...")
    except Exception as e:
        logger.error("运行异常: {}", e)
        import traceback

        traceback.print_exc()
    finally:
        await stop_websocket_client()
        logger.info("企业微信 WebSocket 长连接已关闭")


if __name__ == "__main__":
    asyncio.run(main())
