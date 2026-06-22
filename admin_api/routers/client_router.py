import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Optional, Dict
import uuid
import json
import os
import secrets
import string
from datetime import datetime, timedelta
from admin_api.models.init_db import get_db_connection
from admin_api.services.config_service import ConfigService
from admin_api.services.env_file_service import EnvFileService
from admin_api.services.mcp_service import McpService
from admin_api.services.oss_service import OssService
from admin_api.services.user_service import UserService
from admin_api.services.skill_distribution_service import SkillDistributionService

from loguru import logger

router = APIRouter()


DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 90
DEFAULT_AUTH_TIMEOUT_SECONDS = 10


def get_heartbeat_timeout_seconds() -> int:
    raw_value = os.getenv("WORKMATE_CLIENT_HEARTBEAT_TIMEOUT_SECONDS")
    if not raw_value:
        return DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
    try:
        return max(30, int(raw_value))
    except ValueError:
        return DEFAULT_HEARTBEAT_TIMEOUT_SECONDS


def get_auth_timeout_seconds() -> int:
    raw_value = os.getenv("WORKMATE_CLIENT_AUTH_TIMEOUT_SECONDS")
    if not raw_value:
        return DEFAULT_AUTH_TIMEOUT_SECONDS
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_AUTH_TIMEOUT_SECONDS


def get_install_trigger_mode() -> str:
    env_cfg = ConfigService.get_config("env_config", {})
    mode = str(env_cfg.get("SKILL_INSTALL_TRIGGER_MODE", "hybrid")).lower()
    if mode not in ("active", "passive", "hybrid"):
        return "hybrid"
    return mode


