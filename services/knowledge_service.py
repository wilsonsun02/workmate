"""知识库业务逻辑：分类管理、文件管理、摘要生成。

存储层：MySQL 数据库（kb_categories + kb_files 表）。
多用户隔离：通过 username 字段区分不同用户的知识库数据。
知识库类型：通过 kb_type 区分 personal（个人）和 company（公司）。
  - personal: 绑定特定用户，username 为实际用户名
  - company: 公司级共享知识库，username 统一为 '__company__'
"""

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from workflow.config import BASE_DIR

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".doc",
    ".ppt",
    ".pptx",
    ".csv",
    ".xls",
    ".xlsx",
}

COMPANY_USERNAME = "__company__"

_tables_initialized = False


def _resolve_username(username: str = "") -> str:
    """解析当前操作用户名，优先级：参数 > 环境变量 > default。"""
    u = str(username or "").strip()
    if u:
        return u
    for key in ("WORKMATE_DESKTOP_ACTIVE_USERNAME", "AGENT_USERNAME", "USERNAME"):
        env_u = os.environ.get(key, "").strip()
        if env_u:
            return env_u
    return "default"


def _resolve_kb_username(kb_type: str, username: str = "") -> str:
    """根据知识库类型解析 username。

    公司知识库统一使用 __company__ 作为 username，
    个人知识库使用实际用户名。
    """
    if kb_type == "company":
        return COMPANY_USERNAME
    return _resolve_username(username)


def _ensure_tables():
    """延迟初始化知识库数据库表（仅执行一次）。"""
    global _tables_initialized
    if _tables_initialized:
        return
    try:
        from admin_api.models.init_db import init_knowledge_tables

        init_knowledge_tables()
        _tables_initialized = True
    except Exception as e:
        logger.error("知识库表初始化失败: {}", e)


def _safe_filename(name: str) -> str:
    """将分类名称转为安全的目录名，过滤非法字符。"""
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name or "unnamed"


def _get_doc_reader():
    """延迟初始化 DocumentReader，避免启动时的循环导入问题。"""
    from mcp_filesystem.security import PathValidator
    from mcp_filesystem.doc_reader import DocumentReader

    temp_dir = os.path.join(BASE_DIR, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    validator = PathValidator([temp_dir])
    return DocumentReader(validator)


_MIN_SUMMARY_CONTENT_LEN = 500


async def _generate_summary(content: str) -> str:
    """使用 LLM 生成文档结构化索引摘要。

    防幻觉策略：
    1. 内容过短（<100字符）时直接返回原文，不调用 LLM，避免模型编造内容
    2. Prompt 中明确要求仅基于文档实际内容生成摘要，严禁编造
    3. 使用轻量 text_llm 替代主模型 mcp_llm，降低成本
    """
    stripped = content.strip()
    if len(stripped) < _MIN_SUMMARY_CONTENT_LEN:
        logger.info(f"文档内容过短({len(stripped)}字符)，跳过LLM摘要生成，直接返回原文")
        return stripped

    try:
        from workflow.model import create_text_llm_instance
        from langchain_core.messages import HumanMessage

        text_llm = create_text_llm_instance()
        prompt = (
            "请为以下文档生成一个结构化的内容索引，用于知识库检索和摘录。\n\n"
            "【重要约束】\n"
            "- 你必须且仅基于下方提供的文档实际内容生成摘要，严禁编造、推测或补充文档中不存在的任何信息\n"
            "- 如果文档内容不足以生成完整的结构化索引，请如实说明内容不足，不要虚构章节或关键词\n"
            "- 概述和索引中的每一项都必须能在原文中找到对应依据\n\n"
            "要求：\n"
            "1. 【文档概述】：用50-80字概括文档整体主题和类型\n"
            "2. 【内容索引】：按文档的实际结构（段落/章节），列出各部分的核心内容描述，"
            "格式为 '## 标题：内容简述'\n"
            "3. 【关键词】：提取5-10个核心关键词\n"
            "4. 如果文档包含'Page N'标记，请忽略页码标记，按实际内容组织索引\n\n"
            f"文档内容：\n{content}\n\n"
            "请直接输出索引内容，无需额外说明："
        )
        response = await text_llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        logger.error(f"生成摘要失败: {e}")
        if len(content) > 200:
            return content[:200] + "..."
        return content


async def _convert_file_to_md(file_path: str) -> str:
    """调用 DocumentReader 将文件转为 Markdown。"""
    doc_reader = _get_doc_reader()
    return await doc_reader.read_to_markdown(file_path)


async def _convert_url_to_md(url: str) -> str:
    """将 URL 网页转为 Markdown。"""
    import shutil
    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="kb_url_")
    pdf_path = os.path.join(temp_dir, "temp_page.pdf")
    try:
        try:
            pdf_path = await _html_to_pdf(url, pdf_path)
        except ImportError:
            logger.info("Playwright 未安装，使用 requests 抓取网页文本")
            return await _fetch_url_text(url)

        md_content = await _convert_file_to_md(pdf_path)
        return md_content
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except OSError:
            pass


