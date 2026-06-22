"""模板缓存层。

通过 HTTP 调用 admin_serve 的运行时 API 获取模板数据，
本地缓存模板元信息和文件，供消费端同步调用。

降级策略：
1. 初始化时尝试连接 admin_api，成功则进入在线模式
2. 连接失败则进入离线模式，直接读取本地 template/ 目录
3. 在线模式下单次 API 调用失败不切换为离线模式，仅记录日志并使用已缓存数据
4. 连续 3 次调用失败后，切换为离线模式并每 5 分钟重试连接
"""

import json
import os
import shutil
import threading
import time
from typing import Optional

import requests
from loguru import logger

from workflow.config import BASE_DIR, get_admin_api_base

_CACHE_DIR_NAME = ".template_cache"
_POLL_INTERVAL = 300
_REQUEST_TIMEOUT = 10
_MAX_CONSECUTIVE_FAILURES = 3

_template_cache_instance: Optional["TemplateCache"] = None
_cache_lock = threading.Lock()


class TemplateCache:
    """模板缓存管理器，支持在线/离线双模式。"""

    def __init__(self):
        self._admin_api_base = get_admin_api_base()
        self._cache_dir = os.path.join(BASE_DIR, _CACHE_DIR_NAME)
        self._online = False
        self._consecutive_failures = 0
        self._templates: dict[str, dict] = {}
        self._last_poll_time = 0.0
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._initialized = False

    def initialize(self) -> None:
        """初始化缓存：尝试连接 admin_api 并加载模板数据。"""
        if self._initialized:
            return

        os.makedirs(self._cache_dir, exist_ok=True)

        try:
            self._fetch_and_cache_templates()
            self._online = True
            self._consecutive_failures = 0
            logger.info("TemplateCache 初始化成功（在线模式）")
        except Exception as e:
            logger.warning("TemplateCache 无法连接 admin_api，进入离线模式: {}", e)
            self._online = False
            self._load_fallback_data()

        self._start_poll_thread()
        self._initialized = True

    def _fetch_and_cache_templates(self) -> None:
        """从 admin_api 获取所有模板数据并缓存到内存。"""
        url = f"{self._admin_api_base}/templates/runtime/list"
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise RuntimeError(f"API 返回失败: {data}")

        templates = data.get("data", [])
        new_templates: dict[str, dict] = {}

        for tpl in templates:
            key = tpl.get("template_key", "")
            if not key:
                continue

            entry = {
                "template_key": key,
                "template_name": tpl.get("template_name", ""),
                "template_type": tpl.get("template_type", ""),
                "category_key": tpl.get("category_key", ""),
                "category_name": tpl.get("category_name", ""),
                "file_url": tpl.get("file_url", ""),
                "file_download_url": tpl.get("file_download_url", ""),
                "file_type": tpl.get("file_type", ""),
                "cover_url": tpl.get("cover_url", ""),
                "cover_download_url": tpl.get("cover_download_url", ""),
                "style_config": tpl.get("style_config"),
                "version": tpl.get("version", 1),
            }

            if entry["file_url"] and not entry["file_url"].startswith("http"):
                local_path = self._download_template_file(entry)
                if local_path:
                    entry["local_file_path"] = local_path

            new_templates[key] = entry

        self._templates = new_templates
        self._consecutive_failures = 0
        self._cleanup_stale_cache_files()

    def _download_template_file(self, entry: dict) -> Optional[str]:
        """下载模板文件到本地缓存目录。"""
        key = entry["template_key"]
        version = entry.get("version", 1)
        ext = entry.get("file_type", "bin")
        category = entry.get("category_key", "unknown")

        cache_filename = f"{key}_v{version}.{ext}"
        category_dir = os.path.join(self._cache_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        cache_path = os.path.join(category_dir, cache_filename)

        if os.path.exists(cache_path):
            return cache_path

        download_url = entry.get("file_download_url") or entry.get("file_url", "")
        if not download_url:
            return None

        try:
            if download_url.startswith("http"):
                resp = requests.get(download_url, timeout=30)
                resp.raise_for_status()
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
            else:
                src_path = os.path.join(BASE_DIR, download_url)
                if os.path.exists(src_path):
                    shutil.copy2(src_path, cache_path)
                else:
                    return None

            logger.debug("缓存模板文件: {} -> {}", key, cache_path)
            return cache_path
        except Exception as e:
            logger.error("下载模板文件失败 {}: {}", key, e)
            return None

    def _cleanup_stale_cache_files(self) -> None:
        """清理不在活跃模板列表中的缓存文件。"""
        active_files = set()
        for entry in self._templates.values():
            local_path = entry.get("local_file_path", "")
            if local_path and os.path.exists(local_path):
                active_files.add(os.path.normpath(local_path))

        for root, _dirs, files in os.walk(self._cache_dir):
            for fname in files:
                fpath = os.path.normpath(os.path.join(root, fname))
                if fpath not in active_files:
                    try:
                        os.remove(fpath)
                        logger.debug("清理过期缓存文件: {}", fpath)
                    except OSError:
                        pass

    def _load_fallback_data(self) -> None:
        """离线模式下从本地 template/ 目录加载模板数据。"""
        self._templates = {}

        report_dir = os.path.join(BASE_DIR, "template", "report-template")
        if os.path.isdir(report_dir):
            style_path = os.path.join(report_dir, "template_style.json")
            if os.path.exists(style_path):
                try:
                    with open(style_path, "r", encoding="utf-8") as f:
                        style_data = json.load(f)
                    for item in style_data:
                        tpl_type = str(item.get("template_type", ""))
                        tpl_name = item.get("template_name", "")
                        file_path = item.get("template_file_path", "")
                        style = item.get("template_style", {})

                        if isinstance(style, str):
                            try:
                                style = json.loads(style)
                            except json.JSONDecodeError:
                                style = {}

                        key = f"report-{tpl_type}"
                        local_path = ""
                        if file_path:
                            full_path = os.path.join(BASE_DIR, file_path)
                            if os.path.exists(full_path):
                                local_path = full_path

                        self._templates[key] = {
                            "template_key": key,
                            "template_name": tpl_name,
                            "template_type": tpl_type,
                            "category_key": "report",
                            "category_name": "报告模板",
                            "file_url": file_path,
                            "local_file_path": local_path,
                            "file_type": "docx",
                            "style_config": style,
                            "version": 1,
                        }
                except Exception as e:
                    logger.error("加载本地报告模板数据失败: {}", e)

        image_dir = os.path.join(BASE_DIR, "template", "image-template")
        if os.path.isdir(image_dir):
            image_mapping = {
                "2": "广西铝产品仓储交易中心模板.png",
                "3": "吉利科技集团模板.png",
                "4": "科技感模板.png",
                "5": "中央财经大学模板.png",
            }
            for tpl_type, filename in image_mapping.items():
                fpath = os.path.join(image_dir, filename)
                if os.path.exists(fpath):
                    key = f"image-{tpl_type}"
                    self._templates[key] = {
                        "template_key": key,
                        "template_name": filename.replace(".png", ""),
                        "template_type": tpl_type,
                        "category_key": "image",
                        "category_name": "图片模板",
                        "file_url": f"template/image-template/{filename}",
                        "local_file_path": fpath,
                        "file_type": "png",
                        "style_config": None,
                        "version": 1,
                    }

        video_dir = os.path.join(BASE_DIR, "template", "video-template")
        video_file = os.path.join(video_dir, "金融主播.png")
        if os.path.exists(video_file):
            self._templates["video-0"] = {
                "template_key": "video-0",
                "template_name": "金融主播",
                "template_type": "0",
                "category_key": "video",
                "category_name": "视频模板",
                "file_url": "template/video-template/金融主播.png",
                "local_file_path": video_file,
                "file_type": "png",
                "style_config": None,
                "version": 1,
            }

        logger.info("TemplateCache 离线模式加载 {} 个模板", len(self._templates))

    def _start_poll_thread(self) -> None:
        """启动定时轮询线程。"""
        if self._poll_thread and self._poll_thread.is_alive():
            return

        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="template-cache-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """定时轮询检查模板更新。"""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_POLL_INTERVAL)
            if self._stop_event.is_set():
                break

            try:
                self._fetch_and_cache_templates()
                if not self._online:
                    self._online = True
                    logger.info("TemplateCache 恢复在线模式")
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    if self._online:
                        self._online = False
                        logger.warning(
                            "TemplateCache 连续 {} 次失败，切换为离线模式",
                            self._consecutive_failures,
                        )
                logger.debug(
                    "TemplateCache 轮询失败 ({}/{}): {}",
                    self._consecutive_failures,
                    _MAX_CONSECUTIVE_FAILURES,
                    e,
                )

    def refresh(self) -> None:
        """手动触发缓存刷新。"""
        try:
            self._fetch_and_cache_templates()
            self._online = True
        except Exception as e:
            logger.error("手动刷新缓存失败: {}", e)

    def get_template_by_key(self, template_key: str) -> Optional[dict]:
        """按 template_key 获取模板数据。"""
        if not self._initialized:
            self.initialize()
        return self._templates.get(template_key)

    def get_template_by_type_sync(
        self, template_type: str, category: str = ""
    ) -> Optional[dict]:
        """按旧 template_type 编号同步获取模板数据。

        优先匹配 category_key + template_type，若无 category 则全量搜索。
        """
        if not self._initialized:
            self.initialize()

        for entry in self._templates.values():
            if str(entry.get("template_type", "")) == str(template_type):
                if category and entry.get("category_key") != category:
                    continue
                return entry

        return None

    def get_templates_by_category(self, category_key: str) -> list[dict]:
        """按分类获取模板列表。"""
        if not self._initialized:
            self.initialize()
        return [
            t for t in self._templates.values() if t.get("category_key") == category_key
        ]

    def get_all_templates(self) -> list[dict]:
        """获取所有缓存模板。"""
        if not self._initialized:
            self.initialize()
        return list(self._templates.values())

    @property
    def is_online(self) -> bool:
        """当前是否在线模式。"""
        return self._online

    def shutdown(self) -> None:
        """停止轮询线程。"""
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)


def get_template_cache() -> Optional[TemplateCache]:
    """获取全局 TemplateCache 单例。"""
    global _template_cache_instance
    if _template_cache_instance is None:
        with _cache_lock:
            if _template_cache_instance is None:
                try:
                    cache = TemplateCache()
                    cache.initialize()
                    _template_cache_instance = cache
                except Exception as e:
                    logger.error("创建 TemplateCache 失败: {}", e)
                    return None
    return _template_cache_instance


def shutdown_template_cache() -> None:
    """关闭全局 TemplateCache。"""
    global _template_cache_instance
    if _template_cache_instance:
        _template_cache_instance.shutdown()
        _template_cache_instance = None
