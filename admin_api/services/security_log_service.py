"""安全拦截日志服务：将安全拦截事件持久化到数据库，供管理端安全合规页面查询"""

import json
import os
import threading
from typing import Optional

from loguru import logger


# 原始内容最大截取长度，避免大量文本入库
_MAX_RAW_CONTENT_LEN = 500


def insert_intercept_log(
    username: str,
    channel: str,
    intercept_type: str,
    tool_name: str,
    violations: list[str],
    raw_content: str,
    block_message: str,
    mate_name: str = "",
) -> None:
    """异步写入安全拦截日志（fire-and-forget，不阻塞主流程）

    Args:
        username: 操作用户名
        channel: 拦截渠道（wechat / wxwork / unknown）
        intercept_type: 拦截类型（keyword / llm_review）
        tool_name: 触发的工具名
        violations: 违规项列表
        raw_content: 原始内容（将自动截取前500字）
        block_message: 拦截提示消息
        mate_name: 工作伙伴名称
    """
    # 在后台线程中执行写入，避免阻塞主流程
    thread = threading.Thread(
        target=_do_insert,
        args=(
            username,
            channel,
            intercept_type,
            tool_name,
            violations,
            raw_content,
            block_message,
            mate_name,
        ),
        daemon=True,
    )
    thread.start()


def _do_insert(
    username: str,
    channel: str,
    intercept_type: str,
    tool_name: str,
    violations: list[str],
    raw_content: str,
    block_message: str,
    mate_name: str,
) -> None:
    """实际执行数据库写入（在后台线程中运行）"""
    try:
        from admin_api.models.init_db import get_db_connection

        conn = get_db_connection()
        if not conn:
            logger.error("[安全日志] 数据库连接失败，跳过拦截日志写入")
            return

        try:
            cursor = conn.cursor()
            # 原始内容脱敏截取
            truncated_content = (raw_content or "")[:_MAX_RAW_CONTENT_LEN]
            violations_json = json.dumps(violations or [], ensure_ascii=False)

            cursor.execute(
                """INSERT INTO security_intercept_log
                   (username, channel, intercept_type, tool_name, violations, raw_content, block_message, mate_name)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    username,
                    channel,
                    intercept_type,
                    tool_name,
                    violations_json,
                    truncated_content,
                    block_message,
                    mate_name,
                ),
            )
            conn.commit()
            logger.info(
                "[安全日志] 拦截日志已写入: user={}, channel={}, type={}",
                username,
                channel,
                intercept_type,
            )
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    except Exception as e:
        # 日志写入失败不影响主流程，仅记录错误
        logger.error("[安全日志] 写入拦截日志失败: {}", e)


def query_intercept_logs(
    keyword: Optional[str] = None,
    channel: Optional[str] = None,
    intercept_type: Optional[str] = None,
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """分页查询安全拦截日志

    Returns:
        (日志列表, 总数)
    """
    from admin_api.models.init_db import get_db_connection

    conn = get_db_connection()
    if not conn:
        logger.error("[安全日志] 数据库连接失败")
        return [], 0

    try:
        cursor = conn.cursor(dictionary=True)

        # 构建查询条件
        conditions = []
        params = []

        if keyword:
            conditions.append(
                "(username LIKE %s OR violations LIKE %s OR raw_content LIKE %s)"
            )
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        if channel:
            conditions.append("channel = %s")
            params.append(channel)

        if intercept_type:
            conditions.append("intercept_type = %s")
            params.append(intercept_type)

        if username:
            conditions.append("username = %s")
            params.append(username)

        if start_time:
            conditions.append("created_at >= %s")
            params.append(start_time)

        if end_time:
            conditions.append("created_at <= %s")
            params.append(end_time)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # 查询总数
        count_sql = (
            f"SELECT COUNT(*) as total FROM security_intercept_log {where_clause}"
        )
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"]

        # 分页查询
        query_sql = (
            f"SELECT id, username, channel, intercept_type, tool_name, violations, "
            f"raw_content, block_message, mate_name, created_at "
            f"FROM security_intercept_log {where_clause} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s"
        )
        cursor.execute(query_sql, params + [limit, offset])
        rows = cursor.fetchall()

        # 解析 violations JSON
        for row in rows:
            if row.get("violations"):
                try:
                    row["violations"] = json.loads(row["violations"])
                except (json.JSONDecodeError, TypeError):
                    row["violations"] = []
            else:
                row["violations"] = []

        return rows, total

    except Exception as e:
        logger.error("[安全日志] 查询拦截日志失败: {}", e)
        return [], 0
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


def get_intercept_stats() -> dict:
    """获取安全拦截统计概览"""
    from admin_api.models.init_db import get_db_connection

    conn = get_db_connection()
    if not conn:
        logger.error("[安全日志] 数据库连接失败")
        return {"total": 0, "today": 0, "by_channel": [], "by_type": []}

    try:
        cursor = conn.cursor(dictionary=True)

        # 总拦截数
        cursor.execute("SELECT COUNT(*) as total FROM security_intercept_log")
        total = cursor.fetchone()["total"]

        # 今日拦截数
        cursor.execute(
            "SELECT COUNT(*) as today FROM security_intercept_log WHERE DATE(created_at) = CURDATE()"
        )
        today = cursor.fetchone()["today"]

        # 按渠道分布
        cursor.execute(
            "SELECT channel, COUNT(*) as count FROM security_intercept_log GROUP BY channel ORDER BY count DESC"
        )
        by_channel = cursor.fetchall()

        # 按拦截类型分布
        cursor.execute(
            "SELECT intercept_type, COUNT(*) as count FROM security_intercept_log GROUP BY intercept_type ORDER BY count DESC"
        )
        by_type = cursor.fetchall()

        return {
            "total": total,
            "today": today,
            "by_channel": by_channel,
            "by_type": by_type,
        }

    except Exception as e:
        logger.error("[安全日志] 获取拦截统计失败: {}", e)
        return {"total": 0, "today": 0, "by_channel": [], "by_type": []}
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()
