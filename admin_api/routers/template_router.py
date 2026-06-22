"""模板管理路由。

提供模板分类查询、模板 CRUD、文件上传、批量操作和运行时只读接口。
"""

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel

from admin_api.services import template_service

router = APIRouter()


class UpdateTemplateRequest(BaseModel):
    template_name: Optional[str] = None
    template_type: Optional[str] = None
    description: Optional[str] = None
    style_config: Optional[str] = None
    is_active: Optional[int] = None
    sort_order: Optional[int] = None


class ToggleRequest(BaseModel):
    is_active: int


class BatchToggleRequest(BaseModel):
    ids: List[str]
    is_active: int


class BatchDeleteRequest(BaseModel):
    ids: List[str]


class BatchSortItem(BaseModel):
    id: str
    sort_order: int


class BatchSortRequest(BaseModel):
    items: List[BatchSortItem]


@router.get("/categories")
async def list_categories():
    """获取模板分类列表。"""
    try:
        categories = template_service.get_categories()
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error("获取模板分类列表失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_templates(
    category_key: str = Query("", description="分类标识"),
    keyword: str = Query("", description="搜索关键词"),
    is_active: Optional[int] = Query(None, description="启用状态: 1=启用, 0=禁用"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """分页获取模板列表。"""
    try:
        result = template_service.list_templates(
            category_key=category_key,
            keyword=keyword,
            is_active=is_active,
            page=page,
            page_size=page_size,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error("获取模板列表失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{template_id}")
async def get_template(template_id: str):
    """获取模板详情。"""
    try:
        template = template_service.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"success": True, "data": template}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取模板详情失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_template(
    category_key: str = Form(..., description="分类标识"),
    template_key: str = Form(..., description="模板唯一标识"),
    template_name: str = Form(..., description="模板名称"),
    template_type: str = Form("", description="兼容旧type编号"),
    description: str = Form("", description="模板描述"),
    style_config: str = Form("", description="样式配置JSON(仅报告模板)"),
    sort_order: int = Form(0, description="排序权重"),
    created_by: str = Form("", description="创建人"),
    file: UploadFile = File(..., description="模板文件"),
    cover: Optional[UploadFile] = File(None, description="封面图文件"),
):
    """创建模板。"""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="模板文件名不能为空")

        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="模板文件大小不能超过 50MB")

        cover_content = None
        cover_file_name = None
        if cover and cover.filename:
            cover_content = await cover.read()
            cover_file_name = cover.filename
            if len(cover_content) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="封面图大小不能超过 5MB")

        result = template_service.create_template(
            category_key=category_key,
            template_key=template_key,
            template_name=template_name,
            file_content=file_content,
            file_name=file.filename,
            template_type=template_type,
            description=description,
            style_config=style_config,
            sort_order=sort_order,
            created_by=created_by,
            cover_content=cover_content,
            cover_file_name=cover_file_name,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "创建失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("创建模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{template_id}")
async def update_template(template_id: str, request: UpdateTemplateRequest):
    """更新模板元信息。"""
    try:
        result = template_service.update_template(
            template_id, **request.model_dump(exclude_none=True)
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "更新失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("更新模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{template_id}/file")
async def update_template_file(
    template_id: str,
    file: UploadFile = File(..., description="模板文件"),
):
    """更新模板文件。"""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件大小不能超过 50MB")

        result = template_service.update_template_file(
            template_id=template_id,
            file_content=file_content,
            file_name=file.filename,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "更新文件失败")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("更新模板文件失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{template_id}/toggle")
async def toggle_template(template_id: str, request: ToggleRequest):
    """启用/禁用模板。"""
    try:
        result = template_service.update_template(
            template_id, is_active=request.is_active
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("切换模板状态失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{template_id}/upload-cover")
async def upload_cover(
    template_id: str,
    cover: UploadFile = File(..., description="封面图文件"),
):
    """上传模板封面图。"""
    try:
        if not cover.filename:
            raise HTTPException(status_code=400, detail="封面图文件名不能为空")

        cover_content = await cover.read()
        if len(cover_content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="封面图大小不能超过 5MB")

        result = template_service.update_template_cover(
            template_id=template_id,
            cover_content=cover_content,
            cover_file_name=cover.filename,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "上传封面失败")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("上传封面图失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """删除模板（软删除）。"""
    try:
        result = template_service.delete_template(template_id)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/batch-toggle")
async def batch_toggle(request: BatchToggleRequest):
    """批量启用/禁用模板。"""
    try:
        result = template_service.batch_toggle_templates(request.ids, request.is_active)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("批量切换模板状态失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/batch-delete")
async def batch_delete(request: BatchDeleteRequest):
    """批量删除模板。"""
    try:
        result = template_service.batch_delete_templates(request.ids)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("批量删除模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/batch-sort")
async def batch_sort(request: BatchSortRequest):
    """批量更新模板排序。"""
    try:
        items = [
            {"id": item.id, "sort_order": item.sort_order} for item in request.items
        ]
        result = template_service.batch_sort_templates(items)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("批量排序模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---- 运行时只读 API（供桌面端/技能使用，无需 admin 鉴权） ----


@router.get("/runtime/list")
async def runtime_list(category_key: str = Query("", description="分类标识")):
    """获取所有启用的模板列表。"""
    try:
        templates = template_service.get_runtime_templates(category_key=category_key)
        return {"success": True, "data": templates}
    except Exception as e:
        logger.error("获取运行时模板列表失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runtime/{template_key}")
async def runtime_get(template_key: str):
    """按 template_key 获取模板详情。"""
    try:
        template = template_service.get_runtime_template_by_key(template_key)
        if not template:
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"success": True, "data": template}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取运行时模板详情失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runtime/resolve/by-type")
async def runtime_resolve(
    type: str = Query(..., description="旧 template_type 编号"),
    category: str = Query("", description="分类标识"),
):
    """按旧 template_type 兼容查询模板。"""
    try:
        template = template_service.resolve_template_by_type(type, category=category)
        if not template:
            raise HTTPException(status_code=404, detail="未找到匹配的模板")
        return {"success": True, "data": template}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("兼容查询模板失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
