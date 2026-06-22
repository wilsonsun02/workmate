import json
from typing import Dict, Any, List, Optional

from loguru import logger

from admin_api.models.init_db import get_db_connection


class PermissionEngine:
    @staticmethod
    def _get_user_info(username: str) -> dict:
        """获取用户的角色和部门信息"""
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            # 首先尝试在 sys_users 表查找（企微用户/同步用户）
            cursor.execute(
                "SELECT id, role_id, dept_id FROM sys_users WHERE wechat_work_id = %s OR username = %s LIMIT 1",
                (username, username),
            )
            user = cursor.fetchone()

            if not user:
                # 其次尝试在 sys_admin_users 表查找（管理员）
                cursor.execute(
                    "SELECT id, role_id, NULL as dept_id FROM sys_admin_users WHERE username = %s LIMIT 1",
                    (username,),
                )
                user = cursor.fetchone()

            return user
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_user_mcp_permissions(username: str) -> Dict[str, Dict[str, Any]]:
        """
        计算用户最终的 MCP 工具权限。
        返回格式: {
            "server_name:tool_name": {
                "action": "allow" | "deny",
                "rules": {...}
            }
        }
        """
        user = PermissionEngine._get_user_info(username)
        if not user:
            return {}

        conn = get_db_connection()
        if not conn:
            return {}

        # 收集需要查询的所有 owner
        owners = []
        if user.get("dept_id"):
            owners.append(("dept", user["dept_id"], 1))  # 优先级最低
        if user.get("role_id"):
            owners.append(("role", user["role_id"], 2))
        owners.append(("user", user["id"], 3))  # 优先级最高

        final_permissions = {}

        try:
            cursor = conn.cursor(dictionary=True)
            for owner_type, owner_id, priority in owners:
                cursor.execute(
                    """
                    SELECT server_name, tool_name, action, rules 
                    FROM sys_mcp_tool_permissions 
                    WHERE owner_type = %s AND owner_id = %s
                """,
                    (owner_type, owner_id),
                )

                perms = cursor.fetchall()
                for p in perms:
                    key = f"{p['server_name']}:{p['tool_name']}"

                    # 如果不存在，或者当前权限优先级更高（因为我们按优先级顺序遍历，所以后遍历的直接覆盖）
                    final_permissions[key] = {
                        "action": p["action"],
                        "rules": json.loads(p["rules"]) if p["rules"] else {},
                    }
            return final_permissions
        except Exception as e:
            logger.error("Error fetching MCP permissions: {}", e)
            return {}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_user_mcp_service_permissions(username: str) -> Dict[str, str]:
        """
        计算用户最终的 MCP 服务级权限。
        返回格式: {"server_name": "allow" | "deny"}
        """
        user = PermissionEngine._get_user_info(username)
        if not user:
            return {}

        conn = get_db_connection()
        if not conn:
            return {}

        owners = []
        if user.get("dept_id"):
            owners.append(("dept", user["dept_id"]))
        if user.get("role_id"):
            owners.append(("role", user["role_id"]))
        owners.append(("user", user["id"]))

        final_permissions = {}

        try:
            cursor = conn.cursor(dictionary=True)
            for owner_type, owner_id in owners:
                cursor.execute(
                    """
                    SELECT server_name, action
                    FROM sys_mcp_service_permissions
                    WHERE owner_type = %s AND owner_id = %s
                """,
                    (owner_type, owner_id),
                )

                perms = cursor.fetchall()
                for p in perms:
                    # 后遍历的(优先级更高)覆盖先遍历的
                    final_permissions[p["server_name"]] = p["action"]
            return final_permissions
        except Exception as e:
            logger.error("Error fetching MCP service permissions: {}", e)
            return {}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_user_skill_permissions(username: str) -> Dict[str, str]:
        """
        计算用户最终的 Skill 权限。
        返回格式: {"skill_name": "allow" | "deny"}
        """
        user = PermissionEngine._get_user_info(username)
        if not user:
            return {}

        conn = get_db_connection()
        if not conn:
            return {}

        owners = []
        if user.get("dept_id"):
            owners.append(("dept", user["dept_id"]))
        if user.get("role_id"):
            owners.append(("role", user["role_id"]))
        owners.append(("user", user["id"]))

        final_permissions = {}

        try:
            cursor = conn.cursor(dictionary=True)
            for owner_type, owner_id in owners:
                cursor.execute(
                    """
                    SELECT skill_name, action 
                    FROM sys_skill_permissions 
                    WHERE owner_type = %s AND owner_id = %s
                """,
                    (owner_type, owner_id),
                )

                perms = cursor.fetchall()
                for p in perms:
                    # 后遍历的(优先级更高)覆盖先遍历的
                    final_permissions[p["skill_name"]] = p["action"]
            return final_permissions
        except Exception as e:
            logger.error("Error fetching Skill permissions: {}", e)
            return {}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def filter_mcp_servers_by_explicit_allow(
        username: Optional[str], server_names: List[str]
    ) -> List[str]:
        """
        Runtime MCP server names aligned with Admin market / sys_mcp_service_permissions.

        - Blank username: no extra filter (local / legacy flows).
        - User not found in DB: no extra filter.
        - User found: only MCP servers with explicit action == "allow" are kept.
          Missing rows are treated as deny (Admin default-deny).
        """
        if not username or not str(username).strip():
            return list(server_names)
        user = PermissionEngine._get_user_info(username)
        if not user:
            return list(server_names)
        perms = PermissionEngine.get_user_mcp_service_permissions(username)
        return [n for n in server_names if perms.get(n) == "allow"]

    @staticmethod
    def filter_skills_by_explicit_allow(
        username: Optional[str], skill_names: List[str]
    ) -> List[str]:
        """
        Runtime skill names aligned with Admin skill_market / sys_skill_permissions.

        - Blank username: no extra filter (local / legacy flows).
        - User not found in DB: no extra filter.
        - User found: only skills with explicit action == \"allow\" are kept.
          Missing rows are treated as deny (Admin default-deny).
        """
        if not username or not str(username).strip():
            return list(skill_names)
        user = PermissionEngine._get_user_info(username)
        if not user:
            return list(skill_names)
        perms = PermissionEngine.get_user_skill_permissions(username)
        return [n for n in skill_names if perms.get(n) == "allow"]

    @staticmethod
    def get_user_mcp_service_permissions(username: str) -> Dict[str, str]:
        """
        Resolve MCP service-level permissions for a user.

        Returns: {"server_name": "allow" | "deny"} with user > role > dept precedence.
        """
        user = PermissionEngine._get_user_info(username)
        if not user:
            return {}

        conn = get_db_connection()
        if not conn:
            return {}

        owners = []
        if user.get("dept_id"):
            owners.append(("dept", user["dept_id"]))
        if user.get("role_id"):
            owners.append(("role", user["role_id"]))
        owners.append(("user", user["id"]))

        final_permissions: Dict[str, str] = {}
        try:
            cursor = conn.cursor(dictionary=True)
            for owner_type, owner_id in owners:
                cursor.execute(
                    """
                    SELECT server_name, action
                    FROM sys_mcp_service_permissions
                    WHERE owner_type = %s AND owner_id = %s
                    """,
                    (owner_type, owner_id),
                )
                for row in cursor.fetchall():
                    final_permissions[row["server_name"]] = row["action"]
            return final_permissions
        except Exception as e:
            logger.error("Error fetching MCP service permissions: {}", e)
            return {}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def filter_mcp_servers_by_explicit_allow(
        username: Optional[str], server_names: List[str]
    ) -> List[str]:
        """
        Keep only MCP servers with explicit allow for the user.

        Unknown users pass through unchanged (legacy/local flows).
        """
        if not username or not str(username).strip():
            return list(server_names)
        user = PermissionEngine._get_user_info(username)
        if not user:
            return list(server_names)
        perms = PermissionEngine.get_user_mcp_service_permissions(username)
        return [name for name in server_names if perms.get(name) == "allow"]
