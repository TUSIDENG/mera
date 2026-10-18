"""M04 用户评测请求/响应模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=50)
    snapshot_used_ids: list[uuid.UUID] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    fetch_task_id: uuid.UUID | None = None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: str
    user_id: str
    domain: str
    status: str
    fetch_task_id: uuid.UUID | None
    snapshot_used_ids: list[uuid.UUID]
    data: dict[str, Any]
    created_at: datetime
