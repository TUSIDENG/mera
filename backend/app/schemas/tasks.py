"""M04 采集任务请求/响应模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FetchStrategy = Literal["api", "reverse_api", "playwright"]


class FetchTaskCreate(BaseModel):
    """手动触发采集：task_type/domain 与 M02 业务键一致；strategy 缺省由编排层自动降级。

    task_type 必须在目标站点 config.yaml 声明的 data_types 内（路由层校验）。
    """

    task_type: Literal[
        "model_metrics", "infrastructure_cost", "api_price", "subscription_plan"
    ]
    source_key: str = Field(min_length=1, max_length=80)
    domain: str | None = Field(default=None, max_length=50)
    fetch_strategy: FetchStrategy | None = None


class FetchTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    source_key: str
    domain: str | None
    triggered_by: str
    status: str
    attempt_count: int
    hit_count: int
    auto_start: bool
    fetch_strategy: str | None
    error_message: str | None
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class FetchCallbackIn(BaseModel):
    """RPA 回调（采集实现指南第 5 节契约）：终态分流由 fetch_tasks 状态机负责。"""

    result: Literal[
        "succeeded", "partial_succeeded", "failed_exhausted", "captcha_pending"
    ]
    strategy: FetchStrategy | None = None
    hit_count: int = Field(default=0, ge=0)
    error_message: str | None = None