async def _fetch_url_text(url: str) -> str:
    """使用 requests + BeautifulSoup 抓取网页纯文本内容。"""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return (
            "Error: URL转换需要安装 playwright 或 requests+beautifulsoup4。\n"
            "请运行: pip install playwright requests beautifulsoup4 && playwright install chromium"
        )

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else url
        body = soup.body
        text = body.get_text(separator="\n", strip=True) if body else resp.text

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n\n".join(lines)

        return f"# {title}\n\n来源：{url}\n\n{text}"
    except Exception as e:
        logger.error(f"URL文本抓取失败: {e}")
        return f"Error: URL抓取失败 - {str(e)}"


async def _html_to_pdf(url: str, pdf_path: str) -> str:
    """使用 Playwright 将网页渲染并保存为 PDF。"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(executor, _html_to_pdf_sync, url, pdf_path)


def _html_to_pdf_sync(url: str, pdf_path: str) -> str:
    """同步版本的网页转 PDF。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "URL转换需要安装 playwright: pip install playwright && playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle")

        last_height = page.evaluate("document.documentElement.scrollHeight")
        scroll_count = 0
        while scroll_count < 4:
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(2000)
            new_height = page.evaluate("document.documentElement.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_count += 1

        page.emulate_media(media="print")
        content_width = page.evaluate("document.documentElement.scrollWidth") + 100
        page.pdf(path=pdf_path, width=f"{content_width}px")
        browser.close()

    return pdf_path


def get_categories(kb_type: str = "personal", username: str = "") -> list[dict]:
    """获取分类列表。

    Args:
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            cursor.execute(
                "SELECT c.id, c.name, c.display_name, c.kb_type, c.username, c.created_at, "
                "(SELECT COUNT(*) FROM kb_files f WHERE f.category_id = c.id) AS file_count "
                "FROM kb_categories c WHERE c.username = %s AND c.kb_type = %s ORDER BY c.created_at",
                (uname, kb_type),
            )
            rows = cursor.fetchall()
            categories = []
            for row in rows:
                categories.append(
                    {
                        "name": row["name"],
                        "display_name": row["display_name"],
                        "kb_type": row["kb_type"],
                        "username": row["username"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else "",
                        "file_count": row["file_count"],
                    }
                )
            return categories
        except Exception as e:
            logger.error(f"获取分类列表失败: {e}")
            return []


def create_category(name: str, kb_type: str = "personal", username: str = "") -> dict:
    """创建新的主题分类。

    Args:
        name: 分类名称
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    safe_name = _safe_filename(name)
    if not safe_name:
        return {"success": False, "error": "分类名称不能为空"}

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            cursor.execute(
                "SELECT id FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
                (uname, kb_type, safe_name),
            )
            if cursor.fetchone():
                return {"success": False, "error": f"分类 '{safe_name}' 已存在"}

            cat_id = uuid.uuid4().hex
            cursor.execute(
                "INSERT INTO kb_categories (id, username, kb_type, name, display_name) VALUES (%s, %s, %s, %s, %s)",
                (cat_id, uname, kb_type, safe_name, name.strip()),
            )
            conn.commit()

            cursor.execute(
                "SELECT created_at FROM kb_categories WHERE id = %s",
                (cat_id,),
            )
            row = cursor.fetchone()
            created_at = (
                row["created_at"].isoformat() if row and row["created_at"] else ""
            )

            logger.info(f"创建知识库分类: {uname}/{kb_type}/{safe_name}")
            return {
                "success": True,
                "name": safe_name,
                "display_name": name.strip(),
                "kb_type": kb_type,
                "created_at": created_at,
            }
        except Exception as e:
            logger.error(f"创建分类失败: {e}")
            return {"success": False, "error": str(e)}


def delete_category(name: str, kb_type: str = "personal", username: str = "") -> dict:
    """删除主题分类及其所有文件（CASCADE 自动删除关联文件）。

    Args:
        name: 分类名称
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    safe_name = _safe_filename(name)

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor() as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            cursor.execute(
                "SELECT id FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
                (uname, kb_type, safe_name),
            )
            if not cursor.fetchone():
                return {"success": False, "error": f"分类 '{safe_name}' 不存在"}

            cursor.execute(
                "DELETE FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
                (uname, kb_type, safe_name),
            )
            conn.commit()

            logger.info(f"删除知识库分类: {uname}/{kb_type}/{safe_name}")
            return {"success": True, "name": safe_name}
        except Exception as e:
            logger.error(f"删除分类失败: {e}")
            return {"success": False, "error": str(e)}


def rename_category(
    old_name: str,
    new_display_name: str,
    kb_type: str = "personal",
    username: str = "",
) -> dict:
    """重命名知识库分类（修改 display_name，name 保持不变）。

    Args:
        old_name: 分类安全名称（name 字段，不可变）
        new_display_name: 新的显示名称
        kb_type: 知识库类型
        username: 用户名
    """
    safe_old = _safe_filename(old_name)
    new_display_name = new_display_name.strip()
    if not new_display_name:
        return {"success": False, "error": "新名称不能为空"}

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            # 检查分类是否存在
            cursor.execute(
                "SELECT id FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
                (uname, kb_type, safe_old),
            )
            if not cursor.fetchone():
                return {"success": False, "error": f"分类 '{safe_old}' 不存在"}

            # 更新 display_name
            cursor.execute(
                "UPDATE kb_categories SET display_name = %s WHERE username = %s AND kb_type = %s AND name = %s",
                (new_display_name, uname, kb_type, safe_old),
            )
            conn.commit()

            logger.info(
                f"重命名知识库分类: {uname}/{kb_type}/{safe_old} -> {new_display_name}"
            )
            return {"success": True, "name": safe_old, "display_name": new_display_name}
        except Exception as e:
            logger.error(f"重命名分类失败: {e}")
            return {"success": False, "error": str(e)}


def get_files(
    category: Optional[str] = None, kb_type: str = "personal", username: str = ""
) -> list[dict]:
    """获取文件列表。

    Args:
        category: 分类名称，为空则返回所有
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            if category:
                cursor.execute(
                    "SELECT id, category_name AS category, original_filename, md_filename, "
                    "file_type, file_size, summary, kb_type, created_at, updated_at "
                    "FROM kb_files WHERE username = %s AND kb_type = %s AND category_name = %s "
                    "ORDER BY created_at",
                    (uname, kb_type, category),
                )
            else:
                cursor.execute(
                    "SELECT id, category_name AS category, original_filename, md_filename, "
                    "file_type, file_size, summary, kb_type, created_at, updated_at "
                    "FROM kb_files WHERE username = %s AND kb_type = %s ORDER BY created_at",
                    (uname, kb_type),
                )
            rows = cursor.fetchall()
            files = []
            for row in rows:
                files.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "original_filename": row["original_filename"],
                        "md_filename": row["md_filename"],
                        "file_type": row["file_type"],
                        "file_size": row["file_size"],
                        "summary": row["summary"] or "",
                        "kb_type": row["kb_type"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else "",
                        "updated_at": row["updated_at"].isoformat()
                        if row["updated_at"]
                        else "",
                    }
                )
            return files
        except Exception as e:
            logger.error(f"获取文件列表失败: {e}")
            return []


