"""用户选型评估历史。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import EvaluationStatus
from app.db.models.base import Base
from app.db.types import JSONBType, UUIDArrayType
from app.db.uuid7 import uuid7


class UserEvaluation(Base):
    __tablename__ = "user_evaluations"
    __table_args__ = (
        Index("idx_user_eval_org", "org_id", "created_at"),
        Index("idx_user_eval_user", "user_id", "created_at"),
        Index("idx_user_eval_fetch_task", "fetch_task_id"),
        Index("idx_user_eval_data", "data", postgresql_using="gin"),
        CheckConstraint(
            f"status IN ({', '.join(repr(v.value) for v in EvaluationStatus)})",
            name="ck_user_eval_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=EvaluationStatus.COMPLETED.value
    )
    fetch_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("fetch_tasks.id", name="fk_eval_fetch_task"),
        nullable=True,
    )
    snapshot_used_ids: Mapped[list[uuid.UUID]] = mapped_column(
        UUIDArrayType, nullable=False, default=list
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
