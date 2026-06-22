import json
import os
import uuid
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from loguru import logger

from admin_api.models.init_db import get_db_connection


class McpService:
    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value or {}, ensure_ascii=False)

    @staticmethod
    def _json_loads(value: Any, default: Any):
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    @staticmethod
    def _normalize_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, tool in enumerate(tools or []):
            tool_name = str(tool.get("tool_name") or "").strip()
            if not tool_name:
                continue
            normalized.append(
                {
                    "tool_name": tool_name,
                    "tool_description": str(tool.get("tool_description") or "").strip(),
                    "is_load": bool(tool.get("is_load", True)),
                    "sort_order": int(tool.get("sort_order", index)),
                }
            )
        return normalized

    @staticmethod
    def _sanitize_server_config(server_config: Dict[str, Any]) -> Dict[str, Any]:
        transport = str(server_config.get("transport") or "stdio").strip() or "stdio"
        sanitized = {"transport": transport}

        if transport == "stdio":
            sanitized["command"] = str(server_config.get("command") or "").strip()
            sanitized["args"] = [
                str(arg).strip()
                for arg in (server_config.get("args") or [])
                if str(arg).strip()
            ]
            sanitized["env"] = {
                str(k): str(v)
                for k, v in (server_config.get("env") or {}).items()
                if str(k).strip()
            }
            sanitized["url"] = ""
            sanitized["headers"] = {}
            return sanitized

        if transport in {"sse", "streamable_http"}:
            sanitized["command"] = ""
            sanitized["args"] = []
            sanitized["env"] = {}
            sanitized["url"] = str(server_config.get("url") or "").strip()
            sanitized["headers"] = {
                str(k): str(v)
                for k, v in (server_config.get("headers") or {}).items()
                if str(k).strip()
            }
            return sanitized

        return {
            "transport": transport,
            "command": str(server_config.get("command") or "").strip(),
            "args": [
                str(arg).strip()
                for arg in (server_config.get("args") or [])
                if str(arg).strip()
            ],
            "env": {
                str(k): str(v)
                for k, v in (server_config.get("env") or {}).items()
                if str(k).strip()
            },
            "url": str(server_config.get("url") or "").strip(),
            "headers": {
                str(k): str(v)
                for k, v in (server_config.get("headers") or {}).items()
                if str(k).strip()
            },
        }

    @staticmethod
    def normalize_server_payload(server: Dict[str, Any]) -> Dict[str, Any]:
        server_name = str(server.get("server_name") or "").strip()
        if not server_name:
            raise ValueError("服务器名称不能为空")

        server_config = server.get("server_config") or {}
        transport = str(server_config.get("transport") or "stdio").strip() or "stdio"
        if transport not in {"stdio", "sse", "streamable_http"}:
            raise ValueError("不支持的 transport 类型")

        normalized = {
            "server_name": server_name,
            "server_description": str(server.get("server_description") or "").strip(),
            "is_load": bool(server.get("is_load", True)),
            "skills": str(server.get("skills") or "").strip(),
            "server_config": McpService._sanitize_server_config(server_config),
            "tools": McpService._normalize_tools(server.get("tools")),
        }

        if transport == "stdio" and not normalized["server_config"]["command"]:
            raise ValueError("stdio 模式下 command 不能为空")
        if (
            transport in {"sse", "streamable_http"}
            and not normalized["server_config"]["url"]
        ):
            raise ValueError("远程模式下 url 不能为空")
        return normalized

    @staticmethod
    def _server_row_to_item(
        row: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "server_name": row["server_name"],
            "server_description": row.get("server_description") or "",
            "is_load": bool(row.get("is_load", 1)),
            "skills": row.get("skills") or "",
            "server_config": {
                "transport": row.get("transport") or "stdio",
                "command": row.get("command") or "",
                "args": McpService._json_loads(row.get("args_json"), []),
                "env": McpService._json_loads(row.get("env_json"), {}),
                "url": row.get("url") or "",
                "headers": McpService._json_loads(row.get("headers_json"), {}),
            },
            "tools": tools,
        }

    @staticmethod
    def _load_server_rows(
        cursor, where_clause: str = "", params: tuple = ()
    ) -> List[Dict[str, Any]]:
        query = f"""
            SELECT id, server_name, server_description, is_load, skills,
                   transport, command, args_json, env_json, url, headers_json
            FROM sys_mcp_servers
            {where_clause}
            ORDER BY updated_at DESC, server_name ASC
        """
        cursor.execute(query, params)
        return cursor.fetchall()

    @staticmethod
    def list_servers(enabled_only: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            where_clause = "WHERE is_load = 1" if enabled_only else ""
            rows = McpService._load_server_rows(cursor, where_clause=where_clause)
            if not rows:
                return []

            server_ids = [row["id"] for row in rows]
            cursor.execute(
                f"""
                SELECT server_id, tool_name, tool_description, is_load, sort_order
                FROM sys_mcp_server_tools
                WHERE server_id IN ({",".join(["%s"] * len(server_ids))})
                ORDER BY sort_order ASC, tool_name ASC
            """,
                tuple(server_ids),
            )
            tool_rows = cursor.fetchall()
            tools_map: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in server_ids}
            for tool_row in tool_rows:
                tools_map.setdefault(tool_row["server_id"], []).append(
                    {
                        "tool_name": tool_row["tool_name"],
                        "tool_description": tool_row.get("tool_description") or "",
                        "is_load": bool(tool_row.get("is_load", 1)),
                    }
                )

            return [
                McpService._server_row_to_item(row, tools_map.get(row["id"], []))
                for row in rows
            ]
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def list_servers_paginated(
        *,
        keyword: Optional[str] = None,
        enabled_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        conn = get_db_connection()
        if not conn:
            return [], 0
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            conditions: List[str] = []
            params: List[Any] = []

            if enabled_only:
                conditions.append("is_load = 1")

            normalized_keyword = str(keyword or "").strip()
            if normalized_keyword:
                like = f"%{normalized_keyword}%"
                conditions.append(
                    "("
                    "server_name LIKE %s OR "
                    "server_description LIKE %s OR "
                    "skills LIKE %s OR "
                    "transport LIKE %s OR "
                    "command LIKE %s OR "
                    "url LIKE %s"
                    ")"
                )
                params.extend([like, like, like, like, like, like])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor.execute(
                f"SELECT COUNT(*) AS total FROM sys_mcp_servers {where_clause}",
                tuple(params),
            )
            total = int((cursor.fetchone() or {}).get("total") or 0)

            cursor.execute(
                f"""
                SELECT id, server_name, server_description, is_load, skills,
                       transport, command, args_json, env_json, url, headers_json
                FROM sys_mcp_servers
                {where_clause}
                ORDER BY updated_at DESC, server_name ASC
                LIMIT %s OFFSET %s
                """,
                tuple(params) + (int(limit), int(offset)),
            )
            rows = cursor.fetchall() or []
            if not rows:
                return [], total

            server_ids = [row["id"] for row in rows]
            cursor.execute(
                f"""
                SELECT server_id, tool_name, tool_description, is_load, sort_order
                FROM sys_mcp_server_tools
                WHERE server_id IN ({",".join(["%s"] * len(server_ids))})
                ORDER BY sort_order ASC, tool_name ASC
                """,
                tuple(server_ids),
            )
            tool_rows = cursor.fetchall() or []
            tools_map: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in server_ids}
            for tool_row in tool_rows:
                tools_map.setdefault(tool_row["server_id"], []).append(
                    {
                        "tool_name": tool_row["tool_name"],
                        "tool_description": tool_row.get("tool_description") or "",
                        "is_load": bool(tool_row.get("is_load", 1)),
                    }
                )

            return (
                [
                    McpService._server_row_to_item(row, tools_map.get(row["id"], []))
                    for row in rows
                ],
                total,
            )
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def get_allowed_servers_for_username(username: str) -> List[Dict[str, Any]]:
        username = str(username or "").strip()
        if not username:
            return []

        from workflow.permission_engine import PermissionEngine

        enabled_servers = McpService.list_servers(enabled_only=True)
        if not enabled_servers:
            return []

        enabled_names = [
            item["server_name"] for item in enabled_servers if item.get("server_name")
        ]
        allowed_names = set(
            PermissionEngine.filter_mcp_servers_by_explicit_allow(
                username, enabled_names
            )
        )
        if not allowed_names:
            return []

        return [
            item for item in enabled_servers if item.get("server_name") in allowed_names
        ]

    @staticmethod
    def get_server(server_name: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            rows = McpService._load_server_rows(
                cursor, where_clause="WHERE server_name = %s", params=(server_name,)
            )
            if not rows:
                return None
            row = rows[0]
            cursor.execute(
                """
                SELECT tool_name, tool_description, is_load
                FROM sys_mcp_server_tools
                WHERE server_id = %s
                ORDER BY sort_order ASC, tool_name ASC
            """,
                (row["id"],),
            )
            tools = [
                {
                    "tool_name": item["tool_name"],
                    "tool_description": item.get("tool_description") or "",
                    "is_load": bool(item.get("is_load", 1)),
                }
                for item in cursor.fetchall()
            ]
            return McpService._server_row_to_item(row, tools)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def _replace_tools(cursor, server_id: str, tools: List[Dict[str, Any]]) -> None:
        cursor.execute(
            "DELETE FROM sys_mcp_server_tools WHERE server_id = %s", (server_id,)
        )
        if not tools:
            return
        values = [
            (
                str(uuid.uuid4()),
                server_id,
                tool["tool_name"],
                tool.get("tool_description") or "",
                1 if tool.get("is_load", True) else 0,
                tool.get("sort_order", index),
            )
            for index, tool in enumerate(tools)
        ]
        cursor.executemany(
            """
            INSERT INTO sys_mcp_server_tools
            (id, server_id, tool_name, tool_description, is_load, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            values,
        )

    @staticmethod
    def _delete_server_relations(cursor, server_id: str, server_name: str) -> None:
        cursor.execute(
            "DELETE FROM sys_mcp_server_tools WHERE server_id = %s", (server_id,)
        )
        cursor.execute(
            "DELETE FROM sys_mcp_tool_permissions WHERE server_name = %s",
            (server_name,),
        )
        cursor.execute(
            "DELETE FROM sys_mcp_service_permissions WHERE server_name = %s",
            (server_name,),
        )

    @staticmethod
    def create_server(server: Dict[str, Any]) -> Dict[str, Any]:
        payload = McpService.normalize_server_payload(server)
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM sys_mcp_servers WHERE server_name = %s",
                (payload["server_name"],),
            )
            if cursor.fetchone():
                raise ValueError("服务器名称已存在")

            server_id = str(uuid.uuid4())
            config = payload["server_config"]
            cursor.execute(
                """
                INSERT INTO sys_mcp_servers
                (id, server_name, server_description, is_load, skills, transport,
                 command, args_json, env_json, url, headers_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    server_id,
                    payload["server_name"],
                    payload["server_description"],
                    1 if payload["is_load"] else 0,
                    payload["skills"],
                    config["transport"],
                    config["command"],
                    json.dumps(config["args"], ensure_ascii=False),
                    json.dumps(config["env"], ensure_ascii=False),
                    config["url"],
                    json.dumps(config["headers"], ensure_ascii=False),
                ),
            )
            McpService._replace_tools(cursor, server_id, payload["tools"])
            conn.commit()
            return payload
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def update_server(server_name: str, server: Dict[str, Any]) -> Dict[str, Any]:
        payload = McpService.normalize_server_payload(
            {**server, "server_name": server_name}
        )
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM sys_mcp_servers WHERE server_name = %s",
                (server_name,),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("MCP 服务不存在")
            config = payload["server_config"]
            cursor.execute(
                """
                UPDATE sys_mcp_servers
                SET server_description = %s,
                    is_load = %s,
                    skills = %s,
                    transport = %s,
                    command = %s,
                    args_json = %s,
                    env_json = %s,
                    url = %s,
                    headers_json = %s
                WHERE server_name = %s
            """,
                (
                    payload["server_description"],
                    1 if payload["is_load"] else 0,
                    payload["skills"],
                    config["transport"],
                    config["command"],
                    json.dumps(config["args"], ensure_ascii=False),
                    json.dumps(config["env"], ensure_ascii=False),
                    config["url"],
                    json.dumps(config["headers"], ensure_ascii=False),
                    server_name,
                ),
            )
            McpService._replace_tools(cursor, existing["id"], payload["tools"])
            conn.commit()
            return payload
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def delete_server_by_id(server_id: str) -> bool:
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, server_name FROM sys_mcp_servers WHERE id = %s",
                (server_id,),
            )
            existing = cursor.fetchone()
            if not existing:
                return False
            McpService._delete_server_relations(
                cursor, existing["id"], existing["server_name"]
            )
            cursor.execute(
                "DELETE FROM sys_mcp_servers WHERE id = %s", (existing["id"],)
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def replace_all_servers(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = [
            McpService.normalize_server_payload(item) for item in (servers or [])
        ]
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, server_name FROM sys_mcp_servers")
            existing_rows = cursor.fetchall()
            existing_map = {row["server_name"]: row["id"] for row in existing_rows}
            incoming_names = {item["server_name"] for item in normalized}

            # 删除缺失项
            for old_name, old_id in existing_map.items():
                if old_name not in incoming_names:
                    McpService._delete_server_relations(cursor, old_id, old_name)
                    cursor.execute(
                        "DELETE FROM sys_mcp_servers WHERE id = %s",
                        (old_id,),
                    )

            for item in normalized:
                config = item["server_config"]
                if item["server_name"] in existing_map:
                    server_id = existing_map[item["server_name"]]
                    cursor.execute(
                        """
                        UPDATE sys_mcp_servers
                        SET server_description = %s,
                            is_load = %s,
                            skills = %s,
                            transport = %s,
                            command = %s,
                            args_json = %s,
                            env_json = %s,
                            url = %s,
                            headers_json = %s
                        WHERE id = %s
                    """,
                        (
                            item["server_description"],
                            1 if item["is_load"] else 0,
                            item["skills"],
                            config["transport"],
                            config["command"],
                            json.dumps(config["args"], ensure_ascii=False),
                            json.dumps(config["env"], ensure_ascii=False),
                            config["url"],
                            json.dumps(config["headers"], ensure_ascii=False),
                            server_id,
                        ),
                    )
                else:
                    server_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO sys_mcp_servers
                        (id, server_name, server_description, is_load, skills, transport,
                         command, args_json, env_json, url, headers_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            server_id,
                            item["server_name"],
                            item["server_description"],
                            1 if item["is_load"] else 0,
                            item["skills"],
                            config["transport"],
                            config["command"],
                            json.dumps(config["args"], ensure_ascii=False),
                            json.dumps(config["env"], ensure_ascii=False),
                            config["url"],
                            json.dumps(config["headers"], ensure_ascii=False),
                        ),
                    )
                McpService._replace_tools(cursor, server_id, item["tools"])

            conn.commit()
            return normalized
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    async def probe_server_tools(
        server_name: str, server_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        probe_config = {server_name: McpService._sanitize_server_config(server_config)}
        tool_rows: List[Dict[str, Any]] = []
        try:
            async with AsyncExitStack() as stack:
                probe_client = MultiServerMCPClient(probe_config)
                session = await stack.enter_async_context(
                    probe_client.session(server_name)
                )
                probe_tools = await load_mcp_tools(session, server_name=server_name)
                for index, tool in enumerate(probe_tools):
                    tool_rows.append(
                        {
                            "tool_name": tool.name,
                            "tool_description": tool.description or "",
                            "is_load": True,
                            "sort_order": index,
                        }
                    )
                logger.info(
                    "成功探测到 MCP 服务 {} 的 {} 个工具", server_name, len(tool_rows)
                )
                return tool_rows
        except Exception as error:
            logger.error("探测 MCP 服务 {} 失败: {}", server_name, error)
            raise HTTPException(
                status_code=422, detail=f"无法连接到该服务: {str(error)}"
            )

    @staticmethod
    def list_service_allocations(server_name: str) -> Dict[str, List[Dict[str, Any]]]:
        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT p.owner_id, p.action, u.username
                FROM sys_mcp_service_permissions p
                JOIN sys_users u ON p.owner_id = u.id
                WHERE p.server_name = %s AND p.owner_type = 'user'
            """,
                (server_name,),
            )
            users = cursor.fetchall()
            cursor.execute(
                """
                SELECT p.owner_id, p.action, r.name AS role_name
                FROM sys_mcp_service_permissions p
                JOIN sys_roles r ON p.owner_id = r.id
                WHERE p.server_name = %s AND p.owner_type = 'role'
            """,
                (server_name,),
            )
            roles = cursor.fetchall()
            cursor.execute(
                """
                SELECT p.owner_id, p.action, d.name AS dept_name
                FROM sys_mcp_service_permissions p
                JOIN sys_departments d ON p.owner_id = d.id
                WHERE p.server_name = %s AND p.owner_type = 'dept'
            """,
                (server_name,),
            )
            depts = cursor.fetchall()
            return {"users": users, "roles": roles, "depts": depts}
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_runtime_servers() -> List[Dict[str, Any]]:
        return McpService.list_servers(enabled_only=False)

    @staticmethod
    def export_legacy_config_json() -> List[Dict[str, Any]]:
        return McpService.list_servers(enabled_only=False)
