"""
Agent 工具函数模块
为 DeepAgent 提供定时任务管理的工具函数
"""

import json
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

from .scheduler import get_scheduler
from .parser import TaskParser
from .models import ScheduledTask, TaskStatus, TaskType, ExecutionStatus
from .database import SchedulerDatabase

from loguru import logger


def _resolve_agent_username() -> str:
    """自动获取当前 Agent 的系统用户名：优先从 contextvar 获取，回退到环境变量 AGENT_USERNAME。"""
    from workflow.report_tools import agent_username_ctx

    v = agent_username_ctx.get().strip()
    if v:
        return v
    env_val = (
        os.getenv("USERNAME", "").strip() or os.getenv("AGENT_USERNAME", "").strip()
    )
    if env_val:
        return env_val
    logger.error("无法获取 AGENT_USERNAME，请检查环境变量或 contextvar 设置")
    return ""


def _normalize_task_body(text: Optional[str]) -> str:
    """用于判断「是否相同任务」：去首尾空白、合并空白、小写。"""
    if not text:
        return ""
    return " ".join(str(text).strip().lower().split())


def _normalize_cron_expression(expr: Optional[str]) -> str:
    """统一 cron 五段式中的数字写法（如 08 与 8），保留 * 与 step 语法。"""
    if not expr or not str(expr).strip():
        return ""
    parts = str(expr).strip().split()
    if len(parts) != 5:
        return " ".join(parts)
    out: List[str] = []
    for p in parts:
        if p == "*":
            out.append("*")
        elif p.isdigit():
            out.append(str(int(p)))
        else:
            out.append(p)
    return " ".join(out)


def _schedule_fingerprint(
    cron_expression: Optional[str],
    next_run_time: Optional[datetime],
) -> str:
    """同指纹视为同一「执行计划」，用于与任务正文一起做去重。"""
    cron_n = _normalize_cron_expression(cron_expression)
    if cron_n:
        return f"cron:{cron_n}"
    if next_run_time:
        dt = next_run_time
        if getattr(dt, "tzinfo", None):
            dt = dt.replace(tzinfo=None)
        dt = dt.replace(second=0, microsecond=0)
        return f"once:{dt.isoformat()}"
    return "none:"


def _find_duplicate_active_task(
    username: str,
    cron_expression: Optional[str],
    next_run_time: Optional[datetime],
    task_description: str,
) -> Optional[ScheduledTask]:
    """
    若该用户已有「执行计划指纹 + 任务正文」均相同的 **active** 任务，则视为重复。

    用于阻断 DeepAgent 在同一会话反复读历史时多次调用 create_scheduled_task。
    """
    body = _normalize_task_body(task_description)
    if not body:
        return None
    fp_new = _schedule_fingerprint(cron_expression, next_run_time)
    db = SchedulerDatabase()
    for t in db.get_tasks_by_username(username, status=TaskStatus.ACTIVE.value):
        ex_fp = _schedule_fingerprint(t.cron_expression, t.next_run_time)
        if ex_fp != fp_new:
            continue
        ex_body = _normalize_task_body(t.task_prompt) or _normalize_task_body(
            t.task_description
        )
        if ex_body == body:
            return t
    return None


