"""
基于 JSON 文件的数据库操作模块
提供定时任务和执行记录的 CRUD 操作
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from .models import ScheduledTask, TaskExecution, TaskStatus

from loguru import logger


class JsonDatabase:
    """基于 JSON 文件的数据库操作类"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """初始化数据库"""
        if self._initialized:
            return

        _base = os.environ.get("BASE_DIR", "").strip()
        if _base:
            self.config_dir = os.path.join(_base, "config")
        else:
            self.config_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config"
            )
        os.makedirs(self.config_dir, exist_ok=True)

        self.tasks_file = os.path.join(self.config_dir, "scheduled_tasks.json")
        self.executions_file = os.path.join(self.config_dir, "task_executions.json")

        self._file_lock = threading.RLock()

        self._initialized = True
        logger.info("JSON 数据库初始化完成")

    def _read_json(self, file_path: str) -> List[Dict]:
        """读取 JSON 文件"""
        with self._file_lock:
            try:
                if not os.path.exists(file_path):
                    return []
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取文件 {file_path} 失败: {e}")
                return []

    def _write_json(self, file_path: str, data: List[Dict]) -> bool:
        """原子写入 JSON 文件，避免进程中断时留下半截配置。"""
        with self._file_lock:
            tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, file_path)
                return True
            except Exception as e:
                logger.error(f"写入文件 {file_path} 失败: {e}")
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception as cleanup_error:
                    logger.info("清理临时文件失败: {}", cleanup_error)
                return False

    # ==================== 辅助方法 ====================

    def _serialize_datetime(self, obj: Any) -> Any:
        """序列化 datetime 对象"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    def _deserialize_datetime(self, val: Any) -> Any:
        """反序列化 datetime 字符串，统一返回 naive datetime（无时区）"""
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val)
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt
            except ValueError:
                pass
        return val

    def _task_to_dict(self, task: ScheduledTask) -> Dict:
        """将任务对象转换为字典"""
        data = task.dict()
        for k, v in data.items():
            data[k] = self._serialize_datetime(v)
        return data

    def _dict_to_task(self, data: Dict) -> ScheduledTask:
        """将字典转换为任务对象"""
        for k, v in data.items():
            data[k] = self._deserialize_datetime(v)
        return ScheduledTask(**data)

    def _execution_to_dict(self, execution: TaskExecution) -> Dict:
        """将执行记录对象转换为字典"""
        data = execution.dict()
        for k, v in data.items():
            data[k] = self._serialize_datetime(v)
        return data

    def _dict_to_execution(self, data: Dict) -> TaskExecution:
        """将字典转换为执行记录对象"""
        for k, v in data.items():
            data[k] = self._deserialize_datetime(v)
        return TaskExecution(**data)

    # ==================== 任务操作 ====================

    def create_task(self, task: ScheduledTask) -> ScheduledTask:
        """创建定时任务"""
        with self._file_lock:
            tasks = self._read_json(self.tasks_file)

            # 检查 ID 是否已存在
            if any(t.get("task_id") == task.task_id for t in tasks):
                raise ValueError(f"任务 ID {task.task_id} 已存在")

            tasks.append(self._task_to_dict(task))

            if self._write_json(self.tasks_file, tasks):
                logger.info(f"创建任务成功: {task.task_id}")
                return task
            else:
                raise IOError("写入任务数据失败")

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """根据任务ID获取任务"""
        tasks = self._read_json(self.tasks_file)
        for task_data in tasks:
            if task_data.get("task_id") == task_id:
                return self._dict_to_task(task_data)
        return None

    def get_tasks_by_username(
        self, username: str, status: Optional[str] = None
    ) -> List[ScheduledTask]:
        """获取用户的所有任务"""
        tasks = self._read_json(self.tasks_file)
        result = []

        for task_data in tasks:
            if task_data.get("username") == username:
                if status is None or task_data.get("status") == status:
                    result.append(self._dict_to_task(task_data))

        # 按创建时间倒序排序
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result

    def get_all_active_tasks(self) -> List[ScheduledTask]:
        """获取所有活跃任务"""
        tasks = self._read_json(self.tasks_file)
        result = []

        for task_data in tasks:
            if task_data.get("status") == "active":
                result.append(self._dict_to_task(task_data))

        # 按下次执行时间排序
        result.sort(key=lambda x: x.next_run_time if x.next_run_time else datetime.max)
        return result

    def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """更新任务状态"""
        with self._file_lock:
            tasks = self._read_json(self.tasks_file)
            updated = False

            for task_data in tasks:
                if task_data.get("task_id") == task_id:
                    task_data["status"] = (
                        status.value if isinstance(status, TaskStatus) else status
                    )
                    task_data["updated_at"] = datetime.now().isoformat()
                    updated = True
                    break

            if updated:
                return self._write_json(self.tasks_file, tasks)
            return False

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """更新任务信息"""
        with self._file_lock:
            tasks = self._read_json(self.tasks_file)
            updated = False

            valid_fields = [
                "task_name",
                "task_description",
                "task_prompt",
                "cron_expression",
                "next_run_time",
                "status",
                "task_type",
            ]

            for task_data in tasks:
                if task_data.get("task_id") == task_id:
                    for field, value in updates.items():
                        if field in valid_fields:
                            task_data[field] = self._serialize_datetime(value)
                            updated = True

                    if updated:
                        task_data["updated_at"] = datetime.now().isoformat()
                    break

            if updated:
                return self._write_json(self.tasks_file, tasks)
            return False

    def update_task_times(
        self,
        task_id: str,
        next_run_time: Optional[datetime] = None,
        last_run_time: Optional[datetime] = None,
    ) -> bool:
        """更新任务执行时间"""
        with self._file_lock:
            tasks = self._read_json(self.tasks_file)
            updated = False

            for task_data in tasks:
                if task_data.get("task_id") == task_id:
                    if next_run_time is not None:
                        task_data["next_run_time"] = next_run_time.isoformat()
                        updated = True
                    if last_run_time is not None:
                        task_data["last_run_time"] = last_run_time.isoformat()
                        updated = True

                    if updated:
                        task_data["updated_at"] = datetime.now().isoformat()
                    break

            if updated:
                return self._write_json(self.tasks_file, tasks)
            return False

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        with self._file_lock:
            tasks = self._read_json(self.tasks_file)
            initial_len = len(tasks)

            tasks = [t for t in tasks if t.get("task_id") != task_id]

            if len(tasks) < initial_len:
                return self._write_json(self.tasks_file, tasks)
            return False

    # ==================== 执行记录操作 ====================

    def create_execution(self, execution: TaskExecution) -> TaskExecution:
        """创建执行记录"""
        with self._file_lock:
            executions = self._read_json(self.executions_file)

            # 检查 ID 是否已存在
            if any(e.get("execution_id") == execution.execution_id for e in executions):
                raise ValueError(f"执行记录 ID {execution.execution_id} 已存在")

            executions.append(self._execution_to_dict(execution))

            if self._write_json(self.executions_file, executions):
                logger.info(f"创建执行记录成功: {execution.execution_id}")
                return execution
            else:
                raise IOError("写入执行记录数据失败")

    def get_execution(self, execution_id: str) -> Optional[TaskExecution]:
        """根据执行ID获取执行记录"""
        executions = self._read_json(self.executions_file)
        for exec_data in executions:
            if exec_data.get("execution_id") == execution_id:
                return self._dict_to_execution(exec_data)
        return None

    def get_executions_by_task(
        self, task_id: str, limit: int = 10
    ) -> List[TaskExecution]:
        """获取任务的执行记录"""
        executions = self._read_json(self.executions_file)
        result = []

        for exec_data in executions:
            if exec_data.get("task_id") == task_id:
                result.append(self._dict_to_execution(exec_data))

        # 按开始时间倒序排序
        result.sort(key=lambda x: x.start_time, reverse=True)
        return result[:limit]

    def list_executions_for_user(
        self,
        username: str,
        *,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 200,
    ) -> List[TaskExecution]:
        """按用户列出执行记录，可选任务、状态、日期区间（YYYY-MM-DD），按 start_time 倒序。"""
        executions = self._read_json(self.executions_file)
        result: List[TaskExecution] = []

        from_d = None
        to_d = None
        if from_date:
            try:
                from_d = datetime.fromisoformat(from_date.strip()[:10]).date()
            except ValueError:
                from_d = None
        if to_date:
            try:
                to_d = datetime.fromisoformat(to_date.strip()[:10]).date()
            except ValueError:
                to_d = None

        cap = max(1, min(int(limit or 200), 500))

        for exec_data in executions:
            if exec_data.get("username") != username:
                continue
            if task_id and exec_data.get("task_id") != task_id:
                continue
            if status and exec_data.get("status") != status:
                continue
            ex = self._dict_to_execution(exec_data)
            st = ex.start_time
            if from_d and st.date() < from_d:
                continue
            if to_d and st.date() > to_d:
                continue
            result.append(ex)

        result.sort(key=lambda x: x.start_time, reverse=True)
        return result[:cap]

    def get_running_execution(self, task_id: str) -> Optional[TaskExecution]:
        """获取任务正在运行的执行记录（排除超过配置时限的过期记录）"""
        from datetime import timedelta

        from .config import STALE_EXECUTION_MAX_AGE

        executions = self._read_json(self.executions_file)
        stale_threshold = datetime.now() - timedelta(seconds=STALE_EXECUTION_MAX_AGE)

        for exec_data in executions:
            if (
                exec_data.get("task_id") == task_id
                and exec_data.get("status") == "running"
            ):
                start_time = self._deserialize_datetime(exec_data.get("start_time"))
                if start_time and start_time > stale_threshold:
                    return self._dict_to_execution(exec_data)

        return None

    def cleanup_stale_executions(self, task_id: Optional[str] = None) -> int:
        """将过期的 running 状态执行记录标记为失败

        Args:
            task_id: 指定任务ID则只清理该任务，否则清理所有任务

        Returns:
            清理的记录数量
        """
        from datetime import timedelta

        from .config import STALE_EXECUTION_MAX_AGE

        with self._file_lock:
            executions = self._read_json(self.executions_file)
            stale_threshold = datetime.now() - timedelta(
                seconds=STALE_EXECUTION_MAX_AGE
            )
            cleaned = 0

            for exec_data in executions:
                if task_id and exec_data.get("task_id") != task_id:
                    continue
                if exec_data.get("status") != "running":
                    continue
                start_time = self._deserialize_datetime(exec_data.get("start_time"))
                if start_time and start_time < stale_threshold:
                    exec_data["status"] = "failed"
                    exec_data["progress"] = 100
                    exec_data["error_message"] = "执行超时，被系统自动标记为失败"
                    exec_data["end_time"] = datetime.now().isoformat()
                    cleaned += 1

            if cleaned > 0:
                self._write_json(self.executions_file, executions)
                logger.info("清理了 {} 条过期的执行记录", cleaned)

            return cleaned

    def update_execution(self, execution_id: str, **kwargs) -> bool:
        """更新执行记录"""
        with self._file_lock:
            executions = self._read_json(self.executions_file)
            updated = False

            valid_fields = [
                "status",
                "progress",
                "result_summary",
                "result_detail",
                "error_message",
                "end_time",
            ]

            for exec_data in executions:
                if exec_data.get("execution_id") == execution_id:
                    for field, value in kwargs.items():
                        if field in valid_fields and value is not None:
                            if isinstance(value, Enum):
                                exec_data[field] = value.value
                            else:
                                exec_data[field] = self._serialize_datetime(value)
                            updated = True
                    break

            if updated:
                return self._write_json(self.executions_file, executions)
            return False

    def delete_executions_for_user(
        self,
        username: str,
        *,
        execution_ids: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> int:
        """
        删除该用户的执行记录。
        - execution_ids 非空：仅删除这些 id（必须属于 username），忽略筛选字段。
        - 否则：删除符合 task_id / status / 日期 条件的记录（与 list_executions_for_user 规则一致；字段全空则删除该用户全部记录）。
        返回删除条数。
        """
        with self._file_lock:
            executions = self._read_json(self.executions_file)
            id_set: Optional[set] = None
            if execution_ids:
                id_set = {str(x).strip() for x in execution_ids if str(x).strip()}

            from_d = None
            to_d = None
            if from_date:
                try:
                    from_d = datetime.fromisoformat(from_date.strip()[:10]).date()
                except ValueError:
                    from_d = None
            if to_date:
                try:
                    to_d = datetime.fromisoformat(to_date.strip()[:10]).date()
                except ValueError:
                    to_d = None

            new_list: List[Dict[str, Any]] = []
            removed = 0

            for exec_data in executions:
                if exec_data.get("username") != username:
                    new_list.append(exec_data)
                    continue

                if id_set is not None:
                    eid = exec_data.get("execution_id")
                    if eid in id_set:
                        removed += 1
                        continue
                    new_list.append(exec_data)
                    continue

                if task_id and exec_data.get("task_id") != task_id:
                    new_list.append(exec_data)
                    continue
                if status and exec_data.get("status") != status:
                    new_list.append(exec_data)
                    continue
                ex = self._dict_to_execution(exec_data)
                st = ex.start_time
                if from_d and st.date() < from_d:
                    new_list.append(exec_data)
                    continue
                if to_d and st.date() > to_d:
                    new_list.append(exec_data)
                    continue
                removed += 1

            if removed and self._write_json(self.executions_file, new_list):
                return removed
            return 0


# 为了兼容现有代码，将 SchedulerDatabase 指向 JsonDatabase
SchedulerDatabase = JsonDatabase
