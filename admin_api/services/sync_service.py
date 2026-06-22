import uuid
from admin_api.services.config_service import ConfigService
from admin_api.models.init_db import connect_mysql, get_db_connection
from admin_api.services.user_service import UserService


class SyncService:
    @staticmethod
    def get_tenant_config(tenant_id: str):
        configs = ConfigService.get_config("third_party_dbs_config", [])
        for conf in configs:
            if conf.get("tenant_id") == tenant_id:
                return conf
        return None

    @staticmethod
    def sync_tenant_data(tenant_id: str):
        config = SyncService.get_tenant_config(tenant_id)
        if not config:
            raise Exception(f"未找到租户 {tenant_id} 的数据源配置")

        conn_config = config.get("connection", {})
        mapping = config.get("mapping", {})

        # 1. 连接外部数据库
        try:
            ext_conn = connect_mysql(
                host=conn_config.get("host"),
                port=int(conn_config.get("port", 3306)),
                user=conn_config.get("user"),
                password=conn_config.get("password"),
                database=conn_config.get("database"),
            )
            ext_cursor = ext_conn.cursor(dictionary=True)
        except Exception as e:
            raise Exception(f"连接第三方数据库失败: {e}")

        # 2. 获取本地连接
        local_conn = get_db_connection()
        if not local_conn:
            ext_conn.close()
            raise Exception("连接本地数据库失败")
        local_cursor = local_conn.cursor()

        stats = {"dept_synced": 0, "user_synced": 0}

        try:
            # --- 3. 同步部门数据 ---
            dept_table = mapping.get("dept_table")
            if dept_table:
                dept_id_field = mapping.get("dept_id_field", "id")
                dept_name_field = mapping.get("dept_name_field", "name")
                dept_parent_field = mapping.get("dept_parent_id_field", "parent_id")

                ext_cursor.execute(
                    f"SELECT {dept_id_field}, {dept_name_field}, {dept_parent_field} FROM {dept_table}"
                )
                departments = ext_cursor.fetchall()

                # 先收集所有外部 ID 到内部 ID 的映射，便于处理 parent_id
                ext_to_int_dept = {}

                # 第一遍：Upsert 所有部门
                for dept in departments:
                    ext_id = str(dept.get(dept_id_field))
                    name = dept.get(dept_name_field)

                    # 查找本地是否已有
                    local_cursor.execute(
                        "SELECT id FROM sys_departments WHERE tenant_id = %s AND third_party_id = %s",
                        (tenant_id, ext_id),
                    )
                    existing = local_cursor.fetchone()

                    if existing:
                        dept_uuid = existing[0]
                        local_cursor.execute(
                            "UPDATE sys_departments SET name = %s WHERE id = %s",
                            (name, dept_uuid),
                        )
                    else:
                        dept_uuid = str(uuid.uuid4())
                        local_cursor.execute(
                            "INSERT INTO sys_departments (id, tenant_id, name, third_party_id) VALUES (%s, %s, %s, %s)",
                            (dept_uuid, tenant_id, name, ext_id),
                        )
                    ext_to_int_dept[ext_id] = dept_uuid
                    stats["dept_synced"] += 1

                # 第二遍：更新 parent_id
                for dept in departments:
                    ext_id = str(dept.get(dept_id_field))
                    ext_parent = (
                        str(dept.get(dept_parent_field))
                        if dept.get(dept_parent_field)
                        else None
                    )
                    if ext_parent and ext_parent in ext_to_int_dept:
                        dept_uuid = ext_to_int_dept[ext_id]
                        parent_uuid = ext_to_int_dept[ext_parent]
                        local_cursor.execute(
                            "UPDATE sys_departments SET parent_id = %s WHERE id = %s",
                            (parent_uuid, dept_uuid),
                        )

            # --- 4. 同步用户数据 ---
            user_table = mapping.get("user_table")
            if user_table:
                user_id_field = mapping.get("user_id_field", "id")
                user_name_field = mapping.get("user_name_field", "username")
                user_display_name_field = (
                    mapping.get("user_display_name_field") or user_name_field
                )
                user_dept_field = mapping.get("user_dept_id_field", "dept_id")
                user_select_fields = [user_id_field, user_name_field, user_dept_field]
                if user_display_name_field not in user_select_fields:
                    user_select_fields.append(user_display_name_field)

                ext_cursor.execute(
                    f"SELECT {', '.join(user_select_fields)} FROM {user_table}"
                )
                users = ext_cursor.fetchall()

                for user in users:
                    ext_id = str(user.get(user_id_field))
                    username = user.get(user_name_field)
                    display_name = user.get(user_display_name_field) or username
                    ext_dept_id = (
                        str(user.get(user_dept_field))
                        if user.get(user_dept_field)
                        else None
                    )

                    # 转换部门ID
                    int_dept_id = None
                    if ext_dept_id:
                        local_cursor.execute(
                            "SELECT id FROM sys_departments WHERE tenant_id = %s AND third_party_id = %s",
                            (tenant_id, ext_dept_id),
                        )
                        dept_row = local_cursor.fetchone()
                        if dept_row:
                            int_dept_id = dept_row[0]

                    # 查找本地是否已有
                    local_cursor.execute(
                        "SELECT id FROM sys_users WHERE tenant_id = %s AND third_party_id = %s",
                        (tenant_id, ext_id),
                    )
                    existing = local_cursor.fetchone()

                    if existing:
                        user_uuid = existing[0]
                        local_cursor.execute(
                            "UPDATE sys_users SET username = %s, name = %s, dept_id = %s WHERE id = %s",
                            (username, display_name, int_dept_id, user_uuid),
                        )
                    else:
                        user_uuid = str(uuid.uuid4())
                        # 为同步的用户生成默认密码 (例如: workmate123)
                        default_password_hash = UserService.hash_password("workmate123")
                        local_cursor.execute(
                            "INSERT INTO sys_users (id, tenant_id, username, name, password_hash, third_party_id, dept_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (
                                user_uuid,
                                tenant_id,
                                username,
                                display_name,
                                default_password_hash,
                                ext_id,
                                int_dept_id,
                            ),
                        )
                    stats["user_synced"] += 1

            local_conn.commit()
            return stats

        except Exception as e:
            local_conn.rollback()
            raise Exception(f"同步过程中发生错误: {e}")
        finally:
            ext_cursor.close()
            ext_conn.close()
            local_cursor.close()
            local_conn.close()
