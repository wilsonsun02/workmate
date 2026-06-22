from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from admin_api.routers.auth_router import verify_token
from admin_api.services.agent_runtime_service import get_agent_base_url


router = APIRouter()


def _verify_admin_token(request: Request) -> None:
    authorization = request.headers.get("authorization") or ""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或令牌已过期")


async def _proxy(request: Request, path: str) -> Any:
    _verify_admin_token(request)

    base_url = get_agent_base_url().rstrip("/")
    url = f"{base_url}/scheduler/{path}".rstrip("/")

    query = dict(request.query_params)
    body = None
    if request.method not in ("GET", "DELETE"):
        try:
            body = await request.json()
        except Exception:
            body = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                params=query,
                json=body,
            )
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            return resp.json()
        return resp.text
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=f"Scheduler 代理失败: {str(e)}"
        ) from e


@router.api_route("/tasks", methods=["GET", "POST"])
async def scheduler_tasks(request: Request):
    return await _proxy(request, "tasks")


@router.api_route("/tasks/{task_id}", methods=["GET", "DELETE"])
async def scheduler_task_detail(task_id: str, request: Request):
    return await _proxy(request, f"tasks/{task_id}")


@router.api_route("/tasks/{task_id}/pause", methods=["POST"])
async def scheduler_task_pause(task_id: str, request: Request):
    return await _proxy(request, f"tasks/{task_id}/pause")


@router.api_route("/tasks/{task_id}/resume", methods=["POST"])
async def scheduler_task_resume(task_id: str, request: Request):
    return await _proxy(request, f"tasks/{task_id}/resume")


@router.api_route("/tasks/{task_id}/run", methods=["POST"])
async def scheduler_task_run(task_id: str, request: Request):
    return await _proxy(request, f"tasks/{task_id}/run")


@router.api_route("/executions", methods=["GET"])
async def scheduler_executions(request: Request):
    return await _proxy(request, "executions")


@router.api_route("/executions/{execution_id}", methods=["GET"])
async def scheduler_execution_detail(execution_id: str, request: Request):
    return await _proxy(request, f"executions/{execution_id}")


@router.api_route("/executions/{execution_id}/cancel", methods=["POST"])
async def scheduler_execution_cancel(execution_id: str, request: Request):
    return await _proxy(request, f"executions/{execution_id}/cancel")


@router.api_route("/users/{username}/executions", methods=["DELETE"])
async def scheduler_user_executions_delete(username: str, request: Request):
    return await _proxy(request, f"users/{username}/executions")
