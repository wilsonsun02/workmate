import base64
import hashlib
import os
import uuid

from cryptography.fernet import Fernet, InvalidToken
from mysql.connector import IntegrityError
from admin_api.models.init_db import get_db_connection
import bcrypt

from loguru import logger


class UserService:
    WXWORK_BOT_NAME_MAX_LENGTH = 100
    WXWORK_BOT_ID_MAX_LENGTH = 100
    WXWORK_SECRET_MAX_LENGTH = 255
    _USER_BASE_SELECT_FIELDS = [
        "u.id",
        "u.username",
        "COALESCE(NULLIF(u.name, ''), u.username) AS name",
        "u.title",
        "u.status",
        "u.is_special",
        "u.special_type",
        "u.external_agent_base_url",
        "u.created_at",
        "u.tenant_id",
        "u.dept_id",
        "r.id as role_id",
        "r.name as role_name",
        "d.name as dept_name",
    ]

    @staticmethod
    def _get_wxwork_cipher() -> Fernet:
        secret = (
            os.getenv("WORKMATE_USER_CONFIG_SECRET")
            or os.getenv("WORKMATE_CONFIG_SECRET")
            or os.getenv("WORKMATE_DB_PASS")
            or "workmate-local-dev-secret"
        )
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @staticmethod
    def _encrypt_wxwork_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return (
            UserService._get_wxwork_cipher()
            .encrypt(text.encode("utf-8"))
            .decode("utf-8")
        )

    @staticmethod
    def _decrypt_wxwork_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return (
                UserService._get_wxwork_cipher()
                .decrypt(text.encode("utf-8"))
                .decode("utf-8")
            )
        except (InvalidToken, ValueError):
            logger.warning(
                "Failed to decrypt wxwork bot config, falling back to raw value"
            )
            return text

    @staticmethod
    def _normalize_wxwork_bot_field(value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()

    @staticmethod
    def _normalize_optional_text_field(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _build_deleted_username(username: str | None, user_id: str) -> str:
        base = str(username or "deleted_user").strip() or "deleted_user"
        suffix = str(user_id or "").replace("-", "")[:8] or uuid.uuid4().hex[:8]
        return f"{base}__deleted__{suffix}"

    @staticmethod
    def _normalize_wxwork_bot_fields(
        wxwork_bot_name: str | None,
        wxwork_bot_id: str | None,
        wxwork_secret: str | None,
    ) -> dict[str, str | None]:
        return {
            "wxwork_bot_name": UserService._normalize_wxwork_bot_field(wxwork_bot_name),
            "wxwork_bot_id": UserService._normalize_wxwork_bot_field(wxwork_bot_id),
            "wxwork_secret": UserService._normalize_wxwork_bot_field(wxwork_secret),
        }

    @staticmethod
    def validate_wxwork_bot_config(
        wxwork_bot_name: str | None,
        wxwork_bot_id: str | None,
        wxwork_secret: str | None,
        *,
        require_all: bool,
    ) -> dict[str, str] | None:
        normalized = UserService._normalize_wxwork_bot_fields(
            wxwork_bot_name,
            wxwork_bot_id,
            wxwork_secret,
        )
        has_any_value = any(value not in (None, "") for value in normalized.values())
        if not has_any_value and not require_all:
            return None

        missing_fields = [key for key, value in normalized.items() if not value]
        if missing_fields:
            raise ValueError("企业微信机器人配置字段不能为空")

        if len(normalized["wxwork_bot_name"]) > UserService.WXWORK_BOT_NAME_MAX_LENGTH:
            raise ValueError("机器人名称长度不能超过 100 个字符")
        if len(normalized["wxwork_bot_id"]) > UserService.WXWORK_BOT_ID_MAX_LENGTH:
            raise ValueError("机器人 ID 长度不能超过 100 个字符")
        if len(normalized["wxwork_secret"]) > UserService.WXWORK_SECRET_MAX_LENGTH:
            raise ValueError("机器人密钥长度不能超过 255 个字符")
        if any(ch.isspace() for ch in normalized["wxwork_bot_id"]):
            raise ValueError("机器人 ID 不能包含空白字符")
        if any(ch.isspace() for ch in normalized["wxwork_secret"]):
            raise ValueError("机器人密钥不能包含空白字符")

        return {
            "wxwork_bot_name": normalized["wxwork_bot_name"],
            "wxwork_bot_id": UserService._encrypt_wxwork_value(
                normalized["wxwork_bot_id"]
            ),
            "wxwork_secret": UserService._encrypt_wxwork_value(
                normalized["wxwork_secret"]
            ),
        }

    @staticmethod
    def get_users(tenant_id: str = None):
        items, _ = UserService.list_users_paginated(
            tenant_id=tenant_id,
            limit=None,
            offset=0,
            include_extra_fields=True,
        )
        return items

    @staticmethod
    def _build_user_list_where(
        *,
        tenant_id: str | None = None,
        keyword: str | None = None,
        dept_id: str | None = None,
        role_id: str | None = None,
        status: int | None = None,
        dept_name: str | None = None,
        role_name: str | None = None,
    ) -> tuple[list[str], list]:
        where_clauses: list[str] = ["u.deleted_at IS NULL"]
        params: list = []
        if tenant_id:
            where_clauses.append("u.tenant_id = %s")
            params.append(tenant_id)
        if dept_id:
            where_clauses.append("u.dept_id = %s")
            params.append(dept_id)
        if role_id:
            where_clauses.append("u.role_id = %s")
            params.append(role_id)
        if status is not None:
            where_clauses.append("u.status = %s")
            params.append(int(status))
        if dept_name:
            where_clauses.append("d.name LIKE %s")
            params.append(f"%{dept_name}%")
        if role_name:
            where_clauses.append("r.name LIKE %s")
            params.append(f"%{role_name}%")
        if keyword:
            where_clauses.append(
                """
                (
                    u.username LIKE %s
                    OR COALESCE(NULLIF(u.name, ''), u.username) LIKE %s
                    OR COALESCE(u.title, '') LIKE %s
                    OR COALESCE(d.name, '') LIKE %s
                    OR COALESCE(r.name, '') LIKE %s
                )
                """
            )
            keyword_like = f"%{keyword}%"
            params.extend(
                [keyword_like, keyword_like, keyword_like, keyword_like, keyword_like]
            )
        return where_clauses, params

    @staticmethod
    def list_users_paginated(
        *,
        tenant_id: str | None = None,
        keyword: str | None = None,
        dept_id: str | None = None,
        role_id: str | None = None,
        status: int | None = None,
        dept_name: str | None = None,
        role_name: str | None = None,
        limit: int | None = 20,
        offset: int = 0,
        include_extra_fields: bool = False,
    ) -> tuple[list[dict], int]:
        connection = get_db_connection()
        if not connection:
            return [], 0

        select_fields = list(UserService._USER_BASE_SELECT_FIELDS)
        if include_extra_fields:
            select_fields.extend(
                [
                    "u.third_party_id",
                    "u.wechat_work_id",
                ]
            )

        where_clauses, where_params = UserService._build_user_list_where(
            tenant_id=tenant_id,
            keyword=keyword,
            dept_id=dept_id,
            role_id=role_id,
            status=status,
            dept_name=dept_name,
            role_name=role_name,
        )
        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        from_sql = """
            FROM sys_users u
            LEFT JOIN sys_roles r ON u.role_id = r.id
            LEFT JOIN sys_departments d ON u.dept_id = d.id
        """

        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"SELECT COUNT(*) AS total {from_sql}{where_sql}",
                tuple(where_params),
            )
            total_row = cursor.fetchone() or {}
            total = int(total_row.get("total") or 0)

            query = (
                f"SELECT {', '.join(select_fields)} {from_sql}{where_sql}"
                " ORDER BY u.created_at DESC"
            )
            query_params = list(where_params)
            if limit is not None:
                query += " LIMIT %s OFFSET %s"
                query_params.extend([max(1, int(limit)), max(0, int(offset))])

            cursor.execute(query, tuple(query_params))
            return cursor.fetchall() or [], total
        except Exception as e:
            logger.error("Error listing users: {}", e)
            return [], 0
        finally:
            if connection.is_connected():
                if cursor:
                    cursor.close()
                connection.close()

    @staticmethod
    def get_user_by_id(user_id: str):
        """按 sys_users.id 查询用户（含角色/部门名称）。"""
        uid = str(user_id or "").strip()
        if not uid:
            return None

        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT u.id, u.username, COALESCE(NULLIF(u.name, ''), u.username) AS name,
                       u.title,
                       u.third_party_id, u.wechat_work_id, u.status,
                       u.is_special, u.special_type, u.external_agent_base_url,
                       u.created_at, u.tenant_id, u.dept_id,
                       r.id as role_id, r.name as role_name,
                       d.name as dept_name
                FROM sys_users u
                LEFT JOIN sys_roles r ON u.role_id = r.id
                LEFT JOIN sys_departments d ON u.dept_id = d.id
                WHERE u.id = %s AND u.deleted_at IS NULL
                """,
                (uid,),
            )
            return cursor.fetchone()
        except Exception as e:
            logger.error("Error getting user by id: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_user_wxwork_bot_config(user_id: str) -> dict | None:
        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, wxwork_bot_name, wxwork_bot_id, wxwork_secret
                FROM sys_users
                WHERE id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "user_id": str(row.get("id") or user_id),
                "wxwork_bot_name": str(row.get("wxwork_bot_name") or ""),
                "wxwork_bot_id": UserService._decrypt_wxwork_value(
                    row.get("wxwork_bot_id") or ""
                ),
                "wxwork_secret": UserService._decrypt_wxwork_value(
                    row.get("wxwork_secret") or ""
                ),
            }
        except Exception as e:
            logger.error("Error getting user wxwork bot config: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_departments(tenant_id: str = None):
        connection = get_db_connection()
        if not connection:
            return []

        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT id, name, parent_id, tenant_id, dept_code, manager_user_id, third_party_id FROM sys_departments"
            params = []
            if tenant_id:
                query += " WHERE tenant_id = %s"
                params.append(tenant_id)
            cursor.execute(query, tuple(params))
            depts = cursor.fetchall()
            return depts
        except Exception as e:
            logger.error("Error getting departments: {}", e)
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def create_department(
        name: str,
        dept_code: str = None,
        manager_user_id: str = None,
        parent_id: str = None,
        tenant_id: str = None,
        third_party_id: str = None,
    ):
        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor()

            # 校验租户内 dept_code 唯一性
            if dept_code and tenant_id:
                cursor.execute(
                    "SELECT id FROM sys_departments WHERE tenant_id = %s AND dept_code = %s",
                    (tenant_id, dept_code),
                )
                if cursor.fetchone():
                    raise ValueError(f"部门编码 '{dept_code}' 在该租户下已存在")

            dept_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO sys_departments (id, tenant_id, parent_id, name, dept_code, manager_user_id, third_party_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dept_id,
                    tenant_id,
                    parent_id,
                    name,
                    dept_code,
                    manager_user_id,
                    third_party_id,
                ),
            )
            connection.commit()
            return dept_id
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error("Error creating department: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def validate_department_parent(cursor, dept_id: str, parent_id: str):
        if not parent_id:
            return True
        if dept_id == parent_id:
            raise ValueError("不能将自己设为父部门")

        # 检查循环引用
        current_parent = parent_id
        while current_parent:
            cursor.execute(
                "SELECT parent_id FROM sys_departments WHERE id = %s", (current_parent,)
            )
            row = cursor.fetchone()
            if not row:
                break
            next_parent = row.get("parent_id") if isinstance(row, dict) else row[0]
            if next_parent == dept_id:
                raise ValueError("不能形成循环的部门层级")
            current_parent = str(next_parent or "").strip()
        return True

    @staticmethod
    def update_department(
        dept_id: str,
        name: str = None,
        dept_code: str = None,
        manager_user_id: str = None,
        parent_id: str = None,
        tenant_id: str = None,
        third_party_id: str = None,
    ):
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor(dictionary=True)

            name_provided = name is not None
            dept_code_provided = dept_code is not None
            manager_user_id_provided = manager_user_id is not None
            parent_id_provided = parent_id is not None
            tenant_id_provided = tenant_id is not None
            third_party_id_provided = third_party_id is not None

            if name_provided:
                normalized_name = str(name).strip()
                if not normalized_name:
                    raise ValueError("部门名称不能为空")
                if len(normalized_name) > 100:
                    raise ValueError("部门名称长度不能超过 100 个字符")
                name = normalized_name

            if dept_code_provided:
                dept_code = UserService._normalize_optional_text_field(dept_code)
            if manager_user_id_provided:
                manager_user_id = UserService._normalize_optional_text_field(
                    manager_user_id
                )
            if parent_id_provided:
                parent_id = UserService._normalize_optional_text_field(parent_id)
            if tenant_id_provided:
                tenant_id = UserService._normalize_optional_text_field(tenant_id)
            if third_party_id_provided:
                third_party_id = UserService._normalize_optional_text_field(
                    third_party_id
                )

            # 如果更新了 parent_id，需校验
            if parent_id_provided:
                UserService.validate_department_parent(cursor, dept_id, parent_id)

            # 校验 dept_code 唯一性
            if dept_code_provided and dept_code:
                # 获取当前记录的 tenant_id 以防未传入
                current_tenant_id = tenant_id
                if not current_tenant_id:
                    cursor.execute(
                        "SELECT tenant_id FROM sys_departments WHERE id = %s",
                        (dept_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        current_tenant_id = row["tenant_id"]

                if current_tenant_id:
                    cursor.execute(
                        "SELECT id FROM sys_departments WHERE tenant_id = %s AND dept_code = %s AND id != %s",
                        (current_tenant_id, dept_code, dept_id),
                    )
                    if cursor.fetchone():
                        raise ValueError(f"部门编码 '{dept_code}' 在该租户下已存在")

            updates = []
            params = []

            if name_provided:
                updates.append("name = %s")
                params.append(name)
            if dept_code_provided:
                updates.append("dept_code = %s")
                params.append(dept_code)
            if manager_user_id_provided:
                updates.append("manager_user_id = %s")
                params.append(manager_user_id)
            if parent_id_provided:
                updates.append("parent_id = %s")
                params.append(parent_id)
            if tenant_id_provided:
                updates.append("tenant_id = %s")
                params.append(tenant_id)
            if third_party_id_provided:
                updates.append("third_party_id = %s")
                params.append(third_party_id)

            if not updates:
                return True

            params.append(dept_id)
            query = f"UPDATE sys_departments SET {', '.join(updates)} WHERE id = %s"

            cursor.execute(query, tuple(params))
            connection.commit()
            return True
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error("Error updating department: {}", e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def can_delete_department(cursor, dept_id: str):
        # 检查是否有子部门
        cursor.execute(
            "SELECT id FROM sys_departments WHERE parent_id = %s", (dept_id,)
        )
        if cursor.fetchone():
            raise ValueError("该部门下存在子部门，禁止删除")

        return True

    @staticmethod
    def delete_department(dept_id: str):
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            UserService.can_delete_department(cursor, dept_id)

            cursor.execute("DELETE FROM sys_departments WHERE id = %s", (dept_id,))
            connection.commit()
            return True
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error("Error deleting department: {}", e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_roles():
        connection = get_db_connection()
        if not connection:
            return []
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, name, code, description FROM sys_roles ORDER BY name ASC"
            )
            return cursor.fetchall()
        except Exception as e:
            logger.error("Error getting roles: {}", e)
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_user_by_username(username: str):
        """仅从管理员表中获取用户（兼容旧逻辑）"""
        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM sys_admin_users WHERE username = %s", (username,)
            )
            user = cursor.fetchone()
            return user
        except Exception as e:
            logger.error("Error getting user by username: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_normal_user_by_username(username: str):
        """从普通员工表中获取用户"""
        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM sys_users WHERE username = %s AND deleted_at IS NULL",
                (username,),
            )
            user = cursor.fetchone()
            return user
        except Exception as e:
            logger.error("Error getting normal user by username: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def hash_password(password: str) -> str:
        """使用 bcrypt 对密码进行哈希"""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    @staticmethod
    def check_password(password: str, hashed_password: str) -> bool:
        """校验密码，兼容明文（admin123）和 bcrypt"""
        if not hashed_password:
            return False
        # 兼容旧的明文密码 "admin123"
        if hashed_password == "admin123":
            return password == "admin123"

        try:
            return bcrypt.checkpw(
                password.encode("utf-8"), hashed_password.encode("utf-8")
            )
        except ValueError:
            # 如果不是合法的 bcrypt hash 格式，尝试直接比较
            return password == hashed_password

    @staticmethod
    def verify_password(username: str, password: str):
        # 1. 优先尝试管理员表
        user = UserService.get_user_by_username(username)
        if user:
            if UserService.check_password(password, user.get("password_hash")):
                return user

        # 2. 如果管理员表未找到或密码错误，尝试普通用户表
        user = UserService.get_normal_user_by_username(username)
        if user:
            if UserService.check_password(password, user.get("password_hash")):
                return user

        return None

    @staticmethod
    def create_user(
        username: str,
        name: str = None,
        title: str = None,
        third_party_id: str = None,
        wechat_work_id: str = None,
        wxwork_bot_name: str = None,
        wxwork_bot_id: str = None,
        wxwork_secret: str = None,
        role_id: str = None,
        dept_id: str = None,
        tenant_id: str = None,
        is_special: int = None,
        special_type: str = None,
        external_agent_base_url: str = None,
        external_agent_token: str = None,
        password: str = None,
    ):
        connection = get_db_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor()
            user_id = str(uuid.uuid4())
            display_name = str(name or username or "").strip() or username
            normalized_third_party_id = UserService._normalize_optional_text_field(
                third_party_id
            )
            normalized_wechat_work_id = UserService._normalize_optional_text_field(
                wechat_work_id
            )

            password_hash = UserService.hash_password(password) if password else None
            bot_config = UserService.validate_wxwork_bot_config(
                wxwork_bot_name,
                wxwork_bot_id,
                wxwork_secret,
                require_all=False,
            )
            normalized_title = UserService._normalize_optional_text_field(title)
            normalized_special_type = UserService._normalize_optional_text_field(
                special_type
            )
            normalized_external_agent_base_url = (
                UserService._normalize_optional_text_field(external_agent_base_url)
            )
            normalized_external_agent_token = (
                UserService._normalize_optional_text_field(external_agent_token)
            )
            encrypted_external_agent_token = (
                UserService._encrypt_wxwork_value(normalized_external_agent_token)
                if normalized_external_agent_token
                else ""
            )
            normalized_is_special = int(is_special) if is_special is not None else 0

            cursor.execute(
                """
                INSERT INTO sys_users (
                    id, username, name, password_hash, third_party_id, wechat_work_id,
                    wxwork_bot_name, wxwork_bot_id, wxwork_secret,
                    role_id, dept_id, tenant_id,
                    title, is_special, special_type, external_agent_base_url, external_agent_token
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    user_id,
                    username,
                    display_name,
                    password_hash,
                    normalized_third_party_id,
                    normalized_wechat_work_id,
                    (bot_config or {}).get("wxwork_bot_name"),
                    (bot_config or {}).get("wxwork_bot_id"),
                    (bot_config or {}).get("wxwork_secret"),
                    role_id,
                    dept_id,
                    tenant_id,
                    normalized_title,
                    normalized_is_special,
                    normalized_special_type,
                    normalized_external_agent_base_url,
                    encrypted_external_agent_token,
                ),
            )

            connection.commit()
            return user_id
        except ValueError:
            raise
        except IntegrityError as e:
            logger.error("Error creating user: {}", e)
            raise ValueError("同一租户下第三方 ID、企微 ID 或登录账号不能重复")
        except Exception as e:
            logger.error("Error creating user: {}", e)
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def update_user(
        user_id: str,
        username: str = None,
        name: str = None,
        title: str = None,
        third_party_id: str = None,
        wechat_work_id: str = None,
        wxwork_bot_name: str = None,
        wxwork_bot_id: str = None,
        wxwork_secret: str = None,
        role_id: str = None,
        dept_id: str = None,
        tenant_id: str = None,
        status: int = None,
        is_special: int = None,
        special_type: str = None,
        external_agent_base_url: str = None,
        external_agent_token: str = None,
        password: str = None,
    ):
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            normalized_third_party_id = UserService._normalize_optional_text_field(
                third_party_id
            )
            normalized_wechat_work_id = UserService._normalize_optional_text_field(
                wechat_work_id
            )

            updates = []
            params = []
            if any(
                value is not None
                for value in (wxwork_bot_name, wxwork_bot_id, wxwork_secret)
            ):
                normalized_bot_fields = UserService._normalize_wxwork_bot_fields(
                    wxwork_bot_name,
                    wxwork_bot_id,
                    wxwork_secret,
                )
                has_any_bot_value = any(
                    value not in (None, "") for value in normalized_bot_fields.values()
                )
                bot_config = (
                    UserService.validate_wxwork_bot_config(
                        wxwork_bot_name,
                        wxwork_bot_id,
                        wxwork_secret,
                        require_all=True,
                    )
                    if has_any_bot_value
                    else None
                )
                updates.extend(
                    [
                        "wxwork_bot_name = %s",
                        "wxwork_bot_id = %s",
                        "wxwork_secret = %s",
                    ]
                )
                params.extend(
                    [
                        (bot_config or {}).get("wxwork_bot_name"),
                        (bot_config or {}).get("wxwork_bot_id"),
                        (bot_config or {}).get("wxwork_secret"),
                    ]
                )

            if username is not None:
                updates.append("username = %s")
                params.append(username)
            if name is not None:
                normalized_name = str(name).strip() or username or None
                updates.append("name = %s")
                params.append(normalized_name)
            if third_party_id is not None:
                updates.append("third_party_id = %s")
                params.append(normalized_third_party_id)
            if wechat_work_id is not None:
                updates.append("wechat_work_id = %s")
                params.append(normalized_wechat_work_id)
            if title is not None:
                updates.append("title = %s")
                params.append(UserService._normalize_optional_text_field(title))
            if role_id is not None:
                updates.append("role_id = %s")
                params.append(role_id)
            if dept_id is not None:
                updates.append("dept_id = %s")
                params.append(dept_id)
            if tenant_id is not None:
                updates.append("tenant_id = %s")
                params.append(tenant_id)
            if status is not None:
                updates.append("status = %s")
                params.append(status)
            if is_special is not None:
                updates.append("is_special = %s")
                params.append(int(is_special))
            if special_type is not None:
                updates.append("special_type = %s")
                params.append(UserService._normalize_optional_text_field(special_type))
            if external_agent_base_url is not None:
                updates.append("external_agent_base_url = %s")
                params.append(
                    UserService._normalize_optional_text_field(external_agent_base_url)
                )
            if external_agent_token is not None:
                normalized_external_agent_token = (
                    UserService._normalize_optional_text_field(external_agent_token)
                )
                encrypted = (
                    UserService._encrypt_wxwork_value(normalized_external_agent_token)
                    if normalized_external_agent_token
                    else ""
                )
                updates.append("external_agent_token = %s")
                params.append(encrypted)
            if password is not None:
                updates.append("password_hash = %s")
                params.append(UserService.hash_password(password))

            if not updates:
                return True

            params.append(user_id)
            query = f"UPDATE sys_users SET {', '.join(updates)} WHERE id = %s AND deleted_at IS NULL"

            cursor.execute(query, tuple(params))
            connection.commit()
            return True
        except ValueError:
            raise
        except IntegrityError as e:
            logger.error("Error updating user: {}", e)
            raise ValueError("同一租户下第三方 ID、企微 ID 或登录账号不能重复")
        except Exception as e:
            logger.error("Error updating user: {}", e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def delete_user(user_id: str):
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT username FROM sys_users WHERE id = %s AND deleted_at IS NULL",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            deleted_username = UserService._build_deleted_username(
                row.get("username"), user_id
            )
            cursor.execute(
                """
                UPDATE sys_users
                SET deleted_at = NOW(),
                    status = 0,
                    username = %s,
                    password_hash = NULL,
                    third_party_id = NULL,
                    wechat_work_id = NULL,
                    wxwork_bot_name = NULL,
                    wxwork_bot_id = NULL,
                    wxwork_secret = NULL,
                    role_id = NULL,
                    dept_id = NULL
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_username, user_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error deleting user: {}", e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def save_user_wxwork_bot_config(
        user_id: str,
        wxwork_bot_name: str,
        wxwork_bot_id: str,
        wxwork_secret: str,
    ) -> bool:
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            bot_config = UserService.validate_wxwork_bot_config(
                wxwork_bot_name,
                wxwork_bot_id,
                wxwork_secret,
                require_all=True,
            )
            cursor.execute(
                """
                UPDATE sys_users
                SET wxwork_bot_name = %s,
                    wxwork_bot_id = %s,
                    wxwork_secret = %s
                WHERE id = %s
                """,
                (
                    bot_config["wxwork_bot_name"],
                    bot_config["wxwork_bot_id"],
                    bot_config["wxwork_secret"],
                    user_id,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error saving user wxwork bot config: {}", e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
