from fastapi import APIRouter, HTTPException
from admin_api.services.sync_service import SyncService

router = APIRouter()


@router.post("/{tenant_id}")
async def sync_tenant_data(tenant_id: str):
    try:
        stats = SyncService.sync_tenant_data(tenant_id)
        return {"success": True, "message": "同步成功", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
