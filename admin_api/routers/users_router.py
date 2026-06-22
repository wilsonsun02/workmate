from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from admin_api.services.user_service import UserService
from admin_api.services.user_preference_service import UserPreferenceService

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    name: Optional[str] = None
    title: Optional[str] = None
    password: Optional[str] = None
    third_party_id: Optional[str] = None
    wechat_work_id: Optional[str] = None
    wxwork_bot_name: Optional[str] = None
    wxwork_bot_id: Optional[str] = None
    wxwork_secret: Optional[str] = None
    role_id: Optional[str] = None
    dept_id: Optional[str] = None
    tenant_id: Optional[str] = None
    is_special: Optional[int] = None
    special_type: Optional[str] = None
    external_agent_base_url: Optional[str] = None
    external_agent_token: Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    password: Optional[str] = None
    third_party_id: Optional[str] = None
    wechat_work_id: Optional[str] = None
    wxwork_bot_name: Optional[str] = None
    wxwork_bot_id: Optional[str] = None
    wxwork_secret: Optional[str] = None
    role_id: Optional[str] = None
    dept_id: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[int] = None
    is_special: Optional[int] = None
    special_type: Optional[str] = None
    external_agent_base_url: Optional[str] = None
    external_agent_token: Optional[str] = None


class WxWorkBotConfigPayload(BaseModel):
    wxwork_bot_name: str
    wxwork_bot_id: str
    wxwork_secret: str


class DepartmentCreate(BaseModel):
    name: str
    dept_code: Optional[str] = None
    manager_user_id: Optional[str] = None
    parent_id: Optional[str] = None
    tenant_id: Optional[str] = None
    third_party_id: Optional[str] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    dept_code: Optional[str] = None
    manager_user_id: Optional[str] = None
    parent_id: Optional[str] = None
    tenant_id: Optional[str] = None
    third_party_id: Optional[str] = None


