"""
定时任务 API 路由模块
提供定时任务管理的 RESTful API 接口
"""

import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from loguru import logger

router = APIRouter(prefix="/scheduler", tags=["定时任务管理"])


class CreateTaskRequest(BaseModel):
    """创建任务请求模型"""

    username: str
    task_description: str
    cron_expression: Optional[str] = None
    task_type: Optional[str] = "custom"
    task_name: Optional[str] = None


class DeleteUserExecutionsRequest(BaseModel):
    """按 id 批量删除，或按筛选条件清空执行历史"""

    username: str
    execution_ids: Optional[List[str]] = None
    task_id: Optional[str] = None
    status: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None


@router.post("/tasks")
async def create_task(request: CreateTaskRequest):
    """
    创建定时任务
    """
    try:
        from .tools import create_scheduled_task

        result = create_scheduled_task(
            username=request.username,
            task_description=request.task_description,
            cron_expression=request.cron_expression,
            task_type=request.task_type,
            task_name=request.task_name,
        )

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "创建失败"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(
    username: str = Query(..., description="用户名"),
    status: Optional[str] = Query(None, description="任务状态筛选"),
):
    """
    获取用户的定时任务列表
    """
    try:
        from .tools import list_scheduled_tasks

        result = list_scheduled_tasks(username, status)

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "获取失败"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, username: str = Query(..., description="用户名")):
    """
    获取任务详情
    """
    try:
        from .tools import get_task_details

        result = get_task_details(task_id, username)

        if result.get("success"):
            return result
        else:
            raise HTTPException(
                status_code=404, detail=result.get("error", "任务不存在")
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, username: str = Query(..., description="用户名")):
    """
    删除定时任务
    """
    try:
        from .tools import delete_scheduled_task

        result = delete_scheduled_task(task_id, username)

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str, username: str = Query(..., description="用户名")):
    """
    暂停定时任务
    """
    try:
        from .tools import pause_scheduled_task

        result = pause_scheduled_task(task_id, username)

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "暂停失败"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, username: str = Query(..., description="用户名")):
    """
    恢复定时任务
    """
    try:
        from .tools import resume_scheduled_task

        result = resume_scheduled_task(task_id, username)

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "恢复失败"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str, username: str = Query(..., description="用户名")):
    """
    立即执行任务
    """
    try:
        from .tools import run_task_now as run_task_now_sync

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: run_task_now_sync(task_id, username)
        )

        if result.get("success"):
            return result
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": result.get("error", "执行失败"),
                    "execution_id": result.get("execution_id"),
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"立即执行任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution_record(
    execution_id: str,
    username: str = Query(..., description="用户名"),
):
    """
    将仍处于 running 的执行记录标记为失败（清理服务重启后的遗留状态）。
    """
    try:
        from .tools import cancel_stale_execution

        result = cancel_stale_execution(execution_id, username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消执行记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions")
async def list_executions(
    task_id: str = Query(..., description="任务ID"),
    username: str = Query(..., description="用户名"),
    limit: int = Query(10, description="返回数量限制"),
):
    """
    获取任务执行历史
    """
    try:
        from .tools import get_task_execution_history

        result = get_task_execution_history(task_id, username, limit)

        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "获取失败"))

    except Exception as e:
        logger.error(f"获取执行历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/user_executions/delete")
async def delete_user_executions_route(request: DeleteUserExecutionsRequest):
    """
    删除当前用户的执行记录：传 execution_ids 则为选择删除；否则按筛选字段删除（与列表接口条件一致，全空则删除该用户全部历史）。
    """
    try:
        from .tools import delete_user_executions

        result = delete_user_executions(
            username=request.username,
            execution_ids=request.execution_ids,
            task_id=request.task_id,
            status=request.status,
            from_date=request.from_date,
            to_date=request.to_date,
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除执行记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user_executions")
async def list_user_executions_route(
    username: str = Query(..., description="用户名"),
    task_id: Optional[str] = Query(None, description="按任务ID筛选"),
    status: Optional[str] = Query(None, description="running/success/failed"),
    from_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(200, ge=1, le=500, description="最大返回条数"),
):
    """
    按用户列出定时任务执行历史（可跨任务、按日期与状态筛选）。
    """
    try:
        from .tools import list_user_executions

        result = list_user_executions(
            username,
            task_id=task_id,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "获取失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出用户执行记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