async def upload_file(
    file_content: bytes,
    filename: str,
    category: str,
    kb_type: str = "personal",
    username: str = "",
) -> dict:
    """上传文件并转换为 Markdown，存储到数据库。

    Args:
        file_content: 文件原始字节内容
        filename: 原始文件名
        category: 所属分类名称
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    safe_category = _safe_filename(category)

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "SELECT id FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
            (uname, kb_type, safe_category),
        )
        cat_row = cursor.fetchone()
        if not cat_row:
            return {
                "success": False,
                "error": f"分类 '{safe_category}' 不存在，请先创建",
            }
        category_id = cat_row["id"]

    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS and ext not in (".url",):
        return {"success": False, "error": f"不支持的文件类型: {ext}"}

    temp_dir = os.path.join(BASE_DIR, "temp", "kb_upload")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, filename)
    with open(temp_path, "wb") as f:
        f.write(file_content)

    try:
        if ext == ".md":
            md_content = file_content.decode("utf-8", errors="replace")
        else:
            md_content = await _convert_file_to_md(temp_path)

        summary = await _generate_summary(md_content)

        file_id = uuid.uuid4().hex
        md_filename = os.path.splitext(filename)[0] + ".md"
        now = datetime.now().isoformat()
        file_info = {
            "id": file_id,
            "category": safe_category,
            "original_filename": filename,
            "md_filename": md_filename,
            "file_type": ext.lstrip("."),
            "file_size": len(file_content),
            "summary": summary,
            "created_at": now,
            "updated_at": now,
        }

        with db_cursor() as (conn, cursor):
            if not conn:
                return {"success": False, "error": "数据库连接失败"}
            cursor.execute(
                "INSERT INTO kb_files "
                "(id, username, kb_type, category_id, category_name, original_filename, md_filename, "
                "file_type, file_size, summary, md_content, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    file_id,
                    uname,
                    kb_type,
                    category_id,
                    safe_category,
                    filename,
                    md_filename,
                    ext.lstrip("."),
                    len(file_content),
                    summary,
                    md_content,
                    now,
                    now,
                ),
            )
            conn.commit()

        logger.info(
            f"知识库文件上传成功: {uname}/{kb_type}/{safe_category}/{md_filename}"
        )
        return {"success": True, "file": file_info}

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


async def add_url(
    url: str, category: str, kb_type: str = "personal", username: str = ""
) -> dict:
    """添加 URL 网页到知识库，存储到数据库。

    Args:
        url: 网页 URL
        category: 所属分类名称
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    safe_category = _safe_filename(category)

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}

        cursor.execute(
            "SELECT id FROM kb_categories WHERE username = %s AND kb_type = %s AND name = %s",
            (uname, kb_type, safe_category),
        )
        cat_row = cursor.fetchone()
        if not cat_row:
            return {
                "success": False,
                "error": f"分类 '{safe_category}' 不存在，请先创建",
            }
        category_id = cat_row["id"]

    logger.info(f"开始转换URL: {url}")

    md_content = await _convert_url_to_md(url)

    if not md_content or md_content.startswith("Error"):
        return {"success": False, "error": f"URL转换失败: {md_content}"}

    title_match = re.match(r"^#\s+(.+)$", md_content.strip(), re.MULTILINE)
    if title_match:
        page_title = title_match.group(1).strip()
        safe_title = re.sub(r'[\\/:*?"<>|\n\r]', "_", page_title)
        safe_title = safe_title[:60].strip()
    else:
        safe_title = re.sub(
            r"[^\w\-]", "_", url.split("//")[-1].split("/")[0] or "webpage"
        )[:30]

    random_suffix = uuid.uuid4().hex[:4]
    md_filename = f"{safe_title}_{random_suffix}.md"

    summary = await _generate_summary(md_content)

    file_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    file_info = {
        "id": file_id,
        "category": safe_category,
        "original_filename": safe_title,
        "md_filename": md_filename,
        "file_type": "url",
        "file_size": len(md_content.encode("utf-8")),
        "summary": summary,
        "created_at": now,
        "updated_at": now,
    }

    with db_cursor() as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        cursor.execute(
            "INSERT INTO kb_files "
            "(id, username, kb_type, category_id, category_name, original_filename, md_filename, "
            "file_type, file_size, summary, md_content, source_url, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                file_id,
                uname,
                kb_type,
                category_id,
                safe_category,
                safe_title,
                md_filename,
                "url",
                len(md_content.encode("utf-8")),
                summary,
                md_content,
                url,
                now,
                now,
            ),
        )
        conn.commit()

    logger.info(f"URL知识库添加成功: {uname}/{kb_type}/{safe_category}/{md_filename}")
    return {"success": True, "file": file_info}


