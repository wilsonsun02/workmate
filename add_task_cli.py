import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workflow.config import OWNER_NAME
from workflow.model import create_llm_instance
from scheduler.tools import (
    create_scheduled_task,
    update_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
)

from loguru import logger


# 定义输出结构
class TaskInfo(BaseModel):
    operation: str = Field(
        description="操作类型：'create' (创建)、'update' (修改) 或 'delete' (删除)"
    )
    task_id: str | None = Field(
        description="任务ID，仅在 operation='update' 或 'delete' 时需要"
    )
    task_name: str | None = Field(description="任务名称，删除操作时用于查找任务")
    task_description: str | None = Field(description="任务详细描述")
    cron_expression: str | None = Field(description="Cron 表达式，如果是周期性任务")
    next_run_time: str | None = Field(
        description="下次执行时间，如果是一次性任务，格式 YYYY-MM-DD HH:MM:SS"
    )
    task_type: str | None = Field(description="任务类型，默认为 custom")


def _load_prompt_from_file(prompt_file: str) -> str:
    """从文件加载 Prompt 模板"""
    prompt_path = Path(__file__).parent / "prompt" / prompt_file
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")


def parse_instruction(instruction: str):
    """使用 LLM 解析指令"""
    logger.info("正在调用大模型解析指令...")

    llm = create_llm_instance(temperature=0)

    # 定义 Prompt - 从文件加载
    parser = JsonOutputParser(pydantic_object=TaskInfo)
    prompt_template = _load_prompt_from_file("TASK_PARSER_PROMPT.md")

    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["user_input", "current_time"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )

    chain = prompt | llm | parser

    try:
        result = chain.invoke(
            {
                "user_input": instruction,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        return result
    except Exception as e:
        logger.info(f"解析失败: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="AI 定时任务添加工具")
    parser.add_argument(
        "instruction",
        help="自然语言指令，例如：'每隔15分钟执行一次，任务如下：获取热门资讯'",
    )
    parser.add_argument("--username", default=OWNER_NAME, help="用户名")
    parser.add_argument("--yes", "-y", action="store_true", help="自动确认")

    args = parser.parse_args()

    # 1. 解析指令
    task_info = parse_instruction(args.instruction)
    if not task_info:
        logger.info("无法解析指令，请重试。")
        return

    logger.info("\n解析结果：")
    logger.info(json.dumps(task_info, indent=2, ensure_ascii=False))

    # 2. 确认
    if not args.yes:
        op_name = {"update": "修改", "delete": "删除"}.get(
            task_info.get("operation"), "添加"
        )
        confirm = input(f"\n确认{op_name}该任务吗？(y/n): ").strip().lower()
        if confirm != "y":
            logger.info("已取消。")
            return

    # 3. 处理时间格式
    next_run_time = None
    if task_info.get("next_run_time"):
        try:
            next_run_time = datetime.strptime(
                task_info["next_run_time"], "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            logger.info(f"时间格式错误: {task_info['next_run_time']}")
            return

    # 4. 执行操作
    if task_info.get("operation") == "delete":
        # 删除任务
        task_id = task_info.get("task_id")
        task_name = task_info.get("task_name")

        if not task_id and not task_name:
            logger.info("错误：删除任务必须提供 task_id 或 task_name")
            return

        # 如果没有提供 task_id，根据 task_name 查找
        if not task_id and task_name:
            logger.info(f"正在根据任务名称 '{task_name}' 查找任务...")
            list_result = list_scheduled_tasks(username=args.username)
            if list_result.get("success"):
                tasks = list_result.get("tasks", [])
                matched_tasks = [
                    t
                    for t in tasks
                    if task_name.lower() in t.get("task_name", "").lower()
                ]
                if not matched_tasks:
                    logger.info(f"错误：未找到名称包含 '{task_name}' 的任务")
                    return
                if len(matched_tasks) > 1:
                    logger.info(f"找到多个匹配的任务，请使用 task_id 指定：")
                    for t in matched_tasks:
                        logger.info(f"  - {t.get('task_id')}: {t.get('task_name')}")
                    return
                task_id = matched_tasks[0].get("task_id")
                logger.info(f"找到任务: {task_id}")

        result = delete_scheduled_task(task_id=task_id, username=args.username)
    elif task_info.get("operation") == "update":
        if not task_info.get("task_id"):
            logger.info("错误：修改任务必须提供 task_id")
            return

        result = update_scheduled_task(
            task_id=task_info["task_id"],
            username=args.username,
            task_description=task_info.get("task_description"),
            cron_expression=task_info.get("cron_expression"),
            task_name=task_info.get("task_name"),
            next_run_time=next_run_time,
        )
    else:
        # 默认为创建任务
        # 确保必填字段存在
        if not task_info.get("task_description"):
            logger.info("错误：创建任务必须提供任务描述")
            return

        result = create_scheduled_task(
            username=args.username,
            task_description=task_info["task_description"],
            cron_expression=task_info.get("cron_expression"),
            task_type=task_info.get("task_type", "custom"),
            task_name=task_info.get("task_name"),
            next_run_time=next_run_time,
        )

    logger.info("\n执行结果：")
    logger.info(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
