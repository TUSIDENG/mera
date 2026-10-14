"""模型订阅套餐。"""

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

from app.db.enums import BillingCycle, SubscriptionSource
from app.db.models.base import Base
from app.db.types import JSONBType
from app.db.uuid7 import uuid7


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        UniqueConstraint("provider", "plan_key", "billing_cycle", name="uq_subscription_plan"),
        Index("idx_subscription_active", "is_active", "provider"),
        Index("idx_subscription_data", "data", postgresql_using="gin"),
        CheckConstraint("monthly_price >= 0", name="ck_subscription_price_non_negative"),
        CheckConstraint(
            f"billing_cycle IN ({', '.join(repr(v.value) for v in BillingCycle)})",
            name="ck_subscription_billing_cycle",
        ),
        CheckConstraint(
            f"source IN ({', '.join(repr(v.value) for v in SubscriptionSource)})",
            name="ck_subscription_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(150), nullable=False)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