def get_file_content(
    file_id: str, kb_type: str = "personal", username: str = ""
) -> dict:
    """获取文件内容。

    Args:
        file_id: 文件ID
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            cursor.execute(
                "SELECT id, category_name AS category, original_filename, md_filename, "
                "file_type, file_size, summary, md_content, source_url, kb_type, created_at, updated_at "
                "FROM kb_files WHERE id = %s AND username = %s AND kb_type = %s",
                (file_id, uname, kb_type),
            )
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "文件ID不存在"}

            file_info = {
                "id": row["id"],
                "category": row["category"],
                "original_filename": row["original_filename"],
                "md_filename": row["md_filename"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
                "summary": row["summary"] or "",
                "kb_type": row["kb_type"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else "",
                "updated_at": row["updated_at"].isoformat()
                if row["updated_at"]
                else "",
            }
            return {
                "success": True,
                "file": file_info,
                "content": row["md_content"],
            }
        except Exception as e:
            logger.error(f"获取文件内容失败: {e}")
            return {"success": False, "error": str(e)}


def update_file_content(
    file_id: str, content: str, kb_type: str = "personal", username: str = ""
) -> dict:
    """编辑文件内容并更新数据库。

    Args:
        file_id: 文件ID
        content: 新的 Markdown 内容
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            cursor.execute(
                "SELECT id FROM kb_files WHERE id = %s AND username = %s AND kb_type = %s",
                (file_id, uname, kb_type),
            )
            if not cursor.fetchone():
                return {"success": False, "error": "文件ID不存在"}

            now = datetime.now().isoformat()
            cursor.execute(
                "UPDATE kb_files SET md_content = %s, file_size = %s, updated_at = %s "
                "WHERE id = %s AND username = %s AND kb_type = %s",
                (content, len(content.encode("utf-8")), now, file_id, uname, kb_type),
            )
            conn.commit()

            cursor.execute(
                "SELECT id, category_name AS category, original_filename, md_filename, "
                "file_type, file_size, summary, kb_type, created_at, updated_at "
                "FROM kb_files WHERE id = %s",
                (file_id,),
            )
            row = cursor.fetchone()
            file_info = {
                "id": row["id"],
                "category": row["category"],
                "original_filename": row["original_filename"],
                "md_filename": row["md_filename"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
                "summary": row["summary"] or "",
                "kb_type": row["kb_type"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else "",
                "updated_at": row["updated_at"].isoformat()
                if row["updated_at"]
                else "",
            }

            logger.info(
                f"知识库文件编辑成功: {uname}/{kb_type}/{row['category']}/{row['md_filename']}"
            )
            return {"success": True, "file": file_info}
        except Exception as e:
            logger.error(f"编辑文件失败: {e}")
            return {"success": False, "error": str(e)}


async def update_file_and_summary(
    file_id: str, content: str, kb_type: str = "personal", username: str = ""
) -> dict:
    """编辑文件内容并重新生成摘要。

    Args:
        file_id: 文件ID
        content: 新的 Markdown 内容
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    result = update_file_content(file_id, content, kb_type=kb_type, username=username)
    if not result["success"]:
        return result

    new_summary = await _generate_summary(content)

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor() as (conn, cursor):
        if not conn:
            return result
        try:
            cursor.execute(
                "UPDATE kb_files SET summary = %s WHERE id = %s AND username = %s AND kb_type = %s",
                (new_summary, file_id, uname, kb_type),
            )
            conn.commit()
            result["file"]["summary"] = new_summary
        except Exception as e:
            logger.error(f"更新摘要失败: {e}")

    return result


def delete_file(file_id: str, kb_type: str = "personal", username: str = "") -> dict:
    """删除文件。

    Args:
        file_id: 文件ID
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            cursor.execute(
                "SELECT id, category_name FROM kb_files WHERE id = %s AND username = %s AND kb_type = %s",
                (file_id, uname, kb_type),
            )
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "文件ID不存在"}

            cursor.execute(
                "DELETE FROM kb_files WHERE id = %s AND username = %s AND kb_type = %s",
                (file_id, uname, kb_type),
            )
            conn.commit()

            logger.info(
                f"知识库文件删除成功: {uname}/{kb_type}/{row['category_name']}/{file_id}"
            )
            return {"success": True, "file_id": file_id}
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            return {"success": False, "error": str(e)}


def search_files(
    query: str,
    category: Optional[str] = None,
    kb_type: str = "personal",
    username: str = "",
) -> list[dict]:
    """根据关键词搜索文件（LIKE 匹配文件名和摘要）。

    Args:
        query: 搜索关键词
        category: 分类名称，为空则搜索所有
        kb_type: 知识库类型，personal 或 company
        username: 用户名，为空则自动获取（company 类型时忽略）
    """
    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            like_pattern = f"%{query}%"
            if category:
                cursor.execute(
                    "SELECT id, category_name AS category, original_filename, md_filename, "
                    "file_type, file_size, summary, kb_type, created_at, updated_at "
                    "FROM kb_files WHERE username = %s AND kb_type = %s AND category_name = %s "
                    "AND (original_filename LIKE %s OR summary LIKE %s OR md_filename LIKE %s) "
                    "ORDER BY updated_at DESC",
                    (
                        uname,
                        kb_type,
                        category,
                        like_pattern,
                        like_pattern,
                        like_pattern,
                    ),
                )
            else:
                cursor.execute(
                    "SELECT id, category_name AS category, original_filename, md_filename, "
                    "file_type, file_size, summary, kb_type, created_at, updated_at "
                    "FROM kb_files WHERE username = %s AND kb_type = %s "
                    "AND (original_filename LIKE %s OR summary LIKE %s OR md_filename LIKE %s) "
                    "ORDER BY updated_at DESC",
                    (uname, kb_type, like_pattern, like_pattern, like_pattern),
                )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "original_filename": row["original_filename"],
                        "md_filename": row["md_filename"],
                        "file_type": row["file_type"],
                        "file_size": row["file_size"],
                        "summary": row["summary"] or "",
                        "kb_type": row["kb_type"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else "",
                        "updated_at": row["updated_at"].isoformat()
                        if row["updated_at"]
                        else "",
                    }
                )
            return results
        except Exception as e:
            logger.error(f"搜索文件失败: {e}")
            return []


