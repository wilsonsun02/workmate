from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from loguru import logger

from admin_api.models.init_db import get_db_connection
from admin_api.services.env_file_service import EnvFileService


class EnvChangeLogService:
    TABLE_NAME = "sys_env_change_logs"

    @staticmethod
    def _mask_value(key: str, value: Any) -> str:
        text = "" if value is None else str(value)
        if not text:
            return ""
        if not EnvFileService.is_sensitive_key(key):
            return text
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:4]}***{text[-4:]}"

    @classmethod
    def _mask_mapping(cls, values: Mapping[str, Any]) -> dict[str, str]:
        return {key: cls._mask_value(key, value) for key, value in values.items()}

    @classmethod
    def log_change(
        cls,
        *,
        operator: Mapping[str, Any] | None,
        source_ip: str,
        target_file: str,
        changed_keys: list[str],
        before_values: Mapping[str, Any],
        after_values: Mapping[str, Any],
    ) -> None:
        if not changed_keys:
            return
        filtered_before = {
            key: before_values.get(key) for key in changed_keys if key in before_values
        }
        filtered_after = {
            key: after_values.get(key) for key in changed_keys if key in after_values
        }
        masked_before = cls._mask_mapping(filtered_before)
        masked_after = cls._mask_mapping(filtered_after)
        logger.info(
            "环境配置已更新 user={} ip={} keys={}",
            (operator or {}).get("username") or "",
            source_ip,
            ",".join(changed_keys),
        )
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO {cls.TABLE_NAME}
                (id, operator_user_id, operator_username, source_ip, target_file,
                 changed_keys_json, before_masked_json, after_masked_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    str((operator or {}).get("user_id") or ""),
                    str((operator or {}).get("username") or ""),
                    source_ip or "",
                    target_file,
                    json.dumps(changed_keys, ensure_ascii=False),
                    json.dumps(masked_before, ensure_ascii=False),
                    json.dumps(masked_after, ensure_ascii=False),
                ),
            )
            conn.commit()
        except Exception as error:
            logger.error("写入环境配置日志失败: {}", error)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def list_logs(cls, limit: int = 50) -> list[dict[str, Any]]:
        conn = get_db_connection()
        if not conn:
            return []
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT id, operator_user_id, operator_username, source_ip, target_file,
                       changed_keys_json, before_masked_json, after_masked_json, created_at
                FROM {cls.TABLE_NAME}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            )
            rows = cursor.fetchall() or []
            result: list[dict[str, Any]] = []
            for row in rows:
                result.append(
                    {
                        "id": row["id"],
                        "operator_user_id": row.get("operator_user_id") or "",
                        "operator_username": row.get("operator_username") or "",
                        "source_ip": row.get("source_ip") or "",
                        "target_file": row.get("target_file") or "",
                        "changed_keys": json.loads(
                            row.get("changed_keys_json") or "[]"
                        ),
                        "before_values": json.loads(
                            row.get("before_masked_json") or "{}"
                        ),
                        "after_values": json.loads(
                            row.get("after_masked_json") or "{}"
                        ),
                        "created_at": row.get("created_at").isoformat()
                        if row.get("created_at")
                        else "",
                    }
                )
            return result
        except Exception as error:
            logger.error("读取环境配置日志失败: {}", error)
            return []
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()
