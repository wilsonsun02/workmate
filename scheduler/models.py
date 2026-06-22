"""
定时任务数据模型定义
使用 Pydantic 进行数据验证和序列化
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    """任务状态枚举"""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    """任务类型枚举"""

    NEWS_REPORT = "news_report"  # 新闻报告
    MARKET_SUMMARY = "market_summary"  # 市场总结
    DATA_ANALYSIS = "data_analysis"  # 数据分析
    CUSTOM = "custom"  # 自定义任务


class ExecutionStatus(str, Enum):
    """任务执行状态枚举"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScheduledTask(BaseModel):
    """定时任务模型"""

    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    username: str
    contact: str
    task_name: Optional[str] = None
    task_type: TaskType = TaskType.CUSTOM
    task_description: Optional[str] = None
    task_prompt: str
    cron_expression: Optional[str] = None
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    status: TaskStatus = TaskStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        use_enum_values = True


class TaskExecution(BaseModel):
    """任务执行记录模型"""

    execution_id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:12]}")
    task_id: str
    username: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    progress: int = Field(default=0, ge=0, le=100)
    result_summary: Optional[str] = None
    result_detail: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        use_enum_values = True


class CreateTaskRequest(BaseModel):
    """创建任务请求模型"""

    username: str
    contact: str
    task_description: str
    cron_expression: Optional[str] = None
    task_type: Optional[TaskType] = TaskType.CUSTOM
    task_name: Optional[str] = None


class TaskResponse(BaseModel):
    """任务响应模型"""

    task_id: str
    task_name: Optional[str]
    task_type: str
    status: str
    next_run_time: Optional[str]
    cron_expression: Optional[str]
    created_at: str


class ExecutionResponse(BaseModel):
    """执行记录响应模型"""

    execution_id: str
    task_id: str
    status: str
    start_time: str
    end_time: Optional[str]
    progress: int
    result_summary: Optional[str]
    error_message: Optional[str]


class TaskListResponse(BaseModel):
    """任务列表响应模型"""

    total: int
    tasks: List[TaskResponse]


class ExecutionListResponse(BaseModel):
    """执行记录列表响应模型"""

    total: int
    executions: List[ExecutionResponse]