# ===== 知识库分享功能 =====


def share_files(
    file_ids: list[str],
    target_username: str,
    owner_username: str = "",
) -> dict:
    """将指定文件分享给目标用户。

    Args:
        file_ids: 要分享的文件ID列表
        target_username: 被分享人用户名
        owner_username: 分享人用户名，为空则自动获取
    """
    if not file_ids:
        return {"success": False, "error": "未选择要分享的文件"}
    if not target_username.strip():
        return {"success": False, "error": "未指定分享目标用户"}

    _ensure_tables()
    uname = _resolve_username(owner_username)
    target = target_username.strip()

    # 不允许分享给自己
    if uname == target:
        return {"success": False, "error": "不能分享给自己"}

    from admin_api.models.init_db import db_cursor

    success_count = 0
    errors = []

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            for file_id in file_ids:
                # 校验文件归属（仅个人知识库文件可分享）
                cursor.execute(
                    "SELECT id, category_name, kb_type FROM kb_files "
                    "WHERE id = %s AND username = %s AND kb_type = 'personal'",
                    (file_id, uname),
                )
                file_row = cursor.fetchone()
                if not file_row:
                    errors.append(f"文件 {file_id} 不存在或不属于您")
                    continue

                # 插入分享记录（忽略重复）
                share_id = uuid.uuid4().hex
                try:
                    cursor.execute(
                        "INSERT INTO kb_shares (id, file_id, owner_username, target_username, category_name) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (share_id, file_id, uname, target, file_row["category_name"]),
                    )
                    success_count += 1
                except Exception as insert_err:
                    # 唯一索引冲突说明已分享过，跳过
                    if "Duplicate" in str(insert_err) or "uk_file_target" in str(
                        insert_err
                    ):
                        errors.append(f"文件 {file_id} 已分享给 {target}")
                    else:
                        errors.append(f"文件 {file_id} 分享失败: {insert_err}")

            conn.commit()
            logger.info(
                f"知识库分享: {uname} -> {target}, 成功 {success_count}/{len(file_ids)}"
            )
            return {
                "success": True,
                "success_count": success_count,
                "total": len(file_ids),
                "errors": errors,
            }
        except Exception as e:
            logger.error(f"分享文件失败: {e}")
            return {"success": False, "error": str(e)}


