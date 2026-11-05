"""采集记录留痕：每次采集任务的每条标准化记录一行（append-only，仅 model_metrics）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base
from app.db.types import JSONBType
from app.db.uuid7 import uuid7


class FetchRecord(Base):
    __tablename__ = "fetch_records"
    __table_args__ = (
        Index("idx_fetch_record_task", "task_id"),
        Index("idx_fetch_record_model", "model_id", "created_at"),
        Index("idx_fetch_record_source", "source_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("fetch_tasks.id", ondelete="CASCADE", name="fk_fetch_record_task"),
        nullable=False,
    )
    # 来自哪个平台（站点 key）
    source_key: Mapped[str] = mapped_column(String(50), nullable=False)
    # 归并后的规范模型 id
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 平台上的原始模型名（含 vendor 前缀/变体后缀）
    raw_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    # 该条标准化后的完整记录（含 scores/data 等）
    record: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
