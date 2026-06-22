"""
任务执行器模块
负责执行定时任务，调用 main.py 运行实际任务
"""

import subprocess
import json
import threading
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from .database import SchedulerDatabase
from .models import TaskExecution, ExecutionStatus, TaskStatus
from .config import (
    MAIN_SCRIPT_PATH,
    TASK_EXECUTION_TIMEOUT,
    TASK_EXECUTION_SUBPROCESS_TIMEOUT,
)


from loguru import logger


def _append_desktop_task_feed(
    username: str,
    task_id: str,
    execution_id: str,
    task_description: str,
    status: str,
    result_text: str,
    execution_time: Optional[str] = None,
) -> None:
    """将定时任务执行摘要写入桌面端侧栏（非 checkpoint）。"""
    try:
        from .desktop_feed_storage import append_scheduler_desktop_result
        from .database import SchedulerDatabase

        db = SchedulerDatabase()
        task = db.get_task(task_id)
        append_scheduler_desktop_result(
            username=username,
            task_id=task_id,
            execution_id=execution_id,
            task_name=task.task_name if task else None,
            task_description=task_description or "",
            status=status,
            result_text=result_text or "",
            execution_time=execution_time,
        )
    except Exception as ex:
        logger.info("桌面端定时任务会话写入失败: {}", ex)


def _scheduler_output_root() -> str:
    """与 workflow.config 一致：优先 OUTPUT_BASE_DIR，否则 BASE_DIR/workspace，否则源码树。"""
    import os

    out = os.environ.get("OUTPUT_BASE_DIR", "").strip()
    if out:
        return os.path.normcase(os.path.normpath(os.path.expandvars(out)))
    base = os.environ.get("BASE_DIR", "").strip()
    if base:
        return os.path.normcase(
            os.path.normpath(os.path.join(os.path.expandvars(base), "workspace"))
        )
    return os.path.normcase(
        os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace"
            )
        )
    )


