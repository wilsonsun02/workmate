from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import uuid
import time
from admin_api.services.user_service import UserService

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def _user_display_name(user: dict) -> str:
    """Prefer sys_users.name for UI; fall back to login username."""
    name = str(user.get("name") or "").strip()
    if name:
        return name
    return str(user.get("username") or "").strip()


# 简单实现：使用内存字典存储 token (实际生产环境应使用 JWT 或 Redis)
# Token: {"user_id": str, "username": str, "exp": float}
_TOKEN_STORE = {}


@router.post("/login")
async def login(req: LoginRequest):
    user = UserService.verify_password(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.get("status") == 0:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    display_name = _user_display_name(user)

    # 生成 Token (24小时有效期)
    token = str(uuid.uuid4())
    _TOKEN_STORE[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "exp": time.time() + 24 * 3600,
    }

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": display_name,
            "role_id": user.get("role_id"),
        },
    }


@router.get("/me")
async def get_me(authorization: str | None = Header(default=None)):
    """Return current session user profile (includes display name)."""
    token = _token_from_authorization(authorization)
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或 token 已过期")

    user = UserService.get_user_by_id(session["user_id"])
    if not user:
        user = UserService.get_user_by_username(session.get("username") or "")
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    display_name = _user_display_name(user)
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "name": display_name,
            "role_id": user.get("role_id"),
        },
    }


def _token_from_authorization(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


@router.post("/logout")
async def logout(token: str = "", authorization: str | None = Header(default=None)):
    token = str(token or "").strip() or _token_from_authorization(authorization)
    if token in _TOKEN_STORE:
        del _TOKEN_STORE[token]
    return {"success": True, "message": "登出成功"}


def verify_token(token: str) -> dict:
    """内部校验 Token 用的工具函数"""
    if not token or token not in _TOKEN_STORE:
        return None
    session = _TOKEN_STORE[token]
    if time.time() > session["exp"]:
        del _TOKEN_STORE[token]
        return None
    return session
