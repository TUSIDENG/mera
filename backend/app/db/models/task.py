"""按需数据获取任务。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import FetchTaskStatus
from app.db.models.base import Base
from app.db.types import JSONBType
from app.db.uuid7 import uuid7


class FetchTask(Base):
    __tablename__ = "fetch_tasks"
    __table_args__ = (
        Index("idx_fetch_task_user", "triggered_by", "created_at"),
        Index("idx_fetch_task_type", "task_type", "source_key", "domain", "created_at"),
        Index("idx_fetch_task_data", "data", postgresql_using="gin"),
        CheckConstraint("attempt_count >= 0", name="ck_fetch_attempt_count_non_negative"),
        CheckConstraint("hit_count >= 0", name="ck_fetch_hit_count_non_negative"),
        CheckConstraint(
            f"status IN ({', '.join(repr(v.value) for v in FetchTaskStatus)})",
            name="ck_fetch_status",
        ),
        CheckConstraint(
            "status <> 'failed_exhausted' OR hit_count = 0",
            name="ck_fetch_terminal_hit_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=FetchTaskStatus.PENDING.value
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fetch_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
