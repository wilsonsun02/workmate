"""模板管理服务层。

提供模板分类和模板的 CRUD 操作，包括文件上传到 OSS/本地存储、
样式配置校验、软删除等功能。
"""

import json
import os
import shutil
import uuid
from typing import Optional

from loguru import logger

from admin_api.models.init_db import db_cursor
from admin_api.services.oss_service import OssService
from workflow.config import BASE_DIR


_TEMPLATE_OSS_DIR = os.path.join(BASE_DIR, "template_oss")


def _is_oss_configured() -> bool:
    """检查 OSS 是否已配置可用。"""
    try:
        cfg = OssService._load_env_config()
        endpoint = OssService._get_value(cfg, "OSS_ENDPOINT")
        bucket = OssService._get_value(cfg, "OSS_BUCKET")
        key_id = OssService._get_value(cfg, "OSS_ACCESS_KEY_ID")
        key_secret = OssService._get_value(cfg, "OSS_ACCESS_KEY_SECRET")
        return bool(endpoint and bucket and key_id and key_secret)
    except Exception:
        return False


def _build_template_object_key(
    category_key: str, template_key: str, version: int, ext: str
) -> str:
    """构建模板文件的 OSS object_key 或本地相对路径。"""
    return f"templates/{category_key}/{template_key}_v{version}.{ext}"


def _build_cover_object_key(category_key: str, template_key: str, ext: str) -> str:
    """构建封面图的 OSS object_key 或本地相对路径。"""
    return f"templates/{category_key}/{template_key}_cover.{ext}"


def _upload_file_to_storage(
    file_content: bytes, object_key: str, file_name: str
) -> str:
    """上传文件到 OSS 或本地存储，返回存储路径。"""
    if _is_oss_configured():
        temp_path = os.path.join(_TEMPLATE_OSS_DIR, f"_upload_{uuid.uuid4().hex[:8]}")
        try:
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            with open(temp_path, "wb") as f:
                f.write(file_content)
            OssService.upload_file(temp_path, object_key)
            return object_key
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    else:
        local_path = os.path.join(_TEMPLATE_OSS_DIR, object_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_content)
        return object_key


def _get_file_url(object_key: str) -> str:
    """根据存储模式返回文件访问 URL。"""
    if _is_oss_configured():
        try:
            return OssService.generate_presigned_get_url(object_key, expires=600)
        except Exception as e:
            logger.error("生成 OSS presigned URL 失败: {}", e)
            return object_key
    return object_key


def _validate_style_config(style_config_str: str) -> Optional[str]:
    """校验报告模板的 style_config JSON 格式，返回校验后的 JSON 字符串或错误信息。"""
    try:
        config = json.loads(style_config_str)
    except (json.JSONDecodeError, TypeError) as e:
        return f"style_config 不是有效的 JSON: {e}"

    if not isinstance(config, dict):
        return "style_config 必须是 JSON 对象"

    required_keys = {"DOCX_STYLE", "TABLE_STYLE", "IMG_STYLE"}
    missing = required_keys - set(config.keys())
    if missing:
        return f"style_config 缺少必要字段: {', '.join(missing)}"

    return None


