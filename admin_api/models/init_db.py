import os
import threading
import time
import uuid
from contextlib import contextmanager

from loguru import logger

mysql = None
try:
    import pymysql
    from pymysql import MySQLError as Error
except (
    ImportError
):  # Keep local/dev environments working until dependencies are refreshed.
    pymysql = None
    import mysql.connector
    from mysql.connector import Error


class _ManagedConnection:
    def __init__(self, connection, *, pool=None, use_pymysql: bool = False):
        self._connection = connection
        self._pool = pool
        self._use_pymysql = use_pymysql
        self._released = False

    def cursor(self, dictionary: bool = False):
        if self._use_pymysql:
            if dictionary:
                return self._connection.cursor(pymysql.cursors.DictCursor)
            return self._connection.cursor()
        if dictionary:
            return self._connection.cursor(dictionary=True)
        return self._connection.cursor()

    def is_connected(self) -> bool:
        if self._released or self._connection is None:
            return False
        if self._use_pymysql:
            return bool(getattr(self._connection, "open", False))
        try:
            return bool(self._connection.is_connected())
        except Exception:
            return bool(getattr(self._connection, "open", False))

    def close(self):
        if self._released:
            return None
        self._released = True
        if self._pool and self._connection is not None:
            self._pool.release(self._connection)
        else:
            try:
                if self._connection is not None:
                    self._connection.close()
            except Exception:
                pass
        self._connection = None
        return None

    def __getattr__(self, name):
        if self._connection is None:
            raise AttributeError(name)
        return getattr(self._connection, name)


