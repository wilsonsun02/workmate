"""管理端知识库路由。

提供公司/个人知识库的分类管理和文件管理接口，
供 admin-web 前端调用。
"""

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel

router = APIRouter()


class CreateCategoryRequest(BaseModel):
    name: str
    kb_type: str = "personal"
    username: str = ""


class AddUrlRequest(BaseModel):
    url: str
    category: str


class BatchAddUrlRequest(BaseModel):
    urls: List[str]
    category: str


class EditFileRequest(BaseModel):
    content: str


@router.get("/categories")
async def list_categories(
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """获取知识库分类列表。"""
    try:
        from services.knowledge_service import get_categories

        categories = get_categories(kb_type, username=username)
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error(f"获取分类列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories")
async def create_category(request: CreateCategoryRequest):
    """创建新的知识库分类。"""
    try:
        from services.knowledge_service import create_category

        result = create_category(
            request.name, kb_type=request.kb_type, username=request.username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "创建失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/categories/{name}")
async def delete_category(
    name: str,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """删除知识库分类及其所有文件。"""
    try:
        from services.knowledge_service import delete_category

        result = delete_category(name, kb_type=kb_type, username=username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RenameCategoryRequest(BaseModel):
    new_display_name: str


@router.put("/categories/{name}/rename")
async def rename_category(
    name: str,
    request: RenameCategoryRequest,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """重命名知识库分类（修改显示名称）。"""
    try:
        from services.knowledge_service import rename_category

        result = rename_category(
            name, request.new_display_name, kb_type=kb_type, username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "重命名失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = Query(..., description="所属分类名称"),
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """上传文件到知识库，自动转换为 Markdown 格式。"""
    try:
        from services.knowledge_service import upload_file as upload_kb_file

        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        file_content = await file.read()
        result = await upload_kb_file(
            file_content, file.filename, category, kb_type=kb_type, username=username
        )

        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "上传失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/batch-upload")
async def batch_upload_files(
    files: List[UploadFile] = File(...),
    category: str = Query(..., description="所属分类名称"),
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
):
    """批量上传文件到知识库。"""
    import asyncio

    from services.knowledge_service import upload_file as upload_kb_file

    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    async def _upload_one(f: UploadFile) -> dict:
        if not f.filename:
            return {"filename": "", "success": False, "error": "文件名不能为空"}
        try:
            content = await f.read()
            result = await upload_kb_file(
                content, f.filename, category, kb_type=kb_type
            )
            if result.get("success"):
                return {
                    "filename": f.filename,
                    "success": True,
                    "file": result.get("file"),
                }
            return {
                "filename": f.filename,
                "success": False,
                "error": result.get("error", "上传失败"),
            }
        except Exception as e:
            logger.error(f"批量上传 - 文件 {f.filename} 失败: {e}")
            return {"filename": f.filename, "success": False, "error": str(e)}

    results = await asyncio.gather(*[_upload_one(f) for f in files])
    success_count = sum(1 for r in results if r.get("success"))
    logger.info(f"批量上传完成: {success_count}/{len(files)} 成功")
    return {
        "success": True,
        "results": results,
        "total": len(files),
        "success_count": success_count,
    }


@router.post("/files/url")
async def add_url(
    request: AddUrlRequest,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """添加 URL 网页到知识库。"""
    try:
        from services.knowledge_service import add_url as add_kb_url

        result = await add_kb_url(
            request.url, request.category, kb_type=kb_type, username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "URL添加失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加URL失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/batch-url")
async def batch_add_urls(
    request: BatchAddUrlRequest,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
):
    """批量添加 URL 网页到知识库。"""
    import asyncio

    from services.knowledge_service import add_url as add_kb_url

    if not request.urls:
        raise HTTPException(status_code=400, detail="URL列表不能为空")

    async def _add_one(url: str) -> dict:
        try:
            result = await add_kb_url(url, request.category, kb_type=kb_type)
            if result.get("success"):
                return {"url": url, "success": True, "file": result.get("file")}
            return {
                "url": url,
                "success": False,
                "error": result.get("error", "URL添加失败"),
            }
        except Exception as e:
            logger.error(f"批量添加URL - {url} 失败: {e}")
            return {"url": url, "success": False, "error": str(e)}

    results = await asyncio.gather(
        *[_add_one(u.strip()) for u in request.urls if u.strip()]
    )
    success_count = sum(1 for r in results if r.get("success"))
    logger.info(f"批量添加URL完成: {success_count}/{len(results)} 成功")
    return {
        "success": True,
        "results": results,
        "total": len(results),
        "success_count": success_count,
    }


@router.get("/files")
async def list_files(
    category: Optional[str] = Query(None, description="分类名称"),
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """获取知识库文件列表。"""
    try:
        from services.knowledge_service import get_files

        files = get_files(category, kb_type, username=username)
        return {"success": True, "files": files}
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """获取知识库文件内容。"""
    try:
        from services.knowledge_service import get_file_content

        result = get_file_content(file_id, kb_type=kb_type, username=username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/files/{file_id}")
async def edit_file(
    file_id: str,
    request: EditFileRequest,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """编辑知识库文件内容，并重新生成摘要。"""
    try:
        from services.knowledge_service import update_file_and_summary

        result = await update_file_and_summary(
            file_id, request.content, kb_type=kb_type, username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "编辑失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"编辑文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """删除知识库文件。"""
    try:
        from services.knowledge_service import delete_file as delete_kb_file

        result = delete_kb_file(file_id, kb_type=kb_type, username=username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_files(
    q: str = Query(..., description="搜索关键词"),
    category: Optional[str] = Query(None, description="分类名称"),
    kb_type: str = Query(
        "personal", alias="type", description="知识库类型：personal 或 company"
    ),
):
    """搜索知识库文件。"""
    try:
        from services.knowledge_service import search_files as search_kb_files

        results = search_kb_files(q, category, kb_type=kb_type)
        return {"success": True, "files": results}
    except Exception as e:
        logger.error(f"搜索文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 知识库分享管理接口 =====


class MoveFileRequest(BaseModel):
    target_category: str


@router.get("/shares")
async def list_shares(
    page: int = Query(1, description="页码"),
    size: int = Query(20, description="每页数量"),
    keyword: str = Query("", description="搜索关键词"),
    owner: str = Query("", description="分享人筛选"),
    target: str = Query("", description="被分享人筛选"),
):
    """查询全公司知识库分享记录（管理端）。"""
    try:
        from services.knowledge_service import get_all_shares

        result = get_all_shares(
            page=page, size=size, keyword=keyword, owner=owner, target=target
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=500, detail=result.get("error", "查询失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询分享记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/{file_id}/move")
async def move_file(
    file_id: str,
    request: MoveFileRequest,
    kb_type: str = Query(
        "company", alias="type", description="知识库类型：personal 或 company"
    ),
    username: str = Query(
        "", alias="user", description="用户名（仅 personal 类型需要）"
    ),
):
    """移动知识库文件到另一个分类（管理端）。"""
    try:
        from services.knowledge_service import move_file as do_move

        result = do_move(
            file_id, request.target_category, kb_type=kb_type, username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "移动失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
