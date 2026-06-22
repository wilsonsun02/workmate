from __future__ import annotations

from admin_api.models.init_db import get_db_connection
from loguru import logger


class UserPreferenceService:
    @staticmethod
    def list_preferences(user_id: str) -> list[dict]:
        uid = str(user_id or "").strip()
        if not uid:
            return []

        conn = get_db_connection()
        if not conn:
            return []

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT pref_key, pref_value, created_at, updated_at
                FROM user_preferences
                WHERE user_id = %s
                ORDER BY updated_at DESC, pref_key ASC
                """,
                (uid,),
            )
            return cursor.fetchall() or []
        except Exception as e:
            logger.error("Error listing user preferences: {}", e)
            return []
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def list_preferences_by_username(username: str) -> list[dict]:
        uname = str(username or "").strip()
        if not uname:
            return []

        conn = get_db_connection()
        if not conn:
            return []

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT p.pref_key, p.pref_value, p.created_at, p.updated_at
                FROM user_preferences p
                WHERE p.agent_username = %s
                ORDER BY p.updated_at DESC, p.pref_key ASC
                """,
                (uname,),
            )
            return cursor.fetchall() or []
        except Exception as e:
            logger.error("Error listing user preferences by username: {}", e)
            return []
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def upsert_preference(user_id: str, pref_key: str, pref_value: str) -> bool:
        uid = str(user_id or "").strip()
        key = str(pref_key or "").strip()
        value = str(pref_value or "")
        if not uid or not key:
            return False

        conn = get_db_connection()
        if not conn:
            return False

        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_preferences (user_id, pref_key, pref_value)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE pref_value = VALUES(pref_value)
                """,
                (uid, key, value),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Error upserting user preference: {}", e)
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def delete_preference(user_id: str, pref_key: str) -> bool:
        uid = str(user_id or "").strip()
        key = str(pref_key or "").strip()
        if not uid or not key:
            return False

        conn = get_db_connection()
        if not conn:
            return False

        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_preferences WHERE user_id = %s AND pref_key = %s",
                (uid, key),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error deleting user preference: {}", e)
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()
