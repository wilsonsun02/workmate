"""
任务调度器模块
基于 APScheduler 实现定时任务调度
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Dict, Any, List
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from .config import (
    SCHEDULER_TIMEZONE,
    SCHEDULER_MAX_INSTANCES,
    SCHEDULER_COALESCE,
    SCHEDULER_MISFIRE_GRACE_TIME,
)
from .database import SchedulerDatabase
from .models import ScheduledTask, TaskStatus
from .executor import TaskExecutor

from loguru import logger


class TaskScheduler:
    """任务调度器类"""

    _instance = None
    _initialized = False

    # 方案3：独立的有界任务执行线程池，避免APScheduler线程被长时间阻塞
    # max_workers=3，与TaskExecutor信号量上限(5)配合，最终并发受两者下限控制
    _task_executor_pool: Optional[ThreadPoolExecutor] = None
    _task_submitted: set = set()
    _task_submitted_lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化调度器"""
        if TaskScheduler._initialized:
            return

        self.db = SchedulerDatabase()
        self.executor = TaskExecutor()
        self.scheduler = None
        self._job_task_map: Dict[str, str] = {}  # job_id -> task_id
        self._watcher_stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._desktop_active_username = str(
            os.environ.get("WORKMATE_DESKTOP_ACTIVE_USERNAME", "") or ""
        ).strip()

        # 方案3：初始化独立任务执行线程池（线程名前缀便于日志排查）
        if TaskScheduler._task_executor_pool is None:
            TaskScheduler._task_executor_pool = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="TaskExec"
            )
            logger.info("独立任务执行线程池已初始化，max_workers=3")

        TaskScheduler._initialized = True
        logger.info("TaskScheduler 初始化完成")

    def _active_username(self) -> str:
        """读取当前桌面端激活用户（空字符串表示不过滤）。"""
        # 以环境变量为准，便于被 /api/desktop/set_active_username 动态切换
        env_user = str(
            os.environ.get("WORKMATE_DESKTOP_ACTIVE_USERNAME", "") or ""
        ).strip()
        if env_user != self._desktop_active_username:
            self._desktop_active_username = env_user
        return self._desktop_active_username

    def _is_task_allowed(self, task: ScheduledTask) -> bool:
        """桌面端激活用户过滤：未登录不调度，登录后仅调度当前用户任务。"""
        active_user = self._active_username()
        if not active_user:
            return False
        return str(task.username or "").strip() == active_user

    def _cleanup_stale_executions_on_startup(self) -> None:
        """启动时清理过期的执行记录"""
        try:
            from .config import STALE_EXECUTION_CLEANUP_ON_STARTUP

            if not STALE_EXECUTION_CLEANUP_ON_STARTUP:
                return
            cleaned = self.db.cleanup_stale_executions()
            if cleaned > 0:
                logger.info("启动时清理了 {} 条过期执行记录", cleaned)
        except Exception as e:
            logger.info("启动清理过期执行记录失败: {}", e)

    def _prune_disallowed_jobs(self, active_tasks: List[ScheduledTask]) -> None:
        """移除当前过滤条件下不应执行的已调度任务。"""
        if self.scheduler is None or not self.scheduler.running:
            return
        allowed_ids = {
            str(task.task_id) for task in active_tasks if self._is_task_allowed(task)
        }
        stale_job_ids: List[str] = []
        for job_id, task_id in list(self._job_task_map.items()):
            if str(task_id) not in allowed_ids:
                stale_job_ids.append(job_id)
        for job_id in stale_job_ids:
            try:
                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
            except Exception as e:
                logger.info("移除非激活用户任务失败: job_id={} err={}", job_id, e)
            self._job_task_map.pop(job_id, None)

    def apply_active_user_filter(self, username: str) -> None:
        """
        动态设置桌面端激活用户，并立即重建内存调度任务：
        - 仅保留该用户 active 任务
        - 移除其他用户已挂载 job，避免继续自动执行
        """
        self._desktop_active_username = str(username or "").strip()
        os.environ["WORKMATE_DESKTOP_ACTIVE_USERNAME"] = self._desktop_active_username
        try:
            if self.scheduler is None or not self.scheduler.running:
                return
            tasks = self.db.get_all_active_tasks()
            self._prune_disallowed_jobs(tasks)
            for task in tasks:
                if not self._is_task_allowed(task):
                    continue
                self._schedule_task(task)
            logger.info(
                "已应用桌面端任务过滤，仅调度用户: %s",
                self._desktop_active_username or "(none)",
            )
        except Exception as e:
            logger.info("应用桌面端任务过滤失败: {}", e)

    def start(self):
        """启动调度器"""
        if self.scheduler is not None and self.scheduler.running:
            logger.info("调度器已在运行中")
            return

        self._watcher_stop_event.clear()

        # 配置 jobstore
        jobstores = {"default": MemoryJobStore()}

        # 配置执行器
        executors = {"default": {"type": "threadpool", "max_workers": 10}}

        # 配置任务失败回调
        job_defaults = {
            "coalesce": SCHEDULER_COALESCE,
            "max_instances": SCHEDULER_MAX_INSTANCES,
            "misfire_grace_time": SCHEDULER_MISFIRE_GRACE_TIME,
        }

        # 创建调度器
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=SCHEDULER_TIMEZONE,
        )

        # 添加事件监听器
        self.scheduler.add_listener(
            self._job_executed_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        # 启动调度器
        self.scheduler.start()
        logger.info("调度器已启动")

        # 清理上次可能遗留的过期执行记录，避免阻塞任务调度
        self._cleanup_stale_executions_on_startup()

        # 加载已有任务
        self._load_existing_tasks()

        # 启动后台线程，定期检查数据库中的新任务
        self._start_db_watcher()

    def _start_db_watcher(self):
        """启动数据库监控线程，定期检查新任务"""
        if self._watcher_thread and self._watcher_thread.is_alive():
            logger.info("数据库任务监控线程已在运行中")
            return

        def check_new_tasks():
            logger.info("启动数据库任务监控线程")

            while not self._watcher_stop_event.is_set():
                try:
                    scheduler = self.scheduler
                    if scheduler is None or not scheduler.running:
                        logger.info("调度器未运行，数据库任务监控线程退出")
                        break

                    # 获取所有 active 任务
                    tasks = self.db.get_all_active_tasks()
                    self._prune_disallowed_jobs(tasks)

                    for task in tasks:
                        if not self._is_task_allowed(task):
                            continue
                        job_id = f"task_{task.task_id}"
                        job = scheduler.get_job(job_id)

                        # 检查任务是否已经在调度器中
                        if not job:
                            # 新任务处理逻辑
                            if task.next_run_time:
                                from datetime import datetime

                                now = datetime.now()
                                time_diff = (task.next_run_time - now).total_seconds()

                                # 如果是一次性任务且执行时间已过期，直接执行
                                if not task.cron_expression:
                                    if time_diff < 0:
                                        # 检查是否已经在运行
                                        running = self.db.get_running_execution(
                                            task.task_id
                                        )
                                        if running:
                                            # 任务正在运行，跳过
                                            pass
                                        else:
                                            # 已过期且未运行，直接执行
                                            logger.info(
                                                f"一次性任务已过期，立即执行: {task.task_id}"
                                            )
                                            self._execute_task_directly(task)
                                    else:
                                        # 未过期，添加到调度器
                                        logger.info(
                                            f"发现一次性任务: {task.task_id}, 添加到调度器"
                                        )
                                        self._schedule_task(task)
                                elif task.next_run_time > now:
                                    # 定时任务且未过期
                                    logger.info(
                                        f"发现待执行任务: {task.task_id}, 添加到调度器"
                                    )
                                    self._schedule_task(task)
                                else:
                                    # 定时任务已过期，更新状态
                                    logger.info(
                                        "任务 {} 执行时间已过期，跳过", task.task_id
                                    )
                            else:
                                # 没有执行时间，立即添加
                                logger.info(f"发现新任务: {task.task_id}, 添加到调度器")
                                self._schedule_task(task)
                        else:
                            # 任务已存在，检查是否需要更新
                            # 比较下次执行时间
                            if task.next_run_time and job.next_run_time:
                                # 注意：job.next_run_time 是带时区的，task.next_run_time 可能不带
                                # 这里简单比较时间戳或者转换为相同时区
                                job_time = job.next_run_time.replace(tzinfo=None)
                                task_time = task.next_run_time.replace(tzinfo=None)

                                # 如果时间差异超过1秒，说明任务被修改了
                                if abs((job_time - task_time).total_seconds()) > 1:
                                    logger.info(
                                        f"任务 {task.task_id} 执行时间已变更，更新调度器"
                                    )
                                    self._schedule_task(task)

                            # 比较 cron 表达式
                            # TODO: 如果需要支持 cron 表达式的动态修改，这里也需要比较

                except Exception as e:
                    logger.error(f"检查任务失败: {e}")

                self._watcher_stop_event.wait(30)  # 每30秒检查一次

            logger.info("数据库任务监控线程已退出")

        self._watcher_thread = threading.Thread(target=check_new_tasks, daemon=True)
        self._watcher_thread.start()
        logger.info("数据库任务监控线程已启动")

    def stop(self, wait: bool = True):
        """停止调度器。wait=False 时不等待当前任务结束，适合进程退出路径。"""
        self._watcher_stop_event.set()
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("调度器已停止")
        self.scheduler = None
        self._job_task_map.clear()
        if (
            self._watcher_thread
            and self._watcher_thread.is_alive()
            and threading.current_thread() is not self._watcher_thread
        ):
            self._watcher_thread.join(timeout=2)

        # 方案3：关闭独立任务执行线程池
        pool = TaskScheduler._task_executor_pool
        if pool is not None:
            pool.shutdown(wait=wait)
            TaskScheduler._task_executor_pool = None
            # 清空提交追踪集，防止重新初始化时残留
            with TaskScheduler._task_submitted_lock:
                TaskScheduler._task_submitted.clear()
            logger.info("任务执行线程池已关闭")

    def _job_executed_listener(self, event):
        """任务执行监听器"""
        if event.exception:
            logger.error(f"任务执行失败: {event.job_id}, 异常: {event.exception}")
        else:
            logger.info(f"任务执行完成: {event.job_id}")

    def _load_existing_tasks(self):
        """加载已有任务"""
        try:
            # 确保调度器已启动
            if self.scheduler is None or not self.scheduler.running:
                self.start()

            tasks = self.db.get_all_active_tasks()
            self._prune_disallowed_jobs(tasks)
            for task in tasks:
                if not self._is_task_allowed(task):
                    continue
                self._schedule_task(task)
            active_user = self._active_username()
            if active_user:
                logger.info("已按用户过滤加载定时任务: user={}", active_user)
            else:
                logger.info(f"已加载 {len(tasks)} 个定时任务")
        except Exception as e:
            logger.error(f"加载已有任务失败: {e}")

    def add_task(self, task: ScheduledTask) -> bool:
        """添加定时任务"""
        try:
            # 确保调度器已启动
            if self.scheduler is None or not self.scheduler.running:
                self.start()

            # 保存到数据库
            self.db.create_task(task)

            # 添加到调度器
            if task.status == TaskStatus.ACTIVE and self._is_task_allowed(task):
                self._schedule_task(task)

            logger.info(f"添加任务成功: {task.task_id}")
            return True
        except Exception as e:
            logger.error(f"添加任务失败: {e}")
            return False

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """更新任务"""
        try:
            # 1. 更新数据库
            if not self.db.update_task(task_id, updates):
                logger.error(f"更新任务数据库失败: {task_id}")
                return False

            # 2. 获取更新后的任务
            task = self.db.get_task(task_id)
            if not task:
                return False

            # 3. 如果任务是激活状态，更新调度器
            if task.status == TaskStatus.ACTIVE and self._is_task_allowed(task):
                # 确保调度器已启动
                if self.scheduler is None or not self.scheduler.running:
                    self.start()

                # 重新调度任务（会覆盖旧的 job）
                self._schedule_task(task)
                logger.info(f"任务已更新并重新调度: {task_id}")
            else:
                # 不在当前激活用户范围内时，确保不被调度
                job_id = f"task_{task_id}"
                if self.scheduler is not None and self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
                self._job_task_map.pop(job_id, None)

            return True
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            return False

    def _schedule_task(self, task: ScheduledTask):
        """将任务添加到调度器"""
        job_id = f"task_{task.task_id}"

        # 解析 cron 表达式或创建一次性触发器
        trigger = self._create_trigger(task.cron_expression, task.next_run_time)
        if trigger is None:
            logger.error(
                f"无法创建触发器: cron={task.cron_expression}, next_run={task.next_run_time}"
            )
            return False

        # 添加任务
        self.scheduler.add_job(
            func=self._execute_task_wrapper,
            trigger=trigger,
            id=job_id,
            name=task.task_name or task.task_id,
            replace_existing=True,
            kwargs={
                "task_id": task.task_id,
                "task_prompt": task.task_prompt,
                "username": task.username,
            },
        )

        self._job_task_map[job_id] = task.task_id

        # 更新下次执行时间
        job = self.scheduler.get_job(job_id)
        if job:
            self.db.update_task_times(task.task_id, next_run_time=job.next_run_time)

        logger.info(
            f"任务已调度: {task.task_id}, 下次执行: {job.next_run_time if job else 'N/A'}"
        )
        return True

    def _create_trigger(self, cron_expression: str, next_run_time=None):
        """创建触发器"""
        # 如果没有 cron 表达式但有 next_run_time，创建一次性触发器
        if not cron_expression and next_run_time:
            try:
                return DateTrigger(run_date=next_run_time, timezone=SCHEDULER_TIMEZONE)
            except Exception as e:
                logger.error(f"创建一次性触发器失败: {e}")
                return None

        if not cron_expression:
            return None

        parts = cron_expression.split()
        if len(parts) != 5:
            return None

        try:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone=SCHEDULER_TIMEZONE,
            )
        except Exception as e:
            logger.error(f"创建触发器失败: {e}")
            return None

    def _execute_task_wrapper(self, task_id: str, task_prompt: str, username: str):
        """任务执行包装器：提交到独立线程池，立即释放APScheduler调度线程"""
        logger.info(f"提交任务到执行线程池: {task_id}")

        # 方案3：防止同一任务重复提交到线程池
        with TaskScheduler._task_submitted_lock:
            if task_id in TaskScheduler._task_submitted:
                logger.info("任务 {} 已在执行队列中，跳过重复提交", task_id)
                return
            TaskScheduler._task_submitted.add(task_id)

        # 提交到独立线程池，不阻塞APScheduler
        self._task_executor_pool.submit(
            self._do_execute_task, task_id, task_prompt, username
        )

        # 更新任务执行时间（快速DB操作，在原线程中完成）
        self.db.update_task_times(task_id, last_run_time=datetime.now())

        # 更新下次执行时间
        job = self.scheduler.get_job(f"task_{task_id}")
        if job:
            self.db.update_task_times(task_id, next_run_time=job.next_run_time)

    def _execute_task_directly(self, task: ScheduledTask):
        """直接执行任务（用于已过期的任务），提交到独立线程池"""
        logger.info(f"提交过期任务到执行线程池: {task.task_id}")

        # 方案3：防止重复提交
        with TaskScheduler._task_submitted_lock:
            if task.task_id in TaskScheduler._task_submitted:
                logger.info("任务 {} 已在执行队列中，跳过重复提交", task.task_id)
                return
            TaskScheduler._task_submitted.add(task.task_id)

        self._task_executor_pool.submit(
            self._do_execute_task, task.task_id, task.task_prompt, task.username
        )

    def _do_execute_task(self, task_id: str, task_prompt: str, username: str):
        """在独立线程池中执行任务，完成后自动清理提交记录"""
        try:
            self.executor.execute(task_id, task_prompt, username)
        finally:
            # 方案5：确保执行完成后清理提交记录，允许下次调度
            with TaskScheduler._task_submitted_lock:
                TaskScheduler._task_submitted.discard(task_id)

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        try:
            job_id = f"task_{task_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.pause_job(job_id)
                self.db.update_task_status(task_id, TaskStatus.PAUSED)
                logger.info(f"任务已暂停: {task_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"暂停任务失败: {e}")
            return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        try:
            job_id = f"task_{task_id}"

            # 情况1: job 已在调度器中（仅被 paused），直接 resume
            if self.scheduler.get_job(job_id):
                self.scheduler.resume_job(job_id)
                self.db.update_task_status(task_id, TaskStatus.ACTIVE)
                logger.info(f"任务已恢复: {task_id}")
                return True

            # 情况2: job 不在调度器中（服务重启后 paused 任务不会加载到内存），
            # 从数据库取出任务并重新调度
            task = self.db.get_task(task_id)
            if not task:
                logger.error(f"恢复任务失败，任务不存在: {task_id}")
                return False

            self.db.update_task_status(task_id, TaskStatus.ACTIVE)
            task.status = TaskStatus.ACTIVE

            if not self._is_task_allowed(task):
                logger.info(
                    "恢复任务 {} 跳过：当前桌面用户 {} 不匹配任务用户 {}",
                    task_id,
                    self._active_username(),
                    task.username,
                )
                return True

            self._schedule_task(task)
            logger.info(f"任务已恢复并重新调度: {task_id}")
            return True
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
            return False

    def remove_task(self, task_id: str) -> bool:
        """删除任务"""
        try:
            # 从调度器中移除
            job_id = f"task_{task_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                self._job_task_map.pop(job_id, None)

            # 从数据库中删除
            self.db.delete_task(task_id)

            logger.info(f"任务已删除: {task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            return False

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        job_id = f"task_{task_id}"
        job = self.scheduler.get_job(job_id)

        task = self.db.get_task(task_id)
        if not task:
            return None

        result = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "status": task.status,
            "next_run_time": job.next_run_time.isoformat()
            if job and job.next_run_time
            else None,
            "last_run_time": task.last_run_time.isoformat()
            if task.last_run_time
            else None,
        }

        return result

    def list_tasks(self, username: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有任务"""
        if username:
            tasks = self.db.get_tasks_by_username(username)
        else:
            tasks = self.db.get_all_active_tasks()

        result = []
        for task in tasks:
            job_id = f"task_{task.task_id}"
            job = self.scheduler.get_job(job_id)

            next_run_iso = None
            if job and job.next_run_time:
                next_run_iso = job.next_run_time.isoformat()
            elif task.next_run_time:
                next_run_iso = task.next_run_time.isoformat()

            result.append(
                {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "task_description": task.task_description,
                    "task_prompt": task.task_prompt,
                    "task_type": task.task_type,
                    "status": task.status,
                    "cron_expression": task.cron_expression,
                    "next_run_time": next_run_iso,
                    "last_run_time": task.last_run_time.isoformat()
                    if task.last_run_time
                    else None,
                    "created_at": task.created_at.isoformat(),
                }
            )

        return result


# 全局调度器实例
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """获取调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
