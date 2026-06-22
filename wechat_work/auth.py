import time

from cachetools import TTLCache
from loguru import logger


class AuthManager:
    """权限验证与防重放服务"""

    def __init__(self, allowed_users: list[str], nonce_ttl: int = 300):
        self.allowed_users = allowed_users
        self.nonce_ttl = nonce_ttl
        # 使用 TTLCache 存储 nonce，自动过期
        self.nonce_cache = TTLCache(maxsize=10000, ttl=nonce_ttl)

    def verify(self, user_id: str, timestamp: str, nonce: str) -> bool:
        """
        验证用户权限及防重放
        :param user_id: 用户ID
        :param timestamp: 请求时间戳
        :param nonce: 随机数
        :return: bool
        """
        # 1. 白名单校验
        if self.allowed_users and user_id not in self.allowed_users:
            logger.info("拦截非白名单用户: {}", user_id)
            return False

        # 2. 时间戳窗口校验 (5分钟)
        try:
            ts = int(timestamp)
            now = int(time.time())
            if abs(now - ts) > self.nonce_ttl:
                logger.info("时间戳过期: {}", timestamp)
                return False
        except ValueError:
            return False

        # 3. Nonce 缓存校验 (防重放)
        if nonce in self.nonce_cache:
            logger.info("Nonce重复 (重放攻击): {}", nonce)
            return False

        # 记录 nonce
        self.nonce_cache[nonce] = True
        return True