@router.get("/")
async def get_users(
    tenant_id: Optional[str] = None,
    keyword: Optional[str] = None,
    dept_id: Optional[str] = None,
    role_id: Optional[str] = None,
    status: Optional[int] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    users, total = UserService.list_users_paginated(
        tenant_id=tenant_id,
        keyword=keyword,
        dept_id=dept_id,
        role_id=role_id,
        status=status,
        limit=limit,
        offset=offset,
        include_extra_fields=True,
    )
    return {
        "success": True,
        "data": users,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/departments")
async def get_departments(tenant_id: Optional[str] = None):
    depts = UserService.get_departments(tenant_id)
    return {"success": True, "data": depts}


@router.get("/roles")
async def get_roles():
    roles = UserService.get_roles()
    return {"success": True, "data": roles}


@router.get("/employees/basic")
async def get_employee_basics(
    tenant_id: Optional[str] = None,
    keyword: Optional[str] = None,
    dept_id: Optional[str] = None,
    status: Optional[int] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    users, total = UserService.list_users_paginated(
        tenant_id=tenant_id,
        keyword=keyword,
        dept_id=dept_id,
        status=status,
        limit=limit,
        offset=offset,
        include_extra_fields=True,
    )
    items = [
        {
            "id": user["id"],
            "username": user["username"],
            "name": user.get("name") or user["username"],
            "title": user.get("title") or "",
            "dept_id": user.get("dept_id") or "",
            "dept_name": user.get("dept_name") or "",
            "third_party_id": user.get("third_party_id") or "",
            "wechat_work_id": user.get("wechat_work_id") or "",
            "status": user.get("status"),
            "is_special": user.get("is_special") or 0,
            "special_type": user.get("special_type") or "",
            "external_agent_base_url": user.get("external_agent_base_url") or "",
            "created_at": user.get("created_at"),
        }
        for user in users
    ]
    return {
        "success": True,
        "data": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/")
async def create_user(user: UserCreate):
    try:
        user_id = UserService.create_user(
            username=user.username,
            name=user.name,
            title=user.title,
            third_party_id=user.third_party_id,
            wechat_work_id=user.wechat_work_id,
            wxwork_bot_name=user.wxwork_bot_name,
            wxwork_bot_id=user.wxwork_bot_id,
            wxwork_secret=user.wxwork_secret,
            role_id=user.role_id,
            dept_id=user.dept_id,
            tenant_id=user.tenant_id,
            is_special=user.is_special,
            special_type=user.special_type,
            external_agent_base_url=user.external_agent_base_url,
            external_agent_token=user.external_agent_token,
            password=user.password or "workmate123",  # 默认密码
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if user_id:
        return {"success": True, "message": "User created", "user_id": user_id}
    raise HTTPException(status_code=500, detail="Failed to create user")


@router.put("/{user_id}")
async def update_user(user_id: str, user: UserUpdate):
    try:
        success = UserService.update_user(
            user_id=user_id,
            username=user.username,
            name=user.name,
            title=user.title,
            third_party_id=user.third_party_id,
            wechat_work_id=user.wechat_work_id,
            wxwork_bot_name=user.wxwork_bot_name,
            wxwork_bot_id=user.wxwork_bot_id,
            wxwork_secret=user.wxwork_secret,
            role_id=user.role_id,
            dept_id=user.dept_id,
            tenant_id=user.tenant_id,
            status=user.status,
            is_special=user.is_special,
            special_type=user.special_type,
            external_agent_base_url=user.external_agent_base_url,
            external_agent_token=user.external_agent_token,
            password=user.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if success:
        return {"success": True, "message": "User updated"}
    raise HTTPException(status_code=500, detail="Failed to update user")


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    success = UserService.delete_user(user_id)
    if success:
        return {"success": True, "message": "User deleted"}
    raise HTTPException(status_code=500, detail="Failed to delete user")


@router.get("/{user_id}/wxwork-bot-config")
async def get_user_wxwork_bot_config(user_id: str):
    config = UserService.get_user_wxwork_bot_config(user_id)
    if config is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "data": config}


@router.put("/{user_id}/wxwork-bot-config")
async def save_user_wxwork_bot_config(user_id: str, payload: WxWorkBotConfigPayload):
    try:
        success = UserService.save_user_wxwork_bot_config(
            user_id=user_id,
            wxwork_bot_name=payload.wxwork_bot_name,
            wxwork_bot_id=payload.wxwork_bot_id,
            wxwork_secret=payload.wxwork_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "message": "企业微信机器人配置已保存"}


@router.get("/by-agent-username/{agent_username}/preferences")
async def list_user_preferences_by_agent_username(agent_username: str):
    rows = UserPreferenceService.list_preferences_by_username(agent_username)
    return {"success": True, "data": rows}


@router.get("/by-username/{username}/preferences")
async def list_user_preferences_by_username(username: str):
    rows = UserPreferenceService.list_preferences_by_username(username)
    return {"success": True, "data": rows}


@router.get("/{user_id}/preferences")
async def list_user_preferences(user_id: str):
    rows = UserPreferenceService.list_preferences(user_id)
    return {"success": True, "data": rows}


class UserPreferenceUpsertPayload(BaseModel):
    pref_value: str


@router.put("/{user_id}/preferences/{pref_key}")
async def upsert_user_preference(
    user_id: str, pref_key: str, payload: UserPreferenceUpsertPayload
):
    ok = UserPreferenceService.upsert_preference(user_id, pref_key, payload.pref_value)
    if ok:
        return {"success": True, "message": "偏好已保存"}
    raise HTTPException(status_code=400, detail="保存失败")


@router.delete("/{user_id}/preferences/{pref_key}")
async def delete_user_preference(user_id: str, pref_key: str):
    ok = UserPreferenceService.delete_preference(user_id, pref_key)
    if ok:
        return {"success": True, "message": "偏好已删除"}
    raise HTTPException(status_code=404, detail="偏好不存在")


@router.post("/departments")
async def create_department(dept: DepartmentCreate):
    dept_id = UserService.create_department(
        name=dept.name,
        dept_code=dept.dept_code,
        manager_user_id=dept.manager_user_id,
        parent_id=dept.parent_id,
        tenant_id=dept.tenant_id,
        third_party_id=dept.third_party_id,
    )
    if dept_id:
        return {
            "success": True,
            "message": "Department created",
            "department_id": dept_id,
        }
    raise HTTPException(status_code=500, detail="Failed to create department")


@router.put("/departments/{dept_id}")
async def update_department(dept_id: str, dept: DepartmentUpdate):
    try:
        success = UserService.update_department(
            dept_id=dept_id,
            name=dept.name,
            dept_code=dept.dept_code,
            manager_user_id=dept.manager_user_id,
            parent_id=dept.parent_id,
            tenant_id=dept.tenant_id,
            third_party_id=dept.third_party_id,
        )
        if success:
            return {"success": True, "message": "Department updated"}
        raise HTTPException(status_code=500, detail="Failed to update department")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/departments/{dept_id}")
async def delete_department(dept_id: str):
    try:
        success = UserService.delete_department(dept_id)
        if success:
            return {"success": True, "message": "Department deleted"}
        raise HTTPException(status_code=500, detail="Failed to delete department")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
