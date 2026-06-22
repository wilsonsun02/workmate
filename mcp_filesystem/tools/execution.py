"""Execution tools.

This module contains tools for executing scripts and commands.
"""

import os
import time
import subprocess
import shlex
import anyio
import json
import re
import uuid
from datetime import datetime
from typing import Dict, Optional

from fastmcp import Context
from fastmcp.utilities.logging import get_logger

from ..context import mcp, get_components

logger = get_logger(__name__)

# Control whether Execution tools are exposed
ENABLE_EXECUTION_TOOLS = (
    os.environ.get("MCP_ENABLE_EXECUTION_TOOLS", "true").lower() == "true"
)


class TaskParser:
    """任务解析器，用于将自然语言时间描述解析为 cron 表达式"""

    # 时间模式映射
    TIME_PATTERNS = {
        # 每天
        r"每天": ("0 8 * * *", "每天"),
        r"每天早上(\d+)点": (None, "每天早上"),
        r"每天下午(\d+)点": (None, "每天下午"),
        r"每天中午(\d+)点": (None, "每天中午"),
        r"每天凌晨(\d+)点": (None, "每天凌晨"),
        # 每周
        r"每周一": ("0 9 * * 1", "每周一"),
        r"每周二": ("0 9 * * 2", "每周二"),
        r"每周三": ("0 9 * * 3", "每周三"),
        r"每周四": ("0 9 * * 4", "每周四"),
        r"每周五": ("0 9 * * 5", "每周五"),
        r"每周六": ("0 9 * * 6", "每周六"),
        r"每周日": ("0 9 * * 0", "每周日"),
        # 每月
        r"每月(\d+)号": (None, "每月几号"),
        r"每月初": ("0 9 1 * *", "每月1号"),
        r"每月末": ("0 9 28 * *", "每月28号"),
        # 间隔
        r"每隔(\d+)分钟": (None, "间隔分钟"),
        r"每隔(\d+)小时": (None, "间隔小时"),
        # 每小时
        r"每小时": ("0 * * * *", "每小时"),
        # 具体时间
        r"早上(\d+)点": (None, "早上几点"),
        r"下午(\d+)点": (None, "下午几点"),
        r"中午(\d+)点": (None, "中午几点"),
        r"凌晨(\d+)点": (None, "凌晨几点"),
        r"(\d+):(\d+)": (None, "具体时间"),
    }

    @classmethod
    def parse_time(cls, user_input: str) -> Optional[str]:
        """解析时间描述为 cron 表达式"""
        # 处理 "每天早上8点" 类型的模式
        daily_morning = re.search(r"每天早上([一二三四五六七八九十\d]+)点", user_input)
        if daily_morning:
            hour_str = daily_morning.group(1)
            num_map = {
                "一": 1,
                "二": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
            }
            hour = num_map.get(hour_str)
            if hour is None:
                try:
                    hour = int(hour_str)
                except ValueError:
                    hour = 8
            return f"0 {hour} * * *"

        daily_afternoon = re.search(
            r"每天下午([一二三四五六七八九十\d]+)点", user_input
        )
        if daily_afternoon:
            hour_str = daily_afternoon.group(1)
            num_map = {
                "一": 1,
                "二": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
            }
            hour = num_map.get(hour_str)
            if hour is None:
                try:
                    hour = int(hour_str)
                except ValueError:
                    hour = 4
            hour += 12
            return f"0 {hour} * * *"

        daily_noon = re.search(r"每天中午(\d+)点", user_input)
        if daily_noon:
            hour = int(daily_noon.group(1))
            return f"0 {hour} * * *"

        daily_dawn = re.search(r"每天凌晨(\d+)点", user_input)
        if daily_dawn:
            hour = int(daily_dawn.group(1))
            return f"0 {hour} * * *"

        # 处理 "每周X早上Y点"
        weekly_match = re.search(r"每周([一二三四五六日])早上(\d+)点", user_input)
        if weekly_match:
            day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0}
            day = day_map.get(weekly_match.group(1), 0)
            hour = int(weekly_match.group(2))
            return f"0 {hour} * * {day}"

        # 处理 "每月X号"
        monthly_match = re.search(r"每月(\d+)号", user_input)
        if monthly_match:
            day = int(monthly_match.group(1))
            return f"0 9 {day} * *"

        # 处理 "每隔X分钟/小时"
        interval_minute = re.search(r"每隔(\d+)分钟", user_input)
        if interval_minute:
            minute = int(interval_minute.group(1))
            return f"*/{minute} * * * *"

        interval_hour = re.search(r"每隔(\d+)小时", user_input)
        if interval_hour:
            hour = int(interval_hour.group(1))
            return f"0 */{hour} * * *"

        # 处理具体时间 "HH:MM"
        time_match = re.search(r"(\d{1,2}):(\d{2})", user_input)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            return f"{minute} {hour} * * *"

        # 处理 "早上/下午/中午 X点"
        morning_match = re.search(r"早上(\d+)点", user_input)
        if morning_match:
            hour = int(morning_match.group(1))
            return f"0 {hour} * * *"

        afternoon_match = re.search(r"下午([一二三四五六七八九十\d]+)点", user_input)
        if afternoon_match:
            hour_str = afternoon_match.group(1)
            num_map = {
                "一": 1,
                "二": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
            }
            hour = num_map.get(hour_str)
            if hour is None:
                try:
                    hour = int(hour_str)
                except ValueError:
                    hour = 4  # 默认
            hour += 12
            return f"0 {hour} * * *"

        # 处理预定义模式
        for pattern, (cron, _) in cls.TIME_PATTERNS.items():
            if cron and re.search(pattern, user_input):
                return cron

        return None

    @classmethod
    def generate_task_name(cls, user_input: str) -> str:
        """生成任务名称"""
        if "新闻" in user_input or "资讯" in user_input:
            return "新闻报告"
        elif "市场" in user_input or "行情" in user_input or "报价" in user_input:
            return "市场总结"
        elif "分析" in user_input or "数据" in user_input:
            return "数据分析"
        return "定时任务"


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_EXECUTION_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def schedule_task(
    contact_name: str, schedule_task_desc: str, task_type: str, ctx: Context
) -> str:
    """设定定时任务工具。

    Args:
        contact_name: 微信联系人，即设定定时任务的联系人，也是接收agent运行定时任务结果的联系人
        schedule_task_desc: 任务内容，示例：设定一个定时任务，每天下午四点，获取各类型网站的热门资讯（调用hot-news-briefs技能），并形成一份汇总摘要
        task_type: 任务类型，是新增还是修改。可以新建一个定时任务，也可以修改该定时任务。可选值：'新增', '修改'
        ctx: MCP context

    Returns:
        执行结果信息
    """
    try:
        # 配置文件路径
        from workflow.config import BASE_DIR

        config_path = os.path.join(BASE_DIR, "config", "scheduled_tasks.json")
        config_dir = os.path.dirname(config_path)

        # 确保目录存在
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        # 读取现有任务
        tasks = []
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        tasks = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"[schedule_task] 无法解析 {config_path}，将创建新文件")
                tasks = []

        # 解析时间
        cron_expression = TaskParser.parse_time(schedule_task_desc)
        if not cron_expression:
            # 默认每天早上8点
            cron_expression = "0 8 * * *"
            logger.info(
                f"[schedule_task] 未能从描述中解析出时间，使用默认时间: {cron_expression}"
            )

        task_name = TaskParser.generate_task_name(schedule_task_desc)
        current_time = datetime.now().isoformat()

        if task_type == "新增":
            # 创建新任务
            new_task = {
                "contact": contact_name,
                "created_at": current_time,
                "cron_expression": cron_expression,
                "last_run_time": None,
                "next_run_time": None,  # 实际应用中可能需要计算
                "status": "active",
                "task_description": schedule_task_desc,
                "task_id": f"task_{uuid.uuid4().hex[:12]}",
                "task_name": task_name,
                "task_prompt": schedule_task_desc,
                "task_type": "custom",
                "updated_at": current_time,
                "username": contact_name,  # 假设 username 和 contact_name 相同
            }
            tasks.append(new_task)
            result_msg = f"成功新增定时任务: {task_name} (ID: {new_task['task_id']})，执行时间: {cron_expression}"

        elif task_type == "修改":
            # 查找匹配的任务
            # 简单的匹配逻辑：查找同一个联系人的任务，如果只有一个则直接修改，如果有多个则尝试匹配描述
            user_tasks = [t for t in tasks if t.get("contact") == contact_name]

            if not user_tasks:
                return f"未找到联系人 {contact_name} 的定时任务，无法修改。"

            target_task = None
            if len(user_tasks) == 1:
                target_task = user_tasks[0]
            else:
                # 尝试通过关键词匹配
                for t in user_tasks:
                    # 简单的关键词匹配，实际应用中可能需要更复杂的 NLP 匹配
                    if t.get("task_name") in schedule_task_desc or any(
                        word in schedule_task_desc
                        for word in t.get("task_description", "").split("，")
                    ):
                        target_task = t
                        break

                # 如果还是没找到，默认修改第一个
                if not target_task:
                    target_task = user_tasks[0]
                    logger.info(
                        f"[schedule_task] 未能精确匹配任务，默认修改第一个任务: {target_task['task_id']}"
                    )

            # 更新任务
            target_task["cron_expression"] = cron_expression
            target_task["task_description"] = schedule_task_desc
            target_task["task_prompt"] = schedule_task_desc
            target_task["task_name"] = task_name
            target_task["updated_at"] = current_time

            result_msg = f"成功修改定时任务: {task_name} (ID: {target_task['task_id']})，新的执行时间: {cron_expression}"

        else:
            return f"不支持的任务类型: {task_type}，请使用 '新增' 或 '修改'"

        # 保存回文件
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

        logger.info(f"[schedule_task] {result_msg}")
        return result_msg

    except Exception as e:
        error_msg = f"设定定时任务失败: {str(e)}"
        logger.error(f"[schedule_task] {error_msg}")
        return error_msg


