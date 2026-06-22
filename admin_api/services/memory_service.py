from typing import Optional

from loguru import logger

from admin_api.models.init_db import get_db_connection


class MemoryService:
    @staticmethod
    def list_mid_term(
        username: Optional[str] = None,
        thread_id: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ):
        connection = get_db_connection()
        if not connection:
            return [], 0

        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))

        where_clauses = []
        where_params = []

        if username:
            where_clauses.append("username = %s")
            where_params.append(username)
        if thread_id:
            where_clauses.append("thread_id = %s")
            where_params.append(thread_id)
        if keyword:
            where_clauses.append("summary LIKE %s")
            where_params.append(f"%{keyword}%")

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        try:
            cursor = connection.cursor(dictionary=True)

            count_sql = (
                f"SELECT COUNT(*) AS total FROM conversation_summaries{where_sql}"
            )
            cursor.execute(count_sql, tuple(where_params))
            total_row = cursor.fetchone() or {}
            total = int(total_row.get("total", 0))

            query_sql = f"""
                SELECT
                    id,
                    username,
                    thread_id,
                    summary,
                    last_sequence_number,
                    last_chat_index,
                    created_at
                FROM conversation_summaries
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
            """
            query_params = list(where_params) + [safe_limit, safe_offset]
            cursor.execute(query_sql, tuple(query_params))
            rows = cursor.fetchall()
            return rows, total
        except Exception as e:
            logger.error("Error listing mid-term memories: {}", e)
            return [], 0
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_mid_term_detail(memory_id: int):
        connection = get_db_connection()
        if not connection:
            return None

        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    username,
                    thread_id,
                    summary,
                    full_conversation,
                    last_sequence_number,
                    last_chat_index,
                    created_at
                FROM conversation_summaries
                WHERE id = %s
                LIMIT 1
                """,
                (memory_id,),
            )
            return cursor.fetchone()
        except Exception as e:
            logger.error("Error getting mid-term memory detail {}: {}", memory_id, e)
            return None
        finally:
            if connection.is_connected():
                if cursor:
                    cursor.close()
                connection.close()

    @staticmethod
    def update_mid_term_summary(memory_id: int, summary: str) -> bool:
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE conversation_summaries SET summary = %s WHERE id = %s",
                (summary, memory_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error updating mid-term memory {}: {}", memory_id, e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def delete_mid_term(memory_id: int) -> bool:
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM conversation_summaries WHERE id = %s",
                (memory_id,),
            )
            connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error deleting mid-term memory {}: {}", memory_id, e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