def get_wechat_config() -> dict:
    """获取微信配置"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "wechat.json"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取微信配置失败: {e}")
        return {}


def create_scheduled_task(
    username: str,
    task_description: str,
    cron_expression: Optional[str] = None,
    task_type: str = "custom",
    task_name: Optional[str] = None,
    next_run_time: Optional[datetime] = None,
    contact: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建定时任务的工具函数

    Args:
        username: 用户名
        task_description: 任务描述（自然语言）
        cron_expression: Cron 表达式（可选，如果不提供则自动解析）
        task_type: 任务类型 (news_report/market_summary/data_analysis/custom)
        task_name: 任务名称（可选）
        next_run_time: 下次执行时间（可选，用于一次性任务）

    Returns:
        创建结果字典
    """
    try:
        # 如果没有提供 cron 表达式，则自动解析
        if not cron_expression and not next_run_time:
            parsed = TaskParser.parse(task_description)
            cron_expression = parsed.get("cron_expression", "0 8 * * *")
            if not task_type or task_type == "custom":
                task_type = parsed.get("task_type", "custom")
            if not task_name:
                task_name = parsed.get("task_name")

        # 验证 cron 表达式（如果有）
        if cron_expression:
            is_valid, error_msg = TaskParser.validate_cron(cron_expression)
            if not is_valid:
                return {"success": False, "error": f"无效的 Cron 表达式: {error_msg}"}

        # 计算下次执行时间（如果没有 cron 表达式且未提供 next_run_time）
        from datetime import timedelta

        if not cron_expression and not next_run_time:
            # 默认10分钟后执行
            next_run_time = datetime.now() + timedelta(minutes=10)

        # 确定联系人：优先使用调用方传入的 contact，否则自动推断
        if not contact:
            config = get_wechat_config()
            owner_name = config.get("owner_name", "YourName")
            default_contact = config.get("default_contact", "文件传输助手")
            agent_username_env = (
                os.getenv("USERNAME", "").strip()
                or os.getenv("AGENT_USERNAME", "").strip()
            )
            # username may be system name or display name; match both when filtering tasks
            if username == owner_name or username == agent_username_env:
                contact = default_contact
            else:
                contact = username

        dup = _find_duplicate_active_task(
            username, cron_expression, next_run_time, task_description
        )
        if dup:
            logger.info(
                "拒绝重复创建定时任务: user=%s existing_id=%s",
                username,
                dup.task_id,
            )
            cron_human = (
                TaskParser.cron_to_human(dup.cron_expression)
                if dup.cron_expression
                else "一次性任务"
            )
            return {
                "success": True,
                "deduplicated": True,
                "task_id": dup.task_id,
                "task_name": dup.task_name,
                "cron_expression": dup.cron_expression,
                "next_run_time": dup.next_run_time.isoformat()
                if dup.next_run_time
                else None,
                "message": (
                    f"已存在相同条件的定时任务（task_id={dup.task_id}，{cron_human}），"
                    f"本次未重复创建。如需调整请修改或删除原任务后再建。"
                ),
            }

        # 创建任务对象
        task = ScheduledTask(
            username=username,
            contact=contact,
            task_name=task_name,
            task_type=TaskType(task_type),
            task_description=task_description,
            task_prompt=task_description,
            cron_expression=cron_expression,
            next_run_time=next_run_time,
            status=TaskStatus.ACTIVE,
        )

        # 添加到调度器
        scheduler = get_scheduler()
        if scheduler.add_task(task):
            return {
                "success": True,
                "task_id": task.task_id,
                "task_name": task.task_name,
                "cron_expression": task.cron_expression,
                "next_run_time": task.next_run_time.isoformat()
                if task.next_run_time
                else None,
                "message": f"任务创建成功，将在 {TaskParser.cron_to_human(cron_expression)} 执行",
            }
        else:
            return {"success": False, "error": "任务创建失败"}

    except Exception as e:
        logger.error(f"创建定时任务失败: {e}")
        return {"success": False, "error": str(e)}


def update_scheduled_task(
    task_id: str,
    username: str,
    task_description: Optional[str] = None,
    cron_expression: Optional[str] = None,
    task_name: Optional[str] = None,
    next_run_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    更新定时任务

    Args:
        task_id: 任务ID
        username: 用户名
        task_description: 新的任务描述（可选）
        cron_expression: 新的 Cron 表达式（可选）
        task_name: 新的任务名称（可选）
        next_run_time: 新的下次执行时间（可选）

    Returns:
        更新结果
    """
    try:
        scheduler = get_scheduler()

        # 验证任务归属
        db = SchedulerDatabase()
        task = db.get_task(task_id)
        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限操作此任务"}

        # 准备更新数据
        updates = {}
        if task_description:
            updates["task_description"] = task_description
            updates["task_prompt"] = task_description

        if task_name:
            updates["task_name"] = task_name

        if cron_expression:
            # 验证 cron 表达式
            is_valid, error_msg = TaskParser.validate_cron(cron_expression)
            if not is_valid:
                return {"success": False, "error": f"无效的 Cron 表达式: {error_msg}"}
            updates["cron_expression"] = cron_expression
            # 如果更新了 cron，清除 next_run_time（除非同时也指定了）
            if not next_run_time:
                updates["next_run_time"] = None

        if next_run_time:
            updates["next_run_time"] = next_run_time
            # 如果指定了 next_run_time，清除 cron_expression（转为一次性任务）
            if not cron_expression:
                updates["cron_expression"] = None

        if not updates:
            return {"success": False, "error": "没有提供需要更新的内容"}

        # 更新任务
        if scheduler.update_task(task_id, updates):
            return {
                "success": True,
                "message": f"任务 {task_id} 更新成功",
                "updates": {k: str(v) for k, v in updates.items()},
            }
        else:
            return {"success": False, "error": "更新任务失败"}

    except Exception as e:
        logger.error(f"更新任务失败: {e}")
        return {"success": False, "error": str(e)}


def pause_scheduled_task(task_id: str, username: str) -> Dict[str, Any]:
    """
    暂停定时任务

    Args:
        task_id: 任务ID
        username: 用户名（用于验证权限）

    Returns:
        操作结果
    """
    try:
        scheduler = get_scheduler()

        # 验证任务归属
        db = SchedulerDatabase()
        task = db.get_task(task_id)
        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限操作此任务"}

        if scheduler.pause_task(task_id):
            return {"success": True, "message": f"任务 {task_id} 已暂停"}
        else:
            return {"success": False, "error": "暂停任务失败"}

    except Exception as e:
        logger.error(f"暂停任务失败: {e}")
        return {"success": False, "error": str(e)}


def resume_scheduled_task(task_id: str, username: str) -> Dict[str, Any]:
    """
    恢复定时任务

    Args:
        task_id: 任务ID
        username: 用户名（用于验证权限）

    Returns:
        操作结果
    """
    try:
        scheduler = get_scheduler()

        # 验证任务归属
        db = SchedulerDatabase()
        task = db.get_task(task_id)
        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限操作此任务"}

        if scheduler.resume_task(task_id):
            return {"success": True, "message": f"任务 {task_id} 已恢复"}
        else:
            return {"success": False, "error": "恢复任务失败"}

    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        return {"success": False, "error": str(e)}


def delete_scheduled_task(task_id: str, username: str) -> Dict[str, Any]:
    """
    删除定时任务

    Args:
        task_id: 任务ID
        username: 用户名（用于验证权限）

    Returns:
        操作结果
    """
    try:
        scheduler = get_scheduler()

        # 验证任务归属
        db = SchedulerDatabase()
        task = db.get_task(task_id)
        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限操作此任务"}

        if scheduler.remove_task(task_id):
            return {"success": True, "message": f"任务 {task_id} 已删除"}
        else:
            return {"success": False, "error": "删除任务失败"}

    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        return {"success": False, "error": str(e)}


def list_scheduled_tasks(username: str, status: Optional[str] = None) -> Dict[str, Any]:
    """
    列出用户的定时任务

    Args:
        username: 用户名
        status: 任务状态筛选（可选）

    Returns:
        任务列表
    """
    try:
        scheduler = get_scheduler()
        tasks = scheduler.list_tasks(username)

        # 状态筛选
        if status:
            tasks = [t for t in tasks if t["status"] == status]

        # 转换 cron 为人类可读形式
        for task in tasks:
            if task.get("cron_expression"):
                task["cron_human"] = TaskParser.cron_to_human(task["cron_expression"])

        return {"success": True, "total": len(tasks), "tasks": tasks}

    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        return {"success": False, "error": str(e)}


def get_task_details(task_id: str, username: str) -> Dict[str, Any]:
    """
    获取任务详情

    Args:
        task_id: 任务ID
        username: 用户名

    Returns:
        任务详情
    """
    try:
        db = SchedulerDatabase()
        task = db.get_task(task_id)

        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限查看此任务"}

        # 获取执行历史
        from .executor import TaskExecutor

        executor = TaskExecutor()
        executions = executor.get_task_executions(task_id)

        return {
            "success": True,
            "task": {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "task_type": task.task_type,
                "task_description": task.task_description,
                "cron_expression": task.cron_expression,
                "cron_human": TaskParser.cron_to_human(task.cron_expression)
                if task.cron_expression
                else None,
                "status": task.status,
                "next_run_time": task.next_run_time.isoformat()
                if task.next_run_time
                else None,
                "last_run_time": task.last_run_time.isoformat()
                if task.last_run_time
                else None,
                "created_at": task.created_at.isoformat(),
            },
            "executions": executions,
        }

    except Exception as e:
        logger.error(f"获取任务详情失败: {e}")
        return {"success": False, "error": str(e)}


def get_task_execution_history(
    task_id: str, username: str, limit: int = 10
) -> Dict[str, Any]:
    """
    获取任务执行历史

    Args:
        task_id: 任务ID
        username: 用户名
        limit: 返回数量限制

    Returns:
        执行历史列表
    """
    try:
        db = SchedulerDatabase()
        task = db.get_task(task_id)

        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限查看此任务"}

        from .executor import TaskExecutor

        executor = TaskExecutor()
        executions = executor.get_task_executions(task_id, limit)

        return {"success": True, "total": len(executions), "executions": executions}

    except Exception as e:
        logger.error(f"获取执行历史失败: {e}")
        return {"success": False, "error": str(e)}


def list_user_executions(
    username: str,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """
    按用户列出执行历史（跨任务），供桌面端等聚合展示。
    """
    try:
        db = SchedulerDatabase()
        cap = max(1, min(int(limit), 500))
        rows = db.list_executions_for_user(
            username,
            task_id=task_id or None,
            status=status or None,
            from_date=from_date or None,
            to_date=to_date or None,
            limit=cap,
        )
        executions = [
            {
                "execution_id": e.execution_id,
                "task_id": e.task_id,
                "status": e.status,
                "progress": e.progress,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "result_summary": e.result_summary,
                "error_message": e.error_message,
            }
            for e in rows
        ]
        return {"success": True, "total": len(executions), "executions": executions}
    except Exception as e:
        logger.error(f"列出用户执行记录失败: {e}")
        return {"success": False, "error": str(e)}


def delete_user_executions(
    username: str,
    execution_ids: Optional[List[str]] = None,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    删除执行历史。
    - 若 execution_ids 非空：仅删除这些 id（须属于该用户）。
    - 否则：按 task_id / status / 日期 条件删除（规则与 list_executions_for_user 一致；全空则删该用户全部记录）。
    """
    try:
        db = SchedulerDatabase()
        ids = [str(x).strip() for x in (execution_ids or []) if str(x).strip()]
        if ids:
            n = db.delete_executions_for_user(username, execution_ids=ids)
        else:
            n = db.delete_executions_for_user(
                username,
                task_id=task_id or None,
                status=status or None,
                from_date=from_date or None,
                to_date=to_date or None,
            )
        return {"success": True, "deleted": n}
    except Exception as e:
        logger.error(f"删除执行记录失败: {e}")
        return {"success": False, "error": str(e)}


def cancel_stale_execution(execution_id: str, username: str) -> Dict[str, Any]:
    """
    将一条仍标记为 running 的执行记录手动结束（用于服务重启后遗留的僵尸状态）。

    不会终止机器上可能仍在跑的进程，只修正 JSON 中的执行记录。
    """
    try:
        db = SchedulerDatabase()
        ex = db.get_execution(execution_id)
        if not ex:
            return {"success": False, "error": "执行记录不存在"}
        if ex.username != username:
            return {"success": False, "error": "无权限操作此记录"}
        st = str(ex.status or "").lower()
        if st != "running":
            return {"success": False, "error": "仅可停止「运行中」的执行记录"}
        msg = (
            "已在客户端手动标记为已停止（服务或进程可能已中断，"
            "无法从界面真正终止后台任务）"
        )
        db.update_execution(
            execution_id,
            status=ExecutionStatus.FAILED,
            progress=100,
            error_message=msg,
            end_time=datetime.now(),
        )
        return {"success": True, "execution_id": execution_id}
    except Exception as e:
        logger.error(f"手动结束执行记录失败: {e}")
        return {"success": False, "error": str(e)}


def run_task_now(task_id: str, username: str) -> Dict[str, Any]:
    """
    立即执行任务（手动触发）

    Args:
        task_id: 任务ID
        username: 用户名

    Returns:
        执行结果
    """
    try:
        db = SchedulerDatabase()
        task = db.get_task(task_id)

        if not task:
            return {"success": False, "error": "任务不存在"}

        if task.username != username:
            return {"success": False, "error": "无权限操作此任务"}

        # 检查是否有正在运行的执行
        running = db.get_running_execution(task_id)
        if running:
            return {"success": False, "error": "任务正在运行中"}

        # 执行任务
        from .executor import TaskExecutor

        executor = TaskExecutor()
        result = executor.execute(task_id, task.task_prompt, username)

        return result

    except Exception as e:
        logger.error(f"立即执行任务失败: {e}")
        return {"success": False, "error": str(e)}


def get_scheduler_tools() -> List:
    """
    获取所有调度器相关的工具函数，供 DeepAgent 使用

    Returns:
        工具函数列表
    """
    from langchain_core.tools import tool

    @tool
    def create_scheduled_task_tool(
        task_description: str,
        cron_expression: str = None,
        task_type: str = "custom",
        task_name: str = None,
    ) -> Dict[str, Any]:
        """
        创建定时任务。当用户**本次对话中明确提出新的**定时需求时使用。
        请先确认没有同等任务：可先调用 list_scheduled_tasks_tool；**不要**因历史消息里
        已有相同指令就再次创建。同一用户、相同执行计划、相同任务内容时会由服务端去重，
        返回 deduplicated=true，切勿为「复述/确认」类回复反复调用本工具。

        参数:
            - task_description: 任务的自然语言描述，例如"每天早上8点帮我整理新闻"
            - cron_expression: Cron 表达式（可选），例如"0 8 * * *"表示每天8点
            - task_type: 任务类型，可选值: news_report, market_summary, data_analysis, custom
            - task_name: 任务名称（可选）
        """
        username = _resolve_agent_username()
        return create_scheduled_task(
            username, task_description, cron_expression, task_type, task_name
        )

    @tool
    def pause_scheduled_task_tool(task_id: str) -> Dict[str, Any]:
        """暂停一个定时任务"""
        username = _resolve_agent_username()
        return pause_scheduled_task(task_id, username)

    @tool
    def resume_scheduled_task_tool(task_id: str) -> Dict[str, Any]:
        """恢复一个暂停的定时任务"""
        username = _resolve_agent_username()
        return resume_scheduled_task(task_id, username)

    @tool
    def delete_scheduled_task_tool(task_id: str) -> Dict[str, Any]:
        """删除一个定时任务"""
        username = _resolve_agent_username()
        return delete_scheduled_task(task_id, username)

    @tool
    def list_scheduled_tasks_tool(status: str = None) -> Dict[str, Any]:
        """列出用户的所有定时任务"""
        username = _resolve_agent_username()
        return list_scheduled_tasks(username, status)

    @tool
    def get_task_details_tool(task_id: str) -> Dict[str, Any]:
        """获取定时任务的详细信息和执行历史"""
        username = _resolve_agent_username()
        return get_task_details(task_id, username)

    @tool
    def get_task_execution_history_tool(
        task_id: str, limit: int = 10
    ) -> Dict[str, Any]:
        """获取定时任务的执行历史记录"""
        username = _resolve_agent_username()
        return get_task_execution_history(task_id, username, limit)

    @tool
    def run_task_now_tool(task_id: str) -> Dict[str, Any]:
        """立即手动执行一个定时任务"""
        username = _resolve_agent_username()
        return run_task_now(task_id, username)

    return [
        create_scheduled_task_tool,
        pause_scheduled_task_tool,
        resume_scheduled_task_tool,
        delete_scheduled_task_tool,
        list_scheduled_tasks_tool,
        get_task_details_tool,
        get_task_execution_history_tool,
        run_task_now_tool,
    ]