def _parse_retry_policy(raw_value):
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _json_dumps_or_none(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _build_user_profile(user: Dict) -> Dict:
    user_type = "user" if "tenant_id" in user or "dept_id" in user else "admin"
    return {
        "user_id": user["id"],
        "user_type": user_type,
        "username": user.get("username") or user["id"],
        "status": int(user.get("status") or 0),
    }


def _build_client_env_config_payload() -> Dict:
    payload = EnvFileService.build_client_payload()
    return {
        "env_config": payload["env_config"],
        "global_config": payload["global_config"],
        "mcp_local_tools_config": payload["mcp_local_tools_config"],
        "flat_env_config": payload["flat_env_config"],
        "updated_at": payload["updated_at"],
        "source": payload["source"],
    }


async def _send_skill_market(
    websocket: WebSocket, user_id: str, client_id: str
) -> None:
    available = SkillDistributionService.get_enabled_allowed_skills_for_user(user_id)
    inventory_map = SkillDistributionService.get_inventory_for_client(client_id)
    for item in available:
        local = inventory_map.get(item["name"])
        installed_version = local["version"] if local else None
        item["installed_version"] = installed_version
        item["upgrade_available"] = bool(
            installed_version
            and str(installed_version) != str(item.get("latest_version"))
        )
    await websocket.send_text(
        json.dumps({"action": "skill_market", "skills": available})
    )


async def _send_mcp_market(websocket: WebSocket, username: str) -> None:
    available = McpService.get_allowed_servers_for_username(username)
    await websocket.send_text(
        json.dumps({"action": "mcp_market", "mcp_servers": available})
    )


def _get_user_profile_by_id(user_id: str) -> Optional[Dict]:
    conn = get_db_connection()
    if not conn:
        return None
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, username, status, tenant_id, dept_id FROM sys_users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone()
        if user:
            return _build_user_profile(user)

        cursor.execute(
            "SELECT id, username, status FROM sys_admin_users WHERE id = %s",
            (user_id,),
        )
        admin_user = cursor.fetchone()
        if admin_user:
            return _build_user_profile(admin_user)
        return None
    except Exception as e:
        logger.error("Error getting websocket user profile: {}", e)
        return None
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


class ClientCreate(BaseModel):
    name: str


class ClientUpdate(BaseModel):
    name: str
    status: int


class ClientResponse(BaseModel):
    id: str
    name: str
    type: str  # 'client' or 'user'
    identifier: str  # client_id or username
    client_secret: Optional[str] = None  # 只在创建返回或需要时展示
    status: int
    is_online: int
    last_heartbeat: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


def generate_random_string(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


@router.get("/", response_model=List[ClientResponse])
async def get_clients():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    result_list = []
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # 获取所有客户端节点
        cursor.execute("SELECT * FROM sys_clients ORDER BY created_at DESC")
        clients = cursor.fetchall()
        for c in clients:
            result_list.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "type": "client",
                    "identifier": c["client_id"],
                    "client_secret": c["client_secret"],
                    "status": c["status"],
                    "is_online": c["is_online"],
                    "last_heartbeat": c["last_heartbeat"],
                    "created_at": c["created_at"],
                    "updated_at": c["updated_at"],
                }
            )

        cutoff = datetime.now() - timedelta(seconds=get_heartbeat_timeout_seconds())
        cursor.execute(
            """
            SELECT client_key, user_id, user_type, username, status, last_heartbeat,
                   created_at, updated_at
            FROM sys_client_user_sessions
            WHERE is_online = 1
              AND last_heartbeat IS NOT NULL
              AND last_heartbeat >= %s
            ORDER BY last_heartbeat DESC
            """,
            (cutoff,),
        )
        session_rows = cursor.fetchall()
        seen_user_keys = set()
        for row in session_rows:
            seen_user_keys.add(row["client_key"])
            suffix = "管理员节点" if row["user_type"] == "admin" else "用户节点"
            result_list.append(
                {
                    "id": row["user_id"],
                    "name": f"{row['username']} ({suffix})",
                    "type": "user",
                    "identifier": row["username"],
                    "client_secret": None,
                    "status": row["status"],
                    "is_online": 1,
                    "last_heartbeat": row["last_heartbeat"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )

        for client_key in manager.get_online_user_keys():
            if client_key in seen_user_keys:
                continue
            profile = manager.user_profiles.get(client_key)
            if not profile:
                continue
            suffix = "管理员节点" if profile["user_type"] == "admin" else "用户节点"
            result_list.append(
                {
                    "id": profile["user_id"],
                    "name": f"{profile['username']} ({suffix})",
                    "type": "user",
                    "identifier": profile["username"],
                    "client_secret": None,
                    "status": profile["status"],
                    "is_online": 1,
                    "last_heartbeat": manager.get_last_heartbeat(client_key),
                    "created_at": manager.get_last_heartbeat(client_key),
                    "updated_at": manager.get_last_heartbeat(client_key),
                }
            )

        return result_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


@router.get("/env-file")
async def get_client_env_file():
    payload = _build_client_env_config_payload()
    return {
        "success": True,
        "env_config": payload["flat_env_config"],
        "updated_at": payload["updated_at"],
        "source": payload["source"],
    }


@router.post("/", response_model=ClientResponse)
async def create_client(client: ClientCreate):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        client_uuid = str(uuid.uuid4())
        client_id = f"client_{generate_random_string(16)}"
        client_secret = generate_random_string(32)

        cursor.execute(
            """INSERT INTO sys_clients (id, name, client_id, client_secret)
               VALUES (%s, %s, %s, %s)""",
            (client_uuid, client.name, client_id, client_secret),
        )
        conn.commit()

        cursor.execute("SELECT * FROM sys_clients WHERE id = %s", (client_uuid,))
        new_client = cursor.fetchone()
        return {
            "id": new_client["id"],
            "name": new_client["name"],
            "type": "client",
            "identifier": new_client["client_id"],
            "client_secret": new_client["client_secret"],
            "status": new_client["status"],
            "is_online": new_client["is_online"],
            "last_heartbeat": new_client["last_heartbeat"],
            "created_at": new_client["created_at"],
            "updated_at": new_client["updated_at"],
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


@router.put("/{client_id_uuid}")
async def update_client(client_id_uuid: str, client: ClientUpdate):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sys_clients SET name = %s, status = %s WHERE id = %s",
            (client.name, client.status, client_id_uuid),
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


@router.delete("/{client_id_uuid}")
async def delete_client(client_id_uuid: str):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sys_clients WHERE id = %s", (client_id_uuid,))
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


# --- WebSocket 管理 ---
class ConnectionManager:
    def __init__(self):
        # 记录 active connections: client_id/user_id -> websocket
        self.active_connections: Dict[str, WebSocket] = {}
        # 记录所有连接的最近心跳时间，用于判定半开连接
        self.last_heartbeats: Dict[str, datetime] = {}
        # 记录用户节点的心跳时间
        self.user_heartbeats: Dict[str, datetime] = {}
        # 记录用户工作状态
        self.client_status: Dict[str, Dict] = {}
        # 记录用户连接元信息，用于跨进程持久化在线状态
        self.user_profiles: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        await self.replace_connection(websocket, client_id)

    async def replace_connection(
        self, websocket: WebSocket, client_id: str, user_profile: Optional[Dict] = None
    ):
        old_websocket = self.active_connections.get(client_id)
        if old_websocket is not None and old_websocket is not websocket:
            try:
                await old_websocket.close(
                    code=1000, reason="replaced by newer connection"
                )
            except Exception:
                pass
        self.register_connection(websocket, client_id, user_profile)

    def register_connection(
        self, websocket: WebSocket, client_id: str, user_profile: Optional[Dict] = None
    ):
        now = datetime.now()
        self.active_connections[client_id] = websocket
        self.last_heartbeats[client_id] = now
        if client_id.startswith("user_"):
            if user_profile:
                self.user_profiles[client_id] = user_profile
            self.user_heartbeats[client_id] = now
            # 初始化用户状态
            self.client_status[client_id] = {
                "status": "idle",
                "current_task": None,
                "updated_at": now,
            }
            self.update_user_presence(client_id, 1, now)
        else:
            self.update_client_status(client_id, 1)

    def disconnect(self, client_id: str, websocket: Optional[WebSocket] = None):
        current = self.active_connections.get(client_id)
        if websocket is not None and current is not websocket:
            return
        if current is None:
            return

        del self.active_connections[client_id]
        self.last_heartbeats.pop(client_id, None)
        if client_id.startswith("user_"):
            self.user_heartbeats.pop(client_id, None)
            self.client_status.pop(client_id, None)
            self.update_user_presence(client_id, 0)
            self.user_profiles.pop(client_id, None)
        else:
            self.update_client_status(client_id, 0)

    def get_last_heartbeat(self, client_id: str) -> Optional[datetime]:
        return self.last_heartbeats.get(client_id) or self.user_heartbeats.get(
            client_id
        )

    def is_connection_online(
        self, client_id: str, now: Optional[datetime] = None
    ) -> bool:
        if client_id not in self.active_connections:
            return False
        last_heartbeat = self.get_last_heartbeat(client_id)
        if not last_heartbeat:
            return False
        now = now or datetime.now()
        return (now - last_heartbeat).total_seconds() <= get_heartbeat_timeout_seconds()

    def get_online_user_ids(self) -> List[str]:
        return [
            client_key.removeprefix("user_")
            for client_key in self.get_online_user_keys()
        ]

    def get_online_user_keys(self) -> List[str]:
        now = datetime.now()
        return [
            client_id
            for client_id in list(self.active_connections.keys())
            if client_id.startswith("user_")
            and self.is_connection_online(client_id, now)
        ]

    async def cleanup_stale_connections(self):
        now = datetime.now()
        stale_client_ids = [
            client_id
            for client_id in list(self.active_connections.keys())
            if not self.is_connection_online(client_id, now)
        ]
        for client_id in stale_client_ids:
            websocket = self.active_connections.get(client_id)
            self.disconnect(client_id, websocket)
            if websocket:
                try:
                    await websocket.close(code=1001, reason="heartbeat timeout")
                except Exception:
                    pass

    def cleanup_stale_client_rows(self):
        cutoff = datetime.now() - timedelta(seconds=get_heartbeat_timeout_seconds())
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sys_clients
                SET is_online = 0
                WHERE is_online = 1
                  AND (last_heartbeat IS NULL OR last_heartbeat < %s)
                """,
                (cutoff,),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error cleaning stale client rows: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def cleanup_stale_user_session_rows(self):
        cutoff = datetime.now() - timedelta(seconds=get_heartbeat_timeout_seconds())
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sys_client_user_sessions
                SET is_online = 0, work_status = 'offline'
                WHERE is_online = 1
                  AND (last_heartbeat IS NULL OR last_heartbeat < %s)
                """,
                (cutoff,),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error cleaning stale user session rows: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def update_client_status(self, client_id: str, is_online: int):
        if client_id.startswith("user_"):
            return
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            if is_online == 1:
                cursor.execute(
                    "UPDATE sys_clients SET is_online = 1, last_heartbeat = CURRENT_TIMESTAMP WHERE client_id = %s",
                    (client_id,),
                )
            else:
                cursor.execute(
                    "UPDATE sys_clients SET is_online = 0 WHERE client_id = %s",
                    (client_id,),
                )
            conn.commit()
        except Exception as e:
            logger.error("Error updating client status: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def update_heartbeat(self, client_id: str):
        now = datetime.now()
        self.last_heartbeats[client_id] = now
        if client_id.startswith("user_"):
            self.user_heartbeats[client_id] = now
            self.touch_user_presence(client_id, now)
            return
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sys_clients SET last_heartbeat = CURRENT_TIMESTAMP WHERE client_id = %s",
                (client_id,),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error updating client heartbeat: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def update_user_presence(
        self, client_key: str, is_online: int, heartbeat_at: Optional[datetime] = None
    ):
        profile = self.user_profiles.get(client_key)
        if not profile:
            return
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        heartbeat_at = heartbeat_at or datetime.now()
        work_status = "idle" if is_online else "offline"
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sys_client_user_sessions
                    (client_key, user_id, user_type, username, status, is_online,
                     work_status, current_task, last_heartbeat)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)
                ON DUPLICATE KEY UPDATE
                    user_id = VALUES(user_id),
                    user_type = VALUES(user_type),
                    username = VALUES(username),
                    status = VALUES(status),
                    is_online = VALUES(is_online),
                    work_status = VALUES(work_status),
                    current_task = VALUES(current_task),
                    last_heartbeat = VALUES(last_heartbeat)
                """,
                (
                    client_key,
                    profile["user_id"],
                    profile["user_type"],
                    profile["username"],
                    profile["status"],
                    is_online,
                    work_status,
                    heartbeat_at,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error updating user presence: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def touch_user_presence(
        self, client_key: str, heartbeat_at: Optional[datetime] = None
    ):
        profile = self.user_profiles.get(client_key)
        if not profile:
            return
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        heartbeat_at = heartbeat_at or datetime.now()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sys_client_user_sessions
                    (client_key, user_id, user_type, username, status, is_online,
                     work_status, current_task, last_heartbeat)
                VALUES (%s, %s, %s, %s, %s, 1, 'idle', NULL, %s)
                ON DUPLICATE KEY UPDATE
                    user_id = VALUES(user_id),
                    user_type = VALUES(user_type),
                    username = VALUES(username),
                    status = VALUES(status),
                    is_online = 1,
                    work_status = IF(work_status = 'offline', 'idle', work_status),
                    last_heartbeat = VALUES(last_heartbeat)
                """,
                (
                    client_key,
                    profile["user_id"],
                    profile["user_type"],
                    profile["username"],
                    profile["status"],
                    heartbeat_at,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error touching user presence: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    async def send_to_user(self, user_id: str, message: dict) -> bool:
        """向指定用户发送 WebSocket 消息"""
        client_key = f"user_{user_id}"
        websocket = self.active_connections.get(client_key)
        if not websocket:
            return False
        if not self.is_connection_online(client_key):
            self.disconnect(client_key, websocket)
            try:
                await websocket.close(code=1001, reason="heartbeat timeout")
            except Exception:
                pass
            return False
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error sending message to user {user_id}: {e}")
            self.disconnect(client_key, websocket)
        return False

    def get_user_status(self, user_id: str) -> dict:
        """获取用户在线状态和工作状态"""
        client_key = f"user_{user_id}"
        is_online = self.is_connection_online(client_key)

        if client_key in self.client_status:
            status_data = self.client_status[client_key]
            if is_online:
                return {
                    "is_online": True,
                    "work_status": status_data["status"],
                    "current_task": status_data["current_task"],
                    "updated_at": status_data["updated_at"].isoformat(),
                }

        persisted_status = self.get_persisted_user_status(user_id)
        if persisted_status:
            return persisted_status

        return {
            "is_online": is_online,
            "work_status": "offline" if not is_online else "idle",
            "current_task": None,
            "updated_at": datetime.now().isoformat(),
        }

    def get_users_status(self, user_ids: list[str]) -> dict[str, dict]:
        ids = [
            str(uid or "").strip() for uid in (user_ids or []) if str(uid or "").strip()
        ]
        if not ids:
            return {}

        now_iso = datetime.now().isoformat()
        result: dict[str, dict] = {}
        needs_persisted: list[str] = []

        for uid in ids:
            client_key = f"user_{uid}"
            is_online = self.is_connection_online(client_key)
            status_data = self.client_status.get(client_key)
            if is_online and status_data:
                result[uid] = {
                    "is_online": True,
                    "work_status": status_data.get("status"),
                    "current_task": status_data.get("current_task"),
                    "updated_at": status_data.get("updated_at").isoformat()
                    if status_data.get("updated_at")
                    else now_iso,
                }
            else:
                needs_persisted.append(uid)

        persisted = self.get_persisted_users_status(needs_persisted)
        for uid in needs_persisted:
            if uid in result:
                continue
            if uid in persisted:
                result[uid] = persisted[uid]
                continue
            client_key = f"user_{uid}"
            is_online = self.is_connection_online(client_key)
            result[uid] = {
                "is_online": is_online,
                "work_status": "offline" if not is_online else "idle",
                "current_task": None,
                "updated_at": now_iso,
            }

        return result

    def get_persisted_users_status(self, user_ids: list[str]) -> dict[str, dict]:
        ids = [
            str(uid or "").strip() for uid in (user_ids or []) if str(uid or "").strip()
        ]
        if not ids:
            return {}

        cutoff = datetime.now() - timedelta(seconds=get_heartbeat_timeout_seconds())
        conn = get_db_connection()
        if not conn:
            return {}

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(
                f"""
                SELECT s.user_id, s.is_online, s.work_status, s.current_task, s.updated_at
                FROM sys_client_user_sessions s
                JOIN (
                  SELECT user_id, MAX(last_heartbeat) AS max_heartbeat
                  FROM sys_client_user_sessions
                  WHERE user_id IN ({placeholders})
                    AND is_online = 1
                    AND last_heartbeat IS NOT NULL
                    AND last_heartbeat >= %s
                  GROUP BY user_id
                ) latest
                  ON s.user_id = latest.user_id
                 AND s.last_heartbeat = latest.max_heartbeat
                """,
                tuple(ids) + (cutoff,),
            )
            rows = cursor.fetchall() or []
            out: dict[str, dict] = {}
            for row in rows:
                current_task = row.get("current_task")
                if isinstance(current_task, str):
                    try:
                        current_task = json.loads(current_task)
                    except Exception:
                        pass
                out[str(row.get("user_id") or "")] = {
                    "is_online": bool(row.get("is_online")),
                    "work_status": row.get("work_status") or "idle",
                    "current_task": current_task,
                    "updated_at": row["updated_at"].isoformat()
                    if row.get("updated_at")
                    else datetime.now().isoformat(),
                }
            return out
        except Exception as e:
            logger.error("Error getting persisted user statuses: {}", e)
            return {}
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def get_persisted_user_status(self, user_id: str) -> Optional[dict]:
        cutoff = datetime.now() - timedelta(seconds=get_heartbeat_timeout_seconds())
        conn = get_db_connection()
        if not conn:
            return None
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT is_online, work_status, current_task, updated_at
                FROM sys_client_user_sessions
                WHERE user_id = %s
                  AND is_online = 1
                  AND last_heartbeat IS NOT NULL
                  AND last_heartbeat >= %s
                ORDER BY last_heartbeat DESC
                LIMIT 1
                """,
                (user_id, cutoff),
            )
            row = cursor.fetchone()
            if not row:
                return None

            current_task = row.get("current_task")
            if isinstance(current_task, str):
                try:
                    current_task = json.loads(current_task)
                except Exception:
                    pass

            return {
                "is_online": bool(row["is_online"]),
                "work_status": row.get("work_status") or "idle",
                "current_task": current_task,
                "updated_at": row["updated_at"].isoformat(),
            }
        except Exception as e:
            logger.error("Error getting persisted user status: {}", e)
            return None
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    def update_user_work_status(
        self, user_id: str, status: str, current_task: dict = None
    ):
        """更新用户工作状态"""
        client_key = f"user_{user_id}"
        if client_key not in self.active_connections:
            return
        self.client_status[client_key] = {
            "status": status,
            "current_task": current_task,
            "updated_at": datetime.now(),
        }
        self.update_user_work_status_row(client_key, status, current_task)

    def update_user_work_status_row(
        self, client_key: str, status: str, current_task: dict = None
    ):
        if client_key not in self.user_profiles:
            return
        conn = get_db_connection()
        if not conn:
            return
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sys_client_user_sessions
                SET work_status = %s, current_task = %s
                WHERE client_key = %s
                """,
                (status, _json_dumps_or_none(current_task), client_key),
            )
            conn.commit()
        except Exception as e:
            logger.error("Error updating user work status: {}", e)
        finally:
            if conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()


manager = ConnectionManager()


def authenticate_client(client_id: str, client_secret: str) -> bool:
    conn = get_db_connection()
    if not conn:
        return False
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, status FROM sys_clients WHERE client_id = %s AND client_secret = %s",
            (client_id, client_secret),
        )
        client = cursor.fetchone()
        if client and client["status"] == 1:
            return True
        return False
    except Exception as e:
        logger.error("Auth error: {}", e)
        return False
    finally:
        if conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = None
    user_id = None
    try:
        # 第一条消息必须是鉴权信息
        try:
            data = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=get_auth_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            await websocket.send_text(
                json.dumps({"action": "error", "message": "Authentication timeout"})
            )
            await websocket.close(code=1008, reason="authentication timeout")
            return
        msg = json.loads(data)

        is_authenticated = False
        current_username = None

        # 兼容节点凭证登录
        if msg.get("action") == "login":
            cid = msg.get("client_id")
            csecret = msg.get("client_secret")
            if authenticate_client(cid, csecret):
                client_id = cid
                is_authenticated = True
                await manager.replace_connection(websocket, client_id)

        # 新增用户账号密码登录
        elif msg.get("action") == "user_login":
            username = msg.get("username")
            password = msg.get("password")
            user = UserService.verify_password(username, password)
            if user and user.get("status") == 1:
                user_id = user["id"]
                client_id = f"user_{user['id']}"
                current_username = user.get("username") or username
                is_authenticated = True
                await manager.replace_connection(
                    websocket, client_id, _build_user_profile(user)
                )

        elif msg.get("action") == "token_login":
            token = str(msg.get("token") or "").strip()
            from admin_api.routers.auth_router import verify_token

            session = verify_token(token)
            if session:
                profile = _get_user_profile_by_id(session["user_id"])
                if profile and profile["status"] == 1:
                    user_id = profile["user_id"]
                    client_id = f"user_{user_id}"
                    current_username = profile.get("username")
                    is_authenticated = True
                    await manager.replace_connection(websocket, client_id, profile)

        if is_authenticated:
            logger.info("Admin client WebSocket authenticated: {}", client_id)
            trigger_mode = get_install_trigger_mode()
            configs = {
                "action": "config_sync",
                **_build_client_env_config_payload(),
                "mcp_servers": McpService.export_legacy_config_json(),
                "skills_config": ConfigService.get_config("skills_config", {}),
                "skills_catalog": SkillDistributionService.get_catalog(),
                "content_security_rules": ConfigService.get_config(
                    "content_security_rules", {}
                ),
            }
            await websocket.send_text(json.dumps(configs))
            if user_id:
                await _send_skill_market(websocket, user_id, client_id)
                if current_username:
                    await _send_mcp_market(websocket, current_username)
                if trigger_mode in ("active", "hybrid"):
                    pending_tasks = (
                        SkillDistributionService.list_pending_tasks_for_user(user_id)
                    )
                    for task in pending_tasks:
                        package = SkillDistributionService.get_package(
                            task["skill_name"], task["target_version"]
                        )
                        if not package:
                            continue
                        package_path = package.get("file_path", "")
                        if package_path and not os.path.exists(package_path):
                            download_url = OssService.generate_presigned_get_url(
                                package_path, 600
                            )
                        else:
                            token = SkillDistributionService.create_download_token(
                                package["id"], client_id
                            )
                            host = websocket.headers.get("host", "127.0.0.1:8009")
                            http_scheme = (
                                "https" if websocket.url.scheme == "wss" else "http"
                            )
                            download_url = f"{http_scheme}://{host}/api/admin/skills/packages/{package['id']}/download?token={token}&client_id={client_id}"
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "action": "install_skill",
                                    "task_id": task["id"],
                                    "release_id": task.get("release_id"),
                                    "rollout_batch": int(
                                        task.get("rollout_batch") or 0
                                    ),
                                    "retry_policy": _parse_retry_policy(
                                        task.get("retry_policy")
                                    ),
                                    "skill_name": task["skill_name"],
                                    "version": task["target_version"],
                                    "download_url": download_url,
                                    "sha256": package["sha256"],
                                }
                            )
                        )
        else:
            await websocket.send_text(
                json.dumps({"action": "error", "message": "Authentication failed"})
            )
            await websocket.close()
            return

        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=get_heartbeat_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning("WebSocket heartbeat timeout: {}", client_id)
                if client_id:
                    manager.disconnect(client_id, websocket)
                    client_id = None
                try:
                    await websocket.close(code=1001, reason="heartbeat timeout")
                except Exception:
                    pass
                return
            if client_id and manager.active_connections.get(client_id) is not websocket:
                try:
                    await websocket.close(
                        code=1000, reason="replaced by newer connection"
                    )
                except Exception:
                    pass
                return
            if client_id:
                manager.update_heartbeat(client_id)
            msg = json.loads(data)
            if msg.get("action") == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))
            elif msg.get("action") == "client_status_report" and user_id:
                # 处理员工状态上报
                work_status = msg.get("status", "idle")
                current_task = msg.get("current_task")
                manager.update_user_work_status(user_id, work_status, current_task)
                logger.debug(f"User {user_id} reported status: {work_status}")
            elif msg.get("action") == "skill_inventory":
                skills = msg.get("skills", [])
                for item in skills:
                    name = item.get("name")
                    version = item.get("version")
                    if not name or not version:
                        continue
                    SkillDistributionService.upsert_inventory(
                        client_id=client_id,
                        user_id=user_id,
                        skill_name=name,
                        version=str(version),
                        installed_at=item.get("installed_at"),
                    )
            elif msg.get("action") == "install_status":
                task_id = msg.get("task_id")
                status = msg.get("status")
                if task_id and status:
                    SkillDistributionService.update_install_task_status(
                        task_id=task_id,
                        status=status,
                        client_id=client_id,
                        error_message=msg.get("error_message"),
                    )
            elif msg.get("action") == "refresh_skill_market" and user_id:
                await _send_skill_market(websocket, user_id, client_id)
            elif (
                msg.get("action") == "refresh_mcp_market"
                and user_id
                and current_username
            ):
                await _send_mcp_market(websocket, current_username)
            elif msg.get("action") == "pull_install_tasks" and user_id:
                trigger_mode = get_install_trigger_mode()
                if trigger_mode == "active":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "action": "install_tasks",
                                "tasks": [],
                                "trigger_mode": trigger_mode,
                            }
                        )
                    )
                    continue
                pending_tasks = SkillDistributionService.list_pending_tasks_for_user(
                    user_id
                )
                tasks_payload = []
                for task in pending_tasks:
                    package = SkillDistributionService.get_package(
                        task["skill_name"], task["target_version"]
                    )
                    if not package:
                        continue
                    package_path = package.get("file_path", "")
                    if package_path and not os.path.exists(package_path):
                        download_url = OssService.generate_presigned_get_url(
                            package_path, 600
                        )
                    else:
                        token = SkillDistributionService.create_download_token(
                            package["id"], client_id
                        )
                        host = websocket.headers.get("host", "127.0.0.1:8009")
                        http_scheme = (
                            "https" if websocket.url.scheme == "wss" else "http"
                        )
                        download_url = f"{http_scheme}://{host}/api/admin/skills/packages/{package['id']}/download?token={token}&client_id={client_id}"
                    tasks_payload.append(
                        {
                            "task_id": task["id"],
                            "release_id": task.get("release_id"),
                            "rollout_batch": int(task.get("rollout_batch") or 0),
                            "retry_policy": _parse_retry_policy(
                                task.get("retry_policy")
                            ),
                            "skill_name": task["skill_name"],
                            "version": task["target_version"],
                            "download_url": download_url,
                            "sha256": package["sha256"],
                        }
                    )
                await websocket.send_text(
                    json.dumps(
                        {
                            "action": "install_tasks",
                            "tasks": tasks_payload,
                            "trigger_mode": trigger_mode,
                        }
                    )
                )

    except WebSocketDisconnect:
        if client_id:
            manager.disconnect(client_id, websocket)
    except Exception as e:
        logger.error("WebSocket error: {}", e)
        if client_id:
            manager.disconnect(client_id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass
