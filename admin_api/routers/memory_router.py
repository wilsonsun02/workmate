from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from admin_api.services.memory_service import MemoryService

router = APIRouter()


class MidTermMemoryUpdate(BaseModel):
    summary: str


@router.get("/mid-term")
async def get_mid_term_memories(
    username: Optional[str] = None,
    thread_id: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows, total = MemoryService.list_mid_term(
        username=username,
        thread_id=thread_id,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": rows, "total": total}


@router.get("/mid-term/{memory_id}")
async def get_mid_term_memory_detail(memory_id: int):
    row = MemoryService.get_mid_term_detail(memory_id)
    if row:
        return {"success": True, "data": row}
    raise HTTPException(status_code=404, detail="记录不存在")


@router.put("/mid-term/{memory_id}")
async def update_mid_term_memory(memory_id: int, payload: MidTermMemoryUpdate):
    summary = payload.summary.strip()
    if not summary:
        raise HTTPException(status_code=400, detail="summary 不能为空")

    success = MemoryService.update_mid_term_summary(memory_id, summary)
    if success:
        return {"success": True, "message": "中期记忆更新成功"}
    raise HTTPException(status_code=404, detail="记录不存在或未发生变更")


@router.delete("/mid-term/{memory_id}")
async def delete_mid_term_memory(memory_id: int):
    success = MemoryService.delete_mid_term(memory_id)
    if success:
        return {"success": True, "message": "中期记忆删除成功"}
    raise HTTPException(status_code=404, detail="记录不存在")
