import redis
import os
import re
from typing import Any

from fastapi import HTTPException, Request, status

# Redis connection pool
redis_pool = None

_PACKAGE_DOWNLOAD_RE = re.compile(r"^/api/admin/skills/packages/[^/]+/download/?$")


def get_redis_client():
    global redis_pool
    if not redis_pool:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_password = os.getenv("REDIS_PASSWORD", None)
        redis_pool = redis.ConnectionPool(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
        )
    return redis.Redis(connection_pool=redis_pool)


async def require_admin_auth(request: Request) -> dict[str, Any]:
    """
    Dependency for FastAPI to verify admin token
    """
    return await require_admin_auth_request(request)


def is_admin_auth_exempt_path(path: str) -> bool:
    """Return True for public admin endpoints that have their own auth flow."""
    normalized = "/" + str(path or "").lstrip("/")
    if normalized in {"/admin/health"}:
        return True
    if normalized.startswith("/api/admin/auth/"):
        return True
    # Skill package downloads are guarded by one-time package tokens.
    if _PACKAGE_DOWNLOAD_RE.match(normalized):
        return True
    # 模板运行时只读 API 无需 admin 鉴权
    if "/api/admin/templates/runtime/" in normalized:
        return True
    return False


def _extract_bearer_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    token = str(request.query_params.get("token") or "").strip()
    return token


async def require_admin_auth_request(request: Request) -> dict[str, Any]:
    """
    Verify the admin session token from Authorization: Bearer <token>.

    The token store currently lives in auth_router to preserve the existing
    login/logout response contract. Import lazily to avoid module import cycles.
    """
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from admin_api.routers.auth_router import verify_token

    session = verify_token(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.admin_session = session
    return session


def check_rate_limit(user_id: str, limit: int = 100, window: int = 3600):
    """
    Check if user has exceeded their rate limit
    """
    r = get_redis_client()
    key = f"rate_limit:{user_id}"

    current = r.get(key)
    if current and int(current) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    pipe.execute()


def consume_tokens(user_id: str, tokens: int):
    """
    Consume LLM tokens for a user
    """
    r = get_redis_client()

    # Check monthly quota
    quota_key = f"token_quota:{user_id}"
    used_key = f"token_used:{user_id}"

    quota = r.get(quota_key)
    if quota is not None:
        used = r.incrby(used_key, tokens)
        if used > int(quota):
            # Rollback if exceeded
            r.decrby(used_key, tokens)
            raise HTTPException(status_code=402, detail="Token quota exceeded")
    else:
        # If no quota set, just track usage
        r.incrby(used_key, tokens)
