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
