"""M04 模型榜单快照响应模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_id: str
    provider: str
    domain: str
    benchmark_score: Decimal | None
    scores: dict[str, Any]
    score_source: str | None
    data: dict[str, Any]
    updated_at: datetime


class FetchRecordOut(BaseModel):
    """采集留痕行：哪次任务、从哪个平台、采了什么（标准化后的完整记录）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    source_key: str
    model_id: str
    raw_model_id: str | None
    domain: str
    record: dict[str, Any]
    created_at: datetime