@register_tool()
async def execute_script(
    command: str,
    ctx: Context,
    cwd: Optional[str] = None,
    timeout: Optional[int] = 300,
    shell: bool = True,
    environment: Optional[Dict[str, str]] = None,
    stream_output: bool = True,
) -> str:
    """Execute a local script file or command.

    Args:
        command: The command or script path to execute. Can be:
            - Full command with interpreter: "python D:/path/to/script.py"
            - Just script path: "D:/path/to/script.py" (requires interpreter in PATH)
            - Relative or absolute script path
        ctx: MCP context
        cwd: Working directory for execution (defaults to script's directory)
        timeout: Maximum execution time in seconds (default: 300)
        shell: Whether to run command through shell (default: True)
        environment: Optional environment variables to set
        stream_output: Whether to stream output in real-time (default: True)

    Returns:
        Execution result with status, stdout, and stderr
    """
    try:
        components = get_components()
        validator = components["validator"]

        script_path = None
        interpreter_cmd = None

        logger.info(f"[execute_script] 开始执行命令: {command}")

        if os.path.isabs(command):
            if os.path.isfile(command):
                script_path = command
        else:
            resolved_path = os.path.abspath(command)
            if os.path.isfile(resolved_path):
                script_path = resolved_path

        if script_path:
            script_path, is_allowed = await validator.validate_path(script_path)
            if not is_allowed:
                error_msg = f"Error: Script path is not within allowed directories: {script_path}"
                logger.error(f"[execute_script] {error_msg}")
                return error_msg

            script_dir = os.path.dirname(script_path)
            script_ext = os.path.splitext(script_path)[1].lower()

            if script_ext == ".py":
                interpreter_cmd = "python"
            elif script_ext == ".bat":
                interpreter_cmd = "cmd"
            elif script_ext == ".ps1":
                interpreter_cmd = "powershell"
            elif script_ext == ".sh":
                interpreter_cmd = "bash"

            if interpreter_cmd:
                cmd_list = [interpreter_cmd, str(script_path)]
            else:
                cmd_list = [str(script_path)] if shell else str(script_path).split()
        else:
            cmd_list = command if shell else command.split()

        exec_cwd = cwd
        if exec_cwd is None and script_path:
            exec_cwd = os.path.dirname(script_path)

        env = os.environ.copy()
        if environment:
            env.update(environment)

        logger.info(f"[execute_script] 准备执行命令: {cmd_list}")
        logger.info(f"[execute_script] 工作目录: {exec_cwd}")
        logger.info(f"[execute_script] 超时设置: {timeout}秒")

        start_time = time.time()

        if shell:
            command_string = (
                subprocess.list2cmdline(cmd_list)
                if isinstance(cmd_list, list)
                else cmd_list
            )
            if os.name == "nt":  # For Windows
                executable_command = ["cmd", "/c", command_string]
            else:  # For POSIX-like systems
                executable_command = ["/bin/sh", "-c", command_string]
        else:
            if isinstance(cmd_list, str):
                executable_command = shlex.split(cmd_list)
            else:
                executable_command = cmd_list

        stdout_list = []
        stderr_list = []
        returncode = -1
        process = None

        try:
            with anyio.move_on_after(timeout) as scope:
                process = await anyio.open_process(
                    executable_command,
                    cwd=exec_cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                async with process:

                    async def read_stream(stream, target_list, log_prefix):
                        async for line_bytes in stream:
                            line = line_bytes.decode("gbk", errors="replace").rstrip(
                                "\r"
                            )
                            target_list.append(line + "\n")
                            if stream_output:
                                logger.info(f"{log_prefix} {line}")

                    async with anyio.create_task_group() as tg:
                        tg.start_soon(
                            read_stream,
                            process.stdout,
                            stdout_list,
                            "[execute_script STDOUT]",
                        )
                        tg.start_soon(
                            read_stream,
                            process.stderr,
                            stderr_list,
                            "[execute_script STDERR]",
                        )

                returncode = process.returncode

            if scope.cancelled_caught:
                status = "TIMEOUT"
                stderr_list.append(
                    f"\nError: Process timed out after {timeout} seconds."
                )
            else:
                status = "SUCCESS" if returncode == 0 else "FAILED"

        except FileNotFoundError as e:
            error_msg = f"Error: Command not found: {str(e)}"
            logger.error(f"[execute_script] {error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"Error starting or running script: {str(e)}"
            logger.error(f"[execute_script] {error_msg}")
            return error_msg
        finally:
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await process.aclose()
                except Exception:
                    pass  # Ignore errors on cleanup

        elapsed_time = time.time() - start_time

        logger.info(
            f"[execute_script] 执行完成 - 状态: {status}, 退出码: {returncode}, 耗时: {elapsed_time:.2f}秒"
        )

        stdout = "".join(stdout_list)
        stderr = "".join(stderr_list)

        output_parts = [
            f"Status: {status}",
            f"Exit Code: {returncode}",
            f"Elapsed Time: {elapsed_time:.2f} seconds",
        ]

        if stdout:
            output_parts.append(f"\n--- STDOUT ---\n{stdout}")

        if stderr:
            output_parts.append(f"\n--- STDERR ---\n{stderr}")

        return "\n".join(output_parts)

    except Exception as e:
        error_msg = f"Error executing script: {str(e)}"
        logger.error(f"[execute_script] {error_msg}")
        return error_msg
