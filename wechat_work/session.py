class SessionManager:
    """会话管理器"""

    def get_thread_id(self, user_id: str) -> str:
        """
        获取用户的 thread_id
        使用固定的前缀+用户ID作为 thread_id，确保 DeepAgent 能读取历史记忆
        """
        return f"wechat_work_thread_{user_id}"

    def get_session_id(self, user_id: str) -> str:
        """获取用户的 session_id"""
        return f"wechat_work_session_{user_id}"
