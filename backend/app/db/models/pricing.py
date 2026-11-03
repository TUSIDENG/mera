"""模型 API 按量价格：一行一模型，与榜单快照分表存储。

粒度为 (model_id, provider)；价格单位由 unit 列表达（默认每 token，USD）。
cache/图片等扩展价放 data JSONB；token 包与订阅套餐存 subscription_plans。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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


class ModelApiPrice(Base):
    __tablename__ = "model_api_prices"
    __table_args__ = (
        UniqueConstraint("model_id", "provider", name="uq_model_api_price"),
        Index("idx_model_api_price_provider", "provider"),
        Index("idx_model_api_price_data", "data", postgresql_using="gin"),
        CheckConstraint(
            "input_price IS NULL OR input_price >= 0",
            name="ck_model_api_price_input_non_negative",
        ),
        CheckConstraint(
            "output_price IS NULL OR output_price >= 0",
            name="ck_model_api_price_output_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # 每 unit（默认 token）单价；允许单边缺失（如仅输出价）
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="token")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="fetch")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
