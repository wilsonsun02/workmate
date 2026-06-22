import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import websockets

import requests
from typing import Optional
import yaml
from dotenv import load_dotenv
from loguru import logger


ADMIN_WS_PATH = "/api/admin/client/ws"
DEFAULT_ADMIN_WS_URL = f"ws://127.0.0.1:8010{ADMIN_WS_PATH}"


def normalize_admin_ws_url(raw_url: Optional[str]) -> str:
    if not raw_url:
        return DEFAULT_ADMIN_WS_URL

    raw_url = raw_url.strip()
    if not raw_url:
        return DEFAULT_ADMIN_WS_URL

    parsed = urlparse(raw_url)
    if not parsed.scheme:
        raw_url = f"ws://{raw_url}"
        parsed = urlparse(raw_url)

    scheme_map = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}
    scheme = scheme_map.get(parsed.scheme.lower(), parsed.scheme)
    path = parsed.path.rstrip("/")
    if not path:
        path = ADMIN_WS_PATH
    elif not path.endswith(ADMIN_WS_PATH):
        if path.endswith("/api/admin/client"):
            path = f"{path}/ws"
        elif path.endswith("/api/admin"):
            path = f"{path}/client/ws"
        else:
            path = f"{path}{ADMIN_WS_PATH}"

    return urlunparse(
        (
            scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


class CloudClient:
    def __init__(self, server_url: str = None):
        load_dotenv()
        self.client_id = os.getenv("WORKMATE_CLIENT_ID")
        self.client_secret = os.getenv("WORKMATE_CLIENT_SECRET")
        self.username = os.getenv("WORKMATE_USER")
        self.password = os.getenv("WORKMATE_PASSWORD")
        self.server_url = normalize_admin_ws_url(
            server_url
            or os.getenv("WORKMATE_ADMIN_WS_URL")
            or os.getenv("WORKMATE_CLOUD_URL")
        )

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self.reconnect_interval = 5
        self.heartbeat_interval = 30
        self.skills_dir = os.path.join(os.path.dirname(__file__), "skills")
        self.skill_market = []
        self.install_trigger_mode = "hybrid"
        self.install_max_concurrency = 1
        self.install_retry_times = 2
        self.install_retry_backoff_sec = 5
        self.install_queue: Optional[asyncio.Queue] = None
        # 协同任务相关
        self.current_work_status = "idle"
        self.current_collab_task = None
        self.pending_collab_tasks = []

    def has_credentials(self) -> bool:
        return bool(
            (self.client_id and self.client_secret) or (self.username and self.password)
        )

    async def connect(self):
        """建立连接并进行鉴权"""
        if not self.has_credentials():
            logger.error(
                "未配置 WORKMATE_CLIENT_ID/SECRET 或 WORKMATE_USER/PASSWORD，云端同步功能已禁用"
            )
            return False

        try:
            logger.info(f"正在连接到云端控制塔: {self.server_url} ...")
            self.websocket = await websockets.connect(self.server_url)

            # 优先使用用户名密码登录，否则使用 client_id 登录
            if self.username and self.password:
                login_data = {
                    "action": "user_login",
                    "username": self.username,
                    "password": self.password,
                }
            else:
                login_data = {
                    "action": "login",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }

            await self.websocket.send(json.dumps(login_data))

            # 等待第一条消息（通常是配置同步或错误信息）
            response = await self.websocket.recv()
            msg = json.loads(response)

            if msg.get("action") == "error":
                logger.error(f"登录失败: {msg.get('message')}")
                await self.websocket.close()
                return False

            if msg.get("action") == "config_sync":
                self._apply_configs(msg)
                await self._send_skill_inventory()
                if self.install_trigger_mode in ("passive", "hybrid"):
                    await self.websocket.send(
                        json.dumps({"action": "pull_install_tasks"})
                    )
                # 上报初始状态
                await self._send_work_status()
                logger.info("云端配置同步成功")
                return True

            return True
        except Exception as e:
            logger.error(f"连接云端失败: {e}")
            return False

    def _apply_configs(self, config_msg: dict):
        env_config = config_msg.get("env_config", {})
        for k, v in env_config.items():
            if v:
                os.environ[k] = str(v)
        self.install_trigger_mode = str(
            env_config.get("SKILL_INSTALL_TRIGGER_MODE", "hybrid")
        ).lower()
        if self.install_trigger_mode not in ("active", "passive", "hybrid"):
            self.install_trigger_mode = "hybrid"
        self.install_max_concurrency = max(
            1, int(env_config.get("SKILL_AUTO_UPGRADE_MAX_CONCURRENCY", 1))
        )
        self.install_retry_times = max(
            0, int(env_config.get("SKILL_AUTO_UPGRADE_RETRY_TIMES", 2))
        )
        self.install_retry_backoff_sec = max(
            1, int(env_config.get("SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC", 5))
        )

        global_config = config_msg.get("global_config", {})
        for k, v in global_config.items():
            if v:
                os.environ[k] = str(v)

        local_tools_config = config_msg.get("mcp_local_tools_config", {})
        for k, v in local_tools_config.items():
            os.environ[k] = str(v).lower()
        mcp_servers = config_msg.get("mcp_servers", [])
        logger.info(
            f"已从云端同步并应用了 {len(env_config) + len(global_config) + len(local_tools_config)} 项配置"
        )

    def _parse_local_skill(self, skill_dir: str):
        skill_name = os.path.basename(skill_dir)
        version = "0.0.1"
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            return {"name": skill_name, "version": version}
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
            if content.startswith("---"):
                end_idx = content.find("---", 3)
                if end_idx != -1:
                    metadata = yaml.safe_load(content[3:end_idx]) or {}
                    skill_name = metadata.get("name") or skill_name
                    version = str(metadata.get("version") or version)
        except Exception:
            pass
        return {"name": skill_name, "version": version}

    def _collect_skill_inventory(self):
        if not os.path.exists(self.skills_dir):
            return []
        inventory = []
        for item in os.listdir(self.skills_dir):
            path = os.path.join(self.skills_dir, item)
            if not os.path.isdir(path):
                continue
            if item.startswith("_"):
                continue
            skill = self._parse_local_skill(path)
            skill["installed_at"] = datetime.now().isoformat()
            inventory.append(skill)
        return inventory

    async def _send_skill_inventory(self):
        if not self.websocket:
            return
        inventory = self._collect_skill_inventory()
        await self.websocket.send(
            json.dumps({"action": "skill_inventory", "skills": inventory})
        )

    def _download_zip(self, url: str, target_path: str):
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        with open(target_path, "wb") as f:
            f.write(response.content)

    def _sha256(self, file_path: str):
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def _send_install_status(
        self, task_id: str, status: str, error_message: Optional[str] = None
    ):
        if not self.websocket:
            return
        await self.websocket.send(
            json.dumps(
                {
                    "action": "install_status",
                    "task_id": task_id,
                    "status": status,
                    "error_message": error_message,
                }
            )
        )

    async def _send_work_status(self):
        """向管理端上报工作状态"""
        if not self.websocket:
            return
        status_msg = {
            "action": "client_status_report",
            "status": self.current_work_status,
            "current_task": self.current_collab_task,
        }
        await self.websocket.send(json.dumps(status_msg))
        logger.debug(f"上报工作状态: {self.current_work_status}")

    def set_work_status(self, status: str, current_task: dict = None):
        """设置工作状态并上报"""
        self.current_work_status = status
        self.current_collab_task = current_task
        # 异步上报状态
        if self.is_running and self.websocket:
            asyncio.create_task(self._send_work_status())

    def _handle_collab_task_assigned(self, msg: dict):
        """处理协同任务分配消息（通知由桌面协同空间 + Admin WS 消费，不再写入对话 feed）"""
        chain_title = msg.get("chain_title")
        step_index = msg.get("step_index")

        logger.info(f"收到协同任务: {chain_title} - 步骤 {step_index}")

        if self.current_work_status == "busy":
            self.pending_collab_tasks.append(msg)
            logger.info(
                f"任务加入待处理队列，当前队列长度: {len(self.pending_collab_tasks)}"
            )
            return

    def _handle_collab_chain_completed(self, msg: dict):
        """处理协同链完成消息（桌面协同空间通过 Admin WS 刷新，不写对话 feed）"""
        chain_title = msg.get("chain_title")
        logger.info(f"协同链完成: {chain_title}")

    def _handle_collab_step_rejected(self, msg: dict):
        """处理步骤被退回消息（桌面协同空间通过 Admin WS 刷新，不写对话 feed）"""
        chain_title = msg.get("chain_title")
        rejected_step_index = msg.get("rejected_step_index")
        logger.info(f"步骤被退回: {chain_title} - 步骤 {rejected_step_index}")

    def _process_pending_collab_tasks(self):
        """处理待处理的协同任务队列"""
        if self.current_work_status != "idle" or not self.pending_collab_tasks:
            return

        # 处理队列中的第一个任务
        msg = self.pending_collab_tasks.pop(0)
        self._handle_collab_task_assigned(msg)
        logger.info(f"处理待处理队列任务，剩余: {len(self.pending_collab_tasks)}")

    async def _install_skill(self, msg: dict, suppress_failure_status: bool = False):
        task_id = msg.get("task_id")
        skill_name = msg.get("skill_name")
        target_version = str(msg.get("version"))
        download_url = msg.get("download_url")
        expected_sha = msg.get("sha256")
        if not task_id or not skill_name or not target_version or not download_url:
            return
        backup_dir = None
        target_dir = os.path.join(self.skills_dir, skill_name)
        try:
            await self._send_install_status(task_id, "downloading")
            os.makedirs(self.skills_dir, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.skills_dir) as td:
                zip_path = os.path.join(td, "skill.zip")
                await asyncio.to_thread(self._download_zip, download_url, zip_path)
                if expected_sha:
                    actual_sha = self._sha256(zip_path)
                    if actual_sha.lower() != str(expected_sha).lower():
                        raise RuntimeError("技能包哈希校验失败")
                await self._send_install_status(task_id, "installing")
                extract_dir = os.path.join(td, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    abs_target = os.path.abspath(extract_dir)
                    for member in zip_ref.infolist():
                        member_name = member.filename.replace("\\", "/")
                        if member_name.startswith("/") or ".." in member_name.split(
                            "/"
                        ):
                            raise RuntimeError("安装包路径非法")
                        member_target = os.path.abspath(
                            os.path.join(extract_dir, member_name)
                        )
                        if not member_target.startswith(abs_target):
                            raise RuntimeError("安装包路径非法")
                    zip_ref.extractall(extract_dir)
                skill_root = extract_dir
                items = os.listdir(extract_dir)
                if len(items) == 1 and os.path.isdir(
                    os.path.join(extract_dir, items[0])
                ):
                    skill_root = os.path.join(extract_dir, items[0])
                local = self._parse_local_skill(skill_root)
                if local["name"] != skill_name:
                    raise RuntimeError("技能名称与下发信息不一致")
                if str(local["version"]) != target_version:
                    raise RuntimeError("技能版本与下发信息不一致")
                backup_dir = (
                    f"{target_dir}_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
                if os.path.exists(target_dir):
                    shutil.move(target_dir, backup_dir)
                shutil.move(skill_root, target_dir)
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
            await self._send_skill_inventory()
            await self._send_install_status(task_id, "success")
            logger.info(f"技能安装成功: {skill_name}@{target_version}")
        except Exception as e:
            if backup_dir and os.path.exists(backup_dir):
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                shutil.move(backup_dir, target_dir)
            if not suppress_failure_status:
                await self._send_install_status(task_id, "failed", str(e))
            logger.error(f"技能安装失败: {skill_name}@{target_version}, error={e}")
            raise

    async def _enqueue_install(self, task: dict):
        if not self.install_queue:
            self.install_queue = asyncio.Queue()
        await self.install_queue.put(task)

    async def _install_with_retry(self, task: dict):
        attempts = self.install_retry_times + 1
        for idx in range(attempts):
            try:
                await self._install_skill(task, suppress_failure_status=True)
                return
            except Exception as e:
                if idx >= attempts - 1:
                    task_id = task.get("task_id")
                    if task_id:
                        await self._send_install_status(task_id, "failed", str(e))
                    return
                await asyncio.sleep(self.install_retry_backoff_sec * (2**idx))

    async def _install_worker(self, worker_name: str):
        while self.is_running and self.websocket:
            try:
                if not self.install_queue:
                    await asyncio.sleep(0.2)
                    continue
                task = await self.install_queue.get()
                try:
                    await self._install_with_retry(task)
                finally:
                    self.install_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"安装 worker({worker_name}) 异常: {e}")
                await asyncio.sleep(1)

    async def _heartbeat_loop(self):
        while self.is_running and self.websocket:
            try:
                await self.websocket.send(json.dumps({"action": "ping"}))
                logger.debug("Sent heartbeat ping")
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"发送心跳失败: {e}")
                break

    async def _receive_loop(self):
        while self.is_running and self.websocket:
            try:
                message = await self.websocket.recv()
                msg = json.loads(message)

                if msg.get("action") == "pong":
                    logger.debug("Received heartbeat pong")
                elif msg.get("action") == "config_sync":
                    self._apply_configs(msg)
                    if self.install_trigger_mode in ("passive", "hybrid"):
                        await self.websocket.send(
                            json.dumps({"action": "pull_install_tasks"})
                        )
                    logger.info("收到云端下发的实时配置更新")
                elif msg.get("action") == "skill_market":
                    self.skill_market = msg.get("skills", [])
                    logger.info(f"收到可安装技能列表: {len(self.skill_market)} 项")
                elif msg.get("action") == "install_skill":
                    await self._enqueue_install(msg)
                elif msg.get("action") == "install_tasks":
                    tasks = msg.get("tasks", [])
                    for task in tasks:
                        await self._enqueue_install(task)
                elif msg.get("action") == "collab_task_assigned":
                    self._handle_collab_task_assigned(msg)
                elif msg.get("action") == "collab_chain_completed":
                    self._handle_collab_chain_completed(msg)
                elif msg.get("action") == "collab_step_rejected":
                    self._handle_collab_step_rejected(msg)
                elif msg.get("action") == "error":
                    logger.error(f"云端错误: {msg.get('message')}")
            except Exception as e:
                logger.error(f"接收消息异常: {e}")
                break

    async def start(self):
        """启动客户端"""
        self.is_running = True
        while self.is_running:
            if await self.connect():
                self.install_queue = asyncio.Queue()
                worker_tasks = [
                    asyncio.create_task(self._install_worker(f"w{i + 1}"))
                    for i in range(self.install_max_concurrency)
                ]
                # 接收/心跳结束后终止安装 worker
                try:
                    await asyncio.gather(self._receive_loop(), self._heartbeat_loop())
                finally:
                    for task in worker_tasks:
                        task.cancel()
                    await asyncio.gather(*worker_tasks, return_exceptions=True)

            if not self.is_running:
                break

            logger.info(f"{self.reconnect_interval} 秒后尝试重新连接...")
            await asyncio.sleep(self.reconnect_interval)

    async def stop(self):
        """停止客户端"""
        self.is_running = False
        if self.websocket:
            await self.websocket.close()
        logger.info("云端客户端已停止")


# 单例模式
_client: Optional[CloudClient] = None


def get_cloud_client():
    global _client
    if _client is None:
        _client = CloudClient()
    return _client


if __name__ == "__main__":
    # 测试运行
    client = get_cloud_client()
    try:
        asyncio.run(client.start())
    except KeyboardInterrupt:
        asyncio.run(client.stop())
