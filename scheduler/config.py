"""
调度器配置文件
包含调度器的各种配置选项
"""

import os

# 调度器基础配置
SCHEDULER_TIMEZONE = "Asia/Shanghai"  # 时区
SCHEDULER_MAX_INSTANCES = 3  # 同一任务最大并发实例数
SCHEDULER_COALESCE = True  # 合并错过执行的任务
SCHEDULER_MISFIRE_GRACE_TIME = 300  # 任务错过的宽限期(秒)

# 任务执行配置
TASK_EXECUTION_TIMEOUT = 600  # API调用超时时间(秒)，定时任务应在10分钟内完成
TASK_EXECUTION_SUBPROCESS_TIMEOUT = 3600  # 子进程执行超时时间(秒)
TASK_RETRY_COUNT = 3  # 任务失败重试次数
TASK_RETRY_DELAY = 60  # 重试延迟(秒)

# 执行记录过期配置
STALE_EXECUTION_MAX_AGE = (
    300  # 超过此时间(秒)的running状态执行记录视为过期，允许重新调度
)
STALE_EXECUTION_CLEANUP_ON_STARTUP = True  # 启动时是否自动清理过期记录

# 数据库配置 (已废弃，改为使用 JSON 文件)
# SCHEDULER_DB_HOST = os.getenv("REPORT_DB_HOST", "localhost")
# SCHEDULER_DB_PORT = int(os.getenv("REPORT_DB_PORT", "3306"))
# SCHEDULER_DB_DATABASE = os.getenv("REPORT_DB_DATABASE", "analysis_report")
# SCHEDULER_DB_USER = os.getenv("REPORT_DB_USER", "report")
# SCHEDULER_DB_PASS = os.getenv("REPORT_DB_PASS", "")

# 主程序路径配置
MAIN_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")

# 反馈配置
NOTIFICATION_ENABLED = True  # 是否启用通知
NOTIFICATION_CHANNELS = ["wechat"]  # 通知渠道：仅微信

# 日志配置
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
