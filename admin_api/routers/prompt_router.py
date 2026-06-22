from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from admin_api.services.prompt_file_service import PromptFileService

router = APIRouter()


class PromptFileSaveRequest(BaseModel):
    content: str = ""


@router.get("/files")
async def list_prompt_files(owner_type: str = "root", owner_id: str = "root"):
    try:
        items = PromptFileService.list_prompt_files_for_owner(
            owner_type=owner_type, owner_id=owner_id
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"success": True, "items": items}


@router.get("/files/{file_name}")
async def get_prompt_file(
    file_name: str, owner_type: str = "root", owner_id: str = "root"
):
    try:
        data = PromptFileService.get_prompt_file(
            file_name, owner_type=owner_type, owner_id=owner_id
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")
    return {"success": True, "data": data}


@router.put("/files/{file_name}")
async def save_prompt_file(
    file_name: str,
    payload: PromptFileSaveRequest,
    request: Request,
    owner_type: str = "root",
    owner_id: str = "root",
):
    try:
        result = PromptFileService.save_prompt_file(
            file_name,
            payload.content,
            owner_type=owner_type,
            owner_id=owner_id,
            operator=getattr(request.state, "admin_session", {}) or {},
            source_ip=request.client.host if request.client else "",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))

    return {
        "success": True,
        "message": "Prompt 保存成功" if result["changed"] else "没有检测到内容变更",
        "changed": bool(result["changed"]),
        "file_name": result["file_name"],
        "version": result["version"],
        "sha256": result["sha256"],
        "updated_at": result["updated_at"],
    }


@router.get("/files/{file_name}/logs")
async def list_prompt_file_logs(
    file_name: str, limit: int = 50, owner_type: str = "root", owner_id: str = "root"
):
    try:
        items = PromptFileService.list_change_logs(
            file_name, owner_type=owner_type, owner_id=owner_id, limit=limit
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")
    return {"success": True, "items": items, "total": len(items)}


@router.get("/files/{file_name}/versions")
async def list_prompt_publish_versions(
    file_name: str, limit: int = 50, owner_type: str = "root", owner_id: str = "root"
):
    try:
        items = PromptFileService.list_version_history(
            file_name, owner_type=owner_type, owner_id=owner_id, limit=limit
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")
    return {"success": True, "items": items, "total": len(items)}