def get_received_shares(username: str = "") -> list[dict]:
    """获取别人分享给我的文件列表。

    联表查询 kb_shares + kb_files，返回文件详情 + 分享信息。
    """
    _ensure_tables()
    uname = _resolve_username(username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            cursor.execute(
                "SELECT s.id AS share_id, s.owner_username, s.category_name AS share_category, s.created_at AS shared_at, "
                "f.id AS file_id, f.category_name, f.original_filename, f.md_filename, "
                "f.file_type, f.file_size, f.summary, f.kb_type, "
                "f.created_at, f.updated_at "
                "FROM kb_shares s "
                "INNER JOIN kb_files f ON s.file_id = f.id "
                "WHERE s.target_username = %s "
                "ORDER BY s.created_at DESC",
                (uname,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "share_id": row["share_id"],
                        "owner_username": row["owner_username"],
                        "share_category": row["share_category"],
                        "shared_at": row["shared_at"].isoformat()
                        if row["shared_at"]
                        else "",
                        "id": row["file_id"],
                        "category": row["category_name"],
                        "original_filename": row["original_filename"],
                        "md_filename": row["md_filename"],
                        "file_type": row["file_type"],
                        "file_size": row["file_size"],
                        "summary": row["summary"] or "",
                        "kb_type": row["kb_type"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else "",
                        "updated_at": row["updated_at"].isoformat()
                        if row["updated_at"]
                        else "",
                    }
                )
            return results
        except Exception as e:
            logger.error(f"获取收到的分享列表失败: {e}")
            return []


def get_sent_shares(username: str = "") -> list[dict]:
    """获取我分享出去的文件列表，包含每个文件的分享对象。"""
    _ensure_tables()
    uname = _resolve_username(username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return []
        try:
            cursor.execute(
                "SELECT s.id AS share_id, s.target_username, s.category_name AS share_category, s.created_at AS shared_at, "
                "f.id AS file_id, f.category_name, f.original_filename, f.md_filename, "
                "f.file_type, f.file_size, f.summary, f.kb_type, "
                "f.created_at, f.updated_at "
                "FROM kb_shares s "
                "INNER JOIN kb_files f ON s.file_id = f.id "
                "WHERE s.owner_username = %s "
                "ORDER BY s.created_at DESC",
                (uname,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "share_id": row["share_id"],
                        "target_username": row["target_username"],
                        "share_category": row["share_category"],
                        "shared_at": row["shared_at"].isoformat()
                        if row["shared_at"]
                        else "",
                        "id": row["file_id"],
                        "category": row["category_name"],
                        "original_filename": row["original_filename"],
                        "md_filename": row["md_filename"],
                        "file_type": row["file_type"],
                        "file_size": row["file_size"],
                        "summary": row["summary"] or "",
                        "kb_type": row["kb_type"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else "",
                        "updated_at": row["updated_at"].isoformat()
                        if row["updated_at"]
                        else "",
                    }
                )
            return results
        except Exception as e:
            logger.error(f"获取发出的分享列表失败: {e}")
            return []


def cancel_share(share_id: str, owner_username: str = "") -> dict:
    """取消分享（仅分享人可操作）。

    Args:
        share_id: 分享记录ID
        owner_username: 操作人用户名，校验是否为分享人
    """
    _ensure_tables()
    uname = _resolve_username(owner_username)

    from admin_api.models.init_db import db_cursor

    with db_cursor() as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            # 校验分享记录归属
            cursor.execute(
                "SELECT id FROM kb_shares WHERE id = %s AND owner_username = %s",
                (share_id, uname),
            )
            if not cursor.fetchone():
                return {"success": False, "error": "分享记录不存在或无权操作"}

            cursor.execute("DELETE FROM kb_shares WHERE id = %s", (share_id,))
            conn.commit()
            logger.info(f"取消知识库分享: share_id={share_id}, owner={uname}")
            return {"success": True}
        except Exception as e:
            logger.error(f"取消分享失败: {e}")
            return {"success": False, "error": str(e)}


def get_file_share_count(file_id: str) -> int:
    """获取文件被分享的人数。"""
    _ensure_tables()

    from admin_api.models.init_db import db_cursor

    with db_cursor() as (conn, cursor):
        if not conn:
            return 0
        try:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM kb_shares WHERE file_id = %s",
                (file_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0


def get_all_shares(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    owner: str = "",
    target: str = "",
) -> dict:
    """管理端查询全公司分享记录（分页 + 筛选）。

    Returns:
        dict: {success, items, total, page, size}
    """
    _ensure_tables()

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            where_clauses = []
            params = []

            if keyword:
                where_clauses.append(
                    "(f.original_filename LIKE %s OR f.summary LIKE %s)"
                )
                like_kw = f"%{keyword}%"
                params.extend([like_kw, like_kw])
            if owner:
                where_clauses.append("s.owner_username = %s")
                params.append(owner)
            if target:
                where_clauses.append("s.target_username = %s")
                params.append(target)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # 总数
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM kb_shares s "
                f"INNER JOIN kb_files f ON s.file_id = f.id {where_sql}",
                params,
            )
            total = cursor.fetchone()["total"]

            # 分页数据
            offset = (page - 1) * size
            cursor.execute(
                f"SELECT s.id AS share_id, s.owner_username, s.target_username, "
                f"s.category_name AS share_category, s.created_at AS shared_at, "
                f"f.id AS file_id, f.original_filename, f.md_filename, "
                f"f.file_type, f.summary "
                f"FROM kb_shares s "
                f"INNER JOIN kb_files f ON s.file_id = f.id {where_sql} "
                f"ORDER BY s.created_at DESC "
                f"LIMIT %s OFFSET %s",
                params + [size, offset],
            )
            rows = cursor.fetchall()
            items = []
            for row in rows:
                items.append(
                    {
                        "share_id": row["share_id"],
                        "owner_username": row["owner_username"],
                        "target_username": row["target_username"],
                        "share_category": row["share_category"],
                        "shared_at": row["shared_at"].isoformat()
                        if row["shared_at"]
                        else "",
                        "file_id": row["file_id"],
                        "original_filename": row["original_filename"],
                        "md_filename": row["md_filename"],
                        "file_type": row["file_type"],
                        "summary": (row["summary"] or "")[:200],
                    }
                )

            return {
                "success": True,
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            }
        except Exception as e:
            logger.error(f"查询分享记录失败: {e}")
            return {"success": False, "error": str(e)}


def move_file(
    file_id: str,
    target_category: str,
    kb_type: str = "personal",
    username: str = "",
) -> dict:
    """将文件移动到另一个分类。

    Args:
        file_id: 文件ID
        target_category: 目标分类名称
        kb_type: 知识库类型
        username: 操作人用户名
    """
    safe_target = _safe_filename(target_category)
    if not safe_target:
        return {"success": False, "error": "目标分类名称不能为空"}

    _ensure_tables()
    uname = _resolve_kb_username(kb_type, username)

    from admin_api.models.init_db import db_cursor

    with db_cursor(dictionary=True) as (conn, cursor):
        if not conn:
            return {"success": False, "error": "数据库连接失败"}
        try:
            # 校验文件归属
            cursor.execute(
                "SELECT id, category_name FROM kb_files "
                "WHERE id = %s AND username = %s AND kb_type = %s",
                (file_id, uname, kb_type),
            )
            file_row = cursor.fetchone()
            if not file_row:
                return {"success": False, "error": "文件不存在或不属于您"}

            if file_row["category_name"] == safe_target:
                return {"success": False, "error": "文件已在目标分类中"}

            # 校验目标分类存在
            cursor.execute(
                "SELECT id FROM kb_categories "
                "WHERE username = %s AND kb_type = %s AND name = %s",
                (uname, kb_type, safe_target),
            )
            target_cat = cursor.fetchone()
            if not target_cat:
                return {"success": False, "error": f"目标分类 '{safe_target}' 不存在"}

            # 更新文件的分类
            cursor.execute(
                "UPDATE kb_files SET category_id = %s, category_name = %s, "
                "updated_at = %s WHERE id = %s",
                (target_cat["id"], safe_target, datetime.now().isoformat(), file_id),
            )

            # 同步更新分享记录中的分类名
            cursor.execute(
                "UPDATE kb_shares SET category_name = %s WHERE file_id = %s",
                (safe_target, file_id),
            )

            conn.commit()
            logger.info(f"知识库文件移动: {file_id} -> {safe_target}, user={uname}")
            return {"success": True, "file_id": file_id, "target_category": safe_target}
        except Exception as e:
            logger.error(f"移动文件失败: {e}")
            return {"success": False, "error": str(e)}
