"""模型榜单快照：多维评分结构化存储，价格已拆分到 model_api_prices。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base
from app.db.types import JSONBType
from app.db.uuid7 import uuid7


class ModelSnapshot(Base):
    __tablename__ = "model_snapshots"
    __table_args__ = (
        UniqueConstraint("model_id", "domain", name="uq_model_snapshot"),
        Index("idx_model_snapshot_domain", "domain", "benchmark_score"),
        Index("idx_model_snapshot_provider", "provider", "domain"),
        Index("idx_model_snapshot_data", "data", postgresql_using="gin"),
        CheckConstraint("benchmark_score >= 0", name="ck_model_snapshot_score_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    # 主榜分：多维度按回落顺序取出的代表分；全部维度缺失时为 None（区别于真 0 分）
    benchmark_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 各维度原始分（如 {"intelligence": 51, "coding": 70.1, "agentic": null}）
    scores: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    # 主榜分来源维度（score/intelligence/coding/agentic），缺失为 None
    score_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
