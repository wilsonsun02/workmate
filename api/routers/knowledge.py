"""知识库管理 API 路由。

提供个人/公司知识库的分类管理和文件管理接口。
所有接口支持可选 username 参数，用于多用户数据隔离。
通过 type 参数区分 personal（个人）和 company（公司）知识库。
"""

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel

router = APIRouter(prefix="/knowledge", tags=["知识库管理"])


class CreateCategoryRequest(BaseModel):
    name: str
    type: str = "personal"


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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """获取知识库分类列表。"""
    try:
        from services.knowledge_service import get_categories

        categories = get_categories(type, username=username)
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error(f"获取分类列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories")
async def create_category(
    request: CreateCategoryRequest,
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """创建新的知识库分类。"""
    try:
        from services.knowledge_service import create_category

        result = create_category(request.name, kb_type=request.type, username=username)
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """删除知识库分类及其所有文件。"""
    try:
        from services.knowledge_service import delete_category

        result = delete_category(name, kb_type=type, username=username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = Query(..., description="所属分类名称"),
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """上传文件到知识库，自动转换为 Markdown 格式。"""
    try:
        from services.knowledge_service import upload_file as upload_kb_file

        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        file_content = await file.read()
        result = await upload_kb_file(
            file_content, file.filename, category, kb_type=type, username=username
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """批量上传文件到知识库，自动转换为 Markdown 格式，返回每个文件的上传结果。"""
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
                content, f.filename, category, kb_type=type, username=username
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """添加 URL 网页到知识库。"""
    try:
        from services.knowledge_service import add_url as add_kb_url

        result = await add_kb_url(
            request.url, request.category, kb_type=type, username=username
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """批量添加 URL 网页到知识库，返回每个URL的处理结果。"""
    import asyncio

    from services.knowledge_service import add_url as add_kb_url

    if not request.urls:
        raise HTTPException(status_code=400, detail="URL列表不能为空")

    async def _add_one(url: str) -> dict:
        try:
            result = await add_kb_url(
                url, request.category, kb_type=type, username=username
            )
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """获取知识库文件列表。"""
    try:
        from services.knowledge_service import get_files

        files = get_files(category, type, username=username)
        return {"success": True, "files": files}
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """获取知识库文件内容。"""
    try:
        from services.knowledge_service import get_file_content

        result = get_file_content(file_id, kb_type=type, username=username)
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """编辑知识库文件内容，并重新生成摘要。"""
    try:
        from services.knowledge_service import update_file_and_summary

        result = await update_file_and_summary(
            file_id, request.content, kb_type=type, username=username
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """删除知识库文件。"""
    try:
        from services.knowledge_service import delete_file as delete_kb_file

        result = delete_kb_file(file_id, kb_type=type, username=username)
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
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """搜索知识库文件。"""
    try:
        from services.knowledge_service import search_files as search_kb_files

        results = search_kb_files(q, category, kb_type=type, username=username)
        return {"success": True, "files": results}
    except Exception as e:
        logger.error(f"搜索文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 知识库分享接口 =====


class ShareFilesRequest(BaseModel):
    file_ids: List[str]
    target_username: str


class MoveFileRequest(BaseModel):
    target_category: str


@router.post("/shares")
async def share_files(
    request: ShareFilesRequest,
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """分享知识库文件给指定用户。"""
    try:
        from services.knowledge_service import share_files as do_share

        result = do_share(
            request.file_ids, request.target_username, owner_username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "分享失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分享文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shares/received")
async def get_received_shares(
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """获取别人分享给我的文件列表。"""
    try:
        from services.knowledge_service import get_received_shares

        files = get_received_shares(username=username)
        return {"success": True, "files": files}
    except Exception as e:
        logger.error(f"获取收到的分享列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shares/sent")
async def get_sent_shares(
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """获取我分享出去的文件列表。"""
    try:
        from services.knowledge_service import get_sent_shares

        files = get_sent_shares(username=username)
        return {"success": True, "files": files}
    except Exception as e:
        logger.error(f"获取发出的分享列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/shares/{share_id}")
async def cancel_share(
    share_id: str,
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """取消分享（仅分享人可操作）。"""
    try:
        from services.knowledge_service import cancel_share as do_cancel

        result = do_cancel(share_id, owner_username=username)
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "取消分享失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消分享失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/{file_id}/move")
async def move_file(
    file_id: str,
    request: MoveFileRequest,
    type: str = Query("personal", description="知识库类型：personal 或 company"),
    username: Optional[str] = Query(None, description="用户名，为空则自动获取"),
):
    """移动知识库文件到另一个分类。"""
    try:
        from services.knowledge_service import move_file as do_move

        result = do_move(
            file_id, request.target_category, kb_type=type, username=username
        )
        if result.get("success"):
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "移动失败"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
