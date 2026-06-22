"""
任务解析器模块
将自然语言描述的定时任务解析为结构化数据
"""

import re
from typing import Optional, Dict, Any, Tuple

from .models import TaskType

from loguru import logger


class TaskParser:
    """任务解析器"""

    # 时间模式映射
    TIME_PATTERNS = {
        # 每天
        r"每天": ("0 8 * * *", "每天"),
        r"每天早上(\d+)点": (None, "每天早上"),  # 动态处理
        r"每天下午(\d+)点": (None, "每天下午"),  # 动态处理
        r"每天中午(\d+)点": (None, "每天中午"),  # 动态处理
        r"每天凌晨(\d+)点": (None, "每天凌晨"),  # 动态处理
        # 每周
        r"每周一": ("0 9 * * 1", "每周一"),
        r"每周二": ("0 9 * * 2", "每周二"),
        r"每周三": ("0 9 * * 3", "每周三"),
        r"每周四": ("0 9 * * 4", "每周四"),
        r"每周五": ("0 9 * * 5", "每周五"),
        r"每周六": ("0 9 * * 6", "每周六"),
        r"每周日": ("0 9 * * 0", "每周日"),
        r"每周(.*?)早上": (None, "每周早上"),  # 动态处理
        # 每月
        r"每月(\d+)号": (None, "每月几号"),  # 动态处理
        r"每月初": ("0 9 1 * *", "每月1号"),
        r"每月末": ("0 9 28 * *", "每月28号"),
        # 间隔
        r"每隔(\d+)分钟": (None, "间隔分钟"),  # 动态处理
        r"每隔(\d+)小时": (None, "间隔小时"),  # 动态处理
        # 每小时
        r"每小时": ("0 * * * *", "每小时"),
        # 具体时间
        r"早上(\d+)点": (None, "早上几点"),
        r"下午(\d+)点": (None, "下午几点"),
        r"中午(\d+)点": (None, "中午几点"),
        r"凌晨(\d+)点": (None, "凌晨几点"),
        r"(\d+):(\d+)": (None, "具体时间"),  # HH:MM 格式
    }

    # 任务类型关键词映射
    TASK_TYPE_KEYWORDS = {
        TaskType.NEWS_REPORT: ["新闻", "热点", "晨报", "资讯", "报道"],
        TaskType.MARKET_SUMMARY: ["市场", "行情", "隔夜", "收盘", "复盘", "交易日"],
        TaskType.DATA_ANALYSIS: ["分析", "统计", "数据", "报表"],
    }

    @classmethod
    def parse(cls, user_input: str) -> Dict[str, Any]:
        """
        解析用户输入的自然语言任务描述

        Args:
            user_input: 用户输入的自然语言描述

        Returns:
            包含解析结果的字典:
            - cron_expression: Cron 表达式
            - task_type: 任务类型
            - task_prompt: 解析后的任务 Prompt
            - task_name: 生成的任务名称
        """
        result = {
            "cron_expression": "0 8 * * *",  # 默认每天早上8点
            "task_type": TaskType.CUSTOM,
            "task_prompt": user_input,
            "task_name": None,
        }

        # 解析时间
        cron_expr = cls._parse_time(user_input)
        if cron_expr:
            result["cron_expression"] = cron_expr

        # 解析任务类型
        task_type = cls._parse_task_type(user_input)
        if task_type:
            result["task_type"] = task_type

        # 生成任务名称
        result["task_name"] = cls._generate_task_name(user_input, result["task_type"])

        logger.info(f"解析任务: {user_input} -> {result}")
        return result

    @classmethod
    def _parse_time(cls, user_input: str) -> Optional[str]:
        """解析时间描述"""
        # 处理 "每天早上8点" 类型的模式
        daily_morning = re.search(r"每天早上(\d+)点", user_input)
        if daily_morning:
            hour = int(daily_morning.group(1))
            return f"0 {hour} * * *"

        daily_afternoon = re.search(r"每天下午(\d+)点", user_input)
        if daily_afternoon:
            hour = int(daily_afternoon.group(1)) + 12
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

        afternoon_match = re.search(r"下午(\d+)点", user_input)
        if afternoon_match:
            hour = int(afternoon_match.group(1)) + 12
            return f"0 {hour} * * *"

        # 处理预定义模式
        for pattern, (cron, _) in cls.TIME_PATTERNS.items():
            if cron and re.search(pattern, user_input):
                return cron

        return None

    @classmethod
    def _parse_task_type(cls, user_input: str) -> Optional[TaskType]:
        """解析任务类型"""
        for task_type, keywords in cls.TASK_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in user_input:
                    return task_type
        return None

    @classmethod
    def _generate_task_name(cls, user_input: str, task_type: TaskType) -> str:
        """生成任务名称"""
        # 根据任务类型生成默认名称
        type_names = {
            TaskType.NEWS_REPORT: "新闻报告",
            TaskType.MARKET_SUMMARY: "市场总结",
            TaskType.DATA_ANALYSIS: "数据分析",
            TaskType.CUSTOM: "定时任务",
        }

        base_name = type_names.get(task_type, "定时任务")

        # 尝试从输入中提取时间信息
        time_match = re.search(
            r"每天|每周|每月|早上|下午|中午|凌晨|(\d+):(\d+)", user_input
        )
        if time_match:
            time_info = time_match.group(0)
            return f"{time_info}{base_name}"

        return f"{base_name}"

    @classmethod
    def validate_cron(cls, cron_expression: str) -> Tuple[bool, str]:
        """
        验证 Cron 表达式

        Returns:
            (是否有效, 错误信息)
        """
        parts = cron_expression.split()
        if len(parts) != 5:
            return False, "Cron 表达式必须包含5个字段"

        # 简单验证（实际可以使用 croniter 库进行更严格验证）
        try:
            # 验证分钟 (0-59)
            if parts[0] != "*" and not re.match(
                r"^(\d+|(\d+,)+\d+|(\d+-\d+)|\*/\d+)$", parts[0]
            ):
                return False, "分钟字段无效"
            # 验证小时 (0-23)
            if parts[1] != "*" and not re.match(
                r"^(\d+|(\d+,)+\d+|(\d+-\d+)|\*/\d+)$", parts[1]
            ):
                return False, "小时字段无效"
            # 验证日期 (1-31)
            if parts[2] != "*" and not re.match(
                r"^(\d+|(\d+,)+\d+|(\d+-\d+)|\*/\d+)$", parts[2]
            ):
                return False, "日期字段无效"
            # 验证月份 (1-12)
            if parts[3] != "*" and not re.match(
                r"^(\d+|(\d+,)+\d+|(\d+-\d+)|\*/\d+)$", parts[3]
            ):
                return False, "月份字段无效"
            # 验证星期 (0-6)
            if parts[4] != "*" and not re.match(
                r"^(\d+|(\d+,)+\d+|(\d+-\d+)|\*/\d+)$", parts[4]
            ):
                return False, "星期字段无效"

            return True, ""
        except Exception as e:
            return False, f"Cron 表达式验证失败: {str(e)}"

    @classmethod
    def cron_to_human(cls, cron_expression: str) -> str:
        """将 Cron 表达式转换为人类可读的形式"""
        parts = cron_expression.split()
        if len(parts) != 5:
            return "未知"

        minute, hour, day, month, weekday = parts

        # 每天
        if day == "*" and month == "*" and weekday == "*":
            if minute.startswith("*/"):
                interval = minute[2:]
                return f"每隔 {interval} 分钟"
            elif hour.startswith("*/"):
                interval = hour[2:]
                return f"每隔 {interval} 小时"
            elif hour != "*" and minute != "*":
                return f"每天 {hour}:{minute.zfill(2)}"

        # 每周
        if day == "*" and month == "*" and weekday != "*":
            day_names = {
                "0": "周日",
                "1": "周一",
                "2": "周二",
                "3": "周三",
                "4": "周四",
                "5": "周五",
                "6": "周六",
            }
            if weekday in day_names:
                return f"每周 {day_names[weekday]} {hour}:{minute.zfill(2)}"

        # 每月
        if day != "*" and month == "*" and weekday == "*":
            return f"每月 {day} 号 {hour}:{minute.zfill(2)}"

        return cron_expression
