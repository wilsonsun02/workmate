"""
任务通知模块
负责将任务执行结果通知给用户
支持微信（通过 MCP 工具）、邮件、钉钉、飞书等渠道
"""

import asyncio
import os
import sys
from typing import Optional, Dict, Any
from datetime import datetime

from .config import NOTIFICATION_ENABLED, NOTIFICATION_CHANNELS

from loguru import logger


def _scheduler_app_root() -> str:
    base = os.environ.get("BASE_DIR", "").strip()
    if base:
        return os.path.expandvars(base)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TaskNotifier:
    """任务通知器类"""

    def __init__(self):
        """初始化通知器"""
        self.enabled = NOTIFICATION_ENABLED
        self.channels = NOTIFICATION_CHANNELS
        logger.info(
            f"TaskNotifier 初始化完成, enabled={self.enabled}, channels={self.channels}"
        )

    def notify(
        self,
        username: str,
        task_id: str,
        execution_id: str,
        status: str,
        result: str,
        attachments: Optional[list] = None,
        task_description: str = "",
    ) -> bool:
        """
        发送任务执行结果通知

        Args:
            username: 用户名
            task_id: 任务ID
            execution_id: 执行ID
            status: 执行状态 (success/failed/error)
            result: 执行结果
            attachments: 附件本地路径列表（先于文字消息发送）
            task_description: 任务描述内容

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.info(f"通知功能未启用，跳过通知: {username}, task_id={task_id}")
            return False

        message = self._build_message(
            username, task_id, execution_id, status, result, task_description
        )

        success = True
        for channel in self.channels:
            try:
                if not self._send_to_channel(channel, message, attachments or []):
                    success = False
            except Exception as e:
                logger.error(f"发送通知到 {channel} 失败: {e}")
                success = False

        return success

    def _build_message(
        self,
        username: str,
        task_id: str,
        execution_id: str,
        status: str,
        result: str,
        task_description: str = "",
    ) -> Dict[str, Any]:
        """构建通知消息"""
        status_text = {"success": "✅ 成功", "failed": "❌ 失败", "error": "⚠️ 错误"}

        return {
            "username": username,
            "task_id": task_id,
            "execution_id": execution_id,
            "status": status,
            "status_text": status_text.get(status, status),
            "result": result,
            "task_description": task_description,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _send_to_channel(
        self, channel: str, message: Dict[str, Any], attachments: list = None
    ) -> bool:
        """
        发送消息到指定渠道

        Args:
            channel: 渠道名称 (email/dingtalk/feishu/wechat)
            message: 消息内容
            attachments: 附件路径列表

        Returns:
            是否发送成功
        """
        if channel == "email":
            return self._send_email(message)
        elif channel == "dingtalk":
            return self._send_dingtalk(message)
        elif channel == "feishu":
            return self._send_feishu(message)
        elif channel == "wechat":
            return self._send_wechat(message, attachments or [])
        else:
            logger.info("未知渠道: {}", channel)
            return False

    def _send_email(self, message: Dict[str, Any]) -> bool:
        """发送邮件通知（预留）"""
        # TODO: 实现邮件发送逻辑
        # 可以使用 smtplib 或 yagmail 库
        logger.info(f"[预留] 发送邮件通知: {message['username']}")
        return True

    def _send_dingtalk(self, message: Dict[str, Any]) -> bool:
        """发送钉钉通知（预留）"""
        # TODO: 实现钉钉机器人通知
        # 使用钉钉机器人 Webhook
        logger.info(f"[预留] 发送钉钉通知: {message['username']}")
        return True

    def _send_feishu(self, message: Dict[str, Any]) -> bool:
        """发送飞书通知（预留）"""
        # TODO: 实现飞书机器人通知
        # 使用飞书 Webhook
        logger.info(f"[预留] 发送飞书通知: {message['username']}")
        return True

    def _send_wechat(self, message: Dict[str, Any], attachments: list = None) -> bool:
        """通过微信 MCP 工具发送任务执行结果通知（先发附件，再发文字）"""
        contact_name = message.get("username", "")
        if not contact_name:
            logger.info("[微信通知] 联系人名称为空，跳过发送")
            return False

        notify_text = self._format_wechat_message(message)

        try:
            return asyncio.run(
                self._async_send_wechat_with_attachments(
                    contact_name, attachments or [], notify_text
                )
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._async_send_wechat_with_attachments(
                        contact_name, attachments or [], notify_text
                    )
                )
            finally:
                loop.close()

    def _load_alias_name(self) -> str:
        """从 wechat.json 读取 alias_name"""
        try:
            config_path = os.path.join(_scheduler_app_root(), "config", "wechat.json")
            import json

            with open(config_path, encoding="utf-8") as f:
                return json.load(f).get("alias_name", "")
        except Exception:
            return ""

    def _format_wechat_message(self, message: Dict[str, Any]) -> str:
        """将通知消息格式化为微信可读文本（参考 monitor_wechat_messages 发送格式）"""
        alias_name = self._load_alias_name()
        status_text = message.get("status_text", message.get("status", ""))
        task_id = message.get("task_id", "")
        timestamp = message.get("timestamp", "")
        task_description = message.get("task_description", "")
        result = message.get("result", message.get("content", ""))

        header = f"现在是{alias_name}与您对话。\n\n" if alias_name else ""
        lines = [
            f"{header}【定时任务通知】{status_text}",
            f"任务ID：{task_id}",
            f"执行时间：{timestamp}",
        ]
        if task_description:
            lines.append(f"任务内容：{task_description}")
        lines += [
            "",
            "【定时任务执行结果】",
            str(result)[:1500] if result else "（无输出）",
        ]
        return "\n".join(lines)

    async def _async_send_wechat_with_attachments(
        self, contact_name: str, attachments: list, text: str
    ) -> bool:
        """异步调用 MCP 工具：先逐个发送附件，再发送文字消息"""
        _root = _scheduler_app_root()
        if _root not in sys.path:
            sys.path.insert(0, _root)

        from workflow.report_tools import load_mcp_config
        from workflow.robust_mcp_client import RobustMultiServerMCPClient

        mcp_servers, _ = load_mcp_config()
        if not mcp_servers:
            logger.error("[微信通知] MCP 配置加载失败，无法发送微信消息")
            return False

        client = RobustMultiServerMCPClient(mcp_servers)
        try:
            tools = await client.get_tools()
            file_tool = next(
                (t for t in tools if t.name.endswith("send_wechat_file")), None
            )
            msg_tool = next(
                (t for t in tools if t.name.endswith("send_wechat_message")), None
            )

            if not msg_tool:
                logger.error("[微信通知] 未找到 send_wechat_message 工具")
                return False

            # 第一步：逐个发送附件
            for file_path in attachments:
                if not file_tool:
                    logger.info(
                        "[微信通知] 未找到 send_wechat_file 工具，跳过附件: {}",
                        file_path,
                    )
                    continue
                try:
                    r = await file_tool.ainvoke(
                        {"chat_name": contact_name, "file_path": file_path}
                    )
                    logger.info(f"[微信通知] 附件发送成功 '{file_path}': {r}")
                except Exception as e:
                    logger.error(f"[微信通知] 附件发送失败 '{file_path}': {e}")

            # 第二步：发送文字消息
            result = await msg_tool.ainvoke(
                {"chat_name": contact_name, "message": text}
            )
            logger.info(f"[微信通知] 文字消息发送给 '{contact_name}' 成功: {result}")
            return True
        except Exception as e:
            logger.error(f"[微信通知] 发送给 '{contact_name}' 失败: {e}")
            return False
        finally:
            await client.shutdown()

    def send_custom_notification(
        self, username: str, title: str, content: str, channel: Optional[str] = None
    ) -> bool:
        """
        发送自定义通知

        Args:
            username: 用户名
            title: 通知标题
            content: 通知内容
            channel: 指定渠道，不指定则发送到所有启用的渠道

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.info(f"通知功能未启用，跳过通知")
            return False

        message = {
            "username": username,
            "title": title,
            "content": content,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if channel:
            return self._send_to_channel(channel, message)

        # 发送到所有渠道
        success = True
        for ch in self.channels:
            try:
                if not self._send_to_channel(ch, message):
                    success = False
            except Exception as e:
                logger.error(f"发送通知到 {ch} 失败: {e}")
                success = False

        return success


# 全局通知器实例
_notifier: Optional[TaskNotifier] = None


def get_notifier() -> TaskNotifier:
    """获取通知器单例"""
    global _notifier
    if _notifier is None:
        _notifier = TaskNotifier()
    return _notifier
