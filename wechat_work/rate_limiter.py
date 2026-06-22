from collections import defaultdict
import time


class RateLimiter:
    """频率限制器"""

    def __init__(self, max_requests: int = 10, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)

    def is_allowed(self, user_id: str) -> bool:
        """检查用户请求是否允许"""
        now = time.time()
        # 清理过期记录
        self.requests[user_id] = [
            t for t in self.requests[user_id] if now - t < self.window
        ]

        if len(self.requests[user_id]) >= self.max_requests:
            return False

        self.requests[user_id].append(now)
        return True