class _MySQLConnectionPool:
    def __init__(
        self,
        *,
        pool_size: int,
        max_overflow: int,
        pool_recycle: int,
        use_pymysql: bool,
    ):
        self._pool_size = max(1, int(pool_size))
        self._max_overflow = max(0, int(max_overflow))
        self._pool_recycle = max(30, int(pool_recycle))
        self._use_pymysql = use_pymysql
        self._condition = threading.Condition()
        self._idle: list[tuple[object, float]] = []
        self._checked_out = 0
        self._total_created = 0

    def _close_raw(self, connection):
        try:
            connection.close()
        except Exception:
            pass

    @staticmethod
    def _rollback_quiet(connection) -> None:
        """Reset an open transaction before returning a connection to the pool."""
        try:
            connection.rollback()
        except Exception:
            pass

    def _is_alive(self, connection) -> bool:
        try:
            if self._use_pymysql:
                connection.ping(reconnect=False)
                return bool(getattr(connection, "open", False))
            connection.ping(reconnect=False, attempts=1, delay=0)
            try:
                return bool(connection.is_connected())
            except Exception:
                return bool(getattr(connection, "open", False))
        except Exception:
            return bool(getattr(connection, "open", False))

    def _create_connection(self):
        return connect_mysql_raw(
            host=os.getenv("WORKMATE_DB_HOST"),
            database=os.getenv("WORKMATE_DB_DATABASE"),
            user=os.getenv("WORKMATE_DB_USER"),
            password=os.getenv("WORKMATE_DB_PASS"),
            port=os.getenv("WORKMATE_DB_PORT"),
        )

    def acquire(self):
        deadline = time.monotonic() + 3.0
        with self._condition:
            while True:
                while self._idle:
                    connection, created_at = self._idle.pop()
                    if (
                        time.monotonic() - created_at > self._pool_recycle
                        or not self._is_alive(connection)
                    ):
                        self._total_created = max(0, self._total_created - 1)
                        self._close_raw(connection)
                        continue
                    self._checked_out += 1
                    return _ManagedConnection(
                        connection,
                        pool=self,
                        use_pymysql=self._use_pymysql,
                    )

                if self._total_created < self._pool_size + self._max_overflow:
                    connection = self._create_connection()
                    self._total_created += 1
                    self._checked_out += 1
                    return _ManagedConnection(
                        connection,
                        pool=self,
                        use_pymysql=self._use_pymysql,
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("数据库连接池获取连接超时")
                self._condition.wait(timeout=remaining)

    def release(self, connection):
        with self._condition:
            self._rollback_quiet(connection)
            self._checked_out = max(0, self._checked_out - 1)
            if not self._is_alive(connection):
                self._total_created = max(0, self._total_created - 1)
                self._close_raw(connection)
            elif len(self._idle) < self._pool_size:
                self._idle.append((connection, time.monotonic()))
            else:
                self._total_created = max(0, self._total_created - 1)
                self._close_raw(connection)
            self._condition.notify()


_DB_POOL = None
_DB_POOL_LOCK = threading.Lock()


def connect_mysql_raw(**kwargs):
    """建立MySQL连接，设置合理的超时时间避免卡住"""
    kwargs = {
        key: value for key, value in kwargs.items() if value is not None and value != ""
    }
    if pymysql is None:
        # mysql.connector 设置连接超时
        kwargs.setdefault("connection_timeout", 3)
        return mysql.connector.connect(**kwargs)

    if kwargs.get("port") is not None:
        kwargs["port"] = int(kwargs["port"])
    kwargs.setdefault("charset", "utf8mb4")
    # pymysql 设置连接超时（connect_timeout 是TCP连接超时）
    kwargs.setdefault("connect_timeout", 3)
    return pymysql.connect(**kwargs)


def connect_mysql(**kwargs):
    raw = connect_mysql_raw(**kwargs)
    return _ManagedConnection(raw, use_pymysql=pymysql is not None)


def _get_db_pool():
    global _DB_POOL
    if _DB_POOL is not None:
        return _DB_POOL
    with _DB_POOL_LOCK:
        if _DB_POOL is None:
            _DB_POOL = _MySQLConnectionPool(
                pool_size=int(os.getenv("WORKMATE_DB_POOL_SIZE", "8")),
                max_overflow=int(os.getenv("WORKMATE_DB_MAX_OVERFLOW", "8")),
                pool_recycle=int(os.getenv("WORKMATE_DB_POOL_RECYCLE", "1800")),
                use_pymysql=pymysql is not None,
            )
    return _DB_POOL


def get_db_connection():
    try:
        if not os.getenv("WORKMATE_DB_HOST") or not os.getenv("WORKMATE_DB_DATABASE"):
            return None
        connection = _get_db_pool().acquire()
        if connection.is_connected():
            return connection
    except Error as e:
        logger.error("Error connecting to MySQL database: {}", e)
    except TimeoutError as e:
        logger.error("Error acquiring MySQL pooled connection: {}", e)
    return None


@contextmanager
def db_cursor(dictionary: bool = False):
    connection = get_db_connection()
    cursor = None
    try:
        if not connection:
            yield None, None
            return
        cursor = connection.cursor(dictionary=dictionary)
        yield connection, cursor
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def init_admin_tables():
    connection = get_db_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        logger.info("Initializing admin tables...")
        # 租户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_tenants (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        # 部门表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_departments (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36),
                parent_id VARCHAR(36) NULL,
                name VARCHAR(100) NOT NULL,
                dept_code VARCHAR(100) NULL COMMENT '部门编码',
                manager_user_id VARCHAR(36) NULL COMMENT '负责人员工ID',
                third_party_id VARCHAR(100) NULL COMMENT '第三方系统关联ID',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_tenant_third_party_dept (tenant_id, third_party_id),
                UNIQUE KEY uk_tenant_dept_code (tenant_id, dept_code)
            )
        """)

        # 检查是否需要增加 dept_code 和 manager_user_id 字段 (兼容旧表)
        try:
            cursor.execute("SHOW COLUMNS FROM sys_departments LIKE 'dept_code'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_departments ADD COLUMN dept_code VARCHAR(100) NULL COMMENT '部门编码' AFTER name"
                )
                logger.info("Added dept_code column to sys_departments")

                # 同时添加 uk_tenant_dept_code 唯一索引
                cursor.execute(
                    "ALTER TABLE sys_departments ADD UNIQUE KEY uk_tenant_dept_code (tenant_id, dept_code)"
                )
                logger.info("Added uk_tenant_dept_code index to sys_departments")
        except Error as e:
            logger.error("Error checking/adding dept_code to sys_departments: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_departments LIKE 'manager_user_id'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_departments ADD COLUMN manager_user_id VARCHAR(36) NULL COMMENT '负责人员工ID' AFTER dept_code"
                )
                logger.info("Added manager_user_id column to sys_departments")
        except Error as e:
            logger.error(
                "Error checking/adding manager_user_id to sys_departments: {}", e
            )

        # 用户表（员工表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_users (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NULL,
                dept_id VARCHAR(36) NULL,
                username VARCHAR(50) NOT NULL COMMENT '登录账号',
                name VARCHAR(100) NULL COMMENT '页面显示名称',
                title VARCHAR(100) NULL COMMENT '职位',
                password_hash VARCHAR(255) NULL,
                third_party_id VARCHAR(100) NULL COMMENT '第三方系统关联ID',
                wechat_work_id VARCHAR(100) NULL COMMENT '企业微信用户ID',
                wxwork_bot_name VARCHAR(100) NULL COMMENT '企业微信机器人名称',
                wxwork_bot_id TEXT NULL COMMENT '企业微信机器人ID(加密存储)',
                wxwork_secret TEXT NULL COMMENT '企业微信机器人密钥(加密存储)',
                role_id VARCHAR(36),
                status TINYINT DEFAULT 1 COMMENT '1:active, 0:disabled',
                is_special TINYINT DEFAULT 0 COMMENT '是否特殊员工',
                special_type VARCHAR(50) NULL COMMENT '特殊员工类型',
                external_agent_base_url VARCHAR(255) NULL COMMENT '外部Agent地址',
                external_agent_token TEXT NULL COMMENT '外部Agent Token(加密存储)',
                deleted_at DATETIME NULL COMMENT '软删除时间，NULL表示未删除',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_tenant_third_party_user (tenant_id, third_party_id),
                UNIQUE KEY uk_tenant_wechat_work_user (tenant_id, wechat_work_id),
                UNIQUE KEY uk_username (username),
                KEY idx_users_tenant_created (tenant_id, created_at),
                KEY idx_users_dept_status_created (dept_id, status, created_at),
                KEY idx_users_role_status_created (role_id, status, created_at),
                KEY idx_users_title (title),
                KEY idx_users_deleted_at (deleted_at)
            )
        """)

        # 检查是否需要增加 password_hash 字段 (兼容旧表)
        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'username'")
            row = cursor.fetchone()
            if row and row[8] != "登录账号":
                cursor.execute(
                    "ALTER TABLE sys_users MODIFY COLUMN username VARCHAR(50) NOT NULL COMMENT '登录账号'"
                )
                logger.info("Updated username comment on sys_users")
        except Error as e:
            logger.error("Error checking/updating username comment on sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'name'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN name VARCHAR(100) NULL COMMENT '页面显示名称' AFTER username"
                )
                logger.info("Added name column to sys_users")
        except Error as e:
            logger.error("Error checking/adding name to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'title'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN title VARCHAR(100) NULL COMMENT '职位' AFTER name"
                )
                logger.info("Added title column to sys_users")
        except Error as e:
            logger.error("Error checking/adding title to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'password_hash'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN password_hash VARCHAR(255) NULL AFTER username"
                )
                logger.info("Added password_hash column to sys_users")
        except Error as e:
            logger.error("Error checking/adding password_hash to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'wxwork_bot_name'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN wxwork_bot_name VARCHAR(100) NULL COMMENT '企业微信机器人名称' AFTER wechat_work_id"
                )
                logger.info("Added wxwork_bot_name column to sys_users")
        except Error as e:
            logger.error("Error checking/adding wxwork_bot_name to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'wxwork_bot_id'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN wxwork_bot_id TEXT NULL COMMENT '企业微信机器人ID(加密存储)' AFTER wxwork_bot_name"
                )
                logger.info("Added wxwork_bot_id column to sys_users")
        except Error as e:
            logger.error("Error checking/adding wxwork_bot_id to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'wxwork_secret'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN wxwork_secret TEXT NULL COMMENT '企业微信机器人密钥(加密存储)' AFTER wxwork_bot_id"
                )
                logger.info("Added wxwork_secret column to sys_users")
        except Error as e:
            logger.error("Error checking/adding wxwork_secret to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'is_special'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN is_special TINYINT DEFAULT 0 COMMENT '是否特殊员工' AFTER status"
                )
                logger.info("Added is_special column to sys_users")
        except Error as e:
            logger.error("Error checking/adding is_special to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'special_type'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN special_type VARCHAR(50) NULL COMMENT '特殊员工类型' AFTER is_special"
                )
                logger.info("Added special_type column to sys_users")
        except Error as e:
            logger.error("Error checking/adding special_type to sys_users: {}", e)

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'external_agent_base_url'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN external_agent_base_url VARCHAR(255) NULL COMMENT '外部Agent地址' AFTER special_type"
                )
                logger.info("Added external_agent_base_url column to sys_users")
        except Error as e:
            logger.error(
                "Error checking/adding external_agent_base_url to sys_users: {}", e
            )

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'external_agent_token'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN external_agent_token TEXT NULL COMMENT '外部Agent Token(加密存储)' AFTER external_agent_base_url"
                )
                logger.info("Added external_agent_token column to sys_users")
        except Error as e:
            logger.error(
                "Error checking/adding external_agent_token to sys_users: {}", e
            )

        try:
            cursor.execute("SHOW COLUMNS FROM sys_users LIKE 'deleted_at'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD COLUMN deleted_at DATETIME NULL COMMENT '软删除时间，NULL表示未删除' AFTER external_agent_token"
                )
                logger.info("Added deleted_at column to sys_users")
        except Error as e:
            logger.error("Error checking/adding deleted_at to sys_users: {}", e)

        try:
            cursor.execute(
                "SHOW INDEX FROM sys_users WHERE Key_name = 'idx_users_title'"
            )
            if not cursor.fetchone():
                cursor.execute("CREATE INDEX idx_users_title ON sys_users (title)")
                logger.info("Added idx_users_title index to sys_users")
        except Error as e:
            logger.error("Error checking/adding idx_users_title to sys_users: {}", e)

        try:
            cursor.execute(
                "SHOW INDEX FROM sys_users WHERE Key_name = 'idx_users_deleted_at'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    "CREATE INDEX idx_users_deleted_at ON sys_users (deleted_at)"
                )
                logger.info("Added idx_users_deleted_at index to sys_users")
        except Error as e:
            logger.error(
                "Error checking/adding idx_users_deleted_at to sys_users: {}", e
            )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                user_id VARCHAR(36) NOT NULL,
                pref_key VARCHAR(100) NOT NULL,
                pref_value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_user_pref (user_id, pref_key),
                KEY idx_user_pref_user (user_id)
            )
        """)

        # 管理员表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_admin_users (
                id VARCHAR(36) PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role_id VARCHAR(36),
                status TINYINT DEFAULT 1 COMMENT '1:active, 0:disabled',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        logger.info("Admin tables initialized successfully.")

        # 角色表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_roles (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                code VARCHAR(50) NOT NULL UNIQUE,
                description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 菜单/权限表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_permissions (
                id VARCHAR(36) PRIMARY KEY,
                parent_id VARCHAR(36),
                name VARCHAR(50) NOT NULL,
                code VARCHAR(100) NOT NULL UNIQUE,
                type VARCHAR(20) COMMENT 'menu, button, api',
                path VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 角色-权限映射表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_role_permissions (
                role_id VARCHAR(36),
                permission_id VARCHAR(36),
                PRIMARY KEY (role_id, permission_id)
            )
        """)

        # 配置信息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_configs (
                config_key VARCHAR(100) PRIMARY KEY,
                config_type VARCHAR(50) NOT NULL COMMENT 'env, global, mcp, skills, wechat, etc.',
                config_value JSON NOT NULL,
                description VARCHAR(255),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        # MCP工具细粒度权限表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_mcp_tool_permissions (
                id VARCHAR(36) PRIMARY KEY,
                owner_type VARCHAR(20) NOT NULL COMMENT 'user, role, dept',
                owner_id VARCHAR(36) NOT NULL,
                server_name VARCHAR(100) NOT NULL,
                tool_name VARCHAR(100) NOT NULL COMMENT '* means all tools in server',
                action VARCHAR(20) NOT NULL COMMENT 'allow, deny',
                rules JSON NULL COMMENT 'extra rules like allowed_dirs',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_owner_server_tool (owner_type, owner_id, server_name, tool_name)
            )
        """)

        # Skills细粒度权限表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_permissions (
                id VARCHAR(36) PRIMARY KEY,
                owner_type VARCHAR(20) NOT NULL COMMENT 'user, role, dept',
                owner_id VARCHAR(36) NOT NULL,
                skill_name VARCHAR(100) NOT NULL,
                action VARCHAR(20) NOT NULL COMMENT 'allow, deny',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_owner_skill (owner_type, owner_id, skill_name)
            )
        """)

        # 客户端节点表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_clients (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                client_id VARCHAR(50) UNIQUE NOT NULL,
                client_secret VARCHAR(255) NOT NULL,
                status TINYINT DEFAULT 1,
                is_online TINYINT DEFAULT 0,
                last_heartbeat TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_client_user_sessions (
                client_key VARCHAR(100) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                user_type VARCHAR(20) NOT NULL COMMENT 'user, admin',
                username VARCHAR(50) NOT NULL,
                status TINYINT DEFAULT 1,
                is_online TINYINT DEFAULT 0,
                work_status VARCHAR(30) DEFAULT 'idle',
                current_task JSON NULL,
                last_heartbeat TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_online_heartbeat (is_online, last_heartbeat),
                KEY idx_user_type_id (user_type, user_id),
                KEY idx_user_online_heartbeat (user_id, is_online, last_heartbeat)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_packages (
                id VARCHAR(36) PRIMARY KEY,
                skill_name VARCHAR(100) NOT NULL,
                version VARCHAR(50) NOT NULL,
                description VARCHAR(255) NULL,
                file_name VARCHAR(255) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                sha256 VARCHAR(64) NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                is_active TINYINT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_skill_version (skill_name, version),
                KEY idx_skill_package_skill_created (skill_name, created_at)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_install_tasks (
                id VARCHAR(36) PRIMARY KEY,
                release_id VARCHAR(36) NULL,
                target_owner_type VARCHAR(20) NOT NULL,
                target_owner_id VARCHAR(36) NOT NULL,
                target_user_id VARCHAR(36) NOT NULL,
                client_id VARCHAR(100) NULL,
                skill_name VARCHAR(100) NOT NULL,
                target_version VARCHAR(50) NOT NULL,
                rollout_batch INT NOT NULL DEFAULT 0,
                retry_policy JSON NULL,
                status VARCHAR(30) NOT NULL,
                error_message TEXT NULL,
                started_at TIMESTAMP NULL,
                finished_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_releases (
                id VARCHAR(36) PRIMARY KEY,
                skill_name VARCHAR(100) NOT NULL,
                version VARCHAR(50) NOT NULL,
                strategy VARCHAR(20) NOT NULL DEFAULT 'hybrid' COMMENT 'active, passive, hybrid',
                rollout_type VARCHAR(20) NOT NULL COMMENT 'user, role, dept',
                rollout_id VARCHAR(36) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'draft' COMMENT 'draft, running, paused, completed, rollback',
                total_targets INT NOT NULL DEFAULT 0,
                batch_size INT NOT NULL DEFAULT 100,
                failure_threshold FLOAT NOT NULL DEFAULT 0.3,
                created_by VARCHAR(100) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_release_targets (
                id VARCHAR(36) PRIMARY KEY,
                release_id VARCHAR(36) NOT NULL,
                target_user_id VARCHAR(36) NOT NULL,
                rollout_batch INT NOT NULL DEFAULT 1,
                status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT 'pending, dispatched, success, failed, skipped',
                latest_task_id VARCHAR(36) NULL,
                last_error_message TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_release_user (release_id, target_user_id),
                KEY idx_release_batch_status (release_id, rollout_batch, status)
            )
        """)

        try:
            cursor.execute(
                "SHOW COLUMNS FROM sys_skill_install_tasks LIKE 'release_id'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_skill_install_tasks ADD COLUMN release_id VARCHAR(36) NULL AFTER id"
                )
        except Error as e:
            logger.error(
                "Error checking/adding release_id to sys_skill_install_tasks: {}", e
            )

        try:
            cursor.execute(
                "SHOW COLUMNS FROM sys_skill_install_tasks LIKE 'rollout_batch'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_skill_install_tasks ADD COLUMN rollout_batch INT NOT NULL DEFAULT 0 AFTER target_version"
                )
        except Error as e:
            logger.error(
                "Error checking/adding rollout_batch to sys_skill_install_tasks: {}",
                e,
            )

        try:
            cursor.execute(
                "SHOW COLUMNS FROM sys_skill_install_tasks LIKE 'retry_policy'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_skill_install_tasks ADD COLUMN retry_policy JSON NULL AFTER rollout_batch"
                )
        except Error as e:
            logger.error(
                "Error checking/adding retry_policy to sys_skill_install_tasks: {}", e
            )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sys_skill_inventories (
                id VARCHAR(36) PRIMARY KEY,
                client_id VARCHAR(100) NOT NULL,
                user_id VARCHAR(36) NULL,
                skill_name VARCHAR(100) NOT NULL,
                version VARCHAR(50) NOT NULL,
                installed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_client_skill (client_id, skill_name)
            )
        """)

        # 初始化超级管理员角色和用户
        cursor.execute("SELECT id FROM sys_roles WHERE code = 'super_admin'")
        admin_role = cursor.fetchone()

        if not admin_role:
            role_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO sys_roles (id, name, code, description) VALUES (%s, %s, %s, %s)",
                (role_id, "超级管理员", "super_admin", "系统最高权限"),
            )

            user_id = str(uuid.uuid4())
            # 默认密码 admin123 的 hash (实际中应使用 bcrypt)
            default_hash = "admin123"
            cursor.execute(
                "INSERT INTO sys_admin_users (id, username, password_hash, role_id) VALUES (%s, %s, %s, %s)",
                (user_id, "admin", default_hash, role_id),
            )

        # 协同任务链表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collab_chains (
                id VARCHAR(36) PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                description TEXT,
                initiator_user_id VARCHAR(36) NOT NULL,
                initiator_username VARCHAR(100) NOT NULL,
                status ENUM('defining','running','completed','cancelled') NOT NULL DEFAULT 'defining',
                current_step INT NOT NULL DEFAULT 0,
                total_steps INT NOT NULL DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_initiator (initiator_user_id),
                INDEX idx_status (status),
                INDEX idx_initiator_updated (initiator_user_id, updated_at),
                INDEX idx_status_updated (status, updated_at)
            )
        """)

        # 协同任务步骤表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collab_steps (
                id VARCHAR(36) PRIMARY KEY,
                chain_id VARCHAR(36) NOT NULL,
                step_index INT NOT NULL,
                assignee_user_id VARCHAR(36) NOT NULL,
                assignee_username VARCHAR(100) NOT NULL,
                task_prompt TEXT NOT NULL,
                task_prompt_rendered TEXT,
                note_from_previous TEXT,
                status ENUM('pending','running','completed','rejected') NOT NULL DEFAULT 'pending',
                result_summary TEXT,
                result_detail LONGTEXT,
                relay_note TEXT,
                reject_reason TEXT,
                started_at TIMESTAMP NULL,
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (chain_id) REFERENCES collab_chains(id) ON DELETE CASCADE,
                UNIQUE KEY uk_chain_step (chain_id, step_index),
                INDEX idx_assignee_status (assignee_user_id, status),
                INDEX idx_assignee_chain (assignee_user_id, chain_id)
            )
        """)

        # 协同附件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collab_attachments (
                id VARCHAR(36) PRIMARY KEY,
                chain_id VARCHAR(36) NOT NULL,
                step_id VARCHAR(36) NOT NULL,
                uploader_user_id VARCHAR(36) NOT NULL,
                original_filename VARCHAR(500) NOT NULL,
                stored_path VARCHAR(1000) NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                mime_type VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chain_id) REFERENCES collab_chains(id) ON DELETE CASCADE,
                INDEX idx_step (step_id)
            )
        """)

        # 协同消息表（用于离线消息存储）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collab_messages (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                message_type ENUM('collab_task_assigned','collab_chain_completed','collab_step_rejected') NOT NULL,
                message_payload JSON NOT NULL,
                is_read TINYINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_unread (user_id, is_read)
            )
        """)

        # 协同链按用户的未读/已读状态（桌面侧栏 NEW 标识）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collab_user_chain_state (
                user_id VARCHAR(64) NOT NULL,
                chain_id VARCHAR(64) NOT NULL,
                unread_at DATETIME NULL,
                read_at DATETIME NULL,
                PRIMARY KEY (user_id, chain_id),
                INDEX idx_collab_ucs_user_unread (user_id, unread_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 检查 sys_users 是否需要添加 uk_username 唯一索引（兼容旧表）
        try:
            cursor.execute("SHOW INDEX FROM sys_users WHERE Key_name = 'uk_username'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE sys_users ADD UNIQUE KEY uk_username (username)"
                )
                logger.info("Added uk_username unique index to sys_users")
        except Error as e:
            logger.error("Error checking/adding uk_username index: {}", e)

        try:
            cursor.execute(
                """
                UPDATE sys_users
                SET name = username
                WHERE name IS NULL OR TRIM(name) = ''
                """
            )
        except Error as e:
            logger.error("Error backfilling sys_users.name: {}", e)

        connection.commit()
        logger.info("Admin tables initialized successfully")

        # 初始化基础配置
        init_default_configs(cursor, connection)

    except Error as e:
        logger.error("Error initializing tables: {}", e)
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def init_default_configs(cursor, connection):
    """初始化默认配置，如果不存在的话，尝试从本地文件迁移"""
    import json

    # 初始化 env_config
    cursor.execute("SELECT config_key FROM sys_configs WHERE config_key = 'env_config'")
    if not cursor.fetchone():
        env_config = {
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
            "MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""),
            "DASHSCOPE_API_KEY": os.getenv("DASHSCOPE_API_KEY", ""),
            "RUNLOOP_API_KEY": os.getenv("RUNLOOP_API_KEY", ""),
            "OSS_ENDPOINT": os.getenv("OSS_ENDPOINT", ""),
            "OSS_REGION": os.getenv("OSS_REGION", ""),
            "OSS_BUCKET": os.getenv("OSS_BUCKET", ""),
            "OSS_ACCESS_KEY_ID": os.getenv("OSS_ACCESS_KEY_ID", ""),
            "OSS_ACCESS_KEY_SECRET": os.getenv("OSS_ACCESS_KEY_SECRET", ""),
            "OSS_AUTH_MODE": os.getenv("OSS_AUTH_MODE", "aksk"),
            "OSS_STS_TOKEN": os.getenv("OSS_STS_TOKEN", ""),
            "SKILL_INSTALL_TRIGGER_MODE": os.getenv(
                "SKILL_INSTALL_TRIGGER_MODE", "hybrid"
            ),
            "SKILL_AUTO_UPGRADE_MAX_CONCURRENCY": os.getenv(
                "SKILL_AUTO_UPGRADE_MAX_CONCURRENCY", "1"
            ),
            "SKILL_AUTO_UPGRADE_RETRY_TIMES": os.getenv(
                "SKILL_AUTO_UPGRADE_RETRY_TIMES", "2"
            ),
            "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC": os.getenv(
                "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC", "5"
            ),
            "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE": os.getenv(
                "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE", "100"
            ),
            "SKILL_ROLLOUT_FAILURE_THRESHOLD": os.getenv(
                "SKILL_ROLLOUT_FAILURE_THRESHOLD", "0.3"
            ),
        }
        cursor.execute(
            "INSERT INTO sys_configs (config_key, config_type, config_value, description) VALUES (%s, %s, %s, %s)",
            ("env_config", "env", json.dumps(env_config), "环境变量配置"),
        )

    # 初始化 global_config
    cursor.execute(
        "SELECT config_key FROM sys_configs WHERE config_key = 'global_config'"
    )
    if not cursor.fetchone():
        global_config = {
            "WECHAT_WORK_ALLOWED_USERS": os.getenv("WECHAT_WORK_ALLOWED_USERS", ""),
            "MCP_READ_ALLOWED_DIRS": os.getenv("MCP_READ_ALLOWED_DIRS", ""),
            "MCP_WRITE_ALLOWED_DIRS": os.getenv("MCP_WRITE_ALLOWED_DIRS", ""),
        }
        cursor.execute(
            "INSERT INTO sys_configs (config_key, config_type, config_value, description) VALUES (%s, %s, %s, %s)",
            ("global_config", "global", json.dumps(global_config), "全局运行参数"),
        )

    # 初始化 mcp_local_tools_config
    cursor.execute(
        "SELECT config_key FROM sys_configs WHERE config_key = 'mcp_local_tools_config'"
    )
    if not cursor.fetchone():
        # 根据 .env 默认值设定
        mcp_local_tools_config = {
            "MCP_ENABLE_WINDOWS_TOOLS": os.getenv(
                "MCP_ENABLE_WINDOWS_TOOLS", "false"
            ).lower()
            == "true",
            "MCP_ENABLE_ADVANCED_TOOLS": os.getenv(
                "MCP_ENABLE_ADVANCED_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_COMMON_TOOLS": os.getenv(
                "MCP_ENABLE_COMMON_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_DOCUMENT_TOOLS": os.getenv(
                "MCP_ENABLE_DOCUMENT_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_EXECUTION_TOOLS": os.getenv(
                "MCP_ENABLE_EXECUTION_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_MEDIA_TOOLS": os.getenv(
                "MCP_ENABLE_MEDIA_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_SEARCH_TOOLS": os.getenv(
                "MCP_ENABLE_SEARCH_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_WECHAT_TOOLS": os.getenv(
                "MCP_ENABLE_WECHAT_TOOLS", "true"
            ).lower()
            == "true",
            "MCP_ENABLE_HAPP_TOOLS": os.getenv("MCP_ENABLE_HAPP_TOOLS", "true").lower()
            == "true",
        }
        cursor.execute(
            "INSERT INTO sys_configs (config_key, config_type, config_value, description) VALUES (%s, %s, %s, %s)",
            (
                "mcp_local_tools_config",
                "mcp_tools",
                json.dumps(mcp_local_tools_config),
                "本地MCP工具模块开关",
            ),
        )

    # 迁移 MCP servers
    cursor.execute(
        "SELECT config_key FROM sys_configs WHERE config_key = 'mcp_servers'"
    )
    if not cursor.fetchone():
        mcp_config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "mcp_servers.json",
        )
        mcp_servers = []
        if os.path.exists(mcp_config_path):
            try:
                with open(mcp_config_path, "r", encoding="utf-8") as f:
                    mcp_servers = json.load(f)
            except Exception as e:
                logger.error("Error loading mcp_servers.json: {}", e)
        cursor.execute(
            "INSERT INTO sys_configs (config_key, config_type, config_value, description) VALUES (%s, %s, %s, %s)",
            ("mcp_servers", "mcp", json.dumps(mcp_servers), "MCP服务器配置"),
        )

    # 迁移 Skills config
    cursor.execute(
        "SELECT config_key FROM sys_configs WHERE config_key = 'skills_config'"
    )
    if not cursor.fetchone():
        skills_config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "skills_config.json",
        )
        skills_config = {}
        if os.path.exists(skills_config_path):
            try:
                with open(skills_config_path, "r", encoding="utf-8") as f:
                    skills_config = json.load(f)
            except Exception as e:
                logger.error("Error loading skills_config.json: {}", e)
        cursor.execute(
            "INSERT INTO sys_configs (config_key, config_type, config_value, description) VALUES (%s, %s, %s, %s)",
            ("skills_config", "skills", json.dumps(skills_config), "技能启用状态配置"),
        )

    connection.commit()
    logger.info("Default configs initialized/migrated successfully")


def init_knowledge_tables():
    """初始化知识库相关表（kb_categories + kb_files），支持公司/个人知识库。"""
    connection = get_db_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        logger.info("Initializing knowledge tables...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kb_categories (
                id           VARCHAR(36)   PRIMARY KEY COMMENT '分类UUID',
                username     VARCHAR(100)  NOT NULL    COMMENT '所属用户（AGENT_USERNAME）',
                kb_type      VARCHAR(20)   NOT NULL DEFAULT 'personal' COMMENT '知识库类型：personal-个人, company-公司',
                name         VARCHAR(100)  NOT NULL    COMMENT '分类安全名称（原目录名）',
                display_name VARCHAR(200)  NOT NULL    COMMENT '分类显示名称',
                created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                UNIQUE KEY uk_user_type_category (username, kb_type, name),
                INDEX idx_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='知识库分类表'
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kb_files (
                id                VARCHAR(36)   PRIMARY KEY COMMENT '文件UUID',
                username          VARCHAR(100)  NOT NULL    COMMENT '所属用户（AGENT_USERNAME）',
                kb_type           VARCHAR(20)   NOT NULL DEFAULT 'personal' COMMENT '知识库类型：personal-个人, company-公司',
                category_id       VARCHAR(36)   NOT NULL    COMMENT '所属分类ID',
                category_name     VARCHAR(100)  NOT NULL    COMMENT '所属分类安全名称（冗余，便于查询）',
                original_filename VARCHAR(500)  NOT NULL    COMMENT '原始文件名',
                md_filename       VARCHAR(500)  NOT NULL    COMMENT 'Markdown文件名',
                file_type         VARCHAR(20)   NOT NULL    COMMENT '文件类型（docx/pdf/url等）',
                file_size         BIGINT        NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
                summary           LONGTEXT      NULL        COMMENT 'LLM生成的结构化摘要',
                md_content        LONGTEXT      NOT NULL    COMMENT 'Markdown正文内容（原.md文件内容）',
                source_url        VARCHAR(2000) NULL        COMMENT 'URL来源（仅url类型文件）',
                created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                INDEX idx_username (username),
                INDEX idx_user_type_category (username, kb_type, category_name),
                FOREIGN KEY (category_id) REFERENCES kb_categories(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='知识库文件表'
        """)

        # 知识库分享记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kb_shares (
                id             VARCHAR(36)   PRIMARY KEY COMMENT '分享记录UUID',
                file_id        VARCHAR(36)   NOT NULL    COMMENT '被分享的文件ID（kb_files.id）',
                owner_username VARCHAR(100)  NOT NULL    COMMENT '分享人（文件所有者）',
                target_username VARCHAR(100) NOT NULL    COMMENT '被分享人',
                category_name  VARCHAR(100)  NOT NULL    COMMENT '文件所属分类名（冗余，便于展示）',
                created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '分享时间',
                updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                UNIQUE KEY uk_file_target (file_id, target_username),
                INDEX idx_owner (owner_username),
                INDEX idx_target (target_username),
                FOREIGN KEY (file_id) REFERENCES kb_files(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='知识库分享记录表'
        """)

        connection.commit()

        _migrate_knowledge_kb_type(cursor)
        connection.commit()

        logger.info("Knowledge tables initialized successfully")

    except Error as e:
        logger.error("Error initializing knowledge tables: {}", e)
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def _migrate_knowledge_kb_type(cursor):
    """兼容旧表：为已有 kb_categories / kb_files 增加 kb_type 字段和索引。"""
    try:
        cursor.execute("SHOW COLUMNS FROM kb_categories LIKE 'kb_type'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE kb_categories "
                "ADD COLUMN kb_type VARCHAR(20) NOT NULL DEFAULT 'personal' "
                "COMMENT '知识库类型：personal-个人, company-公司' "
                "AFTER username"
            )
            cursor.execute("ALTER TABLE kb_categories DROP INDEX uk_user_category")
            cursor.execute(
                "ALTER TABLE kb_categories "
                "ADD UNIQUE KEY uk_user_type_category (username, kb_type, name)"
            )
            logger.info(
                "Migrated kb_categories: added kb_type column and updated index"
            )
    except Error as e:
        logger.error("Error migrating kb_categories kb_type: {}", e)

    try:
        cursor.execute("SHOW COLUMNS FROM kb_files LIKE 'kb_type'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE kb_files "
                "ADD COLUMN kb_type VARCHAR(20) NOT NULL DEFAULT 'personal' "
                "COMMENT '知识库类型：personal-个人, company-公司' "
                "AFTER username"
            )
            cursor.execute("ALTER TABLE kb_files DROP INDEX idx_user_category")
            cursor.execute(
                "ALTER TABLE kb_files "
                "ADD INDEX idx_user_type_category (username, kb_type, category_name)"
            )
            logger.info("Migrated kb_files: added kb_type column and updated index")
    except Error as e:
        logger.error("Error migrating kb_files kb_type: {}", e)


def init_template_tables():
    """初始化模板管理相关表（tpl_categories + tpl_templates）。"""
    connection = get_db_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        logger.info("Initializing template tables...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tpl_categories (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                category_key  VARCHAR(50)  NOT NULL UNIQUE  COMMENT '分类标识: report / image / video',
                category_name VARCHAR(100) NOT NULL          COMMENT '分类名称',
                description   VARCHAR(500) NULL              COMMENT '分类描述',
                sort_order    INT          NOT NULL DEFAULT 0 COMMENT '排序权重',
                created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='模板分类表'
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tpl_templates (
                id            VARCHAR(36)  PRIMARY KEY           COMMENT 'UUID主键',
                category_id   INT          NOT NULL             COMMENT '分类ID',
                template_key  VARCHAR(100) NOT NULL UNIQUE       COMMENT '模板唯一标识',
                template_name VARCHAR(200) NOT NULL              COMMENT '模板名称',
                template_type VARCHAR(50)  NOT NULL DEFAULT ''   COMMENT '兼容旧type编号',
                description   VARCHAR(500) NULL                  COMMENT '模板描述',
                cover_url     VARCHAR(2000) NULL                 COMMENT '模板封面图URL',
                file_url      VARCHAR(2000) NULL                 COMMENT '模板文件存储路径',
                file_name     VARCHAR(500)  NULL                 COMMENT '原始文件名',
                file_size     BIGINT        NOT NULL DEFAULT 0   COMMENT '文件大小(字节)',
                file_type     VARCHAR(20)   NOT NULL DEFAULT ''  COMMENT '文件类型',
                style_config  LONGTEXT      NULL                 COMMENT '样式配置JSON',
                version       INT           NOT NULL DEFAULT 1   COMMENT '模板版本号',
                is_active     TINYINT       NOT NULL DEFAULT 1   COMMENT '是否启用',
                sort_order    INT           NOT NULL DEFAULT 0   COMMENT '排序权重',
                created_by    VARCHAR(100)  NOT NULL DEFAULT ''  COMMENT '创建人',
                created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                deleted_at    DATETIME      NULL                  COMMENT '软删除时间',
                INDEX idx_category (category_id),
                INDEX idx_template_key (template_key),
                INDEX idx_template_type (template_type),
                INDEX idx_active (is_active),
                INDEX idx_deleted (deleted_at),
                FOREIGN KEY (category_id) REFERENCES tpl_categories(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='模板表'
        """)

        cursor.execute("SELECT COUNT(*) FROM tpl_categories")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO tpl_categories (category_key, category_name, description, sort_order) VALUES "
                "('report', '报告模板', 'Word/PDF 报告文档模板，包含 .docx 模板文件和样式配置', 1), "
                "('image', '图片模板', 'PPT/宣传图等图片生成模板，包含 .png 模板图片', 2), "
                "('video', '视频模板', '数字人视频生成模板，包含主播形象图片', 3)"
            )
            logger.info("Inserted default template categories")

        connection.commit()
        logger.info("Template tables initialized successfully")

    except Error as e:
        logger.error("Error initializing template tables: {}", e)
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    # init_admin_tables()
