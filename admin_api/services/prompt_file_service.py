from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from admin_api.models.init_db import get_db_connection
from workflow.config import BASE_DIR


class PromptFileService:
    PROMPT_DIR = Path(BASE_DIR) / "prompt"
    CURRENT_TABLE = "sys_prompt_files"
    CHANGE_LOG_TABLE = "sys_prompt_change_logs"
    MANAGED_FILES = frozenset({"department.md", "rich.md", "identity.md"})
    EDITABLE_FILES = MANAGED_FILES
    ROOT_OWNER_TYPE = "root"
    ROOT_OWNER_ID = "root"
    OWNER_TYPES = frozenset({"root", "dept", "user"})
    OWNER_ALLOWED_FILES = {
        "root": frozenset({"rich.md"}),
        "dept": frozenset({"department.md"}),
        "user": frozenset({"identity.md"}),
    }
    _SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    INITIAL_VERSION = "0.0.1"

    @classmethod
    def ensure_tables(cls) -> None:
        return None

    @classmethod
    def prompt_dir(cls) -> Path:
        cls.PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        return cls.PROMPT_DIR

    @staticmethod
    def _normalize_file_name(file_name: str) -> str:
        value = str(file_name or "").strip()
        if not value:
            raise ValueError("文件名不能为空")
        if value != os.path.basename(value):
            raise ValueError("非法文件路径")
        if "/" in value or "\\" in value:
            raise ValueError("非法文件路径")
        if not value.lower().endswith(".md"):
            raise ValueError("仅支持 .md 文件")
        return value

    @classmethod
    def _normalize_managed_file_name(cls, file_name: str) -> str:
        normalized = cls._normalize_file_name(file_name)
        if normalized not in cls.MANAGED_FILES:
            raise FileNotFoundError(f"Prompt 文件不存在: {normalized}")
        return normalized

    @classmethod
    def _normalize_owner(
        cls, owner_type: str | None, owner_id: str | None
    ) -> tuple[str, str]:
        normalized_type = (
            str(owner_type or cls.ROOT_OWNER_TYPE).strip() or cls.ROOT_OWNER_TYPE
        )
        if normalized_type not in cls.OWNER_TYPES:
            raise ValueError("非法 owner_type")

        normalized_id = str(owner_id or "").strip()
        if normalized_type == cls.ROOT_OWNER_TYPE:
            return (cls.ROOT_OWNER_TYPE, cls.ROOT_OWNER_ID)

        if not normalized_id:
            raise ValueError("owner_id 不能为空")

        return (normalized_type, normalized_id)

    @classmethod
    def allowed_files_for_owner(cls, owner_type: str) -> frozenset[str]:
        return cls.OWNER_ALLOWED_FILES.get(owner_type, frozenset())

    @classmethod
    def safe_prompt_path(cls, file_name: str) -> Path:
        normalized = cls._normalize_file_name(file_name)
        path = cls.prompt_dir() / normalized
        try:
            path.resolve().relative_to(cls.prompt_dir().resolve())
        except ValueError as error:
            raise ValueError("非法文件路径") from error
        return path

    @classmethod
    def list_local_prompt_files(cls) -> list[str]:
        root = cls.prompt_dir()
        file_names = [
            item.name
            for item in sorted(root.iterdir(), key=lambda p: p.name.lower())
            if item.is_file() and item.name.lower().endswith(".md")
        ]
        return file_names

    @staticmethod
    def _sha256_text(content: str) -> str:
        return hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    @classmethod
    def get_file_policy(
        cls,
        file_name: str,
        owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        normalized = cls._normalize_managed_file_name(file_name)
        allowed_files = cls.allowed_files_for_owner(owner_type_value)
        if normalized not in allowed_files:
            raise FileNotFoundError(f"Prompt 文件不存在: {normalized}")
        return {
            "file_name": normalized,
            "owner_type": owner_type_value,
            "owner_id": owner_id_value,
            "editable": normalized in cls.EDITABLE_FILES,
        }

    @classmethod
    def _with_file_policy(
        cls, payload: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        if not payload:
            return None
        result = dict(payload)
        file_name = str(result.get("file_name") or "")
        if not file_name:
            return result
        result.update(
            cls.get_file_policy(
                file_name,
                owner_type=str(result.get("owner_type") or ""),
                owner_id=str(result.get("owner_id") or ""),
            )
        )
        return result

    @staticmethod
    def _iso(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "")

    @classmethod
    def _row_to_current_payload(
        cls, row: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": str(row.get("id") or ""),
            "owner_type": str(row.get("owner_type") or ""),
            "owner_id": str(row.get("owner_id") or ""),
            "file_name": str(row.get("file_name") or ""),
            "target_file": str(row.get("target_file") or ""),
            "version": str(row.get("version") or cls.INITIAL_VERSION),
            "content": str(row.get("content") or ""),
            "sha256": str(row.get("sha256") or ""),
            "operator_user_id": str(row.get("operator_user_id") or ""),
            "operator_username": str(row.get("operator_username") or ""),
            "updated_at": cls._iso(row.get("updated_at")),
            "created_at": cls._iso(row.get("created_at")),
        }

    @classmethod
    def _parse_semver_safe(cls, version: str) -> tuple[int, int, int]:
        try:
            return cls._parse_semver(version)
        except ValueError:
            return (-1, -1, -1)

    @classmethod
    def _current_row_order_key(cls, row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            cls._parse_semver_safe(str(row.get("version") or cls.INITIAL_VERSION)),
            cls._iso(row.get("updated_at")),
            cls._iso(row.get("created_at")),
            str(row.get("id") or ""),
        )

    @classmethod
    def _fetch_current_row(
        cls, file_name: str, *, owner_type: str, owner_id: str
    ) -> dict[str, Any] | None:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT id, owner_type, owner_id, file_name, target_file, version, content, sha256,
                       operator_user_id, operator_username, updated_at, created_at
                FROM {cls.CURRENT_TABLE}
                WHERE owner_type = %s AND owner_id = %s AND file_name = %s
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT 1
                """,
                (owner_type, owner_id, file_name),
            )
            return cls._row_to_current_payload(cursor.fetchone())
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def _fetch_all_current_rows(
        cls, *, owner_type: str, owner_id: str
    ) -> dict[str, dict[str, Any]]:
        conn = get_db_connection()
        if not conn:
            return {}
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT id, owner_type, owner_id, file_name, target_file, version, content, sha256,
                       operator_user_id, operator_username, updated_at, created_at
                FROM {cls.CURRENT_TABLE}
                WHERE owner_type = %s AND owner_id = %s
                """,
                (owner_type, owner_id),
            )
            rows = cursor.fetchall() or []
            return {
                str(row.get("file_name") or ""): cls._row_to_current_payload(row)
                for row in rows
                if row.get("file_name")
            }
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def _fetch_latest_current_rows(
        cls, *, owner_type: str, owner_id: str
    ) -> list[dict[str, Any]]:
        conn = get_db_connection()
        if not conn:
            return []
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT
                    c.id,
                    c.owner_type,
                    c.owner_id,
                    c.file_name,
                    c.target_file,
                    c.version,
                    c.content,
                    c.sha256,
                    c.operator_user_id,
                    c.operator_username,
                    c.updated_at,
                    c.created_at
                FROM {cls.CURRENT_TABLE} c
                WHERE c.owner_type = %s AND c.owner_id = %s
                ORDER BY c.file_name ASC, c.updated_at DESC, c.created_at DESC
                """,
                (owner_type, owner_id),
            )
            rows = cursor.fetchall() or []
            latest_by_file: dict[str, dict[str, Any]] = {}
            for raw_row in rows:
                row = cls._row_to_current_payload(raw_row)
                if not row:
                    continue
                file_name = str(row.get("file_name") or "")
                if not file_name:
                    continue
                current = latest_by_file.get(file_name)
                if not current or cls._current_row_order_key(
                    row
                ) > cls._current_row_order_key(current):
                    latest_by_file[file_name] = row
            return [latest_by_file[file_name] for file_name in sorted(latest_by_file)]
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def _upsert_current_row(
        cls,
        *,
        owner_type: str,
        owner_id: str,
        file_name: str,
        target_file: str,
        version: str,
        content: str,
        sha256: str,
        operator: Mapping[str, Any] | None = None,
    ) -> None:
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("数据库连接不可用")
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO {cls.CURRENT_TABLE}
                (id, owner_type, owner_id, file_name, target_file, version, content, sha256, operator_user_id, operator_username)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                target_file = VALUES(target_file),
                version = VALUES(version),
                content = VALUES(content),
                sha256 = VALUES(sha256),
                operator_user_id = VALUES(operator_user_id),
                operator_username = VALUES(operator_username)
                """,
                (
                    str(uuid.uuid4()),
                    owner_type,
                    owner_id,
                    file_name,
                    target_file,
                    version,
                    content,
                    sha256,
                    str((operator or {}).get("user_id") or ""),
                    str((operator or {}).get("username") or ""),
                ),
            )
            conn.commit()
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def _insert_change_log(
        cls,
        *,
        owner_type: str,
        owner_id: str,
        file_name: str,
        target_file: str,
        before_version: str,
        after_version: str,
        before_content: str,
        after_content: str,
        operator: Mapping[str, Any] | None = None,
        source_ip: str = "",
    ) -> None:
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO {cls.CHANGE_LOG_TABLE}
                (id, owner_type, owner_id, file_name, target_file, operator_user_id, operator_username, source_ip,
                 before_version, after_version, before_sha256, after_sha256, before_content, after_content)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    owner_type,
                    owner_id,
                    file_name,
                    target_file,
                    str((operator or {}).get("user_id") or ""),
                    str((operator or {}).get("username") or ""),
                    source_ip or "",
                    before_version,
                    after_version,
                    cls._sha256_text(before_content),
                    cls._sha256_text(after_content),
                    before_content,
                    after_content,
                ),
            )
            conn.commit()
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def list_change_logs(
        cls,
        file_name: str,
        *,
        owner_type: str | None = None,
        owner_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        normalized = cls._normalize_managed_file_name(file_name)
        cls.get_file_policy(normalized, owner_type_value, owner_id_value)
        conn = get_db_connection()
        if not conn:
            return []
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT id, file_name, target_file, operator_user_id, operator_username, source_ip,
                       before_version, after_version, before_sha256, after_sha256,
                       before_content, after_content, created_at
                FROM {cls.CHANGE_LOG_TABLE}
                WHERE owner_type = %s AND owner_id = %s AND file_name = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (owner_type_value, owner_id_value, normalized, max(1, int(limit))),
            )
            rows = cursor.fetchall() or []
            return [
                {
                    "id": str(row.get("id") or ""),
                    "file_name": str(row.get("file_name") or ""),
                    "target_file": str(row.get("target_file") or ""),
                    "operator_user_id": str(row.get("operator_user_id") or ""),
                    "operator_username": str(row.get("operator_username") or ""),
                    "source_ip": str(row.get("source_ip") or ""),
                    "before_version": str(
                        row.get("before_version") or cls.INITIAL_VERSION
                    ),
                    "after_version": str(
                        row.get("after_version") or cls.INITIAL_VERSION
                    ),
                    "before_sha256": str(row.get("before_sha256") or ""),
                    "after_sha256": str(row.get("after_sha256") or ""),
                    "before_content": str(row.get("before_content") or ""),
                    "after_content": str(row.get("after_content") or ""),
                    "created_at": cls._iso(row.get("created_at")),
                }
                for row in rows
            ]
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @classmethod
    def _read_local_content(cls, file_name: str) -> str:
        path = cls.safe_prompt_path(file_name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Prompt 文件不存在: {file_name}")
        return path.read_text(encoding="utf-8")

    @classmethod
    def _write_local_content(cls, file_name: str, content: str) -> str:
        path = cls.safe_prompt_path(file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    @classmethod
    def seed_prompt_file_from_local(cls, file_name: str) -> dict[str, Any]:
        owner_type_value, owner_id_value = cls._normalize_owner(None, None)
        normalized = cls._normalize_file_name(file_name)
        content = cls._read_local_content(normalized)
        target_file = str(cls.safe_prompt_path(normalized))
        sha256 = cls._sha256_text(content)
        cls._upsert_current_row(
            owner_type=owner_type_value,
            owner_id=owner_id_value,
            file_name=normalized,
            target_file=target_file,
            version=cls.INITIAL_VERSION,
            content=content,
            sha256=sha256,
            operator=None,
        )
        return cls.get_prompt_file(
            normalized, owner_type=owner_type_value, owner_id=owner_id_value
        )

    @classmethod
    def get_prompt_file(
        cls,
        file_name: str,
        *,
        owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        normalized = cls._normalize_managed_file_name(file_name)
        cls.get_file_policy(normalized, owner_type_value, owner_id_value)
        row = cls._fetch_current_row(
            normalized, owner_type=owner_type_value, owner_id=owner_id_value
        )
        if not row:
            row = cls.seed_prompt_file_from_local_for_owner(
                normalized, owner_type=owner_type_value, owner_id=owner_id_value
            )
        path = cls.safe_prompt_path(normalized)
        return (
            cls._with_file_policy(
                {
                    "owner_type": owner_type_value,
                    "owner_id": owner_id_value,
                    "file_name": normalized,
                    "path": str(path),
                    "version": row.get("version", cls.INITIAL_VERSION),
                    "content": row.get("content", ""),
                    "sha256": row.get("sha256", ""),
                    "updated_at": row.get("updated_at", ""),
                }
            )
            or {}
        )

    @classmethod
    def seed_prompt_file_from_local_for_owner(
        cls, file_name: str, *, owner_type: str, owner_id: str
    ) -> dict[str, Any]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        normalized = cls._normalize_managed_file_name(file_name)
        cls.get_file_policy(normalized, owner_type_value, owner_id_value)
        content = cls._read_local_content(normalized)
        target_file = str(cls.safe_prompt_path(normalized))
        sha256 = cls._sha256_text(content)
        cls._upsert_current_row(
            owner_type=owner_type_value,
            owner_id=owner_id_value,
            file_name=normalized,
            target_file=target_file,
            version=cls.INITIAL_VERSION,
            content=content,
            sha256=sha256,
            operator=None,
        )
        row = (
            cls._fetch_current_row(
                normalized, owner_type=owner_type_value, owner_id=owner_id_value
            )
            or {}
        )
        return row

    @classmethod
    def hydrate_local_prompts_from_db(
        cls, fallback_to_local: bool = True
    ) -> dict[str, Any]:
        local_files = cls.list_local_prompt_files()
        current_rows = cls._fetch_all_current_rows(
            owner_type=cls.ROOT_OWNER_TYPE, owner_id=cls.ROOT_OWNER_ID
        )
        seeded_files: list[str] = []

        if current_rows:
            known_file_names = sorted(set(local_files) | set(current_rows.keys()))
            for file_name in known_file_names:
                row = current_rows.get(file_name)
                if not row and fallback_to_local and file_name in local_files:
                    cls.seed_prompt_file_from_local(file_name)
                    seeded_files.append(file_name)
            return {
                "source": "database_seed_only",
                "seeded_files": seeded_files,
            }

        if fallback_to_local:
            for file_name in local_files:
                cls.seed_prompt_file_from_local(file_name)
                seeded_files.append(file_name)
            return {
                "source": "local",
                "seeded_files": seeded_files,
            }

        return {
            "source": "empty",
            "seeded_files": [],
        }

    @classmethod
    def list_prompt_files(cls) -> list[dict[str, Any]]:
        rows = cls._fetch_latest_current_rows(
            owner_type=cls.ROOT_OWNER_TYPE, owner_id=cls.ROOT_OWNER_ID
        )
        return [
            cls._with_file_policy(
                {
                    "owner_type": cls.ROOT_OWNER_TYPE,
                    "owner_id": cls.ROOT_OWNER_ID,
                    "file_name": str(row.get("file_name") or ""),
                    "path": str(row.get("target_file") or ""),
                    "version": str(row.get("version") or cls.INITIAL_VERSION),
                    "sha256": str(row.get("sha256") or ""),
                    "updated_at": cls._iso(row.get("updated_at")),
                }
            )
            for row in rows
            if row.get("file_name") in cls.allowed_files_for_owner(cls.ROOT_OWNER_TYPE)
        ]

    @classmethod
    def list_prompt_files_for_owner(
        cls, *, owner_type: str | None = None, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        rows = cls._fetch_latest_current_rows(
            owner_type=owner_type_value, owner_id=owner_id_value
        )
        allowed = cls.allowed_files_for_owner(owner_type_value)
        return [
            cls._with_file_policy(
                {
                    "owner_type": owner_type_value,
                    "owner_id": owner_id_value,
                    "file_name": str(row.get("file_name") or ""),
                    "path": str(row.get("target_file") or ""),
                    "version": str(row.get("version") or cls.INITIAL_VERSION),
                    "sha256": str(row.get("sha256") or ""),
                    "updated_at": cls._iso(row.get("updated_at")),
                }
            )
            for row in rows
            if row.get("file_name") in allowed
        ]

    @classmethod
    def list_version_history(
        cls,
        file_name: str,
        *,
        owner_type: str | None = None,
        owner_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        current = cls.get_prompt_file(
            file_name, owner_type=owner_type_value, owner_id=owner_id_value
        )
        logs = cls.list_change_logs(
            file_name,
            owner_type=owner_type_value,
            owner_id=owner_id_value,
            limit=max(1, int(limit)),
        )
        history: list[dict[str, Any]] = [
            {
                "file_name": current["file_name"],
                "version": current.get("version") or cls.INITIAL_VERSION,
                "content": current.get("content") or "",
                "sha256": current.get("sha256") or "",
                "operator_user_id": "",
                "operator_username": "当前版本",
                "source_ip": "",
                "updated_at": current.get("updated_at") or "",
            }
        ]
        seen_versions = {str(current.get("version") or cls.INITIAL_VERSION)}
        for log in logs:
            version = str(log.get("before_version") or cls.INITIAL_VERSION)
            if version in seen_versions:
                continue
            seen_versions.add(version)
            history.append(
                {
                    "file_name": current["file_name"],
                    "version": version,
                    "content": str(log.get("before_content") or ""),
                    "sha256": str(log.get("before_sha256") or ""),
                    "operator_user_id": str(log.get("operator_user_id") or ""),
                    "operator_username": str(log.get("operator_username") or ""),
                    "source_ip": str(log.get("source_ip") or ""),
                    "updated_at": str(log.get("created_at") or ""),
                }
            )
        history.sort(
            key=lambda item: cls._parse_semver(
                str(item.get("version") or cls.INITIAL_VERSION)
            ),
            reverse=True,
        )
        return history[: max(1, int(limit))]

    @classmethod
    def save_prompt_file(
        cls,
        file_name: str,
        content: str,
        *,
        owner_type: str | None = None,
        owner_id: str | None = None,
        operator: Mapping[str, Any] | None = None,
        source_ip: str = "",
    ) -> dict[str, Any]:
        owner_type_value, owner_id_value = cls._normalize_owner(owner_type, owner_id)
        current = cls.get_prompt_file(
            cls._normalize_managed_file_name(file_name),
            owner_type=owner_type_value,
            owner_id=owner_id_value,
        )
        normalized = current["file_name"]
        policy = cls.get_file_policy(normalized, owner_type_value, owner_id_value)
        if not policy["editable"]:
            raise PermissionError("当前 Prompt 仅支持查看和版本管理，不允许编辑")
        before_version = current.get("version") or cls.INITIAL_VERSION
        before_content = current["content"]
        after_content = str(content or "")
        if before_content == after_content:
            return {
                "changed": False,
                "file_name": normalized,
                "path": current["path"],
                "version": before_version,
                "sha256": current["sha256"],
                "updated_at": current["updated_at"],
            }

        sha256 = cls._sha256_text(after_content)
        after_version = cls.next_current_version(before_version)
        cls._upsert_current_row(
            owner_type=owner_type_value,
            owner_id=owner_id_value,
            file_name=normalized,
            target_file=current["path"],
            version=after_version,
            content=after_content,
            sha256=sha256,
            operator=operator,
        )
        cls._insert_change_log(
            owner_type=owner_type_value,
            owner_id=owner_id_value,
            file_name=normalized,
            target_file=current["path"],
            before_version=before_version,
            after_version=after_version,
            before_content=before_content,
            after_content=after_content,
            operator=operator,
            source_ip=source_ip,
        )
        latest = cls.get_prompt_file(
            normalized, owner_type=owner_type_value, owner_id=owner_id_value
        )
        return {
            "changed": True,
            "file_name": normalized,
            "path": latest["path"],
            "version": latest["version"],
            "sha256": latest["sha256"],
            "updated_at": latest["updated_at"],
            "before_version": before_version,
            "after_version": after_version,
            "before_content": before_content,
            "after_content": after_content,
        }

    @classmethod
    def _parse_semver(cls, version: str) -> tuple[int, int, int]:
        text = str(version or "").strip()
        match = cls._SEMVER_PATTERN.match(text)
        if not match:
            raise ValueError(f"非法版本号: {version}")
        return int(match.group(1)), int(match.group(2)), int(match.group(3))

    @classmethod
    def next_current_version(cls, current_version: str) -> str:
        text = str(current_version or "").strip()
        if not text:
            return cls.INITIAL_VERSION
        major, minor, patch = cls._parse_semver(text)
        return f"{major}.{minor}.{patch + 1}"