def get_categories() -> list[dict]:
    """获取模板分类列表，含每个分类的模板数量。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        cursor.execute(
            "SELECT c.id, c.category_key, c.category_name, c.description, c.sort_order, "
            "  (SELECT COUNT(*) FROM tpl_templates t "
            "   WHERE t.category_id = c.id AND t.deleted_at IS NULL AND t.is_active = 1) AS template_count "
            "FROM tpl_categories c ORDER BY c.sort_order"
        )
        return list(cursor.fetchall() or [])


def list_templates(
    category_key: str = "",
    keyword: str = "",
    is_active: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页获取模板列表。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"total": 0, "items": []}

        conditions = ["t.deleted_at IS NULL"]
        params: list = []

        if category_key:
            conditions.append("c.category_key = %s")
            params.append(category_key)

        if keyword:
            conditions.append(
                "(t.template_name LIKE %s OR t.template_key LIKE %s OR t.description LIKE %s)"
            )
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        if is_active is not None:
            conditions.append("t.is_active = %s")
            params.append(is_active)

        where = " AND ".join(conditions)

        cursor.execute(
            f"SELECT COUNT(*) AS total FROM tpl_templates t "
            f"JOIN tpl_categories c ON t.category_id = c.id WHERE {where}",
            params,
        )
        total = cursor.fetchone()["total"]

        offset = (page - 1) * page_size
        cursor.execute(
            f"SELECT t.id, t.template_key, t.template_name, t.template_type, t.description, "
            f"  t.cover_url, t.file_url, t.file_name, t.file_size, t.file_type, "
            f"  t.version, t.is_active, t.sort_order, t.created_by, t.created_at, t.updated_at, "
            f"  c.category_key, c.category_name "
            f"FROM tpl_templates t "
            f"JOIN tpl_categories c ON t.category_id = c.id "
            f"WHERE {where} "
            f"ORDER BY c.sort_order, t.sort_order, t.created_at DESC "
            f"LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        items = list(cursor.fetchall() or [])

        for item in items:
            if item.get("file_url") and not item["file_url"].startswith("http"):
                item["file_download_url"] = _get_file_url(item["file_url"])
            if item.get("cover_url") and not item["cover_url"].startswith("http"):
                item["cover_download_url"] = _get_file_url(item["cover_url"])

        return {"total": total, "items": items}


def get_template(template_id: str) -> Optional[dict]:
    """获取模板详情。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return None

        cursor.execute(
            "SELECT t.*, c.category_key, c.category_name "
            "FROM tpl_templates t "
            "JOIN tpl_categories c ON t.category_id = c.id "
            "WHERE t.id = %s AND t.deleted_at IS NULL",
            (template_id,),
        )
        item = cursor.fetchone()
        if not item:
            return None

        if item.get("file_url") and not item["file_url"].startswith("http"):
            item["file_download_url"] = _get_file_url(item["file_url"])
        if item.get("cover_url") and not item["cover_url"].startswith("http"):
            item["cover_download_url"] = _get_file_url(item["cover_url"])

        return item


def create_template(
    category_key: str,
    template_key: str,
    template_name: str,
    file_content: bytes,
    file_name: str,
    template_type: str = "",
    description: str = "",
    style_config: str = "",
    sort_order: int = 0,
    created_by: str = "",
    cover_content: Optional[bytes] = None,
    cover_file_name: Optional[str] = None,
) -> dict:
    """创建模板，上传文件到 OSS/本地存储。"""
    if style_config:
        error = _validate_style_config(style_config)
        if error:
            return {"success": False, "error": error}

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "SELECT id, category_key FROM tpl_categories WHERE category_key = %s",
            (category_key,),
        )
        category = cursor.fetchone()
        if not category:
            return {"success": False, "error": f"分类 '{category_key}' 不存在"}

        cursor.execute(
            "SELECT id FROM tpl_templates WHERE template_key = %s AND deleted_at IS NULL",
            (template_key,),
        )
        if cursor.fetchone():
            return {"success": False, "error": f"模板标识 '{template_key}' 已存在"}

        category_id = category["id"]
        template_id = str(uuid.uuid4())

        ext = os.path.splitext(file_name)[1].lstrip(".") or "bin"
        object_key = _build_template_object_key(category_key, template_key, 1, ext)

        try:
            file_url = _upload_file_to_storage(file_content, object_key, file_name)
        except Exception as e:
            logger.error("上传模板文件失败: {}", e)
            return {"success": False, "error": f"上传模板文件失败: {e}"}

        cover_url = None
        if cover_content and cover_file_name:
            cover_ext = os.path.splitext(cover_file_name)[1].lstrip(".") or "png"
            cover_key = _build_cover_object_key(category_key, template_key, cover_ext)
            try:
                cover_url = _upload_file_to_storage(
                    cover_content, cover_key, cover_file_name
                )
            except Exception as e:
                logger.error("上传封面图失败: {}", e)

        cursor.execute(
            "INSERT INTO tpl_templates "
            "(id, category_id, template_key, template_name, template_type, description, "
            " cover_url, file_url, file_name, file_size, file_type, style_config, "
            " version, is_active, sort_order, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                template_id,
                category_id,
                template_key,
                template_name,
                template_type,
                description,
                cover_url,
                file_url,
                file_name,
                len(file_content),
                ext,
                style_config if style_config else None,
                1,
                1,
                sort_order,
                created_by,
            ),
        )
        conn.commit()

        return {"success": True, "id": template_id, "template_key": template_key}


