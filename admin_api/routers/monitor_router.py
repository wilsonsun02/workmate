from fastapi import APIRouter, HTTPException, Header
from typing import Optional

from admin_api.models.init_db import get_db_connection
from admin_api.routers.auth_router import verify_token
from admin_api.routers.client_router import manager
from admin_api.services.user_service import UserService
from loguru import logger

router = APIRouter()


def get_current_user(authorization: str = Header(None)) -> dict:
    """从 Authorization header 中获取当前用户"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    token = authorization.removeprefix("Bearer ").strip()
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或令牌已过期")
    return session


@router.get("/employees")
async def get_all_employees_status(
    user_ids: Optional[str] = None,
    authorization: str = Header(None),
):
    """获取员工实时在线状态列表"""
    get_current_user(authorization)

    try:
        ids: list[str] = []
        seen: set[str] = set()
        for raw in str(user_ids or "").split(","):
            uid = raw.strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            ids.append(uid)

        status_map = manager.get_users_status(ids)
        employees = []
        for uid in ids:
            user_status = status_map.get(uid) or {
                "is_online": False,
                "work_status": "offline",
                "current_task": None,
                "updated_at": "",
            }
            employees.append(
                {
                    "user_id": uid,
                    "is_online": user_status["is_online"],
                    "work_status": user_status["work_status"],
                    "current_task": user_status["current_task"],
                    "status_updated_at": user_status["updated_at"],
                }
            )

        return {
            "success": True,
            "employees": employees,
            "total": len(employees),
        }

    except Exception as e:
        logger.error(f"获取员工状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/employees/{user_id}")
async def get_employee_status_detail(user_id: str, authorization: str = Header(None)):
    """获取指定员工实时状态详情"""
    get_current_user(authorization)

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        cursor = conn.cursor(dictionary=True)

        # 获取用户信息
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 从 ConnectionManager 获取在线状态和工作状态
        user_status = manager.get_user_status(user_id)
        is_online = user_status["is_online"]
        work_status = user_status["work_status"]
        current_task = user_status["current_task"]
        status_updated_at = user_status["updated_at"]

        # 获取该用户相关的协同任务
        cursor.execute(
            """
            SELECT c.id, c.title, c.status, c.current_step, c.total_steps, c.updated_at,
                   s.step_index, s.status as step_status
            FROM collab_chains c
            JOIN collab_steps s ON c.id = s.chain_id
            WHERE s.assignee_user_id = %s
            ORDER BY c.updated_at DESC
            LIMIT 10
        """,
            (user_id,),
        )
        recent_tasks = cursor.fetchall()

        return {
            "success": True,
            "employee": {
                "user_id": user["id"],
                "username": user["username"],
                "role_name": user.get("role_name", ""),
                "dept_name": user.get("dept_name", ""),
                "is_online": is_online,
                "work_status": work_status,
                "current_task": current_task,
                "status_updated_at": status_updated_at,
                "recent_tasks": recent_tasks,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取员工详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