class TaskExecutor:
    """任务执行器类"""

    # 方案2：全局并发信号量，防止多个定时任务同时执行耗尽系统资源
    # 上限5个，兼顾多任务并行需求与SQLite/CPU资源安全
    _global_semaphore = threading.BoundedSemaphore(5)

    def __init__(self):
        """初始化执行器"""
        self.db = SchedulerDatabase()

    def execute(self, task_id: str, task_prompt: str, username: str) -> Dict[str, Any]:
        """
        执行任务

        Args:
            task_id: 任务ID
            task_prompt: 任务提示词
            username: 用户名

        Returns:
            执行结果字典
        """
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        # 创建执行记录
        execution = TaskExecution(
            execution_id=execution_id,
            task_id=task_id,
            username=username,
            start_time=datetime.now(),
            status=ExecutionStatus.RUNNING,
            progress=0,
        )
        self.db.create_execution(execution)

        logger.info(f"开始执行任务: {task_id}, execution_id: {execution_id}")

        # 方案2：获取全局并发信号量，防止任务堆积导致线程池枯竭
        acquired = self._global_semaphore.acquire(timeout=30)
        if not acquired:
            logger.error("系统繁忙，获取执行许可超时: task_id={}", task_id)
            self.db.update_execution(
                execution_id,
                status=ExecutionStatus.FAILED,
                error_message="系统繁忙，当前并发任务数已达上限，请稍后重试",
                end_time=datetime.now(),
            )
            return {"success": False, "error": "系统繁忙，请稍后重试"}

        try:
            task = self.db.get_task(task_id)
            contact = task.contact if task else username
            task_description = task.task_description if task else ""

            # 检查并清理过期的执行记录，避免卡住后续调度
            self._cleanup_stale_executions(task_id)

            # 检查是否有正在运行的执行
            running = self.db.get_running_execution(task_id)
            if running and running.execution_id != execution_id:
                logger.info(
                    "任务 {} 已有正在运行的执行: {}", task_id, running.execution_id
                )
                self.db.update_execution(
                    execution_id,
                    status=ExecutionStatus.FAILED,
                    error_message="任务正在运行中",
                    end_time=datetime.now(),
                )
                return {"success": False, "error": "任务正在运行中"}

            # 更新进度
            self.db.update_execution(execution_id, progress=10)

            # 立即写入 running 状态的桌面端 feed，让用户能实时看到执行状态
            _append_desktop_task_feed(
                username,
                task_id,
                execution_id,
                task_description,
                "running",
                "任务正在执行中…",
                execution_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

            # 获取微信上下文（如最近消息），供Agent在执行时参考
            wechat_ctx = self._get_wechat_context(username)

            # 方案1：使用同步HTTP调用替代 asyncio.run()，避免嵌套事件循环导致线程卡死
            result = self._call_api_directly(
                task_prompt, username, execution_id, contact, wechat_ctx
            )

            # 更新进度
            self.db.update_execution(execution_id, progress=80)

            # 解析结果
            if result["returncode"] == 0:
                # 执行成功
                result_summary = self._extract_summary(result["stdout"])
                raw_files = result.get("generated_files") or []
                logger.info(f"[执行] 原始生成文件列表: {raw_files}")
                attachments = self._filter_attachments(raw_files)
                logger.info(f"[执行] 过滤后附件列表: {attachments}")
                self.db.update_execution(
                    execution_id,
                    status=ExecutionStatus.SUCCESS,
                    progress=100,
                    result_summary=result_summary,
                    result_detail=result["stdout"],
                    end_time=datetime.now(),
                )

                logger.info(f"任务执行成功: {task_id}, 附件数量: {len(attachments)}")

                task = self.db.get_task(task_id)
                if task and not task.cron_expression:
                    self.db.update_task_status(task_id, TaskStatus.COMPLETED)
                    logger.info("一次性任务已完成，状态更新为: completed")

                _append_desktop_task_feed(
                    username,
                    task_id,
                    execution_id,
                    task_description,
                    "success",
                    result_summary,
                    execution_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )

                return {
                    "success": True,
                    "execution_id": execution_id,
                    "result": result_summary,
                }
            else:
                # 执行失败
                error_msg = result.get("stderr", "未知错误")
                self.db.update_execution(
                    execution_id,
                    status=ExecutionStatus.FAILED,
                    progress=100,
                    error_message=error_msg,
                    end_time=datetime.now(),
                )

                logger.error(f"任务执行失败: {task_id}, error: {error_msg}")

                _append_desktop_task_feed(
                    username,
                    task_id,
                    execution_id,
                    task_description,
                    "failed",
                    error_msg,
                    execution_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )

                return {
                    "success": False,
                    "execution_id": execution_id,
                    "error": error_msg,
                }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"任务执行异常: {task_id}, error: {error_msg}")

            self.db.update_execution(
                execution_id,
                status=ExecutionStatus.FAILED,
                progress=100,
                error_message=error_msg,
                end_time=datetime.now(),
            )

            td = ""
            try:
                t0 = self.db.get_task(task_id)
                td = (t0.task_description or "") if t0 else ""
            except Exception:
                td = ""

            _append_desktop_task_feed(
                username,
                task_id,
                execution_id,
                td,
                "error",
                error_msg,
                execution_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

            return {"success": False, "execution_id": execution_id, "error": error_msg}
        finally:
            # 方案5：确保无论成功/失败/异常都释放信号量，防止永久占用
            self._global_semaphore.release()

    def _run_main_script(
        self, task_prompt: str, username: str, contact: str = ""
    ) -> Dict[str, Any]:
        """
        运行 main.py 脚本（通过命令行参数）

        Args:
            task_prompt: 任务提示词
            username: 用户名
            contact: 接收结果的微信联系人

        Returns:
            包含 returncode, stdout, stderr 的字典
        """
        try:
            # 构建命令
            cmd = [
                "python",
                MAIN_SCRIPT_PATH,
                "--task-prompt",
                task_prompt,
                "--username",
                username,
            ]

            if contact:
                cmd.extend(["--contact", contact])

            # 环境变量（不再需要传递任务内容，但保留其他环境变量）
            import os

            env = os.environ.copy()
            # 强制子进程使用 UTF-8 编码输出，避免乱码
            env["PYTHONIOENCODING"] = "utf-8"

            logger.info(
                f"开始执行 main.py: {' '.join(cmd)} (超时设置: {TASK_EXECUTION_SUBPROCESS_TIMEOUT}秒)"
            )

            # 使用 Popen 实时获取输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=MAIN_SCRIPT_PATH.rsplit("/", 1)[0]
                if "/" in MAIN_SCRIPT_PATH
                else MAIN_SCRIPT_PATH.rsplit("\\", 1)[0],
                encoding="utf-8",
                errors="replace",
            )

            stdout_lines = []
            stderr_lines = []
            generated_files = []
            seen_files = set()

            import threading

            def read_stdout(stream):
                buffer = []
                depth = 0
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    logger.info("[MAIN] {}", line)
                    stdout_lines.append(line)
                    # 实时收集 generated_files（参考 wechat_agent.py 的处理方式）
                    if not buffer and line.startswith("{"):
                        buffer.append(line)
                        depth = line.count("{") - line.count("}")
                    elif buffer:
                        buffer.append(line)
                        depth += line.count("{") - line.count("}")
                        if depth <= 0:
                            raw = "\n".join(buffer)
                            try:
                                event = json.loads(raw)
                                for f in event.get("generated_files", []):
                                    if f and f not in seen_files:
                                        seen_files.add(f)
                                        generated_files.append(f)
                            except (json.JSONDecodeError, ValueError):
                                pass
                            buffer.clear()
                            depth = 0

            def read_stderr(stream):
                for line in stream:
                    line = line.strip()
                    if line:
                        logger.error("[ERROR] {}", line)
                        stderr_lines.append(line)

            t1 = threading.Thread(target=read_stdout, args=(process.stdout,))
            t2 = threading.Thread(target=read_stderr, args=(process.stderr,))

            t1.start()
            t2.start()

            try:
                process.wait(timeout=TASK_EXECUTION_SUBPROCESS_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                logger.error(f"任务执行超时: {TASK_EXECUTION_SUBPROCESS_TIMEOUT}秒")
                return {
                    "returncode": -1,
                    "stdout": "\n".join(stdout_lines),
                    "stderr": f"任务执行超时 ({TASK_EXECUTION_SUBPROCESS_TIMEOUT}秒)\n"
                    + "\n".join(stderr_lines),
                    "generated_files": generated_files,
                }

            t1.join()
            t2.join()

            return {
                "returncode": process.returncode,
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines),
                "generated_files": generated_files,
            }

        except Exception as e:
            logger.error(f"运行 main.py 失败: {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def _cleanup_stale_executions(self, task_id: str) -> None:
        """清理过期的 running 状态执行记录，标记为失败，避免阻塞后续调度"""
        try:
            cleaned = self.db.cleanup_stale_executions(task_id=task_id)
            if cleaned > 0:
                logger.info("清理了 {} 条过期的执行记录(task_id={})", cleaned, task_id)
        except Exception as e:
            logger.info("清理过期执行记录失败: {}", e)

    def _get_wechat_context(self, username: str) -> str:
        """获取定时任务执行的微信上下文，从 wechat.json 配置中加载"""
        try:
            import os

            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config",
                "wechat.json",
            )
            if not os.path.exists(config_path):
                return ""

            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            parts = []
            alias = config.get("alias_name", "").strip()
            if alias:
                parts.append(f"当前AI助手名称: {alias}")
            session_name = config.get("session_name", "").strip()
            if session_name:
                parts.append(f"当前微信会话: {session_name}")
            owner = config.get("owner_name", "").strip()
            if owner:
                parts.append(f"当前用户: {owner}")

            return "\n".join(parts) if parts else ""
        except Exception as e:
            logger.info("获取微信上下文失败: {}", e)
            return ""

    def _call_api_directly_async(
        self,
        task_prompt: str,
        username: str,
        thread_id: str,
        contact: str = "",
        wechat_context: str = "",
    ) -> Dict[str, Any]:
        """
        异步调用 /quotation API 执行任务

        Args:
            task_prompt: 任务提示词
            username: 用户名
            thread_id: 线程ID
            contact: 接收结果的微信联系人
            wechat_context: 微信上下文信息

        Returns:
            包含 returncode, stdout, stderr 的字典
        """
        import httpx

        url = "http://127.0.0.1:8009/quotation"

        payload = {
            "user_input": "【定时任务】" + task_prompt,
            "chat_history": [],
            "thread_id": thread_id,
            "sessionId": f"scheduled_{thread_id}",
            "mode": 0,
            "username": username,
            "wechat_context": wechat_context or "",
            "contact_name": username,
            "scheduled_task_invocation": True,
        }

        timeout = httpx.Timeout(TASK_EXECUTION_TIMEOUT, read=TASK_EXECUTION_TIMEOUT)

        async def _do_request():
            full_output = []
            generated_files = []
            seen_files = set()

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        return {
                            "returncode": response.status_code,
                            "stdout": "",
                            "stderr": f"API 返回错误: {response.status_code}",
                        }

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            full_output.append(line)
                            try:
                                event = json.loads(line[6:])
                                files_in_event = event.get("generated_files", [])
                                if files_in_event:
                                    logger.info(
                                        "[API] 事件 {} 包含文件: {}",
                                        event.get("event_type"),
                                        files_in_event,
                                    )
                                for f in files_in_event:
                                    if f and f not in seen_files:
                                        seen_files.add(f)
                                        generated_files.append(f)
                            except (json.JSONDecodeError, ValueError):
                                pass

            logger.info(
                "[API] 异步调用完成，共收集到 {} 个生成文件: {}",
                len(generated_files),
                generated_files,
            )
            return {
                "returncode": 0,
                "stdout": "\n".join(full_output),
                "stderr": "",
                "generated_files": generated_files,
            }

        # 返回协程，由调用方 asyncio.run() 执行并捕获异常
        return _do_request()

    def _call_api_directly(
        self,
        task_prompt: str,
        username: str,
        thread_id: str,
        contact: str = "",
        wechat_context: str = "",
    ) -> Dict[str, Any]:
        """
        同步调用 /quotation API 执行任务

        Args:
            task_prompt: 任务提示词
            username: 用户名
            thread_id: 线程ID
            contact: 接收结果的微信联系人
            wechat_context: 微信上下文信息

        Returns:
            包含 returncode, stdout, stderr 的字典
        """
        import requests

        url = "http://127.0.0.1:8009/quotation"

        payload = {
            "user_input": "【定时任务】" + task_prompt,
            "chat_history": [],
            "thread_id": thread_id,
            "sessionId": f"scheduled_{thread_id}",
            "mode": 0,
            "username": username,
            "wechat_context": wechat_context or "",
            "contact_name": username,
            "scheduled_task_invocation": True,
        }

        try:
            # 使用流式读取响应
            response = requests.post(
                url, json=payload, stream=True, timeout=TASK_EXECUTION_TIMEOUT
            )

            if response.status_code == 200:
                full_output = []
                generated_files = []
                seen_files = set()
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            full_output.append(line)
                            try:
                                event = json.loads(line[6:])
                                files_in_event = event.get("generated_files", [])
                                if files_in_event:
                                    logger.info(
                                        f"[API] 事件 {event.get('event_type')} 包含文件: {files_in_event}"
                                    )
                                for f in files_in_event:
                                    if f and f not in seen_files:
                                        seen_files.add(f)
                                        generated_files.append(f)
                            except (json.JSONDecodeError, ValueError):
                                pass

                logger.info(
                    f"[API] 任务完成，共收集到 {len(generated_files)} 个生成文件: {generated_files}"
                )
                return {
                    "returncode": 0,
                    "stdout": "\n".join(full_output),
                    "stderr": "",
                    "generated_files": generated_files,
                }
            else:
                return {
                    "returncode": response.status_code,
                    "stdout": "",
                    "stderr": f"API 返回错误: {response.status_code}",
                }

        except requests.exceptions.Timeout:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"API 请求超时 ({TASK_EXECUTION_TIMEOUT}秒)",
            }
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def _extract_summary(self, stdout: str) -> str:
        """从 SSE 流式输出中提取 AI 最终回复。
        优先取 done 事件的完整 content；若不存在则拼接所有 think 事件的 content，
        取最后一条有实质内容的作为结果摘要。
        """
        if not stdout:
            return "任务执行完成，无输出"

        done_content = ""
        all_think_contents = []

        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("data: "):
                json_str = stripped[6:]
                try:
                    event = json.loads(json_str)
                    event_type = event.get("event_type", "")
                    content = event.get("content", "")
                    if not isinstance(content, str):
                        continue
                    if event_type == "done" and content:
                        done_content = content
                    elif event_type == "think" and content:
                        all_think_contents.append(content)
                except (json.JSONDecodeError, ValueError):
                    pass

        # 优先使用 done 事件（包含完整最终回复）
        if done_content:
            return done_content[:3000]

        # 回退：从 think 事件中取最后一条有实质内容的（通常是最终 AI 回复）
        if all_think_contents:
            # 倒序查找最长的有实质内容的片段
            for c in reversed(all_think_contents):
                if len(c.strip()) > 20:
                    return c[:3000]
            # 没有长片段，取最后一条
            return all_think_contents[-1][:3000]

        return "任务执行完成"

    def _parse_json_events(self, raw_lines: list) -> list:
        """将可能包含多行缩进 JSON 的行列表解析为事件字典列表"""
        events = []
        buffer = []
        depth = 0

        def _try_flush():
            if not buffer:
                return
            text = "\n".join(buffer)
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    events.append(obj)
            except (json.JSONDecodeError, ValueError):
                pass
            buffer.clear()

        for line in raw_lines:
            stripped = line.strip()
            if not buffer and stripped.startswith("{"):
                buffer.append(line)
                depth = stripped.count("{") - stripped.count("}")
            elif buffer:
                buffer.append(line)
                depth += stripped.count("{") - stripped.count("}")
                if depth <= 0:
                    _try_flush()
                    depth = 0

        _try_flush()
        return events

    def _filter_attachments(self, file_paths: list) -> list:
        """过滤文件路径列表，仅保留 output 目录下实际存在的文件"""
        import os

        _output_dir = _scheduler_output_root()
        seen = set()
        result = []
        for path in file_paths:
            if not isinstance(path, str):
                continue
            norm = os.path.normpath(path.rstrip(".,;)"))
            norm_case = os.path.normcase(norm)
            if norm_case in seen:
                continue
            if not os.path.isfile(norm):
                continue
            if not norm_case.startswith(_output_dir):
                continue
            seen.add(norm_case)
            result.append(norm)
        return result

    def _extract_attachments(self, stdout: str) -> list:
        """从流式输出中提取任务生成的本地文件路径（仅限 output 目录下的附件）"""
        import re
        import os

        if not stdout:
            return []

        _FILE_EXTS = (
            r"\.(docx?|pdf|xlsx?|pptx?|csv|txt|md|jpg|jpeg|png|gif|bmp|webp|mp3|mp4)"
        )
        _PATH_RE = re.compile(
            r'[A-Za-z]:[/\\][^\s\'"<>|*?\x00-\x1f]+' + _FILE_EXTS, re.IGNORECASE
        )

        _output_dir = _scheduler_output_root()

        seen = set()
        attachments = []

        def _try_add(path: str):
            path = os.path.normpath(path.rstrip(".,;)"))
            path_case = os.path.normcase(path)
            if path_case in seen:
                return
            if not os.path.isfile(path):
                return
            if not path_case.startswith(_output_dir):
                return
            seen.add(path_case)
            attachments.append(path)

        raw_lines = [
            (line[len("[MAIN] ") :] if line.startswith("[MAIN] ") else line)
            for line in stdout.splitlines()
            if line.strip()
        ]

        for event in self._parse_json_events(raw_lines):
            generated = event.get("generated_files", [])
            if isinstance(generated, list):
                for path in generated:
                    if isinstance(path, str):
                        _try_add(path)

            content = event.get("content", "")
            if isinstance(content, str):
                for m in _PATH_RE.finditer(content):
                    _try_add(m.group(0))

        for raw in raw_lines:
            if not raw.strip().startswith("{"):
                for m in _PATH_RE.finditer(raw):
                    _try_add(m.group(0))

        return attachments

    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """获取执行状态"""
        execution = self.db.get_execution(execution_id)
        if not execution:
            return None

        return {
            "execution_id": execution.execution_id,
            "task_id": execution.task_id,
            "status": execution.status,
            "progress": execution.progress,
            "start_time": execution.start_time.isoformat(),
            "end_time": execution.end_time.isoformat() if execution.end_time else None,
            "result_summary": execution.result_summary,
            "error_message": execution.error_message,
        }

    def get_task_executions(self, task_id: str, limit: int = 10) -> list:
        """获取任务的执行历史"""
        executions = self.db.get_executions_by_task(task_id, limit)
        return [
            {
                "execution_id": e.execution_id,
                "status": e.status,
                "progress": e.progress,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "result_summary": e.result_summary,
                "error_message": e.error_message,
            }
            for e in executions
        ]