def update_template(template_id: str, **kwargs) -> dict:
    """更新模板元信息（名称、描述、样式配置、启用状态等）。"""
    allowed_fields = {
        "template_name",
        "template_type",
        "description",
        "style_config",
        "is_active",
        "sort_order",
    }
    updates = {}
    params = []

    for field in allowed_fields:
        if field in kwargs and kwargs[field] is not None:
            if field == "style_config" and kwargs[field]:
                error = _validate_style_config(kwargs[field])
                if error:
                    return {"success": False, "error": error}
            updates[field] = kwargs[field]
            params.append(kwargs[field])

    if not updates:
        return {"success": False, "error": "没有可更新的字段"}

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params.append(template_id)

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            f"UPDATE tpl_templates SET {set_clause} WHERE id = %s AND deleted_at IS NULL",
            params,
        )
        conn.commit()

        if cursor.rowcount == 0:
            return {"success": False, "error": "模板不存在或已删除"}

        return {"success": True}


def update_template_file(
    template_id: str,
    file_content: bytes,
    file_name: str,
) -> dict:
    """更新模板文件，版本号自增。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "SELECT t.id, t.template_key, t.version, c.category_key "
            "FROM tpl_templates t "
            "JOIN tpl_categories c ON t.category_id = c.id "
            "WHERE t.id = %s AND t.deleted_at IS NULL",
            (template_id,),
        )
        template = cursor.fetchone()
        if not template:
            return {"success": False, "error": "模板不存在或已删除"}

        new_version = template["version"] + 1
        ext = os.path.splitext(file_name)[1].lstrip(".") or "bin"
        object_key = _build_template_object_key(
            template["category_key"], template["template_key"], new_version, ext
        )

        try:
            file_url = _upload_file_to_storage(file_content, object_key, file_name)
        except Exception as e:
            logger.error("上传模板文件失败: {}", e)
            return {"success": False, "error": f"上传模板文件失败: {e}"}

        cursor.execute(
            "UPDATE tpl_templates SET file_url = %s, file_name = %s, "
            "file_size = %s, file_type = %s, version = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (file_url, file_name, len(file_content), ext, new_version, template_id),
        )
        conn.commit()

        return {"success": True, "file_url": file_url, "version": new_version}


def update_template_cover(
    template_id: str,
    cover_content: bytes,
    cover_file_name: str,
) -> dict:
    """单独更新模板封面图。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "SELECT t.id, t.template_key, c.category_key "
            "FROM tpl_templates t "
            "JOIN tpl_categories c ON t.category_id = c.id "
            "WHERE t.id = %s AND t.deleted_at IS NULL",
            (template_id,),
        )
        template = cursor.fetchone()
        if not template:
            return {"success": False, "error": "模板不存在或已删除"}

        cover_ext = os.path.splitext(cover_file_name)[1].lstrip(".") or "png"
        cover_key = _build_cover_object_key(
            template["category_key"], template["template_key"], cover_ext
        )

        try:
            cover_url = _upload_file_to_storage(
                cover_content, cover_key, cover_file_name
            )
        except Exception as e:
            logger.error("上传封面图失败: {}", e)
            return {"success": False, "error": f"上传封面图失败: {e}"}

        cursor.execute(
            "UPDATE tpl_templates SET cover_url = %s WHERE id = %s AND deleted_at IS NULL",
            (cover_url, template_id),
        )
        conn.commit()

        return {"success": True, "cover_url": cover_url}


def delete_template(template_id: str) -> dict:
    """软删除模板。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "UPDATE tpl_templates SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL",
            (template_id,),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return {"success": False, "error": "模板不存在或已删除"}

        return {"success": True}


def batch_toggle_templates(ids: list[str], is_active: int) -> dict:
    """批量启用/禁用模板。"""
    if not ids:
        return {"success": False, "error": "ids 不能为空"}

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        placeholders = ", ".join(["%s"] * len(ids))
        cursor.execute(
            f"UPDATE tpl_templates SET is_active = %s "
            f"WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            [is_active] + ids,
        )
        conn.commit()

        return {"success": True, "affected": cursor.rowcount}


def batch_delete_templates(ids: list[str]) -> dict:
    """批量软删除模板。"""
    if not ids:
        return {"success": False, "error": "ids 不能为空"}

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        placeholders = ", ".join(["%s"] * len(ids))
        cursor.execute(
            f"UPDATE tpl_templates SET deleted_at = NOW() "
            f"WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            ids,
        )
        conn.commit()

        return {"success": True, "affected": cursor.rowcount}


def batch_sort_templates(items: list[dict]) -> dict:
    """批量更新模板排序。"""
    if not items:
        return {"success": False, "error": "items 不能为空"}

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        for item in items:
            cursor.execute(
                "UPDATE tpl_templates SET sort_order = %s "
                "WHERE id = %s AND deleted_at IS NULL",
                (item.get("sort_order", 0), item.get("id")),
            )
        conn.commit()

        return {"success": True, "affected": len(items)}


def get_runtime_templates(
    category_key: str = "", include_download_urls: bool = True
) -> list[dict]:
    """获取运行时模板列表（所有启用的模板，供桌面端/技能使用）。

    Args:
        category_key: 按分类筛选，空字符串表示全部。
        include_download_urls: 是否生成 file_download_url / cover_download_url。
            设为 False 可避免 OSS 签名 URL 生成的网络开销，适用于仅展示列表的场景。
    """
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []

        if category_key:
            cursor.execute(
                "SELECT t.template_key, t.template_name, t.template_type, t.description, "
                "  t.cover_url, t.file_url, t.file_name, t.file_size, t.file_type, "
                "  t.style_config, t.version, t.is_active, t.updated_at, "
                "  c.category_key, c.category_name "
                "FROM tpl_templates t "
                "JOIN tpl_categories c ON t.category_id = c.id "
                "WHERE t.is_active = 1 AND t.deleted_at IS NULL AND c.category_key = %s "
                "ORDER BY t.sort_order",
                (category_key,),
            )
        else:
            cursor.execute(
                "SELECT t.template_key, t.template_name, t.template_type, t.description, "
                "  t.cover_url, t.file_url, t.file_name, t.file_size, t.file_type, "
                "  t.style_config, t.version, t.is_active, t.updated_at, "
                "  c.category_key, c.category_name "
                "FROM tpl_templates t "
                "JOIN tpl_categories c ON t.category_id = c.id "
                "WHERE t.is_active = 1 AND t.deleted_at IS NULL "
                "ORDER BY c.sort_order, t.sort_order"
            )

        items = list(cursor.fetchall() or [])
        if include_download_urls:
            for item in items:
                if item.get("file_url") and not item["file_url"].startswith("http"):
                    item["file_download_url"] = _get_file_url(item["file_url"])
                if item.get("cover_url") and not item["cover_url"].startswith("http"):
                    item["cover_download_url"] = _get_file_url(item["cover_url"])
        return items


def get_runtime_template_by_key(template_key: str) -> Optional[dict]:
    """按 template_key 获取运行时模板详情。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return None

        cursor.execute(
            "SELECT t.*, c.category_key, c.category_name "
            "FROM tpl_templates t "
            "JOIN tpl_categories c ON t.category_id = c.id "
            "WHERE t.template_key = %s AND t.is_active = 1 AND t.deleted_at IS NULL",
            (template_key,),
        )
        item = cursor.fetchone()
        if not item:
            return None

        if item.get("file_url") and not item["file_url"].startswith("http"):
            item["file_download_url"] = _get_file_url(item["file_url"])
        if item.get("cover_url") and not item["cover_url"].startswith("http"):
            item["cover_download_url"] = _get_file_url(item["cover_url"])
        return item


def resolve_template_by_type(template_type: str, category: str = "") -> Optional[dict]:
    """按旧 template_type 兼容查询模板。"""
    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return None

        if category:
            cursor.execute(
                "SELECT t.template_key, t.template_name, t.template_type, "
                "  t.file_url, t.file_type, t.style_config, t.version, "
                "  c.category_key "
                "FROM tpl_templates t "
                "JOIN tpl_categories c ON t.category_id = c.id "
                "WHERE t.template_type = %s AND c.category_key = %s "
                "AND t.is_active = 1 AND t.deleted_at IS NULL "
                "LIMIT 1",
                (template_type, category),
            )
        else:
            cursor.execute(
                "SELECT t.template_key, t.template_name, t.template_type, "
                "  t.file_url, t.file_type, t.style_config, t.version, "
                "  c.category_key "
                "FROM tpl_templates t "
                "JOIN tpl_categories c ON t.category_id = c.id "
                "WHERE t.template_type = %s "
                "AND t.is_active = 1 AND t.deleted_at IS NULL "
                "LIMIT 1",
                (template_type,),
            )

        item = cursor.fetchone()
        if not item:
            return None

        if item.get("file_url") and not item["file_url"].startswith("http"):
            item["file_download_url"] = _get_file_url(item["file_url"])
        return item
